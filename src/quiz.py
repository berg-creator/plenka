"""СЛЕПАЯ ПРОСЛУШКА — викторина по тридцатисекундному отрывку.

Единственная рубрика канала, где от читателя требуется действие, а не чтение.
Пост состоит из двух сообщений: отрывок трека и нативная викторина Telegram
с четырьмя вариантами. Правильный ответ и пояснение Telegram покажет сам,
без нашего участия.

Отрывки — официальные превью iTunes, те самые, что магазин отдаёт всем для
прослушивания. Токенов рубрика не тратит вовсе: все факты берутся из магазина,
придумывать тут нечего.

**Почему не свежее и не хит** (владелец, 08.10.2026: загадка была очевидной).
До этого дня отрывок брался из трёх последних релизов случайного артиста базы —
их подписчик и так слышал. Теперь загадывается русскоязычный артист, релиз —
из старой половины его дискографии, альбом раньше сингла: голос и звук там
ещё другие. Треки из самых слушаемых у него на Deezer мимо, как и фиты, ремиксы
и скиты: в их отрывке мог звучать не он. Ложные варианты — на языке ответа,
иначе лишних вычёркивает язык, а не слух, и того же голоса: женский среди
мужских слышно сразу (поле `voice` базы). Иностранный артист — примерно в каждой
пятой загадке. «Голос другой» кодом не измерить,
а год релиза и место среди хитов — измерить, поэтому отбор стоит на них.

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
данные о людях, они лежат в приватном хранилище (config.PRIVATE). Там же сама
загадка и опрос под ней: из открытого репозитория ответ подсмотрел бы кто
угодно, поэтому в data/quiz.json остаются только отпечатки прошлых загадок.

**По воскресеньям — «где ИИ»** (src/quiz_ai.py, владелец 27.09.2026): видео
из четырёх кусков, один из выпущенного ИИ-трека, та же викторина в комментариях,
титул «слышит ИИ». Раунды готовит Mac заранее; запас пуст или метка ИИ
не подтвердилась — в воскресенье выходит обычная загадка про артиста.
Ответ в лог Actions не пишется ни для одной из загадок: лог открытого
репозитория читает кто угодно.

    python -m src.quiz                    показать загадку, ничего не отправляя
    python -m src.quiz --target admin     себе в личку: отрывок и викторина, без титулов
    python -m src.quiz --target channel   раздать титулы и загадать новую в канал
    python -m src.quiz --ai --target admin   «где ИИ» из запаса себе в личку, обе версии видео
    python -m src.quiz --selftest         метки, голоса и угадавшие — без сети
"""

from __future__ import annotations

import argparse
import logging
import os
import random
import re
import shutil
import subprocess
import time
from pathlib import Path

from . import config, quiz_ai, state, telegram
from .sources import deezer, itunes

log = logging.getLogger("quiz")

STATE_FILE = config.DATA / "quiz.json"
# Загадка до пересылки и опрос под ней — там же, где угадавшие: открытый
# репозиторий читает кто угодно, и ответ лежал бы в нём весь день.
RIDDLE = config.PRIVATE / "quiz.json"
# Кто угадал: пустой файл на человека в папке опроса. Файлы, а не общий JSON:
# угадавших дописывает дежурство, а стирает запуск викторины, и правки одного
# файла с двух машин конфликтовали бы при ребейзе, а новый файл рядом
# с удалёнными — нет.
WINNERS = config.PRIVATE / "quiz"

# Сколько артистов пробуем, прежде чем сдаться: у каждого запроса к магазину
# своя пауза, и перебирать всю базу ради одного поста незачем.
ATTEMPTS = 8
OPTIONS = 4
# Сколько релизов просить у магазина — предел его lookup: загадке нужна вся дискография.
DEPTH = 200
# Сколько релизов одного артиста перебрать, прежде чем взять другого.
RELEASES = 3
# Доля загадок про иностранных артистов: «иногда» владельца — примерно одна в неделю.
ABROAD = 0.2
# Столько самых слушаемых треков артиста загадкой не идут.
HITS = 25
# Короче — скит или вступление: голоса в отрывке может не быть.
MIN_SECONDS = 60
# Гость, чужая обработка и трек без слов: в отрывке звучал бы не тот, кого загадали.
UNFAIR = re.compile(
    r"\b(feat|ft|skit|intro|outro|interlude|instrumental|remix|live"
    r"|скит|интро|аутро|инструментал|ремикс)\b",
    re.IGNORECASE,
)
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


def _remember(mark: str | None) -> None:
    # У «где ИИ» отпечатка нет: раунд уходит из запаса, а отпечаток ИИ-трека
    # в открытом файле подбирался бы по списку ИИ-треков раньше ответа.
    if not mark:
        return
    data = state.read_json(STATE_FILE, {})
    data["used"] = (data.get("used", []) + [mark])[-MEMORY:]
    state.write_json(STATE_FILE, data)


def _ru(artist: dict) -> bool:
    """Русскоязычный: метка базы или кириллица в имени — у пришедших в базу самих меток нет."""
    tags = artist.get("tags", [])
    return any(t == "ru" or t.startswith("ru-") for t in tags) or bool(re.search("[а-яё]", artist["name"].casefold()))


def _plain(title: str) -> str:
    """Название без скобок и знаков: два магазина пишут один трек по-разному."""
    return " ".join(re.sub(r"\(.*?\)|\[.*?\]|[^\w\s]", " ", title.casefold()).split())


def deep(releases: list[dict], artist_id: int) -> list[dict]:
    """Старая половина своих релизов артиста, альбомы раньше синглов.

    Ранний альбом — тот же артист с другим голосом и звуком, а сингл и свежий
    релиз у подписчика на слуху. Релизы, где артист гостем, мимо: в отрывке
    звучал бы хозяин.
    """
    own = sorted((r for r in releases if r.get("artist_ids") == [artist_id]), key=lambda r: r["released_at"])
    old = own[: (len(own) + 1) // 2]
    random.shuffle(old)
    return sorted(old, key=lambda r: (r.get("track_count") or 0) < 4)


def _hits(artist: dict) -> set[str]:
    """Самые слушаемые треки артиста по Deezer. Не ответил — загадка выйдет без этого отсева."""
    try:
        return {_plain(title) for title in deezer.top_tracks(artist["deezer_id"], HITS)}
    except Exception:  # noqa: BLE001 — ни имени, ни адреса в лог: по ним читается ответ
        log.info("Deezer не ответил: загадка без отсева хитов")
        return set()


def decoys(target: dict, artists: list[dict], count: int = OPTIONS - 1) -> list[str]:
    """Ложные варианты — соседи по сцене на языке ответа, а не кто попало.

    Если подставить кого попало, викторина решается методом исключения:
    среди рэперов сразу видно рок-группу, а среди русских — того, кто читает
    по-английски: язык отрывка вычёркивает лишних раньше, чем человек узнал голос.
    Поэтому берём только тех, у кого с загаданным общая метка сцены, общий язык
    и общий голос (поле `voice` базы: `f` — женский, без поля — мужской): женщину
    среди мужчин слышно сразу — и ответом, и лишним вариантом.
    Не набралось трёх — вернётся меньше, и артист не загадывается (`pick`).
    """
    tags = set(target.get("tags", []))
    kin = [
        a["name"] for a in artists
        if a["name"] != target["name"] and _ru(a) == _ru(target)
        and a.get("voice") == target.get("voice") and tags & set(a.get("tags", []))
    ]
    random.shuffle(kin)
    return kin[:count]


def pick() -> dict | None:
    """Готовит загадку: отрывок, ответ и три ложных варианта."""
    artists = state.read_json(config.ARTISTS_FILE, {"artists": []})["artists"]
    tracked = [a for a in artists if a.get("itunes_id") and len(decoys(a, artists)) == OPTIONS - 1]
    if not tracked:
        return None

    used = _used()
    random.shuffle(tracked)
    # Русскоязычные первыми, иностранные — иногда (владелец, 08.10.2026);
    # вторая половина базы — когда у первой отрывка не нашлось.
    abroad = random.random() < ABROAD
    tracked.sort(key=lambda a: _ru(a) == abroad)

    for artist in tracked[:ATTEMPTS]:
        try:
            releases = itunes.recent_releases(artist["itunes_id"], limit=DEPTH)
        except Exception as exc:  # noqa: BLE001 — магазин мог не ответить
            log.info("Релизы «%s» не достались: %s", artist["name"], exc)
            continue

        old = deep(releases, artist["itunes_id"])[:RELEASES]
        hits = _hits(artist) if old else set()
        for release in old:
            album_id = itunes.album_id_from_url(release.get("url", ""))
            if not album_id:
                continue
            try:
                tracks = itunes.album_tracks(album_id).get("tracks", [])
            except Exception as exc:  # noqa: BLE001
                log.info("Треки «%s» не достались: %s", release.get("title", ""), exc)
                continue

            playable = [
                t for t in tracks
                if t.get("preview") and t["seconds"] >= MIN_SECONDS
                and not UNFAIR.search(t["title"]) and _plain(t["title"]) not in hits
            ]
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
    У «где ИИ» пояснение готово заранее (quiz_ai.explanation).
    """
    if item.get("explanation"):
        return item["explanation"]
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
    ours = not tag or tag.startswith("знаток") or tag == quiz_ai.TAG
    return member.get("status") in ("member", "restricted") and ours


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
    user = guessed(answer, state.read_json(RIDDLE, {}).get("poll"))
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
    return f"Титул за прошлую загадку теперь у {count} {people}."


def award() -> int:
    """Ставит метки угадавшим прошлую загадку. Возвращает, скольким поставили.

    Раздача одна при любом исходе: опрос из quiz.json убирается, список
    угадавших стирается — после неё ответ висит в метках, и угадывать нечего.
    """
    data = state.read_json(RIDDLE, {})
    poll = data.pop("poll", None)
    people = winners(poll)
    given = 0
    try:
        if not people:
            # Молчание здесь в логе не отличить от поломки: опроса не было или голоса не дошли.
            log.info("Титулы: %s", "угадавших нет" if poll else "опроса под прошлой загадкой не было")
            return 0
        chat, tag = poll["chat"], poll.get("tag") or title(poll["artist"])
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
        state.write_json(RIDDLE, data)
        shutil.rmtree(WINNERS, ignore_errors=True)


# ─────────────────────────── отправка ───────────────────────────


def _clip(target: str, item: dict, where: str) -> None:
    from .publish import hushed  # звук в канале — у одного поста за сутки; publish здесь — своя функция

    if item.get("video"):
        telegram.send_video_file(target, Path(item["video"]), quiz_ai.INTRO.format(where=where),
                                 seconds=item["seconds"], quiet=hushed(target))
        return
    telegram.send_audio(
        target,
        item["preview"],
        INTRO.format(where=where),
        # Ни имени, ни названия, ни обложки: всё это и есть ответ.
        title=QUESTION,
        performer="ПЛЁНКА",
        quiet=hushed(target),
    )


def _quiz(target: str, item: dict) -> None:
    telegram.send_quiz(target, item.get("question", QUESTION), item["options"], item["correct"],
                       explanation=explanation(item))


def publish(item: dict, target: str) -> None:
    """Отправляет отрывок и следом анонимную викторину: в личку или в канал без чата.

    Двумя сообщениями, а не одним: подпись к аудио и опрос в Telegram
    несовместимы, а опрос без отрывка бессмысленен.
    """
    _clip(target, item, BELOW)
    _quiz(target, item)


def _sync() -> None:
    """Отправляет загадку в приватный git и забирает чужое: дежурство живёт
    на другой машине и видит её только так. Локально файл у обоих один."""
    if os.environ.get("GITHUB_ACTIONS"):
        from .moderate import _push_repo  # moderate сам импортирует quiz

        _push_repo(config.PRIVATE, [RIDDLE.name], "прослушка: загадка")


def to_channel(item: dict, channel: str, awarded: int) -> str:
    """Отрывок — в канал, викторина — под ним в комментарии. Возвращает, где викторина."""
    try:
        linked = telegram.get_chat(channel).get("linked_chat_id")
    except telegram.TelegramError as exc:
        log.warning("Карточка канала не пришла: %s", exc)
        linked = None
    if not linked:
        publish(item, channel)
        _remember(item.get("mark"))
        return "в канале: чата обсуждений нет"

    _remember(item.get("mark"))
    riddle = state.read_json(RIDDLE, {})
    riddle["pending"] = {
        "artist": item.get("artist", ""),
        "question": item.get("question", QUESTION),
        "tag": item.get("tag") or title(item["artist"]),
        "options": item["options"],
        "correct": item["correct"],
        "explanation": explanation(item),
        "date": state.iso()[:10],
        "awarded": awarded,
    }
    state.write_json(RIDDLE, riddle)
    _sync()
    _clip(channel, item, IN_COMMENTS)

    deadline = time.monotonic() + WAIT
    while time.monotonic() < deadline:
        time.sleep(15)
        _sync()
        if "pending" not in state.read_json(RIDDLE, {}):
            return "в комментариях"

    # ponytail: дежурство может забрать загадку ровно между последней проверкой
    # и этой записью — тогда викторин будет две. Окно в секунды на исходе WAIT;
    # понадобится — замок в git.
    data = state.read_json(RIDDLE, {})
    data.pop("pending", None)
    state.write_json(RIDDLE, data)
    _sync()
    _quiz(channel, item)
    return "в канале: дежурство не повесило её под постом"


def is_riddle(message: dict) -> bool:
    """Пересланный в чат отрывок прослушки или видео «где ИИ»? Узнаём по подписи."""
    return (message.get("caption") or "").startswith(("СЛЕПАЯ ПРОСЛУШКА", "ГДЕ ИИ"))


def attach(message: dict) -> bool:
    """Вешает викторину под пересланным в чат отрывком. Зовёт дежурство.

    Загадку запуск викторины кладёт в git за секунды до отрывка, а своё дерево
    дежурство подтягивает раз в десять минут, поэтому первым делом — свежий git.
    Не вышло — загадка остаётся в quiz.json, и через WAIT запуск викторины
    отдаст её в канал.
    """
    _sync()
    data = state.read_json(RIDDLE, {})
    riddle = data.get("pending")
    if not riddle:
        log.info("Под прослушкой вешать нечего: загадку уже отдали в канал")
        return False

    chat, post = message["chat"]["id"], message["message_id"]
    try:
        sent = telegram.send_quiz(
            chat, riddle.get("question", QUESTION), riddle["options"], riddle["correct"],
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
        "tag": riddle.get("tag") or title(riddle["artist"]),
        "date": riddle["date"],
    }
    state.write_json(RIDDLE, data)
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

    # «Где ИИ»: видео под постом узнаётся так же, титул влезает в метку и не считается чужой.
    assert is_riddle({"video": {"file_id": "v"}, "caption": re.sub(r"<[^>]+>", "", quiz_ai.INTRO.format(where=IN_COMMENTS))})
    assert len(quiz_ai.TAG) <= TAG_LIMIT and re.fullmatch(r"[\w $/&'.:-]+", quiz_ai.TAG)
    assert taggable({"status": "member", "tag": quiz_ai.TAG})
    # Приманка на плашке — в безопасную ширину, как у роликов (reels.BAIT_*).
    from . import reels, stories

    assert stories.font(64, 600).getlength(quiz_ai.BAIT) + 6 <= reels.SAFE_TEXT * 1080, quiz_ai.BAIT
    quiz_ai._selftest()

    # Воскресенье выпускает «где ИИ», пустой запас и снятая метка — загадку про артиста,
    # в будни запас не трогается. Ответ не печатается ни в каком виде.
    from unittest import mock

    from .sources import ai_labels

    artist = {"artist": "Хаски", "track": "Секрет", "options": ["Хаски"], "correct": 0, "album": "", "year": "",
              "preview": "https://x", "mark": "m"}
    secret = {"artist": "Секретный ИИ", "track": "Тайна", "ya_id": "1", "dz_album": "2"}
    told: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        riddle = root / "quiz.json"
        state.write_json(riddle, {"ai_letter": 2})
        board = {"pick": lambda: artist, "_tell_owner": told.append, "RIDDLE": riddle}
        with mock.patch.dict(globals(), board), mock.patch.object(config, "PRIVATE", root), \
                mock.patch.object(quiz_ai, "render", lambda order, out, answer=None: out):
            with mock.patch.object(quiz_ai, "sunday", return_value=False):
                assert choose("channel") is artist and not told
            with mock.patch.object(quiz_ai, "sunday", return_value=True):
                assert choose("channel") is artist and "пуст" in told.pop()
                assert choose("admin") is artist and not told  # в личку по воскресеньям — как в будни
                state.write_json(root / quiz_ai.STOCK / "r1" / "round.json", {"made": "1", "ai": secret})
                with mock.patch.object(ai_labels, "confirmed", return_value=False):
                    assert choose("channel") is artist and told.pop() and not quiz_ai.stock()
                state.write_json(root / quiz_ai.STOCK / "r2" / "round.json", {"made": "2", "ai": secret})
                with mock.patch.object(ai_labels, "confirmed", return_value=True):
                    # Сбой ffmpeg: в тексте ошибки входы по порядку — в лог уходит только имя ошибки.
                    records: list[str] = []
                    handler = logging.Handler()
                    handler.emit = lambda record: records.append(record.getMessage())
                    log.addHandler(handler)
                    failed = subprocess.CalledProcessError(1, ["ffmpeg", "-i", "real-1.m4a", "-i", "ai.m4a"])
                    try:
                        with mock.patch.object(quiz_ai, "render", side_effect=failed):
                            assert choose("channel") is artist and told.pop()
                    finally:
                        log.removeHandler(handler)
                    assert records and not any("m4a" in r for r in records), records
                    item = choose("channel")
        assert item["kind"] == "ai" and item["correct"] != 2 and item["tag"] == quiz_ai.TAG
        assert explanation(item).startswith(f"ИИ — {quiz_ai.LETTERS[item['correct']]}:")
        line = describe(item)
        assert "Секретный" not in line and "Тайна" not in line and "ИИ —" not in line, line
        with mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}):
            assert "Хаски" not in describe(artist)
    # Загадка не из свежего и не гостем: старая половина своих релизов, альбом раньше сингла.
    rows = [
        {"artist_ids": [1 if year else 2], "released_at": f"20{year:02d}-01-01", "track_count": count, "title": str(year)}
        for year, count in ((24, 12), (22, 1), (18, 1), (16, 10), (14, 9), (0, 14))
    ]
    old = deep(rows, 1)
    assert sorted(r["title"] for r in old) == ["14", "16", "18"] and old[-1]["title"] == "18", old
    assert UNFAIR.search("Трек (feat. Гость)") and UNFAIR.search("Интро") and not UNFAIR.search("Интроверт")
    assert _plain("Группа крови (Remastered 2019)") == _plain("группа крови!")
    # Варианты — на языке ответа: иначе лишних вычёркивает язык отрывка, а не слух.
    base = state.read_json(config.ARTISTS_FILE, {"artists": []})["artists"]
    ru = {a["name"]: _ru(a) for a in base}
    assert ru["Хаски"] and ru["Molchat Doma"] and not ru["Bones"]
    for target in base:
        assert all(ru[name] == ru[target["name"]] for name in decoys(target, base)), target["name"]
    # Один в своей сцене — вариантов нет, и загадкой он не идёт: наугад подставленных видно сразу.
    scene = [{"name": name, "tags": [tag]} for name, tag in zip("АБВГД", ["ru-rap"] * 4 + ["ru-indie"])]
    assert len(decoys(scene[0], scene)) == OPTIONS - 1 and decoys(scene[4], scene) == []
    # Женский голос среди мужских слышно сразу: ни ответом, ни лишним вариантом он к ним не идёт.
    scene[1]["voice"] = "f"
    assert "Б" not in decoys(scene[0], scene) and decoys(scene[1], scene) == []
    print("прослушка: все проверки прошли")
    return 0


def choose(target: str | None, force_ai: bool = False) -> dict | None:
    """Загадка на сегодня: в воскресенье в канал — «где ИИ», в остальные дни
    и когда раунда нет — про артиста."""
    if force_ai or (target == "channel" and quiz_ai.sunday()):
        try:
            item = quiz_ai.item(state.read_json(RIDDLE, {}).get("ai_letter"))
            why = ("площадки не ответили на сверку меток ИИ" if quiz_ai.stock()
                   else "запас раундов пуст — его пополняет Mac по субботам (python -m src.quiz_ai --stock)")
        except Exception as exc:  # noqa: BLE001 — сбой видео не повод остаться без загадки
            # Только имя ошибки: в тексте ошибки ffmpeg — входы по порядку, то есть буква ИИ.
            log.error("«Где ИИ» не собрался: %s", type(exc).__name__)
            item, why = None, f"видео не собралось ({type(exc).__name__}), подробности — запуском на Маке"
        if item:
            return item
        if target == "channel":
            # Запас пополняет только Mac владельца: молча откатываться каждую неделю
            # значило бы потерять формат, не узнав почему.
            _tell_owner(f"«Где ИИ» сегодня не вышел, вместо него загадка про артиста: {why}.")
    return pick()


def _tell_owner(text: str) -> None:
    try:
        telegram.send_message(config.secret("TELEGRAM_ADMIN_ID"), text)
    except (telegram.TelegramError, RuntimeError) as exc:
        log.warning("Владельцу не ушло: %s", exc)


def describe(item: dict) -> str:
    """Что печатаем о загадке. В Actions — без ответа: лог открытого репозитория публичен.
    У «где ИИ» ответа нет нигде: раунд знает только приватное хранилище."""
    if item.get("kind") == "ai":
        return "Загадка: «где ИИ», раунд из запаса."
    if os.environ.get("GITHUB_ACTIONS"):
        return "Загадка: угадай артиста."
    return (f"\nОтвет:    {item['artist']} — {item['track']}\n"
            f"Варианты: {', '.join(item['options'])}\n"
            f"Верный:   {item['correct'] + 1}\n"
            f"Пояснение: {explanation(item)}\n"
            f"Титул:    {title(item['artist'])}\n"
            f"Отрывок:  {item['preview'][:60]}…")


def _youtube(chat: str, item: dict) -> None:
    """YouTube-версия с ответом — только владельцу: Shorts он заливает сам."""
    telegram.send_video_file(chat, Path(item["youtube"]), item["youtube_text"],
                             seconds=item["youtube_seconds"])


def _ai_done(item: dict) -> None:
    """Раунд вышел: букву помним (следующий её не повторит), раунд — из запаса.

    Буква лежит в приватном quiz.json: в открытом data/quiz.json её прочли бы
    раньше, чем проголосовали.
    """
    data = state.read_json(RIDDLE, {})
    data["ai_letter"] = item["correct"]
    state.write_json(RIDDLE, data)
    shutil.rmtree(item["folder"], ignore_errors=True)
    try:
        _youtube(config.secret("TELEGRAM_ADMIN_ID"), item)
    except (telegram.TelegramError, RuntimeError) as exc:
        log.warning("YouTube-версия владельцу не ушла: %s", exc)


def main() -> int:
    parser = argparse.ArgumentParser(description="Слепая прослушка")
    parser.add_argument("--preview", action="store_true", help="показать, не отправляя")
    parser.add_argument(
        "--target",
        choices=["admin", "channel"],
        help="куда отправлять: admin — себе в личку, channel — в канал, с титулами",
    )
    parser.add_argument("--ai", action="store_true", help="«где ИИ» из запаса в любой день")
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

    item = choose(args.target, args.ai)
    if not item:
        print("Не нашлось трека с отрывком — попробуй позже.")
        return 1
    print(describe(item))

    if not args.target:
        print("\nОтправить себе: python -m src.quiz --target admin")
        return 0

    if args.target == "admin":
        admin = config.secret("TELEGRAM_ADMIN_ID")
        publish(item, admin)
        if item.get("youtube"):
            _youtube(admin, item)
        _remember(item.get("mark"))
        print("\nОтправлено: в личку.")
        return 0

    where = to_channel(item, config.secret("TELEGRAM_CHANNEL_ID"), awarded)
    if item.get("kind") == "ai":
        _ai_done(item)
    print(f"\nОтправлено: {'видео' if item.get('video') else 'отрывок'} в канал, викторина {where}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
