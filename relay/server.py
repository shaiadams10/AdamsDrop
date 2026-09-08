import os
import logging
import time
import secrets
import asyncio
import urllib.parse
from contextlib import asynccontextmanager
from typing import Optional

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Header, Query, Request, Response, HTTPException, status
from fastapi.responses import JSONResponse, HTMLResponse

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

# In-memory storage: { token: { "content_type": str, "data": bytes, "created_at": float } }
storage = {}
storage_lock = asyncio.Lock()

async def sweep_expired_tokens():
    while True:
        try:
            await asyncio.sleep(60)
            now = time.time()
            async with storage_lock:
                expired = [
                    token for token, item in storage.items()
                    if now - item["created_at"] > TOKEN_TTL_SECONDS
                ]
                for token in expired:
                    del storage[token]
        except asyncio.CancelledError:
            break
        except Exception:
            pass

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http_client = httpx.AsyncClient(timeout=10.0)
    sweep_task = asyncio.create_task(sweep_expired_tokens())
    yield
    await app.state.http_client.aclose()
    sweep_task.cancel()
    try:
        await sweep_task
    except asyncio.CancelledError:
        pass

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
    x_api_key: Optional[str] = Header(None, alias="X-Api-Key")
):
    verify_api_key(x_api_key)

    started = time.perf_counter()
    body_buffer = bytearray()
    async for chunk in request.stream():
        if len(body_buffer) + len(chunk) > MAX_PAYLOAD_SIZE:
            raise HTTPException(status_code=413, detail="Payload too large")
        body_buffer.extend(chunk)
    body = bytes(body_buffer)
    del body_buffer
    if len(body) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty payload")
    if len(body) > MAX_PAYLOAD_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Payload exceeds limit of {MAX_PAYLOAD_SIZE} bytes"
        )

    content_type = request.headers.get("content-type", "text/plain; charset=utf-8")

    # Extract payload from multipart if sent as form/multipart
    if content_type.startswith("multipart/form-data"):
        try:
            import email
            msg = email.message_from_bytes(b"Content-Type: " + content_type.encode("utf-8") + b"\r\n\r\n" + body)
            for part in msg.walk():
                if part.get_content_maintype() == "image":
                    body = part.get_payload(decode=True)
                    content_type = part.get_content_type()
                    break
                elif part.get_content_maintype() == "text":
                    body = part.get_payload(decode=True)
                    content_type = part.get_content_type()
        except Exception:
            pass

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

    token = secrets.token_urlsafe(32)

    async with storage_lock:
        now = time.time()
        for expired in [t for t, item in storage.items()
                        if now - item["created_at"] > TOKEN_TTL_SECONDS]:
            del storage[expired]
        if (len(storage) >= MAX_STORED_ITEMS or
                sum(len(item["data"]) for item in storage.values()) + len(body) > MAX_STORED_BYTES):
            raise HTTPException(status_code=503, detail="Clipboard buffer full; retry later")
        storage[token] = {
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
        click_action = f"shortcuts://run-shortcut?name=SetClipboard&input=text&text={encoded_fetch_url}"
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
    try:
        if source == "windows":
            ntfy_resp = await client.post(NTFY_URL, json=ntfy_payload)
        else:
            ntfy_resp = await client.post(f"{NTFY_URL}/clip-to-windows", content=token)
        ntfy_resp.raise_for_status()
    except httpx.HTTPError:
        async with storage_lock:
            storage.pop(token, None)
        raise HTTPException(status_code=502, detail="Notification publication failed")
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

    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Item not found or already retrieved/expired"
        )

    return Response(content=item["data"], media_type=item["content_type"],
                    headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

@app.get("/setup", response_class=HTMLResponse)
async def setup_page():
    return HTMLResponse("""<!doctype html><html><head><meta name="viewport" content="width=device-width"></head>
    <body><h1>Adams’Drop</h1>
    <p>Subscribe to your ntfy server / clip-to-ipad in ntfy.</p>
    <p>SetClipboard: Get Contents of URL (Shortcut Input), then Copy to Clipboard.</p>
    <p>This method opens Shortcuts. Developer Mode does not change that behavior.</p>
    <p>For iPad-to-PC setup, use the private Windows client configuration. Credentials are not served on this page.</p>
    </body></html>""", headers={"Cache-Control": "no-store"})
