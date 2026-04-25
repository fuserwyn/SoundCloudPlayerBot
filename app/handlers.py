from __future__ import annotations

import logging
import uuid
from collections import OrderedDict
from urllib.parse import quote

from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
    LinkPreviewOptions,
    Message,
    WebAppInfo,
)
from aiogram.utils.markdown import hbold

from app.config import Settings
from app.llm import LLMClient, LLMUnavailable
from app.soundcloud import (
    SearchResult,
    SoundCloudError,
    Track,
    TrackTooLargeError,
    download_track,
    find_soundcloud_url,
    search_tracks,
)

logger = logging.getLogger(__name__)

WELCOME_TEXT = (
    "Привет! Я работаю с SoundCloud:\n\n"
    "1) Кинь ссылку на трек — пришлю mp3 с обложкой.\n"
    "2) Напиши название — найду первые 10 совпадений. Если не нашлось, AI попробует "
    "угадать артиста (опечатки, фонетика — например «пинк флойд камфортабли намб») "
    "и поищет ещё раз.\n"
    "3) Открой Mini App ниже — встроенный плеер с поиском и виджетом.\n\n"
    "Команды:\n"
    "/start — это сообщение\n"
    "/player — открыть плеер\n"
    "/help — помощь"
)

HELP_TEXT = (
    "Поддерживаются ссылки вида:\n"
    "• https://soundcloud.com/&lt;artist&gt;/&lt;track&gt;\n"
    "• https://m.soundcloud.com/...\n"
    "• https://on.soundcloud.com/&lt;short&gt;\n\n"
    "Поиск: просто пришли название трека (например, «forss flickermood» или "
    "«психоцикл амба») — выберу из топ-10.\n"
    "Если ничего не нашлось и на сервере включён GROQ_API_KEY, AI попробует узнать "
    "артиста (даже если ты написал «пинк флойд камфортабли намб» — поищет «pink floyd "
    "comfortably numb») и поищет ещё раз.\n\n"
    "Скачивание: лимит Telegram на аудио от ботов — 50 МБ.\n"
    "Mini App плеер: открывается прямо в Telegram, без скачивания."
)

CALLBACK_PICK_PREFIX = "pick:"
MAX_BUTTON_TEXT = 60
SEARCH_LIMIT = 10
SEARCH_CACHE_SIZE = 2000


class _UrlCache:
    """Tiny LRU cache mapping short id -> SoundCloud URL.

    callback_data is limited to 64 bytes, but track URLs can be longer than that,
    so we hand out short opaque ids and resolve them server-side.
    """

    def __init__(self, max_items: int = SEARCH_CACHE_SIZE) -> None:
        self._items: OrderedDict[str, str] = OrderedDict()
        self._max = max_items

    def put(self, url: str) -> str:
        key = uuid.uuid4().hex[:12]
        self._items[key] = url
        self._items.move_to_end(key)
        while len(self._items) > self._max:
            self._items.popitem(last=False)
        return key

    def get(self, key: str) -> str | None:
        url = self._items.get(key)
        if url is not None:
            self._items.move_to_end(key)
        return url


def _player_button(webapp_url: str, track_url: str | None, label: str) -> InlineKeyboardButton:
    if track_url:
        url = f"{webapp_url}/?track={quote(track_url, safe='')}"
    else:
        url = f"{webapp_url}/"
    return InlineKeyboardButton(text=label, web_app=WebAppInfo(url=url))


def _format_duration(seconds: int) -> str:
    if seconds <= 0:
        return ""
    minutes, sec = divmod(seconds, 60)
    return f"{minutes}:{sec:02d}"


def _truncate(text: str, limit: int = MAX_BUTTON_TEXT) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _format_button_label(idx: int, item: SearchResult) -> str:
    parts: list[str] = [f"{idx}."]
    if item.artist:
        parts.append(f"{item.artist} —")
    parts.append(item.title or "Без названия")
    label = " ".join(parts)
    duration = _format_duration(item.duration)
    if duration:
        # keep duration in case label was truncated
        label = _truncate(label, MAX_BUTTON_TEXT - len(duration) - 3) + f"  ({duration})"
    else:
        label = _truncate(label, MAX_BUTTON_TEXT)
    return label


def build_router(settings: Settings) -> Router:
    router = Router(name="main")
    webapp_url = settings.webapp_url
    url_cache = _UrlCache()
    llm: LLMClient | None = None
    if settings.groq_api_key:
        llm = LLMClient(api_key=settings.groq_api_key, model=settings.groq_model)

    def make_track_keyboard(track_url: str) -> InlineKeyboardMarkup:
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

    def make_search_keyboard(results: list[SearchResult]) -> InlineKeyboardMarkup:
        rows: list[list[InlineKeyboardButton]] = []
        for idx, item in enumerate(results, start=1):
            key = url_cache.put(item.url)
            rows.append(
                [
                    InlineKeyboardButton(
                        text=_format_button_label(idx, item),
                        callback_data=f"{CALLBACK_PICK_PREFIX}{key}",
                    )
                ]
            )
        return InlineKeyboardMarkup(inline_keyboard=rows)

    async def deliver_track(
        chat_message: Message,
        status: Message,
        url: str,
    ) -> None:
        """Download `url`, send it as audio to the chat, edit/delete `status`."""
        try:
            track: Track = await download_track(
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
            await status.edit_text(text, reply_markup=make_track_keyboard(url))
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
            await chat_message.bot.send_chat_action(
                chat_message.chat.id, ChatAction.UPLOAD_VOICE
            )
            caption = f"{hbold(track.title)}\n{track.artist}"
            await chat_message.answer_audio(
                audio=FSInputFile(track.file_path, filename=f"{track.title}.mp3"),
                caption=caption,
                title=track.title,
                performer=track.artist,
                duration=track.duration or None,
                reply_markup=make_track_keyboard(track.webpage_url),
            )
            try:
                await status.delete()
            except Exception:
                pass
        except Exception:
            logger.exception("Failed to send audio for %s", url)
            await status.edit_text("Скачал, но не получилось отправить файл. Попробуй ещё раз.")
        finally:
            track.cleanup()

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
                "Mini App плеер сейчас недоступен — WEBAPP_URL не настроен."
            )
            return
        await message.answer(
            "Открыть встроенный плеер:",
            reply_markup=start_keyboard(),
        )

    @router.message(Command("search"))
    async def on_search_cmd(message: Message) -> None:
        query = (message.text or "").partition(" ")[2].strip()
        if not query:
            await message.reply(
                "Использование: /search <название трека>\n"
                "Или просто пришли название без команды."
            )
            return
        await _do_search(message, query)

    @router.message(F.text)
    async def on_text(message: Message) -> None:
        text = message.text or ""
        url = find_soundcloud_url(text)
        if url:
            status = await message.reply("Качаю трек… это займёт несколько секунд.")
            await message.bot.send_chat_action(message.chat.id, ChatAction.RECORD_VOICE)
            await deliver_track(message, status, url)
            return

        await _do_search(message, text)

    async def _do_search(message: Message, query: str) -> None:
        query = query.strip()
        if len(query) < 2:
            await message.reply(
                "Слишком короткий запрос. Дай хотя бы 2 символа или пришли ссылку на трек."
            )
            return

        status = await message.reply(f"Ищу «{_truncate(query, 80)}»…")

        try:
            results = await search_tracks(query, limit=SEARCH_LIMIT)
        except SoundCloudError as exc:
            logger.warning("Search failed for %r: %s", query, exc)
            await status.edit_text("Не получилось выполнить поиск. Попробуй ещё раз.")
            return
        except Exception:
            logger.exception("Unexpected search error for %r", query)
            await status.edit_text("Что-то сломалось при поиске. Попробуй позже.")
            return

        if results:
            await status.edit_text(
                f"Нашёл {len(results)} треков. Выбери, что скачать:",
                reply_markup=make_search_keyboard(results),
            )
            return

        if llm:
            normalized = await _try_normalize(query)
            if normalized and normalized.lower() != query.lower():
                try:
                    await status.edit_text(
                        f"Не нашёл «{_truncate(query, 40)}». Пробую «{_truncate(normalized, 60)}»…"
                    )
                except Exception:
                    pass
                try:
                    results = await search_tracks(normalized, limit=SEARCH_LIMIT)
                except SoundCloudError as exc:
                    logger.warning("Search failed for %r: %s", normalized, exc)
                    results = []
                except Exception:
                    logger.exception("Unexpected search error for %r", normalized)
                    results = []
                if results:
                    await status.edit_text(
                        f"По «{_truncate(query, 40)}» ничего не нашёл, "
                        f"но по «{_truncate(normalized, 60)}» нашёл {len(results)}:",
                        reply_markup=make_search_keyboard(results),
                    )
                    return

        await status.edit_text(
            "Ничего не нашёл. Попробуй переформулировать или пришли прямую ссылку."
        )

    async def _try_normalize(query: str) -> str | None:
        if not llm:
            return None
        try:
            return await llm.normalize_query(query)
        except LLMUnavailable as exc:
            logger.warning("LLM normalize failed for %r: %s", query, exc)
            return None

    @router.inline_query()
    async def on_inline(iq: InlineQuery) -> None:
        query = (iq.query or "").strip()
        if len(query) < 2:
            await iq.answer(
                results=[],
                cache_time=5,
                is_personal=False,
                button=None,
            )
            return

        try:
            results = await search_tracks(query, limit=20)
        except Exception:
            logger.exception("Inline search failed for %r", query)
            await iq.answer([], cache_time=5)
            return

        articles: list[InlineQueryResultArticle] = []
        for item in results:
            description_parts: list[str] = []
            if item.artist:
                description_parts.append(item.artist)
            duration = _format_duration(item.duration)
            if duration:
                description_parts.append(duration)
            description = " · ".join(description_parts) or "SoundCloud"

            kb_rows: list[list[InlineKeyboardButton]] = []
            if webapp_url:
                kb_rows.append(
                    [
                        InlineKeyboardButton(
                            text="🎧 Открыть в плеере",
                            url=f"{webapp_url}/?track={quote(item.url, safe='')}",
                        )
                    ]
                )
            kb_rows.append(
                [InlineKeyboardButton(text="Открыть на SoundCloud", url=item.url)]
            )
            keyboard = InlineKeyboardMarkup(inline_keyboard=kb_rows)

            articles.append(
                InlineQueryResultArticle(
                    id=uuid.uuid4().hex,
                    title=_truncate(item.title or "Без названия", 64),
                    description=_truncate(description, 80),
                    thumbnail_url=item.thumbnail or None,
                    input_message_content=InputTextMessageContent(
                        message_text=item.url,
                        link_preview_options=LinkPreviewOptions(
                            url=item.url, prefer_small_media=False
                        ),
                    ),
                    reply_markup=keyboard,
                )
            )

        await iq.answer(
            results=articles,
            cache_time=30,
            is_personal=False,
        )

    @router.callback_query(F.data.startswith(CALLBACK_PICK_PREFIX))
    async def on_pick(cq: CallbackQuery) -> None:
        if not cq.data or not cq.message:
            await cq.answer()
            return
        key = cq.data[len(CALLBACK_PICK_PREFIX):]
        url = url_cache.get(key)
        if not url:
            await cq.answer("Список устарел, поищи заново.", show_alert=True)
            return

        await cq.answer("Качаю…")
        try:
            await cq.message.edit_text("Качаю выбранный трек…")
        except Exception:
            pass
        await cq.message.bot.send_chat_action(
            cq.message.chat.id, ChatAction.RECORD_VOICE
        )
        # cq.message is the search-results message; reuse it as status placeholder
        await deliver_track(cq.message, cq.message, url)

    return router
