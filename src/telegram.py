"""Клиент Telegram Bot API — ровно те методы, что нужны каналу."""

from __future__ import annotations

import html
import json
import re
import struct
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
_CLOSING = re.compile(r"<\s*/")
# Всё, что похоже на тег, разбирает _TAG выше; уцелевший «<» — это просто знак
# «меньше», и Telegram считает его началом тега, отвечая ошибкой разбора.
_BARE_LT = re.compile(r"<(?!\s*/?\s*[a-zA-Z][a-zA-Z0-9-]*[^>]*>)")


def _balance(text: str) -> str:
    """Закрывает теги, которые модель открыла и забыла, и срезает лишние закрытия.

    На «<b>жир» без пары Telegram отвечает «can't find end tag», на «<i>x</b>» —
    тем же, и пост не уходит вообще: ни в канал, ни в архив, молча (проверено
    на Bot API 10.09.2026). Досчитать пары дешевле, чем повторять запрос без
    разметки: лишнего запроса нет, а пост сохраняет жир и ссылки.

    Внахлёст («<b><i>x</b></i>») лишнее закрытие вырезается, а хвост
    дописывается в конце — разметка та же, порядок вложения выправлен.
    """
    open_tags: list[str] = []

    def pair(match: re.Match[str]) -> str:
        name = match.group(1).lower()
        if _CLOSING.match(match.group(0)):
            if not open_tags or open_tags[-1] != name:
                return ""
            open_tags.pop()
        else:
            open_tags.append(name)
        return match.group(0)

    return _TAG.sub(pair, text) + "".join(f"</{name}>" for name in reversed(open_tags))


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

    # «Цена < 100» роняет отправку целиком и молча: Telegram отвечает
    # «Unsupported start tag». Экранируем — но только после разбора цитат,
    # иначе собственная чистка «&gt;» разъедется с экранированием.
    # Голый «&» так не ломает: проверено вживую, API принимает его в любом виде
    # (Simon & Garfunkel, R&B;, «хвост &»), поэтому в тексте он и остаётся —
    # в очереди должен лежать пост, а не «&amp;».
    text = _BARE_LT.sub("&lt;", text)

    # Ссылка, приклеенная к последнему слову, читается как опечатка.
    text = re.sub(r"(?<=[^\s>\n])(<a\s+href=)", r"\n\n\1", text)

    # Схлопываем лишние пустые строки, появившиеся после вырезанных тегов.
    # Пары досчитываются последними: хвост закрытий дописывается за текстом,
    # уже обрезанным по краям.
    return _balance(re.sub(r"\n{3,}", "\n\n", text).strip())

API = "https://api.telegram.org/bot{token}/{method}"

# Ограничения Telegram: подпись к фото короче обычного сообщения.
MAX_TEXT = 4096
MAX_CAPTION = 1024


def visible_len(text: str) -> int:
    """Длина текста так, как её считает Telegram: после разбора HTML.

    Теги и экранирование в лимит не входят — важно для строки площадок
    (src/publish.listen): восемь ссылок занимают в разметке под шестьсот
    символов, а на экране — полсотни. Считать сырую длину значит отказаться
    от обложки на ровном месте: пост уходил текстом (проверено 12.09.2026).
    """
    return len(html.unescape(_TAG.sub("", text)))


def clip(text: str, limit: int) -> str:
    """Обрезает подпись по видимой длине, не кромсая разметку почём зря.

    Рез приходится на сырой текст, поэтому он может прийтись и на середину
    тега: обрубок вырезаем, а незакрытое досчитываем — иначе Telegram ответит
    ошибкой разбора и подпись не уйдёт вовсе.
    """
    if visible_len(text) <= limit:
        return text
    return _balance(re.sub(r"<[^>]*$", "", text[:limit]))


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
    quiet: bool = False,
) -> dict:
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": sanitize(text)[:MAX_TEXT],
        "parse_mode": "HTML",
        "link_preview_options": json.dumps({"is_disabled": not preview}),
    }
    if buttons:
        payload["reply_markup"] = json.dumps({"inline_keyboard": buttons})
    if quiet:
        payload["disable_notification"] = True
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
            # poll_answer — голоса в неанонимной прослушке под постом (src/quiz.py):
            # без него Telegram их боту не присылает вовсе.
            "allowed_updates": json.dumps(["callback_query", "message", "poll_answer"]),
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


def edit_text(chat_id: str | int, message_id: int, text: str, *, buttons: list[list[dict]] | None = None) -> dict:
    """Новый текст уже отправленного сообщения — правка вышедшего поста (src/review.py).

    Кнопки передаются заново: правка без reply_markup снимает их с сообщения.
    Превью ссылок выключено, как при отправке, — иначе правка его включила бы.
    """
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": sanitize(text)[:MAX_TEXT],
        "parse_mode": "HTML",
        "link_preview_options": json.dumps({"is_disabled": True}),
    }
    if buttons:
        payload["reply_markup"] = json.dumps({"inline_keyboard": buttons})
    return _call("editMessageText", payload)


def edit_caption(chat_id: str | int, message_id: int, caption: str, *, buttons: list[list[dict]] | None = None) -> dict:
    """Новая подпись фото или плеера. Кнопки — заново, как в edit_text."""
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "caption": clip(sanitize(caption), MAX_CAPTION),
        "parse_mode": "HTML",
    }
    if buttons:
        payload["reply_markup"] = json.dumps({"inline_keyboard": buttons})
    return _call("editMessageCaption", payload)


def send_photo_file(
    chat_id: str, path: Path, caption: str, *, buttons: list[list[dict]] | None = None,
    quiet: bool = False,
) -> dict:
    """Отправляет картинку с диска. Нужна сервису: карточку разбора мы рисуем
    сами, публичной ссылки на неё нет — файл уходит прямо в загрузку."""
    payload = {
        "chat_id": chat_id,
        "caption": clip(sanitize(caption), MAX_CAPTION),
        "parse_mode": "HTML",
    }
    if buttons:
        payload["reply_markup"] = json.dumps({"inline_keyboard": buttons})
    if quiet:
        payload["disable_notification"] = True
    with path.open("rb") as handle:
        return _call("sendPhoto", payload, files={"photo": (path.name, handle, "image/jpeg")})


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
            "caption": clip(sanitize(caption), MAX_CAPTION),
            "parse_mode": "HTML",
            "supports_streaming": True,
        }
        if seconds:
            payload["duration"] = seconds
        return _call("sendVideo", payload, files={"video": (path.name, handle, "video/mp4")})


def send_video_url(chat_id: str, url: str, caption: str, *, reply_to: int | None = None) -> dict:
    """Ролик по чужой ссылке: файл забирает сам Telegram.

    Так под пост попадает сниппет из паблика, откуда пришёл инфоповод. Качать
    его себе незачем: боту Bot API отдаёт не больше 20 МБ, а по ссылке те же
    файлы уходят без нашего диска и без перекодирования — ролик уже mp4.
    """
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "video": url,
        "caption": clip(sanitize(caption), MAX_CAPTION),
        "parse_mode": "HTML",
        "supports_streaming": True,
    }
    if reply_to is not None:
        payload["reply_parameters"] = json.dumps({"message_id": reply_to})
    return _call("sendVideo", payload)


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


def send_photo(
    chat_id: str, photo_url: str, caption: str, *, buttons: list[list[dict]] | None = None,
    quiet: bool = False,
) -> dict:
    payload = {
        "chat_id": chat_id,
        "photo": photo_url,
        "caption": clip(sanitize(caption), MAX_CAPTION),
        "parse_mode": "HTML",
    }
    if buttons:
        payload["reply_markup"] = json.dumps({"inline_keyboard": buttons})
    if quiet:
        payload["disable_notification"] = True
    return _call("sendPhoto", payload)


def _seconds(clip: bytes) -> int:
    """Длительность m4a из заголовка mvhd — Telegram сам её не считает,
    и без неё в ленте висит плеер на 0:00.

    Магазин кладёт moov в начало файла (иначе превью не начало бы играть
    до полной загрузки), так что заголовок ищется простым поиском.
    """
    mark = clip.find(b"mvhd")
    if mark < 0:
        return 0
    head = clip[mark + 4 :]
    try:
        if head[0] == 0:
            scale, length = struct.unpack(">II", head[12:20])
        else:
            scale, length = struct.unpack(">IQ", head[20:32])
        return round(length / scale) if scale else 0
    except Exception:
        return 0


def _audio_kind(clip: bytes) -> tuple[str, str]:
    """Имя и тип файла по содержимому, а не по ссылке.

    iTunes отдаёт отрывок в m4a, Deezer — в mp3. Залитый под чужим типом
    mp3 Telegram не узнаёт и кладёт в ленту файл с именем вместо плеера.
    """
    if clip[4:8] == b"ftyp":
        return "preview.m4a", "audio/mp4"
    return "preview.mp3", "audio/mpeg"


def _download(url: str) -> bytes | None:
    """Тянет отрывок в память. Превью магазина — около мегабайта, держать его
    в памяти дешевле, чем возиться с временными файлами.
    """
    try:
        response = requests.get(url, timeout=60)
        return response.content if response.status_code == 200 else None
    except Exception:
        return None


# Больше Bot API ботам не отдаёт: getFile отвечает «file is too big».
MAX_DOWNLOAD = 20 * 1024 * 1024


def download_file(file_id: str) -> bytes:
    """Скачивает файл, присланный боту, в память — больше 20 МБ он всё равно не весит."""
    path = _call("getFile", {"file_id": file_id})["file_path"]
    token = config.secret("TELEGRAM_BOT_TOKEN")
    try:
        response = requests.get(f"https://api.telegram.org/file/bot{token}/{path}", timeout=120)
    except requests.RequestException:
        # Текст исключения несёт адрес вместе с токеном — наружу его не отдаём.
        raise TelegramError("файл не скачался: нет связи с Telegram") from None
    if response.status_code != 200:
        raise TelegramError(f"файл не скачался (код {response.status_code})")
    return response.content


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
    audio: str | bytes,
    caption: str,
    *,
    title: str = "",
    performer: str = "",
    cover_url: str = "",
    thumb: bytes | None = None,
    seconds: int = 0,
    buttons: list[list[dict]] | None = None,
    quiet: bool = False,
    reply_to: int | None = None,
) -> dict:
    """Отправляет трек с текстом в подписи.

    reply_to — ответ на пересылку поста в чате обсуждений: так полный трек
    встаёт первым комментарием под постом (src/comments.py). Без него плеер
    повис бы в чате отдельной репликой.

    Отрывок качаем сами, а не даём Telegram ссылку: магазин помечает превью
    типом `audio/x-m4p`, Telegram его не узнаёт и кладёт в ленту файл, который
    слушателю надо сперва скачать. Тот же байт, загруженный как `.m4a`,
    становится обычным плеером — нажал и играет.

    Превью-картинку Telegram по ссылке не берёт вовсе, поэтому обложка идёт
    вторым файлом в том же запросе.

    Не ссылка — значит file_id файла, который уже лежит у Telegram (полный трек
    от владельца): он уходит строкой как есть, без загрузки. File_id документа
    Telegram тоже принимает, но и в ленту кладёт документом, а не плеером.

    Байты — сам файл: так дежурство перезаливает полный трек от владельца
    (src/moderate.py). Название, артиста и превью Telegram берёт только при
    загрузке, поэтому готовая обложка приходит в thumb, длительность — в seconds.
    """
    payload = {
        "chat_id": chat_id,
        "caption": clip(sanitize(caption), MAX_CAPTION),
        "parse_mode": "HTML",
    }
    if title:
        payload["title"] = title[:64]
    if performer:
        payload["performer"] = performer[:64]
    if reply_to is not None:
        payload["reply_parameters"] = json.dumps({"message_id": reply_to})

    files = {}
    blob = audio if isinstance(audio, bytes) else None
    if blob is None and audio.startswith("http"):
        blob = _download(audio)
        if not blob:
            # Отдавать Telegram ссылку магазина бесполезно: протухшую он не скачает,
            # а живую положит файлом без плеера. Пусть вызывающий откатится сам.
            raise TelegramError(f"отрывок не скачался: {audio[:80]}")
    if blob:
        name, mime = _audio_kind(blob)
        payload["audio"] = "attach://audio"
        files["audio"] = (name, blob, mime)
        if mime == "audio/mp4":
            seconds = seconds or _seconds(blob)
    else:
        # file_id файла, который уже лежит у Telegram, уходит как есть.
        payload["audio"] = audio
    if seconds:
        payload["duration"] = seconds
    if quiet:
        payload["disable_notification"] = True

    if thumb is None and cover_url:
        thumb = _thumbnail(cover_url)
    if thumb:
        payload["thumbnail"] = "attach://thumb"
        files["thumb"] = ("thumb.jpg", thumb, "image/jpeg")

    if buttons:
        payload["reply_markup"] = json.dumps({"inline_keyboard": buttons})
    return _call("sendAudio", payload, files or None)


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
    anonymous: bool = True,
    reply_to: int | None = None,
) -> dict:
    """Нативная викторина: Telegram сам покажет верный ответ и пояснение.

    Отличается от обычного опроса тем, что у неё есть правильный вариант —
    человек сразу узнаёт, угадал или нет, и это работает без нашего участия.
    В канале викторина обязана быть анонимной. Неанонимная уходит в чат
    обсуждений ответом на пересылку поста (src/quiz.py): только за такие
    Telegram сообщает боту, кто что ответил.
    """
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "type": "quiz",
        "question": question[:300],
        "options": json.dumps([o[:100] for o in options[:10]], ensure_ascii=False),
        # Bot API 9.4 заменил correct_option_id списком: верных вариантов
        # у викторины теперь может быть несколько.
        "correct_option_ids": json.dumps([correct]),
        "is_anonymous": anonymous,
    }
    if explanation:
        payload["explanation"] = sanitize(explanation)[:MAX_EXPLANATION]
        payload["explanation_parse_mode"] = "HTML"
    if reply_to is not None:
        payload["reply_parameters"] = json.dumps({"message_id": reply_to})
    return _call("sendPoll", payload)


def chat_member(chat_id: str | int, user_id: str | int) -> dict:
    """Участник чата: статус, метка, права. Что делать при ошибке, решает вызывающий."""
    return _call("getChatMember", {"chat_id": chat_id, "user_id": user_id})


def set_member_tag(chat_id: str | int, user_id: int, tag: str) -> None:
    """Метка рядом с именем обычного участника группы (Bot API 9.5).

    Боту нужно право can_manage_tags; админу так метку не поставить.
    До 16 знаков и без эмодзи — иначе запрос отклоняется.
    """
    _call("setChatMemberTag", {"chat_id": chat_id, "user_id": user_id, "tag": tag[:16]})


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


def _selftest() -> None:
    """Проверка sanitize: молчаливая потеря поста дороже любого теста.

    Запуск: python -m src.telegram
    """
    # Голый «<» — единственное, что действительно роняет отправку.
    assert sanitize("цена < 100") == "цена &lt; 100"
    # Тип отрывка — по байтам: mp3 под видом m4a ложится в ленту файлом без плеера.
    assert _audio_kind(b"\x00\x00\x00\x20ftypM4A \x00") == ("preview.m4a", "audio/mp4")
    assert _audio_kind(b"ID3\x04\x00\x00") == ("preview.mp3", "audio/mpeg")
    assert sanitize("рейтинг <3 из 10") == "рейтинг &lt;3 из 10"
    # Разрешённая разметка проходит целиком.
    assert sanitize('<b>жир</b> и <a href="https://x.ru">ссылка</a>').startswith("<b>жир</b>")
    # Уже экранированное вторым проходом не портится.
    assert sanitize("&lt;тег&gt; внутри") == "&lt;тег&gt; внутри"
    assert sanitize("Hall &amp; Oates") == "Hall &amp; Oates"
    # Голый амперсанд Telegram принимает — не трогаем, иначе «&amp;» полезет
    # в очередь, в консоль и в карточки историй.
    assert sanitize("Simon & Garfunkel") == "Simon & Garfunkel"
    # Markdown-цитата в начале строки по-прежнему срезается, в обоих видах.
    assert sanitize("&gt; цитата") == "цитата"
    assert sanitize("> цитата") == "цитата"
    # Неподдерживаемые теги вырезаются, полезные — нет.
    assert sanitize("<div>текст<br>ещё</div>") == "текст\nещё"

    # Незакрытый и перекрёстный тег Telegram не прощает: «can't find end tag»,
    # и пост не уходит вовсе. Досчитываем пары сами.
    assert sanitize("незакрытый <b>жир") == "незакрытый <b>жир</b>"
    assert sanitize("<i>курсив</b>") == "<i>курсив</i>"
    assert sanitize("хвост </b> без начала") == "хвост  без начала"
    assert sanitize("<b><i>внахлёст</b></i>") == "<b><i>внахлёст</i></b>"
    assert sanitize('<a href="https://x.ru">ссылка') == '<a href="https://x.ru">ссылка</a>'
    # Закрытия дописываются за текстом, а не за пустыми строками в конце.
    assert sanitize("<b>жир\n\n") == "<b>жир</b>"

    # Лимит подписи Telegram считает по видимому тексту: строка площадок
    # занимает в разметке сотни символов, на экране — полсотни.
    link = '<a href="https://music.apple.com/us/album/x?uo=4">Слушать в Apple Music</a>'
    assert visible_len(link) == len("Слушать в Apple Music"), visible_len(link)
    assert visible_len("Цена &lt; 100") == len("Цена < 100")
    assert clip("а" * 30 + link, 60) == "а" * 30 + link
    assert len(clip("а" * 90, 60)) == 60
    # Рез посреди разметки: обрубок тега вырезан, открытое закрыто.
    assert clip("<b>" + "а" * 90, 60) == "<b>" + "а" * 57 + "</b>"
    assert clip("а" * 55 + link, 60) == "а" * 55

    # Полный трек первым комментарием: file_id уходит строкой, подпись обрезается
    # той самой clip(). 12.09.2026 локальная переменная с этим же именем затенила
    # функцию, и дежурство падало на каждом посте о релизе.
    calls: list[tuple] = []
    real_call, globals()["_call"] = _call, lambda method, payload, files=None: (
        calls.append((method, payload, files)) or {"message_id": 1})
    try:
        send_audio("-100", "FILE_ID", "Подпись", reply_to=7)
    finally:
        globals()["_call"] = real_call
    method, payload, files = calls[0]
    assert method == "sendAudio" and payload["audio"] == "FILE_ID" and files is None, calls[0]
    assert payload["caption"] == "Подпись" and "reply_parameters" in payload, payload
    print("sanitize: все проверки прошли")


if __name__ == "__main__":
    _selftest()
