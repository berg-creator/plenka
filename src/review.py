"""Автопилот точности: облачный Claude сверяет новые посты с данными и сам правит выдумки.

Посты пишет GigaChat, и он выдумывает: звучание, которого нет в данных
(«жёсткий ритм, отрывистый вокал»), прошлое артиста («после серии больших
альбомов» у Смоки Мо, у которого за лето четыре сингла), устройство релиза
(«все треки короткие, кроме последнего» — неправда). Решение владельца
от 11.09.2026 — автопилот: сам он посты не проверяет. Раз в два часа облачный
Claude по его подписке (запланированный агент claude.ai/code, бриф —
prompts/review.md) сверяет новые посты очереди с данными, из которых они
написаны, и вырезает выдумку или заменяет её фактом.

Отвергнуто:

- Список выдумок владельцу. Читать его владелец не будет, а непрочитанный
  список ничем не лучше никакого.
- Claude через API прямо в конвейере. Около $0,7 в день — дороже, чем стоит
  проверка, а подписка владельца уже оплачена.
- Правка из рутины прямо в main. Облачный автор в main пушить не может, поэтому,
  как у роликов (src/reels.py), ветка служит почтовым ящиком: рутина пушит файл
  правок в claude/review-*, воркфлоу review.yml проверяет его, применяет к main
  и удаляет ветку.

Путь одной правки:

1. Рутина смотрит git log за шесть часов — втрое шире расписания: пропущенный
   по лимитам подписки запуск иначе уносит с собой посты, которых не проверит
   уже никто. Новых и вышедших постов нет — выходит, ничего не читая. Есть —
   сверяет и пишет content/review/<ГГГГММДД-ЧЧММ>.json: пост, rewrite (новый
   полный текст) или drop (снять из очереди), дословная цитата выдумки и чего
   нет в данных. Выдумок нет — не пушит ничего.
2. --check на снимке, по которому рутина писала правки: цитата есть в посте
   и ушла из нового текста, новый текст проходит quality.problems (там же
   заголовок <b> у рубрик с заголовком), строка кнопки «▸ <a …>» осталась
   как была. Мем и опрос только снимаются: подпись мема держится на картинке,
   а опрос — это JSON. Проверке не нужны ни сеть, ни пакеты сверх стандартной
   библиотеки — её же рутина зовёт перед пушем.
3. --apply на свежем main. Между проходом и применением пост мог поменяться:
   такой пропускается, а не затирается устаревшей правкой. Битый файл
   не применяется целиком и красит запуск.

Вышедший пост правится прямо в канале. publish.to_channel кладёт в архивный
JSON сообщение с текстом поста — поле message, вместе с кнопками: правка
без reply_markup их снимает. --apply зовёт publish.edit, а тот
editMessageCaption или editMessageText. Снять вышедший нельзя, только
rewrite; старый пост без message пропускается — править не с чем. Отказ
канала красит запуск, но годные правки рядом применяются: в канале они уже
вышли, и архив должен помнить их текст. ВКонтакте не правится вовсе.

Второй вид правки — мнения о свежих релизах (владелец, 29.09.2026): поиск
Gemini на бесплатном ключе отвечает 429, а подписка уже оплачена. Тем же
проходом рутина берёт список --voices (свежие релизы без поста и без мнения;
сингл без чужого голоса поста не получает) и приносит полем voices адрес
страницы и цитату. Цитату принимает только sources/web_voice.accept, скачав
страницу сам, — Claude верим не больше, чем Gemini. Не подтвердилась — строка
в логе, а не красный запуск: это промах автора, а не поломка. Релиз не из
списка --apply пропускает без сети: пост уже написан, сутки вышли, или рутина
выдумала артиста. --voices и --check на мнениях — та же стандартная
библиотека; web_voice тянет requests и зовётся только из --apply.

Третий вид — новые связи для ОТКУДА НОГИ (владелец, 01.10.2026). Связь рассказывается
один раз, база из 18 ручных кончилась, и пополнять её руками владелец не будет. Правило
«lineage.json только руками» держалось на том, что выдуманный год убивает доверие;
смысл остался, сменился способ: рутина приносит полем lineage двух артистов, вид связи
(сэмпл, кавер, слова артиста о влиянии, общий продюсер, объединение), факты и к каждому
адрес страницы с дословной цитатой, а годится ли запись, решает код. --check без сети:
сайт из списка (Википедия и издания сбора, trusted), числа в фактах — только из цитат.
--apply: страница скачана, цитата стоит на ней слово в слово, хотя бы одна называет
обоих артистов, оба трека по ссылкам Deezer — те самые, и ни одного из артистов в базе
ещё нет. Не прошла — строка в лог. --lineage говорит рутине, искать ли вообще:
нерассказанных меньше двух, за неделю добавлено меньше двух, искали не сегодня.
Отвергнуто: сверять повтор по паре артистов — «Three 6 Mafia → ещё кто-то» прошло бы
и вышло седьмым постом про Мемфис; и дописывать второй трек старым связям — они
рассказаны, а рассказанная связь второго поста не получит.

    python -m src.review --check content/review/20260912-0835.json    проверка без сети
    python -m src.review --apply content/review/20260912-0835.json --dry-run
    python -m src.review --voices                                     кому рутина ищет мнение, без сети
    python -m src.review --lineage                                    нужна ли новая связь ОТКУДА НОГИ, без сети
    python -m src.review --selftest
"""

from __future__ import annotations

import argparse
import html
import json
import re
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse

# Только лёгкое: --check зовёт облачный автор, и requests с Pillow ему ставить незачем.
from . import config, quality, state

ACTIONS = ("rewrite", "drop")
# Мем держится на картинке, опрос — JSON: подпись мема без выдумки остаётся
# шуткой ни о чём, а JSON опроса, переписанный руками, ломает опрос.
DROP_ONLY = ("meme", "poll")
# Посты, собранные шаблоном без модели, не правятся никогда: выдумать в них нечего, а испортить есть что —
# в ПАМЯТКЕ (src/pamyatka.py) цитаты закона стоят слово в слово, в ОТБОРЕ имя и название написал сам артист.
# Правка такого поста — пропуск, а не порок файла: годные правки рядом применяются (владелец 09.10.2026).
TEMPLATE = ("pamyatka", "sovet", "beat", "week", "doposle", "otbor")

ID_FORMAT = re.compile(r"\d{8}-\d{4}")
# Путь приходит из ветки, то есть снаружи: только файл очереди или архива, без «../».
POST_PATH = re.compile(r"content/(queue|archive)/[\w-]+\.json")
BUTTON = re.compile(r"(?m)^▸\s*<a\s+href=.*$")
TAG = re.compile(r"<[^>]+>")

PUBLISHED = "пост вышел, а сообщение в канале не записано — править не с чем"

# Релизов, которым рутина ищет мнение за проход: каждый — поиск и чтение страниц,
# а лимиты подписки те же, что у разбора постов.
VOICES_PER_RUN = 5
BY = ("", "critic", "listener")

# Что считается связью для ОТКУДА НОГИ — только задокументированное: сэмпл, кавер, слова
# самого артиста о влиянии, общий продюсер, общее объединение. У «звучит похоже» и общего
# жанра вида нет, и запись без вида код не берёт.
LINK_KINDS = ("sample", "cover", "said", "producer", "group")
LINK_QUOTE = (30, 400)
LINK_FACTS = 4
DEEZER_TRACK = re.compile(r"https://(?:www\.)?deezer\.com/(?:[a-z]{2}/)?track/\d+")


def _filled(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def plain(text: str) -> str:
    """Текст для поиска цитаты: без разметки, сущностей, регистра, «ё» и лишних пробелов.

    Цитату рутина переписывает из поста: теги и переносы строк в ней не угадать,
    а «ё» модели меняют на «е» и обратно. Дословность — по словам, не по разметке.
    """
    text = html.unescape(TAG.sub("", text)).casefold().replace("ё", "е")
    return " ".join(text.split())


def _shape(edit) -> str:
    """Что не так с правкой по форме, без чтения поста. Пустая строка — годна."""
    if not isinstance(edit, dict):
        return "правка — это объект"
    file, action = edit.get("file"), edit.get("action")
    if not isinstance(file, str) or not POST_PATH.fullmatch(file):
        return "file: путь поста вида content/queue/<имя>.json или content/archive/<имя>.json"
    if action not in ACTIONS:
        return f"action «{action}»: rewrite или drop"
    missing = [field for field in ("fragment", "why") if not _filled(edit.get(field))]
    if action == "rewrite" and not _filled(edit.get("text")):
        missing.append("text")
    if missing:
        return "нет " + ", ".join(missing)
    if action == "drop" and not file.startswith("content/queue/"):
        return "drop — только для поста в очереди"
    return ""


def _current(file: str) -> Path:
    """Где пост лежит сейчас: в очереди, а вышедший — в архиве."""
    path = config.ROOT / file
    return path if file.startswith("content/queue/") and path.is_file() else config.ARCHIVE / path.name


def _post(edit: dict) -> tuple[dict | None, str]:
    """Пост из правки, как он лежит сейчас. None — править нечего, и почему."""
    path = _current(edit["file"])
    if not path.is_file():
        return None, "поста уже нет"
    try:
        post = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None, "пост — битый JSON"
    if post.get("rubric") in TEMPLATE:
        return None, f"{post['rubric']} собран шаблоном без модели — не правится"
    if path.parent == config.ARCHIVE:
        if edit["action"] == "drop":
            return None, "пост уже вышел — снять нельзя, только rewrite"
        if not post.get("message"):
            return None, PUBLISHED
    return post, ""


def _text_problems(post: dict, edit: dict) -> list[str]:
    """Годен ли новый текст на место старого."""
    rubric = post.get("rubric", "")
    if edit["action"] == "drop":
        return []
    if rubric in DROP_ONLY:
        return [f"{rubric} не переписывается — только drop"]
    old, new = post.get("text", ""), edit["text"]
    errors = [f"новый текст: {issue}" for issue in quality.problems(new, rubric)]
    if plain(edit["fragment"]) in plain(new):
        errors.append("цитата выдумки осталась в новом тексте")
    kept = {line.strip() for line in new.splitlines()}
    errors += [
        f"строки кнопки нет в новом тексте: {line.strip()}"
        for line in BUTTON.findall(old)
        if line.strip() not in kept
    ]
    return errors


def _voice_key(voice: dict) -> str:
    # Тот же ключ, что web_voice.key: импортировать его нельзя — модуль тянет requests.
    return quality.norm(f"{voice['artist']} — {voice['release']}")


def voices_wanted(rows: list[dict], used: set[str], cache: dict, artists: dict[str, dict]) -> list[dict]:
    """Кому рутина ищет мнение: свежие релизы inbox без поста и без мнения, по убыванию веса.

    Окно то же, что у compose --fresh (fresh_releases): вышли не больше
    RELEASE_MAX_AGE_HOURS назад и не в будущем. Без поста — отпечаток не в used:
    сингл без чужого голоса compose пропускает, не помечая, и пересматривает
    каждым сбором, пока релиз свежий; это главные адресаты. Дубль второго
    магазина уже написанного релиза — тоже с постом. Искали и не нашли — снова
    не раньше WEB_VOICE_RETRY_HOURS. names — написания для сверки страницы,
    как у compose.outside_voice.
    """
    now = state.now()
    cutoff = timedelta(hours=config.RELEASE_MAX_AGE_HOURS)
    retry = timedelta(hours=config.WEB_VOICE_RETRY_HOURS)
    wanted: dict[str, dict] = {}
    posted = set()
    for row in sorted(rows, key=lambda r: r.get("score", 0), reverse=True):
        voice = {"artist": row.get("artist", ""), "release": quality.release_name(row.get("title", ""))}
        if row.get("kind") != "release" or not (voice["artist"] and voice["release"]):
            continue
        if row.get("fingerprint") in used:
            posted.add(_voice_key(voice))
            continue
        released = state._parse(row.get("released_at") or "")
        if released is None or released.date() > now.date() or now - released > cutoff:
            continue
        seen = cache.get(_voice_key(voice)) or {}
        searched = state._parse(seen.get("at", ""))
        if seen.get("voice") or (searched and now - searched < retry):
            continue
        tracked = row.get("tracked") or voice["artist"]
        voice["names"] = [tracked, *(artists.get(tracked, {}).get("aliases") or [])]
        wanted.setdefault(_voice_key(voice), voice)
    return [voice for key, voice in wanted.items() if key not in posted]


def _wanted() -> dict[str, dict]:
    """voices_wanted по файлам состояния: {ключ: релиз}."""
    rows = list(state.read_jsonl(config.INBOX_FILE))
    artists = {a["name"]: a for a in state.read_json(config.ARTISTS_FILE, {"artists": []})["artists"]}
    found = voices_wanted(rows, set(state.read_json(config.USED_INBOX_FILE, [])),
                          state.read_json(config.WEB_VOICE_FILE, {}), artists)
    return {_voice_key(v): v for v in found}


def _voice_shape(voice) -> str:
    """Что не так с мнением по форме. Пустая строка — годно; правду сверит --apply."""
    if not isinstance(voice, dict):
        return "мнение — это объект"
    missing = [field for field in ("artist", "release") if not _filled(voice.get(field))]
    if missing:
        return "нет " + ", ".join(missing)
    url, quote = voice.get("url", ""), voice.get("quote", "")
    if not isinstance(url, str) or not isinstance(quote, str):
        return "url и quote — строки"
    if url and not url.startswith(("http://", "https://")):
        return "url: адрес страницы http(s)://…, а не нашлось ничего — пустая строка"
    if url and not quote.strip():
        return "нет quote — дословной цитаты с этой страницы"
    if quote.strip() and not url:
        return "quote без url: код сверит цитату только со страницей"
    if voice.get("by", "") not in BY:
        return "by: critic или listener"
    return ""


def trusted() -> list[str]:
    """Сайты, чьей странице верим как источнику связи: config.LINEAGE_SITES и издания,
    которым уже верит сбор, — включённые ленты data/feeds.json и сайты его Telegram-каналов."""
    feeds = state.read_json(config.DATA / "feeds.json", {})
    hosts = [urlparse(feed.get("url", "")).netloc for feed in feeds.get("feeds", []) if feed.get("enabled")]
    hosts += [channel.get("site", "") for channel in feeds.get("telegram", []) if channel.get("enabled")]
    return sorted({*config.LINEAGE_SITES, *(re.sub(r"^www\.", "", host.lower()) for host in hosts if host)})


def _trusted(url: str, sites: list[str]) -> bool:
    host = urlparse(url).netloc.lower().split(":")[0]
    return any(host == site or host.endswith("." + site) for site in sites)


def _digits(text: str) -> set[str]:
    return set(re.findall(r"\d+", text))


def _link_artists(link: dict) -> set[str]:
    """Артисты связи, как их сравнивать: концы и поле artist."""
    names = [link.get("artist", ""), *(end.get("artist", "") for end in link.get("ends") or [])]
    return {quality.norm(name) for name in names if name}


def _link_id(link: dict) -> str:
    return "--".join("-".join(re.findall(r"\w+", end["artist"].casefold())) for end in link["ends"])


def lineage_need(base: dict) -> int:
    """Сколько новых связей искать сейчас. Ноль — рутина не ищет и лимиты подписки не тратит.

    Нужна, когда нерассказанных меньше config.LINEAGE_MIN_UNTOLD, и не больше
    LINEAGE_PER_WEEK за неделю. Искали меньше LINEAGE_RETRY_HOURS назад — тоже ноль:
    рутина ходит каждые два часа, и без этого пустой поиск повторялся бы каждым проходом.
    """
    now = state.now()

    def within(stamp, **span) -> bool:
        moment = state._parse(stamp or "")
        return moment is not None and now - moment < timedelta(**span)

    if within(base.get("searched_at"), hours=config.LINEAGE_RETRY_HOURS):
        return 0
    links, done = base.get("links", []), state.told_links()
    untold = sum(link.get("id") not in done for link in links)
    recent = sum(within(link.get("added_at"), days=7) for link in links)
    return max(0, min(config.LINEAGE_MIN_UNTOLD - untold, config.LINEAGE_PER_WEEK - recent))


def _link_shape(link, sites: list[str]) -> str:
    """Что не так со связью, насколько это видно без сети. Пустая строка — годно;
    цитату на странице и треки в Deezer сверит --apply.

    Числа — только из цитат: год и счёт модель выдумывает первыми, а придуманный год
    убивает доверие быстрее всего. Числа прописью («в девяностых») так не поймать.
    """
    if not isinstance(link, dict):
        return "связь — это объект"
    missing = [field for field in ("modern", "ancestor", "connection") if not _filled(link.get(field))]
    if missing:
        return "нет " + ", ".join(missing)
    if link.get("kind") not in LINK_KINDS:
        return f"kind: {', '.join(LINK_KINDS)} — «звучит похоже» и общий жанр не связь"
    ends = link.get("ends")
    if not (isinstance(ends, list) and len(ends) == 2 and all(
            isinstance(end, dict) and _filled(end.get("artist")) and _filled(end.get("track"))
            and isinstance(end.get("url"), str) and DEEZER_TRACK.fullmatch(end["url"]) for end in ends)):
        return "ends: два конца, корень и наследник, у каждого artist, track и url — https://www.deezer.com/track/…"
    if len(_link_artists({"ends": ends})) < 2:
        return "ends: корень и наследник — один и тот же артист"
    facts = link.get("facts")
    if not (isinstance(facts, list) and 1 <= len(facts) <= LINK_FACTS):
        return f"facts: от 1 до {LINK_FACTS} фактов"
    quotes = ""
    named = _digits(" ".join(f"{end['artist']} {end['track']}" for end in ends))  # «Three 6 Mafia» — не год
    for fact in facts:
        if not (isinstance(fact, dict) and _filled(fact.get("text"))
                and isinstance(fact.get("sources"), list) and fact["sources"]):
            return "facts: у каждого факта text и sources — хотя бы один источник"
        for source in fact["sources"]:
            if not (isinstance(source, dict) and _filled(source.get("url")) and _filled(source.get("quote"))
                    and source["url"].startswith(("http://", "https://"))):
                return "sources: url страницы http(s)://… и quote — дословная цитата с неё"
            if not _trusted(source["url"], sites):
                return f"{urlparse(source['url']).netloc}: этого сайта нет в списке sites из --lineage"
            if not LINK_QUOTE[0] <= len(source["quote"].strip()) <= LINK_QUOTE[1]:
                return f"quote: {LINK_QUOTE[0]}–{LINK_QUOTE[1]} знаков"
        own = " ".join(source["quote"] for source in fact["sources"])
        if extra := _digits(fact["text"]) - _digits(own) - named:
            return f"факт «{fact['text'][:40]}»: чисел {', '.join(sorted(extra))} нет в его цитатах"
        quotes += " " + own
    said = " ".join(link[field] for field in ("modern", "ancestor", "connection"))
    if extra := _digits(said) - _digits(quotes) - named:
        return f"modern, ancestor, connection: чисел {', '.join(sorted(extra))} нет в цитатах"
    return ""


def _words(text: str) -> str:
    """Одни буквы и цифры подряд — для сверки цитаты со страницей по словам.

    Точного совпадения с пробелами и знаками, как у мнений (web_voice.verify), тут мало:
    в Википедии почти каждая фраза идёт через ссылки и сноски, вместо тегов встают пробелы
    («Paris , [ 29 ] Three 6 Mafia , UGK»), и списанная со страницы цитата не находилась бы.
    Слова и их порядок остаются дословными, сноски в скобках выпадают с обеих сторон.
    """
    return "".join(re.findall(r"\w+", re.sub(r"\[[^\]]{0,20}\]", " ", quality.norm(text))))


def _named(name: str, text: str) -> bool:
    return bool(re.search(rf"(?<!\w){re.escape(quality.norm(name))}(?!\w)", text))


def _unproven(link: dict, sites: list[str], aliases: dict[str, list[str]], from_link, bare, page) -> str:
    """Почему связи нельзя верить; пустая строка — подтвердилась. Тут вся сеть.

    Рутине верим не больше, чем модели, которая пишет посты: треки по ссылкам сверяет
    Deezer, страницу код качает сам и цитату ищет на ней слово в слово (как
    web_voice.verify). И хотя бы одна цитата должна связывать обоих: каждый артист
    назван в ней или в заголовке её страницы — иначе из двух правдивых цитат о разных
    людях складывается выдуманная связь между ними.
    """
    for end in link["ends"]:
        found = from_link(end["url"])
        if not (quality.norm(found.get("artist", "")) == quality.norm(end["artist"])
                and bare(found.get("title", "")) == bare(end["track"])):
            return f"трек «{end['artist']} — {end['track']}» по ссылке Deezer не подтвердился"
    spellings = [[end["artist"], *aliases.get(end["artist"], [])] for end in link["ends"]]
    pages: dict[str, tuple[str, str] | None] = {}
    tied = False
    for source in (source for fact in link["facts"] for source in fact["sources"]):
        url = source["url"]
        if url not in pages:
            got = page(url)
            # Переадресация могла увести на чужой сайт — такой странице не верим тоже.
            pages[url] = (quality.norm(got[1]), _words(got[2])) if got and _trusted(got[0], sites) else None
        if pages[url] is None:
            return f"страница {url} не скачалась"
        title, text = pages[url]
        if _words(source["quote"]) not in text:
            return f"цитаты нет на странице {url} слово в слово"
        quote = quality.norm(source["quote"])
        tied = tied or all(any(_named(name, quote) or _named(name, title) for name in names) for names in spellings)
    return "" if tied else "ни одна цитата не называет обоих артистов — в самой цитате или в заголовке страницы"


def _stored(link: dict) -> dict:
    """Запись базы из находки рутины. facts остаются строками: их читают клипы и модель,
    а адреса и цитаты лежат рядом в sources — по ним связь можно перепроверить руками."""
    root, heir = link["ends"]
    return {
        "id": _link_id(link), "by": "auto", "added_at": state.iso(), "kind": link["kind"],
        "modern": link["modern"].strip(), "ancestor": link["ancestor"].strip(),
        "connection": link["connection"].strip(),
        "facts": [fact["text"].strip() for fact in link["facts"]],
        # Лицо поста — наследник: по этому полю card.cover ищет фотографию.
        "artist": heir["artist"],
        "ends": [{field: end[field] for field in ("artist", "track", "url")} for end in (root, heir)],
        "sources": [{"fact": fact["text"].strip(), "url": source["url"], "quote": source["quote"].strip()}
                    for fact in link["facts"] for source in fact["sources"]],
    }


def _links(found: list[dict], dry_run: bool) -> None:
    """Новые связи из файла — в data/lineage.json, откуда их берёт следующий compose.

    Не прошла проверку — строка в лог, а не красный запуск и не письмо владельцу: это
    промах автора, а не поломка. Артист, который в базе уже есть, второй раз не берётся,
    даже в паре с новым: шесть постов про Мемфис и Three 6 Mafia читались как один
    и тот же, а повтор хуже молчания (владелец, 01.10.2026). Ручные связи не трогаются:
    запись только дописывается. Проход запоминается и пустым — иначе искали бы каждые два часа.
    """
    base = state.read_json(config.LINEAGE_FILE, {"links": []})
    need = lineage_need(base)
    taken = {name for link in base["links"] for name in _link_artists(link)}
    ids = {link.get("id") for link in base["links"]}
    if not dry_run:
        # Не наверху: --check и --lineage зовёт облачный автор, а эти модули тянут requests.
        from . import otbor
        from .sources import web_voice

        aliases = {a["name"]: a.get("aliases") or []
                   for a in state.read_json(config.ARTISTS_FILE, {"artists": []})["artists"]}
        sites = trusted()
    for link in found:
        name = " → ".join(end["artist"] for end in link["ends"])
        why = ("связь сейчас не нужна" if need <= 0
               else "артист уже есть в базе связей" if _link_artists(link) & taken or _link_id(link) in ids
               else "" if dry_run else _unproven(link, sites, aliases, otbor.from_link, otbor._bare, web_voice.page))
        if why:
            print(f"  — связь «{name}»: {why}")
            continue
        if dry_run:
            print(f"  связь «{name}»: сверилась бы с Deezer и страницами источников")
            continue
        base["links"].append(_stored(link))
        taken |= _link_artists(link)
        need -= 1
        print(f"  связь «{name}» принята: {link['connection']}")
    if not dry_run:
        base["searched_at"] = state.iso()
        # Не state.write_json: тот сортирует ключи, а файл правят и читают руками.
        config.LINEAGE_FILE.write_text(json.dumps(base, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def check(review, name: str = "") -> tuple[list[str], dict[int, str]]:
    """Ошибки файла правок и пропуски — {номер правки с нуля: почему}.

    Ошибка — файл сделан неверно, применять его нельзя. Пропуск — правка годна
    по форме, но пост вышел, снят или поменялся. На снимке рутины пропуск —
    тоже ошибка (пост там лежит ровно как она его читала, значит, неверны путь
    или цитата), а на свежем main — обычная гонка, и правка просто не нужна.
    """
    if not (isinstance(review, dict) and all(isinstance(review.get(field, []), list)
                                            for field in ("edits", "voices", "lineage"))):
        return ['файл правок — объект {"edits": [...], "voices": [...], "lineage": [...]}'], {}
    edits, voices, links = review.get("edits", []), review.get("voices", []), review.get("lineage", [])
    errors: list[str] = []
    skipped: dict[int, str] = {}
    if name and not ID_FORMAT.fullmatch(name):
        errors.append(f"имя файла «{name}»: ГГГГММДД-ЧЧММ, например 20260912-0835")
    # Пустой lineage — годный файл: связь искали и не нашли, и проход надо запомнить.
    if not edits and not voices and "lineage" not in review:
        errors.append("edits и voices пусты — без выдумок и мнений файл не пушится")
    sites = trusted()
    errors += [f"связь {index + 1}: {wrong}" for index, link in enumerate(links) if (wrong := _link_shape(link, sites))]
    if len(links) > config.LINEAGE_PER_WEEK:
        errors.append(f"связей больше {config.LINEAGE_PER_WEEK} — столько за проход не берём")
    shapes = [_voice_shape(voice) for voice in voices]
    errors += [f"мнение {index + 1}: {wrong}" for index, wrong in enumerate(shapes) if wrong]
    if not any(shapes) and len({_voice_key(voice) for voice in voices}) > VOICES_PER_RUN:
        errors.append(f"мнения о больше чем {VOICES_PER_RUN} релизах — столько за проход не ищем")
    files = [edit.get("file") for edit in edits if isinstance(edit, dict)]
    for index, edit in enumerate(edits):
        where = f"правка {index + 1}"
        wrong = _shape(edit)
        # Две правки одного поста: вторая молча затёрла бы первую.
        if not wrong and files.count(edit["file"]) > 1:
            wrong = f"{edit['file']} второй раз — одна правка на пост, все его выдумки в одном text"
        if wrong:
            errors.append(f"{where}: {wrong}")
            continue
        post, reason = _post(edit)
        if post is not None and plain(edit["fragment"]) not in plain(post.get("text", "")):
            post, reason = None, "цитаты fragment нет в тексте поста — не дословно или пост поменялся"
        if post is None:
            skipped[index] = reason
            continue
        errors += [f"{where}: {problem}" for problem in _text_problems(post, edit)]
    return errors, skipped


def _write(edit: dict, path: Path) -> str:
    """Пишет одну правку. Непустая строка — канал её не принял, и почему."""
    if edit["action"] == "drop":
        path.unlink()
        return ""
    post = {**json.loads(path.read_text(encoding="utf-8")), "text": edit["text"]}
    if path.parent == config.ARCHIVE:
        # Не наверху: --check зовёт облачный автор, а publish тянет requests и Pillow.
        from . import publish, telegram

        try:
            publish.edit(post)
        except telegram.TelegramError as exc:
            # «not modified» — этот текст уже в канале: прошлый запуск поправил,
            # а коммит не дошёл. «not found» — пост удалили руками. Остальное — поломка.
            if "message is not modified" not in str(exc) and "message to edit not found" not in str(exc):
                return f"в канале не поправлен — {exc}"
    state.write_json(path, post)
    return ""


def apply(review, name: str, dry_run: bool) -> int:
    """Применяет правки: очередь переписывает и снимает, вышедшее правит в канале.
    1 — файл битый и не тронуто ничего, или канал не принял правку.

    Сначала проверяется весь файл, потом пишется: применённый наполовину файл
    хуже неприменённого — следующий проход рутины не узнает, какая половина
    осталась. Отказ канала — не порок файла: годные правки рядом применяются.
    """
    errors, skipped = check(review, name)
    for error in errors:
        print(f"  ✗ {error}")
    if errors:
        print(f"Правки {name} не применены: ошибок {len(errors)}.")
        return 1

    done = failed = 0
    for index, edit in enumerate(review.get("edits", [])):
        path = _current(edit["file"])
        if index in skipped:
            print(f"  — {path.name}: {skipped[index]}")
            continue
        problem = "" if dry_run else _write(edit, path)
        if problem:
            print(f"  ✗ {path.name}: {problem}")
            failed += 1
            continue
        what = "снят" if edit["action"] == "drop" else "поправлен в канале" if path.parent == config.ARCHIVE else "переписан"
        print(f"  {what} {path.name}: {edit['why']}")
        done += 1
    print(f"{'Применилось бы' if dry_run else 'Применено'} правок: {done}, пропущено: {len(skipped)}, "
          f"не принял канал: {failed}.")
    if review.get("voices"):
        _voices(review["voices"], dry_run)
    if "lineage" in review:
        _links(review["lineage"], dry_run)
    return 1 if failed else 0


def _voices(voices: list[dict], dry_run: bool) -> None:
    """Мнения из файла — в data/web_voice.json, откуда их берёт следующий compose --fresh.

    Цитату принимает только web_voice.accept: страницу он качает сам и ищет
    цитату в тексте дословно. Не подтвердилась — строка в лог, а не красный
    запуск: это ошибка автора, а не поломка, и промах запомнится. Релиз, который
    мнения уже не ждёт (пост написан, срок вышел, искали недавно), пропускается
    без сети — так же и выдуманный рутиной артист в кэш не попадёт.
    """
    wanted = _wanted()
    found: dict[str, list[dict]] = {}
    for voice in voices:
        found.setdefault(_voice_key(voice), []).append(voice)
    if not dry_run:
        # Не наверху: --check и --voices зовёт облачный автор, а web_voice тянет requests.
        from .sources import web_voice
    for key, items in found.items():
        name = f"{items[0]['artist']} — {items[0]['release']}"
        release = wanted.get(key)
        if release is None:
            print(f"  — мнение о «{name}»: релиз мнения уже не ждёт")
            continue
        pages = [item for item in items if item.get("url")]
        if dry_run:
            print(f"  мнение о «{name}»: сверилось бы со страниц: {len(pages)}")
            continue
        voice = web_voice.accept(release["artist"], release["release"], pages, release["names"])
        if voice:
            print(f"  мнение о «{name}»: {voice['who']} — «{voice['text']}»")
        else:
            print(f"  мнение о «{name}»: {'цитата на странице не подтвердилась' if pages else 'не нашлось'}"
                  " — запомнено, повтор не раньше чем через "
                  f"{config.WEB_VOICE_RETRY_HOURS} ч")


def _selftest() -> None:
    """Без сети, во временной папке: правка, снятие, отказ на битом тексте,
    вышедший пост — правка в канале, отказ канала и пропуск без сообщения;
    мнения — форма, список релизов и сверка со страницей-заглушкой.

    Запуск: python -m src.review --selftest
    """
    import contextlib
    import io
    import tempfile
    from unittest import mock

    from . import publish, telegram
    from .sources import web_voice

    button = '▸ <a href="https://music.apple.com/us/album/x/6809882935">Слушать в Apple Music</a>'
    # Живой пример из очереди 11.09.2026: содержание трека, который никто не слушал.
    old = (
        "<b>NKEEEI & YANIX СДЕЛАЛИ ТРЕК-ПРИЗНАНИЕ</b>\n\n"
        "У nkeeei и Yanix вышел сингл <i>Поцелуи</i>: короткий и лишённый драмы.\n\n"
        "<blockquote>Получилось тепло и искренне. Без пафоса и драм.</blockquote>\n\n" + button
    )
    new = (
        "<b>NKEEEI И YANIX ВЫПУСТИЛИ СИНГЛ ПОЦЕЛУИ</b>\n\n"
        "У nkeeei и Yanix вышел сингл <i>Поцелуи</i>.\n\n"
        "<blockquote>Два имени на обложке, один трек — поделить его ещё предстоит.</blockquote>\n\n" + button
    )
    name = "20260912-0835"
    fix = {"file": "content/queue/a-verdict.json", "action": "rewrite", "text": new,
           "fragment": "Получилось тепло и искренне.", "why": "в inbox только название, 2:05 и жанр"}
    drop = {"file": "content/queue/b-meme.json", "action": "drop",
            "fragment": "Bones выпустил 90 альбомов", "why": "числа альбомов нет в данных"}

    def post_of(path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def refused(word: str, review: dict | None = None, file_name: str = name, **change) -> None:
        errors, skipped = check(review or {"edits": [{**fix, **change}]}, file_name)
        found = errors + list(skipped.values())
        assert any(word in problem for problem in found), (word, found)

    saved = config.ROOT, config.ARCHIVE
    with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
        config.ROOT, config.ARCHIVE = Path(tmp), Path(tmp) / "content" / "archive"
        queue = config.ROOT / "content" / "queue"
        try:
            state.write_json(queue / "a-verdict.json", {"rubric": "verdict", "artist": "nkeeei & Yanix", "text": old})
            state.write_json(queue / "b-meme.json",
                             {"rubric": "meme", "text": "Bones выпустил 90 альбомов за год. Я — ни одного плейлиста."})
            state.write_json(config.ARCHIVE / "c-release.json", {"rubric": "release", "text": old})

            good = {"edits": [fix, drop]}
            assert check(good, name) == ([], {}), check(good, name)
            # Цитату ищут без разметки, регистра и «ё»: переписанная глазами находится.
            assert plain("сингл ПОЦЕЛУИ: короткий и лишенный") in plain(old)

            refused("ГГГГММДД-ЧЧММ", file_name="20260912")
            refused("edits и voices пусты", {"edits": [], "voices": []})
            refused("объект", {"edits": {}})
            refused("путь поста", file="content/queue/../../.env")
            refused("rewrite или drop", action="fix")
            refused("нет why", why=" ")
            refused("нет text", text="")
            refused("цитаты fragment нет", fragment="жёсткий ритм")
            refused("осталась", text=old)
            refused("одна правка на пост", {"edits": [fix, fix]})
            # Отказ на битом тексте: заголовок пропал, кнопка пропала, реферат.
            refused("заголовком <b>", text=new.replace("<b>", "").replace("</b>", ""))
            refused("строки кнопки нет", text=new.replace(button, "Слушать"))
            refused("запрещённый оборот", text=new.replace("<i>Поцелуи</i>.", "<i>Поцелуи</i>. Стоит отметить, что это сингл."))
            refused("только drop", {"edits": [{**drop, "action": "rewrite", "text": "Подпись без выдумки и без шутки."}]})
            refused("только для поста в очереди", {"edits": [{**drop, "file": "content/archive/c-release.json"}]})
            # Вышедший пост без записанного сообщения править не с чем: пропуск с причиной.
            refused("не записано", file="content/archive/c-release.json")

            # Сухой прогон не трогает ничего.
            assert apply(good, name, dry_run=True) == 0
            assert post_of(queue / "a-verdict.json")["text"] == old and (queue / "b-meme.json").is_file()

            # Битый текст — не пишется ничего, даже годное снятие рядом.
            assert apply({"edits": [{**fix, "text": new.replace(button, "")}, drop]}, name, dry_run=False) == 1
            assert post_of(queue / "a-verdict.json")["text"] == old and (queue / "b-meme.json").is_file()

            # Пост вышел между проходом рутины и применением — пропуск, остальное применяется.
            state.write_json(queue / "d-verdict.json", {"rubric": "verdict", "text": old})
            late = {**fix, "file": "content/queue/d-verdict.json"}
            assert check({"edits": [late]}, name) == ([], {})
            (queue / "d-verdict.json").rename(config.ARCHIVE / "d-verdict.json")
            assert apply({"edits": [fix, drop, late]}, name, dry_run=False) == 0
            rewritten = post_of(queue / "a-verdict.json")
            assert rewritten == {"rubric": "verdict", "artist": "nkeeei & Yanix", "text": new}, rewritten
            assert not (queue / "b-meme.json").exists()
            assert post_of(config.ARCHIVE / "d-verdict.json")["text"] == old

            # Перезапуск воркфлоу: пост уже переписан, мем снят — пропуски, а не красный запуск.
            assert apply(good, name, dry_run=False) == 0
            assert post_of(queue / "a-verdict.json")["text"] == new

            # Вышедший пост с записанным сообщением правится в канале: строка «▸ Слушать…»
            # в подписи развёрнута в площадки, кнопки старого поста на месте (правка без
            # reply_markup их сняла бы), в архиве — новый текст.
            message = {"chat": -100, "message_id": 5, "kind": "caption", "buttons": [[{"text": "Apple", "url": "a"}]]}
            released = {"rubric": "verdict", "artist": "nkeeei & Yanix", "text": old, "message": message,
                        "links": {"nkeeei": 1}}
            state.write_json(config.ARCHIVE / "e-verdict.json", released)
            out = {**fix, "file": "content/archive/e-verdict.json"}
            assert check({"edits": [out]}, name) == ([], {})
            refused("снять нельзя", {"edits": [{**drop, "file": "content/queue/e-verdict.json"}]})
            edited = []
            with (mock.patch.object(publish, "release_title", lambda post: ""),
                  mock.patch.object(telegram, "edit_caption", lambda *args, **kw: edited.append((*args, kw)))):
                assert apply({"edits": [out]}, name, dry_run=False) == 0
            assert len(edited) == 1 and edited[0][0::3] == (-100, {"buttons": message["buttons"]}), edited
            caption = edited[0][2]
            # Имена — ссылками на карточку артиста: их ставит правка, в тексте архива их нет (publish.artist_links).
            assert f'<a href="{publish.ARTIST_LINK.format(1)}">nkeeei</a>' in caption, caption
            bare = re.sub(r'<a href="[^"]*\?start=a_\d+">([^<]*)</a>', r"\1", caption)
            assert bare.startswith(new.replace("\n\n" + button, "")) and button not in bare, caption
            assert "\n\n▸ Слушать:\n<a href=" in caption, caption
            assert post_of(config.ARCHIVE / "e-verdict.json") == {**released, "text": new}

            # Канал не принял — запуск красный, архив прежний. Тот же текст уже в канале
            # (прошлый запуск поправил, коммит не дошёл) — это успех.
            for error, code, text in (("Forbidden: not enough rights", 1, old), ("message is not modified", 0, new),
                                      ("message to edit not found", 0, new)):
                state.write_json(config.ARCHIVE / "e-verdict.json", released)

                def refuse(*_, error=error, **__):
                    raise telegram.TelegramError(f"editMessageCaption: Bad Request: {error}")

                with (mock.patch.object(publish, "release_title", lambda post: ""),
                      mock.patch.object(telegram, "edit_caption", refuse)):
                    assert apply({"edits": [out]}, name, dry_run=False) == code, error
                assert post_of(config.ARCHIVE / "e-verdict.json")["text"] == text, error

            # Пост, собранный шаблоном, не правится: в ПАМЯТКЕ цитата закона, и правка её переписала бы.
            # Это пропуск — годная правка рядом применяется, канал не тронут, архив прежний.
            state.write_json(config.ARCHIVE / "e-verdict.json", released)
            for rubric in TEMPLATE:
                memo = {"rubric": rubric, "text": old, "message": message}
                state.write_json(config.ARCHIVE / f"{rubric}-free.json", memo)
                law = {**fix, "file": f"content/archive/{rubric}-free.json"}
                assert check({"edits": [law]}, name) == ([], {0: f"{rubric} собран шаблоном без модели — не правится"})
            edited = []
            with (mock.patch.object(publish, "release_title", lambda post: ""),
                  mock.patch.object(telegram, "edit_caption", lambda *args, **kw: edited.append(args[1]))):
                assert apply({"edits": [law, out]}, name, dry_run=False) == 0
            assert edited == [5] and post_of(config.ARCHIVE / "e-verdict.json")["text"] == new, edited
            assert all(post_of(config.ARCHIVE / f"{rubric}-free.json")["text"] == old for rubric in TEMPLATE)

            # Мнения о релизах — второй вид правки. Файл с одними voices годен,
            # битая форма — нет; правду цитаты --check не знает, её сверяет --apply.
            quote = "Ghost Mountain makes Winchester the heaviest thing he has made this year."
            voice = {"artist": "Ghost Mountain", "release": "Winchester",
                     "url": "https://pitchfork.com/reviews/winchester", "quote": quote, "by": "critic"}
            assert check({"voices": [voice]}, name) == ([], {})
            assert check({"voices": [{**voice, "url": "", "quote": ""}]}, name) == ([], {}), "промах годен"
            refused("объект", {"voices": {}})
            refused("нет release", {"voices": [{**voice, "release": " "}]})
            refused("http", {"voices": [{**voice, "url": "pitchfork.com/reviews"}]})
            refused("нет quote", {"voices": [{**voice, "quote": ""}]})
            refused("quote без url", {"voices": [{**voice, "url": ""}]})
            refused("critic или listener", {"voices": [{**voice, "by": "editor"}]})
            refused("за проход", {"voices": [{**voice, "release": str(n)} for n in range(VOICES_PER_RUN + 1)]})

            data = config.ROOT / "data"
            today = state.iso()
            state.append_jsonl(data / "inbox.jsonl", [
                {"kind": "release", "fingerprint": f, "artist": a, "title": t, "released_at": when, "score": 50}
                for f, a, t, when in (("gm", "Ghost Mountain", "Winchester - Single", today),
                                      ("old", "Yeat", "COCOON", state.iso(state.now() - timedelta(days=2))),
                                      ("done", "Bones", "Rot", today), ("done2", "Bones", "Rot - Single", today))])
            state.write_json(data / "used_inbox.json", ["done"])
            key = quality.norm("Ghost Mountain — Winchester")
            html_page = f"<title>Ghost Mountain – Winchester review</title><p>{quote}</p>"
            with (mock.patch.multiple(config, INBOX_FILE=data / "inbox.jsonl", USED_INBOX_FILE=data / "used_inbox.json",
                                      WEB_VOICE_FILE=data / "web_voice.json", ARTISTS_FILE=data / "artists.json"),
                  mock.patch.object(web_voice, "page",
                                    lambda url: (url, "Ghost Mountain – Winchester review", quality.norm(html_page)))):
                # Старое, с постом и дубль второго магазина под постом — не ищем.
                assert list(_wanted()) == [key], _wanted()
                lie = {**voice, "quote": "Winchester is the best song of the whole decade, no question."}
                # Цитаты нет на странице — не принята, запуск не красный, промах запомнен.
                assert apply({"voices": [lie]}, name, dry_run=False) == 0
                assert state.read_json(config.WEB_VOICE_FILE, {})[key]["voice"] == {} and _wanted() == {}
                cache = state.read_json(config.WEB_VOICE_FILE, {})
                cache[key]["at"] = state.iso(state.now() - timedelta(hours=config.WEB_VOICE_RETRY_HOURS + 1))
                state.write_json(config.WEB_VOICE_FILE, cache)
                # Через срок повтора — снова в списке; дословная цитата со страницы принята.
                assert apply({"voices": [lie, voice]}, name, dry_run=False) == 0
                assert state.read_json(config.WEB_VOICE_FILE, {})[key]["voice"] == {"who": "Pitchfork", "text": quote}
                # Выдуманный рутиной релиз в кэш не попадает.
                assert apply({"voices": [{**voice, "artist": "Nobody"}]}, name, dry_run=False) == 0
                assert list(state.read_json(config.WEB_VOICE_FILE, {})) == [key]

            # Новые связи ОТКУДА НОГИ — третий вид правки. Форму, сайт и числа видит --check,
            # страницу, цитату на ней и треки в Deezer — только --apply.
            said = "Molchat Doma have named Kino as their main influence since the first album in 2017."
            wiki = "https://en.wikipedia.org/wiki/Molchat_Doma"
            link = {"kind": "said", "modern": "Molchat Doma", "ancestor": "Kino", "connection": "сами называют главным влиянием",
                    "ends": [{"artist": "Kino", "track": "Gruppa krovi", "url": "https://www.deezer.com/track/1"},
                             {"artist": "Molchat Doma", "track": "Sudno", "url": "https://www.deezer.com/track/2"}],
                    "facts": [{"text": "Первый альбом вышел в 2017 году", "sources": [{"url": wiki, "quote": said}]}]}

            def change(**fields) -> dict:
                return {"lineage": [{**link, **fields}]}

            def fact(text: str = link["facts"][0]["text"], url: str = wiki, quote: str = said) -> dict:
                return change(facts=[{"text": text, "sources": [{"url": url, "quote": quote}]}])

            state.write_json(data / "feeds.json", {
                "feeds": [{"url": "https://www.pitchfork.com/feed", "enabled": True},
                          {"url": "https://dead.example/rss", "enabled": False}],
                "telegram": [{"site": "the-flow.ru", "enabled": True}, {"channel": "rapsmi", "enabled": True}]})
            base = {"links": [{"id": "hand", "modern": "Bones", "ends": [{"artist": "Bones"}], "facts": ["Сам"]},
                              {"id": "old", "modern": "Korn", "artist": "Korn"}]}
            state.write_json(data / "lineage.json", base)
            pages = {wiki: (wiki, "Molchat Doma - Wikipedia", quality.norm(f"<p>{said}</p> Bones met Korn in a studio once."))}
            tracks = {"https://www.deezer.com/track/1": {"artist": "Kino", "title": "Gruppa krovi (Remastered)"},
                      "https://www.deezer.com/track/2": {"artist": "Molchat Doma", "title": "Sudno"}}

            def answer(review: dict) -> str:
                with contextlib.redirect_stdout(io.StringIO()) as out:
                    assert apply(review, name, dry_run=False) == 0  # отказ связи — не красный запуск
                return out.getvalue()

            def stored() -> dict:
                return state.read_json(config.LINEAGE_FILE, {})

            def forget() -> None:  # как будто прошлый поиск был давно
                state.write_json(config.LINEAGE_FILE, {**stored(), "searched_at": ""})

            from . import otbor

            with (mock.patch.multiple(config, DATA=data, LINEAGE_FILE=data / "lineage.json", QUEUE=queue,
                                      ARTISTS_FILE=data / "artists.json"),
                  mock.patch.object(web_voice, "page", pages.get),
                  mock.patch.object(otbor, "from_link", lambda url: tracks.get(url, {}))):
                assert trusted() == ["pitchfork.com", "the-flow.ru", "wikipedia.org"], trusted()
                # Википедия: ссылки и сноски рвут фразу пробелами — цитата находится по словам.
                assert _words("Paris,[29] Three 6 Mafia, UGK") in _words("paris , [ 29 ] three 6 mafia , ugk , big l")
                assert _words("Three 6 Mafia and UGK") not in _words("paris , [ 29 ] three 6 mafia , ugk , big l")
                assert check({"lineage": [link]}, name) == ([], {}), check({"lineage": [link]}, name)
                assert check({"lineage": []}, name) == ([], {}), "искали и не нашли — годный файл"
                refused("объект", {"lineage": {}})
                refused("не связь", change(kind="similar"))
                refused("нет connection", change(connection=""))
                refused("два конца", change(ends=link["ends"][:1]))
                refused("два конца", change(ends=[link["ends"][0], {"artist": "Molchat Doma", "track": "Sudno", "url": "d/2"}]))
                refused("один и тот же", change(ends=[link["ends"][0], {**link["ends"][1], "artist": "KINO"}]))
                refused("хотя бы один источник", change(facts=[{"text": "Факт", "sources": []}]))
                refused("нет в списке sites", fact(url="https://someblog.example/kino"))  # чужой домен
                refused("нет в списке sites", fact(url="https://notwikipedia.org/wiki/Kino"))
                refused("чисел 1984", fact(text="Kino собрались в 1984 году"))  # года нет в цитате
                refused("чисел 80", change(connection="звук 80-х"))
                refused("знаков", fact(quote="Kino."))
                refused("за проход", {"lineage": [link] * (config.LINEAGE_PER_WEEK + 1)})
                assert _link_shape({**link, "ancestor": "Three 6 Mafia", "ends": [
                    {**link["ends"][0], "artist": "Three 6 Mafia"}, link["ends"][1]]}, trusted()) == "", "цифра в имени — не год"

                # Обе связи базы не рассказаны — искать незачем, и готовая связь не берётся.
                assert lineage_need(stored()) == 0
                assert "сейчас не нужна" in answer({"lineage": [link]}) and len(stored()["links"]) == 2
                state.write_json(config.ARCHIVE / "1-lineage.json", {"link": "hand"})
                state.write_json(queue / "2-lineage.json", {"link": "old"})
                # Проход запомнен: сутки не ищем, даже когда связи кончились.
                assert lineage_need(stored()) == 0
                forget()
                assert lineage_need(stored()) == config.LINEAGE_MIN_UNTOLD

                # Цитаты нет на странице — отказ, и промах запомнен.
                lie = fact(quote="Molchat Doma recorded their first album in 2017 in the flat of Kino's drummer.")
                assert "слово в слово" in answer(lie) and len(stored()["links"]) == 2
                assert lineage_need(stored()) == 0
                # Повтор: артист, о котором связь уже есть, — отказ без сети, и в паре с новым тоже.
                for taken in ("Bones", "korn"):
                    forget()
                    repeat = change(ends=[{**link["ends"][0], "artist": taken}, link["ends"][1]])
                    assert "уже есть в базе" in answer(repeat) and len(stored()["links"]) == 2, taken
                # Трек по ссылке — не тот; страница не скачалась; цитата правдива, но связывает не этих двоих.
                forget()
                assert "Deezer не подтвердился" in answer(change(ends=[{**link["ends"][0], "track": "Pachka sigaret"},
                                                                         link["ends"][1]]))
                forget()
                assert "не скачалась" in answer(fact(url="https://ru.wikipedia.org/wiki/Kino"))
                forget()
                assert "не называет обоих" in answer(fact(text="Встретились в студии", quote="Bones met Korn in a studio once."))
                # Годная: дописана к ручным, те не тронуты, facts — строки, как их читают клипы.
                forget()
                assert "принята" in answer({"lineage": [link]})
                hand, old_link, auto = stored()["links"]
                assert [hand, old_link] == base["links"], "ручные связи не переписываются"
                assert (auto["id"], auto["by"], auto["artist"]) == ("kino--molchat-doma", "auto", "Molchat Doma"), auto
                assert auto["facts"] == ["Первый альбом вышел в 2017 году"] and auto["ends"] == link["ends"], auto
                assert auto["sources"] == [{"fact": auto["facts"][0], "url": wiki, "quote": said}], auto
                # Та же связь вторым проходом — повтор; а одна нерассказанная — искать ещё одну.
                forget()
                assert "уже есть в базе" in answer({"lineage": [link]}) and len(stored()["links"]) == 3
                forget()
                assert lineage_need(stored()) == 1
                # Две за неделю — предел, сколько бы ни было рассказано.
                state.write_json(config.LINEAGE_FILE, {"links": [auto, {**auto, "id": "second"}]})
                state.write_json(queue / "3-lineage.json", {"link": auto["id"]})
                state.write_json(queue / "4-lineage.json", {"link": "second"})
                assert lineage_need(stored()) == 0
        finally:
            config.ROOT, config.ARCHIVE = saved


def main() -> int:
    parser = argparse.ArgumentParser(description="Автопилот точности: правки выдумок в постах")
    parser.add_argument("--check", metavar="ФАЙЛ", help="проверить файл правок по постам, без сети")
    parser.add_argument("--apply", metavar="ФАЙЛ",
                        help="применить правки: переписать или снять посты очереди, поправить вышедшие в канале")
    parser.add_argument("--dry-run", action="store_true", help="с --apply: показать, что изменится, ничего не меняя")
    parser.add_argument("--voices", action="store_true",
                        help="каким свежим релизам рутине искать мнение в сети — строкой JSON на релиз, без сети")
    parser.add_argument("--lineage", action="store_true",
                        help="нужна ли ОТКУДА НОГИ новая связь: строка JSON — сколько искать, каким сайтам "
                             "верим и кто уже рассказан; пусто — не искать. Без сети")
    parser.add_argument("--selftest", action="store_true",
                        help="правка, снятие, отказ на битом тексте и правка вышедшего поста — без сети")
    args = parser.parse_args()

    if args.selftest:
        _selftest()
        print("Правка, снятие, отказ на битом тексте, правка вышедшего поста в канале, пост шаблоном (ПАМЯТКА) не правится, "
              "мнения о релизах — форма, список и сверка со страницей; новые связи — чужой сайт, "
              "число не из цитаты, цитаты нет на странице, повтор артиста, трек не тот: все проверки прошли.")
        return 0
    if args.voices:
        for voice in list(_wanted().values())[:VOICES_PER_RUN]:
            print(json.dumps(voice, ensure_ascii=False))
        return 0
    if args.lineage:
        base = state.read_json(config.LINEAGE_FILE, {"links": []})
        if need := lineage_need(base):
            names = [name for link in base["links"]
                     for name in (link.get("artist", ""), *(end.get("artist", "") for end in link.get("ends") or []))]
            print(json.dumps({"need": need, "sites": trusted(), "taken": sorted({n for n in names if n}),
                              "told": [f"{link.get('ancestor', '')} → {link.get('modern', '')}"
                                       for link in base["links"]]}, ensure_ascii=False))
        return 0
    if not (args.check or args.apply):
        parser.print_help()
        return 0

    path = Path(args.check or args.apply)
    # Не state.read_json: тот прячет битый файл в .broken и молча отдаёт пустое,
    # а проверке нужно сказать, где JSON сломан.
    try:
        review = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        print(f"Не прочитать {path}: {exc.strerror}")
        return 1
    except json.JSONDecodeError as exc:
        print(f"{path.name}: не JSON — строка {exc.lineno}, {exc.msg}")
        return 1

    if args.apply:
        config.load_dotenv()  # токен бота для правки в канале; в Actions он в окружении
        return apply(review, path.stem, args.dry_run)

    errors, skipped = check(review, path.stem)
    errors += [f"правка {index + 1}: {reason}" for index, reason in sorted(skipped.items())]
    for error in errors:
        print(f"  ✗ {error}")
    if errors:
        print(f"Правки {path.name} не годны: ошибок {len(errors)}.")
        return 1
    actions = [edit["action"] for edit in review.get("edits", [])]
    voices = review.get("voices", [])
    # Не ошибка: к применению список мог сдвинуться сам — пост написан, сутки вышли.
    wanted = _wanted()
    for voice in voices:
        if _voice_key(voice) not in wanted:
            print(f"  ! «{voice['artist']} — {voice['release']}» нет в списке --voices: "
                  "применение его пропустит — перепиши artist и release оттуда буква в букву")
    # То же со связями: проверку страниц и Deezer делает применение, а эти отказы видны уже сейчас.
    base = state.read_json(config.LINEAGE_FILE, {"links": []})
    taken = {name for link in base["links"] for name in _link_artists(link)}
    for link in review.get("lineage", []):
        name = " → ".join(end["artist"] for end in link["ends"])
        if not lineage_need(base):
            print(f"  ! связь «{name}»: --lineage пуст — связь сейчас не нужна, применение её пропустит")
        elif _link_artists(link) & taken:
            print(f"  ! связь «{name}»: артист уже есть в taken из --lineage — применение её пропустит")
    print(f"Правки {path.name} годны: переписать {actions.count('rewrite')}, снять {actions.count('drop')}, "
          f"мнений {len(voices)}, связей {len(review.get('lineage', []))}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
