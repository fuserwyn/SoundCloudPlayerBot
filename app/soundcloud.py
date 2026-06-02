from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

logger = logging.getLogger(__name__)

# work_dir для каждой загрузки называется uuid4().hex — 32 hex-символа.
_WORK_DIR_RE = re.compile(r"[0-9a-f]{32}")

# Глобальный предел одновременных загрузок: yt-dlp + ffmpeg прожорливы по RAM/CPU,
# без ограничения N параллельных запросов могут уронить контейнер (OOM) на малом плане.
_download_semaphore: asyncio.Semaphore | None = None


def _get_download_semaphore() -> asyncio.Semaphore:
    """Лениво создаёт семафор в работающем event loop (значение из env)."""
    global _download_semaphore
    if _download_semaphore is None:
        try:
            limit = int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "2"))
        except ValueError:
            limit = 2
        _download_semaphore = asyncio.Semaphore(max(1, limit))
    return _download_semaphore


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
    """Если файл > лимита Telegram: нарезка, все пути в одной папке work_dir."""
    chunk_paths: list[Path] | None = field(default=None, repr=False)

    def cleanup(self) -> None:
        paths: list[Path] = (
            list(self.chunk_paths) if self.chunk_paths else [self.file_path]
        )
        seen: set[str] = set()
        for fp in paths:
            key = str(fp.resolve())
            if key in seen:
                continue
            seen.add(key)
            try:
                if fp.exists():
                    fp.unlink()
            except OSError:
                logger.warning("Failed to remove %s", fp, exc_info=True)
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


def _build_ydl_opts(out_template: str, audio_bitrate: str = "192") -> dict[str, Any]:
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
                "preferredquality": audio_bitrate,
            },
            {"key": "FFmpegMetadata"},
        ],
    }


def _download_sync(url: str, work_dir: Path, audio_bitrate: str = "192") -> Track:
    out_template = str(work_dir / "%(title).200B.%(ext)s")
    opts = _build_ydl_opts(out_template, audio_bitrate)

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
    )


def _read_audio_duration(file_path: Path) -> int:
    try:
        from mutagen.mp3 import MP3

        return int(MP3(file_path).info.length)
    except Exception:
        return 0


def _ffprobe_duration_sec(path: Path) -> float:
    r = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if r.returncode != 0 or not (r.stdout or "").strip():
        return 0.0
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def _audio_duration_seconds(path: Path) -> float:
    d = _read_audio_duration(path)
    if d > 0:
        return float(d)
    return _ffprobe_duration_sec(path)


def read_mp3_duration_seconds(file_path: Path) -> int:
    """Длительность готового mp3 (чанк или целиком) в секундах."""
    d = _read_audio_duration(file_path)
    if d > 0:
        return d
    return int(_ffprobe_duration_sec(file_path) or 0)


def _ffmpeg_segment_to_chunks(
    src: Path, work_dir: Path, segment_seconds: float
) -> list[Path]:
    for old in work_dir.glob("chunk_*.mp3"):
        try:
            old.unlink()
        except OSError:
            pass
    out_tmpl = str(work_dir / "chunk_%03d.mp3")
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(src),
        "-f",
        "segment",
        "-segment_time",
        f"{segment_seconds:.6f}",
        "-c",
        "copy",
        "-reset_timestamps",
        "1",
        out_tmpl,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
    if r.returncode != 0:
        logger.error(
            "ffmpeg segment failed: %s",
            (r.stderr or r.stdout or "")[:2500],
        )
        raise SoundCloudError("Не удалось нарезать трек (ffmpeg).")
    parts = sorted(work_dir.glob("chunk_*.mp3"))
    if not parts:
        raise SoundCloudError("Нарезка не создала файлов.")
    return parts


def _split_mp3_into_chunks(src: Path, max_bytes: int, work_dir: Path) -> list[Path]:
    """Делит один mp3 на несколько, каждый ≤ max_bytes (Telegram Bot API)."""
    size = src.stat().st_size
    if size <= max_bytes:
        return [src]
    dur = _audio_duration_seconds(src)
    if dur <= 0:
        raise SoundCloudError("Не удалось определить длительность для нарезки.")
    # Цель по размеру с запасом под VBR
    target = max(int(max_bytes * 0.82), 1024 * 1024)
    n = max(2, (size + target - 1) // target)
    for _ in range(14):
        seg_dur = dur / n
        parts = _ffmpeg_segment_to_chunks(src, work_dir, seg_dur)
        if all(p.stat().st_size <= max_bytes for p in parts):
            try:
                src.unlink()
            except OSError as exc:
                logger.warning("Remove source after split: %s", exc)
            return parts
        n = n + max(1, n // 3)
    raise SoundCloudError(
        "Не удалось нарезать трек: части всё ещё больше лимита Telegram (50 МБ)."
    )


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


def cleanup_stale_downloads(download_root: Path) -> int:
    """Удаляет осиротевшие per-download папки (например, после краша процесса).

    Безопасно: трогает только каталоги с именем-uuid (как их создаёт download_track),
    а не сам download_root и не посторонние файлы. Возвращает число удалённых.
    """
    removed = 0
    try:
        entries = list(download_root.iterdir())
    except OSError:
        return 0
    for entry in entries:
        if entry.is_dir() and _WORK_DIR_RE.fullmatch(entry.name):
            shutil.rmtree(entry, ignore_errors=True)
            removed += 1
    return removed


async def download_track(
    url: str,
    download_root: Path,
    max_bytes: int,
    audio_bitrate: str = "192",
) -> Track:
    """Download a SoundCloud track and return metadata + file path.

    Runs the blocking yt-dlp call in a worker thread. Параллелизм ограничен
    глобальным семафором (MAX_CONCURRENT_DOWNLOADS), чтобы не выжрать RAM/CPU.
    """

    async with _get_download_semaphore():
        work_dir = download_root / uuid.uuid4().hex
        work_dir.mkdir(parents=True, exist_ok=True)

        try:
            track = await asyncio.to_thread(
                _download_sync, url, work_dir, audio_bitrate
            )
        except Exception:
            shutil.rmtree(work_dir, ignore_errors=True)
            raise

        size = track.file_path.stat().st_size
        if size > max_bytes:
            try:
                parts = await asyncio.to_thread(
                    _split_mp3_into_chunks, track.file_path, max_bytes, work_dir
                )
            except Exception:
                track.cleanup()
                shutil.rmtree(work_dir, ignore_errors=True)
                raise
            track.chunk_paths = parts
            track.file_path = parts[0]

        return track
