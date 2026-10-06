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

Исключение — трек, сведённый ботом (владелец, 06.10.2026). Кнопка под готовым
треком СВЕДЕНИЯ вела сюда же, в отбор с площадкой, а человек получил трек минуту
назад и ничего не выкладывал: из 33 сведённых треков 13 человек в отбор не дошёл
никто, двое прислали файл и бросили на просьбе дать ссылку, пост отбора за всё
время вышел один. Теперь «🎙 Этот трек — в канал ПЛЁНКИ» берёт сам сведённый файл,
без ссылки и без поиска в магазинах (mixed), а подпись «Артист — Трек» человек
пишет сам. Фильтр площадки заменён тем, что бот об этом треке знает: голос он
мерил при сведении, и запись с явным браком (skleyka.flaws — шум, перегруз, нет
верха, гул) в канал не идёт, как не идёт и в ручное сведение. Чужим именем
не подписаться: известное каналу или Deezer имя — отказ. Обложки у такого трека
нет, а фото по имени было бы лицом тёзки, поэтому кадр поста — карточка с именем
и названием (card.cover, поле mixed); во ВКонтакте пост не дублируется — слушать
там было бы нечего. Обычный отбор не изменился: там трек по-прежнему выложен.

Под треком в комментариях висит анонимный опрос «как вам» (comments.OTBOR_POLL):
послушал и отметился там же. Выходит каждый, кто прошёл проверки,
по порядку прихода, не больше одного в день и днём. Выпускает дежурство
(src/moderate.py), как и релизы: крон занимал бы группу state-write.

БИТ НЕДЕЛИ (владелец, 06.10.2026). Канал терял подписчиков: приходят те, кто сам
делает музыку, а лента — чужие релизы. Теперь канал — сцена для пришедших в бот:
в понедельник выходит бит владельца (bity.air), под него пишут и сводят ботом,
и трек, сведённый с этим битом через «🎚 Свести с этим битом» и присланный сюда
до конца субботы, выходит с меткой недели (week_of, build_post) — раньше обычных
заявок и мимо правила «один в день», но не больше двух в сутки и не чаще раза
в три часа (shift). Опрос под таким треком считается: в воскресенье вечером итог
(final) закрывает опросы и выпускает пост — победитель по «🔥», все треки со счётом.
Конкурса из двух треков нет: итог выходит, когда треков недели вышло не меньше
трёх, иначе неделя кончается молча. Приз — ручное сведение бесплатно — бот только
обещает: победителю сообщение, владельцу строка, а заказ владелец заводит сам
(skleyka --hand и «🎁»). Отвергнуто: считать голоса без закрытия опроса — чтения
опроса у Bot API нет, а пересылка опроса ради счёта сорила бы в чате обсуждений.

Пост — шаблоном, без модели. О звуке канал не пишет ни слова: трек он не слушал,
а шаблону выдумывать нечего. Сам трек идёт первым комментарием (comments.seed) —
тот плеер, что бот показал артисту при приёме: файл артиста или отрывок магазина,
перезалитый с именем и обложкой.

Заявки и черновики — в приватном хранилище (config.OTBOR_FILE): там chat_id
человека, а репозиторий открытый. Готовый пост ждёт выхода там же
(config.OTBOR_POSTS), так что имя и трек попадают в открытый репозиторий
только вышедшим постом, в архиве.

    python -m src.otbor --selftest                 три способа прислать, трек из СВЕДЕНИЯ без площадки, отказы, пост, бит недели и его итог — без сети
    python -m src.otbor --dry-run                  какой пост отбора выйдет следующим
    python -m src.otbor --find "ссылка или Артист — Трек"   что бот найдёт и пустит ли в отбор
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import re
import tempfile
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

from . import config, publish, state, telegram
from .sources import deezer, http, itunes
from .sources.youtube_comments import JUNK, MIN_LIKES, RUDE, suitable

log = logging.getLogger("otbor")

# Короче минуты — набросок или интро, длиннее восьми — сет или подкаст.
MIN_SECONDS, MAX_SECONDS = 60, 8 * 60
WEEK = timedelta(days=7)
# Днём по Москве: утро занято обычными слотами, после девяти вечера лента уже забита.
DAY_HOURS_MSK = range(12, 21)
# Трек на бит недели идёт мимо правила «один пост отбора в сутки»: по одному в день шесть треков
# заняли бы всю неделю, а седьмой вышел бы после итога. Но и не лентой подряд — не больше
# WEEK_PER_DAY в сутки и не чаще раза в WEEK_GAP.
WEEK_PER_DAY, WEEK_GAP = 2, timedelta(hours=3)
# Итог — в воскресенье с FINAL_HOUR_MSK по Москве, когда треков недели вышло не меньше WEEK_MIN:
# из двух победителя не выбирают.
WEEK_MIN, FINAL_HOUR_MSK = 3, 19
WEEK_KICKER = "БИТ НЕДЕЛИ"
# Отметка итога в content/archive по понедельнику недели: файл есть — итог вышел или снят (final).
FINAL_FILE = "week-{week}.json"
FIRE, FINE = 0, 1  # места «🔥» и «👍» в comments.OTBOR_POLL

URL = re.compile(r"https?://\S+")
# Где найти артиста: страница ВКонтакте или свой канал в Telegram — читатель поста
# подписывается там одним касанием. Instagram не берём: в России он запрещён.
# Схема необязательна — «t.me/имя» пишут без неё; «+» после t.me — приглашение в чат.
PAGES = {
    "vk": ("ВКонтакте", re.compile(r"(?:https?://)?(?:m\.)?vk\.(?:com|ru)/[\w.]+")),
    "tg": ("Telegram", re.compile(r"(?:https?://)?t\.me/[A-Za-z]\w{3,}")),
}
# Тире с пробелами: «ню-метал» и «Jay-Z» — не «Артист — Трек».
DASH = re.compile(r"\s+[—–-]\s+")
CANCEL = ("отмена", "стоп", "cancel")

HINT = (
    "🎙 <b>ОТБОР</b>\n\n"
    "Пришли свой трек — он выйдет в канале отдельным постом с твоим именем, "
    "а сам трек встанет под постом.\n\n"
    "Как удобно:\n"
    "· ссылкой на любую площадку\n"
    "· текстом <i>Артист — Трек</i>\n"
    "· файлом\n\n"
    "Условия:\n"
    "· трек твой и уже на площадках\n"
    "· один трек в неделю\n"
    "· в канал — один трек в сутки, по очереди\n\n"
    # Та же строка, что в меню бота (service.MENU): «нужна подписка» читалась как платная.
    f'Всё <b>бесплатно</b> — достаточно подписаться на <a href="https://t.me/{config.CHANNEL_HANDLE.lstrip("@")}">канал</a>.'
)
FORMAT = "Не понял, какой трек. Пришли ссылку или напиши <i>Артист — Трек</i>."
NO_LINK = ("Эту ссылку не разобрал — VK и Звук без входа ничего не отдают. "
           "Напиши просто <i>Артист — Трек</i>.")
ASK_LINK = ("Файл принял. Теперь ссылку, где трек уже выложен, или <i>Артист — Трек</i>: "
            "канал выпускает только то, что вышло на площадке.")
NOT_FOUND = ("Не нашёл «{name}» ни в Apple Music, ни в Deezer. Пришли ссылку, где трек "
             "выложен: Spotify, Яндекс, YouTube или SoundCloud.\n\n"
             "Ещё не выложен и лежит вокалом и битом — сведу: /svedenie")
NEED_FILE = ("Нашёл «{name}», но площадка не отдаёт даже отрывка — под постом было бы "
             "нечего слушать. Пришли сам трек файлом: mp3 или m4a до 20 МБ.")
TOO_BIG = "Файл больше 20 МБ — Telegram не отдаёт такие ботам. Пришли mp3 полегче."
BAD_FILE = "Файл не прочитался ({reason}). Пришли другой — mp3 или m4a."

NOT_SUBSCRIBED = ('ОТБОР <b>бесплатный</b> — достаточно подписаться на <a href="https://t.me/{handle}">канал</a>.\n\n'
                  "Подпишись и пришли /otbor ещё раз.")
WEEKLY = "Один трек в неделю от человека: следующий можно прислать {date}."
KNOWN_BASE = "{artist} канал уже знает — отбор для тех, о ком ещё не слышали."
KNOWN_FANS = ("У {artist} уже {fans} фанатов на Deezer — отбор для тех, "
              "о ком ещё не слышали.")
REPEAT = "Этот трек уже был в отборе."
LENGTH = "В треке {length}, а в отбор берём от 1 до 8 минут."

WORDS = (
    "Беру: <b>{artist} — {title}</b>. Так он прозвучит под постом.\n\n"
    "Напиши одну-две фразы о треке — встанут в пост цитатой со слов артиста. "
    "Тем же сообщением можно дать ссылку на свой Telegram-канал или страницу ВКонтакте.\n\n"
    "Нечего сказать — жми кнопку."
)
BAD_WORDS = ("Так в пост не поставить: нужно 25–160 знаков, без мата, ссылок, @ников "
             "и капса. Перепиши или жми «Без слов».")
CONSENT = ("Последнее: можно взять трек в ролик канала на YouTube и в TikTok? "
           "На выход в канал ответ не влияет.")
ACCEPTED = ("Принято ✅ Ты {place}-й в очереди. В канал выходит один трек в сутки, днём. "
            "Выйдет — пришлю ссылку.")
# Трек на бит недели места в очереди не называет: он выходит раньше обычных заявок.
ACCEPTED_WEEK = ("Принято ✅ Трек идёт на бит недели: выйдет в канале раньше обычной очереди, "
                 "под ним — голосование. Выйдет — пришлю ссылку.")
WEEK_MARK = "🎚 " + WEEK_KICKER + " · «{beat}»"
WEEK_SENT = "Трек на бит недели прислал сам артист. Голосуй в комментариях ↓"
# Итог недели (final) — шаблоном, как и пост отбора: о звуке ни слова, только счёт опросов.
FINAL = ("🏆 <b>" + WEEK_KICKER + " · «{beat}» — ИТОГ</b>\n\n{table}\n\n"
         "Победил трек «{title}»: звукорежиссёр сведёт его руками бесплатно.\n\n"
         "Завтра — новый бит недели.")
FINAL_ROW = '{place} <a href="{link}">{name}</a> — 🔥 {fire}'
FINAL_MORE = "…и ещё {count}"
FINAL_ASK = "За какой трек голосовал ты?"  # первый комментарий под итогом (comments.seed берёт поле comment)
WON = ("🏆 Твой трек «{title}» выиграл бит недели: {link}\n\n"
       "Приз — ручное сведение: звукорежиссёр сведёт этот трек руками бесплатно и напишет сюда.")
# Метка чата — та же, что у /vopros (skleyka.QUESTION_TAG): ответ владельца на эту строку уходит победителю.
WON_OWNER = ("🏆 Бит недели выиграл трек {name} — {link}. Победителю обещано ручное сведение бесплатно. "
             "Ответ на это сообщение уйдёт ему · {tag}")
WON_LOST = "чат победителя не нашёл, напиши ему сам"
FINAL_FAILED = "🏆 Итог бита недели не вышел: до ночи не закрылись опросы под треками ({why}). Итога этой недели не будет."
CANCELLED = "Отменил. Захочешь вернуться — /otbor."
CLOSED = "Эта заявка уже закрыта. Новая — /otbor."
PUBLISHED = "Вышло: {link}\n\nПерешли своим — пусть слушают и пишут в комментариях."
# У трека из СВЕДЕНИЯ площадок нет — вкладыша и слов о нём тоже.
PUBLISHED_CARD = " Ниже — вкладыш трека со всеми площадками: его можно выложить у себя."

# Трек из СВЕДЕНИЯ (mixed): подпись пишет человек — в магазинах трека нет, сверять её не с чем.
MIX_NAME = ("Выложу этот трек в канал ПЛЁНКИ: пост с твоим именем, трек под ним.\n\n"
            "Как подписать? Напиши: <i>Артист — Трек</i>.\n\n"
            "В канал уйдёт именно эта версия. Хочешь поправить звук — сначала поправь, "
            "потом жми «🎙» под новым треком.")
# Длиннее имя и название не влезают в плеер Telegram (64 знака) и в строку карточки.
NAME_MAX = 60
BAD_NAME = (f"Так не подписать. Напиши <i>Артист — Трек</i>: имя и название до {NAME_MAX} знаков, "
            "без мата, ссылок и @ников.")
MIX_KNOWN = "Имя {artist} уже занято известным артистом. Подпиши иначе — так, чтобы вас не спутали."
# Советы — те же, что при отказе в ручном сведении (skleyka.TAKE_FLAWS): замер один.
MIX_FLAWS = ("🎙 В канал эту запись не возьму: дело в записи голоса, а запись сведением не исправить.\n\n"
             "{flaws}\n\n"
             "Перезапиши голос, сведи заново — /svedenie — и жми «🎙» под новым треком.")
MIX_FAILED = "Не вышло — что-то сломалось у меня. Напиши подпись ещё раз: <i>Артист — Трек</i>."


def _cb(choice: str) -> str:
    return f"s:otbor:{choice}"  # префикс сервиса: кнопки разбирает service.handle_callback


QUIET_BUTTONS = [[{"text": "Без слов", "callback_data": _cb("quiet")}]]
# Кнопкой, а не «напиши отмена» (владелец, 16.09.2026); слово по-прежнему работает.
CANCEL_BUTTONS = [[{"text": "Отмена", "callback_data": _cb("cancel")}]]
CONSENT_BUTTONS = [[{"text": "Можно", "callback_data": _cb("yes")},
                    {"text": "Нет", "callback_data": _cb("no")}]]


# ─────────────────────────── поиск трека ───────────────────────────


_SPLIT = re.compile(r"\s*(?:,(?=\s)|&|\bfeat\.?|\bft\.?|\bx\b)\s*", re.IGNORECASE)


def _credits(artist: str) -> list[str]:
    """«A & B feat. C» → [A, B, C]: известность и повтор сверяются по каждому имени.

    Запятая делит только с пробелом после неё: «nothing,nowhere.» — одно имя, а половина
    «nothing» находила в Deezer чужую группу, и имя в посте вело бы на её карточку (01.10.2026).
    Имя из базы идёт целиком: «Tyler, The Creator» делился на «Tyler» и «The Creator»,
    и пост получал ссылку на тёзку Tyler, а ОТБОР не узнавал в половинке артиста из базы.
    """
    whole = [name for item in state.read_json(config.ARTISTS_FILE, {}).get("artists", [])
             for name in (item.get("name") or "", *(item.get("aliases") or []))
             if len(_SPLIT.split(name)) > 1 and name.casefold() in artist.casefold()]
    for n, name in enumerate(whole):
        artist = re.sub(re.escape(name), f"\0{n}\0", artist, flags=re.IGNORECASE)
    parts = [p for p in _SPLIT.split(artist) if p] or [artist]
    return [re.sub(r"\0(\d+)\0", lambda m: whole[int(m[1])], p) for p in parts]


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


def spotify(kind: str, number: str) -> dict:
    """Трек (track) или альбом (album) Spotify, обложка — полем cover; пусто — страница не отдала.

    oEmbed Spotify отдаёт одно название, без артиста; встраиваемый плеер —
    всё сразу, включая отрывок. Ключ API для этого не нужен.
    """
    page = http.get(f"https://open.spotify.com/embed/{kind}/{number}")
    found = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page.text if page else "", re.S)
    if not found:
        return {}
    entity = json.loads(found.group(1))["props"]["pageProps"]["state"]["data"]["entity"]
    images = sorted(entity.get("visualIdentity", {}).get("image", []), key=lambda i: i.get("maxWidth", 0))
    return {**entity, "cover": images[-1]["url"] if images else ""}


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
        # link.deezer.com, deezer.page.link — короткая ссылка. Сверка точная: «deezer.com»
        # есть и в link.deezer.com, и до 01.10.2026 такая ссылка не раскрывалась вовсе.
        if host != "deezer.com":
            url = requests.get(url, timeout=20, headers={"User-Agent": http.BROWSER_UA}).url
        track = next(iter(re.findall(r"/track/(\d+)", url)), "")
        if not track and (album := deezer.album_id_from_url(url)):
            data = http.get_json(f"{deezer.BASE}/album/{album}", min_interval=deezer.MIN_INTERVAL) or {}
            tracks = data.get("tracks", {}).get("data", [])
            track = str(tracks[0]["id"]) if len(tracks) == 1 else ""
        data = http.get_json(f"{deezer.BASE}/track/{track}", min_interval=deezer.MIN_INTERVAL) if track else None
        return _deezer(data) if data and not data.get("error") else {}

    if host.endswith("spotify.com"):
        track = next(iter(re.findall(r"/track/(\w+)", url)), "")
        entity = spotify("track", track) if track else {}
        if not entity:
            return {}
        return {
            "artist": ", ".join(a["name"] for a in entity.get("artists", [])),
            "title": entity.get("name", ""),
            "url": f"https://open.spotify.com/track/{track}",
            "cover": entity["cover"],
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
    # Площадка сама отдала и отрывок, и обложку — магазин добавить нечего, а запрос к нему
    # после ссылки Apple — это три секунды паузы iTunes.
    if not found or found.get("preview") and found.get("cover"):
        return found
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
    """Отказ, если артист уже известен; пусто — берём.

    Найденных сами (tier auto, src/newcomers.py) база не знает в этом смысле:
    о них писала пресса, но это не значит, что у них есть слушатель, —
    решают фанаты на Deezer.
    """
    base = {
        itunes._norm(name)
        for item in state.read_json(config.ARTISTS_FILE, {"artists": []})["artists"]
        if item.get("tier") != "auto"
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


def start(chat_id: str | int, user_id: str | int, *, admin: bool = False, skleyka: bool = False) -> None:
    """Открывает заявку: /otbor, кнопка меню, ссылка с меткой из ролика (service.SOURCES),
    «💿 Уже выпущенный — тоже в канал» под готовым треком СВЕДЕНИЯ и старая кнопка оттуда же,
    когда живого трека за ней нет (mixed), — тогда заявка помнит, что трек сводил бот."""
    chat_id, user_id = str(chat_id), str(user_id)
    data = load()
    denied = refusal(data, chat_id, user_id, admin=admin)
    if denied:
        data["drafts"].pop(chat_id, None)
    else:
        data["drafts"][chat_id] = {"stage": "track", "user": user_id, **({"skleyka": True} if skleyka else {})}
    save(data)
    telegram.send_message(chat_id, denied or HINT, buttons=None if denied else CANCEL_BUTTONS)


def mixed(chat_id: str, user_id: str, track_id: str = "", *, admin: bool = False) -> None:
    """«🎙 Этот трек — в канал ПЛЁНКИ» под готовым треком СВЕДЕНИЯ: заявка без площадки.

    Проверки человека те же (refusal), проверки трека — по записи сведения (skleyka.song):
    запись жива и MP3 есть, голос записан без явного брака, длина 1–8 минут. Дальше — подпись
    (take_name) и прежние шаги. Старая «🎙 Выложил — в ОТБОР» трек не называет: берётся последний
    готовый, а нет живого — обычный отбор, куда она вела раньше.
    """
    from . import skleyka  # тянет за собой ролики и ffmpeg-цепочки — нужен только этой кнопке

    data = load()
    denied = refusal(data, chat_id, user_id, admin=admin)
    found = {} if denied else skleyka.song(chat_id, track_id)
    if denied:
        pass
    elif not found and not track_id:
        start(chat_id, user_id, admin=admin, skleyka=True)
        return
    elif not found:
        denied = skleyka.STALE
    elif found["flaws"]:
        denied = MIX_FLAWS.format(flaws="\n\n".join(f"• {advice}" for advice in found["flaws"]))
    elif found["seconds"] and not MIN_SECONDS <= found["seconds"] <= MAX_SECONDS:
        denied = LENGTH.format(length=_clock(found["seconds"]))
    data["drafts"].pop(chat_id, None)
    if not denied:
        # beat — номер бита ПЛЁНКИ, с которым трек сведён: по нему заявка идёт в зачёт бита недели (week_of).
        data["drafts"][chat_id] = {"stage": "name", "user": user_id, "skleyka": True, "file_id": found["file"],
                                   **({"beat": found["beat"]} if found.get("beat") else {})}
    save(data)
    telegram.send_message(chat_id, denied or MIX_NAME, buttons=None if denied else CANCEL_BUTTONS)


def take_name(draft: dict, text: str, data: dict, chat_id: str) -> str:
    """Подпись трека из СВЕДЕНИЯ — «Артист — Трек» словами человека, через фильтр слов о треке
    (брань, ссылки, @ники). Известное имя — отказ с просьбой подписать своим: площадка за артиста
    здесь не ручается, и подписаться чужим именем иначе мог бы любой. Заявка при этом открыта —
    человек пишет подпись заново. Дальше плеер и вопрос о словах, как у трека с площадки.
    """
    text = " ".join(text.split())
    parts = [part.strip() for part in DASH.split(text, maxsplit=1)]
    if len(parts) != 2 or not all(parts) or max(map(len, parts)) > NAME_MAX or RUDE.search(text) or JUNK.search(text):
        return BAD_NAME
    artist, title = parts
    if known(artist):
        return MIX_KNOWN.format(artist=html.escape(artist))
    if any(item.get("key") == key(artist, title) for item in (*data["queue"], *data["done"])):
        draft["stage"] = "refused"
        return REPEAT
    draft.update(artist=artist, title=title)
    file_id = draft["file_id"]
    reply = _player(draft, chat_id)
    if "file_id" not in draft:
        # Плеер не вышел, а файл здесь наш, не человека: «пришли другой» сказать некому.
        draft["file_id"] = file_id
        return MIX_FAILED
    return reply


def _clock(seconds: float) -> str:
    return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"


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
    elif draft["stage"] == "name":
        reply = take_name(draft, text, data, chat_id)
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
    return _player(draft, chat_id)


def _player(draft: dict, chat_id: str) -> str:
    """Плеер артисту с вопросом о словах — последний шаг приёма трека, общий для трека с площадки
    и трека из СВЕДЕНИЯ. Пусто — плеер ушёл; текст — отказ по длине или файл не прочитался."""
    caption = WORDS.format(artist=html.escape(draft["artist"]), title=html.escape(draft["title"]))
    try:
        with tempfile.TemporaryDirectory() as work:
            audio, seconds, thumb = _audio(draft, Path(work))
            if seconds and not MIN_SECONDS <= seconds <= MAX_SECONDS:
                draft["stage"] = "refused"
                return LENGTH.format(length=_clock(seconds))
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
    pages = {field: found.group(0) for field, (_, pattern) in PAGES.items() if (found := pattern.search(text))}
    for _, pattern in PAGES.values():
        text = pattern.sub("", text)
    words = " ".join(URL.sub("", text).split())
    if words and not suitable(words, MIN_LIKES) or not (words or pages):
        return BAD_WORDS, QUIET_BUTTONS
    for field, link in pages.items():
        draft[field] = link if link.startswith("http") else f"https://{link}"
    if words:
        draft["quote"] = words
    draft["stage"] = "consent"
    return CONSENT, CONSENT_BUTTONS


def callback(chat_id: str | int, user_id: str | int, choice: str, *, admin: bool = False) -> None:
    """Кнопки отбора: пустой выбор — открыть заявку, mix:<трек> — трек из СВЕДЕНИЯ без площадки
    (skleyka — та же кнопка до 06.10.2026, без номера трека), cancel — закрыть, quiet — без слов,
    yes/no — ролик."""
    chat_id = str(chat_id)
    if choice == "":
        start(chat_id, user_id, admin=admin)
        return
    if choice == "skleyka" or choice.startswith("mix:"):
        mixed(chat_id, str(user_id), choice.partition(":")[2], admin=admin)
        return
    if choice == "cancel":
        telegram.send_message(chat_id, CANCELLED if active(chat_id) else CLOSED)
        cancel(chat_id)
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


FIELDS = ("artist", "title", "url", "cover", "track_file_id", "seconds", "quote", "skleyka", "beat", *PAGES)


def submit(data: dict, chat_id: str, user_id: str, *, reel: bool, admin: bool) -> None:
    draft = data["drafts"].pop(chat_id)
    denied = refusal(data, chat_id, user_id, admin=admin)
    if not denied:
        data["queue"].append({
            **{field: draft[field] for field in FIELDS if draft.get(field)},
            "chat": chat_id, "at": state.iso(), "reel": reel, "key": key(draft["artist"], draft["title"]),
        })
    save(data)
    telegram.send_message(chat_id, denied or (ACCEPTED_WEEK if week_of(data["queue"][-1])
                                              else ACCEPTED.format(place=len(data["queue"]))))


# ─────────────────────────── выход в канал ───────────────────────────


def week_of(application: dict) -> str:
    """Неделя бита недели (дата понедельника), в зачёт которой идёт заявка; пусто — обычная заявка.

    В зачёт идёт трек, сведённый с битом этой недели через «🎚 Свести с этим битом» (номер бита —
    поле beat, от skleyka.song) и присланный на этой же неделе до конца субботы по Москве. Считается
    в момент выхода, а не приёма: трек, не успевший выйти к итогу (final), в итог не идёт — после
    итога и на следующей неделе он выходит обычным постом отбора, без метки и без очереди недели.
    """
    moment = state._parse(application.get("at", ""))
    if not application.get("beat") or not moment:
        return ""
    from . import bity  # тянет за собой сведение и ролики — нужен только треку с битом ПЛЁНКИ
    from .compose import MSK

    monday = bity.week()
    if bity.week(moment) != monday or moment.astimezone(MSK).weekday() == 6:
        return ""
    if application["beat"] != bity.weekly() or (config.ARCHIVE / FINAL_FILE.format(week=monday)).exists():
        return ""
    return monday


def build_post(application: dict) -> dict:
    """Пост шаблоном: имя, трек, кто прислал, слова артиста, ссылки. О звуке — ничего.
    У трека на бит недели (week_of) первой строкой метка с названием бита, а в посте — поле week:
    по нему итог недели находит свои треки (final)."""
    esc = html.escape
    artist, title = application["artist"], application["title"]
    week = week_of(application)
    if week:
        from . import bity

        beat = bity.load().get(application["beat"], {}).get("title", "")
    parts = [
        *([WEEK_MARK.format(beat=esc(beat))] if week else []),
        f"<b>{esc(artist.upper())} — «{esc(title.upper())}»</b>",
        WEEK_SENT if week else "Трек прислал в отбор сам артист.",  # где слушать — строкой publish.track_note
    ]
    if application.get("quote"):
        parts.append(f"Со слов артиста:\n<blockquote>{esc(application['quote'])}</blockquote>")
    links = []
    # Короткими словами, как площадки в строке «Слушать», а не фразой-ссылкой.
    pages = [f'<a href="{esc(application[field])}">{label}</a>' for field, (label, _) in PAGES.items()
             if application.get(field)]
    if pages:
        links.append("▸ Артист — " + " · ".join(pages))
    if application.get("url"):
        # Строку разворачивает в площадки publish.listen — как у поста о релизе.
        links.append(f'▸ <a href="{esc(application["url"])}">Слушать</a>')
    if links:
        parts.append("\n".join(links))
    if application.get("skleyka"):
        # Артист нажал «🎙» под своим треком из СВЕДЕНИЯ (владелец, 24.09.2026):
        # читатель канала видит живой трек из бота, а не рекламу бота.
        parts.append(f'Вокал с битом свёл бот канала — <a href="https://t.me/{config.BOT_HANDLE.lstrip("@")}'
                     f'?start=skleyka_otbor">СВЕДЕНИЕ</a>.')
    parts.append(f"Пришли свой — {config.BOT_HANDLE}")
    return {
        "rubric": "otbor",
        "text": "\n\n".join(parts),
        "artist": artist,
        "track": title,
        "cover": application.get("cover", ""),
        # Сведён ботом и площадки нет (mixed): кадр поста — карточка с именем, а не фото по имени
        # (card.cover), и во ВКонтакте пост не идёт — слушать там нечего (publish.crosspost_vk).
        **({"mixed": True} if application.get("skleyka") and not application.get("url") else {}),
        **({"week": week, "kicker": WEEK_KICKER} if week else {}),  # kicker — надпись на карточке (card.cover)
        "full_track_file_id": application.get("track_file_id", ""),
        # Согласие на ролик — в открытый архив: по нему бриф роликов собирает
        # «ТРИ ТРЕКА ИЗ БОТА», а к приватной заявке облачный сценарист доступа не имеет.
        "reel": bool(application.get("reel")),
        "created_at": state.iso(),
    }


def _lanes() -> tuple[bool, bool]:
    """Что отбору можно выпустить сейчас: (трек на бит недели, обычную заявку). Считается по вышедшим
    сегодня по Москве постам отбора: обычный — один в сутки, трек недели — не больше WEEK_PER_DAY
    и не чаще раза в WEEK_GAP. Трек недели узнаётся по полю week поста в архиве."""
    from .compose import MSK

    today = state.now().astimezone(MSK).date()
    usual, week = [], []
    for item in state.read_json(config.POSTED_FILE, {"items": []}).get("items", []):
        moment = state._parse(item.get("published_at", ""))
        if item.get("rubric") == "otbor" and moment and moment.astimezone(MSK).date() == today:
            marked = item.get("file") and state.read_json(config.ARCHIVE / item["file"], {}).get("week")
            (week if marked else usual).append(moment)
    return len(week) < WEEK_PER_DAY and (not week or state.now() - max(week) >= WEEK_GAP), not usual


def _first(data: dict, lanes: tuple[bool, bool]) -> dict | None:
    """Заявка, которая выходит следующей: трек на бит недели — раньше обычных, среди своих —
    по порядку прихода. lanes — что сейчас можно выпустить (_lanes)."""
    queue = [(not week_of(application), application) for application in data["queue"]]
    return next((application for usual, application in sorted(queue, key=lambda pair: pair[0]) if lanes[usual]), None)


def next_path(data: dict, lanes: tuple[bool, bool] = (True, True)) -> tuple[Path | None, dict]:
    """Пост отбора, который выходит следующим: готовый или собранный из заявки (_first)."""
    pending = sorted(config.OTBOR_POSTS.glob("*.json"))
    if pending:
        post = state.read_json(pending[0], {})
        return (pending[0], post) if lanes[not post.get("week")] else (None, {})
    application = _first(data, lanes)
    if not application:
        return None, {}
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
    lanes = _lanes()
    if state.now().astimezone(MSK).hour not in DAY_HOURS_MSK or not any(lanes):
        return
    path, post = next_path(data, lanes)
    if path is None or post.get("approval_sent_at"):
        return
    if not path.exists():
        application = _first(data, lanes)
        data["queue"].remove(application)
        state.write_json(path, post)
        data["done"].append({field: application[field] for field in ("chat", "at", "key", "reel")}
                            | {"file": path.name})
        save(data)
    publish.deliver(post, path, target)
    print(f"Выход отбора: {path.name} → {target}")


def final() -> str:
    """Итог бита недели — постом в канал: в воскресенье с FINAL_HOUR_MSK по Москве, не ночью, один
    на неделю. Возвращает «итог <понедельник>» или пусто. Зовёт дежурство (moderate.publish_shift).

    Треки недели — вышедшие посты отбора с полем week этой недели. Меньше WEEK_MIN — итога нет вовсе,
    молча. Голоса отдаёт только закрытие опроса (telegram.stop_poll), и счёт сразу ложится в файл поста
    полем votes: закрытый опрос второй раз не закрыть, а заход может повториться. Опроса под треком
    нет — ноль голосов. Опрос не закрылся — попытка на следующем круге; в последний час перед ночью
    сдаёмся: отметка без поста и строка владельцу. Победитель — по «🔥», при равенстве по «👍»,
    затем — кто вышел раньше.

    Отметка — content/archive/week-<понедельник>.json: сам пост итога (или запись о сбое). Не вышло —
    отметка снимается, и следующий заход пробует снова; голоса к тому времени уже в файлах постов.
    Победителю — сообщение от бота, владельцу — строка с меткой чата, как у /vopros: его ответ на неё
    уходит победителю. Бесплатный заказ бот не заводит — владелец отдаёт его сам (skleyka --hand, «🎁»).
    """
    from . import bity, skleyka
    from .compose import MSK

    now = state.now()
    local, monday = now.astimezone(MSK), bity.week(now)
    mark = config.ARCHIVE / FINAL_FILE.format(week=monday)
    if local.weekday() != 6 or local.hour < FINAL_HOUR_MSK or publish.night(now) or mark.exists():
        return ""
    # Имя файла поста начинается с даты выхода: старые недели не читаются, а порядок файлов — порядок выхода.
    posts = [(path, state.read_json(path, {})) for path in sorted(config.ARCHIVE.glob("*-otbor-*.json"))
             if path.name[:8] >= monday.replace("-", "")]
    posts = [(path, post) for path, post in posts if post.get("week") == monday and post.get("message")]
    if len(posts) < WEEK_MIN:
        return ""
    admin, failed = config.secret("TELEGRAM_ADMIN_ID"), ""
    for path, post in posts:
        if "votes" in post or not post.get("poll"):
            continue
        try:
            poll = telegram.stop_poll(post["poll"]["chat"], post["poll"]["message_id"])
        except telegram.TelegramError as exc:
            failed = str(exc)[:120]
            continue
        post["votes"] = [option.get("voter_count", 0) for option in poll.get("options", [])]
        state.write_json(path, post)
    if failed:
        # ponytail: сдаёмся в последний час перед ночью. Стояло дежурство весь этот час — строки
        # владельцу не будет, неделя кончится молча; понадобится — сверять прошлую неделю в понедельник.
        if local.hour >= config.QUIET_FROM_HOUR - 1:
            # Сначала строка, потом отметка: не ушла строка — следующий круг скажет ещё раз.
            telegram.send_message(admin, FINAL_FAILED.format(why=html.escape(failed)))
            state.write_json(mark, {"rubric": "week", "week": monday, "failed": failed})
        return ""

    def votes(post: dict, place: int) -> int:
        counted = post.get("votes") or []
        return counted[place] if place < len(counted) else 0

    # sorted стабилен: при равном счёте остаётся порядок выхода.
    ranked = sorted(posts, key=lambda pair: (-votes(pair[1], FIRE), -votes(pair[1], FINE)))
    handle = config.CHANNEL_HANDLE.lstrip("@")
    links = [f"https://t.me/{handle}/{post['message']['message_id']}" for _, post in ranked]
    rows = [FINAL_ROW.format(place=f"{number}." if number > 1 else "🥇", link=link, fire=votes(post, FIRE),
                             name=html.escape(f"{post['artist']} — «{post['track']}»"))
            for number, (link, (_, post)) in enumerate(zip(links, ranked), 1)]
    won_path, won = ranked[0]
    beat = bity.load().get(bity.weekly(now), {}).get("title", "")
    shown = len(rows)
    while True:
        # Подпись к фото — до 1024 знаков: не влезло — хвост таблицы уходит под «…и ещё N», победитель остаётся.
        table = "\n".join([*rows[:shown], *([FINAL_MORE.format(count=len(rows) - shown)] if shown < len(rows) else [])])
        text = FINAL.format(beat=html.escape(beat), table=table, title=html.escape(won["track"]))
        if shown == 1 or telegram.visible_len(text) <= telegram.MAX_CAPTION:
            break
        shown -= 1
    # mixed и kicker — кадр поста: карточка с именем победителя (card.cover); во ВКонтакте итог не идёт.
    post = {"rubric": "week", "week": monday, "text": text, "artist": won["artist"], "track": won["track"],
            "mixed": True, "kicker": f"{WEEK_KICKER} · ИТОГ", "comment": FINAL_ASK, "winner": won_path.name,
            "created_at": state.iso()}
    state.write_json(mark, post)
    try:
        publish.to_channel(post, mark, config.secret("TELEGRAM_CHANNEL_ID"))
    except Exception:
        mark.unlink(missing_ok=True)
        raise
    chat = next((entry["chat"] for entry in load()["done"] if entry.get("file") == won_path.name), "")
    name = html.escape(f"{won['artist']} — «{won['track']}»")
    for whom, line in ((chat, WON.format(title=html.escape(won["track"]), link=links[0])),
                       (admin, WON_OWNER.format(name=name, link=links[0],
                                                tag=f"{skleyka.QUESTION_TAG}{chat}" if chat else WON_LOST))):
        try:
            if whom:
                telegram.send_message(whom, line)
        except telegram.TelegramError as exc:  # итог уже вышел — несказанное слово его не отменяет
            log.warning("Весть об итоге бита недели не ушла: %s", exc)
    return f"итог {monday}"


def notify(data: dict) -> None:
    """Артисту — ссылка на его пост: перешлёт своим, ради этого отбор и затеян.
    Следом — ВКЛАДЫШ его трека (src/vkladysh.py): карточку со всеми площадками
    артист постит у себя сам, и на ней марка канала. У трека из СВЕДЕНИЯ площадок
    нет — уходит одна ссылка."""
    from . import vkladysh  # vkladysh сам берёт поиск отсюда

    changed = False
    for entry in data["done"]:
        if entry.get("notified"):
            continue
        post = state.read_json(config.ARCHIVE / entry["file"], {})
        message = post.get("message") or {}
        if not message:
            if not (config.OTBOR_POSTS / entry["file"]).exists():
                entry["notified"] = changed = True  # владелец удалил пост кнопкой — сказать нечего
            continue
        link = f"https://t.me/{config.CHANNEL_HANDLE.lstrip('@')}/{message['message_id']}"
        listen = publish._LISTEN_LINE.search(post.get("text", ""))
        try:
            telegram.send_message(entry["chat"], PUBLISHED.format(link=link) + (PUBLISHED_CARD if listen else ""),
                                  preview=True)
        except telegram.TelegramError as exc:
            log.warning("Артист не узнал о выходе: %s", exc)  # закрыл бота — повторять незачем
        else:
            try:
                if listen:
                    vkladysh.send(entry["chat"], {"artist": post["artist"], "title": post["track"],
                                                  "url": html.unescape(listen.group(1)), "cover": post.get("cover", "")})
            except Exception as exc:  # noqa: BLE001 — весть ушла, второй раз её слать нельзя
                log.warning("Вкладыш артисту не ушёл: %s", exc)
        entry["notified"] = changed = True
    if changed:
        save(data)


# ─────────────────────────── проверка ───────────────────────────


def _selftest() -> None:
    """Без сети: три способа прислать, трек из СВЕДЕНИЯ без площадки, отказы, текст поста, выход и весть артисту."""
    import os
    import sys
    from datetime import datetime, timezone
    from unittest import mock

    from . import card, footage, moderate

    assert _credits("A, B & C feat. D") == ["A", "B", "C", "D"] and _credits("nothing,nowhere.") == ["nothing,nowhere."]

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
    subscribed = {"1": True, "2": True, "3": True, "4": True, "5": False, "6": True, "7": True, "8": True}
    reloaded: list[str] = []  # какие файлы перезаливались плеером
    now = datetime(2026, 9, 17, 10, 0, tzinfo=timezone.utc)  # 13:00 МСК

    with mock.patch.object(requests, "get", lambda url, **_: mock.Mock(url="https://www.deezer.com/de/track/7?host=1")), \
            mock.patch.object(http, "get_json", lambda url, **_: {"title": "Подвал", "link": url}):
        assert _from_link("https://link.deezer.com/s/abc")["url"].endswith("/track/7"), "короткая ссылка Deezer"

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
    ), mock.patch.object(moderate, "normalize_track",
                         lambda track, post, work: reloaded.append(track["file_id"]) or (b"mp3", 200, None)), \
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
        handle(msg(1, "Записал за одну ночь в гараже у друга https://vk.com/nobodyhome t.me/nobodyhome_music"))
        assert last("1") == CONSENT
        callback(1, 1, "yes")
        assert last("1").startswith("Принято") and "1-й" in last("1")
        queued = load()["queue"][0]
        assert queued["vk"] == "https://vk.com/nobodyhome" and queued["track_file_id"] == "PLAYER-1"
        assert queued["tg"] == "https://t.me/nobodyhome_music"
        assert queued["quote"] == "Записал за одну ночь в гараже у друга", queued["quote"]

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
        callback(4, 4, "cancel")
        assert last("4") == CANCELLED and not active(4)
        start(5, 5)
        assert last("5").startswith("ОТБОР <b>бесплатный</b>") and 'href="https://t.me/' in last("5") and not active(5)
        start(1, 1)
        assert last("1") == WEEKLY.format(date="24.09") and not active(1)

        # Текст поста: шаблон без слов о звуке, цитата артиста, ссылки и зов в бота.
        text = build_post(queued)["text"]
        assert text.startswith("<b>NOBODY HOME — «NIGHT DRIVE»</b>")
        assert "Со слов артиста:\n<blockquote>Записал" in text and text.endswith(f"Пришли свой — {config.BOT_HANDLE}")
        assert "skleyka_otbor" not in text and "?start=skleyka_otbor\">СВЕДЕНИЕ</a>" in build_post({**queued, "skleyka": True})["text"]
        assert ('▸ Артист — <a href="https://vk.com/nobodyhome">ВКонтакте</a> · '
                '<a href="https://t.me/nobodyhome_music">Telegram</a>') in text and publish._LISTEN_LINE.search(text)
        # Площадки разворачиваются, а зов в бота остаётся отдельным абзацем.
        assert "</a>\n\nПришли свой" in publish.listen(text, "Nobody Home", "Night Drive")
        assert build_post({"artist": "A&B", "title": "<x>"})["text"].startswith("<b>A&amp;B — «&lt;X&gt;»</b>")

        # Выход: первая заявка днём, вторая — не в тот же день.
        shift("channel")
        assert delivered and "NOBODY HOME" in delivered[0] and len(load()["queue"]) == 1
        path = next(config.OTBOR_POSTS.glob("*.json"))
        state.write_json(config.POSTED_FILE, {"items": [{"rubric": "otbor", "published_at": state.iso()}]})
        state.write_json(config.ARCHIVE / path.name, {**build_post(queued), "message": {"message_id": 321}})
        path.unlink()
        cards = []
        with mock.patch("src.vkladysh.send", lambda chat, track: cards.append((chat, track))):
            shift("channel")
        assert len(delivered) == 1, "второй пост отбора в тот же день"
        assert last("1") == PUBLISHED.format(link="https://t.me/plenka_fm/321") + PUBLISHED_CARD
        assert cards == [("1", {"artist": "Nobody Home", "title": "Night Drive",
                                "url": "https://music.apple.com/us/album/x/1?i=2",
                                "cover": "https://is1.mzstatic.com/c.jpg"})], cards

        # 4. Из-под готового трека СВЕДЕНИЯ: ни ссылки, ни магазина — подпись словами, плеер из
        # сведённого файла, заявка с меткой. Чужое имя и мат в подписи заявку не закрывают.
        fine = {"file": "MIX6", "seconds": 153.0, "flaws": []}
        songs = {("6", "t6"): fine, ("8", ""): dict(fine, file="MIX8"),
                 ("7", "t7"): dict(fine, flaws=["Голос записан с перегрузом."]), ("7", "t8"): dict(fine, seconds=40.0)}
        asked: list[tuple] = []

        def song(chat, track=""):
            asked.append((str(chat), track))
            return dict(songs.get((str(chat), track), {}))

        with mock.patch("src.skleyka.song", song), mock.patch("src.skleyka.STALE", "устарело"):
            callback(6, 6, "mix:t6")
            assert last("6") == MIX_NAME and "именно эта версия" in MIX_NAME and load()["drafts"]["6"]["stage"] == "name"
            for text, reply in (("просто слова", BAD_NAME), ("Лил Пи @lilpi — Рейс", BAD_NAME),
                                ("Лил Пи — сука любовь", BAD_NAME), (f"Лил Пи — {'я' * (NAME_MAX + 1)}", BAD_NAME),
                                ("Kizaru — Мой трек", "Имя Kizaru уже занято известным артистом. Подпиши иначе — так, чтобы вас не спутали."),
                                ("Big Name — Мой трек", "Имя Big Name уже занято известным артистом. Подпиши иначе — так, чтобы вас не спутали.")):
                handle(msg(6, text))
                assert last("6") == reply and load()["drafts"]["6"]["stage"] == "name", (text, last("6"))
            handle(msg(6, "Лил Пи — Ночной рейс"))
            assert reloaded[-1] == "MIX6" and played[-1]["audio"] == b"mp3" and "Беру: <b>Лил Пи — Ночной рейс</b>" in last("6")
            assert (played[-1]["performer"], played[-1]["title"]) == ("Лил Пи", "Ночной рейс")
            callback(6, 6, "quiet")
            callback(6, 6, "yes")
            sent = load()["queue"][-1]
            assert last("6").startswith("Принято") and sent["skleyka"] and sent["track_file_id"] == "PLAYER-6" \
                and not {"url", "cover"} & set(sent) and sent["key"] == key("Лил Пи", "Ночной рейс"), sent

            # Старая кнопка без номера трека: последний готовый; живого нет — обычный отбор, как раньше.
            callback(8, 8, "skleyka")
            assert last("8") == MIX_NAME and load()["drafts"]["8"]["file_id"] == "MIX8"
            handle(msg(8, "Лил Пи — Ночной рейс"))
            assert last("8") == REPEAT and not active(8), "та же подпись второй раз"
            callback(7, 7, "skleyka")
            assert last("7") == HINT and load()["drafts"]["7"] == {"stage": "track", "user": "7", "skleyka": True}
            # «💿 Уже выпущенный»: обычный отбор и без метки сведения.
            callback(7, 7, "")
            assert last("7") == HINT and "skleyka" not in load()["drafts"]["7"]
            # Отказы трека: брак записи — с советом и дорогой дальше, длина, стёртая запись.
            for choice, start_of in (("mix:t7", "🎙 В канал эту запись не возьму"), ("mix:t8", "В треке 0:40"),
                                     ("mix:нет000", "устарело")):
                callback(7, 7, choice)
                assert last("7").startswith(start_of) and not active(7), (choice, last("7"))
            callback(7, 7, "mix:t7")
            assert "• Голос записан с перегрузом." in last("7") and "жми «🎙» под новым треком" in last("7")
            # Отказы человека — раньше трека: без подписки и в ту же неделю сведение даже не спрашивают.
            asked.clear()
            callback(5, 5, "mix:t6")
            callback(1, 1, "mix:t6")
            assert last("5").startswith("ОТБОР <b>бесплатный</b>") and last("1") == WEEKLY.format(date="24.09") and not asked

        # Пост сведённого трека: площадок нет — ни строки «Слушать», ни пустых строк, ни разделителей.
        post = build_post(sent)
        assert post["text"] == (
            "<b>ЛИЛ ПИ — «НОЧНОЙ РЕЙС»</b>\n\nТрек прислал в отбор сам артист.\n\n"
            f'Вокал с битом свёл бот канала — <a href="https://t.me/{config.BOT_HANDLE.lstrip("@")}?start=skleyka_otbor">'
            f"СВЕДЕНИЕ</a>.\n\nПришли свой — {config.BOT_HANDLE}"), post["text"]
        assert post["mixed"] and not post["cover"] and post["full_track_file_id"] == "PLAYER-6"
        assert "mixed" not in build_post(queued) and "mixed" not in build_post({**queued, "skleyka": True})
        shown = publish.track_note(publish.listen(post["text"], post["artist"], post["track"]), post)
        assert shown == f"{post['text']}\n\n{publish.TRACK_ALONE}", shown
        # Кадр — карточка с именем: фото по имени было бы лицом тёзки. Во ВКонтакте пост не идёт.
        with mock.patch.object(card, "OUT_DIR", Path(tmp) / "cards"), \
                mock.patch.object(footage, "find_artist", mock.Mock(side_effect=AssertionError("поиск фото"))), \
                mock.patch.object(footage, "artist_images", mock.Mock(side_effect=AssertionError("поиск фото"))):
            assert card.cover(dict(post)).stat().st_size > 10_000
        with mock.patch.dict(os.environ, {"VK_TOKEN": "x"}), mock.patch("src.vk.post") as vk_post:
            publish.crosspost_vk(dict(post))
            assert not vk_post.called
            publish.crosspost_vk(build_post(queued))
            assert vk_post.called, "обычный отбор во ВКонтакте идёт как шёл"
        # Вышел — артисту одна ссылка: вкладыш строится по площадкам, а их нет.
        data = load()
        data["queue"].remove(sent)
        data["done"].append({"chat": "6", "at": sent["at"], "key": sent["key"], "reel": True, "file": "mixed.json"})
        save(data)
        state.write_json(config.ARCHIVE / "mixed.json", {**post, "message": {"message_id": 654}})
        with mock.patch("src.vkladysh.send", lambda chat, track: cards.append((chat, track))):
            notify(load())
        assert last("6") == PUBLISHED.format(link="https://t.me/plenka_fm/654") and len(cards) == 1, last("6")

        # 5. БИТ НЕДЕЛИ. Бит №3 вышел в понедельник 14.09; трек, сведённый с ним, несёт номер бита
        # из сведения в заявку и выходит с меткой недели, раньше обычных заявок.
        from . import skleyka

        stops: list[int] = []
        finals: list[dict] = []
        polls = {501: [5, 1, 0], 502: [5, 3, 1], 503: None}  # None — опрос не закрылся

        def deliver(post: dict, path: Path, target: str) -> None:
            """Как publish.to_channel: пост в архиве с сообщением канала, запись в журнале."""
            delivered.append(post["text"])
            state.write_json(config.ARCHIVE / path.name, {**post, "message": {"message_id": 700 + len(delivered)}})
            path.unlink()
            posted = state.read_json(config.POSTED_FILE, {"items": []})
            posted["items"].append({"rubric": "otbor", "file": path.name, "published_at": state.iso()})
            state.write_json(config.POSTED_FILE, posted)

        def stop_poll(chat, message_id):
            stops.append(message_id)
            if polls[message_id] is None:
                raise telegram.TelegramError("stopPoll: сеть")
            return {"options": [{"voter_count": count} for count in polls[message_id]]}

        def clock(day: int, hour: int, minute: int = 0) -> None:
            nonlocal now
            now = datetime(2026, 9, day, hour, minute, tzinfo=timezone.utc)

        def archived(number: int) -> Path:
            return next(path for path in sorted(config.ARCHIVE.glob("*-otbor-*.json"))
                        if state.read_json(path, {})["message"]["message_id"] == number)

        subscribed["9"] = True
        songs[("9", "t9")] = dict(fine, file="MIX9", beat="3")
        mark = config.ARCHIVE / FINAL_FILE.format(week="2026-09-14")
        with mock.patch("src.skleyka.song", song), mock.patch.object(config, "BEATS_FILE", Path(tmp) / "beats.json"), \
                mock.patch.dict(os.environ, {"TELEGRAM_ADMIN_ID": "900"}), mock.patch.object(publish, "deliver", deliver), \
                mock.patch.object(publish, "to_channel", lambda post, path, chat: finals.append(post)), \
                mock.patch.object(telegram, "stop_poll", stop_poll), mock.patch.object(card, "OUT_DIR", Path(tmp) / "cards"), \
                mock.patch("src.vkladysh.send", lambda chat, track: cards.append((chat, track))):
            state.write_json(config.BEATS_FILE, {"3": {"title": "Наждак", "artists": ["Kizaru"]}})
            state.write_json(config.ARCHIVE / "beat-3.json", {"rubric": "beat", "beat": "3", "week": "2026-09-14",
                                                             "message": {"message_id": 300}})
            callback(9, 9, "mix:t9")
            handle(msg(9, "Ваня — Гараж"))
            callback(9, 9, "quiet")
            callback(9, 9, "yes")
            entry = load()["queue"][-1]
            assert entry["beat"] == "3" and last("9") == ACCEPTED_WEEK and week_of(entry) == "2026-09-14", (entry, last("9"))
            post = build_post(entry)
            assert post["text"].startswith(f"🎚 БИТ НЕДЕЛИ · «Наждак»\n\n<b>ВАНЯ — «ГАРАЖ»</b>\n\n{WEEK_SENT}\n\n"), post["text"]
            assert post["week"] == "2026-09-14" and post["kicker"] == WEEK_KICKER and post["mixed"], post
            # Чужой бит, заявка в воскресенье и заявка прошлой недели — обычный пост отбора, без метки.
            for other in ({**entry, "beat": "1"}, {**entry, "at": "2026-09-13T10:00:00+00:00"}):
                assert not week_of(other) and "week" not in build_post(other) and "БИТ НЕДЕЛИ" not in build_post(other)["text"]
            late = {**entry, "at": "2026-09-19T21:00:00+00:00"}  # воскресенье, 00:00 по Москве
            clock(20, 10)
            assert week_of({**entry, "at": "2026-09-19T20:59:00+00:00"}) == "2026-09-14", "суббота, 23:59 — ещё в зачёт"
            assert not week_of(late) and "week" not in build_post(late), "после субботы — обычный отбор"
            clock(21, 10)
            assert not week_of(entry), "новая неделя — прежний бит уже не бит недели"

            # Очередь: трек недели — раньше обычной заявки и мимо «одного в сутки» (обычный сегодня уже
            # выходил), но не больше двух в сутки и не чаще раза в три часа.
            clock(17, 10)
            data = load()
            assert [item["artist"] for item in data["queue"]] == ["Ghost Tape", "Ваня"], data["queue"]
            data["queue"] += [{**entry, "chat": str(chat), "title": title, "key": key("Ваня", title)}
                              for chat, title in ((10, "Двор"), (11, "Мост"))]
            save(data)
            count = len(delivered)
            shift("channel")
            assert len(delivered) == count + 1 and "«ГАРАЖ»" in delivered[-1] and "БИТ НЕДЕЛИ" in delivered[-1], delivered[-1]
            shift("channel")
            clock(17, 12, 59)
            shift("channel")
            assert len(delivered) == count + 1, "второй трек недели — не раньше чем через три часа"
            clock(17, 13)
            shift("channel")
            assert len(delivered) == count + 2 and "«ДВОР»" in delivered[-1], delivered[-1]
            clock(17, 16, 30)
            shift("channel")
            assert len(delivered) == count + 2, "третий трек недели за сутки и второй обычный не выходят"
            # Двух треков для итога мало: воскресный вечер проходит молча, опросы не трогаются.
            clock(20, 16)
            assert final() == "" and not stops and not mark.exists() and not finals, "итог при двух треках"
            clock(18, 10)
            shift("channel")
            assert len(delivered) == count + 3 and "«МОСТ»" in delivered[-1], "наутро трек недели — раньше обычной заявки"
            shift("channel")
            assert len(delivered) == count + 4 and "GHOST TAPE" in delivered[-1] and "БИТ НЕДЕЛИ" not in delivered[-1], \
                "обычный отбор — как был: один в сутки"

            # Итог: воскресенье с 19:00 по Москве. Голоса — закрытием опроса, сразу в файл поста;
            # незакрывшийся опрос — попытка на следующем круге, закрытые второй раз не трогаются.
            first, second, third = (archived(700 + count + number) for number in (1, 2, 3))
            for path, number in ((first, 501), (second, 502), (third, 503)):
                state.write_json(path, {**state.read_json(path, {}), "poll": {"chat": "-100", "message_id": number}})
            clock(19, 17)
            assert final() == "", "суббота — не день итога"
            clock(20, 15, 59)
            assert final() == "" and not stops, "воскресенье, 18:59 по Москве — рано"
            clock(20, 16)
            assert final() == "" and stops == [501, 502, 503] and not mark.exists() and not finals, stops
            assert state.read_json(first, {})["votes"] == [5, 1, 0] and "votes" not in state.read_json(third, {})
            polls[503] = [5, 3, 0]
            clock(20, 16, 10)
            assert final() == "итог 2026-09-14" and stops == [501, 502, 503, 503], stops
            # При равенстве «🔥» решает «👍», при равенстве обоих — кто вышел раньше: «Двор» раньше «Моста».
            urls = [f"https://t.me/plenka_fm/{700 + count + number}" for number in (1, 2, 3)]
            assert finals[0]["text"] == (
                "🏆 <b>БИТ НЕДЕЛИ · «Наждак» — ИТОГ</b>\n\n"
                f'🥇 <a href="{urls[1]}">Ваня — «Двор»</a> — 🔥 5\n'
                f'2. <a href="{urls[2]}">Ваня — «Мост»</a> — 🔥 5\n'
                f'3. <a href="{urls[0]}">Ваня — «Гараж»</a> — 🔥 5\n\n'
                "Победил трек «Двор»: звукорежиссёр сведёт его руками бесплатно.\n\n"
                "Завтра — новый бит недели."), finals[0]["text"]
            assert finals[0]["rubric"] == "week" and finals[0]["mixed"] and finals[0]["winner"] == second.name \
                and (finals[0]["artist"], finals[0]["track"]) == ("Ваня", "Двор") and "chat" not in finals[0], finals[0]
            assert card.cover(dict(finals[0])).stat().st_size > 10_000, "кадр итога — карточка с именем победителя"
            # Победителю — сообщение, владельцу — строка с меткой чата: ответ на неё уходит победителю.
            assert last("10") == WON.format(title="Двор", link=urls[1]) and "бесплатно" in WON
            assert f"{skleyka.QUESTION_TAG}10" in last("900") and "обещано ручное сведение бесплатно" in last("900"), last("900")
            assert final() == "" and len(finals) == 1 and len(stops) == 4, "итог — один на неделю"
            # Трек, не успевший выйти к итогу, в итог не идёт: после итога он — обычный пост отбора.
            assert not week_of(entry) and "week" not in build_post(entry)

            # Длинная неделя: подпись к картинке не длиннее 1024 знаков — хвост таблицы под «…и ещё N».
            # Опроса под треком нет — ноль голосов; сохранённые голоса второй раз не запрашиваются.
            mark.unlink()
            for number in range(15):
                state.write_json(config.ARCHIVE / f"20260919-10{number:02d}-otbor-x.json", {
                    "week": "2026-09-14", "artist": "Длинное Имя Артиста", "track": f"Очень длинное название трека {number}",
                    "message": {"message_id": 800 + number}})
            assert final() and len(stops) == 4 and "🥇" in finals[1]["text"].split("\n\n")[1], finals[1]["text"]
            assert telegram.visible_len(finals[1]["text"]) <= telegram.MAX_CAPTION and "…и ещё " in finals[1]["text"]

            # Опрос так и не закрылся: до последнего часа перед ночью — попытки, потом отметка без поста
            # и одна строка владельцу.
            mark.unlink()
            state.write_json(third, {key_: value for key_, value in state.read_json(third, {}).items() if key_ != "votes"})
            polls[503] = None
            clock(20, 18, 59)
            assert final() == "" and not mark.exists() and len(finals) == 2
            clock(20, 19)
            assert final() == "" and state.read_json(mark, {})["failed"] and last("900").startswith("🏆 Итог бита недели не вышел")
            told = len(said)
            assert final() == "" and len(said) == told and len(finals) == 2, "строка о сбое — одна"

        # Разборы понимают ссылку и «Артист — Трек»: в разбор уходит имя артиста.
        assert subject("Molchat Doma — Судно") == "Molchat Doma"
        assert subject("https://soundcloud.com/ghost/tape") == "Ghost Tape"
        assert subject("https://vk.com/audio-1_2") == "" and subject("Bones, фонк") == "Bones, фонк"

    assert _split_title("Rick Astley - Never Gonna Give You Up (Official Video)") == {
        "artist": "Rick Astley", "title": "Never Gonna Give You Up"}
    assert _match("Nobody Home & Ghost", "Night Drive (feat. Ghost) - Single", "nobody home", "Night Drive")
    assert not _match("Nobody Homeless", "Night Drive", "Nobody Home", "Night Drive")
    print("отбор: три способа прислать, трек из СВЕДЕНИЯ без площадки (брак записи и чужое имя — отказ, старая кнопка — "
          "последний готовый, «💿» — обычный отбор без метки), отказы, пост шаблоном и без площадок, выход раз в день, "
          "весть и вкладыш артисту; бит недели: метка у трека с битом недели, без неё — чужой бит, прошлая неделя "
          "и заявка после субботы, трек недели раньше обычных — два в сутки и раз в три часа, итога нет при двух треках, "
          "голоса закрытием опроса и один раз, равенство — по «👍» и по выходу, победителю и владельцу весть, "
          "длинный итог в подписи к картинке, опросы не закрылись до ночи — строка владельцу")


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
