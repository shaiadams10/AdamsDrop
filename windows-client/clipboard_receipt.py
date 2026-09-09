"""One bounded notification worker, independent of clipboard transfer latency."""
import queue
import threading
import logging
import requests
import time
import foreground_guard

_pending = queue.Queue(maxsize=1)
_lock = threading.Lock()
_worker = None
_last_queued = 0.0

def _run():
    with requests.Session() as session:
        while True:
            url, key, kind, created = _pending.get()
            try:
                if time.monotonic() - created > 5 or foreground_guard.should_pause():
                    continue
                session.post(url + '/copied', params={'kind': kind},
                             headers={'X-Api-Key': key}, timeout=5).raise_for_status()
            except Exception as exc:
                logging.getLogger('ClipboardDirect').warning('Receipt failed (%s)', type(exc).__name__)
            finally:
                _pending.task_done()

def notify(url, key, content_type):
    global _worker, _last_queued
    with _lock:
        now = time.monotonic()
        if now - _last_queued < 2:
            return
        if _worker is None:
            _worker = threading.Thread(target=_run, daemon=True, name='ClipboardReceipt')
            _worker.start()
        try:
            _pending.put_nowait((url, key, 'image' if content_type.startswith('image/') else 'text', now))
            _last_queued = now
        except queue.Full:
            # An existing receipt already signals a recent copy; never build a backlog.
            pass
