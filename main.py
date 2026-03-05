"""
main.py
-------
Application entry point for YT Downloader.

Run with:
    python main.py

Or package with PyInstaller for distribution.
"""

import sys
import os

# Ensure the project root is on PYTHONPATH so "app.*" imports resolve
# regardless of where the user runs the script from.
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


def _check_dependencies() -> None:
    """
    Verify required third-party packages are installed.
    Prints a clear error and exits if any are missing.
    """
    missing = []
    deps = {
        "customtkinter": "customtkinter",
        "yt_dlp":        "yt-dlp",
        "PIL":           "Pillow",
    }
    for module, pip_name in deps.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(pip_name)

    if missing:
        print("=" * 60)
        print("ERROR: Missing required packages.")
        print("Install them with:")
        print(f"  pip install {' '.join(missing)}")
        print("=" * 60)
        sys.exit(1)


def main() -> None:
    _check_dependencies()

    from app.ui.main_window import MainWindow

    app = MainWindow()
    app.run()


if __name__ == "__main__":
    main()
