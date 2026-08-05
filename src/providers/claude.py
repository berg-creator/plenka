"""Провайдер Anthropic Claude — платный, с батч-режимом и кэшированием промпта.

Включается переключателем LLM_PROVIDER=anthropic. Нужен, если захочется
сравнить качество текстов с бесплатным провайдером.
"""

from __future__ import annotations

import json
from typing import Any

import anthropic

from .. import config

MODEL = "claude-opus-5"


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=config.secret("ANTHROPIC_API_KEY"))


def _params(system: str, user: str, schema: dict) -> dict:
    return {
        "model": MODEL,
        "max_tokens": 8000,
        # Точка кэширования: тон канала одинаков во всех запросах и на повторных
        # вызовах читается примерно за десятую часть цены.
        "system": [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ],
        "messages": [{"role": "user", "content": user}],
        "output_config": {"format": {"type": "json_schema", "schema": schema}},
    }


def generate(system: str, user: str, schema: dict) -> dict:
    response = _client().messages.create(**_params(system, user, schema))
    return parse_message(response)


def submit_batch(jobs: list[tuple[str, str, str, dict]]) -> str:
    """jobs — список (custom_id, system, user, schema). Возвращает id батча."""
    payload = [
        {"custom_id": custom_id, "params": _params(system, user, schema)}
        for custom_id, system, user, schema in jobs
    ]
    return _client().messages.batches.create(requests=payload).id


def batch_status(batch_id: str) -> str:
    return _client().messages.batches.retrieve(batch_id).processing_status


def fetch_batch(batch_id: str) -> dict[str, dict]:
    results: dict[str, dict] = {}
    for entry in _client().messages.batches.results(batch_id):
        if entry.result.type != "succeeded":
            results[entry.custom_id] = {
                "skip": True,
                "text": "",
                "reason": f"ошибка генерации: {entry.result.type}",
            }
            continue
        results[entry.custom_id] = parse_message(entry.result.message)
    return results


def parse_message(message: Any) -> dict:
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
