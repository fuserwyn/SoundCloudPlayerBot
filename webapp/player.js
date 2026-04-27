(() => {
  const tg = window.Telegram && window.Telegram.WebApp;
  if (tg) {
    tg.ready();
    tg.expand();
    tg.setHeaderColor && tg.setHeaderColor("secondary_bg_color");
  }

  const initData = (tg && tg.initData) || "";

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

  const SC_URL_RE = /https?:\/\/(?:(?:www|m|on)\.)?soundcloud\.com\/[^\s]+/i;
  const SEARCH_DEBOUNCE_MS = 450;
  const MIN_QUERY_LENGTH = 2;

  function apiHeaders(json) {
    const h = {};
    if (initData) h["X-Telegram-Init-Data"] = initData;
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

  function readInitialTrack() {
    const params = new URLSearchParams(location.search);
    const fromQuery = params.get("track");
    if (fromQuery) return decodeURIComponent(fromQuery);

    const startParam =
      tg && tg.initDataUnsafe && tg.initDataUnsafe.start_param;
    if (startParam) {
      try {
        return atob(startParam.replace(/-/g, "+").replace(/_/g, "/"));
      } catch (e) {
        return startParam;
      }
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
      widget.bind(SC.Widget.Events.FINISH, () => setPlayBtn(false));
      widget.bind(SC.Widget.Events.PLAY_PROGRESS, () => {
        if (!isPlaying) setPlayBtn(true);
      });
    });
  }

  function updateMeta(sound) {
    metaTitle.textContent = sound.title || "Без названия";
    metaArtist.textContent = (sound.user && sound.user.username) || "";
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
    refreshPlList();
  }

  function switchToSearchAndPlay(url) {
    showSearchTab();
    loadTrack(url);
  }

  function loadTrack(rawUrl) {
    const match = SC_URL_RE.exec((rawUrl || "").trim());
    if (!match) return false;
    const trackUrl = match[0];
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

  function renderResultsStatus(text) {
    resultsBox.innerHTML = `<div class="results__status">${escapeHtml(text)}</div>`;
    showResultsView();
  }

  let plCache = null;

  async function fetchPlSummaries() {
    if (!initData) return [];
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
      btn.addEventListener("click", () => loadTrack(it.url));
      wrap.appendChild(btn);

      if (initData) {
        const plRow = document.createElement("div");
        plRow.className = "result__plrow";
        const addBtn = document.createElement("button");
        addBtn.type = "button";
        addBtn.className = "result__pladd";
        addBtn.textContent = "В плейлист…";
        addBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          void openPlPicker(it, plRow, addBtn);
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

  async function openPlPicker(it, plRow, addBtn) {
    if (!initData) return;
    addBtn.disabled = true;
    plRow.querySelectorAll(".pl-pick").forEach((n) => n.remove());
    if (plCache === null) {
      plCache = await fetchPlSummaries();
    }
    if (!plCache || !plCache.length) {
      const tip = document.createElement("div");
      tip.className = "pl-pick pl-hint";
      tip.style.margin = "0";
      tip.style.fontSize = "12px";
      tip.textContent = "Сначала создай плейлист во вкладке «Плейлисты».";
      plRow.appendChild(tip);
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
          url: it.url,
          title: it.title,
          artist: it.artist,
        });
        plRow.querySelectorAll(".pl-pick").forEach((n) => n.remove());
        if (res.ok) {
          addBtn.textContent = "✓ " + pl.name;
          plCache = null;
        } else {
          const data = await res.json().catch(() => ({}));
          addBtn.textContent = (data && data.error) || "Ошибка";
        }
        addBtn.disabled = false;
        setTimeout(() => {
          addBtn.textContent = "В плейлист…";
        }, 2000);
      });
      plRow.appendChild(b);
    });
    addBtn.disabled = false;
  }

  let currentPlId = null;

  async function refreshPlList() {
    if (!initData) {
      plNoAuth.hidden = false;
      plBox.hidden = true;
      return;
    }
    plNoAuth.hidden = true;
    plBox.hidden = false;
    plList.innerHTML = "";
    const res = await apiGet("/api/playlists");
    if (res.status === 401) {
      plNoAuth.hidden = false;
      plBox.hidden = true;
      return;
    }
    if (!res.ok) {
      plList.innerHTML = `<li class="pl-hint">Не удалось загрузить</li>`;
      plEmpty.hidden = true;
      return;
    }
    plCache = await res.json();
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

  async function openPlDetail(id) {
    const res = await apiGet(`/api/playlists/${id}`);
    if (!res.ok) return;
    const data = await res.json();
    currentPlId = data.id;
    plDetailTitle.textContent = data.name;
    plTracks.innerHTML = "";
    (data.tracks || []).forEach((t) => {
      const li = document.createElement("li");
      li.className = "pl-tracks__row";
      const lab = (t.title || "—") + (t.artist ? " — " + t.artist : "");
      li.innerHTML = `<span class="pl-tracks__text">${escapeHtml(lab)}</span>`;
      const playB = document.createElement("button");
      playB.type = "button";
      playB.className = "pl-tracks__play";
      playB.textContent = "▶";
      playB.addEventListener("click", () => switchToSearchAndPlay(t.url));
      const delB = document.createElement("button");
      delB.type = "button";
      delB.className = "pl-tracks__del";
      delB.textContent = "✕";
      delB.addEventListener("click", async () => {
        const d = await apiJson("DELETE", `/api/playlists/${id}/tracks/${t.id}`);
        if (d.ok) void openPlDetail(id);
      });
      li.appendChild(playB);
      li.appendChild(delB);
      plTracks.appendChild(li);
    });
    plListView.hidden = true;
    plDetail.hidden = false;
  }

  plBack.addEventListener("click", () => {
    plDetail.hidden = true;
    plListView.hidden = false;
    currentPlId = null;
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

  prevBtn.addEventListener("click", () => {
    if (!widget) return;
    widget.getPosition((pos) => widget.seekTo(Math.max(0, pos - 15000)));
  });

  nextBtn.addEventListener("click", () => {
    if (!widget) return;
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

  const initialTrack = readInitialTrack();
  if (initialTrack) {
    loadTrack(initialTrack);
  } else {
    showEmptyView();
  }
})();
