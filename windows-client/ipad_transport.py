"""Paired USB first, then authenticated developer Wi-Fi discovery."""
import asyncio
from pymobiledevice3.remote import userspace_tunnel as transport
from pymobiledevice3.bonjour import browse_remotepairing
from pymobiledevice3.remote.tunnel_service import create_core_device_tunnel_service_using_remotepairing
_original = transport._create_no_root_tunnel_provider
_last_endpoint = None

async def _wireless(serial):
    global _last_endpoint
    async def connect(endpoint):
        return await asyncio.wait_for(create_core_device_tunnel_service_using_remotepairing(serial, *endpoint, autopair=False), 3)
    if _last_endpoint:
        try:
            return await connect(_last_endpoint), None
        except Exception:
            pass
    services = await browse_remotepairing(timeout=2)
    endpoints = list(dict.fromkeys((a.full_ip, s.port) for s in services for a in s.addresses))
    endpoints.sort(key=lambda e: ':' in e[0])
    for endpoint in endpoints:
        try:
            result = await connect(endpoint)
            _last_endpoint = endpoint
            return result, None
        except Exception:
            pass
    raise ConnectionError('Paired iPad unavailable over Wi-Fi')

async def _provider(serial, autopair, fallback):
    try:
        return await _original(serial, False, False)
    except Exception:
        return await _wireless(serial)

def install():
    # Pinned library lacks provider injection; adaptation stays in this process.
    transport._create_no_root_tunnel_provider = _provider
