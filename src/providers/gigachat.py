"""Провайдер GigaChat (Сбер).

Работает в России, оплачивается рублями, физлицам даётся 1 млн токенов
бесплатно с обновлением раз в год. Русский язык для модели родной — для
канала про русскую сцену это скорее преимущество.

Две особенности, из-за которых код сложнее обычного HTTP-клиента:

1. Авторизация двухступенчатая: по ключу выдаётся access_token на 30 минут,
   его приходится кэшировать и обновлять.
2. Сервер использует сертификаты НУЦ Минцифры, которых нет в стандартном
   хранилище доверенных корневых сертификатов ни на macOS, ни на серверах
   GitHub. Поэтому корневой сертификат подкладывается свой.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

import requests

OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
API_URL = "https://gigachat.devices.sberbank.ru/api/v1"

# Корневой сертификат НУЦ Минцифры, нужный для проверки TLS-соединения.
CA_URL = "https://gu-st.ru/content/Other/doc/russian_trusted_root_ca.cer"
CA_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "russian_trusted_root_ca.pem"

_token: str = ""
_token_expires: float = 0.0


def _credentials() -> str:
    key = os.environ.get("GIGACHAT_CREDENTIALS", "").strip()
    if not key:
        raise RuntimeError(
            "Не задан GIGACHAT_CREDENTIALS. Ключ авторизации берётся на "
            "developers.sber.ru → GigaChat API → создать проект для физлица."
        )
    return key


def model_name() -> str:
    return os.environ.get("GIGACHAT_MODEL", "GigaChat-Pro").strip()


def _verify() -> Any:
    """Что передавать в requests как проверку TLS.

    Пробуем использовать корневой сертификат Минцифры. Если его нет —
    скачиваем один раз и кладём рядом с данными проекта.
    """
    if os.environ.get("GIGACHAT_INSECURE", "").strip() == "1":
        return False  # аварийный режим, если сертификат недоступен

    if CA_FILE.exists():
        return str(CA_FILE)

    try:
        response = requests.get(CA_URL, timeout=30)
        if response.status_code == 200 and response.content:
            CA_FILE.parent.mkdir(parents=True, exist_ok=True)
            CA_FILE.write_bytes(response.content)
            return str(CA_FILE)
    except requests.RequestException:
        pass

    # Не смогли получить сертификат — соединение всё равно нужно установить.
    return False


def _access_token() -> str:
    """Токен доступа с кэшем: сервер выдаёт его на 30 минут."""
    global _token, _token_expires

    if _token and time.time() < _token_expires - 120:
        return _token

    response = requests.post(
        OAUTH_URL,
        headers={
            "Authorization": f"Basic {_credentials()}",
            "RqUID": str(uuid.uuid4()),
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={"scope": os.environ.get("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")},
        verify=_verify(),
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"GigaChat не выдал токен ({response.status_code}): {response.text[:200]}"
        )

    payload = response.json()
    _token = payload["access_token"]
    # expires_at приходит в миллисекундах
    _token_expires = payload.get("expires_at", 0) / 1000 or time.time() + 1500
    return _token


def generate(system: str, user: str, schema: dict) -> dict:
    """Один запрос к GigaChat. Схема используется как подсказка в промпте:
    строгих JSON-схем этот API не принимает, поэтому ответ разбирается вручную."""
    instruction = (
        f"{user}\n\n"
        "Ответ верни строго одним объектом JSON без markdown-обёртки, с полями:\n"
        '{"skip": true|false, "text": "текст поста", "reason": "если skip — почему"}'
    )

    last_error = ""
    for attempt in range(3):
        try:
            response = requests.post(
                f"{API_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {_access_token()}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model_name(),
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": instruction},
                    ],
                    "temperature": 0.9,  # тексты канала должны быть живыми, не сухими
                    "max_tokens": 2000,
                },
                verify=_verify(),
                timeout=120,
            )
        except requests.RequestException as exc:
            last_error = str(exc)[:200]
            time.sleep(3 * (attempt + 1))
            continue

        if response.status_code == 200:
            return _parse(response.json())

        last_error = f"{response.status_code}: {response.text[:200]}"
        if response.status_code == 429:
            time.sleep(20 * (attempt + 1))
            continue
        if response.status_code == 401:
            global _token
            _token = ""  # токен протух — обновим на следующем круге
            continue
        if response.status_code < 500:
            break
        time.sleep(4 * (attempt + 1))

    return {"skip": True, "text": "", "reason": f"GigaChat не ответил ({last_error})"}


def available_models() -> list[str]:
    """Список моделей, доступных по ключу — имена у тарифов различаются."""
    response = requests.get(
        f"{API_URL}/models",
        headers={"Authorization": f"Bearer {_access_token()}"},
        verify=_verify(),
        timeout=30,
    )
    if response.status_code != 200:
        return []
    return [m.get("id", "") for m in response.json().get("data", [])]


def _parse(data: dict) -> dict:
    choices = data.get("choices") or []
    if not choices:
        return {"skip": True, "text": "", "reason": "GigaChat вернул пустой ответ"}

    content = choices[0].get("message", {}).get("content", "").strip()
    parsed = _extract_json(content)

    if parsed is None:
        # Модель ответила прозой вместо JSON — используем текст как есть,
        # это лучше, чем терять готовый пост из-за формата.
        return {"skip": not content, "text": content, "reason": ""}

    return {
        "skip": bool(parsed.get("skip", False)),
        "text": _as_text(parsed.get("text")),
        "reason": _as_text(parsed.get("reason")),
    }


def _as_text(value: Any) -> str:
    """Приводит поле ответа к строке.

    Схему GigaChat не принимает, поэтому вместо строки может прийти вложенный
    объект или список абзацев. Терять из-за этого готовый пост не хочется.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n\n".join(_as_text(item) for item in value if item).strip()
    if isinstance(value, dict):
        # Опрос — это структура, а не проза: сохраняем её как JSON,
        # публикатор разберёт и отправит нативным опросом Telegram.
        if "question" in value and "options" in value:
            return json.dumps(value, ensure_ascii=False)
        # Иногда модель заворачивает текст ещё на уровень глубже.
        for key in ("text", "post", "content", "value"):
            if key in value:
                return _as_text(value[key])
        return "\n\n".join(_as_text(v) for v in value.values() if v).strip()
    return str(value).strip()


def _extract_json(text: str) -> dict | None:
    """Достаёт объект JSON из ответа, даже если он завёрнут в ```json."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else text

    variants = (
        candidate,
        _unescape_line_breaks(candidate),
        _escape_raw_newlines(_unescape_line_breaks(candidate)),
    )
    for attempt in variants:
        try:
            data = json.loads(attempt)
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            continue

    # Последняя попытка: вырезать самый внешний объект по фигурным скобкам.
    start, end = candidate.find("{"), candidate.rfind("}")
    if 0 <= start < end:
        chunk = candidate[start : end + 1]
        for attempt in (chunk, _unescape_line_breaks(chunk)):
            try:
                data = json.loads(attempt)
                return data if isinstance(data, dict) else None
            except json.JSONDecodeError:
                continue
    return None


def _escape_raw_newlines(text: str) -> str:
    """Экранирует переводы строк, оказавшиеся внутри строкового значения JSON.

    Модель часто вставляет в текст поста настоящий перевод строки, хотя по
    стандарту JSON там должно стоять «\\n». Без этой правки весь ответ считался
    неразборчивым, и служебный JSON уходил прямо в текст поста.
    """
    result: list[str] = []
    in_string = False
    escaped = False

    for char in text:
        if escaped:
            result.append(char)
            escaped = False
            continue
        if char == "\\":
            result.append(char)
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            result.append(char)
            continue
        if char == "\n" and in_string:
            result.append("\\n")
            continue
        result.append(char)

    return "".join(result)


def _unescape_line_breaks(text: str) -> str:
    """Убирает перенос строки, экранированный обратным слешем.

    GigaChat иногда разбивает длинную строку JSON так, как это делают в коде:
    обратный слеш и перевод строки. Для JSON это синтаксическая ошибка, и без
    такой правки готовый пост уходил в мусор целиком.
    """
    return re.sub(r"\\\s*\n\s*", "", text)
