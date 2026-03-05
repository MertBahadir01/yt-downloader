"""
downloader/format_parser.py
============================
Parses raw yt-dlp format dictionaries into clean, UI-friendly objects.
Isolated so UI code never touches raw yt-dlp dicts directly.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class VideoFormat:
    """Represents one available format returned by yt-dlp."""
    format_id: str
    ext: str
    resolution: str          # e.g. "1080p", "audio only"
    fps: Optional[int]
    vcodec: str
    acodec: str
    filesize: Optional[int]  # bytes, may be None
    tbr: Optional[float]     # total bitrate kbps
    note: str                # yt-dlp's format_note
    has_video: bool
    has_audio: bool

    @property
    def filesize_human(self) -> str:
        if self.filesize is None:
            return "?"
        for unit, threshold in [("GB", 1_073_741_824), ("MB", 1_048_576), ("KB", 1024)]:
            if self.filesize >= threshold:
                return f"{self.filesize / threshold:.1f} {unit}"
        return f"{self.filesize} B"

    @property
    def label(self) -> str:
        parts = [self.resolution]
        if self.fps and self.fps > 30:
            parts.append(f"{self.fps}fps")
        if self.ext:
            parts.append(self.ext.upper())
        if self.filesize:
            parts.append(self.filesize_human)
        return " · ".join(parts)


@dataclass
class VideoInfo:
    """Parsed metadata for a single video."""
    url: str
    video_id: str
    title: str
    channel: str
    duration: int            # seconds
    thumbnail_url: str
    description: str
    formats: list[VideoFormat] = field(default_factory=list)
    is_playlist: bool = False
    playlist_title: str = ""
    playlist_count: int = 0
    playlist_entries: list["VideoInfo"] = field(default_factory=list)

    @property
    def duration_human(self) -> str:
        h, rem = divmod(self.duration, 3600)
        m, s = divmod(rem, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    @property
    def video_formats(self) -> list[VideoFormat]:
        return [f for f in self.formats if f.has_video]

    @property
    def audio_formats(self) -> list[VideoFormat]:
        return [f for f in self.formats if not f.has_video and f.has_audio]


# ------------------------------------------------------------------ #
#  Parsing helpers                                                     #
# ------------------------------------------------------------------ #

def parse_format(raw: dict) -> VideoFormat:
    """Convert a raw yt-dlp format dict to a VideoFormat."""
    vcodec = raw.get("vcodec") or "none"
    acodec = raw.get("acodec") or "none"
    has_video = vcodec != "none"
    has_audio = acodec != "none"

    height = raw.get("height")
    if height:
        resolution = f"{height}p"
    elif not has_video:
        resolution = "audio only"
    else:
        resolution = raw.get("format_note") or "unknown"

    return VideoFormat(
        format_id=raw.get("format_id", ""),
        ext=raw.get("ext", ""),
        resolution=resolution,
        fps=raw.get("fps"),
        vcodec=vcodec,
        acodec=acodec,
        filesize=raw.get("filesize") or raw.get("filesize_approx"),
        tbr=raw.get("tbr"),
        note=raw.get("format_note", ""),
        has_video=has_video,
        has_audio=has_audio,
    )


def parse_info(raw: dict, url: str) -> VideoInfo:
    """Convert a raw yt-dlp info dict to VideoInfo."""
    formats = [parse_format(f) for f in raw.get("formats", [])]

    return VideoInfo(
        url=url,
        video_id=raw.get("id", ""),
        title=raw.get("title", "Unknown"),
        channel=raw.get("uploader") or raw.get("channel") or "Unknown",
        duration=raw.get("duration") or 0,
        thumbnail_url=raw.get("thumbnail") or "",
        description=raw.get("description") or "",
        formats=formats,
    )


# Resolutions the UI offers as quick-picks
RESOLUTION_OPTIONS = ["best", "2160p", "1440p", "1080p", "720p", "480p", "360p", "240p", "144p"]

# Format string templates for yt-dlp
FORMAT_TEMPLATES: dict[str, str] = {
    # (output_format, resolution) -> yt-dlp format selector
    # Video formats
    ("mp4", "best"):   "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
    ("mp4", "1080p"):  "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best",
    ("mp4", "720p"):   "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=720]+bestaudio/best",
    ("mp4", "480p"):   "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480]",
    ("mp4", "360p"):   "bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360]",
    ("mp4", "240p"):   "bestvideo[height<=240][ext=mp4]+bestaudio[ext=m4a]/best[height<=240]",
    ("mp4", "144p"):   "bestvideo[height<=144][ext=mp4]+bestaudio[ext=m4a]/best[height<=144]",
    ("webm", "best"):  "bestvideo[ext=webm]+bestaudio[ext=webm]/bestvideo+bestaudio/best",
    ("webm", "1080p"): "bestvideo[height<=1080][ext=webm]+bestaudio[ext=webm]/best",
    ("webm", "720p"):  "bestvideo[height<=720][ext=webm]+bestaudio[ext=webm]/best",
    # Audio-only
    ("mp3", "best"):   "bestaudio/best",
    ("m4a", "best"):   "bestaudio[ext=m4a]/bestaudio/best",
    ("opus", "best"):  "bestaudio[ext=webm]/bestaudio/best",
    ("wav", "best"):   "bestaudio/best",
}


def build_format_selector(output_format: str, resolution: str) -> str:
    """Return the yt-dlp format string for the given output format + resolution."""
    key = (output_format.lower(), resolution.lower())
    if key in FORMAT_TEMPLATES:
        return FORMAT_TEMPLATES[key]
    # Generic fallback: pick best video up to requested height
    height_map = {"2160p": 2160, "1440p": 1440, "1080p": 1080, "720p": 720,
                  "480p": 480, "360p": 360, "240p": 240, "144p": 144}
    h = height_map.get(resolution)
    if h:
        return f"bestvideo[height<={h}]+bestaudio/best[height<={h}]"
    return "bestvideo+bestaudio/best"
