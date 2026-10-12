"""Synthetic Windows file sends; no device, clipboard, notifications or picker UI."""
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "windows-client"))
import send_files_to_ipad as sender


class FileSendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "test λ.png"
        self.data = b"\x89PNG\r\n\x1a\n\x00\xffsynthetic"
        self.path.write_bytes(self.data)
        self.guard = patch.object(sender.foreground_guard, "should_pause", return_value=False)
        self.guard.start()
        self.addCleanup(self.guard.stop)
        self.config = {"relay_url": "http://test", "api_key": "synthetic"}

    def test_original_bytes_name_length_and_checksum(self):
        session = Mock()
        def post(url, **kwargs):
            self.assertTrue(url.endswith("source=windows&kind=file"))
            self.assertEqual(b"".join(kwargs["data"]), self.data)
            self.assertEqual(len(kwargs["data"]), len(self.data))
            self.assertEqual(kwargs["headers"]["X-Content-SHA256"], hashlib.sha256(self.data).hexdigest())
            self.assertEqual(kwargs["headers"]["X-Filename"], "test%20%CE%BB.png")
            return Mock(status_code=200)
        session.post.side_effect = post
        self.assertEqual(sender.send_files([self.path], config=self.config, session=session), 1)

    def test_pause_aborts_before_network_and_during_upload(self):
        session = Mock()
        with patch.object(sender.foreground_guard, "should_pause", return_value=True):
            with self.assertRaises(InterruptedError):
                sender.send_files([self.path], config=self.config, session=session)
            with self.path.open("rb") as file:
                with self.assertRaises(InterruptedError):
                    list(sender.Upload(file, len(self.data)))
        session.post.assert_not_called()

    def test_folder_batch_limit_and_size_rejected(self):
        session = Mock()
        for paths in ([Path(self.temp.name)], [self.path] * 17):
            with self.assertRaises(ValueError):
                sender.send_files(paths, config=self.config, session=session)
        with patch.object(sender, "MAX_SIZE", 2):
            with self.assertRaises(ValueError):
                sender.send_files([self.path], config=self.config, session=session)
        session.post.assert_not_called()

    def test_partial_batch_failure_is_explicit_and_releases_lock(self):
        session = Mock()
        session.post.side_effect = [Mock(status_code=200), Mock(status_code=503)]
        with self.assertRaisesRegex(RuntimeError, "1 file.*remaining transfer failed"):
            sender.send_files([self.path, self.path], config=self.config, session=session)
        self.assertFalse(sender.sync_state.send_lock.locked())

    def test_native_picker_multiselect_and_cancel(self):
        import win32gui
        with patch.object(win32gui, "GetOpenFileNameW", return_value=("C:\\test\0a.pdf\0b.png", "", 0)):
            self.assertEqual(sender.select_files(), ["C:\\test\\a.pdf", "C:\\test\\b.png"])
        with patch.object(win32gui, "GetOpenFileNameW", side_effect=win32gui.error(0, "GetOpenFileName", "cancel")):
            self.assertEqual(sender.select_files(), [])

    def test_progress_reports_actual_bytes_and_publication_completion(self):
        events = []
        def post(url, **kwargs):
            self.assertEqual(b"".join(kwargs["data"]), self.data)
            self.assertEqual(events[-1][0], "Notifying")
            return Mock(status_code=200)
        session = Mock()
        session.post.side_effect = post
        sender.send_files([self.path], config=self.config, session=session,
                          progress=lambda *event: events.append(event))
        self.assertEqual(events[0][0], "Preparing")
        self.assertEqual(events[-1][0], "Queued")
        uploaded = [event for event in events if event[0] == "Uploading"]
        self.assertEqual(uploaded[-1][1:3], (len(self.data), len(self.data)))
        self.assertTrue(all(event[3:] == (self.path.name, 1, 1) for event in events))

    def test_cancelled_transfer_does_not_publish(self):
        session = Mock()
        with self.assertRaisesRegex(InterruptedError, "cancelled"):
            sender.send_files([self.path], config=self.config, session=session, cancelled=lambda: True)
        session.post.assert_not_called()
        self.assertFalse(sender.sync_state.send_lock.locked())

    def test_explorer_selection_and_ambiguous_tabs(self):
        import win32gui
        import win32com.client
        item = Mock(Path=str(self.path), IsFileSystem=True)
        virtual = Mock(IsFileSystem=False)
        window = Mock(HWND=42)
        window.Document.SelectedItems.return_value = [item, virtual]
        shell = Mock()
        shell.Windows.return_value = [window]
        with patch.object(win32gui, "GetForegroundWindow", return_value=42), \
             patch.object(win32gui, "GetClassName", return_value="CabinetWClass"), \
             patch.object(win32gui, "FindWindowEx", return_value=0), \
             patch.object(win32com.client, "Dispatch", return_value=shell):
            self.assertEqual(sender.selected_explorer_files(), [str(self.path)])
            shell.Windows.return_value = [window, window]
            self.assertEqual(sender.selected_explorer_files(), [])
            shell.Windows.return_value = [Mock(HWND=99)]
            self.assertEqual(sender.selected_explorer_files(), [])

    def test_windows11_active_tab_not_first_com_entry(self):
        import win32gui
        import win32com.client
        active = Mock(HWND=42)
        inactive = Mock(HWND=42)
        active.Document.SelectedItems.return_value = [Mock(Path=str(self.path), IsFileSystem=True)]
        inactive.Document.SelectedItems.return_value = [Mock(Path="C:\\wrong.pdf", IsFileSystem=True)]
        active._oleobj_.QueryInterface.return_value.QueryService.return_value.GetWindow.return_value = 202
        inactive._oleobj_.QueryInterface.return_value.QueryService.return_value.GetWindow.return_value = 101
        shell = Mock()
        shell.Windows.return_value = [inactive, active]
        with patch.object(win32gui, "GetForegroundWindow", return_value=42) as foreground, \
             patch.object(win32gui, "GetClassName", return_value="CabinetWClass"), \
             patch.object(win32gui, "FindWindowEx", return_value=202) as tab, \
             patch.object(win32com.client, "Dispatch", return_value=shell):
            self.assertEqual(sender.selected_explorer_files(), [str(self.path)])
            active.Document.SelectedItems.return_value = []
            self.assertEqual(sender.selected_explorer_files(), [])  # Never use inactive tab selection.
            active.Document.SelectedItems.return_value = [Mock(Path=str(self.path), IsFileSystem=True)]
            tab.side_effect = [202, 101]
            self.assertEqual(sender.selected_explorer_files(), [])
            tab.side_effect = None
            foreground.side_effect = [42, 99]
            self.assertEqual(sender.selected_explorer_files(), [])

    def test_common_and_unknown_extensions_are_original_files(self):
        for name, data in [("clip.mp4", b"\x00\x00\x00\x18ftypisom\x00\xff"),
                           ("clip.mov", b"\x00\x00\x00\x18ftypqt  \x00\xff"),
                           ("data.json", b'{"value":"\\u03bb"}\r\n'),
                           ("notes.txt", b"\xef\xbb\xbfhello\r\nworld\r\n"),
                           ("table.csv", b"name,value\r\nsample,001.20\r\n"),
                           ("archive.zip", b"PK\x03\x04\x00\xff"),
                           ("unknown.custom", b"\x00\xff\xfe"), ("empty.txt", b"")]:
            with self.subTest(name=name):
                path = Path(self.temp.name) / name
                path.write_bytes(data)
                def post(url, **kwargs):
                    body = kwargs["data"]
                    self.assertEqual(body if isinstance(body, bytes) else b"".join(body), data)
                    self.assertTrue(url.endswith("source=windows&kind=file"))
                    self.assertEqual(kwargs["headers"]["X-Filename"], name)
                    self.assertEqual(kwargs["headers"]["X-Content-SHA256"], hashlib.sha256(data).hexdigest())
                    return Mock(status_code=200)
                session = Mock()
                session.post.side_effect = post
                self.assertEqual(sender.send_files([path], config=self.config, session=session), 1)


if __name__ == "__main__":
    unittest.main()
