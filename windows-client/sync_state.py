"""Shared synchronization state to coordinate clipboard read/write events and prevent feedback loops."""
import time

last_received_hash = None
last_received_time = 0.0
last_sent_hash = None
auto_send_enabled = True

import threading
clipboard_lock = threading.RLock()
send_lock = threading.Lock()
last_received_sequence = None
last_sent_sequence = None
