# SoundCloud Player Bot

Telegram-бот + Mini App для SoundCloud.

- Кидаешь боту ссылку — он скачивает трек через `yt-dlp` и присылает mp3 (192 kbps) с обложкой и метаданными.
- Жмёшь **🎧 Открыть в плеере** — открывается Telegram Mini App с встроенным SoundCloud Widget. Реальный плеер с обложкой, паузой и перемоткой; играет напрямую с soundcloud.com.

## Стек

- Python 3.12, [aiogram 3](https://docs.aiogram.dev/), [`yt-dlp`](https://github.com/yt-dlp/yt-dlp), `ffmpeg`
- Статичный фронтенд: HTML/CSS/JS + [SoundCloud Widget API](https://developers.soundcloud.com/docs/api/html5-widget) + [Telegram WebApp SDK](https://core.telegram.org/bots/webapps)
- Docker для бота, nginx для webapp

## Структура

```
SoundCloudPlayerBot/
├── app/                   # код бота (aiogram)
│   ├── config.py
│   ├── handlers.py
│   ├── main.py
│   └── soundcloud.py
├── webapp/                # Mini App (отдельный сервис на Railway)
│   ├── index.html
│   ├── styles.css
│   ├── player.js
│   ├── Dockerfile         # образ webapp; контекст сборки = корень репо
│   └── railway.json       # builder: Dockerfile.webapp из корня (см. RAILWAY_WEBAPP.txt)
├── Dockerfile             # бот (Python + ffmpeg)
├── Dockerfile.webapp      # Railway: zip с GitHub по RAILWAY_GIT_* (без COPY из context)
├── RAILWAY_WEBAPP.txt     # Root Directory для сервиса webapp на Railway
├── railway.json           # конфиг bot-сервиса для Railway
├── docker-compose.yml     # для локального запуска
├── requirements.txt
└── .env.example
```

## Деплой на Railway (рекомендуется)

В одном Railway-проекте — два сервиса: **bot** и **webapp**, оба из этого же репозитория.

### Шаг 1. Запушь репо на GitHub

```bash
cd SoundCloudPlayerBot
git add .
git commit -m "Initial bot + mini app"
git push
```

Убедись, что `.env` в `.gitignore` (он уже там).

### Шаг 2. Создай проект на Railway

1. Залогинься на [railway.app](https://railway.app), создай новый проект.
2. **Deploy from GitHub repo** → выбери свой репозиторий.
3. Railway создаст первый сервис из корневого `Dockerfile` (это будущий **bot**). Переименуй его в `bot`.

### Шаг 3. Добавь сервис webapp

1. В этом же проекте → **+ New** → **GitHub Repo** → тот же репо.
2. В настройках нового сервиса:
   - **Build**: Dockerfile = **`Dockerfile.webapp`** в корне репо (или Config as Code → **`webapp/railway.json`**).
   - Образ собирается **без** `COPY` из контекста: исходник качается с GitHub по commit (переменные `RAILWAY_GIT_*` от Railway). Root Directory может быть пустым или `webapp` — на такой сборке это не ломает Dockerfile.
   - Деплой должен быть **из GitHub**; для **приватного** репо — добавь `GITHUB_TOKEN` (PAT) в Variables с галочкой **Build Time** (см. `RAILWAY_WEBAPP.txt`).
3. Переименуй сервис в `webapp`.
4. **Settings → Networking → Generate Domain** → получишь URL вида `https://webapp-production-xxxx.up.railway.app`. Скопируй его.

Подробнее: **`RAILWAY_WEBAPP.txt`** в корне репо.

### Шаг 4. Настрой переменные

На сервисе **bot** → **Variables**:

| Переменная        | Значение                                          |
|-------------------|---------------------------------------------------|
| `TELEGRAM_API_KEY`| токен от [@BotFather](https://t.me/BotFather)     |
| `WEBAPP_URL`      | URL из шага 3, например `https://webapp-production-xxxx.up.railway.app` |

Сервис **webapp** дополнительных переменных не требует — `PORT` Railway инжектит сам.

### Шаг 5. Деплой

После добавления переменных Railway передеплоит bot автоматически. В логах увидишь:
```
INFO | app.config | Using WEBAPP_URL from env: https://webapp-production-xxxx.up.railway.app
INFO | scbot      | Bot @Your_Bot started. Polling for updates…
```

Webapp поднимется автоматически после первого деплоя.

### Шаг 6. Проверь

1. В Telegram → `/start` боту → жми **🎧 Открыть плеер** — откроется Mini App
2. Кинь ссылку на трек → получишь mp3 + кнопку плеера

## Локальный запуск (без Railway)

Mini App требует HTTPS, поэтому статику нужно разместить на любом HTTPS-хостинге.

**Самый быстрый вариант — Netlify Drop, без регистрации:**
1. Открой [app.netlify.com/drop](https://app.netlify.com/drop)
2. Перетащи туда папку `webapp/`
3. Скопируй полученный URL вида `https://random-name.netlify.app`

Затем:
```bash
cp .env.example .env
# отредактируй .env: TELEGRAM_API_KEY=..., WEBAPP_URL=https://...netlify.app
docker compose up -d --build
docker compose logs -f bot
```

## Использование

В Telegram:

1. `/start` — приветствие + кнопка плеера.
2. Кинь ссылку, например `https://soundcloud.com/forss/flickermood`.
3. Бот пришлёт mp3 + 2 кнопки: **🎧 Открыть в плеере** (Mini App) и **Открыть на SoundCloud**.
4. Внутри Mini App можно вставить любую другую ссылку и слушать.

## Как это работает

```
   ┌─────────┐    polling    ┌──────────────────┐
   │Telegram │◄──────────────►│   bot (Railway)  │
   └────┬────┘                │   Python+yt-dlp  │
        │ web_app button      └──────────────────┘
        ▼ (HTTPS)
   ┌────────────────────────┐
   │  webapp (Railway)      │  *.up.railway.app
   │  nginx + статика       │  HTTPS из коробки
   └────────────────────────┘
        │ iframe
        ▼
   ┌────────────────────────┐
   │ SoundCloud Widget      │  публичный API soundcloud.com
   └────────────────────────┘
```

- Бот шлёт `web_app` кнопку с URL `https://webapp-...railway.app/?track=<encoded_sc_url>`.
- Mini App грузит трек в SoundCloud Widget.
- Воспроизведение идёт прямо с SoundCloud.

## Ограничения

- **Telegram Bot API** не даёт ботам слать аудио больше **50 МБ** — длинные/lossless треки не уйдут как файл, но в Mini App плеере по-прежнему сыграют.
- **SoundCloud не даёт регистрировать новые API-клиенты с 2015 года.** Используется встроенный публичный Widget API (без ключа) для воспроизведения и `yt-dlp` для скачивания.
- **Приватные треки** и треки с ограничением «только превью» не скачаются и не сыграют.
- Скачанные mp3 удаляются сразу после отправки.
- Railway hobby plan: $5 кредита/мес. Бот в idle расходует копейки, основная нагрузка — конвертация ffmpeg при скачивании. Для личного использования бесплатных кредитов с лихвой хватает.

## Обновление

- **Railway**: `git push` в основную ветку → автодеплой обоих сервисов.
- **Локально**: правки в `app/` — `docker compose up -d --build bot`. Правки в `webapp/` — пересобрать/перезалить статику на хостинг.

## Локально без Docker (для разработки)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
brew install ffmpeg     # или apt install ffmpeg
export TELEGRAM_API_KEY=...
export WEBAPP_URL=https://your-webapp.netlify.app
python -m app.main
```
