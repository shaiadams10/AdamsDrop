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

4. Run `windows-client/install_startup_task.ps1`. The task Adams'Drop runs the executable five seconds after login with a one-minute recovery trigger and no execution time limit.

5. Copy text and a screenshot. Expect a receipt after exact iPad clipboard read-back. The initial connection is slower.



To run from source instead, configure windows-client/config.json and run `python windows-client/receive_from_ipad.py`. Do not run it alongside the packaged executable.



The process is AdamsDrop.exe. The tray says Adams’Drop. start.ps1 and stop.ps1 control the installed task; uninstall_startup_task.ps1 removes registration without deleting source, configuration or pairing data.



Packaging is unsigned. Windows may prompt before running a locally built binary. The build script does not include your config; never zip a configured dist directory for public distribution.


## Upgrading a configured build

Stop and disable the `Adams'Drop` scheduled task before rebuilding. Save config.json outside dist (for example in ignored .local/), then remove it from dist. The build replaces dist/AdamsDrop. Restore config.json after a successful build and rerun install_startup_task.ps1. Keep a previous complete build for rollback.
