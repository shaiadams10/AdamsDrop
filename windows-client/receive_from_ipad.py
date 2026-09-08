"""Listen for incoming iPad clipboard events via ntfy SSE and copy directly to Windows clipboard."""
import hashlib
import ctypes
import io
import json
import logging
import os
import sys
import time
import subprocess
from pathlib import Path

import requests
import win32clipboard
import clipboard_origin
from PIL import Image

try:
    import sync_state
except ImportError:
    from . import sync_state

SCRIPT_DIR = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
LOG_FILE = SCRIPT_DIR / "listener.log"
CACHE_DIR = SCRIPT_DIR / "cache"
CACHE_DIR.mkdir(exist_ok=True)

handlers = [logging.FileHandler(LOG_FILE, encoding="utf-8")]
if sys.stdout is not None:
    handlers.append(logging.StreamHandler(sys.stdout))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=handlers
)
logger = logging.getLogger("ClipboardListener")
CONFIG_PATH = SCRIPT_DIR / "config.json"

tray_instance = None

def load_config():
    if not CONFIG_PATH.exists():
        logger.error(f"Config file not found at {CONFIG_PATH}")
        sys.exit(1)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def write_text_to_clipboard(text: str):
    with sync_state.clipboard_lock:
        return _write_text_to_clipboard(text)


def _write_text_to_clipboard(text: str):
    """Write Unicode text to Windows clipboard with retry logic."""
    for _ in range(5):
        try:
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, text)
                clipboard_origin.mark_received()
                sync_state.last_received_sequence = ctypes.windll.user32.GetClipboardSequenceNumber()
                return True
            finally:
                win32clipboard.CloseClipboard()
        except Exception:
            time.sleep(0.1)
    return False

def write_image_to_clipboard(image_bytes: bytes):
    with sync_state.clipboard_lock:
        return _write_image_to_clipboard(image_bytes)


def _write_image_to_clipboard(image_bytes: bytes):
    """Convert PNG/JPEG bytes to DIB and write to Windows clipboard."""
    for _ in range(5):
        try:
            image = Image.open(io.BytesIO(image_bytes))
            output = io.BytesIO()
            # Convert to RGB (DIB requires BMP structure)
            image.convert("RGB").save(output, "BMP")
            dib_data = output.getvalue()[14:]

            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32clipboard.CF_DIB, dib_data)
                png = io.BytesIO()
                image.save(png, 'PNG')
                win32clipboard.SetClipboardData(win32clipboard.RegisterClipboardFormat('PNG'), png.getvalue())
                clipboard_origin.mark_received()
                sync_state.last_received_sequence = ctypes.windll.user32.GetClipboardSequenceNumber()
                return True, image.size
            finally:
                win32clipboard.CloseClipboard()
        except Exception:
            time.sleep(0.1)
    return False, (0, 0)

def process_token(token: str, relay_url: str, api_key: str, config: dict = None):
    """Fetch item from relay using token and write to Windows clipboard."""
    global tray_instance
    fetch_url = f"{relay_url}/fetch/{token}"
    try:
        resp = requests.get(fetch_url, headers={"X-Api-Key": api_key}, timeout=10)
        if resp.status_code == 200:
            content_type = resp.headers.get("content-type", "").lower()
            # Set sync_state before writing to clipboard to prevent echo feedback
            sync_state.last_received_hash = hashlib.sha256(resp.content).hexdigest()
            sync_state.last_received_time = time.time()
            sync_state.last_sent_hash = sync_state.last_received_hash

            notify_enabled = config.get("notify_on_receive", True) if config else True

            if content_type.startswith("image/"):
                success, size = write_image_to_clipboard(resp.content)
                if success:
                    # Save image to cache for click-to-open
                    img_file = CACHE_DIR / "last_clip.png"
                    try:
                        with open(img_file, "wb") as f:
                            f.write(resp.content)
                    except Exception:
                        pass

                    msg = f"Copied image from iPad ({size[0]}x{size[1]})"
                    logger.info(msg)

                    if notify_enabled and tray_instance:
                        tray_instance.show_balloon(
                            "iPad Adams’Drop",
                            f"📷 Image copied ({size[0]}x{size[1]}) — Click to view",
                            image_path=str(img_file)
                        )
                else:
                    logger.error("Failed to write image to clipboard")
            else:
                text = resp.content.decode("utf-8", errors="replace")
                success = write_text_to_clipboard(text)
                if success:
                    preview = f"Text ({len(text)} characters)"
                    msg = "Copied text from iPad"
                    logger.info(msg)

                    if notify_enabled and tray_instance:
                        tray_instance.show_balloon(
                            "iPad Adams’Drop",
                            f"📋 Copied: \"{preview}\""
                        )
                else:
                    logger.error("Failed to write text to clipboard")
        else:
            logger.warning(f"Fetch failed with status {resp.status_code}")
    except Exception as exc:
        logger.error(f"Clipboard fetch failed ({type(exc).__name__})")

def listen_loop():
    config = load_config()
    relay_url = config.get("relay_url", "http://127.0.0.1:8765").rstrip("/")
    ntfy_sse_url = config.get("ntfy_sse_url", "http://127.0.0.1:2586/clip-to-windows/sse")
    api_key = config.get("api_key")

    logger.info("Starting iPad -> Windows clipboard listener...")
    logger.info(f"Connecting to SSE stream: {ntfy_sse_url}")

    backoff = 1
    while True:
        try:
            with requests.get(ntfy_sse_url, stream=True, timeout=90) as response:
                if response.status_code != 200:
                    logger.warning(f"SSE endpoint returned status {response.status_code}. Retrying in {backoff}s...")
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 30)
                    continue

                logger.info("Connected to ntfy SSE stream. Waiting for iPad clipboard events...")
                backoff = 1

                for line in response.iter_lines(chunk_size=1, decode_unicode=True):
                    if not line:
                        continue
                    if line.startswith("data:"):
                        payload_str = line[5:].strip()
                        try:
                            event_data = json.loads(payload_str)
                        except json.JSONDecodeError:
                            continue

                        event_type = event_data.get("event")
                        if event_type == "message":
                            if time.time() - event_data.get('time', 0) > 60:
                                logger.info('Ignored stale incoming clipboard event')
                                continue
                            token = event_data.get("message", "").strip()
                            if token:
                                logger.info("Received clipboard event")
                                process_token(token, relay_url, api_key, config=config)
        except (requests.exceptions.RequestException, Exception) as exc:
            logger.warning("SSE disconnected (%s); retry in %ss", type(exc).__name__, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)

if __name__ == "__main__":
    import win32event
    import win32api
    import threading
    # Hold the handle for the process lifetime: repeated launches must not compete.
    instance_mutex = win32event.CreateMutex(None, False, "Local\\AdamsDrop")
    if win32api.GetLastError() == 183:
        sys.exit(0)

    def trigger_send():
        try:
            import send_to_ipad
            send_to_ipad.send_clipboard(silent=False)
        except Exception as err:
            logger.error("Manual send failed (%s)", type(err).__name__)

    def prepare_direct():
        cfg = load_config()
        if cfg.get("direct_to_ipad") and cfg.get("direct_device"):
            try:
                subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                                '-File', str(SCRIPT_DIR / 'ensure_apple_connection.ps1')],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
                               creationflags=subprocess.CREATE_NO_WINDOW)
                import direct_to_ipad
                with sync_state.send_lock:
                    direct_to_ipad.prepare(cfg["direct_device"])
            except Exception:
                logger.warning("Direct clipboard startup unavailable")
    threading.Thread(target=prepare_direct, daemon=True).start()

    # Start SSE listener loop in a daemon thread
    listener_thread = threading.Thread(target=listen_loop, daemon=True)
    listener_thread.start()

    # Run system tray icon on the main thread
    try:
        from tray_manager import TrayIcon
        tray_instance = TrayIcon(on_send_to_ipad=trigger_send)
        tray_instance.run()
    except Exception as exc:
        logger.warning(f"System tray icon could not be created: {exc}. Continuing headless listener...")
        listener_thread.join()
