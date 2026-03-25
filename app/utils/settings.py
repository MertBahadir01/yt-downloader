"""
utils/settings.py
=================
Persistent settings manager using a JSON config file.
"""

import json
import os
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULTS: dict[str, Any] = {
    "download_dir": str(Path.home() / "Downloads"),
    "video_format": "mp4",
    "audio_format": "mp3",
    "resolution": "best",
    "theme": "dark",
    "embed_metadata": True,
    "embed_thumbnail": True,
    "concurrent_downloads": 2,
    "max_retries": 3,
    "retry_delay": 5,
    "auto_update_ytdlp": False,
    "window_width": 1100,
    "window_height": 780,
    "last_urls": [],
    "download_history": [],
}

CONFIG_DIR = Path.home() / ".ytdownloader"
CONFIG_FILE = CONFIG_DIR / "config.json"


class Settings:
    def __init__(self):
        self._data: dict[str, Any] = {}
        self._load()

    def get(self, key: str, fallback: Any = None) -> Any:
        if key in self._data:
            return self._data[key]
        if key in DEFAULTS:
            return DEFAULTS[key]
        return fallback

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def save(self) -> None:
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
        except OSError as exc:
            logger.warning("Could not save settings: %s", exc)

    def reset(self) -> None:
        self._data = dict(DEFAULTS)
        self.save()

    def add_to_history(self, record: dict) -> None:
        history: list = self.get("download_history") or []
        history.insert(0, record)
        self._data["download_history"] = history[:200]
        self.save()

    def clear_history(self) -> None:
        self._data["download_history"] = []
        self.save()

    def _load(self) -> None:
        self._data = dict(DEFAULTS)
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, encoding="utf-8") as f:
                    stored = json.load(f)
                self._data.update(stored)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Could not load settings: %s", exc)


settings = Settings()
