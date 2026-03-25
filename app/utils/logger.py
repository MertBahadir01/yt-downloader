"""
utils/logger.py
===============
Centralised logging setup.
UI panels can register a callback to receive log lines for display.
"""

import logging
import sys
from typing import Callable

_ui_callbacks: list[Callable[[str, str], None]] = []


class UILogHandler(logging.Handler):
    """Forwards log records to registered UI callback functions."""

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        level = record.levelname
        for cb in _ui_callbacks:
            try:
                cb(msg, level)
            except Exception:
                pass


def register_ui_callback(cb: Callable[[str, str], None]) -> None:
    """Register a function(message, level) to receive log output."""
    _ui_callbacks.append(cb)


def unregister_ui_callback(cb: Callable[[str, str], None]) -> None:
    if cb in _ui_callbacks:
        _ui_callbacks.remove(cb)


def setup_logging(level: int = logging.WARNING) -> None:
    """Configure root logger — suppress noisy DEBUG output from third-party libs."""
    root = logging.getLogger()
    # Root at WARNING so PIL, tkinterdnd2, yt-dlp internals etc. stay silent.
    root.setLevel(logging.WARNING)

    if not root.handlers:
        fmt = logging.Formatter(
            "[%(asctime)s] %(levelname)-8s %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(fmt)
        ch.setLevel(logging.WARNING)
        root.addHandler(ch)

    # Our own app logger stays at INFO so deliberate app messages come through.
    logging.getLogger("app").setLevel(logging.INFO)

    # UI handler receives only INFO+ from app.* — not third-party debug spam.
    ui_handler = UILogHandler()
    ui_handler.setLevel(logging.INFO)
    ui_handler.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", datefmt="%H:%M:%S"))
    root.addHandler(ui_handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
