"""Проверка initData из Telegram Mini App (см. core.telegram.org/bots/webapps)."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import parse_qsl

# initData не старше этого (секунд) — защита от replay
_MAX_AGE_SEC = 86400 * 7


def parse_user_id_from_init_data(init_data: str, bot_token: str) -> int | None:
    """Возвращает Telegram user id или None, если подпись неверна / нет user."""
    if not init_data or not bot_token:
        return None
    try:
        pairs = parse_qsl(init_data, keep_blank_values=True)
    except Exception:
        return None
    data: dict[str, str] = dict(pairs)
    received_hash = data.pop("hash", None)
    if not received_hash:
        return None
    ad = data.get("auth_date")
    if ad:
        try:
            if time.time() - int(ad) > _MAX_AGE_SEC:
                return None
        except (TypeError, ValueError):
            return None
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret_key = hmac.new(
        b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256
    ).digest()
    calculated = hmac.new(
        secret_key, data_check_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if calculated != received_hash:
        return None
    raw_user = data.get("user")
    if not raw_user:
        return None
    try:
        u: dict[str, Any] = json.loads(raw_user)
        uid = u.get("id")
        return int(uid) if uid is not None else None
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
