(() => {
  const tg = window.Telegram && window.Telegram.WebApp;

  function applyTelegramTheme() {
    if (!tg || !tg.themeParams) return;
    const t = tg.themeParams;
    const r = document.documentElement;
    if (t.bg_color) {
      r.style.setProperty("--tg-theme-bg-color", t.bg_color);
      r.style.setProperty("--bg", t.bg_color);
    }
    if (t.text_color) {
      r.style.setProperty("--tg-theme-text-color", t.text_color);
      r.style.setProperty("--text", t.text_color);
    }
    if (t.hint_color) {
      r.style.setProperty("--tg-theme-hint-color", t.hint_color);
      r.style.setProperty("--text-dim", t.hint_color);
    }
    if (t.button_color) {
      r.style.setProperty("--tg-theme-button-color", t.button_color);
      r.style.setProperty("--accent", t.button_color);
    }
    if (t.button_text_color) {
      r.style.setProperty("--tg-theme-button-text-color", t.button_text_color);
      r.style.setProperty("--accent-text", t.button_text_color);
    }
    if (t.secondary_bg_color) {
      r.style.setProperty("--tg-theme-secondary-bg-color", t.secondary_bg_color);
      r.style.setProperty("--bg-elev", t.secondary_bg_color);
    }
    if (t.link_color) {
      r.style.setProperty("--tg-theme-link-color", t.link_color);
    }
    r.classList.add("tg-integrated");
    const themeMeta = document.querySelector('meta[name="theme-color"]');
    if (themeMeta && t.bg_color) {
      themeMeta.setAttribute("content", t.bg_color);
    }
    if (tg.setBackgroundColor && t.bg_color) {
      try {
        tg.setBackgroundColor(t.bg_color);
      } catch (e) {
        /* */
      }
    }
  }

  if (tg) {
    tg.ready();
    tg.expand();
    applyTelegramTheme();
    try {
      if (typeof tg.onEvent === "function") {
        tg.onEvent("themeChanged", applyTelegramTheme);
      }
    } catch (e) {
      /* */
    }
    try {
      if (tg.setHeaderColor) {
        tg.setHeaderColor("bg_color");
      }
    } catch (e) {
      /* */
    }
    try {
      if (tg.disableVerticalSwipes) {
        tg.disableVerticalSwipes();
      }
    } catch (e) {
      /* */
    }
    try {
      if (tg.MainButton && typeof tg.MainButton.hide === "function") {
        tg.MainButton.hide();
      }
    } catch (e) {
      /* */
    }
  }

  /** initData в части клиентов появляется не в первый кадр — читать при каждом запросе. */
  function getInitData() {
    const w = window.Telegram && window.Telegram.WebApp;
    return (w && w.initData) || "";
  }

  const iframe = document.getElementById("scPlayer");
  const empty = document.getElementById("empty");
  const playerWrap = document.getElementById("playerWrap");
  const playBtn = document.getElementById("playBtn");
  const prevBtn = document.getElementById("prevBtn");
  const nextBtn = document.getElementById("nextBtn");
  const closeBtn = document.getElementById("closeBtn");
  const metaTitle = document.getElementById("metaTitle");
  const metaArtist = document.getElementById("metaArtist");

  const searchInput = document.getElementById("searchInput");
  const searchBtn = document.getElementById("searchBtn");
  const resultsBox = document.getElementById("results");

  const tabSearchBtn = document.getElementById("tabSearchBtn");
  const tabPlBtn = document.getElementById("tabPlBtn");
  const panelSearch = document.getElementById("panelSearch");
  const panelPl = document.getElementById("panelPl");
  const plNoAuth = document.getElementById("plNoAuth");
  const plBox = document.getElementById("plBox");
  const plList = document.getElementById("plList");
  const plEmpty = document.getElementById("plEmpty");
  const plNewName = document.getElementById("plNewName");
  const plNewBtn = document.getElementById("plNewBtn");
  const plListView = document.getElementById("plListView");
  const plDetail = document.getElementById("plDetail");
  const plBack = document.getElementById("plBack");
  const plDeleteList = document.getElementById("plDeleteList");
  const plDetailTitle = document.getElementById("plDetailTitle");
  const plTracks = document.getElementById("plTracks");
  const playerPlRow = document.getElementById("playerPlRow");
  const playerPlAdd = document.getElementById("playerPlAdd");
  const playerPlHint = document.getElementById("playerPlHint");
  const playerPlHintNo = document.getElementById("playerPlHintNo");
  const playerPlPickSlot = document.getElementById("playerPlPickSlot");

  const SC_URL_RE = /https?:\/\/(?:(?:www|m|on)\.)?soundcloud\.com\/[^\s]+/i;
  const SEARCH_DEBOUNCE_MS = 450;
  const MIN_QUERY_LENGTH = 2;

  function apiHeaders(json) {
    const h = {};
    const d = getInitData();
    if (d) h["X-Telegram-Init-Data"] = d;
    if (json) h["Content-Type"] = "application/json";
    return h;
  }

  async function apiGet(path) {
    return fetch(path, { headers: apiHeaders() });
  }

  async function apiJson(method, path, body) {
    return fetch(path, {
      method,
      headers: apiHeaders(!!body),
      body: body ? JSON.stringify(body) : undefined,
    });
  }

  function readInitialPlId() {
    const params = new URLSearchParams(location.search);
    const q = params.get("pl");
    if (q && /^\d+$/.test(q)) {
      return parseInt(q, 10);
    }
    const sp = tg && tg.initDataUnsafe && tg.initDataUnsafe.start_param;
    if (sp) {
      const m = /^pl_(\d+)$/.exec(sp);
      if (m) {
        return parseInt(m[1], 10);
      }
    }
    return null;
  }

  function readInitialTrack() {
    const params = new URLSearchParams(location.search);
    const fromQuery = params.get("track");
    if (fromQuery) {
      return decodeURIComponent(fromQuery);
    }

    const startParam =
      tg && tg.initDataUnsafe && tg.initDataUnsafe.start_param;
    if (!startParam) {
      return null;
    }
    if (/^pl_\d+$/.test(startParam)) {
      return null;
    }
    try {
      const dec = atob(
        startParam.replace(/-/g, "+").replace(/_/g, "/")
      );
      if (dec && /^https?:\/\//i.test(dec)) {
        return dec;
      }
    } catch (e) {
      /* not base64 */
    }
    if (/^https?:\/\//i.test(startParam)) {
      return startParam;
    }
    return null;
  }

  function buildWidgetSrc(trackUrl) {
    const params = new URLSearchParams({
      url: trackUrl,
      auto_play: "true",
      visual: "true",
      hide_related: "true",
      show_comments: "false",
      show_user: "true",
      show_reposts: "false",
      show_teaser: "false",
      buying: "false",
      sharing: "false",
      download: "false",
      color: "ff5500",
    });
    return `https://w.soundcloud.com/player/?${params.toString()}`;
  }

  let widget = null;
  let isPlaying = false;

  /** Очередь при воспроизведении из плейлиста: листать треки кнопками вместо ±15 с. */
  let playlistQueue = null;
  let lastTrackLoadAt = 0;
  let lastLoadedTrackUrl = "";
  let nowPlaying = { url: "", title: "", artist: "", thumbnail: null };

  function setPlayBtn(playing) {
    isPlaying = playing;
    playBtn.textContent = playing ? "❚❚" : "▶";
  }

  function attachWidget() {
    widget = SC.Widget(iframe);
    widget.bind(SC.Widget.Events.READY, () => {
      widget.getCurrentSound((sound) => {
        if (sound) updateMeta(sound);
      });
      widget.bind(SC.Widget.Events.PLAY, () => setPlayBtn(true));
      widget.bind(SC.Widget.Events.PAUSE, () => setPlayBtn(false));
      widget.bind(SC.Widget.Events.FINISH, () => {
        setPlayBtn(false);
        if (Date.now() - lastTrackLoadAt < 500) return;
        const pl = playlistQueue;
        if (!pl || pl.urls.length < 2 || pl.index >= pl.urls.length - 1) {
          return;
        }
        const j = pl.index + 1;
        loadTrack(pl.urls[j], {
          playlist: { plId: pl.plId, urls: pl.urls, index: j },
        });
        if (currentPlId === pl.plId && !plDetail.hidden) {
          highlightPlRow(j);
        }
      });
      widget.bind(SC.Widget.Events.PLAY_PROGRESS, () => {
        if (!isPlaying) setPlayBtn(true);
      });
    });
  }

  function updatePlaylistNavLabels() {
    const pl = playlistQueue;
    const multi = pl && pl.urls.length > 1;
    if (multi) {
      prevBtn.textContent = "‹ трек";
      nextBtn.textContent = "трек ›";
      prevBtn.title = "Предыдущий трек в плейлисте (на первом — −15 с)";
      nextBtn.title = "Следующий трек в плейлисте (на последнем — +15 с)";
    } else {
      prevBtn.textContent = "«15";
      nextBtn.textContent = "15»";
      prevBtn.title = "−15 секунд";
      nextBtn.title = "+15 секунд";
    }
  }

  function highlightPlRow(index) {
    const rows = plTracks.querySelectorAll(".pl-tracks__row");
    if (index < 0) {
      rows.forEach((row) => row.classList.remove("pl-tracks__row--current"));
      return;
    }
    rows.forEach((row, i) => {
      row.classList.toggle("pl-tracks__row--current", i === index);
    });
  }

  function setNowPlaying(p) {
    nowPlaying = {
      url: p.url != null ? p.url : nowPlaying.url,
      title: p.title != null ? p.title : nowPlaying.title,
      artist: p.artist != null ? p.artist : nowPlaying.artist,
      thumbnail: p.thumbnail !== undefined ? p.thumbnail : nowPlaying.thumbnail,
    };
    updatePlayerArtwork(nowPlaying.thumbnail);
  }

  function updateMeta(sound) {
    if (!sound) return;
    metaTitle.textContent = sound.title || "Без названия";
    metaArtist.textContent = (sound.user && sound.user.username) || "";
    const u = sound.permalink_url || lastLoadedTrackUrl;
    const art =
      sound.artwork_url || (sound.user && sound.user.avatar_url) || null;
    setNowPlaying({
      url: u,
      title: sound.title || "Без названия",
      artist: (sound.user && sound.user.username) || "",
      thumbnail: art,
    });
    void syncPlayerPlaylistRow();
  }

  async function syncPlayerPlaylistRow() {
    if (!playerPlRow) return;
    if (!getInitData() || !nowPlaying.url || !nowPlaying.url.startsWith("http")) {
      playerPlRow.classList.add("hidden");
      return;
    }
    const res = await apiGet(
      "/api/playlists/track_status?url=" + encodeURIComponent(nowPlaying.url)
    );
    if (!res.ok) {
      playerPlRow.classList.add("hidden");
      return;
    }
    const st = await res.json();
    playerPlRow.classList.remove("hidden");
    if (playerPlHint) playerPlHint.classList.add("hidden");
    if (playerPlHintNo) playerPlHintNo.classList.add("hidden");
    if (playerPlAdd) playerPlAdd.classList.remove("hidden");
    if (playerPlPickSlot) playerPlPickSlot.innerHTML = "";
    if (st.playlists_total === 0) {
      if (playerPlAdd) playerPlAdd.classList.add("hidden");
      if (playerPlHintNo) {
        playerPlHintNo.classList.remove("hidden");
        playerPlHintNo.textContent =
          "Создай плейлист во вкладке «Плейлисты».";
      }
      return;
    }
    if (st.in_all) {
      if (playerPlAdd) playerPlAdd.classList.add("hidden");
      if (playerPlHint) {
        playerPlHint.classList.remove("hidden");
        playerPlHint.textContent = "Трек уже во всех плейлистах";
      }
      return;
    }
    if (playerPlAdd) {
      playerPlAdd.textContent = "В плейлист…";
    }
  }

  function showPlayerView() {
    empty.classList.add("hidden");
    resultsBox.classList.add("hidden");
    playerWrap.classList.remove("hidden");
  }

  function showEmptyView() {
    empty.classList.remove("hidden");
    resultsBox.classList.add("hidden");
    playerWrap.classList.add("hidden");
  }

  function showResultsView() {
    empty.classList.add("hidden");
    resultsBox.classList.remove("hidden");
    playerWrap.classList.add("hidden");
  }

  function showSearchTab() {
    panelPl.classList.add("tab-panel--hidden");
    panelPl.setAttribute("hidden", "");
    panelSearch.classList.remove("tab-panel--hidden");
    panelSearch.removeAttribute("hidden");
    tabSearchBtn.classList.add("tab--active");
    tabPlBtn.classList.remove("tab--active");
  }

  function showPlTab() {
    panelSearch.classList.add("tab-panel--hidden");
    panelSearch.setAttribute("hidden", "");
    panelPl.classList.remove("tab-panel--hidden");
    panelPl.removeAttribute("hidden");
    tabPlBtn.classList.add("tab--active");
    tabSearchBtn.classList.remove("tab--active");
    void refreshPlList();
  }

  /**
   * @param {string} rawUrl
   * @param {{ playlist: { plId: number, urls: string[], index: number } }} [opts] — соседние кнопки = треки плейлиста
   */
  function loadTrack(rawUrl, opts) {
    const match = SC_URL_RE.exec((rawUrl || "").trim());
    if (!match) return false;
    const trackUrl = match[0];
    lastTrackLoadAt = Date.now();
    lastLoadedTrackUrl = trackUrl;
    setNowPlaying({
      url: trackUrl,
      title: "Загружаю…",
      artist: "",
      thumbnail:
        opts && opts.thumbnail !== undefined ? opts.thumbnail : null,
    });
    void syncPlayerPlaylistRow();

    if (opts && opts.playlist) {
      playlistQueue = {
        plId: opts.playlist.plId,
        urls: opts.playlist.urls,
        index: opts.playlist.index
      };
    } else {
      playlistQueue = null;
    }
    updatePlaylistNavLabels();

    metaTitle.textContent = "Загружаю…";
    metaArtist.textContent = "";

    if (widget) {
      widget.load(trackUrl, {
        auto_play: true,
        visual: true,
        hide_related: true,
        show_comments: false,
        show_reposts: false,
        show_teaser: false,
        sharing: false,
        download: false,
        buying: false,
        color: "ff5500",
        callback: () => {
          widget.getCurrentSound((sound) => sound && updateMeta(sound));
        },
      });
    } else {
      iframe.src = buildWidgetSrc(trackUrl);
      iframe.addEventListener("load", attachWidget, { once: true });
    }

    showPlayerView();
    if (tg && typeof tg.enableClosingConfirmation === "function") {
      try {
        tg.enableClosingConfirmation(true);
      } catch (e) {
        /* older clients */
      }
    }
    return true;
  }

  function formatDuration(seconds) {
    const total = Math.floor(Number(seconds) || 0);
    if (total <= 0) return "";
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${m}:${String(s).padStart(2, "0")}`;
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function thumbStyleUrl(u) {
    if (!u || typeof u !== "string") return "";
    let s = u.trim();
    if (s.startsWith("//")) s = "https:" + s;
    if (s.startsWith("http://") && s.indexOf("sndcdn.com") !== -1) {
      s = "https://" + s.slice(7);
    }
    return s;
  }

  function updatePlayerArtwork(url) {
    const img = document.getElementById("playerArt");
    const ph = document.getElementById("playerArtPh");
    if (!img || !ph) return;
    const u = thumbStyleUrl(url);
    if (u) {
      img.src = u;
      img.alt = "";
      img.classList.remove("player__art--hidden");
      ph.classList.add("player__art--hidden");
    } else {
      img.removeAttribute("src");
      img.classList.add("player__art--hidden");
      ph.classList.remove("player__art--hidden");
    }
  }

  function renderResultsStatus(text) {
    resultsBox.innerHTML = `<div class="results__status">${escapeHtml(text)}</div>`;
    showResultsView();
  }

  let plCache = null;
  let plListRefreshGen = 0;

  async function fetchPlSummaries() {
    if (!getInitData()) return [];
    const res = await apiGet("/api/playlists");
    if (res.status === 401) return [];
    if (!res.ok) return [];
    return res.json();
  }

  function renderResults(items) {
    if (!items || !items.length) {
      renderResultsStatus("Ничего не нашёл. Попробуй переформулировать запрос.");
      return;
    }
    const frag = document.createDocumentFragment();
    items.forEach((it) => {
      const wrap = document.createElement("div");
      wrap.className = "result-wrap";
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "result";
      btn.dataset.url = it.url;
      const cover = document.createElement("div");
      cover.className = "result__cover";
      if (it.thumbnail) {
        cover.style.backgroundImage = `url("${it.thumbnail.replace(/"/g, '\\"')}")`;
      }
      const body = document.createElement("div");
      body.className = "result__body";
      body.innerHTML = `
        <div class="result__title">${escapeHtml(it.title || "Без названия")}</div>
        <div class="result__artist">${escapeHtml(it.artist || "")}</div>
      `;
      const dur = document.createElement("div");
      dur.className = "result__duration";
      const sec = it.duration
        ? typeof it.duration === "number" && it.duration > 1000
          ? it.duration / 1000
          : it.duration
        : 0;
      dur.textContent = formatDuration(sec);
      btn.appendChild(cover);
      btn.appendChild(body);
      btn.appendChild(dur);
      btn.addEventListener("click", () => loadTrack(it.url, { thumbnail: it.thumbnail }));
      wrap.appendChild(btn);

      if (getInitData()) {
        const plRow = document.createElement("div");
        plRow.className = "result__plrow";
        const addBtn = document.createElement("button");
        addBtn.type = "button";
        addBtn.className = "result__pladd";
        addBtn.textContent = "В плейлист…";
        addBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          void openPlPickerForItem(it, plRow, addBtn);
        });
        plRow.appendChild(addBtn);
        wrap.appendChild(plRow);
      }

      frag.appendChild(wrap);
    });
    resultsBox.innerHTML = "";
    resultsBox.appendChild(frag);
    showResultsView();
  }

  async function openPlPickerForItem(item, rowEl, addBtn) {
    if (!getInitData()) return;
    const pickParent = rowEl.querySelector(".player__plpick") || rowEl;
    addBtn.disabled = true;
    pickParent.querySelectorAll(".pl-pick").forEach((n) => n.remove());
    if (plCache === null) {
      plCache = await fetchPlSummaries();
    }
    if (!plCache || !plCache.length) {
      const tip = document.createElement("div");
      tip.className = "pl-pick pl-hint";
      tip.style.margin = "0";
      tip.style.fontSize = "12px";
      tip.textContent = "Сначала создай плейлист во вкладке «Плейлисты».";
      pickParent.appendChild(tip);
      addBtn.disabled = false;
      return;
    }
    plCache.forEach((pl) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "result__pladd pl-pick";
      b.textContent = pl.name;
      b.addEventListener("click", async (e) => {
        e.stopPropagation();
        const res = await apiJson("POST", `/api/playlists/${pl.id}/tracks`, {
          url: item.url,
          title: item.title,
          artist: item.artist,
          thumbnail: item.thumbnail || undefined,
        });
        pickParent.querySelectorAll(".pl-pick").forEach((n) => n.remove());
        if (res.ok) {
          addBtn.textContent = "✓ " + pl.name;
          plCache = null;
          void syncPlayerPlaylistRow();
          void refreshPlList();
          if (currentPlId === pl.id) {
            void openPlDetail(pl.id);
          }
        } else {
          const data = await res.json().catch(() => ({}));
          addBtn.textContent = (data && data.error) || "Ошибка";
        }
        addBtn.disabled = false;
        setTimeout(() => {
          addBtn.textContent = "В плейлист…";
        }, 2000);
      });
      pickParent.appendChild(b);
    });
    addBtn.disabled = false;
  }

  let currentPlId = null;

  async function moveTrackInPlaylist(plId, fromIdx, delta) {
    const rows = [...plTracks.querySelectorAll(".pl-tracks__row")];
    const to = fromIdx + delta;
    if (to < 0 || to >= rows.length) return;
    const ids = rows.map((r) => +r.dataset.trackId);
    const tmp = ids[fromIdx];
    ids[fromIdx] = ids[to];
    ids[to] = tmp;
    const res = await apiJson("PUT", `/api/playlists/${plId}/tracks/reorder`, {
      order: ids,
    });
    if (res.ok) {
      void openPlDetail(plId);
    } else {
      const d = await res.json().catch(() => ({}));
      window.alert((d && d.error) || "Не удалось изменить порядок");
    }
  }

  const plNoAuthDefaultText =
    "Открой мини-апп из Telegram (кнопка «SoundCloud» в боте) — " +
    "тогда плейлисты будут привязаны к твоему аккаунту.";

  async function refreshPlList() {
    const gen = ++plListRefreshGen;
    if (!getInitData()) {
      plNoAuth.textContent = plNoAuthDefaultText;
      plNoAuth.hidden = false;
      plBox.hidden = true;
      return;
    }
    plNoAuth.textContent = plNoAuthDefaultText;
    plNoAuth.hidden = true;
    plBox.hidden = false;
    plList.innerHTML = "";
    const res = await apiGet("/api/playlists");
    if (gen !== plListRefreshGen) return;
    if (res.status === 401) {
      plNoAuth.textContent =
        "Сервер не подтвердил сессию Telegram. В деплое мини-аппа " +
        "нужен тот же бот-токен, что у бота (TELEGRAM_API_KEY / BOT_TOKEN), " +
        "и общая с ботом база (DATABASE_URL).";
      plNoAuth.hidden = false;
      plBox.hidden = true;
      return;
    }
    if (!res.ok) {
      plList.innerHTML = `<li class="pl-hint">Не удалось загрузить</li>`;
      plEmpty.hidden = true;
      return;
    }
    if (gen !== plListRefreshGen) return;
    plCache = await res.json();
    if (gen !== plListRefreshGen) return;
    if (!plCache.length) {
      plEmpty.hidden = false;
      return;
    }
    plEmpty.hidden = true;
    plCache.forEach((p) => {
      const li = document.createElement("li");
      const b = document.createElement("button");
      b.type = "button";
      b.className = "pl-list__item";
      b.innerHTML = `<span class="pl-list__name">${escapeHtml(p.name)}</span>
        <span class="pl-list__meta">${p.track_count} тр.</span>`;
      b.addEventListener("click", () => void openPlDetail(p.id));
      li.appendChild(b);
      plList.appendChild(li);
    });
  }

  async function openPlDetail(id, options) {
    if (playlistQueue && playlistQueue.plId !== id) {
      playlistQueue = null;
      updatePlaylistNavLabels();
    }

    const res = await apiGet(`/api/playlists/${id}`);
    if (!res.ok) return;
    const data = await res.json();
    currentPlId = data.id;
    plDetailTitle.textContent = data.name;
    const tracks = data.tracks || [];
    const urls = tracks.map((t) => t.url);

    if (playlistQueue && playlistQueue.plId === id) {
      const cur = playlistQueue.urls[playlistQueue.index];
      const ni = cur != null ? urls.indexOf(cur) : -1;
      if (ni >= 0) {
        playlistQueue = { plId: id, urls, index: ni };
      } else if (urls.length) {
        playlistQueue = { plId: id, urls, index: 0 };
      } else {
        playlistQueue = null;
        updatePlaylistNavLabels();
      }
    }

    plTracks.innerHTML = "";
    tracks.forEach((t, idx) => {
      const li = document.createElement("li");
      li.className = "pl-tracks__row";
      li.dataset.trackId = String(t.id);
      const lab = (t.title || "—") + (t.artist ? " — " + t.artist : "");

      const playFromRow = () => {
        const ok = loadTrack(t.url, {
          playlist: { plId: id, urls, index: idx },
          thumbnail: t.thumbnail || undefined,
        });
        if (!ok) return;
        highlightPlRow(idx);
        requestAnimationFrame(() => {
          try {
            playerWrap.scrollIntoView({ behavior: "smooth", block: "nearest" });
          } catch (e) {
            /* */
          }
        });
      };

      const thumb = document.createElement("button");
      thumb.type = "button";
      thumb.className = "pl-tracks__thumb";
      thumb.setAttribute("aria-label", "Обложка, включить: " + lab);
      const tu = thumbStyleUrl(t.thumbnail);
      if (tu) {
        thumb.style.backgroundImage = `url("${tu.replace(/"/g, '\\"')}")`;
      }
      thumb.addEventListener("click", (e) => {
        e.stopPropagation();
        playFromRow();
      });

      const playIco = document.createElement("button");
      playIco.type = "button";
      playIco.className = "pl-tracks__playico";
      playIco.setAttribute("aria-label", "Включить");
      playIco.textContent = "▶";
      playIco.addEventListener("click", (e) => {
        e.stopPropagation();
        playFromRow();
      });

      const textBtn = document.createElement("button");
      textBtn.type = "button";
      textBtn.className = "pl-tracks__main";
      textBtn.setAttribute("aria-label", "Включить: " + lab);
      const tTitle = document.createElement("div");
      tTitle.className = "pl-tracks__title";
      tTitle.textContent = t.title || "—";
      const tArt = document.createElement("div");
      tArt.className = "pl-tracks__artist";
      tArt.textContent = t.artist || "";
      textBtn.appendChild(tTitle);
      textBtn.appendChild(tArt);
      textBtn.addEventListener("click", playFromRow);

      const moves = document.createElement("div");
      moves.className = "pl-tracks__moves";
      const up = document.createElement("button");
      up.type = "button";
      up.className = "pl-tracks__move";
      up.setAttribute("aria-label", "Выше");
      up.textContent = "↑";
      up.disabled = idx === 0;
      const down = document.createElement("button");
      down.type = "button";
      down.className = "pl-tracks__move";
      down.setAttribute("aria-label", "Ниже");
      down.textContent = "↓";
      down.disabled = idx === tracks.length - 1;
      up.addEventListener("click", (e) => {
        e.stopPropagation();
        void moveTrackInPlaylist(id, idx, -1);
      });
      down.addEventListener("click", (e) => {
        e.stopPropagation();
        void moveTrackInPlaylist(id, idx, 1);
      });
      moves.appendChild(up);
      moves.appendChild(down);

      const delB = document.createElement("button");
      delB.type = "button";
      delB.className = "pl-tracks__del";
      delB.setAttribute("aria-label", "Удалить трек");
      delB.textContent = "✕";
      delB.addEventListener("click", async (e) => {
        e.stopPropagation();
        const d = await apiJson("DELETE", `/api/playlists/${id}/tracks/${t.id}`);
        if (d.ok) void openPlDetail(id);
      });
      li.appendChild(thumb);
      li.appendChild(playIco);
      li.appendChild(textBtn);
      li.appendChild(moves);
      li.appendChild(delB);
      plTracks.appendChild(li);
    });

    if (playlistQueue && playlistQueue.plId === id) {
      highlightPlRow(playlistQueue.index);
    } else {
      highlightPlRow(-1);
    }

    plListView.hidden = true;
    plDetail.hidden = false;

    if (
      options &&
      typeof options.autoPlayIndex === "number" &&
      tracks.length
    ) {
      const idx = Math.min(
        Math.max(0, options.autoPlayIndex),
        tracks.length - 1
      );
      const t0 = tracks[idx];
      const ok = loadTrack(t0.url, {
        playlist: { plId: id, urls, index: idx },
        thumbnail: t0.thumbnail || undefined,
      });
      if (ok) {
        highlightPlRow(idx);
        showPlayerView();
        requestAnimationFrame(() => {
          try {
            playerWrap.scrollIntoView({ behavior: "smooth", block: "nearest" });
          } catch (e) {
            /* */
          }
        });
      }
    }
  }

  plBack.addEventListener("click", () => {
    plDetail.hidden = true;
    plListView.hidden = false;
    currentPlId = null;
    highlightPlRow(-1);
  });

  plDeleteList.addEventListener("click", async () => {
    if (currentPlId == null) return;
    if (!window.confirm("Удалить плейлист целиком?")) return;
    const r = await apiJson("DELETE", `/api/playlists/${currentPlId}`);
    if (r.ok) {
      plBack.click();
      plCache = null;
      void refreshPlList();
    }
  });

  plNewBtn.addEventListener("click", async () => {
    const name = (plNewName.value || "").trim();
    if (name.length < 1) return;
    const r = await apiJson("POST", "/api/playlists", { name });
    if (r.ok) {
      plNewName.value = "";
      plCache = null;
      void refreshPlList();
    } else {
      const d = await r.json().catch(() => ({}));
      window.alert((d && d.error) || "Не удалось создать");
    }
  });

  if (playerPlAdd) {
    playerPlAdd.addEventListener("click", (e) => {
      e.preventDefault();
      void openPlPickerForItem(
        {
          url: nowPlaying.url,
          title: nowPlaying.title,
          artist: nowPlaying.artist,
          thumbnail: nowPlaying.thumbnail,
        },
        playerPlRow,
        playerPlAdd
      );
    });
  }

  tabSearchBtn.addEventListener("click", showSearchTab);
  tabPlBtn.addEventListener("click", showPlTab);

  let searchAbortController = null;
  let searchSeq = 0;

  async function performSearch(query) {
    query = (query || "").trim();
    if (query.length < MIN_QUERY_LENGTH) {
      resultsBox.classList.add("hidden");
      resultsBox.innerHTML = "";
      return;
    }

    const urlMatch = SC_URL_RE.exec(query);
    if (urlMatch) {
      loadTrack(urlMatch[0]);
      return;
    }

    if (searchAbortController) searchAbortController.abort();
    searchAbortController = new AbortController();
    const seq = ++searchSeq;

    renderResultsStatus("Ищу…");
    searchBtn.disabled = true;

    try {
      const res = await fetch(
        `/api/search?q=${encodeURIComponent(query)}&limit=10`,
        { signal: searchAbortController.signal }
      );
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        if (seq === searchSeq) {
          renderResultsStatus(data.error || `Поиск упал (${res.status})`);
        }
        return;
      }
      const data = await res.json();
      if (seq === searchSeq) renderResults(data.results || []);
    } catch (e) {
      if (e.name === "AbortError") return;
      if (seq === searchSeq) renderResultsStatus("Сеть недоступна. Попробуй ещё раз.");
    } finally {
      if (seq === searchSeq) searchBtn.disabled = false;
    }
  }

  let debounceTimer = null;
  searchInput.addEventListener("input", () => {
    clearTimeout(debounceTimer);
    const q = searchInput.value;
    debounceTimer = setTimeout(() => performSearch(q), SEARCH_DEBOUNCE_MS);
  });
  searchInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      clearTimeout(debounceTimer);
      performSearch(searchInput.value);
    }
  });
  searchBtn.addEventListener("click", () => {
    clearTimeout(debounceTimer);
    performSearch(searchInput.value);
  });

  playBtn.addEventListener("click", () => {
    if (!widget) return;
    widget.toggle();
  });

  function loadPlaylistStep(delta) {
    const pl = playlistQueue;
    if (!pl || pl.urls.length < 2) return false;
    const j = pl.index + delta;
    if (j < 0 || j >= pl.urls.length) return false;
    const url = pl.urls[j];
    if (
      !loadTrack(url, {
        playlist: { plId: pl.plId, urls: pl.urls, index: j },
      })
    ) {
      return false;
    }
    if (currentPlId === pl.plId && !plDetail.hidden) {
      highlightPlRow(j);
    }
    requestAnimationFrame(() => {
      try {
        playerWrap.scrollIntoView({ behavior: "smooth", block: "nearest" });
      } catch (e) {
        /* */
      }
    });
    return true;
  }

  prevBtn.addEventListener("click", () => {
    if (!widget) return;
    const pl = playlistQueue;
    if (pl && pl.urls.length > 1 && pl.index > 0) {
      if (loadPlaylistStep(-1)) return;
    }
    widget.getPosition((pos) => widget.seekTo(Math.max(0, pos - 15000)));
  });

  nextBtn.addEventListener("click", () => {
    if (!widget) return;
    const pl = playlistQueue;
    if (pl && pl.urls.length > 1 && pl.index < pl.urls.length - 1) {
      if (loadPlaylistStep(1)) return;
    }
    widget.getPosition((pos) =>
      widget.getDuration((dur) =>
        widget.seekTo(Math.min(dur || pos + 15000, pos + 15000))
      )
    );
  });

  closeBtn.addEventListener("click", () => {
    if (tg && tg.close) tg.close();
    else window.close();
  });

  async function boot() {
    const plId = readInitialPlId();
    if (plId) {
      showPlTab();
      await refreshPlList();
      await openPlDetail(plId, { autoPlayIndex: 0 });
      return;
    }
    const initialTrack = readInitialTrack();
    if (initialTrack) {
      loadTrack(initialTrack);
    } else {
      showEmptyView();
    }
  }
  void boot();
})();
