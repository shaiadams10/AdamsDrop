# iPad setup

Enable Developer Mode, connect USB, unlock and trust the Windows PC. Open Apple Devices. Using the same Python environment/user as the listener:

```powershell
python -m pymobiledevice3 lockdown wifi-connections on
python -m pymobiledevice3 lockdown remotepairing
python -m pymobiledevice3 mounter auto-mount
```

Separate developer pairing is essential. Pairing completion may raise RemotePairingCompletedError: reconnect and verify. Put the selected device UDID in local config only. Never print or publish pairing records. After setup, use the same LAN without USB. Unlock once after reboot. The client remounts missing developer support over the trusted Wi-Fi tunnel when available.

Subscribe to clip-to-ipad on your ntfy server. Keep compatibility Shortcut names **SetClipboard** and **SendToWindows**; notification titles say Adams’Drop. Changing a Shortcut name without changing encoded actions breaks fallback.

SetClipboard: Shortcut Input URL -> Get Contents of URL -> Copy to Clipboard. Used for large-image/manual fallback. The URL contains a single-use token, not a reusable API key.

SendToWindows: Get Clipboard -> POST raw text/image to your relay /send?source=ipad, with the private X-Api-Key header and appropriate Content-Type. Preserve existing working actions when upgrading. Keep credentials in local Shortcut configuration, never screenshots or Git. Grant local-network and paste permissions as needed.

No custom iPad app is installed. Native background iPad-copy monitoring failed testing and is not shipped.
