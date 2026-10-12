# Relay deployment

Configure a separate ntfy server, including its self-hosted iOS upstream/APNs path: https://docs.ntfy.sh/config/#ios-instant-notifications

Copy relay/.env.example to relay/.env. Generate a random secret locally (`python -c "import secrets; print(secrets.token_urlsafe(32))"`) and use it in the relay, Windows config and SendToWindows Shortcut. Set NTFY_URL to an address reachable inside the container, and RELAY_BASE_URL to an address reachable from the iPad.

```sh
cd relay
docker compose up -d --build
```

Compose project/service/container: adams-drop. Port 8765. The host.docker.internal mapping can reach host-published ntfy; alternatively use a local override to join an existing external Docker network. Do not commit private overrides or .env.

Endpoints: GET /health; authenticated POST /send?source=windows or ipad (optional kind=file and filename for iPad files); authenticated POST /copied?kind=text or image; GET /fetch/TOKEN (single-use, no-store); GET /setup (no secrets).

Text/image items remain in bounded RAM storage (25 MiB per item, 100 MiB total). Raw iPad video and generic file uploads share private temporary disk storage: 2 GiB per file, 4 GiB total including active downloads, at most two concurrent uploads and sixteen files. A 256 MiB free-disk reserve is checked during uploads. Small multipart files remain supported within the 25 MiB request limit; multiple attachments in one request are rejected. Use a raw File body for larger files.

The same authenticated `/send?source=ipad` endpoint recognizes MP4/MOV and PDF signatures, generic binary/document Content-Types including CSV/JSON, or named files. Optional URL-encoded `X-Filename` (or filename query parameter) preserves a sanitized name and extension. `/send?source=ipad&kind=file` explicitly forces file storage, including zero-byte and plain-text files. Unnamed text/plain remains a clipboard item. Keep default routing for screenshots/videos; explicit file mode suppresses their clipboard/automatic-reveal behavior.

File fetches include length, SHA-256 and `X-AdamsDrop-Kind` headers and stream from disk; Windows verifies both length and hash before exposing the final file. The kind marker distinguishes generic files from clipboard text/images and videos even when their Content-Type is text/plain or image/*. Generic files only reveal on notification click.

Windows original-file sends explicitly use `/send?source=windows&kind=file`, sharing the same authentication, spool and limits. The optional `X-Content-SHA256` upload header is checked before notification publication; a mismatch deletes the upload and returns 422. Notifications select **SaveToFiles**, while existing clipboard notifications retain **SetClipboard**. File downloads for iPad use `application/octet-stream` and a sanitized attachment filename so Shortcuts receives bytes rather than parsing JSON/text. Notification messages contain no filename or file contents. HTTP 200 confirms notification publication, not iPad persistence. Physical shortcut saves must be tested separately.

The shared file/video spool keeps the existing location `/tmp/adamsdrop-video-buffer` (override with `VIDEO_SPOOL_DIR`). Run one relay worker per spool directory. Files are removed after fetch, on failed upload/publication, or after ten minutes waiting; crash leftovers are removed at the next startup. These files are transient transfer storage, not backup or history. The existing `MAX_VIDEO_SIZE` and `MAX_VIDEO_STORED_BYTES` settings now limit all disk-backed attachments; the Windows client accepts at most 2 GiB per file. No additional dependency or persistent volume is required.

Restart loses pending items. ntfy has its own notification cache. Preserve unrelated ntfy topics/services. For rollback retain the prior source/image, restore and recreate only adams-drop, then test health and transfer. Do not revert to early versions that exposed reusable keys in URLs.
