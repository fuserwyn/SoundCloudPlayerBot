"""Serves the Mini App: static files, /api/search, /api/playlists* (DB via app.db)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from aiohttp import web
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from tg_webapp_auth import parse_user_id_from_init_data

logger = logging.getLogger("webapp")
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = Path(__file__).resolve().parent
for p in (ROOT_DIR, ROOT_DIR.parent):
    if (p / "app" / "db.py").is_file():
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
        break
else:
    raise RuntimeError("Cannot find app/db.py (run from project root with app package).")

from app.db import AcceptanceStore  # noqa: E402

MAX_LIMIT = 20
DEFAULT_LIMIT = 10
STATIC_FILES = {"index.html", "styles.css", "player.js"}


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


def _get_init_data(request: web.Request) -> str:
    h = request.headers.get("X-Telegram-Init-Data", "").strip()
    if h:
        return h
    return (request.query.get("init_data") or "").strip()


def _require_telegram_user(request: web.Request) -> int:
    init = _get_init_data(request)
    token = (request.app.get("bot_token") or "").strip()
    if not init or not token:
        raise web.HTTPUnauthorized(
            text=json.dumps(
                {"error": "Нет данных Telegram Mini App (открой из бота)."},
                ensure_ascii=False,
            ),
            content_type="application/json; charset=utf-8",
        )
    uid = parse_user_id_from_init_data(init, token)
    if uid is None:
        raise web.HTTPUnauthorized(
            text=json.dumps(
                {
                    "error": "Сессия недействительна. Закрой и открой мини-апп снова.",
                },
                ensure_ascii=False,
            ),
            content_type="application/json; charset=utf-8",
        )
    return uid


def _load_db_settings() -> tuple[str | None, Path | None]:
    database_url = (os.getenv("DATABASE_URL") or "").strip() or None
    if database_url:
        return database_url, None
    db_path = Path(os.getenv("DB_PATH", "/data/scbot.db"))
    return None, db_path


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


async def handle_playlists_list(request: web.Request) -> web.Response:
    uid = _require_telegram_user(request)
    store: AcceptanceStore = request.app["store"]
    rows = await store.playlists_list(uid)
    return web.json_response(
        [
            {"id": r.id, "name": r.name, "track_count": r.track_count}
            for r in rows
        ]
    )


async def handle_playlist_create(request: web.Request) -> web.Response:
    uid = _require_telegram_user(request)
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "Invalid JSON."}, status=400)
    name = (body.get("name") or "").strip() if isinstance(body, dict) else ""
    if not name:
        return web.json_response({"error": "Укажи name."}, status=400)
    store: AcceptanceStore = request.app["store"]
    pid, err = await store.playlist_create(uid, name)
    if err:
        return web.json_response({"error": err}, status=400)
    return web.json_response({"id": pid, "name": name})


async def handle_playlist_get(request: web.Request) -> web.Response:
    uid = _require_telegram_user(request)
    try:
        pl_id = int(request.match_info["id"])
    except (KeyError, ValueError, TypeError):
        return web.json_response({"error": "Bad id."}, status=400)
    store: AcceptanceStore = request.app["store"]
    n = await store.playlist_name(uid, pl_id)
    if n is None:
        return web.json_response({"error": "Не найдено."}, status=404)
    tracks = await store.playlist_get_tracks(uid, pl_id)
    if tracks is None:
        return web.json_response({"error": "Не найдено."}, status=404)
    return web.json_response(
        {
            "id": pl_id,
            "name": n,
            "tracks": [
                {
                    "id": t.id,
                    "url": t.track_url,
                    "title": t.title,
                    "artist": t.artist,
                }
                for t in tracks
            ],
        }
    )


async def handle_playlist_delete(request: web.Request) -> web.Response:
    uid = _require_telegram_user(request)
    try:
        pl_id = int(request.match_info["id"])
    except (KeyError, ValueError, TypeError):
        return web.json_response({"error": "Bad id."}, status=400)
    store: AcceptanceStore = request.app["store"]
    if not await store.playlist_delete(uid, pl_id):
        return web.json_response({"error": "Не найдено."}, status=404)
    return web.json_response({"ok": True})


async def handle_playlist_add_track(request: web.Request) -> web.Response:
    uid = _require_telegram_user(request)
    try:
        pl_id = int(request.match_info["id"])
    except (KeyError, ValueError, TypeError):
        return web.json_response({"error": "Bad id."}, status=400)
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "Invalid JSON."}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "Invalid body."}, status=400)
    url = (body.get("url") or "").strip()
    title = (body.get("title") or "Без названия").strip()
    artist = (body.get("artist") or "").strip()
    if not url:
        return web.json_response({"error": "Нужен url."}, status=400)
    store: AcceptanceStore = request.app["store"]
    err = await store.playlist_add_track(uid, pl_id, url, title, artist)
    if err:
        return web.json_response({"error": err}, status=400)
    return web.json_response({"ok": True})


async def handle_playlist_remove_track(request: web.Request) -> web.Response:
    uid = _require_telegram_user(request)
    try:
        pl_id = int(request.match_info["id"])
        tr_id = int(request.match_info["track_id"])
    except (KeyError, ValueError, TypeError):
        return web.json_response({"error": "Bad id."}, status=400)
    store: AcceptanceStore = request.app["store"]
    if not await store.playlist_remove_track(uid, pl_id, tr_id):
        return web.json_response({"error": "Не найдено."}, status=404)
    return web.json_response({"ok": True})


async def handle_health(_: web.Request) -> web.Response:
    return web.Response(text="ok")


async def handle_root(_: web.Request) -> web.FileResponse:
    return web.FileResponse(BASE_DIR / "index.html")


async def handle_static(request: web.Request) -> web.StreamResponse:
    name = request.match_info.get("name", "")
    if name not in STATIC_FILES:
        raise web.HTTPNotFound()
    return web.FileResponse(BASE_DIR / name)


async def on_startup(app: web.Application) -> None:
    token = (os.getenv("TELEGRAM_API_KEY") or "").strip()
    if not token:
        logger.warning("TELEGRAM_API_KEY is empty — /api/playlists* will reject initData.")
    du, dpath = _load_db_settings()
    if not du:
        p = dpath
        if p is not None:
            p.parent.mkdir(parents=True, exist_ok=True)
    store = AcceptanceStore(du, dpath)
    await store.init()
    app["store"] = store
    app["bot_token"] = token
    logger.info("DB ready for webapp; playlists API enabled.")


async def on_cleanup(app: web.Application) -> None:
    store: AcceptanceStore | None = app.get("store")
    if store:
        await store.close()


def build_app() -> web.Application:
    app = web.Application()
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    app.router.add_get("/", handle_root)
    app.router.add_get("/healthz", handle_health)
    app.router.add_get("/api/search", handle_search)
    app.router.add_get("/api/playlists", handle_playlists_list)
    app.router.add_post("/api/playlists", handle_playlist_create)
    app.router.add_get("/api/playlists/{id}", handle_playlist_get)
    app.router.add_delete("/api/playlists/{id}", handle_playlist_delete)
    app.router.add_post("/api/playlists/{id}/tracks", handle_playlist_add_track)
    app.router.add_delete(
        "/api/playlists/{id}/tracks/{track_id}", handle_playlist_remove_track
    )
    app.router.add_get("/{name}", handle_static)
    return app


def main() -> None:
    port = int(os.getenv("PORT", "8080"))
    logger.info("Starting webapp on 0.0.0.0:%d (base=%s)", port, BASE_DIR)
    web.run_app(build_app(), host="0.0.0.0", port=port, access_log=None)


if __name__ == "__main__":
    main()
