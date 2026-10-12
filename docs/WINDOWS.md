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

## Send original files to iPad

Set up **SaveToFiles** on the iPad as described in IPAD.md. Run `windows-client/install_sendto.ps1` once to add **Send to → AdamsDrop - iPad** to Explorer's classic context menu (Windows 11: **Show more options**). The tray also has **Send Files to iPad…**, opening a native file picker with multiple selection. Explorer invokes the same executable with `--send-files <paths>`; that command runs once, below normal priority, without starting another clipboard listener or adding a schedule. It works even when the tray is closed.

The command sends original files through the existing relay, with length, original filename and a SHA-256 upload check. It never changes either clipboard. Up to sixteen files may be selected; each creates a separate notification to tap on iPad. Files/folders over the limits are rejected; folders must be archived first. Errors appear only for the explicitly requested send and outside protected full-screen activity. A successful command means the relay has queued the notifications; the iPad save is not acknowledged to Windows. No automatic retry or offline backlog is added. To remove the context-menu entry, delete **AdamsDrop - iPad** from `shell:sendto`.

## Stream Deck and transfer progress

Assign **System → Open** in Stream Deck to **dist/AdamsDrop/AdamsDropSend.exe**. This entry point needs no arguments: select files in Explorer, leave that window in front, then press the hardware button. It reads the **active tab**, including Windows 11 windows with several tabs, by matching the Shell browser's tab window to the active child in the frame. Selections in other tabs/windows are ignored. If there is no usable selection, the layout is unknown/ambiguous, or focus/tab changes during lookup, it opens a picker. Desktop icons and files open inside another application also use the picker. `AdamsDrop.exe --send-selected` provides the same behavior for other launchers. `windows-client/install_send_button.ps1` optionally creates an **AdamsDrop - Send to iPad** desktop shortcut. No Stream Deck plug-in, keyboard hook or extra startup task is required.

File sending accepts **any file extension**: PDF, images, MP4/MOV and other videos, JSON, TXT, CSV, Office documents, audio, ZIP and unknown formats. Original bytes are streamed with no conversion, text parsing or newline changes. Files have a **2 GiB per-file** limit and up to **16 files per send**, within the relay's shared **4 GiB** temporary capacity. Folders must be zipped first. The iPad saves the file in the chosen folder even when its format requires another app to open; Quick Look preview/playback depends on iPad format and codec support. Very large Shortcut downloads need device testing.

All explicit file sends now display a compact charcoal card with rounded Windows 11 corners, a filename, blue progress bar and green confirmation. It uses native drawing with no web runtime or bitmap background, without activating it or stealing keyboard focus. **Preparing** reports checksum progress; **Uploading** reports bytes actually handed to the HTTP client; **Notifying** waits for the existing relay/ntfy request to complete. Once publication succeeds, **Notification on its way** keeps the blue card visible for three seconds, showing **Upload complete / 100%**, then green **Notification sent** appears for about two seconds before closing. This grace period only affects the display: the upload and notification are sent immediately. It gives the iPad banner time to appear but is an estimate, not an APNs delivery acknowledgment. **Notification sent** means ntfy accepted publication; it does not certify that the iPad displayed the banner or saved the file. Errors stay visible briefly and can be closed. Cancel/closing the panel stops the local operation; a notification already submitted cannot be retracted. Full-screen protection applies before sending and during the transfer. The panel exists only for the user-initiated one-shot process, with no idle worker or progress polling.

The Stream Deck entry point works while the tray is closed. It never starts another clipboard listener. Rapid duplicate button presses are rejected by the existing file-send mutex. Automatic clipboard sends stay quiet.

## Quiet operation

iPad videos received through SendToWindows save as original files in `Downloads/AdamsDrop`. An optional `receive_video_dir` configuration value selects another folder. Downloads stream to temporary `.part` files and become visible with a unique filename only after length/SHA-256 verification. Videos never change the clipboard. Once saved, a video automatically opens its folder in File Explorer with that exact file selected when full-screen protection is off, independently of notification settings. Protection is checked again immediately before the Shell action; skipped automatic openings are not replayed. An enabled video notification can reveal the file again when clicked. An interrupted transfer must be shared again from the iPad.

Incoming screenshots/images still copy to the clipboard and also save their original bytes with a unique filename in the same receive folder. Set `receive_image_dir` to override the image folder; otherwise it follows `receive_video_dir` or defaults to `Downloads/AdamsDrop`. The image notification reveals its saved file in Explorer only when clicked; there is no automatic folder opening for images. Video/image files remain until you delete them. An image file-save failure leaves the successful clipboard copy usable and shows a notification without a file action.

Other iPad files, including PDF, CSV, JSON, archives and named text files, save through the same verified streaming path. They leave the clipboard unchanged and show a **File saved — Click to show in folder** notification when receive notifications are enabled. They do not automatically open Explorer or their associated application. Set `receive_file_dir` to select a folder; otherwise it follows `receive_video_dir` or defaults to `Downloads/AdamsDrop`. The uploaded bytes and original supplied extension are preserved, with a unique name suffix. See IPAD.md for the optional filename header and explicit generic-file branch.

Exit in the tray menu closes the application. No automatic relaunch is installed by default. The optional login task starts once per login only. Background helpers launch hidden; the tray takes focus only when its menu is explicitly opened. Incoming Windows notifications default off. The process uses below-normal priority, drops overlapping send requests (copy again when ready), rotates listener/sender logs, and exits if its tray fails. These measures reduce interference; they do not certify driver or game stability.

Full-screen protection is enabled: Windows busy/exclusive-game/presentation state and foreground borderless full-screen geometry are checked when events occur. New clipboard sends, incoming fetches/writes, receipts and startup warmup are skipped during that activity. Skipped items are not queued; copy/send again afterwards. There is no polling loop, keyboard hook, simulated keypress or game injection. Ordinary desktop copying runs below normal priority. Windows notifications remain off unless explicitly configured, including send errors. PNG encoding finishes before opening the Windows clipboard.

Limits: this is a full-screen heuristic, not universal game detection; ordinary windowed games may not be detected. Work already in progress may finish as a game starts. Use tray Exit for no AdamsDrop process or transfer activity. Zero performance impact or driver/game stability cannot be guaranteed.
