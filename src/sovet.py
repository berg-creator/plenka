"""СОВЕТ НЕДЕЛИ — раз в неделю пост по настоящим замерам бота: что чаще всего мешало в записях голоса.

Канал — сцена для тех, кто пришёл в бот делать музыку (владелец 06.10.2026), а им полезнее
чужих релизов совет, как записать голос чище. Совет берётся не из головы: сведение само
меряет каждый сырой голос (skleyka.gauge, пороги TAKE_*) и кладёт числа в запись трека, поле
take. Здесь они считаются за TRACK_DAYS суток — ровно столько живёт запись трека (чистка в
skleyka.tick), так что отдельный журнал замеров не нужен, а данные о людях остаются в приватном
хранилище: в пост попадают только два числа и название брака, ни имён, ни треков.

Текст — шаблоном, без модели: модель не меряла записи, а совет в TAKE_FLAWS уже написан и
сверен. Выход — четверг по Москве после 12:00, не ночью, раз на неделю (отметка — файл
sovet-<понедельник>.json в content/archive, как у бита). Замерено меньше MIN_TAKES голосов или
самый частый брак в меньше чем MIN_HITS — поста нет: «чаще всего» из двух случаев — выдумка.
Тот же брак, что на прошлой неделе, не повторяется — идёт следующий по частоте.
Отвергнуто: журнал замеров отдельным файлом (записи треков и так живут нужную неделю) и
ссылка на трек или имя автора в посте (данные о людях).

    python -m src.sovet --selftest   без сети и Telegram
    python -m src.sovet --dry-run    что вышло бы сейчас по настоящему STATE_DIR, без записи и отправки
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from . import config, state

MIN_TAKES = 5   # меньше замеренных голосов за неделю — «чаще всего» ничего не значит
MIN_HITS = 2    # брак реже чем в двух записях — случай, а не совет
HOUR = 12       # четверг с этого часа по Москве

# Название на карточке и оборот для текста «в K из них …».
NAMES = {"noise": ("Шум в паузах", "слышен шум в паузах"),
         "clip": ("Перегруз", "голос записан с перегрузом"),
         "dull": ("Нет верха", "нет верхних частот"),
         "room": ("Гул комнаты", "звук не затихает после слов")}
POST = ("<b>СОВЕТ НЕДЕЛИ: {title}</b>\n\n"
        "За неделю бот замерил {total} {records} голоса, в {hits} из них — {phrase}.\n\n"
        "Как убрать. {advice}\n\n"
        '▸ Проверить свой голос — <a href="https://t.me/{bot}?start=skleyka_sovet">в боте</a>')
ASK = "С чем борешься при записи?"


def monday(moment: datetime):
    """Дата понедельника той недели по Москве — ключ недели."""
    from .compose import MSK

    day = moment.astimezone(MSK).date()
    return day - timedelta(days=day.weekday())


def count(data: dict) -> tuple[int, dict[str, int]]:
    """Замерено голосов за TRACK_DAYS и в скольких найден каждый вид брака.

    Один и тот же файл голоса, сведённый дважды, даёт два трека с замером цифра в цифру — считается
    один раз: на настоящих данных 06.10.2026 из 14 замеров три пары были повторами, и порог
    «в двух записях» иначе брал бы один человек, приславший одну запись два раза.
    """
    from . import skleyka

    total, hits, seen = 0, {}, set()
    for track in data.get("tracks", {}).values():
        if not track.get("take") or skleyka._age(track.get("at", "")) > skleyka.TRACK_DAYS * 86400:
            continue
        mark = json.dumps(track["take"], sort_keys=True)
        if mark in seen:
            continue
        seen.add(mark)
        total += 1
        for key in skleyka.flaws(track["take"]):
            hits[key] = hits.get(key, 0) + 1
    return total, hits


def pick(total: int, hits: dict[str, int], last: str = "") -> str:
    """Брак недели: самый частый, прошедший порог, не прошлонедельный. Нет такого — пусто."""
    if total < MIN_TAKES:
        return ""
    for key, number in sorted(hits.items(), key=lambda item: -item[1]):
        if number >= MIN_HITS and key != last:
            return key
    return ""


def _records(number: int) -> str:
    """«21 запись», «22 записи», «25 записей»: за неделю набирается и два десятка, шаблон «N записей» соврал бы."""
    if 10 < number % 100 < 20 or number % 10 in (0, 5, 6, 7, 8, 9):
        return "записей"
    return "запись" if number % 10 == 1 else "записи"


def build(key: str, total: int, hits: int) -> dict:
    from . import skleyka

    title, phrase = NAMES[key]
    text = POST.format(title=title.upper(), total=total, records=_records(total), hits=hits, phrase=phrase,
                       advice=html.escape(skleyka.TAKE_FLAWS[key][1]), bot=config.BOT_HANDLE.lstrip("@"))
    return {"rubric": "sovet", "flaw": key, "title": title, "text": text, "comment": ASK}


def _last(moment: datetime) -> str:
    """Брак прошлой недели («» — совета не было)."""
    return state.read_json(config.ARCHIVE / f"sovet-{monday(moment) - timedelta(days=7)}.json", {}).get("flaw", "")


def due(moment: datetime | None = None) -> bool:
    """Четверг после HOUR по Москве, не ночью, и на этой неделе совета ещё не было."""
    from . import publish
    from .compose import MSK

    moment = moment or state.now()
    local = moment.astimezone(MSK)
    return (local.weekday() == 3 and local.hour >= HOUR and not publish.night(moment)
            and not (config.ARCHIVE / f"sovet-{monday(moment)}.json").exists())


def make(data: dict, moment: datetime | None = None) -> dict | None:
    """Пост этой недели по записям треков или None. Ничего не пишет."""
    moment = moment or state.now()
    if not due(moment):
        return None
    total, hits = count(data)
    key = pick(total, hits, _last(moment))
    return build(key, total, hits[key]) if key else None


def air() -> str:
    """Выход из дежурства (moderate.publish_shift): ключ брака вышедшего совета или пустая строка.
    Не вышло — отметка снимается, и следующий заход пробует снова."""
    from . import publish, skleyka

    post = make(skleyka.load())
    if not post:
        return ""
    path = config.ARCHIVE / f"sovet-{monday(state.now())}.json"
    config.ARCHIVE.mkdir(parents=True, exist_ok=True)
    state.write_json(path, post)
    try:
        publish.to_channel(post, path, config.secret("TELEGRAM_CHANNEL_ID"))
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return post["flaw"]


def shot(post: dict) -> Path:
    """Карточка поста: название брака крупно, «СОВЕТ НЕДЕЛИ» — рубрикой (publish.send)."""
    from . import card

    return card.save(post["title"], [], label="СОВЕТ НЕДЕЛИ", name="sovet")


def _selftest() -> None:
    from . import publish, skleyka

    stamp = lambda days: state.iso(state.now() - timedelta(days=days))  # noqa: E731
    bad = {"noise": 5.0, "clip": 0.0, "air": -30.0, "body": -20.0, "room": None}
    fine = {"noise": 45.0, "clip": 0.0, "air": -30.0, "body": -20.0, "room": 40.0}
    tracks = {f"t{n}": {"at": stamp(1), "take": {**(bad if n < 3 else fine), "air": -30.0 - n}} for n in range(6)}
    tracks["again"] = {"at": stamp(1), "take": dict(tracks["t0"]["take"])}  # тот же файл второй раз — не считается
    tracks["old"] = {"at": stamp(9), "take": bad}      # старше срока — не считается
    tracks["none"] = {"at": stamp(1)}                  # замера нет
    data = {"tracks": tracks}
    assert count(data) == (6, {"noise": 3}), count(data)

    assert pick(4, {"noise": 4}) == "" and pick(6, {"noise": 1}) == "", "мало замеров и редкий брак — молчим"
    assert pick(6, {"noise": 3, "clip": 2}, last="noise") == "clip" and pick(6, {"noise": 3}, last="noise") == "", "повтор уступает"

    real, saved_load = state.now, skleyka.load
    saved = config.ARCHIVE, publish.to_channel
    with tempfile.TemporaryDirectory() as tmp:
        config.ARCHIVE = Path(tmp)
        os.environ.setdefault("TELEGRAM_CHANNEL_ID", "-1")
        sent = []
        publish.to_channel = lambda post, path, chat: sent.append(post)
        try:
            thursday = datetime.fromisoformat("2026-10-08T12:30:00+03:00")
            state.now = lambda: thursday - timedelta(days=1)
            assert not due() and make(data) is None, "не четверг — молчит"
            state.now = lambda: thursday.replace(hour=11)
            assert not due(), "до 12:00 — молчит"
            state.now = lambda: thursday
            post = make(data)
            assert post and post["flaw"] == "noise" and "замерил 6 записей голоса, в 3 из них — слышен шум в паузах" in post["text"]
            assert [_records(n) for n in (5, 11, 21, 22, 25, 112)] == ["записей", "записей", "запись", "записи", "записей", "записей"]
            assert "?start=skleyka_sovet" in post["text"] and len(post["text"]) <= 1024 and "t0" not in post["text"]
            assert skleyka.TAKE_FLAWS["noise"][1] in post["text"], "совет — из TAKE_FLAWS"
            assert make({"tracks": {}}) is None, "замеров нет"
            last = Path(tmp) / f"sovet-{monday(thursday) - timedelta(days=7)}.json"
            state.write_json(last, {"flaw": "noise"})
            assert make(data) is None, "шум повторять нельзя, другого брака нет"
            last.unlink()
            skleyka.load = lambda: data
            assert air() == "noise" and len(sent) == 1
            assert air() == "" and len(sent) == 1, "вторая отметка недели не выходит"
            (Path(tmp) / f"sovet-{monday(thursday)}.json").unlink()
            publish.to_channel = lambda *a: 1 / 0
            try:
                air()
            except ZeroDivisionError:
                pass
            assert not (Path(tmp) / f"sovet-{monday(thursday)}.json").exists(), "сбой отправки снимает отметку"
            state.now = lambda: thursday.replace(hour=23, minute=30)
            assert not due(), "ночью — молчит"
        finally:
            state.now, skleyka.load = real, saved_load
            config.ARCHIVE, publish.to_channel = saved
    print("sovet: самопроверка пройдена")


def main() -> None:
    parser = argparse.ArgumentParser(description="СОВЕТ НЕДЕЛИ: пост по замерам голоса за неделю")
    parser.add_argument("--selftest", action="store_true", help="проверка без сети и Telegram")
    parser.add_argument("--dry-run", action="store_true", help="что вышло бы сейчас по настоящему STATE_DIR, без записи")
    args = parser.parse_args()
    if args.selftest:
        return _selftest()
    from . import skleyka

    total, hits = count(skleyka.load())
    print(f"Замерено за неделю: {total}; брак: {hits or 'нет'}; сейчас можно выйти: {due()}")
    key = pick(total, hits, _last(state.now()))
    print(build(key, total, hits[key])["text"] if key else "Поста нет: мало замеров, редкий брак или повтор прошлой недели.")


if __name__ == "__main__":
    sys.exit(main())
