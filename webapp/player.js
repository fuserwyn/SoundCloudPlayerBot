(() => {
  const tg = window.Telegram && window.Telegram.WebApp;

  /** Кнопка трека в плейлисте: ?compact=1 — без вкладок/поиска, виджет компактный; expand() всё равно вызываем. */
  const startParamsEarly = new URLSearchParams(window.location.search);
  const startCompact = startParamsEarly.get("compact") === "1";
  if (startCompact) {
    document.documentElement.classList.add("app--compact");
  }

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
    /* expand() всегда: иначе мини-апп остаётся «листом» снизу, сверху пустота. */
    if (typeof tg.expand === "function") {
      try {
        tg.expand();
      } catch (e) {
        /* */
      }
    }
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

  /** С кнопки меню / при первом кадре initData иногда пустой — ждём, иначе плейлисты 401. */
  function waitForInitData(maxMs) {
    return new Promise((resolve) => {
      if (getInitData()) {
        resolve(true);
        return;
      }
      const t0 = Date.now();
      const id = setInterval(() => {
        if (getInitData()) {
          clearInterval(id);
          resolve(true);
          return;
        }
        if (Date.now() - t0 >= maxMs) {
          clearInterval(id);
          resolve(false);
        }
      }, 100);
    });
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

  let I18N = null;

  function t(key) {
    return (I18N && I18N[key]) || key;
  }

  async function loadLocale() {
    try {
      const r = await fetch("/api/locale", { headers: apiHeaders() });
      if (!r.ok) return;
      const d = await r.json();
      if (d && d.ui) {
        I18N = d.ui;
        document.documentElement.setAttribute(
          "lang",
          d.lang === "en" ? "en" : "ru"
        );
        applyLocale();
      }
    } catch (e) {
      /* offline or old server */
    }
  }

  function applyLocale() {
    if (!I18N) return;
    const setText = (id, key) => {
      const el = document.getElementById(id);
      if (el) el.textContent = t(key);
    };
    const setPh = (id, key) => {
      const el = document.getElementById(id);
      if (el) el.placeholder = t(key);
    };
    const setAria = (id, key) => {
      const el = document.getElementById(id);
      if (el) el.setAttribute("aria-label", t(key));
    };
    setText("brandTagline", "webapp_brand_subtitle");
    setAria("closeBtn", "webapp_close");
    setText("tabSearchBtn", "webapp_tab_search");
    setText("tabPlBtn", "webapp_tab_playlists");
    setAria("mainNav", "webapp_nav_sections");
    setPh("searchInput", "webapp_search_placeholder");
    setAria("searchBtn", "webapp_search_btn");
    const sh = document.getElementById("searchHint");
    if (sh) sh.textContent = t("webapp_search_hint");
    setText("emptyTitle", "webapp_empty_title");
    setText("emptySub", "webapp_empty_sub");
    setPh("plNewName", "webapp_pl_name_placeholder");
    setText("plNewBtn", "webapp_pl_create");
    setAria("plList", "webapp_pl_list_a11y");
    setText("plEmpty", "webapp_pl_empty");
    setAria("plBack", "webapp_pl_back");
    setAria("plDeleteList", "webapp_pl_delete_aria");
    const pld = document.getElementById("plDeleteList");
    if (pld) pld.setAttribute("title", t("webapp_pl_delete_title"));
    setAria("playerWrap", "webapp_player_a11y");
    setText("metaTitle", "webapp_loading");
    setText("hintFooter", "webapp_footer");
    if (playBtn) setAria("playBtn", "webapp_aria_play_pause");
    const ifr = document.getElementById("scPlayer");
    if (ifr) ifr.setAttribute("title", "SoundCloud");
    updatePlaylistNavLabels();
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

  function buildWidgetSrc(trackUrl, showVisual) {
    if (showVisual === undefined) {
      showVisual = true;
    }
    const params = new URLSearchParams({
      url: trackUrl,
      auto_play: "true",
      visual: showVisual ? "true" : "false",
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
      prevBtn.textContent = t("webapp_nav_prev_pl");
      nextBtn.textContent = t("webapp_nav_next_pl");
      prevBtn.title = t("webapp_tip_prev_pl");
      nextBtn.title = t("webapp_tip_next_pl");
    } else {
      prevBtn.textContent = t("webapp_btn_prev");
      nextBtn.textContent = t("webapp_btn_next");
      prevBtn.title = t("webapp_tip_seek_m15");
      nextBtn.title = t("webapp_tip_seek_p15");
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
    const title = sound.title || t("no_title");
    metaTitle.textContent = title;
    metaArtist.textContent = (sound.user && sound.user.username) || "";
    const u = sound.permalink_url || lastLoadedTrackUrl;
    const art =
      sound.artwork_url || (sound.user && sound.user.avatar_url) || null;
    setNowPlaying({
      url: u,
      title,
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
        playerPlHintNo.textContent = t("webapp_pl_pick_first");
      }
      return;
    }
    if (st.in_all) {
      if (playerPlAdd) playerPlAdd.classList.add("hidden");
      if (playerPlHint) {
        playerPlHint.classList.remove("hidden");
        playerPlHint.textContent = t("webapp_in_all_pl");
      }
      return;
    }
    if (playerPlAdd) {
      playerPlAdd.textContent = t("webapp_add_pl");
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
   * @param {{
   *   playlist?: { plId: number, urls: string[], index: number },
   *   thumbnail?: string | null,
   *   compact?: boolean,
   * }} [opts]
   */
  function loadTrack(rawUrl, opts) {
    const match = SC_URL_RE.exec((rawUrl || "").trim());
    if (!match) return false;
    const trackUrl = match[0];
    const useCompact =
      opts && Object.prototype.hasOwnProperty.call(opts, "compact")
        ? opts.compact
        : startCompact;
    lastTrackLoadAt = Date.now();
    lastLoadedTrackUrl = trackUrl;
    setNowPlaying({
      url: trackUrl,
      title: t("webapp_loading"),
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

    metaTitle.textContent = t("webapp_loading");
    metaArtist.textContent = "";

    if (widget) {
      widget.load(trackUrl, {
        auto_play: true,
        visual: !useCompact,
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
      iframe.src = buildWidgetSrc(trackUrl, !useCompact);
      iframe.addEventListener("load", attachWidget, { once: true });
    }

    showPlayerView();
    if (useCompact) {
      document.documentElement.classList.add("app--compact");
    }
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
    resultsBox.className = "results";
    resultsBox.innerHTML = `<div class="results__status">${escapeHtml(text)}</div>`;
    showResultsView();
  }

  let plCache = null;
  let plListRefreshGen = 0;
  let tmaVersion = 0;
  let tmaPollId = null;
  let tmaRemoteStarted = false;

  async function fetchPlSummaries() {
    if (!getInitData()) return [];
    const res = await apiGet("/api/playlists");
    if (res.status === 401) return [];
    if (!res.ok) return [];
    return res.json();
  }

  function renderResults(items) {
    if (!items || !items.length) {
      renderResultsStatus(t("webapp_no_results"));
      return;
    }
    const head = document.createElement("h2");
    head.className = "results__head";
    head.textContent = t("webapp_results");

    const scroll = document.createElement("div");
    scroll.className = "results__scroll";
    scroll.setAttribute("role", "list");

    items.forEach((it) => {
      const wrap = document.createElement("div");
      wrap.className = "result-wrap";
      wrap.setAttribute("role", "listitem");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "result result--sc-card";
      btn.dataset.url = it.url;
      const cover = document.createElement("div");
      cover.className = "result__cover";
      if (it.thumbnail) {
        cover.style.backgroundImage = `url("${it.thumbnail.replace(/"/g, '\\"')}")`;
      }
      const body = document.createElement("div");
      body.className = "result__body";
      const sec = it.duration
        ? typeof it.duration === "number" && it.duration > 1000
          ? it.duration / 1000
          : it.duration
        : 0;
      const durStr = formatDuration(sec);
      body.innerHTML = `
        <div class="result__title">${escapeHtml(it.title || t("no_title"))}</div>
        <div class="result__artist">${escapeHtml(it.artist || "")}</div>
        ${durStr ? `<div class="result__duration">${escapeHtml(durStr)}</div>` : ""}
      `;
      btn.appendChild(cover);
      btn.appendChild(body);
      btn.addEventListener("click", () => loadTrack(it.url, { thumbnail: it.thumbnail }));
      wrap.appendChild(btn);

      if (getInitData()) {
        const plRow = document.createElement("div");
        plRow.className = "result__plrow";
        const addBtn = document.createElement("button");
        addBtn.type = "button";
        addBtn.className = "result__pladd";
        addBtn.textContent = t("webapp_add_pl");
        addBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          void openPlPickerForItem(it, plRow, addBtn);
        });
        plRow.appendChild(addBtn);
        wrap.appendChild(plRow);
      }

      scroll.appendChild(wrap);
    });
    resultsBox.className = "results results--sc";
    resultsBox.innerHTML = "";
    resultsBox.appendChild(head);
    resultsBox.appendChild(scroll);
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
      tip.textContent = t("webapp_pl_pick_first");
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
          addBtn.textContent = (data && data.error) || t("webapp_err_short");
        }
        addBtn.disabled = false;
        setTimeout(() => {
          addBtn.textContent = t("webapp_add_pl");
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
      window.alert((d && d.error) || t("webapp_reorder_fail"));
    }
  }

  async function refreshPlList() {
    const gen = ++plListRefreshGen;
    if (!getInitData()) {
      plNoAuth.textContent = t("webapp_pl_open_tg");
      plNoAuth.hidden = false;
      plBox.hidden = true;
      return;
    }
    plNoAuth.textContent = t("webapp_pl_open_tg");
    plNoAuth.hidden = true;
    plBox.hidden = false;
    plList.innerHTML = "";
    const res = await apiGet("/api/playlists");
    if (gen !== plListRefreshGen) return;
    if (res.status === 401) {
      plNoAuth.textContent = t("webapp_pl_auth_err");
      plNoAuth.hidden = false;
      plBox.hidden = true;
      return;
    }
    if (!res.ok) {
      plList.innerHTML = `<li class="pl-hint">${escapeHtml(
        t("webapp_pl_load_list_fail")
      )}</li>`;
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
        <span class="pl-list__meta">${escapeHtml(
          String(p.track_count)
        )} ${escapeHtml(t("webapp_pl_n_tr"))}</span>`;
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
      thumb.setAttribute("aria-label", t("webapp_aria_play_cover") + lab);
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
      playIco.setAttribute("aria-label", t("webapp_aria_enable_short"));
      playIco.textContent = "▶";
      playIco.addEventListener("click", (e) => {
        e.stopPropagation();
        playFromRow();
      });

      const textBtn = document.createElement("button");
      textBtn.type = "button";
      textBtn.className = "pl-tracks__main";
      textBtn.setAttribute("aria-label", t("webapp_aria_row_play") + lab);
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
      up.setAttribute("aria-label", t("webapp_aria_up"));
      up.textContent = "↑";
      up.disabled = idx === 0;
      const down = document.createElement("button");
      down.type = "button";
      down.className = "pl-tracks__move";
      down.setAttribute("aria-label", t("webapp_aria_down"));
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
      delB.setAttribute("aria-label", t("webapp_aria_delete_track"));
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
    if (!window.confirm(t("webapp_pl_del_confirm"))) return;
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
      window.alert((d && d.error) || t("webapp_pl_create_fail"));
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

    renderResultsStatus(t("webapp_searching"));
    searchBtn.disabled = true;

    try {
      const res = await fetch(
        `/api/search?q=${encodeURIComponent(query)}&limit=10`,
        { signal: searchAbortController.signal }
      );
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        if (seq === searchSeq) {
          renderResultsStatus(
            data.error || `${t("webapp_search_err")} (${res.status})`
          );
        }
        return;
      }
      const data = await res.json();
      if (seq === searchSeq) renderResults(data.results || []);
    } catch (e) {
      if (e.name === "AbortError") return;
      if (seq === searchSeq) renderResultsStatus(t("webapp_network_fail"));
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

  async function tmaApplyPlay(play) {
    if (!play || !play.url) return;
    const plId = play.playlist_id;
    const idx0 = play.track_index != null ? +play.track_index : 0;
    const th = play.thumbnail || null;
    if (plId != null && plId !== "") {
      const r = await apiGet("/api/playlists/" + plId);
      if (r.ok) {
        const data = await r.json();
        const tr = data.tracks || [];
        const urls = tr.map((t) => t.url);
        if (!urls.length) {
          loadTrack(play.url, {
            thumbnail: th || undefined,
            compact: startCompact
          });
          showPlayerView();
          return;
        }
        const idx = Math.min(Math.max(0, idx0), urls.length - 1);
        const trow = tr[idx];
        const thumb = th || (trow && trow.thumbnail) || undefined;
        showPlTab();
        loadTrack(urls[idx], {
          playlist: { plId: +plId, urls, index: idx },
          thumbnail: thumb,
          compact: startCompact
        });
        showPlayerView();
        void openPlDetail(+plId);
        return;
      }
    }
    loadTrack(play.url, { thumbnail: th || undefined, compact: startCompact });
    showPlayerView();
  }

  async function tmaPollOnce() {
    if (!getInitData()) return;
    try {
      const r = await fetch(
        "/api/tma/poll?since=" + encodeURIComponent(String(tmaVersion)),
        { headers: apiHeaders() }
      );
      if (!r.ok) return;
      const d = await r.json();
      const v = parseInt(d.v, 10) || 0;
      if (d.has_update && d.play) {
        tmaVersion = v;
        await tmaApplyPlay(d.play);
      } else {
        tmaVersion = v;
      }
    } catch (e) {
      /* */
    }
  }

  function startTmaRemotePoll() {
    if (tmaPollId != null) return;
    tmaPollId = setInterval(() => void tmaPollOnce(), 1500);
  }

  function ensureTmaRemote() {
    if (tmaRemoteStarted || !getInitData() || !tg) return;
    tmaRemoteStarted = true;
    startTmaRemotePoll();
  }

  function startInitDataRecovery() {
    if (getInitData() || !tg) return;
    const t0 = Date.now();
    const id = setInterval(() => {
      if (getInitData()) {
        clearInterval(id);
        void (async () => {
          await loadLocale();
          await refreshPlList();
          void syncPlayerPlaylistRow();
        })();
        ensureTmaRemote();
        return;
      }
      if (Date.now() - t0 > 12000) clearInterval(id);
    }, 120);
  }

  async function boot() {
    const plId = readInitialPlId();
    if (plId) {
      showPlTab();
      await waitForInitData(10000);
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

  async function init() {
    await loadLocale();
    await boot();
    ensureTmaRemote();
    startInitDataRecovery();
  }
  void init();
})();
