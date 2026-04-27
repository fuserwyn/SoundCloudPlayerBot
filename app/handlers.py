from __future__ import annotations

import html
import logging
import uuid
from collections import OrderedDict
from urllib.parse import quote

from aiogram import F, Router
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.enums import ChatAction, ChatType, ParseMode
from aiogram.filters import Command, CommandObject, CommandStart
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
from app.db import AcceptanceStore, PlaylistSummary
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
    "после /terms.\n"
    "5) Свои плейлисты: после выбора трека в поиске — «➕ В плейлист»; смотри /pl.\n\n"
    "Команды:\n"
    "/start — это сообщение\n"
    "/player — открыть плеер\n"
    "/pl — плейлисты\n"
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
CALLBACK_PL_MENU = "plm:"  # открыть выбор плейлиста для ключа кэша
CALLBACK_PL_ADD = "padd:"  # padd:playlist_id:cache_key
CALLBACK_PL_VIEW = "pvv:"  # pvv:playlist_id
CALLBACK_PL_DEL = "pdl:"  # pdl:playlist_id
CALLBACK_PL_RMT = "rmt:"  # rmt:playlist_id:track_row_id
MAX_BUTTON_TEXT = 60
PLAYLIST_BUTTON_LABEL = 30
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
    "Факт твоего согласия (Telegram user_id, username, дата и время по Москве) "
    "сохраняется как доказательство принятия этих условий.\n\n"
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


class UserActivityMiddleware(BaseMiddleware):
    """Считает заходы: upsert в БД и кладёт актуальный request_count в data."""

    def __init__(self, store: AcceptanceStore) -> None:
        self._store = store

    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if user is not None and not user.is_bot:
            data["user_request_count"] = await self._store.record_user_request(
                user.id, user.username
            )
        else:
            data["user_request_count"] = None
        return await handler(event, data)


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
    _act = UserActivityMiddleware(acceptance_store)
    router.message.middleware(_act)
    router.callback_query.middleware(_act)
    router.inline_query.middleware(_act)
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
        rows.append(
            [
                InlineKeyboardButton(
                    text="➕ В плейлист",
                    callback_data=f"{CALLBACK_PL_MENU}{cache_key}",
                )
            ]
        )
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def _pl_summaries_keyboard(rows: list[PlaylistSummary]) -> InlineKeyboardMarkup:
        kb: list[list[InlineKeyboardButton]] = []
        for s in rows:
            label = f"{_truncate(s.name, PLAYLIST_BUTTON_LABEL)} · {s.track_count}"
            kb.append(
                [
                    InlineKeyboardButton(
                        text=label,
                        callback_data=f"{CALLBACK_PL_VIEW}{s.id}",
                    )
                ]
            )
        return InlineKeyboardMarkup(inline_keyboard=kb)

    def _format_playlist_message(pl_name: str, entries) -> str:
        head = f"🎧 {html.escape(pl_name)}"
        if not entries:
            return (
                head
                + "\n\nПока пусто. Найди трек в поиске (название или ссылка) — после "
                "выбора в списке нажми «➕ В плейлист»."
            )
        lines: list[str] = []
        for i, e in enumerate(entries, start=1):
            t = f"{e.title} — {e.artist}" if (e.artist or "").strip() else e.title
            lines.append(f"{i}. {html.escape(t)}")
        return head + "\n\n" + "\n".join(lines)

    def _playlist_tracks_keyboard(playlist_id: int, entries) -> InlineKeyboardMarkup:
        rrows: list[list[InlineKeyboardButton]] = []
        for i, e in enumerate(entries, start=1):
            one: list[InlineKeyboardButton] = []
            if webapp_url:
                one.append(
                    _player_button(webapp_url, e.track_url, f"▶ {i}"),
                )
            else:
                one.append(InlineKeyboardButton(text=f"🌐 {i}", url=e.track_url))
            one.append(
                InlineKeyboardButton(
                    text="🗑",
                    callback_data=f"{CALLBACK_PL_RMT}{playlist_id}:{e.id}",
                )
            )
            rrows.append(one)
        rrows.append(
            [
                InlineKeyboardButton(
                    text="🗑 Удалить плейлист",
                    callback_data=f"{CALLBACK_PL_DEL}{playlist_id}",
                )
            ]
        )
        return InlineKeyboardMarkup(inline_keyboard=rrows)

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

    async def _open_playlist_view_message(
        message: Message, user_id: int, pl_id: int
    ) -> bool:
        pl_name = await acceptance_store.playlist_name(user_id, pl_id)
        if pl_name is None:
            await message.reply("Плейлист не найден. Смотри /pl")
            return False
        tr = await acceptance_store.playlist_get_tracks(user_id, pl_id)
        if tr is None:
            await message.reply("Плейлист не найден. Смотри /pl")
            return False
        text = _format_playlist_message(pl_name, tr)
        await message.reply(
            text,
            reply_markup=_playlist_tracks_keyboard(pl_id, tr),
            parse_mode=ParseMode.HTML,
        )
        return True

    async def _open_playlist_view_edit(cq: CallbackQuery, user_id: int, pl_id: int) -> None:
        if not cq.message:
            return
        pl_name = await acceptance_store.playlist_name(user_id, pl_id)
        if pl_name is None:
            try:
                await cq.message.edit_text("Плейлист не найден.")
            except Exception:
                pass
            return
        tr = await acceptance_store.playlist_get_tracks(user_id, pl_id)
        if tr is None:
            try:
                await cq.message.edit_text("Плейлист не найден.")
            except Exception:
                pass
            return
        text = _format_playlist_message(pl_name, tr)
        kb = _playlist_tracks_keyboard(pl_id, tr)
        try:
            await cq.message.edit_text(
                text, reply_markup=kb, parse_mode=ParseMode.HTML
            )
        except Exception:
            try:
                await cq.message.answer(
                    text, reply_markup=kb, parse_mode=ParseMode.HTML
                )
            except Exception:
                pass

    @router.message(CommandStart())
    async def on_start(
        message: Message,
        user_request_count: int | None = None,
    ) -> None:
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

        extra = (
            f"\n\n📊 Ваших обращений к боту: {user_request_count}"
            if user_request_count is not None
            else ""
        )
        await message.answer(
            WELCOME_TEXT + extra,
            disable_web_page_preview=True,
            reply_markup=start_keyboard(),
        )

    @router.message(Command("help"))
    async def on_help(
        message: Message,
        user_request_count: int | None = None,
    ) -> None:
        extra = (
            f"\n\n📊 Ваших обращений к боту: {user_request_count}"
            if user_request_count is not None
            else ""
        )
        await message.answer(HELP_TEXT + extra, disable_web_page_preview=True)

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

    @router.message(
        Command("pl", "playlists"),
        F.chat.type == ChatType.PRIVATE,
    )
    async def on_playlists(
        message: Message,
        command: CommandObject,
    ) -> None:
        if not message.from_user:
            return
        uid = message.from_user.id
        args = (command.args or "").strip()
        al = args.lower()
        if al.startswith("new "):
            name = args[4:].strip()
            if not name:
                await message.reply("Использование: /pl new Название плейлиста")
                return
            pid, err = await acceptance_store.playlist_create(uid, name)
            if err:
                await message.reply(err)
                return
            assert pid is not None
            await message.reply(
                f"Готово — плейлист «{html.escape(name)}» (#{pid}).\n"
                f"Найди треки в поиске и жми «➕ В плейлист» после выбора.",
                parse_mode=ParseMode.HTML,
            )
            return
        if al == "new":
            await message.reply("Использование: /pl new Название плейлиста")
            return
        if args.isdigit():
            await _open_playlist_view_message(
                message, uid, int(args)
            )
            return
        if args:
            await message.reply(
                "Команда не распознана. Показать плейлисты: /pl\n"
                "Создать: /pl new Мой плейлист\n"
                "Открыть: /pl 3  (по id из списка)"
            )
            return
        rows = await acceptance_store.playlists_list(uid)
        if not rows:
            await message.reply(
                "У тебя ещё нет плейлистов.\n\n"
                "Создай: /pl new Название\n"
                "После поиска трека — кнопка «➕ В плейлист»."
            )
            return
        intro = (
            "Твои плейлисты (нажми на строку, чтобы открыть). "
            "Или: /pl 5 — плейлист с id 5."
        )
        await message.reply(
            intro,
            reply_markup=_pl_summaries_keyboard(rows),
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
            + "\n\nПлеер, SoundCloud, скачать MP3 или добавить в плейлист — кнопки ниже."
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

    @router.callback_query(F.data.startswith(CALLBACK_PL_MENU))
    async def on_pl_menu(cq: CallbackQuery) -> None:
        if not cq.data or not cq.from_user or not cq.message:
            await cq.answer()
            return
        key = cq.data[len(CALLBACK_PL_MENU):]
        if not key or not url_cache.get(key):
            await cq.answer("Список устарел — поищи трек снова.", show_alert=True)
            return
        rows = await acceptance_store.playlists_list(cq.from_user.id)
        if not rows:
            await cq.answer("Создай плейлист: /pl new Название", show_alert=True)
            return
        meta = pick_meta.get(key)
        if meta:
            t0, a0 = meta[0], meta[1]
            head = (
                f"{html.escape(t0)}\n{html.escape(a0)}\n\nВыбери плейлист:"
                if a0
                else f"{html.escape(t0)}\n\nВыбери плейлист:"
            )
        else:
            head = "Выбери плейлист:"
        pl_rows: list[list[InlineKeyboardButton]] = [
            [
                InlineKeyboardButton(
                    text=f"{_truncate(s.name, PLAYLIST_BUTTON_LABEL)} · {s.track_count}",
                    callback_data=f"{CALLBACK_PL_ADD}{s.id}:{key}",
                )
            ]
            for s in rows
        ]
        try:
            await cq.message.edit_text(
                head,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=pl_rows),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            try:
                await cq.message.answer(
                    head,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=pl_rows),
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass
        await cq.answer()

    @router.callback_query(F.data.startswith(CALLBACK_PL_ADD))
    async def on_pl_add(cq: CallbackQuery) -> None:
        if not cq.data or not cq.from_user or not cq.message:
            await cq.answer()
            return
        rest = cq.data[len(CALLBACK_PL_ADD):]
        try:
            pl_s, key = rest.split(":", 1)
            pl_id = int(pl_s)
        except (ValueError, IndexError):
            await cq.answer("Ошибка кнопки", show_alert=True)
            return
        url = url_cache.get(key)
        if not url:
            await cq.answer("Ссылка устарела, поищи снова.", show_alert=True)
            return
        meta = pick_meta.get(key)
        title, ar = (
            (meta[0], meta[1]) if meta else ("Без названия", "")
        )
        err = await acceptance_store.playlist_add_track(
            cq.from_user.id, pl_id, url, title, ar
        )
        if err:
            await cq.answer(err, show_alert=True)
            return
        pname = await acceptance_store.playlist_name(cq.from_user.id, pl_id) or ""
        note = f"В «{pname[:50]}»" if pname else "Добавлено"
        await cq.answer(note, show_alert=True)
        tail = "Плеер, SoundCloud, скачать или добавить в плейлист — кнопки ниже."
        if meta and meta[0]:
            t0, a0 = meta[0], (meta[1] or "").strip()
            if a0:
                back = f"{html.escape(t0)}\n{html.escape(a0)}\n\n{tail}"
            else:
                back = f"{html.escape(t0)}\n\n{tail}"
        else:
            back = tail
        kb = make_post_pick_keyboard(key)
        if kb:
            try:
                await cq.message.edit_text(
                    back, reply_markup=kb, parse_mode=ParseMode.HTML
                )
            except Exception:
                pass

    @router.callback_query(F.data.startswith(CALLBACK_PL_VIEW))
    async def on_pl_view(cq: CallbackQuery) -> None:
        if not cq.data or not cq.from_user or not cq.message:
            await cq.answer()
            return
        raw = cq.data[len(CALLBACK_PL_VIEW):]
        if not raw.isdigit():
            await cq.answer()
            return
        pl_id = int(raw)
        await _open_playlist_view_edit(cq, cq.from_user.id, pl_id)
        await cq.answer()

    @router.callback_query(F.data.startswith(CALLBACK_PL_DEL))
    async def on_pl_del(cq: CallbackQuery) -> None:
        if not cq.data or not cq.from_user or not cq.message:
            await cq.answer()
            return
        raw = cq.data[len(CALLBACK_PL_DEL):]
        if not raw.isdigit():
            await cq.answer()
            return
        pl_id = int(raw)
        if await acceptance_store.playlist_delete(cq.from_user.id, pl_id):
            try:
                await cq.message.edit_text("Плейлист удалён.")
            except Exception:
                pass
            await cq.answer()
        else:
            await cq.answer("Не найден", show_alert=True)

    @router.callback_query(F.data.startswith(CALLBACK_PL_RMT))
    async def on_pl_remove_track(cq: CallbackQuery) -> None:
        if not cq.data or not cq.from_user or not cq.message:
            await cq.answer()
            return
        rest = cq.data[len(CALLBACK_PL_RMT):]
        try:
            pl_s, tr_s = rest.split(":", 1)
            pl_id, tr_id = int(pl_s), int(tr_s)
        except (ValueError, IndexError):
            await cq.answer()
            return
        uid = cq.from_user.id
        if not await acceptance_store.playlist_remove_track(uid, pl_id, tr_id):
            await cq.answer("Трек не найден", show_alert=True)
            return
        await cq.answer("Убрано из плейлиста")
        await _open_playlist_view_edit(cq, uid, pl_id)

    return router
