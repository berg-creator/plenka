"""ПРОЯВКА — разборы по запросу в личке бота.

Канал публикует сам по себе, но подписчиков это не приносит: пост не пересылают,
пересылают результат про себя. Поэтому у бота есть три разбора, и главный из них
отдаёт картинку, которую человек показывает друзьям.

    /vkus   список артистов        → откуда растёт твой вкус + карточка
    /nogi   артист, трек или жанр  → к какому предку сходится ниточка
    /tekst  строки из песни        → что в этих строках на самом деле происходит

Команду можно не писать: бот различает список имён, одно имя и куплет по форме
сообщения. Кириллические синонимы (/вкус, /ноги, /текст) тоже работают, но
в меню Telegram их не показать — там разрешена только латиница.

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
import re
from pathlib import Path

from . import card, config, llm, quality, state, stories, telegram
from .sources import lastfm

log = logging.getLogger("service")

STATE_FILE = config.DATA / "service.json"
# Запросы, на которые базы не хватило: готовый список, чем пополнять lineage.json,
# причём по реальному спросу, а не по догадкам.
REQUESTS_FILE = config.DATA / "lineage_requests.jsonl"
# Все выданные разборы — материал для постов «разбор подписчика №N».
LOG_FILE = config.DATA / "service_log.jsonl"

CARD_DIR = config.ROOT / "assets" / "cards"


# ─────────────────────────── разбор входящего ───────────────────────────

# В меню бота Telegram пускает только латиницу и цифры, поэтому основные
# команды — транслитом: по-русски читаются, в меню показываются. Кириллица
# и английские названия оставлены синонимами: их всё равно набирают.
COMMANDS = {
    "vkus": "taste", "вкус": "taste", "taste": "taste",
    "nogi": "roots", "ноги": "roots", "roots": "roots",
    "tekst": "lyrics", "текст": "lyrics", "lyrics": "lyrics",
}

# Меню объясняет все три разбора сразу и показывает пример на каждый.
# Так человеку не нужен лишний круг ожидания: он может ответить прямо на это
# сообщение и получить разбор, ни на что не нажимая. Кнопки — для тех,
# кто читать не станет.
# Одно правило вместо трёх режимов: напиши что угодно. Раньше здесь висело
# меню из трёх разборов с порогом в три артиста — человек читал условия
# и уходил, так и не спросив ничего.
MENU = (
    "<b>ПРОЯВКА</b> — разбираю, откуда что взялось.\n\n"
    "Напиши что угодно:\n"
    "· артиста — <i>Bones</i>\n"
    "· жанр — <i>фонк</i>\n"
    "· песню — <i>Molchat Doma — Судно</i>\n"
    "· или сразу список, кого слушаешь\n\n"
    "В ответ придёт разбор и карточка, которую не стыдно кинуть друзьям.\n\n"
    "Ещё умею разбирать тексты: пришли несколько строк из песни."
)

# Что бот отвечает на нажатие кнопки: коротко, что прислать, и пример.
HINTS = {
    "taste": (
        "🎧 <b>Что разобрать?</b>\n\n"
        "Напиши артиста, жанр или песню — по одному имени тоже работает.\n\n"
        "<i>Bones</i>  ·  <i>фонк</i>  ·  <i>Молчат Дома</i>\n\n"
        "Или сразу список, кого слушаешь, — тогда покажу, что у них общего."
    ),
    "lyrics": (
        "📝 <b>Разбор текста</b>\n\n"
        "Пришли несколько строк из песни — своих или чужих.\n\n"
        "Разберу приём, двойные смыслы и отсылки. Автора не угадываю: "
        "если хочешь, чтобы учёл — напиши его сам."
    ),
}

# Префикс отличает кнопки сервиса от кнопок модерации: у тех callback_data
# вида «pub:имя-файла», и обработчики не должны пересекаться.
CALLBACK_PREFIX = "s:"


def menu_buttons() -> list[list[dict]]:
    return [
        [{"text": "🎧 Что разобрать?", "callback_data": f"{CALLBACK_PREFIX}taste"}],
        [{"text": "📝 Разобрать текст песни", "callback_data": f"{CALLBACK_PREFIX}lyrics"}],
    ]


def again_buttons() -> list[list[dict]]:
    """Кнопки под готовым разбором — чтобы не искать, как повторить."""
    return [[{"text": "Ещё разбор", "callback_data": f"{CALLBACK_PREFIX}menu"}]]

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
            tags = lastfm.artist_tags(name, limit=6)
            similar = lastfm.similar_artists(name, limit=6)
            bio = lastfm.artist_bio(name)
        except Exception as exc:  # noqa: BLE001 — источник необязательный
            log.info("Last.fm молчит про «%s»: %s", name, exc)
            continue

        if not (tags or similar):
            continue  # артиста не знает даже Last.fm — выдумывать не станем

        facts.append(
            {
                "artist": name,
                "tags": tags,
                "similar": [s["name"] for s in similar],
                "bio": stories.strip_html(bio)[:BIO_LIMIT],
            }
        )
    return facts


# ─────────────────────────── лимиты ───────────────────────────


def _today() -> str:
    return state.now().strftime("%Y-%m-%d")


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
    path = card.save(verdict, items, name=f"card-{state.now().strftime('%H%M%S')}")
    _remember(query, kind, matched=True, verdict=verdict)
    return text, path


def _nothing_found() -> str:
    """Отказ должен помогать, а не закрывать дверь.

    Сухое «нет в базе» человек читает как «бот сломан». Поэтому показываем,
    про что канал вообще, и даём пару имён, с которыми точно сработает.
    """
    artists = state.read_json(config.ARTISTS_FILE, {"artists": []})["artists"]
    core = [a["name"] for a in artists if a.get("tier") == "core"][:4]
    examples = ", ".join(core) if core else "Three 6 Mafia, Bones"
    return (
        "Такого в базе канала нет — она про тёмный звук: мемфис, фонк, "
        "эмо-рэп, дрейн, ню-метал, русский андеграунд.\n\n"
        f"Попробуй так: <i>{examples}</i>\n"
        "Или просто жанр: <i>фонк</i>, <i>витч-хаус</i>, <i>ню-метал</i>.\n\n"
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

    kind, body = parse_command(text)
    if kind == "menu":
        # Пришёл по ссылке с готовым разбором — не показываем меню, а сразу
        # объясняем, что слать: лишний экран между кнопкой и делом только мешает.
        if body in HINTS:
            set_mode(data, key, body)
            telegram.send_message(chat_id, HINTS[body])
        else:
            telegram.send_message(chat_id, MENU, buttons=menu_buttons())
        return False
    if not kind:
        # Разбор, выбранный кнопкой, старше догадки по форме сообщения:
        # человек уже сказал, чего хочет, и переспрашивать его глупо.
        kind = peek_mode(data, key) or guess_kind(text)
        body = text
    if not kind:
        telegram.send_message(chat_id, MENU, buttons=menu_buttons())
        return False

    channel = config.secret("TELEGRAM_CHANNEL_ID", required=False)
    if channel and not admin and not telegram.is_member(channel, user_id):
        telegram.send_message(
            chat_id,
            "Разборы — для своих.\n\n"
            f"Подпишись на {channel} и пришли запрос ещё раз.",
        )
        return False

    denied = check_limit(data, key, admin=admin)
    if denied:
        telegram.send_message(chat_id, denied)
        return False

    # Выбор кнопкой гасим только здесь: если человека развернули на подписке
    # или лимите, он не должен нажимать кнопку заново.
    clear_mode(data, key)

    telegram.send_chat_action(chat_id)
    try:
        answer, image = analyse(kind, body)
    except Exception as exc:  # noqa: BLE001 — один сбойный запрос не должен ронять запуск
        log.error("Разбор «%s» сорвался: %s", kind, exc)
        telegram.send_message(chat_id, "Плёнку зажевало. Попробуй ещё раз.")
        return False

    if image is not None:
        # Подпись к фото у Telegram короче обычного сообщения. Разбор длиннее
        # лимита не режем — карточка уходит молча, а текст следом отдельно.
        if len(answer) <= telegram.MAX_CAPTION:
            telegram.send_photo_file(chat_id, image, answer)
            telegram.send_message(chat_id, WHAT_NEXT, buttons=again_buttons())
        else:
            telegram.send_photo_file(chat_id, image, "")
            telegram.send_message(chat_id, answer, buttons=again_buttons())
        image.unlink(missing_ok=True)  # карточка уже у человека, в репозитории не нужна
    else:
        telegram.send_message(chat_id, answer, buttons=again_buttons())

    spend(data, key)
    return True


# Строка под карточкой: кнопки к фото прицепить можно, но тогда подпись
# и кнопка живут в одном сообщении и пересылаются вместе — а карточку
# пересылают именно без служебных кнопок.
WHAT_NEXT = "Забирай карточку. Разберём что-нибудь ещё?"


def handle_callback(query: dict, data: dict) -> None:
    """Нажатие кнопки сервиса. Разборов не делает — только объясняет, что слать.

    Собственно разбор всегда идёт следующим сообщением: так человек видит
    инструкцию с примером до того, как потратит свой суточный лимит.
    """
    raw = query.get("data", "")
    kind = raw[len(CALLBACK_PREFIX):]
    chat_id = str(query.get("message", {}).get("chat", {}).get("id", ""))
    key = user_key(query.get("from", {}).get("id", ""))

    telegram.answer_callback(query.get("id", ""))
    if not chat_id:
        return

    if kind not in HINTS:
        telegram.send_message(chat_id, MENU, buttons=menu_buttons())
        return

    set_mode(data, key, kind)
    telegram.send_message(chat_id, HINTS[kind])


def set_mode(data: dict, user_id: str, kind: str) -> None:
    user = data.setdefault("users", {}).setdefault(user_id, {"day": "", "count": 0, "total": 0})
    user["mode"] = kind


def peek_mode(data: dict, user_id: str) -> str:
    return data.get("users", {}).get(user_id, {}).get("mode", "")


def clear_mode(data: dict, user_id: str) -> None:
    """Кнопка отвечает за одно следующее сообщение, дальше человек снова
    волен слать что угодно."""
    data.get("users", {}).get(user_id, {}).pop("mode", None)


# ─────────────────────────── командная строка ───────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description="Разборы ПРОЯВКИ")
    parser.add_argument("--try", dest="query", help="прогнать разбор в терминал")
    parser.add_argument("--kind", default="", help="taste | roots | lyrics")
    parser.add_argument("--match", help="показать, что нашлось в базе, без затрат на модель")
    parser.add_argument("--stats", action="store_true", help="расход лимитов")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    config.load_dotenv()

    if args.stats:
        data = load_state()
        print(f"День: {data['day']}. Выдано разборов: {data['total']}/{config.SERVICE_DAILY_TOTAL}")
        for user, info in sorted(data.get("users", {}).items()):
            print(f"  {user}: сегодня {info.get('count', 0)}, всего {info.get('total', 0)}")
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
