"""
ui/download_panel.py
=====================
Middle section: video info display, thumbnail, format selectors.
"""

from __future__ import annotations

import io
import threading
import tkinter as tk
import customtkinter as ctk
from typing import Optional, Callable
from pathlib import Path

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

from app.downloader.format_parser import (
    VideoInfo, RESOLUTION_OPTIONS
)
from app.utils.settings import settings

# Available output formats grouped by type
VIDEO_FORMATS = ["MP4", "WebM"]
AUDIO_FORMATS = ["MP3", "M4A", "Opus", "WAV"]
ALL_FORMATS   = VIDEO_FORMATS + AUDIO_FORMATS


class DownloadPanel(ctk.CTkFrame):
    """
    Shows video metadata and format selection controls.
    Fires on_download_requested(url, format, resolution, output_dir) callback.
    """

    def __init__(self, parent, on_download_requested: Callable, **kwargs):
        super().__init__(parent, **kwargs)
        self._on_download_requested = on_download_requested
        self._video_info: Optional[VideoInfo] = None
        self._thumb_img  = None  # keep reference to prevent GC
        self._build_ui()

    # ---------------------------------------------------------------- #
    #  UI construction                                                  #
    # ---------------------------------------------------------------- #

    def _build_ui(self):
        # ── Two-column layout ──────────────────────────────────────
        left  = ctk.CTkFrame(self, fg_color="transparent")
        right = ctk.CTkFrame(self, fg_color="transparent")
        left.pack(side="left", fill="both", padx=(12, 6), pady=12)
        right.pack(side="left", fill="both", expand=True, padx=(6, 12), pady=12)

        # ── Thumbnail (left column) ────────────────────────────────
        self._thumb_label = ctk.CTkLabel(
            left, text="No thumbnail",
            width=240, height=135,
            fg_color="#1E293B",
            corner_radius=8,
            font=ctk.CTkFont(size=12),
            text_color="#4B5563",
        )
        self._thumb_label.pack(pady=(0, 8))

        # Playlist badge
        self._playlist_badge = ctk.CTkLabel(
            left, text="", fg_color="#7C3AED",
            corner_radius=6, font=ctk.CTkFont(size=11), text_color="white",
            padx=8, pady=2,
        )
        self._playlist_badge.pack()

        # ── Video metadata (right column) ─────────────────────────
        self._lbl_title = ctk.CTkLabel(
            right, text="Paste a URL above to get started",
            font=ctk.CTkFont(size=14, weight="bold"),
            anchor="w", wraplength=520,
        )
        self._lbl_title.pack(anchor="w")

        meta_row = ctk.CTkFrame(right, fg_color="transparent")
        meta_row.pack(anchor="w", pady=(4, 8))

        self._lbl_channel = ctk.CTkLabel(meta_row, text="", font=ctk.CTkFont(size=12),
                                         text_color="#60A5FA")
        self._lbl_channel.pack(side="left", padx=(0, 12))

        self._lbl_duration = ctk.CTkLabel(meta_row, text="", font=ctk.CTkFont(size=12),
                                          text_color="#9CA3AF")
        self._lbl_duration.pack(side="left")

        # ── Format selectors ──────────────────────────────────────
        fmt_frame = ctk.CTkFrame(right, fg_color="#1E293B", corner_radius=8)
        fmt_frame.pack(fill="x", pady=(0, 10))

        # Row 1: Output format
        row1 = ctk.CTkFrame(fmt_frame, fg_color="transparent")
        row1.pack(fill="x", padx=12, pady=(10, 4))
        ctk.CTkLabel(row1, text="Format:", font=ctk.CTkFont(size=12),
                     width=80, anchor="w").pack(side="left")
        self._format_var = tk.StringVar(value=settings.get("video_format", "mp4").upper())
        self._format_menu = ctk.CTkOptionMenu(
            row1, variable=self._format_var,
            values=ALL_FORMATS, width=120, height=28,
            font=ctk.CTkFont(size=12),
            command=self._on_format_changed,
        )
        self._format_menu.pack(side="left", padx=(0, 16))

        # Row 2: Resolution
        row2 = ctk.CTkFrame(fmt_frame, fg_color="transparent")
        row2.pack(fill="x", padx=12, pady=(4, 10))
        ctk.CTkLabel(row2, text="Quality:", font=ctk.CTkFont(size=12),
                     width=80, anchor="w").pack(side="left")
        self._res_var = tk.StringVar(value=settings.get("resolution", "best"))
        self._res_menu = ctk.CTkOptionMenu(
            row2, variable=self._res_var,
            values=RESOLUTION_OPTIONS, width=120, height=28,
            font=ctk.CTkFont(size=12),
        )
        self._res_menu.pack(side="left")
        self._update_resolution_options()

        # ── Output folder ─────────────────────────────────────────
        folder_frame = ctk.CTkFrame(right, fg_color="transparent")
        folder_frame.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(folder_frame, text="Save to:", font=ctk.CTkFont(size=12),
                     width=65, anchor="w").pack(side="left")
        self._folder_var = tk.StringVar(value=settings.get("download_dir"))
        self._folder_entry = ctk.CTkEntry(folder_frame, textvariable=self._folder_var,
                                          font=ctk.CTkFont(size=11), height=28)
        self._folder_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ctk.CTkButton(folder_frame, text="Browse", width=70, height=28,
                      font=ctk.CTkFont(size=11),
                      command=self._browse_folder).pack(side="left")

        # ── Estimated size ────────────────────────────────────────
        self._lbl_est_size = ctk.CTkLabel(right, text="", font=ctk.CTkFont(size=11),
                                          text_color="#9CA3AF", anchor="w")
        self._lbl_est_size.pack(anchor="w")

        # ── Playlist selector (hidden until playlist loaded) ──────
        self._playlist_frame = ctk.CTkFrame(right, fg_color="#1E293B", corner_radius=8)
        self._playlist_listbox_var: list[tk.BooleanVar] = []

        # ── Download button ───────────────────────────────────────
        self._btn_download = ctk.CTkButton(
            right,
            text="⬇  Download",
            font=ctk.CTkFont(size=13, weight="bold"),
            height=38,
            fg_color="#059669",
            hover_color="#047857",
            command=self._request_download,
        )
        self._btn_download.pack(fill="x", pady=(6, 0))
        self._btn_download.configure(state="disabled")

    # ---------------------------------------------------------------- #
    #  Public methods                                                   #
    # ---------------------------------------------------------------- #

    def set_video_info(self, info: VideoInfo) -> None:
        """Populate the panel with fetched video info."""
        self._video_info = info

        # Title / channel / duration
        self._lbl_title.configure(text=info.title)
        self._lbl_channel.configure(text=f"📺  {info.channel}")
        dur = info.duration_human if info.duration else ""
        self._lbl_duration.configure(text=f"⏱  {dur}" if dur else "")

        # Playlist badge
        if info.is_playlist:
            self._playlist_badge.configure(text=f"Playlist  ·  {info.playlist_count} videos")
            self._show_playlist_selector(info)
        else:
            self._playlist_badge.configure(text="")
            self._playlist_frame.pack_forget()

        # Estimated size from best available format
        self._update_size_estimate()
        self._btn_download.configure(state="normal")

        # Load thumbnail in background
        if info.thumbnail_url:
            threading.Thread(
                target=self._load_thumbnail,
                args=(info.thumbnail_url,),
                daemon=True,
            ).start()

    def clear(self) -> None:
        self._video_info = None
        self._lbl_title.configure(text="Paste a URL above to get started")
        self._lbl_channel.configure(text="")
        self._lbl_duration.configure(text="")
        self._lbl_est_size.configure(text="")
        self._playlist_badge.configure(text="")
        self._playlist_frame.pack_forget()
        self._thumb_label.configure(image=None, text="No thumbnail")
        self._thumb_img = None
        self._btn_download.configure(state="disabled")

    def set_loading(self, loading: bool) -> None:
        state = "disabled" if loading else "normal"
        self._btn_download.configure(state=state)

    # ---------------------------------------------------------------- #
    #  Internal helpers                                                 #
    # ---------------------------------------------------------------- #

    def _on_format_changed(self, _value: str) -> None:
        self._update_resolution_options()
        self._update_size_estimate()

    def _update_resolution_options(self) -> None:
        fmt = self._format_var.get().lower()
        if fmt in ("mp3", "m4a", "opus", "wav"):
            # Audio-only: no resolution choice
            self._res_menu.configure(values=["best"])
            self._res_var.set("best")
            self._res_menu.configure(state="disabled")
        else:
            self._res_menu.configure(values=RESOLUTION_OPTIONS, state="normal")

    def _update_size_estimate(self) -> None:
        if not self._video_info or self._video_info.is_playlist:
            self._lbl_est_size.configure(text="")
            return
        fmt = self._format_var.get().lower()
        res = self._res_var.get()
        # Find best matching format
        audio_only = fmt in ("mp3", "m4a", "opus", "wav")
        candidates = self._video_info.audio_formats if audio_only else self._video_info.video_formats
        if not candidates:
            self._lbl_est_size.configure(text="")
            return
        # Try to find a matching resolution
        size = None
        for f in candidates:
            if not audio_only and res != "best" and f.resolution != res:
                continue
            if f.filesize:
                size = f.filesize
                break
        if size is None and candidates:
            size = candidates[0].filesize
        if size:
            from app.downloader.yt_downloader import _human_bytes
            self._lbl_est_size.configure(text=f"Estimated size: {_human_bytes(size)}")
        else:
            self._lbl_est_size.configure(text="")

    def _browse_folder(self) -> None:
        from tkinter import filedialog
        folder = filedialog.askdirectory(initialdir=self._folder_var.get())
        if folder:
            self._folder_var.set(folder)
            settings.set("download_dir", folder)
            settings.save()

    def _request_download(self) -> None:
        if not self._video_info:
            return
        fmt    = self._format_var.get().lower()
        res    = self._res_var.get()
        folder = self._folder_var.get()

        if not folder:
            from tkinter import messagebox
            messagebox.showwarning("No folder", "Please choose a download folder.")
            return

        # Persist last-used settings
        settings.set("download_dir", folder)
        settings.set("video_format" if fmt in ("mp4", "webm") else "audio_format", fmt)
        settings.set("resolution", res)
        settings.save()

        self._on_download_requested(
            self._video_info.url,
            fmt,
            res,
            folder,
            self._video_info,
        )

    def _show_playlist_selector(self, info: VideoInfo) -> None:
        """Display a checklist of playlist entries."""
        # Clear old widgets
        for w in self._playlist_frame.winfo_children():
            w.destroy()
        self._playlist_listbox_var.clear()

        ctk.CTkLabel(
            self._playlist_frame,
            text=f"Playlist: {info.playlist_title} ({info.playlist_count} videos)",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(anchor="w", padx=10, pady=(8, 4))

        scroll = ctk.CTkScrollableFrame(self._playlist_frame, height=120)
        scroll.pack(fill="x", padx=10, pady=(0, 8))

        for i, entry in enumerate(info.playlist_entries[:50]):
            var = tk.BooleanVar(value=True)
            self._playlist_listbox_var.append(var)
            cb = ctk.CTkCheckBox(
                scroll,
                text=f"{i+1}. {entry.title[:60]}",
                variable=var,
                font=ctk.CTkFont(size=11),
                height=22,
            )
            cb.pack(anchor="w", pady=1)

        self._playlist_frame.pack(fill="x", pady=(0, 8))

    def _load_thumbnail(self, url: str) -> None:
        """Download and display thumbnail image (runs in background thread)."""
        if not PIL_AVAILABLE or not REQUESTS_AVAILABLE:
            return
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            img  = Image.open(io.BytesIO(resp.content))
            img  = img.resize((240, 135), Image.LANCZOS)
            photo = ctk.CTkImage(light_image=img, dark_image=img, size=(240, 135))
            # Schedule UI update on main thread
            self._thumb_label.after(0, lambda: self._set_thumbnail(photo))
        except Exception:
            pass  # thumbnail failure is non-critical

    def _set_thumbnail(self, photo) -> None:
        self._thumb_img = photo
        self._thumb_label.configure(image=photo, text="")
