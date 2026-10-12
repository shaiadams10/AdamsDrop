"""Small native-drawn file-transfer card; no web runtime or idle polling."""
import ctypes
import threading
import win32api
import win32con
import win32gui
import foreground_guard

UPDATE = win32con.WM_APP + 41
WIDTH, HEIGHT = 480, 252
NOTIFICATION_GRACE_MS = 3000
CONFIRMATION_MS = 1800

def progress_percent(done, total):
    return max(0, min(100, int(100 * done / total))) if total else 0

def color(value):
    r, g, b = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    return r | g << 8 | b << 16

BG, TEXT, MUTED, TRACK, BLUE, GREEN, RED = map(color,
    ("171c24", "f0f3f8", "a2aec0", "303a48", "7ba8ff", "59d995", "f3a3a3"))

class TransferWindow:
    def __init__(self):
        self.cancelled = threading.Event()
        self.lock = threading.Lock()
        self.state = ("Preparing", 0, 0, "", 1, 1)
        self.completed = self.success = False
        self.settling = self.completion_scheduled = False
        self.error = ""
        self.hwnd = None
        self.scale = 1.0
        self.fonts, self.brushes, self.pens = {}, {}, {}
        self.hover_close = self.hover_cancel = False

    def report(self, *state):
        with self.lock:
            self.state = state
        self._post_update()

    def _post_update(self):
        if self.hwnd:
            try:
                win32gui.PostMessage(self.hwnd, UPDATE, 0, 0)
            except win32gui.error:
                pass

    def _work(self, work):
        try:
            work(self.report, self.cancelled.is_set)
            self.success = True
        except Exception as exc:
            self.error = str(exc) if isinstance(exc, (ValueError, RuntimeError, InterruptedError)) else f"Transfer failed ({type(exc).__name__}); send again"
        self.completed = True
        self._post_update()

    def _px(self, value):
        return round(value * self.scale)

    def _font(self, size, bold=False):
        key = (size, bold)
        if key not in self.fonts:
            font = win32gui.LOGFONT()
            font.lfFaceName = "Segoe UI"
            font.lfHeight = -self._px(size)
            font.lfWeight = 600 if bold else 400
            font.lfQuality = 5
            self.fonts[key] = win32gui.CreateFontIndirect(font)
        return self.fonts[key]

    def _brush(self, value):
        if value not in self.brushes:
            self.brushes[value] = win32gui.CreateSolidBrush(value)
        return self.brushes[value]

    def _pen(self, value, width=1):
        key = (value, width)
        if key not in self.pens:
            self.pens[key] = win32gui.CreatePen(win32con.PS_SOLID, max(1, self._px(width)), value)
        return self.pens[key]

    def _text(self, dc, text, bounds, size=14, value=TEXT, bold=False, flags=0):
        win32gui.SelectObject(dc, self._font(size, bold))
        win32gui.SetTextColor(dc, value)
        win32gui.DrawText(dc, text, -1, tuple(self._px(v) for v in bounds), win32con.DT_NOPREFIX | flags)

    def _line(self, dc, points, value, width=1):
        win32gui.SelectObject(dc, self._pen(value, width))
        win32gui.MoveToEx(dc, self._px(points[0][0]), self._px(points[0][1]))
        for x, y in points[1:]:
            win32gui.LineTo(dc, self._px(x), self._px(y))

    def _round(self, dc, bounds, radius, value):
        win32gui.SelectObject(dc, win32gui.GetStockObject(win32con.NULL_PEN))
        win32gui.SelectObject(dc, self._brush(value))
        win32gui.RoundRect(dc, *(self._px(v) for v in bounds), self._px(radius * 2), self._px(radius * 2))

    def _create(self):
        ctypes.windll.user32.SetProcessDPIAware()
        foreground = win32gui.GetForegroundWindow()
        try:
            self.scale = max(1.0, ctypes.windll.user32.GetDpiForWindow(foreground) / 96)
        except AttributeError:
            pass
        wc = win32gui.WNDCLASS()
        wc.hInstance = win32api.GetModuleHandle(None)
        wc.lpszClassName = "AdamsDropFileTransfer"
        wc.lpfnWndProc = self._window_proc
        wc.hCursor = win32gui.LoadCursor(0, win32con.IDC_ARROW)
        win32gui.RegisterClass(wc)
        _, _, right, bottom = win32api.GetMonitorInfo(win32api.MonitorFromWindow(foreground, 2))["Work"]
        self.hwnd = win32gui.CreateWindowEx(
            win32con.WS_EX_TOOLWINDOW | win32con.WS_EX_TOPMOST | win32con.WS_EX_NOACTIVATE,
            wc.lpszClassName, "AdamsDrop · Send to iPad", win32con.WS_POPUP | win32con.WS_THICKFRAME,
            right - self._px(WIDTH + 20), bottom - self._px(HEIGHT + 20),
            self._px(WIDTH), self._px(HEIGHT), 0, 0, wc.hInstance, None)
        dwm = ctypes.windll.dwmapi
        for attribute, value in ((20, 1), (33, 2), (34, TRACK)):
            setting = ctypes.c_int(value)
            dwm.DwmSetWindowAttribute(ctypes.c_void_p(self.hwnd), attribute, ctypes.byref(setting), 4)
        class Margins(ctypes.Structure):
            _fields_ = [(name, ctypes.c_int) for name in ("left", "right", "top", "bottom")]
        margins = Margins(1, 1, 1, 1)
        dwm.DwmExtendFrameIntoClientArea(ctypes.c_void_p(self.hwnd), ctypes.byref(margins))
        win32gui.ShowWindow(self.hwnd, win32con.SW_SHOWNOACTIVATE)
        win32gui.UpdateWindow(self.hwnd)

    def _update(self):
        if foreground_guard.should_pause():
            self.cancelled.set()
            win32gui.ShowWindow(self.hwnd, win32con.SW_HIDE)
        if self.completed and not self.completion_scheduled:
            self.completion_scheduled = True
            self.settling = self.success
            self._timer(2 if self.success else 1, NOTIFICATION_GRACE_MS if self.success else 10000)
        with self.lock:
            stage, _, _, name, _, _ = self.state
        # Expose status as the native window name for assistive tools.
        status = 'Notification on its way' if self.settling else 'Notification sent' if self.success else 'Transfer stopped' if self.completed else stage
        win32gui.SetWindowText(self.hwnd, f"AdamsDrop · {status} · {name}")
        win32gui.InvalidateRect(self.hwnd, None, False)

    def _timer(self, identifier, milliseconds):
        timer = ctypes.windll.user32.SetTimer
        timer.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint, ctypes.c_void_p]
        timer.restype = ctypes.c_size_t
        timer(self.hwnd, identifier, milliseconds, None)

    def _paint(self, hwnd):
        dc, paint = win32gui.BeginPaint(hwnd)
        memory = bitmap = old_bitmap = None
        try:
            _, _, width, height = win32gui.GetClientRect(hwnd)
            memory = win32gui.CreateCompatibleDC(dc)
            bitmap = win32gui.CreateCompatibleBitmap(dc, width, height)
            old_bitmap = win32gui.SelectObject(memory, bitmap)
            win32gui.FillRect(memory, (0, 0, width, height), self._brush(BG))
            win32gui.SetBkMode(memory, win32con.TRANSPARENT)
            with self.lock:
                stage, done, total, name, index, count = self.state
            self._line(memory, [(24, 27), (44, 27), (39, 22)], BLUE, 2)
            self._line(memory, [(44, 27), (39, 32)], BLUE, 2)
            self._line(memory, [(44, 37), (24, 37), (29, 32)], BLUE, 2)
            self._line(memory, [(24, 37), (29, 42)], BLUE, 2)
            brand = "AdamsDrop" + (f" · {index} of {count}" if count > 1 else "")
            self._text(memory, brand, (56, 20, 395, 43), 13, MUTED)
            close_color = TEXT if self.hover_close else MUTED
            self._line(memory, [(440, 25), (451, 36)], close_color)
            self._line(memory, [(451, 25), (440, 36)], close_color)
            title_x = 24
            if self.completed and not self.settling:
                self._round(memory, (24, 64, 50, 90), 13, GREEN if self.success else RED)
                if self.success:
                    self._line(memory, [(31, 76), (36, 82), (44, 72)], BG, 2)
                else:
                    self._line(memory, [(32, 72), (42, 82)], BG, 2)
                    self._line(memory, [(42, 72), (32, 82)], BG, 2)
                title = ("Notification sent" if count == 1 else "Notifications sent") if self.success else "Transfer stopped"
                title_x = 62
            else:
                title = "Notification on its way" if self.settling else "Preparing file" if stage == "Preparing" else "Sending to iPad"
            self._text(memory, title, (title_x, 57, 456, 94), 24, TEXT, True)
            self._line(memory, [(25, 104), (36, 104), (41, 110), (41, 124), (25, 124), (25, 104)], MUTED)
            self._line(memory, [(36, 104), (36, 111), (41, 111)], MUTED)
            self._text(memory, name, (53, 102, 456, 128), 16, TEXT,
                       flags=win32con.DT_SINGLELINE | win32con.DT_END_ELLIPSIS)
            if self.completed and not self.success:
                self._text(memory, self.error, (24, 137, 455, 208), 13, RED, flags=win32con.DT_WORDBREAK)
            else:
                percentage = 100 if self.completed else progress_percent(done, total)
                scale, unit = (1024**2, "MiB") if total >= 1024**2 else (1024, "KiB")
                detail = "Upload complete" if self.settling else "Ready to save and open" if self.completed else f"{done / scale:.1f} of {total / scale:.1f} {unit}"
                self._text(memory, detail, (24, 134, 383, 158), 13, MUTED)
                self._text(memory, f"{percentage}%", (390, 134, 456, 158), 13, MUTED, flags=win32con.DT_RIGHT)
                self._round(memory, (24, 169, 456, 176), 3, TRACK)
                if percentage:
                    self._round(memory, (24, 169, 24 + max(7, 432 * percentage / 100), 176), 3, GREEN if self.completed and not self.settling else BLUE)
                footer = "iPad notification may take a moment." if self.settling else "Tap the notification on iPad to open." if self.completed else {
                    "Preparing": "Checking original file", "Notifying": "Waiting for notification service",
                    "Queued": "Notification queued"}.get(stage, "Uploading original file")
                self._text(memory, footer, (24, 198, 389, 227), 12, MUTED)
            self._text(memory, "Close" if self.completed else "Cancel", (394, 198, 456, 229),
                       13, TEXT if self.hover_cancel else BLUE, flags=win32con.DT_RIGHT)
            win32gui.BitBlt(dc, 0, 0, width, height, memory, 0, 0, win32con.SRCCOPY)
        finally:
            if old_bitmap:
                win32gui.SelectObject(memory, old_bitmap)
            if bitmap:
                win32gui.DeleteObject(bitmap)
            if memory:
                win32gui.DeleteDC(memory)
            win32gui.EndPaint(hwnd, paint)

    def _hit(self, x, y):
        x, y = x / self.scale, y / self.scale
        return (428 <= x <= 468 and 12 <= y <= 48), (385 <= x <= 468 and 188 <= y <= 240)

    def _window_proc(self, hwnd, message, wparam, lparam):
        if message == win32con.WM_NCCALCSIZE:
            return 0
        if message == win32con.WM_ERASEBKGND:
            return 1
        if message == win32con.WM_MOUSEACTIVATE:
            return win32con.MA_NOACTIVATE
        if message == win32con.WM_PAINT:
            self._paint(hwnd)
            return 0
        if message == UPDATE:
            self._update()
            return 0
        if message in (win32con.WM_MOUSEMOVE, win32con.WM_LBUTTONUP):
            hit = self._hit(win32api.LOWORD(lparam), win32api.HIWORD(lparam))
            if message == win32con.WM_LBUTTONUP and any(hit):
                self.cancelled.set()
                win32gui.DestroyWindow(hwnd)
            elif hit != (self.hover_close, self.hover_cancel):
                self.hover_close, self.hover_cancel = hit
                win32gui.InvalidateRect(hwnd, None, False)
            return 0
        if message == win32con.WM_NCHITTEST:
            left, top, _, _ = win32gui.GetWindowRect(hwnd)
            x = ctypes.c_short(lparam & 0xffff).value - left
            y = ctypes.c_short((lparam >> 16) & 0xffff).value - top
            if y < self._px(48) and not any(self._hit(x, y)):
                return win32con.HTCAPTION
            return win32con.HTCLIENT
        if message == win32con.WM_TIMER and wparam == 2:
            kill_timer = ctypes.windll.user32.KillTimer
            kill_timer.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
            kill_timer(hwnd, 2)
            self.settling = False
            self._timer(1, CONFIRMATION_MS)
            self._update()
            return 0
        if message in (win32con.WM_CLOSE, win32con.WM_TIMER):
            if message == win32con.WM_CLOSE:
                self.cancelled.set()
            win32gui.DestroyWindow(hwnd)
            return 0
        if message == win32con.WM_DESTROY:
            self.hwnd = None
            win32gui.PostQuitMessage(0)
            return 0
        return win32gui.DefWindowProc(hwnd, message, wparam, lparam)

    def run(self, work):
        self._create()
        worker = threading.Thread(target=self._work, args=(work,), daemon=True, name="AdamsDropFileUpload")
        worker.start()
        try:
            win32gui.PumpMessages()
            worker.join(timeout=0.5)
            return 0 if self.completed and self.success else 1
        finally:
            self.cancelled.set()
            for handle in (*self.fonts.values(), *self.brushes.values(), *self.pens.values()):
                win32gui.DeleteObject(handle)
