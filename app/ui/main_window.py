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

        self._root = ctk.CTk()
        self._root.title("YT Downloader")
        self._root.geometry(
            f"{settings.get('window_width')}x{settings.get('window_height')}"
        )
        self._root.minsize(900, 640)

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
        header = ctk.CTkFrame(self._root, height=52, fg_color="#0F172A", corner_radius=0)
        header.pack(fill="x")
        header.pack_propagate(False)

        ctk.CTkLabel(
            header,
            text="⬇  YT Downloader",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color="#F1F5F9",
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
            fg_color="#1E293B", hover_color="#334155",
            command=self._show_history,
        ).pack(side="right", padx=(0, 8))

        # Settings button
        ctk.CTkButton(
            header, text="⚙ Settings", width=90, height=28,
            font=ctk.CTkFont(size=12),
            fg_color="#1E293B", hover_color="#334155",
            command=self._show_settings,
        ).pack(side="right", padx=(0, 4))

        # ── URL input bar ─────────────────────────────────────────
        url_bar = ctk.CTkFrame(self._root, fg_color="#1E293B", corner_radius=0, height=60)
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
            border_color="#334155",
            fg_color="#0F172A",
        )
        self._url_entry.pack(side="left", fill="x", expand=True, padx=(0, 8), pady=12)

        self._btn_paste = ctk.CTkButton(
            url_bar, text="⎘ Paste", width=75, height=36,
            font=ctk.CTkFont(size=12),
            fg_color="#334155", hover_color="#475569",
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
            text_color="#6B7280",
            anchor="w",
        )
        self._status_bar.pack(fill="x", padx=20, pady=(4, 0))

        # ── Scrollable main content area ──────────────────────────
        content = ctk.CTkFrame(self._root, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=0, pady=0)

        # Middle: video info + format selector
        self._download_panel = DownloadPanel(
            content,
            on_download_requested=self._on_download_requested,
            fg_color="#162032",
            corner_radius=0,
        )
        self._download_panel.pack(fill="x")

        # Separator
        sep = ctk.CTkFrame(content, height=1, fg_color="#1E293B")
        sep.pack(fill="x")

        # Bottom: progress + log
        self._progress_panel = ProgressPanel(
            content,
            fg_color="#0F172A",
            corner_radius=0,
        )
        self._progress_panel.pack(fill="both", expand=True)

        # ── Download control strip ────────────────────────────────
        ctrl = ctk.CTkFrame(self._root, fg_color="#0F172A", corner_radius=0, height=50)
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
            font=ctk.CTkFont(size=11), text_color="#6B7280",
        )
        self._lbl_queue.pack(side="left", padx=16)

    # ---------------------------------------------------------------- #
    #  Event bindings                                                   #
    # ---------------------------------------------------------------- #

    def _bind_events(self):
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._url_entry.bind("<Return>", lambda _: self._fetch_info())

        # Drag-and-drop URL support (optional — requires tkinterdnd2)
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

        self._downloader.fetch_info(
            url,
            callback = self._on_info_received,
            error_cb = self._on_fetch_error,
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
        self._root.after(0, lambda: self._progress_panel.update_progress(prog))

    def _on_download_error(self, task_id: str, message: str) -> None:
        self._root.after(0, lambda: self._handle_download_error(message))

    def _on_download_complete(self, prog: DownloadProgress) -> None:
        self._root.after(0, self._handle_complete)

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
        self._progress_panel.append_log(f"Fetched: {info.title}", "SUCCESS")

    def _handle_fetch_error(self, message: str) -> None:
        self._fetch_in_progress = False
        self._btn_fetch.configure(state="normal", text="🔍 Fetch Info")
        self._download_panel.set_loading(False)
        self._set_status(f"Error: {message[:80]}", "#EF4444")
        self._progress_panel.append_log(f"Fetch error: {message}", "ERROR")

    def _handle_download_error(self, message: str) -> None:
        self._set_status(f"Download error: {message[:80]}", "#EF4444")
        self._progress_panel.append_log(f"Download error: {message}", "ERROR")
        self._reset_controls()

    def _handle_complete(self) -> None:
        self._set_status("✓  Download complete!", "#10B981")
        self._reset_controls()

        # Save to history
        if self._current_task and self._current_task.video_info:
            info = self._current_task.video_info
            settings.add_to_history({
                "title": info.title,
                "url":   info.url,
                "format": self._current_task.output_format,
                "dir":   self._current_task.output_dir,
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
        self._progress_panel.append_log(
            f"Starting download: {video_info.title if video_info else url}", "INFO"
        )
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
        win.geometry("420x360")
        win.grab_set()

        ctk.CTkLabel(win, text="Settings", font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(16, 8))

        frame = ctk.CTkFrame(win)
        frame.pack(fill="both", expand=True, padx=20, pady=8)

        # Embed metadata
        meta_var = tk.BooleanVar(value=settings.get("embed_metadata"))
        ctk.CTkCheckBox(frame, text="Embed metadata", variable=meta_var).pack(anchor="w", pady=6, padx=12)

        # Embed thumbnail
        thumb_var = tk.BooleanVar(value=settings.get("embed_thumbnail"))
        ctk.CTkCheckBox(frame, text="Embed thumbnail in file", variable=thumb_var).pack(anchor="w", pady=6, padx=12)

        # Concurrent downloads
        ctk.CTkLabel(frame, text="Concurrent downloads:", anchor="w").pack(anchor="w", padx=12, pady=(8, 0))
        conc_var = tk.IntVar(value=settings.get("concurrent_downloads"))
        ctk.CTkSlider(frame, from_=1, to=5, number_of_steps=4, variable=conc_var).pack(fill="x", padx=12)

        def _save():
            settings.set("embed_metadata", meta_var.get())
            settings.set("embed_thumbnail", thumb_var.get())
            settings.set("concurrent_downloads", conc_var.get())
            settings.save()
            win.destroy()

        ctk.CTkButton(win, text="Save", command=_save).pack(pady=12)

    # ---------------------------------------------------------------- #
    #  History dialog                                                   #
    # ---------------------------------------------------------------- #

    def _show_history(self) -> None:
        history = settings.get("download_history") or []

        win = ctk.CTkToplevel(self._root)
        win.title("Download History")
        win.geometry("560x400")
        win.grab_set()

        ctk.CTkLabel(win, text="Download History",
                     font=ctk.CTkFont(size=15, weight="bold")).pack(pady=(12, 4))

        if not history:
            ctk.CTkLabel(win, text="No downloads yet.", text_color="#6B7280").pack(expand=True)
        else:
            scroll = ctk.CTkScrollableFrame(win)
            scroll.pack(fill="both", expand=True, padx=12, pady=8)
            for item in history:
                row = ctk.CTkFrame(scroll, fg_color="#1E293B", corner_radius=6)
                row.pack(fill="x", pady=3)
                ctk.CTkLabel(row, text=item.get("title", "?")[:55],
                             font=ctk.CTkFont(size=12), anchor="w").pack(side="left", padx=10, pady=6)
                ctk.CTkLabel(row, text=item.get("format", "").upper(),
                             font=ctk.CTkFont(size=11), text_color="#9CA3AF").pack(side="right", padx=10)

        def _clear():
            settings.clear_history()
            win.destroy()

        ctk.CTkButton(win, text="Clear History", fg_color="#7F1D1D",
                      hover_color="#991B1B", command=_clear).pack(pady=8)

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

    def _set_status(self, message: str, colour: str = "#9CA3AF") -> None:
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
