"""LIVE test: sends synthetic iPad-origin items through the relay to Windows.

Requires the configured tray app to be running. Overwrites the Windows clipboard
and may show notifications. Does not require or imitate native iPad monitoring.
"""
import io
import json
import time
from pathlib import Path

import requests
import win32clipboard
from PIL import Image

import clipboard_origin


def main():
    config = json.loads((Path(__file__).parent / 'config.json').read_text(encoding='utf-8'))
    picture = Image.new('RGB', (128, 80), (30, 130, 180))
    encoded = io.BytesIO()
    picture.save(encoded, 'PNG')
    sample = 'AdamsDrop incoming test ' + str(time.time_ns())
    for kind, payload in [('text/plain', sample.encode()), ('image/png', encoded.getvalue())]:
        response = requests.post(config['relay_url'].rstrip('/') + '/send?source=ipad',
                                 headers={'X-Api-Key': config['api_key'], 'Content-Type': kind},
                                 data=payload, timeout=10)
        assert response.status_code == 200, f'Relay returned {response.status_code}'
        matched = False
        for _ in range(100):
            time.sleep(.1)
            try:
                win32clipboard.OpenClipboard()
                try:
                    if kind == 'text/plain':
                        matched = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT) == sample
                    else:
                        image = Image.open(io.BytesIO(win32clipboard.GetClipboardData(
                            win32clipboard.RegisterClipboardFormat('PNG'))))
                        matched = image.size == picture.size and image.convert('RGB').tobytes() == picture.tobytes()
                finally:
                    win32clipboard.CloseClipboard()
                if matched:
                    break
            except Exception:
                pass
        assert matched, f'{kind}: incoming clipboard mismatch or timeout'
        assert clipboard_origin.is_received(), 'Missing echo-suppression marker'
        print(f'{kind}: incoming data and echo-suppression marker verified')


if __name__ == '__main__':
    main()
