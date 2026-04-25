"""Tiny aiohttp server: serves the Mini App static files and a /api/search endpoint.

Search uses yt-dlp's `scsearch` to query SoundCloud, the same way the bot does.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from aiohttp import web
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

logger = logging.getLogger("webapp")
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)

BASE_DIR = Path(__file__).resolve().parent
STATIC_FILES = {"index.html", "styles.css", "player.js"}
MAX_LIMIT = 20
DEFAULT_LIMIT = 10


def _search_sync(query: str, limit: int) -> list[dict[str, Any]]:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"scsearch{limit}:{query}", download=False)

    entries = (info or {}).get("entries") or []
    results: list[dict[str, Any]] = []
    for e in entries:
        if not e:
            continue
        url = e.get("webpage_url") or e.get("url") or ""
        if not isinstance(url, str) or not url.startswith("http"):
            continue
        results.append(
            {
                "title": str(e.get("title") or "Без названия"),
                "artist": str(
                    e.get("uploader") or e.get("channel") or e.get("creator") or ""
                ),
                "url": url,
                "duration": int(e.get("duration") or 0),
                "thumbnail": e.get("thumbnail") or None,
            }
        )
    return results


async def handle_search(request: web.Request) -> web.Response:
    query = (request.query.get("q") or "").strip()
    if len(query) < 2:
        return web.json_response(
            {"error": "Query must be at least 2 characters."}, status=400
        )

    try:
        limit = int(request.query.get("limit") or DEFAULT_LIMIT)
    except ValueError:
        limit = DEFAULT_LIMIT
    limit = max(1, min(MAX_LIMIT, limit))

    try:
        results = await asyncio.to_thread(_search_sync, query, limit)
    except DownloadError as exc:
        logger.warning("yt-dlp search failed for %r: %s", query, exc)
        return web.json_response({"error": "Search failed."}, status=502)
    except Exception:
        logger.exception("Unexpected error during search for %r", query)
        return web.json_response({"error": "Internal error."}, status=500)

    return web.json_response({"query": query, "results": results})


async def handle_health(_: web.Request) -> web.Response:
    return web.Response(text="ok")


async def handle_root(_: web.Request) -> web.FileResponse:
    return web.FileResponse(BASE_DIR / "index.html")


async def handle_static(request: web.Request) -> web.StreamResponse:
    name = request.match_info.get("name", "")
    if name not in STATIC_FILES:
        raise web.HTTPNotFound()
    return web.FileResponse(BASE_DIR / name)


def build_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", handle_root)
    app.router.add_get("/healthz", handle_health)
    app.router.add_get("/api/search", handle_search)
    app.router.add_get("/{name}", handle_static)
    return app


def main() -> None:
    port = int(os.getenv("PORT", "8080"))
    logger.info("Starting webapp on 0.0.0.0:%d (base=%s)", port, BASE_DIR)
    web.run_app(build_app(), host="0.0.0.0", port=port, access_log=None)


if __name__ == "__main__":
    main()
