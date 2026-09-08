"""Origin travels with imported clipboard data until a new local copy replaces it."""
import win32clipboard

def mark_received():
    # Caller holds the clipboard open. This is an extra format, not visible text.
    win32clipboard.SetClipboardData(
        win32clipboard.RegisterClipboardFormat('AdamsDrop.Clipboard.RemoteOrigin.v1'), b'ipad\0')

def is_received():
    win32clipboard.OpenClipboard()
    try:
        fmt = win32clipboard.RegisterClipboardFormat('AdamsDrop.Clipboard.RemoteOrigin.v1')
        return win32clipboard.IsClipboardFormatAvailable(fmt)
    finally:
        win32clipboard.CloseClipboard()
