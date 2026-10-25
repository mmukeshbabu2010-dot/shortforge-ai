from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import time
import uuid
from collections import defaultdict, deque
from contextlib import suppress
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .processor import (
    choose_windows,
    create_job,
    download_youtube,
    extract_thumbnail,
    probe_duration,
    transcribe,
)

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
UPLOADS = DATA / "uploads"
OUTPUTS = DATA / "outputs"
PREVIEWS = DATA / "previews"
WEB = ROOT / "web"

MAX_VIDEO_BYTES = 500 * 1024 * 1024
MAX_BROLL_BYTES = 100 * 1024 * 1024
MAX_COOKIE_BYTES = 2 * 1024 * 1024
JOB_RETENTION_SECONDS = 24 * 60 * 60
CLEANUP_INTERVAL_SECONDS = 15 * 60
VIDEO_SUFFIXES = {".mp4", ".mkv", ".webm", ".mov"}
JOB_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
THUMBNAIL_PATTERN = re.compile(r"^hook-\d+\.jpg$")
OUTPUT_PATTERN = re.compile(r"^short_\d{2}\.mp4$")
logger = logging.getLogger(__name__)

for folder in (UPLOADS, OUTPUTS, PREVIEWS):
    folder.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="ShortForge AI", version="0.4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://vruntime-labs.github.io",
        "http://localhost",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)

# Only the public frontend is mounted statically. User uploads, analysis JSON,
# thumbnails, and generated clips are never exposed through a directory mount.
app.mount("/static", StaticFiles(directory=WEB), name="static")


class RequestBodySizeLimitMiddleware:
    """Reject oversized request bodies while they are being received, including chunked requests."""

    def __init__(self, app, max_analyze_bytes: int, max_generate_bytes: int):
        self.app = app
        self.limits = {
            "/api/analyze": max_analyze_bytes,
            "/api/generate": max_generate_bytes,
        }

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or scope.get("method") != "POST":
            await self.app(scope, receive, send)
            return
        limit = self.limits.get(scope.get("path", ""))
        if not limit:
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        raw_length = headers.get(b"content-length")
        if raw_length:
            try:
                if int(raw_length) > limit:
                    await self._reject(scope, send)
                    return
            except ValueError:
                await self._reject(scope, send, 400, "Invalid Content-Length header.")
                return

        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise HTTPException(status_code=413, detail="Request body exceeds the upload size limit.")
            return message

        await self.app(scope, limited_receive, send)

    async def _reject(self, scope, send, status_code: int = 413, detail: str = "Upload request is too large."):
        body = json.dumps({"error": detail}).encode("utf-8")
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode("ascii")),
            (b"cache-control", b"no-store"),
        ]
        origin = dict(scope.get("headers", [])).get(b"origin", b"").decode("latin1")
        if origin in {"https://vruntime-labs.github.io", "http://localhost", "http://localhost:8000", "http://127.0.0.1:8000"}:
            headers.extend([(b"access-control-allow-origin", origin.encode("latin1")), (b"vary", b"Origin")])
        await send({"type": "http.response.start", "status": status_code, "headers": headers})
        await send({"type": "http.response.body", "body": body})


app.add_middleware(
    RequestBodySizeLimitMiddleware,
    max_analyze_bytes=MAX_VIDEO_BYTES + MAX_COOKIE_BYTES + 12 * 1024 * 1024,
    max_generate_bytes=MAX_BROLL_BYTES + 12 * 1024 * 1024,
)

RATE_WINDOW_SECONDS = 10 * 60
RATE_LIMITS = {"/api/analyze": 12, "/api/generate": 20}
_rate_buckets: dict[tuple[str, str], deque[float]] = defaultdict(deque)
_active_job_requests = 0


def is_allowed_youtube_url(value: str) -> bool:
    try:
        parsed = urlparse(value.strip())
        host = (parsed.hostname or "").lower().rstrip(".")
        return (
            parsed.scheme == "https"
            and parsed.username is None
            and parsed.password is None
            and parsed.port in (None, 443)
            and host in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be", "www.youtube-nocookie.com"}
        )
    except ValueError:
        return False


@app.middleware("http")
async def protect_expensive_endpoints(request: Request, call_next):
    global _active_job_requests
    path = request.url.path
    if request.method != "POST" or path not in RATE_LIMITS:
        return await call_next(request)

    client_ip = request.client.host if request.client else "unknown"
    origin = request.headers.get("origin", "")
    cors_headers = {"Access-Control-Allow-Origin": origin, "Vary": "Origin"} if origin in {"https://vruntime-labs.github.io", "http://localhost", "http://localhost:8000", "http://127.0.0.1:8000"} else {}
    now = time.monotonic()
    bucket = _rate_buckets[(path, client_ip)]
    while bucket and now - bucket[0] >= RATE_WINDOW_SECONDS:
        bucket.popleft()
    if len(bucket) >= RATE_LIMITS[path]:
        retry_after = max(1, int(RATE_WINDOW_SECONDS - (now - bucket[0])))
        return JSONResponse(
            status_code=429,
            content={"error": "Too many processing requests. Please wait and try again."},
            headers={"Retry-After": str(retry_after), "Cache-Control": "no-store", **cors_headers},
        )
    if _active_job_requests >= 2:
        return JSONResponse(
            status_code=503,
            content={"error": "The processing service is busy. Please retry shortly."},
            headers={"Retry-After": "20", "Cache-Control": "no-store", **cors_headers},
        )

    bucket.append(now)
    _active_job_requests += 1
    try:
        return await call_next(request)
    finally:
        _active_job_requests -= 1

    if request.method == "POST" and request.url.path in {"/api/analyze", "/api/generate"}:
        raw_length = request.headers.get("content-length")
        if raw_length:
            try:
                if int(raw_length) > MAX_VIDEO_BYTES + MAX_BROLL_BYTES + 12 * 1024 * 1024:
                    return JSONResponse(
                        status_code=413,
                        content={"error": "Upload is too large. Video limit: 500 MB; B-roll limit: 100 MB."},
                    )
            except ValueError:
                return JSONResponse(status_code=400, content={"error": "Invalid Content-Length header."})
    return await call_next(request)


def cleanup_expired_jobs() -> None:
    cutoff = __import__("time").time() - JOB_RETENTION_SECONDS
    # Treat the analysis folder as the job's canonical creation/retention point
    # so generated output cannot outlive its source job by another full day.
    for job_dir in PREVIEWS.iterdir():
        if not job_dir.is_dir():
            continue
        try:
            if job_dir.stat().st_mtime < cutoff:
                job_id = job_dir.name
                shutil.rmtree(job_dir, ignore_errors=True)
                shutil.rmtree(OUTPUTS / job_id, ignore_errors=True)
        except OSError:
            logger.warning("Could not inspect an expired ShortForge job directory.")

    # Remove stale output directories left behind if an analysis folder was
    # manually removed or a prior cleanup was interrupted.
    for output_dir in OUTPUTS.iterdir():
        if not output_dir.is_dir() or (PREVIEWS / output_dir.name).exists():
            continue
        try:
            if output_dir.stat().st_mtime < cutoff:
                shutil.rmtree(output_dir, ignore_errors=True)
        except OSError:
            logger.warning("Could not inspect an orphaned ShortForge output directory.")


async def cleanup_loop() -> None:
    while True:
        cleanup_expired_jobs()
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)


_cleanup_task: asyncio.Task | None = None


@app.on_event("startup")
async def start_cleanup_task() -> None:
    global _cleanup_task
    _cleanup_task = asyncio.create_task(cleanup_loop())


@app.on_event("shutdown")
async def stop_cleanup_task() -> None:
    global _cleanup_task
    if _cleanup_task:
        _cleanup_task.cancel()
        with suppress(asyncio.CancelledError):
            await _cleanup_task
        _cleanup_task = None


def valid_job_id(job_id: str) -> bool:
    return bool(JOB_ID_PATTERN.fullmatch(job_id))


async def save_upload(upload: UploadFile, destination: Path, max_bytes: int) -> Path:
    suffix = Path(upload.filename or "video.mp4").suffix.lower()
    if suffix not in VIDEO_SUFFIXES:
        suffix = ".mp4"
    target = destination.with_suffix(suffix)
    written = 0
    try:
        with target.open("wb") as buffer:
            try:
                target.chmod(0o600)
            except OSError:
                logger.warning("Could not restrict permissions on a temporary upload.")
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File is too large. Maximum allowed size is {max_bytes // (1024 * 1024)} MB.",
                    )
                buffer.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()
    return target


def media_path(job_id: str, filename: str) -> Path:
    if not valid_job_id(job_id) or Path(filename).name != filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=404, detail="File not found.")

    if filename.startswith("source") and Path(filename).suffix.lower() in VIDEO_SUFFIXES:
        path = PREVIEWS / job_id / filename
        if filename != "source" + Path(filename).suffix.lower():
            raise HTTPException(status_code=404, detail="File not found.")
    elif THUMBNAIL_PATTERN.fullmatch(filename):
        path = PREVIEWS / job_id / filename
    elif OUTPUT_PATTERN.fullmatch(filename):
        path = OUTPUTS / job_id / filename
    else:
        raise HTTPException(status_code=404, detail="File not found.")

    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    return path


@app.get("/", response_class=HTMLResponse)
def home():
    return (WEB / "index.html").read_text(encoding="utf-8")


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "shortforge-ai-api", "version": "0.4.0"}


@app.get("/api/media/{job_id}/{filename}")
def get_media(job_id: str, filename: str):
    path = media_path(job_id, filename)
    media_type = "video/mp4" if path.suffix.lower() == ".mp4" else None
    if path.suffix.lower() == ".jpg":
        media_type = "image/jpeg"
    return FileResponse(
        path,
        media_type=media_type,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@app.post("/api/analyze")
async def analyze(
    url: str = Form(""),
    video: UploadFile | None = File(None),
    cookie_file: UploadFile | None = File(None),
    segments_json: str = Form(""),
    language: str = Form(""),
    source_title: str = Form(""),
    count: int = Form(5),
):
    cleanup_expired_jobs()
    job_id = uuid.uuid4().hex
    job_dir = PREVIEWS / job_id
    job_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    source_path = None
    cookie_path = None

    try:
        if cookie_file and cookie_file.filename:
            cookie_bytes = await cookie_file.read(MAX_COOKIE_BYTES + 1)
            await cookie_file.close()
            if len(cookie_bytes) > MAX_COOKIE_BYTES:
                raise RuntimeError("YouTube cookies file is too large. Please upload a cookies.txt file under 2 MB.")
            cookie_text = cookie_bytes.decode("utf-8-sig", errors="replace")
            first_line = cookie_text.splitlines()[0].strip() if cookie_text.splitlines() else ""
            if first_line not in {"# HTTP Cookie File", "# Netscape HTTP Cookie File"}:
                raise RuntimeError("Invalid YouTube cookies file. Upload a Netscape-format cookies.txt file.")
            cookie_path = job_dir / "youtube-cookies.txt"
            cookie_path.write_bytes(cookie_bytes)
            try:
                cookie_path.chmod(0o600)
            except OSError:
                logger.warning("Could not restrict permissions on a temporary cookie file.")

        if url.strip():
            if not is_allowed_youtube_url(url):
                raise RuntimeError("Only HTTPS links from YouTube or youtu.be are supported.")
            source_path, title = download_youtube(
                url.strip(),
                job_dir / "source.mp4",
                cookie_file=cookie_path,
            )
        elif video and video.filename:
            source_path = await save_upload(video, job_dir / "source", MAX_VIDEO_BYTES)
            title = Path(video.filename).stem.replace("_", " ")
        else:
            shutil.rmtree(job_dir, ignore_errors=True)
            return {"error": "Add a YouTube URL or choose a video file."}

        if source_path.suffix.lower() not in VIDEO_SUFFIXES or not source_path.is_file():
            raise RuntimeError("The source video could not be prepared.")
        duration = probe_duration(source_path)
        if duration <= 0:
            raise RuntimeError("The video duration could not be read.")

        if segments_json.strip():
            if len(segments_json) > 5_000_000:
                raise RuntimeError("Local transcription data is too large.")
            try:
                raw_segments = json.loads(segments_json)
            except json.JSONDecodeError as exc:
                raise RuntimeError("Invalid local transcription data.") from exc
            if not isinstance(raw_segments, list):
                raise RuntimeError("Invalid local transcription data.")
            segments = []
            for item in raw_segments:
                if not isinstance(item, dict):
                    continue
                try:
                    start = float(item["start"])
                    end = float(item["end"])
                    text = str(item.get("text", "")).strip()
                except (KeyError, TypeError, ValueError):
                    continue
                if end > start and start >= 0 and text:
                    segments.append({"start": start, "end": end, "text": text})
            if not segments:
                raise RuntimeError("No speech segments were supplied by the local bridge.")
            detected_language = language.strip()[:40] or "unknown"
        else:
            segments, detected_language = transcribe(source_path)

        hooks = choose_windows(segments, count=max(3, min(count * 2, 10)), target_duration=45)
        for hook in hooks:
            thumb = job_dir / (hook["id"] + ".jpg")
            extract_thumbnail(source_path, thumb, hook["start"])
            hook["thumbnail_url"] = f"/api/media/{job_id}/{thumb.name}"
            hook["preview_url"] = (
                f"/api/media/{job_id}/{source_path.name}"
                f"#t={hook['start']:.2f},{hook['end']:.2f}"
            )
            hook.pop("text", None)

        (job_dir / "analysis.json").write_text(
            json.dumps(
                {
                    "title": source_title.strip()[:200] or title[:200],
                    "duration": duration,
                    "language": detected_language,
                    "hooks": hooks,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        return {
            "job_id": job_id,
            "title": source_title.strip()[:200] or title[:200],
            "duration": duration,
            "language": detected_language,
            "preview_url": f"/api/media/{job_id}/{source_path.name}",
            "hooks": hooks,
        }
    except HTTPException:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise
    except RuntimeError as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        return {"error": str(exc)}
    except Exception:
        logger.exception("ShortForge analysis failed.")
        shutil.rmtree(job_dir, ignore_errors=True)
        return {"error": "Analysis failed. Check the video format and try again."}
    finally:
        if cookie_path:
            cookie_path.unlink(missing_ok=True)


@app.post("/api/generate")
async def generate(
    job_id: str = Form(""),
    selected: str = Form("[]"),
    subtitles: str = Form("false"),
    subtitle_style: str = Form("Modern Highlight"),
    broll: str = Form("false"),
    fmt: str = Form("9:16"),
    broll_file: UploadFile | None = File(None),
):
    cleanup_expired_jobs()
    if not valid_job_id(job_id):
        return {"error": "Analyze a video before generating Shorts."}

    job_dir = PREVIEWS / job_id
    snapshot_path = job_dir / "analysis.json"
    if not snapshot_path.is_file():
        return {"error": "This analysis has expired. Analyze the video again."}
    # Refresh the directory timestamp so retention cleanup does not expire a job
    # while it is actively being used. Path.touch() fails on directories.
    try:
        os.utime(job_dir, None)
    except OSError:
        return {"error": "The analyzed video is no longer available."}

    try:
        selected_ids = json.loads(selected)
        if (
            not isinstance(selected_ids, list)
            or not selected_ids
            or len(selected_ids) > 10
            or any(not isinstance(item, str) or len(item) > 40 for item in selected_ids)
        ):
            return {"error": "Select between 1 and 10 valid hook moments."}

        data = json.loads(snapshot_path.read_text(encoding="utf-8"))
        hooks = {item["id"]: item for item in data.get("hooks", []) if isinstance(item, dict) and isinstance(item.get("id"), str)}
        chosen = [hooks[item] for item in selected_ids if item in hooks]
        if not chosen:
            return {"error": "The selected moments do not belong to this analysis."}

        source = next((job_dir / f"source{suffix}" for suffix in VIDEO_SUFFIXES if (job_dir / f"source{suffix}").is_file()), None)
        if source is None:
            return {"error": "The analyzed source video is no longer available."}

        broll_path = None
        if broll.lower() == "true" and broll_file and broll_file.filename:
            broll_path = await save_upload(broll_file, job_dir / "broll", MAX_BROLL_BYTES)

        output_dir = OUTPUTS / job_id
        segments, _ = (
            transcribe(source)
            if subtitles.lower() == "true"
            else (
                [
                    {
                        "start": item["start"],
                        "end": item["end"],
                        "text": item.get("title", ""),
                    }
                    for item in chosen
                ],
                "unknown",
            )
        )

        clips = create_job(
            source,
            output_dir,
            chosen,
            segments=segments,
            subtitles=subtitles.lower() == "true",
            fmt=fmt if fmt in {"9:16", "1:1", "16:9"} else "9:16",
            broll=broll_path,
        )

        return {
            "clips": [
                {
                    "name": path.name,
                    "url": f"/api/media/{job_id}/{path.name}",
                    "download_url": f"/api/download/{job_id}/{path.name}",
                    "duration": float(chosen[index]["end"]) - float(chosen[index]["start"]),
                }
                for index, path in enumerate(clips)
            ],
            "subtitle_style": subtitle_style[:80],
        }
    except HTTPException as exc:
        return {"error": exc.detail}
    except RuntimeError as exc:
        return {"error": str(exc)}
    except Exception:
        logger.exception("ShortForge generation failed.")
        return {"error": "Short generation failed. Please retry."}


@app.get("/api/download/{job_id}/{filename}")
def download(job_id: str, filename: str):
    if not valid_job_id(job_id) or not OUTPUT_PATTERN.fullmatch(filename):
        raise HTTPException(status_code=404, detail="File not found.")
    path = OUTPUTS / job_id / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(
        path,
        media_type="video/mp4",
        filename=path.name,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )
