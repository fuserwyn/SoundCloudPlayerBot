from __future__ import annotations

import asyncio
import logging
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

logger = logging.getLogger(__name__)

SOUNDCLOUD_URL_RE = re.compile(
    r"https?://(?:(?:www|m|on)\.)?soundcloud\.com/[^\s]+",
    re.IGNORECASE,
)


class SoundCloudError(Exception):
    """Anything that goes wrong while talking to SoundCloud / yt-dlp."""


class TrackTooLargeError(SoundCloudError):
    def __init__(self, size_bytes: int, limit_bytes: int) -> None:
        super().__init__(
            f"Track is {size_bytes / 1024 / 1024:.1f} MB which exceeds "
            f"Telegram limit of {limit_bytes / 1024 / 1024:.0f} MB."
        )
        self.size_bytes = size_bytes
        self.limit_bytes = limit_bytes


@dataclass
class Track:
    file_path: Path
    title: str
    artist: str
    duration: int  # seconds
    thumbnail_url: str | None
    webpage_url: str

    def cleanup(self) -> None:
        try:
            if self.file_path.exists():
                self.file_path.unlink()
        except OSError:
            logger.warning("Failed to remove %s", self.file_path, exc_info=True)
        # Drop the parent dir too if we created a unique one
        parent = self.file_path.parent
        try:
            if parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
        except OSError:
            pass


def find_soundcloud_url(text: str) -> str | None:
    match = SOUNDCLOUD_URL_RE.search(text or "")
    return match.group(0) if match else None


def _extract_artist(info: dict[str, Any]) -> str:
    for key in ("artist", "uploader", "channel", "creator"):
        value = info.get(key)
        if value:
            return str(value)
    return "SoundCloud"


def _build_ydl_opts(out_template: str) -> dict[str, Any]:
    return {
        "format": "bestaudio/best",
        "outtmpl": out_template,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
        "writethumbnail": False,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            },
            {"key": "FFmpegMetadata"},
        ],
    }


def _download_sync(url: str, work_dir: Path) -> Track:
    out_template = str(work_dir / "%(title).200B.%(ext)s")
    opts = _build_ydl_opts(out_template)

    with YoutubeDL(opts) as ydl:
        try:
            info = ydl.extract_info(url, download=True)
        except DownloadError as exc:
            raise SoundCloudError(f"yt-dlp failed: {exc}") from exc

    if not info:
        raise SoundCloudError("yt-dlp returned no info for this URL.")

    if info.get("_type") == "playlist":
        entries = [e for e in (info.get("entries") or []) if e]
        if not entries:
            raise SoundCloudError("Playlist is empty.")
        info = entries[0]

    requested = info.get("requested_downloads") or []
    file_path: Path | None = None
    if requested:
        file_path = Path(requested[0].get("filepath") or requested[0].get("_filename"))
    if file_path is None:
        candidate = info.get("filepath") or info.get("_filename")
        file_path = Path(candidate) if candidate else None
    if file_path is None or not file_path.exists():
        mp3s = list(work_dir.glob("*.mp3"))
        if not mp3s:
            raise SoundCloudError("Downloaded file was not found on disk.")
        file_path = mp3s[0]

    title = str(info.get("title") or file_path.stem)
    return Track(
        file_path=file_path,
        title=title,
        artist=_extract_artist(info),
        duration=int(info.get("duration") or 0),
        thumbnail_url=info.get("thumbnail"),
        webpage_url=str(info.get("webpage_url") or url),
    )


async def download_track(
    url: str,
    download_root: Path,
    max_bytes: int,
) -> Track:
    """Download a SoundCloud track and return metadata + file path.

    Runs the blocking yt-dlp call in a worker thread.
    """

    work_dir = download_root / uuid.uuid4().hex
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        track = await asyncio.to_thread(_download_sync, url, work_dir)
    except Exception:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise

    size = track.file_path.stat().st_size
    if size > max_bytes:
        track.cleanup()
        raise TrackTooLargeError(size, max_bytes)

    return track
