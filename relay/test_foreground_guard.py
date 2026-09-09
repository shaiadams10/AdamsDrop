"""Synthetic checks; no clipboard changes, device traffic, or visible windows."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'windows-client'))
import foreground_guard as guard
import send_to_ipad as sender
import receive_from_ipad as receiver
import tray_manager


class GuardTests(unittest.TestCase):
    def test_windows_busy_states_pause(self):
        for state in (1, 2, 3, 4):
            with patch.object(guard, '_notification_state', return_value=state):
                self.assertTrue(guard.should_pause())

    def test_query_failure_skips_work(self):
        with patch.object(guard, '_notification_state', side_effect=OSError):
            self.assertTrue(guard.should_pause())

    def test_borderless_secondary_monitor_and_normal_window(self):
        with patch.object(guard, '_notification_state', return_value=5), \
             patch.object(guard.win32gui, 'GetForegroundWindow', return_value=1), \
             patch.object(guard.win32gui, 'GetClassName', return_value='Synthetic'), \
             patch.object(guard.win32gui, 'GetWindowLong', return_value=0) as style, \
             patch.object(guard.win32gui, 'GetWindowRect', return_value=(-1920, 0, 0, 1080)), \
             patch.object(guard.win32api, 'MonitorFromWindow', return_value=2), \
             patch.object(guard.win32api, 'GetMonitorInfo', return_value={'Monitor': (-1920, 0, 0, 1080)}):
            self.assertTrue(guard.should_pause())
            style.return_value = guard.win32con.WS_CAPTION
            self.assertFalse(guard.should_pause())

    def test_busy_copy_does_not_capture_or_send(self):
        with patch.object(guard, 'should_pause', return_value=True), \
             patch.object(sender, '_send_clipboard') as send:
            for silent in (True, False):
                self.assertFalse(sender.send_clipboard(silent)[0])
            send.assert_not_called()

    def test_busy_receive_does_not_fetch_decode_or_touch_clipboard(self):
        with patch.object(guard, 'should_pause', return_value=True), \
             patch.object(receiver.requests, 'get') as fetch, \
             patch.object(receiver.win32clipboard, 'OpenClipboard') as clipboard, \
             patch.object(receiver.Image, 'open') as decode:
            receiver.process_token('synthetic', 'http://test', 'synthetic')
            self.assertFalse(receiver.write_text_to_clipboard('synthetic'))
            self.assertFalse(receiver.write_image_to_clipboard(b'synthetic')[0])
            fetch.assert_not_called(); clipboard.assert_not_called(); decode.assert_not_called()

    def test_busy_clipboard_event_does_not_spawn_timer(self):
        tray = tray_manager.TrayIcon.__new__(tray_manager.TrayIcon)
        tray.auto_send = True
        with patch.object(guard, 'should_pause', return_value=True), \
             patch.object(tray_manager.threading, 'Timer') as timer:
            tray._wnd_proc(0, tray_manager.WM_CLIPBOARDUPDATE, 0, 0)
            timer.assert_not_called()

    def test_disabled_notifications_do_not_launch_powershell(self):
        with patch.object(guard, 'should_pause', return_value=False), \
             patch.object(sender, 'load_config', return_value={'notify_on_send': False}), \
             patch.object(sender.subprocess, 'run') as run:
            sender.show_toast('Synthetic error', 'Synthetic error')
            run.assert_not_called()

    def test_switching_fullscreen_during_capture_drops_send(self):
        with patch.object(guard, 'should_pause', side_effect=[False, True]), \
             patch.object(sender, 'load_config', return_value={'api_key': 'synthetic'}), \
             patch.object(sender, 'get_clipboard_content', return_value=('text/plain', b'x', 'test')), \
             patch.object(sender.ctypes.windll.user32, 'GetClipboardSequenceNumber', return_value=321), \
             patch.object(sender.http_session, 'post') as post:
            self.assertFalse(sender.send_clipboard(False)[0])
            post.assert_not_called()

    def test_receive_image_encoding_precedes_clipboard_lock(self):
        import io
        image = receiver.Image.new('RGB', (2, 2), 'blue')
        data = io.BytesIO(); image.save(data, 'PNG')
        locked = False
        original_save = receiver.Image.Image.save
        def save(img, *args, **kwargs):
            self.assertFalse(locked, 'Image encoding held the Windows clipboard')
            return original_save(img, *args, **kwargs)
        def opened():
            nonlocal locked
            locked = True
        def closed():
            nonlocal locked
            locked = False
        with patch.object(guard, 'should_pause', return_value=False), \
             patch.object(receiver.Image.Image, 'save', save), \
             patch.object(receiver.win32clipboard, 'OpenClipboard', side_effect=opened), \
             patch.object(receiver.win32clipboard, 'CloseClipboard', side_effect=closed), \
             patch.object(receiver.win32clipboard, 'EmptyClipboard'), \
             patch.object(receiver.win32clipboard, 'SetClipboardData'), \
             patch.object(receiver.clipboard_origin, 'mark_received'):
            self.assertTrue(receiver.write_image_to_clipboard(data.getvalue())[0])
        self.assertFalse(locked)


if __name__ == '__main__':
    unittest.main()
