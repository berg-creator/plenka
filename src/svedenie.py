"""СВЕДЕНИЕ — «ты на 89% Toxi$»: бот считает, на сколько музыка человека совпала с артистом.

Зачем. Самая большая просьба на форуме Яндекс Музыки — «найдите людей с тем же
вкусом», 18 266 голосов с 2019 года, и Яндекс её так и не сделал. Сравнение
двух людей требует второго человека, а сравнение с артистом работает сразу:
кинул ссылку на свои лайки — получил ответ и карточку, которую есть что
переслать. Поэтому строится оно первым, а сравнение двоих — следом (NEXT.md,
задача 50в). Модель здесь не нужна вовсе: всё, что бот говорит, — это проценты
и имена, а придумывать ему нечего.

Формула. Процент — доля доступных треков из списка человека, где хоть один
исполнитель входит в круг артиста: сам артист и `similarArtists` Яндекса.
Лайки самого артиста закрыты, как у всех, поэтому «вкус артиста» честно —
это он и те, кого Яндекс ставит рядом с ним. Считать по одному артисту было бы
почти всегда «на 3%»: у человека в лайках десятки имён, и совпадение с одним
из них — не ответ. Есть у артиста свой плейлист («С любовью, Toxi$») — второй
строкой идёт совпадение с ним: общие треки к меньшему из двух списков.

Кого сравнивать, бот выбирает сам: двадцать артистов, которых человек лайкал
чаще других, — и три лучших по проценту в ответ. Полный перебор отпадает:
на тысяче лайков это сотни запросов brief-info ради тех же трёх имён.

Списки — данные о человеке, поэтому снимок лежит только в приватном хранилище
(config.SVED_STATE), живёт 30 дней и нужен ровно для кнопки «Сравнить
с артистом»: без него каждое сравнение снова тянуло бы всю фонотеку.
Разборов — три в сутки на человека: каждый стоит до 25 запросов к Яндексу.

Запасной путь — имена (решение владельца 21.09.2026). «Мне нравится» открывается
только на сайте Яндекса, с телефона до этой настройки почти никто не дойдёт,
а ВК Музыка и Звук без входа не читаются вовсе (проверено 21.09: ВК уводит
на badbrowser.php, Звук отдаёт заглушку). Поэтому человек с любым стримингом
может просто написать 5–20 артистов, которых слушает чаще всего. Второго счёта
под это нет: каждый названный артист становится в снимке одной «строкой», как
трек с одним исполнителем, и процент — доля названных, что входят в круг
кандидата. Снимок тот же, поэтому «Сравнить с артистом» работает и после имён,
а свой плейлист артиста второй строкой не выходит — общих треков у имён нет.
Такой разбор стоит около сорока запросов: поиск и brief-info на каждое имя.

    python -m src.svedenie --selftest              формула, отказы и ответ — без сети
    python -m src.svedenie --dry-run               разбор открытой фонотеки, без Telegram
    python -m src.svedenie --check "ССЫЛКА"        что ответил бы бот на эту ссылку
"""

from __future__ import annotations

import argparse
import html
import logging
import re
import tempfile
from collections import Counter
from datetime import timedelta
from pathlib import Path

from . import card, config, state, telegram
from .sources import yandex_music

log = logging.getLogger("svedenie")

# Сколько артистов из списка проверяем и сколько показываем.
CANDIDATES = 20
TOP = 3
# Меньше — считать не из чего: на десятке треков процент пляшет от одного лайка.
MIN_TRACKS = 15
# Запасной путь именами: меньше пяти — процент шагает по 25%, больше двадцати —
# это уже не «чаще всего», а вся фонотека, и запросов к Яндексу на каждое имя два.
MIN_NAMES = 5
MAX_NAMES = 20
# Снимок фонотеки живёт месяц: дальше человек слушает уже другое.
SNAPSHOT_DAYS = 30
# Ниже этого процента совпадения нет: у разношёрстной фонотеки (проверено
# 20.09.2026 на открытой users/music-blog — 206 треков, у каждого свой артист)
# лучший ответ выходил «ты на 1%». Число честное, но карточку с ним не пересылают,
# поэтому ниже порога бот так и говорит — и картинку не рисует.
SOFT = 10

# INTRO уходит с полем ответа, и метка в нём — чтобы список артистов в ответ ушёл
# сюда, а не в ПРОЯВКУ: без ответа на сообщение список там и разбирается
# («покажу, что у них общего»). Яндекс называет только эта инструкция — в меню,
# кнопках и описании бота площадки нет (владелец, 21.09.2026).
INTRO_MARK = "Ссылку или артистов ответом на это сообщение"
INTRO = (
    "🎚 <b>СВЕДЕНИЕ</b>\n\n"
    "Посчитаю, на сколько процентов твоя музыка совпадает с артистами, "
    "и покажу, с кем сильнее всего.\n\n"
    "Кинь ссылку на свои лайки в Яндекс Музыке: Моя музыка → «Мне нравится» → поделиться. "
    'Если список закрыт, открой его на <a href="https://music.yandex.ru/settings/other">'
    "music.yandex.ru/settings/other</a> — «Публичный доступ к моей фонотеке».\n\n"
    f"Или просто напиши через запятую {MIN_NAMES}–{MAX_NAMES} артистов, которых слушаешь чаще всего.\n\n"
    f"{INTRO_MARK}."
)
CLOSED = (
    "Этот список я не читаю — он закрыт или ссылка не на плейлист.\n\n"
    'Открыть доступ: <a href="https://music.yandex.ru/settings/other">music.yandex.ru/settings/other</a> → '
    "«Публичный доступ к моей фонотеке». В приложении такой настройки нет, только на сайте."
)
FEW = "В списке всего {count} — по такому считать нечего. Нужно хотя бы {need} треков."
LIMIT = "Сегодня уже три разбора. Приходи завтра — посчитаю ещё."
NO_SNAPSHOT = "Сначала кинь ссылку на свои лайки или напиши артистов — сравнивать пока не с чем."
NO_ARTIST = "Яндекс такого артиста не знает. Напиши имя так, как оно стоит в Яндекс Музыке."
SILENT = "Яндекс Музыка сейчас не отвечает. Попробуй через полчаса."
COMPARE_MARK = "Имя артиста ответом на это сообщение"
COMPARE_ASK = "С кем сравнить? " + COMPARE_MARK + " — посчитаю, на сколько ты совпал с ним."
NAMES_MARK = "Артистов через запятую ответом на это сообщение"
NAMES_ASK = (
    f"Кого ты слушаешь чаще всего? {NAMES_MARK} — от {MIN_NAMES} до {MAX_NAMES}, "
    "как их зовут в любом стриминге."
)
FEW_NAMES = "Нужно хотя бы {need} артистов, которых Яндекс знает, — нашёл {count}."
# Тем, кто пришёл на «делаем» и остался ждать (config.SVED_FILE).
READY = "🎚 <b>СВЕДЕНИЕ</b> заработало — кидай ссылку на своё «Мне нравится», посчитаю."

# Префикс и обрезка — как у кнопок сервиса (service.CALLBACK_PREFIX и _cb):
# «следить» разбирает service.handle_callback через watch_add, и второй путь
# к тому же списку заводить незачем. Связку держит service._selftest.
CALLBACK_PREFIX = "s:"
CALLBACK_BYTES = 64


def _cb(action: str, arg: str = "") -> str:
    return f"{CALLBACK_PREFIX}{action}:{arg}".encode()[:CALLBACK_BYTES].decode(errors="ignore")


# Для тех, у кого поле ответа INTRO уже закрыто: закрытый или короткий список,
# сравнение без снимка, мало найденных имён. С закрытым списком человек не должен отваливаться.
NAMES_BUTTON = [[{"text": "✍️ Написать артистов", "callback_data": _cb("imena")}]]


def buttons(artist: str) -> list[list[dict]]:
    return [
        [{"text": "🎯 Сравнить с артистом", "callback_data": _cb("sravni")}],
        [{"text": f"🔔 Следить за {artist}", "callback_data": _cb("watch", artist)}],
    ]


# ─────────────────────────── снимок фонотеки ───────────────────────────


def _load() -> dict:
    return state.read_json(config.SVED_STATE, {})


def _save(data: dict) -> None:
    edge = state.now() - timedelta(days=SNAPSHOT_DAYS)
    fresh = {
        chat: entry
        for chat, entry in data.items()
        if (moment := state._parse(entry.get("at", ""))) is not None and moment > edge
    }
    config.SVED_STATE.parent.mkdir(parents=True, exist_ok=True)
    state.write_json(config.SVED_STATE, fresh)


def _short(tracks: list[dict]) -> list[list]:
    """Снимок: id трека и id его исполнителей. Имена не хранятся — они не нужны,
    а лишние данные о человеке в хранилище не лежат."""
    return [[t["id"], [a["id"] for a in t["artists"] if a.get("id")]] for t in tracks if t["available"]]


def _spend(data: dict, chat_id: str) -> bool:
    """Тратит один разбор из суточных трёх. False — на сегодня хватит.

    Тратится и неудачный: запросы к Яндексу по закрытой ссылке уходят те же.
    """
    today = state.now().strftime("%Y-%m-%d")
    entry = data.setdefault(str(chat_id), {})
    used = entry.get("used", 0) if entry.get("day") == today else 0
    if used >= config.SVED_PER_DAY:
        return False
    entry.update(day=today, used=used + 1, at=state.iso())
    _save(data)
    return True


# ─────────────────────────── счёт ───────────────────────────


def percent(tracks: list[list], circle: set[int]) -> int:
    """Доля треков списка, где хоть один исполнитель — из круга артиста."""
    if not tracks:
        return 0
    hits = sum(1 for _, artists in tracks if any(a in circle for a in artists))
    return round(100 * hits / len(tracks))


def matches(tracks: list[list], limit: int = TOP, known: dict | None = None) -> list[dict]:
    """Артисты, с которыми человек совпал сильнее всего.

    known — уже прочитанные артисты по id: у имён brief-info пришёл при поиске,
    и второй раз за ним ходить незачем.
    """
    counts = Counter(artist for _, artists in tracks for artist in artists)
    found = []
    for artist_id, liked in counts.most_common(CANDIDATES):
        data = (known or {}).get(artist_id) or yandex_music.info(artist_id)
        if data:
            found.append({**data, "percent": percent(tracks, set(data["circle"])), "liked": liked})
    # Круги соседей по сцене покрывают одни и те же треки, и проценты сходятся
    # до равных. Равные разводит число своих треков: в шапку идёт тот, кого
    # человек правда слушает, а не первый, кто попался в переборе.
    found.sort(key=lambda a: (a["percent"], a["liked"]), reverse=True)
    return found[:limit]


def own_percent(match: dict, tracks: list[list]) -> int:
    """Совпадение с тем, что артист собрал сам: общие треки к меньшему из двух списков."""
    if not match.get("playlist"):
        return 0
    own = yandex_music.playlist(match["playlist"]["owner"], match["playlist"]["kind"])
    theirs = {t["id"] for t in own or [] if t["available"]}
    mine = {track for track, _ in tracks}
    if not theirs or not mine:
        return 0
    return round(100 * len(mine & theirs) / min(len(mine), len(theirs)))


def answer(tracks: list[list], found: list[dict], unit: str = "трекам") -> str:
    """Ответ человеку: только проценты и имена, вкус бот не оценивает.

    unit — чем считали: треками из лайков или артистами, которых человек назвал.
    """
    head = (
        f"Посчитал по {len(tracks)} {unit} из твоего списка:"
        if found[0]["percent"] >= SOFT
        else f"Посчитал по {len(tracks)} {unit}. Список слишком разный — "
        "заметного совпадения ни с кем нет. Ближе всех:"
    )
    lines = ["🎚 <b>СВЕДЕНИЕ</b>\n", head + "\n"]
    lines += [f"· ты на <b>{a['percent']}%</b> {a['name']}" for a in found]
    best = found[0]
    if share := own_percent(best, tracks):
        lines.append(
            f"\nС тем, что {best['name']} собрал сам («{best['playlist']['title']}»), — {share}%."
        )
    return "\n".join(lines)


def _card(match: dict) -> Path:
    return card.save(
        f"ты на {match['percent']}% {match['name']}",
        [match["name"]],
        label="СВЕДЕНИЕ",
        name=f"sved-{state.now().strftime('%H%M%S')}",
        photo_url=match.get("photo", ""),
    )


def _send(chat_id: str, text: str, match: dict) -> None:
    """Карточка и ответ. Карточка уходит без подписи и без кнопок: её пересылают."""
    if match["percent"] < SOFT:
        telegram.send_message(chat_id, text, buttons=buttons(match["name"]))
        return
    try:
        picture = _card(match)
    except Exception as exc:  # noqa: BLE001 — без картинки ответ всё равно уходит
        log.info("Карточка не нарисовалась: %s", exc)
    else:
        telegram.send_photo_file(chat_id, picture, "")
        picture.unlink(missing_ok=True)
    telegram.send_message(chat_id, text, buttons=buttons(match["name"]))


# ─────────────────────────── разговор ───────────────────────────


def intro(chat_id: str) -> None:
    telegram.send_message(chat_id, INTRO, ask="Ссылка или артисты через запятую")


def handle(chat_id: str, text: str) -> None:
    """Пришла ссылка на плейлист — главный вход СВЕДЕНИЯ."""
    data = _load()
    if not _spend(data, chat_id):
        telegram.send_message(chat_id, LIMIT)
        return

    telegram.send_chat_action(chat_id)
    found = yandex_music.by_link(text)
    if found is None:
        telegram.send_message(chat_id, CLOSED, buttons=NAMES_BUTTON)
        return
    tracks = _short(found)
    if len(tracks) < MIN_TRACKS:
        telegram.send_message(chat_id, FEW.format(count=len(tracks), need=MIN_TRACKS), buttons=NAMES_BUTTON)
        return

    best = matches(tracks)
    if not best:
        telegram.send_message(chat_id, SILENT)
        return

    data[str(chat_id)]["tracks"] = tracks
    _save(data)
    _send(chat_id, answer(tracks, best), best[0])


def ask_artist(chat_id: str) -> None:
    telegram.send_message(chat_id, COMPARE_ASK, ask="Имя артиста")


def compare(chat_id: str, name: str) -> None:
    """Сравнение с артистом, которого назвал человек, — по сохранённому снимку."""
    data = _load()
    tracks = data.get(str(chat_id), {}).get("tracks")
    if not tracks:
        telegram.send_message(chat_id, NO_SNAPSHOT, buttons=NAMES_BUTTON)
        return
    if not _spend(data, chat_id):
        telegram.send_message(chat_id, LIMIT)
        return

    telegram.send_chat_action(chat_id)
    found = yandex_music.artist(name.strip()[:120])
    if not found:
        telegram.send_message(chat_id, NO_ARTIST)
        return

    match = {**found, "percent": percent(tracks, set(found["circle"]))}
    text = f"🎚 <b>СВЕДЕНИЕ</b>\n\nТы на <b>{match['percent']}%</b> {match['name']}."
    if share := own_percent(match, tracks):
        text += f"\n\nС тем, что он собрал сам («{match['playlist']['title']}»), — {share}%."
    _send(chat_id, text, match)


def ask_names(chat_id: str) -> None:
    telegram.send_message(chat_id, NAMES_ASK, ask="Артисты через запятую")


def names(text: str) -> list[str]:
    """Имена из сообщения: через запятую или с новой строки, без повторов, не больше двадцати."""
    # ponytail: имя с запятой внутри («Tyler, The Creator») разрежется на два;
    # чинить, если в «Не нашёл» такие начнут попадаться.
    unique: dict[str, str] = {}
    for name in re.split(r"[,\n]", text):
        if name := name.strip()[:120]:
            unique.setdefault(name.casefold(), name)
    return list(unique.values())[:MAX_NAMES]


def by_names(chat_id: str, text: str) -> None:
    """Запасной путь: человек назвал артистов сам. Счёт и снимок — те же, что у лайков."""
    data = _load()
    if not _spend(data, chat_id):
        telegram.send_message(chat_id, LIMIT)
        return

    telegram.send_chat_action(chat_id)
    known: dict[int, dict] = {}
    missed: list[str] = []
    for name in names(text):
        if found := yandex_music.artist(name):
            known[found["id"]] = found  # «Баста» и «Basta» — один артист, одна строка
        else:
            missed.append(name)
    # Имена пишет человек, а ответ уходит HTML-разметкой: «<b>» в имени уронил бы отправку.
    note = f"\n\nНе нашёл: {html.escape(', '.join(missed), quote=False)}." if missed else ""
    if len(known) < MIN_NAMES:
        telegram.send_message(chat_id, FEW_NAMES.format(need=MIN_NAMES, count=len(known)) + note,
                              buttons=NAMES_BUTTON)
        return

    # Названный артист — «трек» с одним исполнителем: percent и matches считают как есть.
    tracks = [[f"a{artist_id}", [artist_id]] for artist_id in known]
    best = matches(tracks, known=known)
    data[str(chat_id)]["tracks"] = tracks
    _save(data)
    _send(chat_id, answer(tracks, best, unit="артистам") + note, best[0])


def notify_waiting() -> None:
    """Тем, кто пришёл по метке до стройки, бот обещал написать первым.

    Список одноразовый: разослали — файл удалён, и обещание больше не висит.
    """
    waiting = state.read_json(config.SVED_FILE, [])
    if not waiting:
        return
    for chat_id in waiting:
        try:
            telegram.send_message(chat_id, READY)
        except Exception as exc:  # noqa: BLE001 — один закрытый чат не держит остальных
            log.info("Ждущему %s не написалось: %s", chat_id, exc)
    config.SVED_FILE.unlink(missing_ok=True)
    log.info("СВЕДЕНИЕ: оповещено ждущих — %d", len(waiting))


# ─────────────────────────── проверки ───────────────────────────


def _selftest() -> None:
    """Формула, отказы и ответ — без сети.

    Запуск: python -m src.svedenie --selftest
    """
    circle = {1: [1, 2, 3], 9: [9]}
    fake = {
        1: {"id": 1, "name": "Toxi$", "circle": circle[1], "photo": "",
            "playlist": {"owner": "7", "kind": "1001", "title": "С любовью, Toxi$"}},
        9: {"id": 9, "name": "Дора", "circle": circle[9], "photo": "", "playlist": None},
    }
    real = (yandex_music.info, yandex_music.artist, yandex_music.by_link, yandex_music.playlist,
            telegram.send_message, telegram.send_photo_file, telegram.send_chat_action,
            card.save, config.SVED_STATE, config.SVED_FILE, yandex_music._get)
    # brief-info отдаёт id самого артиста строкой, соседей — числом, а треки — числом:
    # круг приводится к числам, иначе сам артист в свой круг не входит.
    yandex_music._get = lambda path, **kw: {"artist": {"id": "7", "name": "X"}, "similarArtists": [{"id": 8}]}
    assert yandex_music.info(7)["circle"] == [7, 8] and yandex_music.info(7)["id"] == 7
    replies: list[str] = []
    yandex_music.info = lambda artist_id: fake.get(int(artist_id))
    yandex_music.artist = lambda name: next((a for a in fake.values() if a["name"] == name), None)
    yandex_music.playlist = lambda owner, kind: [
        {"id": "t1", "available": True, "artists": [], "title": ""},
        {"id": "нет", "available": True, "artists": [], "title": ""},
    ]
    telegram.send_message = lambda chat_id, text, **kw: replies.append(text) or {}
    telegram.send_photo_file = lambda chat_id, path, caption, **kw: replies.append("[карточка]") or {}
    telegram.send_chat_action = lambda *a, **kw: None
    card.save = lambda *a, **kw: Path(tempfile.gettempdir()) / "sved-test.jpg"

    try:
        tmp = tempfile.TemporaryDirectory()
        config.SVED_STATE = Path(tmp.name) / "svedenie.json"
        config.SVED_FILE = Path(tmp.name) / "sved.json"

        # Формула: из четырёх треков три сделаны кругом Toxi$ (1, 2, 3), один — чужой.
        tracks = [["t1", [1]], ["t2", [2, 5]], ["t3", [3]], ["t4", [9]]]
        assert percent(tracks, set(circle[1])) == 75, percent(tracks, set(circle[1]))
        assert percent(tracks, set(circle[9])) == 25
        assert percent([], {1}) == 0, "пустой список — ноль, а не деление на ноль"

        best = matches(tracks)
        assert [a["name"] for a in best] == ["Toxi$", "Дора"], best
        # Свой плейлист: из двух его треков общий один, в списке человека четыре.
        assert own_percent(best[0], tracks) == 50, own_percent(best[0], tracks)
        assert own_percent(best[1], tracks) == 0, "плейлиста нет — строки нет"
        text = answer(tracks, best)
        assert "ты на <b>75%</b> Toxi$" in text and "«С любовью, Toxi$»), — 50%" in text, text

        # Закрытая фонотека и короткий список — отказ, но разбор всё равно потрачен:
        # запросы к Яндексу ушли.
        yandex_music.by_link = lambda url: None
        handle("55501", "music.yandex.ru/users/kto/playlists/3")
        assert replies[-1] == CLOSED, replies[-1]
        yandex_music.by_link = lambda url: [
            {"id": "t1", "available": True, "artists": [{"id": 1, "name": "Toxi$"}], "title": ""}
        ]
        handle("55501", "ссылка")
        assert replies[-1].startswith("В списке всего 1"), replies[-1]

        # Обычный разбор: карточка, ответ и снимок в приватном хранилище.
        yandex_music.by_link = lambda url: [
            {"id": f"t{i}", "available": True, "artists": [{"id": 1, "name": "Toxi$"}], "title": ""}
            for i in range(MIN_TRACKS)
        ]
        handle("55501", "ссылка")
        assert replies[-2] == "[карточка]" and "ты на <b>100%</b> Toxi$" in replies[-1], replies[-2:]
        saved = state.read_json(config.SVED_STATE, {})["55501"]
        assert saved["used"] == 3 and len(saved["tracks"]) == MIN_TRACKS, saved["used"]
        assert saved["tracks"][0] == ["t0", [1]], "в снимке только id — имён человека в файле нет"

        # Слабое совпадение: бот говорит как есть и карточку не рисует.
        weak = [["t%d" % i, [7]] for i in range(20)] + [["t99", [9]]]
        assert "Список слишком разный" in answer(weak, [{**fake[9], "percent": 5}])
        _send("55501", "текст", {**fake[9], "percent": 5})
        assert replies[-1] == "текст", replies[-1]

        # Четвёртый разбор за сутки — отказ.
        handle("55501", "ссылка")
        assert replies[-1] == LIMIT, replies[-1]

        # Сравнение с артистом: по снимку, без снимка — отказ.
        state.write_json(config.SVED_STATE, {"55501": {**saved, "used": 0, "tracks": tracks}})
        compare("55501", "Дора")
        assert "ты на <b>25%</b> Дора".casefold() in replies[-1].casefold(), replies[-1]
        compare("55501", "Кто-то")
        assert replies[-1] == NO_ARTIST, replies[-1]
        compare("60002", "Дора")
        assert replies[-1] == NO_SNAPSHOT, replies[-1]

        # Имена вместо ссылки: запятые и строки, пробелы, повтор в другом регистре, потолок в двадцать.
        assert names(" Toxi$, Дора\ntoxi$ ,, Кто-то\n") == ["Toxi$", "Дора", "Кто-то"]
        assert len(names(",".join(f"x{i}" for i in range(30)))) == MAX_NAMES
        assert NAMES_BUTTON[0][0]["callback_data"] == "s:imena:"
        fake.update({n: {"id": n, "name": name, "circle": [n], "photo": "", "playlist": None}
                     for n, name in ((2, "Сосед"), (3, "Третий"), (5, "Пятый"))})
        # Четыре найденных — отказ, и ненайденный назван, а не выкинут молча.
        by_names("70003", "Toxi$, Дора, Сосед, Кто-то, Третий")
        assert replies[-1].startswith("Нужно хотя бы 5") and "Не нашёл: Кто-то." in replies[-1], replies[-1]
        # Пять: круг Toxi$ (1, 2, 3) покрывает троих из пяти названных — 60%.
        by_names("70003", "Toxi$, Дора, Сосед, Третий, Пятый, Кто-то, toxi$")
        text = replies[-1]
        assert "Посчитал по 5 артистам" in text and "ты на <b>60%</b> Toxi$" in text, text
        assert "Не нашёл: Кто-то." in text and "собрал сам" not in text, text
        saved = state.read_json(config.SVED_STATE, {})["70003"]
        assert saved["tracks"][0] == ["a1", [1]] and len(saved["tracks"]) == 5, saved["tracks"]
        compare("70003", "Дора")
        assert "ты на <b>20%</b> Дора".casefold() in replies[-1].casefold(), "сравнение по снимку из имён"

        # Ждущие: одно сообщение и файл удалён — обещание не висит второй раз.
        state.write_json(config.SVED_FILE, ["55501", "60002"])
        notify_waiting()
        assert replies[-2:] == [READY, READY] and not config.SVED_FILE.exists()
        notify_waiting()
        assert replies[-1] == READY, "второй раз не пишем"
    finally:
        (yandex_music.info, yandex_music.artist, yandex_music.by_link, yandex_music.playlist,
         telegram.send_message, telegram.send_photo_file, telegram.send_chat_action,
         card.save, config.SVED_STATE, config.SVED_FILE, yandex_music._get) = real

    print("СВЕДЕНИЕ: процент по кругу артиста, свой плейлист второй строкой, "
          "закрытый список и четвёртый разбор за сутки — отказ, снимок без имён; "
          "по названным артистам: ненайденные названы, меньше пяти — отказ")


def _show(link: str) -> int:
    found = yandex_music.by_link(link)
    if found is None:
        print(CLOSED)
        return 1
    tracks = _short(found)
    if len(tracks) < MIN_TRACKS:
        print(FEW.format(count=len(tracks), need=MIN_TRACKS))
        return 1
    best = matches(tracks)
    if not best:
        print(SILENT)
        return 1
    print(answer(tracks, best))
    return 0


# Открытая фонотека Яндекса — на ней проверяли разбор 18.09.2026.
SAMPLE = "https://music.yandex.ru/users/music-blog/playlists/3"


def main() -> int:
    parser = argparse.ArgumentParser(description="СВЕДЕНИЕ: на сколько процентов ты совпал с артистом")
    parser.add_argument("--selftest", action="store_true", help="формула, отказы и ответ — без сети")
    parser.add_argument("--dry-run", action="store_true", help="разбор открытой фонотеки, без Telegram")
    parser.add_argument("--check", metavar="ССЫЛКА", help="что ответил бы бот на эту ссылку")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    config.load_dotenv()

    if args.selftest:
        _selftest()
        return 0
    if args.dry_run or args.check:
        return _show(args.check or SAMPLE)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
