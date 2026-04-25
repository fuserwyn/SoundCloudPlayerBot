from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.config import load_settings
from app.handlers import build_router


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

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(build_router(settings))

    me = await bot.get_me()
    log.info("Bot @%s (id=%s) started. Polling for updates…", me.username, me.id)

    allowed = dp.resolve_used_update_types()
    log.info("Subscribed update types: %s", allowed)

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, allowed_updates=allowed)
    finally:
        await bot.session.close()


def main() -> None:
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
