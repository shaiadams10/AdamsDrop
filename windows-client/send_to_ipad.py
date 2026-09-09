"""Send current Windows clipboard (text or image) to iPad via TinyPC Adams’Drop."""
import io
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import sys
import time
import hashlib
import ctypes
import subprocess
from pathlib import Path

import requests
import win32clipboard
import clipboard_origin
import foreground_guard
from PIL import Image, ImageGrab

SCRIPT_DIR = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.json"
LOG_FILE = SCRIPT_DIR / "listener.log"

logger = logging.getLogger("ClipboardSender")
logger.propagate = False
if not logger.handlers:
    logger.setLevel(logging.INFO)
    fh = RotatingFileHandler(SCRIPT_DIR / 'sender.log', maxBytes=2_000_000, backupCount=2, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(fh)

try:
    import sync_state
except ImportError:
    from . import sync_state

http_session = requests.Session()

def load_config():
    if not CONFIG_PATH.exists():
        logger.error(f"Config file not found at {CONFIG_PATH}")
        sys.exit(1)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def show_toast(title: str, message: str):
    """Display a native Windows notification toast via PowerShell."""
    if foreground_guard.should_pause() or not load_config().get('notify_on_send', False):
        return
    ps_cmd = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null; "
        "$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02); "
        "$textNodes = $template.GetElementsByTagName('text'); "
        f"$textNodes.Item(0).AppendChild($template.CreateTextNode('{title}')) > $null; "
        f"$textNodes.Item(1).AppendChild($template.CreateTextNode('{message}')) > $null; "
        "$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('AdamsDrop'); "
        "$notification = [Windows.UI.Notifications.ToastNotification]::new($template); "
        "$notifier.Show($notification)"
    )
    try:
        CREATE_NO_WINDOW = 0x08000000
        subprocess.run(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_cmd],
            capture_output=True,
            timeout=5,
            creationflags=CREATE_NO_WINDOW
        )
    except Exception:
        pass

def get_clipboard_content():
    """Retrieve text or image from Windows clipboard with retry logic."""
    for attempt in range(5):
        try:
            # 1. Try image first (supports PrintScreen, Win+Shift+S, copied image files)
            grabbed = ImageGrab.grabclipboard()
            if isinstance(grabbed, Image.Image):
                buf = io.BytesIO()
                grabbed.save(buf, format="PNG", compress_level=1)
                return "image/png", buf.getvalue(), f"Image ({grabbed.width}x{grabbed.height})"
            elif isinstance(grabbed, list) and len(grabbed) > 0:
                file_path = Path(grabbed[0])
                if file_path.suffix.lower() in [".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"]:
                    with Image.open(file_path) as img:
                        buf = io.BytesIO()
                        img.save(buf, format="PNG", compress_level=1)
                        return "image/png", buf.getvalue(), f"Image ({img.width}x{img.height})"

            # 2. Try text
            win32clipboard.OpenClipboard()
            try:
                if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                    text = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
                    if text:
                        return "text/plain; charset=utf-8", text.encode("utf-8"), f"Text ({len(text)} characters)"
            finally:
                win32clipboard.CloseClipboard()

            return None, None, "Empty or unsupported clipboard format"
        except Exception:
            time.sleep(0.1)

    return None, None, "Could not open clipboard (locked by another app)"

def send_clipboard(silent: bool = False):
    # Timer callbacks and manual sends share one session and cannot race.
    if foreground_guard.should_pause():
        return False, "Paused for full-screen activity; copy again afterwards"
    if not sync_state.send_lock.acquire(blocking=False):
        return False, "Transfer busy; copy again when ready"
    try:
        return _send_clipboard(silent)
    finally:
        sync_state.send_lock.release()


def _send_clipboard(silent: bool = False):
    """Read clipboard and send to iPad relay, returning (success: bool, description: str)."""
    config = load_config()
    relay_url = config.get("relay_url", "http://127.0.0.1:8765").rstrip("/")
    api_key = config.get("api_key")

    if not api_key:
        err = "Error: 'api_key' missing in config.json"
        logger.error(err)
        if not silent:
            show_toast("Adams’Drop Error", err)
        return False, err

    started = time.perf_counter()
    with sync_state.clipboard_lock:
        sequence = ctypes.windll.user32.GetClipboardSequenceNumber()
        if silent and sequence == sync_state.last_received_sequence:
            return False, "Echo suppressed"
        if silent and sequence == sync_state.last_sent_sequence:
            return False, "Duplicate event suppressed"
        if silent:
            try:
                if clipboard_origin.is_received():
                    return False, 'Remote clipboard origin suppressed'
            except Exception:
                return False, 'Clipboard locked; wait for next copy'
        content_type, payload, desc = get_clipboard_content()
        if sequence != ctypes.windll.user32.GetClipboardSequenceNumber():
            return False, "Clipboard changed during capture; next event will send latest"
    if not payload:
        return False, f"Nothing sent: {desc}"
    if foreground_guard.should_pause():
        return False, "Paused for full-screen activity; copy again afterwards"
    captured = time.perf_counter()
    payload_hash = hashlib.sha256(payload).hexdigest()

    if config.get("direct_to_ipad", False):
        try:
            import direct_to_ipad
            if direct_to_ipad.send(payload, content_type, config.get("direct_device"),
                                  is_current=lambda: not foreground_guard.should_pause() and ctypes.windll.user32.GetClipboardSequenceNumber() == sequence):
                sync_state.last_sent_hash = payload_hash
                sync_state.last_sent_sequence = sequence
                if config.get('notify_ipad_on_direct', True):
                    import clipboard_receipt
                    clipboard_receipt.notify(relay_url, api_key, content_type)
                logger.info("Direct iPad copy: capture=%.1fms transfer=%.1fms bytes=%d",
                            (captured-started)*1000, (time.perf_counter()-captured)*1000, len(payload))
                return True, desc
            if silent and direct_to_ipad.last_failure == 'unavailable':
                logger.info('iPad unavailable; skipped automatic fallback to avoid stale notification backlog')
                return False, 'iPad unavailable; copy again when connected or use manual Send'
        except Exception as exc:
            logger.warning("Direct clipboard setup unavailable (%s)", type(exc).__name__)
            if silent:
                return False, "Direct clipboard unavailable; copy again when connected"

    try:
        if foreground_guard.should_pause():
            return False, "Paused for full-screen activity; copy again afterwards"
        url = f"{relay_url}/send?source=windows"
        headers = {
            "X-Api-Key": api_key,
            "Content-Type": content_type
        }
        resp = http_session.post(url, headers=headers, data=payload, timeout=10)

        if resp.status_code == 200:
            sync_state.last_sent_hash = payload_hash
            sync_state.last_sent_sequence = sequence
            logger.info("Send timing: capture=%.1fms request=%.1fms %s", (captured-started)*1000,
                        (time.perf_counter()-captured)*1000, resp.headers.get("Server-Timing", ""))
            msg = f"Sent to iPad: {desc}"
            logger.info(msg)
            if not silent and config.get("notify_on_send", False):
                show_toast("Adams’Drop", msg)
            return True, desc
        else:
            err_msg = f"Relay returned HTTP {resp.status_code}"
            logger.warning(err_msg)
            if not silent:
                show_toast("Adams’Drop Error", err_msg)
            return False, err_msg
    except Exception as exc:
        err_msg = f"Connection failed ({type(exc).__name__})"
        logger.error(err_msg)
        if not silent:
            show_toast("Adams’Drop Error", err_msg)
        return False, err_msg

def main():
    success, msg = send_clipboard(silent=False)
    if success:
        print(f"Sent to iPad: {msg}")
        return 0
    else:
        print(f"Failed or skipped: {msg}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
