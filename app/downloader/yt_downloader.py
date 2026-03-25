"""
downloader/yt_downloader.py
============================
Core download engine — the ONLY module that imports yt-dlp.
All business logic for fetching video info and downloading lives here.
Updating yt-dlp behaviour requires changes only in this file.
"""

from __future__ import annotations

import os
import threading
import time
import logging
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Optional

import yt_dlp

from app.downloader.format_parser import (
    VideoInfo, parse_info, build_format_selector
)
from app.utils.settings import settings

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
#  Download state                                                      #
# ------------------------------------------------------------------ #

class DownloadStatus(Enum):
    QUEUED    = auto()
    FETCHING  = auto()   # fetching info
    RUNNING   = auto()
    PAUSED    = auto()
    COMPLETED = auto()
    CANCELLED = auto()
    ERROR     = auto()
    SKIPPED   = auto()   # failed after retries — skipped


@dataclass
class DownloadProgress:
    """Snapshot of a download's current progress — passed to callbacks."""
    task_id: str
    status: DownloadStatus
    filename: str = ""
    percent: float = 0.0
    speed: str = ""
    eta: str = ""
    downloaded_bytes: int = 0
    total_bytes: int = 0
    message: str = ""

    @property
    def total_bytes_human(self) -> str:
        return _human_bytes(self.total_bytes)

    @property
    def downloaded_bytes_human(self) -> str:
        return _human_bytes(self.downloaded_bytes)


@dataclass
class DownloadTask:
    """Represents one queued or active download job."""
    task_id: str
    url: str
    output_format: str          # mp4 / webm / mp3 / m4a …
    resolution: str             # best / 1080p / 720p …
    output_dir: str
    video_info: Optional[VideoInfo] = None
    status: DownloadStatus = DownloadStatus.QUEUED
    error: str = ""
    retry_count: int = 0
    _cancel_event: threading.Event = field(default_factory=threading.Event)
    _pause_event: threading.Event = field(default_factory=threading.Event)

    def __post_init__(self):
        self._pause_event.set()  # not paused by default

    def cancel(self):
        self._cancel_event.set()
        self._pause_event.set()  # unblock pause so thread can exit

    def pause(self):
        self._pause_event.clear()

    def resume(self):
        self._pause_event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()


# ------------------------------------------------------------------ #
#  Downloader                                                          #
# ------------------------------------------------------------------ #

ProgressCallback = Callable[[DownloadProgress], None]
InfoCallback     = Callable[[VideoInfo], None]
ErrorCallback    = Callable[[str, str], None]   # (task_id, message)


class YTDownloader:
    """
    Manages a queue of DownloadTask objects, running each in its own thread.

    Usage:
        dl = YTDownloader(on_progress=my_cb)
        task = dl.enqueue("https://youtube.com/...", "mp4", "1080p", "/tmp")
        # later:
        dl.cancel(task.task_id)
    """

    def __init__(
        self,
        on_progress: Optional[ProgressCallback] = None,
        on_info:     Optional[InfoCallback]     = None,
        on_error:    Optional[ErrorCallback]    = None,
        on_complete: Optional[ProgressCallback] = None,
    ):
        self._on_progress = on_progress
        self._on_info     = on_info
        self._on_error    = on_error
        self._on_complete = on_complete

        self._tasks: dict[str, DownloadTask] = {}
        self._lock = threading.Lock()
        self._task_counter = 0

    # ---------------------------------------------------------------- #
    #  Public API                                                        #
    # ---------------------------------------------------------------- #

    def fetch_info(self, url: str, callback: InfoCallback, error_cb: ErrorCallback,
                   progress_cb: Optional[Callable[[str], None]] = None) -> None:
        """Fetch video/playlist info in a background thread."""
        t = threading.Thread(target=self._fetch_info_worker, args=(url, callback, error_cb, progress_cb), daemon=True)
        t.start()

    def enqueue(
        self,
        url: str,
        output_format: str,
        resolution: str,
        output_dir: str,
        video_info: Optional[VideoInfo] = None,
    ) -> DownloadTask:
        """Add a download task to the queue and start it immediately."""
        with self._lock:
            self._task_counter += 1
            task_id = f"task_{self._task_counter:04d}"

        task = DownloadTask(
            task_id=task_id,
            url=url,
            output_format=output_format,
            resolution=resolution,
            output_dir=output_dir,
            video_info=video_info,
        )
        with self._lock:
            self._tasks[task_id] = task

        t = threading.Thread(target=self._download_worker, args=(task,), daemon=True)
        t.start()
        logger.info("Enqueued task %s for %s", task_id, url)
        return task

    def cancel(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        if task:
            task.cancel()
            logger.info("Cancelled task %s", task_id)

    def pause(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        if task and task.status == DownloadStatus.RUNNING:
            task.pause()
            task.status = DownloadStatus.PAUSED
            logger.info("Paused task %s", task_id)

    def resume(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        if task and task.status == DownloadStatus.PAUSED:
            task.resume()
            task.status = DownloadStatus.RUNNING
            logger.info("Resumed task %s", task_id)

    def cancel_all(self) -> None:
        for task_id in list(self._tasks.keys()):
            self.cancel(task_id)

    def get_task(self, task_id: str) -> Optional[DownloadTask]:
        return self._tasks.get(task_id)

    def active_tasks(self) -> list[DownloadTask]:
        return [t for t in self._tasks.values()
                if t.status not in (DownloadStatus.COMPLETED, DownloadStatus.CANCELLED, DownloadStatus.ERROR)]

    # ---------------------------------------------------------------- #
    #  Workers                                                           #
    # ---------------------------------------------------------------- #

    def _fetch_info_worker(self, url: str, callback: InfoCallback, error_cb: ErrorCallback,
                           progress_cb: Optional[Callable[[str], None]] = None) -> None:
        """Background thread: extract video metadata without downloading."""
        def _log(msg: str):
            if progress_cb:
                progress_cb(msg)

        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            "skip_download": True,
        }
        try:
            _log("Connecting to URL…")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                _log("Extracting video information…")
                raw = ydl.extract_info(url, download=False)
                if raw is None:
                    error_cb("fetch", "No information returned for this URL.")
                    return

                # Handle playlists
                if raw.get("_type") == "playlist":
                    entries = raw.get("entries") or []
                    _log(f"Playlist detected: \"{raw.get('title', 'Playlist')}\" — {len(entries)} videos")
                    # Build a VideoInfo representing the playlist
                    info = VideoInfo(
                        url=url,
                        video_id=raw.get("id", ""),
                        title=raw.get("title", "Playlist"),
                        channel=raw.get("uploader") or raw.get("channel") or "Unknown",
                        duration=0,
                        thumbnail_url="",
                        description="",
                        is_playlist=True,
                        playlist_title=raw.get("title", "Playlist"),
                        playlist_count=len(entries),
                    )
                    # Parse individual entries (may be partial — that's OK)
                    restricted_count = 0
                    for i, entry in enumerate(entries, 1):
                        if entry:
                            try:
                                entry_info = parse_info(entry, entry.get("url") or entry.get("webpage_url") or url)
                                info.playlist_entries.append(entry_info)
                                # Use first video's thumbnail for playlist thumb
                                if not info.thumbnail_url and entry_info.thumbnail_url:
                                    info.thumbnail_url = entry_info.thumbnail_url
                                # Log restricted entries immediately
                                if entry_info.availability != "public":
                                    restricted_count += 1
                                    _log(f"  ⚠ [{i}] {entry_info.title[:55]} — {entry_info.restriction_reason}")
                                elif i % 10 == 0 or i == len(entries):
                                    _log(f"  Parsed {i}/{len(entries)} entries…")
                            except Exception:
                                pass
                    summary = f"Done — {len(info.playlist_entries)} entries"
                    if restricted_count:
                        summary += f" ({restricted_count} restricted)"
                    _log(summary + ".")
                    callback(info)
                else:
                    title = raw.get("title", "")
                    _log(f"Found: {title[:70]}" if title else "Parsing video info…")
                    info = parse_info(raw, url)
                    if info.availability != "public":
                        _log(f"⚠ Restricted: {info.restriction_reason}")
                    _log("Info ready.")
                    callback(info)

        except yt_dlp.utils.DownloadError as exc:
            error_cb("fetch", _friendly_error(str(exc)))
        except Exception as exc:
            error_cb("fetch", f"Unexpected error: {exc}")

    def _download_worker(self, task: DownloadTask) -> None:
        """Background thread: perform the actual download with retry-then-skip."""
        MAX_RETRIES = int(settings.get("max_retries", 3))
        RETRY_DELAY = int(settings.get("retry_delay", 5))

        task.status = DownloadStatus.RUNNING

        is_playlist = bool(task.video_info and task.video_info.is_playlist)
        total_videos = (task.video_info.playlist_count
                        if is_playlist and task.video_info else 1)

        # Mutable counters shared with hooks/logger
        completed_count: list[int] = [0]
        skipped_titles:  list[str] = []

        # ---- yt-dlp silent logger (suppress all yt-dlp internal noise) ----
        class _YdlLogger:
            def debug(self, msg):   pass
            def info(self, msg):    pass
            def warning(self, msg): pass
            def error(self, msg):   pass   # errors surface via ignoreerrors + hook

        last_error: str = ""

        for attempt in range(1, MAX_RETRIES + 1):
            if task.is_cancelled:
                break

            try:
                output_dir = Path(task.output_dir)
                output_dir.mkdir(parents=True, exist_ok=True)

                audio_only      = task.output_format in ("mp3", "m4a", "opus", "wav")
                format_selector = build_format_selector(task.output_format, task.resolution)
                postprocessors  = self._build_postprocessors(task.output_format, audio_only)
                outtmpl         = str(output_dir / "%(title)s [%(id)s].%(ext)s")

                ydl_opts: dict = {
                    "format":               format_selector,
                    "outtmpl":              outtmpl,
                    "logger":               _YdlLogger(),
                    "progress_hooks":       [self._make_progress_hook(
                                                task,
                                                completed_count,
                                                skipped_titles,
                                                total_videos,
                                                is_playlist,
                                            )],
                    "postprocessors":       postprocessors,
                    "merge_output_format":  task.output_format if not audio_only else None,
                    "writethumbnail":       settings.get("embed_thumbnail"),
                    "embedthumbnail":       settings.get("embed_thumbnail"),
                    "addmetadata":          settings.get("embed_metadata"),
                    "quiet":                True,
                    "no_warnings":          True,
                    "noprogress":           True,
                    "ignoreerrors":         is_playlist,   # skip bad videos in playlists only
                    "retries":              3,
                    "fragment_retries":     3,
                    "concurrent_fragment_downloads": 4,
                }
                # Drop None values
                ydl_opts = {k: v for k, v in ydl_opts.items() if v is not None}

                if attempt > 1:
                    self._emit_progress(task, DownloadProgress(
                        task_id=task.task_id,
                        status=DownloadStatus.RUNNING,
                        message=f"Retrying... (attempt {attempt}/{MAX_RETRIES})",
                    ))

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([task.url])

                # ---- success ----
                if task.is_cancelled:
                    task.status = DownloadStatus.CANCELLED
                    self._emit_progress(task, DownloadProgress(
                        task_id=task.task_id,
                        status=DownloadStatus.CANCELLED,
                        message="Download cancelled.",
                    ))
                else:
                    task.status = DownloadStatus.COMPLETED

                    # Summary for playlists
                    if is_playlist:
                        ok  = completed_count[0]
                        skp = len(skipped_titles)
                        summary = f"Download finished. {ok} downloaded"
                        if skp:
                            summary += f", {skp} skipped"
                        summary += f" / {total_videos} total"
                        self._emit_progress(task, DownloadProgress(
                            task_id=task.task_id,
                            status=DownloadStatus.RUNNING,
                            message=summary,
                        ))

                    task._skipped_titles  = skipped_titles
                    task._completed_count = completed_count[0]

                    prog = DownloadProgress(
                        task_id=task.task_id,
                        status=DownloadStatus.COMPLETED,
                        percent=100.0,
                        message="Download complete!",
                    )
                    self._emit_progress(task, prog)
                    if self._on_complete:
                        self._on_complete(prog)
                return  # done — exit retry loop

            except yt_dlp.utils.DownloadError as exc:
                if task.is_cancelled:
                    task.status = DownloadStatus.CANCELLED
                    self._emit_progress(task, DownloadProgress(
                        task_id=task.task_id,
                        status=DownloadStatus.CANCELLED,
                        message="Download cancelled.",
                    ))
                    return
                last_error = _friendly_error(str(exc))
                logger.warning("Download error for %s (attempt %d/%d): %s",
                               task.task_id, attempt, MAX_RETRIES, last_error)
                task.retry_count = attempt

            except Exception as exc:
                if task.is_cancelled:
                    task.status = DownloadStatus.CANCELLED
                    return
                last_error = str(exc)
                logger.warning("Unexpected error for %s (attempt %d/%d): %s",
                               task.task_id, attempt, MAX_RETRIES, last_error)
                task.retry_count = attempt

            if attempt < MAX_RETRIES and not task.is_cancelled:
                self._emit_progress(task, DownloadProgress(
                    task_id=task.task_id,
                    status=DownloadStatus.RUNNING,
                    message=f"Failed, retrying in {RETRY_DELAY}s... ({attempt}/{MAX_RETRIES})",
                ))
                time.sleep(RETRY_DELAY)

        # ---- all retries exhausted ----
        if not task.is_cancelled:
            task.status = DownloadStatus.SKIPPED
            task.error  = last_error
            logger.error("Skipping task %s after %d failed attempts: %s",
                         task.task_id, MAX_RETRIES, last_error)
            self._emit_progress(task, DownloadProgress(
                task_id=task.task_id,
                status=DownloadStatus.SKIPPED,
                message=f"Skipped after {MAX_RETRIES} failed attempts.",
            ))
            if self._on_error:
                self._on_error(task.task_id, f"Skipped: {last_error}")

    # ---------------------------------------------------------------- #
    #  Helpers                                                           #
    # ---------------------------------------------------------------- #

    def _make_progress_hook(
        self,
        task: DownloadTask,
        completed_count: list[int],
        skipped_titles:  list[str],
        total_videos:    int,
        is_playlist:     bool,
    ):
        """Return a yt-dlp progress hook that emits clean per-video log lines."""

        def hook(d: dict) -> None:
            # Respect cancel flag
            if task.is_cancelled:
                raise yt_dlp.utils.DownloadError("Cancelled by user")

            # Respect pause
            task._pause_event.wait()

            raw_status = d.get("status", "")

            # ── Per-video COMPLETED ──────────────────────────────────
            if raw_status == "finished":
                info_dict  = d.get("info_dict") or {}
                title      = (info_dict.get("title") or
                              Path(d.get("filename") or "").stem or
                              "Unknown")
                title      = title[:70]

                completed_count[0] += 1
                index = completed_count[0] + len(skipped_titles)
                idx_str = f"{index}/{total_videos}" if is_playlist else ""

                msg = f"Completed: {title}"
                if idx_str:
                    msg += f" ({idx_str})"

                self._emit_progress(task, DownloadProgress(
                    task_id=task.task_id,
                    status=DownloadStatus.RUNNING,
                    message=msg,
                ))
                return

            # ── Per-video ERROR (playlist only — ignoreerrors keeps going) ──
            if raw_status == "error":
                info_dict = d.get("info_dict") or {}
                title     = (info_dict.get("title") or
                             info_dict.get("id") or
                             "Unknown video")
                title     = title[:70]
                error_raw = d.get("error") or ""
                reason    = _short_error(error_raw)

                skipped_titles.append(title)
                index = completed_count[0] + len(skipped_titles)
                idx_str = f"{index}/{total_videos}" if is_playlist else ""

                msg = f"Skipped: {title} ({reason})"
                if idx_str:
                    msg += f" ({idx_str})"

                self._emit_progress(task, DownloadProgress(
                    task_id=task.task_id,
                    status=DownloadStatus.RUNNING,
                    message=msg,
                ))
                return

            # ── Downloading — forward speed/progress ─────────────────
            if raw_status == "downloading":
                total      = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                downloaded = d.get("downloaded_bytes") or 0
                percent    = (downloaded / total * 100) if total else 0
                speed_raw  = d.get("speed") or 0
                speed_str  = f"{_human_bytes(int(speed_raw))}/s" if speed_raw else ""
                eta_raw    = d.get("eta")
                eta_str    = _format_eta(eta_raw) if eta_raw else ""
                filename   = Path(d.get("filename") or "").name

                self._emit_progress(task, DownloadProgress(
                    task_id=task.task_id,
                    status=DownloadStatus.RUNNING,
                    filename=filename,
                    percent=round(percent, 1),
                    speed=speed_str,
                    eta=eta_str,
                    downloaded_bytes=downloaded,
                    total_bytes=total,
                ))

        return hook

    def _emit_progress(self, task: DownloadTask, prog: DownloadProgress) -> None:
        if self._on_progress:
            try:
                self._on_progress(prog)
            except Exception:
                pass

    @staticmethod
    def _build_postprocessors(output_format: str, audio_only: bool) -> list[dict]:
        """Build yt-dlp postprocessor list for the chosen format."""
        pp = []
        if audio_only:
            pp.append({
                "key": "FFmpegExtractAudio",
                "preferredcodec": output_format,
                "preferredquality": "192" if output_format == "mp3" else "0",
            })
        if settings.get("embed_metadata"):
            pp.append({"key": "FFmpegMetadata", "add_metadata": True})
        if settings.get("embed_thumbnail"):
            pp.append({"key": "EmbedThumbnail"})
        return pp


# ------------------------------------------------------------------ #
#  Utility functions                                                   #
# ------------------------------------------------------------------ #

def _human_bytes(n: int) -> str:
    if n <= 0:
        return "0 B"
    for unit, thresh in [("GB", 1_073_741_824), ("MB", 1_048_576), ("KB", 1024)]:
        if n >= thresh:
            return f"{n / thresh:.1f} {unit}"
    return f"{n} B"


def _format_eta(seconds: int) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def _short_error(raw: str) -> str:
    """Return a short human-readable reason for a per-video skip."""
    msg = raw.lower()
    if "age" in msg and ("restrict" in msg or "confirm" in msg):
        return "Age restricted"
    if "private" in msg:
        return "Private video"
    if "copyright" in msg:
        return "Copyright claim"
    if "not available" in msg or "unavailable" in msg:
        return "Unavailable"
    if "login" in msg or "sign in" in msg or "cookie" in msg:
        return "Login required"
    if "format" in msg or "no video" in msg:
        return "Format unavailable"
    if "network" in msg or "timed out" in msg or "connection" in msg:
        return "Network error"
    cleaned = raw.replace("ERROR: ", "").strip()
    return cleaned[:60] if cleaned else "Error"


def _friendly_error(raw: str) -> str:
    """Convert yt-dlp error strings to user-friendly messages."""
    msg = raw.lower()
    if "private video" in msg:
        return "This video is private and cannot be downloaded."
    if "age" in msg and ("restrict" in msg or "confirm" in msg):
        return "Age-restricted video. Cookies or login required."
    if "not available" in msg:
        return "This video is not available in your region."
    if "unable to extract" in msg:
        return "Unable to extract video information. The URL may be invalid."
    if "no video formats" in msg or "requested format" in msg:
        return "The requested format/resolution is not available for this video."
    if "network" in msg or "connection" in msg or "timed out" in msg:
        return "Network error. Check your internet connection."
    if "copyright" in msg:
        return "This video has been removed due to a copyright claim."
    # Strip yt-dlp prefix for cleaner display
    cleaned = raw.replace("ERROR: ", "").strip()
    return cleaned[:300]  # cap length
