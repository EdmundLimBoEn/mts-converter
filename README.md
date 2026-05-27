# MTS → MP4 Converter (H.265)

A macOS desktop app for converting `.MTS` video files from JVC camcorders (specifically the **JVC GZ-E600-N**) into modern `.mp4` files encoded in H.265/HEVC.

## Why this exists

The JVC GZ-E600-N records in **AVCHD** — a professional broadcast format that stores footage as `.MTS` files buried inside a `PRIVATE/AVCHD/BDMV/STREAM/` folder structure on the SD card. This format is:

- Not natively supported by most modern video editors or streaming platforms
- Stored in a folder that macOS treats as an opaque package (invisible in Finder)
- Encoded in H.264, which is larger than necessary for archival

This app converts those files into `.mp4` (H.265/HEVC), which is universally compatible with iPhones, Apple TV, YouTube, iMovie, Final Cut Pro, and virtually every modern device — at roughly 30% of the original file size with no visible quality loss.

## Requirements

- **macOS** (tested on macOS 15 Sequoia)
- **ffmpeg** with libx265 support: `brew install ffmpeg`
- **Homebrew Python 3.13** with Tk: `brew install python@3.13 python-tk@3.13`

## Installation

### Option 1 — Build the `.app` yourself

```bash
git clone https://github.com/limboenedmund/mts-converter.git
cd mts-converter
python3.13 -m venv .venv
.venv/bin/pip install pyinstaller
.venv/bin/pyinstaller --windowed --name "MTS Converter" --clean --collect-all tkinter converter.py
xattr -cr "dist/MTS Converter.app"
codesign --force --deep --sign - "dist/MTS Converter.app"
cp -R "dist/MTS Converter.app" /Applications/
```

### Option 2 — Run directly

```bash
/opt/homebrew/opt/python@3.13/bin/python3.13 converter.py
```

## Usage

1. Insert the JVC camera SD card — it mounts as `JVCCAM_SD`
2. Launch **MTS Converter** from Spotlight (`⌘Space` → "MTS")
3. Click **Detect Camera** — the app finds all `.MTS` files automatically
4. Choose a quality preset (Balanced is recommended)
5. Click **Convert**

Converted files are saved to `~/Movies/Converted/` by default.

## Quality presets

| Preset | Codec | File size vs original |
|--------|-------|-----------------------|
| Stream Copy | H.264 (no re-encode) | ~100% — zero quality loss |
| Fast | H.265 CRF 28 | ~30% |
| **Balanced** | H.265 CRF 23 | ~30% (recommended) |
| High Quality | H.265 CRF 20 | ~40% |
| Archival | H.265 CRF 18 | ~50% |
| Lossless H.265 | H.265 lossless | >100% — mathematically lossless |

> **On "smaller = worse quality":** H.265 is simply a more efficient compression algorithm than H.264. At CRF 23 the output is visually indistinguishable from the original. The file is smaller because H.265 is smarter, not because data was thrown away. Use **Stream Copy** if you want a guarantee of zero re-encoding.

## Keyboard shortcut

The app can be triggered from anywhere with `⇧⌃⌥⌘M` via an Automator Quick Action. After installing:

1. Open **System Settings → Keyboard → Keyboard Shortcuts → Services**
2. Find **"Launch MTS Converter"** under General
3. Confirm the shortcut `⇧⌃⌥⌘M` is checked
