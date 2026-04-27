from __future__ import annotations

import asyncio
import html
import logging
import re
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
    KeyboardButton,
    LinkPreviewOptions,
    Message,
    ReplyKeyboardMarkup,
    WebAppInfo,
)
from aiogram.utils.markdown import hbold

from app import i18n
from app.config import Settings
from app.db import AcceptanceStore, PlaylistSummary
from app.llm import LLMClient, LLMUnavailable
from app.soundcloud import (
    SearchResult,
    SoundCloudError,
    Track,
    download_track,
    find_soundcloud_url,
    read_mp3_duration_seconds,
    search_tracks,
    tag_id3,
)

logger = logging.getLogger(__name__)


def _safe_mp3_filename(title: str, part: int, total: int) -> str:
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", (title or "track").strip()) or "track"
    if len(s) > 100:
        s = s[:100].rstrip()
    if total > 1:
        return f"{s} ({part}-{total}).mp3"
    return f"{s}.mp3"


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

TERMS_VERSION = "1.4"


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


def _format_button_label(idx: int, item: SearchResult, lang: str) -> str:
    parts: list[str] = [f"{idx}."]
    if item.artist:
        parts.append(f"{item.artist} —")
    parts.append(item.title or i18n.t(lang, "no_title"))
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

    _TXT_PLAYLISTS = (i18n.t("ru", "k_playlists"), i18n.t("en", "k_playlists"))
    _TXT_HELP_BTN = (i18n.t("ru", "k_help"), i18n.t("en", "k_help"))
    _TXT_LANG_RU = i18n.t("ru", "k_lang_ru")
    _TXT_LANG_EN = i18n.t("en", "k_lang_en")
    _K_SOUND = i18n.t("ru", "k_soundcloud")  # same in en

    async def _lang_of(user_id: int | None) -> str:
        if user_id is None:
            return "ru"
        return await acceptance_store.get_user_lang(user_id)

    def main_reply_markup(lang: str) -> ReplyKeyboardMarkup:
        row1: list[KeyboardButton] = []
        if webapp_url:
            wu = webapp_url.rstrip("/")
            row1.append(
                KeyboardButton(
                    text=_K_SOUND,
                    web_app=WebAppInfo(url=f"{wu}/"),
                )
            )
        else:
            row1.append(KeyboardButton(text=_K_SOUND))
        row1.append(KeyboardButton(text=i18n.t(lang, "k_playlists")))
        row1.append(KeyboardButton(text=i18n.t(lang, "k_help")))
        return ReplyKeyboardMarkup(
            keyboard=[
                row1,
                [
                    KeyboardButton(text=_TXT_LANG_RU),
                    KeyboardButton(text=_TXT_LANG_EN),
                ],
            ],
            resize_keyboard=True,
            is_persistent=True,
            input_field_placeholder=i18n.t(lang, "input_placeholder"),
        )

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

    def make_track_keyboard(track_url: str, lang: str) -> InlineKeyboardMarkup:
        rows: list[list[InlineKeyboardButton]] = []
        if webapp_url:
            rows.append(
                [
                    _player_button(
                        webapp_url, track_url, i18n.t(lang, "btn_open_player")
                    )
                ]
            )
        rows.append(
            [InlineKeyboardButton(text=i18n.t(lang, "btn_open_sc"), url=track_url)]
        )
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def start_keyboard(lang: str) -> InlineKeyboardMarkup | None:
        if not webapp_url:
            return None
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    _player_button(
                        webapp_url, None, i18n.t(lang, "btn_open_player")
                    )
                ]
            ]
        )

    def make_search_keyboard(results: list[SearchResult], lang: str) -> InlineKeyboardMarkup:
        rows: list[list[InlineKeyboardButton]] = []
        for idx, item in enumerate(results, start=1):
            key = url_cache.put(item.url)
            pick_meta.set(
                key,
                (item.title or i18n.t(lang, "no_title")).strip(),
                (item.artist or "").strip(),
                item.thumbnail,
            )
            rows.append(
                [
                    InlineKeyboardButton(
                        text=_format_button_label(idx, item, lang),
                        callback_data=f"{CALLBACK_PICK_PREFIX}{key}",
                    )
                ]
            )
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def make_post_pick_keyboard(
        cache_key: str, lang: str, *, show_playlist: bool = True
    ) -> InlineKeyboardMarkup | None:
        """Плеер, SoundCloud, скачивание — после нажатия на строке в поиске."""
        track_url = url_cache.get(cache_key)
        if not track_url:
            return None
        rows: list[list[InlineKeyboardButton]] = []
        if webapp_url:
            rows.append(
                [
                    _player_button(
                        webapp_url, track_url, i18n.t(lang, "btn_open_player")
                    )
                ]
            )
        rows.append(
            [InlineKeyboardButton(text=i18n.t(lang, "btn_open_sc"), url=track_url)]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text=i18n.t(lang, "btn_download"),
                    callback_data=f"{CALLBACK_DOWNLOAD_PREFIX}{cache_key}",
                )
            ]
        )
        if show_playlist:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=i18n.t(lang, "btn_add_pl"),
                        callback_data=f"{CALLBACK_PL_MENU}{cache_key}",
                    )
                ]
            )
        return InlineKeyboardMarkup(inline_keyboard=rows)

    async def _send_mp3_to_chat(
        target: Message,
        url: str,
        lang: str,
    ) -> str | None:
        """Скачать один трек и отправить одним сообщением с mp3.

        Плейлист: вызывается по разу на трек — отдельное скачивание и отдельная
        отправка, лимит Telegram 50 МБ на каждый файл, не на весь плейлист сразу.
        """
        try:
            track: Track = await download_track(
                url=url,
                download_root=settings.download_dir,
                max_bytes=settings.max_upload_bytes,
            )
        except SoundCloudError:
            logger.warning("Failed to download %s", url)
            return i18n.t(lang, "sc_failed")
        except Exception:
            logger.exception("Unexpected error while handling %s", url)
            return i18n.t(lang, "server_err")

        try:
            bot_tag = await get_bot_tag(target.bot)
            base_caption = f"{hbold(track.title)}\n{track.artist}"
            if track.is_preview:
                meta = f"{track.duration // 60}:{track.duration % 60:02d}"
                cap_extra = i18n.t(
                    lang,
                    "preview_note",
                    actual=track.actual_duration,
                    meta=meta,
                )
                if webapp_url:
                    cap_extra += i18n.t(
                        lang,
                        "preview_full_hint_pl",
                        btn=i18n.t(lang, "btn_open_player"),
                    )
                else:
                    cap_extra += i18n.t(lang, "preview_full_hint_sc")
                base_caption += cap_extra
            if bot_tag:
                base_caption += f"\n\nvia {bot_tag}"

            parts = list(track.chunk_paths) if track.chunk_paths else [track.file_path]
            n = len(parts)
            if n > 1:
                base_caption += f"\n\n{i18n.t(lang, 'file_split', n=n)}"

            for idx, part_path in enumerate(parts):
                caption = base_caption
                if n > 1:
                    caption += f"\n{i18n.t(lang, 'part_n', i=idx + 1, n=n)}"
                await target.bot.send_chat_action(
                    target.chat.id, ChatAction.UPLOAD_VOICE
                )
                tag_id3(part_path, bot_tag)
                fname = _safe_mp3_filename(track.title, idx + 1, n)
                part_dur = read_mp3_duration_seconds(part_path) or None
                await target.answer_audio(
                    audio=FSInputFile(part_path, filename=fname),
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                    title=track.title,
                    performer=track.artist,
                    duration=part_dur,
                    reply_markup=make_track_keyboard(track.webpage_url, lang)
                    if idx == 0
                    else None,
                )
        except Exception:
            logger.exception("Failed to send audio for %s", url)
            return i18n.t(lang, "send_fail")
        finally:
            track.cleanup()
        return None

    async def deliver_track(
        chat_message: Message,
        status: Message,
        url: str,
        lang: str,
    ) -> None:
        """Скачать трек SoundCloud и отправить mp3."""
        err = await _send_mp3_to_chat(chat_message, url, lang)
        if err:
            _sz = "50" in err or "МБ" in err or "MB" in err
            km = make_track_keyboard(url, lang) if (webapp_url and _sz) else None
            await status.edit_text(err, reply_markup=km)
            return
        try:
            await status.delete()
        except Exception:
            pass

    def _acceptance_keyboard(key: str, lang: str) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=i18n.t(lang, "btn_accept"),
                        callback_data=f"{CALLBACK_ACCEPT_PREFIX}{key}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=i18n.t(lang, "btn_read_full"),
                        callback_data=f"{CALLBACK_ACCEPT_PREFIX}show",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=i18n.t(lang, "btn_not_now"),
                        callback_data=CALLBACK_DECLINE,
                    )
                ],
            ]
        )

    async def _send_acceptance_prompt(
        target_message: Message, url: str, lang: str
    ) -> None:
        key = pending_cache.put(url)
        await target_message.answer(
            i18n.t(lang, "terms_prompt"),
            reply_markup=_acceptance_keyboard(key, lang),
            disable_web_page_preview=True,
        )

    async def _ensure_accepted_or_prompt(message: Message, url: str) -> bool:
        if not message.from_user:
            return True
        if await acceptance_store.has_accepted(message.from_user.id, TERMS_VERSION):
            return True
        lang = await _lang_of(message.from_user.id)
        await _send_acceptance_prompt(message, url, lang)
        return False

    async def _send_pl_bulk_terms_prompt(
        target_message: Message, pl_id: int, lang: str
    ) -> None:
        pkey = pending_cache.put(f"plbulk:{pl_id}")
        await target_message.answer(
            i18n.t(lang, "terms_prompt"),
            reply_markup=_acceptance_keyboard(pkey, lang),
            disable_web_page_preview=True,
        )

    def _format_playlist_message(pl_name: str, entries, lang: str) -> str:
        head = f"🎧 {html.escape(pl_name)}"
        if not entries:
            return head + f"\n\n{i18n.t(lang, 'pl_empty_body')}"
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

    def _playlist_tracks_keyboard(
        playlist_id: int, entries, lang: str
    ) -> InlineKeyboardMarkup:
        rrows: list[list[InlineKeyboardButton]] = []
        if webapp_url:
            wu = webapp_url.rstrip("/")
            rrows.append(
                [
                    InlineKeyboardButton(
                        text=i18n.t(lang, "btn_pl_in_player"),
                        web_app=WebAppInfo(url=f"{wu}/?pl={playlist_id}"),
                    )
                ]
            )
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
                    text=i18n.t(
                        lang, "bulk_dl_all", m=BULK_MP3_MAX
                    ),
                    callback_data=f"{CALLBACK_PL_BULK}{playlist_id}",
                )
            ]
        )
        rrows.append(
            [
                InlineKeyboardButton(
                    text=i18n.t(lang, "pl_del_btn"),
                    callback_data=f"{CALLBACK_PL_DEL}{playlist_id}",
                )
            ]
        )
        return InlineKeyboardMarkup(inline_keyboard=rrows)

    async def _open_playlist_view_message(
        message: Message, user_id: int, pl_id: int, lang: str
    ) -> bool:
        pl_name = await acceptance_store.playlist_name(user_id, pl_id)
        if pl_name is None:
            await message.reply(i18n.t(lang, "pl_not_found"))
            return False
        tr = await acceptance_store.playlist_get_tracks(user_id, pl_id)
        if tr is None:
            await message.reply(i18n.t(lang, "pl_not_found"))
            return False
        text = _format_playlist_message(pl_name, tr, lang)
        await message.reply(
            text,
            reply_markup=_playlist_tracks_keyboard(pl_id, tr, lang),
            parse_mode=ParseMode.HTML,
        )
        return True

    async def _open_playlist_view_edit(
        cq: CallbackQuery, user_id: int, pl_id: int, lang: str
    ) -> None:
        if not cq.message:
            return
        pl_name = await acceptance_store.playlist_name(user_id, pl_id)
        if pl_name is None:
            try:
                await cq.message.edit_text(i18n.t(lang, "pl_not_found"))
            except Exception:
                pass
            return
        tr = await acceptance_store.playlist_get_tracks(user_id, pl_id)
        if tr is None:
            try:
                await cq.message.edit_text(i18n.t(lang, "pl_not_found"))
            except Exception:
                pass
            return
        text = _format_playlist_message(pl_name, tr, lang)
        kb = _playlist_tracks_keyboard(pl_id, tr, lang)
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

    async def _run_pl_bulk(
        target: Message, user_id: int, pl_id: int, lang: str
    ) -> None:
        name = await acceptance_store.playlist_name(user_id, pl_id)
        if name is None:
            await target.bot.send_message(
                target.chat.id,
                i18n.t(lang, "pl_not_found"),
            )
            return
        tracks = await acceptance_store.playlist_get_tracks(user_id, pl_id)
        if tracks is None:
            await target.bot.send_message(
                target.chat.id,
                i18n.t(lang, "pl_not_found"),
            )
            return
        if not tracks:
            await target.bot.send_message(
                target.chat.id,
                i18n.t(lang, "pl_tracks_empty"),
            )
            return
        n = len(tracks)
        if n > BULK_MP3_MAX:
            await target.bot.send_message(
                target.chat.id,
                i18n.t(lang, "pl_bulk_too_many", n=n, m=BULK_MP3_MAX),
            )
            return
        # send_message: после accept сообщение с «Принимаю» может быть удалено
        st = await target.bot.send_message(
            target.chat.id,
            i18n.t(lang, "download_warn")
            + f"\n\n{i18n.t(lang, 'pl_bulk_status', name=html.escape(name), n=n)}",
            parse_mode=ParseMode.HTML,
        )
        ok = 0
        err = 0
        for i, t in enumerate(tracks, start=1):
            try:
                await st.edit_text(
                    f"🎧 «{html.escape(name)}»\n"
                    f"{i18n.t(lang, 'progress_bulk', i=i, n=n)}",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass
            emsg = await _send_mp3_to_chat(target, t.track_url, lang)
            if emsg is None:
                ok += 1
            else:
                err += 1
            if i < n:
                await asyncio.sleep(BULK_MP3_DELAY_SEC)
        final = i18n.t(
            lang, "pl_bulk_final", name=html.escape(name), ok=ok, err=err
        )
        try:
            await st.edit_text(final, parse_mode=ParseMode.HTML)
        except Exception:
            await target.bot.send_message(
                target.chat.id,
                final,
                parse_mode=ParseMode.HTML,
            )

    @router.message(CommandStart())
    async def on_start(message: Message) -> None:
        lang = await _lang_of(message.from_user.id if message.from_user else None)
        payload = (message.text or "").partition(" ")[2].strip()
        if payload.startswith("dl_"):
            key = payload[3:]
            url = url_cache.get(key)
            if not url:
                tag = await get_bot_tag(message.bot)
                await message.answer(
                    i18n.t(lang, "start_expired_user", tag=tag or "…")
                )
                return
            if not await _ensure_accepted_or_prompt(message, url):
                return
            status = await message.answer(
                i18n.t(lang, "download_warn")
                + f"\n\n{i18n.t(lang, 'downloading_one')}",
                parse_mode=ParseMode.HTML,
                reply_markup=main_reply_markup(lang),
            )
            await message.bot.send_chat_action(message.chat.id, ChatAction.RECORD_VOICE)
            await deliver_track(message, status, url, lang)
            return

        try:
            await message.answer(
                i18n.t(lang, "welcome"),
                disable_web_page_preview=True,
                reply_markup=main_reply_markup(lang),
            )
        except TelegramBadRequest as exc:
            logger.warning(
                "/start: reply with WebApp keyboard failed, sending text only: %s",
                exc,
            )
            await message.answer(
                i18n.t(lang, "welcome"),
                disable_web_page_preview=True,
            )

    @router.message(Command("help"))
    async def on_help(message: Message) -> None:
        lang = await _lang_of(message.from_user.id if message.from_user else None)
        await message.answer(
            i18n.t(lang, "help"),
            disable_web_page_preview=True,
        )

    @router.message(Command("terms"))
    async def on_terms(message: Message) -> None:
        lang = await _lang_of(message.from_user.id if message.from_user else None)
        suffix = ""
        if message.from_user:
            accepted = await acceptance_store.has_accepted(
                message.from_user.id, TERMS_VERSION
            )
            suffix = (
                "\n\n" + i18n.t(lang, "terms_footer_already", ver=TERMS_VERSION)
                if accepted
                else "\n\n" + i18n.t(lang, "terms_footer_later")
            )
        await message.answer(
            i18n.terms_html(lang, TERMS_VERSION) + suffix,
            disable_web_page_preview=True,
        )

    @router.message(Command("player"))
    async def on_player(message: Message) -> None:
        lang = await _lang_of(message.from_user.id if message.from_user else None)
        if not webapp_url:
            await message.answer(i18n.t(lang, "webapp_unavailable"))
            return
        try:
            await message.answer(
                i18n.t(lang, "open_player"),
                reply_markup=start_keyboard(lang),
            )
        except TelegramBadRequest as exc:
            logger.warning("/player: WebApp keyboard failed: %s", exc)
            await message.answer(i18n.t(lang, "open_player_fail"))

    async def _playlists_cmd_body(
        message: Message, args: str, lang: str
    ) -> None:
        if not message.from_user:
            return
        uid = message.from_user.id
        al = args.lower()
        if al.startswith("new "):
            name = args[4:].strip()
            if not name:
                await message.reply(i18n.t(lang, "pl_new_usage"))
                return
            pid, err = await acceptance_store.playlist_create(uid, name)
            if err:
                await message.reply(err)
                return
            assert pid is not None
            await message.reply(
                i18n.t(
                    lang,
                    "pl_after_create",
                    name=html.escape(name),
                ),
                parse_mode=ParseMode.HTML,
            )
            return
        if al == "new":
            await message.reply(i18n.t(lang, "pl_new_usage"))
            return
        if args.isdigit():
            await _open_playlist_view_message(message, uid, int(args), lang)
            return
        if args:
            await message.reply(i18n.t(lang, "pl_confused"))
            return
        rows = await acceptance_store.playlists_list(uid)
        if not rows:
            await message.reply(i18n.t(lang, "pl_none_title"))
            return
        await message.reply(
            i18n.t(lang, "pl_list_intro"),
            reply_markup=_pl_summaries_keyboard(rows),
        )

    @router.message(
        Command("pl", "playlists"),
        F.chat.type == ChatType.PRIVATE,
    )
    async def on_playlists(message: Message, command: CommandObject) -> None:
        lang = await _lang_of(message.from_user.id if message.from_user else None)
        args = (command.args or "").strip()
        await _playlists_cmd_body(message, args, lang)

    @router.message(
        F.text.in_({_TXT_LANG_RU, _TXT_LANG_EN}),
        F.chat.type == ChatType.PRIVATE,
    )
    async def on_lang_button(message: Message) -> None:
        if not message.from_user:
            return
        text = (message.text or "").strip()
        if text == _TXT_LANG_RU:
            await acceptance_store.set_user_lang(message.from_user.id, "ru")
            lang = "ru"
        else:
            await acceptance_store.set_user_lang(message.from_user.id, "en")
            lang = "en"
        await message.answer(
            i18n.t(lang, "language_set_ru")
            if lang == "ru"
            else i18n.t(lang, "language_set_en"),
            reply_markup=main_reply_markup(lang),
        )

    @router.message(
        F.text.in_(_TXT_PLAYLISTS),
        F.chat.type == ChatType.PRIVATE,
    )
    async def on_playlists_button(message: Message) -> None:
        lang = await _lang_of(message.from_user.id if message.from_user else None)
        await _playlists_cmd_body(message, "", lang)

    @router.message(
        F.text.in_(_TXT_HELP_BTN),
        F.chat.type == ChatType.PRIVATE,
    )
    async def on_help_button(message: Message) -> None:
        lang = await _lang_of(message.from_user.id if message.from_user else None)
        await message.answer(
            i18n.t(lang, "help"),
            disable_web_page_preview=True,
        )

    @router.message(
        F.text == _K_SOUND,
        F.chat.type == ChatType.PRIVATE,
    )
    async def on_soundcloud_text(message: Message) -> None:
        """Текст с кнопки без WebApp; при WEBAPP настроен — как обычный поиск."""
        lang = await _lang_of(message.from_user.id if message.from_user else None)
        if webapp_url:
            await _do_search(message, _K_SOUND, lang)
            return
        await message.answer(
            i18n.t(lang, "webapp_unavailable"),
            reply_markup=main_reply_markup(lang),
        )

    @router.message(Command("search"))
    async def on_search_cmd(message: Message) -> None:
        lang = await _lang_of(message.from_user.id if message.from_user else None)
        query = (message.text or "").partition(" ")[2].strip()
        if not query:
            await message.reply(i18n.t(lang, "search_no_cmd"), parse_mode=ParseMode.HTML)
            return
        await _do_search(message, query, lang)

    @router.message(F.text)
    async def on_text(message: Message) -> None:
        lang = await _lang_of(message.from_user.id if message.from_user else None)
        text = message.text or ""
        url = find_soundcloud_url(text)
        if url:
            if not await _ensure_accepted_or_prompt(message, url):
                return
            status = await message.reply(
                i18n.t(lang, "download_warn")
                + f"\n\n{i18n.t(lang, 'downloading_start')}",
                parse_mode=ParseMode.HTML,
                reply_markup=main_reply_markup(lang),
            )
            await message.bot.send_chat_action(message.chat.id, ChatAction.RECORD_VOICE)
            await deliver_track(message, status, url, lang)
            return

        # В группах/каналах не рассматривать произвольный текст как поиск — иначе бот
        # реагирует на каждое сообщение в чате. Поиск там: /search, либо через @ в inline.
        if message.chat.type != ChatType.PRIVATE:
            return

        await _do_search(message, text, lang)

    async def _do_search(message: Message, query: str, lang: str) -> None:
        query = query.strip()
        if len(query) < 2:
            await message.reply(i18n.t(lang, "search_too_short"))
            return

        status = await message.reply(
            i18n.t(lang, "search_looking", q=_truncate(query, 80))
        )

        try:
            results = await search_tracks(query, limit=SEARCH_LIMIT)
        except SoundCloudError as exc:
            logger.warning("Search failed for %r: %s", query, exc)
            await status.edit_text(i18n.t(lang, "search_fail"))
            return
        except Exception:
            logger.exception("Unexpected search error for %r", query)
            await status.edit_text(i18n.t(lang, "search_broken"))
            return

        if results:
            await status.edit_text(
                i18n.t(lang, "found_intro", n=len(results)),
                reply_markup=make_search_keyboard(results, lang),
            )
            return

        if llm:
            normalized = await _try_normalize(query)
            if normalized and normalized.lower() != query.lower():
                try:
                    await status.edit_text(
                        i18n.t(
                            lang,
                            "search_llm_try",
                            q1=_truncate(query, 40),
                            q2=_truncate(normalized, 60),
                        )
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
                        i18n.t(
                            lang,
                            "search_llm_found",
                            q1=_truncate(query, 40),
                            q2=_truncate(normalized, 60),
                            n=len(results),
                        ),
                        reply_markup=make_search_keyboard(results, lang),
                    )
                    return

        await status.edit_text(i18n.t(lang, "search_nothing"))

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
        lang = await _lang_of(iq.from_user.id if iq.from_user else None)
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
                            text=i18n.t(lang, "btn_open_player"),
                            url=f"{webapp_url}/?track={quote(item.url, safe='')}",
                        )
                    ]
                )
            kb_rows.append(
                [
                    InlineKeyboardButton(
                        text=i18n.t(lang, "btn_open_sc"),
                        url=item.url,
                    )
                ]
            )
            if bot_username:
                dl_key = url_cache.put(item.url)
                kb_rows.append(
                    [
                        InlineKeyboardButton(
                            text=i18n.t(lang, "btn_download"),
                            url=f"https://t.me/{bot_username}?start=dl_{dl_key}",
                        )
                    ]
                )
            keyboard = InlineKeyboardMarkup(inline_keyboard=kb_rows)

            articles.append(
                InlineQueryResultArticle(
                    id=uuid.uuid4().hex,
                    title=_truncate(
                        item.title or i18n.t(lang, "no_title"),
                        64,
                    ),
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
        lang = await _lang_of(cq.from_user.id if cq.from_user else None)
        key = cq.data[len(CALLBACK_PICK_PREFIX):]
        url = url_cache.get(key)
        if not url:
            await cq.answer(i18n.t(lang, "cq_list_stale"), show_alert=True)
            return
        show_pl = cq.message.chat.type == ChatType.PRIVATE
        pick_kb = make_post_pick_keyboard(
            key, lang, show_playlist=show_pl
        )
        if not pick_kb:
            await cq.answer(i18n.t(lang, "cq_list_stale"), show_alert=True)
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
            lines = [i18n.t(lang, "track_default")]
        pl_hint = i18n.t(lang, "pick_pl_or_add") if show_pl else ""
        text = (
            "\n".join(lines)
            + f"\n\n{i18n.t(lang, 'pick_actions')}"
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
        lang = await _lang_of(cq.from_user.id)
        key = cq.data[len(CALLBACK_DOWNLOAD_PREFIX):]
        url = url_cache.get(key)
        if not url:
            await cq.answer(i18n.t(lang, "cq_link_stale"), show_alert=True)
            return
        if not await acceptance_store.has_accepted(
            cq.from_user.id, TERMS_VERSION
        ):
            await cq.answer()
            await _send_acceptance_prompt(cq.message, url, lang)
            return
        await cq.answer(i18n.t(lang, "downloading_short"))
        progress = (
            i18n.t(lang, "download_warn")
            + f"\n\n{i18n.t(lang, 'downloading_start')}"
        )
        try:
            await cq.message.edit_text(
                progress,
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        await cq.message.bot.send_chat_action(
            cq.message.chat.id, ChatAction.RECORD_VOICE
        )
        await deliver_track(cq.message, cq.message, url, lang)

    @router.callback_query(F.data.startswith(CALLBACK_ACCEPT_PREFIX))
    async def on_accept(cq: CallbackQuery) -> None:
        if not cq.data or not cq.from_user or not cq.message:
            await cq.answer()
            return

        lang = await _lang_of(cq.from_user.id)
        payload = cq.data[len(CALLBACK_ACCEPT_PREFIX):]

        if payload == "show":
            await cq.answer()
            await cq.message.answer(
                i18n.terms_html(lang, TERMS_VERSION),
                disable_web_page_preview=True,
            )
            return

        raw = pending_cache.get(payload)
        await acceptance_store.record(
            user_id=cq.from_user.id,
            username=cq.from_user.username,
            terms_version=TERMS_VERSION,
        )
        await cq.answer(i18n.t(lang, "accept_thanks"))

        if not raw:
            try:
                await cq.message.edit_text(i18n.t(lang, "accept_stale"))
            except Exception:
                pass
            return

        if isinstance(raw, str) and raw.startswith("plbulk:"):
            try:
                pl_id = int(raw.split(":", 1)[1])
            except (ValueError, IndexError):
                try:
                    await cq.message.edit_text(i18n.t(lang, "accept_err"))
                except Exception:
                    pass
                return
            try:
                await cq.message.delete()
            except Exception:
                pass
            await _run_pl_bulk(cq.message, cq.from_user.id, pl_id, lang)
            return

        url = raw
        if not str(url).startswith("http"):
            try:
                await cq.message.edit_text(i18n.t(lang, "accept_stale_url"))
            except Exception:
                pass
            return

        try:
            await cq.message.edit_text(
                i18n.t(lang, "download_warn")
                + f"\n\n{i18n.t(lang, 'downloading_one')}",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        await cq.message.bot.send_chat_action(
            cq.message.chat.id, ChatAction.RECORD_VOICE
        )
        await deliver_track(cq.message, cq.message, url, lang)

    @router.callback_query(F.data == CALLBACK_DECLINE)
    async def on_decline(cq: CallbackQuery) -> None:
        await cq.answer()
        if not cq.message or not cq.from_user:
            return
        lang = await _lang_of(cq.from_user.id)
        try:
            await cq.message.edit_text(i18n.t(lang, "decline_body"))
        except Exception:
            pass

    @router.callback_query(F.data.startswith(CALLBACK_PL_MENU))
    async def on_pl_menu(cq: CallbackQuery) -> None:
        if not cq.data or not cq.from_user or not cq.message:
            await cq.answer()
            return
        lang = await _lang_of(cq.from_user.id)
        if cq.message.chat.type != ChatType.PRIVATE:
            await cq.answer(
                i18n.t(lang, "pl_only_private"), show_alert=True
            )
            return
        key = cq.data[len(CALLBACK_PL_MENU):]
        if not key or not url_cache.get(key):
            await cq.answer(
                i18n.t(lang, "cq_list_stale"), show_alert=True
            )
            return
        rows = await acceptance_store.playlists_list(cq.from_user.id)
        if not rows:
            await cq.answer(
                i18n.t(lang, "pl_new_hint_alert"), show_alert=True
            )
            return
        meta = pick_meta.get(key)
        q = i18n.t(lang, "pl_what_name_full")
        if meta:
            t0, a0 = meta[0], meta[1]
            if a0:
                head = i18n.t(
                    lang, "pl_add_head1", title=html.escape(t0), artist=html.escape(a0), q=q
                )
            else:
                head = i18n.t(lang, "pl_add_head0", title=html.escape(t0), q=q)
        else:
            head = q
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
        lang = await _lang_of(cq.from_user.id)
        rest = cq.data[len(CALLBACK_PL_ADD):]
        try:
            pl_s, key = rest.split(":", 1)
            pl_id = int(pl_s)
        except (ValueError, IndexError):
            await cq.answer(i18n.t(lang, "bad_callback"), show_alert=True)
            return
        url = url_cache.get(key)
        if not url:
            await cq.answer(
                i18n.t(lang, "cq_link_stale"), show_alert=True
            )
            return
        meta = pick_meta.get(key)
        if meta:
            title, ar, th = meta[0], meta[1], meta[2]
        else:
            title, ar, th = i18n.t(lang, "no_title"), "", None
        err = await acceptance_store.playlist_add_track(
            cq.from_user.id, pl_id, url, title, ar, th
        )
        if err:
            await cq.answer(err, show_alert=True)
            return
        pname = await acceptance_store.playlist_name(cq.from_user.id, pl_id) or ""
        ack = (
            i18n.t(lang, "pl_added", name=pname[:40])
            if pname
            else i18n.t(lang, "pl_ok")
        )
        await cq.answer(ack, show_alert=True)
        tail = i18n.t(lang, "pl_tail")
        if meta and meta[0]:
            t0, a0 = meta[0], (meta[1] or "").strip()
            if a0:
                back = f"{html.escape(t0)}\n{html.escape(a0)}\n\n{tail}"
            else:
                back = f"{html.escape(t0)}\n\n{tail}"
        else:
            back = tail
        kb = make_post_pick_keyboard(
            key,
            lang,
            show_playlist=cq.message.chat.type == ChatType.PRIVATE,
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
        lang = await _lang_of(cq.from_user.id)
        await _open_playlist_view_edit(cq, cq.from_user.id, int(raw), lang)
        await cq.answer()

    @router.callback_query(F.data.startswith(CALLBACK_PL_DEL))
    async def on_pl_del(cq: CallbackQuery) -> None:
        if not cq.data or not cq.from_user or not cq.message:
            await cq.answer()
            return
        lang = await _lang_of(cq.from_user.id)
        raw = cq.data[len(CALLBACK_PL_DEL):]
        if not raw.isdigit():
            await cq.answer()
            return
        pl_id = int(raw)
        if await acceptance_store.playlist_delete(cq.from_user.id, pl_id):
            try:
                await cq.message.edit_text(i18n.t(lang, "pl_deleted"))
            except Exception:
                pass
            await cq.answer()
        else:
            await cq.answer(
                i18n.t(lang, "pl_not_found_nb"), show_alert=True
            )

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
        lang = await _lang_of(uid)
        if not await acceptance_store.playlist_remove_track(uid, pl_id, tr_id):
            await cq.answer(
                i18n.t(lang, "pl_not_found_nb"), show_alert=True
            )
            return
        await cq.answer(i18n.t(lang, "pl_removed"))
        await _open_playlist_view_edit(cq, uid, pl_id, lang)

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
        lang = await _lang_of(uid)
        if not await acceptance_store.has_accepted(uid, TERMS_VERSION):
            await cq.answer()
            await _send_pl_bulk_terms_prompt(cq.message, pl_id, lang)
            return
        await cq.answer(i18n.t(lang, "pl_bulk_start"))
        try:
            await cq.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await _run_pl_bulk(cq.message, uid, pl_id, lang)

    return router
