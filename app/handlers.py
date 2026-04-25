from __future__ import annotations

import logging
from urllib.parse import quote

from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)
from aiogram.utils.markdown import hbold

from app.config import Settings
from app.soundcloud import (
    SoundCloudError,
    TrackTooLargeError,
    download_track,
    find_soundcloud_url,
)

logger = logging.getLogger(__name__)

WELCOME_TEXT = (
    "Привет! Я работаю с SoundCloud двумя способами:\n\n"
    "1) Кинь ссылку на трек — пришлю mp3 с обложкой.\n"
    "2) Открой Mini App ниже — встроенный плеер с обложкой, паузой и перемоткой "
    "(играет напрямую с SoundCloud, ничего не скачивается).\n\n"
    "Команды:\n"
    "/start — это сообщение\n"
    "/player — открыть плеер\n"
    "/help — помощь"
)

HELP_TEXT = (
    "Поддерживаются ссылки вида:\n"
    "• https://soundcloud.com/<artist>/<track>\n"
    "• https://m.soundcloud.com/...\n"
    "• https://on.soundcloud.com/<short>\n\n"
    "Скачивание: лимит Telegram на аудио от ботов — 50 МБ.\n"
    "Mini App плеер: открывается прямо в Telegram, без скачивания."
)


def _player_button(webapp_url: str, track_url: str | None, label: str) -> InlineKeyboardButton:
    if track_url:
        url = f"{webapp_url}/?track={quote(track_url, safe='')}"
    else:
        url = f"{webapp_url}/"
    return InlineKeyboardButton(text=label, web_app=WebAppInfo(url=url))


def build_router(settings: Settings) -> Router:
    router = Router(name="main")
    webapp_url = settings.webapp_url

    def make_keyboard(track_url: str) -> InlineKeyboardMarkup:
        rows: list[list[InlineKeyboardButton]] = []
        if webapp_url:
            rows.append([_player_button(webapp_url, track_url, "🎧 Открыть в плеере")])
        rows.append(
            [InlineKeyboardButton(text="Открыть на SoundCloud", url=track_url)]
        )
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def start_keyboard() -> InlineKeyboardMarkup | None:
        if not webapp_url:
            return None
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [_player_button(webapp_url, None, "🎧 Открыть плеер")]
            ]
        )

    @router.message(CommandStart())
    async def on_start(message: Message) -> None:
        await message.answer(
            WELCOME_TEXT,
            disable_web_page_preview=True,
            reply_markup=start_keyboard(),
        )

    @router.message(Command("help"))
    async def on_help(message: Message) -> None:
        await message.answer(HELP_TEXT, disable_web_page_preview=True)

    @router.message(Command("player"))
    async def on_player(message: Message) -> None:
        if not webapp_url:
            await message.answer(
                "Mini App плеер сейчас недоступен — туннель ещё не поднялся "
                "или WEBAPP_URL не настроен."
            )
            return
        await message.answer(
            "Открыть встроенный плеер:",
            reply_markup=start_keyboard(),
        )

    @router.message(F.text)
    async def on_text(message: Message) -> None:
        url = find_soundcloud_url(message.text or "")
        if not url:
            await message.reply(
                "Это не похоже на ссылку SoundCloud. Пришли URL вида "
                "https://soundcloud.com/...",
                disable_web_page_preview=True,
            )
            return

        status = await message.reply("Качаю трек… это займёт несколько секунд.")
        await message.bot.send_chat_action(message.chat.id, ChatAction.RECORD_VOICE)

        try:
            track = await download_track(
                url=url,
                download_root=settings.download_dir,
                max_bytes=settings.max_upload_bytes,
            )
        except TrackTooLargeError as exc:
            logger.info("Track too large for %s: %s", url, exc)
            text = (
                f"Трек весит {exc.size_bytes / 1024 / 1024:.1f} МБ — это больше "
                f"лимита Telegram (50 МБ). Файл не отправлю."
            )
            if webapp_url:
                text += "\n\nНо его можно послушать прямо в плеере 👇"
            await status.edit_text(text, reply_markup=make_keyboard(url))
            return
        except SoundCloudError as exc:
            logger.warning("Failed to download %s: %s", url, exc)
            await status.edit_text(
                "Не получилось скачать трек. Проверь, что ссылка ведёт на публичный "
                "трек SoundCloud, и попробуй ещё раз."
            )
            return
        except Exception:
            logger.exception("Unexpected error while handling %s", url)
            await status.edit_text("Что-то пошло не так на моей стороне. Попробуй позже.")
            return

        try:
            await message.bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_VOICE)
            caption = f"{hbold(track.title)}\n{track.artist}"
            await message.answer_audio(
                audio=FSInputFile(track.file_path, filename=f"{track.title}.mp3"),
                caption=caption,
                title=track.title,
                performer=track.artist,
                duration=track.duration or None,
                reply_markup=make_keyboard(track.webpage_url),
            )
            await status.delete()
        except Exception:
            logger.exception("Failed to send audio for %s", url)
            await status.edit_text("Скачал, но не получилось отправить файл. Попробуй ещё раз.")
        finally:
            track.cleanup()

    return router
