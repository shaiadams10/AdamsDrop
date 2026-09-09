"""Synthetic tests: oversized data must never reach the direct SET path."""
import io
import random
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'windows-client'))
from PIL import Image
import direct_to_ipad as direct
import send_to_ipad as sender
import clipboard_receipt

class Limits(unittest.TestCase):
    def setUp(self):
        guard = patch.object(sender.foreground_guard, 'should_pause', return_value=False)
        guard.start(); self.addCleanup(guard.stop)

    def test_large_rgb_stays_lossless_and_uses_fallback(self):
        image = Image.frombytes('RGB', (900, 900), random.Random(42).randbytes(900*900*3))
        stream = io.BytesIO(); image.save(stream, format='PNG')
        payload = stream.getvalue()
        with patch.object(direct.asyncio, 'run_coroutine_threadsafe') as submit:
            self.assertFalse(direct.send(payload, 'image/png', 'synthetic-device'))
            submit.assert_not_called()
        config = {'api_key':'synthetic', 'relay_url':'http://test', 'direct_to_ipad':True}
        with patch.object(sender,'load_config',return_value=config), \
             patch.object(sender,'get_clipboard_content',return_value=('image/png',payload,'synthetic image')), \
             patch.object(sender.ctypes.windll.user32,'GetClipboardSequenceNumber',return_value=98765), \
             patch.object(sender.http_session,'post') as post, \
             patch.object(clipboard_receipt,'notify') as notify:
            post.return_value.status_code=200; post.return_value.headers={}
            self.assertTrue(sender.send_clipboard()[0])
            self.assertEqual(post.call_args.kwargs['data'],payload)
            notify.assert_not_called()

    def test_large_text_never_writes(self):
        with patch.object(direct.asyncio, 'run_coroutine_threadsafe') as submit:
            self.assertFalse(direct.send(b'x'*1_000_001,'text/plain','synthetic-device'))
            submit.assert_not_called()

if __name__ == '__main__': unittest.main()
