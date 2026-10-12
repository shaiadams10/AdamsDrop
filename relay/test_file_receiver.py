"""Offline original-file receiver checks: no device traffic, Shell or clipboard changes."""
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "windows-client"))
import file_transfer
import receive_from_ipad as receiver


def response(data, name, content_type="application/octet-stream"):
    result = Mock(status_code=200)
    result.headers = {"content-type": content_type, "content-length": str(len(data)),
                      "x-content-sha256": hashlib.sha256(data).hexdigest(), "x-adamsdrop-kind": "file",
                      "content-disposition": "attachment; filename*=UTF-8''" + name}
    result.iter_content.return_value = iter((data[:4], data[4:]))
    return result


class FileTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.config = {"receive_file_dir": str(self.directory), "notify_on_receive": True}

    def test_original_bytes_extension_and_unique_names_in_configured_folder(self):
        for name, data in [("report.pdf", b"%PDF-1.7\x00\xff"), ("values.csv", b"a,b\r\n001,2.00\r\n"),
                           ("settings.JSON", b'{"escaped":"\\u00e9"}\r\n'), ("empty.txt", b"")]:
            first = file_transfer.save_file(response(data, "..%2F" + name), self.config, lambda: False)
            second = file_transfer.save_file(response(data, name), self.config, lambda: False)
            self.assertEqual(first.read_bytes(), data)
            self.assertEqual(first.parent, self.directory.resolve())
            self.assertEqual(first.suffix, Path(name).suffix)
            self.assertNotEqual(first, second)
        self.assertFalse(list(self.directory.glob("*.part")))

    def test_generic_files_notify_without_clipboard_or_automatic_reveal(self):
        item = response(b'{"original":true}\r\n', "sample.json", "application/json")
        with patch.object(receiver.foreground_guard, "should_pause", return_value=False), \
             patch.object(receiver.requests, "get", return_value=item), \
             patch.object(receiver.win32clipboard, "OpenClipboard") as clipboard, \
             patch.object(receiver, "reveal_file_in_explorer") as reveal, \
             patch.object(receiver, "tray_instance", Mock()) as tray:
            receiver.process_token("synthetic", "http://test", "synthetic", self.config)
            clipboard.assert_not_called()
            reveal.assert_not_called()
            tray.show_balloon.assert_called_once()
            self.assertEqual(Path(tray.show_balloon.call_args.kwargs["reveal_path"]).suffix, ".json")
            item.close.assert_called_once()

    def test_corrupt_and_paused_downloads_leave_no_final_or_partial_file(self):
        for paused in (False, True):
            item = response(b"original", "report.csv")
            item.iter_content.return_value = iter([b"changed!"])
            with self.assertRaises((ValueError, InterruptedError)):
                file_transfer.save_file(item, self.config, lambda: paused)
            self.assertEqual(list(self.directory.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
