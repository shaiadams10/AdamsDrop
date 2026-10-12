"""Windows System Tray Icon manager for Adams’Drop with Auto-Sync and Native Notifications."""
import ctypes
import json
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

import win32api
import win32con
import win32gui
import pythoncom
from win32com.shell import shell
import foreground_guard

try:
    import sync_state
except ImportError:
    from . import sync_state

SCRIPT_DIR = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
ICON_PATH = SCRIPT_DIR / "tray_icon.ico"
LOG_FILE = SCRIPT_DIR / "listener.log"
CONFIG_PATH = SCRIPT_DIR / "config.json"

WM_TRAY_NOTIFY = win32con.WM_USER + 20
WM_CLIPBOARDUPDATE = 0x031D
NIN_BALLOONUSERCLICK = 0x0405

ID_TOGGLE_AUTOSYNC = 1000
ID_SEND_TO_IPAD = 1001
ID_OPEN_SETUP = 1002
ID_VIEW_LOGS = 1003
ID_EXIT = 1004
ID_SEND_FILES = 1005

def reveal_file_in_explorer(file_path, *, automatic=False):
    """Open the containing folder with this exact file selected, without playback."""
    if automatic and foreground_guard.should_pause():
        return False
    pythoncom.CoInitialize()
    try:
        item, _ = shell.SHParseDisplayName(str(Path(file_path).resolve()), 0)
        if automatic and foreground_guard.should_pause():
            return False
        # No child list: the absolute item identifies the file to select in its parent.
        shell.SHOpenFolderAndSelectItems(item, (), 0)
        return True
    finally:
        pythoncom.CoUninitialize()


class TrayIcon:
    def __init__(self, on_send_to_ipad=None, tooltip="Adams’Drop (Active)"):
        self.on_send_to_ipad = on_send_to_ipad
        self.tooltip = tooltip
        self.hwnd = None
        self.hicon = None
        self.last_received_file = None
        self._debounce_timer = None
        self._closing = False
        self._load_config()
        self._create_window()
        self._create_icon()
        self._register_clipboard_listener()

    def _load_config(self):
        self.auto_send = True
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    self.auto_send = cfg.get("auto_send", True)
            except Exception:
                pass
        sync_state.auto_send_enabled = self.auto_send

    def _save_auto_send_config(self, enabled: bool):
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                cfg["auto_send"] = enabled
                with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, indent=2)
            except Exception:
                pass

    def _create_window(self):
        wc = win32gui.WNDCLASS()
        self.hinst = wc.hInstance = win32gui.GetModuleHandle(None)
        wc.lpszClassName = "AdamsDropTrayWindow"
        wc.lpfnWndProc = self._wnd_proc
        try:
            self.class_atom = win32gui.RegisterClass(wc)
        except win32gui.error:
            pass

        self.hwnd = win32gui.CreateWindow(
            wc.lpszClassName,
            "AdamsDropHiddenWindow",
            0,
            0, 0, 0, 0,
            0, 0, self.hinst, None
        )

    def _register_clipboard_listener(self):
        try:
            ctypes.windll.user32.AddClipboardFormatListener(self.hwnd)
        except Exception:
            pass

    def _create_icon(self):
        if ICON_PATH.exists():
            self.hicon = win32gui.LoadImage(
                0, str(ICON_PATH), win32con.IMAGE_ICON,
                0, 0, win32con.LR_LOADFROMFILE | win32con.LR_DEFAULTSIZE
            )
        else:
            self.hicon = win32gui.LoadIcon(0, win32con.IDI_APPLICATION)

        flags = win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP
        nid = (self.hwnd, 0, flags, WM_TRAY_NOTIFY, self.hicon, self.tooltip)
        win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, nid)

    def update_tooltip(self, text: str):
        flags = win32gui.NIF_TIP
        nid = (self.hwnd, 0, flags, 0, 0, text)
        try:
            win32gui.Shell_NotifyIcon(win32gui.NIM_MODIFY, nid)
        except Exception:
            pass

    def show_balloon(self, title: str, message: str, image_path: str = None, reveal_path: str = None):
        """Display native Windows toast notification without external processes."""
        if foreground_guard.should_pause():
            return
        self.last_received_file = reveal_path or image_path
        flags = win32gui.NIF_INFO | win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP
        nid = (
            self.hwnd,
            0,
            flags,
            WM_TRAY_NOTIFY,
            self.hicon,
            self.tooltip,
            message,
            6000,
            title,
            win32gui.NIIF_INFO | 0x10 | 0x80  # No sound; respect Windows quiet time.
        )
        try:
            win32gui.Shell_NotifyIcon(win32gui.NIM_MODIFY, nid)
        except Exception:
            pass

    def _show_menu(self):
        menu = win32gui.CreatePopupMenu()
        auto_flag = win32con.MF_CHECKED if self.auto_send else win32con.MF_UNCHECKED
        win32gui.AppendMenu(menu, win32con.MF_STRING | auto_flag, ID_TOGGLE_AUTOSYNC, "Auto-Send on Copy (Win+Shift+S / Ctrl+C)")
        win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")
        win32gui.AppendMenu(menu, win32con.MF_STRING, ID_SEND_TO_IPAD, "Send Clipboard to iPad Now")
        win32gui.AppendMenu(menu, win32con.MF_STRING, ID_SEND_FILES, "Send Files to iPad...")
        win32gui.AppendMenu(menu, win32con.MF_STRING, ID_OPEN_SETUP, "Open iPad Setup Page")
        win32gui.AppendMenu(menu, win32con.MF_STRING, ID_VIEW_LOGS, "View Logs")
        win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")
        win32gui.AppendMenu(menu, win32con.MF_STRING, ID_EXIT, "Exit")

        pos = win32gui.GetCursorPos()
        win32gui.SetForegroundWindow(self.hwnd)
        win32gui.TrackPopupMenu(
            menu,
            win32con.TPM_LEFTALIGN | win32con.TPM_RIGHTBUTTON,
            pos[0], pos[1],
            0,
            self.hwnd,
            None
        )
        win32gui.PostMessage(self.hwnd, win32con.WM_NULL, 0, 0)
        win32gui.DestroyMenu(menu)

    def _on_clipboard_change(self):
        if self._closing:
            return
        try:
            import send_to_ipad
            success, desc = send_to_ipad.send_clipboard(silent=True)
            if success:
                self.update_tooltip(f"Adams’Drop (Sent: {desc})")
        except Exception:
            pass

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_CLIPBOARDUPDATE:
            if self.auto_send and sync_state.auto_send_enabled and not foreground_guard.should_pause():
                if self._debounce_timer:
                    self._debounce_timer.cancel()
                # Coalesce multi-format clipboard events; capture retries handle temporary locks.
                self._debounce_timer = threading.Timer(0.025, self._on_clipboard_change)
                self._debounce_timer.daemon = True
                self._debounce_timer.start()
            return 0
        elif msg == WM_TRAY_NOTIFY:
            if lparam == NIN_BALLOONUSERCLICK:
                if self.last_received_file:
                    file_path = self.last_received_file
                    self.last_received_file = None
                    if os.path.isfile(file_path):
                        try:
                            reveal_file_in_explorer(file_path)
                        except Exception:
                            pass
                    return 0
                return 0
            elif lparam == win32con.WM_RBUTTONUP:
                self._show_menu()
            elif lparam == win32con.WM_LBUTTONDBLCLK:
                if self.on_send_to_ipad:
                    threading.Thread(target=self.on_send_to_ipad, daemon=True).start()
            return 0
        elif msg == win32con.WM_COMMAND:
            cmd_id = win32gui.LOWORD(wparam)
            if cmd_id == ID_TOGGLE_AUTOSYNC:
                self.auto_send = not self.auto_send
                sync_state.auto_send_enabled = self.auto_send
                self._save_auto_send_config(self.auto_send)
                status_str = "ON" if self.auto_send else "OFF"
                self.update_tooltip(f"Adams’Drop (Auto-Sync: {status_str})")
            elif cmd_id == ID_SEND_TO_IPAD:
                if self.on_send_to_ipad:
                    threading.Thread(target=self.on_send_to_ipad, daemon=True).start()
            elif cmd_id == ID_OPEN_SETUP:
                webbrowser.open(json.loads(CONFIG_PATH.read_text()).get('relay_url', 'http://127.0.0.1:8765').rstrip('/') + '/setup')
            elif cmd_id == ID_SEND_FILES:
                # The explicit action opens a picker in an isolated one-shot process.
                import subprocess
                args = [sys.executable, "--send-files"] if getattr(sys, 'frozen', False) else [sys.executable, str(SCRIPT_DIR / 'receive_from_ipad.py'), "--send-files"]
                subprocess.Popen(args, creationflags=subprocess.CREATE_NO_WINDOW)
            elif cmd_id == ID_VIEW_LOGS:
                if LOG_FILE.exists():
                    os.startfile(str(LOG_FILE))
            elif cmd_id == ID_EXIT:
                self.destroy()
            return 0
        elif msg == win32con.WM_DESTROY:
            self.destroy()
            return 0

        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def destroy(self):
        if self._closing:
            return
        self._closing = True
        sync_state.auto_send_enabled = False
        if self._debounce_timer:
            self._debounce_timer.cancel()
        try:
            ctypes.windll.user32.RemoveClipboardFormatListener(self.hwnd)
        except Exception:
            pass
        try:
            win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, (self.hwnd, 0))
        except Exception:
            pass
        win32gui.PostQuitMessage(0)
        sys.exit(0)

    def run(self):
        win32gui.PumpMessages()
