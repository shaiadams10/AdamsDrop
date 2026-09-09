"""Event-driven full-screen protection; no polling, hooks, or focus changes.

SHQueryUserNotificationState covers exclusive Direct3D and presentation mode.
The foreground-window geometry check also covers borderless full-screen apps.
Windowed games cannot be reliably identified by this heuristic.
"""
import ctypes
import win32api
import win32con
import win32gui


def _notification_state():
    state = ctypes.c_int()
    query = ctypes.windll.shell32.SHQueryUserNotificationState
    query.argtypes = [ctypes.POINTER(ctypes.c_int)]
    query.restype = ctypes.c_long
    if query(ctypes.byref(state)) < 0:
        raise OSError('Cannot query foreground state')
    return state.value


def should_pause():
    """Prefer skipping a transfer when Windows cannot confirm foreground state."""
    try:
        if _notification_state() in (1, 2, 3, 4):
            return True
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return True
        if win32gui.GetClassName(hwnd) in ('Progman', 'WorkerW', 'Shell_TrayWnd'):
            return False
        # A maximized normal window is not a borderless full-screen application.
        if win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE) & win32con.WS_CAPTION:
            return False
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        monitor = win32api.GetMonitorInfo(win32api.MonitorFromWindow(hwnd, 2))['Monitor']
        ml, mt, mr, mb = monitor
        return left <= ml and top <= mt and right >= mr and bottom >= mb
    except Exception:
        return True
