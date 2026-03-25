"""
ui/main_window.py
==================
Root application window. Wires together all panels and the downloader engine.
This is the top-level controller: it owns the YTDownloader instance and routes
callbacks between UI panels.
"""

from __future__ import annotations

import tkinter as tk
import customtkinter as ctk
from tkinter import messagebox
from typing import Optional
import threading
import logging
import sys

from app.downloader.yt_downloader import (
    YTDownloader, DownloadProgress, DownloadStatus, DownloadTask
)
from app.downloader.format_parser import VideoInfo
from app.ui.download_panel import DownloadPanel
from app.ui.progress_panel import ProgressPanel
from app.utils.settings import settings
from app.utils.logger import setup_logging, register_ui_callback

logger = logging.getLogger(__name__)

# Theme: "dark" / "light" / "system"
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class MainWindow:
    """Main application window."""

    def __init__(self):
        setup_logging()
        register_ui_callback(self._on_log_message)

        # tkinterdnd2 must initialise before CTk steals the Tk root class.
        # Use TkinterDnD.Tk() as the base window; CTk theming still applies.
        self._root = ctk.CTk()

        self._root.title("YT Downloader")
        self._root.geometry(
            f"{settings.get('window_width')}x{settings.get('window_height')}"
        )
        self._root.minsize(900, 640)
        self._root.after(0, lambda: self._root.state("zoomed") if sys.platform != "darwin" else self._root.attributes("-fullscreen", True))

        # Downloader engine
        self._downloader = YTDownloader(
            on_progress = self._on_progress,
            on_info     = self._on_info_received,
            on_error    = self._on_download_error,
            on_complete = self._on_download_complete,
        )

        self._current_task: Optional[DownloadTask] = None
        self._fetch_in_progress = False

        self._build_ui()
        self._bind_events()

    # ---------------------------------------------------------------- #
    #  UI construction                                                  #
    # ---------------------------------------------------------------- #

    def _build_ui(self):
        # ── App header bar ────────────────────────────────────────
        header = ctk.CTkFrame(self._root, height=52, fg_color=("#E2E8F0", "#0F172A"), corner_radius=0)
        header.pack(fill="x")
        header.pack_propagate(False)

        ctk.CTkLabel(
            header,
            text="⬇  YT Downloader",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=("#0F172A", "#F1F5F9"),
        ).pack(side="left", padx=20)

        # Theme toggle
        self._theme_switch = ctk.CTkSwitch(
            header, text="Dark Mode",
            font=ctk.CTkFont(size=12),
            command=self._toggle_theme,
        )
        self._theme_switch.pack(side="right", padx=20)
        self._theme_switch.select()  # dark by default

        # History button
        ctk.CTkButton(
            header, text="📋 History", width=90, height=28,
            font=ctk.CTkFont(size=12),
            fg_color=("#CBD5E1", "#1E293B"), hover_color=("#94A3B8", "#334155"),
            command=self._show_history,
        ).pack(side="right", padx=(0, 8))

        # Settings button
        ctk.CTkButton(
            header, text="⚙ Settings", width=90, height=28,
            font=ctk.CTkFont(size=12),
            fg_color=("#CBD5E1", "#1E293B"), hover_color=("#94A3B8", "#334155"),
            command=self._show_settings,
        ).pack(side="right", padx=(0, 4))

        # ── URL input bar ─────────────────────────────────────────
        url_bar = ctk.CTkFrame(self._root, fg_color=("#F1F5F9", "#1E293B"), corner_radius=0, height=60)
        url_bar.pack(fill="x")
        url_bar.pack_propagate(False)

        ctk.CTkLabel(url_bar, text="URL:", font=ctk.CTkFont(size=13),
                     width=40).pack(side="left", padx=(16, 6), pady=14)

        self._url_var = tk.StringVar()
        self._url_entry = ctk.CTkEntry(
            url_bar,
            textvariable=self._url_var,
            placeholder_text="Paste a YouTube video or playlist URL…",
            font=ctk.CTkFont(size=13),
            height=36,
            border_color=("#94A3B8", "#334155"),
            fg_color=("#FFFFFF", "#0F172A"),
        )
        self._url_entry.pack(side="left", fill="x", expand=True, padx=(0, 8), pady=12)

        self._btn_paste = ctk.CTkButton(
            url_bar, text="⎘ Paste", width=75, height=36,
            font=ctk.CTkFont(size=12),
            fg_color=("#CBD5E1", "#334155"), hover_color=("#94A3B8", "#475569"),
            command=self._paste_url,
        )
        self._btn_paste.pack(side="left", padx=(0, 6))

        self._btn_fetch = ctk.CTkButton(
            url_bar, text="🔍 Fetch Info", width=110, height=36,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#1D4ED8", hover_color="#1E40AF",
            command=self._fetch_info,
        )
        self._btn_fetch.pack(side="left", padx=(0, 16))

        # ── Status indicator ──────────────────────────────────────
        self._status_bar = ctk.CTkLabel(
            self._root, text="Ready",
            font=ctk.CTkFont(size=11),
            text_color=("#6B7280", "#6B7280"),
            anchor="w",
        )
        self._status_bar.pack(fill="x", padx=20, pady=(4, 0))

        # ── Scrollable main content area ──────────────────────────
        self._content_scroll = ctk.CTkScrollableFrame(
            self._root,
            fg_color="transparent",
            scrollbar_button_color=("#94A3B8", "#334155"),
            scrollbar_button_hover_color=("#64748B", "#475569"),
        )
        self._content_scroll.pack(fill="both", expand=True, padx=0, pady=0)

        # Middle: video info + format selector
        self._download_panel = DownloadPanel(
            self._content_scroll,
            on_download_requested=self._on_download_requested,
            fg_color=("#F8FAFC", "#162032"),
            corner_radius=0,
        )
        self._download_panel.pack(fill="x")

        # Separator
        sep = ctk.CTkFrame(self._content_scroll, height=1, fg_color=("#CBD5E1", "#1E293B"))
        sep.pack(fill="x")

        # Bottom: progress + log
        self._progress_panel = ProgressPanel(
            self._content_scroll,
            fg_color=("#F1F5F9", "#0F172A"),
            corner_radius=0,
        )
        self._progress_panel.pack(fill="both", expand=True)

        # ── Focus-based scroll routing ────────────────────────────
        from app.ui.scroll_manager import ScrollManager
        main_canvas = getattr(self._content_scroll, "_parent_canvas", None)
        if main_canvas:
            self._scroll_manager = ScrollManager(main_canvas, self._root)
            self._download_panel.register_scroll(self._scroll_manager)
            self._progress_panel.register_scroll(self._scroll_manager)

            # Clicking the main canvas (outside all zones) releases focus
            main_canvas.bind("<Button-1>", lambda _e: self._scroll_manager.release(), add="+")
            self._content_scroll.bind("<Button-1>", lambda _e: self._scroll_manager.release(), add="+")

        # ── Download control strip ────────────────────────────────
        ctrl = ctk.CTkFrame(self._root, fg_color=("#E2E8F0", "#0F172A"), corner_radius=0, height=50)
        ctrl.pack(fill="x", side="bottom")
        ctrl.pack_propagate(False)

        self._btn_cancel = ctk.CTkButton(
            ctrl, text="✕ Cancel", width=100, height=32,
            font=ctk.CTkFont(size=12),
            fg_color="#7F1D1D", hover_color="#991B1B",
            command=self._cancel_download,
            state="disabled",
        )
        self._btn_cancel.pack(side="right", padx=16, pady=9)

        self._btn_pause_resume = ctk.CTkButton(
            ctrl, text="⏸ Pause", width=100, height=32,
            font=ctk.CTkFont(size=12),
            fg_color="#78350F", hover_color="#92400E",
            command=self._toggle_pause,
            state="disabled",
        )
        self._btn_pause_resume.pack(side="right", padx=(0, 6), pady=9)

        self._lbl_queue = ctk.CTkLabel(
            ctrl, text="",
            font=ctk.CTkFont(size=11), text_color=("#6B7280", "#6B7280"),
        )
        self._lbl_queue.pack(side="left", padx=16)

    # ---------------------------------------------------------------- #
    #  Event bindings                                                   #
    # ---------------------------------------------------------------- #

    def _bind_events(self):
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._url_entry.bind("<Return>", lambda _: self._fetch_info())

        # Drag-and-drop URL support
        try:
            from tkinterdnd2 import DND_TEXT
            self._root.drop_target_register(DND_TEXT)
            self._root.dnd_bind("<<Drop>>", self._on_drop)
            logger.info("Drag-and-drop enabled.")
        except Exception:
            logger.debug("tkinterdnd2 not available; drag-and-drop disabled.")

    # ---------------------------------------------------------------- #
    #  URL / fetch actions                                             #
    # ---------------------------------------------------------------- #

    def _paste_url(self):
        try:
            text = self._root.clipboard_get().strip()
            self._url_var.set(text)
        except tk.TclError:
            pass

    def _fetch_info(self):
        url = self._url_var.get().strip()
        if not url:
            messagebox.showwarning("No URL", "Please enter a YouTube URL first.")
            return
        if not url.startswith(("http://", "https://")):
            messagebox.showwarning("Invalid URL", "URL must start with http:// or https://")
            return

        self._fetch_in_progress = True
        self._btn_fetch.configure(state="disabled", text="Fetching…")
        self._download_panel.clear()
        self._download_panel.set_loading(True)
        self._set_status("Fetching video info…", "#60A5FA")
        self._progress_panel.append_log("── Fetch started ──", "INFO")

        def _on_fetch_progress(msg: str):
            level = "WARNING" if msg.startswith("⚠") else "INFO"
            self._root.after(0, lambda m=msg, l=level: self._progress_panel.append_log(f"  {m}", l))

        self._downloader.fetch_info(
            url,
            callback    = self._on_info_received,
            error_cb    = self._on_fetch_error,
            progress_cb = _on_fetch_progress,
        )

    def _on_drop(self, event):
        """Handle drag-and-drop of a URL onto the window."""
        url = event.data.strip().strip("{}")
        self._url_var.set(url)
        self._fetch_info()

    # ---------------------------------------------------------------- #
    #  Downloader callbacks (called from background threads)           #
    # ---------------------------------------------------------------- #

    def _on_info_received(self, info: VideoInfo) -> None:
        """Schedule UI update on main thread."""
        self._root.after(0, lambda: self._apply_info(info))

    def _on_fetch_error(self, _task_id: str, message: str) -> None:
        self._root.after(0, lambda: self._handle_fetch_error(message))

    def _on_progress(self, prog: DownloadProgress) -> None:
        self._root.after(0, lambda: self._handle_progress(prog))

    def _handle_progress(self, prog: DownloadProgress) -> None:
        """Update progress bar and route per-video log messages to console."""
        self._progress_panel.update_progress(prog)
        if prog.message:
            if prog.message.startswith("Completed:"):
                self._progress_panel.append_log(prog.message, "SUCCESS")
            elif prog.message.startswith("Skipped:"):
                self._progress_panel.append_log(prog.message, "WARNING")
            elif prog.message.startswith("Download finished"):
                pass  # summary shown in _handle_complete
            elif "Retrying" in prog.message or "retrying" in prog.message:
                self._progress_panel.append_log(prog.message, "WARNING")
            elif "Failed" in prog.message:
                self._progress_panel.append_log(prog.message, "WARNING")

    def _on_download_error(self, task_id: str, message: str) -> None:
        self._root.after(0, lambda: self._handle_download_error(message))

    def _on_download_complete(self, prog: DownloadProgress) -> None:
        self._root.after(0, lambda: self._handle_complete(prog))

    def _on_log_message(self, message: str, level: str) -> None:
        """Called by UILogHandler — forward to log console on main thread."""
        try:
            self._root.after(0, lambda: self._progress_panel.append_log(message, level))
        except Exception:
            pass

    # ---------------------------------------------------------------- #
    #  UI update methods (called on main thread via .after())          #
    # ---------------------------------------------------------------- #

    def _apply_info(self, info: VideoInfo) -> None:
        self._fetch_in_progress = False
        self._btn_fetch.configure(state="normal", text="🔍 Fetch Info")
        self._download_panel.set_loading(False)
        self._download_panel.set_video_info(info)

        label = f"Playlist: {info.playlist_count} videos" if info.is_playlist else "Video ready"
        self._set_status(f"✓  {label} — {info.title[:60]}", "#10B981")
        self._progress_panel.append_log(f"✓ Fetch complete: {info.title[:65]}", "SUCCESS")

    def _handle_fetch_error(self, message: str) -> None:
        self._fetch_in_progress = False
        self._btn_fetch.configure(state="normal", text="🔍 Fetch Info")
        self._download_panel.set_loading(False)
        self._set_status(f"Error: {message[:80]}", "#EF4444")
        self._progress_panel.append_log(f"Fetch error: {message}", "ERROR")

    def _handle_download_error(self, message: str) -> None:
        if message.startswith("Skipped:"):
            self._set_status(f"⚠ {message[:80]}", "#F59E0B")
            self._progress_panel.append_log(message, "WARNING")
        else:
            self._set_status(f"Download error: {message[:80]}", "#EF4444")
            self._progress_panel.append_log(f"Download error: {message}", "ERROR")
        self._reset_controls()

    def _handle_complete(self, prog: DownloadProgress) -> None:
        task = self._current_task
        self._reset_controls()

        if task and task.video_info:
            info      = task.video_info
            completed = getattr(task, "_completed_count", None)
            skipped   = getattr(task, "_skipped_titles", [])

            if info.is_playlist:
                if completed is None:
                    selected  = self._download_panel.get_selected_count()
                    completed = selected if selected is not None else info.playlist_count
                total     = info.playlist_count
                title     = info.playlist_title or info.title
                status_msg = f"✓  {completed}/{total} videos downloaded — {title[:50]}"
                log_msg    = (f"Download finished. {completed} downloaded"
                              + (f", {len(skipped)} skipped" if skipped else "")
                              + f" / {total} total")
            else:
                title      = info.title
                status_msg = f"✓  Downloaded — {title[:65]}"
                log_msg    = f"Download finished."
        else:
            status_msg = "✓  Download complete!"
            log_msg    = "Download finished."

        self._set_status(status_msg, "#10B981")
        self._progress_panel.append_log(log_msg, "SUCCESS")

        # Save to history
        if task and task.video_info:
            from datetime import datetime
            info = task.video_info
            settings.add_to_history({
                "title":      info.title,
                "url":        info.url,
                "format":     task.output_format,
                "resolution": task.resolution,
                "dir":        task.output_dir,
                "status":     "completed",
                "date":       datetime.now().strftime("%Y-%m-%d %H:%M"),
            })

    # ---------------------------------------------------------------- #
    #  Download controls                                               #
    # ---------------------------------------------------------------- #

    def _on_download_requested(
        self,
        url: str,
        output_format: str,
        resolution: str,
        output_dir: str,
        video_info: Optional[VideoInfo],
    ) -> None:
        self._progress_panel.reset_progress()
        if video_info and video_info.is_playlist:
            start_msg = (f"Starting download: {video_info.playlist_title or video_info.title}"
                         f" ({video_info.playlist_count} videos)")
        else:
            start_msg = f"Starting download: {video_info.title if video_info else url}"
        self._progress_panel.append_log(start_msg, "INFO")
        self._set_status("Downloading…", "#F59E0B")

        task = self._downloader.enqueue(
            url=url,
            output_format=output_format,
            resolution=resolution,
            output_dir=output_dir,
            video_info=video_info,
        )
        self._current_task = task
        self._btn_cancel.configure(state="normal")
        self._btn_pause_resume.configure(state="normal")

    def _cancel_download(self) -> None:
        if self._current_task:
            self._downloader.cancel(self._current_task.task_id)
            self._set_status("Cancelled.", "#6B7280")
            self._progress_panel.append_log("Download cancelled by user.", "WARNING")
        self._reset_controls()

    def _toggle_pause(self) -> None:
        if not self._current_task:
            return
        task = self._current_task
        if task.status == DownloadStatus.RUNNING:
            self._downloader.pause(task.task_id)
            self._btn_pause_resume.configure(text="▶ Resume")
            self._set_status("Paused", "#F59E0B")
        elif task.status == DownloadStatus.PAUSED:
            self._downloader.resume(task.task_id)
            self._btn_pause_resume.configure(text="⏸ Pause")
            self._set_status("Downloading…", "#F59E0B")

    def _reset_controls(self) -> None:
        self._btn_cancel.configure(state="disabled")
        self._btn_pause_resume.configure(state="disabled", text="⏸ Pause")
        self._current_task = None

    # ---------------------------------------------------------------- #
    #  Settings dialog                                                  #
    # ---------------------------------------------------------------- #

    def _show_settings(self) -> None:
        win = ctk.CTkToplevel(self._root)
        win.title("Settings")
        win.geometry("460x480")
        win.grab_set()

        ctk.CTkLabel(win, text="Settings", font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(16, 8))

        frame = ctk.CTkFrame(win)
        frame.pack(fill="both", expand=True, padx=20, pady=8)
        frame.grid_columnconfigure(1, weight=1)

        def _row(parent, label, row):
            ctk.CTkLabel(parent, text=label, anchor="w").grid(
                row=row, column=0, sticky="w", padx=12, pady=8)

        def _spinbox(parent, row, var, min_val, max_val):
            """Number entry with +/- buttons."""
            box = ctk.CTkFrame(parent, fg_color="transparent")
            box.grid(row=row, column=1, sticky="e", padx=12, pady=8)
            ctk.CTkButton(box, text="−", width=28, height=28,
                          command=lambda: var.set(max(min_val, var.get() - 1))).pack(side="left")
            lbl = ctk.CTkLabel(box, textvariable=var, width=40, anchor="center",
                               font=ctk.CTkFont(size=13, weight="bold"))
            lbl.pack(side="left", padx=6)
            ctk.CTkButton(box, text="+", width=28, height=28,
                          command=lambda: var.set(min(max_val, var.get() + 1))).pack(side="left")

        # Embed metadata
        meta_var = tk.BooleanVar(value=settings.get("embed_metadata"))
        _row(frame, "Embed metadata", 0)
        ctk.CTkSwitch(frame, text="", variable=meta_var).grid(row=0, column=1, sticky="e", padx=12, pady=8)

        # Embed thumbnail
        thumb_var = tk.BooleanVar(value=settings.get("embed_thumbnail"))
        _row(frame, "Embed thumbnail in file", 1)
        ctk.CTkSwitch(frame, text="", variable=thumb_var).grid(row=1, column=1, sticky="e", padx=12, pady=8)

        # Separator
        ctk.CTkFrame(frame, height=1, fg_color=("#CBD5E1", "#334155")).grid(
            row=2, column=0, columnspan=2, sticky="ew", padx=12, pady=4)

        # Concurrent downloads
        conc_var = tk.IntVar(value=settings.get("concurrent_downloads"))
        _row(frame, "Concurrent downloads", 3)
        _spinbox(frame, 3, conc_var, 1, 10)

        # Max retries
        retry_var = tk.IntVar(value=settings.get("max_retries"))
        _row(frame, "Max retries per video", 4)
        _spinbox(frame, 4, retry_var, 0, 10)

        # Retry delay
        delay_var = tk.IntVar(value=settings.get("retry_delay"))
        _row(frame, "Retry delay (seconds)", 5)
        _spinbox(frame, 5, delay_var, 1, 60)

        def _save():
            settings.set("embed_metadata",      meta_var.get())
            settings.set("embed_thumbnail",      thumb_var.get())
            settings.set("concurrent_downloads", conc_var.get())
            settings.set("max_retries",          retry_var.get())
            settings.set("retry_delay",          delay_var.get())
            settings.save()
            win.destroy()

        ctk.CTkButton(win, text="Save", command=_save).pack(pady=14)

    # ---------------------------------------------------------------- #
    #  History dialog                                                   #
    # ---------------------------------------------------------------- #

    def _show_history(self) -> None:
        win = ctk.CTkToplevel(self._root)
        win.title("Download History")
        win.geometry("680x520")
        win.grab_set()
        win.grid_columnconfigure(0, weight=1)
        win.grid_rowconfigure(1, weight=1)

        # Header
        hdr = ctk.CTkFrame(win, fg_color=("#CBD5E1", "#16213e"), corner_radius=0)
        hdr.grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(hdr, text="Download History",
                     font=ctk.CTkFont(size=15, weight="bold")).pack(side="left", padx=16, pady=10)

        scroll_holder = [None]  # mutable ref so _build can replace scroll

        def _build_scroll():
            if scroll_holder[0]:
                scroll_holder[0].destroy()
            history = settings.get("download_history") or []
            scroll = ctk.CTkScrollableFrame(win, fg_color=("#F8FAFC", "#0F172A"), corner_radius=0)
            scroll.grid(row=1, column=0, sticky="nsew")
            scroll.grid_columnconfigure(0, weight=1)
            scroll_holder[0] = scroll

            if not history:
                ctk.CTkLabel(scroll, text="No downloads yet.",
                             text_color=("#6B7280", "#6B7280"),
                             font=ctk.CTkFont(size=13)).pack(pady=40)
                return

            for i, entry in enumerate(history):
                status = entry.get("status", "completed")
                status_color = "#10B981" if status == "completed" else "#EF4444"

                card = ctk.CTkFrame(scroll, fg_color=("#FFFFFF", "#1E293B"), corner_radius=8)
                card.grid(row=i, column=0, sticky="ew", padx=12, pady=4)
                card.grid_columnconfigure(0, weight=1)

                ctk.CTkLabel(card,
                             text=entry.get("title", "Unknown title")[:65],
                             font=ctk.CTkFont(size=12, weight="bold"),
                             anchor="w").grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 2))

                fmt        = entry.get("format", "?").upper()
                resolution = entry.get("resolution", "")
                date       = entry.get("date", "")
                meta = "  ·  ".join(filter(None, [date, fmt, resolution]))
                ctk.CTkLabel(card, text=meta,
                             font=ctk.CTkFont(size=11),
                             text_color=("#6B7280", "#9CA3AF"), anchor="w").grid(
                             row=1, column=0, sticky="ew", padx=10, pady=(0, 8))

                ctk.CTkLabel(card,
                             text=status.upper(),
                             font=ctk.CTkFont(size=10, weight="bold"),
                             text_color=status_color).grid(
                             row=0, column=1, rowspan=2, padx=14)

        def _clear():
            settings.clear_history()
            _build_scroll()

        ctk.CTkButton(hdr, text="Clear History", width=120,
                      fg_color="#7F1D1D", hover_color="#991B1B",
                      command=_clear).pack(side="right", padx=16, pady=8)

        _build_scroll()


    # ---------------------------------------------------------------- #
    #  Theme toggle                                                     #
    # ---------------------------------------------------------------- #

    def _toggle_theme(self) -> None:
        mode = "dark" if self._theme_switch.get() else "light"
        ctk.set_appearance_mode(mode)
        settings.set("theme", mode)
        settings.save()

    # ---------------------------------------------------------------- #
    #  Misc                                                             #
    # ---------------------------------------------------------------- #

    def _set_status(self, message: str, colour: str = "#6B7280") -> None:
        self._status_bar.configure(text=message, text_color=colour)

    def _on_close(self) -> None:
        if self._downloader.active_tasks():
            if not messagebox.askyesno(
                "Active downloads",
                "There are active downloads. Cancel them and exit?",
            ):
                return
            self._downloader.cancel_all()

        # Save window size
        w = self._root.winfo_width()
        h = self._root.winfo_height()
        settings.set("window_width", w)
        settings.set("window_height", h)
        settings.save()
        self._root.destroy()

    def run(self) -> None:
        """Start the Tkinter event loop."""
        self._root.mainloop()
