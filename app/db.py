"""DB: /terms acceptances and per-user request stats — PostgreSQL or SQLite (local)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Acceptance:
    user_id: int
    username: str | None
    accepted_at: str  # ISO-8601 UTC
    terms_version: str


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
        accepted_at = datetime.now(timezone.utc)
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

        now = datetime.now(timezone.utc)
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
