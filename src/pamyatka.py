"""ПАМЯТКА — два раза в неделю короткий пост-совет артисту: чьи права на трек и как записать голос.

Канал — сцена для тех, кто пришёл в бот делать музыку (владелец 06.10.2026), и им нужнее пересказа
чужого релиза то, на чём начинающий теряет трек или деньги: «free» в названии бита, фит без уговора,
голосовое вместо записи. Поэтому ПАМЯТКА выходит вместо поста о релизе, а не вдобавок (владелец
09.10.2026): в её сутки ленты publish.release_due релиз не пускает, а слот обычного поста она
занимает так же, как занял бы он (publish.due), — постов в день больше не становится. Релиз этого
дня на завтра не переносится: пост о релизе живёт сутки от выхода и к утру протухает.

В пост идёт только то, за чем стоит документ или правило самого бота: у каждой записи базы
(data/pamyatka.json) обязательное поле sources — статьи ГК РФ или место в коде. Цитаты закона стоят
в кавычках дословно; сверены они с копией кодекса на Викитеке (главы 69 и 70), с официальной
публикацией — нет. «Что делать» — практический вывод, а не цитата. Текст — шаблоном, без модели:
норму, пересказанную своими словами, уже не проверить по статье. Базу пополняют руками.
Строка про бота — поле bot: слова «в боте» в ней становятся ссылкой ?start=<поле start>. Обещает
она только то, что в боте есть: отдельной проверки голоса в нём нет — замер записи (skleyka.gauge)
идёт внутри сведения и человеку не показывается, — поэтому зовёт она в сведение.

Выход — в дни config.PAMYATKA_DAYS с config.PAMYATKA_HOUR_MSK по Москве, не ночью, одна запись
в сутки ленты, по порядку базы. Отметка вышедшей — pamyatka-<id>.json в content/archive, как у совета
недели (src/sovet.py): запись дважды не выходит, поэтому id в базе не менять. База кончилась —
рубрика молчит и релизы в её дни выходят как раньше; с последней записью владельцу уходит строка.
Отвергнуто: счётчик «какая запись следующая» отдельным файлом (отметки в архиве уже это знают
и переживают вставку записи в середину базы), пост вдобавок к релизу (владелец 06.10.2026: постов
в ленте и так много) и посты по справке YouTube — её страницы автоматически не читаются, а писать
по памяти значит выдумывать.

    python -m src.pamyatka --selftest   без сети и Telegram; настоящая база — источники и длина подписи
    python -m src.pamyatka --dry-run    что в запасе, когда выйдет следующая и её текст, без записи и отправки
"""
from __future__ import annotations

import argparse
import html
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from . import config, state

RUBRIC = "pamyatka"
LAST = "📌 Запас ПАМЯТКИ кончился: «{title}» — последняя запись базы. Новые — в data/pamyatka.json."


def load() -> list[dict]:
    """Записи базы. Без id, заголовка или текста — не запись: базу правят руками, а спрашивает о ней
    и выход релизов (publish.release_due) — кривая правка не должна ронять дежурство."""
    data = state.read_json(config.PAMYATKA_FILE, [])
    return [item for item in data if isinstance(item, dict) and item.get("id") and item.get("title") and item.get("text")] \
        if isinstance(data, list) else []


def pending() -> list[dict]:
    """Невышедшие записи в порядке базы."""
    return [item for item in load() if not (config.ARCHIVE / f"{RUBRIC}-{item['id']}.json").exists()]


def build(item: dict) -> dict:
    parts = [f"<b>ПАМЯТКА: {html.escape(item['title'])}</b>", *map(html.escape, item["text"])]
    if item.get("bot"):
        url = f"https://t.me/{config.BOT_HANDLE.lstrip('@')}?start={item['start']}"
        parts.append(re.sub("(?i)в боте", lambda found: f'<a href="{url}">{found[0]}</a>', html.escape(item["bot"]), count=1))
    return {"rubric": RUBRIC, "id": item["id"], "title": item["title"], "text": "\n\n".join(parts)}


def aired(moment: datetime) -> bool:
    """Вышла ли памятка в эти сутки ленты — по журналу публикаций, как счёт релизов (publish.releases_today)."""
    from . import publish

    today = publish.feed_day(moment)
    return any(item.get("rubric") == RUBRIC and (at := state._parse(item.get("published_at", "")))
               and publish.feed_day(at) == today
               for item in state.read_json(config.POSTED_FILE, {"items": []}).get("items", []))


def due(moment: datetime | None = None) -> bool:
    """День рубрики с PAMYATKA_HOUR_MSK по Москве, не ночью, и в эти сутки ленты памятка ещё не выходила."""
    from . import publish
    from .compose import MSK

    moment = moment or state.now()
    local = moment.astimezone(MSK)
    return (local.weekday() in config.PAMYATKA_DAYS and local.hour >= config.PAMYATKA_HOUR_MSK
            and not publish.night(moment) and not aired(moment))


def day(moment: datetime | None = None) -> bool:
    """Отданы ли сутки ленты ПАМЯТКЕ: она сегодня уже вышла либо сегодня её день и в базе есть невышедшая.
    В такие сутки пост о релизе не выходит (publish.release_due) — с их начала, а не с 12:00:
    иначе утренний релиз и памятка днём давали бы тот самый лишний пост."""
    from . import publish

    moment = moment or state.now()
    return aired(moment) or publish.feed_day(moment).weekday() in config.PAMYATKA_DAYS and bool(pending())


def air() -> str:
    """Выход из дежурства (moderate.publish_shift): id вышедшей записи или пустая строка.
    Не вышло — отметка снимается, и следующий заход пробует снова."""
    from . import publish, telegram

    left = pending()
    if not left or not due():
        return ""
    post = build(left[0])
    path = config.ARCHIVE / f"{RUBRIC}-{post['id']}.json"
    config.ARCHIVE.mkdir(parents=True, exist_ok=True)
    state.write_json(path, post)
    try:
        publish.to_channel(post, path, config.secret("TELEGRAM_CHANNEL_ID"))
    except Exception:
        path.unlink(missing_ok=True)
        raise
    if len(left) == 1:
        try:
            telegram.send_message(config.secret("TELEGRAM_ADMIN_ID"), LAST.format(title=html.escape(post["title"])))
        except telegram.TelegramError as exc:  # памятка уже вышла — строка владельцу её не отменяет
            print(f"  памятка: строка о запасе не ушла: {str(exc)[:120]}")
    return post["id"]


def shot(post: dict) -> Path:
    """Карточка поста: заголовок крупно, «ПАМЯТКА» — рубрикой (publish.send)."""
    from . import card

    return card.save(post["title"][:1].upper() + post["title"][1:], [], label="ПАМЯТКА", name=RUBRIC)


def _selftest() -> None:
    import os

    from . import publish, quality, skleyka, telegram

    # Настоящая база: у каждой записи источник, подпись влезает в подпись к фото, сказанное о боте стоит на коде.
    base = load()
    assert base and len({item["id"] for item in base}) == len(base), "id записей не повторяются"
    for item in base:
        text, cited = build(item)["text"], " ".join(item.get("sources") or [])
        assert re.fullmatch(r"[a-z0-9-]+", item["id"]) and cited, f"{item['id']}: нет источника"
        assert telegram.visible_len(text) <= quality.CAPTION_LIMIT, f"{item['id']}: подпись {telegram.visible_len(text)} знаков"
        assert set(re.findall(r"ст\. (\d+)", text)) == set(re.findall(r"ст\. (\d+)", cited)), f"{item['id']}: статьи текста и источника"
        assert all(key in skleyka.TAKE_FLAWS for key in re.findall(r'TAKE_FLAWS\["(\w+)"\]', cited)), item["id"]
        assert not item.get("bot") or f'?start={item["start"]}">' in text, f"{item['id']}: «в боте» не стало ссылкой"
        assert "prod." not in text or config.BEAT_CREDIT in text, f"{item['id']}: условие бита — config.BEAT_CREDIT"
        assert "Проверить свой голос" not in text, f"{item['id']}: отдельной проверки голоса в боте нет"

    at = lambda stamp: datetime.fromisoformat(f"2026-10-{stamp}:00+03:00")  # noqa: E731 — 07.10 среда, 10.10 суббота
    real = state.now, config.ARCHIVE, config.POSTED_FILE, config.PAMYATKA_FILE, publish.to_channel, telegram.send_message
    with tempfile.TemporaryDirectory() as tmp:
        config.ARCHIVE, config.POSTED_FILE, config.PAMYATKA_FILE = Path(tmp) / "archive", Path(tmp) / "posted.json", Path(tmp) / "base.json"
        os.environ.setdefault("TELEGRAM_CHANNEL_ID", "-1")
        os.environ.setdefault("TELEGRAM_ADMIN_ID", "1")
        sent, lines = [], []
        channel = lambda post, path, chat: (sent.append(post), publish.record(post, path, "channel"))  # noqa: E731
        publish.to_channel = channel
        telegram.send_message = lambda chat, text, **_: lines.append(text)
        items = [{"id": key, "title": f"запись {key}", "text": ["Текст."], "sources": ["ГК РФ"]} for key in "abc"]
        state.write_json(config.PAMYATKA_FILE, items[:2])
        try:
            state.now = lambda: at("06T13:00")
            assert not due() and air() == "" and not day() and publish.release_due(), "вторник — молчит, релиз выходит"
            state.write_json(config.POSTED_FILE, {"items": [{"rubric": "release", "published_at": state.iso(at("06T10:00"))}]})
            assert not publish.release_due(), "в обычный день лимит релизов прежний"
            state.write_json(config.POSTED_FILE, {"items": []})
            state.now = lambda: at("07T08:00")
            assert not day() and publish.release_due(), "среда до 9:00 — ещё сутки вторника, релиз выходит"
            state.now = lambda: at("07T09:30")
            assert day() and not publish.release_due() and air() == "", "сутки среды отданы памятке с начала, сама она — с 12:00"
            state.now = lambda: at("07T12:30")
            assert air() == "a" and sent[0]["text"] == "<b>ПАМЯТКА: запись a</b>\n\nТекст." and not lines
            assert air() == "" and len(sent) == 1, "одна запись в сутки"
            assert day() and not publish.release_due(), "памятка вышла — релиз в эти сутки не выходит"
            state.now = lambda: at("08T02:00")
            assert not publish.release_due() and air() == "", "ночь четверга — хвост суток среды"
            state.now = lambda: at("08T09:30")
            assert not day() and publish.release_due(), "четверг — релиз выходит как раньше"
            state.now = lambda: at("10T23:30")
            assert not due(), "ночью — молчит"
            state.now = lambda: at("10T12:30")
            assert air() == "b" and len(lines) == 1 and "Запас ПАМЯТКИ кончился" in lines[0], "порядок базы, с последней — строка владельцу"
            state.now = lambda: at("14T12:30")
            assert air() == "" and len(sent) == 2 and len(lines) == 1, "база кончилась — молчит, строка одна"
            assert not day() and publish.release_due(), "база кончилась — релизы в дни рубрики как раньше"
            state.write_json(config.PAMYATKA_FILE, items)
            publish.to_channel = lambda *a: 1 / 0
            try:
                air()
            except ZeroDivisionError:
                pass
            assert not (config.ARCHIVE / "pamyatka-c.json").exists() and day(), "сбой отправки снимает отметку"
            publish.to_channel = channel
            assert air() == "c" and [post["id"] for post in sent] == ["a", "b", "c"], "после сбоя — та же запись"
        finally:
            state.now, config.ARCHIVE, config.POSTED_FILE, config.PAMYATKA_FILE, publish.to_channel, telegram.send_message = real
    print("pamyatka: самопроверка пройдена")


def main() -> None:
    parser = argparse.ArgumentParser(description="ПАМЯТКА: пост-совет артисту по средам и субботам")
    parser.add_argument("--selftest", action="store_true", help="проверка без сети и Telegram")
    parser.add_argument("--dry-run", action="store_true", help="что в запасе и какой пост вышел бы следующим, без записи")
    args = parser.parse_args()
    if args.selftest:
        return _selftest()
    from . import telegram

    left = pending()
    print(f"В базе: {len(load())}, не вышло: {len(left)}; сутки отданы памятке: {day()}; сейчас можно выйти: {bool(left) and due()}")
    for item in left:
        print(f"  {item['id']}: подпись {telegram.visible_len(build(item)['text'])} знаков — {item['title']}")
    print("\n" + build(left[0])["text"] if left else "Запас кончился: рубрика молчит, релизы в её дни выходят как раньше.")


if __name__ == "__main__":
    sys.exit(main())
