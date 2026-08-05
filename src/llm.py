"""Обёртка над Claude API.

Две особенности, ради которых существует этот модуль:

1. Тон канала (prompts/voice.md) отправляется как кэшируемый system-промпт.
   Он одинаков во всех запросах, поэтому повторные вызовы читают его из кэша
   примерно за 10% цены вместо полной.

2. Посты генерируются через Batch API — это вдвое дешевле обычных запросов.
   Батч готовится минуты-часы, но посты и не нужны сию секунду: они всё равно
   лежат в очереди и публикуются по расписанию.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

import anthropic

from . import config

# Схема ответа: модель обязана вернуть ровно эти поля, парсить свободный текст не нужно.
POST_SCHEMA = {
    "type": "object",
    "properties": {
        "skip": {
            "type": "boolean",
            "description": "true, если материал не тянет на пост — тогда text пустой",
        },
        "text": {
            "type": "string",
            "description": "Готовый текст поста с HTML-разметкой Telegram",
        },
        "reason": {
            "type": "string",
            "description": "Если skip=true — одной строкой почему",
        },
    },
    "required": ["skip", "text", "reason"],
    "additionalProperties": False,
}


@lru_cache(maxsize=1)
def voice() -> str:
    return (config.PROMPTS / "voice.md").read_text(encoding="utf-8")


@lru_cache(maxsize=16)
def rubric_prompt(key: str) -> str:
    path = config.PROMPTS / "rubrics" / f"{key}.md"
    if not path.exists():
        raise FileNotFoundError(f"Нет промпта рубрики: {path}")
    return path.read_text(encoding="utf-8")


def client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=config.secret("ANTHROPIC_API_KEY"))


def system_blocks() -> list[dict]:
    """System-промпт с точкой кэширования на конце."""
    return [
        {
            "type": "text",
            "text": voice(),
            "cache_control": {"type": "ephemeral"},
        }
    ]


def build_request(rubric_key: str, payload: dict) -> dict:
    """Параметры одного запроса — годятся и для батча, и для обычного вызова."""
    user_text = (
        f"{rubric_prompt(rubric_key)}\n\n"
        f"## Данные для этого поста\n\n"
        f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```\n\n"
        f"Напиши пост по правилам рубрики и голосу канала. "
        f"Если материала не хватает или он не тянет на публикацию — верни skip=true."
    )
    return {
        "model": config.MODEL,
        "max_tokens": 8000,
        "system": system_blocks(),
        "messages": [{"role": "user", "content": user_text}],
        "output_config": {"format": {"type": "json_schema", "schema": POST_SCHEMA}},
    }


def generate_now(rubric_key: str, payload: dict) -> dict:
    """Синхронная генерация — для отладки и срочного пополнения очереди.

    Дороже батча вдвое, поэтому в рабочем цикле не используется.
    """
    response = client().messages.create(**build_request(rubric_key, payload))
    return _extract(response)


def submit_batch(jobs: list[tuple[str, str, dict]]) -> str:
    """Отправляет пачку заданий. jobs — список (custom_id, rubric_key, payload).

    Возвращает id батча, по которому позже забираются результаты.
    """
    requests_payload = [
        {"custom_id": custom_id, "params": build_request(rubric_key, payload)}
        for custom_id, rubric_key, payload in jobs
    ]
    batch = client().messages.batches.create(requests=requests_payload)
    return batch.id


def batch_status(batch_id: str) -> str:
    return client().messages.batches.retrieve(batch_id).processing_status


def fetch_batch(batch_id: str) -> dict[str, dict]:
    """Забирает результаты готового батча: custom_id → разобранный ответ."""
    results: dict[str, dict] = {}
    for entry in client().messages.batches.results(batch_id):
        if entry.result.type != "succeeded":
            results[entry.custom_id] = {
                "skip": True,
                "text": "",
                "reason": f"ошибка генерации: {entry.result.type}",
            }
            continue
        results[entry.custom_id] = _extract(entry.result.message)
    return results


def _extract(message: Any) -> dict:
    """Достаёт JSON из ответа. Схема гарантирует структуру, но подстраховка нужна."""
    for block in message.content:
        if getattr(block, "type", None) == "text":
            try:
                data = json.loads(block.text)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and "text" in data:
                return {
                    "skip": bool(data.get("skip", False)),
                    "text": (data.get("text") or "").strip(),
                    "reason": (data.get("reason") or "").strip(),
                }
    return {"skip": True, "text": "", "reason": "модель вернула неразборчивый ответ"}
