"""Тексты бота: ru / en. Ключи — стабильные идентификаторы."""

from __future__ import annotations

import html
from typing import Literal

Lang = Literal["ru", "en"]


def normalize_lang(value: str | None) -> Lang:
    v = (value or "").strip().lower()
    if v == "en":
        return "en"
    return "ru"


def _M(**pairs: str) -> dict[str, str]:
    return {k: v for k, v in pairs.items()}


# Полные условия (HTML) вынесены в terms_body_ru / terms_body_en
_STR: dict[str, dict[str, str]] = {
    "ru": _M(
        welcome=(
            "Привет! Работаю с SoundCloud.\n\n"
            "• Пришли ссылку на трек — пришлю mp3 с обложкой.\n"
            "• Напиши название — покажу до 10 вариантов; дальше плеер, SoundCloud "
            "или скачивание. При GROQ подсказки AI — если не нашлось по первому разу.\n"
            "• Кнопка <b>SoundCloud</b> снизу — плеер и плейлисты (Mini App); те же "
            "плейлисты — кнопка «Плейлисты».\n"
            "• В любом чате через @бот — inline-поиск; mp3 только здесь, после /terms.\n\n"
            "Снизу: быстрые кнопки. Команды всё ещё работают: /start /help /pl /terms"
        ),
        help=(
            "Ссылки: soundcloud.com/…, m.soundcloud.com, on.soundcloud.com/…\n\n"
            "Поиск: напиши название — выбери вариант, дальше плеер, SoundCloud или MP3.\n"
            "С GROQ бот попробует исправить запрос, если пусто.\n\n"
            "Лимит MP3: 50 МБ; часто только превью — полный трек в плеере Mini App. "
            "Перед первой загрузкой — /terms.\n\n"
            "Плейлисты: кнопка «Плейлисты» = Mini App. До 30 треков за раз на «скачать всё»."
        ),
        k_soundcloud="SoundCloud",
        k_playlists="📂 Плейлисты",
        k_help="❓ Справка",
        k_lang_ru="🌐 RU",
        k_lang_en="🌐 EN",
        language_set_ru="Язык: русский.",
        language_set_en="Language: English.",
        btn_open_player="🎧 В плеере",
        tma_queued="▶",
        tma_err="Не удалось",
        tma_pl_stale="Обнови список плейлиста.",
        btn_pl_in_player="🎧 Весь плейлист",
        btn_open_sc="На SoundCloud",
        btn_download="Скачать MP3",
        btn_add_pl="➕ В плейлист",
        pl_list_intro=(
            "Твои плейлисты (синхрон с Mini App). Нажми на строку "
            "или <code>/pl 5</code> по id."
        ),
        pl_not_found="Плейлист не найден. /pl",
        pl_new_usage="Использование: /pl new Название",
        pl_empty_hint="Нет плейлистов — создай по полю выше.",
        pl_none_title="Плейлистов пока нет. Создай: /pl new Мои треки\nТо же в Mini App → «Плейлисты».",
        pl_after_create="Плейлист «{name}» готов. Те же плейлисты в Mini App. "
        "Клади треки — «➕ В плейлист» после поиска.",
        pl_confused="Непонятно. /pl — список, /pl new Имя, /pl 3 — открыть id 3",
        search_too_short="Слишком короткий запрос. Минимум 2 символа или ссылка.",
        search_looking="Ищу «{q}»…",
        search_fail="Не получилось выполнить поиск. Попробуй ещё раз.",
        search_broken="Что-то сломалось при поиске. Попробуй позже.",
        search_no_cmd="Использование: /search &lt;запрос&gt; или пришли название.",
        found_intro="Нашёл {n} треков. Нажми на вариант — плеер, SoundCloud или MP3.",
        terms_suffix_accepted="✅ Условия {ver} приняты.",
        terms_suffix_prompt="Сначала прими условия — /terms.",
        webapp_unavailable="Mini App недоступен — нет WEBAPP_URL.",
        player_hint_fail="Плеер: проверь WEBAPP_URL (нужен https).",
        start_expired="Ссылка устарела — поищи снова.",
        sc_failed="Не скачал с SoundCloud, пропускаю.",
        server_err="Ошибка на сервере, пропускаю.",
        send_fail="Не получилось отправить файл в Telegram.",
        pl_bulk_final="🎧 «{name}»\n"
        "Готово: {ok} файлов, сбой/пропуск: {err}. "
        "Каждый трек — отдельное сообщение; лимит 50 МБ на один файл. "
        "Дальше — SoundCloud / сеть.",
        input_placeholder="Поиск или ссылка SoundCloud…",
        terms_prompt=(
            "Перед скачиванием: у части треков в чат уходит только превью (~30 с) — "
            "ограничения правообладателей; полный трек — в плеере (Mini App) или на SoundCloud. "
            "Один раз прими условия (/terms)."
        ),
        download_warn=(
            "⚠️ <b>Перед скачиванием</b>\n"
            "Целый трек одним MP3 в чат часто <b>недоступен</b> из‑за прав "
            "правообладателей: может быть только короткое <b>превью</b> (~30 с).\n"
            "Полностью <b>послушать</b> — во <b>встроенном плеере</b> (SoundCloud снизу) "
            "или на soundcloud.com."
        ),
        no_title="Без названия",
        track_default="Трек",
        terms_footer_already="✅ Ты уже принял эту версию условий ({ver}).",
        terms_footer_later="Я покажу кнопку «Принимаю» при первом скачивании.",
        btn_accept="✅ Принимаю",
        btn_read_full="📄 Прочитать полный текст",
        btn_not_now="❌ Не сейчас",
        cq_list_stale="Список устарел, поищи заново.",
        cq_link_stale="Ссылка устарела, поищи заново.",
        pick_actions="Плеер, SoundCloud, скачать MP3.",
        pick_pl_or_add=" Или ➕ в плейлист — кнопка ниже.",
        downloading_short="Качаю…",
        downloading_one="Согласие принято. Качаю выбранный трек…",
        downloading_start="Качаю трек… это займёт несколько секунд.",
        progress_bulk="⏳ {i}/{n}…",
        accept_thanks="Спасибо! Согласие сохранено.",
        accept_stale="Согласие принято. Заявка на скачивание устарела — пришли ссылку "
        "или название трека ещё раз.",
        accept_err="Согласие сохранено, но заявка сбой.",
        accept_stale_url="Согласие принято, но ссылка устарела — пришли снова.",
        decline_body=(
            "Окей, без проблем. Если передумаешь — пришли ссылку или название трека снова, "
            "я ещё раз покажу условия. Полный текст всегда по /terms."
        ),
        pl_only_private="Плейлисты только в личке с ботом.",
        pl_new_hint_alert="Создай: /pl new Название",
        pl_what_name="Куда добавить?",
        pl_what_name_full="Куда добавить трек?",
        pl_added="Добавлено в «{name}»",
        pl_ok="Ок",
        pl_tail="Плеер, MP3, плейлист — снова кнопки ниже.",
        pl_deleted="Плейлист удалён (и в Mini App пропадёт).",
        pl_not_found_nb="Не найден",
        pl_removed="Убрано",
        pl_bulk_start="Начинаю рассылку mp3…",
        pl_tracks_empty="В плейлисте нет треков.",
        pl_bulk_too_many=(
            "В плейлисте {n} треков. За раз отправляю не больше {m} mp3 — сократи плейлист "
            "в /pl / Mini App и нажми снова, либо качай остаток другой порцией после "
            "удаления уже скачанных."
        ),
        pl_empty_body="Плейлист пуст. Добавь треки из поиска (➕ В плейлист) или в Mini App.",
        pl_add_head1="{title}\n{artist}\n\n{q}",
        pl_add_head0="{title}\n\n{q}",
        search_nothing="Ничего не нашёл. Попробуй переформулировать или пришли прямую ссылку.",
        search_llm_try="Не нашёл «{q1}». Пробую «{q2}»…",
        search_llm_found=(
            "По «{q1}» ничего не нашёл, но по «{q2}» нашёл {n}. "
            "Нажми на вариант — плеер, SoundCloud или скачать MP3."
        ),
        start_expired_user="Эта ссылка устарела — поищи трек заново через {tag} или просто "
        "пришли название.",
        open_player="Открыть встроенный плеер:",
        open_player_fail=(
            "Открыть плеер: проверь WEBAPP_URL (нужен https). "
            "Сейчас кнопку показать не удалось — открой мини-апп из меня бота вручную."
        ),
        bulk_dl_all="⬇ Скачать все mp3 (≤{m})",
        pl_del_btn="🗑 Удалить",
        preview_note=(
            "\n\n⚠️ Это превью ~{actual} с (метаданные: {meta}) — "
            "так настроил правообладатель, полный трек в MP3 в чат не отдать."
        ),
        preview_full_hint_sc=" Полный трек — на SoundCloud, если открыт поток.",
        preview_full_hint_pl=" Полный трек — кнопка «{btn}» / на SoundCloud.",
        file_split="Файл разбит на {n} частей по лимиту Telegram (50 МБ).",
        part_n="Часть {i} из {n}.",
        pl_bulk_status="🎧 «{name}»\n⏳ 0/{n}…",
        bad_callback="Ошибка",
        webapp_brand_subtitle="в Telegram",
        webapp_close="Закрыть",
        webapp_tab_search="Поиск",
        webapp_tab_playlists="Плейлисты",
        webapp_nav_sections="Разделы",
        webapp_search_placeholder="Найти трек или вставить ссылку…",
        webapp_search_hint=(
            "Название, ссылка soundcloud.com. Плейлисты — соседняя вкладка. "
            "Mp3 в личке с ботом."
        ),
        webapp_empty_title="Что послушаем?",
        webapp_empty_sub=(
            "Введи запрос или ссылку — подберу треки. Плейлисты — соседняя вкладка."
        ),
        webapp_pl_name_placeholder="Название плейлиста",
        webapp_pl_create="Создать",
        webapp_pl_list_a11y="Список плейлистов",
        webapp_pl_empty="Нет плейлистов — создай по полю выше.",
        webapp_pl_back="Назад",
        webapp_pl_back_to_list="К плейлистам",
        webapp_pl_delete_aria="Удалить плейлист",
        webapp_pl_delete_title="Удалить",
        webapp_player_a11y="Плеер",
        webapp_loading="Загружаю…",
        webapp_footer=(
            "Widget SoundCloud. Звук, пока открыт мини-апп. "
            "MP3 — в чате с ботом."
        ),
        webapp_search_btn="Искать",
        webapp_results="Результаты",
        webapp_no_results="Ничего не нашёл. Попробуй переформулировать запрос.",
        webapp_search_err="Ошибка поиска",
        webapp_err_short="Ошибка",
        webapp_add_pl="В плейлист…",
        webapp_searching="Ищу…",
        webapp_pl_pick_first="Сначала создай плейлист во вкладке «Плейлисты».",
        webapp_pl_open_tg=(
            "Открой мини-апп из Telegram (кнопка «SoundCloud» в боте) — "
            "тогда плейлисты будут привязаны к твоему аккаунту."
        ),
        webapp_pl_auth_err=(
            "Сервер не подтвердил сессию Telegram. В деплое мини-аппа "
            "нужен тот же бот-токен, что у бота (TELEGRAM_API_KEY / BOT_TOKEN), "
            "и общая с ботом база (DATABASE_URL)."
        ),
        webapp_pl_load_list_fail="Не удалось загрузить",
        webapp_pl_open_detail_fail="Не удалось открыть плейлист. Попробуй ещё раз.",
        webapp_pl_n_tr="тр.",
        webapp_in_all_pl="Трек уже во всех плейлистах",
        webapp_reorder_fail="Не удалось изменить порядок",
        webapp_pl_del_confirm="Удалить плейлист целиком?",
        webapp_pl_create_fail="Не удалось создать",
        webapp_network_fail="Сеть недоступна. Попробуй ещё раз.",
        webapp_btn_prev="«15",
        webapp_btn_next="15»",
        webapp_nav_prev_pl="‹ трек",
        webapp_nav_next_pl="трек ›",
        webapp_tip_prev_pl="Предыдущий трек в плейлисте (на первом — −15 с)",
        webapp_tip_next_pl="Следующий трек в плейлисте (на последнем — +15 с)",
        webapp_tip_seek_m15="−15 секунд",
        webapp_tip_seek_p15="+15 секунд",
        webapp_aria_play_cover="Обложка, включить: ",
        webapp_aria_row_play="Включить: ",
        webapp_aria_enable_short="Включить",
        webapp_aria_up="Выше",
        webapp_aria_down="Ниже",
        webapp_aria_delete_track="Удалить трек",
        webapp_aria_play_pause="Воспроизведение / пауза",
    ),
    "en": _M(
        welcome=(
            "Hi! I work with SoundCloud.\n\n"
            "• Send a track link — I’ll send mp3 with art.\n"
            "• Type a name — I’ll list up to 10 matches; then player, SoundCloud, "
            "or download. With GROQ, AI may fix your query if needed.\n"
            "• The <b>SoundCloud</b> button below opens the player & playlists (Mini App); "
            "same lists via «Playlists».\n"
            "• In any chat, @ mention me for inline search; mp3 only here, after /terms.\n\n"
            "Quick buttons below. Commands still work: /start /help /pl /terms"
        ),
        help=(
            "Links: soundcloud.com/…, m.soundcloud.com, on.soundcloud.com/…\n\n"
            "Search: send a name — pick a result, then player, SoundCloud, or MP3. "
            "With GROQ, the bot may fix your query.\n\n"
            "MP3 limit: 50 MB; often a preview only — full track in the Mini App player. "
            "Before first download — /terms.\n\n"
            "Playlists: the «Playlists» button = same as Mini App. Up to 30 tracks per «download all»."
        ),
        k_soundcloud="SoundCloud",
        k_playlists="📂 Playlists",
        k_help="❓ Help",
        k_lang_ru="🌐 RU",
        k_lang_en="🌐 EN",
        language_set_ru="Language: Русский.",
        language_set_en="Language: English.",
        btn_open_player="🎧 In player",
        tma_queued="▶",
        tma_err="Couldn’t queue",
        tma_pl_stale="Refresh the playlist.",
        btn_pl_in_player="🎧 Full playlist",
        btn_open_sc="Open on SoundCloud",
        btn_download="Download MP3",
        btn_add_pl="➕ Add to playlist",
        pl_list_intro=(
            "Your playlists (synced with the Mini App). Tap a row or use "
            "<code>/pl 5</code> by id."
        ),
        pl_not_found="Playlist not found. /pl",
        pl_new_usage="Usage: /pl new Name",
        pl_empty_hint="No playlists — create one above.",
        pl_none_title="No playlists yet. Create: /pl new My tracks\nSame in the Mini App → «Playlists».",
        pl_after_create="Playlist “{name}” is ready. Same playlists in the Mini App. "
        "Add tracks with «➕ Add to playlist» after search.",
        pl_confused="Unknown. /pl — list, /pl new Name, /pl 3 — open id 3",
        search_too_short="Query too short. At least 2 characters or a link.",
        search_looking="Searching for «{q}»…",
        search_fail="Search failed. Try again.",
        search_broken="Something broke during search. Try later.",
        search_no_cmd="Usage: /search &lt;query&gt; or send a name.",
        found_intro="Found {n} tracks. Pick one — player, SoundCloud, or MP3.",
        terms_suffix_accepted="✅ Terms {ver} accepted.",
        terms_suffix_prompt="Accept the terms first — /terms.",
        webapp_unavailable="Mini App unavailable — WEBAPP_URL is not set.",
        player_hint_fail="Player: check WEBAPP_URL (https required).",
        start_expired="Link expired — search again.",
        sc_failed="Couldn’t download from SoundCloud, skipping.",
        server_err="Server error, skipping.",
        send_fail="Couldn’t send the file in Telegram.",
        pl_bulk_final="🎧 «{name}»\n"
        "Done: {ok} files, failed/skipped: {err}. "
        "Each track is a separate message; 50 MB per file. "
        "After that — SoundCloud / network.",
        input_placeholder="Search or SoundCloud link…",
        terms_prompt=(
            "Before downloading: some tracks only send a preview (~30 s) — rights limits; "
            "full playback is in the Mini App player or on SoundCloud. "
            "Accept the terms once (/terms)."
        ),
        download_warn=(
            "⚠️ <b>Before downloading</b>\n"
            "A full track as a single MP3 in chat is often <b>not available</b> due to "
            "rights holders: you may get only a short <b>preview</b> (~30 s).\n"
            "To listen in full, use the <b>built-in player</b> (SoundCloud button below) "
            "or soundcloud.com."
        ),
        no_title="Untitled",
        track_default="Track",
        terms_footer_already="✅ You already accepted terms version {ver}.",
        terms_footer_later="You’ll see an «Accept» button on the first download.",
        btn_accept="✅ I accept",
        btn_read_full="📄 Read full text",
        btn_not_now="❌ Not now",
        cq_list_stale="The list expired — search again.",
        cq_link_stale="The link expired — search again.",
        pick_actions="Player, SoundCloud, download MP3.",
        pick_pl_or_add=" Or add to a playlist with ➕ below.",
        downloading_short="Downloading…",
        downloading_one="Terms accepted. Downloading your track…",
        downloading_start="Downloading… this may take a few seconds.",
        progress_bulk="⏳ {i}/{n}…",
        accept_thanks="Thanks! Your acceptance is saved.",
        accept_stale="Acceptance saved, but the download request expired — send the link or track name again.",
        accept_err="Acceptance saved, but something went wrong with the request.",
        accept_stale_url="Acceptance saved, but the link expired — try again.",
        decline_body=(
            "Okay. If you change your mind, send a link or a track name again — "
            "I’ll show the terms. Full text: /terms."
        ),
        pl_only_private="Playlists are only in private chat with the bot.",
        pl_new_hint_alert="Create: /pl new Name",
        pl_what_name="Add to which playlist?",
        pl_what_name_full="Add this track to which playlist?",
        pl_added="Added to «{name}»",
        pl_ok="OK",
        pl_tail="Player, MP3, playlist — use the buttons below again.",
        pl_deleted="Playlist removed (it will also disappear in the Mini App).",
        pl_not_found_nb="Not found",
        pl_removed="Removed",
        pl_bulk_start="Starting mp3 delivery…",
        pl_tracks_empty="This playlist has no tracks.",
        pl_bulk_too_many=(
            "This playlist has {n} tracks. I send at most {m} mp3 at once — "
            "shorten the playlist in /pl or the Mini App, or download the rest in another batch."
        ),
        pl_empty_body="The playlist is empty. Add tracks from search (➕ Add to playlist) or the Mini App.",
        pl_add_head1="{title}\n{artist}\n\n{q}",
        pl_add_head0="{title}\n\n{q}",
        search_nothing="Nothing found. Rephrase or send a direct link.",
        search_llm_try="No results for «{q1}». Trying «{q2}»…",
        search_llm_found=(
            "Nothing for «{q1}», but {n} for «{q2}». Pick a result — player, "
            "SoundCloud, or MP3."
        ),
        start_expired_user="This link expired — search again with {tag} or send a track name.",
        open_player="Open the built-in player:",
        open_player_fail=(
            "To open the player, check WEBAPP_URL (https required). "
            "The button couldn’t be shown — open the mini app from the bot menu."
        ),
        bulk_dl_all="⬇ Download all mp3 (≤{m})",
        pl_del_btn="🗑 Delete",
        preview_note=(
            "\n\n⚠️ This is a ~{actual} s preview (metadata: {meta}) — "
            "as set by the rights holder; the full track can’t be sent as one MP3 here."
        ),
        preview_full_hint_sc=" Full playback on SoundCloud if streaming is open.",
        preview_full_hint_pl=" Full track: «{btn}» button or SoundCloud.",
        file_split="The file is split into {n} parts due to Telegram’s 50 MB limit per file.",
        part_n="Part {i} of {n}.",
        pl_bulk_status="🎧 «{name}»\n⏳ 0/{n}…",
        bad_callback="Error",
        webapp_brand_subtitle="in Telegram",
        webapp_close="Close",
        webapp_tab_search="Search",
        webapp_tab_playlists="Playlists",
        webapp_nav_sections="Sections",
        webapp_search_placeholder="Find a track or paste a link…",
        webapp_search_hint=(
            "Name or soundcloud.com link. Playlists — next tab. "
            "MP3 in a private chat with the bot."
        ),
        webapp_empty_title="What should we play?",
        webapp_empty_sub=(
            "Enter a search or a link — I’ll pick tracks. Playlists are on the other tab."
        ),
        webapp_pl_name_placeholder="Playlist name",
        webapp_pl_create="Create",
        webapp_pl_list_a11y="Playlist list",
        webapp_pl_empty="No playlists — create one above.",
        webapp_pl_back="Back",
        webapp_pl_back_to_list="All playlists",
        webapp_pl_delete_aria="Delete playlist",
        webapp_pl_delete_title="Delete",
        webapp_player_a11y="Player",
        webapp_loading="Loading…",
        webapp_footer=(
            "SoundCloud widget. Audio while the mini app is open. "
            "MP3 in the bot chat."
        ),
        webapp_search_btn="Search",
        webapp_results="Results",
        webapp_no_results="Nothing found. Try a different search.",
        webapp_search_err="Search error",
        webapp_err_short="Error",
        webapp_add_pl="Add to playlist…",
        webapp_searching="Searching…",
        webapp_pl_pick_first="Create a playlist in the «Playlists» tab first.",
        webapp_pl_open_tg=(
            "Open the mini app from Telegram (the SoundCloud button in the bot) — "
            "so playlists are linked to your account."
        ),
        webapp_pl_auth_err=(
            "Could not verify the Telegram session. The mini app needs the same "
            "bot token (TELEGRAM_API_KEY / BOT_TOKEN) and the same database (DATABASE_URL) as the bot."
        ),
        webapp_pl_load_list_fail="Failed to load",
        webapp_pl_open_detail_fail="Could not open the playlist. Try again.",
        webapp_pl_n_tr="tr",
        webapp_in_all_pl="Track is already in every playlist",
        webapp_reorder_fail="Could not change order",
        webapp_pl_del_confirm="Delete the entire playlist?",
        webapp_pl_create_fail="Could not create",
        webapp_network_fail="Network error. Please try again.",
        webapp_btn_prev="«15",
        webapp_btn_next="15»",
        webapp_nav_prev_pl="‹ tr",
        webapp_nav_next_pl="tr ›",
        webapp_tip_prev_pl="Previous playlist track (on first: −15 s)",
        webapp_tip_next_pl="Next playlist track (on last: +15 s)",
        webapp_tip_seek_m15="−15 seconds",
        webapp_tip_seek_p15="+15 seconds",
        webapp_aria_play_cover="Cover, play: ",
        webapp_aria_row_play="Play: ",
        webapp_aria_enable_short="Play",
        webapp_aria_up="Up",
        webapp_aria_down="Down",
        webapp_aria_delete_track="Remove track",
        webapp_aria_play_pause="Play / Pause",
    ),
}


def webapp_ui_keys() -> tuple[str, ...]:
    """Ключи строк для мини-аппа (GET /api/locale)."""
    return tuple(
        sorted(k for k in _STR["ru"] if k.startswith("webapp_")) + ["no_title"]
    )


# Условия (HTML) — отдельно, подставляем TERMS_VERSION в handlers при необходимости
def terms_html(lang: str, version: str) -> str:
    lang = normalize_lang(lang)
    if lang == "en":
        return _terms_en(version)
    return _terms_ru(version)


def _terms_ru(ver: str) -> str:
    return (
        f"<b>Условия использования</b> (версия {ver})\n\n"
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
        "юрисдикции лежит на тебе.\n"
        "4. Соблюдаешь Terms of Service SoundCloud и применимое законодательство.\n"
        "5. Понимаешь, что у части релизов в Telegram весь трек <b>одним</b> MP3 "
        "недоступен: может быть лишь превью (часто ~30 с); полный трек — "
        "во встроенном плеере (Mini App) и на SoundCloud.\n\n"
        "Бот не хранит скачанные файлы после отправки. "
        "Факт согласия (user_id, username, дата/время МСК) хранится в БД.\n\n"
        "Правообладатели: напиши владельцу бота, если нужно исключение."
    )


def _terms_en(ver: str) -> str:
    return (
        f"<b>Terms of use</b> (version {ver})\n\n"
        "This bot is a general-purpose tool that, at your request, uses SoundCloud’s "
        "public API and stores audio locally to send it via Telegram.\n\n"
        "<b>By using the bot, you agree that you:</b>\n"
        "1. Download tracks <b>only for private, non-commercial listening</b>.\n"
        "2. Will not redistribute, resell, or publish the files to the public or "
        "to a wide audience.\n"
        "3. Understand that copyright belongs to rights holders, and you are responsible "
        "for the legality of downloading in your jurisdiction.\n"
        "4. Comply with SoundCloud’s Terms of Service and applicable law.\n"
        "5. Understand that for some releases, Telegram may only get a <b>short preview</b> "
        "as a single MP3; the full track may be available in the Mini App player and on "
        "SoundCloud under platform rules.\n\n"
        "The bot does not keep files after sending. Your acceptance (user_id, username, "
        "Moscow time) is stored in the database.\n\n"
        "Rights holders: contact the bot owner to request takedown."
    )


def t(lang: str, key: str, **kwargs) -> str:
    lang = normalize_lang(lang)
    d = _STR.get(lang) or _STR["ru"]
    s = d.get(key) or _STR["ru"].get(key) or key
    if kwargs:
        return s.format(**kwargs)
    return s


def t_html_escape(lang: str, key: str, **kwargs) -> str:
    return html.escape(t(lang, key, **kwargs))
