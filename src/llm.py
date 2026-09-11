"""Генерация текстов. Провайдер выбирается переменной LLM_PROVIDER.

    LLM_PROVIDER=anthropic   Claude Opus — платно, пишет лучше всех (по умолчанию)
    LLM_PROVIDER=gigachat    GigaChat от Сбера — работает в России
    LLM_PROVIDER=gemini      Google Gemini 2.5 Pro — бесплатно, но не в России

Второй переменной, LLM_FALLBACK, задаётся запасной генератор: если основной
не ответил — кончились деньги, отвалилась сеть, упал сам сервис — пост пишет
он, и канал не встаёт. По умолчанию это GigaChat: он работает из России
и оплачивается отдельно от Клода, так что общей точки отказа у них нет.

Рубрики и промпты от провайдера не зависят: смена одной строки в .env
меняет генератор целиком, ничего больше править не нужно.
"""

from __future__ import annotations

import json
import logging
import os
from functools import lru_cache

from . import config
from .providers import claude, gemini, gigachat

log = logging.getLogger("llm")

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

# Ролики отвечают не постом, а раскадровкой: что говорит голос и что стоит
# на экране (см. src/clips.py). Схема отдельная, потому что разбирать
# короткие строки обратно из готового текста поста было бы гаданием.
CLIP_SCHEMA = {
    "type": "object",
    "properties": {
        "skip": {
            "type": "boolean",
            "description": "true, если из новости ролика не выйдет — остальные поля пустые",
        },
        "artist": {
            "type": "string",
            "description": "Имя артиста ровно как в списке known — по нему ищется фотография",
        },
        "lines": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Ровно три фразы закадрового голоса",
        },
        "labels": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Ровно три надписи на экран, по два-три слова",
        },
        "reason": {
            "type": "string",
            "description": "Если skip=true — одной строкой почему",
        },
    },
    "required": ["skip", "artist", "lines", "labels", "reason"],
    "additionalProperties": False,
}

# Мем — картинка с надписью и подпись под ней, поэтому отвечает он не одним
# текстом, а полями: что написать на шаблоне сверху и снизу, какой шаблон
# взять из списка pictures (каталог data/memes.json) и что сказать под фото.
# Схема отдельная, а не поля в POST_SCHEMA: остальным рубрикам картинка
# не нужна, а лишнее поле в их ответе — лишний повод модели его заполнить.
# Порядок полей — порядок мысли: сначала шутка на картинке, потом подпись.
MEME_SCHEMA = {
    "type": "object",
    "properties": {
        "skip": POST_SCHEMA["properties"]["skip"],
        "top": {
            "type": "string",
            "description": "Надпись на картинке сверху — подводка, до 40 знаков; может быть пустой",
        },
        "bottom": {
            "type": "string",
            "description": "Надпись на картинке снизу — поворот, до 40 знаков; может быть пустой",
        },
        "picture": {
            "type": "string",
            "description": "Ключ картинки ровно как в списке pictures",
        },
        "text": {
            "type": "string",
            "description": "Подпись под картинкой — своя короткая реплика канала, не повтор надписи",
        },
        "reason": POST_SCHEMA["properties"]["reason"],
    },
    "required": ["skip", "top", "bottom", "picture", "text", "reason"],
    "additionalProperties": False,
}

# Схема ответа по рубрике; кого здесь нет, тот отвечает POST_SCHEMA.
SCHEMAS = {"meme": MEME_SCHEMA}

GEMINI_MODEL = "gemini-2.5-pro"


def provider() -> str:
    return os.environ.get("LLM_PROVIDER", "anthropic").strip().lower()


def fallback() -> str:
    """Запасной генератор. Пустая строка — фоллбека нет, ошибка идёт наверх."""
    spare = os.environ.get("LLM_FALLBACK", "gigachat").strip().lower()
    return "" if spare == provider() else spare


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


def _call(name: str, user: str, schema: dict) -> dict:
    """Один запрос к конкретному провайдеру. Голос канала одинаков для всех."""
    if name == "anthropic":
        return claude.generate(voice(), user, schema)
    if name == "gemini":
        return gemini.generate(GEMINI_MODEL, voice(), user, schema)
    return gigachat.generate(voice(), user, schema)


def _generate(user: str, schema: dict = POST_SCHEMA) -> dict:
    """Запрос к основному генератору, при отказе — к запасному.

    Исключение здесь всегда означает «провайдер недоступен»: сеть, ключ, лимит,
    пятисотка. Осознанный отказ модели приходит как skip=true и запасного
    не поднимает — если Клод счёл материал негодным, ГигаЧат тем более.
    """
    primary = provider()
    try:
        return _call(primary, user, schema)
    except Exception as exc:
        spare = fallback()
        if not spare:
            raise
        log.warning("Генератор %s недоступен (%s). Пишет запасной — %s.", primary, exc, spare)
        return _call(spare, user, schema)


def generate_service(kind: str, payload: dict) -> dict:
    """Разбор по запросу человека. Схема ответа та же, что у постов:
    провайдеру всё равно, а нам не нужен второй разборщик ответа."""
    return _generate(
        f"{service_prompt(kind)}\n\n"
        f"## Данные запроса\n\n"
        f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```\n\n"
        f"Напиши разбор по правилам выше и голосу канала. "
        f"Если данных не хватает — верни skip=true и причину одной строкой."
    )


def generate_clip(payload: dict) -> dict:
    """Раскадровка новостного ролика: что сказать голосом, что вывести на экран.

    Границы достоверности тут жёстче, чем у поста: строки читают вслух,
    и выдуманная цифра в ролике стоит дороже пропущенной. Правила — в
    prompts/rubrics/clip_news.md, сборка — в src/clips.py.
    """
    return _generate(
        f"{rubric_prompt('clip_news')}\n\n"
        f"## Новость\n\n"
        f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```\n\n"
        f"Сделай раскадровку по правилам выше. Ничего сверх заголовка и краткого "
        f"содержания не добавляй. Если новость пустая — верни skip=true и причину "
        f"одной строкой.",
        CLIP_SCHEMA,
    )


def build_user_prompt(rubric_key: str, payload: dict) -> str:
    return (
        f"{rubric_prompt(rubric_key)}\n\n"
        f"## Данные для этого поста\n\n"
        f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```\n\n"
        f"Напиши пост по правилам рубрики и голосу канала. "
        f"Если материала не хватает или он не тянет на публикацию — верни skip=true."
    )


def generate_now(rubric_key: str, payload: dict) -> dict:
    return _generate(build_user_prompt(rubric_key, payload), SCHEMAS.get(rubric_key, POST_SCHEMA))


def submit_batch(jobs: list[tuple[str, str, dict]]) -> str:
    """jobs — список (custom_id, ключ рубрики, данные). Только для Claude."""
    if not supports_batch():
        raise RuntimeError("Батч доступен только при LLM_PROVIDER=anthropic")
    prepared = [
        (custom_id, voice(), build_user_prompt(key, payload), SCHEMAS.get(key, POST_SCHEMA))
        for custom_id, key, payload in jobs
    ]
    return claude.submit_batch(prepared)


def batch_status(batch_id: str) -> str:
    return claude.batch_status(batch_id)


def fetch_batch(batch_id: str) -> dict[str, dict]:
    return claude.fetch_batch(batch_id)


def _name(key: str) -> str:
    return {
        "gigachat": f"Сбер {gigachat.model_name()}",
        "gemini": f"Google {GEMINI_MODEL} (бесплатный тариф)",
        "anthropic": f"Anthropic {claude.MODEL} (платный)",
    }.get(key, key)


def describe() -> str:
    """Человекочитаемое название генераторов — для логов и отчётов."""
    spare = fallback()
    if not spare:
        return _name(provider())
    return f"{_name(provider())}, запасной — {_name(spare)}"
