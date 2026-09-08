import sys
import unittest
from pathlib import Path
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'windows-client'))
import send_to_ipad as s
import sync_state as state

class SenderTests(unittest.TestCase):
 def setUp(self):
  self.origin_patch=patch.object(s.clipboard_origin,'is_received',return_value=False)
  self.origin_patch.start();self.addCleanup(self.origin_patch.stop)
  state.last_received_sequence=None; state.last_sent_sequence=None
  state.last_received_time=10**15; state.last_received_hash='old'
 def run_send(self,seq,silent=True):
  response=Mock(status_code=200,headers={})
  with patch.object(s,'load_config',return_value={'api_key':'synthetic','relay_url':'http://test'}), patch.object(s.ctypes.windll.user32,'GetClipboardSequenceNumber',return_value=seq), patch.object(s,'get_clipboard_content',return_value=('text/plain',b'test','Text (4 characters)')), patch.object(s.http_session,'post',return_value=response) as post:
   result=s.send_clipboard(silent=silent)
   return result,post.call_count
 def test_receive_echo(self):
  state.last_received_sequence=7
  self.assertEqual(self.run_send(7)[1],0)
 def test_new_copy_immediately_after_receive(self):
  state.last_received_sequence=7
  self.assertTrue(self.run_send(8)[0][0])
 def test_duplicate_event(self):
  state.last_sent_sequence=8
  self.assertEqual(self.run_send(8)[1],0)
 def test_manual_resend(self):
  state.last_sent_sequence=8
  self.assertTrue(self.run_send(8,silent=False)[0][0])
 def test_repeat_content_new_copy(self):
  self.assertTrue(self.run_send(8)[0][0])
  self.assertTrue(self.run_send(9)[0][0])
 def test_origin_marker_suppresses_changed_sequence(self):
  with patch.object(s.clipboard_origin,'is_received',return_value=True):
   self.assertEqual(self.run_send(999)[1],0)
 def test_manual_send_ignores_origin_marker(self):
  with patch.object(s.clipboard_origin,'is_received',return_value=True):
   self.assertTrue(self.run_send(999,silent=False)[0][0])
unittest.main()
