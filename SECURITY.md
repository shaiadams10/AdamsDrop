# Security

This project reads clipboard content intentionally. Treat the configured installation as private.

- Never commit config.json, .env, pairing records, certificates, private keys, captured images or logs.
- API keys are shared between the configured Windows client and relay. Generate a random secret, keep it outside Git, and rotate any previously exposed key.
- Fetch URLs are short-lived, single-use bearer capabilities. Anyone possessing an unexpired link can fetch that one item. Do not log or share them.
- The relay is not an authentication gateway for ntfy. Configure ntfy topic access separately; do not expose an unauthenticated topic on an untrusted network.
- HTTP relay examples are for a trusted private LAN. Use TLS and access controls for deployment across untrusted networks. Direct developer transport uses existing pairing trust; it does not bypass authentication.
- Developer Mode and pairing grant powerful device access. Keep host pairing files protected. Do not publish them or ship them in binaries.
- The direct client may restart only Apple’s developer clipboard helper after a timeout. It never intentionally restarts the device or its normal clipboard daemon.
- Shortcuts-received images may be cached locally for click-to-open. Delete that cache if no longer needed.
- No cloud clipboard history is required. ntfy still retains notification metadata according to its server settings and APNs may delay delivery.
- Builds are unsigned unless you sign them yourself. Do not run an untrusted binary or assume an unsigned source build has been independently audited.

Report vulnerabilities privately to the repository owner when a private reporting channel is configured. Do not post clipboard contents or credentials in public issues.
