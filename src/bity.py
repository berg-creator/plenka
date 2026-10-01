"""Биты владельца: type beat на его YouTube — бит в боте и сразу СВЕДЕНИЕ с ним.

С 02.10.2026 владелец сам делает type beat'ы и сам выкладывает их на YouTube.
Зрители type beat'ов — артисты, ровно те, кому нужно СВЕДЕНИЕ, а «скачать
в Телеграме» — стандарт ниши. Поэтому в описании ролика — ссылка на бота
?start=beat_<id>: бот отдаёт бит бесплатно, с условием подписать BEAT_CREDIT,
и кнопкой «🎚 Свести с этим битом» открывает заявку СВЕДЕНИЯ, где бит уже лежит.

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
и кодировать звук в цикле опроса значит держать кнопки всех. Обложка — панель
кассетника src/make_cover.py с названием бита, без фото артистов: чужое лицо
в превью — жалоба правообладателя. Служебный вход бота для битов больше 20 МБ
открывает и сведение, а ключ, открытый дважды, Telegram гасит, поэтому ролик
и сведение не идут одновременно (tick, skleyka.tick).

    python -m src.bity --selftest
    python -m src.bity --video БИТ.wav --title "Kizaru x Toxi$ — Полёт, 140 Fm" --out ПАПКА   ролик и тексты без Telegram
"""

from __future__ import annotations

import argparse
import html
import re
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import timedelta
from pathlib import Path

from PIL import Image, ImageDraw

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
RISING_DAYS = 14
RISING_TOP = 5
NOT_RAP = re.compile(r"metal|grunge|punk|rock")
# Поле «Теги» на YouTube — до 500 знаков на все.
TAGS_LIMIT = 500
WIDTH, HEIGHT = 1920, 1080

FORMAT = ("🎚 Бит не принял — не понял подпись. Нужно так: артисты, тире, название, "
          "потом, если знаешь, темп и тональность через запятую:\n<code>бит Kizaru x Toxi$ — Полёт, 140 Fm</code>")
ADDED = ("🎚 Бит №{id} в каталоге: «{title}» — {artists}{tempo}.\n"
         "Ссылка для описания: {link}\n\n"
         "<b>Название для YouTube</b>\n<code>{name}</code>\n\n"
         "<b>Описание</b>\n<pre>{about}</pre>\n\n"
         "<b>Теги</b>\n<code>{tags}</code>\n\n"
         "{rising}🎬 Ролик 1920×1080 для YouTube соберу и пришлю следом.")
RISING = f"📈 На подъёме — больше всего новостей и релизов в сборе канала за {RISING_DAYS} дней: {{names}}.\n\n"
ABOUT = ("Скачать бесплатно ({format}) — в Telegram-боте: {link}\n"
         "Там же бот бесплатно сведёт твой голос с этим битом.\n\n"
         "Бесплатно и для коммерческого релиза (free for profit). "
         "Одно условие — подпиши в названии трека: {credit}\n"
         "{tempo}\n{hashtags}")
GIVEN = ("🎚 <b>«{title}»</b> — {artists} type beat{tempo}\n\n"
         "Бесплатно, и для релиза тоже. Одно условие — подпиши в названии трека: <b>{credit}</b>.\n\n"
         f"Записал голос? Жми «{MAKE}» — бит уже будет в заявке, пришлёшь только голос.")
MISSING = ("🎚 Такого бита не нашёл — похоже, ссылка обрезалась. Открой её из описания ролика ещё раз "
           "или найду бесплатный бит как у нужного артиста.")
VIDEO = "🎬 Ролик к биту №{id} «{title}» — {minutes}, {mb:.0f} МБ. Название и описание — в сообщении выше."
VIDEO_BIG = "🎬 Ролик к биту №{id} вышел {mb:.0f} МБ — Telegram бота принимает до 50. Собери его сам: python -m src.bity --video."
VIDEO_FAILED = "🎬 Ролик к биту №{id} «{title}» не собрался — причина в журнале дежурства."


def load() -> dict:
    return state.read_json(config.BEATS_FILE, {})


def save(catalog: dict) -> None:
    state.write_json(config.BEATS_FILE, catalog)


def parse(caption: str) -> dict | None:
    """Подпись бита — {artists, title, bpm, key}; None — не понял. «бит» в начале необязателен:
    так же читается --title сухого прогона."""
    text = " ".join(MARK.sub("", caption, count=1).split())
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
    return {"artists": artists, "title": title, "bpm": bpm, "key": key} if artists and title else None


def link(beat_id: str) -> str:
    return f"https://t.me/{config.BOT_HANDLE.lstrip('@')}?start=beat_{beat_id}"


def _tempo(beat: dict, sep: str = ", ") -> str:
    return "".join(f"{sep}{part}" for part in (beat["bpm"] and f"{beat['bpm']} BPM", beat["key"]) if part)


def youtube_title(beat: dict) -> str:
    return f"[FREE FOR PROFIT] {' x '.join(beat['artists'])} Type Beat — «{beat['title']}»"


def tags(beat: dict) -> str:
    """Поле «Теги»: артист type beat, их пара, бесплатность, темп — по убыванию важности, в TAGS_LIMIT."""
    names = [name.casefold() for name in beat["artists"]]
    found = [*(f"{name} type beat" for name in names),
             *([f"{' x '.join(names)} type beat"] if len(names) > 1 else []),
             f"{names[0]} type beat free for profit", "free for profit type beat", "type beat",
             *(f"бит в стиле {name}" for name in names), *([f"{beat['bpm']} bpm type beat"] if beat["bpm"] else [])]
    while len(", ".join(found)) > TAGS_LIMIT:
        found.pop()
    return ", ".join(found)


def about(beat_id: str, beat: dict) -> str:
    """Описание ролика: скачать и свести — в боте, условия, темп, хэштеги."""
    tempo = " · ".join(filter(None, (beat["bpm"] and f"BPM: {beat['bpm']}", beat["key"] and f"Тональность: {beat['key']}")))
    hashtags = " ".join([*(f"#{re.sub(r'\W', '', name.casefold())}typebeat" for name in beat["artists"][:3]),
                         "#typebeat", "#freeforprofit"])
    return ABOUT.format(format=(Path(beat.get("name", "")).suffix.lstrip(".").upper() or "WAV"), link=link(beat_id),
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
    save(catalog)
    hot = rising(state.read_jsonl(config.INBOX_FILE), collect.load_artists(), state.now())
    telegram.send_message(chat, texts(beat_id, catalog[beat_id], hot))


def _label(what: str) -> str:
    return f"{skleyka.BEAT_COUNT['own']}{what}"


def give(chat_id: str | int, beat_id: str) -> None:
    """Переход ?start=beat_<id>: бит по file_id с условиями и кнопкой сведения. Без подписки —
    за битом и шли; подписку, как всегда, спросит СВЕДЕНИЕ."""
    beat = load().get(beat_id)
    if not beat:
        telegram.send_message(chat_id, MISSING, buttons=[[skleyka.BEAT_BUTTON]])
        return
    caption = GIVEN.format(title=html.escape(beat["title"]), artists=html.escape(" x ".join(beat["artists"])),
                           tempo=html.escape(_tempo(beat, " · ")), credit=html.escape(config.BEAT_CREDIT))
    telegram.send_by_id(chat_id, beat["kind"], beat["file_id"], caption,
                        buttons=[[{"text": MAKE, "callback_data": f"{PREFIX}{beat_id}"}]])
    skleyka._count(_label(": выдан"))


def callback(chat_id: str | int, user_id: str | int, beat_id: str, *, admin: bool = False) -> None:
    """«🎚 Свести с этим битом»: заявка СВЕДЕНИЯ «вокал + бит», бит в ней уже лежит. Номер
    сообщения — владельца: больше 20 МБ сведение качает бит служебным входом по нему."""
    beat = load().get(beat_id)
    if not beat:
        telegram.send_message(chat_id, MISSING, buttons=[[skleyka.BEAT_BUTTON]])
        return
    item = {"m": beat["message"], "f": beat["file_id"], "n": f"{beat['title'][:50]}{Path(beat['name']).suffix}",
            "s": beat["size"], "g": ""}
    skleyka.start(chat_id, user_id, admin=admin, beat=item)


def matching(names: list[str], bpm: float | None = None) -> list[dict]:
    """Биты владельца для «🔎 Нет бита» (skleyka.find_beats): артист среди названных — строкой выдачи,
    но со ссылкой на бота вместо YouTube, новые первыми. Темп далёк от голоса — прочь, неназванный — годится."""
    wanted = {name.casefold() for name in names}
    found = []
    for beat_id, beat in reversed(load().items()):
        if not wanted & {name.casefold() for name in beat["artists"]}:
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
    if waiting and not skleyka.busy(drafts=False):
        print(f"  ролик к биту {waiting[0]}: пошёл")
        _RENDER = subprocess.Popen([sys.executable, "-m", "src.bity", "--render", waiting[0]], cwd=config.ROOT), waiting[0]


def _line(draw: ImageDraw.ImageDraw, text: str, size: int, top: float, fill, weight: int = 700) -> float:
    """Строка по центру, кегль ужимается до ширины кадра с полями; возвращает низ строки."""
    while True:
        face = stories.font(size, weight)
        box = draw.textbbox((0, 0), text, font=face)
        if box[2] - box[0] <= WIDTH * 0.88 or size <= 24:
            break
        size -= 4
    draw.text(((WIDTH - box[2] - box[0]) / 2, top - box[1]), text, font=face, fill=fill)
    return top + box[3] - box[1]


def cover(beat: dict) -> Image.Image:
    """Кадр ролика: кремовая панель и окно с катушками из шапки канала (make_cover), название,
    артисты, темп и условие. Без фото: чужое лицо в превью — жалоба правообладателя."""
    img = make_cover.brushed(WIDTH, HEIGHT, make_cover.CREAM)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, WIDTH, 6], fill=(232, 224, 208))
    draw.rectangle([0, HEIGHT - 8, WIDTH, HEIGHT], fill=(150, 140, 122))
    draw.rounded_rectangle([WIDTH * 0.33, HEIGHT * 0.07, WIDTH * 0.67, HEIGHT * 0.33], radius=18,
                           fill=(52, 47, 42), outline=(150, 140, 122), width=4)
    make_cover.reel(draw, WIDTH * 0.43, HEIGHT * 0.20, HEIGHT * 0.10, 0.35)
    make_cover.reel(draw, WIDTH * 0.57, HEIGHT * 0.20, HEIGHT * 0.10, 0.85)
    bottom = _line(draw, f"«{beat['title'].upper()}»", 190, HEIGHT * 0.40, make_cover.INK)
    bottom = _line(draw, f"{' x '.join(beat['artists'])} type beat".upper(), 84, bottom + 40, (96, 88, 76), 600)
    draw.rectangle([WIDTH / 2 - 160, bottom + 36, WIDTH / 2 + 160, bottom + 46], fill=make_cover.ACCENT)
    bottom += 46
    if tempo := _tempo(beat, " · ").strip(" ·"):
        bottom = _line(draw, tempo, 60, bottom + 36, (96, 88, 76), 500)
    _line(draw, f"FREE FOR PROFIT · {config.BEAT_CREDIT}", 56, HEIGHT * 0.86, make_cover.ACCENT, 600)
    return img


def video(audio: Path, beat: dict, folder: Path) -> Path:
    """Ролик: кадр и бит. Кадр — бесконечный источник (-loop 1): длину держат -shortest и явная -t
    перед выходом; без них 30.09.2026 такой источник забил диск на 560 ГБ."""
    seconds = clips.probe_seconds(audio)
    if not seconds:
        raise clips.ClipError("длина бита не читается")
    folder.mkdir(parents=True, exist_ok=True)
    frame, dest = folder / "cover.png", folder / "video.mp4"
    cover(beat).save(frame)
    clips.run([clips.ffmpeg(), "-y", "-hide_banner", "-loop", "1", "-framerate", "1", "-i", str(frame), "-i", str(audio),
               "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage",
               "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "320k", "-shortest", "-t", f"{seconds:.3f}",
               "-movflags", "+faststart", str(dest)])
    return dest


def render(beat_id: str) -> int:
    """Процесс ролика (--render): бит у Telegram — до 20 МБ через Bot API, больше — служебным
    входом по номеру сообщения владельца; ролик — владельцу."""
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
            return 0
        seconds = round(clips.probe_seconds(clip))
        telegram.send_video_file(admin, clip, VIDEO.format(id=beat_id, title=html.escape(beat["title"]), mb=mb,
                                                           minutes=f"{seconds // 60}:{seconds % 60:02d}"),
                                 seconds=seconds, width=WIDTH, height=HEIGHT)
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

    with mock.patch.object(config, "BEATS_FILE", tmp / "beats.json"), \
            mock.patch.object(config, "SKLEYKA_FILE", tmp / "skleyka.json"), \
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
        assert "?start=beat_1" in reply and "[FREE FOR PROFIT] Kizaru x Toxi$ Type Beat — «Полёт»" in reply
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
        assert draft["files"] == [{"m": 5, "f": "F5", "n": "Полёт.wav", "s": 40 * 2**20, "g": "", "r": "бит"}]
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

        # «🔎 Нет бита»: биты владельца с этим артистом — первыми, со ссылкой на бота; чужой темп — прочь.
        assert [v["link"] for v in matching(["kizaru"])] == [link("1")] and not matching(["Mayot"])
        assert not matching(["Kizaru"], 100) and matching(["Kizaru"], 71)
        with mock.patch.object(skleyka.youtube_comments, "search", lambda query, count: []):
            found = skleyka.find_beats("Kizaru")
        assert [v["link"] for v in found] == [link("1")], "YouTube молчит — свои биты всё равно есть"
        assert f'href="{link("1")}"' in skleyka.beats_text("Kizaru", found)

        # Ролик: синтетический бит с d= — длина и размер, кадр 1920×1080; tick отмечает сделанное.
        audio = tmp / "beat.wav"
        clips.run([clips.ffmpeg(), "-y", "-f", "lavfi", "-i", "sine=f=55:d=7", str(audio)])
        clip = video(audio, beat, tmp / "out")
        assert abs(clips.probe_seconds(clip) - 7) < 0.2 and clip.stat().st_size < telegram.MAX_UPLOAD
        assert Image.open(tmp / "out" / "cover.png").size == (WIDTH, HEIGHT)
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
    print("bity: подпись и маршрут бита, каталог и тексты для YouTube, на подъёме, ссылка beat_ по file_id, "
          "кнопка — заявка с битом, «🔎 Нет бита» и без заявки, лимит, свои биты первыми, счётчик, ролик — ок")


def main() -> int:
    parser = argparse.ArgumentParser(description="Биты владельца: каталог, ссылка в боте, ролик для YouTube")
    parser.add_argument("--selftest", action="store_true", help="самопроверка без сети и Telegram")
    parser.add_argument("--video", type=Path, metavar="ФАЙЛ", help="сухой прогон: ролик и тексты для YouTube, без Telegram")
    parser.add_argument("--title", default="", help="подпись бита: «Kizaru x Toxi$ — Полёт, 140 Fm»")
    parser.add_argument("--out", type=Path, default=Path("bity-out"), help="папка для ролика")
    parser.add_argument("--render", help=argparse.SUPPRESS)  # так ролик запускает дежурство (tick)
    args = parser.parse_args()
    if args.selftest:
        _selftest()
        return 0
    if args.render:
        return render(args.render)
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
              f"кадр: {args.out / 'cover.png'}")
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
