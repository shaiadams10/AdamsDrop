"""Relay video checks; synthetic bytes and mocked ntfy, no device traffic."""
import asyncio
import hashlib
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

import httpx

os.environ.setdefault("API_KEY", "synthetic-test-key")
spec = importlib.util.spec_from_file_location("video_relay", Path(__file__).with_name("server.py"))
relay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(relay)
VIDEO = b"\x00\x00\x00\x18ftypqt  \x00\x00\x00\x00qt  " + bytes(range(256)) * 4


async def main():
    with tempfile.TemporaryDirectory() as directory:
        relay.VIDEO_SPOOL_DIR = Path(directory)
        async with relay.lifespan(relay.app):
            await relay.app.state.http_client.aclose()
            publications = []
            def publish(request):
                publications.append(request)
                return httpx.Response(200)
            relay.app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(publish))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=relay.app), base_url="http://test") as client:
                headers = {"X-Api-Key": relay.API_KEY, "Content-Type": "application/octet-stream",
                           "X-Filename": "..%2F..%2FOriginal%20clip.exe"}
                assert (await client.post("/send?source=ipad", content=VIDEO)).status_code == 401
                assert (await client.post("/send?source=windows", content=VIDEO, headers=headers)).status_code == 415
                # A video bypasses the image cap and remains on disk, with exact bytes.
                relay.MAX_PAYLOAD_SIZE = 128
                response = await client.post("/send?source=ipad", content=VIDEO, headers=headers)
                assert response.status_code == 200, response.text
                token = response.json()["token"]
                item = relay.storage[token]
                assert "data" not in item and item["path"].read_bytes() == VIDEO
                assert item["filename"].endswith(".mov") and "/" not in item["filename"]
                assert publications[-1].content.decode() == token
                fetched = await client.get("/fetch/" + token)
                assert fetched.content == VIDEO
                assert fetched.headers["content-type"] == "video/quicktime"
                assert fetched.headers["x-content-sha256"] == hashlib.sha256(VIDEO).hexdigest()
                assert int(fetched.headers["content-length"]) == len(VIDEO)
                assert fetched.headers["cache-control"] == "no-store"
                assert not item["path"].exists() and not relay.app.state.video_files
                assert (await client.get("/fetch/" + token)).status_code == 404
                # Multipart compatibility is bounded by the original 25 MiB cap.
                relay.MAX_PAYLOAD_SIZE = 4096
                response = await client.post("/send?source=ipad", files={"file": ("clip.mov", VIDEO, "video/quicktime")},
                                             headers={"X-Api-Key": relay.API_KEY})
                assert response.status_code == 200, response.text
                assert (await client.get("/fetch/" + response.json()["token"])).content == VIDEO
                # Caps with and without Content-Length must clean partial uploads.
                relay.MAX_VIDEO_SIZE = len(VIDEO) - 1
                assert (await client.post("/send?source=ipad", content=VIDEO, headers=headers)).status_code == 413
                async def chunks():
                    for offset in range(0, len(VIDEO), 73):
                        yield VIDEO[offset:offset + 73]
                assert (await client.post("/send?source=ipad", content=chunks(), headers=headers)).status_code == 413
                assert not relay.app.state.video_files and not list(Path(directory).glob("*.upload"))
                relay.MAX_VIDEO_SIZE = 2 * 1024**3
                relay.MAX_VIDEO_STORED_BYTES = len(VIDEO) - 1
                assert (await client.post("/send?source=ipad", content=VIDEO, headers=headers)).status_code == 503
                assert not relay.app.state.video_files
                relay.MAX_VIDEO_STORED_BYTES = 4 * 1024**3
                response = await client.post("/send?source=ipad", content=VIDEO, headers=headers)
                token = response.json()["token"]
                item = relay.storage[token]
                item["created_at"] = 0
                assert (await client.get("/fetch/" + token)).status_code == 404
                assert not item["path"].exists() and not relay.app.state.video_files
                response = await client.post("/send?source=ipad", content=VIDEO, headers=headers)
                item = relay.storage[response.json()["token"]]
                item["created_at"] = 0
                await relay.expire_items()
                assert not relay.storage and not item["path"].exists()
                await relay.app.state.http_client.aclose()
                relay.app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(500)))
                assert (await client.post("/send?source=ipad", content=VIDEO, headers=headers)).status_code == 502
                assert not relay.storage and not relay.app.state.video_files
                assert not list(Path(directory).glob("*.upload"))
                assert relay.video_type(b"\x00\x00\x00\x18ftypheic", "application/octet-stream") is None
                assert relay.video_type(b"\x00\x00\x00\x18ftypavif", "video/mp4") is None
    print("PASS: video auth, direction, disk streaming, exact bytes/hash, multipart, single use, expiry, limits and cleanup")


if __name__ == "__main__":
    asyncio.run(main())
