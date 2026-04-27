from __future__ import annotations

import asyncio
import html
import logging
import uuid
from collections import OrderedDict
from urllib.parse import quote

from aiogram import F, Router
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.enums import ChatAction, ChatType, ParseMode
from aiogram.exceptions import TelegramBadRequest
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
    "3) Открой Mini App — плеер и плейлисты; те же плейлисты доступны в чате: "
    "/pl — смотри, создавай, клади треки из поиска (кнопка «➕ В плейлист»).\n"
    "4) В любом чате через @бот можно быстро найти трек и отправить ссылку — "
    "там только прослушивание в плеере или на SoundCloud; mp3 — только в этом чате "
    "после /terms.\n\n"
    "Команды:\n"
    "/start — это сообщение\n"
    "/player — открыть плеер\n"
    "/pl — плейлисты (как в Mini App)\n"
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
    "без отправки mp3 оттуда.\n\n"
    "Плейлисты: /pl (в чате) — те же, что в Mini App. Из поиска — «➕ В плейлист»; в "
    "открытом плейлисте — «Скачать всё (mp3)» (после /terms, до 30 треков за раз)."
)

CALLBACK_PICK_PREFIX = "pick:"
CALLBACK_DOWNLOAD_PREFIX = "dld:"  # скачать MP3 после выбора в списке поиска
CALLBACK_ACCEPT_PREFIX = "accept:"
CALLBACK_DECLINE = "decline"
CALLBACK_PL_MENU = "plm:"
CALLBACK_PL_ADD = "padd:"
CALLBACK_PL_VIEW = "pvv:"
CALLBACK_PL_DEL = "pdl:"
CALLBACK_PL_RMT = "rmt:"
CALLBACK_PL_BULK = "pldl:"  # pldl:playlist_id — скачать весь (до лимита)
MAX_BUTTON_TEXT = 60
PLAYLIST_BUTTON_LABEL = 30
# За одно нажатие — столько mp3, чтобы не упереться в flood и не зависать часами
BULK_MP3_MAX = 30
BULK_MP3_DELAY_SEC = 1.0
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
    """Название/артист/превью обложки для строки в списке (в т.ч. в БД плейлиста)."""

    def __init__(self, max_items: int = SEARCH_CACHE_SIZE) -> None:
        self._items: OrderedDict[str, tuple[str, str, str | None]] = OrderedDict()
        self._max = max_items

    def set(
        self, key: str, title: str, artist: str, thumbnail: str | None = None
    ) -> None:
        self._items[key] = (title, artist, thumbnail)
        self._items.move_to_end(key)
        while len(self._items) > self._max:
            self._items.popitem(last=False)

    def get(self, key: str) -> tuple[str, str, str | None] | None:
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
    """Считает заходы в БД (статистика), без отображения в чате."""

    def __init__(self, store: AcceptanceStore) -> None:
        self._store = store

    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if user is not None and not user.is_bot:
            try:
                await self._store.record_user_request(user.id, user.username)
            except Exception:
                logger.exception(
                    "record_user_request failed (user_id=%s); handler still runs",
                    user.id,
                )
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
                item.thumbnail,
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

    def make_post_pick_keyboard(
        cache_key: str, *, show_playlist: bool = True
    ) -> InlineKeyboardMarkup | None:
        """Плеер, SoundCloud, скачивание — после нажатия на строке в поиске."""
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
        if show_playlist:
            rows.append(
                [
                    InlineKeyboardButton(
                        text="➕ В плейлист",
                        callback_data=f"{CALLBACK_PL_MENU}{cache_key}",
                    )
                ]
            )
        return InlineKeyboardMarkup(inline_keyboard=rows)

    async def _send_mp3_to_chat(
        target: Message,
        url: str,
    ) -> str | None:
        """Скачать трек и отправить mp3. None = ОК, иначе короткое сообщение об ошибке."""
        try:
            track: Track = await download_track(
                url=url,
                download_root=settings.download_dir,
                max_bytes=settings.max_upload_bytes,
            )
        except TrackTooLargeError as exc:
            text = (
                f"Трек весит {exc.size_bytes / 1024 / 1024:.1f} МБ — больше лимита "
                f"Telegram (50 МБ). Пропускаю."
            )
            if webapp_url:
                text += " В плеере Mini App послушать можно."
            return text
        except SoundCloudError:
            logger.warning("Failed to download %s", url)
            return "Не скачал с SoundCloud, пропускаю."
        except Exception:
            logger.exception("Unexpected error while handling %s", url)
            return "Ошибка на сервере, пропускаю."

        try:
            bot_tag = await get_bot_tag(target.bot)
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

            await target.bot.send_chat_action(
                target.chat.id, ChatAction.UPLOAD_VOICE
            )
            tag_id3(track.file_path, bot_tag)
            await target.answer_audio(
                audio=FSInputFile(track.file_path, filename=f"{track.title}.mp3"),
                caption=caption,
                title=track.title,
                performer=track.artist,
                duration=track.actual_duration or track.duration or None,
                reply_markup=make_track_keyboard(track.webpage_url),
            )
        except Exception:
            logger.exception("Failed to send audio for %s", url)
            return "Не получилось отправить файл в Telegram."
        finally:
            track.cleanup()
        return None

    async def deliver_track(
        chat_message: Message,
        status: Message,
        url: str,
    ) -> None:
        """Скачать трек SoundCloud и отправить mp3."""
        err = await _send_mp3_to_chat(chat_message, url)
        if err:
            km = (
                make_track_keyboard(url)
                if (webapp_url and "50 МБ" in err)
                else None
            )
            await status.edit_text(err, reply_markup=km)
            return
        try:
            await status.delete()
        except Exception:
            pass

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

    async def _send_pl_bulk_terms_prompt(target_message: Message, pl_id: int) -> None:
        pkey = pending_cache.put(f"plbulk:{pl_id}")
        await target_message.answer(
            TERMS_PROMPT_TEXT,
            reply_markup=_acceptance_keyboard(pkey),
            disable_web_page_preview=True,
        )

    def _format_playlist_message(pl_name: str, entries) -> str:
        head = f"🎧 {html.escape(pl_name)}"
        if not entries:
            return head + "\n\nПлейлист пуст. Добавь треки из поиска (➕ В плейлист) или в Mini App."
        lines: list[str] = [head, ""]
        for i, e in enumerate(entries, start=1):
            t = f"{e.title} — {e.artist}" if (e.artist or "").strip() else e.title
            lines.append(f"{i}. {html.escape(t)}")
        return "\n".join(lines)

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

    def _playlist_tracks_keyboard(playlist_id: int, entries) -> InlineKeyboardMarkup:
        rrows: list[list[InlineKeyboardButton]] = []
        for i, e in enumerate(entries, start=1):
            one: list[InlineKeyboardButton] = []
            if webapp_url:
                one.append(_player_button(webapp_url, e.track_url, f"▶ {i}"))
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
                    text=f"⬇ Скачать все mp3 (≤{BULK_MP3_MAX})",
                    callback_data=f"{CALLBACK_PL_BULK}{playlist_id}",
                )
            ]
        )
        rrows.append(
            [
                InlineKeyboardButton(
                    text="🗑 Удалить плейлист",
                    callback_data=f"{CALLBACK_PL_DEL}{playlist_id}",
                )
            ]
        )
        return InlineKeyboardMarkup(inline_keyboard=rrows)

    async def _open_playlist_view_message(
        message: Message, user_id: int, pl_id: int
    ) -> bool:
        pl_name = await acceptance_store.playlist_name(user_id, pl_id)
        if pl_name is None:
            await message.reply("Плейлист не найден. /pl")
            return False
        tr = await acceptance_store.playlist_get_tracks(user_id, pl_id)
        if tr is None:
            await message.reply("Плейлист не найден. /pl")
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

    async def _run_pl_bulk(target: Message, user_id: int, pl_id: int) -> None:
        name = await acceptance_store.playlist_name(user_id, pl_id)
        if name is None:
            await target.answer("Плейлист не найден.")
            return
        tracks = await acceptance_store.playlist_get_tracks(user_id, pl_id)
        if tracks is None:
            await target.answer("Плейлист не найден.")
            return
        if not tracks:
            await target.answer("В плейлисте нет треков.")
            return
        n = len(tracks)
        if n > BULK_MP3_MAX:
            await target.answer(
                f"В плейлисте {n} треков. За раз отправляю не больше {BULK_MP3_MAX} mp3 — "
                f"сократи плейлист в /pl / Mini App и нажми снова, либо качай остаток "
                f"другой порцией после удаления уже скачанных."
            )
            return
        st = await target.answer(
            f"🎧 «{html.escape(name)}»\n⏳ 0/{n}…",
            parse_mode=ParseMode.HTML,
        )
        ok = 0
        err = 0
        for i, t in enumerate(tracks, start=1):
            try:
                await st.edit_text(
                    f"🎧 «{html.escape(name)}»\n⏳ {i}/{n}…",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass
            emsg = await _send_mp3_to_chat(target, t.track_url)
            if emsg is None:
                ok += 1
            else:
                err += 1
            if i < n:
                await asyncio.sleep(BULK_MP3_DELAY_SEC)
        final = (
            f"🎧 «{html.escape(name)}»\n"
            f"Готово: {ok} файлов, с ошибками/пропусков: {err} (лимит 50 МБ, "
            f"SoundCloud, сеть)."
        )
        try:
            await st.edit_text(final, parse_mode=ParseMode.HTML)
        except Exception:
            await target.answer(final, parse_mode=ParseMode.HTML)

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

        try:
            await message.answer(
                WELCOME_TEXT,
                disable_web_page_preview=True,
                reply_markup=start_keyboard(),
            )
        except TelegramBadRequest as exc:
            logger.warning(
                "/start: reply with WebApp keyboard failed, sending text only: %s",
                exc,
            )
            await message.answer(
                WELCOME_TEXT,
                disable_web_page_preview=True,
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
        try:
            await message.answer(
                "Открыть встроенный плеер:",
                reply_markup=start_keyboard(),
            )
        except TelegramBadRequest as exc:
            logger.warning("/player: WebApp keyboard failed: %s", exc)
            await message.answer(
                "Открыть плеер: проверь WEBAPP_URL (нужен https). "
                "Сейчас кнопку показать не удалось — открой мини-апп из меня бота вручную."
            )

    @router.message(
        Command("pl", "playlists"),
        F.chat.type == ChatType.PRIVATE,
    )
    async def on_playlists(message: Message, command: CommandObject) -> None:
        if not message.from_user:
            return
        uid = message.from_user.id
        args = (command.args or "").strip()
        al = args.lower()
        if al.startswith("new "):
            name = args[4:].strip()
            if not name:
                await message.reply("Использование: /pl new Название")
                return
            pid, err = await acceptance_store.playlist_create(uid, name)
            if err:
                await message.reply(err)
                return
            assert pid is not None
            await message.reply(
                f"Плейлист «{html.escape(name)}» готов. Те же плейлисты в Mini App. "
                f"Клади треки кнопкой «➕ В плейлист» после поиска.",
                parse_mode=ParseMode.HTML,
            )
            return
        if al == "new":
            await message.reply("Использование: /pl new Название")
            return
        if args.isdigit():
            await _open_playlist_view_message(message, uid, int(args))
            return
        if args:
            await message.reply(
                "Непонятно. /pl — список, /pl new Имя, /pl 3 — открыть id 3"
            )
            return
        rows = await acceptance_store.playlists_list(uid)
        if not rows:
            await message.reply(
                "Плейлистов пока нет. Создай: /pl new Мои треки\n"
                "То же в Mini App → вкладка «Плейлисты»."
            )
            return
        await message.reply(
            "Твои плейлисты (синхрон с Mini App). Нажми на строку или /pl 5 по id.",
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
        show_pl = cq.message.chat.type == ChatType.PRIVATE
        pick_kb = make_post_pick_keyboard(key, show_playlist=show_pl)
        if not pick_kb:
            await cq.answer("Список устарел, поищи заново.", show_alert=True)
            return

        meta = pick_meta.get(key)
        if meta:
            title, artist = meta[0], meta[1]
        else:
            title, artist = None, None
        if title:
            lines: list[str] = [title]
            if artist:
                lines.append(artist)
        else:
            lines = ["Трек"]
        pl_hint = " Или ➕ в плейлист — кнопка ниже." if show_pl else ""
        text = (
            "\n".join(lines)
            + "\n\nПлеер, SoundCloud, скачать MP3."
            + pl_hint
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

        raw = pending_cache.get(payload)
        await acceptance_store.record(
            user_id=cq.from_user.id,
            username=cq.from_user.username,
            terms_version=TERMS_VERSION,
        )
        await cq.answer("Спасибо! Согласие сохранено.")

        if not raw:
            try:
                await cq.message.edit_text(
                    "Согласие принято. Заявка на скачивание устарела — пришли "
                    "ссылку или название трека ещё раз."
                )
            except Exception:
                pass
            return

        if isinstance(raw, str) and raw.startswith("plbulk:"):
            try:
                pl_id = int(raw.split(":", 1)[1])
            except (ValueError, IndexError):
                try:
                    await cq.message.edit_text("Согласие сохранено, но заявка сбой.")
                except Exception:
                    pass
                return
            try:
                await cq.message.edit_text("Согласие принято. Качаю плейлист…")
            except Exception:
                pass
            await _run_pl_bulk(cq.message, cq.from_user.id, pl_id)
            return

        url = raw
        if not str(url).startswith("http"):
            try:
                await cq.message.edit_text(
                    "Согласие принято, но ссылка устарела — пришли снова."
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
        if cq.message.chat.type != ChatType.PRIVATE:
            await cq.answer("Плейлисты только в личке с ботом.", show_alert=True)
            return
        key = cq.data[len(CALLBACK_PL_MENU):]
        if not key or not url_cache.get(key):
            await cq.answer("Список устарел — поищи снова.", show_alert=True)
            return
        rows = await acceptance_store.playlists_list(cq.from_user.id)
        if not rows:
            await cq.answer("Создай: /pl new Название", show_alert=True)
            return
        meta = pick_meta.get(key)
        if meta:
            t0, a0 = meta[0], meta[1]
            if a0:
                head = f"{html.escape(t0)}\n{html.escape(a0)}\n\nКуда добавить?"
            else:
                head = f"{html.escape(t0)}\n\nКуда добавить?"
        else:
            head = "Куда добавить трек?"
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
            await cq.answer("Ошибка", show_alert=True)
            return
        url = url_cache.get(key)
        if not url:
            await cq.answer("Ссылка устарела.", show_alert=True)
            return
        meta = pick_meta.get(key)
        if meta:
            title, ar, th = meta[0], meta[1], meta[2]
        else:
            title, ar, th = "Без названия", "", None
        err = await acceptance_store.playlist_add_track(
            cq.from_user.id, pl_id, url, title, ar, th
        )
        if err:
            await cq.answer(err, show_alert=True)
            return
        pname = await acceptance_store.playlist_name(cq.from_user.id, pl_id) or ""
        await cq.answer(f"Добавлено в «{pname[:40]}»" if pname else "Ок", show_alert=True)
        tail = "Плеер, MP3, плейлист — снова кнопки ниже."
        if meta and meta[0]:
            t0, a0 = meta[0], (meta[1] or "").strip()
            if a0:
                back = f"{html.escape(t0)}\n{html.escape(a0)}\n\n{tail}"
            else:
                back = f"{html.escape(t0)}\n\n{tail}"
        else:
            back = tail
        kb = make_post_pick_keyboard(
            key, show_playlist=cq.message.chat.type == ChatType.PRIVATE
        )
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
        await _open_playlist_view_edit(cq, cq.from_user.id, int(raw))
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
                await cq.message.edit_text("Плейлист удалён (и в Mini App пропадёт).")
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
            await cq.answer("Не найден", show_alert=True)
            return
        await cq.answer("Убрано")
        await _open_playlist_view_edit(cq, uid, pl_id)

    @router.callback_query(F.data.startswith(CALLBACK_PL_BULK))
    async def on_pl_bulk_download(cq: CallbackQuery) -> None:
        if not cq.data or not cq.from_user or not cq.message:
            await cq.answer()
            return
        raw = cq.data[len(CALLBACK_PL_BULK):]
        if not raw.isdigit():
            await cq.answer()
            return
        pl_id = int(raw)
        uid = cq.from_user.id
        if not await acceptance_store.has_accepted(uid, TERMS_VERSION):
            await cq.answer()
            await _send_pl_bulk_terms_prompt(cq.message, pl_id)
            return
        await cq.answer("Начинаю рассылку mp3…")
        try:
            await cq.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await _run_pl_bulk(cq.message, uid, pl_id)

    return router
