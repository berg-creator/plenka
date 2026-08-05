"""ПРОЯВКА — разборы по запросу в личке бота.

Канал публикует сам по себе, но подписчиков это не приносит: пост не пересылают,
пересылают результат про себя. Поэтому у бота есть три разбора, и главный из них
отдаёт картинку, которую человек показывает друзьям.

    /вкус   список артистов        → откуда растёт твой вкус + карточка
    /ноги   артист, трек или жанр  → к какому предку сходится ниточка
    /текст  строки из песни        → что в этих строках на самом деле происходит

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

log = logging.getLogger("service")

STATE_FILE = config.DATA / "service.json"
# Запросы, на которые базы не хватило: готовый список, чем пополнять lineage.json,
# причём по реальному спросу, а не по догадкам.
REQUESTS_FILE = config.DATA / "lineage_requests.jsonl"
# Все выданные разборы — материал для постов «разбор подписчика №N».
LOG_FILE = config.DATA / "service_log.jsonl"

CARD_DIR = config.ROOT / "assets" / "cards"


# ─────────────────────────── разбор входящего ───────────────────────────

COMMANDS = {
    "вкус": "taste", "taste": "taste",
    "ноги": "roots", "roots": "roots",
    "текст": "lyrics", "lyrics": "lyrics",
}

MENU = (
    "<b>ПРОЯВКА</b> — разборы по запросу.\n\n"
    "<code>/вкус</code> — пришли своих артистов через запятую, "
    "покажу, откуда растёт твой вкус. С картинкой.\n\n"
    "<code>/ноги</code> — артист, трек или жанр. Расскажу, к какому предку "
    "сходится ниточка.\n\n"
    "<code>/текст</code> — пришли строки из песни, разберу, что в них "
    "происходит.\n\n"
    "Отвечаю не мгновенно: плёнку надо проявить, это пара минут."
)

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
        return "menu", ""
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

    if len(items) >= 3 and looks_like_names(items):
        return "taste"
    if len(lines) >= 2 and sum(len(line) for line in lines) / len(lines) > 18:
        return "lyrics"
    # Имя артиста, название трека или жанр — это несколько слов. Фраза длиннее
    # похожа на разговор с ботом, а разговоров он не ведёт.
    if len(lines) == 1 and 2 <= len(text.strip()) <= 80 and len(text.split()) <= 6:
        return "roots"
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


# ─────────────────────────── лимиты ───────────────────────────


def _today() -> str:
    return state.now().strftime("%Y-%m-%d")


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
    """Готовит разбор. Возвращает (текст ответа, карточка или None)."""
    if kind == "taste":
        return _taste(body)
    if kind == "lyrics":
        return _lyrics(body)
    return _roots(body)


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
    items = split_items(body)[:MAX_ARTISTS]
    if len(items) < 3:
        return ("Пришли хотя бы трёх артистов через запятую — по одному вкус не читается.", None)

    query = ", ".join(items)
    scene = known_artists(query)
    links = match_links(query, scene)

    if not links:
        _remember(query, "taste", matched=False)
        return (
            "Ни одного знакомого имени — база канала про тёмный звук: "
            "мемфис, фонк, эмо-рэп, дрейн, ню-метал.\n\n"
            "Пришли что-нибудь из этой стороны, разберу.",
            None,
        )

    result = _generate(
        "taste",
        {
            "artists": items,
            "known": links,
            "scene": scene_payload(scene),
            "unknown": [i for i in items if not any(_mentions(i, a["name"]) for a in scene)],
        },
    )
    if result["skip"] or not result["text"]:
        _remember(query, "taste", matched=False)
        return (NO_BASE, None)

    text = telegram.sanitize(result["text"])
    verdict = _verdict(text)
    path = card.save(verdict, items, name=f"taste-{state.now().strftime('%H%M%S')}")
    _remember(query, "taste", matched=True, verdict=verdict)
    return text, path


def _roots(body: str) -> tuple[str, Path | None]:
    query = body.strip()[:MAX_QUERY]
    if len(query) < 2:
        return ("Напиши, про кого или про что — артиста, трек или жанр.", None)

    scene = known_artists(query)
    links = match_links(query, scene, limit=2)
    if not links:
        _remember(query, "roots", matched=False)
        return (NO_BASE, None)

    result = _generate("roots", {"query": query, "known": links, "scene": scene_payload(scene)})
    if result["skip"] or not result["text"]:
        _remember(query, "roots", matched=False)
        return (NO_BASE, None)

    _remember(query, "roots", matched=True)
    return telegram.sanitize(result["text"]), None


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

    _remember(" / ".join(lines[:2]), "lyrics", matched=True)
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

    kind, body = parse_command(text)
    if kind == "menu":
        telegram.send_message(chat_id, MENU)
        return False
    if not kind:
        kind = guess_kind(text)
        body = text
    if not kind:
        telegram.send_message(chat_id, MENU)
        return False

    channel = config.secret("TELEGRAM_CHANNEL_ID", required=False)
    if channel and not admin and not telegram.is_member(channel, user_id):
        telegram.send_message(
            chat_id,
            "Разборы — для своих.\n\n"
            f"Подпишись на {channel} и пришли запрос ещё раз.",
        )
        return False

    denied = check_limit(data, user_id, admin=admin)
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

    if image is not None:
        # Подпись к фото у Telegram короче обычного сообщения. Разбор длиннее
        # лимита не режем — карточка уходит молча, а текст следом отдельно.
        if len(answer) <= telegram.MAX_CAPTION:
            telegram.send_photo_file(chat_id, image, answer)
        else:
            telegram.send_photo_file(chat_id, image, "")
            telegram.send_message(chat_id, answer)
        image.unlink(missing_ok=True)  # карточка уже у человека, в репозитории не нужна
    else:
        telegram.send_message(chat_id, answer)

    spend(data, user_id)
    return True


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
