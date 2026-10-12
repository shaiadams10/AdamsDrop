import os
import logging
import time
import secrets
import asyncio
import hashlib
import shutil
import tempfile
import re
from email.message import Message
from pathlib import Path
import urllib.parse
from contextlib import asynccontextmanager
from typing import Optional

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Header, Query, Request, Response, HTTPException, status
from fastapi.responses import JSONResponse, HTMLResponse, StreamingResponse

# Fetch URLs contain single-use capabilities; do not write them to access logs.
logging.getLogger("uvicorn.access").disabled = True
load_dotenv()

API_KEY = os.getenv("API_KEY")
if not API_KEY:
    raise RuntimeError("API_KEY must be set in .env")

NTFY_URL = os.getenv("NTFY_URL", "http://ntfy:80").rstrip("/")
RELAY_BASE_URL = os.getenv("RELAY_BASE_URL", "http://127.0.0.1:8765").rstrip("/")
MAX_PAYLOAD_SIZE = int(os.getenv("MAX_PAYLOAD_SIZE", 25 * 1024 * 1024))  # 25 MB cap
MAX_STORED_BYTES = 100 * 1024 * 1024
MAX_STORED_ITEMS = 256
TOKEN_TTL_SECONDS = int(os.getenv("TOKEN_TTL_SECONDS", 600))  # 10 minutes
MAX_VIDEO_SIZE = int(os.getenv("MAX_VIDEO_SIZE", 2 * 1024**3))
MAX_VIDEO_STORED_BYTES = int(os.getenv("MAX_VIDEO_STORED_BYTES", 4 * 1024**3))
MAX_VIDEO_FILES = 16
MAX_VIDEO_UPLOADS = 2
VIDEO_DISK_RESERVE = 256 * 1024**2
VIDEO_SPOOL_DIR = Path(os.getenv("VIDEO_SPOOL_DIR", str(Path(tempfile.gettempdir()) / "adamsdrop-video-buffer")))
VIDEO_TYPES = {
    "video/mp4": ".mp4", "video/quicktime": ".mov", "video/x-m4v": ".m4v",
    "video/webm": ".webm", "video/x-matroska": ".mkv", "video/x-msvideo": ".avi",
}
FILE_TYPES = {
    "application/pdf": ".pdf", "text/csv": ".csv", "application/csv": ".csv",
    "application/json": ".json", "application/ld+json": ".jsonld",
    "application/xml": ".xml", "text/xml": ".xml", "text/tab-separated-values": ".tsv",
    "application/zip": ".zip", "application/gzip": ".gz", "application/x-gzip": ".gz",
    "application/x-tar": ".tar", "application/x-7z-compressed": ".7z",
    "application/rtf": ".rtf", "text/rtf": ".rtf",
    "application/msword": ".doc", "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "text/plain": ".txt", "text/html": ".html",
}

# Single-use metadata: text/images hold bytes; videos hold a transient file path.
storage = {}
storage_lock = asyncio.Lock()

def video_type(prefix: bytes, content_type: str):
    """Recognize original containers even when Shortcuts sends octet-stream."""
    if len(prefix) >= 12 and prefix[4:8] == b"ftyp":
        brand = prefix[8:12]
        if brand in (b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1", b"avif", b"avis"):
            return None  # HEIF/AVIF images also use an ISO media container.
        if brand == b"qt  ":
            return "video/quicktime"
        if brand in (b"isom", b"iso2", b"mp41", b"mp42", b"avc1", b"M4V ", b"MSNV", b"dash"):
            return "video/mp4"
    if len(prefix) >= 12 and prefix[:4] == b"RIFF" and prefix[8:12] == b"AVI ":
        return "video/x-msvideo"
    if prefix.startswith(b"\x1a\x45\xdf\xa3"):
        if b"matroska" in prefix:
            return "video/x-matroska"
        return content_type if content_type in ("video/webm", "video/x-matroska") else "video/webm"
    return content_type if content_type in VIDEO_TYPES else None


def incoming_filename(request: Request):
    name = request.query_params.get("filename", "") or urllib.parse.unquote(request.headers.get("x-filename", ""))
    if not name:
        message = Message()
        message["content-disposition"] = request.headers.get("content-disposition", "")
        name = message.get_filename() or ""
    return name


def safe_filename(name, content_type, *, video=False):
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join("_" if ord(c) < 32 or c in '<>:"/\\|?*' or '\u202a' <= c <= '\u202e' else c for c in name).strip(" .")
    original_suffix = Path(name).suffix
    if video:
        suffix = VIDEO_TYPES[content_type]
        stem = Path(name).stem if original_suffix.lower() in VIDEO_TYPES.values() else name
    else:
        suffix = original_suffix if re.fullmatch(r"\.[a-zA-Z0-9_-]{1,20}", original_suffix) else FILE_TYPES.get(content_type, ".bin")
        stem = Path(name).stem if original_suffix else name
    return (stem[:120] or ("video" if video else "file")) + suffix


def attachment_kind(prefix, content_type, filename, force_file=False):
    """Explicit file mode keeps text files separate from clipboard text."""
    if force_file:
        return "file", content_type
    if prefix.startswith(b"%PDF-"):
        return "file", "application/pdf"
    video = video_type(prefix, "")
    if video:
        return "video", video
    if content_type.startswith("multipart/"):
        return None
    if (prefix.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF8", b"BM")) or
            (prefix[:4] == b"RIFF" and prefix[8:12] == b"WEBP")):
        return None
    if filename:
        suffix = Path(filename).suffix.lower()
        if suffix not in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".heic", ".heif", ".tif", ".tiff") and suffix not in VIDEO_TYPES.values():
            return "file", content_type
    if content_type.startswith("image/"):
        return None
    video = video_type(prefix, content_type)
    if video:
        return "video", video
    if filename:
        return "file", content_type
    if content_type.startswith(("application/", "audio/")) or content_type in FILE_TYPES and content_type not in ("text/plain", "text/html"):
        return "file", content_type
    return None


async def remove_video(path):
    # Keep disk accounting until deletion has completed, including active fetches.
    async with storage_lock:
        await asyncio.to_thread(path.unlink, missing_ok=True)
        app.state.video_files.pop(path, None)


async def expire_items():
    async with storage_lock:
        now = time.time()
        expired = [storage.pop(t) for t in list(storage)
                   if now - storage[t]["created_at"] > TOKEN_TTL_SECONDS]
    for item in expired:
        if "path" in item:
            await remove_video(item["path"])


async def receive_video(request, prefix, stream, content_type, *, filename=None, file_kind="video", multipart=False):
    length = request.headers.get("content-length")
    try:
        declared_size = int(length) if length else 0
    except ValueError:
        raise HTTPException(400, "Invalid Content-Length")
    if not multipart and declared_size > MAX_VIDEO_SIZE:
        raise HTTPException(413, "File exceeds configured limit")
    async with storage_lock:
        if app.state.video_uploads >= MAX_VIDEO_UPLOADS or len(app.state.video_files) >= MAX_VIDEO_FILES:
            raise HTTPException(503, "File buffer busy; retry later")
        fd, name = tempfile.mkstemp(dir=app.state.video_dir, suffix=".upload")
        path = Path(name)
        app.state.video_uploads += 1
        app.state.video_files[path] = 0
    size = 0
    digest = hashlib.sha256()
    completed = False
    disk_checked = 0
    try:
        with os.fdopen(fd, "wb") as output:
            chunk = prefix
            while True:
                if chunk:
                    size += len(chunk)
                    if size > MAX_VIDEO_SIZE:
                        raise HTTPException(413, "File exceeds configured limit")
                    async with storage_lock:
                        if sum(app.state.video_files.values()) + len(chunk) > MAX_VIDEO_STORED_BYTES:
                            raise HTTPException(503, "File buffer full; retry later")
                        app.state.video_files[path] = size
                    if not disk_checked or size - disk_checked >= 16 * 1024**2:
                        free = (await asyncio.to_thread(shutil.disk_usage, app.state.video_dir)).free
                        if free < len(chunk) + VIDEO_DISK_RESERVE:
                            raise HTTPException(507, "Insufficient temporary file storage")
                        disk_checked = size
                    await asyncio.to_thread(output.write, chunk)
                    digest.update(chunk)
                try:
                    chunk = await anext(stream)
                except StopAsyncIteration:
                    break
        if file_kind == "video" and not size:
            raise HTTPException(400, "Empty video")
        item = {"path": path, "size": size, "sha256": digest.hexdigest(),
                "filename": safe_filename(filename if filename is not None else incoming_filename(request),
                                          content_type, video=file_kind == "video"),
                "content_type": content_type, "kind": file_kind, "created_at": time.time()}
        completed = True
        return item
    finally:
        async with storage_lock:
            app.state.video_uploads -= 1
        if not completed:
            await remove_video(path)


async def sweep_expired_tokens():
    while True:
        try:
            await asyncio.sleep(60)
            await expire_items()
        except asyncio.CancelledError:
            break
        except Exception:
            pass

@asynccontextmanager
async def lifespan(app: FastAPI):
    # One relay worker owns this private transient directory. Remove crash leftovers.
    video_dir = VIDEO_SPOOL_DIR
    video_dir.mkdir(mode=0o700, exist_ok=True)
    for leftover in video_dir.glob("*.upload"):
        leftover.unlink()
    app.state.video_dir = str(video_dir)
    app.state.video_files = {}
    app.state.video_uploads = 0
    app.state.http_client = httpx.AsyncClient(timeout=10.0)
    sweep_task = asyncio.create_task(sweep_expired_tokens())
    try:
        yield
    finally:
        await app.state.http_client.aclose()
        sweep_task.cancel()
        try:
            await sweep_task
        except asyncio.CancelledError:
            pass
        storage.clear()
        for leftover in video_dir.glob("*.upload"):
            await asyncio.to_thread(leftover.unlink, missing_ok=True)
        app.state.video_files.clear()

app = FastAPI(title="Adams’Drop Relay", lifespan=lifespan)

def verify_api_key(provided_key: Optional[str]):
    if not provided_key or not secrets.compare_digest(provided_key, API_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key"
        )

@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.post("/send")
async def send_clipboard(
    request: Request,
    source: str = Query(..., pattern="^(windows|ipad)$"),
    kind: Optional[str] = Query(None, pattern="^file$"),
    x_api_key: Optional[str] = Header(None, alias="X-Api-Key")
):
    verify_api_key(x_api_key)

    started = time.perf_counter()
    await expire_items()
    content_type = request.headers.get("content-type", "text/plain; charset=utf-8")
    stream = request.stream().__aiter__()
    prefix = bytearray()
    while len(prefix) < 64:
        try:
            prefix.extend(await anext(stream))
        except StopAsyncIteration:
            break
    filename = incoming_filename(request)
    media_type = content_type.split(";", 1)[0].strip().lower()
    multipart = media_type == "multipart/form-data"
    attachment = None if multipart else attachment_kind(bytes(prefix[:64]), media_type, filename, kind == "file")
    if not prefix and not attachment:
        raise HTTPException(400, "Empty payload")
    if attachment:
        if source == "windows" and kind != "file":
            raise HTTPException(415, "Use kind=file for Windows file sharing")
        file_kind, media_type = attachment
        if source == "windows":
            file_kind = "file"
        item = await receive_video(request, bytes(prefix), stream, media_type, filename=filename, file_kind=file_kind)
        body = b""
        content_type = media_type
    else:
        body_buffer = prefix
        if len(body_buffer) > MAX_PAYLOAD_SIZE:
            raise HTTPException(413, "Payload too large; send videos as a raw File body")
        async for chunk in stream:
            if len(body_buffer) + len(chunk) > MAX_PAYLOAD_SIZE:
                raise HTTPException(413, "Payload too large; send videos as a raw File body")
            body_buffer.extend(chunk)
        body = bytes(body_buffer)
        del body_buffer
    if not attachment and len(body) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty payload")
    if len(body) > MAX_PAYLOAD_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Payload exceeds limit of {MAX_PAYLOAD_SIZE} bytes"
        )

    # Extract payload from multipart if sent as form/multipart
    if content_type.startswith("multipart/form-data"):
        try:
            import email
            msg = email.message_from_bytes(b"Content-Type: " + content_type.encode("utf-8") + b"\r\n\r\n" + body)
            file_parts = [part for part in msg.walk() if part.get_filename()]
            if len(file_parts) > 1:
                raise HTTPException(400, "Send one file at a time")
            selected = file_parts[0] if file_parts else None
            for part in msg.walk():
                if not part.is_multipart() and not file_parts:
                    if part.get_content_maintype() in ("image", "video"):
                        selected = part
                        break
                    if part.get_content_maintype() == "text":
                        selected = part
            if selected is None:
                raise ValueError("Missing multipart item")
            body = selected.get_payload(decode=True)
            content_type = selected.get_content_type()
            filename = selected.get_filename() or filename
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(400, "Invalid multipart file upload")

        attachment = attachment_kind(body[:64], content_type, filename, kind == "file")
        if attachment:
            if source == "windows" and kind != "file":
                raise HTTPException(415, "Use kind=file for Windows file sharing")
            file_kind, content_type = attachment
            if source == "windows":
                file_kind = "file"
            item = await receive_video(request, body, stream, content_type,
                                       filename=filename, file_kind=file_kind, multipart=True)
            body = b""

    # Inspect magic bytes for image formats
    if body.startswith(b"\x89PNG\r\n\x1a\n"):
        content_type = "image/png"
    elif body.startswith(b"\xff\xd8\xff"):
        content_type = "image/jpeg"
    elif body.startswith(b"GIF8"):
        content_type = "image/gif"
    elif body.startswith(b"BM"):
        content_type = "image/bmp"
    elif body.startswith(b"RIFF") and len(body) > 12 and body[8:12] == b"WEBP":
        content_type = "image/webp"

    if attachment and request.headers.get("x-content-sha256"):
        expected = request.headers["x-content-sha256"].lower()
        if not secrets.compare_digest(expected, item["sha256"]):
            await remove_video(item["path"])
            raise HTTPException(422, "Uploaded file checksum mismatch")
    if attachment and source == "windows":
        # Shortcuts otherwise decodes JSON/text into values, losing original bytes.
        item["download_as_file"] = True

    token = secrets.token_urlsafe(32)

    async with storage_lock:
        if (len(storage) >= MAX_STORED_ITEMS or
                sum(len(stored.get("data", b"")) for stored in storage.values()) + len(body) > MAX_STORED_BYTES):
            if attachment:
                item["path"].unlink(missing_ok=True)
                app.state.video_files.pop(item["path"], None)
            raise HTTPException(status_code=503, detail="Clipboard buffer full; retry later")
        storage[token] = item if attachment else {
            "content_type": content_type,
            "data": body,
            "created_at": time.time()
        }

    client = request.app.state.http_client
    publish_started = time.perf_counter()
    if source == "windows":
        # The random, single-use token grants access to this item only.
        fetch_url = f"{RELAY_BASE_URL}/fetch/{token}"
        encoded_fetch_url = urllib.parse.quote(fetch_url, safe="")
        shortcut = "SaveToFiles" if attachment else "SetClipboard"
        click_action = f"shortcuts://run-shortcut?name={shortcut}&input=text&text={encoded_fetch_url}"
        ntfy_payload = {
            "topic": "clip-to-ipad",
            "title": "Adams’Drop: ready to copy",
            "message": "Image ready - tap to copy" if content_type.startswith("image/") else "Text ready - tap to copy",
            "priority": 5,
            "tags": ["clipboard"],
            "click": click_action,
            "actions": [{"action": "view", "label": "Copy to Clipboard",
                         "url": click_action, "clear": True}]
        }
        if attachment:
            ntfy_payload.update({
                "title": "Adams’Drop: file ready",
                "message": "File ready - tap to save in Files",
                "tags": ["file_folder"],
                "actions": [{"action": "view", "label": "Save to Files",
                             "url": click_action, "clear": True}],
            })
    try:
        if source == "windows":
            ntfy_resp = await client.post(NTFY_URL, json=ntfy_payload)
        else:
            ntfy_resp = await client.post(f"{NTFY_URL}/clip-to-windows", content=token)
        ntfy_resp.raise_for_status()
    except BaseException as exc:
        async with storage_lock:
            storage.pop(token, None)
        if attachment:
            await remove_video(item["path"])
        if isinstance(exc, httpx.HTTPError):
            raise HTTPException(status_code=502, detail="Notification publication failed")
        raise
    publish_ms = (time.perf_counter() - publish_started) * 1000
    total_ms = (time.perf_counter() - started) * 1000
    return JSONResponse(content={"token": token}, headers={
        "Server-Timing": f"publish;dur={publish_ms:.1f}, relay;dur={total_ms:.1f}",
        "Cache-Control": "no-store"
    })

@app.post("/copied")
async def clipboard_receipt(request: Request, kind: str = Query(..., pattern="^(text|image)$"),
                            x_api_key: Optional[str] = Header(None, alias="X-Api-Key")):
    verify_api_key(x_api_key)
    try:
        response = await request.app.state.http_client.post(NTFY_URL, json={
            "topic": "clip-to-ipad", "title": "Adams’Drop: copied to iPad",
            "message": "Image is on your clipboard - paste anywhere." if kind == "image" else
                       "Text is on your clipboard - paste anywhere.",
            "priority": 5, "tags": ["clipboard"]})
        response.raise_for_status()
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Receipt publication failed")
    return {"status": "notified"}

@app.get("/fetch/{token}")
async def fetch_clipboard(
    token: str,
    key: Optional[str] = Query(None),
    x_api_key: Optional[str] = Header(None, alias="X-Api-Key")
):
    # Possession of a 256-bit single-use token authorizes fetching only this item.
    # Legacy query/header credentials are accepted but never required or returned.

    now = time.time()
    item = None
    async with storage_lock:
        stored = storage.get(token)
        if stored:
            if now - stored["created_at"] <= TOKEN_TTL_SECONDS:
                item = stored
            del storage[token]

    if stored and not item and "path" in stored:
        await remove_video(stored["path"])

    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Item not found or already retrieved/expired"
        )

    if "path" in item:
        async def video_chunks():
            try:
                with item["path"].open("rb") as file:
                    while chunk := await asyncio.to_thread(file.read, 512 * 1024):
                        yield chunk
            finally:
                await asyncio.shield(remove_video(item["path"]))
        return StreamingResponse(video_chunks(), media_type="application/octet-stream" if item.get("download_as_file") else item["content_type"], headers={
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
            "Content-Length": str(item["size"]), "X-Content-SHA256": item["sha256"],
            "X-AdamsDrop-Kind": item.get("kind", "video"),
            "Content-Disposition": "attachment; filename*=UTF-8''" + urllib.parse.quote(item["filename"], safe=""),
        })
    return Response(content=item["data"], media_type=item["content_type"],
                    headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

@app.get("/setup", response_class=HTMLResponse)
async def setup_page():
    return HTMLResponse("""<!doctype html><html><head><meta name="viewport" content="width=device-width"></head>
    <body><h1>Adams’Drop</h1>
    <p>Subscribe to your ntfy server / clip-to-ipad in ntfy.</p>
    <p>SetClipboard: Get Contents of URL (Shortcut Input), then Copy to Clipboard.</p>
    <p>This method opens Shortcuts. Developer Mode does not change that behavior.</p>
    <h2>Windows files to iPad</h2>
    <p>Create a shortcut named <b>SaveToFiles</b>: Get Contents of URL (Shortcut Input, GET),
    then Save File (Contents of URL). Expand Save File, turn Ask Where to Save off,
    and choose an AdamsDrop folder in Files. Leave Overwrite If File Exists off.</p>
    <p>On Windows, right-click a file, Show more options, Send to, AdamsDrop - iPad,
    or use the tray menu Send Files to iPad. Tap the ntfy notification on iPad within ten minutes.
    Allow local-network and folder access the first time. No API key is needed in SaveToFiles.</p>
    <p>Original file bytes are transferred, including PNG and PDF, up to 2 GiB per file.
    An upload confirmation means ready to download, not yet saved on the iPad.
    Resend if the shortcut fails; the download link is single-use.</p>
    <h2>Send a video to Windows</h2>
    <p>Edit SendToWindows: enable Show in Share Sheet and accept Media and Files alongside Text and Images.</p>
    <p>Use Shortcut Input when provided; otherwise use your existing Get Clipboard action.</p>
    <p>Keep your existing /send?source=ipad URL and private X-Api-Key header.
    Set Request Body to File and pass the input directly. Do not use Encode Media or Convert Image.</p>
    <p>In Photos, tap Share, then Options, then Current to prevent format conversion.
    Share one video with SendToWindows. An original video in Files can be shared directly.</p>
    <p>Videos up to 2 GiB save in Downloads/AdamsDrop on Windows after a checksum check.
    Videos automatically reveal their folder with the file selected when full-screen protection is off.
    Their notifications can reveal the file again. The clipboard is unchanged.</p>
    <p>Screenshots copy to the clipboard and save an original file in Downloads/AdamsDrop.
    Click the screenshot notification to reveal its folder with that file selected. Screenshots do not open folders automatically.</p>
    <h2>Send PDFs, CSVs, JSON and other files</h2>
    <p>Share one file from Files with SendToWindows using the same File request body.
    Files up to 2 GiB save in Downloads/AdamsDrop with original bytes and a checksum check.
    Their notifications reveal the saved file on click; the clipboard is unchanged.</p>
    <p>To keep the original filename, on the shared-file branch use Get Details of Files: Name,
    then URL Encode, then pass that value in an X-Filename header. Keep the clipboard-text branch unchanged.</p>
    <p>For an explicit generic-file branch, use /send?source=ipad&amp;kind=file.
    This also saves empty and plain-text files. Keep the default URL for text, screenshots and automatic-video behavior.</p>
    <p>The PC app must be running on the desktop. If a transfer fails or full-screen protection pauses it, send again.</p>
    <p>For iPad-to-PC setup, use the private Windows client configuration. Credentials are not served on this page.</p>
    </body></html>""", headers={"Cache-Control": "no-store"})
