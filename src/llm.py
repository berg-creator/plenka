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

from . import config, state
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

# СКЛЕЙКА (src/skleyka.py): просьба словами — в значения тех же ручек, что у кнопок.
# Пределы код держит сам (skleyka.heard), здесь они — подсказка модели: ГигаЧат
# строгих схем не принимает и видит только описания полей.
SKLEYKA_SCHEMA = {
    "type": "object",
    "properties": {
        "style": {"type": "string", "description": "Стиль: чисто, мелодично, грязно или близко"},
        "design": {"type": "boolean", "description": "Саунд-дизайн: true — включён"},
        "voice": {"type": "number", "description": "Голос к биту, дБ, от -6 до 6"},
        "echo": {"type": "number", "description": "Эхо — отзвук и повторы вместе, дБ, от -12 до 8"},
        "at": {"type": "number",
               "description": "С какой секунды бита входит первое слово голоса; -1 — как в присланном файле"},
        "like": {"type": "string",
                 "description": "К чьему треку подтянуть тембр, ширину и громкость: «Артист» или «Артист — Трек»; пусто — ни к чьему"},
        "reply": {"type": "string", "description": "Ответ человеку: что сделал или чего не умею, 1–3 фразы до 300 знаков"},
    },
    "required": ["style", "design", "voice", "echo", "at", "like", "reply"],
    "additionalProperties": False,
}

# Схема ответа по рубрике; кого здесь нет, тот отвечает POST_SCHEMA.
SCHEMAS = {"meme": MEME_SCHEMA}

# Модель Gemini. Поколения сменяются каждые пару месяцев, поэтому имя берётся
# из окружения: что доступно по ключу, показывает python -m src.check_llm.
# Не новейшая намеренно: 20.09.2026 на бесплатном тарифе gemini-3.8-flash
# ответила 0 раз из 5 («high demand»), 3.7-flash — 0 из 3, а 3.5-flash — 5 из 5.
# Свежие модели там перегружены, и канал уходил бы на запасной генератор.
GEMINI_MODEL_DEFAULT = "gemini-3.5-flash"
# Кто пишет, когда у основной модели кончились бесплатные 20 запросов в сутки:
# квота у каждой модели своя (см. src/providers/gemini.py). Перегруженные 20.09
# свежие модели идут за основной, облегчённая 3.1-flash-lite — последней.
GEMINI_SPARE = ("gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.8-flash", "gemini-3.1-flash-lite")


def gemini_model() -> str:
    return os.environ.get("GEMINI_MODEL", "").strip() or GEMINI_MODEL_DEFAULT


def gemini_models() -> list[str]:
    first = gemini_model()
    return [first, *(m for m in GEMINI_SPARE if m != first)]


def provider() -> str:
    return os.environ.get("LLM_PROVIDER", "gemini").strip().lower()


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
        return gemini.generate(gemini_models(), voice(), user, schema)
    return gigachat.generate(voice(), user, schema)


def _generate(user: str, schema: dict = POST_SCHEMA) -> dict:
    """Запрос к основному генератору, при отказе — к запасному.

    Исключение здесь всегда означает «провайдер недоступен»: сеть, ключ, лимит,
    пятисотка. Осознанный отказ модели приходит как skip=true и запасного
    не поднимает — если Клод счёл материал негодным, ГигаЧат тем более.
    """
    primary = provider()
    try:
        answer = _call(primary, user, schema)
    except Exception as exc:
        spare = fallback()
        if not spare:
            raise
        log.warning("Генератор %s недоступен (%s). Пишет запасной — %s.", primary, exc, spare)
        answer = _call(spare, user, schema)
        _note(spare)
        return answer
    _note(primary)
    return answer


def _note(name: str) -> None:
    """Отметка в журнале: кто написал этот текст.

    Запасной генератор подхватывает молча — в логе запуска остаётся строка
    WARNING, которую никто не читает, и канал незаметно возвращается на тот
    генератор, ради ухода от которого переход и делался. Отметка ставится
    здесь, а не при сохранении поста: через _generate проходит всё — посты,
    разборы в боте, раскадровки, — и сторожу важна доля, а не рубрика.
    Журнал дописывается в конец (data/*.jsonl, merge=union), поэтому
    одновременные запуски на GitHub не дерутся за него.
    """
    try:
        state.append_jsonl(config.LLM_LOG, [{"at": state.iso(), "llm": name}])
    except OSError as exc:  # журнал не повод терять готовый текст
        log.warning("Не записался журнал генератора: %s", exc)


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


def generate_skleyka(payload: dict) -> dict:
    """Просьба человека к готовой склейке — в новые значения ручек (prompts/skleyka.md)."""
    return _generate(
        f"{(config.PROMPTS / 'skleyka.md').read_text(encoding='utf-8')}\n\n"
        f"## Данные\n\n"
        f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```\n\n"
        f"Верни ручки по правилам выше: о чём не просили — как в knobs.",
        SKLEYKA_SCHEMA,
    )


def generate_comment(payload: dict) -> dict:
    """Первый комментарий под вышедшим постом: вопрос по его тексту (src/comments.py).

    Схема та же, что у постов: вопрос уходит в поле text, а skip значит
    «кроме общего вопроса ничего не выходит» — тогда берётся готовый набор.
    """
    return _generate(
        f"{rubric_prompt('comment')}\n\n"
        f"## Пост\n\n"
        f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```\n\n"
        f"Напиши вопрос по правилам выше. Не выходит вопроса про этот пост — "
        f"верни skip=true и причину одной строкой."
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
        "gemini": f"Google {gemini_model()} (бесплатный тариф)",
        "anthropic": f"Anthropic {claude.MODEL} (платный)",
    }.get(key, key)


def short_name(key: str) -> str:
    """Коротко, как пишут владельцу: «Gemini», «GigaChat»."""
    return {"gigachat": "GigaChat", "gemini": "Gemini", "anthropic": "Claude"}.get(key, key)


def describe() -> str:
    """Человекочитаемое название генераторов — для логов и отчётов."""
    spare = fallback()
    if not spare:
        return _name(provider())
    return f"{_name(provider())}, запасной — {_name(spare)}"
