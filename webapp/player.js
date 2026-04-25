(() => {
  const tg = window.Telegram && window.Telegram.WebApp;
  if (tg) {
    tg.ready();
    tg.expand();
    tg.setHeaderColor && tg.setHeaderColor("secondary_bg_color");
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

  const SC_URL_RE = /https?:\/\/(?:(?:www|m|on)\.)?soundcloud\.com\/[^\s]+/i;
  const SEARCH_DEBOUNCE_MS = 450;
  const MIN_QUERY_LENGTH = 2;

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

  function renderResults(items) {
    if (!items || !items.length) {
      renderResultsStatus("Ничего не нашёл. Попробуй переформулировать запрос.");
      return;
    }
    const frag = document.createDocumentFragment();
    items.forEach((it) => {
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
      dur.textContent = formatDuration((it.duration || 0) / 1000);
      btn.appendChild(cover);
      btn.appendChild(body);
      btn.appendChild(dur);
      btn.addEventListener("click", () => loadTrack(it.url));
      frag.appendChild(btn);
    });
    resultsBox.innerHTML = "";
    resultsBox.appendChild(frag);
    showResultsView();
  }

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
