# YT Downloader 🎬

A modern, full-featured YouTube downloader with a dark-mode GUI.

## Features

- ✅ Download videos (MP4, WebM) and audio (MP3, M4A, Opus, WAV)
- ✅ Resolution picker: 144p → 4K + "Best available"
- ✅ Playlist support with per-video selection
- ✅ Real-time progress bar, speed, ETA
- ✅ Pause / Resume / Cancel controls
- ✅ Thumbnail preview
- ✅ Drag-and-drop URL input
- ✅ Download history
- ✅ File size estimation before download
- ✅ FFmpeg post-processing (merge streams, embed metadata/thumbnail)
- ✅ Dark/Light mode toggle
- ✅ Persistent settings (config saved to `~/.ytdownloader/config.json`)
- ✅ Thread-safe — UI never freezes

## Requirements

- Python 3.11+
- FFmpeg (must be in PATH)

## Installation

```bash
# 1. Install Python dependencies
pip install -r requirements.txt

# 2. Install FFmpeg
#    macOS:   brew install ffmpeg
#    Ubuntu:  sudo apt install ffmpeg
#    Windows: https://ffmpeg.org/download.html  (add to PATH)

# 3. Run the app
python main.py
```

## Project Structure

```
ytdownloader/
├── main.py                     # Entry point
├── requirements.txt
├── app/
│   ├── ui/
│   │   ├── main_window.py      # Root window + controller
│   │   ├── download_panel.py   # Video info + format selectors
│   │   └── progress_panel.py   # Progress bar + log console
│   ├── downloader/
│   │   ├── yt_downloader.py    # yt-dlp engine (isolated)
│   │   └── format_parser.py    # Format parsing + selectors
│   └── utils/
│       ├── settings.py         # JSON config manager
│       └── logger.py           # Logging + UI log bridge
```

## Updating yt-dlp

Only `app/downloader/yt_downloader.py` imports yt-dlp.
To update: `pip install -U yt-dlp`

## Configuration

Settings are saved to `~/.ytdownloader/config.json` and include:
- Default download directory
- Last-used format/resolution
- Embed metadata/thumbnail toggles
- Window size

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| Enter (in URL box) | Fetch video info |
| Ctrl+V (in URL box) | Paste URL |

## Troubleshooting

**"ffmpeg not found"**: Install FFmpeg and ensure it's in your system PATH.

**Age-restricted videos**: Use `--cookies-from-browser` option (advanced; see yt-dlp docs).

**Slow fetching**: Normal for playlists with many entries. First fetch resolves all metadata.
