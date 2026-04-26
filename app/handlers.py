from __future__ import annotations

import logging
import uuid
from collections import OrderedDict
from urllib.parse import quote

from aiogram import F, Router
from aiogram.enums import ChatAction, ChatType
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
from app.db import AcceptanceStore
from app.llm import LLMClient, LLMUnavailable
from app.soundcloud import (
    SearchResult,
    SoundCloudError,
    Track,
    TrackTooLargeError,
    download_track,
    find_soundcloud_url,
    search_tracks,
    tag_id3,
)

logger = logging.getLogger(__name__)

WELCOME_TEXT = (
    "Привет! Я работаю с SoundCloud:\n\n"
    "1) Кинь ссылку на трек SoundCloud — пришлю mp3 с обложкой.\n"
    "2) Напиши название — найду первые 10 совпадений; после выбора можно открыть в "
    "плеере, на SoundCloud или скачать MP3. Если не нашлось, AI попробует угадать "
    "артиста (опечатки, фонетика — например «пинк флойд камфортабли намб») и поищет "
    "ещё раз.\n"
    "3) Открой Mini App ниже — встроенный плеер с поиском и виджетом.\n"
    "4) В любом чате через @бот можно быстро найти трек и отправить ссылку — "
    "там только прослушивание в плеере или на SoundCloud; mp3 — только в этом чате "
    "после /terms.\n\n"
    "Команды:\n"
    "/start — это сообщение\n"
    "/player — открыть плеер\n"
    "/terms — условия использования\n"
    "/help — помощь"
)

HELP_TEXT = (
    "Поддерживаются ссылки вида:\n"
    "• https://soundcloud.com/&lt;artist&gt;/&lt;track&gt;\n"
    "• https://m.soundcloud.com/...\n"
    "• https://on.soundcloud.com/&lt;short&gt;\n\n"
    "Поиск: пришли название (например, «forss flickermood») — выберу из топ-10, "
    "потом плеер, SoundCloud или скачать.\n"
    "Если ничего не нашлось и на сервере включён GROQ_API_KEY, AI попробует узнать "
    "артиста (даже если ты написал «пинк флойд камфортабли намб» — поищет «pink floyd "
    "comfortably numb») и поищет ещё раз.\n\n"
    "Скачивание: лимит Telegram на аудио от ботов — 50 МБ.\n"
    "Перед первым скачиванием бот один раз попросит принять условия "
    "использования (/terms).\n"
    "Mini App плеер: открывается прямо в Telegram, без скачивания. Звук идёт, пока "
    "открыт Mini App; при полном закрытии окна Telegram обычно останавливает "
    "воспроизведение (это ограничение платформы, не «фон» как в Spotify).\n"
    "Inline (@бот в любом чате): только ссылка и кнопки «в плеере» / на SoundCloud — "
    "без отправки mp3 оттуда."
)

CALLBACK_PICK_PREFIX = "pick:"
CALLBACK_DOWNLOAD_PREFIX = "dld:"  # скачать MP3 после выбора в списке поиска
CALLBACK_ACCEPT_PREFIX = "accept:"
CALLBACK_DECLINE = "decline"
MAX_BUTTON_TEXT = 60
SEARCH_LIMIT = 10
SEARCH_CACHE_SIZE = 2000

TERMS_VERSION = "1.3"

TERMS_TEXT = (
    "<b>Условия использования</b> (версия " + TERMS_VERSION + ")\n\n"
    "Этот бот — инструмент общего назначения, который по запросу пользователя "
    "обращается к публичному API SoundCloud и сохраняет аудиофайл локально для "
    "передачи через Telegram.\n\n"
    "<b>Используя бота, ты подтверждаешь, что:</b>\n"
    "1. Скачиваешь треки <b>исключительно для личного, некоммерческого "
    "прослушивания</b>.\n"
    "2. Не будешь распространять, перепродавать, публиковать в открытых "
    "каналах/платформах или иным образом доводить полученные файлы до "
    "неопределённого круга лиц.\n"
    "3. Понимаешь, что авторские права на треки принадлежат их правообладателям, "
    "а ответственность за правомерность скачивания конкретного трека в твоей "
    "юрисдикции лежит на тебе как на конечном пользователе.\n"
    "4. Соблюдаешь Terms of Service SoundCloud и применимое "
    "законодательство своей страны.\n\n"
    "Бот не хранит скачанные файлы после отправки и не передаёт их третьим лицам. "
    "Факт твоего согласия (Telegram user_id, username, дата) сохраняется как "
    "доказательство принятия этих условий.\n\n"
    "Если ты — правообладатель и хочешь, чтобы бот перестал отдавать твой "
    "контент, напиши владельцу бота."
)

TERMS_PROMPT_TEXT = (
    "Прежде чем что-то скачать, нужно один раз принять условия использования. "
    "Это короткий текст про то, что ты используешь бота для личного "
    "прослушивания и сам отвечаешь за легальность скачиваемого. "
    "Полный текст: /terms"
)


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


class _PickMetaCache:
    """Название/артист для строки в списке — чтобы после выбора показать подпись к кнопкам."""

    def __init__(self, max_items: int = SEARCH_CACHE_SIZE) -> None:
        self._items: OrderedDict[str, tuple[str, str]] = OrderedDict()
        self._max = max_items

    def set(self, key: str, title: str, artist: str) -> None:
        self._items[key] = (title, artist)
        self._items.move_to_end(key)
        while len(self._items) > self._max:
            self._items.popitem(last=False)

    def get(self, key: str) -> tuple[str, str] | None:
        t = self._items.get(key)
        if t is not None:
            self._items.move_to_end(key)
        return t


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


def build_router(settings: Settings, acceptance_store: AcceptanceStore) -> Router:
    router = Router(name="main")
    webapp_url = settings.webapp_url
    url_cache = _UrlCache()
    pick_meta = _PickMetaCache()
    pending_cache = _UrlCache()
    llm: LLMClient | None = None
    if settings.groq_api_key:
        llm = LLMClient(api_key=settings.groq_api_key, model=settings.groq_model)

    bot_info_cache: dict[str, str] = {}

    async def _get_bot_info(bot) -> tuple[str, str]:
        """Return (username_without_at, tag_with_at), cached after first call."""
        cached_username = bot_info_cache.get("username")
        if cached_username is not None:
            return cached_username, bot_info_cache.get("tag", "")
        try:
            me = await bot.get_me()
            username = me.username or ""
        except Exception:
            username = ""
        tag = f"@{username}" if username else ""
        bot_info_cache["username"] = username
        bot_info_cache["tag"] = tag
        return username, tag

    async def get_bot_tag(bot) -> str:
        _, tag = await _get_bot_info(bot)
        return tag

    async def get_bot_username(bot) -> str:
        username, _ = await _get_bot_info(bot)
        return username

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
            pick_meta.set(
                key,
                (item.title or "Без названия").strip(),
                (item.artist or "").strip(),
            )
            rows.append(
                [
                    InlineKeyboardButton(
                        text=_format_button_label(idx, item),
                        callback_data=f"{CALLBACK_PICK_PREFIX}{key}",
                    )
                ]
            )
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def make_post_pick_keyboard(cache_key: str) -> InlineKeyboardMarkup | None:
        """Плеер, SoundCloud, скачивание — после нажатия на строку в поиске."""
        track_url = url_cache.get(cache_key)
        if not track_url:
            return None
        rows: list[list[InlineKeyboardButton]] = []
        if webapp_url:
            rows.append([_player_button(webapp_url, track_url, "🎧 Открыть в плеере")])
        rows.append(
            [InlineKeyboardButton(text="Открыть на SoundCloud", url=track_url)]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text="Скачать мп3",
                    callback_data=f"{CALLBACK_DOWNLOAD_PREFIX}{cache_key}",
                )
            ]
        )
        return InlineKeyboardMarkup(inline_keyboard=rows)

    async def deliver_track(
        chat_message: Message,
        status: Message,
        url: str,
    ) -> None:
        """Скачать трек SoundCloud и отправить mp3."""
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
                f"лимита Telegram (50 МБ). Не отправлю."
            )
            if webapp_url:
                text += "\n\nНо его можно послушать прямо в плеере 👇"
            await status.edit_text(text, reply_markup=make_track_keyboard(url))
            return
        except SoundCloudError:
            logger.warning("Failed to download %s", url)
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
            bot_tag = await get_bot_tag(chat_message.bot)
            caption = f"{hbold(track.title)}\n{track.artist}"
            if track.is_preview:
                caption += (
                    f"\n\n⚠️ Это превью {track.actual_duration} сек "
                    f"(полный трек {track.duration // 60}:{track.duration % 60:02d}). "
                    f"Лейбл закрыл полную версию через SoundCloud Go+. "
                    f"Поищи неофициальную загрузку — там обычно полный трек."
                )
            if bot_tag:
                caption += f"\n\nvia {bot_tag}"

            await chat_message.bot.send_chat_action(
                chat_message.chat.id, ChatAction.UPLOAD_VOICE
            )
            tag_id3(track.file_path, bot_tag)
            await chat_message.answer_audio(
                audio=FSInputFile(track.file_path, filename=f"{track.title}.mp3"),
                caption=caption,
                title=track.title,
                performer=track.artist,
                duration=track.actual_duration or track.duration or None,
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

    def _acceptance_keyboard(key: str) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Принимаю",
                        callback_data=f"{CALLBACK_ACCEPT_PREFIX}{key}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="📄 Прочитать полный текст",
                        callback_data=f"{CALLBACK_ACCEPT_PREFIX}show",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="❌ Не сейчас",
                        callback_data=CALLBACK_DECLINE,
                    )
                ],
            ]
        )

    async def _send_acceptance_prompt(target_message: Message, url: str) -> None:
        key = pending_cache.put(url)
        await target_message.answer(
            TERMS_PROMPT_TEXT,
            reply_markup=_acceptance_keyboard(key),
            disable_web_page_preview=True,
        )

    async def _ensure_accepted_or_prompt(message: Message, url: str) -> bool:
        if not message.from_user:
            return True
        if await acceptance_store.has_accepted(message.from_user.id, TERMS_VERSION):
            return True
        await _send_acceptance_prompt(message, url)
        return False

    @router.message(CommandStart())
    async def on_start(message: Message) -> None:
        payload = (message.text or "").partition(" ")[2].strip()
        if payload.startswith("dl_"):
            key = payload[3:]
            url = url_cache.get(key)
            if not url:
                await message.answer(
                    "Эта ссылка устарела — поищи трек заново через @"
                    f"{await get_bot_username(message.bot)} или просто пришли название."
                )
                return
            if not await _ensure_accepted_or_prompt(message, url):
                return
            status = await message.answer("Качаю выбранный трек…")
            await message.bot.send_chat_action(message.chat.id, ChatAction.RECORD_VOICE)
            await deliver_track(message, status, url)
            return

        await message.answer(
            WELCOME_TEXT,
            disable_web_page_preview=True,
            reply_markup=start_keyboard(),
        )

    @router.message(Command("help"))
    async def on_help(message: Message) -> None:
        await message.answer(HELP_TEXT, disable_web_page_preview=True)

    @router.message(Command("terms"))
    async def on_terms(message: Message) -> None:
        suffix = ""
        if message.from_user:
            accepted = await acceptance_store.has_accepted(
                message.from_user.id, TERMS_VERSION
            )
            suffix = (
                f"\n\n✅ Ты уже принял эту версию условий ({TERMS_VERSION})."
                if accepted
                else "\n\nЯ покажу кнопку «Принимаю» при первом скачивании."
            )
        await message.answer(TERMS_TEXT + suffix, disable_web_page_preview=True)

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
            if not await _ensure_accepted_or_prompt(message, url):
                return
            status = await message.reply("Качаю трек… это займёт несколько секунд.")
            await message.bot.send_chat_action(message.chat.id, ChatAction.RECORD_VOICE)
            await deliver_track(message, status, url)
            return

        # В группах/каналах не рассматривать произвольный текст как поиск — иначе бот
        # реагирует на каждое сообщение в чате. Поиск там: /search, либо через @ в inline.
        if message.chat.type != ChatType.PRIVATE:
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
                f"Нашёл {len(results)} треков. Нажми на вариант — дальше можно "
                f"открыть в плеере, на SoundCloud или скачать MP3.",
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
                        f"но по «{_truncate(normalized, 60)}» нашёл {len(results)}. "
                        f"Нажми на вариант — плеер, SoundCloud или скачать MP3.",
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
            await iq.answer(results=[], cache_time=5, is_personal=False)
            return

        try:
            results = await search_tracks(query, limit=20)
        except Exception:
            logger.exception("Inline search failed for %r", query)
            await iq.answer([], cache_time=5)
            return

        if not results and llm:
            normalized = await _try_normalize(query)
            if normalized and normalized.lower() != query.lower():
                try:
                    results = await search_tracks(normalized, limit=20)
                except Exception:
                    logger.exception("Inline search (normalized) failed for %r", normalized)
                    results = []

        articles: list[InlineQueryResultArticle] = []
        bot_username = await get_bot_username(iq.bot)
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
            if bot_username:
                dl_key = url_cache.put(item.url)
                kb_rows.append(
                    [
                        InlineKeyboardButton(
                            text="Скачать мп3",
                            url=f"https://t.me/{bot_username}?start=dl_{dl_key}",
                        )
                    ]
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
        pick_kb = make_post_pick_keyboard(key)
        if not pick_kb:
            await cq.answer("Список устарел, поищи заново.", show_alert=True)
            return

        meta = pick_meta.get(key)
        title, artist = meta if meta else (None, None)
        if title:
            lines: list[str] = [title]
            if artist:
                lines.append(artist)
        else:
            lines = ["Трек"]
        text = (
            "\n".join(lines)
            + "\n\nОткрой плеер, SoundCloud или скачай MP3 — кнопки ниже."
        )
        await cq.answer()
        try:
            await cq.message.edit_text(text, reply_markup=pick_kb)
        except Exception:
            try:
                await cq.message.answer(text, reply_markup=pick_kb)
            except Exception:
                pass

    @router.callback_query(F.data.startswith(CALLBACK_DOWNLOAD_PREFIX))
    async def on_post_pick_download(cq: CallbackQuery) -> None:
        if not cq.data or not cq.from_user or not cq.message:
            await cq.answer()
            return
        key = cq.data[len(CALLBACK_DOWNLOAD_PREFIX):]
        url = url_cache.get(key)
        if not url:
            await cq.answer("Ссылка устарела, поищи заново.", show_alert=True)
            return
        if not await acceptance_store.has_accepted(
            cq.from_user.id, TERMS_VERSION
        ):
            await cq.answer()
            await _send_acceptance_prompt(cq.message, url)
            return
        await cq.answer("Качаю…")
        try:
            await cq.message.edit_text("Качаю трек…")
        except Exception:
            pass
        await cq.message.bot.send_chat_action(
            cq.message.chat.id, ChatAction.RECORD_VOICE
        )
        await deliver_track(cq.message, cq.message, url)

    @router.callback_query(F.data.startswith(CALLBACK_ACCEPT_PREFIX))
    async def on_accept(cq: CallbackQuery) -> None:
        if not cq.data or not cq.from_user or not cq.message:
            await cq.answer()
            return

        payload = cq.data[len(CALLBACK_ACCEPT_PREFIX):]

        if payload == "show":
            await cq.answer()
            await cq.message.answer(TERMS_TEXT, disable_web_page_preview=True)
            return

        url = pending_cache.get(payload)
        await acceptance_store.record(
            user_id=cq.from_user.id,
            username=cq.from_user.username,
            terms_version=TERMS_VERSION,
        )
        await cq.answer("Спасибо! Согласие сохранено.")

        if not url:
            try:
                await cq.message.edit_text(
                    "Согласие принято. Заявка на скачивание устарела — пришли "
                    "ссылку или название трека ещё раз."
                )
            except Exception:
                pass
            return

        try:
            await cq.message.edit_text("Согласие принято. Качаю выбранный трек…")
        except Exception:
            pass
        await cq.message.bot.send_chat_action(
            cq.message.chat.id, ChatAction.RECORD_VOICE
        )
        await deliver_track(cq.message, cq.message, url)

    @router.callback_query(F.data == CALLBACK_DECLINE)
    async def on_decline(cq: CallbackQuery) -> None:
        await cq.answer()
        if not cq.message:
            return
        try:
            await cq.message.edit_text(
                "Окей, без проблем. Если передумаешь — пришли ссылку или название "
                "трека снова, я ещё раз покажу условия. Полный текст всегда "
                "доступен по /terms."
            )
        except Exception:
            pass

    return router
