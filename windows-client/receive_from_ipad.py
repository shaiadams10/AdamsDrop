"""Listen for incoming iPad clipboard events via ntfy SSE and copy directly to Windows clipboard."""
import hashlib
import ctypes
import io
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import sys
import time
import subprocess
import uuid
from pathlib import Path

import requests
import win32clipboard
import clipboard_origin
import foreground_guard
import video_transfer
import file_transfer
from tray_manager import reveal_file_in_explorer
from PIL import Image

try:
    import sync_state
except ImportError:
    from . import sync_state

SCRIPT_DIR = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
LOG_FILE = SCRIPT_DIR / "listener.log"

handlers = [RotatingFileHandler(LOG_FILE, maxBytes=2_000_000, backupCount=2, encoding="utf-8")]
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
        if foreground_guard.should_pause():
            return False
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
        if foreground_guard.should_pause():
            return False, (0, 0)
        try:
            image = Image.open(io.BytesIO(image_bytes))
            output = io.BytesIO()
            # Convert to RGB (DIB requires BMP structure)
            image.convert("RGB").save(output, "BMP")
            dib_data = output.getvalue()[14:]
            png = io.BytesIO()
            image.save(png, 'PNG')
            png_data = png.getvalue()

            if foreground_guard.should_pause():
                return False, (0, 0)

            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32clipboard.CF_DIB, dib_data)
                win32clipboard.SetClipboardData(win32clipboard.RegisterClipboardFormat('PNG'), png_data)
                clipboard_origin.mark_received()
                sync_state.last_received_sequence = ctypes.windll.user32.GetClipboardSequenceNumber()
                return True, image.size
            finally:
                win32clipboard.CloseClipboard()
        except Exception:
            time.sleep(0.1)
    return False, (0, 0)

def save_received_image(image_bytes, content_type, config):
    """Keep each original image as a separate file for notification selection."""
    suffixes = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif",
                "image/bmp": ".bmp", "image/webp": ".webp", "image/tiff": ".tif"}
    suffix = suffixes.get(content_type.split(";", 1)[0], ".png")
    destination = Path(config.get("receive_image_dir") or config.get("receive_video_dir") or
                       Path.home() / "Downloads" / "AdamsDrop").expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    name = "image-" + time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:12]
    final_path = destination / (name + suffix)
    partial = destination / (".adamsdrop-" + name + ".part")
    try:
        with partial.open("xb") as file:
            file.write(image_bytes)
        partial.rename(final_path)
        return final_path
    finally:
        partial.unlink(missing_ok=True)


def process_token(token: str, relay_url: str, api_key: str, config: dict = None):
    """Fetch item from relay using token and write to Windows clipboard."""
    global tray_instance
    if foreground_guard.should_pause():
        return
    fetch_url = f"{relay_url}/fetch/{token}"
    try:
        resp = requests.get(fetch_url, headers={"X-Api-Key": api_key}, timeout=(10, 60), stream=True)
        if resp.status_code == 200:
            content_type = resp.headers.get("content-type", "").lower()
            if resp.headers.get("x-adamsdrop-kind") == "file":
                file_path = file_transfer.save_file(resp, config or {}, foreground_guard.should_pause)
                logger.info("Saved original file from iPad (%s bytes; SHA-256 verified)", file_path.stat().st_size)
                if config and config.get("notify_on_receive", False) and tray_instance:
                    tray_instance.show_balloon(
                        "iPad Adams’Drop", "File saved — Click to show in folder",
                        reveal_path=str(file_path))
                return
            if content_type.startswith("video/"):
                video_path = video_transfer.save_video(resp, config or {}, foreground_guard.should_pause)
                logger.info("Saved original video from iPad (%s bytes; SHA-256 verified)", video_path.stat().st_size)
                if config and config.get("notify_on_receive", False) and tray_instance:
                    tray_instance.show_balloon(
                        "iPad Adams’Drop", "Original video saved — Click to show in folder",
                        reveal_path=str(video_path))
                if not foreground_guard.should_pause():
                    try:
                        reveal_file_in_explorer(str(video_path), automatic=True)
                    except Exception as exc:
                        logger.warning("Video folder reveal failed (%s)", type(exc).__name__)
                return
            # Set sync_state before writing to clipboard to prevent echo feedback
            sync_state.last_received_hash = hashlib.sha256(resp.content).hexdigest()
            sync_state.last_received_time = time.time()
            sync_state.last_sent_hash = sync_state.last_received_hash

            notify_enabled = config.get("notify_on_receive", False) if config else False

            if content_type.startswith("image/"):
                success, size = write_image_to_clipboard(resp.content)
                if success:
                    img_file = None
                    try:
                        img_file = save_received_image(resp.content, content_type, config or {})
                    except Exception as exc:
                        logger.warning("Image file save failed (%s); clipboard copy succeeded", type(exc).__name__)

                    msg = f"Copied image from iPad ({size[0]}x{size[1]})"
                    logger.info(msg)

                    if notify_enabled and tray_instance:
                        tray_instance.show_balloon(
                            "iPad Adams’Drop",
                            f"📷 Image copied ({size[0]}x{size[1]})" +
                            (" — Click to show in folder" if img_file else " — File save unavailable"),
                            reveal_path=str(img_file) if img_file else None
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
    finally:
        if 'resp' in locals():
            resp.close()

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
    if (len(sys.argv) > 1 and sys.argv[1] in ("--send-files", "--send-selected")) or (
            getattr(sys, 'frozen', False) and Path(sys.executable).stem == "AdamsDropSend"):
        import send_files_to_ipad
        selected = Path(sys.executable).stem == "AdamsDropSend" or sys.argv[1] == "--send-selected"
        paths = sys.argv[2:] if len(sys.argv) > 1 and sys.argv[1].startswith("--send-") else sys.argv[1:]
        sys.exit(send_files_to_ipad.run(paths, selected=selected))
    import win32event
    import win32api
    import threading
    # Hold the handle for the process lifetime: repeated launches must not compete.
    instance_mutex = win32event.CreateMutex(None, False, "Local\\AdamsDrop")
    if win32api.GetLastError() == 183:
        sys.exit(0)

    # Give games and foreground work scheduling preference, including manual launches.
    import win32process
    win32process.SetPriorityClass(win32api.GetCurrentProcess(), win32process.BELOW_NORMAL_PRIORITY_CLASS)

    def trigger_send():
        try:
            import send_to_ipad
            send_to_ipad.send_clipboard(silent=False)
        except Exception as err:
            logger.error("Manual send failed (%s)", type(err).__name__)

    def prepare_direct():
        if foreground_guard.should_pause():
            return
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
        logger.error("System tray failed (%s); exiting", type(exc).__name__)
        sys.exit(1)
