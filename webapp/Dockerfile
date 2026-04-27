FROM python:3.12-slim

# Сборка должна идти с контекстом = корень SoundCloudPlayerBot (рядом лежат app/ и webapp/).
# Если репозиторий — монorepo (контекст на уровень выше), в Railway/CI задайте:
#   --build-arg PROJECT_ROOT=SoundCloudPlayerBot
# или в переменных сборки: PROJECT_ROOT=SoundCloudPlayerBot
ARG PROJECT_ROOT=.

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /app

COPY ${PROJECT_ROOT}/webapp/requirements.txt ./
RUN pip install -r requirements.txt

COPY ${PROJECT_ROOT}/app ./app
COPY ${PROJECT_ROOT}/webapp/index.html ${PROJECT_ROOT}/webapp/styles.css ${PROJECT_ROOT}/webapp/player.js ${PROJECT_ROOT}/webapp/server.py ${PROJECT_ROOT}/webapp/tg_webapp_auth.py ./

EXPOSE 8080

CMD ["python", "server.py"]
