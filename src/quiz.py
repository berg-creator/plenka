"""СЛЕПАЯ ПРОСЛУШКА — викторина по тридцатисекундному отрывку.

Единственная рубрика канала, где от читателя требуется действие, а не чтение.
Пост состоит из двух сообщений: отрывок трека и нативная викторина Telegram
с четырьмя вариантами. Правильный ответ и пояснение Telegram покажет сам,
без нашего участия.

Отрывки — официальные превью iTunes, те самые, что магазин отдаёт всем для
прослушивания. Токенов рубрика не тратит вовсе: все факты берутся из магазина,
придумывать тут нечего.

Главная забота — не проговориться раньше времени. В аудио не уходит ни имя
исполнителя, ни название трека, ни обложка: любое из этого превращает
викторину в объявление ответа.

**Почему викторина в комментариях, а не в канале.** В канале голоса анонимны:
Telegram не говорит боту, кто ответил, и титул знатока выдать было бы некому.
Поэтому отрывок уходит в канал, а викторина — неанонимной в чат обсуждений,
ответом на пересылку поста, и видна под постом как комментарий. Пересылку,
как и для первого комментария (src/comments.py), ловит единственный поллер
src/moderate.py: второй опросчик воровал бы у него события. Дежурство живёт
на другой машине и видит загадку только через git, поэтому она уходит туда
раньше отрывка. Не повесило дежурство опрос за WAIT — викторина уходит в канал
как раньше, анонимной и без титулов: загадка без титула лучше загадки
без вариантов.

**Почему титул на следующий день.** Метка «знаток: Хаски» у угадавшего спалила
бы ответ всем, кто ещё листает комментарии. Поэтому следующий запуск сначала
ставит метки за прошлую загадку и только потом загадывает новую, а голоса
за старую после этого не в счёт: по меткам её угадает кто угодно. Кто угадал —
данные о людях, они лежат в приватном хранилище (config.PRIVATE); в открытом
data/quiz.json — только опрос, варианты и ответ.

    python -m src.quiz                    показать загадку, ничего не отправляя
    python -m src.quiz --target admin     себе в личку: отрывок и викторина, без титулов
    python -m src.quiz --target channel   раздать титулы и загадать новую в канал
    python -m src.quiz --selftest         метки, голоса и угадавшие — без сети
"""

from __future__ import annotations

import argparse
import logging
import os
import random
import re
import shutil
import time
from pathlib import Path

from . import config, state, telegram
from .sources import itunes

log = logging.getLogger("quiz")

STATE_FILE = config.DATA / "quiz.json"
# Кто угадал: пустой файл на человека в папке опроса. Файлы, а не общий JSON:
# угадавших дописывает дежурство, а стирает запуск викторины, и правки одного
# файла с двух машин конфликтовали бы при ребейзе, а новый файл рядом
# с удалёнными — нет.
WINNERS = config.PRIVATE / "quiz"

# Сколько артистов пробуем, прежде чем сдаться: у каждого запроса к магазину
# своя пауза, и перебирать всю базу ради одного поста незачем.
ATTEMPTS = 8
OPTIONS = 4
# Сколько последних загадок помним, чтобы не повторяться.
MEMORY = 60
# Сколько ждём, пока дежурство повесит опрос под пересылкой. Обычно хватает
# полминуты, но дежурство может сидеть над разбором ПРОЯВКИ или меняться сменой.
WAIT = 600

INTRO = (
    "<b>СЛЕПАЯ ПРОСЛУШКА</b>\n\n"
    "30 секунд трека без имени и обложки. Угадай, кто это, — {where}.\n\n"
    "Угадал — выдаём титул главного знатока этого артиста. "
    "Не угадал — поздравляю, у тебя есть личная жизнь."
)
BELOW = "варианты в опросе ниже"
IN_COMMENTS = "варианты — в комментариях"

QUESTION = "Кто это?"

# Метка участника в чате: не больше 16 знаков и без эмодзи (setChatMemberTag).
TITLE = "знаток: "
TAG_LIMIT = 16
_VOWELS = "аеёиоуыэюяaeiouy"


def _used() -> set[str]:
    return set(state.read_json(STATE_FILE, {}).get("used", []))


def _remember(mark: str, **extra) -> None:
    data = state.read_json(STATE_FILE, {})
    data["used"] = (data.get("used", []) + [mark])[-MEMORY:]
    data.update(extra)
    state.write_json(STATE_FILE, data)


def decoys(target: dict, artists: list[dict], count: int = OPTIONS - 1) -> list[str]:
    """Ложные варианты — из соседних сцен, а не наугад.

    Если подставить кого попало, викторина решается методом исключения:
    среди мемфисского рэпа сразу видно случайную поп-звезду. Поэтому берём
    тех, у кого есть общий тег с загаданным, и только если таких не хватило,
    добираем случайными.
    """
    tags = set(target.get("tags", []))
    name = target["name"]

    kin = [a for a in artists if a["name"] != name and tags & set(a.get("tags", []))]
    random.shuffle(kin)
    picked = [a["name"] for a in kin[:count]]

    if len(picked) < count:
        rest = [a["name"] for a in artists if a["name"] != name and a["name"] not in picked]
        random.shuffle(rest)
        picked += rest[: count - len(picked)]

    return picked[:count]


def pick() -> dict | None:
    """Готовит загадку: отрывок, ответ и три ложных варианта."""
    artists = state.read_json(config.ARTISTS_FILE, {"artists": []})["artists"]
    tracked = [a for a in artists if a.get("itunes_id")]
    if not tracked:
        return None

    used = _used()
    random.shuffle(tracked)

    for artist in tracked[:ATTEMPTS]:
        try:
            releases = itunes.recent_releases(artist["itunes_id"], limit=3)
        except Exception as exc:  # noqa: BLE001 — магазин мог не ответить
            log.info("Релизы «%s» не достались: %s", artist["name"], exc)
            continue

        for release in releases:
            album_id = itunes.album_id_from_url(release.get("url", ""))
            if not album_id:
                continue
            try:
                tracks = itunes.album_tracks(album_id).get("tracks", [])
            except Exception as exc:  # noqa: BLE001
                log.info("Треки «%s» не достались: %s", release.get("title", ""), exc)
                continue

            playable = [t for t in tracks if t.get("preview")]
            random.shuffle(playable)
            for track in playable:
                mark = state.fingerprint(artist["name"], track["title"])
                if mark in used:
                    continue

                options = decoys(artist, artists) + [artist["name"]]
                random.shuffle(options)
                return {
                    "artist": artist["name"],
                    "track": track["title"],
                    "album": release.get("title", ""),
                    "year": (release.get("released_at") or "")[:4],
                    "preview": track["preview"],
                    "options": options,
                    "correct": options.index(artist["name"]),
                    "mark": mark,
                }

    return None


def explanation(item: dict) -> str:
    """Пояснение к ответу. Только проверяемые факты из магазина.

    Двести знаков — жёсткий предел Telegram, поэтому ни одного лишнего слова.
    """
    parts = [f"{item['artist']} — «{item['track']}»"]

    # У синглов магазин зовёт альбом так же, как трек, только с приставкой
    # «- Single». Повторять это в пояснении незачем — остаётся один год.
    album = item["album"]
    single = album.casefold().startswith(item["track"].casefold())
    if album and not single:
        parts.append(f"{album}, {item['year']}" if item["year"] else album)
    elif item["year"]:
        parts.append(item["year"])

    return ". ".join(parts)[: telegram.MAX_EXPLANATION]


# ─────────────────────────── титулы ───────────────────────────


def short(name: str, room: int = TAG_LIMIT - len(TITLE)) -> str:
    """Имя артиста, которое влезает в метку вместе с «знаток: », — 8 знаков.

    Режем так, как режут люди, а не по счётчику: «Lil», «Yung» и «The»
    отбрасываются («Uzi Vert», «Prodigy»); из трёх слов и больше остаются
    первые два, если влезли и не кончаются предлогом («Three 6»), иначе
    аббревиатура («RATM», «КиШ»); из двух — имя и инициал («Агата К.»);
    одно длинное слово сокращается по-русски, перед гласной («Скрипт.»).
    Эмодзи метка не принимает, а на «(!)» в восьми знаках места нет.
    """
    words = re.sub(r"[^\w\s$/&'-]|_", " ", name).split()
    if len(" ".join(words)) > room and len(words) > 1 and words[0].casefold() in {"lil", "yung", "the"}:
        words = words[1:]
    if len(" ".join(words)) > room:
        # SpaceGhostPurrp — те же три слова, только слитно.
        words = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", " ".join(words)).split()
    if len(" ".join(words)) <= room:
        return " ".join(words)

    first = words[0]
    if len(words) >= 3:
        pair = " ".join(words[:2])
        if len(pair) <= room and not (words[1].isalpha() and len(words[1]) <= 2):
            return pair
        return "".join(w if w.isupper() or w.isdigit() else w[0] for w in words)[:room]
    if len(words) == 2:
        if len(first) + 3 <= room:
            return f"{first} {words[1][0]}."
        return first if len(first) <= room else (first[0] + words[1][0]).upper()

    stem = first.split("-")[0]  # blink-182
    if 3 <= len(stem) <= room:
        return stem
    cut = re.match(rf"(.{{3,{room - 2}}}[^{_VOWELS}])(?=[{_VOWELS}])", first, re.IGNORECASE)
    return (cut.group(1) if cut else first[: room - 1]) + "."


def title(artist: str) -> str:
    return TITLE + short(artist)


def taggable(member: dict) -> bool:
    """Ставить ли метку этому участнику чата.

    Только обычному участнику: админу Telegram метку так не ставит, а ушедшему
    она ни к чему. Метку, которую человек выбрал себе сам, знаток не затирает —
    это порча, а не награда; прошлый титул новым заменяется.
    """
    tag = member.get("tag") or ""
    return member.get("status") in ("member", "restricted") and (not tag or tag.startswith("знаток"))


def guessed(answer: dict, poll: dict | None) -> int | None:
    """id угадавшего, если голос верный и за текущую загадку, иначе None.

    Голос за загадку, чьи метки уже розданы, не в счёт: её ответ висит рядом
    с именами угадавших. Голос от имени чата (анонимный админ) — тоже: метку
    ставят человеку.
    """
    user = (answer.get("user") or {}).get("id")
    if not user or not poll or answer.get("poll_id") != poll.get("id"):
        return None
    return user if sorted(answer.get("option_ids") or []) == poll.get("correct") else None


def take_answer(answer: dict) -> None:
    """Запоминает угадавшего. Зовёт дежурство (src/moderate.py) на poll_answer."""
    user = guessed(answer, state.read_json(STATE_FILE, {}).get("poll"))
    if user is not None:
        folder = WINNERS / answer["poll_id"]
        folder.mkdir(parents=True, exist_ok=True)
        (folder / str(user)).touch()


def winners(poll: dict | None, folder: Path | None = None) -> list[int]:
    """Угадавшие прошлую загадку. Файлы от более старых опросов не в счёт."""
    if not poll:
        return []
    found = (folder or WINNERS) / str(poll["id"])
    return sorted(int(p.name) for p in found.glob("*") if p.name.isdigit())


def awarded_line(count: int) -> str:
    """Строка под новой загадкой. Без имён: кому надо, увидит метки."""
    people = "человека" if count % 10 == 1 and count % 100 != 11 else "человек"
    return f"Титул знатока за прошлую загадку теперь у {count} {people}."


def award() -> int:
    """Ставит метки угадавшим прошлую загадку. Возвращает, скольким поставили.

    Раздача одна при любом исходе: опрос из quiz.json убирается, список
    угадавших стирается — после неё ответ висит в метках, и угадывать нечего.
    """
    data = state.read_json(STATE_FILE, {})
    poll = data.pop("poll", None)
    people = winners(poll)
    given = 0
    try:
        if not people:
            return 0
        chat, tag = poll["chat"], title(poll["artist"])
        bot = config.secret("TELEGRAM_BOT_TOKEN").split(":")[0]
        if not telegram.chat_member(chat, bot).get("can_manage_tags"):
            log.warning(
                "Титулы не розданы: у бота в чате обсуждений нет права менять метки "
                "участников. Выдай его в правах администратора чата."
            )
            return 0
        for user in people:
            try:
                member = telegram.chat_member(chat, user)
                if not taggable(member):
                    # Без id и без чужой метки: логи открытого репозитория читает кто угодно.
                    log.info("Метку не ставим: %s", "своя метка" if member.get("tag") else member.get("status"))
                    continue
                telegram.set_member_tag(chat, user, tag)
                given += 1
            except Exception as exc:  # noqa: BLE001 — один человек не срывает раздачу остальным
                log.info("Метка не встала: %s", exc)
        log.info("Титул «%s»: %d из %d угадавших", tag, given, len(people))
        return given
    finally:
        state.write_json(STATE_FILE, data)
        shutil.rmtree(WINNERS, ignore_errors=True)


# ─────────────────────────── отправка ───────────────────────────


def _clip(target: str, item: dict, where: str) -> None:
    telegram.send_audio(
        target,
        item["preview"],
        INTRO.format(where=where),
        # Ни имени, ни названия, ни обложки: всё это и есть ответ.
        title=QUESTION,
        performer="ПЛЁНКА",
    )


def _quiz(target: str, item: dict) -> None:
    telegram.send_quiz(target, QUESTION, item["options"], item["correct"], explanation=explanation(item))


def publish(item: dict, target: str) -> None:
    """Отправляет отрывок и следом анонимную викторину: в личку или в канал без чата.

    Двумя сообщениями, а не одним: подпись к аудио и опрос в Telegram
    несовместимы, а опрос без отрывка бессмысленен.
    """
    _clip(target, item, BELOW)
    _quiz(target, item)


def _sync() -> None:
    """Отправляет quiz.json в git и забирает чужое: дежурство живёт на другой
    машине и видит загадку только так. Локально файл у обоих один."""
    if os.environ.get("GITHUB_ACTIONS"):
        from .moderate import _push_repo  # moderate сам импортирует quiz

        _push_repo(config.ROOT, ["data/quiz.json"], "прослушка: загадка")


def to_channel(item: dict, channel: str, awarded: int) -> str:
    """Отрывок — в канал, викторина — под ним в комментарии. Возвращает, где викторина."""
    try:
        linked = telegram.get_chat(channel).get("linked_chat_id")
    except telegram.TelegramError as exc:
        log.warning("Карточка канала не пришла: %s", exc)
        linked = None
    if not linked:
        publish(item, channel)
        _remember(item["mark"])
        return "в канале: чата обсуждений нет"

    _remember(
        item["mark"],
        pending={
            "artist": item["artist"],
            "options": item["options"],
            "correct": item["correct"],
            "explanation": explanation(item),
            "date": state.iso()[:10],
            "awarded": awarded,
        },
    )
    _sync()
    _clip(channel, item, IN_COMMENTS)

    deadline = time.monotonic() + WAIT
    while time.monotonic() < deadline:
        time.sleep(15)
        _sync()
        if "pending" not in state.read_json(STATE_FILE, {}):
            return "в комментариях"

    # ponytail: дежурство может забрать загадку ровно между последней проверкой
    # и этой записью — тогда викторин будет две. Окно в секунды на исходе WAIT;
    # понадобится — замок в git.
    data = state.read_json(STATE_FILE, {})
    data.pop("pending", None)
    state.write_json(STATE_FILE, data)
    _sync()
    _quiz(channel, item)
    return "в канале: дежурство не повесило её под постом"


def is_riddle(message: dict) -> bool:
    """Пересланный в чат отрывок прослушки? Узнаём по подписи — больше в нём ничего нет."""
    return (message.get("caption") or "").startswith("СЛЕПАЯ ПРОСЛУШКА")


def attach(message: dict) -> bool:
    """Вешает викторину под пересланным в чат отрывком. Зовёт дежурство.

    Загадку запуск викторины кладёт в git за секунды до отрывка, а своё дерево
    дежурство подтягивает раз в десять минут, поэтому первым делом — свежий git.
    Не вышло — загадка остаётся в quiz.json, и через WAIT запуск викторины
    отдаст её в канал.
    """
    _sync()
    data = state.read_json(STATE_FILE, {})
    riddle = data.get("pending")
    if not riddle:
        log.info("Под прослушкой вешать нечего: загадку уже отдали в канал")
        return False

    chat, post = message["chat"]["id"], message["message_id"]
    try:
        sent = telegram.send_quiz(
            chat, QUESTION, riddle["options"], riddle["correct"],
            explanation=riddle["explanation"], anonymous=False, reply_to=post,
        )
    except telegram.TelegramError as exc:
        log.warning("Викторина под постом не встала: %s", exc)
        return False

    del data["pending"]
    data["poll"] = {
        "id": sent["poll"]["id"],
        "chat": chat,
        "correct": [riddle["correct"]],
        "artist": riddle["artist"],
        "date": riddle["date"],
    }
    state.write_json(STATE_FILE, data)
    _sync()

    if riddle.get("awarded"):
        try:
            telegram.send_message(chat, awarded_line(riddle["awarded"]), reply_to=post, quiet=True)
        except telegram.TelegramError as exc:
            log.warning("Строка про титулы не ушла: %s", exc)
    return True


def _selftest() -> int:
    """Без сети: метки, кому их ставить, чей голос верный и чей список раздаём.

    Запуск: python -m src.quiz --selftest
    """
    import tempfile

    names = [a["name"] for a in state.read_json(config.ARTISTS_FILE, {"artists": []})["artists"]]
    assert names, "артистов в базе нет"
    for name in names:
        tag = title(name)
        # Длиннее 16 или с эмодзи Telegram метку не примет вовсе.
        assert len(tag) <= TAG_LIMIT and tag != TITLE, (name, tag)
        assert re.fullmatch(r"[\w $/&'.:-]+", tag), (name, tag)
    assert title("Агата Кристи") == "знаток: Агата К."
    assert title("Three 6 Mafia") == "знаток: Three 6"
    assert title("Rage Against The Machine") == "знаток: RATM"
    assert title("Король и Шут") == "знаток: КиШ"
    assert title("Скриптонит") == "знаток: Скрипт."
    assert title("Хаски") == "знаток: Хаски"
    assert title("Bones 🔥") == "знаток: Bones"

    # Метка — обычному участнику; свою не трогаем, прошлый титул меняем.
    assert taggable({"status": "member"})
    assert taggable({"status": "restricted", "tag": "знаток: Bones"})
    assert not taggable({"status": "member", "tag": "мама сказала"})
    assert not taggable({"status": "administrator"})
    assert not taggable({"status": "left"})

    poll = {"id": "77", "correct": [2]}
    assert guessed({"poll_id": "77", "user": {"id": 5}, "option_ids": [2]}, poll) == 5
    assert guessed({"poll_id": "77", "user": {"id": 5}, "option_ids": [1]}, poll) is None
    assert guessed({"poll_id": "76", "user": {"id": 5}, "option_ids": [2]}, poll) is None
    assert guessed({"poll_id": "77", "voter_chat": {"id": -1}, "option_ids": [2]}, poll) is None
    assert guessed({"poll_id": "77", "user": {"id": 5}, "option_ids": [2]}, None) is None

    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        for poll_id, user in (("77", 9), ("77", 5), ("76", 3)):
            (folder / poll_id).mkdir(exist_ok=True)
            (folder / poll_id / str(user)).touch()
        assert winners(poll, folder) == [5, 9]
        assert winners({"id": "78"}, folder) == []
        assert winners(None, folder) == []

    assert awarded_line(1).endswith("у 1 человека.")
    assert awarded_line(3).endswith("у 3 человек.")
    assert awarded_line(11).endswith("у 11 человек.")
    assert awarded_line(21).endswith("у 21 человека.")
    # Дежурство узнаёт пересылку по подписи: разметку Telegram переносит в entities.
    assert is_riddle({"caption": re.sub(r"<[^>]+>", "", INTRO.format(where=IN_COMMENTS))})
    assert IN_COMMENTS in INTRO.format(where=IN_COMMENTS)
    print("прослушка: все проверки прошли")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Слепая прослушка")
    parser.add_argument("--preview", action="store_true", help="показать, не отправляя")
    parser.add_argument(
        "--target",
        choices=["admin", "channel"],
        help="куда отправлять: admin — себе в личку, channel — в канал, с титулами",
    )
    parser.add_argument("--selftest", action="store_true", help="проверки без сети")
    args = parser.parse_args()

    if args.selftest:
        return _selftest()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    config.load_dotenv()

    # Сначала титулы за прошлую загадку: под новой напишем, скольким досталось.
    awarded = 0
    if args.target == "channel":
        try:
            awarded = award()
        except Exception as exc:  # noqa: BLE001 — титулы не повод остаться без загадки
            log.error("Титулы не розданы: %s", exc)

    item = pick()
    if not item:
        print("Не нашлось трека с отрывком — попробуй позже.")
        return 1

    print(f"\nОтвет:    {item['artist']} — {item['track']}")
    print(f"Варианты: {', '.join(item['options'])}")
    print(f"Верный:   {item['correct'] + 1}")
    print(f"Пояснение: {explanation(item)}")
    print(f"Титул:    {title(item['artist'])}")
    print(f"Отрывок:  {item['preview'][:60]}…")

    if not args.target:
        print("\nОтправить себе: python -m src.quiz --target admin")
        return 0

    if args.target == "admin":
        publish(item, config.secret("TELEGRAM_ADMIN_ID"))
        _remember(item["mark"])
        print("\nОтправлено: в личку.")
        return 0

    where = to_channel(item, config.secret("TELEGRAM_CHANNEL_ID"), awarded)
    print(f"\nОтправлено: отрывок в канал, викторина {where}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
