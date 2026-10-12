"""Original-file relay checks, with mocked ntfy and private temporary storage."""
import asyncio
import hashlib
import importlib.util
import os
import json
import tempfile
from pathlib import Path

import httpx

os.environ.setdefault("API_KEY", "synthetic-file-test-key")
spec = importlib.util.spec_from_file_location("file_relay", Path(__file__).with_name("server.py"))
relay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(relay)


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
                key = {"X-Api-Key": relay.API_KEY}
                assert (await client.post("/send?source=ipad&kind=file", content=b"pdf")).status_code == 401
                # Windows files select SaveToFiles and download as bytes, not parsed JSON/clipboard.
                for name, data, mime in [("worksheet.pdf", b"%PDF-1.7\r\nsynthetic", "application/pdf"),
                                         ("screenshot.png", b"\x89PNG\r\n\x1a\nsynthetic", "image/png"),
                                         ("data.json", b'{"value":1}\r\n', "application/json"),
                                         ("notes.txt", b"\xef\xbb\xbfhello\r\nworld\r\n", "text/plain"),
                                         ("table.csv", b"name,value\r\nsample,001.20\r\n", "text/csv"),
                                         ("clip.mp4", b"\x00\x00\x00\x18ftypisom\x00\xff", "video/mp4"),
                                         ("clip.mov", b"\x00\x00\x00\x18ftypqt  \x00\xff", "video/quicktime"),
                                         ("archive.zip", b"PK\x03\x04\x00\xff", "application/zip"),
                                         ("unknown.custom", b"\x00\xff\xfe", "application/octet-stream"),
                                         ("empty.txt", b"", "text/plain")]:
                    response = await client.post("/send?source=windows&kind=file", content=data,
                        headers={**key, "X-Filename": name, "Content-Type": mime,
                                 "X-Content-SHA256": hashlib.sha256(data).hexdigest()})
                    assert response.status_code == 200, response.text
                    token = response.json()["token"]
                    publication = json.loads(publications[-1].content)
                    assert "name=SaveToFiles&" in publication["click"]
                    assert publication["actions"][0]["label"] == "Save to Files"
                    assert relay.API_KEY not in publication["click"]
                    fetched = await client.get("/fetch/" + token)
                    assert fetched.content == data
                    assert fetched.headers["content-type"] == "application/octet-stream"
                    assert name in fetched.headers["content-disposition"]
                    assert (await client.get("/fetch/" + token)).status_code == 404
                response = await client.post("/send?source=windows&kind=file", content=b"changed",
                    headers={**key, "X-Content-SHA256": "0" * 64})
                assert response.status_code == 422 and not relay.app.state.video_files
                # No content coercion or newline normalization; default extensions from MIME.
                samples = [(b"%PDF-1.7\r\nsynthetic\x00\xff", "text/plain", ".pdf"),
                           (b"name,value\r\nsynthetic,001.20\r\n", "text/csv", ".csv"),
                           (b'{"value":1,"escaped":"\\u03bb"}\r\n', "application/json", ".json"),
                           (b"\x00\xff\xfe\r\n", "application/octet-stream", ".bin"),
                           (b"", "application/json", ".json")]
                for data, content_type, suffix in samples:
                    response = await client.post("/send?source=ipad", content=data,
                                                 headers={**key, "Content-Type": content_type})
                    assert response.status_code == 200, response.text
                    token = response.json()["token"]
                    item = relay.storage[token]
                    assert item["kind"] == "file" and "data" not in item
                    assert item["path"].read_bytes() == data and item["filename"].endswith(suffix)
                    assert publications[-1].content == token.encode()
                    fetched = await client.get("/fetch/" + token)
                    assert fetched.content == data and fetched.headers["x-adamsdrop-kind"] == "file"
                    assert fetched.headers["x-content-sha256"] == hashlib.sha256(data).hexdigest()
                    assert int(fetched.headers["content-length"]) == len(data)
                    assert (await client.get("/fetch/" + token)).status_code == 404
                    assert not item["path"].exists()
                # A named text file saves as a file; unnamed text still remains clipboard text.
                for url, extra in [("/send?source=ipad&filename=report.csv", {}),
                                   ("/send?source=ipad", {"X-Filename": "..%2F..%2Fdata.JSON", "Content-Type": "image/png"}),
                                   ("/send?source=ipad&kind=file&filename=empty.txt", {})]:
                    response = await client.post(url, content=b"", headers={**key, "Content-Type": "text/plain", **extra})
                    assert response.status_code == 200, response.text
                    item = relay.storage[response.json()["token"]]
                    assert item["kind"] == "file" and "/" not in item["filename"]
                    assert item["filename"].endswith((".csv", ".JSON", ".txt"))
                    await client.get("/fetch/" + response.json()["token"])
                response = await client.post("/send?source=ipad", content=b'{"ordinary":"clipboard text"}',
                                             headers={**key, "Content-Type": "text/plain"})
                item = relay.storage[response.json()["token"]]
                assert "path" not in item and item["data"].startswith(b"{")
                await client.get("/fetch/" + response.json()["token"])
                # A file above the image cap still streams; one-file multipart compatibility.
                relay.MAX_PAYLOAD_SIZE = 4
                response = await client.post("/send?source=ipad", content=b"1,2\r\n" * 10,
                                             headers={**key, "Content-Type": "text/csv"})
                assert response.status_code == 200
                await client.get("/fetch/" + response.json()["token"])
                relay.MAX_PAYLOAD_SIZE = 4096
                response = await client.post("/send?source=ipad", data={"description": "ignored"},
                                             files={"file": ("report.csv", b"a,b\r\n", "text/plain")}, headers=key)
                assert response.status_code == 200, response.text
                item = relay.storage[response.json()["token"]]
                assert item["filename"] == "report.csv" and item["kind"] == "file"
                assert (await client.get("/fetch/" + response.json()["token"])).content == b"a,b\r\n"
                assert (await client.post("/send?source=ipad", files=[("file", ("a.txt", b"a")), ("file", ("b.txt", b"b"))],
                                          headers=key)).status_code == 400
                relay.MAX_VIDEO_SIZE = 4
                assert (await client.post("/send?source=ipad", content=b"12345", headers={**key, "Content-Type": "text/csv"})).status_code == 413
                assert not relay.app.state.video_files
                relay.MAX_VIDEO_SIZE = 2 * 1024**3
                response = await client.post("/send?source=ipad", content=b"{}", headers={**key, "Content-Type": "application/json"})
                item = relay.storage[response.json()["token"]]
                item["created_at"] = 0
                await relay.expire_items()
                assert not item["path"].exists() and not relay.storage
                await relay.app.state.http_client.aclose()
                relay.app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(500)))
                assert (await client.post("/send?source=ipad", content=b"{}", headers={**key, "Content-Type": "application/json"})).status_code == 502
                assert not relay.storage and not relay.app.state.video_files and not list(Path(directory).glob("*.upload"))
    print("PASS: PDF/CSV/JSON/binary/empty files, explicit file mode, safe names, unchanged clipboard-text routing, streaming, single use, limits and cleanup")


if __name__ == "__main__":
    asyncio.run(main())
