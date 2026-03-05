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


def setup_logging(level: int = logging.DEBUG) -> None:
    """Configure root logger with console + UI handlers."""
    root = logging.getLogger()
    root.setLevel(level)

    if not root.handlers:
        fmt = logging.Formatter(
            "[%(asctime)s] %(levelname)-8s %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
        # Console handler
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(fmt)
        ch.setLevel(logging.DEBUG)
        root.addHandler(ch)

    # UI handler (always added fresh)
    ui_handler = UILogHandler()
    ui_handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s", datefmt="%H:%M:%S"))
    root.addHandler(ui_handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
