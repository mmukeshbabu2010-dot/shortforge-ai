from __future__ import annotations

import json
import os
import tempfile
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import requests
import yt_dlp

HOST = "127.0.0.1"
PORT = int(os.getenv("SHORTFORGE_LOCAL_PORT", "8765"))
API_URL = os.getenv("SHORTFORGE_API_URL", "https://shortforge-ai-api.onrender.com").rstrip("/")
MAX_BODY = 2_500_000
MAX_COOKIE_BYTES = 2_000_000


def cors_headers(handler: BaseHTTPRequestHandler) -> None:
    origin = handler.headers.get("Origin", "")
    if origin in {"https://vruntime-labs.github.io", "http://localhost", "http://127.0.0.1"} or origin.startswith("http://localhost:") or origin.startswith("http://127.0.0.1:"):
        handler.send_header("Access-Control-Allow-Origin", origin)
        handler.send_header("Vary", "Origin")


def send_json(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    cors_headers(handler)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def download_youtube(url: str, folder: Path, cookie_text: str) -> tuple[Path, str]:
    cookie_path = None
    if cookie_text:
        raw = cookie_text.encode("utf-8")
        if len(raw) > MAX_COOKIE_BYTES:
            raise RuntimeError("The cookies.txt file is too large. Keep it under 2 MB.")
        first_line = cookie_text.splitlines()[0].strip() if cookie_text.splitlines() else ""
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
                media = next((p for p in folder.glob("source.*") if p.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}), None)
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
            raise RuntimeError("YouTube rejected the local download even with the supplied cookies. Refresh/export a fresh youtube.com cookies.txt and try again.")
        raise RuntimeError("YouTube rejected the local downloader. Try a fresh cookies.txt file, or use Upload Video.")
    raise RuntimeError(f"Could not download the YouTube video: {message}")


def upload_to_shortforge(video_path: Path, count: int) -> dict:
    with video_path.open("rb") as video:
        response = requests.post(
            f"{API_URL}/api/analyze",
            files={"video": (video_path.name, video, "video/mp4")},
            data={"count": str(max(1, min(int(count), 8))), "duration": "45"},
            timeout=(30, 3600),
        )
    try:
        payload = response.json()
    except ValueError:
        payload = {"error": f"ShortForge API returned HTTP {response.status_code}."}
    if response.status_code >= 400 or payload.get("error"):
        raise RuntimeError(payload.get("error") or f"ShortForge API returned HTTP {response.status_code}.")
    return payload


class Handler(BaseHTTPRequestHandler):
    server_version = "ShortForgeLocalBridge/0.1"

    def do_OPTIONS(self):
        self.send_response(204)
        cors_headers(self)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            send_json(self, 200, {"status": "ok", "service": "shortforge-local-bridge", "version": "0.1.0"})
            return
        send_json(self, 404, {"error": "Not found."})

    def do_POST(self):
        if self.path != "/analyze":
            send_json(self, 404, {"error": "Not found."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY:
            send_json(self, 413, {"error": "Request is too large."})
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            url = str(payload.get("url", "")).strip()
            cookies = str(payload.get("cookies", ""))
            count = int(payload.get("count", 5))
            if not url:
                raise RuntimeError("Paste a YouTube URL first.")
            with tempfile.TemporaryDirectory(prefix=f"shortforge-{uuid.uuid4().hex[:8]}-") as temp:
                video_path, _ = download_youtube(url, Path(temp), cookies)
                result = upload_to_shortforge(video_path, count)
            send_json(self, 200, result)
        except Exception as exc:
            send_json(self, 400, {"error": str(exc)})

    def log_message(self, format, *args):
        print(f"[ShortForge Local] {self.address_string()} - {format % args}")


if __name__ == "__main__":
    print(f"ShortForge Local YouTube Bridge listening on http://{HOST}:{PORT}")
    print(f"Cloud analysis API: {API_URL}")
    print("Keep this window open while using the YouTube URL mode.")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
