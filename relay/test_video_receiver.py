"""Offline receiver checks; private temporary files, no clipboard changes."""
import hashlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "windows-client"))
import video_transfer
import receive_from_ipad as receiver
import tray_manager

VIDEO = b"\x00\x00\x00\x18ftypqt  " + bytes(range(256)) * 4


def response(data=VIDEO):
    result = Mock(status_code=200)
    result.headers = {"content-type": "video/quicktime", "content-length": str(len(VIDEO)),
                      "x-content-sha256": hashlib.sha256(VIDEO).hexdigest(),
                      "content-disposition": "attachment; filename*=UTF-8''..%2F..%2FOriginal.mov"}
    result.iter_content.return_value = (data[i:i + 71] for i in range(0, len(data), 71))
    return result


class VideoTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.config = {"receive_video_dir": str(self.directory)}
        reveal = patch.object(receiver, "reveal_file_in_explorer", return_value=True)
        self.reveal = reveal.start()
        self.addCleanup(reveal.stop)

    def test_exact_original_saved_inside_destination_without_overwriting(self):
        first = video_transfer.save_video(response(), self.config, lambda: False)
        second = video_transfer.save_video(response(), self.config, lambda: False)
        self.assertNotEqual(first, second)
        self.assertEqual(first.parent, self.directory.resolve())
        self.assertEqual(first.suffix, ".mov")
        self.assertEqual(first.read_bytes(), VIDEO)
        self.assertEqual(second.read_bytes(), VIDEO)
        self.assertFalse(list(self.directory.glob("*.part")))

    def test_corruption_and_truncation_leave_no_video_or_partial_file(self):
        for data in (VIDEO[:-1], VIDEO[:-1] + b"!", VIDEO + b"extra"):
            with self.assertRaises(ValueError):
                video_transfer.save_video(response(data), self.config, lambda: False)
            self.assertEqual(list(self.directory.iterdir()), [])

    def test_game_pause_and_network_failure_clean_partial_file(self):
        with self.assertRaises(InterruptedError):
            video_transfer.save_video(response(), self.config, lambda: True)
        def broken_download():
            yield VIDEO[:71]
            raise OSError("synthetic disconnect")
        interrupted = response()
        interrupted.iter_content.return_value = broken_download()
        with self.assertRaises(OSError):
            video_transfer.save_video(interrupted, self.config, lambda: False)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_integrity_metadata_and_size_required(self):
        for field, value in (("x-content-sha256", ""), ("content-length", "0"),
                             ("content-length", str(video_transfer.MAX_VIDEO_SIZE + 1))):
            result = response()
            result.headers[field] = value
            with self.assertRaises(ValueError):
                video_transfer.save_video(result, self.config, lambda: False)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_receiver_streams_and_notifies_without_touching_clipboard(self):
        result = response()
        self.config["notify_on_receive"] = True
        with patch.object(receiver.foreground_guard, "should_pause", return_value=False), \
             patch.object(receiver.requests, "get", return_value=result) as fetch, \
             patch.object(receiver.win32clipboard, "OpenClipboard") as clipboard, \
             patch.object(receiver, "tray_instance", Mock()) as tray:
            receiver.process_token("synthetic", "http://test", "synthetic", self.config)
            self.assertTrue(fetch.call_args.kwargs["stream"])
            clipboard.assert_not_called()
            result.close.assert_called_once()
            tray.show_balloon.assert_called_once()
            self.assertEqual(next(self.directory.iterdir()).read_bytes(), VIDEO)
            self.reveal.assert_called_once_with(tray.show_balloon.call_args.kwargs["reveal_path"], automatic=True)

    def test_video_auto_reveal_is_independent_of_notification_setting(self):
        self.config["notify_on_receive"] = False
        with patch.object(receiver.foreground_guard, "should_pause", return_value=False), \
             patch.object(receiver.requests, "get", return_value=response()), \
             patch.object(receiver, "tray_instance", None):
            receiver.process_token("synthetic", "http://test", "synthetic", self.config)
        self.reveal.assert_called_once()
        self.assertTrue(self.reveal.call_args.kwargs["automatic"])

    def test_video_saved_before_protection_starts_is_not_opened_later(self):
        path = self.directory / "original.mov"
        path.write_bytes(VIDEO)
        with patch.object(receiver.foreground_guard, "should_pause", side_effect=[False, True]), \
             patch.object(receiver.requests, "get", return_value=response()), \
             patch.object(receiver.video_transfer, "save_video", return_value=path):
            receiver.process_token("synthetic", "http://test", "synthetic", self.config)
        self.reveal.assert_not_called()
        self.assertEqual(path.read_bytes(), VIDEO)

    def test_automatic_reveal_rechecks_protection_before_shell_opens(self):
        with patch.object(tray_manager.foreground_guard, "should_pause", side_effect=[False, True]), \
             patch.object(tray_manager.pythoncom, "CoInitialize"), \
             patch.object(tray_manager.pythoncom, "CoUninitialize") as uninitialize, \
             patch.object(tray_manager.shell, "SHParseDisplayName", return_value=([], 0)), \
             patch.object(tray_manager.shell, "SHOpenFolderAndSelectItems") as shell_open:
            self.assertFalse(tray_manager.reveal_file_in_explorer(self.directory / "video.mov", automatic=True))
            shell_open.assert_not_called()
            uninitialize.assert_called_once()

    def test_screenshots_keep_separate_original_files_and_only_reveal_on_click(self):
        self.config["notify_on_receive"] = True
        received = []
        with patch.object(receiver.foreground_guard, "should_pause", return_value=False), \
             patch.object(receiver, "write_image_to_clipboard", return_value=(True, (2, 2))) as clipboard, \
             patch.object(receiver, "tray_instance", Mock()) as tray:
            for color in ("blue", "red"):
                encoded = io.BytesIO()
                receiver.Image.new("RGB", (2, 2), color).save(encoded, "PNG")
                data = encoded.getvalue()
                item = Mock(status_code=200, content=data, headers={"content-type": "image/png"})
                with patch.object(receiver.requests, "get", return_value=item):
                    receiver.process_token("synthetic", "http://test", "synthetic", self.config)
                clipboard.assert_called_with(data)
                path = Path(tray.show_balloon.call_args.kwargs["reveal_path"])
                self.assertEqual(path.read_bytes(), data)
                received.append((path, data))
                self.reveal.assert_not_called()
            self.assertNotEqual(received[0][0], received[1][0])
            self.assertEqual(received[0][0].read_bytes(), received[0][1])
            # Use the real click handler; no media/image viewer is invoked.
            notification = tray_manager.TrayIcon.__new__(tray_manager.TrayIcon)
            notification.last_received_file = str(received[1][0])
            with patch.object(tray_manager, "reveal_file_in_explorer") as reveal, \
                 patch.object(tray_manager.os, "startfile") as viewer:
                notification._wnd_proc(0, tray_manager.WM_TRAY_NOTIFY, 0, tray_manager.NIN_BALLOONUSERCLICK)
                reveal.assert_called_once_with(str(received[1][0]))
                viewer.assert_not_called()

    def test_image_save_failure_preserves_clipboard_copy(self):
        self.config["notify_on_receive"] = True
        item = Mock(status_code=200, content=b"synthetic", headers={"content-type": "image/png"})
        with patch.object(receiver.foreground_guard, "should_pause", return_value=False), \
             patch.object(receiver.requests, "get", return_value=item), \
             patch.object(receiver, "write_image_to_clipboard", return_value=(True, (2, 2))) as clipboard, \
             patch.object(receiver, "save_received_image", side_effect=OSError("synthetic failure")), \
             patch.object(receiver, "tray_instance", Mock()) as tray:
            receiver.process_token("synthetic", "http://test", "synthetic", self.config)
            clipboard.assert_called_once()
            self.assertIsNone(tray.show_balloon.call_args.kwargs["reveal_path"])
            self.reveal.assert_not_called()


if __name__ == "__main__":
    unittest.main()
