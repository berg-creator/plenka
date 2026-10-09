"""ПАМЯТКА — два раза в неделю короткий пост-совет артисту: чьи права на трек и как записать голос.

Канал — сцена для тех, кто пришёл в бот делать музыку (владелец 06.10.2026), и им нужнее пересказа
чужого релиза то, на чём начинающий теряет трек или деньги: «free» в названии бита, фит без уговора,
голосовое вместо записи. Поэтому ПАМЯТКА выходит вместо поста о релизе, а не вдобавок (владелец
09.10.2026): в её сутки ленты publish.release_due релиз не пускает, а слот обычного поста она
занимает так же, как занял бы он (publish.due), — постов в день больше не становится. Релиз этого
дня в свои сутки не выходит; с выходом в 10:00 МСК (iTunes) он годен ещё час следующего утра
и выходит тогда — побочный эффект, а не решение (NEXT.md, раздел 121).

В пост идёт только то, за чем стоит документ или правило самого бота: у каждой записи базы
(data/pamyatka.json) обязательное поле sources — статьи ГК РФ или место в коде. Цитаты закона стоят
в кавычках дословно: все сверены 09.10.2026 с официальным текстом на pravo.gov.ru (nd=102110716,
редакция 48, последняя правка — 214-ФЗ от 07.07.2025). «Что делать» —
практический вывод, а не цитата. Текст — шаблоном, без модели: норму, пересказанную своими словами,
уже не проверить по статье. Базу пополняют руками.
Последняя строка поста зовёт в бота, слова «в боте» в ней — ссылка. Своя строка записи — поле bot,
метка ссылки — поле start: про бит «free» она ведёт в список битов, про запись голоса — в сведение
(отдельной проверки голоса в боте нет: замер записи, skleyka.gauge, идёт внутри сведения и человеку
не показывается). Записи про права (поле topic) без своей строки шаблон дописывает призыв CALL —
«Лучше пишите ПЛЁНКЕ» со ссылкой на раздел в боте (владелец 09.10.2026). Команд в тексте поста нет:
в канале Telegram подсвечивает /команду, а нажатие никуда не ведёт.

Та же база открывается в боте разделом «ПАМЯТКА» (screen, answer; кнопки и счёт — service._memo):
вопросы кнопками (поле ask) по config.PAMYATKA_PAGE на экран, ответ — та же запись без призыва.
Это справочник, а не консультант: модель не вызывается, текст человека раздел не разбирает —
«модель выдумывает, юриста у нас нет» (владелец 09.10.2026), и экран раздела говорит это первым.
Отвергнуто: две темы вместо страниц (права — 14 вопросов из 20, простыня осталась бы) и правка
сообщения на месте (ответ пропадал бы при возврате к списку — прочитанное остаётся в чате).

Выход — в дни config.PAMYATKA_DAYS с config.PAMYATKA_HOUR_MSK по Москве, не ночью, одна запись
в сутки ленты, по порядку базы. Отметка вышедшей — pamyatka-<id>.json в content/archive, как у совета
недели (src/sovet.py): запись дважды не выходит, поэтому id в базе не менять. База кончилась —
рубрика молчит и релизы в её дни выходят как раньше; с последней записью владельцу уходит строка.
Отвергнуто: счётчик «какая запись следующая» отдельным файлом (отметки в архиве уже это знают
и переживают вставку записи в середину базы), пост вдобавок к релизу (владелец 06.10.2026: постов
в ленте и так много) и посты по справке YouTube — её страницы автоматически не читаются, а писать
по памяти значит выдумывать.

    python -m src.pamyatka --selftest   без сети и Telegram; настоящая база — источники, длина подписи с призывом,
                                        раздел в боте: страницы, кнопки и ответы в лимитах Telegram
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
LAW = "prava"  # поле topic записи про права; вторая тема — "golos", запись голоса
# Отсылка к названию сериала о юристе — без имени персонажа: его нигде не пишем.
CALL = "▸ Лучше пишите ПЛЁНКЕ: все памятки про права — в боте"
# Кнопки раздела в боте: s:pam:<id> — запись, s:pam:<номер> — страница списка; «s:pam» без хвоста — вход
# из меню (service.menu_buttons). Число id не бывает — селфтест базы.
PICK = "s:pam:"
ICONS = {LAW: "⚖️", "golos": "🎤"}
HEAD = "⚖️ <b>ПАМЯТКА</b>"
INTRO = "Ответы на то, на чём начинающий теряет трек или деньги: чьи права на музыку и как записать голос."
NOTE = "ПЛЁНКА не юрист: здесь цитаты закона и что с ними делать, свой случай — к юристу."
MORE = "Новые памятки выходят в канале {channel} по средам и субботам."  # дни — config.PAMYATKA_DAYS, сверяет селфтест
BACK = "← Все вопросы"
# Своя строка записи зовёт в биты или в сведение — под ответом кнопка туда же, тем же путём, что кнопка меню.
DOORS = {"bity": "🎚 БИТЫ — бесплатно, можно в релиз", "skleyka": "🎛 СВЕДЕНИЕ — вокал и бит в трек"}
# Счёт в data/bot_sources.json (service.count_source): вход в раздел и каждая открытая запись, по дню.
OPENED = "ПАМЯТКА: открыт раздел"
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


def _parts(item: dict) -> list[str]:
    return [f"<b>ПАМЯТКА: {html.escape(item['title'])}</b>", *map(html.escape, item["text"])]


def build(item: dict) -> dict:
    """Пост канала: запись и последней строкой — своя строка про бота или, у записи про права, призыв CALL."""
    parts = _parts(item)
    line, start = (item["bot"], item["start"]) if item.get("bot") else (CALL, RUBRIC) if item.get("topic") == LAW else ("", "")
    if line:
        url = f"https://t.me/{config.BOT_HANDLE.lstrip('@')}?start={start}"
        parts.append(re.sub("(?i)в боте", lambda found: f'<a href="{url}">{found[0]}</a>', html.escape(line), count=1))
    return {"rubric": RUBRIC, "id": item["id"], "title": item["title"], "text": "\n\n".join(parts)}


def label(item: dict) -> str:
    """Подпись счётчика открытой записи — её вопрос: владельцу видно, что открывают."""
    return f"ПАМЯТКА: «{item.get('ask') or item['title']}»"


def find(key: str) -> dict | None:
    return next((item for item in load() if item["id"] == key), None)


def screen(page: int | None = None) -> tuple[str, list[list[dict]]]:
    """Экран раздела в боте: оговорка и вопросы кнопками, config.PAMYATKA_PAGE на страницу, в порядке базы.
    page=None — вход в раздел: со вступлением и строкой о канале (пока в базе есть невышедшее);
    номер — страница списка, туда же возвращает «← Все вопросы» под ответом."""
    base, size = load(), config.PAMYATKA_PAGE
    at = min(page or 0, max(0, (len(base) - 1) // size)) * size
    rows = [[{"text": f"{ICONS.get(item.get('topic'), '')} {item.get('ask') or item['title']}".strip(),
              "callback_data": f"{PICK}{item['id']}"}] for item in base[at:at + size]]
    turn = ([{"text": "← Назад", "callback_data": f"{PICK}{at // size - 1}"}] if at else []) + \
        ([{"text": "Ещё вопросы →", "callback_data": f"{PICK}{at // size + 1}"}] if at + size < len(base) else [])
    parts = [HEAD, *([INTRO] if page is None else []), NOTE,
             *([MORE.format(channel=config.CHANNEL_HANDLE)] if page is None and pending() else []),
             *([f"Вопросы {at + 1}–{min(at + size, len(base))} из {len(base)} ↓"] if base else [])]
    return "\n\n".join(parts), rows + ([turn] if turn else [])


def answer(item: dict) -> tuple[str, list[list[dict]]]:
    """Ответ на вопрос в боте: запись тем же шаблоном, что пост, без призыва и без ссылки — человек уже
    в боте. Своя строка про бота остаётся строкой, а ведёт туда кнопка под ответом."""
    door = item.get("start", "").partition("_")[0]
    page = [row["id"] for row in load()].index(item["id"]) // config.PAMYATKA_PAGE
    rows = [[{"text": DOORS[door], "callback_data": f"s:{door}"}]] if item.get("bot") and door in DOORS else []
    return ("\n\n".join(_parts(item) + ([html.escape(item["bot"])] if item.get("bot") else [])),
            rows + [[{"text": BACK, "callback_data": f"{PICK}{page}"}]])


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
    assert len(base) >= 16 and len({item["id"] for item in base}) == len(base), "id записей не повторяются"
    link = f'<a href="https://t.me/{config.BOT_HANDLE.lstrip("@")}?start={RUBRIC}">в боте</a>'
    for item in base:
        text, cited = build(item)["text"], " ".join(item.get("sources") or [])
        assert re.fullmatch(r"[a-z0-9-]+", item["id"]) and not item["id"].isdigit() and cited, f"{item['id']}: нет источника"
        # Последняя строка зовёт в бота: своя — в биты или сведение, у записи про права без своей — призыв в раздел.
        assert item.get("topic") in ICONS and text.count("<a href") == 1, f"{item['id']}: тема и одна ссылка в бота"
        assert item.get("bot") or text.endswith(CALL.replace("в боте", link)), f"{item['id']}: призыв — последней строкой"
        assert not item.get("bot") or item["start"].partition("_")[0] in DOORS and CALL not in text, f"{item['id']}: своя строка — с кнопкой"
        assert not re.search(r"(?<![:/\w<])/[a-z]", text), f"{item['id']}: команда в посте канала не нажимается"
        # Раздел в боте: вопрос влезает в кнопку, её данные — в 64 байта, ответ — без призыва и ссылки.
        reply, keys = answer(item)
        assert 0 < len(item.get("ask") or "") <= 36 and len(f"{PICK}{item['id']}".encode()) <= 64, f"{item['id']}: кнопка"
        assert reply == text.split("\n\n▸")[0] + (f"\n\n{html.escape(item['bot'])}" if item.get("bot") else ""), item["id"]
        assert telegram.visible_len(reply) <= telegram.MAX_TEXT and keys[-1][0]["text"] == BACK
        assert [key["callback_data"] for row in keys for key in row] == \
            [f"s:{item.get('start', '').partition('_')[0]}"] * bool(item.get("bot")) + [f"{PICK}{base.index(item) // config.PAMYATKA_PAGE}"]
        assert telegram.visible_len(text) <= quality.CAPTION_LIMIT, f"{item['id']}: подпись {telegram.visible_len(text)} знаков"
        assert set(re.findall(r"ст\. (\d+)", text)) == set(re.findall(r"ст\. (\d+)", cited)), f"{item['id']}: статьи текста и источника"
        assert all(key in skleyka.TAKE_FLAWS for key in re.findall(r'TAKE_FLAWS\["(\w+)"\]', cited)), item["id"]
        assert not item.get("bot") or f'?start={item["start"]}">' in text, f"{item['id']}: «в боте» не стало ссылкой"
        assert "prod." not in text or config.BEAT_CREDIT in text, f"{item['id']}: условие бита — config.BEAT_CREDIT"
        assert " ГБ" not in text or f"до {config.SKLEYKA_LINK_MB // 1024} ГБ и {config.SKLEYKA_LINK_FILES} файлов" in text, f"{item['id']}: лимиты облака — из config"
        assert "Проверить свой голос" not in text, f"{item['id']}: отдельной проверки голоса в боте нет"
    # Экран раздела: оговорка на каждой странице, вступление и строка о канале — только на входе, каждая
    # запись — ровно одной кнопкой, страницы листаются в обе стороны, всё в лимитах Telegram.
    first, keys = screen()
    assert first.startswith(f"{HEAD}\n\n{INTRO}\n\n{NOTE}") and (config.CHANNEL_HANDLE in first) == bool(pending())
    assert config.PAMYATKA_DAYS == (2, 5), "MORE называет среду и субботу"
    pages = [screen(n) for n in range(-(-len(base) // config.PAMYATKA_PAGE))]
    assert keys == pages[0][1] and screen(99) == pages[-1], "вход — первая страница, лишний номер — последняя"
    asked = [key for _, rows in pages for row in rows for key in row if not key["callback_data"].removeprefix(PICK).isdigit()]
    assert [key["callback_data"] for key in asked] == [f"{PICK}{item['id']}" for item in base], "все записи, по разу, в порядке базы"
    assert all(find(key["callback_data"].removeprefix(PICK)) for key in asked) and find("") is None and find("1") is None
    for n, (text, rows) in enumerate(pages):
        turn = [key["callback_data"] for row in rows for key in row if key["callback_data"].removeprefix(PICK).isdigit()]
        assert turn == [f"{PICK}{m}" for m in (n - 1, n + 1) if 0 <= m < len(pages)], (n, turn)
        assert NOTE in text and INTRO not in text and telegram.visible_len(text) <= telegram.MAX_TEXT and len(rows) <= config.PAMYATKA_PAGE + 1
        assert all(len(key["callback_data"].encode()) <= 64 and len(key["text"]) <= 40 for row in rows for key in row)

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
    print(f"В боте: {len(load())} вопросов, по {config.PAMYATKA_PAGE} на экран; счёт — python -m src.service --sources | grep ПАМЯТКА")
    print("\n" + build(left[0])["text"] if left else "Запас кончился: рубрика молчит, релизы в её дни выходят как раньше.")


if __name__ == "__main__":
    sys.exit(main())
