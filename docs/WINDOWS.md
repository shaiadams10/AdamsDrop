# Windows setup



1. Install Apple Devices from Microsoft Store and Python (tested with 3.14). Keep the same Windows user for pairing and the listener.

2. From the repository root:



```powershell

python -m venv .venv

.\.venv\Scripts\Activate.ps1

python -m pip install -r windows-client/requirements-build.txt

.\windows-client\build.ps1

Copy-Item windows-client/config.example.json dist/AdamsDrop/config.json

```



3. Edit the local config beside AdamsDrop.exe. Set relay_url, api_key, ntfy_sse_url, and the paired iPad UDID in direct_device. Leave direct_from_ipad false.

4. Run `windows-client/start.ps1` or double-click `dist/AdamsDrop/AdamsDrop.exe`. Startup is manual by default. Optionally run `windows-client/install_startup_task.ps1` for login-only startup 30 seconds after sign-in; it never installs a repeating recovery trigger or failure restart.

5. Copy text and a screenshot. Expect a receipt after exact iPad clipboard read-back. The initial connection is slower.



To run from source instead, configure windows-client/config.json and run `python windows-client/receive_from_ipad.py`. Do not run it alongside the packaged executable.



The process is AdamsDrop.exe. The tray says Adams’Drop. start.ps1 launches the executable directly and stop.ps1 stops it; uninstall_startup_task.ps1 removes registration without deleting source, configuration or pairing data.



Packaging is unsigned. Windows may prompt before running a locally built binary. The build script does not include your config; never zip a configured dist directory for public distribution.


## Upgrading a configured build

Stop and disable the `Adams'Drop` scheduled task before rebuilding. Save config.json outside dist (for example in ignored .local/), then remove it from dist. The build replaces dist/AdamsDrop. Restore config.json after a successful build. Launch with start.ps1; install the optional login task only if wanted. Keep a previous complete build for rollback.

## Quiet operation

Exit in the tray menu closes the application. No automatic relaunch is installed by default. The optional login task starts once per login only. Background helpers launch hidden; the tray takes focus only when its menu is explicitly opened. Incoming Windows notifications default off. The process uses below-normal priority, drops overlapping send requests (copy again when ready), rotates listener/sender logs, and exits if its tray fails. These measures reduce interference; they do not certify driver or game stability.

Full-screen protection is enabled: Windows busy/exclusive-game/presentation state and foreground borderless full-screen geometry are checked when events occur. New clipboard sends, incoming fetches/writes, receipts and startup warmup are skipped during that activity. Skipped items are not queued; copy/send again afterwards. There is no polling loop, keyboard hook, simulated keypress or game injection. Ordinary desktop copying runs below normal priority. Windows notifications remain off unless explicitly configured, including send errors. PNG encoding finishes before opening the Windows clipboard.

Limits: this is a full-screen heuristic, not universal game detection; ordinary windowed games may not be detected. Work already in progress may finish as a game starts. Use tray Exit for no AdamsDrop process or transfer activity. Zero performance impact or driver/game stability cannot be guaranteed.
