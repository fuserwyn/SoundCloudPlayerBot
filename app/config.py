from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Settings:
    bot_token: str
    download_dir: Path
    """PostgreSQL DSN (Railway sets DATABASE_URL). If None, SQLite uses db_path."""
    database_url: str | None
    """SQLite file when database_url is unset (local dev)."""
    db_path: Path | None
    webapp_url: str | None
    groq_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"
    max_upload_bytes: int = 50 * 1024 * 1024  # Telegram Bot API hard limit for audio
    request_timeout: int = 120


def _read_webapp_url(wait_seconds: int) -> str | None:
    """Resolve the Mini App URL.

    Priority:
      1. WEBAPP_URL env var (explicit override, e.g. for production hosting).
      2. WEBAPP_URL_FILE path (written by the tunnel sidecar). We wait up
         to `wait_seconds` for the file to appear so the bot survives
         compose start-up ordering.
    """

    explicit = os.getenv("WEBAPP_URL", "").strip()
    if explicit:
        logger.info("Using WEBAPP_URL from env: %s", explicit)
        return explicit.rstrip("/")

    url_file_env = os.getenv("WEBAPP_URL_FILE", "").strip()
    if not url_file_env:
        logger.info("WEBAPP_URL / WEBAPP_URL_FILE not set, Mini App disabled.")
        return None

    url_file = Path(url_file_env)
    deadline = time.time() + max(0, wait_seconds)
    logged_waiting = False
    while time.time() < deadline:
        if url_file.exists():
            value = url_file.read_text().strip()
            if value:
                logger.info("Picked up Mini App URL from %s: %s", url_file, value)
                return value.rstrip("/")
        if not logged_waiting:
            logger.info("Waiting for tunnel URL at %s ...", url_file)
            logged_waiting = True
        time.sleep(1)

    logger.warning(
        "Tunnel URL file %s did not appear within %ds, Mini App disabled.",
        url_file,
        wait_seconds,
    )
    return None


def load_settings() -> Settings:
    token = os.getenv("TELEGRAM_API_KEY")
    if not token:
        raise RuntimeError(
            "TELEGRAM_API_KEY is not set. Put it into .env or pass as env var."
        )

    download_dir = Path(os.getenv("DOWNLOAD_DIR", "/tmp/scbot"))
    download_dir.mkdir(parents=True, exist_ok=True)

    database_url = (os.getenv("DATABASE_URL") or "").strip() or None

    db_path: Path | None = None
    if not database_url:
        db_path = Path(os.getenv("DB_PATH", "/data/scbot.db"))
        try:
            db_path.parent.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            fallback = Path("/tmp/scbot.db")
            logger.warning(
                "DB_PATH parent %s is not writable, falling back to %s. "
                "For production use DATABASE_URL (PostgreSQL) on Railway.",
                db_path.parent,
                fallback,
            )
            db_path = fallback
        logger.info("Using SQLite for acceptances at %s", db_path)
        logger.warning(
            "SQLite: при деплое нового контейнера файл БД обычно пустой — плейлисты "
            "и /terms сбрасываются. В проде задай ОДИН AND тот же DATABASE_URL "
            "(Postgres) сервисам «бот» и «webapp» в Railway, либо повесь volume на "
            "каталог с .db (DB_PATH)."
        )
    else:
        logger.info("Using PostgreSQL for acceptances (DATABASE_URL is set).")

    wait_seconds = int(os.getenv("WEBAPP_URL_WAIT_SECONDS", "120"))
    webapp_url = _read_webapp_url(wait_seconds)

    groq_api_key = (os.getenv("GROQ_API_KEY") or "").strip() or None
    groq_model = (os.getenv("GROQ_MODEL") or "llama-3.3-70b-versatile").strip()
    if groq_api_key:
        logger.info("Groq LLM enabled (model=%s).", groq_model)
    else:
        logger.info("GROQ_API_KEY not set, /smart and /playlist disabled.")

    return Settings(
        bot_token=token,
        download_dir=download_dir,
        database_url=database_url,
        db_path=db_path,
        webapp_url=webapp_url,
        groq_api_key=groq_api_key,
        groq_model=groq_model,
    )
