"""Explicit original-file sends through the existing relay; no clipboard changes."""
import hashlib
import json
import mimetypes
import sys
import urllib.parse
from pathlib import Path

import requests
import foreground_guard
import sync_state

SCRIPT_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
MAX_SIZE = 2 * 1024**3
MAX_FILES = 16


def check_activity():
    if foreground_guard.should_pause():
        raise InterruptedError("Paused for full-screen activity; send again afterwards")


class Upload:
    def __init__(self, file, size, progress=None, cancelled=None):
        self.file, self.size = file, size
        self.progress, self.cancelled = progress, cancelled

    def __len__(self):
        return self.size

    def __iter__(self):
        sent = 0
        while True:
            check_activity()
            if self.cancelled and self.cancelled():
                raise InterruptedError("Transfer cancelled")
            chunk = self.file.read(512 * 1024)
            if not chunk:
                if self.progress:
                    self.progress("Notifying", self.size, self.size)
                return
            sent += len(chunk)
            if self.progress:
                self.progress("Uploading", sent, self.size)
            yield chunk


def send_files(paths, *, config=None, session=None, progress=None, cancelled=None):
    """Return ready-to-download count; raise if any file cannot be queued."""
    check_activity()
    paths = [Path(path).resolve() for path in paths]
    if not paths or len(paths) > MAX_FILES:
        raise ValueError("Select between 1 and 16 files")
    for path in paths:
        if not path.is_file():
            raise ValueError("Select files, not folders")
        if path.stat().st_size > MAX_SIZE:
            raise ValueError("File exceeds the 2 GiB limit")
    config = config if config is not None else json.loads((SCRIPT_DIR / "config.json").read_text(encoding="utf-8"))
    if not config.get("api_key"):
        raise ValueError("AdamsDrop API key is missing from local configuration")
    if not sync_state.send_lock.acquire(blocking=False):
        raise RuntimeError("Another transfer is in progress; send again when ready")
    owned = session is None
    session = session or requests.Session()
    completed = 0
    try:
        for index, path in enumerate(paths, 1):
            def report(stage, done=0, total=0):
                if progress:
                    progress(stage, done, total, path.name, index, len(paths))

            check_activity()
            if cancelled and cancelled():
                raise InterruptedError("Transfer cancelled")
            with path.open("rb") as file:
                size = path.stat().st_size
                if size > MAX_SIZE:
                    raise ValueError("File exceeds the 2 GiB limit")
                digest = hashlib.sha256()
                report("Preparing", 0, size)
                hashed = 0
                while chunk := file.read(512 * 1024):
                    check_activity()
                    if cancelled and cancelled():
                        raise InterruptedError("Transfer cancelled")
                    digest.update(chunk)
                    hashed += len(chunk)
                    report("Preparing", hashed, size)
                file.seek(0)
                report("Uploading", 0, size)
                if not size:
                    report("Notifying", 0, 0)
                response = session.post(config["relay_url"].rstrip("/") + "/send?source=windows&kind=file",
                    headers={"X-Api-Key": config["api_key"],
                             "Content-Type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                             "X-Filename": urllib.parse.quote(path.name, safe=""),
                             "X-Content-SHA256": digest.hexdigest(), "Content-Length": str(size)},
                    data=Upload(file, size, report, cancelled) if size else b"", timeout=(5, 120))
                try:
                    if response.status_code != 200:
                        raise RuntimeError(f"Relay returned HTTP {response.status_code}")
                finally:
                    response.close()
                completed += 1
                report("Queued", size, size)
        return completed
    except Exception as exc:
        # Do not log URLs, filenames, server responses or credentials.
        if completed:
            raise RuntimeError(f"{completed} file(s) ready; remaining transfer failed ({type(exc).__name__}). Tap existing iPad notifications before retrying remaining files.") from None
        raise
    finally:
        sync_state.send_lock.release()
        if owned:
            session.close()


def select_files():
    import win32con
    import win32gui
    try:
        selection, _, _ = win32gui.GetOpenFileNameW(
            Title="Send Files to iPad", Filter="All files\0*.*\0",
            Flags=win32con.OFN_EXPLORER | win32con.OFN_ALLOWMULTISELECT |
                  win32con.OFN_FILEMUSTEXIST | win32con.OFN_NOCHANGEDIR,
            MaxFile=65536)
    except win32gui.error as exc:
        if exc.winerror == 0:
            return []
        raise
    parts = selection.split("\0")
    if len(parts) == 1:
        return parts
    return [str(Path(parts[0]) / name) for name in parts[1:] if name]


def selected_explorer_files():
    """Read the foreground Explorer's active tab without touching the clipboard."""
    import pythoncom
    import win32gui
    foreground = win32gui.GetForegroundWindow()
    pythoncom.CoInitialize()
    try:
        # Helper releases all COM references before apartment teardown.
        return _read_explorer_selection(foreground)
    except Exception:
        return []
    finally:
        pythoncom.CoUninitialize()


def _read_explorer_selection(foreground):
    import pythoncom
    import win32gui
    import win32com.client
    from win32com.shell import shell as shell_api
    if win32gui.GetClassName(foreground) not in ("CabinetWClass", "ExploreWClass"):
        return []
    shell = win32com.client.Dispatch("Shell.Application")
    matches = []
    for window in shell.Windows():
        try:
            if int(window.HWND) == foreground:
                matches.append(window)
        except Exception:
            continue  # A closing unrelated Explorer window must not abort selection.
    # Windows 11 puts the active ShellTabWindowClass first in child Z order.
    # All tabs share the frame HWND; COM enumeration order is not tab order.
    active_tab = win32gui.FindWindowEx(foreground, 0, "ShellTabWindowClass", None)
    if active_tab:
        active_matches = []
        for window in matches:
            try:
                provider = window._oleobj_.QueryInterface(pythoncom.IID_IServiceProvider)
                browser = provider.QueryService(shell_api.SID_STopLevelBrowser, pythoncom.IID_IOleWindow)
                if browser.GetWindow() == active_tab:
                    active_matches.append(window)
            except Exception:
                continue
        matches = active_matches
    # Legacy Explorer has one entry per frame. Unknown/ambiguous layouts use picker.
    if len(matches) != 1:
        return []
    paths = [item.Path for item in matches[0].Document.SelectedItems() if item.IsFileSystem]
    if win32gui.GetForegroundWindow() != foreground or (
            active_tab and win32gui.FindWindowEx(foreground, 0, "ShellTabWindowClass", None) != active_tab):
        return []  # Focus/tab changed during lookup; do not send a stale selection.
    return paths


def run(paths=None, *, selected=False):
    """One-shot command for Explorer Send to; no background listener starts."""
    import ctypes
    import win32api
    import win32event
    import win32process
    mutex = win32event.CreateMutex(None, False, "Local\\AdamsDropFileSend")
    try:
        if win32api.GetLastError() == 183:
            raise RuntimeError("Another file send is in progress")
        win32process.SetPriorityClass(win32api.GetCurrentProcess(), win32process.BELOW_NORMAL_PRIORITY_CLASS)
        check_activity()
        paths = paths or (selected_explorer_files() if selected else []) or select_files()
        if not paths:
            return 0
        from transfer_progress import TransferWindow
        return TransferWindow().run(lambda progress, cancelled: send_files(paths, progress=progress, cancelled=cancelled))
    except Exception as exc:
        message = str(exc) if isinstance(exc, (ValueError, RuntimeError, InterruptedError)) else f"Transfer failed ({type(exc).__name__}); send again"
        if not foreground_guard.should_pause():
            ctypes.windll.user32.MessageBoxW(None, message, "AdamsDrop file send", 0x10)
        return 1
    finally:
        win32api.CloseHandle(mutex)
