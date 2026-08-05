"""Клиент Telegram Bot API — ровно те методы, что нужны каналу."""

from __future__ import annotations

import json
import re
from typing import Any

import requests

from . import config

# Telegram понимает лишь небольшой набор тегов. Всё остальное — ошибка разбора,
# из-за которой сообщение не уходит вовсе, поэтому текст чистится перед отправкой.
ALLOWED_TAGS = {
    "b", "strong", "i", "em", "u", "ins", "s", "strike", "del",
    "a", "code", "pre", "blockquote", "tg-spoiler", "span",
}

_BR = re.compile(r"<\s*br\s*/?\s*>", re.IGNORECASE)
_P_CLOSE = re.compile(r"<\s*/\s*p\s*>", re.IGNORECASE)
_TAG = re.compile(r"<\s*/?\s*([a-zA-Z][a-zA-Z0-9-]*)[^>]*>")


def sanitize(text: str) -> str:
    """Убирает разметку, которую Telegram не поддерживает.

    Модель периодически добавляет <br>, <p> или списки — с ними API отвечает
    ошибкой разбора, и пост не публикуется. Полезные теги сохраняются.
    """
    text = _BR.sub("\n", text)
    text = _P_CLOSE.sub("\n\n", text)

    def keep_or_drop(match: re.Match[str]) -> str:
        return match.group(0) if match.group(1).lower() in ALLOWED_TAGS else ""

    text = _TAG.sub(keep_or_drop, text)

    # Модель иногда оформляет абзацы markdown-цитатой «> ». В HTML-режиме
    # Telegram выводит эти символы как есть, и пост выглядит сломанным.
    text = re.sub(r"(?m)^\s*&gt;\s?", "", text)
    text = re.sub(r"(?m)^\s*>\s?", "", text)

    # Ссылка, приклеенная к последнему слову, читается как опечатка.
    text = re.sub(r"(?<=[^\s>\n])(<a\s+href=)", r"\n\n\1", text)

    # Схлопываем лишние пустые строки, появившиеся после вырезанных тегов.
    return re.sub(r"\n{3,}", "\n\n", text).strip()

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
            "text": sanitize(text)[:MAX_TEXT],
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
            "caption": sanitize(caption)[:MAX_CAPTION],
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
