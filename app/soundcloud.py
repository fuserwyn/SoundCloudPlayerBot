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

INSTAGRAM_REEL_RE = re.compile(
    r"https?://(?:www\.)?(?:instagram\.com|instagr\.am)/(?:reel|reels|share/reel)/[A-Za-z0-9_-]+[^\s]*",
    re.IGNORECASE,
)

TIKTOK_URL_RE = re.compile(
    r"https?://(?:(?:www|m|vm|vt|lc)\.)?tiktok\.com/[^\s]+",
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
class SearchResult:
    title: str
    artist: str
    url: str
    duration: int  # seconds, 0 if unknown
    thumbnail: str | None = None


@dataclass
class Track:
    file_path: Path
    title: str
    artist: str
    duration: int  # seconds (from SoundCloud metadata, i.e. full track length)
    actual_duration: int  # seconds (length of the downloaded file)
    is_preview: bool  # True when SoundCloud only let us grab a short snippet
    thumbnail_url: str | None
    webpage_url: str
    is_video: bool = False  # True for short vertical video (Reels, TikTok, …), send as video

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


def _strip_trailing_junk(url: str) -> str:
    while url and url[-1] in ").,];\"'":
        url = url[:-1]
    return url


def find_instagram_reel_url(text: str) -> str | None:
    match = INSTAGRAM_REEL_RE.search(text or "")
    return _strip_trailing_junk(match.group(0)) if match else None


def find_tiktok_url(text: str) -> str | None:
    match = TIKTOK_URL_RE.search(text or "")
    return _strip_trailing_junk(match.group(0)) if match else None


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
    claimed = int(info.get("duration") or 0)
    actual = _read_audio_duration(file_path) or claimed
    is_preview = bool(claimed and actual and actual < claimed * 0.6)
    return Track(
        file_path=file_path,
        title=title,
        artist=_extract_artist(info),
        duration=claimed,
        actual_duration=actual,
        is_preview=is_preview,
        thumbnail_url=info.get("thumbnail"),
        webpage_url=str(info.get("webpage_url") or url),
        is_video=False,
    )


def _read_audio_duration(file_path: Path) -> int:
    try:
        from mutagen.mp3 import MP3

        return int(MP3(file_path).info.length)
    except Exception:
        return 0


def _read_video_duration(file_path: Path) -> int:
    try:
        from mutagen.mp4 import MP4

        return int(MP4(file_path).info.length)
    except Exception:
        return 0


def _download_merged_mp4_sync(url: str, work_dir: Path) -> Track:
    """Download a short public video (Instagram Reels, TikTok, …) as mp4 via yt-dlp."""

    out_template = str(work_dir / "%(title).200B.%(ext)s")
    opts: dict[str, Any] = {
        "format": (
            "bestvideo[ext=mp4][vcodec!=none]+bestaudio[ext=m4a]/"
            "bestvideo[vcodec!=none]+bestaudio/best[vcodec!=none]/best"
        ),
        "outtmpl": out_template,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "merge_output_format": "mp4",
        "restrictfilenames": True,
    }

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
            raise SoundCloudError("Список пуст.")
        info = entries[0]

    requested = info.get("requested_downloads") or []
    file_path: Path | None = None
    if requested:
        file_path = Path(requested[0].get("filepath") or requested[0].get("_filename"))
    if file_path is None or not file_path.exists():
        candidate = info.get("filepath") or info.get("_filename")
        file_path = Path(candidate) if candidate else None
    if file_path is None or not file_path.exists():
        mp4s = sorted(work_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
        if mp4s:
            file_path = mp4s[0]
    if file_path is None or not file_path.exists():
        webms = sorted(work_dir.glob("*.webm"), key=lambda p: p.stat().st_mtime, reverse=True)
        if webms:
            file_path = webms[0]
    if file_path is None or not file_path.exists():
        raise SoundCloudError("Скачанный файл не найден на диске.")

    title = str(info.get("title") or file_path.stem)
    claimed = int(info.get("duration") or 0)
    actual = _read_video_duration(file_path) or claimed
    if actual <= 0 and file_path.suffix.lower() == ".webm":
        actual = claimed

    return Track(
        file_path=file_path,
        title=title[:200],
        artist=_extract_artist(info),
        duration=claimed,
        actual_duration=actual,
        is_preview=False,
        thumbnail_url=info.get("thumbnail"),
        webpage_url=str(info.get("webpage_url") or url),
        is_video=True,
    )


async def download_short_video(
    url: str,
    download_root: Path,
    max_bytes: int,
) -> Track:
    """Instagram Reels, TikTok, and similar URLs handled by yt-dlp."""

    work_dir = download_root / uuid.uuid4().hex
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        track = await asyncio.to_thread(_download_merged_mp4_sync, url, work_dir)
    except Exception:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise

    size = track.file_path.stat().st_size
    if size > max_bytes:
        track.cleanup()
        raise TrackTooLargeError(size, max_bytes)

    return track


def _search_sync(query: str, limit: int) -> list[SearchResult]:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
    }
    search_url = f"scsearch{limit}:{query}"
    with YoutubeDL(opts) as ydl:
        try:
            info = ydl.extract_info(search_url, download=False)
        except DownloadError as exc:
            raise SoundCloudError(f"Search failed: {exc}") from exc

    entries = (info or {}).get("entries") or []
    results: list[SearchResult] = []
    for e in entries:
        if not e:
            continue
        url = e.get("webpage_url") or e.get("url") or ""
        if not url.startswith("http"):
            continue
        thumb = e.get("thumbnail")
        if not thumb:
            thumbnails = e.get("thumbnails") or []
            if thumbnails:
                thumb = thumbnails[-1].get("url")
        results.append(
            SearchResult(
                title=str(e.get("title") or "Без названия"),
                artist=str(
                    e.get("uploader") or e.get("channel") or e.get("creator") or ""
                ),
                url=url,
                duration=int(e.get("duration") or 0),
                thumbnail=str(thumb) if thumb else None,
            )
        )
    return results


async def search_tracks(query: str, limit: int = 10) -> list[SearchResult]:
    """Search SoundCloud via yt-dlp's scsearch and return lightweight metadata."""
    query = (query or "").strip()
    if not query:
        return []
    return await asyncio.to_thread(_search_sync, query, limit)


def tag_id3(file_path: Path, bot_tag: str) -> None:
    """Stamp the mp3 with bot attribution in COMM and TENC ID3 frames.

    Best-effort: any failure is logged but never raised, since attribution
    is non-essential and we don't want to block delivery of the file.
    """
    if not bot_tag:
        return
    try:
        from mutagen.id3 import COMM, ID3, TENC, ID3NoHeaderError

        try:
            tags = ID3(file_path)
        except ID3NoHeaderError:
            tags = ID3()
        comment = f"Downloaded via {bot_tag}"
        tags.delall("COMM")
        tags.add(COMM(encoding=3, lang="eng", desc="", text=comment))
        tags.delall("TENC")
        tags.add(TENC(encoding=3, text=bot_tag))
        tags.save(file_path, v2_version=3)
    except Exception:
        logger.warning("Failed to stamp ID3 tag on %s", file_path, exc_info=True)


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
