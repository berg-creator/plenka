"""Клиент Telegram Bot API — ровно те методы, что нужны каналу."""

from __future__ import annotations

import json
from typing import Any

import requests

from . import config

API = "https://api.telegram.org/bot{token}/{method}"

# Ограничения Telegram: подпись к фото короче обычного сообщения.
MAX_TEXT = 4096
MAX_CAPTION = 1024


class TelegramError(RuntimeError):
    pass


def _call(method: str, payload: dict[str, Any]) -> dict:
    token = config.secret("TELEGRAM_BOT_TOKEN")
    response = requests.post(API.format(token=token, method=method), data=payload, timeout=30)

    try:
        data = response.json()
    except ValueError:
        raise TelegramError(f"{method}: ответ не JSON (код {response.status_code})")

    if not data.get("ok"):
        raise TelegramError(f"{method}: {data.get('description', 'неизвестная ошибка')}")
    return data["result"]


def send_message(chat_id: str, text: str, *, preview: bool = False) -> dict:
    return _call(
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": text[:MAX_TEXT],
            "parse_mode": "HTML",
            "link_preview_options": json.dumps({"is_disabled": not preview}),
        },
    )


def send_photo(chat_id: str, photo_url: str, caption: str) -> dict:
    return _call(
        "sendPhoto",
        {
            "chat_id": chat_id,
            "photo": photo_url,
            "caption": caption[:MAX_CAPTION],
            "parse_mode": "HTML",
        },
    )


def send_poll(chat_id: str, question: str, options: list[str], *, anonymous: bool = True) -> dict:
    return _call(
        "sendPoll",
        {
            "chat_id": chat_id,
            "question": question[:300],
            "options": json.dumps([o[:100] for o in options[:10]], ensure_ascii=False),
            "is_anonymous": anonymous,
        },
    )


def check() -> str:
    """Проверяет токен и возвращает имя бота — быстрый тест настройки."""
    me = _call("getMe", {})
    return f"@{me.get('username', '?')}"
