"""Event-driven direct iPad writes. Persistent tunnel; fresh service per command."""
import asyncio
import threading
import logging
import hashlib
import time
from collections import deque
import ipad_transport
ipad_transport.install()
from concurrent.futures import TimeoutError

logger = logging.getLogger('ClipboardDirect')
_loop = None
_thread = None
_tunnel = None
_rsd = None
_start_lock = threading.Lock()
_monitor_future = None
_transport_lock = asyncio.Lock()
_service_lock = asyncio.Lock()
_outbound = deque(maxlen=64)
_last_helper_recovery = 0.0
last_failure = None

async def _recover_helper(device):
    """Restart only Apple's developer clipboard helper, at most once per minute."""
    global _last_helper_recovery
    if time.monotonic() - _last_helper_recovery < 60:
        return
    _last_helper_recovery = time.monotonic()
    from pymobiledevice3.remote.core_device.app_service import AppServiceService
    try:
        await _ensure_connected(device)
        async with AppServiceService(_rsd) as app:
            processes = await asyncio.wait_for(app.list_processes(), 3)
        for process in processes:
            if process.get('executableURL', {}).get('relative') == 'file:///System/Developer/usr/libexec/dtpasteboardd':
                async with AppServiceService(_rsd) as app:
                    await asyncio.wait_for(app.send_signal_to_process(process['processIdentifier'], 9), 3)
                logger.info('Restarted unresponsive developer clipboard helper')
                break
    except Exception as exc:
        logger.info('Developer helper recovery unavailable (%s)', type(exc).__name__)
    finally:
        await _close()

def _signature(payload, kind):
    return kind, hashlib.sha256(payload).digest()

def take_outbound_echo(payload, kind):
    now = time.monotonic()
    while _outbound and now - _outbound[0][0] > 30:
        _outbound.popleft()
    signature = _signature(payload, kind)
    for entry in list(_outbound):
        if entry[1] == signature:
            _outbound.remove(entry)
            return True
    return False

async def _ensure_connected(device):
    global _tunnel, _rsd
    from pymobiledevice3.remote.userspace_tunnel import UserspaceRsdTunnel
    async with _transport_lock:
        if _rsd is None:
            tunnel = UserspaceRsdTunnel(serial=device, autopair=False, remotepairing_fallback=False)
            try:
                rsd = await asyncio.wait_for(tunnel.aopen(), 12)
                if 'com.apple.coredevice.pasteboardservice' not in rsd.peer_info.get('Services', {}):
                    from pymobiledevice3.services.mobile_image_mounter import auto_mount
                    logger.info('Restoring developer support after iPad restart')
                    await asyncio.wait_for(auto_mount(rsd), 60)
                    # RSD's advertised services were captured before the mount.
                    await tunnel.aclose()
                    tunnel = UserspaceRsdTunnel(serial=device, autopair=False, remotepairing_fallback=False)
                    rsd = await asyncio.wait_for(tunnel.aopen(), 12)
                    if 'com.apple.coredevice.pasteboardservice' not in rsd.peer_info.get('Services', {}):
                        raise ConnectionError('Developer clipboard service unavailable after mount')
            except BaseException:
                await tunnel.aclose()
                raise
            _tunnel, _rsd = tunnel, rsd
        return _rsd

async def _close():
    global _tunnel, _rsd
    async with _transport_lock:
        tunnel, _tunnel, _rsd = _tunnel, None, None
        if tunnel:
            try:
                await asyncio.wait_for(tunnel.aclose(), 3)
            except Exception:
                pass

async def _send(payload, content_type, device, is_current=None):
    # The device can expire an idle service/tunnel. SET is idempotent: retry once.
    try:
        # Cold boot restoration may mount developer support; keep that outside
        # the shorter timeout used to diagnose an unresponsive clipboard helper.
        await _ensure_connected(device)
        if is_current is not None and not is_current():
            raise ValueError('Copy superseded while reconnecting')
        return await asyncio.wait_for(_send_once(payload, content_type, device, is_current), 6)
    except TimeoutError:
        async with _service_lock:
            await _recover_helper(device)
        return await _send_once(payload, content_type, device, is_current)
    except (ConnectionError, OSError, asyncio.IncompleteReadError):
        return await _send_once(payload, content_type, device, is_current)
    except Exception as exc:
        if type(exc).__name__ not in ('StreamClosedError', 'ConnectionTerminatedError'):
            raise
        return await _send_once(payload, content_type, device, is_current)


async def _send_once(payload, content_type, device, is_current=None):
    async with _service_lock:
        return await _send_once_impl(payload, content_type, device, is_current)

async def _send_once_impl(payload, content_type, device, is_current=None):
    global _tunnel, _rsd
    from pymobiledevice3.remote.userspace_tunnel import UserspaceRsdTunnel
    from pymobiledevice3.remote.core_device.pasteboard_service import PasteboardService, text_item, data_item
    try:
        await _ensure_connected(device)
        if is_current is not None and not is_current():
            raise ValueError('Copy superseded while reconnecting')
        if content_type.startswith('image/png'):
            items = [data_item('public.png', payload)]
        elif content_type.startswith('text/plain'):
            items = [text_item(payload.decode('utf-8'))]
        else:
            raise ValueError('Unsupported direct clipboard format')
        # This device closes the service after one request. Reuse tunnel, not service.
        async with PasteboardService(_rsd) as pb:
            # Upstream send_request puts the whole message in one HTTP/2 frame.
            # PNGs/long text exceed the peer frame limit. Use its flow-controlled writer.
            from types import MethodType
            from pymobiledevice3.remote.remotexpc import ROOT_CHANNEL, create_xpc_wrapper
            async def send_framed(connection, data, wanting_reply=False):
                packet = create_xpc_wrapper(data, message_id=connection.next_message_id[ROOT_CHANNEL],
                                            wanting_reply=wanting_reply)
                offset = 0
                while offset < len(packet):
                    offset += await connection._send_flow_controlled(ROOT_CHANNEL, packet, offset, len(packet))
                connection.next_message_id[ROOT_CHANNEL] += 1
            pb.service.send_request = MethodType(send_framed, pb.service)
            _outbound.append((time.monotonic(), _signature(payload, 'image' if content_type.startswith('image/') else 'text')))
            reply = await pb.set(items)
            if reply.get('command') != 'SET_REPLY':
                raise RuntimeError('Unexpected pasteboard response')
        # SET_REPLY alone can acknowledge unusable image data. Only report a
        # receipt after the exact representation is present on the device.
        from pymobiledevice3.remote.core_device.pasteboard_service import snapshot_text
        async with PasteboardService(_rsd) as pb:
            snapshot = await pb.get()
        if content_type.startswith('text/plain'):
            verified = snapshot_text(snapshot) == payload.decode('utf-8')
        else:
            verified = any(item.get('data', {}).get('public.png', {}).get('data') == payload
                           for item in snapshot.get('pasteboard', snapshot).get('items', []))
        if not verified:
            raise RuntimeError('Clipboard read-back verification failed')
    except BaseException:
        await _close()
        raise

def send(payload, content_type, device, is_current=None):
    global _loop, _thread, last_failure
    last_failure = None
    # This iPad drops inline representations above ~1 MiB despite SET_REPLY.
    # Optimize losslessly; preserve original via ntfy if it still cannot fit.
    if content_type.startswith('image/png') and len(payload) > 1_000_000:
        import io
        from PIL import Image, ImageChops
        image = Image.open(io.BytesIO(payload))
        if image.mode == 'RGB':
            red, green, blue = image.split()
            if ImageChops.difference(red, green).getbbox() is None and ImageChops.difference(red, blue).getbbox() is None:
                image = red
        packed = io.BytesIO()
        image.save(packed, format='PNG', optimize=True)
        payload = packed.getvalue()
    if len(payload) > 1_000_000:
        last_failure = 'size'
        logger.info('Clipboard exceeds verified direct size limit; using original ntfy transfer')
        return False
    if not device:
        last_failure = 'unavailable'
        return False
    with _start_lock:
        if _loop is None:
            _loop = asyncio.new_event_loop()
            _thread = threading.Thread(target=_loop.run_forever, daemon=True, name='iPadDirect')
            _thread.start()
    future = asyncio.run_coroutine_threadsafe(asyncio.wait_for(_send(payload, content_type, device, is_current), 90), _loop)
    try:
        future.result(timeout=94)
        return True
    except Exception as exc:
        future.cancel()
        last_failure = 'unavailable'
        logger.warning('Direct clipboard unavailable (%s); using ntfy fallback', type(exc).__name__)
        return False


def prepare(device):
    """Warm the developer tunnel at login without touching either clipboard."""
    global _loop, _thread
    with _start_lock:
        if _loop is None:
            _loop = asyncio.new_event_loop()
            _thread = threading.Thread(target=_loop.run_forever, daemon=True, name='iPadDirect')
            _thread.start()
    async def connect():
        global _tunnel, _rsd
        from pymobiledevice3.remote.userspace_tunnel import UserspaceRsdTunnel
        try:
            await _ensure_connected(device)
        except BaseException:
            await _close()
            raise
    future = asyncio.run_coroutine_threadsafe(asyncio.wait_for(connect(), 90), _loop)
    try:
        future.result(timeout=94)
        logger.info('Direct iPad tunnel ready')
    except Exception:
        future.cancel()
        logger.info('Direct iPad tunnel not available at startup; retry on next copy')
