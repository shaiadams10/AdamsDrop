import sys
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'windows-client'))
import send_to_ipad as sender
import direct_to_ipad as direct
import sync_state

class BacklogTests(unittest.TestCase):
 def setUp(self):
  guard=patch.object(sender.foreground_guard,'should_pause',return_value=False)
  guard.start();self.addCleanup(guard.stop)

 def test_busy_send_returns_without_capturing_or_queuing(self):
  with sync_state.send_lock, patch.object(sender, '_send_clipboard') as send:
   for silent in (True, False):
    self.assertEqual(sender.send_clipboard(silent), (False, 'Transfer busy; copy again when ready'))
   send.assert_not_called()

 def test_send_exception_releases_lock(self):
  with patch.object(sender, '_send_clipboard', side_effect=RuntimeError('synthetic')):
   with self.assertRaises(RuntimeError):
    sender.send_clipboard(True)
  self.assertTrue(sync_state.send_lock.acquire(blocking=False))
  sync_state.send_lock.release()

 def test_direct_setup_exception_does_not_publish_automatic_fallback(self):
  config={'api_key':'synthetic','relay_url':'http://test','direct_to_ipad':True}
  with patch.object(sender,'load_config',return_value=config), \
       patch.object(sender,'get_clipboard_content',return_value=('text/plain',b'test','test')), \
       patch.object(sender.clipboard_origin,'is_received',return_value=False), \
       patch.object(sender.ctypes.windll.user32,'GetClipboardSequenceNumber',return_value=9002), \
       patch.object(direct,'send',side_effect=ImportError('synthetic missing dependency')), \
       patch.object(sender.http_session,'post') as post:
   sync_state.last_received_sequence=None;sync_state.last_sent_sequence=None
   self.assertFalse(sender.send_clipboard(silent=True)[0]);post.assert_not_called()

 def test_offline_auto_skips_but_manual_falls_back(self):
  config={'api_key':'synthetic','relay_url':'http://test','direct_to_ipad':True}
  with patch.object(sender,'load_config',return_value=config), \
       patch.object(sender,'get_clipboard_content',return_value=('text/plain',b'test','test')), \
       patch.object(sender.clipboard_origin,'is_received',return_value=False), \
       patch.object(sender.ctypes.windll.user32,'GetClipboardSequenceNumber',return_value=9001), \
       patch.object(direct,'send',return_value=False), \
       patch.object(direct,'last_failure','unavailable'), \
       patch.object(sender.http_session,'post',return_value=Mock(status_code=200,headers={})) as post:
   sync_state.last_received_sequence=None;sync_state.last_sent_sequence=None
   self.assertFalse(sender.send_clipboard(silent=True)[0]);post.assert_not_called()
   self.assertTrue(sender.send_clipboard(silent=False)[0]);post.assert_called_once()

if __name__=='__main__':unittest.main()
