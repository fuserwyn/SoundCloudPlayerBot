#!/usr/bin/env bash
set -euo pipefail

TARGET_HOST="${TUNNEL_HOST:-webapp}"
TARGET_PORT="${TUNNEL_PORT:-80}"
SHARED_DIR="${SHARED_DIR:-/shared}"
URL_FILE="${SHARED_DIR}/webapp_url.txt"
LOG_FILE="/tmp/tunnel.log"

if [ -z "${NGROK_AUTHTOKEN:-}" ]; then
  echo "[tunnel] ERROR: NGROK_AUTHTOKEN is not set." >&2
  echo "[tunnel] Get a free token at https://dashboard.ngrok.com/get-started/your-authtoken" >&2
  echo "[tunnel] Add it to .env as NGROK_AUTHTOKEN=..." >&2
  exit 1
fi

mkdir -p "$SHARED_DIR"
rm -f "$URL_FILE"
: > "$LOG_FILE"

echo "[tunnel] starting ngrok -> http://${TARGET_HOST}:${TARGET_PORT}"

ngrok http \
  --log stdout \
  --log-format logfmt \
  --log-level info \
  "${TARGET_HOST}:${TARGET_PORT}" >>"$LOG_FILE" 2>&1 &
NG_PID=$!

trap 'kill $NG_PID 2>/dev/null || true; wait $NG_PID 2>/dev/null || true' TERM INT

# Poll ngrok local API for the public URL.
DEADLINE=$(( $(date +%s) + 60 ))
URL=""
while [ "$(date +%s)" -lt "$DEADLINE" ]; do
  if ! kill -0 "$NG_PID" 2>/dev/null; then
    echo "[tunnel] ngrok exited unexpectedly" >&2
    cat "$LOG_FILE" >&2
    exit 1
  fi

  RESPONSE="$(curl -fsS --max-time 3 http://127.0.0.1:4040/api/tunnels 2>/dev/null || true)"
  URL="$(printf '%s' "$RESPONSE" | grep -oE 'https://[a-zA-Z0-9.-]+\.ngrok[a-zA-Z0-9.-]*\.app' | head -n1 || true)"
  if [ -z "$URL" ]; then
    URL="$(printf '%s' "$RESPONSE" | grep -oE 'https://[a-zA-Z0-9.-]+\.ngrok\.io' | head -n1 || true)"
  fi
  if [ -n "$URL" ]; then
    break
  fi
  sleep 1
done

if [ -z "$URL" ]; then
  echo "[tunnel] failed to detect ngrok URL within 60s" >&2
  tail -n 50 "$LOG_FILE" >&2
  kill "$NG_PID" 2>/dev/null || true
  exit 1
fi

printf '%s' "$URL" > "$URL_FILE"
echo "[tunnel] public URL: $URL"
echo "[tunnel] wrote $URL_FILE"

tail -n +1 -F "$LOG_FILE" &
TAIL_PID=$!

wait "$NG_PID"
EXIT_CODE=$?
kill "$TAIL_PID" 2>/dev/null || true
exit "$EXIT_CODE"
