"""Первый комментарий под постом канала.

Когда к каналу привязан чат обсуждений, Telegram сам пересылает туда каждый
пост, и ответы на эту пересылку показываются под постом как комментарии.
Пустая ветка комментариев работает против канала: писать первым не хочет никто,
а «0 комментариев» под каждым постом читается как «здесь никого нет».

Поэтому первым пишет сам канал — одной репликой с конкретным вопросом.
Вопрос пишет модель по тексту вышедшего поста (prompts/rubrics/comment.md).
Раньше он брался из готового набора по рубрике, чтобы не тратить токены
на одну строку, и набор себя не оправдал: три вопроса на рубрику повторялись
через пост, а общий вопрос не подходил к частному посту — под синглом Pouya
спросили, «какой трек оттуда» оставить (владелец, 16.09.2026). Вопрос пишется
в момент выхода, а не вместе с постом: так он есть и у постов, написанных
до этого решения, и у срочных. Набор остался запасным — на случай, когда
генератор не ответил или не нашёл вопроса про этот пост.

Под постом о релизе этой репликой идёт сам трек, присланный владельцем: вопрос
уходит ему в подпись. В ленте плеер занимал вторую плитку и делал вид поста
плавающим — есть трек, два сообщения; нет, одно (решение владельца 12.09.2026).
В ветке он и открывает обсуждение, и даёт послушать, не уводя из канала.

У поста о сниппете сам кусок трека — ролик из паблика, откуда пришёл инфоповод, —
встаёт в пост вместо фото (into_post, владелец 24.09.2026): комментарий из ленты
не видно, и пост читался как «сниппета нет». Здесь, а не при выходе, потому что
большой ролик качает только аккаунт владельца, а его ключ живёт в дежурстве.
Своего файла у канала тут нет и быть не может: трек неизданный, взять его негде.
Ссылку Telegram отдаёт с временным ключом, поэтому файл качается в момент
отправки (telegram_web.preview_video), а не при сборе. Большого ролика превью
не отдаёт вовсе — его качает аккаунт владельца. Пост без фото ролик не примет —
тогда он идёт первым комментарием; не скачался вовсе — под постом остаётся вопрос.

Под постом о релизе без трека вопроса нет: «кому первому включаете, Крису
или Блэку?» под постом, где включать нечего, владелец назвал бредом (18.09.2026).
Ветку пост запоминает полем thread — трек, скачанный позже (Mac владельца спал),
встаёт туда первым комментарием (moderate.attach_track).

Под разбором и новостью первым комментарием — что послушать (владелец, 01.10.2026:
«послушать нечего»): треки концов связи, корень и наследник, или трек релиза, который
назвала новость. Они лежат в посте списком listen и идут тем же путём, что трек релиза
(tracks.pieces). Файл к выходу не пришёл — трек встаёт ссылками на площадки, тем же видом,
что «Слушать» в посте о релизе, а файл, скачанный позже, — в ту же ветку. В самом посте
от этого только строка «что послушать — в комментариях» (publish.track_note): пост
остаётся одной плиткой.

Разборы, вышедшие до этого решения, получают тот же комментарий задним числом (old,
запуск руками — comments.yml): ветку вышедшего поста бот из апдейтов уже не узнает,
пересылка давно пришла, а открытая страница виджета обсуждения называет её без входа
в аккаунт (thread_of). Вопрос под такими постами уже стоит, поэтому вторым комментарием
идут одни треки. В дежурстве этого прохода нет намеренно: он разовый, а состояние всё
равно пишет Actions.

Отключается одной строкой в src/config.py — COMMENT_SEED.
"""

from __future__ import annotations

import argparse
import contextlib
import html
import io
import logging
import random
import re
import tempfile
import time
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

from . import config, llm, publish, state, telegram, tracks
from .sources import telegram_web
from .sources.http import get

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
    # Под релизом лежит один трек, а сам релиз чаще сингл: вопрос «какой трек
    # оттуда» спрашивал про альбом, которого в посте нет (16.09.2026).
    "release": (
        "кто уже включил — как оно?",
        "стоит того или мимо?",
        "оставите в плейлисте?",
    ),
    "news": (
        "ваши ставки, чем это кончится",
        "кто-нибудь удивлён? я нет",
        "как думаете, это надолго",
    ),
    # Под сниппетом лежит сам кусок трека, и вопрос спрашивает про звук,
    # а не про новость: рубрика у такого поста всё равно ИНФОПОВОД.
    "snippet": (
        "норм звучит?",
        "берём или мимо?",
        "ждём целиком или и так понятно",
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
    # Под постом отбора лежит трек артиста, и сам он читает ветку первым.
    "otbor": (
        "что скажете артисту — честно",
        "кто дослушал до конца — отметьтесь",
        "что бы вы поменяли в этом треке",
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
# пересланный в чат пост — это именно она. Годится только для постов, у которых
# в архиве нет номера сообщения: обычно связь точная, по нему.
MATCH_WINDOW = timedelta(minutes=30)

# Сколько ждать, пока публикатор закоммитит архив: шаг и число попыток.
# Публикация целиком укладывается в полминуты, минуты хватает с запасом.
WAIT_STEP = timedelta(seconds=15)
WAIT_TRIES = 4


# Под треком отбора — опрос: послушал и тут же отметился, не выходя из ветки.
# Анонимный: «не моё» под треком человека, которого знаешь, вслух не ставят.
OTBOR_POLL = ("Как вам трек?", ["🔥 Огонь", "👍 Норм", "😐 Не моё"])

# Длиннее вопрос не нужен: он стоит подписью под плеером, а не абзацем.
MAX_QUESTION = 120


def question(rubric: str) -> str:
    return random.choice(QUESTIONS.get(rubric, DEFAULT_QUESTIONS))


def ask(post: dict, rubric: str, attached: str = "") -> str:
    """Вопрос по тексту поста, а если не вышло — из готового набора рубрики."""
    try:
        answer = llm.generate_comment({
            "rubric": rubric, "text": post.get("text", ""), "artist": post.get("artist", ""),
            "release": post.get("release", ""), "attached": attached,
        })
    except Exception as exc:  # noqa: BLE001 — без вопроса модели остаётся набор
        log.warning("Вопрос под постом не написан: %s", exc)
        answer = {"skip": True}
    text = " ".join((answer.get("text") or "").split())
    # Разметка и простыня в подписи — брак ответа, а не вопрос.
    if answer.get("skip") or not text or "<" in text or len(text) > MAX_QUESTION:
        return question(rubric)
    return text


def heard(piece: dict) -> str:
    """Трек под разбором, пока файла нет: имя и площадки строкой, как «Слушать» в посте о релизе."""
    name = html.escape(f"{piece['artist']} — {piece['track']}")
    link = html.escape(piece.get("url") or "https://www.deezer.com/")
    return publish.listen(f'<b>{name}</b>\n▸ <a href="{link}">Слушать</a>', piece["artist"], piece["track"])


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
        return {**post, "rubric": item.get("rubric", ""), "file": item.get("file", "")}

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
    files = [piece["full_track_file_id"] for piece in tracks.pieces(post) if piece.get("full_track_file_id")]
    track = files[0] if files else ""
    # Треки под разбором и новостью, к которым файл не пришёл: встают ссылками на площадки.
    missing = [piece for piece in post.get("listen") or [] if not piece.get("full_track_file_id")]
    links = "\n\n".join(heard(piece) for piece in missing)
    # Сниппет живёт в чужом посте, и ссылку на файл Telegram выдаёт с временным
    # ключом — качаем его сейчас, а не при сборе: между сбором и выходом поста
    # проходят часы. Большого файла превью не отдаёт — его качает аккаунт
    # владельца; не вышло и так — остаётся вопрос.
    source = post.get("source_url", "")
    with tempfile.TemporaryDirectory() as folder:
        snippet = ((telegram_web.preview_video(source, Path(folder))
                    or telegram_web.account_video(source, Path(folder)))
                   if (post.get("snippet") or post.get("video")) and not track else {})
        # Под тизером спрашиваем о новости, а не «как вам сниппет».
        about = ("snippet", "сниппет") if post.get("snippet") else (rubric, "ролик")
        try:
            if track:
                # Вопрос — подписью под первым плеером; у разбора их два, корень и наследник.
                for number, file in enumerate(files):
                    telegram.send_audio(chat_id, file, "" if number else ask(post, rubric, "трек"), reply_to=message_id)
                if rubric == "otbor":
                    try:
                        poll = telegram.send_poll(chat_id, *OTBOR_POLL, reply_to=message_id) or {}
                        if post.get("file") and poll.get("message_id"):
                            # Опрос считается (otbor.final): итог бита недели закрывает его по этому номеру.
                            path = config.ARCHIVE / post["file"]
                            state.write_json(path, {**state.read_json(path, {}),
                                                    "poll": {"chat": chat_id, "message_id": poll["message_id"]}})
                    except telegram.TelegramError as exc:
                        # Трек уже в ветке — без опроса она всё равно живая.
                        log.warning("Опрос под отбором не ушёл: %s", exc)
            elif snippet and into_post(post, snippet, message):
                telegram.send_message(chat_id, ask(post, *about), reply_to=message_id)
            elif snippet:
                telegram.send_video_file(chat_id, snippet["path"], ask(post, *about),
                                         seconds=snippet["seconds"], width=snippet["width"],
                                         height=snippet["height"], reply_to=message_id)
            elif rubric in config.RELEASE_RUBRICS and post.get("file"):
                # Трек ещё придёт: запоминаем ветку, туда он и встанет первым.
                path = config.ARCHIVE / post["file"]
                state.write_json(path, {**state.read_json(path, {}),
                                        "thread": {"chat": chat_id, "message_id": message_id}})
                log.info("Под постом о релизе ждём трек: %s", post["file"])
                return True
            else:
                # У ролика вопрос для спора уже написан в сценарии (src/reels.py) — модель не нужна.
                telegram.send_message(chat_id, "\n\n".join(filter(None, (links, post.get("comment") or ask(post, rubric)))),
                                      reply_to=message_id)
                links = ""
            if links:
                telegram.send_message(chat_id, links, reply_to=message_id)
            if missing and post.get("file"):
                # Файл ещё придёт (Mac владельца спал): запоминаем ветку, как у релиза.
                path = config.ARCHIVE / post["file"]
                state.write_json(path, {**state.read_json(path, {}),
                                        "thread": {"chat": chat_id, "message_id": message_id}})
        except telegram.TelegramError as exc:
            # Бота могли не пустить в чат или разжаловать — пост от этого не страдает.
            log.warning("Первый комментарий не ушёл: %s", exc)
            return False

    log.info("Первый комментарий под постом рубрики «%s»", rubric or "неизвестной")
    return True


def into_post(post: dict, snippet: dict, message: dict) -> bool:
    """Ставит сниппет в сам пост вместо фото. True — встал.

    Первым комментарием ролик из ленты не видно, и пост «показали сниппет»
    с картинкой читался как пост без сниппета (владелец, 24.09.2026). Подпись
    берётся из пересылки вместе с разметкой — слово в слово как в канале.
    Текстовый пост ролик не примет: Telegram меняет медиа только на медиа.
    """
    where = post.get("message") or {}
    if not (message.get("photo") and where.get("chat") and where.get("message_id")):
        return False
    try:
        telegram.edit_video(where["chat"], where["message_id"], snippet["path"], message.get("caption", ""),
                            entities=message.get("caption_entities"), seconds=snippet["seconds"],
                            width=snippet["width"], height=snippet["height"], buttons=where.get("buttons"))
    except telegram.TelegramError as exc:
        log.warning("Сниппет в пост не встал, уходит комментарием: %s", exc)
        return False
    return True


# Страница виджета обсуждения открыта без входа: в форме ответа лежат чат обсуждений
# (peer, «c<id>_<ключ>») и номер пересылки поста в нём — та самая ветка.
WIDGET = "https://t.me/{channel}/{post}?embed=1&discussion=1"
_PEER = re.compile(r'name="peer" value="c(\d+)_')
_TOP = re.compile(r'name="top_msg_id" value="(\d+)"')

# Пауза между постами прохода: в один чат Telegram пускает 20 сообщений в минуту.
OLD_PAUSE = 3.5


def widget(post_id: int) -> str:
    """Страница виджета обсуждения под постом канала; пусто — не открылась."""
    response = get(WIDGET.format(channel=config.CHANNEL_HANDLE.lstrip("@"), post=post_id), min_interval=0.5)
    return response.text if response is not None else ""


def thread_of(page: str) -> dict:
    """Ветка комментариев по странице виджета: {chat, message_id}, как её запоминает seed, или {}.

    У удалённого поста и поста без обсуждения формы ответа на странице нет — ветки нет.
    """
    peer, top = _PEER.search(page), _TOP.search(page)
    return {"chat": f"-100{peer.group(1)}", "message_id": int(top.group(1))} if peer and top else {}


def old(post_id: int = 0, dry_run: bool = False) -> int:
    """Треки комментарием под вышедшими разборами, у которых его нет. Возвращает, под сколькими встал.

    Берутся посты архива со связью (link — id в lineage.json), которых путь listen ещё
    не касался: ни listen, ни thread. Треки — концы связи, подтверждённые магазином
    (compose._heard); связь без трека и пост без ветки пропускаются, пустого комментария нет.
    Сначала строка в пост, потом комментарий, запись в архив — последней: что бы ни
    сорвалось, повтор доделывает, а не дублирует. Правка, уже стоящая в канале, — не отказ,
    а комментарий, уже видный на странице виджета (запуск оборвался до коммита), второй
    раз не шлётся. Беззвучно: это 30 сообщений в чат задним числом.
    """
    # Здесь, а не сверху: compose тянет сбор и карточки, а дежурству, которое грузит
    # этот модуль на каждой смене, они ради разового прохода не нужны.
    from . import compose

    links = {link.get("id"): link for link in state.read_json(config.LINEAGE_FILE, {}).get("links", [])}
    done = 0
    for path in sorted(config.ARCHIVE.glob("*.json")):
        post = state.read_json(path, {})
        number = (post.get("message") or {}).get("message_id")
        ends = (links.get(post.get("link")) or {}).get("ends") or []
        if not number or not ends or post.get("listen") or post.get("thread") or post_id not in (0, number):
            continue
        listen = [track for track in map(compose._heard, ends) if track]
        page = widget(number) if listen else ""
        thread = thread_of(page)
        if not thread:
            print(f"{number} · {path.name} · пропуск: {'ветки обсуждения нет' if listen else 'трека у связи нет'}")
            continue
        # ponytail: виджет отдаёт последние комментарии, не все; под постом их единицы —
        # станут десятки, искать свой придётся по страницам (data-before).
        there = publish.LISTEN_HEAD in page
        print(f"{number} · {path.name} · ветка {thread['message_id']} · связь {post['link']}"
              + (" · комментарий уже стоит" if there else ""))
        for piece in listen:
            print(f"    {piece['artist']} — {piece['track']} · {piece['url']}")
        if dry_run:
            continue
        post = {**post, "listen": listen, "thread": thread}
        try:
            try:
                publish.edit(post)
            except telegram.TelegramError as exc:
                if "message is not modified" not in str(exc):
                    raise
            if not there:
                telegram.send_message(thread["chat"], "\n\n".join(map(heard, listen)),
                                      reply_to=thread["message_id"], quiet=True)
        except telegram.TelegramError as exc:
            print(f"{number} · не вышло, архив не тронут: {exc}")
            continue
        state.write_json(path, post)
        done += 1
        time.sleep(OLD_PAUSE)
    return done


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
    # Сниппет встаёт в пост ролик из паблика, и файл качается
    # в момент отправки: при сборе ключ в ссылке был бы уже просроченным.
    sent: list[tuple] = []
    posted = [{"file": "s.json", "rubric": "news", "published_at": state.iso()}]
    snippet = {"message": {"chat": -200, "message_id": 200}, "snippet": True,
               "source_url": "https://t.me/rapsmi/1"}
    state.read_json = lambda path, default=None: (
        {"items": posted} if path == real_posted else snippet)
    real_video, real_msg = telegram_web.preview_video, telegram.send_message
    real_account, real_file = telegram_web.account_video, telegram.send_video_file
    real_comment, real_edit = llm.generate_comment, telegram.edit_video
    real_audio, real_poll = telegram.send_audio, telegram.send_poll
    llm.generate_comment = lambda payload: {"skip": True}
    telegram.edit_video = lambda chat, msg, path, caption, **_: sent.append(("в пост", path.name, caption))
    telegram_web.preview_video = lambda url, folder: {
        "path": folder / "preview.mp4", "seconds": 11, "width": 576, "height": 768}
    telegram.send_message = lambda chat, text, reply_to=None, **_: sent.append(("вопрос", text))
    telegram.send_video_file = lambda chat, path, caption, reply_to=None, **_: sent.append(("файл", path.name))
    forwarded = {"chat": {"id": -100}, "message_id": 5, "forward_from_message_id": 200}
    try:
        # Пост с фото: ролик встаёт вместо фото, подпись та же, в комментарии — вопрос.
        assert seed({**forwarded, "photo": [{}], "caption": "Подпись"})
        assert sent[0] == ("в пост", "preview.mp4", "Подпись") and sent[1][0] == "вопрос", sent
        # Тизер из поста издания встаёт так же, хоть он и не сниппет.
        sent.clear()
        snippet.pop("snippet")
        snippet["video"] = True
        assert seed({**forwarded, "photo": [{}], "caption": "Подпись"}) and sent[0][0] == "в пост", sent
        snippet.pop("video")
        snippet["snippet"] = True
        # Текстовый пост медиа не примет — ролик уходит комментарием.
        sent.clear()
        assert seed(forwarded)
        assert sent == [("файл", "preview.mp4")], sent
        # Большого ролика превью не отдаёт — его качает аккаунт, а без аккаунта
        # остаётся обычный вопрос.
        sent.clear()
        telegram_web.preview_video = lambda url, folder: {}
        telegram_web.account_video = lambda url, folder: {
            "path": folder / "snippet.mp4", "seconds": 51, "width": 720, "height": 1280}
        assert seed(forwarded) and sent == [("файл", "snippet.mp4")], sent
        sent.clear()
        telegram_web.account_video = lambda url, folder: {}
        assert seed(forwarded) and sent[0][0] == "вопрос", sent
        # Отбор: трек артиста первым, опрос — следом, в ту же ветку.
        sent.clear()
        posted[0]["rubric"] = "otbor"
        snippet = {"message": {"chat": -200, "message_id": 200}, "full_track_file_id": "T"}
        telegram.send_audio = lambda chat, track, caption, reply_to=None, **_: sent.append(("трек", track))
        telegram.send_poll = lambda chat, question, options, reply_to=None, **_: sent.append(
            ("опрос", question, reply_to))
        assert seed(forwarded) and sent == [("трек", "T"), ("опрос", OTBOR_POLL[0], 5)], sent
        # Опрос считается: его номер и чат ложатся в файл поста — по ним итог бита недели закрывает опрос.
        real_write, written = state.write_json, []
        state.write_json = lambda path, payload: written.append((path.name, payload.get("poll")))
        telegram.send_poll = lambda chat, question, options, reply_to=None, **_: {"message_id": 77}
        assert seed(forwarded) and written == [("s.json", {"chat": "-100", "message_id": 77})], written
        state.write_json = real_write
        # Разбор: файлов нет — первым комментарием треки обоих концов связи ссылками
        # на площадки и вопрос, одним сообщением; ветка запоминается под поздний файл.
        sent.clear()
        posted[0]["rubric"] = "lineage"
        root = {"artist": "Three 6 Mafia", "track": "Late Nite Tip", "url": "https://www.deezer.com/track/1"}
        heir = {"artist": "Bones", "track": "HDMI", "url": "https://www.deezer.com/track/2"}
        snippet = {"message": {"chat": -200, "message_id": 200}, "listen": [root, heir]}
        real_write, written = state.write_json, []
        state.write_json = lambda path, payload: written.append((path.name, payload.get("thread")))
        assert seed(forwarded) and len(sent) == 1 and sent[0][0] == "вопрос", sent
        text = sent[0][1]
        assert text.index("Three 6 Mafia — Late Nite Tip") < text.index("Bones — HDMI") < text.rindex("\n\n"), text
        assert 'href="https://www.deezer.com/track/1">Deezer' in text and text.count(publish.LISTEN_HEAD) == 2, text
        assert written == [("s.json", {"chat": "-100", "message_id": 5})], written
        # Один файл пришёл: он плеером с вопросом, второй трек — ссылками следом.
        sent.clear()
        root["full_track_file_id"] = "R"
        assert seed(forwarded) and sent[0] == ("трек", "R") and "Bones — HDMI" in sent[1][1], sent
        assert "Late Nite Tip" not in sent[1][1] and len(sent) == 2, sent
        # Оба файла на месте: два плеера, ссылок и запомненной ветки нет.
        sent.clear(), written.clear()
        heir["full_track_file_id"] = "H"
        assert seed(forwarded) and sent == [("трек", "R"), ("трек", "H")] and not written, (sent, written)
        state.write_json = real_write
    finally:
        telegram.send_audio, telegram.send_poll = real_audio, real_poll
        state.read_json = real_read
        telegram_web.preview_video = real_video
        telegram_web.account_video, telegram.send_video_file = real_account, real_file
        telegram.send_message, telegram.edit_video = real_msg, real_edit
        llm.generate_comment = real_comment

    # Вопрос пишет модель по посту; брак ответа и отказ сети уводят в набор рубрики.
    post = {"text": "<b>POUYA ЗАПИСАЛ ТРЕК</b>", "artist": "Pouya"}
    for answer, expected in (
        ({"skip": False, "text": " кого из пятерых\nвы знали? "}, "кого из пятерых вы знали?"),
        ({"skip": True, "text": "что думаете?"}, None),
        ({"skip": False, "text": "<b>вопрос</b>"}, None),
        ({"skip": False, "text": "а" * (MAX_QUESTION + 1)}, None),
        (RuntimeError("сеть"), None),
    ):
        def fake(payload, answer=answer):
            assert payload["attached"] == "трек" and payload["artist"] == "Pouya"
            if isinstance(answer, Exception):
                raise answer
            return answer
        llm.generate_comment = fake
        got = ask(post, "release", "трек")
        assert got == expected if expected else got in QUESTIONS["release"], (answer, got)
    llm.generate_comment = real_comment

    # Ветка вышедшего поста — из формы ответа на странице виджета (кусок страницы поста 26,
    # 01.10.2026); у удалённого поста формы нет.
    form = ('<form class="tgme_post_discussion_new_message_form js-new_message_form"> '
            '<input type="hidden" name="peer" value="c3946355526_-2511569901370190638" /> '
            '<input type="hidden" name="top_msg_id" value="8" /> '
            '<input type="hidden" name="discussion_hash" value="8912b1e24ef425e5f1" /> </form>')
    assert thread_of(form) == {"chat": "-1003946355526", "message_id": 8}, thread_of(form)
    assert thread_of('<div class="tme_no_messages_found">Discussion is not available at the moment.</div>') == {}

    # Старые разборы: трек — конец связи своего поста; без связи, без трека, без ветки
    # и уже с веткой пост не трогается; стоящий комментарий второй раз не шлётся.
    from . import compose
    lineage = {"links": [
        {"id": "a", "ends": [{"artist": "Bones", "track": "HDMI", "url": "d/1"}, {"artist": "Xavier Wulf"}]},
        {"id": "b", "ends": [{"artist": "Salem"}]},
        {"id": "c", "ends": [{"artist": "Korn", "track": "Blind", "url": "d/2"}]}]}
    archive = {
        "1.json": {"link": "a", "message": {"message_id": 11}},
        "2.json": {"link": "b", "message": {"message_id": 12}},
        "3.json": {"link": "https://rap.ru/новость", "message": {"message_id": 13}},
        "4.json": {"link": "c", "message": {"message_id": 14}, "thread": {"chat": "-1", "message_id": 4}},
        "5.json": {"link": "c", "message": {"message_id": 15}},
        "6.json": {"link": "c", "message": {"message_id": 16}},
        "7.json": {"link": "c", "message": {"message_id": 17}},
    }
    pages = {11: form, 15: "", 16: form + publish.LISTEN_HEAD, 17: form}
    real = (state.read_json, state.write_json, compose._heard, publish.edit, telegram.send_message, time.sleep)
    real_widget, real_archive = globals()["widget"], config.ARCHIVE
    sent, edited, written = [], [], []

    class Folder:
        def glob(self, _):
            return [Path(name) for name in archive]

    def edit(post):
        edited.append(post["message"]["message_id"])
        if edited[-1] == 16:
            raise telegram.TelegramError("Bad Request: message is not modified")
        if edited[-1] == 17:
            raise telegram.TelegramError("Bad Request: not enough rights")

    config.ARCHIVE = Folder()
    state.read_json = lambda path, default=None: lineage if path == config.LINEAGE_FILE else archive[path.name]
    state.write_json = lambda path, payload: written.append((path.name, payload["listen"], payload["thread"]))
    compose._heard = lambda end: {**end, "seconds": 200} if end.get("track") else {}
    publish.edit = edit
    telegram.send_message = lambda chat, text, reply_to=None, quiet=False, **_: sent.append((chat, text, reply_to, quiet))
    time.sleep = lambda _: None
    globals()["widget"] = lambda number: pages[number]
    try:
        with contextlib.redirect_stdout(io.StringIO()):  # список постов прохода самопроверке не нужен
            assert old(dry_run=True) == 0 and not (sent or edited or written), (sent, edited, written)
            assert old() == 2, (sent, edited, written)
        assert edited == [11, 16, 17] and [name for name, *_ in written] == ["1.json", "6.json"], (edited, written)
        assert len(sent) == 1 and sent[0][0] == "-1003946355526" and sent[0][2:] == (8, True), sent
        assert "Bones — HDMI" in sent[0][1] and "Korn" not in sent[0][1] and "Xavier" not in sent[0][1], sent
        assert written[0][1:] == ([{"artist": "Bones", "track": "HDMI", "url": "d/1", "seconds": 200}],
                                  {"chat": "-1003946355526", "message_id": 8}), written
        sent.clear()
        with contextlib.redirect_stdout(io.StringIO()):
            assert old(post_id=12) == 0 and old(post_id=14) == 0 and not sent, sent
    finally:
        (state.read_json, state.write_json, compose._heard, publish.edit, telegram.send_message, time.sleep) = real
        globals()["widget"], config.ARCHIVE = real_widget, real_archive

    print("первый комментарий: пост находится по номеру пересылки, сниппет уходит роликом, "
          "под треком отбора опрос, его номер — в файле поста, "
          "под разбором — треки концов связи файлами или ссылками, "
          "вопрос пишется по посту, а брак ответа уводит в запасной набор; "
          "ветка старого поста читается со страницы виджета, треки под старым разбором — "
          "свои, один раз и не под постом без связи, трека или ветки")


def main() -> int:
    parser = argparse.ArgumentParser(description="Первый комментарий под постом канала")
    parser.add_argument("--selftest", action="store_true", help="проверка без сети")
    parser.add_argument("--old", action="store_true",
                        help="треки комментарием под вышедшими разборами, у которых его нет (из Actions: comments.yml)")
    parser.add_argument("--post", type=int, default=0, help="с --old: только пост канала с этим номером")
    parser.add_argument("--dry-run", action="store_true", help="с --old: что ушло бы, без отправки и записи")
    args = parser.parse_args()
    if args.old:
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        print(f"Постов с новым комментарием: {old(args.post, args.dry_run)}")
        return 0
    _selftest()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
