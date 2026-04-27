"""DB: /terms acceptances and per-user request stats — PostgreSQL or SQLite (local)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import aiosqlite

logger = logging.getLogger(__name__)

# Все отметки времени в БД — с часовым поясом Москвы (отображение в SQLite как +03:00).
MSK = ZoneInfo("Europe/Moscow")


def _now_msk() -> datetime:
    return datetime.now(MSK)

# Плейлисты (на пользователя)
MAX_PLAYLISTS = 20
MAX_PLAYLIST_NAME_LEN = 64
MAX_TRACKS_IN_PLAYLIST = 150


def _thumb_out(val: object) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    return s or None


def _thumb_in(url: str | None) -> str | None:
    s = (url or "").strip()
    if not s:
        return None
    return s[:2000]


@dataclass(frozen=True)
class Acceptance:
    user_id: int
    username: str | None
    accepted_at: str  # ISO-8601, Europe/Moscow
    terms_version: str


@dataclass(frozen=True)
class PlaylistSummary:
    id: int
    name: str
    track_count: int


@dataclass(frozen=True)
class PlaylistEntry:
    id: int
    track_url: str
    title: str
    artist: str
    thumbnail_url: str | None = None


class AcceptanceStore:
    def __init__(self, database_url: str | None, db_path: Path | None) -> None:
        self._database_url = database_url
        self._db_path = db_path
        self._pool: Any = None

    async def init(self) -> None:
        if self._database_url:
            import asyncpg as _asyncpg

            # statement_cache_size=0: safe with PgBouncer (Railway) in transaction mode
            self._pool = await _asyncpg.create_pool(
                self._database_url,
                min_size=1,
                max_size=5,
                statement_cache_size=0,
            )
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS acceptances (
                        user_id       BIGINT NOT NULL,
                        terms_version TEXT    NOT NULL,
                        username      TEXT,
                        accepted_at   TIMESTAMPTZ NOT NULL,
                        PRIMARY KEY (user_id, terms_version)
                    )
                    """
                )
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS bot_users (
                        user_id        BIGINT PRIMARY KEY,
                        username       TEXT,
                        first_seen     TIMESTAMPTZ NOT NULL,
                        last_seen      TIMESTAMPTZ NOT NULL,
                        request_count  BIGINT NOT NULL
                    )
                    """
                )
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS playlists (
                        id         BIGSERIAL PRIMARY KEY,
                        user_id    BIGINT NOT NULL,
                        name       TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_playlists_user ON playlists (user_id)"
                )
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS playlist_tracks (
                        id            BIGSERIAL PRIMARY KEY,
                        playlist_id   BIGINT NOT NULL
                            REFERENCES playlists (id) ON DELETE CASCADE,
                        track_url     TEXT NOT NULL,
                        title         TEXT NOT NULL,
                        artist        TEXT NOT NULL,
                        sort_order    INT NOT NULL,
                        created_at    TIMESTAMPTZ NOT NULL,
                        UNIQUE (playlist_id, track_url)
                    )
                    """
                )
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_playlist_tracks_pl "
                    "ON playlist_tracks (playlist_id, sort_order)"
                )
                await conn.execute(
                    "ALTER TABLE playlist_tracks "
                    "ADD COLUMN IF NOT EXISTS thumbnail_url TEXT"
                )
            logger.info("Acceptance DB ready (PostgreSQL)")
            return

        if not self._db_path:
            raise RuntimeError(
                "Configure DATABASE_URL (PostgreSQL) or DB_PATH (SQLite) for acceptances."
            )

        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS acceptances (
                    user_id       INTEGER NOT NULL,
                    terms_version TEXT    NOT NULL,
                    username      TEXT,
                    accepted_at   TEXT    NOT NULL,
                    PRIMARY KEY (user_id, terms_version)
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS bot_users (
                    user_id        INTEGER NOT NULL,
                    username       TEXT,
                    first_seen     TEXT    NOT NULL,
                    last_seen      TEXT    NOT NULL,
                    request_count  INTEGER NOT NULL,
                    PRIMARY KEY (user_id)
                )
                """
            )
            await db.execute("PRAGMA foreign_keys = ON")
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS playlists (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id    INTEGER NOT NULL,
                    name       TEXT    NOT NULL,
                    created_at TEXT    NOT NULL
                )
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_playlists_user ON playlists (user_id)"
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS playlist_tracks (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    playlist_id   INTEGER NOT NULL
                        REFERENCES playlists (id) ON DELETE CASCADE,
                    track_url     TEXT    NOT NULL,
                    title         TEXT    NOT NULL,
                    artist        TEXT    NOT NULL,
                    sort_order    INTEGER NOT NULL,
                    created_at    TEXT    NOT NULL,
                    UNIQUE (playlist_id, track_url)
                )
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_playlist_tracks_pl "
                "ON playlist_tracks (playlist_id, sort_order)"
            )
            cur = await db.execute("PRAGMA table_info(playlist_tracks)")
            col_names = {r[1] for r in await cur.fetchall()}
            if "thumbnail_url" not in col_names:
                await db.execute(
                    "ALTER TABLE playlist_tracks ADD COLUMN thumbnail_url TEXT"
                )
            await db.commit()
        logger.info("Acceptance DB ready (SQLite) at %s", self._db_path)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def has_accepted(self, user_id: int, terms_version: str) -> bool:
        if self._pool is not None:
            async with self._pool.acquire() as conn:
                row = await conn.fetchval(
                    "SELECT 1 FROM acceptances WHERE user_id = $1 AND terms_version = $2",
                    user_id,
                    terms_version,
                )
                return row is not None

        assert self._db_path is not None
        async with aiosqlite.connect(self._db_path) as db:
            cur = await db.execute(
                "SELECT 1 FROM acceptances WHERE user_id = ? AND terms_version = ?",
                (user_id, terms_version),
            )
            row = await cur.fetchone()
            return row is not None

    async def record(
        self, user_id: int, username: str | None, terms_version: str
    ) -> Acceptance:
        accepted_at = _now_msk()
        accepted_iso = accepted_at.isoformat(timespec="seconds")

        if self._pool is not None:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO acceptances (user_id, terms_version, username, accepted_at)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (user_id, terms_version) DO UPDATE SET
                        username = EXCLUDED.username,
                        accepted_at = EXCLUDED.accepted_at
                    """,
                    user_id,
                    terms_version,
                    username,
                    accepted_at,
                )
        else:
            assert self._db_path is not None
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute(
                    """
                    INSERT OR REPLACE INTO acceptances
                        (user_id, terms_version, username, accepted_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (user_id, terms_version, username, accepted_iso),
                )
                await db.commit()

        logger.info(
            "Recorded acceptance: user_id=%s username=%s terms_version=%s",
            user_id,
            username,
            terms_version,
        )
        return Acceptance(
            user_id=user_id,
            username=username,
            accepted_at=accepted_iso,
            terms_version=terms_version,
        )

    async def record_user_request(self, user_id: int, username: str | None) -> int:
        """Upsert user row and increment request_count. Returns the new count."""
        if username is not None:
            u = username.strip()
            username = u if u else None

        now = _now_msk()
        if self._pool is not None:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO bot_users (user_id, username, first_seen, last_seen, request_count)
                    VALUES ($1, $2, $3, $3, 1)
                    ON CONFLICT (user_id) DO UPDATE SET
                        username = COALESCE($2, bot_users.username),
                        last_seen = EXCLUDED.last_seen,
                        request_count = bot_users.request_count + 1
                    RETURNING request_count
                    """,
                    user_id,
                    username,
                    now,
                )
                return int(row["request_count"]) if row else 1

        assert self._db_path is not None
        now_iso = now.isoformat(timespec="seconds")
        async with aiosqlite.connect(self._db_path) as db:
            cur = await db.execute(
                """
                INSERT INTO bot_users (user_id, username, first_seen, last_seen, request_count)
                VALUES (?, ?, ?, ?, 1)
                ON CONFLICT (user_id) DO UPDATE SET
                    username = COALESCE(excluded.username, username),
                    last_seen = excluded.last_seen,
                    request_count = request_count + 1
                RETURNING request_count
                """,
                (user_id, username, now_iso, now_iso),
            )
            row = await cur.fetchone()
            await db.commit()
            return int(row[0]) if row else 1

    @staticmethod
    def _normalize_playlist_name(name: str) -> str | None:
        n = name.strip()
        if not n:
            return None
        if len(n) > MAX_PLAYLIST_NAME_LEN:
            n = n[:MAX_PLAYLIST_NAME_LEN]
        return n

    async def playlists_list(self, user_id: int) -> list[PlaylistSummary]:
        if self._pool is not None:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT p.id, p.name, COUNT(t.id)::bigint AS tc
                    FROM playlists p
                    LEFT JOIN playlist_tracks t ON t.playlist_id = p.id
                    WHERE p.user_id = $1
                    GROUP BY p.id, p.name
                    ORDER BY p.id ASC
                    """,
                    user_id,
                )
                return [
                    PlaylistSummary(
                        id=int(r["id"]),
                        name=str(r["name"]),
                        track_count=int(r["tc"]),
                    )
                    for r in rows
                ]

        assert self._db_path is not None
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            cur = await db.execute(
                """
                SELECT p.id, p.name, COUNT(t.id) AS tc
                FROM playlists p
                LEFT JOIN playlist_tracks t ON t.playlist_id = p.id
                WHERE p.user_id = ?
                GROUP BY p.id, p.name
                ORDER BY p.id ASC
                """,
                (user_id,),
            )
            rows = await cur.fetchall()
            return [
                PlaylistSummary(id=int(r[0]), name=str(r[1]), track_count=int(r[2]))
                for r in rows
            ]

    async def playlist_create(
        self, user_id: int, name: str
    ) -> tuple[int | None, str | None]:
        """Returns (playlist_id, None) or (None, error_message)."""
        n = self._normalize_playlist_name(name)
        if not n:
            return None, "Укажи непустое название."
        now = _now_msk()
        if self._pool is not None:
            async with self._pool.acquire() as conn:
                cnt = await conn.fetchval(
                    "SELECT COUNT(*) FROM playlists WHERE user_id = $1",
                    user_id,
                )
                if int(cnt or 0) >= MAX_PLAYLISTS:
                    return None, (
                        f"Уже {MAX_PLAYLISTS} плейлистов — это максимум. "
                        "Удали лишний через /pl."
                    )
                row = await conn.fetchrow(
                    """
                    INSERT INTO playlists (user_id, name, created_at)
                    VALUES ($1, $2, $3)
                    RETURNING id
                    """,
                    user_id,
                    n,
                    now,
                )
                return (int(row["id"]), None) if row else (None, "Не удалось создать.")

        assert self._db_path is not None
        now_iso = now.isoformat(timespec="seconds")
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            cur = await db.execute(
                "SELECT COUNT(*) FROM playlists WHERE user_id = ?",
                (user_id,),
            )
            r = await cur.fetchone()
            if int(r[0]) >= MAX_PLAYLISTS:
                return None, (
                    f"Уже {MAX_PLAYLISTS} плейлистов — это максимум. "
                    "Удали лишний через /pl."
                )
            cur = await db.execute(
                """
                INSERT INTO playlists (user_id, name, created_at)
                VALUES (?, ?, ?)
                """,
                (user_id, n, now_iso),
            )
            await db.commit()
            cur = await db.execute("SELECT last_insert_rowid()")
            lid = await cur.fetchone()
            return (int(lid[0]), None) if lid else (None, "Не удалось создать.")

    async def playlist_delete(self, user_id: int, playlist_id: int) -> bool:
        if self._pool is not None:
            async with self._pool.acquire() as conn:
                r = await conn.execute(
                    "DELETE FROM playlists WHERE id = $1 AND user_id = $2",
                    playlist_id,
                    user_id,
                )
                return str(r).split()[-1] == "1"

        assert self._db_path is not None
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            cur = await db.execute(
                "DELETE FROM playlists WHERE id = ? AND user_id = ?",
                (playlist_id, user_id),
            )
            await db.commit()
            return bool(cur.rowcount and cur.rowcount > 0)

    async def playlist_name(
        self, user_id: int, playlist_id: int
    ) -> str | None:
        if self._pool is not None:
            async with self._pool.acquire() as conn:
                val = await conn.fetchval(
                    "SELECT name FROM playlists WHERE id = $1 AND user_id = $2",
                    playlist_id,
                    user_id,
                )
                return str(val) if val is not None else None

        assert self._db_path is not None
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            cur = await db.execute(
                "SELECT name FROM playlists WHERE id = ? AND user_id = ?",
                (playlist_id, user_id),
            )
            r = await cur.fetchone()
            return str(r[0]) if r else None

    async def playlist_get_tracks(
        self, user_id: int, playlist_id: int
    ) -> list[PlaylistEntry] | None:
        """None if плейлист не найден или чужой."""
        if self._pool is not None:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT 1 FROM playlists WHERE id = $1 AND user_id = $2",
                    playlist_id,
                    user_id,
                )
                if row is None:
                    return None
                rows = await conn.fetch(
                    """
                    SELECT t.id, t.track_url, t.title, t.artist, t.thumbnail_url
                    FROM playlist_tracks t
                    WHERE t.playlist_id = $1
                    ORDER BY t.sort_order ASC, t.id ASC
                    """,
                    playlist_id,
                )
                return [
                    PlaylistEntry(
                        id=int(r["id"]),
                        track_url=str(r["track_url"]),
                        title=str(r["title"]),
                        artist=str(r["artist"]),
                        thumbnail_url=_thumb_out(r["thumbnail_url"]),
                    )
                    for r in rows
                ]

        assert self._db_path is not None
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            cur = await db.execute(
                "SELECT 1 FROM playlists WHERE id = ? AND user_id = ?",
                (playlist_id, user_id),
            )
            if not await cur.fetchone():
                return None
            cur = await db.execute(
                """
                SELECT t.id, t.track_url, t.title, t.artist, t.thumbnail_url
                FROM playlist_tracks t
                WHERE t.playlist_id = ?
                ORDER BY t.sort_order ASC, t.id ASC
                """,
                (playlist_id,),
            )
            rows = await cur.fetchall()
            return [
                PlaylistEntry(
                    id=int(r[0]),
                    track_url=str(r[1]),
                    title=str(r[2]),
                    artist=str(r[3]),
                    thumbnail_url=_thumb_out(r[4] if len(r) > 4 else None),
                )
                for r in rows
            ]

    async def playlist_add_track(
        self,
        user_id: int,
        playlist_id: int,
        track_url: str,
        title: str,
        artist: str,
        thumbnail_url: str | None = None,
    ) -> str | None:
        """None если ок, иначе текст ошибки."""
        t_title = (title or "Без названия")[:500]
        t_artist = (artist or "")[:500]
        t_thumb = _thumb_in(thumbnail_url)
        url = track_url.strip()
        if not url:
            return "Пустая ссылка."
        now = _now_msk()
        if self._pool is not None:
            import asyncpg

            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT 1 FROM playlists WHERE id = $1 AND user_id = $2",
                    playlist_id,
                    user_id,
                )
                if row is None:
                    return "Плейлист не найден."
                cnt = await conn.fetchval(
                    "SELECT COUNT(*) FROM playlist_tracks WHERE playlist_id = $1",
                    playlist_id,
                )
                if int(cnt or 0) >= MAX_TRACKS_IN_PLAYLIST:
                    return f"В плейлисте уже {MAX_TRACKS_IN_PLAYLIST} треков (лимит)."
                try:
                    await conn.execute(
                        """
                        INSERT INTO playlist_tracks
                            (playlist_id, track_url, title, artist, sort_order,
                             created_at, thumbnail_url)
                        VALUES (
                            $1, $2, $3, $4,
                            (SELECT COALESCE(MAX(t2.sort_order), 0) + 1
                             FROM playlist_tracks t2 WHERE t2.playlist_id = $1),
                            $5, $6
                        )
                        """,
                        playlist_id,
                        url,
                        t_title,
                        t_artist,
                        now,
                        t_thumb,
                    )
                except asyncpg.UniqueViolationError:
                    return "Этот трек уже в плейлисте."
        else:
            assert self._db_path is not None
            import sqlite3

            async with aiosqlite.connect(self._db_path) as db:
                await db.execute("PRAGMA foreign_keys = ON")
                cur = await db.execute(
                    "SELECT 1 FROM playlists WHERE id = ? AND user_id = ?",
                    (playlist_id, user_id),
                )
                if not await cur.fetchone():
                    return "Плейлист не найден."
                cur = await db.execute(
                    "SELECT COUNT(*) FROM playlist_tracks WHERE playlist_id = ?",
                    (playlist_id,),
                )
                r1 = await cur.fetchone()
                if int(r1[0]) >= MAX_TRACKS_IN_PLAYLIST:
                    return f"В плейлисте уже {MAX_TRACKS_IN_PLAYLIST} треков (лимит)."
                try:
                    cur = await db.execute(
                        """
                        INSERT INTO playlist_tracks
                            (playlist_id, track_url, title, artist, sort_order,
                             created_at, thumbnail_url)
                        VALUES (?, ?, ?, ?,
                            (SELECT COALESCE(MAX(t2.sort_order), 0) + 1
                             FROM playlist_tracks t2 WHERE t2.playlist_id = ?),
                            ?, ?)
                        """,
                        (
                            playlist_id,
                            url,
                            t_title,
                            t_artist,
                            playlist_id,
                            now.isoformat(timespec="seconds"),
                            t_thumb,
                        ),
                    )
                except sqlite3.IntegrityError:
                    return "Этот трек уже в плейлисте."
                await db.commit()
        return None

    async def playlist_remove_track(
        self, user_id: int, playlist_id: int, track_id: int
    ) -> bool:
        if self._pool is not None:
            async with self._pool.acquire() as conn:
                r = await conn.execute(
                    """
                    DELETE FROM playlist_tracks
                    WHERE id = $1 AND playlist_id = $2
                      AND EXISTS (
                        SELECT 1 FROM playlists p
                        WHERE p.id = $2 AND p.user_id = $3
                      )
                    """,
                    track_id,
                    playlist_id,
                    user_id,
                )
                return str(r).split()[-1] == "1"

        assert self._db_path is not None
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            cur = await db.execute(
                """
                DELETE FROM playlist_tracks
                WHERE id = ? AND playlist_id = ?
                  AND EXISTS (
                    SELECT 1 FROM playlists p
                    WHERE p.id = ? AND p.user_id = ?
                  )
                """,
                (track_id, playlist_id, playlist_id, user_id),
            )
            await db.commit()
            return bool(cur.rowcount and cur.rowcount > 0)

    async def playlist_track_coverage(
        self, user_id: int, track_url: str
    ) -> tuple[int, int] | None:
        """(всего плейлистов, в скольких есть track_url). None если пустой url."""
        url = (track_url or "").strip()
        if not url:
            return None
        if self._pool is not None:
            async with self._pool.acquire() as conn:
                total = await conn.fetchval(
                    "SELECT COUNT(*)::bigint FROM playlists WHERE user_id = $1", user_id
                )
                with_t = await conn.fetchval(
                    """
                    SELECT COUNT(DISTINCT pt.playlist_id)::bigint
                    FROM playlist_tracks pt
                    INNER JOIN playlists p ON p.id = pt.playlist_id
                    WHERE p.user_id = $1 AND pt.track_url = $2
                    """,
                    user_id,
                    url,
                )
                return (int(total or 0), int(with_t or 0))

        assert self._db_path is not None
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            cur = await db.execute(
                "SELECT COUNT(*) FROM playlists WHERE user_id = ?",
                (user_id,),
            )
            r0 = await cur.fetchone()
            total = int(r0[0] if r0 else 0)
            cur = await db.execute(
                """
                SELECT COUNT(DISTINCT pt.playlist_id) FROM playlist_tracks pt
                INNER JOIN playlists p ON p.id = pt.playlist_id
                WHERE p.user_id = ? AND pt.track_url = ?
                """,
                (user_id, url),
            )
            r1 = await cur.fetchone()
            with_t = int(r1[0] if r1 else 0)
        return (total, with_t)

    async def playlist_reorder_tracks(
        self, user_id: int, playlist_id: int, track_ids: list[int]
    ) -> str | None:
        """None если ok. track_ids — полный желаемый порядок id."""
        if not track_ids:
            return "Пустой список."
        if len(track_ids) != len(set(track_ids)):
            return "Повтор id трека."
        if self._pool is not None:
            async with self._pool.acquire() as conn:
                async with conn.transaction():
                    row = await conn.fetchrow(
                        "SELECT 1 FROM playlists WHERE id = $1 AND user_id = $2",
                        playlist_id,
                        user_id,
                    )
                    if row is None:
                        return "Плейлист не найден."
                    rows = await conn.fetch(
                        "SELECT id FROM playlist_tracks WHERE playlist_id = $1",
                        playlist_id,
                    )
                    existing = {int(r["id"]) for r in rows}
                    if set(track_ids) != existing:
                        return "Список треков не совпадает с плейлистом."
                    for new_o, tid in enumerate(track_ids, start=1):
                        await conn.execute(
                            """
                            UPDATE playlist_tracks SET sort_order = $1
                            WHERE id = $2 AND playlist_id = $3
                            """,
                            new_o,
                            tid,
                            playlist_id,
                        )
        else:
            assert self._db_path is not None

            async with aiosqlite.connect(self._db_path) as db:
                await db.execute("PRAGMA foreign_keys = ON")
                cur = await db.execute(
                    "SELECT 1 FROM playlists WHERE id = ? AND user_id = ?",
                    (playlist_id, user_id),
                )
                if not await cur.fetchone():
                    return "Плейлист не найден."
                cur = await db.execute(
                    "SELECT id FROM playlist_tracks WHERE playlist_id = ?",
                    (playlist_id,),
                )
                rows = await cur.fetchall()
                existing = {int(r[0]) for r in rows}
                if set(track_ids) != existing:
                    return "Список треков не совпадает с плейлистом."
                for new_o, tid in enumerate(track_ids, start=1):
                    await db.execute(
                        """
                        UPDATE playlist_tracks SET sort_order = ?
                        WHERE id = ? AND playlist_id = ?
                        """,
                        (new_o, tid, playlist_id),
                    )
                await db.commit()
        return None
