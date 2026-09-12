"""Первый комментарий под постом канала.

Когда к каналу привязан чат обсуждений, Telegram сам пересылает туда каждый
пост, и ответы на эту пересылку показываются под постом как комментарии.
Пустая ветка комментариев работает против канала: писать первым не хочет никто,
а «0 комментариев» под каждым постом читается как «здесь никого нет».

Поэтому первым пишет сам канал — одной репликой с конкретным вопросом.
Вопрос берётся из готового набора по рубрике, а не сочиняется моделью:
токены он бы тратил как полноценный пост, а работы делает на одну строку.

Под постом о релизе этой репликой идёт сам трек, присланный владельцем: вопрос
уходит ему в подпись. В ленте плеер занимал вторую плитку и делал вид поста
плавающим — есть трек, два сообщения; нет, одно (решение владельца 12.09.2026).
В ветке он и открывает обсуждение, и даёт послушать, не уводя из канала.

Отключается одной строкой в src/config.py — COMMENT_SEED.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from datetime import timedelta

from . import config, state, telegram

log = logging.getLogger("comments")

# Вопросы под постом. Разные по рубрикам: под мемом уместно одно, под разбором
# другое. Каждый — про содержание поста, а не «а вы что думаете, друзья».
# Пишутся с заглавной и с нормальными знаками в конце: строчная буква
# и потерянный вопросительный знак читаются как неряшливость, а не как свой
# тон (замечание владельца от 12.09.2026).
QUESTIONS: dict[str, tuple[str, ...]] = {
    "lineage": (
        "Кидайте свои: что ещё оказалось старше, чем вы думали?",
        "Кто знал про эту связь до поста — признавайтесь.",
        "С чего начали копать вы? У всех своя первая такая ниточка.",
    ),
    "verdict": (
        "Не согласны — пишите. Но с доводами, а не «сам ты».",
        "Кто дослушал до конца, отзовитесь.",
        "Ваш вердикт этому релизу — одной строкой?",
    ),
    "release": (
        "Кто уже включил — как оно?",
        "Стоит того или мимо?",
        "Какой трек оттуда оставите в плейлисте?",
    ),
    "news": (
        "Ваши ставки, чем это кончится?",
        "Кто-нибудь удивлён? Я нет.",
        "Как думаете, это надолго?",
    ),
    "meme": (
        "Узнали кого-нибудь?",
        "Кто это, но с вами?",
        "У кого такой друг есть?",
    ),
    "subtext": (
        "У кого другая трактовка — скидывайте.",
        "Что вы слышали в этих строчках?",
        "Какие строчки разобрать в следующий раз?",
    ),
    "legend": (
        "Кто помнит, где впервые это услышал?",
        "Ваша любимая вещь у него — какая?",
        "Кому это попало вовремя, а кому поздно?",
    ),
}

DEFAULT_QUESTIONS = (
    "Что думаете — пишите сюда.",
    "У кого есть что добавить?",
)

# Насколько свежей должна быть запись о публикации, чтобы считать, что
# пересланный в чат пост — это именно она. Годится только для постов, у которых
# в архиве нет номера сообщения: обычно связь точная, по нему.
MATCH_WINDOW = timedelta(minutes=30)

# Сколько ждать, пока публикатор закоммитит архив: шаг и число попыток.
# Публикация целиком укладывается в полминуты, минуты хватает с запасом.
WAIT_STEP = timedelta(seconds=15)
WAIT_TRIES = 4


def question(rubric: str) -> str:
    return random.choice(QUESTIONS.get(rubric, DEFAULT_QUESTIONS))


def origin_id(message: dict) -> int | None:
    """Номер поста в канале, пересылку которого мы получили."""
    origin = message.get("forward_origin") or {}
    return message.get("forward_from_message_id") or origin.get("message_id")


def last_post(post_id: int | None = None) -> dict:
    """Пост, к которому относится пересылка: рубрика из журнала, сам он — из архива.

    Пересылка называет номер поста в канале, а публикатор кладёт этот номер
    в архив (`message.message_id`) — по нему пост и ищется. Раньше связь шла
    по времени, и запоздавшее дежурство под постом полугодовой давности
    ничего бы не нашло.

    Номера нет (старый пост в архиве без него) — берём последний
    опубликованный, но только если он совсем свежий.
    """
    items = state.read_json(config.POSTED_FILE, {"items": []}).get("items", [])
    if not items:
        return {}

    def load(item: dict) -> dict:
        # Из журнала берётся только рубрика, а полный трек — из самого поста.
        post = state.read_json(config.ARCHIVE / item.get("file", ""), {})
        return {**post, "rubric": item.get("rubric", "")}

    if post_id:
        # Смотрим последние: архив за год перебирать незачем, пересылка
        # приходит через секунды после публикации.
        for item in reversed(items[-20:]):
            post = load(item)
            if post.get("message", {}).get("message_id") == post_id:
                return post
        return {}

    last = items[-1]
    published = state._parse(last.get("published_at", ""))
    if published is None or state.now() - published > MATCH_WINDOW:
        return {}
    return load(last)


def is_channel_post(message: dict, channel_id: int | str) -> bool:
    """Это автоматическая пересылка поста нашего канала в чат обсуждений?"""
    if not message.get("is_automatic_forward"):
        return False
    sender = message.get("sender_chat") or {}
    return str(sender.get("id", "")) == str(channel_id) or (
        f"@{sender.get('username', '')}" == str(channel_id)
    )


def seed(message: dict, refresh: Callable[[], None] | None = None) -> bool:
    """Пишет первый комментарий под пересланным постом. True — написали.

    `refresh` подтягивает состояние из репозитория между попытками найти пост:
    пересылка приходит через три секунды после публикации, а публикатор
    коммитит архив к двадцатой — без ожидания трек владельца под постом
    не появлялся вовсе, уходил один голый вопрос (поймано 12.09.2026).
    """
    chat_id = str(message.get("chat", {}).get("id", ""))
    message_id = message.get("message_id")
    if not chat_id or not message_id:
        return False

    # Опрос сам по себе способ высказаться — под ним вопрос лишний.
    post = last_post(origin_id(message))
    for _ in range(WAIT_TRIES):
        if post or refresh is None:
            break
        # ponytail: дежурство на эту минуту замолкает. Пересылок 4-8 в сутки,
        # отдельный поток тут дороже задержки; станет мешать — выносить в очередь.
        time.sleep(WAIT_STEP.seconds)
        refresh()
        post = last_post(origin_id(message))
    rubric = post.get("rubric", "")
    if rubric == "poll" or message.get("poll"):
        return False

    # Полный трек от владельца уходит сюда же — плеером, с вопросом в подписи.
    # В ленте он занимал вторую плитку и делал вид поста плавающим (есть трек —
    # два сообщения, нет — одно), а здесь открывает ветку и даёт послушать,
    # не уводя из канала. Не ушёл — остаётся обычный вопрос.
    track = post.get("full_track_file_id", "")
    try:
        if track:
            telegram.send_audio(chat_id, track, question(rubric), reply_to=message_id)
        else:
            telegram.send_message(chat_id, question(rubric), reply_to=message_id)
    except telegram.TelegramError as exc:
        # Бота могли не пустить в чат или разжаловать — пост от этого не страдает.
        log.warning("Первый комментарий не ушёл: %s", exc)
        return False

    log.info("Первый комментарий под постом рубрики «%s»", rubric or "неизвестной")
    return True


def _selftest() -> None:
    """Пересылка находит свой пост по номеру, а не по времени."""
    forward = {"forward_origin": {"type": "channel", "message_id": 106}}
    assert origin_id(forward) == 106
    assert origin_id({"forward_from_message_id": 105}) == 105
    assert origin_id({}) is None

    items = [{"file": "a.json", "rubric": "release", "published_at": "2020-01-01T00:00:00+00:00"},
             {"file": "b.json", "rubric": "verdict", "published_at": "2020-01-01T00:00:00+00:00"}]
    posts = {"a.json": {"message": {"message_id": 105}, "full_track_file_id": "A"},
             "b.json": {"message": {"message_id": 106}, "full_track_file_id": "B"}}
    real_read, real_posted = state.read_json, config.POSTED_FILE
    state.read_json = lambda path, default=None: (
        {"items": items} if path == real_posted else posts.get(path.name, {}))
    try:
        # Старая связь по времени тут бы промолчала: посты 2020 года.
        assert last_post(106)["full_track_file_id"] == "B"
        assert last_post(105)["rubric"] == "release"
        assert last_post(999) == {}
        assert last_post() == {}
    finally:
        state.read_json = real_read
    # Реплика бота пишется как нормальная фраза: заглавная в начале, знак
    # в конце. 12.09.2026 владелец увидел в чате «кто уже включил — как оно?»
    # с маленькой буквы и без точки в соседних — это читается неряшливо.
    for rubric_lines in (*QUESTIONS.values(), DEFAULT_QUESTIONS):
        for line in rubric_lines:
            assert line[0].isupper() and line[-1] in ".?", line

    print("первый комментарий: пост находится по номеру пересылки")


if __name__ == "__main__":
    _selftest()
