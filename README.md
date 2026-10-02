# ShortForge AI

**Turn Long Videos into Shorts — Automatically.**

ShortForge AI is a free, open-source video repurposing studio. Give it a long video or a YouTube URL and it can transcribe the speech locally, detect hook-worthy moments, generate vertical Shorts, and optionally burn in subtitles or add your own B-roll.

## What it does

- 🎬 Long-form video → vertical Shorts
- 🪝 Automatic hook detection using transcript signals and content heuristics
- ✂️ Select and batch-generate multiple Shorts
- 💬 Optional free subtitles generated locally with Whisper
- 🎥 A-roll by default, optional user-provided B-roll
- 📱 9:16, 1:1 and 16:9 output formats
- ▶️ Preview generated clips before downloading
- 🔓 Open source and designed for local/self-hosted use

## Requirements

- Python 3.11+
- FFmpeg + ffprobe available in PATH
- A machine with enough CPU/RAM for local Whisper processing

YouTube importing uses yt-dlp, an open-source video downloader installed from Python dependencies.

## Windows

Run `run.bat`, then open `http://127.0.0.1:8000`.

Use only videos you are authorized to download and process.

## Roadmap

- Smarter semantic hook scoring
- Face/speaker-aware auto framing
- Caption word highlighting and styling
- Timeline editor
- Free/open B-roll source integrations
- Project history and saved presets
- GPU acceleration
