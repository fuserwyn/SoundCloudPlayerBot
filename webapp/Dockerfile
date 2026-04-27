FROM python:3.12-slim

# Контекст сборки: корень репозитория SoundCloudPlayerBot (рядом каталоги app/ и webapp/).
# Сборка: docker build -f webapp/Dockerfile .
# Монorepo: docker build -f path/to/SoundCloudPlayerBot/webapp/Dockerfile path/to/SoundCloudPlayerBot
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /app

COPY webapp/requirements.txt ./
RUN pip install -r requirements.txt

COPY app ./app
# Явно /app/ — в части площадок multi-source COPY с «./» даёт сбой checksum; не используем ${ARG} в COPY (ломается, если ARG пустой)
COPY webapp/index.html webapp/styles.css webapp/player.js webapp/server.py webapp/tg_webapp_auth.py /app/

EXPOSE 8080

CMD ["python", "server.py"]
