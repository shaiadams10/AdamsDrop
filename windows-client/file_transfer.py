"""Save streamed original attachments without touching either clipboard."""
import hashlib
import os
import re
import tempfile
import time
import uuid
from email.message import Message
from pathlib import Path


MAX_FILE_SIZE = 2 * 1024**3
FILE_SUFFIXES = {
    "application/pdf": ".pdf", "text/csv": ".csv", "application/csv": ".csv",
    "application/json": ".json", "application/ld+json": ".jsonld",
    "application/xml": ".xml", "text/xml": ".xml", "text/tab-separated-values": ".tsv",
    "application/zip": ".zip", "application/gzip": ".gz", "application/x-gzip": ".gz",
    "application/rtf": ".rtf", "text/rtf": ".rtf", "text/plain": ".txt", "text/html": ".html",
}


def save_download(response, config, should_pause, *, video_suffix=None):
    """Stream to a private partial file; expose it only after length/hash checks."""
    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
    expected_size = int(response.headers.get("content-length", "-1"))
    expected_hash = response.headers.get("x-content-sha256", "").lower()
    if not 0 <= expected_size <= MAX_FILE_SIZE or not re.fullmatch("[a-f0-9]{64}", expected_hash):
        raise ValueError("Missing or invalid file integrity metadata")
    if video_suffix and not expected_size:
        raise ValueError("Empty video")
    configured = config.get("receive_video_dir") if video_suffix else config.get("receive_file_dir") or config.get("receive_video_dir")
    destination = Path(configured or Path.home() / "Downloads" / "AdamsDrop").expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    disposition = Message()
    disposition["content-disposition"] = response.headers.get("content-disposition", "")
    name = (disposition.get_filename() or ("video" if video_suffix else "file")).replace("\\", "/").rsplit("/", 1)[-1]
    stem = Path(name).stem
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", stem).strip(" .")[:100] or "video"
    suffix = video_suffix or Path(name).suffix
    if not re.fullmatch(r"\.[a-zA-Z0-9_-]{1,20}", suffix):
        suffix = FILE_SUFFIXES.get(content_type, ".bin")
    final_path = destination / (stem + "-" + time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:12] + suffix)
    fd, name = tempfile.mkstemp(prefix=".adamsdrop-", suffix=".part", dir=destination)
    partial = Path(name)
    size = 0
    digest = hashlib.sha256()
    try:
        with os.fdopen(fd, "wb") as output:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if should_pause():
                    raise InterruptedError("File transfer paused for full-screen activity; send again afterwards")
                if not chunk:
                    continue
                size += len(chunk)
                if size > expected_size or size > MAX_FILE_SIZE:
                    raise ValueError("File exceeds declared size")
                output.write(chunk)
                digest.update(chunk)
        if size != expected_size or digest.hexdigest() != expected_hash:
            raise ValueError("File integrity check failed")
        if should_pause():
            raise InterruptedError("File transfer paused for full-screen activity; send again afterwards")
        # On Windows rename refuses to overwrite an existing destination.
        partial.rename(final_path)
        return final_path
    finally:
        partial.unlink(missing_ok=True)


def save_file(response, config, should_pause):
    return save_download(response, config, should_pause)
