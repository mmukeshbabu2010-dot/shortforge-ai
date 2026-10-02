from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, parse_qs

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests
import yt_dlp
from faster_whisper import WhisperModel

HOST = "127.0.0.1"
PORT = int(os.getenv("SHORTFORGE_LOCAL_PORT", "8765"))
API_URL = os.getenv("SHORTFORGE_API_URL", "https://shortforge-ai-api.onrender.com").rstrip("/")
MAX_BODY = 5 * 1024 * 1024 * 1024
MAX_COOKIES = 2_000_000

_model: WhisperModel | None = None


def cors_headers(handler: BaseHTTPRequestHandler) -> None:
    origin = handler.headers.get("Origin", "")
    if (
        origin in {
            "https://vruntime-labs.github.io",
            "http://localhost",
            "http://127.0.0.1",
        }
        or origin.startswith("http://localhost:")
        or origin.startswith("http://127.0.0.1:")
    ):
        handler.send_header("Access-Control-Allow-Origin", origin)
        handler.send_header("Vary", "Origin")


def send_json(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    cors_headers(handler)
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type, X-File-Name")
    handler.send_header("Access-Control-Allow-Private-Network", "true")
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def transcribe_local(path: Path) -> tuple[list[dict], str]:
    global _model
    if _model is None:
        print("[ShortForge Local] Loading Whisper base model on this PC...")
        _model = WhisperModel("base", device="cpu", compute_type="int8")

    print(f"[ShortForge Local] Transcribing {path.name}...")
    segments, info = _model.transcribe(
        str(path),
        vad_filter=True,
        word_timestamps=False,
        beam_size=5,
    )

    items: list[dict] = []
    for segment in segments:
        text = segment.text.strip()
        if text:
            items.append(
                {
                    "start": float(segment.start),
                    "end": float(segment.end),
                    "text": text,
                }
            )

    language = getattr(info, "language", "unknown") or "unknown"
    print(f"[ShortForge Local] Transcription complete: {len(items)} segments, language={language}")
    return items, language


def download_youtube(url: str, folder: Path, cookie_text: str) -> tuple[Path, str]:
    cookie_path = None
    if cookie_text:
        raw = cookie_text.encode("utf-8")
        if len(raw) > MAX_COOKIES:
            raise RuntimeError("The cookies.txt file is too large. Keep it under 2 MB.")
        lines = cookie_text.splitlines()
        first_line = lines[0].strip() if lines else ""
        if first_line not in {"# HTTP Cookie File", "# Netscape HTTP Cookie File"}:
            raise RuntimeError("Invalid cookies.txt. Use a Netscape-format YouTube cookies file.")
        cookie_path = folder / "youtube-cookies.txt"
        cookie_path.write_bytes(raw)

    template = str(folder / "source.%(ext)s")
    last_error = None

    try:
        for player_clients in (["android"], None):
            for existing in folder.glob("source.*"):
                if existing.is_file():
                    try:
                        existing.unlink()
                    except OSError:
                        pass

            options = {
                "format": "bv*+ba/b",
                "merge_output_format": "mp4",
                "outtmpl": template,
                "noplaylist": True,
                "quiet": True,
                "no_warnings": True,
                "retries": 3,
                "fragment_retries": 3,
                "socket_timeout": 30,
            }
            if cookie_path:
                options["cookiefile"] = str(cookie_path)
            if player_clients:
                options["extractor_args"] = {"youtube": {"player_client": player_clients}}

            try:
                with yt_dlp.YoutubeDL(options) as ydl:
                    info = ydl.extract_info(url, download=True)
                title = info.get("title") or "YouTube video"
                media = next(
                    (
                        p
                        for p in sorted(folder.glob("source.*"))
                        if p.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}
                    ),
                    None,
                )
                if media:
                    return media, title
            except Exception as exc:
                last_error = exc
    finally:
        if cookie_path and cookie_path.exists():
            try:
                cookie_path.unlink()
            except OSError:
                pass

    message = str(last_error) if last_error else "Unknown YouTube download error."
    if "Sign in to confirm" in message or "not a bot" in message:
        if cookie_text:
            raise RuntimeError(
                "YouTube still rejected the provided cookies. Export a fresh youtube.com cookies.txt file and try again."
            )
        raise RuntimeError(
            "YouTube blocked the local download. Try a fresh cookies.txt file or another video."
        )
    raise RuntimeError(f"Could not download the YouTube video: {message}")


def upload_to_shortforge(
    video_path: Path,
    count: int,
    segments: list[dict],
    language: str,
    title: str = "",
) -> dict:
    print("[ShortForge Local] Sending video + local transcription to ShortForge...")
    with video_path.open("rb") as video:
        response = requests.post(
            f"{API_URL}/api/analyze",
            files={"video": (video_path.name, video, "video/mp4")},
            data={
                "count": str(max(1, min(int(count), 8))),
                "duration": "45",
                "segments_json": json.dumps(segments, separators=(",", ":")),
                "language": language,
                "source_title": title,
            },
            timeout=(30, 3600),
        )

    try:
        payload = response.json()
    except ValueError:
        payload = {"error": f"ShortForge API returned HTTP {response.status_code}."}

    if response.status_code >= 400 or payload.get("error"):
        raise RuntimeError(payload.get("error") or f"ShortForge API returned HTTP {response.status_code}.")
    return payload


def save_raw_upload(handler: BaseHTTPRequestHandler) -> Path:
    try:
        length = int(handler.headers.get("Content-Length", "0"))
    except ValueError:
        length = 0

    if length > MAX_BODY:
        raise RuntimeError("The selected video is larger than the 5 GB limit.")

    filename = handler.headers.get("X-File-Name", "uploaded-video.mp4")
    filename = Path(filename).name or "uploaded-video.mp4"
    suffix = Path(filename).suffix.lower() or ".mp4"

    temp = tempfile.NamedTemporaryFile(
        prefix=f"shortforge-upload-{uuid.uuid4().hex[:8]}-",
        suffix=suffix,
        delete=False,
    )
    path = Path(temp.name)

    remaining = length
    total = 0
    try:
        while True:
            if remaining:
                chunk = handler.rfile.read(min(1024 * 1024, remaining))
            else:
                chunk = handler.rfile.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_BODY:
                raise RuntimeError("The selected video is larger than the 5 GB limit.")
            temp.write(chunk)
            if remaining:
                remaining -= len(chunk)
                if remaining <= 0:
                    break
        temp.close()
        return path
    except Exception:
        temp.close()
        path.unlink(missing_ok=True)
        raise


class Handler(BaseHTTPRequestHandler):
    server_version = "ShortForgeLocalBridge/0.2"

    def do_OPTIONS(self):
        self.send_response(204)
        cors_headers(self)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-File-Name")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            send_json(
                self,
                200,
                {
                    "status": "ok",
                    "service": "shortforge-local-bridge",
                    "version": "0.2.0",
                    "capabilities": ["youtube-download", "local-upload", "local-transcription"],
                },
            )
            return
        send_json(self, 404, {"error": "Not found."})

    def do_POST(self):
        route = urlparse(self.path)
        if route.path == "/analyze-file":
            path = None
            try:
                count = int(parse_qs(route.query).get("count", ["5"])[0])
                path = save_raw_upload(self)
                segments, language = transcribe_local(path)
                result = upload_to_shortforge(path, count, segments, language, Path(path).stem)
                send_json(self, 200, result)
            except Exception as exc:
                send_json(self, 400, {"error": str(exc)})
            finally:
                if path:
                    path.unlink(missing_ok=True)
            return

        if route.path != "/analyze":
            send_json(self, 404, {"error": "Not found."})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 2_500_000:
                raise RuntimeError("Request is too large or missing.")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            url = str(payload.get("url", "")).strip()
            cookies = str(payload.get("cookies", ""))
            count = int(payload.get("count", 5))

            host = (urlparse(url).hostname or "").lower()
            if host not in {
                "youtube.com",
                "www.youtube.com",
                "m.youtube.com",
                "youtu.be",
                "www.youtu.be",
            }:
                raise RuntimeError("The local bridge accepts YouTube URLs only.")

            with tempfile.TemporaryDirectory(prefix=f"shortforge-{uuid.uuid4().hex[:8]}-") as temp:
                folder = Path(temp)
                video_path, title = download_youtube(url, folder, cookies)
                segments, language = transcribe_local(video_path)
                result = upload_to_shortforge(video_path, count, segments, language, title)
                send_json(self, 200, result)
        except Exception as exc:
            send_json(self, 400, {"error": str(exc)})

    def log_message(self, format, *args):
        print(f"[ShortForge Local] {self.address_string()} - {format % args}")


if __name__ == "__main__":
    print(f"ShortForge Local AI Bridge listening on http://{HOST}:{PORT}")
    print(f"ShortForge API: {API_URL}")
    print("Keep this window open while using ShortForge.")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
