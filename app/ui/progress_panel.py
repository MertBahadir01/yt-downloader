"""
ui/progress_panel.py
=====================
Progress bar, download statistics, and scrolling log console.
"""

from __future__ import annotations

import tkinter as tk
import customtkinter as ctk
from datetime import datetime
from typing import Optional

from app.downloader.yt_downloader import DownloadProgress, DownloadStatus


# Log level colours in the console
LOG_COLOURS = {
    "DEBUG":    "#6B7280",
    "INFO":     "#9CA3AF",
    "WARNING":  "#F59E0B",
    "ERROR":    "#EF4444",
    "CRITICAL": "#DC2626",
    "SUCCESS":  "#10B981",
}


class ProgressPanel(ctk.CTkFrame):
    """
    Bottom section of the main window.
    Shows:
    - Active download stats (speed, eta, size)
    - Progress bar
    - Scrolling log console
    """

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self._build_ui()

    def _build_ui(self):
        # ── Title row ──────────────────────────────────────────────
        title = ctk.CTkLabel(self, text="Download Progress", font=ctk.CTkFont(size=14, weight="bold"))
        title.pack(anchor="w", padx=16, pady=(12, 4))

        # ── Stats strip ────────────────────────────────────────────
        stats_frame = ctk.CTkFrame(self, fg_color="transparent")
        stats_frame.pack(fill="x", padx=16, pady=(0, 6))

        self._lbl_filename = ctk.CTkLabel(stats_frame, text="", font=ctk.CTkFont(size=12),
                                          text_color="#9CA3AF", anchor="w")
        self._lbl_filename.pack(side="left", fill="x", expand=True)

        right = ctk.CTkFrame(stats_frame, fg_color="transparent")
        right.pack(side="right")

        self._lbl_speed = ctk.CTkLabel(right, text="", font=ctk.CTkFont(size=12), text_color="#60A5FA", width=100)
        self._lbl_speed.pack(side="left", padx=6)

        self._lbl_eta = ctk.CTkLabel(right, text="", font=ctk.CTkFont(size=12), text_color="#A78BFA", width=80)
        self._lbl_eta.pack(side="left", padx=6)

        self._lbl_size = ctk.CTkLabel(right, text="", font=ctk.CTkFont(size=12), text_color="#34D399", width=110)
        self._lbl_size.pack(side="left", padx=6)

        # ── Progress bar ───────────────────────────────────────────
        self._progress_bar = ctk.CTkProgressBar(self, height=10, corner_radius=5)
        self._progress_bar.pack(fill="x", padx=16, pady=(0, 4))
        self._progress_bar.set(0)

        self._lbl_percent = ctk.CTkLabel(self, text="0%", font=ctk.CTkFont(size=11), text_color="#9CA3AF")
        self._lbl_percent.pack(anchor="e", padx=20)

        # ── Log console ────────────────────────────────────────────
        log_header = ctk.CTkFrame(self, fg_color="transparent")
        log_header.pack(fill="x", padx=16, pady=(8, 4))
        ctk.CTkLabel(log_header, text="Log Console", font=ctk.CTkFont(size=13, weight="bold")).pack(side="left")
        ctk.CTkButton(log_header, text="Clear", width=60, height=24,
                      font=ctk.CTkFont(size=11), command=self.clear_log,
                      fg_color="#374151", hover_color="#4B5563").pack(side="right")

        # Textbox used as the log console
        self._log_box = ctk.CTkTextbox(
            self,
            height=160,
            font=ctk.CTkFont(family="Courier New", size=11),
            fg_color="#0F172A",
            text_color="#CBD5E1",
            border_width=1,
            border_color="#1E293B",
        )
        self._log_box.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        self._log_box.configure(state="disabled")

        # Tag colours — we manually insert tagged text
        self._log_box._textbox.tag_configure("DEBUG",   foreground=LOG_COLOURS["DEBUG"])
        self._log_box._textbox.tag_configure("INFO",    foreground=LOG_COLOURS["INFO"])
        self._log_box._textbox.tag_configure("WARNING", foreground=LOG_COLOURS["WARNING"])
        self._log_box._textbox.tag_configure("ERROR",   foreground=LOG_COLOURS["ERROR"])
        self._log_box._textbox.tag_configure("SUCCESS", foreground=LOG_COLOURS["SUCCESS"])

    # ---------------------------------------------------------------- #
    #  Public update methods (called from UI thread)                    #
    # ---------------------------------------------------------------- #

    def update_progress(self, prog: DownloadProgress) -> None:
        """Update all progress widgets from a DownloadProgress snapshot."""
        self._progress_bar.set(prog.percent / 100)
        self._lbl_percent.configure(text=f"{prog.percent:.0f}%")
        self._lbl_speed.configure(text=prog.speed or "")
        self._lbl_eta.configure(text=f"ETA: {prog.eta}" if prog.eta else "")

        if prog.total_bytes:
            size_text = f"{prog.downloaded_bytes_human} / {prog.total_bytes_human}"
        else:
            size_text = prog.downloaded_bytes_human or ""
        self._lbl_size.configure(text=size_text)

        if prog.filename:
            # Truncate long filenames
            fn = prog.filename
            if len(fn) > 55:
                fn = "…" + fn[-52:]
            self._lbl_filename.configure(text=fn)

        if prog.status == DownloadStatus.COMPLETED:
            self._progress_bar.set(1.0)
            self._lbl_percent.configure(text="100%")
            self.append_log("Download complete! ✓", "SUCCESS")

        elif prog.status == DownloadStatus.CANCELLED:
            self.append_log("Download cancelled.", "WARNING")

    def reset_progress(self) -> None:
        self._progress_bar.set(0)
        self._lbl_percent.configure(text="0%")
        self._lbl_speed.configure(text="")
        self._lbl_eta.configure(text="")
        self._lbl_size.configure(text="")
        self._lbl_filename.configure(text="")

    def append_log(self, message: str, level: str = "INFO") -> None:
        """Append a coloured line to the log console (must be called from UI thread)."""
        tag = level if level in LOG_COLOURS else "INFO"
        ts  = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {message}\n"

        self._log_box.configure(state="normal")
        self._log_box._textbox.insert("end", line, tag)
        self._log_box._textbox.see("end")
        self._log_box.configure(state="disabled")

    def clear_log(self) -> None:
        self._log_box.configure(state="normal")
        self._log_box.delete("0.0", "end")
        self._log_box.configure(state="disabled")
