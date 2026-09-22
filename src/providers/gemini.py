"""Провайдер Google Gemini — основной генератор канала с 20.09.2026.

Обращаемся к REST API напрямую, без SDK: одна зависимость меньше, и код
не ломается при смене версий клиентской библиотеки.

Работает на бесплатном тарифе, поэтому пакетной отправки здесь нет: вдвое
дешевле нуля не бывает, а пакет отвечает часами. Точные лимиты Google меняет
и в документации не печатает, так что между запросами держим паузу с запасом —
каналу нужно 8–10 постов в сутки, в любые лимиты это укладывается.

Из России API не отвечает вовсе («User location is not supported»), причём
и через VPN тоже: проверить генератор с машины владельца нельзя, только
запуском в GitHub Actions — их сервера в США. Ключ выпускается один раз
из разрешённой страны и с 28.05.2026 обязательно привязан к сервис-аккаунту
(console.cloud.google.com → APIs & Services → Credentials).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

import requests

BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# Лимит запросов в минуту Google не публикует — держим паузу с запасом.
MIN_INTERVAL = 13.0
_last_call = 0.0


def _headers() -> dict[str, str]:
    """Ключ уходит заголовком, а не в адресной строке: иначе он попадает
    в текст ошибки requests, а оттуда — в журналы GitHub Actions."""
    return {"x-goog-api-key": _key()}


def _key() -> str:
    key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "Не задан GOOGLE_API_KEY. Бесплатный ключ: aistudio.google.com/apikey"
        )
    return key


def available_models() -> list[str]:
    """Какие модели отдаёт ключ и умеют писать текст.

    Поколения Gemini сменяются быстрее, чем канал успевает следить: зашитая
    в код модель однажды просто исчезнет, и запрос вернёт 404 посреди выхода
    поста. Один дешёвый список перед переключением дороже угадывания
    по документации.
    """
    response = requests.get(BASE, headers=_headers(), timeout=30)
    if response.status_code != 200:
        # Своя ошибка вместо raise_for_status: там в тексте только код и адрес,
        # а причину («location is not supported») Google пишет в теле ответа.
        raise RuntimeError(f"{response.status_code}: {response.text[:200]}")
    return [
        model["name"].removeprefix("models/")
        for model in response.json().get("models", [])
        if "generateContent" in model.get("supportedGenerationMethods", [])
    ]


def generate(model: str, system: str, user: str, schema: dict) -> dict:
    """Один запрос к Gemini с ответом строго по схеме."""
    global _last_call

    waited = time.monotonic() - _last_call
    if waited < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - waited)

    payload: dict[str, Any] = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": _to_gemini_schema(schema),
        },
    }

    last_error, status = "", 0
    for attempt in range(4):
        if attempt:
            # «High demand» у Gemini держится минуту-другую: 22.09.2026 запрос
            # в 06:13 ушёл на ГигаЧат, а в 06:15 Gemini уже ответил. Паузы
            # 15+30+45 секунд такой всплеск переживают; лимит (429) ждём дольше.
            time.sleep((30 if status == 429 else 15) * attempt)
        try:
            response = requests.post(
                f"{BASE}/{model}:generateContent",
                headers=_headers(),
                json=payload,
                timeout=120,
            )
        except requests.RequestException as exc:
            # Не дождались ответа — та же перегрузка, что и 503, повторяем.
            last_error, status = str(exc), 0
            continue
        _last_call = time.monotonic()

        if response.status_code == 200:
            return _parse(response.json())

        status = response.status_code
        last_error = f"{status}: {response.text[:200]}"
        if status < 500 and status != 429:
            break  # ошибка в запросе, повтор не поможет

    # Не ответил — это поломка, а не решение модели: пусть llm._generate
    # поднимет запасной генератор. Отказ вида skip=true оставил бы канал
    # без поста, хотя GigaChat рядом и работает.
    raise RuntimeError(f"Gemini не ответил ({last_error})")


def _to_gemini_schema(schema: dict) -> dict:
    """Приводит схему к диалекту Gemini: он не понимает additionalProperties."""
    cleaned = {k: v for k, v in schema.items() if k != "additionalProperties"}
    if "properties" in cleaned:
        cleaned["properties"] = {
            name: {k: v for k, v in prop.items() if k != "additionalProperties"}
            for name, prop in cleaned["properties"].items()
        }
    return cleaned


def _parse(data: dict) -> dict:
    candidates = data.get("candidates") or []
    if not candidates:
        # Ответ мог быть заблокирован фильтрами безопасности.
        reason = data.get("promptFeedback", {}).get("blockReason", "пустой ответ")
        return {"skip": True, "text": "", "reason": f"Gemini: {reason}"}

    parts = candidates[0].get("content", {}).get("parts") or []
    for part in parts:
        text = part.get("text", "")
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            continue
        # Опознаём ответ по skip, а не по text: у схемы ролика поля text нет,
        # а лишние поля отдаём как есть — см. claude.parse_message.
        if isinstance(parsed, dict) and "skip" in parsed:
            return {
                **parsed,
                "skip": bool(parsed.get("skip", False)),
                "text": (parsed.get("text") or "").strip(),
                "reason": (parsed.get("reason") or "").strip(),
            }

    return {"skip": True, "text": "", "reason": "Gemini вернул неразборчивый ответ"}
