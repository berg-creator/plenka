"""Провайдер Google Gemini — работает на бесплатном тарифе.

Обращаемся к REST API напрямую, без SDK: одна зависимость меньше, и код
не ломается при смене версий клиентской библиотеки.

Бесплатный тариф Gemini 2.5 Pro — 100 запросов в сутки и 5 в минуту.
Каналу нужно 8–10 в сутки, так что запас десятикратный; ограничение
по минуте обходится паузой между запросами.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

import requests

BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# 5 запросов в минуту на бесплатном тарифе — держим паузу с запасом.
MIN_INTERVAL = 13.0
_last_call = 0.0


def _key() -> str:
    key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "Не задан GOOGLE_API_KEY. Бесплатный ключ: aistudio.google.com/apikey"
        )
    return key


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

    last_error = ""
    for attempt in range(3):
        response = requests.post(
            f"{BASE}/{model}:generateContent",
            params={"key": _key()},
            json=payload,
            timeout=120,
        )
        _last_call = time.monotonic()

        if response.status_code == 200:
            return _parse(response.json())

        last_error = f"{response.status_code}: {response.text[:200]}"
        if response.status_code == 429:
            # Упёрлись в лимит — ждём дольше обычного.
            time.sleep(30 * (attempt + 1))
            continue
        if response.status_code < 500:
            break  # ошибка в запросе, повтор не поможет
        time.sleep(5 * (attempt + 1))

    return {"skip": True, "text": "", "reason": f"Gemini не ответил ({last_error})"}


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
        if isinstance(parsed, dict) and "text" in parsed:
            return {
                "skip": bool(parsed.get("skip", False)),
                "text": (parsed.get("text") or "").strip(),
                "reason": (parsed.get("reason") or "").strip(),
            }

    return {"skip": True, "text": "", "reason": "Gemini вернул неразборчивый ответ"}
