"""ПРОЯВКА — разборы по запросу в личке бота.

Канал публикует сам по себе, но подписчиков это не приносит: пост не пересылают,
пересылают результат про себя. Поэтому разбор бывает трёх видов, и главный из них
отдаёт картинку, которую человек показывает друзьям:

    список артистов        → откуда растёт твой вкус + карточка
    артист, трек или жанр  → к какому предку сходится ниточка
    строки из песни        → что в этих строках на самом деле происходит

Для человека это один раздел — ПРОЯВКА (/proyavka): вид бот различает по форме
сообщения. Старые команды /vkus, /nogi, /tekst и кириллица (/вкус, /проявка)
работают при наборе, но в меню Telegram не показаны — там только латиница.

Два ограничения, из которых следует всё устройство модуля:

1. **Постоянного сервера нет.** Запросы забирает раз в пять минут тот же
   поллер, что и кнопки модерации, — см. src/moderate.py. Ответ приходит
   не мгновенно, и человеку об этом сразу говорится: плёнку надо проявить.
2. **Токены не бесплатные.** Миллион GigaChat уже наполовину съеден очередью
   канала, поэтому разбор выдаётся по подписке и с суточными лимитами.

Факты берутся только из data/lineage.json и data/artists.json — по той же
причине, по которой эти базы ведутся руками: придуманная связь между артистами
убивает доверие быстрее, чем что-либо ещё. Если база молчит, бот честно
отвечает, что связь не проверена, и кладёт запрос в очередь на пополнение.

    python -m src.service --try "Bones, Sematary, Slipknot"   разбор в терминал
    python -m src.service --stats                             расход лимитов
"""

from __future__ import annotations

import argparse
import logging
import os
import re
from datetime import timedelta
import pathlib
from pathlib import Path

from . import card, collect, config, llm, otbor, quality, state, stories, telegram
from .sources import afisha, deezer, itunes, lastfm

log = logging.getLogger("service")

STATE_FILE = config.DATA / "service.json"
# Запросы, на которые базы не хватило: готовый список, чем пополнять lineage.json,
# причём по реальному спросу, а не по догадкам.
REQUESTS_FILE = config.DATA / "lineage_requests.jsonl"
# Все выданные разборы — материал для постов «разбор подписчика №N».
LOG_FILE = config.DATA / "service_log.jsonl"
# Откуда приходят в бота: метка ссылки t.me/plenka_fm_bot?start=yt из ролика или чата.
# Только числа по дню и метке — файл открытый, id человека сюда не попадает.
# Метки известные наперёд: любая нагрузка /start в счёт забила бы файл мусором.
SOURCES_FILE = config.DATA / "bot_sources.json"
SOURCES = {"yt": "YouTube", "tt": "TikTok", "vk": "ВКонтакте", "chat": "чаты артистов", "pin": "закреп канала",
           "gorod": "ролик, за концертами"}

CARD_DIR = config.ROOT / "assets" / "cards"


# ─────────────────────────── разбор входящего ───────────────────────────

# В меню бота Telegram пускает только латиницу и цифры, поэтому основные
# команды — транслитом: по-русски читаются, в меню показываются. Кириллица
# и английские названия оставлены синонимами: их всё равно набирают.
COMMANDS = {
    "vkus": "taste", "вкус": "taste", "taste": "taste",
    "nogi": "roots", "ноги": "roots", "roots": "roots",
    "tekst": "lyrics", "текст": "lyrics", "lyrics": "lyrics",
    "sovet": "recommend", "совет": "recommend",
    "novoe": "new", "новое": "new",
    "slezhu": "watchlist", "слежу": "watchlist",
    "stop": "watchstop", "стоп": "watchstop",
    "gorod": "city", "город": "city",
    "otbor": "otbor", "отбор": "otbor",
    "proyavka": "proyavka", "проявка": "proyavka",
}

# У бота три раздела, и называются они везде одинаково — в меню «/», на экране
# до «Начать», здесь и на кнопках: 🎙 ОТБОР, 🎞 ПРОЯВКА и 🔔 СЛЕЖУ. Слежение
# за релизами и концертами жило только кнопкой под разбором артиста и командами,
# которых никто не знает, — о нём не узнавали вовсе (владелец, 16.09.2026). Раньше разбор был
# расколот на «Что разобрать?» и «Разобрать текст песни», в меню «/» его не было
# вовсе, и человек не понимал, что тут есть (владелец, 16.09.2026). Вид разбора
# бот по-прежнему угадывает по форме сообщения, выбирать его не нужно.
# Отбор — первым: ради него из ролика переходят в бота (GROWTH.md, «Третий актив»).
MENU = (
    f'Бот канала — <b><a href="https://t.me/{config.CHANNEL_HANDLE.lstrip("@")}">ПЛЁНКА</a></b>\n\n'
    "🎙 <b>ОТБОР</b>\nПишешь сам? Пришли свой трек — он выйдет в канале с твоим именем.\n\n"
    "🎞 <b>ПРОЯВКА</b>\nПришли артиста, песню или строки из текста — расскажу, откуда это взялось.\n\n"
    "🔔 <b>СЛЕЖУ</b>\nНазови артистов и свой город — напишу, когда выйдет релиз или объявят концерт.\n\n"
    # «Нужна подписка» читалась как платная подписка (владелец, 16.09.2026).
    f'Всё <b>бесплатно</b> — достаточно подписаться на <a href="https://t.me/{config.CHANNEL_HANDLE.lstrip("@")}">канал</a>.'
)

# Что прислать в ПРОЯВКУ — на кнопку и /proyavka без текста.
PROYAVKA = (
    "🎞 <b>ПРОЯВКА</b>\n\n"
    "Пришли одним сообщением:\n"
    "· артиста или песню — <i>Bones</i>, <i>Молчат Дома — Судно</i> или ссылку\n"
    "· список, кого слушаешь, — покажу, что у них общего, и сделаю карточку\n"
    "· несколько строк из песни — разберу, что в них происходит"
)
# Старые кнопки в переписке и ссылки ?start=taste из вышедших постов ведут туда же.
PROYAVKA_KEYS = ("proyavka", "taste", "lyrics", "roots")

# Префикс отличает кнопки сервиса от кнопок модерации: у тех callback_data
# вида «pub:имя-файла», и обработчики не должны пересекаться.
CALLBACK_PREFIX = "s:"


def menu_buttons() -> list[list[dict]]:
    return [
        [{"text": "🎙 ОТБОР — прислать трек", "callback_data": f"{CALLBACK_PREFIX}otbor"}],
        [{"text": "🎞 ПРОЯВКА — разобрать музыку", "callback_data": f"{CALLBACK_PREFIX}proyavka"}],
        [{"text": "🔔 СЛЕЖУ — релизы и концерты", "callback_data": f"{CALLBACK_PREFIX}slezhu"}],
    ]


# Telegram отводит под callback_data 64 байта, а кириллица занимает по два
# на букву. Имя артиста туда обычно влезает, но обрезать всё равно приходится.
CALLBACK_BYTES = 64


def _cb(action: str, arg: str = "") -> str:
    data = f"{CALLBACK_PREFIX}{action}:{arg}".encode()
    return data[:CALLBACK_BYTES].decode(errors="ignore")


def again_buttons(subject: str = "") -> list[list[dict]]:
    """Кнопки под готовым разбором.

    Продолжение разговора должно быть в одно касание: человек только что узнал,
    откуда растёт артист, и следующий его вопрос предсказуем — что послушать
    и что нового. Заставлять набирать это руками незачем.
    """
    if not subject:
        return [[{"text": "Ещё разбор", "callback_data": _cb("menu")}]]
    return [
        [{"text": "🎧 Что послушать дальше", "callback_data": _cb("rec", subject)}],
        [
            {"text": "🆕 Что нового", "callback_data": _cb("new", subject)},
            {"text": "🔔 Следить", "callback_data": _cb("watch", subject)},
        ],
    ]

# Разделители списка: запятая, перенос строки, точка с запятой, буллеты.
_SPLIT = re.compile(r"[,\n;•·|]+")
# Нумерация и маркеры в начале строки — их оставляют, когда копируют список.
_BULLET = re.compile(r"^\s*(?:\d+[.):]?|[-—*])\s*")


def parse_command(text: str) -> tuple[str, str]:
    """Возвращает (вид разбора, остаток текста). Вид пустой — команды не было."""
    match = re.match(r"^/([a-zA-Zа-яА-ЯёЁ_]+)(?:@\S+)?\s*(.*)$", text, re.DOTALL)
    if not match:
        return "", text
    name = match.group(1).lower()
    if name in ("start", "help", "старт", "помощь"):
        # У /start бывает нагрузка: по ссылке t.me/бот?start=taste Telegram
        # присылает «/start taste». Так кнопка из канала ведёт сразу в разбор.
        return "menu", match.group(2).strip()
    return COMMANDS.get(name, ""), match.group(2).strip()


def split_items(text: str) -> list[str]:
    return [_BULLET.sub("", part).strip(" \t\"'«»") for part in _SPLIT.split(text) if part.strip()]


# Длиннее и многословнее этого имя артиста уже не бывает — дальше начинается
# строка песни. На этом и держится разделение вкуса и текста без команды.
NAME_MAX_CHARS = 30
NAME_MAX_WORDS = 4


def looks_like_names(items: list[str]) -> bool:
    return all(len(i) <= NAME_MAX_CHARS and len(i.split()) <= NAME_MAX_WORDS for i in items)


def guess_kind(text: str) -> str:
    """Угадывает разбор по форме сообщения, когда команду не написали.

    Список артистов и куплет выглядят по-разному: имена короткие и в два-три
    слова, строки песни длиннее и с глаголами. Разделители тут не помогают —
    запятые есть и там, и там, — поэтому смотрим на сами куски. Где форма
    неоднозначна, показываем меню: угадать неверно дороже, чем переспросить.
    """
    items = split_items(text)
    lines = [line for line in text.splitlines() if line.strip()]

    # Строки песни: несколько длинных строк подряд. Проверяем первыми — куплет
    # ни при каком раскладе не должен уехать в разбор имён.
    if len(lines) >= 2 and sum(len(line) for line in lines) / len(lines) > 18:
        return "lyrics"

    # Имена, жанры и названия песен — любое количество коротких кусков.
    # Одного достаточно: заставлять человека собирать список нельзя.
    if items and looks_like_names(items):
        return "taste"

    # Одна строка в несколько слов — тоже запрос: «Молчат Дома», «Bones — Dirt».
    if len(lines) == 1 and 2 <= len(text.strip()) <= 80 and len(text.split()) <= 6:
        return "taste"

    return ""


# ─────────────────────────── база фактов ───────────────────────────

# Мостик между тегами артистов (латиницей) и текстом связей (по-русски).
# Без него «memphis» в artists.json и «мемфисский рэп» в lineage.json
# остаются друг для друга посторонними словами.
TAG_WORDS: dict[str, tuple[str, ...]] = {
    "memphis": ("мемфис",),
    "phonk": ("фонк",),
    "drift-phonk": ("фонк", "дрифт"),
    "cloud-rap": ("клауд",),
    "ru-cloud-rap": ("клауд", "русск"),
    "raider-klan": ("raider", "purrp"),
    "emo-rap": ("эмо-рэп",),
    "gbc": ("эмо-рэп", "gothboiclique"),
    "drain-gang": ("drain", "дрейн", "bladee"),
    "sad-boys": ("дрейн", "drain"),
    "witch-house": ("витч",),
    "nu-metal": ("ню-метал",),
    "alt-metal": ("альт-метал", "ню-метал"),
    "rap-metal": ("ню-метал",),
    "trap-metal": ("trap-metal", "метал"),
    "rage": ("rage", "carti"),
    "opium": ("rage", "carti"),
    "grunge": ("грандж",),
    "post-punk": ("пост-панк",),
    "ru-post-punk": ("пост-панк", "русск"),
    "chopped-and-screwed": ("замедлен", "slowed"),
    "haunted-mound": ("sematary", "haunted"),
    "teamsesh": ("bones", "sesh"),
    "g59": ("$uicideboy$", "мемфис"),
    "ru-rap": ("русск",),
    "ru-underground": ("русск", "андеграунд"),
    "ru-classic": ("русск",),
    "dead-dynasty": ("dead dynasty", "русск"),
    "shoegaze": ("гитарн",),
    "metalcore": ("метал",),
}


def _link_text(link: dict) -> str:
    parts = [link.get("modern", ""), link.get("ancestor", ""), link.get("connection", "")]
    parts.extend(link.get("facts", []))
    return " ".join(parts).lower()


def _mentions(haystack: str, needle: str) -> bool:
    """Ищет имя целым словом: «Bones» не должен находиться внутри «Bonestorm»."""
    if len(needle) < 3:
        return False
    return re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack, re.IGNORECASE) is not None


def known_artists(query: str) -> list[dict]:
    """Артисты из базы канала, упомянутые в запросе."""
    artists = state.read_json(config.ARTISTS_FILE, {"artists": []})["artists"]
    return [a for a in artists if _mentions(query, a["name"])]


def match_links(query: str, scene: list[dict], limit: int = 3) -> list[dict]:
    """Связи из lineage.json, подходящие к запросу.

    Совпадение по имени весит больше совпадения по жанру: «Bladee» в тексте
    связи — это прямое попадание, а «русск» — лишь общая рамка.
    """
    links = state.read_json(config.LINEAGE_FILE, {"links": []})["links"]
    tags = {tag for artist in scene for tag in artist.get("tags", [])}
    words = {word for tag in tags for word in TAG_WORDS.get(tag, ())}
    names = [artist["name"] for artist in scene]

    scored: list[tuple[int, dict]] = []
    for link in links:
        text = _link_text(link)
        score = 3 * sum(1 for name in names if _mentions(text, name))
        score += sum(1 for word in words if word in text)
        # Запрос мог прийти словами, а не именами: «фонк», «ню-метал», «дрейн».
        score += 2 * sum(1 for word in re.findall(r"[\w-]{4,}", query.lower()) if word in text)
        if score:
            scored.append((score, link))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [link for _, link in scored[:limit]]


def scene_payload(artists: list[dict]) -> list[dict]:
    return [{"name": a["name"], "tags": a.get("tags", [])} for a in artists]


# Сколько имён из запроса проверяем во внешнем источнике. Каждое — три запроса
# к Last.fm, а человек ждёт ответа: за пределами первых имён польза уже не
# окупает задержку.
LOOKUP_LIMIT = 3
BIO_LIMIT = 400


def lastfm_facts(items: list[str]) -> list[dict]:
    """Настоящие сведения об артистах из Last.fm — теги, похожие, справка.

    Ради этого источника снято ограничение по артистам и жанрам. Курируемая
    база покрывает только тёмный звук, и раньше на всём остальном бот отвечал
    «такого нет». Теперь на всё, чего нет в базе, факты берутся здесь — они
    настоящие, а не придуманные моделью, и это принципиально: правило «ничего
    не выдумывать» осталось прежним, просто источников стало два.

    Молчит при любой ошибке: без ключа или без сети разбор всё ещё возможен
    по курируемой базе, и ронять его из-за необязательного источника незачем.
    """
    facts: list[dict] = []
    for name in items[:LOOKUP_LIMIT]:
        try:
            resolved = _resolve(name)
            if not resolved:
                continue  # такого не знает даже Last.fm — выдумывать не станем
            tags = lastfm.artist_tags(resolved, limit=6)
            similar = lastfm.similar_artists(resolved, limit=6)
            bio = lastfm.artist_bio(resolved)
        except Exception as exc:  # noqa: BLE001 — источник необязательный
            log.info("Last.fm молчит про «%s»: %s", name, exc)
            continue

        if not (tags or similar):
            continue

        facts.append(
            {
                "artist": resolved,
                # Как человек написал имя — если иначе, модель мягко поправит.
                "asked_as": name if resolved.casefold() != name.casefold() else "",
                "tags": tags,
                "similar": [s["name"] for s in similar],
                "bio": stories.strip_html(bio)[:BIO_LIMIT],
            }
        )
    return facts


# Ниже этого числа слушателей совпадение считаем случайным. Поиск Last.fm
# охотно отдаёт пустышки с похожим написанием: на «black kart» — безвестного
# «Black Cart» вместо Black Kray, на набор букв — такой же набор букв.
MIN_LISTENERS = 5000


def _resolve(name: str) -> str:
    """Приводит имя к тому, как оно записано на самом деле.

    Боту пишут на слух: «Chef Keef» вместо Chief Keef, «black kart» вместо
    Black Kray. Раньше такой запрос упирался в «не знаю такого» — а человек
    видел в этом сломанный бот, а не свою опечатку.

    Из кандидатов берём самого слушаемого, а не самого похожего по буквам:
    когда человек ошибается в имени, он почти всегда имеет в виду известного
    артиста, а не его безвестного тёзку.
    """
    if lastfm.artist_tags(name, limit=1):
        return name  # написано верно, искать нечего

    # Сначала магазин: у него нечёткое сравнение, и опечатку он переживает.
    # Поиск Last.fm тут бесполезен — он ищет по подстроке и на «Chef Keef»
    # отдаёт другие опечатки того же имени вместо самого артиста.
    try:
        guess = itunes.resolve_name(name)
    except Exception as exc:  # noqa: BLE001 — магазин мог не ответить
        log.info("iTunes не опознал «%s»: %s", name, exc)
        guess = ""

    if guess and lastfm.artist_tags(guess, limit=1):
        if guess.casefold() != name.casefold():
            log.info("Имя «%s» опознано как «%s»", name, guess)
        return guess

    # Магазин не помог — пробуем поиск Last.fm и берём самого слушаемого:
    # ошибаясь в имени, человек почти всегда имеет в виду известного артиста,
    # а не его безвестного тёзку.
    candidates = [c for c in lastfm.search_artist(name) if c["listeners"] >= MIN_LISTENERS]
    if not candidates:
        return ""

    best = max(candidates, key=lambda c: c["listeners"])
    log.info("Имя «%s» опознано как «%s» (%d слушателей)", name, best["name"], best["listeners"])
    return best["name"]


# ─────────────────────────── лимиты ───────────────────────────


def _today() -> str:
    return state.now().strftime("%Y-%m-%d")


def count_source(label: str) -> None:
    data = state.read_json(SOURCES_FILE, {})
    day = data.setdefault(_today(), {})
    day[label] = day.get(label, 0) + 1
    state.write_json(SOURCES_FILE, data)


# Адрес из config, а не секрет канала: в секрете может стоять числовой id,
# и человек из ролика увидел бы «подпишись на -100…».
NOT_SUBSCRIBED = ("Всё в боте <b>бесплатно</b> — достаточно подписаться на "
                  f'<a href="https://t.me/{config.CHANNEL_HANDLE.lstrip("@")}">канал</a>.\n\n'
                  "Подпишись и пришли ещё раз.")


def _subscribed(chat_id: str, user_id: str, admin: bool) -> bool:
    """Подписан ли человек на канал; нет — говорит, что делать, и возвращает False.

    За подписку здесь всё: и разборы, и отбор, и слежение. Слежение до 17.09.2026
    проверку обходило, и пришедший из ролика за концертами подписчиком канала
    не становился — а бот и есть то, чем ролик приводит в канал (GROWTH.md).
    """
    channel = config.secret("TELEGRAM_CHANNEL_ID", required=False)
    if admin or not channel or telegram.is_member(channel, user_id):
        return True
    telegram.send_message(chat_id, NOT_SUBSCRIBED)
    return False


def user_key(user_id: str | int) -> str:
    """Отпечаток человека вместо его Telegram-id.

    Файл лимитов коммитится в репозиторий, а репозиторий открытый: список
    id тех, кто писал боту, — это список живых людей, и лежать в открытом
    виде он не должен. Солью служит токен бота: он есть в каждом запуске,
    но не в репозитории, поэтому отпечаток не перебирается по номерам.
    """
    salt = config.secret("TELEGRAM_BOT_TOKEN", required=False)
    return state.fingerprint(salt, str(user_id))


def load_state() -> dict:
    data = state.read_json(STATE_FILE, {"day": _today(), "total": 0, "users": {}})
    if data.get("day") != _today():
        # Новый день — общий счётчик обнуляется, история по людям остаётся.
        data["day"] = _today()
        data["total"] = 0
    return data


def save_state(data: dict) -> None:
    """Лимиты переживают запуск только записью на диск: GitHub Actions поднимает
    чистую машину каждые пять минут, состояние живёт в репозитории."""
    state.write_json(STATE_FILE, data)


def check_limit(data: dict, user_id: str, *, admin: bool) -> str:
    """Пусто — разбор разрешён. Иначе строка с объяснением для человека."""
    if admin:
        return ""
    if data.get("total", 0) >= config.SERVICE_DAILY_TOTAL:
        return (
            "На сегодня плёнка закончилась — проявочная перегружена.\n\n"
            "Приходи завтра, лимит обнулится."
        )
    user = data.get("users", {}).get(user_id, {})
    if user.get("day") == _today() and user.get("count", 0) >= config.SERVICE_DAILY_USER:
        return (
            f"На сегодня хватит: {config.SERVICE_DAILY_USER} разбор в сутки на человека.\n\n"
            "Завтра приходи ещё."
        )
    return ""


def spend(data: dict, user_id: str) -> None:
    users = data.setdefault("users", {})
    user = users.setdefault(user_id, {"day": "", "count": 0, "total": 0})
    if user.get("day") != _today():
        user["day"] = _today()
        user["count"] = 0
    user["count"] += 1
    user["total"] = user.get("total", 0) + 1
    data["total"] = data.get("total", 0) + 1


# ─────────────────────────── разборы ───────────────────────────

MAX_ARTISTS = 12
MAX_LYRICS = 1200
MAX_QUERY = 120

NO_BASE = (
    "Такой связи в базе канала пока нет.\n\n"
    "Врать не буду — придуманная родословная хуже молчания. "
    "Запрос записал, если связь подтвердится, разберём в канале."
)


def analyse(kind: str, body: str) -> tuple[str, Path | None]:
    """Готовит разбор. Возвращает (текст ответа, карточка или None).

    Вход всего один: строки песни разбираются отдельно, всё остальное —
    артист, жанр, песня или список — идёт в общий разбор. Человеку не нужно
    выбирать режим, а нам не нужно объяснять разницу между ними.
    """
    if kind == "lyrics":
        return _lyrics(body)
    if kind == "recommend":
        return _recommend(body)
    if kind == "new":
        return _whats_new(body)
    return _taste(body)


def _generate(kind: str, payload: dict) -> dict:
    """Генерация с той же отбраковкой, что и у постов канала: модель одинаково
    охотно сползает в реферат и здесь, а человеку уходит один-единственный ответ."""
    result = llm.generate_service(kind, payload)
    if result["skip"] or not result["text"]:
        return result
    issues = quality.problems(result["text"], kind)
    if issues:
        log.info("Разбор «%s» забракован: %s — пробую ещё раз", kind, "; ".join(issues))
        result = llm.generate_service(kind, payload)
        if not result["skip"] and quality.problems(result["text"], kind):
            return {"skip": True, "text": "", "reason": "брак после двух попыток"}
    return result


def _taste(body: str) -> tuple[str, Path | None]:
    """Разбор присланного: одно имя, жанр, песня или целый список.

    Порога в три артиста больше нет. Он выглядел безобидно, но заставлял
    человека вспоминать и собирать список, прежде чем что-то получить, —
    а до этого места доходят единицы. Один вопрос должен работать сразу.
    """
    items = split_items(body)[:MAX_ARTISTS]
    if not items:
        return ("Напиши артиста, жанр или песню — разберу.", None)

    query = ", ".join(items)
    scene = known_artists(query)
    links = match_links(query, scene)

    # Курируемая база отвечает за тёмный звук и остаётся главной: связи в ней
    # проверены руками. Всё, чего в ней нет, добираем из Last.fm — иначе бот
    # знал бы полторы сцены и на остальное отвечал отказом.
    web = lastfm_facts(items) if len(links) < 2 else []

    if not links and not web:
        _remember(query, "taste", matched=False)
        return (_nothing_found(), None)

    # Список и одно имя разбираются по-разному: у списка ищем общий корень,
    # у одного имени — откуда оно само выросло.
    kind = "taste" if len(items) >= 3 else "roots"
    payload = (
        {
            "artists": items,
            "known": links,
            "web": web,
            "scene": scene_payload(scene),
            "unknown": [i for i in items if not any(_mentions(i, a["name"]) for a in scene)],
        }
        if kind == "taste"
        else {"query": query, "known": links, "web": web, "scene": scene_payload(scene)}
    )

    result = _generate(kind, payload)
    if result["skip"] or not result["text"]:
        _remember(query, kind, matched=False)
        return (NO_BASE, None)

    text = telegram.sanitize(result["text"])
    verdict = _verdict(text)
    # Портрет ищем только когда спрашивали про одного: под списком из пяти имён
    # фотография одного из них — обман, лучше обычная карточка.
    photo = _artist_photo(web[0]["artist"] if len(items) == 1 and web else "")
    path = card.save(
        verdict, items, name=f"card-{state.now().strftime('%H%M%S')}", photo_url=photo
    )
    _remember(query, kind, matched=True, verdict=verdict)
    return text, path


def _artist_photo(name: str) -> str:
    """Портрет артиста — только настоящий и только его.

    Портреты есть примерно у половины андеграунда: остальным Deezer отдаёт
    серый силуэт. В таком случае возвращаемся к фирменной карточке, и это
    осознанный выбор. Пробовали и обложки, и поиск по Википедии — первое
    подсовывает гостевые куплеты с чужим оформлением, второе на имени вроде
    «Bones» находит постороннюю группу. Чужое лицо под разбором — та же
    выдумка, что и выдуманный факт, только заметнее.
    """
    if not name:
        return ""
    try:
        return deezer.artist_picture(name)
    except Exception as exc:  # noqa: BLE001 — без портрета карточка всё равно выйдет
        log.info("Портрет «%s» не нашёлся: %s", name, exc)
        return ""


def _recommend(body: str) -> tuple[str, Path | None]:
    """Что послушать дальше. Кандидаты — только из реальных данных Last.fm.

    Своих имён модель не придумывает: список приходит из статистики
    прослушиваний, где людей, слушающих одно, связали с другим. Модель лишь
    объясняет, почему именно эти.
    """
    items = split_items(body)[:MAX_ARTISTS]
    if not items:
        return ("Напиши, от кого плясать, — верну, что послушать дальше.", None)

    seen = {i.casefold() for i in items}
    picks: list[dict] = []
    tags: list[str] = []

    for name in items[:LOOKUP_LIMIT]:
        try:
            tags.extend(lastfm.artist_tags(name, limit=4))
            for candidate in lastfm.similar_artists(name, limit=10):
                # Того, кого человек и так назвал, советовать обратно нельзя.
                if candidate["name"].casefold() in seen:
                    continue
                seen.add(candidate["name"].casefold())
                picks.append(candidate)
        except Exception as exc:  # noqa: BLE001 — источник необязательный
            log.info("Last.fm не дал похожих на «%s»: %s", name, exc)

    if not picks:
        _remember(", ".join(items), "recommend", matched=False)
        return (_nothing_found(), None)

    # Самые близкие подтверждают вкус, дальние его расширяют — нужны оба края,
    # иначе совет вырождается в «послушай то же самое ещё раз».
    picks.sort(key=lambda p: p["match"], reverse=True)
    chosen = picks[:4] + picks[len(picks) // 2 : len(picks) // 2 + 2]

    query = ", ".join(items)
    scene = known_artists(query)
    result = _generate(
        "recommend",
        {
            "from": items,
            "picks": chosen,
            "known": match_links(query, scene, limit=1),
            "tags": sorted(set(tags))[:6],
        },
    )
    if result["skip"] or not result["text"]:
        _remember(query, "recommend", matched=False)
        return (NO_BASE, None)

    _remember(query, "recommend", matched=True)
    return telegram.sanitize(result["text"]), None


def _whats_new(name: str) -> tuple[str, Path | None]:
    """Свежие релизы артиста. Модель не участвует вовсе.

    Это чистые факты из магазинов: даты, названия, ссылки. Пропускать их через
    генератор было бы и дороже, и хуже — пересказ портит то, что и так точно.
    """
    name = name.strip()[:MAX_QUERY]
    if not name:
        return ("Напиши артиста — покажу, что у него выходило.", None)

    releases: list[dict] = []
    try:
        artist_id = itunes.find_artist_id(name)
        if artist_id:
            releases = itunes.recent_releases(artist_id, limit=5)
    except Exception as exc:  # noqa: BLE001 — магазин мог не ответить
        log.info("iTunes молчит про «%s»: %s", name, exc)

    if not releases:
        try:
            artist_id = deezer.find_artist_id(name)
            if artist_id:
                releases = deezer.recent_releases(artist_id, limit=5)
        except Exception as exc:  # noqa: BLE001
            log.info("Deezer молчит про «%s»: %s", name, exc)

    if not releases:
        return (
            f"Про <b>{name}</b> магазины ничего свежего не отдают.\n\n"
            "Либо имя написано иначе, либо релизов давно не было.",
            None,
        )

    # Магазины отдают релизы в своём порядке, а человек ждёт свежее сверху.
    releases.sort(key=lambda r: (r.get("released_at") or ""), reverse=True)

    lines = [f"<b>{name}</b> — что выходило:\n"]
    for item in releases:
        title = item.get("title", "без названия")
        date = (item.get("released_at") or "")[:10]
        url = item.get("url", "")
        head = f'<a href="{url}">{title}</a>' if url else title
        tracks = item.get("track_count")
        detail = f" · {tracks} {_plural(tracks, 'трек', 'трека', 'треков')}" if tracks else ""
        lines.append(f"{date} — {head}{detail}")

    return ("\n".join(lines), None)


def _plural(count: int, one: str, few: str, many: str) -> str:
    """Русское склонение после числа: 1 трек, 2 трека, 5 треков."""
    tail_two, tail_one = count % 100, count % 10
    if 11 <= tail_two <= 14:
        return many
    if tail_one == 1:
        return one
    if 2 <= tail_one <= 4:
        return few
    return many


# ─────────────────────────── слежение за артистом ───────────────────────────

WATCH_FILE = config.WATCH_FILE
WATCH_LIMIT = 20
# Сколько дней релиз считается новым для вести по артисту вне списка сбора.
# Проход идёт каждые шесть часов; трое суток переживут и пару сорванных сборов,
# а подписавшемуся сегодня не придёт «вышло новое» про прошлый месяц.
WATCH_FRESH_DAYS = 3


def _entries(data: dict, chat_id: str) -> list[dict]:
    # Записи до 16.09.2026 — голые имена без id: по ним молчит только проход
    # по магазинам, находки сбора узнаются по имени, как раньше.
    names = data["watchers"].setdefault(str(chat_id), [])
    names[:] = [n if isinstance(n, dict) else {"name": n} for n in names]
    return names


def find_watch_artist(name: str) -> dict | None:
    """Артист для слежения: имя и id в магазинах, или None, если его там нет.

    Сначала data/artists.json — там id сверены руками, и такие релизы находит
    сбор. Иначе магазины, и только точное совпадение имени: по «Guf» Deezer
    первым отдаёт GUFI, и подписчик получал бы вести о чужом артисте.
    """
    folded = name.casefold()
    for artist in collect.load_artists():
        if artist.get("name", "").casefold() == folded:
            return {k: artist[k] for k in ("name", "itunes_id", "deezer_id") if artist.get(k)}
    found = {"name": name}
    try:
        found["itunes_id"] = itunes.find_artist_id(name, exact=True)
        found["deezer_id"] = deezer.find_artist_id(name)
    except Exception as exc:  # noqa: BLE001 — магазин не ответил, значит, не нашли
        log.info("Магазины молчат про «%s»: %s", name, exc)
    found = {k: v for k, v in found.items() if v}
    return found if len(found) > 1 else None


# Артиста и город бот спрашивает вопросом с ответом (telegram.send_message, ask):
# набрать «/slezhu Имя» человек из ролика не догадается. Ответ узнаётся по фразе
# в сообщении, на которое отвечают, — поэтому фразы стоят в каждом таком вопросе.
WATCH_MARK = "Пришли имя артиста ответом на это сообщение"
CITY_MARK = "Пришли город ответом на это сообщение"
WATCH_ASK = ("🔔 <b>СЛЕЖУ</b>\n\nЗа кем следить? " + WATCH_MARK + " — напишу, когда у него "
             "выйдет релиз или он объявит концерт в твоём городе.")
CITY_ASK = ("В каком ты городе? " + CITY_MARK + " — напишу, когда кто-то из твоего списка "
            "объявит там концерт.")


def watch_buttons() -> list[list[dict]]:
    return [[{"text": "➕ Ещё артист", "callback_data": _cb("slezhu")},
             {"text": "📋 Мой список", "callback_data": _cb("mylist")}]]


def ask_artist(chat_id: str) -> None:
    telegram.send_message(chat_id, WATCH_ASK, ask="Имя артиста")


def watch_reply(chat_id: str, artist: str) -> None:
    """Подписка из любого входа — команда, кнопка под разбором, ответ на вопрос.
    Не нашёл — переспрашивает; нашёл и город не известен — спрашивает город."""
    answer = watch_add(chat_id, artist)
    if WATCH_MARK in answer:
        telegram.send_message(chat_id, answer, ask="Имя артиста")
        return
    telegram.send_message(chat_id, answer, buttons=watch_buttons())
    data = state.read_json(WATCH_FILE, {"watchers": {}})
    if str(chat_id) not in data.get("cities", {}) and any(
            isinstance(n, dict) and n.get("afisha") for n in data["watchers"].get(str(chat_id), [])):
        telegram.send_message(chat_id, CITY_ASK, ask="Город")


def watch_add(chat_id: str, artist: str) -> str:
    """Подписывает на артиста. Возвращает ответ для человека.

    Адрес переписки хранится как есть — но в приватном хранилище, отдельном
    от кода. Прятать его шифром в открытом файле было бы самообманом: чтобы
    прислать весть о релизе, адрес всё равно нужно восстановить, а значит,
    ключ лежит рядом с замком.

    Артист без id в магазинах в список не попадает. До 16.09.2026 бот обещал
    «выйдет релиз — напишу» любому имени, а вести шли только по 156 артистам
    сбора: подписка на остальных не срабатывала никогда.
    """
    artist = artist.strip()[:MAX_QUERY]
    data = state.read_json(WATCH_FILE, {"watchers": {}})
    names = _entries(data, chat_id)

    if any(n["name"].casefold() == artist.casefold() for n in names):
        return f"За <b>{artist}</b> уже слежу. Выйдет что-нибудь — напишу."
    if len(names) >= WATCH_LIMIT:
        return (
            f"Больше {WATCH_LIMIT} артистов не потяну — это уже не слежение, "
            "а лента новостей.\n\nОтписаться — в «Мой список»."
        )

    found = find_watch_artist(artist)
    if not found:
        # Подсказка — нечёткий поиск iTunes: «ASAP rocky» он переводит в «A$AP Rocky».
        # Подписывать по ней сразу нельзя: угадал он или нет, проверит только человек.
        hint = itunes.resolve_name(artist)
        tail = (f"\n\nМожет, <b>{hint}</b>? {WATCH_MARK}."
                if hint and hint.casefold() != artist.casefold() else
                f"\n\nПроверь, как пишется имя. {WATCH_MARK}.")
        return f"В магазинах <b>{artist}</b> не нашёл — следить не за чем.{tail}"

    page = afisha.find_artist(found["name"])
    if page:
        found["afisha"] = page
    names.append(found)
    state.write_json(WATCH_FILE, data)
    city = data.get("cities", {}).get(str(chat_id))
    concerts = (f"Объявит концерт в городе {city} — тоже напишу." if city and page else
                "" if page else
                "В Яндекс Афише его нет — о концертах не узнаю.")
    return (
        f"Слежу за <b>{found['name']}</b>. Выйдет релиз — напишу. {concerts}\n\n"
        f"Сейчас в списке: {len(names)}."
    )


def unwatch_button(name: str) -> list[list[dict]]:
    return [[{"text": f"🔕 Не следить за {name}", "callback_data": _cb("unwatch", name)}]]


def watch_remove(chat_id: str, subject: str) -> str:
    """Снимает одного артиста. subject — имя из кнопки, обрезанное до 64 байт
    callback_data, поэтому сверяется так же обрезанным."""
    data = state.read_json(WATCH_FILE, {"watchers": {}})
    names = _entries(data, chat_id)
    key = _cb("unwatch", subject)
    left = [n for n in names if _cb("unwatch", n["name"]) != key]
    if len(left) == len(names):
        return "Уже не слежу."
    if left:
        data["watchers"][str(chat_id)] = left
    else:
        data["watchers"].pop(str(chat_id))
    state.write_json(WATCH_FILE, data)
    gone = next(n["name"] for n in names if n not in left)
    return f"Больше не слежу за <b>{gone}</b>. В списке: {len(left)}."


def watch_clear(chat_id: str) -> str:
    data = state.read_json(WATCH_FILE, {"watchers": {}})
    # Город без артистов ни к чему, а стереть «всё» значит всё.
    city = data.get("cities", {}).pop(str(chat_id), None)
    if data["watchers"].pop(str(chat_id), None) is None and city is None:
        return "Список и так пуст."
    state.write_json(WATCH_FILE, data)
    return "Больше ни за кем не слежу."


def watch_list(chat_id: str) -> None:
    """Список с кнопкой отписки под каждым артистом: набирать имя, чтобы
    отписаться, никто не станет, а /stop стирает всё разом. Пустой — сразу вопрос."""
    data = state.read_json(WATCH_FILE, {"watchers": {}})
    names = _entries(data, chat_id) if str(chat_id) in data["watchers"] else []
    if not names:
        ask_artist(chat_id)
        return
    city = data.get("cities", {}).get(str(chat_id))
    text = ("Слежу за:\n" + "\n".join(f"· {n['name']}" for n in names)
            + (f"\n\nГород — <b>{city}</b>. Сменить — /gorod." if city else "")
            + "\n\nОтписаться — кнопкой ниже, очистить всё — /stop.")
    buttons = [row for n in names for row in unwatch_button(n["name"])]
    telegram.send_message(chat_id, text, buttons=buttons + [watch_buttons()[0][:1]])


def watched_releases(watchers: dict) -> list[dict]:
    """Свежие релизы артистов, которых нет в списке сбора, — прямо из магазинов.

    Сбор смотрит только data/artists.json, и подписка на остальных молчала.
    Проход здесь, в рассылке, а не в collect намеренно: всё, что лежит в inbox,
    читают compose --fresh и urgent, и чужой любимец подписчика стал бы постом
    канала. Эти находки живут только в памяти одного запуска, а помнятся
    отметками в приватном списке слежения — в открытом репозитории их нет вовсе.
    Имя и id берутся из подписки (watch_add), поэтому проход — два запроса
    на артиста, без поиска.
    """
    covered = {a["name"].casefold() for a in collect.load_artists() if a.get("tier") != "ru_pop"}
    wanted: dict[str, dict] = {}
    for names in watchers.values():
        for n in names:
            if isinstance(n, dict) and n["name"].casefold() not in covered:
                wanted.setdefault(n["name"].casefold(), n)

    now = state.now()
    cutoff = now - timedelta(days=WATCH_FRESH_DAYS)
    found: list[dict] = []
    for artist in wanted.values():
        raw: list[dict] = []
        try:
            if artist.get("itunes_id"):
                raw += itunes.recent_releases(artist["itunes_id"])
            if artist.get("deezer_id"):
                raw += deezer.recent_releases(artist["deezer_id"])
        except Exception as exc:  # noqa: BLE001 — магазин отвалился, сверим в следующий раз
            log.info("%s: релизы не получены (%s)", artist["name"], exc)
            continue
        for item in raw:
            released = collect._parse(item.get("released_at"))
            # Предзаказ магазин отдаёт за недели до выхода, а весть скажет «вышло».
            if released is None or not cutoff <= released <= now:
                continue
            credit, credit_ids = collect.store_credit(item)
            # Фит у чужого артиста — не его релиз (collect.own_release).
            if not credit or not collect.own_release(
                    artist["name"], artist.get(f"{item.get('source')}_id"), credit, credit_ids):
                continue
            found.append({**item, "kind": "release", "artist": credit, "tracked": artist["name"]})
    return found


def notify_releases() -> int:
    """Рассылает вести о новых релизах тем, кто на них подписан.

    Сборщик новинок уже наполняет inbox каждые шесть часов — здесь мы
    сверяем свежие находки со списками слежения, а артистов вне списка сбора
    смотрим в магазинах сами (watched_releases). Отправленное помечаем, чтобы
    одна и та же новость не пришла человеку дважды.
    """
    data = state.read_json(WATCH_FILE, {"watchers": {}, "sent": []})
    watchers = data.get("watchers", {})
    if not watchers:
        return 0

    sent = set(data.get("sent", []))
    releases = [
        item
        for item in state.read_jsonl(config.INBOX_FILE)
        # Релиз без tracked собран до сверки с магазином и подписан тем,
        # по кому нашёлся: там чужие фиты и сольники участников под именем
        # группы. Весть «у X вышло новое» по таким не шлём.
        if (item.get("kind") == "video" or item.get("tracked")) and item.get("artist")
    ] + watched_releases(watchers)
    if not releases:
        return 0

    # Один релиз приходит из двух магазинов разными отпечатками («Arsenal»
    # у Deezer и «Arsenal - Single» у iTunes), и подписчик получал две вести.
    # Помечаем его ключом, которым дубли схлопывает compose.
    from .compose import release_key

    def mark_of(chat_id: str, item: dict) -> str:
        return f"{chat_id}:{':'.join(release_key(item))}"

    delivered = 0
    for chat_id, names in watchers.items():
        wanted = {n["name"].casefold(): n["name"] for n in _entries(data, chat_id)}
        # Отметки, записанные до 12.09.2026, стоят по отпечатку. Переносим их
        # на ключ, иначе смена ключа разослала бы весь inbox заново.
        for item in releases:
            if f"{chat_id}:{item.get('fingerprint', '')}" in sent:
                sent.add(mark_of(chat_id, item))

        for item in releases:
            # Подпись совместного релиза полная («HNTR & Juicy J»), а следят
            # за одним именем — поэтому сверяем с тем, по кому релиз нашёлся.
            watched = wanted.get((item.get("tracked") or item["artist"]).casefold())
            if mark_of(chat_id, item) in sent or not watched:
                continue

            title = item.get("title", "")
            url = item.get("url", "")
            head = f'<a href="{url}">{title}</a>' if url else title
            caption = f"🔔 У <b>{item['artist']}</b> вышло новое: {head}"
            # Отписка — там, где о ней вспоминают: под самой вестью.
            buttons = unwatch_button(watched)

            # Отрывок важнее текста: про релиз можно рассказать, а можно дать
            # услышать. Тридцать секунд магазин отдаёт всем для прослушивания.
            snippet = _preview(url)
            try:
                if snippet:
                    telegram.send_audio(
                        chat_id,
                        snippet["preview"],
                        caption,
                        title=snippet["title"],
                        performer=item["artist"],
                        cover_url=item.get("cover", ""),
                        buttons=buttons,
                    )
                else:
                    telegram.send_message(chat_id, caption, preview=bool(url), buttons=buttons)
            except telegram.TelegramError as exc:
                log.info("Не доставлено про %s: %s", item["artist"], exc)
                continue

            sent.add(mark_of(chat_id, item))
            delivered += 1

    if delivered:
        # Список отправленного подрезаем: он нужен только чтобы не повториться.
        data["sent"] = sorted(sent)[-2000:]
        state.write_json(WATCH_FILE, data)
    return delivered


# ─────────────────────────── концерты в городе ───────────────────────────

# Как город пишут люди → как его пишет Афиша. Остальные сверяются без регистра,
# пробелов и дефисов (afisha.same_name), так что «нижний новгород» сойдётся и так.
CITY_ALIASES = {
    "питер": "Санкт-Петербург", "спб": "Санкт-Петербург", "петербург": "Санкт-Петербург",
    "санкт петербург": "Санкт-Петербург", "ленинград": "Санкт-Петербург",
    "мск": "Москва", "екб": "Екатеринбург", "екат": "Екатеринбург",
    "нск": "Новосибирск", "новосиб": "Новосибирск", "крд": "Краснодар",
    "нижний": "Нижний Новгород", "нн": "Нижний Новгород",
    "ростов": "Ростов-на-Дону", "ростов на дону": "Ростов-на-Дону",
}


def normalize_city(text: str) -> str:
    text = re.sub(r"^г\.?\s+", "", text.strip(" .,!"), flags=re.IGNORECASE)
    key = re.sub(r"[\s-]+", " ", text.casefold().replace("ё", "е"))
    return CITY_ALIASES.get(key) or " ".join(w[:1].upper() + w[1:] for w in text.split())


def city_set(chat_id: str, text: str) -> str:
    """/gorod Город. Город лежит в приватном списке слежения рядом с артистами."""
    data = state.read_json(WATCH_FILE, {"watchers": {}})
    cities = data.setdefault("cities", {})
    names = data["watchers"].get(str(chat_id), [])
    if not text.strip():
        city = cities.get(str(chat_id))
        return (f"Сейчас город — <b>{city}</b>. " if city else "") + CITY_ASK
    city = normalize_city(text[:MAX_QUERY])
    cities[str(chat_id)] = city
    state.write_json(WATCH_FILE, data)
    if not names:
        return (f"Город — <b>{city}</b>. Теперь добавь артистов — кнопкой ниже: "
                "напишу, когда кто-то из них объявит здесь концерт.")
    # Адрес в Афише ищется при подписке; у старых подписок его нет до первого прохода.
    missing = [n["name"] for n in _entries(data, chat_id) if isinstance(n, dict) and not n.get("afisha")]
    tail = f"\n\nВ Яндекс Афише пока не нашёл: {', '.join(missing)}." if missing else ""
    return (f"Город — <b>{city}</b>. Объявит кто-то из твоего списка концерт здесь — напишу. "
            f"Концерты смотрю в Яндекс Афише раз в день.{tail}")


def notify_concerts(dry_run: bool = False) -> int:
    """Вести о концертах в городе подписчика — раз в день, одна на концерт.

    Проход здесь же, после рассылки релизов: там уже подключено приватное
    хранилище, а город и артисты человека живут только в нём. Одна страница
    Афиши на артиста, сколько бы человек за ним ни следило. Концерт помечается
    ссылкой и днём: у тура в одном городе ссылка бывает общей на все даты.
    """
    data = state.read_json(WATCH_FILE, {"watchers": {}, "sent": []})
    today = _today()
    cities = data.get("cities", {})
    if data.get("concerts_day") == today and not dry_run:
        return 0
    wanted = {chat: _entries(data, chat) for chat in cities if data["watchers"].get(chat)}

    pages: dict[str, str | None] = {}
    schedule: dict[str, list[dict]] = {}
    for entries in wanted.values():
        for n in entries:
            key = n["name"].casefold()
            if key not in pages:
                pages[key] = n.get("afisha") or afisha.find_artist(n["name"])
                schedule[key] = afisha.concerts(pages[key]) if pages[key] else []
            if pages[key]:
                n["afisha"] = pages[key]

    sent = set(data.get("sent", []))
    delivered = 0
    for chat_id, entries in wanted.items():
        for n in entries:
            for concert in schedule[n["name"].casefold()]:
                mark = f"{chat_id}:concert:{concert['url']}:{concert['day']}"
                if mark in sent or not afisha.same_name(concert["city"], cities[chat_id]):
                    continue
                place = f", {concert['place']}" if concert["place"] else ""
                # Только то, что сказала Афиша, и ссылка на неё: билеты и подробности там.
                text = (f"🎫 <b>{n['name']}</b>: {concert['city']}{place} — {concert['when']}.\n\n"
                        f'<a href="{concert["url"]}">Билеты и подробности — Яндекс Афиша</a>')
                if dry_run:
                    print(f"  → {chat_id}: {text}")
                    delivered += 1
                    continue
                try:
                    telegram.send_message(chat_id, text, buttons=unwatch_button(n["name"]))
                except telegram.TelegramError as exc:
                    log.info("Не доставлено про концерт %s: %s", n["name"], exc)
                    continue
                sent.add(mark)
                delivered += 1

    if not dry_run:
        data["sent"] = sorted(sent)[-2000:]
        data["concerts_day"] = today
        state.write_json(WATCH_FILE, data)
    return delivered


def _preview(album_url: str) -> dict | None:
    """Первый трек релиза с отрывком для прослушивания.

    Молчит при любой заминке: весть о релизе важнее музыки к ней, и терять
    её из-за недоступного магазина незачем.
    """
    if not album_url or "music.apple.com" not in album_url:
        return None
    try:
        album_id = itunes.album_id_from_url(album_url)
        if not album_id:
            return None
        for track in itunes.album_tracks(album_id).get("tracks", []):
            if track.get("preview"):
                return track
    except Exception as exc:  # noqa: BLE001 — источник необязательный
        log.info("Отрывок не достался: %s", exc)
    return None


def _nothing_found() -> str:
    """Отказ должен помогать, а не закрывать дверь.

    Сухое «нет в базе» человек читает как «бот сломан». Поэтому даём пару
    имён, с которыми точно сработает.
    """
    artists = state.read_json(config.ARTISTS_FILE, {"artists": []})["artists"]
    core = [a["name"] for a in artists if a.get("tier") == "core"][:4]
    examples = ", ".join(core) if core else "Three 6 Mafia, Bones"
    return (
        "Такого в базе канала пока нет.\n\n"
        f"Попробуй так: <i>{examples}</i>\n\n"
        "Запрос я записал — если связь подтвердится, разберём в канале."
    )


def _lyrics(body: str) -> tuple[str, Path | None]:
    lines = [line.strip() for line in body.splitlines() if line.strip()][:24]
    text_len = sum(len(line) for line in lines)
    if len(lines) < 2 or text_len < 30:
        return ("Пришли хотя бы пару строк — по одной разбирать нечего.", None)
    if text_len > MAX_LYRICS:
        return ("Это уже целый альбом. Пришли куплет, а не всё сразу.", None)

    # Автора берём только если человек назвал его сам: угадывать нельзя,
    # иначе разбор начнётся с выдуманного имени.
    scene = known_artists(body)
    result = _generate(
        "lyrics",
        {
            "lines": lines,
            "artist": scene[0]["name"] if scene else "",
            "scene": scene_payload(scene[:1]),
        },
    )
    if result["skip"] or not result["text"]:
        return ("Тут не за что зацепиться — пришли кусок, где что-то происходит.", None)

    # Сами строки в журнал не кладём: репозиторий открытый, а человек мог
    # прислать своё неизданное. Для статистики хватает факта разбора.
    _remember("", "lyrics", matched=True)
    return telegram.sanitize(result["text"]), None


def _verdict(text: str) -> str:
    """Первая строка разбора — она же приговор на карточке.

    Именно строка, а не первое предложение: крючок модель обычно ставит
    заголовком и точку в конце не ставит, а без неё поиск по предложениям
    утаскивает на карточку весь первый абзац.
    """
    clean = stories.strip_html(text)
    first = next((line.strip() for line in clean.splitlines() if line.strip()), "")
    if len(first) > 110:
        first = stories.first_sentence(first, limit=110)
    return first.rstrip(" .")


def _remember(query: str, kind: str, *, matched: bool, verdict: str = "") -> None:
    """Пишет запрос в журнал. Имён и ников не храним — только сам запрос."""
    row = {"at": state.iso(), "kind": kind, "query": query[:200], "matched": matched}
    if verdict:
        row["verdict"] = verdict
    state.append_jsonl(LOG_FILE, [row])
    if not matched:
        state.append_jsonl(REQUESTS_FILE, [row])


# ─────────────────────────── приём сообщений ───────────────────────────


# Последний /start по чату: (текст, время). Повтор в пределах START_REPEAT секунд — дубль.
_STARTS: dict[str, tuple[str, int]] = {}
START_REPEAT = 30


def handle_message(message: dict, data: dict) -> bool:
    """Обрабатывает одно сообщение. True — разбор был выдан (потрачен токен).

    Состояние лимитов передаётся снаружи: за один запуск поллера сообщений
    может прийти несколько, и общий счётчик должен быть у них один.
    """
    chat = message.get("chat", {})
    if chat.get("type") != "private":
        return False  # в канале и группах сервис не работает

    text = (message.get("text") or "").strip()
    if not text:
        return False

    chat_id = str(chat.get("id", ""))
    user_id = str(message.get("from", {}).get("id", ""))
    admin = user_id == str(config.secret("TELEGRAM_ADMIN_ID", required=False))
    # Дальше человек живёт под отпечатком: в файл лимитов его id не попадает.
    key = user_key(user_id)

    # Приложение Telegram порой шлёт /start дважды подряд — в чате два /start
    # и два приветствия (владелец, 16.09.2026). Повтор удаляем и не отвечаем.
    # ponytail: память одной смены; повтор ровно на стыке смен пройдёт.
    if text.startswith("/start"):
        previous = _STARTS.get(chat_id)
        _STARTS[chat_id] = (text, message.get("date", 0))
        if previous and previous[0] == text and message.get("date", 0) - previous[1] <= START_REPEAT:
            try:
                telegram.delete_message(chat_id, message["message_id"])
            except telegram.TelegramError as exc:
                log.info("Повтор /start не удалён: %s", exc)
            return False

    # Ответ на вопрос слежения — намерение явное, заявку отбора он закрывает.
    asked = (message.get("reply_to_message") or {}).get("text", "")
    if not text.startswith("/") and (WATCH_MARK in asked or CITY_MARK in asked):
        otbor.cancel(chat_id)
        if not _subscribed(chat_id, user_id, admin):
            return False
        if WATCH_MARK in asked:
            watch_reply(chat_id, text)
        else:
            telegram.send_message(chat_id, city_set(chat_id, text), buttons=watch_buttons())
        return False

    kind, body = parse_command(text)
    # Отбор ведёт разговор в несколько сообщений (src/otbor.py): пока заявка
    # открыта, всё присланное идёт туда. Другая команда заявку закрывает —
    # человек передумал и ушёл в разборы, а не прислал трек.
    if kind == "otbor" or text.casefold() in ("отбор", "otbor"):
        otbor.start(chat_id, user_id, admin=admin)
        return False
    if otbor.active(chat_id):
        if not text.startswith("/"):
            otbor.handle(message, admin=admin)
            return False
        otbor.cancel(chat_id)
    if kind == "menu" and (body == "gorod" or body.startswith("gorod_")):
        # Из ролика о гастролёре: артист зашит в ссылку (?start=gorod_basta — адрес
        # как в Афише), человеку остаётся написать город. Без артиста — обычный вопрос.
        count_source("gorod")
        if not _subscribed(chat_id, user_id, admin):
            return False
        name = next((a["name"] for a in collect.load_artists() if afisha.slug(a["name"]) == body[len("gorod_"):]), "")
        if name:
            watch_reply(chat_id, name)
        else:
            ask_artist(chat_id)
        return False
    if kind == "menu" and body in SOURCES:
        # Из ролика и чатов зовут прислать трек — меню между ссылкой и заявкой лишнее.
        count_source(body)
        otbor.start(chat_id, user_id, admin=admin)
        return False
    if kind == "proyavka" and body:
        kind, text = "", body
    if kind == "proyavka" or kind == "menu" and body in PROYAVKA_KEYS:
        # Пришёл за разбором — сразу объясняем, что слать: лишний экран между
        # кнопкой и делом только мешает.
        telegram.send_message(chat_id, PROYAVKA)
        return False
    if kind == "menu" and body == "slezhu":
        if _subscribed(chat_id, user_id, admin):
            ask_artist(chat_id)
        return False
    if kind == "menu":
        telegram.send_message(chat_id, MENU, buttons=menu_buttons())
        return False

    # Списками слежения человек распоряжается сам, и это не стоит ни токенов,
    # ни лимита — поэтому разбирается до всех проверок, кроме подписки.
    if kind == "watchlist" and body:
        if _subscribed(chat_id, user_id, admin):
            watch_reply(chat_id, body)
        return False
    if kind == "watchlist":
        watch_list(chat_id)
        return False
    if kind == "watchstop":
        telegram.send_message(chat_id, watch_clear(chat_id))
        return False
    if kind == "city":
        if not _subscribed(chat_id, user_id, admin):
            return False
        answer = city_set(chat_id, body)
        if CITY_MARK in answer:
            telegram.send_message(chat_id, answer, ask="Город")
        else:
            telegram.send_message(chat_id, answer, buttons=watch_buttons())
        return False
    if not kind:
        # Ссылку на трек и «Артист — Трек» разбор понимает тем же поиском, что отбор:
        # в разбор уходит имя артиста. Человеку не надо знать, в каком виде что слать.
        body = otbor.subject(text)
        if not body:
            telegram.send_message(chat_id, "Эту ссылку не разобрал — напиши артиста или <i>Артист — Трек</i>.")
            return False
        kind = guess_kind(body)
    if not kind:
        telegram.send_message(chat_id, MENU, buttons=menu_buttons())
        return False

    if not _subscribed(chat_id, user_id, admin):
        return False

    # Лимит тратят только те ответы, что идут через модель. «Что нового» —
    # выборка из магазина, брать за неё суточную квоту было бы враньём.
    if COSTS_TOKENS.get(kind, True):
        denied = check_limit(data, key, admin=admin)
        if denied:
            telegram.send_message(chat_id, denied)
            return False

    telegram.send_chat_action(chat_id)
    try:
        answer, image = analyse(kind, body)
    except Exception as exc:  # noqa: BLE001 — один сбойный запрос не должен ронять запуск
        log.error("Разбор «%s» сорвался: %s", kind, exc)
        telegram.send_message(chat_id, "Плёнку зажевало. Попробуй ещё раз.")
        return False

    return _deliver(chat_id, answer, image, subject=_subject(kind, body)) and _spend_if_costly(
        data, key, kind
    )


# Что из ответов проходит через модель. Остальное — выборка из магазина
# или работа со списком слежения: они бесплатны и лимит не трогают.
COSTS_TOKENS = {"new": False, "watchlist": False, "watchstop": False, "watch": False, "city": False}


def _subject(kind: str, body: str) -> str:
    """Про кого был разбор — уходит в кнопки продолжения.

    Только для одного имени: под разбором списка кнопка «следить» бессмысленна,
    непонятно, за кем именно.
    """
    if kind in ("lyrics", "new", "recommend"):
        return ""
    items = split_items(body)
    if len(items) != 1:
        return ""
    # Двадцать знаков, а не сорок: кириллица весит по два байта, и длинное имя
    # обрезалось бы прямо в callback_data — а потом не совпало бы с лентой релизов.
    return items[0][:20]


def _deliver(chat_id: str, answer: str, image: Path | None, *, subject: str = "") -> bool:
    buttons = again_buttons(subject)
    if image is not None:
        # Подпись к фото у Telegram короче обычного сообщения. Разбор длиннее
        # лимита не режем — карточка уходит молча, а текст следом отдельно.
        if len(answer) <= telegram.MAX_CAPTION:
            telegram.send_photo_file(chat_id, image, answer)
            telegram.send_message(chat_id, WHAT_NEXT, buttons=buttons)
        else:
            telegram.send_photo_file(chat_id, image, "")
            telegram.send_message(chat_id, answer, buttons=buttons)
        image.unlink(missing_ok=True)  # карточка уже у человека, в репозитории не нужна
    else:
        telegram.send_message(chat_id, answer, buttons=buttons)
    return True


def _spend_if_costly(data: dict, key: str, kind: str) -> bool:
    if not COSTS_TOKENS.get(kind, True):
        return False
    spend(data, key)
    return True


# Строка под карточкой: кнопки к фото прицепить можно, но тогда подпись
# и кнопка живут в одном сообщении и пересылаются вместе — а карточку
# пересылают именно без служебных кнопок.
WHAT_NEXT = "Забирай карточку. Разберём что-нибудь ещё?"


def handle_callback(query: dict, data: dict) -> None:
    """Нажатие кнопки сервиса.

    Кнопки бывают двух родов. Одни только объясняют, что прислать, — тогда
    разбор идёт следующим сообщением, и человек видит пример до того, как
    потратит суточный лимит. Другие продолжают уже состоявшийся разговор:
    под ответом про артиста стоят «что послушать», «что нового» и «следить»,
    и они делают дело сразу — имя уже известно, переспрашивать нечего.
    """
    raw = query.get("data", "")[len(CALLBACK_PREFIX):]
    action, _, subject = raw.partition(":")
    chat_id = str(query.get("message", {}).get("chat", {}).get("id", ""))
    user_id = str(query.get("from", {}).get("id", ""))
    key = user_key(user_id)

    telegram.answer_callback(query.get("id", ""))
    if not chat_id:
        return

    if action in PROYAVKA_KEYS:
        telegram.send_message(chat_id, PROYAVKA)
        return

    if action == "otbor":
        admin = user_id == str(config.secret("TELEGRAM_ADMIN_ID", required=False))
        otbor.callback(chat_id, user_id, subject, admin=admin)
        return

    if action == "watch" and subject:
        watch_reply(chat_id, subject)
        return

    if action == "slezhu":
        otbor.cancel(chat_id)
        admin = user_id == str(config.secret("TELEGRAM_ADMIN_ID", required=False))
        if _subscribed(chat_id, user_id, admin):
            ask_artist(chat_id)
        return

    if action == "mylist":
        watch_list(chat_id)
        return

    if action == "unwatch" and subject:
        telegram.send_message(chat_id, watch_remove(chat_id, subject))
        return

    if action in ("rec", "new") and subject:
        admin = user_id == str(config.secret("TELEGRAM_ADMIN_ID", required=False))
        kind = "recommend" if action == "rec" else "new"

        if COSTS_TOKENS.get(kind, True):
            denied = check_limit(data, key, admin=admin)
            if denied:
                telegram.send_message(chat_id, denied)
                return

        telegram.send_chat_action(chat_id)
        try:
            answer, image = analyse(kind, subject)
        except Exception as exc:  # noqa: BLE001 — чужое нажатие не роняет запуск
            log.error("Кнопка «%s» сорвалась: %s", action, exc)
            telegram.send_message(chat_id, "Плёнку зажевало. Попробуй ещё раз.")
            return

        _deliver(chat_id, answer, image)
        _spend_if_costly(data, key, kind)
        return

    telegram.send_message(chat_id, MENU, buttons=menu_buttons())


def _selftest() -> None:
    """Весть о релизе уходит подписчику один раз, даже если магазинов два.

    Запуск: python -m src.service --selftest
    """
    import contextlib
    import datetime
    import io
    import tempfile

    sent_to: list[str] = []
    real = (telegram.send_message, telegram.send_audio, _preview, state.read_jsonl,
            globals()["WATCH_FILE"])
    telegram.send_message = lambda chat, text, **_: sent_to.append(text) or {"message_id": 1}
    telegram.send_audio = lambda chat, audio, caption, **_: sent_to.append(caption) or {"message_id": 1}
    globals()["_preview"] = lambda url: None  # отрывок из магазина не качаем

    def release(fingerprint: str, title: str, source: str) -> dict:
        return {"kind": "release", "fingerprint": fingerprint, "artist": "Slipknot",
                "tracked": "Slipknot", "title": title, "source": source, "url": ""}

    # Тот же релиз двумя магазинами: отпечатки разные, ключ compose один.
    state.read_jsonl = lambda path: [release("aaa", "Arsenal - Single", "itunes"),
                                     release("bbb", "Arsenal", "deezer")]
    tmp = tempfile.TemporaryDirectory()
    globals()["WATCH_FILE"] = pathlib.Path(tmp.name) / "watch.json"
    try:
        state.write_json(WATCH_FILE, {"watchers": {"77": ["Slipknot"]}, "sent": []})
        assert notify_releases() == 1, sent_to
        assert notify_releases() == 0, "весть ушла второй раз"
        # Старая отметка по отпечатку — из файлов, записанных до 12.09.2026:
        # смена ключа не должна разослать весь inbox заново.
        state.write_json(WATCH_FILE, {"watchers": {"77": ["Slipknot"]}, "sent": ["77:aaa"]})
        assert notify_releases() == 0, "старая отметка забыта"
    finally:
        (telegram.send_message, telegram.send_audio, globals()["_preview"],
         state.read_jsonl, globals()["WATCH_FILE"]) = real
        tmp.cleanup()
    print("рассылка релизов: один релиз — одна весть, старые отметки помнятся")

    # Слежение за артистом вне списка сбора: поиск при подписке, свой проход
    # по магазинам и ни строчки в inbox, откуда пишутся посты канала.
    today = state.iso()
    shops = {"itunes": [
        {"source": "itunes", "artist": "Nobody X", "artist_ids": [5], "title": "Tape - Single",
         "url": "", "released_at": today, "external_id": "i1"},
        # Фит у чужого артиста и предзаказ — не вести.
        {"source": "itunes", "artist": "Other (feat. Nobody X)", "artist_ids": [9], "title": "Guest",
         "url": "", "released_at": today, "external_id": "i2"},
        {"source": "itunes", "artist": "Nobody X", "artist_ids": [5], "title": "Later",
         "url": "", "released_at": state.iso(state.now() + timedelta(days=20)), "external_id": "i3"},
    ], "deezer": [
        {"source": "deezer", "artist": "", "title": "Tape", "url": "", "released_at": today,
         "external_id": "d1"},
    ]}
    real = (telegram.send_message, telegram.send_audio, _preview, state.read_jsonl,
            globals()["WATCH_FILE"], collect.load_artists, itunes.find_artist_id,
            itunes.resolve_name, itunes.recent_releases, deezer.find_artist_id,
            deezer.recent_releases, deezer.album_credit, config.INBOX_FILE, afisha.find_artist)
    messages: list[tuple[str, list | None]] = []
    afisha.find_artist = lambda name: None
    telegram.send_message = lambda chat, text, buttons=None, **_: messages.append((text, buttons)) or {"message_id": 1}
    telegram.send_audio = lambda chat, audio, caption, buttons=None, **_: messages.append((caption, buttons)) or {"message_id": 1}
    globals()["_preview"] = lambda url: None
    collect.load_artists = lambda: [{"name": "Slipknot", "itunes_id": 1, "deezer_id": 2, "tier": "scene"}]
    itunes.find_artist_id = lambda name, exact=False: 5 if name == "Nobody X" else None
    deezer.find_artist_id = lambda name: 6 if name == "Nobody X" else None
    itunes.resolve_name = lambda name: "A$AP Rocky"
    itunes.recent_releases = lambda artist_id, **_: shops["itunes"] if artist_id == 5 else []
    deezer.recent_releases = lambda artist_id, **_: shops["deezer"] if artist_id == 6 else []
    deezer.album_credit = lambda album: ("Nobody X", [6])
    state.read_jsonl = lambda path: [release("aaa", "Arsenal - Single", "itunes")]
    tmp = tempfile.TemporaryDirectory()
    globals()["WATCH_FILE"] = pathlib.Path(tmp.name) / "watch.json"
    config.INBOX_FILE = pathlib.Path(tmp.name) / "inbox.jsonl"
    try:
        assert parse_command("/slezhu Nobody X") == ("watchlist", "Nobody X")
        assert "не нашёл" in watch_add("77", "ASAP rocky") and "A$AP Rocky" in watch_add("77", "ASAP rocky")
        assert "Слежу" in watch_add("77", "slipknot")
        assert "Слежу" in watch_add("77", "Nobody X")
        stored = state.read_json(WATCH_FILE, {})["watchers"]["77"]
        assert stored == [{"name": "Slipknot", "itunes_id": 1, "deezer_id": 2},
                          {"name": "Nobody X", "itunes_id": 5, "deezer_id": 6}], stored

        assert notify_releases() == 2, messages
        texts = sorted(t for t, _ in messages)
        assert "Nobody X" in texts[0] and "Slipknot" in texts[1], texts
        assert all(b and "unwatch" in b[0][0]["callback_data"] for _, b in messages)
        assert notify_releases() == 0, "весть ушла второй раз"
        assert not config.INBOX_FILE.exists(), "находка слежения попала в inbox"

        watch_list("77")
        answer, buttons = messages[-1]
        assert len(buttons) == 3 and "Nobody X" in answer, buttons  # два артиста и «Ещё артист»
        subject = buttons[1][0]["callback_data"][len(CALLBACK_PREFIX):].partition(":")[2]
        assert "Больше не слежу" in watch_remove("77", subject)
        assert [n["name"] for n in state.read_json(WATCH_FILE, {})["watchers"]["77"]] == ["Slipknot"]
    finally:
        (telegram.send_message, telegram.send_audio, globals()["_preview"], state.read_jsonl,
         globals()["WATCH_FILE"], collect.load_artists, itunes.find_artist_id,
         itunes.resolve_name, itunes.recent_releases, deezer.find_artist_id,
         deezer.recent_releases, deezer.album_credit, config.INBOX_FILE, afisha.find_artist) = real
        tmp.cleanup()
    print("слежение: вне списка сбора — поиск в магазинах, одна весть на релиз, inbox не тронут, отписка кнопкой")

    # Слежение без команд: кнопка в меню → вопрос → имя ответом → вопрос о городе.
    # И повтор /start от приложения удаляется без второго приветствия.
    said: list[tuple[str, list | None, str]] = []
    deleted: list[int] = []
    real = (telegram.send_message, telegram.delete_message, globals()["WATCH_FILE"], otbor.cancel,
            otbor.active, globals()["find_watch_artist"], afisha.find_artist, itunes.resolve_name,
            telegram.is_member, globals()["SOURCES_FILE"], os.environ.get("TELEGRAM_CHANNEL_ID"))
    member = {"ok": True}
    telegram.is_member = lambda channel, user: member["ok"]
    os.environ["TELEGRAM_CHANNEL_ID"] = "@plenka_fm"
    telegram.send_message = lambda chat, text, buttons=None, ask="", **_: said.append((text, buttons, ask)) or {"message_id": 1}
    telegram.delete_message = lambda chat, message_id: deleted.append(message_id)
    otbor.cancel = lambda chat: None
    otbor.active = lambda chat: False
    globals()["find_watch_artist"] = lambda name: {"name": "Баста", "deezer_id": 1} if name.casefold() == "баста" else None
    afisha.find_artist = lambda name: "basta"
    itunes.resolve_name = lambda name: ""
    tmp = tempfile.TemporaryDirectory()
    globals()["WATCH_FILE"] = pathlib.Path(tmp.name) / "watch.json"
    globals()["SOURCES_FILE"] = pathlib.Path(tmp.name) / "sources.json"

    def incoming(text: str, message_id: int, date: int = 100, reply: str = "", chat: int = 5) -> dict:
        message = {"chat": {"type": "private", "id": chat}, "from": {"id": chat}, "message_id": message_id,
                   "date": date, "text": text}
        return {**message, "reply_to_message": {"text": reply}} if reply else message

    try:
        handle_message(incoming("/start", 1), {})
        handle_message(incoming("/start", 2, date=101), {})
        assert deleted == [2] and len(said) == 1, (deleted, said)
        assert "СЛЕЖУ" in said[0][0] and said[0][1][2][0]["callback_data"] == f"{CALLBACK_PREFIX}slezhu"
        handle_message(incoming("/start", 3, date=200), {})
        assert len(said) == 2, "осознанный /start позже — снова приветствие"

        handle_message(incoming("Бастаа", 4, reply=f"За кем следить? {WATCH_MARK} — напишу"), {})
        assert said[-1][2] == "Имя артиста" and WATCH_MARK in said[-1][0], "не нашёл — переспросить"
        handle_message(incoming("Баста", 5, reply=said[-1][0]), {})
        assert "Слежу за" in said[-2][0] and said[-1][2] == "Город", said[-2:]
        handle_message(incoming("питер", 6, reply=said[-1][0]), {})
        assert "Санкт-Петербург" in said[-1][0] and state.read_json(WATCH_FILE, {})["cities"]["5"] == "Санкт-Петербург"

        # Ссылка из ролика о гастролёре: артист зашит в неё, бот подписывает и спрашивает город.
        handle_message(incoming("/start gorod_basta", 7, chat=6), {})
        assert "Слежу за" in said[-2][0] and said[-1][2] == "Город", said[-2:]
        assert state.read_json(SOURCES_FILE, {})[_today()] == {"gorod": 1}
        handle_message(incoming("/start gorod_nobody", 8, chat=7), {})
        assert WATCH_MARK in said[-1][0], "неизвестный адрес — обычный вопрос об артисте"
        # Без подписки на канал слежение не заводится: бот и есть то, чем ролик приводит в канал.
        member["ok"] = False
        handle_message(incoming("/start gorod_basta", 9, chat=8), {})
        handle_message(incoming("Баста", 10, chat=8, reply=f"За кем следить? {WATCH_MARK} — напишу"), {})
        handle_message(incoming("/gorod Казань", 11, chat=8), {})
        assert all("подписаться" in text for text, _, _ in said[-3:]) and "8" not in state.read_json(WATCH_FILE, {})["watchers"]
    finally:
        (telegram.send_message, telegram.delete_message, globals()["WATCH_FILE"], otbor.cancel,
         otbor.active, globals()["find_watch_artist"], afisha.find_artist, itunes.resolve_name,
         telegram.is_member, globals()["SOURCES_FILE"], channel_env) = real
        os.environ.pop("TELEGRAM_CHANNEL_ID", None)
        if channel_env:
            os.environ["TELEGRAM_CHANNEL_ID"] = channel_env
        tmp.cleanup()
    print("СЛЕЖУ: кнопка, имя и город ответом, без команд; ссылка с артистом из ролика; без подписки не заводится; "
          "повтор /start удалён без второго приветствия")

    # Концерты: разбор страницы Афиши без сети, город словами, одна весть на концерт.
    today = datetime.date(2026, 9, 16)
    item = ('<div data-test-id="personSchedule.item"><a href="/{city}/concert/{slug}?source=artist">'
            '<div data-test-id="scheduleDate.month">{when}</div>'
            '<div class="person-schedule-place__city">{name}</div>'
            '<span data-test-id="personSchedule.placeName">Клуб</span>{passed}</div>')
    page = "".join(item.format(**row) for row in (
        {"city": "moscow", "slug": "x-tour", "when": "4 и 5 октября", "name": "Москва", "passed": ""},
        {"city": "moscow", "slug": "x-tour", "when": "28 ноября", "name": "Москва", "passed": ""},
        {"city": "kazan", "slug": "x-2019", "when": "24 ноября 2019", "name": "Казань",
         "passed": '<div class="person-schedule-item__passed">Событие прошло</div>'},
        {"city": "kazan", "slug": "x-old", "when": "1 сентября", "name": "Казань", "passed": ""},
        {"city": "kazan", "slug": "x-jan", "when": "29 января", "name": "Казань", "passed": ""},
    ))
    shows = afisha.parse(page, today)
    assert [(c["day"], c["city"]) for c in shows] == [
        ("2026-10-04", "Москва"), ("2026-11-28", "Москва"), ("2027-01-29", "Казань")], shows
    assert afisha.slug("Три дня дождя") == "tri-dnia-dozhdia" and afisha.slug("SODA LUV") == "soda-luv"
    assert [normalize_city(c) for c in ("питер", "г. Москва", "нижний новгород", "Ростов-на-Дону")] == [
        "Санкт-Петербург", "Москва", "Нижний Новгород", "Ростов-на-Дону"]
    assert parse_command("/gorod Питер") == ("city", "Питер")

    real = (telegram.send_message, globals()["WATCH_FILE"], afisha.find_artist, afisha.concerts, globals()["_today"])
    notes: list[tuple[str, str]] = []
    telegram.send_message = lambda chat, text, **_: notes.append((chat, text)) or {"message_id": 1}
    afisha.find_artist = lambda name: "x" if name == "Баста" else None
    afisha.concerts = lambda slug, today=None: shows
    tmp = tempfile.TemporaryDirectory()
    globals()["WATCH_FILE"] = pathlib.Path(tmp.name) / "watch.json"
    try:
        assert CITY_MARK in city_set("1", "") and "добавь артистов" in city_set("1", "мск")
        state.write_json(WATCH_FILE, {"watchers": {"1": [{"name": "Баста"}, {"name": "Nobody X"}],
                                                   "2": [{"name": "Баста"}]},
                                      "cities": {"1": "Москва"}, "sent": []})
        assert "не нашёл: Баста, Nobody X" in city_set("1", "мск")
        assert "Санкт-Петербург" in city_set("2", "спб")
        globals()["_today"] = lambda: "2026-09-16"
        with contextlib.redirect_stdout(io.StringIO()):
            assert notify_concerts(dry_run=True) == 2 and not notes, "сухой прогон отправил"
        assert notify_concerts() == 2, notes
        assert {chat for chat, _ in notes} == {"1"}, "чужой город получил весть"
        assert "4 и 5 октября" in notes[0][1] and "afisha.yandex.ru/moscow/concert/x-tour" in notes[0][1]
        assert notify_concerts() == 0, "второй проход за день"
        globals()["_today"] = lambda: "2026-09-17"
        assert notify_concerts() == 0, "весть о концерте ушла второй раз"
        saved = state.read_json(WATCH_FILE, {})
        assert saved["watchers"]["1"][0]["afisha"] == "x" and "afisha" not in saved["watchers"]["1"][1]
        assert watch_clear("1") and "1" not in state.read_json(WATCH_FILE, {})["cities"]
    finally:
        (telegram.send_message, globals()["WATCH_FILE"], afisha.find_artist, afisha.concerts,
         globals()["_today"]) = real
        tmp.cleanup()
    print("концерты: весть одна на концерт и раз в день, чужой город молчит, прошедшая дата отсеяна")

    opened: list[str] = []
    real = otbor.start, telegram.send_message, globals()["SOURCES_FILE"]
    otbor.start = lambda chat, user, **_: opened.append(chat)
    replies: list[tuple[str, list]] = []
    telegram.send_message = lambda chat, text, buttons=None, **_: replies.append((text, buttons)) or {"message_id": 1}
    tmp = tempfile.TemporaryDirectory()
    globals()["SOURCES_FILE"] = pathlib.Path(tmp.name) / "sources.json"
    try:
        # Минута между сообщениями: одинаковые /start подряд иначе сочтутся повтором приложения.
        for minute, text in enumerate(("/start yt", "/start yt", "/start tt", "/start taste", "/proyavka", "/start")):
            handle_message({"chat": {"id": 55501, "type": "private"}, "from": {"id": 77701},
                            "message_id": minute, "date": minute * 60, "text": text}, {})
        saved = SOURCES_FILE.read_text()
        assert state.read_json(SOURCES_FILE, {}) == {_today(): {"yt": 2, "tt": 1}}, saved
        assert opened == ["55501"] * 3, opened
        assert "555" not in saved and "777" not in saved, "id человека в открытом файле"
        assert [text for text, _ in replies] == [PROYAVKA, PROYAVKA, MENU], "старая ссылка и /proyavka — в ПРОЯВКУ"
        assert [row[0]["text"][:1] for row in replies[-1][1]] == ["🎙", "🎞", "🔔"], "в меню три раздела"
    finally:
        otbor.start, telegram.send_message, globals()["SOURCES_FILE"] = real
        tmp.cleanup()
    print("метка /start: считается по дню без id и сразу открывает отбор; в меню три раздела")


# ─────────────────────────── командная строка ───────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description="Разборы ПРОЯВКИ")
    parser.add_argument("--try", dest="query", help="прогнать разбор в терминал")
    parser.add_argument("--kind", default="", help="taste | roots | lyrics")
    parser.add_argument("--match", help="показать, что нашлось в базе, без затрат на модель")
    parser.add_argument("--stats", action="store_true", help="расход лимитов")
    parser.add_argument("--sources", action="store_true", help="откуда пришли в бота: метки ссылок по дням")
    parser.add_argument("--selftest", action="store_true", help="проверить рассылку вестей, без сети")
    parser.add_argument(
        "--notify",
        action="store_true",
        help="разослать вести о новых релизах тем, кто следит",
    )
    parser.add_argument("--concerts", action="store_true",
                        help="разослать вести о концертах в городе подписчика (раз в день)")
    parser.add_argument("--dry-run", action="store_true", help="с --concerts: показать вести, не отправляя")
    args = parser.parse_args()

    if args.selftest:
        _selftest()
        return 0

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    config.load_dotenv()

    if args.notify:
        sent = notify_releases()
        print(f"Разослано вестей о релизах: {sent}.")
        return 0

    if args.concerts:
        sent = notify_concerts(dry_run=args.dry_run)
        print(f"{'Ушло бы' if args.dry_run else 'Разослано'} вестей о концертах: {sent}.")
        return 0

    if args.stats:
        data = load_state()
        print(f"День: {data['day']}. Выдано разборов: {data['total']}/{config.SERVICE_DAILY_TOTAL}")
        for user, info in sorted(data.get("users", {}).items()):
            print(f"  {user}: сегодня {info.get('count', 0)}, всего {info.get('total', 0)}")
        return 0

    if args.sources:
        counts = state.read_json(SOURCES_FILE, {})
        total: dict[str, int] = {}
        for day, labels in sorted(counts.items()):
            print(day, "  ".join(f"{SOURCES.get(k, k)}: {v}" for k, v in sorted(labels.items())))
            for k, v in labels.items():
                total[k] = total.get(k, 0) + v
        print("Всего:", "  ".join(f"{SOURCES.get(k, k)}: {v}" for k, v in sorted(total.items())) or "никто")
        return 0

    if args.match:
        scene = known_artists(args.match)
        print(f"Узнали артистов: {', '.join(a['name'] for a in scene) or '—'}")
        for link in match_links(args.match, scene):
            print(f"  {link['modern'][:60]}  ←  {link['ancestor'][:50]}")
        return 0

    if args.query:
        kind = args.kind or guess_kind(args.query) or "roots"
        print(f"Разбор: {kind}. Генератор: {llm.describe()}\n")
        answer, image = analyse(kind, args.query)
        print(answer)
        if image:
            print(f"\nКарточка: {image.relative_to(config.ROOT)}")
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
