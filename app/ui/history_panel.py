"""
history_panel.py
----------------
A Toplevel window that shows download history from settings.
"""

from __future__ import annotations
import tkinter as tk
import customtkinter as ctk
from app.utils.settings import settings

CLR = {
    "bg":    "#1a1a2e",
    "panel": "#16213e",
    "card":  "#0f3460",
    "accent":"#e94560",
    "text":  "#eaeaea",
    "sub":   "#8892b0",
    "ok":    "#43d98c",
    "err":   "#ef476f",
}


class HistoryWindow(ctk.CTkToplevel):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.title("Download History")
        self.geometry("760x500")
        self.configure(fg_color=CLR["bg"])
        self.resizable(True, True)
        self._build()
        self.lift()
        self.focus_force()

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        hdr = ctk.CTkFrame(self, fg_color=CLR["panel"], corner_radius=0)
        hdr.grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(hdr, text="Download History",
                     font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=CLR["text"]).pack(side="left", padx=16, pady=12)
        ctk.CTkButton(hdr, text="Clear History", width=120,
                      fg_color=CLR["accent"], hover_color="#c73652",
                      command=self._clear).pack(side="right", padx=16, pady=8)

        scroll = ctk.CTkScrollableFrame(self, fg_color=CLR["bg"], corner_radius=0)
        scroll.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)
        scroll.grid_columnconfigure(0, weight=1)

        history = settings.get("download_history", [])
        if not history:
            ctk.CTkLabel(scroll, text="No downloads yet.",
                         text_color=CLR["sub"],
                         font=ctk.CTkFont(size=13)).pack(pady=40)
            return

        for i, entry in enumerate(history):
            card = ctk.CTkFrame(scroll, fg_color=CLR["card"], corner_radius=8)
            card.grid(row=i, column=0, sticky="ew", padx=12, pady=4)
            card.grid_columnconfigure(0, weight=1)

            status_colour = CLR["ok"] if entry.get("status") == "completed" else CLR["err"]
            ctk.CTkLabel(card, text=entry.get("title", "Unknown"),
                         font=ctk.CTkFont(size=12, weight="bold"),
                         text_color=CLR["text"], anchor="w").grid(
                         row=0, column=0, sticky="ew", padx=10, pady=(8, 2))

            info = f"{entry.get('date','?')}  |  {entry.get('format','?')}  |  {entry.get('resolution','?')}"
            ctk.CTkLabel(card, text=info, font=ctk.CTkFont(size=11),
                         text_color=CLR["sub"], anchor="w").grid(
                         row=1, column=0, sticky="ew", padx=10, pady=(0, 6))

            ctk.CTkLabel(card, text=entry.get("status", "?").upper(),
                         font=ctk.CTkFont(size=10, weight="bold"),
                         text_color=status_colour).grid(
                         row=0, column=1, padx=10, pady=(8, 2))

    def _clear(self) -> None:
        settings.clear_history()
        for w in self.winfo_children():
            w.destroy()
        self._build()
