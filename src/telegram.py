"""Клиент Telegram Bot API — ровно те методы, что нужны каналу."""

from __future__ import annotations

import json
import re
from pathlib import Path
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


def _call(method: str, payload: dict[str, Any], files: dict | None = None) -> dict:
    token = config.secret("TELEGRAM_BOT_TOKEN")
    response = requests.post(
        API.format(token=token, method=method), data=payload, files=files, timeout=90
    )

    try:
        data = response.json()
    except ValueError:
        raise TelegramError(f"{method}: ответ не JSON (код {response.status_code})")

    if not data.get("ok"):
        raise TelegramError(f"{method}: {data.get('description', 'неизвестная ошибка')}")
    return data["result"]


def send_message(
    chat_id: str,
    text: str,
    *,
    preview: bool = False,
    buttons: list[list[dict]] | None = None,
    reply_to: int | None = None,
) -> dict:
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": sanitize(text)[:MAX_TEXT],
        "parse_mode": "HTML",
        "link_preview_options": json.dumps({"is_disabled": not preview}),
    }
    if buttons:
        payload["reply_markup"] = json.dumps({"inline_keyboard": buttons})
    if reply_to is not None:
        # Ответ на пост, пересланный в чат обсуждений, — это и есть комментарий
        # под постом. Без reply_to сообщение повиснет отдельной репликой в чате.
        payload["reply_parameters"] = json.dumps({"message_id": reply_to})
    return _call("sendMessage", payload)


def get_chat(chat_id: str) -> dict:
    """Карточка чата: описание, привязанный чат обсуждений, реакции."""
    return _call("getChat", {"chat_id": chat_id})


def member_count(chat_id: str) -> int:
    return int(_call("getChatMemberCount", {"chat_id": chat_id}))


def administrators(chat_id: str) -> list[dict]:
    return _call("getChatAdministrators", {"chat_id": chat_id})


def pin_message(chat_id: str, message_id: int, *, notify: bool = False) -> None:
    _call(
        "pinChatMessage",
        {"chat_id": chat_id, "message_id": message_id, "disable_notification": not notify},
    )


def approval_buttons(post_id: str) -> list[list[dict]]:
    """Кнопки под превью поста. В callback_data кладём имя файла в очереди."""
    return [
        [
            {"text": "✅ В канал", "callback_data": f"pub:{post_id}"},
            {"text": "🗑 Удалить", "callback_data": f"del:{post_id}"},
        ],
        [{"text": "⏭ Позже", "callback_data": f"skip:{post_id}"}],
    ]


def get_updates(offset: int = 0, timeout: int = 0) -> list[dict]:
    """Забирает новые события бота — в том числе нажатия кнопок."""
    return _call(
        "getUpdates",
        {
            "offset": offset,
            "timeout": timeout,
            "allowed_updates": json.dumps(["callback_query", "message"]),
        },
    )


def answer_callback(callback_id: str, text: str = "") -> None:
    """Гасит «часики» на кнопке и показывает всплывающее уведомление."""
    try:
        _call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text[:200]})
    except TelegramError:
        # Уведомление живёт недолго: если запоздали — не повод падать.
        pass


def edit_markup(chat_id: str, message_id: int, buttons: list[list[dict]] | None) -> None:
    """Меняет кнопки под уже отправленным сообщением (или убирает их)."""
    try:
        _call(
            "editMessageReplyMarkup",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "reply_markup": json.dumps({"inline_keyboard": buttons or []}),
            },
        )
    except TelegramError:
        pass


def send_photo_file(chat_id: str, path: Path, caption: str) -> dict:
    """Отправляет картинку с диска. Нужна сервису: карточку разбора мы рисуем
    сами, публичной ссылки на неё нет — файл уходит прямо в загрузку."""
    with path.open("rb") as handle:
        return _call(
            "sendPhoto",
            {
                "chat_id": chat_id,
                "caption": sanitize(caption)[:MAX_CAPTION],
                "parse_mode": "HTML",
            },
            files={"photo": (path.name, handle, "image/jpeg")},
        )


def send_video_file(chat_id: str, path: Path, caption: str, *, seconds: int = 0) -> dict:
    """Отправляет готовый ролик с диска.

    Через это же место идёт доставка клипов: ВКонтакте заливать видео
    групповым ключом не даёт (video.save требует пользовательский токен),
    поэтому ролик уходит в Telegram, а во ВКонтакте перекладывается руками.

    `supports_streaming` важен для вертикальных роликов: без него Telegram
    показывает файл вложением, а не проигрывателем.
    """
    with path.open("rb") as handle:
        payload = {
            "chat_id": chat_id,
            "caption": sanitize(caption)[:MAX_CAPTION],
            "parse_mode": "HTML",
            "supports_streaming": True,
        }
        if seconds:
            payload["duration"] = seconds
        return _call("sendVideo", payload, files={"video": (path.name, handle, "video/mp4")})


# Подписчиком считается любой, кто не вышел и не выгнан.
MEMBER_STATUSES = {"creator", "administrator", "member", "restricted"}


def is_member(chat_id: str, user_id: str | int) -> bool:
    """Проверяет подписку на канал. Бот админ канала, поэтому право есть.

    При любой ошибке отвечаем «подписан»: сломанная проверка не должна
    выглядеть для человека как отказ в обслуживании.
    """
    try:
        result = _call("getChatMember", {"chat_id": chat_id, "user_id": user_id})
    except TelegramError:
        return True
    return result.get("status", "") in MEMBER_STATUSES


def send_chat_action(chat_id: str, action: str = "typing") -> None:
    """Показывает «печатает…». Ответ готовится минуты — без этого человек
    решит, что бот умер."""
    try:
        _call("sendChatAction", {"chat_id": chat_id, "action": action})
    except TelegramError:
        pass


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


def _thumbnail(cover_url: str) -> bytes | None:
    """Готовит обложку под требования Telegram к превью аудио: JPEG,
    не больше 320 пикселей по стороне и 200 КБ весом. Обложка из магазина
    приходит 600×600 и в эти рамки не влезает, поэтому её ужимаем.

    Не получилось — вернём None: отрывок уйдёт с типовой иконкой ноты,
    это хуже на вид, но не повод не отправлять музыку.
    """
    try:
        import io

        from PIL import Image

        response = requests.get(cover_url, timeout=30)
        if response.status_code != 200:
            return None

        image = Image.open(io.BytesIO(response.content)).convert("RGB")
        image.thumbnail((320, 320))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=85)
        data = buffer.getvalue()
        return data if len(data) <= 200_000 else None
    except Exception:
        return None


def send_audio(
    chat_id: str,
    audio_url: str,
    caption: str,
    *,
    title: str = "",
    performer: str = "",
    cover_url: str = "",
) -> dict:
    """Отправляет отрывок трека с текстом поста в подписи.

    Telegram принимает сам файл по ссылке, а вот превью — только загрузкой,
    ссылку на картинку в `thumbnail` он не берёт. Поэтому обложка идёт
    вторым файлом в том же запросе.
    """
    payload = {
        "chat_id": chat_id,
        "audio": audio_url,
        "caption": sanitize(caption)[:MAX_CAPTION],
        "parse_mode": "HTML",
    }
    if title:
        payload["title"] = title[:64]
    if performer:
        payload["performer"] = performer[:64]

    files = None
    thumb = _thumbnail(cover_url) if cover_url else None
    if thumb:
        payload["thumbnail"] = "attach://thumb"
        files = {"thumb": ("thumb.jpg", thumb, "image/jpeg")}

    return _call("sendAudio", payload, files)


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


# Пояснение к викторине Telegram обрезает жёстко — двести знаков и ни одним
# больше, иначе запрос отклоняется целиком.
MAX_EXPLANATION = 200


def send_quiz(
    chat_id: str,
    question: str,
    options: list[str],
    correct: int,
    *,
    explanation: str = "",
) -> dict:
    """Нативная викторина: Telegram сам покажет верный ответ и пояснение.

    Отличается от обычного опроса тем, что у неё есть правильный вариант —
    человек сразу узнаёт, угадал или нет, и это работает без нашего участия.
    В канале викторина обязана быть анонимной.
    """
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "type": "quiz",
        "question": question[:300],
        "options": json.dumps([o[:100] for o in options[:10]], ensure_ascii=False),
        "correct_option_id": correct,
        "is_anonymous": True,
    }
    if explanation:
        payload["explanation"] = sanitize(explanation)[:MAX_EXPLANATION]
        payload["explanation_parse_mode"] = "HTML"
    return _call("sendPoll", payload)


def check() -> str:
    """Проверяет токен и возвращает имя бота — быстрый тест настройки."""
    me = _call("getMe", {})
    return f"@{me.get('username', '?')}"


# ─────────────────────────── витрина бота ───────────────────────────
#
# То, что человек видит до того, как что-то написал: список команд под кнопкой
# «/», описание на пустом экране и надпись под именем в поиске. Всё ставится
# через API один раз и живёт само.


def set_my_commands(commands: list[tuple[str, str]]) -> None:
    """Список команд в меню бота. Пары (команда без слеша, описание)."""
    _call(
        "setMyCommands",
        {
            "commands": json.dumps(
                [{"command": name, "description": text} for name, text in commands],
                ensure_ascii=False,
            )
        },
    )


def set_my_description(text: str) -> None:
    """Текст на пустом экране до нажатия «Начать» — единственный шанс
    объяснить, зачем сюда пришли."""
    _call("setMyDescription", {"description": text[:512]})


def set_my_short_description(text: str) -> None:
    """Строка под именем бота в поиске и в профиле."""
    _call("setMyShortDescription", {"short_description": text[:120]})


def set_chat_description(chat_id: str, text: str) -> None:
    """Описание канала. Боту нужно право «Изменение профиля канала»."""
    _call("setChatDescription", {"chat_id": chat_id, "description": text[:255]})


def url_button(text: str, url: str) -> list[list[dict]]:
    """Кнопка-ссылка под постом. В канале это единственный способ увести
    человека в бота одним касанием, а не копированием имени из текста."""
    return [[{"text": text, "url": url}]]
