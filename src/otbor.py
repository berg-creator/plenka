"""ОТБОР — артист присылает свой трек в бота, канал его публикует.

Зачем. У канала почти ноль подписчиков, и разбор вкуса их не приносит: ради
любопытства из ролика в бота не переходят. Тому, кто пишет сам, нужен пост
со своим именем — его он перешлёт своим. Присылать трек могут только подписчики,
поэтому каждый артист — подписчик, а его круг, пришедший на пост, — ещё несколько
(раздел «Третий актив» в GROWTH.md, решение владельца 16.09.2026).

Приём — разговор в личке в три шага: трек, пара слов от артиста, согласие
на ролик. Трек присылают как удобно — «Артист — Трек», ссылкой или файлом.
Из ссылки имя и название бот достаёт сам: у Apple, Deezer и Яндекса — по id
из адреса, у Spotify — из встраиваемого плеера, у YouTube и SoundCloud —
по oEmbed. Дальше трек ищется в iTunes и Deezer: оттуда отрывок, обложка
и точная ссылка. Заголовок любой страницы как запасной путь не взят: «Главная -
Мой блог» разобрался бы в артиста и трек и сошёл бы за выложенный релиз.
VK и Звук без входа ничего не отдают — человека просят написать «Артист — Трек».

Владелец ничего не проверяет и не утверждает, поэтому все проверки здесь,
и отказ — одной фразой: подписка, один трек в неделю, артист ещё не известен
(нет в data/artists.json и мало фанатов на Deezer), трек выложен хоть на одной
площадке, длительность 1–8 минут, без повторов. Выложенность — не прихоть:
канал трек не слушает, а площадка его уже приняла.

Голосования пока нет — голосовать некому. Выходит каждый, кто прошёл проверки,
по порядку прихода, не больше одного в день и днём. Выпускает дежурство
(src/moderate.py), как и релизы: крон занимал бы группу state-write.

Пост — шаблоном, без модели. О звуке канал не пишет ни слова: трек он не слушал,
а шаблону выдумывать нечего. Сам трек идёт первым комментарием (comments.seed) —
тот плеер, что бот показал артисту при приёме: файл артиста или отрывок магазина,
перезалитый с именем и обложкой.

Заявки и черновики — в приватном хранилище (config.OTBOR_FILE): там chat_id
человека, а репозиторий открытый. Готовый пост ждёт выхода там же
(config.OTBOR_POSTS), так что имя и трек попадают в открытый репозиторий
только вышедшим постом, в архиве.

    python -m src.otbor --selftest                 три способа прислать, отказы, пост — без сети
    python -m src.otbor --dry-run                  какой пост отбора выйдет следующим
    python -m src.otbor --find "ссылка или Артист — Трек"   что бот найдёт и пустит ли в отбор
"""

from __future__ import annotations

import argparse
import html
import logging
import re
import tempfile
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

from . import config, publish, state, telegram
from .sources import deezer, http, itunes
from .sources.youtube_comments import MIN_LIKES, suitable

log = logging.getLogger("otbor")

# Короче минуты — набросок или интро, длиннее восьми — сет или подкаст.
MIN_SECONDS, MAX_SECONDS = 60, 8 * 60
WEEK = timedelta(days=7)
# Днём по Москве: утро занято обычными слотами, после девяти вечера лента уже забита.
DAY_HOURS_MSK = range(12, 21)

URL = re.compile(r"https?://\S+")
# Тире с пробелами: «ню-метал» и «Jay-Z» — не «Артист — Трек».
DASH = re.compile(r"\s+[—–-]\s+")
CANCEL = ("отмена", "стоп", "cancel")

HINT = (
    "🎙 <b>ОТБОР</b> — пришли свой трек, и он выйдет в канале ПЛЁНКИ: "
    "с твоим именем, ссылкой и самим треком под постом.\n\n"
    "Как удобно:\n"
    "· ссылкой — Apple Music, Spotify, Яндекс, Deezer, YouTube, SoundCloud\n"
    "· текстом — <i>Артист — Трек</i>\n"
    "· файлом — и к нему ссылку, где трек уже выложен\n\n"
    "Условия: трек твой и уже вышел хоть на одной площадке, один трек в неделю, "
    "в канал — один в день, по очереди. Имя и трек выйдут в канале публично.\n\n"
    "Передумаешь — напиши «отмена»."
)
FORMAT = "Не понял, какой трек. Пришли ссылку или напиши <i>Артист — Трек</i>."
NO_LINK = ("Эту ссылку не разобрал — VK и Звук без входа ничего не отдают. "
           "Напиши просто <i>Артист — Трек</i>.")
ASK_LINK = ("Файл принял. Теперь ссылку, где трек уже выложен, или <i>Артист — Трек</i>: "
            "канал выпускает только то, что вышло на площадке.")
NOT_FOUND = ("Не нашёл «{name}» ни в Apple Music, ни в Deezer. Пришли ссылку, где трек "
             "выложен: Spotify, Яндекс, YouTube или SoundCloud.")
NEED_FILE = ("Нашёл «{name}», но площадка не отдаёт даже отрывка — под постом было бы "
             "нечего слушать. Пришли сам трек файлом: mp3 или m4a до 20 МБ.")
TOO_BIG = "Файл больше 20 МБ — Telegram не отдаёт такие ботам. Пришли mp3 полегче."
BAD_FILE = "Файл не прочитался ({reason}). Пришли другой — mp3 или m4a."

NOT_SUBSCRIBED = ("Отбор — для подписчиков ПЛЁНКИ. Подпишись: t.me/{handle} — "
                  "и пришли /otbor ещё раз.")
WEEKLY = "Один трек в неделю от человека: следующий можно прислать {date}."
KNOWN_BASE = "{artist} канал уже знает — отбор для тех, о ком ещё не слышали."
KNOWN_FANS = ("У {artist} уже {fans} фанатов на Deezer — отбор для тех, "
              "о ком ещё не слышали.")
REPEAT = "Этот трек уже был в отборе."
LENGTH = "В треке {length}, а в отбор берём от 1 до 8 минут."

WORDS = (
    "Беру: <b>{artist} — {title}</b>. Так он прозвучит под постом.\n\n"
    "Напиши одну-две фразы о треке — встанут в пост цитатой со слов артиста. "
    "Тем же сообщением можно дать ссылку на свою страницу ВКонтакте.\n\n"
    "Нечего сказать — жми кнопку."
)
BAD_WORDS = ("Так в пост не поставить: нужно 25–160 знаков, без мата, ссылок, @ников "
             "и капса. Перепиши или жми «Без слов».")
CONSENT = ("Последнее: можно взять трек в ролик канала на YouTube и в TikTok? "
           "На выход в канал ответ не влияет.")
ACCEPTED = ("Принято ✅ Ты {place}-й в очереди. В канал выходит один трек в день, днём. "
            "Выйдет — пришлю ссылку.")
CANCELLED = "Отменил. Захочешь вернуться — /otbor."
CLOSED = "Эта заявка уже закрыта. Новая — /otbor."
PUBLISHED = "Вышло: {link}\n\nПерешли своим — пусть слушают и пишут в комментариях."


def _cb(choice: str) -> str:
    return f"s:otbor:{choice}"  # префикс сервиса: кнопки разбирает service.handle_callback


QUIET_BUTTONS = [[{"text": "Без слов", "callback_data": _cb("quiet")}]]
CONSENT_BUTTONS = [[{"text": "Можно", "callback_data": _cb("yes")},
                    {"text": "Нет", "callback_data": _cb("no")}]]


# ─────────────────────────── поиск трека ───────────────────────────


def _credits(artist: str) -> list[str]:
    """«A & B feat. C» → [A, B, C]: известность и повтор сверяются по каждому имени."""
    parts = re.split(r"\s*(?:,|&|\bfeat\.?|\bft\.?|\bx\b)\s*", artist, flags=re.IGNORECASE)
    return [p for p in parts if p] or [artist]


def _bare(title: str) -> str:
    """Название без хвостов: «Ночь (feat. X) - Single» и «Ночь» — один трек."""
    return itunes._norm(re.split(r"\s*[(\[]", title, maxsplit=1)[0])


def _match(credit: str, song: str, artist: str, title: str) -> bool:
    """Точное совпадение и артиста, и трека. Похожий результат хуже никакого:
    поиск охотно отдаёт чужую песню с тем же названием."""
    names = {itunes._norm(name) for name in _credits(credit)}
    return itunes._norm(artist) in names | {itunes._norm(credit)} and _bare(song) == _bare(title)


def key(artist: str, title: str) -> str:
    return f"{itunes._norm(_credits(artist)[0])}|{_bare(title)}"


def _apple(item: dict) -> dict:
    return {
        "artist": item.get("artistName", ""),
        "title": item.get("trackName", ""),
        "url": item.get("trackViewUrl", ""),
        "cover": item.get("artworkUrl100", "").replace("100x100", "600x600"),
        "seconds": round((item.get("trackTimeMillis") or 0) / 1000),
        "preview": item.get("previewUrl", ""),
        "published": True,
    }


def _deezer(item: dict) -> dict:
    return {
        "artist": item.get("artist", {}).get("name", ""),
        "title": item.get("title", ""),
        "url": item.get("link", ""),
        "cover": item.get("album", {}).get("cover_xl", ""),
        "seconds": item.get("duration") or 0,
        "preview": item.get("preview", ""),
        "deezer_artist": item.get("artist", {}).get("id"),
        "published": True,
    }


def lookup(artist: str, title: str) -> dict:
    """Трек в iTunes, затем в Deezer. Пусто — ни там, ни там нет."""
    data = http.get_json(
        itunes.SEARCH_URL, params={"term": f"{artist} {title}", "entity": "song", "limit": 10},
        min_interval=itunes.MIN_INTERVAL,
    )
    for item in (data or {}).get("results") or []:
        if _match(item.get("artistName", ""), item.get("trackName", ""), artist, title):
            return _apple(item)
    # Простой запрос, а не artist:"…" track:"…": расширенный поиск Deezer на малых
    # артистах отдаёт пустоту (16.09.2026 — «ФОНК ПОТРОШИТЕЛЬ», «MOKXJIN»), а сверка ниже и так точная.
    data = http.get_json(
        f"{deezer.BASE}/search/track", params={"q": f"{artist} {title}", "limit": 10},
        min_interval=deezer.MIN_INTERVAL,
    )
    for item in (data or {}).get("data") or []:
        if _match(item.get("artist", {}).get("name", ""), item.get("title", ""), artist, title):
            return _deezer(item)
    return {}


def _split_title(text: str, artist: str = "") -> dict:
    """«Артист - Трек (Official Video)» → артист и трек; без тире — артист из канала."""
    text = re.sub(r"\s*[(\[][^)\]]*[)\]]", "", text).strip()
    parts = DASH.split(text, maxsplit=1)
    if len(parts) == 2:
        return {"artist": parts[0].strip(), "title": parts[1].strip(" \"«»")}
    return {"artist": artist, "title": text.strip(" \"«»")} if artist and text else {}


def _from_link(url: str) -> dict:
    parsed = urlparse(url)
    host = parsed.netloc.casefold().removeprefix("www.")

    if host.endswith("apple.com"):
        song = (parse_qs(parsed.query).get("i") or [""])[0]
        song = song or next(iter(re.findall(r"/song/[^/]+/(\d+)", url)), "")
        if song:
            data = http.get_json(itunes.LOOKUP_URL, params={"id": song}, min_interval=itunes.MIN_INTERVAL)
            items = [i for i in (data or {}).get("results", []) if i.get("kind") == "song"]
        else:
            album = itunes.album_id_from_url(url)
            data = http.get_json(itunes.LOOKUP_URL, params={"id": album, "entity": "song"},
                                 min_interval=itunes.MIN_INTERVAL) if album else None
            items = [i for i in (data or {}).get("results", []) if i.get("kind") == "song"]
            items = items if len(items) == 1 else []  # у альбома не угадать, какой трек прислан
        return _apple(items[0]) if items else {}

    if "deezer" in host:
        if "deezer.com" not in host:  # link.deezer.com, deezer.page.link — короткая ссылка
            url = requests.get(url, timeout=20, headers={"User-Agent": http.BROWSER_UA}).url
        track = next(iter(re.findall(r"/track/(\d+)", url)), "")
        if not track and (album := deezer.album_id_from_url(url)):
            data = http.get_json(f"{deezer.BASE}/album/{album}", min_interval=deezer.MIN_INTERVAL) or {}
            tracks = data.get("tracks", {}).get("data", [])
            track = str(tracks[0]["id"]) if len(tracks) == 1 else ""
        data = http.get_json(f"{deezer.BASE}/track/{track}", min_interval=deezer.MIN_INTERVAL) if track else None
        return _deezer(data) if data and not data.get("error") else {}

    if host.endswith("spotify.com"):
        # oEmbed Spotify отдаёт одно название, без артиста; встраиваемый плеер —
        # всё сразу, включая отрывок. Ключ API для этого не нужен.
        track = next(iter(re.findall(r"/track/(\w+)", url)), "")
        page = http.get(f"https://open.spotify.com/embed/track/{track}") if track else None
        found = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page.text if page else "", re.S)
        if not found:
            return {}
        import json

        entity = json.loads(found.group(1))["props"]["pageProps"]["state"]["data"]["entity"]
        images = sorted(entity.get("visualIdentity", {}).get("image", []), key=lambda i: i.get("maxWidth", 0))
        return {
            "artist": ", ".join(a["name"] for a in entity.get("artists", [])),
            "title": entity.get("name", ""),
            "url": f"https://open.spotify.com/track/{track}",
            "cover": images[-1]["url"] if images else "",
            "seconds": round((entity.get("duration") or 0) / 1000),
            "preview": (entity.get("audioPreview") or {}).get("url", ""),
            "published": True,
        }

    if "yandex" in host:
        track = next(iter(re.findall(r"/track/(\d+)", url)), "")
        data = http.get_json(f"https://api.music.yandex.net/tracks/{track}") if track else None
        items = (data or {}).get("result") or []
        if not items:
            return {}
        item = items[0]
        return {
            "artist": ", ".join(a.get("name", "") for a in item.get("artists", [])),
            "title": item.get("title", ""),
            "url": url,
            "cover": f"https://{item['coverUri'].replace('%%', '600x600')}" if item.get("coverUri") else "",
            "seconds": round((item.get("durationMs") or 0) / 1000),
            "published": True,
        }

    if host in ("youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"):
        data = http.get_json("https://www.youtube.com/oembed", params={"url": url, "format": "json"}) or {}
        found = _split_title(data.get("title", ""), data.get("author_name", "").removesuffix(" - Topic"))
        return {**found, "url": url, "cover": data.get("thumbnail_url", ""), "published": True} if found else {}

    if host.endswith("soundcloud.com"):
        data = http.get_json("https://soundcloud.com/oembed", params={"url": url, "format": "json"}) or {}
        author = data.get("author_name", "")
        title = data.get("title", "").removesuffix(f" by {author}")
        if not (author and title):
            return {}
        return {"artist": author, "title": title, "url": url, "cover": data.get("thumbnail_url", ""),
                "published": True}

    return {}


def from_link(url: str) -> dict:
    """Артист, трек и что ещё отдала площадка по ссылке. Пусто — не разобралась.

    Молчит при любой ошибке: площадка могла поменять страницу, а человеку
    честнее предложить «Артист — Трек», чем уронить приём.
    """
    try:
        found = _from_link(url.rstrip(".,;)»"))
    except Exception as exc:  # noqa: BLE001 — чужая страница не роняет бота
        log.info("Ссылка не разобралась (%s): %s", url[:80], exc)
        return {}
    return found if found.get("artist") and found.get("title") else {}


def by_link(url: str) -> dict:
    """Трек по ссылке, дополненный магазином: отрывок и обложка часто есть только там.
    Ссылка человека главнее найденной — это площадка, которую он сам выбрал."""
    found = from_link(url)
    if not found:
        return {}
    return {**lookup(_credits(found["artist"])[0], found["title"]), **{k: v for k, v in found.items() if v}}


def subject(text: str) -> str:
    """Про кого разбор, если прислали ссылку на трек или «Артист — Трек».

    Разборам человек пишет так же, как отбору, и знать, в каком виде бот чего
    ждёт, ему не надо. Пусто — ссылка не разобралась. Куплет в несколько строк
    не трогаем: тире там — часть текста.
    """
    text = text.strip()
    if "\n" in text:
        return text
    if link := URL.search(text):
        return from_link(link.group(0)).get("artist", "")
    parts = DASH.split(text, maxsplit=1)
    return parts[0] if len(parts) == 2 else text


def fans(artist: str, deezer_id: int | None = None) -> int:
    """Фанаты артиста на Deezer. По id — точно; по имени — самый большой из тёзок:
    известного тёзку с безвестным перепутать безопаснее, чем наоборот."""
    if deezer_id:
        data = http.get_json(f"{deezer.BASE}/artist/{deezer_id}", min_interval=deezer.MIN_INTERVAL) or {}
        return data.get("nb_fan") or 0
    data = http.get_json(f"{deezer.BASE}/search/artist", params={"q": artist, "limit": 10},
                         min_interval=deezer.MIN_INTERVAL) or {}
    return max((a.get("nb_fan") or 0 for a in data.get("data") or []
                if itunes._norm(a.get("name", "")) == itunes._norm(artist)), default=0)


def known(artist: str, deezer_id: int | None = None) -> str:
    """Отказ, если артист уже известен; пусто — берём."""
    base = {
        itunes._norm(name)
        for item in state.read_json(config.ARTISTS_FILE, {"artists": []})["artists"]
        for name in (item.get("name"), item.get("search_name"), *(item.get("aliases") or []))
        if name
    }
    for name in _credits(artist):
        if itunes._norm(name) in base:
            return KNOWN_BASE.format(artist=html.escape(name))
    count = fans(_credits(artist)[0], deezer_id)
    if count >= config.OTBOR_MAX_FANS:
        return KNOWN_FANS.format(artist=html.escape(_credits(artist)[0]), fans=count)
    return ""


# ─────────────────────────── приём заявки ───────────────────────────


def load() -> dict:
    data = state.read_json(config.OTBOR_FILE, {})
    for field, empty in (("drafts", {}), ("queue", []), ("done", [])):
        data.setdefault(field, empty)
    return data


def save(data: dict) -> None:
    state.write_json(config.OTBOR_FILE, data)


def active(chat_id: str | int) -> bool:
    """Идёт ли у человека заявка — тогда его сообщения и файлы идут сюда, а не в разборы."""
    return str(chat_id) in load()["drafts"]


def cancel(chat_id: str | int) -> None:
    data = load()
    if data["drafts"].pop(str(chat_id), None) is not None:
        save(data)


def refusal(data: dict, chat_id: str, user_id: str, *, admin: bool) -> str:
    """Подписка и неделя — проверки человека, а не трека. Пусто — можно."""
    if admin:
        return ""
    channel = config.secret("TELEGRAM_CHANNEL_ID", required=False)
    if channel and not telegram.is_member(channel, user_id):
        # Адрес из config, а не секрет: там может стоять числовой id канала.
        return NOT_SUBSCRIBED.format(handle=config.CHANNEL_HANDLE.lstrip("@"))
    sent = [moment for item in (*data["queue"], *data["done"])
            if item.get("chat") == chat_id and (moment := state._parse(item.get("at", "")))
            and state.now() - moment < WEEK]
    if sent:
        from .compose import MSK

        return WEEKLY.format(date=(min(sent) + WEEK).astimezone(MSK).strftime("%d.%m"))
    return ""


def start(chat_id: str | int, user_id: str | int, *, admin: bool = False) -> None:
    """Открывает заявку: /otbor, кнопка меню и ссылка с меткой из ролика (service.SOURCES)."""
    chat_id, user_id = str(chat_id), str(user_id)
    data = load()
    denied = refusal(data, chat_id, user_id, admin=admin)
    if denied:
        data["drafts"].pop(chat_id, None)
    else:
        data["drafts"][chat_id] = {"stage": "track", "user": user_id}
    save(data)
    telegram.send_message(chat_id, denied or HINT)


def handle(message: dict, *, admin: bool = False) -> None:
    """Сообщение или файл от человека с открытой заявкой; файл открывает её сам."""
    chat_id = str(message.get("chat", {}).get("id", ""))
    user_id = str(message.get("from", {}).get("id", ""))
    text = (message.get("text") or message.get("caption") or "").strip()

    if text.casefold() in CANCEL:
        cancel(chat_id)
        telegram.send_message(chat_id, CANCELLED)
        return

    from .moderate import track_file

    if not active(chat_id):
        # Файл без команды — тоже заявка: знать про /otbor артисту не обязательно.
        start(chat_id, user_id, admin=admin)
        if not (active(chat_id) and track_file(message)):
            return

    data = load()
    draft = data["drafts"][chat_id]
    buttons = None
    if draft["stage"] == "words":
        reply, buttons = take_words(draft, text)
    elif draft["stage"] == "consent":
        reply, buttons = CONSENT, CONSENT_BUTTONS
    else:
        reply = take_track(draft, message, text, data, chat_id)
    if draft["stage"] == "refused":
        data["drafts"].pop(chat_id)
    save(data)
    if reply:
        telegram.send_message(chat_id, reply, buttons=buttons)


def take_track(draft: dict, message: dict, text: str, data: dict, chat_id: str) -> str:
    """Копит в черновике, что известно о треке, и спрашивает недостающее.

    Ответ — текст человеку; пусто, когда ответом стал плеер с вопросом о словах.
    Отказ ставит черновику stage=refused, и handle его закрывает.
    """
    from .moderate import track_file

    file = track_file(message)
    if file:
        if file.get("file_size", 0) > telegram.MAX_DOWNLOAD:
            return TOO_BIG
        draft["file_id"] = file["file_id"]
        # Теги файла — подсказка: нашёлся по ним в магазине — ссылка не нужна.
        tags = message.get("audio") or {}
        if not draft.get("artist") and tags.get("performer") and tags.get("title") and not URL.search(text):
            draft.update(lookup(tags["performer"], tags["title"]))

    if link := URL.search(text):
        found = by_link(link.group(0))
        if not found:
            return NO_LINK
        draft.update(found)
    elif len(parts := DASH.split(text, maxsplit=1)) == 2:
        artist, title = (part.strip() for part in parts)
        found = lookup(artist, title)
        if not found:
            return NOT_FOUND.format(name=html.escape(f"{artist} — {title}"))
        draft.update(found)
    elif not file:
        return FORMAT

    if not draft.get("artist"):
        return ASK_LINK
    name = html.escape(f"{draft['artist']} — {draft['title']}")
    if not draft.get("published"):
        return NOT_FOUND.format(name=name)

    track_key = key(draft["artist"], draft["title"])
    if any(item.get("key") == track_key for item in (*data["queue"], *data["done"])):
        draft["stage"] = "refused"
        return REPEAT
    denied = known(draft["artist"], draft.get("deezer_artist"))
    if denied:
        draft["stage"] = "refused"
        return denied
    if not (draft.get("file_id") or draft.get("preview")):
        return NEED_FILE.format(name=name)

    caption = WORDS.format(artist=html.escape(draft["artist"]), title=html.escape(draft["title"]))
    try:
        with tempfile.TemporaryDirectory() as work:
            audio, seconds, thumb = _audio(draft, Path(work))
            if seconds and not MIN_SECONDS <= seconds <= MAX_SECONDS:
                draft["stage"] = "refused"
                return LENGTH.format(length=f"{seconds // 60}:{seconds % 60:02d}")
            # Плеер уходит артисту сейчас, а его file_id — в пост: под постом
            # прозвучит ровно то, что артист уже слышал, с именем и обложкой.
            sent = telegram.send_audio(
                chat_id, audio, caption, title=draft["title"], performer=draft["artist"],
                thumb=thumb, cover_url="" if thumb else draft.get("cover", ""),
                seconds=seconds if draft.get("file_id") else 0, buttons=QUIET_BUTTONS,
            )
    except Exception as exc:  # noqa: BLE001 — битый файл не роняет дежурство
        log.warning("Трек отбора не принят: %s", exc)
        draft.pop("file_id", None)
        return BAD_FILE.format(reason=html.escape(str(exc))[:120])
    if "audio" not in sent:
        draft.pop("file_id", None)
        return BAD_FILE.format(reason="Telegram не узнал в нём музыку")
    draft.update(track_file_id=sent["audio"]["file_id"], seconds=seconds, stage="words")
    return ""


def _audio(draft: dict, work: Path) -> tuple[bytes | str, int, bytes | None]:
    """Звук для плеера: (файл или ссылка на отрывок, длительность трека, обложка).

    Файл перезаливается тем же путём, что трек от владельца (moderate.normalize_track):
    mp3 документом и wav Telegram иначе кладёт файлом, а не плеером. У отрывка
    длительность — всего трека, из магазина: отрывку всегда 30 секунд.
    """
    if draft.get("file_id"):
        from .moderate import normalize_track

        post = {"artist": draft["artist"], "track": draft["title"], "cover": draft.get("cover", "")}
        return normalize_track({"file_id": draft["file_id"]}, post, work)
    return draft["preview"], draft.get("seconds") or 0, None


def take_words(draft: dict, text: str) -> tuple[str, list[list[dict]]]:
    """Слова артиста о треке — через тот же фильтр, что отзывы YouTube под постом."""
    vk = re.search(r"https?://(?:m\.)?vk\.(?:com|ru)/[\w.]+", text)
    words = " ".join(URL.sub("", text).split())
    if words and not suitable(words, MIN_LIKES) or not (words or vk):
        return BAD_WORDS, QUIET_BUTTONS
    if vk:
        draft["vk"] = vk.group(0)
    if words:
        draft["quote"] = words
    draft["stage"] = "consent"
    return CONSENT, CONSENT_BUTTONS


def callback(chat_id: str | int, user_id: str | int, choice: str, *, admin: bool = False) -> None:
    """Кнопки отбора: пустой выбор — открыть заявку, quiet — без слов, yes/no — ролик."""
    chat_id = str(chat_id)
    if not choice:
        start(chat_id, user_id, admin=admin)
        return
    data = load()
    draft = data["drafts"].get(chat_id)
    if draft and choice == "quiet" and draft["stage"] == "words":
        draft["stage"] = "consent"
        save(data)
        telegram.send_message(chat_id, CONSENT, buttons=CONSENT_BUTTONS)
    elif draft and choice in ("yes", "no") and draft["stage"] == "consent":
        submit(data, chat_id, str(user_id), reel=choice == "yes", admin=admin)
    else:
        telegram.send_message(chat_id, CLOSED)


FIELDS = ("artist", "title", "url", "cover", "track_file_id", "seconds", "quote", "vk")


def submit(data: dict, chat_id: str, user_id: str, *, reel: bool, admin: bool) -> None:
    draft = data["drafts"].pop(chat_id)
    denied = refusal(data, chat_id, user_id, admin=admin)
    if not denied:
        data["queue"].append({
            **{field: draft[field] for field in FIELDS if draft.get(field)},
            "chat": chat_id, "at": state.iso(), "reel": reel, "key": key(draft["artist"], draft["title"]),
        })
    save(data)
    telegram.send_message(chat_id, denied or ACCEPTED.format(place=len(data["queue"])))


# ─────────────────────────── выход в канал ───────────────────────────


def build_post(application: dict) -> dict:
    """Пост шаблоном: имя, трек, кто прислал, слова артиста, ссылки. О звуке — ничего."""
    esc = html.escape
    artist, title = application["artist"], application["title"]
    parts = [
        f"<b>{esc(artist.upper())} — «{esc(title.upper())}»</b>",
        "Трек прислал в отбор сам артист. Послушать — первым комментарием.",
    ]
    if application.get("quote"):
        parts.append(f"Со слов артиста:\n<blockquote>{esc(application['quote'])}</blockquote>")
    links = []
    if application.get("vk"):
        links.append(f'▸ <a href="{esc(application["vk"])}">Артист во ВКонтакте</a>')
    if application.get("url"):
        # Строку разворачивает в площадки publish.listen — как у поста о релизе.
        links.append(f'▸ <a href="{esc(application["url"])}">Слушать</a>')
    if links:
        parts.append("\n".join(links))
    parts.append(f"Пришли свой — {config.BOT_HANDLE}")
    return {
        "rubric": "otbor",
        "text": "\n\n".join(parts),
        "artist": artist,
        "track": title,
        "cover": application.get("cover", ""),
        "full_track_file_id": application.get("track_file_id", ""),
        # Согласие на ролик — в открытый архив: по нему бриф роликов собирает
        # «ТРИ ТРЕКА ИЗ БОТА», а к приватной заявке облачный сценарист доступа не имеет.
        "reel": bool(application.get("reel")),
        "created_at": state.iso(),
    }


def _published_today() -> bool:
    from .compose import MSK

    today = state.now().astimezone(MSK).date()
    return any(
        item.get("rubric") == "otbor" and (moment := state._parse(item.get("published_at", "")))
        and moment.astimezone(MSK).date() == today
        for item in state.read_json(config.POSTED_FILE, {"items": []}).get("items", [])
    )


def next_path(data: dict) -> tuple[Path | None, dict]:
    """Пост отбора, который выходит следующим: готовый или собранный из первой заявки."""
    pending = sorted(config.OTBOR_POSTS.glob("*.json"))
    if pending:
        return pending[0], state.read_json(pending[0], {})
    if not data["queue"]:
        return None, {}
    application = data["queue"][0]
    name = f"{state.now():%Y%m%d-%H%M}-otbor-{state.fingerprint(application['key'])}.json"
    return config.OTBOR_POSTS / name, build_post(application)


def shift(target: str) -> None:
    """Выход отбора из дежурства: артисту — ссылка на вышедший пост, в канал — следующий.

    Заявка становится постом в момент выхода, а не при приёме: до выхода имя
    не должно лежать даже в готовом файле. Не ушёл (сеть, Telegram) — файл
    остаётся в config.OTBOR_POSTS, и следующий заход пробует снова.
    Владельцу (PUBLISH_TARGET=admin) пост уходит один раз и ждёт его кнопки.
    """
    from .compose import MSK

    data = load()
    notify(data)
    if state.now().astimezone(MSK).hour not in DAY_HOURS_MSK or _published_today():
        return
    path, post = next_path(data)
    if path is None or post.get("approval_sent_at"):
        return
    if not path.exists():
        application = data["queue"].pop(0)
        state.write_json(path, post)
        data["done"].append({field: application[field] for field in ("chat", "at", "key", "reel")}
                            | {"file": path.name})
        save(data)
    publish.deliver(post, path, target)
    print(f"Выход отбора: {path.name} → {target}")


def notify(data: dict) -> None:
    """Артисту — ссылка на его пост: перешлёт своим, ради этого отбор и затеян."""
    changed = False
    for entry in data["done"]:
        if entry.get("notified"):
            continue
        message = state.read_json(config.ARCHIVE / entry["file"], {}).get("message") or {}
        if not message:
            if not (config.OTBOR_POSTS / entry["file"]).exists():
                entry["notified"] = changed = True  # владелец удалил пост кнопкой — сказать нечего
            continue
        link = f"https://t.me/{config.CHANNEL_HANDLE.lstrip('@')}/{message['message_id']}"
        try:
            telegram.send_message(entry["chat"], PUBLISHED.format(link=link), preview=True)
        except telegram.TelegramError as exc:
            log.warning("Артист не узнал о выходе: %s", exc)  # закрыл бота — повторять незачем
        entry["notified"] = changed = True
    if changed:
        save(data)


# ─────────────────────────── проверка ───────────────────────────


def _selftest() -> None:
    """Без сети: три способа прислать, отказы, текст поста, выход и весть артисту."""
    import os
    import sys
    from datetime import datetime, timezone
    from unittest import mock

    from . import moderate

    said: list[tuple[str, str]] = []
    played: list[dict] = []
    delivered: list[str] = []

    def send_audio(chat, audio, caption, **kw):
        played.append({"chat": chat, "audio": audio, **kw})
        said.append((chat, caption))
        return {"audio": {"file_id": f"PLAYER-{chat}"}}

    def last(chat: str) -> str:
        return next(text for who, text in reversed(said) if who == chat)

    def msg(chat: int, text: str = "", **extra) -> dict:
        return {"chat": {"id": chat, "type": "private"}, "from": {"id": chat}, "text": text, **extra}

    store = {("Nobody Home", "Night Drive"): {
        "artist": "Nobody Home", "title": "Night Drive", "url": "https://music.apple.com/us/album/x/1?i=2",
        "cover": "https://is1.mzstatic.com/c.jpg", "seconds": 185, "preview": "https://audio/p.m4a",
        "published": True}}
    links = {"https://soundcloud.com/ghost/tape": {
        "artist": "Ghost Tape", "title": "Подвал", "url": "https://soundcloud.com/ghost/tape",
        "cover": "https://i1.sndcdn.com/a.jpg", "published": True}}
    subscribed = {"1": True, "2": True, "3": True, "4": True, "5": False, "6": True}
    now = datetime(2026, 9, 17, 10, 0, tzinfo=timezone.utc)  # 13:00 МСК

    with tempfile.TemporaryDirectory() as tmp, mock.patch.multiple(
        config, OTBOR_FILE=Path(tmp) / "otbor.json", OTBOR_POSTS=Path(tmp) / "posts",
        ARCHIVE=Path(tmp) / "archive", POSTED_FILE=Path(tmp) / "posted.json",
        ARTISTS_FILE=Path(tmp) / "artists.json",
    ), mock.patch.dict(os.environ, {"TELEGRAM_CHANNEL_ID": "@plenka_fm"}), mock.patch.multiple(
        telegram, send_message=lambda chat, text, **_: said.append((chat, text)) or {"message_id": 1},
        send_audio=send_audio, is_member=lambda channel, user: subscribed[str(user)],
    ), mock.patch.multiple(
        sys.modules[__name__],
        lookup=lambda artist, title: dict(store.get((artist, title), {})),
        from_link=lambda url: dict(links.get(url, {})),
        fans=lambda artist, deezer_id=None: 5000 if artist == "Big Name" else 12,
    ), mock.patch.object(moderate, "normalize_track", lambda track, post, work: (b"mp3", 200, None)), \
            mock.patch.object(state, "now", lambda: now), \
            mock.patch.object(publish, "deliver", lambda post, path, target: delivered.append(post["text"])):
        state.write_json(config.ARTISTS_FILE, {"artists": [{"name": "Kizaru", "aliases": ["Кизару"]}]})

        # 1. Текстом «Артист — Трек»: магазин нашёл, плеер с отрывком ушёл артисту.
        start(1, 1)
        assert last("1") == HINT
        handle(msg(1, "Nobody Home — Night Drive"))
        assert played[-1]["audio"] == "https://audio/p.m4a" and "Беру" in last("1"), said[-3:]
        handle(msg(1, "КАПСОМ ОРУ ПРО СВОЙ ТРЕК ЦЕЛЫХ ТРИДЦАТЬ ЗНАКОВ"))
        assert last("1") == BAD_WORDS
        handle(msg(1, "Записал за одну ночь в гараже у друга https://vk.com/nobodyhome"))
        assert last("1") == CONSENT
        callback(1, 1, "yes")
        assert last("1").startswith("Принято") and "1-й" in last("1")
        queued = load()["queue"][0]
        assert queued["vk"] == "https://vk.com/nobodyhome" and queued["track_file_id"] == "PLAYER-1"
        assert queued["quote"].startswith("Записал") and "https" not in queued["quote"]

        # 2. Ссылкой, которой нет в магазинах: нужен файл — перезаливается и становится плеером.
        start(2, 2)
        handle(msg(2, "https://soundcloud.com/ghost/tape"))
        assert "файлом" in last("2")
        handle(msg(2, audio={"file_id": "RAW", "file_size": 5 * 2**20}))
        assert played[-1]["audio"] == b"mp3" and played[-1]["seconds"] == 200
        callback(2, 2, "quiet")
        callback(2, 2, "no")
        assert len(load()["queue"]) == 2 and "quote" not in load()["queue"][1]

        # 3. Файлом без команды: заявка открывается сама, дальше просят ссылку.
        handle(msg(3, document={"file_id": "DOC", "mime_type": "audio/mpeg"}))
        assert said[-2] == ("3", HINT) and last("3") == ASK_LINK
        handle(msg(3, "https://soundcloud.com/ghost/tape"))
        assert last("3") == REPEAT and not active(3), "повтор трека прошёл"

        # Отказы: известный по базе и по фанатам, не выложенный, длина, подписка, неделя.
        store[("Kizaru", "Money")] = {**store[("Nobody Home", "Night Drive")], "artist": "Kizaru", "title": "Money"}
        store[("Big Name", "Hit")] = {**store[("Nobody Home", "Night Drive")], "artist": "Big Name", "title": "Hit"}
        store[("Short", "Intro")] = {**store[("Nobody Home", "Night Drive")], "artist": "Short", "title": "Intro",
                                     "seconds": 40}
        for text, refusal_start in (("Kizaru — Money", "Kizaru канал уже знает"),
                                    ("Big Name — Hit", "У Big Name уже 5000"),
                                    ("Short — Intro", "В треке 0:40")):
            start(4, 4)
            handle(msg(4, text))
            assert last("4").startswith(refusal_start) and not active(4), (text, last("4"))
        start(4, 4)
        handle(msg(4, "Nobody Else — Lost"))
        assert last("4").startswith("Не нашёл") and active(4), "невыложенный трек прошёл"
        handle(msg(4, "отмена"))
        assert not active(4)
        start(5, 5)
        assert last("5").startswith("Отбор — для подписчиков") and not active(5)
        start(1, 1)
        assert last("1") == WEEKLY.format(date="24.09") and not active(1)

        # Текст поста: шаблон без слов о звуке, цитата артиста, ссылки и зов в бота.
        text = build_post(queued)["text"]
        assert text.startswith("<b>NOBODY HOME — «NIGHT DRIVE»</b>")
        assert "Со слов артиста:\n<blockquote>Записал" in text and text.endswith(f"Пришли свой — {config.BOT_HANDLE}")
        assert '▸ <a href="https://vk.com/nobodyhome">' in text and publish._LISTEN_LINE.search(text)
        # Площадки разворачиваются, а зов в бота остаётся отдельным абзацем.
        assert "</a>\n\nПришли свой" in publish.listen(text, "Nobody Home", "Night Drive")
        assert build_post({"artist": "A&B", "title": "<x>"})["text"].startswith("<b>A&amp;B — «&lt;X&gt;»</b>")

        # Выход: первая заявка днём, вторая — не в тот же день.
        shift("channel")
        assert delivered and "NOBODY HOME" in delivered[0] and len(load()["queue"]) == 1
        path = next(config.OTBOR_POSTS.glob("*.json"))
        state.write_json(config.POSTED_FILE, {"items": [{"rubric": "otbor", "published_at": state.iso()}]})
        state.write_json(config.ARCHIVE / path.name, {"message": {"message_id": 321}})
        path.unlink()
        shift("channel")
        assert len(delivered) == 1, "второй пост отбора в тот же день"
        assert last("1") == PUBLISHED.format(link="https://t.me/plenka_fm/321")

        # Разборы понимают ссылку и «Артист — Трек»: в разбор уходит имя артиста.
        assert subject("Molchat Doma — Судно") == "Molchat Doma"
        assert subject("https://soundcloud.com/ghost/tape") == "Ghost Tape"
        assert subject("https://vk.com/audio-1_2") == "" and subject("Bones, фонк") == "Bones, фонк"

    assert _split_title("Rick Astley - Never Gonna Give You Up (Official Video)") == {
        "artist": "Rick Astley", "title": "Never Gonna Give You Up"}
    assert _match("Nobody Home & Ghost", "Night Drive (feat. Ghost) - Single", "nobody home", "Night Drive")
    assert not _match("Nobody Homeless", "Night Drive", "Nobody Home", "Night Drive")
    print("отбор: три способа прислать, отказы, пост шаблоном, выход раз в день и весть артисту")


def main() -> int:
    parser = argparse.ArgumentParser(description="ОТБОР: треки артистов в канал")
    parser.add_argument("--selftest", action="store_true", help="проверка без сети")
    parser.add_argument("--dry-run", action="store_true", help="какой пост отбора выйдет следующим")
    parser.add_argument("--find", help="ссылка или «Артист — Трек»: что найдётся и пустят ли в отбор")
    args = parser.parse_args()

    if args.selftest:
        _selftest()
        return 0

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    config.load_dotenv()

    if args.find:
        parts = DASH.split(args.find, maxsplit=1)
        if link := URL.search(args.find):
            found = by_link(link.group(0))
        else:
            found = lookup(parts[0].strip(), parts[1].strip()) if len(parts) == 2 else {}
        for field, value in found.items():
            print(f"  {field}: {value}")
        if not found:
            print("Не нашлось.")
            return 1
        print(known(found["artist"], found.get("deezer_artist")) or "Артист неизвестен — в отбор можно.")
        return 0

    data = load()
    path, post = next_path(data)
    print(f"Заявок в очереди: {len(data['queue'])}. Черновиков: {len(data['drafts'])}.")
    if path is None:
        print("Выходить нечему.")
        return 0
    print(f"Следующий: {path.name}{' (ждёт кнопки владельца)' if post.get('approval_sent_at') else ''}\n")
    print(publish.listen(post["text"], post["artist"], post["track"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
