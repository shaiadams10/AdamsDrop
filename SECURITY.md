# Security

This project reads clipboard content intentionally. Treat the configured installation as private.

- Never commit config.json, .env, pairing records, certificates, private keys, captured images or logs.
- API keys are shared between the configured Windows client and relay. Generate a random secret, keep it outside Git, and rotate any previously exposed key.
- Fetch URLs are short-lived, single-use bearer capabilities. Anyone possessing an unexpired link can fetch that one item. Do not log or share them.
- The relay is not an authentication gateway for ntfy. Configure ntfy topic access separately; do not expose an unauthenticated topic on an untrusted network.
- HTTP relay examples are for a trusted private LAN. Use TLS and access controls for deployment across untrusted networks. Direct developer transport uses existing pairing trust; it does not bypass authentication.
- Developer Mode and pairing grant powerful device access. Keep host pairing files protected. Do not publish them or ship them in binaries.
- The direct client may restart only Apple’s developer clipboard helper after a timeout. It never intentionally restarts the device or its normal clipboard daemon.
- Shortcuts-received images are saved as original files in the receive folder as well as copied to the clipboard. Saved files remain until deleted.
- No cloud clipboard history is required. ntfy still retains notification metadata according to its server settings and APNs may delay delivery.
- Builds are unsigned unless you sign them yourself. Do not run an untrusted binary or assume an unsigned source build has been independently audited.

Report vulnerabilities privately to the repository owner when a private reporting channel is configured. Do not post clipboard contents or credentials in public issues.

Windows original files share the existing authenticated, bounded transient spool. Their ntfy notification contains a one-use link but no filename or contents; SaveToFiles needs no reusable API key. The sender supplies a SHA-256 upload check, and the relay serves binary attachments to avoid Shortcuts text/JSON conversion. The iPad shortcut's Save File result is not acknowledged back to Windows. Destination folders are chosen and authorized by the owner in Shortcuts.

## Video transfer storage

iPad file/video uploads require the existing X-Api-Key. Fetch links remain random, single-use and short-lived. Original bytes temporarily occupy a private relay spool directory and remain as ordinary files in the Windows receive folder after verified download. Received images also save their original bytes in that folder. Files retain their uploaded metadata. No content transformation, automatic media playback or document execution occurs. Video receipt automatically opens its containing folder with the file selected when full-screen protection is off; image and generic file receipts require clicking their notification to reveal the saved file. Video notifications also support manual reveal. Filenames are sanitized and given unique suffixes. Saved files remain until deleted. Limits and cleanup are described in docs/SERVER.md.
