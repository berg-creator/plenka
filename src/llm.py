"""Генерация текстов. Провайдер выбирается переменной LLM_PROVIDER.

    LLM_PROVIDER=gigachat    GigaChat от Сбера — работает в России (по умолчанию)
    LLM_PROVIDER=gemini      Google Gemini 2.5 Pro — бесплатно, но не в России
    LLM_PROVIDER=anthropic   Claude Opus — платно, тоже недоступен в России

Рубрики и промпты от провайдера не зависят: смена одной строки в .env
меняет генератор целиком, ничего больше править не нужно.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache

from . import config
from .providers import claude, gemini, gigachat

# Ответ модели жёстко ограничен схемой — разбирать свободный текст не приходится.
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

GEMINI_MODEL = "gemini-2.5-pro"


def provider() -> str:
    return os.environ.get("LLM_PROVIDER", "gigachat").strip().lower()


def supports_batch() -> bool:
    """Батч есть только у Claude. Gemini бесплатен — там он не нужен."""
    return provider() == "anthropic"


@lru_cache(maxsize=1)
def voice() -> str:
    return (config.PROMPTS / "voice.md").read_text(encoding="utf-8")


@lru_cache(maxsize=16)
def rubric_prompt(key: str) -> str:
    path = config.PROMPTS / "rubrics" / f"{key}.md"
    if not path.exists():
        raise FileNotFoundError(f"Нет промпта рубрики: {path}")
    return path.read_text(encoding="utf-8")


@lru_cache(maxsize=8)
def service_prompt(kind: str) -> str:
    """Промпт разбора для бота-сервиса. Лежит отдельно от рубрик канала:
    там пост для всех, здесь ответ конкретному человеку."""
    path = config.PROMPTS / "service" / f"{kind}.md"
    if not path.exists():
        raise FileNotFoundError(f"Нет промпта разбора: {path}")
    return path.read_text(encoding="utf-8")


def generate_service(kind: str, payload: dict) -> dict:
    """Разбор по запросу человека. Схема ответа та же, что у постов:
    провайдеру всё равно, а нам не нужен второй разборщик ответа."""
    user = (
        f"{service_prompt(kind)}\n\n"
        f"## Данные запроса\n\n"
        f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```\n\n"
        f"Напиши разбор по правилам выше и голосу канала. "
        f"Если данных не хватает — верни skip=true и причину одной строкой."
    )
    name = provider()
    if name == "anthropic":
        return claude.generate(voice(), user, POST_SCHEMA)
    if name == "gemini":
        return gemini.generate(GEMINI_MODEL, voice(), user, POST_SCHEMA)
    return gigachat.generate(voice(), user, POST_SCHEMA)


def build_user_prompt(rubric_key: str, payload: dict) -> str:
    return (
        f"{rubric_prompt(rubric_key)}\n\n"
        f"## Данные для этого поста\n\n"
        f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```\n\n"
        f"Напиши пост по правилам рубрики и голосу канала. "
        f"Если материала не хватает или он не тянет на публикацию — верни skip=true."
    )


def generate_now(rubric_key: str, payload: dict) -> dict:
    user = build_user_prompt(rubric_key, payload)
    name = provider()
    if name == "anthropic":
        return claude.generate(voice(), user, POST_SCHEMA)
    if name == "gemini":
        return gemini.generate(GEMINI_MODEL, voice(), user, POST_SCHEMA)
    return gigachat.generate(voice(), user, POST_SCHEMA)


def submit_batch(jobs: list[tuple[str, str, dict]]) -> str:
    """jobs — список (custom_id, ключ рубрики, данные). Только для Claude."""
    if not supports_batch():
        raise RuntimeError("Батч доступен только при LLM_PROVIDER=anthropic")
    prepared = [
        (custom_id, voice(), build_user_prompt(key, payload), POST_SCHEMA)
        for custom_id, key, payload in jobs
    ]
    return claude.submit_batch(prepared)


def batch_status(batch_id: str) -> str:
    return claude.batch_status(batch_id)


def fetch_batch(batch_id: str) -> dict[str, dict]:
    return claude.fetch_batch(batch_id)


def describe() -> str:
    """Человекочитаемое название текущего генератора — для логов и отчётов."""
    return {
        "gigachat": f"Сбер {gigachat.model_name()}",
        "gemini": f"Google {GEMINI_MODEL} (бесплатный тариф)",
        "anthropic": f"Anthropic {claude.MODEL} (платный)",
    }.get(provider(), provider())
