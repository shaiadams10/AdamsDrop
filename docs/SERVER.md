# Relay deployment

Configure a separate ntfy server, including its self-hosted iOS upstream/APNs path: https://docs.ntfy.sh/config/#ios-instant-notifications

Copy relay/.env.example to relay/.env. Generate a random secret locally (`python -c "import secrets; print(secrets.token_urlsafe(32))"`) and use it in the relay, Windows config and SendToWindows Shortcut. Set NTFY_URL to an address reachable inside the container, and RELAY_BASE_URL to an address reachable from the iPad.

```sh
cd relay
docker compose up -d --build
```

Compose project/service/container: adams-drop. Port 8765. The host.docker.internal mapping can reach host-published ntfy; alternatively use a local override to join an existing external Docker network. Do not commit private overrides or .env.

Endpoints: GET /health; authenticated POST /send?source=windows or ipad; authenticated POST /copied?kind=text or image; GET /fetch/TOKEN (single-use, no-store); GET /setup (no secrets).

Pending items are in memory, not a persistent history. Restart loses them. ntfy has its own notification cache. Preserve unrelated ntfy topics/services. For rollback retain the prior source/image, restore and recreate only adams-drop, then test health and transfer. Do not revert to early versions that exposed reusable keys in URLs.
