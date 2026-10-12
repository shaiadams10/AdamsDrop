"""Video-specific validation over the shared original-file download path."""
from file_transfer import MAX_FILE_SIZE, save_download

MAX_VIDEO_SIZE = MAX_FILE_SIZE
VIDEO_SUFFIXES = {
    "video/mp4": ".mp4", "video/quicktime": ".mov", "video/x-m4v": ".m4v",
    "video/webm": ".webm", "video/x-matroska": ".mkv", "video/x-msvideo": ".avi",
}


def save_video(response, config, should_pause):
    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
    if content_type not in VIDEO_SUFFIXES:
        raise ValueError("Unsupported video container")
    return save_download(response, config, should_pause, video_suffix=VIDEO_SUFFIXES[content_type])
