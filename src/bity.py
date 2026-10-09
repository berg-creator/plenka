"""Биты владельца: type beat на его YouTube — бит в боте и сразу СВЕДЕНИЕ с ним.

С 02.10.2026 владелец сам делает type beat'ы и сам выкладывает их на YouTube.
Зрители type beat'ов — артисты, ровно те, кому нужно СВЕДЕНИЕ, а «скачать
в Телеграме» — стандарт ниши. Бот отдаёт бит бесплатно, с условием подписать
BEAT_CREDIT, и кнопкой «🎚 Свести с этим битом» открывает заявку СВЕДЕНИЯ, где бит
уже лежит.

Путь к биту — через меню бота: «🎚 БИТЫ» первой кнопкой и команда /bity (listing).
Ссылку ?start=beat_<id> YouTube в описании ролика оставить не дал (02.10.2026),
там только адрес бота, и человек приходит обычным /start. Поэтому описание ролика
называет путь словами, а не ссылкой; сама ссылка жива — для мест, где её пускают.

В канале бит — рамка недели (владелец 06.10.2026): в понедельник он выходит постом
БИТ НЕДЕЛИ (air), под него пишут и сводят ботом, треки выходят в канале с опросом,
в воскресенье — итог по голосам (src/otbor.py: week_of, final). Неделя — дата её
понедельника по Москве (week), бит недели — пост бита с этой датой в архиве (weekly).
Отвергнуто: бит постом раз в два дня, как было до того, — пост звал забрать бит
и ничем не кончался, а лента оставалась чужой для тех, кто пришёл в бот делать своё.

Бит владелец шлёт боту в личку файлом с подписью со слова «бит»:

    бит Kizaru x Toxi$ — Полёт, 140 Fm

артисты — тире — название, темп и тональность через запятую, если есть.
Такой файл не уходит ни дублем ролика, ни дорожкой сведения, ни треком к посту,
ни в ОТБОР (src/moderate.py). В ответ — ссылка, название, описание и теги
для YouTube, кто из артистов канала сейчас на подъёме, а следом ролик 1920×1080.

Хранилище — сам Telegram: в каталоге data/beats.json только file_id, и бот отдаёт
бит по нему, ничего не скачивая, — так уходит и WAV больше 20 МБ. Отвергнуто:
хранить файлы в репозитории — он открытый и распух бы на десятки мегабайт
за бит; качать бит с YouTube — там сжатый звук, а не WAV; вести из описания
в канал — туда идут читать, а бит и сведение живут в боте.

Ролик собирает отдельный процесс (--render), как сведение (--job): качать бит
и кодировать видео в цикле опроса значит держать кнопки всех. Кадр — плёночный
портрет (cover, владелец 02.10.2026): живое фото 4:3 по центру чёрного кадра
и одно слово названия, без имён артистов и плашек — так выглядят соседи
по выдаче, а имена и «free type beat» стоят в названии ролика. Фото — запас
с Pexels (config.BEAT_PHOTOS), каждому биту своё; лицо артиста в превью —
жалоба правообладателя, сгенерированных лиц в проекте нет вовсе. Отвергнуты:
панель кассетника с названием (01.10.2026: терялась рядом с лицами у лидеров)
и двое спинами против света фар с именами на спинах (первый ролик; остались
запасным кадром, когда фото кончились). Кадр живой: наезд дышит, туман плывёт,
свет бьётся в такт — застывшую картинку YouTube показывает хуже. Тот же кадр 1280×720 уходит владельцу файлом — превью
для YouTube. Служебный вход бота для битов больше 20 МБ
открывает и сведение, а ключ, открытый дважды, Telegram гасит, поэтому ролик
и сведение не идут одновременно (tick, skleyka.tick).

    python -m src.bity --selftest
    python -m src.bity --video БИТ.wav --title "Kizaru x Toxi$ — Полёт, 140 Fm" --out ПАПКА   ролик, превью и тексты без Telegram
    python -m src.bity --demand [АРТИСТ ...]   под кого делать бит: сколько смотрят type beat'ы за месяц
"""

from __future__ import annotations

import argparse
import html
import io
import math
import random
import re
import statistics
import subprocess
import sys
import tempfile
import urllib.parse
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

from . import clips, collect, config, make_cover, skleyka, state, stories, telegram

# «бит» первым словом подписи; «биты» и «битмейкер» — не он.
MARK = re.compile(r"\s*бит\b[\s:.,-]*", re.IGNORECASE)
DASH = re.compile(r"\s+[—–-]\s+")
# Артисты: «Kizaru x Toxi$», кириллическая «х», «&», «feat.», запятая.
SPLIT = re.compile(r"\s+(?:x|х|&|feat\.?|ft\.?)\s+|\s*,\s*", re.IGNORECASE)
# Хвост названия после запятой: темп, тональность или оба — «, 140 Fm», «, F# minor», «, 140 bpm».
TAIL = re.compile(r",\s*(?:(?P<bpm>\d{2,3})\s*(?:bpm)?)?\s*"
                  r"(?P<key>[A-G][#b♯♭]?\s*(?:minor|major|min|maj|минор|мажор|m)?)?\s*$", re.IGNORECASE)
PREFIX = "s:bit:"
MAKE = "🎚 Свести с этим битом"
# Бит из списка (listing): своя кнопка, а не PREFIX — та открывает заявку СВЕДЕНИЯ, эта отдаёт файл.
PICK = "s:beat:"
# Метка счётчика (service.SOURCES): бит взят из меню бота, а не по ссылке beat_ — та считается «beat».
MENU_LABEL = "beat_menu"
# ponytail: список без страниц — LIST_MAX свежих битов, старые из меню не видны (по ссылке beat_
# и в «🔎 Нет бита» живы). Страницы — когда битов станет больше.
LIST_MAX = 20
# Знаков на кнопке списка: длиннее Telegram на телефоне обрезает многоточием.
LABEL_MAX = 40
RISING_DAYS = 14
RISING_TOP = 5
NOT_RAP = re.compile(r"metal|grunge|punk|rock")
# Под кого делать бит (--demand). Бот говорит по-русски, и в СВЕДЕНИЕ придёт тот, кто по-русски читает:
# сам на подъёме считается только среди этих уровней базы; чужое имя меряется, если его назвали.
DEMAND_TIERS = ("ru", "ru_pop")
# Параметр sp выдачи YouTube: загружено за этот месяц. Меньше DEMAND_MIN роликов — мерить нечем.
THIS_MONTH, DEMAND_RESULTS, DEMAND_MIN = "EgIIBA%3D%3D", 20, 3
# Поле «Теги» на YouTube — до 500 знаков на все.
TAGS_LIMIT = 500
WIDTH, HEIGHT = 1920, 1080
# Значок: фото 4:3 во всю высоту по центру чёрного кадра, слово — Playfair Display, вес 500, буквы
# вплотную, не шире WORD_WIDTH от фото; кегль от WORD_SIZE вниз. Снято с образца, который выбрал
# владелец 02.10.2026. Невышедших фото меньше PHOTOS_LOW — строка владельцу под превью.
PHOTO_BOX, WORD_FONT, WORD_WIDTH, WORD_SIZE, PHOTOS_LOW = (1440, HEIGHT), stories.FONTS / "Playfair.ttf", 0.74, (420, 120), 5
# Настроение бита — последнее слово подписи («…, 142 Em, злой»), его же подсказывает записка нот (noty.MOODS).
# Фото запаса несут своё полем mood (без поля — «обычный»), злому слово — рубленым Oswald 700: тёплый
# портрет и книжная антиква читались добрыми, а у чужих type beat'ов пары кадр холодный (владелец, 03.10.2026).
MOOD = re.compile(r",\s*(?P<mood>злой|кино|обычный)\s*$", re.IGNORECASE)
WORD_FONTS = {"злой": (stories.FONTS / "Oswald.ttf", 700, 240)}  # шрифт, вес, кегль не больше: узкий Oswald в ширину
# WORD_WIDTH вырастал до половины кадра и закрывал лицо
# Запасной кадр config.BEAT_BACK: где у спин середина и на какой линии стоит имя в одну строку, сколько спина
# вмещает в ширину. Снято с образца, который выбрал владелец 01.10.2026.
BACKS = ((620, 640), (1365, 672))
BACK_WIDTH = 520
WHITE = (246, 242, 234)
PREVIEW_SIZE, PREVIEW_NAME = (1280, 720), "preview.jpg"
# Ролик: кадров в секунду, секунд на вдох-выдох наезда, ход тумана в пикселях в секунду и его
# яркость (из 255), пресет x264.
FPS, BREATH, FOG_SPEED, FOG_LIGHT, PRESET = 24, 20, 12, 48, "veryfast"
AUDIO_KBPS = 192
# Ролик целиком, с запасом до telegram.MAX_UPLOAD на буфер кодека и обвязку mp4.
VIDEO_BUDGET = 48 * 2**20

FORMAT = ("🎚 Бит не принял — не понял подпись. Нужно так: артисты, тире, название, "
          "потом, если знаешь, темп, тональность и настроение (злой, кино) через запятую:\n"
          "<code>бит Kizaru x Toxi$ — Полёт, 140 Fm, злой</code>")
ADDED = ("🎚 Бит №{id} в каталоге: «{title}» — {artists}{tempo}.\n"
         "Прямая ссылка на бит (если YouTube даст вставить): {link}\n\n"
         "<b>Название для YouTube</b>\n<code>{name}</code>\n\n"
         "<b>Описание</b>\n<pre>{about}</pre>\n\n"
         "<b>Теги</b>\n<code>{tags}</code>\n\n"
         "{rising}🎬 Ролик 1920×1080 и превью для YouTube соберу и пришлю следом.")
RISING = f"📈 На подъёме — больше всего новостей и релизов в сборе канала за {RISING_DAYS} дней: {{names}}.\n\n"
# Путь словами, без t.me: ссылку YouTube в описании оставить не дал (02.10.2026), адрес бота — оставил.
ABOUT = ("Скачать бесплатно ({format}): Telegram → {bot} → кнопка «🎚 БИТЫ»\n"
         "Там же бот бесплатно сведёт твой голос с этим битом.\n\n"
         "Бесплатно и для коммерческого релиза (free for profit). "
         "Одно условие — подпиши в названии трека: {credit}\n"
         "{tempo}\n{hashtags}")
GIVEN = ("🎚 <b>«{title}»</b> — {artists} type beat{tempo}\n\n"
         "Бесплатно, и для релиза тоже. Одно условие — подпиши в названии трека: <b>{credit}</b>.\n\n"
         f"Записал голос? Жми «{MAKE}» — бит уже будет в заявке, пришлёшь только голос.")
# БИТ НЕДЕЛИ (air, владелец 06.10.2026). В канал приходят те, кто сам делает музыку, — свести трек
# ботом, взять бит, — а лента была целиком из чужих релизов, и подписчики уходили. Бит стал рамкой
# недели: в понедельник он выходит постом, под него пишут и сводят ботом, треки выходят в канале
# с опросом, в воскресенье — итог по голосам (otbor.final). До этого бит выходил раз в два дня
# и ничего за собой не вёл. Приз назван условно: первую неделю треков может прийти меньше трёх.
POST = ("🎚 <b>БИТ НЕДЕЛИ · «{title}»</b>\n{artists} type beat{tempo}\n\n"
        "Бесплатно, и для релиза тоже — подпиши в названии трека: <b>{credit}</b>.\n\n"
        "Как участвовать:\n"
        '1. <a href="{link}">Забери бит в боте</a> и запиши под него голос.\n'
        f"2. Под битом нажми «{MAKE}» и пришли голос — только так бот поймёт, что трек на бит недели.\n"
        f"3. Под готовым треком нажми «{skleyka.OTBOR_KEYS[0]['text']}».\n\n"
        "Треки выходят здесь, под каждым — голосование. Приём — до конца субботы. Наберётся три трека — "
        "в воскресенье итог по голосам, и трек-победитель звукорежиссёр сведёт руками бесплатно.")
POST_ASK = "Под кого сделать следующий бит?"  # первый комментарий (comments.seed берёт поле comment)
# Понедельник, с десяти утра по Москве: неделя начинается с бита, и звук дня достаётся ему (publish.hushed).
WEEK_DAY, WEEK_HOUR_MSK = 0, 10
LAST_NEW = ("🎚 Бит недели: в канал вышел последний новый бит — «{title}». Запас новых кончился: "
            "не пришлёшь новый — в следующий понедельник выйдет повтор.")
LIST = ("🎚 <b>Биты ПЛЁНКИ</b>\n\n"
        "Бесплатно, и для релиза тоже. Одно условие — подпиши в названии трека: <b>{credit}</b>.\n\n"
        "Выбери бит — пришлю файлом.")
EMPTY = "🎚 Битов ПЛЁНКИ пока нет. Найду бесплатный бит как у нужного артиста."
MISSING = ("🎚 Такого бита не нашёл — похоже, ссылка обрезалась. Все биты ПЛЁНКИ — по команде /bity, "
           "или найду бесплатный бит как у нужного артиста.")
VIDEO = "🎬 Ролик к биту №{id} «{title}» — {minutes}, {mb:.0f} МБ. Название и описание — в сообщении выше."
VIDEO_BIG = "🎬 Ролик к биту №{id} вышел {mb:.0f} МБ — Telegram бота принимает до 50. Собери его сам: python -m src.bity --video."
# Документом, а не фото: фото Telegram пережимает, а превью идёт на YouTube как есть.
PREVIEW = "🖼 Превью к биту №{id} для YouTube, 1280×720 — файлом, чтобы Telegram его не пережал."
PHOTOS_FEW = "\n📷 Фото «{mood}» для значков в запасе: {left}. Кончатся — значок вернётся к спинам; скажи Claude добрать запас."
VIDEO_FAILED = "🎬 Ролик к биту №{id} «{title}» не собрался — причина в журнале дежурства."


def load() -> dict:
    return state.read_json(config.BEATS_FILE, {})


def save(catalog: dict) -> None:
    state.write_json(config.BEATS_FILE, catalog)


def newest() -> list[tuple[str, dict]]:
    """Каталог, новые первыми — по номеру: файл пишется с ключами по алфавиту, и «10» в нём стоит раньше «2»."""
    return sorted(load().items(), key=lambda pair: int(pair[0]), reverse=True)


def parse(caption: str) -> dict | None:
    """Подпись бита — {artists, title, bpm, key}; None — не понял. «бит» в начале необязателен:
    так же читается --title сухого прогона."""
    text = " ".join(MARK.sub("", caption, count=1).split())
    if mood := MOOD.search(text):
        text = text[:mood.start()]
    parts = DASH.split(text, maxsplit=1)
    if len(parts) != 2:
        return None
    who, title = parts
    bpm, key = None, ""
    while (tail := TAIL.search(title)) and (tail["bpm"] or tail["key"]):
        if tail["bpm"] and not 50 <= int(tail["bpm"]) <= 250:
            break  # «Лето, 2» — это название, а не темп
        bpm, key = bpm or (int(tail["bpm"]) if tail["bpm"] else None), key or " ".join((tail["key"] or "").split())
        title = title[:tail.start()]
    artists = [name for name in SPLIT.split(who) if name.strip()]
    title = title.strip(" \"'«»“”")
    if not (artists and title):
        return None
    beat = {"artists": artists, "title": title, "bpm": bpm, "key": key}
    return dict(beat, mood=mood["mood"].lower()) if mood else beat


def link(beat_id: str) -> str:
    return f"https://t.me/{config.BOT_HANDLE.lstrip('@')}?start=beat_{beat_id}"


def _tempo(beat: dict, sep: str = ", ") -> str:
    return "".join(f"{sep}{part}" for part in (beat["bpm"] and f"{beat['bpm']} BPM", beat["key"]) if part)


def youtube_title(beat: dict) -> str:
    """Формат лидеров выдачи type beat'ов: [FREE], имена заглавными через «+», название в кавычках.
    Без «ё»: в поиске набирают «темный принц», и подсказки YouTube пишут так же."""
    title = f'[FREE] {" + ".join(beat["artists"]).upper()} type beat - "{beat["title"]}"'
    return title.replace("ё", "е").replace("Ё", "Е")


def tags(beat: dict) -> str:
    """Поле «Теги»: артист type beat, их пара, бесплатность, темп — по убыванию важности, в TAGS_LIMIT."""
    names = [name.casefold().replace("ё", "е") for name in beat["artists"]]  # как в youtube_title
    found = [*(f"{name} type beat" for name in names),
             *([f"{' x '.join(names)} type beat"] if len(names) > 1 else []),
             f"{names[0]} type beat free for profit", "free for profit type beat", "type beat",
             *(f"бит в стиле {name}" for name in names), *([f"{beat['bpm']} bpm type beat"] if beat["bpm"] else [])]
    while len(", ".join(found)) > TAGS_LIMIT:
        found.pop()
    return ", ".join(found)


def about(beat_id: str, beat: dict) -> str:
    """Описание ролика: скачать и свести — в боте (путь через меню, не ссылка), условия, темп, хэштеги."""
    tempo = " · ".join(filter(None, (beat["bpm"] and f"BPM: {beat['bpm']}", beat["key"] and f"Тональность: {beat['key']}")))
    hashtags = " ".join([*(f"#{re.sub(r'\W', '', name.casefold().replace('ё', 'е'))}typebeat" for name in beat["artists"][:3]),
                         "#typebeat", "#freeforprofit"])
    return ABOUT.format(format=(Path(beat.get("name", "")).suffix.lstrip(".").upper() or "WAV"), bot=config.BOT_HANDLE,
                        credit=config.BEAT_CREDIT, tempo=tempo + "\n" if tempo else "", hashtags=hashtags)


def rising(rows, artists: list[dict], now) -> list[str]:
    """Артисты канала с самым заметным движением за RISING_DAYS: новости и релизы сбора (inbox),
    больше — выше, при равенстве — свежее. Под них type beat'ы сейчас и ищут."""
    since = state.iso(now - timedelta(days=RISING_DAYS))
    # Легенды и рок под type beat не ищут: 01.10.2026 на подъёме выходили Slipknot и Linkin Park.
    known = {artist["name"].casefold(): artist["name"] for artist in artists
             if artist.get("tier") != "legend" and not NOT_RAP.search(" ".join(artist.get("tags") or []))}
    count, last = Counter(), {}
    for row in rows:
        stamp = row.get("released_at") or row.get("collected_at") or ""
        if stamp < since:
            continue
        for said in row.get("artists") or [row.get("tracked") or row.get("artist") or ""]:
            if name := known.get(said.casefold()):
                count[name] += 1
                last[name] = max(last.get(name, ""), stamp)
    return sorted(count, key=lambda name: (count[name], last[name]), reverse=True)[:RISING_TOP]


def _plain(text: str) -> str:
    return text.casefold().replace("ё", "е")


def demand(name: str, entries: list[dict]) -> dict:
    """Спрос на type beat'ы под артиста по выдаче YouTube за месяц: ролики с его именем в названии.
    Мерка — медиана просмотров, а не сумма верхних: новый канал получит столько, сколько
    рядовой ролик под это имя, а не лидер ниши."""
    views = sorted((entry.get("view_count") or 0 for entry in entries
                    if _plain(name) in _plain(entry.get("title") or "") and "type beat" in _plain(entry.get("title") or "")),
                   reverse=True)
    return {"name": name, "videos": len(views), "median": int(statistics.median(views)) if views else 0,
            "top": views[0] if views else 0}


def month(name: str) -> list[dict]:
    """Выдача YouTube «<артист> type beat» за месяц, с просмотрами; YouTube не ответил — пусто."""
    from yt_dlp import YoutubeDL

    url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(name + ' type beat')}&sp={THIS_MONTH}"
    try:
        with YoutubeDL({"quiet": True, "no_warnings": True, "extract_flat": True, "playlistend": DEMAND_RESULTS}) as ydl:
            return (ydl.extract_info(url, download=False) or {}).get("entries") or []
    except Exception:  # noqa: BLE001 — без выдачи артист остаётся без мерки, выбор идёт по остальным
        return []


def demand_table(names: list[str]) -> str:
    """Кандидаты по убыванию медианы; кому мерить нечем — в конце."""
    rows = sorted((demand(name, month(name)) for name in dict.fromkeys(names)),
                  key=lambda row: (row["videos"] >= DEMAND_MIN, row["median"]), reverse=True)
    return "\n".join(f"{row['name']}: роликов за месяц {row['videos']}, рядовой собрал {row['median']}, верхний {row['top']}"
                     + ("" if row["videos"] >= DEMAND_MIN else " — мерить нечем") for row in rows)


def texts(beat_id: str, beat: dict, hot: list[str]) -> str:
    """Ответ владельцу на новый бит: всё для заливки на YouTube одним сообщением."""
    return ADDED.format(id=beat_id, title=html.escape(beat["title"]), artists=html.escape(" x ".join(beat["artists"])),
                        tempo=html.escape(_tempo(beat)), link=link(beat_id), name=html.escape(youtube_title(beat)),
                        about=html.escape(about(beat_id, beat)), tags=html.escape(tags(beat)),
                        rising=RISING.format(names=html.escape(", ".join(hot))) if hot else "")


def wants(message: dict, admin: str | int) -> bool:
    """Бит ли это владельца: звук файлом в его личке с подписью со слова «бит». От других — нет:
    их файлы — дорожки сведения или трек в ОТБОР."""
    return (str(admin) == str(message.get("from", {}).get("id")) == str(message.get("chat", {}).get("id"))
            and bool(MARK.match(message.get("caption") or "")) and bool(skleyka._item(message)))


def add(message: dict) -> None:
    """Бит — в каталог, владельцу — тексты для YouTube. Ролик соберёт tick отдельным процессом."""
    chat = str(message["chat"]["id"])
    beat, item = parse(message.get("caption") or ""), skleyka._item(message)
    if not beat:
        telegram.send_message(chat, FORMAT)
        return
    catalog = load()
    if any(known["message"] == item["m"] for known in catalog.values()):
        return  # то же сообщение второй раз: смена упала до записи offset
    beat_id = str(max(map(int, catalog), default=0) + 1)
    catalog[beat_id] = dict(beat, file_id=item["f"], kind="audio" if message.get("audio") else "document",
                            message=item["m"], name=item["n"], size=item["s"], at=state.iso())
    # Фото значка — сразу за битом: ролик собирает другой процесс, а каталог пишет только дежурство.
    if shot := photo(beat):
        catalog[beat_id]["photo"] = shot["id"]
    save(catalog)
    hot = rising(state.read_jsonl(config.INBOX_FILE), collect.load_artists(), state.now())
    telegram.send_message(chat, texts(beat_id, catalog[beat_id], hot))


def _label(what: str) -> str:
    return f"{skleyka.BEAT_COUNT['own']}{what}"


def _hit(beat_id: str, what: str) -> None:
    """Счёт по номеру бита — в самом каталоге: бит выкладывается, чтобы привести людей в бота,
    и пару для следующего выбирают по тому, какой привёл (score, шаг 1 брифа). В источниках
    (service.SOURCES) бит идёт без номера. Это число на бит, не данные о людях."""
    catalog = load()
    if beat_id in catalog:
        hits = catalog[beat_id].setdefault("hits", {})
        hits[what] = hits.get(what, 0) + 1
        save(catalog)


def score() -> str:
    """Свои биты по числу взявших: что сработало у нас, весомее чужих просмотров."""
    rows = [(beat.get("hits", {}), beat_id, beat) for beat_id, beat in newest()]
    rows.sort(key=lambda row: row[0].get("link", 0) + row[0].get("menu", 0), reverse=True)
    return "\n".join(f"№{beat_id} «{beat['title']}» — {' x '.join(beat['artists'])}: взяли из меню {hits.get('menu', 0)}, "
                     f"по ссылке {hits.get('link', 0)}, нажали «Свести» {hits.get('mix', 0)}" for hits, beat_id, beat in rows)


def give(chat_id: str | int, beat_id: str, via: str = "link") -> None:
    """Переход ?start=beat_<id>: бит по file_id с условиями и кнопкой сведения. Бит — подписчику
    канала (владелец, 09.10.2026; до этого отдавался без подписки): проверка — в service, до вызова."""
    beat = load().get(beat_id)
    if not beat:
        telegram.send_message(chat_id, MISSING, buttons=[[skleyka.BEAT_BUTTON]])
        return
    caption = GIVEN.format(title=html.escape(beat["title"]), artists=html.escape(" x ".join(beat["artists"])),
                           tempo=html.escape(_tempo(beat, " · ")), credit=html.escape(config.BEAT_CREDIT))
    telegram.send_by_id(chat_id, beat["kind"], beat["file_id"], caption,
                        buttons=[[{"text": MAKE, "callback_data": f"{PREFIX}{beat_id}"}]])
    skleyka._count(_label(": выдан"))
    _hit(beat_id, via)


def week(moment: datetime | None = None) -> str:
    """Неделя бита — дата её понедельника по Москве: по ней трек находит свой бит (otbor.week_of),
    а итог — свои треки (otbor.final)."""
    from .compose import MSK

    day = (moment or state.now()).astimezone(MSK).date()
    return (day - timedelta(days=day.weekday())).isoformat()


def _aired() -> dict[str, dict]:
    """Посты битов из архива по номеру бита: content/archive/beat-<номер>.json."""
    return {path.stem.removeprefix("beat-"): state.read_json(path, {}) for path in config.ARCHIVE.glob("beat-*.json")}


def weekly(moment: datetime | None = None) -> str:
    """Номер бита этой недели; пусто — бит недели ещё не вышел."""
    monday = week(moment)
    return next((beat_id for beat_id, post in _aired().items() if post.get("week") == monday), "")


def air() -> str:
    """Бит недели — постом в канал: в понедельник с WEEK_HOUR_MSK по Москве, не ночью, один на неделю.
    Возвращает номер вышедшего бита или пустую строку.

    Берётся бит каталога, который ещё не выходил, новый первым. Не выходивших нет — тот, что
    выходил давнее всех: повтор лучше пустой недели. С последним новым владельцу уходит строка —
    запас кончился. Понедельник пропущен целиком (дежурство стояло) — бита недели на этой неделе нет.

    Выходит сам, без кнопки владельцу: бит уже открыт всем в меню бота, решать тут нечего.
    Отметка о выходе — файл поста в content/archive, как у ролика (reels.to_channel): каталог
    ради неё не переписывается. Поле week поста — неделя, по нему бит недели узнаётся (weekly);
    повтор переписывает файл новым постом. Файл beat-<номер>.json, положенный руками, держит бит
    вне канала, как и раньше: новым такой бит уже не считается, а в повтор идут только посты
    с сообщением канала (поле message) — его номером и меряется давность. Не вышло — файл
    возвращается к прежнему виду, и следующий заход пробует снова.
    """
    from . import publish  # publish берёт значок отсюда (shot)
    from .compose import MSK

    now = state.now()
    local = now.astimezone(MSK)
    if local.weekday() != WEEK_DAY or local.hour < WEEK_HOUR_MSK or publish.night(now) or weekly(now):
        return ""
    aired, catalog = _aired(), dict(newest())
    new = [beat_id for beat_id in catalog if beat_id not in aired]
    again = sorted((beat_id for beat_id in catalog if aired.get(beat_id, {}).get("message")),
                   key=lambda beat_id: aired[beat_id]["message"]["message_id"])
    if not new and not again:
        return ""
    beat_id = (new or again)[0]
    beat, path = catalog[beat_id], config.ARCHIVE / f"beat-{beat_id}.json"
    post = {"rubric": "beat", "beat": beat_id, "week": week(now), "comment": POST_ASK,
            "text": POST.format(title=html.escape(beat["title"]), artists=html.escape(" x ".join(beat["artists"])),
                                tempo=html.escape(_tempo(beat)), credit=html.escape(config.BEAT_CREDIT),
                                link=link(beat_id))}
    config.ARCHIVE.mkdir(parents=True, exist_ok=True)
    state.write_json(path, post)
    try:
        publish.to_channel(post, path, config.secret("TELEGRAM_CHANNEL_ID"))
    except Exception:
        if beat_id in aired:
            state.write_json(path, aired[beat_id])
        else:
            path.unlink(missing_ok=True)
        raise
    if len(new) == 1:
        try:
            telegram.send_message(config.secret("TELEGRAM_ADMIN_ID"), LAST_NEW.format(title=html.escape(beat["title"])))
        except telegram.TelegramError as exc:  # бит уже вышел — строка владельцу его не отменяет
            print(f"  бит недели: строка о запасе не ушла: {str(exc)[:120]}")
    return beat_id


def shot(beat_id: str, folder: Path) -> Path:
    """Значок бита файлом — кадр его поста в канале (publish.send)."""
    path = folder / PREVIEW_NAME
    cover(load()[beat_id]).resize(PREVIEW_SIZE, Image.LANCZOS).save(path, quality=92)
    return path


def _button(beat: dict) -> str:
    """Подпись кнопки списка: название, артисты, темп. Не влезает в LABEL_MAX — артисты с конца
    уходят под многоточие: полное имя первого важнее обрубка третьего."""
    names = list(beat["artists"])
    tempo = f" · {beat['bpm']} BPM" if beat["bpm"] else ""
    while True:
        more = "…" if len(names) < len(beat["artists"]) else ""
        text = f"{beat['title']} · {' x '.join(names)}{more}{tempo}"
        if len(text) <= LABEL_MAX or len(names) == 1:
            return text
        names.pop()


def listing(chat_id: str | int) -> None:
    """«🎚 БИТЫ» в меню и /bity: биты кнопками, новые первыми. Бит в каталоге один — сразу он:
    список из одной кнопки — лишнее нажатие. Подписчику канала, как по ссылке beat_ (проверка — в service)."""
    catalog = newest()
    if len(catalog) == 1:
        pick(chat_id, catalog[0][0])
    elif catalog:
        rows = [[{"text": _button(beat), "callback_data": f"{PICK}{beat_id}"}] for beat_id, beat in catalog[:LIST_MAX]]
        telegram.send_message(chat_id, LIST.format(credit=html.escape(config.BEAT_CREDIT)), buttons=rows)
    else:
        telegram.send_message(chat_id, EMPTY, buttons=[[skleyka.BEAT_BUTTON]])


def pick(chat_id: str | int, beat_id: str) -> None:
    """Бит из меню или списка: та же выдача, что по ссылке, но со своей меткой — владелец видит,
    откуда берут бит."""
    skleyka._count(MENU_LABEL)
    give(chat_id, beat_id, via="menu")


def callback(chat_id: str | int, user_id: str | int, beat_id: str, *, admin: bool = False) -> None:
    """«🎚 Свести с этим битом»: заявка СВЕДЕНИЯ «вокал + бит», бит в ней уже лежит. Номер
    сообщения — владельца: больше 20 МБ сведение качает бит служебным входом по нему."""
    beat = load().get(beat_id)
    if not beat:
        telegram.send_message(chat_id, MISSING, buttons=[[skleyka.BEAT_BUTTON]])
        return
    # b — номер бита в каталоге: по нему готовый трек узнаётся треком на бит недели (skleyka.song,
    # otbor.week_of). Лежит в записи файла, а не заявки: сменил человек бит — номер ушёл вместе с файлом.
    item = {"m": beat["message"], "f": beat["file_id"], "n": f"{beat['title'][:50]}{Path(beat['name']).suffix}",
            "s": beat["size"], "g": "", "b": beat_id}
    _hit(beat_id, "mix")
    skleyka.start(chat_id, user_id, admin=admin, beat=item)


def matching(names: list[str], bpm: float | None = None) -> list[dict]:
    """Биты владельца для «🔎 Нет бита» (skleyka.find_beats): артист среди названных — строкой выдачи,
    но со ссылкой на бота вместо YouTube, новые первыми. Темп далёк от голоса — прочь, неназванный — годится."""
    plain = lambda name: name.casefold().replace("ё", "е")  # набирают «темный принц», в каталоге — «Тёмный»
    wanted = {plain(name) for name in names}
    found = []
    for beat_id, beat in newest():
        if not wanted & {plain(name) for name in beat["artists"]}:
            continue
        if bpm and beat["bpm"] and abs(skleyka._rate(beat["bpm"], bpm) - 1) > skleyka.SWAP_TEMPO:
            continue
        found.append({"id": beat_id, "title": youtube_title(beat), "channel": "ПЛЁНКА", "duration": 0,
                      "bpm": beat["bpm"], "link": link(beat_id)})
    return found


# Ролик, что собирается сейчас: (процесс, номер бита). Один на дежурство.
_RENDER: tuple[subprocess.Popen, str] | None = None


def rendering() -> bool:
    return bool(_RENDER and _RENDER[0].poll() is None)


def busy() -> bool:
    """Идёт ролик или бит его ждёт: смена тогда не уступает свежему коду."""
    return rendering() or any("video" not in beat for beat in load().values())


def tick() -> None:
    """Круг дежурства: кончившийся ролик — отметка в каталоге, следующий бит без ролика — в ход,
    когда сведение не идёт и очередь его пуста. Отметка «video» — и о неудаче: иначе битый бит
    собирался бы каждый круг. Смену оборвали посреди ролика — отметки нет, соберёт следующая."""
    global _RENDER
    if _RENDER and _RENDER[0].poll() is not None:
        (process, beat_id), _RENDER = _RENDER, None
        catalog = load()
        if beat_id in catalog:
            catalog[beat_id]["video"] = process.returncode == 0
            save(catalog)
            if process.returncode:
                telegram.send_message(config.secret("TELEGRAM_ADMIN_ID"),
                                      VIDEO_FAILED.format(id=beat_id, title=html.escape(catalog[beat_id]["title"])))
    if _RENDER:
        return
    waiting = [beat_id for beat_id, beat in load().items() if "video" not in beat]
    from . import ocenka  # ocenka импортирует этот модуль

    # Оценка большого файла (ocenka.logged) держит тот же служебный вход, что и ролик.
    if waiting and not skleyka.busy(drafts=False) and not ocenka.logged():
        print(f"  ролик к биту {waiting[0]}: пошёл")
        _RENDER = subprocess.Popen([sys.executable, "-m", "src.bity", "--render", waiting[0]], cwd=config.ROOT), waiting[0]


def _plate(draw: ImageDraw.ImageDraw, text: str, size: int, top: float, fill, limit: float = WIDTH) -> None:
    """Плашка по центру кадра: на свету фар и красных отблесках голый текст не читается, нужна своя подложка."""
    while draw.textlength(text, font=stories.font(size)) > limit and size > 40:
        size -= 4
    face = stories.font(size)
    half = (draw.textlength(text, font=face) + size * 0.7) / 2
    draw.rectangle([WIDTH / 2 - half, top, WIDTH / 2 + half, top + size * 1.35], fill=fill)
    draw.text((WIDTH / 2, top + size * 0.68), text, font=face, fill=WHITE, anchor="mm")


def _print(draw: ImageDraw.ImageDraw, name: str, x: float, y: float) -> None:
    """Имя принтом на спине: по слову в строку вокруг линии y, кегль ужимается до ширины спины."""
    lines = name.split()
    size = 128 if len(lines) == 1 else 120
    while max(draw.textlength(line, font=stories.font(size)) for line in lines) > BACK_WIDTH and size > 40:
        size -= 4
    face = stories.font(size)
    for n, line in enumerate(lines):
        base = y + (n - (len(lines) - 1) / 2) * size * 1.04
        draw.text((x + 4, base + 5), line, font=face, fill=(0, 0, 0), anchor="ms")
        draw.text((x, base), line, font=face, fill=WHITE, anchor="ms")


def _stock() -> tuple[list[dict], set]:
    """Запас фото и те, что уже отданы битам."""
    return state.read_json(config.BEAT_PHOTOS, []), {beat.get("photo") for beat in load().values()}


def photo(beat: dict) -> dict | None:
    """Фото значка: записанное за битом, иначе первое в запасе его настроения, не отданное другому.
    Фото этого настроения вышли — None: значок вернётся к спинам, чужое настроение хуже."""
    stock, taken = _stock()
    return next((shot for shot in stock if shot["id"] == beat.get("photo")), None) \
        or next((shot for shot in stock if shot["id"] not in taken and _mood(shot) == _mood(beat)), None)


def _mood(item: dict) -> str:
    return item.get("mood", "обычный")


def _picture(url: str) -> Image.Image:
    response = requests.get(url, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    return Image.open(io.BytesIO(response.content)).convert("RGB")


def cover(beat: dict) -> Image.Image:
    return portrait(beat) or _backs(beat)


def portrait(beat: dict) -> Image.Image | None:
    """Кадр ролика и превью — плёночный портрет: фото запаса 4:3 по центру чёрного кадра, обрезка вокруг
    focus, и одно слово названия на линии y (доля высоты: 0.93 — внизу, 0.34 — наверху, где низ занят лицом).
    Фото идёт как есть, без обработки. Имён артистов, темпа и плашек нет: их несёт название ролика.
    Запас вышел или фото не скачалось — None, и кадром идут прежние спины (cover): ролик важнее вида."""
    shot = photo(beat)
    if not shot:
        return None
    try:
        picture = _picture(shot["url"])
    except (OSError, requests.RequestException) as error:
        print(f"  значок: фото {shot['id']} не скачалось ({error}) — спины")
        return None
    img = Image.new("RGB", (WIDTH, HEIGHT), "black")
    img.paste(ImageOps.fit(picture, PHOTO_BOX, centering=(0.5, shot["focus"])), ((WIDTH - PHOTO_BOX[0]) // 2, 0))
    # ponytail: слово одно — из названия в несколько слов идёт самое длинное; захочется другое — поле в подписи бита.
    word = max(beat["title"].split(), key=len).upper()
    font, weight, size = WORD_FONTS.get(_mood(beat), (WORD_FONT, 500, WORD_SIZE[0]))
    while True:
        face = ImageFont.truetype(str(font), size)
        face.set_variation_by_axes([weight])
        gap = -size * 0.06
        width = sum(face.getlength(char) + gap for char in word) - gap
        if width <= PHOTO_BOX[0] * WORD_WIDTH or size <= WORD_SIZE[1]:
            break
        size -= 10
    draw, x = ImageDraw.Draw(img), (WIDTH - width) / 2
    for char in word:
        draw.text((x, HEIGHT * shot["y"]), char, font=face, fill="white", anchor="ls")
        x += face.getlength(char) + gap
    return img


def _backs(beat: dict) -> Image.Image:
    """Запасной кадр: двое спинами к зрителю против света фар (config.BEAT_BACK), имена артистов —
    принтом на спинах, внизу плашка «FREE TYPE BEAT». Имена — без «ё», как в youtube_title."""
    img = Image.open(config.BEAT_BACK).convert("RGB")
    draw = ImageDraw.Draw(img)
    names = [name.upper().replace("Ё", "Е") for name in beat["artists"]]
    if len(names) == 1:
        # ponytail: один артист — имя плашкой между спинами, а не на спине: подписать одного из двоих
        # значит назвать второго никем. Своего кадра с одной спиной нет; понадобится — второй ассет.
        _plate(draw, names[0], 128, 560, make_cover.INK, WIDTH * 0.8)
    else:
        # ponytail: спин две — третий и дальше на кадр не идут (zip берёт первых двоих), они живут
        # в названии ролика и тегах. Понадобятся на кадре — отдельная раскладка.
        for name, (x, y) in zip(names, BACKS):
            _print(draw, name, x, y)
    _plate(draw, "FREE TYPE BEAT", 54, 965, make_cover.ACCENT)
    return img


def fog() -> Image.Image:
    """Туман для ролика: шум в два слоя, крупный и помельче, растянутый до кадра и замкнутый
    по горизонтали, — плывёт по кругу без шва, сколько бы ни длился бит. Шум из своего зерна: туман
    одинаков от сборки к сборке, и яркое облако не ляжет на имя в одном ролике из десяти. Соседние
    копии по бокам нужны растяжке: без них край плитки не сошёлся бы с её началом."""
    rng = random.Random(1)

    def layer(w: int, h: int) -> Image.Image:
        tile = Image.frombytes("L", (w, h), rng.randbytes(w * h))
        wide = Image.new("L", (w * 3, h))
        for n in range(3):
            wide.paste(tile, (w * n, 0))
        return wide.resize((WIDTH * 3, HEIGHT), Image.BICUBIC).crop((WIDTH, 0, WIDTH * 2, HEIGHT))

    return Image.blend(layer(8, 5), layer(20, 11), 0.35)


def maxrate(seconds: float) -> int:
    """Потолок видеопотока, кбит/с: 1800 хватает кадру с зерном, а длинному биту — сколько влезает
    в VIDEO_BUDGET за вычетом звука: ролик обязан пролезть в telegram.MAX_UPLOAD."""
    return int(min(1800, max(200, VIDEO_BUDGET * 8 / 1000 / seconds - AUDIO_KBPS)))


def ffmpeg_args(frame: Path, mist: Path | None, audio: Path, dest: Path, seconds: float, bpm: int | None) -> list[str]:
    """Команда ролика. Текст уже в кадре и движется вместе с ним: наезд дышит на ±4 % вокруг точки
    чуть ниже середины — плашка у нижнего края из кадра не уходит. Наезд — perspective, а не zoompan:
    тот режет окно по целым пикселям, и на таком медленном ходу край букв дёргается даже по кадру,
    увеличенному вдвое (замер 01.10.2026: скачки до 0,4 пикселя между кадрами при ходе 0,1), а perspective
    считает доли пикселя (0,07). Туман — поверх, сложением «экран» по яркости, и только спинам (mist):
    на плёночном портрете он делает чёрное серым и съедает темноту снимка. Свет пульсирует раз
    в такт (bpm / 4 долей в минуту), темпа нет — без пульса.

    Бесконечных источников здесь нет вовсе: кадр и туман — по одной картинке, длину им задаёт счёт
    кадров в loop=, и ещё явная -t перед выходом. 30.09.2026 бесконечный источник (-loop 1 без своей -t)
    забил диск на 560 ГБ; появится здесь -loop 1 или lavfi — только со своей -t или d=."""
    frames = math.ceil(seconds * FPS)
    rate = maxrate(seconds)
    z = f"(1.04+0.04*sin(2*PI*on/{BREATH * FPS}))"
    left, top = f"W*(1-1/{z})/2", f"H*(1-1/{z})*0.8"
    pulse = f",eq=brightness='0.035*sin(2*PI*{bpm / 240:.4f}*t)':eval=frame" if bpm else ""
    graph = (f"[0:v]format=yuv420p,loop=loop={frames}:size=1,"
             f"perspective=x0='{left}':y0='{top}':x1='{left}+W/{z}':y1='{top}':x2='{left}':y2='{top}+H/{z}'"
             f":x3='{left}+W/{z}':y3='{top}+H/{z}':sense=source:eval=frame:interpolation=cubic{pulse}")
    if mist:
        graph += (f"[bg];[1:v]format=yuv420p,loop=loop={frames}:size=1,scroll=horizontal={FOG_SPEED / FPS / WIDTH:.6f}[fog];"
                  f"[bg][fog]blend=c0_mode=screen")
    return [clips.ffmpeg(), "-y", "-hide_banner", "-framerate", str(FPS), "-i", str(frame),
            *(["-framerate", str(FPS), "-i", str(mist)] if mist else []), "-i", str(audio), "-filter_complex", graph + "[v]",
            "-map", "[v]", "-map", f"{2 if mist else 1}:a", "-c:v", "libx264", "-preset", PRESET, "-crf", "23",
            "-maxrate", f"{rate}k", "-bufsize", f"{rate * 2}k", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", f"{AUDIO_KBPS}k", "-movflags", "+faststart", "-t", f"{seconds:.3f}", str(dest)]


def video(audio: Path, beat: dict, folder: Path) -> Path:
    """Ролик: живой кадр и бит. Рядом — cover.png (кадр 1920×1080) и preview.jpg (он же 1280×720,
    превью для YouTube)."""
    seconds = clips.probe_seconds(audio)
    if not seconds:
        raise clips.ClipError("длина бита не читается")
    folder.mkdir(parents=True, exist_ok=True)
    frame, mist, dest = folder / "cover.png", folder / "fog.png", folder / "video.mp4"
    img = portrait(beat)
    if img:
        mist = None
    else:
        img = _backs(beat)
        Image.eval(fog(), lambda value: value * FOG_LIGHT // 255).save(mist)
    img.save(frame)
    img.resize(PREVIEW_SIZE, Image.LANCZOS).save(folder / PREVIEW_NAME, quality=92)
    clips.run(ffmpeg_args(frame, mist, audio, dest, seconds, beat.get("bpm")))
    if mist:
        mist.unlink()
    return dest


def render(beat_id: str) -> int:
    """Процесс ролика (--render): бит у Telegram — до 20 МБ через Bot API, больше — служебным
    входом по номеру сообщения владельца; ролик и превью — владельцу."""
    beat, admin = load()[beat_id], config.secret("TELEGRAM_ADMIN_ID")
    with tempfile.TemporaryDirectory(prefix="bity-") as tmp:
        audio = Path(tmp) / f"beat{Path(beat['name']).suffix.lower()}"
        if 0 < beat["size"] <= telegram.MAX_DOWNLOAD:
            audio.write_bytes(telegram.download_file(beat["file_id"]))
        else:
            with telegram.service_login() as client:
                audio = telegram.fetch_big(client, beat["message"], audio)
        clip = video(audio, beat, Path(tmp) / "out")
        mb = clip.stat().st_size / 2**20
        if clip.stat().st_size > telegram.MAX_UPLOAD:
            telegram.send_message(admin, VIDEO_BIG.format(id=beat_id, mb=mb))
        else:
            seconds = round(clips.probe_seconds(clip))
            telegram.send_video_file(admin, clip, VIDEO.format(id=beat_id, title=html.escape(beat["title"]), mb=mb,
                                                               minutes=f"{seconds // 60}:{seconds % 60:02d}"),
                                     seconds=seconds, width=WIDTH, height=HEIGHT)
        stock, taken = _stock()
        left = sum(shot["id"] not in taken and _mood(shot) == _mood(beat) for shot in stock)
        telegram.send_document(admin, clip.with_name(PREVIEW_NAME), PREVIEW.format(id=beat_id)
                               + (PHOTOS_FEW.format(mood=_mood(beat), left=left) if left < PHOTOS_LOW else ""))
    return 0


def _selftest() -> None:
    """Без сети и Telegram: всё пишется во временную папку, отправки — в список."""
    from unittest import mock

    from . import moderate, service

    tmp = Path(tempfile.mkdtemp(prefix="bity-test-"))
    sent: list[tuple] = []
    counted: list[str] = []
    owner = "1"

    def message(caption: str, sender: str = owner, audio: bool = True, message_id: int = 5) -> dict:
        found = {"file_id": f"F{message_id}", "file_name": "polet.wav", "file_size": 40 * 2**20}
        return {"message_id": message_id, "chat": {"id": int(sender), "type": "private"}, "from": {"id": int(sender)},
                "caption": caption, **({"audio": found} if audio else {"document": dict(found, mime_type="audio/wav")})}

    asked: list[str] = []
    state.write_json(tmp / "photos.json", [{"id": 11, "url": "https://photo/11", "focus": 0.42, "y": 0.93},
                                           {"id": 33, "url": "https://photo/33", "focus": 0.5, "y": 0.93, "mood": "злой"},
                                           {"id": 22, "url": "https://photo/22", "focus": 0.5, "y": 0.34}])
    with mock.patch.object(config, "BEATS_FILE", tmp / "beats.json"), \
            mock.patch.object(config, "BEAT_PHOTOS", tmp / "photos.json"), \
            mock.patch.dict(globals(), {"_picture": lambda url: asked.append(url) or Image.new("RGB", (1600, 1200), (90, 60, 40))}), \
            mock.patch.object(config, "SKLEYKA_FILE", tmp / "skleyka.json"), \
            mock.patch.object(config, "TOUCH_FILE", tmp / "touch.json"), \
            mock.patch.object(config, "INBOX_FILE", tmp / "inbox.jsonl"), \
            mock.patch.object(config, "secret", lambda name, required=True: owner if name == "TELEGRAM_ADMIN_ID" else ""), \
            mock.patch.object(collect, "load_artists", lambda: [{"name": "Kizaru"}, {"name": "Toxi$"}]), \
            mock.patch.object(skleyka, "_count", counted.append), \
            mock.patch.object(telegram, "send_message", lambda chat, text, **kw: sent.append(("text", str(chat), text, kw))
                              or {"message_id": len(sent)}), \
            mock.patch.object(telegram, "send_by_id", lambda chat, kind, file_id, caption="", **kw:
                              sent.append((kind, str(chat), file_id, caption, kw)) or {"message_id": len(sent)}), \
            mock.patch.object(telegram, "edit_markup", lambda *a, **k: None):
        # Подпись: артисты, название, темп и тональность; без тире — не понял.
        assert parse("бит Kizaru x Toxi$ — Полёт, 140 Fm") == \
            {"artists": ["Kizaru", "Toxi$"], "title": "Полёт", "bpm": 140, "key": "Fm"}
        assert parse("Бит: OG Buda & Mayot — «Холодно, мама», 142 bpm, F# minor") == \
            {"artists": ["OG Buda", "Mayot"], "title": "Холодно, мама", "bpm": 142, "key": "F# minor"}
        assert parse("бит Kizaru x Toxi$ — Полёт, 140 Fm, Злой") == \
            {"artists": ["Kizaru", "Toxi$"], "title": "Полёт", "bpm": 140, "key": "Fm", "mood": "злой"}
        assert parse("бит Kizaru x Toxi$ — Злой")["title"] == "Злой", "без запятой — это название"
        assert parse("бит Kizaru х Toxi$ - Лето, 2") == {"artists": ["Kizaru", "Toxi$"], "title": "Лето, 2", "bpm": None, "key": ""}
        assert parse("бит Kizaru") is None and parse("бит — Полёт") is None

        # Маршрут: «бит» от владельца — сюда; от другого, «биты» и файл без подписи — старыми путями.
        assert wants(message("бит Kizaru x Toxi$ — Полёт, 140 Fm"), owner)
        assert wants(message("Бит Kizaru — Полёт", audio=False), owner)
        assert not wants(message("бит Kizaru — Полёт", sender="7"), owner)
        assert not wants(message("биты на неделю"), owner) and not wants(message(""), owner)
        assert not wants({**message("бит Kizaru — Полёт"), "audio": None}, owner)
        routed = []
        with mock.patch.object(moderate.reels, "reply_kind", lambda m: routed.append("reels") or ""), \
                mock.patch.object(moderate.skleyka, "take", lambda m: routed.append("skleyka")), \
                mock.patch.object(moderate.otbor, "handle", lambda m, admin=False: routed.append("otbor")), \
                mock.patch.object(moderate, "attach_track", lambda m, a: routed.append("track") or ""), \
                mock.patch.object(moderate.comments, "is_channel_post", lambda m, c: False), \
                mock.patch.object(moderate.skleyka, "unkey", lambda m: None):
            moderate.process([{"update_id": 1, "message": message("бит Kizaru x Toxi$ — Полёт, 140 Fm")}],
                             {}, owner, False, 0)
            assert routed == [] and list(load()) == ["1"], routed
            moderate.process([{"update_id": 2, "message": {**message("вот трек", message_id=6),
                                                           "reply_to_message": {"message_id": 3}}}], {}, owner, False, 0)
            moderate.process([{"update_id": 3, "message": message("бит Kizaru — Полёт", sender="7", message_id=7)}],
                             {}, owner, False, 0)
            assert routed == ["reels", "track", "otbor"], routed
        # Тот же апдейт второй раз — бит один.
        add(message("бит Kizaru x Toxi$ — Полёт, 140 Fm"))
        beat = load()["1"]
        assert list(load()) == ["1"] and beat["file_id"] == "F5" and beat["kind"] == "audio" and beat["message"] == 5
        reply = sent[0][2]
        assert "?start=beat_1" in reply and "[FREE] KIZARU + TOXI$ type beat - &quot;Полет&quot;" in reply
        assert config.BEAT_CREDIT in reply and "BPM: 140 · Тональность: Fm" in reply and "kizaru type beat" in reply
        assert "(WAV)" in reply and "#toxitypebeat" in reply and "На подъёме" not in reply, "пустой сбор — без подъёма"
        add(message("бит Kizaru без тире", message_id=8))
        assert sent[-1][2] == FORMAT and list(load()) == ["1"]
        assert len(tags({"artists": [f"artist number {n}" for n in range(40)], "bpm": 140, "key": ""})) <= TAGS_LIMIT

        # На подъёме: новости и релизы за две недели, больше — выше, старое не в счёт.
        now = state.now()
        rows = [{"kind": "news", "artists": ["Toxi$"], "released_at": state.iso(now - timedelta(days=d))} for d in (1, 2)] \
            + [{"kind": "release", "tracked": "Kizaru", "artist": "Kizaru & X", "released_at": state.iso(now)},
               {"kind": "news", "artists": ["Kizaru"], "released_at": state.iso(now - timedelta(days=30))},
               {"kind": "news", "artists": ["Незнакомец"], "released_at": state.iso(now)}]
        assert rising(rows, collect.load_artists(), now) == ["Toxi$", "Kizaru"]

        # Переход по ссылке: бит по file_id с условием и кнопкой; неизвестный — «🔎 Нет бита».
        sent.clear()
        with mock.patch.object(service, "count_source", counted.append):
            service.handle_message({"chat": {"id": 42, "type": "private"}, "from": {"id": 42}, "message_id": 1,
                                    "text": "/start beat_1"}, {})
            assert sent[-1][:3] == ("audio", "42", "F5") and config.BEAT_CREDIT in sent[-1][3]
            assert sent[-1][4]["buttons"] == [[{"text": MAKE, "callback_data": f"{PREFIX}1"}]]
            service.handle_message({"chat": {"id": 42, "type": "private"}, "from": {"id": 42}, "message_id": 2,
                                    "text": "/start beat_99"}, {})
            assert sent[-1][2] == MISSING and sent[-1][3]["buttons"] == [[skleyka.BEAT_BUTTON]]
            assert counted == ["beat", "БИТ ПЛЁНКИ: выдан", "beat"], counted

            # Кнопка: заявка «вокал + бит» с битом внутри, вопрос — о голосе; «🔎 Нет бита» — и без заявки.
            service.handle_callback({"id": "q", "data": f"{PREFIX}1", "from": {"id": 42},
                                     "message": {"message_id": 3, "chat": {"id": 42}}}, {})
        draft = skleyka.load()["drafts"]["42"]
        assert draft["plan"] == ["вокал", "бит"] and draft["beat"] == "own" and draft["asked"] == 0
        # Номер бита едет в заявку с файлом: по нему трек узнаётся треком на бит недели.
        assert draft["files"] == [{"m": 5, "f": "F5", "n": "Полёт.wav", "s": 40 * 2**20, "g": "", "b": "1", "r": "бит"}]
        assert "пришли вокал" in sent[-1][2]
        skleyka.take({**message("", sender="42", message_id=20), "caption": None})
        assert [f["r"] for f in skleyka.load()["drafts"]["42"]["files"]] == ["бит", "вокал"]
        skleyka.cancel(42)
        skleyka.callback(43, 43, "g")
        assert sent[-1][2] == skleyka.BEATS_ASK and "43" not in skleyka.load()["drafts"]
        # Голос уже прислан, заявка ждёт бит — бит ПЛЁНКИ ложится в неё, а не новой заявкой.
        skleyka.start(44, 44)
        skleyka.callback(44, 44, "m:1")
        skleyka.take({**message("", sender="44", message_id=30), "caption": None})
        callback(44, 44, "1")
        draft = skleyka.load()["drafts"]["44"]
        assert [f["r"] for f in draft["files"]] == ["вокал", "бит"] and draft["step"] == 2, draft
        # Лимит суток — как обычно: заявки нет, человеку отказ с путями.
        data = skleyka.load()
        data["used"]["45"] = [state.iso()] * config.SKLEYKA_PER_DAY
        skleyka.save(data)
        callback(45, 45, "1")
        assert "45" not in skleyka.load()["drafts"] and sent[-1][2].startswith("Треков в сутки")
        # Готовый трек с битом ПЛЁНКИ — в счётчик.
        assert skleyka.BEAT_COUNT["own"] + " → трек" == "БИТ ПЛЁНКИ → трек"

        # Описание ролика: путь словами и ни одной ссылки — YouTube её не оставил; прямая — только владельцу.
        text = about("1", beat)
        assert text.splitlines()[0] == f"Скачать бесплатно (WAV): Telegram → {config.BOT_HANDLE} → кнопка «🎚 БИТЫ»"
        assert "t.me" not in text and "http" not in text and "Прямая ссылка на бит" in reply
        assert ABOUT.count("{bot}") == 1 and "{link}" not in ABOUT

        # «🎚 БИТЫ» в меню и /bity: один бит — сразу он, со своей меткой; несколько — список кнопками,
        # новые первыми и по номеру, длинная подпись теряет артистов с конца; пустой каталог — «🔎 Нет бита».
        sent.clear()
        counted.clear()
        listing(46)
        assert sent[-1][:3] == ("audio", "46", "F5") and counted == [MENU_LABEL, "БИТ ПЛЁНКИ: выдан"], counted
        assert sent[-1][4]["buttons"] == [[{"text": MAKE, "callback_data": f"{PREFIX}1"}]], "под битом — прежняя кнопка"
        catalog = load()
        save({**catalog, "2": dict(beat, title="Фары", artists=["MADK1D", "Тёмный принц", "TEWIQ"], bpm=156)})
        listing(46)
        assert sent[-1][2] == LIST.format(credit=config.BEAT_CREDIT) and len(sent) == 2, "список — без файла"
        assert sent[-1][3]["buttons"] == [
            [{"text": "Фары · MADK1D x Тёмный принц… · 156 BPM", "callback_data": f"{PICK}2"}],
            [{"text": "Полёт · Kizaru x Toxi$ · 140 BPM", "callback_data": f"{PICK}1"}]]
        assert _button(dict(beat, bpm=None)) == "Полёт · Kizaru x Toxi$"
        assert not PICK.startswith(PREFIX) and not PREFIX.startswith(PICK), "кнопки списка и сведения не путаются"
        pick(46, "2")
        assert sent[-1][:3] == ("audio", "46", "F5") and counted[-2:] == [MENU_LABEL, "БИТ ПЛЁНКИ: выдан"]
        # Счёт по номеру бита: меню, ссылка и «Свести» — врозь; в списке первым тот, кого взяли больше.
        assert (load()["1"]["hits"], load()["2"]["hits"]) == ({"link": 1, "menu": 1, "mix": 3}, {"menu": 1})
        assert score().splitlines()[0] == "№1 «Полёт» — Kizaru x Toxi$: взяли из меню 1, по ссылке 1, нажали «Свести» 3"
        _hit("404", "menu")
        assert "404" not in load(), "ссылка на бит, которого нет, каталог не трогает"
        save({str(n): beat for n in range(1, LIST_MAX + 5)})
        listing(46)
        assert [row[0]["callback_data"] for row in sent[-1][3]["buttons"]] == \
            [f"{PICK}{n}" for n in range(LIST_MAX + 4, 4, -1)], "новые первыми: 24, 23, … — не «9» раньше «10»"
        save({})
        listing(46)
        assert sent[-1][2] == EMPTY and sent[-1][3]["buttons"] == [[skleyka.BEAT_BUTTON]]
        save(catalog)

        # «🔎 Нет бита»: биты владельца с этим артистом — первыми, со ссылкой на бота; чужой темп — прочь.
        assert [v["link"] for v in matching(["kizaru"])] == [link("1")] and not matching(["Mayot"])
        assert not matching(["Kizaru"], 100) and matching(["Kizaru"], 71)
        with mock.patch.object(skleyka.youtube_comments, "search", lambda query, count: []):
            found = skleyka.find_beats("Kizaru")
        assert [v["link"] for v in found] == [link("1")], "YouTube молчит — свои биты всё равно есть"
        assert f'href="{link("1")}"' in skleyka.beats_text("Kizaru", found)

        # Значок: фото запаса 4:3 по центру чёрного кадра и белое слово названия; фото записано за битом
        # при приёме, следующему биту — следующее; сеть не трогается.
        assert load()["1"]["photo"] == 11 and photo({"title": "Новый"})["id"] == 22
        assert photo({"title": "Новый", "mood": "злой"})["id"] == 33 and photo({"title": "Новый", "mood": "кино"}) is None
        frame = cover(load()["1"])
        assert frame.size == (WIDTH, HEIGHT) and frame.getpixel((100, 540)) == (0, 0, 0)
        assert frame.getpixel((960, 300)) == (90, 60, 40) and asked == ["https://photo/11"], asked
        assert any(frame.getpixel((x, 960)) == (255, 255, 255) for x in range(240, 1680)), "слово названия внизу"
        upper = cover({"title": "Тёмная ночь", "artists": ["Kizaru"]})
        assert asked[-1] == "https://photo/22" and upper.getpixel((960, 700)) == (90, 60, 40)
        assert any(upper.getpixel((x, 300)) == (255, 255, 255) for x in range(240, 1680)), "y 0.34 — слово наверху"
        # Фото не скачалось или запас вышел — спины: 1920×1080 при любом числе артистов, третий на кадр не идёт.
        with mock.patch.dict(globals(), {"_picture": lambda url: (_ for _ in ()).throw(OSError("нет сети"))}):
            assert cover(beat).tobytes() == _backs(beat).tobytes() != frame.tobytes()
        with mock.patch.object(config, "BEAT_PHOTOS", tmp / "none.json"):
            assert photo({"title": "Новый"}) is None and cover({"title": "Ночь", "artists": ["Kizaru", "Toxi$"]}).size == (WIDTH, HEIGHT)
        frames = {n: _backs(dict(beat, artists=["Big Baby Tape", "Тёмный Принц", "Kizaru"][:n])) for n in (1, 2, 3)}
        assert all(img.size == (WIDTH, HEIGHT) for img in frames.values())
        assert frames[3].tobytes() == frames[2].tobytes() != frames[1].tobytes()
        # Команда ролика: бесконечных входов нет, а появится -loop — своя -t до его -i; -t и перед выходом.
        args = ffmpeg_args(Path("c.png"), Path("f.png"), Path("b.wav"), Path("v.mp4"), 300.0, 156)
        assert "lavfi" not in args and args[-3:-1] == ["-t", "300.000"]
        assert all("-t" in args[at:args.index("-i", at)] for at, arg in enumerate(args) if arg == "-loop")
        # Свет бьётся раз в такт: 156 BPM — 0,65 Гц; темпа нет — пульса нет.
        assert "eq=brightness='0.035*sin(2*PI*0.6500*t)'" in " ".join(args)
        assert "eq=" not in " ".join(ffmpeg_args(Path("c.png"), Path("f.png"), Path("b.wav"), Path("v.mp4"), 300.0, None))
        # Портрету туман не идёт: входов два, звук — второй; спинам — три и сложение «экран».
        clean = ffmpeg_args(Path("c.png"), None, Path("b.wav"), Path("v.mp4"), 300.0, 156)
        assert "blend" not in " ".join(clean) and clean.count("-i") == 2 and "1:a" in clean and "blend" in " ".join(args)
        # Битрейт: короткому биту 1800, длинному — сколько влезает; с буфером кодека ролик меньше 50 МБ.
        assert maxrate(159) == 1800 > maxrate(300) > maxrate(900) >= 200
        assert all((maxrate(t) + AUDIO_KBPS) * 125 * t + maxrate(t) * 250 < telegram.MAX_UPLOAD for t in (159, 300, 600, 900))
        # Туман замкнут: левый край продолжает правый, шва при ходе по кругу нет.
        mist = fog()
        edge = [abs(mist.getpixel((0, y)) - mist.getpixel((WIDTH - 1, y))) for y in range(0, HEIGHT, 40)]
        assert mist.size == (WIDTH, HEIGHT) and max(edge) <= 3, edge

        # Ролик: синтетический бит с d= — длина и размер, кадр 1920×1080, превью 1280×720; tick отмечает сделанное.
        audio = tmp / "beat.wav"
        clips.run([clips.ffmpeg(), "-y", "-f", "lavfi", "-i", "sine=f=55:d=7", str(audio)])
        clip = video(audio, beat, tmp / "out")
        assert abs(clips.probe_seconds(clip) - 7) < 0.2 and clip.stat().st_size < telegram.MAX_UPLOAD
        assert Image.open(tmp / "out" / "cover.png").size == (WIDTH, HEIGHT)
        assert Image.open(tmp / "out" / PREVIEW_NAME).size == PREVIEW_SIZE
        global _RENDER
        spawned = []
        with mock.patch.object(subprocess, "Popen", lambda args, **_: spawned.append(args) or subprocess.CompletedProcess(args, 0)), \
                mock.patch.object(subprocess.CompletedProcess, "poll", lambda self: 0, create=True):
            assert busy()
            tick()
            assert spawned == [[sys.executable, "-m", "src.bity", "--render", "1"]]
            tick()
            assert load()["1"]["video"] is True and not busy() and _RENDER is None
            tick()
            assert len(spawned) == 1, "ролик один раз"
    found = demand("Тёмный принц", [{"title": "[FREE] ТЕМНЫЙ ПРИНЦ type beat", "view_count": 900},
                                    {"title": "темный принц x madk1d Type Beat", "view_count": 100},
                                    {"title": "[FREE] Темный принц type beat - ночь", "view_count": 300},
                                    {"title": "Тёмный принц — клип", "view_count": 10 ** 6}])
    assert found == {"name": "Тёмный принц", "videos": 3, "median": 300, "top": 900}, found
    assert demand("Никто", [])["median"] == 0

    # Бит недели постом в канал: только в понедельник с WEEK_HOUR_MSK и не ночью, один на неделю, новый
    # первым; запас новых кончился — строка владельцу, дальше повтор того, что выходил давнее всех;
    # файл, положенный руками, держит бит вне канала; сорванный выход отметку возвращает как была.
    from . import publish

    aired: list[dict] = []
    told: list[str] = []
    broken: set[str] = set()
    clock = [datetime(2026, 10, 5, 6, 30, tzinfo=timezone.utc)]  # понедельник, 09:30 по Москве

    def out(post: dict, path: Path, chat: str) -> None:
        if post["beat"] in broken:
            raise telegram.TelegramError("нет связи")
        aired.append(post)
        publish.record(post, path, chat)
        state.write_json(path, {**post, "message": {"message_id": 100 + len(aired)}})

    def monday(day: int, hour: int = 8, month: int = 10) -> str:  # 08:00 UTC — 11:00 по Москве
        clock[0] = datetime(2026, month, day, hour, 0, tzinfo=timezone.utc)
        return air()

    assert week(datetime(2026, 10, 11, 20, 59, tzinfo=timezone.utc)) == "2026-10-05", "воскресенье 23:59 по Москве"
    assert week(datetime(2026, 10, 11, 21, 0, tzinfo=timezone.utc)) == "2026-10-12", "понедельник 00:00 по Москве"
    with mock.patch.object(config, "BEATS_FILE", tmp / "air.json"), mock.patch.object(config, "ARCHIVE", tmp / "archive"), \
            mock.patch.object(config, "POSTED_FILE", tmp / "posted.json"), \
            mock.patch.object(config, "BEAT_PHOTOS", tmp / "none.json"), \
            mock.patch.object(config, "secret", lambda name, required=True: "@канал"), \
            mock.patch.object(telegram, "send_message", lambda chat, text, **_: told.append(text)), \
            mock.patch.object(publish, "to_channel", out), mock.patch.object(state, "now", lambda: clock[0]):
        save({"1": {"artists": ["Kizaru"], "title": "Фары", "bpm": 140, "key": "Fm"},
              "2": {"artists": ["Kizaru", "Toxi$"], "title": "Наждак", "bpm": None, "key": ""}})
        assert air() == "" and not aired, "до десяти утра бит не выходит"
        assert monday(6) == "" and monday(11, 16) == "" and not aired, "вторник и воскресенье — не день бита"
        assert monday(5, 7) == "2" and aired[0]["rubric"] == "beat" and aired[0]["comment"] == POST_ASK, aired
        text = aired[0]["text"]
        assert text.startswith("🎚 <b>БИТ НЕДЕЛИ · «Наждак»</b>\nKizaru x Toxi$ type beat\n") and link("2") in text, text
        assert all(part in text for part in (config.BEAT_CREDIT, MAKE, "🎙 Этот трек — в канал ПЛЁНКИ", "до конца субботы",
                                             "Наберётся три трека", "сведёт руками бесплатно")), text
        assert telegram.visible_len(text) <= telegram.MAX_CAPTION, "пост бита недели — подпись к картинке"
        assert aired[0]["week"] == "2026-10-05" and weekly() == "2" and not told, "неделя — дата понедельника"
        assert monday(5, 12) == "" and len(aired) == 1, "бит недели один на неделю"
        clock[0] = datetime(2026, 10, 11, 16, 0, tzinfo=timezone.utc)
        assert weekly() == "2", "в воскресенье бит недели тот же"
        assert monday(12, 20) == "" and weekly() == "", "понедельник, 23:00 по Москве: ночью бит не выходит"
        assert monday(12) == "1" and ", 140 BPM, Fm" in aired[1]["text"] and weekly() == "1"
        assert told == [LAST_NEW.format(title="Фары")], "ушёл последний новый бит — владельцу строка"
        # Новых нет — повтор того, что выходил давнее всех; строка о запасе второй раз не уходит.
        assert monday(19) == "2" and aired[2]["week"] == "2026-10-19" and len(told) == 1, aired[2]
        # Файл бита, положенный руками (без сообщения канала): ни новым, ни повтором бит не выходит.
        save({**load(), "3": {"artists": ["Toxi$"], "title": "Ручной", "bpm": None, "key": ""}})
        state.write_json(config.ARCHIVE / "beat-3.json", {})
        assert monday(26) == "1" and len(told) == 1, "ручная отметка держит бит вне канала"
        # Сорванный выход: у повтора отметка возвращается к прежнему посту, у нового — снимается.
        broken.update({"2", "4"})
        kept = state.read_json(config.ARCHIVE / "beat-2.json", {})
        for name, left in (("2", kept), ("4", {})):
            try:
                monday(2, month=11)
            except telegram.TelegramError:
                assert state.read_json(config.ARCHIVE / f"beat-{name}.json", {}) == left, "сорванный выход вернул отметку"
            else:
                raise AssertionError("сбой выхода должен дойти до дежурства")
            save({**load(), "4": {"artists": ["Kizaru"], "title": "Сбой", "bpm": None, "key": ""}})
        assert shot("1", tmp).stat().st_size and Image.open(tmp / PREVIEW_NAME).size == PREVIEW_SIZE
        # Ролик бита (поле clip — file_id) встаёт в пост вместо значка; нет его или не ушёл — значок.
        went: list[str] = []

        def film(chat, video, caption, **_) -> dict:
            if video == "битый":
                raise telegram.TelegramError("нет файла")
            went.append(f"ролик {video}")
            return {"message_id": 1, "chat": {"id": -100}}

        def badge(*_, **__) -> dict:
            went.append("значок")
            return {"message_id": 2, "chat": {"id": -100}}

        with mock.patch.object(telegram, "send_video_url", film), mock.patch.object(telegram, "send_photo_file", badge):
            for clip in ("свой", "", "битый"):
                save({**load(), "1": {**load()["1"], "clip": clip}})
                assert publish.send({"rubric": "beat", "beat": "1", "text": "бит"}, "@канал")["kind"] == "caption"
        assert went == ["ролик свой", "значок", "значок"], went
    print("bity: подпись и маршрут бита, каталог и тексты для YouTube, описание без ссылки, на подъёме, "
          "ссылка beat_ по file_id, «🎚 БИТЫ»: один бит — сразу файл, несколько — список, метка меню, "
          "кнопка — заявка с битом и его номером, «🔎 Нет бита» и без заявки, лимит, свои биты первыми, счётчик, счёт по номеру бита, "
          "значок — плёночный портрет со словом названия, без фото — спины, живой ролик в 50 МБ и превью, спрос по медиане без «ё», "
          "бит недели постом в канал: только в понедельник с 10:00 и не ночью, один на неделю, новый первым, запас кончился — "
          "строка владельцу и повтор давнего, ручная отметка держит бит вне канала, сорванный выход возвращает отметку, "
          "ролик бита (поле clip) в посте вместо значка, без ролика и при сбое — значок — ок")


def main() -> int:
    parser = argparse.ArgumentParser(description="Биты владельца: каталог, ссылка в боте, ролик для YouTube")
    parser.add_argument("--selftest", action="store_true", help="самопроверка без сети и Telegram")
    parser.add_argument("--video", type=Path, metavar="ФАЙЛ", help="сухой прогон: ролик, превью и тексты для YouTube, без Telegram")
    parser.add_argument("--title", default="", help="подпись бита: «Kizaru x Toxi$ — Полёт, 140 Fm»")
    parser.add_argument("--out", type=Path, default=Path("bity-out"), help="папка для ролика и превью")
    parser.add_argument("--demand", nargs="*", metavar="АРТИСТ", help="под кого делать бит: сколько смотрят type beat'ы "
                        "за месяц под названных и под русскоязычных артистов канала на подъёме")
    parser.add_argument("--render", help=argparse.SUPPRESS)  # так ролик запускает дежурство (tick)
    args = parser.parse_args()
    if args.selftest:
        _selftest()
        return 0
    if args.render:
        return render(args.render)
    if args.demand is not None:
        local = [artist for artist in collect.load_artists() if artist.get("tier") in DEMAND_TIERS]
        if load():
            print(f"Свои биты, счёт бота:\n{score()}\n\nЧужие type beat'ы на YouTube:")
        print(demand_table([*args.demand, *rising(state.read_jsonl(config.INBOX_FILE), local, state.now())]))
        return 0
    if args.video:
        beat = parse(args.title)
        if not beat:
            parser.error("--title: артисты — название, например «Kizaru x Toxi$ — Полёт, 140 Fm»")
        beat["name"] = args.video.name
        hot = rising(state.read_jsonl(config.INBOX_FILE), collect.load_artists(), state.now())
        print(re.sub(r"<[^>]+>", "", html.unescape(texts("N", beat, hot))))
        clip = video(args.video, beat, args.out)
        seconds = clips.probe_seconds(clip)
        print(f"\nРолик: {clip} — {int(seconds) // 60}:{int(seconds) % 60:02d}, {clip.stat().st_size / 2**20:.1f} МБ, "
              f"превью 1280×720: {args.out / PREVIEW_NAME}")
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
