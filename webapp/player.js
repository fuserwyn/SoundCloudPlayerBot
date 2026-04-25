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
  const urlInput = document.getElementById("urlInput");
  const loadBtn = document.getElementById("loadBtn");
  const metaTitle = document.getElementById("metaTitle");
  const metaArtist = document.getElementById("metaArtist");

  const SC_URL_RE = /https?:\/\/(?:(?:www|m|on)\.)?soundcloud\.com\/[^\s]+/i;

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

  function loadTrack(rawUrl) {
    const match = SC_URL_RE.exec((rawUrl || "").trim());
    if (!match) {
      metaTitle.textContent = "Не похоже на ссылку SoundCloud";
      metaArtist.textContent = "";
      return false;
    }
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

    empty.classList.add("hidden");
    playerWrap.classList.remove("hidden");
    return true;
  }

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

  loadBtn.addEventListener("click", () => loadTrack(urlInput.value));
  urlInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") loadTrack(urlInput.value);
  });

  closeBtn.addEventListener("click", () => {
    if (tg && tg.close) tg.close();
    else window.close();
  });

  const initialTrack = readInitialTrack();
  if (initialTrack) {
    loadTrack(initialTrack);
  } else {
    empty.classList.remove("hidden");
    playerWrap.classList.remove("hidden");
    iframe.src = buildWidgetSrc("https://soundcloud.com/forss/flickermood");
    iframe.addEventListener("load", attachWidget, { once: true });
  }
})();
