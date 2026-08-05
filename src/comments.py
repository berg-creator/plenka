"""Первый комментарий под постом канала.

Когда к каналу привязан чат обсуждений, Telegram сам пересылает туда каждый
пост, и ответы на эту пересылку показываются под постом как комментарии.
Пустая ветка комментариев работает против канала: писать первым не хочет никто,
а «0 комментариев» под каждым постом читается как «здесь никого нет».

Поэтому первым пишет сам канал — одной репликой с конкретным вопросом.
Вопрос берётся из готового набора по рубрике, а не сочиняется моделью:
токены он бы тратил как полноценный пост, а работы делает на одну строку.

Отключается одной строкой в src/config.py — COMMENT_SEED.
"""

from __future__ import annotations

import logging
import random
from datetime import timedelta

from . import config, state, telegram

log = logging.getLogger("comments")

# Вопросы под постом. Разные по рубрикам: под мемом уместно одно, под разбором
# другое. Каждый — про содержание поста, а не «а вы что думаете, друзья».
QUESTIONS: dict[str, tuple[str, ...]] = {
    "lineage": (
        "кидайте свои: что ещё оказалось старше, чем вы думали",
        "кто знал про эту связь до поста — признавайтесь",
        "с чего начали копать вы? у всех своя первая такая ниточка",
    ),
    "verdict": (
        "не согласны — пишите. но с доводами, а не «сам ты»",
        "кто дослушал до конца, отзовитесь",
        "ваш вердикт этому релизу — одной строкой",
    ),
    "release": (
        "кто уже включил — как оно?",
        "стоит того или мимо?",
        "какой трек оттуда оставите в плейлисте",
    ),
    "news": (
        "ваши ставки, чем это кончится",
        "кто-нибудь удивлён? я нет",
        "как думаете, это надолго",
    ),
    "meme": (
        "узнали кого-нибудь?",
        "кто это, но с вами",
        "у кого такой друг есть",
    ),
    "subtext": (
        "у кого другая трактовка — скидывайте",
        "что вы слышали в этих строчках",
        "какие строчки разобрать в следующий раз",
    ),
    "legend": (
        "кто помнит, где впервые это услышал",
        "ваша любимая вещь у него — какая",
        "кому это попало вовремя, а кому поздно",
    ),
}

DEFAULT_QUESTIONS = (
    "что думаете — пишите сюда",
    "у кого есть что добавить",
)

# Насколько свежей должна быть запись о публикации, чтобы считать, что
# пересланный в чат пост — это именно она.
MATCH_WINDOW = timedelta(minutes=30)


def question(rubric: str) -> str:
    return random.choice(QUESTIONS.get(rubric, DEFAULT_QUESTIONS))


def last_rubric() -> str:
    """Рубрика последнего опубликованного поста.

    Пересылка в чат приходит через секунды после публикации, а посты выходят
    раз в несколько часов — этого хватает, чтобы связать одно с другим без
    отдельного журнала. Если запись старая, рубрику не угадываем.
    """
    items = state.read_json(config.POSTED_FILE, {"items": []}).get("items", [])
    if not items:
        return ""

    last = items[-1]
    published = state._parse(last.get("published_at", ""))
    if published is None or state.now() - published > MATCH_WINDOW:
        return ""
    return last.get("rubric", "")


def is_channel_post(message: dict, channel_id: int | str) -> bool:
    """Это автоматическая пересылка поста нашего канала в чат обсуждений?"""
    if not message.get("is_automatic_forward"):
        return False
    sender = message.get("sender_chat") or {}
    return str(sender.get("id", "")) == str(channel_id) or (
        f"@{sender.get('username', '')}" == str(channel_id)
    )


def seed(message: dict) -> bool:
    """Пишет первый комментарий под пересланным постом. True — написали."""
    chat_id = str(message.get("chat", {}).get("id", ""))
    message_id = message.get("message_id")
    if not chat_id or not message_id:
        return False

    # Опрос сам по себе способ высказаться — под ним вопрос лишний.
    rubric = last_rubric()
    if rubric == "poll":
        return False

    try:
        telegram.send_message(chat_id, question(rubric), reply_to=message_id)
    except telegram.TelegramError as exc:
        # Бота могли не пустить в чат или разжаловать — пост от этого не страдает.
        log.warning("Первый комментарий не ушёл: %s", exc)
        return False

    log.info("Первый комментарий под постом рубрики «%s»", rubric or "неизвестной")
    return True
