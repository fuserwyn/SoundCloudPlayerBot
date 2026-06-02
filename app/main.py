from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import ErrorEvent, MenuButtonWebApp, WebAppInfo

from app.config import load_settings
from app.db import AcceptanceStore
from app.handlers import build_router
from app.soundcloud import cleanup_stale_downloads


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        stream=sys.stdout,
    )
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)


async def run() -> None:
    _configure_logging()
    log = logging.getLogger("scbot")

    settings = load_settings()

    stale = cleanup_stale_downloads(settings.download_dir)
    if stale:
        log.info("Removed %d stale download dir(s) from a previous run.", stale)

    acceptance_store = AcceptanceStore(
        settings.database_url,
        settings.db_path,
        pool_max_size=settings.db_pool_max_size,
    )
    await acceptance_store.init()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(build_router(settings, acceptance_store))

    @dp.errors()
    async def on_handler_error(event: ErrorEvent) -> bool:
        log.error(
            "Handler error (update_id=%s): %s",
            event.update.update_id,
            event.exception,
            exc_info=event.exception,
        )
        return True

    me = await bot.get_me()
    log.info("Bot @%s (id=%s) started. Polling for updates…", me.username, me.id)

    if settings.webapp_url:
        wu = settings.webapp_url.rstrip("/") + "/"
        try:
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(
                    text="SoundCloud",
                    web_app=WebAppInfo(url=wu),
                )
            )
            log.info("Default private-chat menu: WebApp (SoundCloud) → %s", wu)
        except Exception as exc:
            log.warning("set_chat_menu_button failed: %s", exc)

    allowed = dp.resolve_used_update_types()
    log.info("Subscribed update types: %s", allowed)

    try:
        wh = await bot.get_webhook_info()
        log.info(
            "Telegram webhook before delete: url=%r pending=%s last_error=%r",
            wh.url,
            wh.pending_update_count,
            (wh.last_error_message or "")[:200] or None,
        )
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, allowed_updates=allowed)
    finally:
        await acceptance_store.close()
        await bot.session.close()


def main() -> None:
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
