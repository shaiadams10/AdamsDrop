# Release checklist

- Run regression tests and mocked relay tests.
- Verify packaged startup and direct text/image, incoming Shortcut and echo suppression on real devices.
- Verify reboot/idle recovery for the versions you claim supported.
- Review staged paths and content; scan for secrets, private hostnames/IPs/user paths, device IDs and captured data.
- Confirm config.json, .env, pairing records, keys, logs, cache, venv, build and dist are ignored/untracked.
- Build public binaries from a clean checkout with placeholder configuration only. Never upload a configured dist directory.
- MIT applies to this project's code; dependencies retain their licenses. Review bundled dependency notices before publishing binaries.
- Local builds are unsigned. Sign release binaries if desired.
- GitHub publication requires a separate explicit request; no remote or push is performed by setup.

This is experimental developer-service integration, not certified always-on clipboard synchronization.
