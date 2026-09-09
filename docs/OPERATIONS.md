# Operation and recovery

Windows -> iPad is automatic. iPad -> Windows requires SendToWindows. Offline copies are not history to reconcile: copy again when connected. Superseded Windows copies and old incoming SSE events are rejected. Receipts are coalesced; stale queued receipts expire. Already queued APNs/ntfy notifications can still arrive, and manual/large-image fallback is transient rather than guaranteed live delivery.

Startup: manual executable launch (or optional login-only task) -> Apple connection helper -> developer tunnel warmup. Next copy retries if unavailable. Missing iPad developer support is remounted after reboot; a timed-out clipboard helper can be restarted at most once per minute. Only the exact developer helper is targeted, not Notes or the system clipboard daemon.

Troubleshooting: check AdamsDrop.exe; unlock iPad on same LAN; copy fresh short text; allow cold-start recovery; inspect metadata-only listener.log beside executable. If still unavailable, connect USB, open Apple Devices and run the mount command in IPAD.md, then relaunch AdamsDrop.

Logs and incoming image cache are private. Direct clipboard contents are not logged. The imported-origin clipboard marker prevents echoes and is replaced by a fresh local copy.

Owner confirmed operation after Windows reboot. Actual iPad reboot preserved trust but removed developer support; Wi-Fi remount and subsequent text/image transfers passed. Integrated automatic remount is implemented, not certified for every reboot/OS/lock combination. No always-delivered guarantee. Experimental native reverse readers were removed from shipped software.

Packaging validation: renamed executable passed direct text and image read-back while the iPad was awake (about 177 / 203 ms in one sample). After the final icon rebuild, relay-to-Windows text/image and origin markers passed again. A later direct check found the iPad undiscoverable, so always-available or final-build reboot delivery is not claimed. The relay healthcheck is healthy.

Windows quiet-operation update: no repeating recovery trigger or failure restart; closing the tray exits. Manual launch does not depend on Task Scheduler. Below-normal process priority, nonblocking send admission, bounded rotating logs, quiet receive defaults, and tray-failure exit reduce background impact. Overlapping copies are dropped; copy again when ready.

Full-screen protection skips new transfer work while Windows reports busy/exclusive-game/presentation state or the foreground borderless window covers its monitor. No backlog is replayed afterwards. Incoming PNG encoding occurs before the Windows clipboard is opened. Login-only startup waits 30 seconds; there is no repeating trigger or restart-on-failure. See WINDOWS.md for detection and in-flight-work limitations.
