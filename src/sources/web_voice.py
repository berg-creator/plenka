"""Мнение о релизе из всего интернета: ищет облачный Claude или Gemini, проверяет код.

Владелец 29.09.2026: «научись всегда находить мнения в инете сам». Новостей
The Flow и RAP.RU из сбора на все релизы не хватает, а отзыв под роликом
на YouTube находится примерно у половины. Рецензии, обсуждения на Reddit,
оценки на Album of the Year лежат по всей сети, и искать их по сайтам руками —
по парсеру на каждый. Поэтому ищет модель с поиском, и путей два.

Сейчас — облачный Claude по подписке владельца (владелец, 29.09.2026): тот же
запланированный агент, что раз в два часа проверяет посты (prompts/review.md, §6).
Список релизов ему печатает review --voices, находки он приносит полем voices
файла правок, а review --apply отдаёт их accept. Сверх подписки это не стоит
ничего, но голос доходит до поста не сразу, а следующим compose --fresh (сбор
раз в шесть часов): сингл без чужого голоса compose не помечает использованным
и пересматривает каждым сбором, пока релиз свежий. Отдельный compose --fresh
сразу после применения не зовём: сбор успевает за сутки жизни поста о релизе,
а воркфлоу разбора ключей генератора не держит.

Второй путь — Gemini с поиском Google (инструмент google_search) прямо из
compose, без нового пакета и нового ключа. Он не удалён: заработает сам, когда
владелец привяжет к ключу платёжный аккаунт (цена — ниже). Оба пути сходятся
в data/web_voice.json, и find читает его раньше проверки ключа Google: голос,
который принёс Claude, нужен и без ключа.

Модель — любая из двух — может выдумать цитату — ровно то, за что канал бракует свои посты.
Поэтому её ответ — только подсказка, где искать: код сам скачивает каждую
страницу (и названную моделью, и те, на которые она опиралась при поиске)
и принимает цитату, только если она стоит в тексте страницы слово в слово,
после сведения пробелов, кавычек, тире и «ё». Это единственная защита, и она
не зависит от того, насколько модель честна. Страница должна быть о релизе:
название релиза — в самой цитате или в заголовке страницы рядом с именем артиста.

Кто сказал — по адресу страницы, а не со слов модели: «Pitchfork», «слушатель
на Reddit». Ник автора не берётся, адрес страницы в данные не идёт.
Тексты песен (Genius и сайты текстов) и витрины магазинов — мимо: строка
песни не мнение о ней, а описание магазина — реклама. Telegram — тоже мимо:
канал в адресе бывает личным, а издания из Telegram и так приходят сбором.

Цена и главное ограничение пути Gemini. По странице цен Google на 29.09.2026 поиск Google
у моделей Gemini 3.x на бесплатном тарифе — «Not available»; на платном —
5 000 поисковых запросов в месяц бесплатно на все модели 3.x, дальше $14
за 1 000, и один запрос к модели может сделать несколько поисков. Ключ канала
бесплатный, и 29.09.2026 запрос с инструментом поиска вернул 429 («exceeded your
current quota») у 3.5 Flash и 3.1/3.5 Flash-Lite, а модели 2.5, где поиск был
бесплатным, новым ключам уже не выдаются. Значит, модуль заработает, только когда
владелец привяжет к проекту Google Cloud платёжный аккаунт. До тех пор первый
же отказ выключает поиск до конца запуска (_down): одна неудачная попытка
за сбор, а не по попытке на релиз.

Сколько он будет тратить: не больше PER_DAY (15) запросов в сутки, один релиз
не чаще раза в RETRY_HOURS, найденное помнится (data/web_voice.json) — повторный
сбор его не ищет; находки Claude в этот предел не идут. Это до ~450 запросов в месяц и поисков внутри них заметно
меньше бесплатных 5 000. Ищет хвост запасного списка моделей (MODELS),
а не основная модель, которая пишет посты. Gemini из России не отвечает,
поэтому проверить модуль вживую можно только из GitHub Actions.

Отвергнуто: Claude через API прямо в конвейере — дороже подписки, которая уже
оплачена (как у автопилота точности, src/review.py); свой поисковик (API Google Custom Search — отдельный ключ и 100 запросов
в сутки; скрейпинг выдачи из датацентра — капча) и Reddit напрямую (из датацентров
отвечает отказом и без OAuth не пускает).

    python -m src.sources.web_voice --check "Buckshot & Ghost Mountain" "Winchester"   только из Actions
    python -m src.sources.web_voice --selftest
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
import sys
from datetime import timedelta
from urllib.parse import urlparse

from .. import config, state
from ..llm import GEMINI_SPARE
from ..providers import gemini
from ..quality import norm
from .http import get
from .youtube_comments import COLLAB, CYRILLIC, JUNK, RUDE, word

log = logging.getLogger("web_voice")

# Хвост запасного списка: основная модель и первые запасные пишут посты.
MODELS = list(reversed(GEMINI_SPARE))[:2]
PER_DAY = 15
RETRY_HOURS = config.WEB_VOICE_RETRY_HOURS
KEEP_DAYS = 3
# Страниц на релиз: каждая — до 10 секунд, а релизов за сбор бывает десяток.
MAX_PAGES = 6
# Короче — не мнение, длиннее — не цитата в пост на 200–400 знаков.
MIN_QUOTE, MAX_QUOTE = 30, 300
# compose --dry-run выключает: сухой прогон квоту не тратит и ничего не пишет.
ENABLED = True
# Поиск отказал — до конца запуска не зовём: отказ квоты на следующем релизе тот же.
_down = False

# Тексты песен, витрины магазинов, Telegram и сам YouTube (у него свой путь).
SKIP_SITES = re.compile(
    r"genius\.com|lyric|musixmatch|tekst|pesni|songtext|apple\.com|spotify|deezer|"
    r"yandex|zvuk\.com|vk\.com/music|t\.me|telegram|youtube|youtu\.be",
    re.IGNORECASE,
)
# Площадки, где пишут слушатели, а не редакция: подпись — «слушатель на …».
CROWD = re.compile(r"reddit|rateyourmusic|albumoftheyear|pikabu|dtf\.ru|vk\.com|twitter|\bx\.com|forum|форум",
                   re.IGNORECASE)
SITES = {
    "reddit.com": "Reddit", "rateyourmusic.com": "Rate Your Music", "albumoftheyear.org": "Album of the Year",
    "pitchfork.com": "Pitchfork", "hotnewhiphop.com": "HotNewHipHop", "hiphopdx.com": "HipHopDX",
    "complex.com": "Complex", "rollingstone.com": "Rolling Stone", "stereogum.com": "Stereogum",
    "rap.ru": "RAP.RU", "the-flow.ru": "The Flow", "afisha.ru": "Афиша", "pikabu.ru": "Пикабу",
}

PROMPT = """Найди в интернете мнения критиков и слушателей о релизе «{release}» артиста {artist}.
Нужны оценки самой музыки этого релиза: впечатление, сравнение, похвала или разнос.
Не подходят: текст песни, описание в магазине, пресс-релиз, новость о выходе,
мнение об артисте вообще или о другом его релизе.{russian}
Верни только JSON-массив, до 5 объектов: [{{"quote": "...", "url": "...", "by": "critic" или "listener"}}].
quote — фрагмент со страницы дословно, 30–300 знаков, на языке страницы, ничего не переводи
и не сокращай внутри; url — адрес страницы, где этот фрагмент стоит; by — написал критик
издания или слушатель. Не нашёл — верни []."""


def page(url: str) -> tuple[str, str, str] | None:
    """Страница после переадресаций: (адрес, заголовок, текст для сверки).
    Скрипты не вырезаются: у страниц-приложений текст лежит в них."""
    response = get(url, timeout=10, retries=1)
    if response is None or "html" not in response.headers.get("content-type", ""):
        return None
    raw = response.text[:3_000_000]
    title = re.search(r"<title[^>]*>(.*?)</title>", raw, re.IGNORECASE | re.DOTALL)
    return response.url, html.unescape(title.group(1)) if title else "", norm(re.sub(r"<[^>]+>", " ", raw))


def site(url: str) -> str:
    host = urlparse(url).netloc.lower().split(":")[0]
    host = re.sub(r"^(?:www|m|old|new)\.", "", host)
    return SITES.get(host, host)


def who(url: str, by: str = "") -> str:
    """Кто сказал — по адресу страницы. Слушатель — на площадке слушателей
    или когда модель так сказала; на сайте издания по умолчанию тоже слушатель:
    под рецензией бывают комментарии, а приписать их изданию — неправда."""
    if CROWD.search(url) or by != "critic":
        return f"слушатель на {site(url)}"
    return site(url)


def ask(artist: str, release: str, russian: bool) -> tuple[list[dict], list[str]]:
    """Что нашла модель: цитаты с адресами и адреса страниц поиска."""
    hint = "\nРусскоязычные источники — в первую очередь." if russian else ""
    text, uris = gemini.ground(MODELS, PROMPT.format(artist=artist, release=release, russian=hint))
    found = re.search(r"\[.*\]", text, re.DOTALL)
    try:
        items = json.loads(found.group(0)) if found else []
    except ValueError:
        items = []
    return [i for i in items if isinstance(i, dict) and isinstance(i.get("quote"), str)], uris


def verify(items: list[dict], pages: dict[str, tuple[str, str]], names: list[str], release: str) -> dict:
    """Первая цитата, которая дословно стоит на скачанной странице о релизе, или {}."""
    # «Buckshot & Ghost Mountain» на странице целиком не стоит.
    names_norm = {norm(p) for n in names for p in [n, *COLLAB.split(n)] if len(p.strip()) > 1}
    for item in items:
        quote = " ".join(item["quote"].split()).strip(" \"'«»“”")
        if not (MIN_QUOTE <= len(quote) <= MAX_QUOTE) or RUDE.search(quote) or JUNK.search(quote):
            continue
        for url, (title, text) in pages.items():
            if norm(quote) not in text:
                continue  # модель процитировала то, чего на странице нет
            if word(release).search(quote) or (word(release).search(title) and any(n in text for n in names_norm)):
                return {"who": who(url, str(item.get("by", ""))), "text": quote}
    return {}


def _fresh(entry: dict, hours: float) -> bool:
    moment = state._parse(entry.get("at", ""))
    return moment is not None and state.now() - moment < timedelta(hours=hours)


def key(artist: str, release: str) -> str:
    """Ключ релиза в data/web_voice.json. Тот же считает review.voices_wanted —
    без импорта этого модуля: облачной рутине requests не ставится."""
    return norm(f"{artist} — {release}")


def _cache() -> dict:
    return {k: v for k, v in state.read_json(config.WEB_VOICE_FILE, {}).items() if _fresh(v, KEEP_DAYS * 24)}


def _pages(urls) -> dict[str, tuple[str, str]]:
    """Скачанные страницы {адрес после переадресаций: (заголовок, текст)}: не больше
    MAX_PAGES, тексты песен и витрины мимо — и до скачивания, и после переадресации."""
    pages: dict[str, tuple[str, str]] = {}
    for url in dict.fromkeys(urls):
        if len(pages) >= MAX_PAGES:
            break
        if not url.startswith("http") or SKIP_SITES.search(url):
            continue
        got = page(url)
        if got and not SKIP_SITES.search(got[0]):
            pages[got[0]] = got[1:]
    return pages


def find(artist: str, release: str, names: list[str] | tuple = ()) -> dict:
    """Проверенная цитата о релизе из сети: {"who", "text"} или {}.

    Сначала — найденное раньше: и поиском Gemini, и облачным Claude (accept).
    Поэтому кэш читается до проверки ключа Google: голос, который принёс Claude,
    нужен и без него."""
    global _down
    if not (artist and release):
        return {}
    cache = _cache()
    seen = cache.get(key(artist, release))
    if seen and (seen.get("voice") or _fresh(seen, RETRY_HOURS)):
        return seen.get("voice") or {}
    if _down or not (ENABLED and os.environ.get("GOOGLE_API_KEY", "").strip()):
        return {}
    # Проходы Claude квоту Google не тратят и в суточный предел не идут.
    if sum(_fresh(v, 24) for v in cache.values() if v.get("by") != "claude") >= PER_DAY:
        log.info("Поиск мнений в сети: суточный предел %d исчерпан, «%s» — без него", PER_DAY, key(artist, release))
        return {}

    names = [artist, *names]
    russian = bool(CYRILLIC.search(" ".join([release, *names])))
    try:
        items, uris = ask(artist, release, russian)
    except RuntimeError as exc:
        # Технический отказ не запоминаем: следующий сбор попробует снова.
        log.warning("Поиск мнений в сети не ответил, до конца запуска без него: %s", str(exc)[:300])
        _down = True
        return {}
    if russian:
        items.sort(key=lambda i: not CYRILLIC.search(i["quote"]))

    pages = _pages([*(str(i.get("url", "")) for i in items), *uris])
    voice = verify(items, pages, names, release)
    log.info("Мнение в сети о «%s»: %s (цитат %d, страниц %d)", key(artist, release),
             voice.get("who") or "не подтвердилось", len(items), len(pages))
    cache[key(artist, release)] = {"at": state.iso(), "voice": voice}
    state.write_json(config.WEB_VOICE_FILE, cache)
    return voice


def accept(artist: str, release: str, found: list[dict], names: list[str] | tuple = ()) -> dict:
    """Мнение, которое принёс облачный Claude (review --apply): {"who", "text"} или {}.

    found — его находки [{"url", "quote", "by"}]. Claude верим не больше, чем Gemini:
    страницу код качает сам, и цитату принимает та же verify. Не подтвердилось или
    Claude не нашёл ничего — промах тоже запоминается, иначе релиз искали бы каждый
    проход. Найденный раньше голос не затирается.
    """
    cache = _cache()
    known = (cache.get(key(artist, release)) or {}).get("voice")
    if known:
        return known
    pages = _pages(str(i.get("url", "")) for i in found)
    voice = verify([i for i in found if isinstance(i.get("quote"), str)], pages, [artist, *names], release)
    cache[key(artist, release)] = {"at": state.iso(), "voice": voice, "by": "claude"}
    state.write_json(config.WEB_VOICE_FILE, cache)
    return voice


def _selftest() -> int:
    """Без сети: модель и страницы подменены."""
    global ask, page
    import tempfile
    from pathlib import Path

    from ..review import voices_wanted

    real = ask, page, config.WEB_VOICE_FILE, os.environ.get("GOOGLE_API_KEY")
    review = ("<html><head><title>Buckshot &amp; Ghost Mountain – Winchester review | Pitchfork</title></head>"
              "<body><p>Buckshot and Ghost Mountain turn “Winchester” into the heaviest thing "
              "either has made&nbsp;this year.</p><script>{}</script></body></html>")
    thread = "<title>New Buckshot leak thoughts</title><p>His flow on the second verse is ridiculous, honestly.</p>"
    lyrics = "<title>Buckshot – Winchester Lyrics | Genius</title><p>Winchester in my hand, loaded, cold and ready now</p>"
    pages = {
        "https://pitchfork.com/reviews/winchester": ("https://pitchfork.com/reviews/winchester", review),
        "https://redirect.example/1": ("https://www.reddit.com/r/hauntedmound/leak", thread),
        "https://genius.com/winchester": ("https://genius.com/winchester", lyrics),
    }
    calls: list[str] = []

    def fake_page(url: str):
        final, raw = pages[url]
        calls.append(final)
        title = re.search(r"<title>(.*?)</title>", raw).group(1)
        return final, html.unescape(title), norm(re.sub(r"<[^>]+>", " ", raw))

    items = [
        # Выдумка: на странице такой фразы нет — отвергается.
        {"quote": "Winchester is the best song Buckshot has ever released, period.",
         "url": "https://pitchfork.com/reviews/winchester", "by": "critic"},
        # Строка песни со страницы текстов — не мнение, Genius не скачивается.
        {"quote": "Winchester in my hand, loaded, cold and ready now", "url": "https://genius.com/winchester"},
        # Настоящая, но о другом: страница не о релизе, в цитате его нет.
        {"quote": "His flow on the second verse is ridiculous, honestly.", "url": "https://redirect.example/1"},
        # Настоящая: другие кавычки, тире и пробел — сверка их сводит.
        {"quote": 'Buckshot and Ghost Mountain turn "Winchester" into the heaviest thing either has made this year.',
         "url": "https://pitchfork.com/reviews/winchester", "by": "critic"},
    ]
    honest = items[3]["quote"]
    try:
        with tempfile.TemporaryDirectory() as tmp:
            config.WEB_VOICE_FILE = Path(tmp) / "web_voice.json"
            os.environ["GOOGLE_API_KEY"] = "test"
            asked: list[str] = []
            ask = lambda artist, release, russian: (asked.append(release) or items, ["https://redirect.example/1"])  # noqa: E731
            page = fake_page
            got = find("Buckshot & Ghost Mountain", "Winchester")
            assert got == {"who": "Pitchfork", "text": items[3]["quote"]}, got
            assert "https://genius.com/winchester" not in calls, "страница текстов не скачивается"
            # Только выдумка — ничего; подпись по сайту слушателей — «слушатель на Reddit».
            assert verify(items[:1], {u: (fake_page(u)[1], fake_page(u)[2]) for u in pages}, ["Buckshot"],
                          "Winchester") == {}
            thread_page = {"https://www.reddit.com/r/x": ("Winchester thoughts", norm(thread))}
            assert verify([{"quote": "His flow on the second verse is ridiculous, honestly."}], thread_page,
                          ["Buckshot"], "Winchester") == {"who": "слушатель на Reddit",
                                                          "text": "His flow on the second verse is ridiculous, honestly."}
            # Найденное помнится: второй сбор модель не зовёт.
            assert find("Buckshot & Ghost Mountain", "Winchester") == got and asked == ["Winchester"], asked
            # Не нашлось — повтор не раньше RETRY_HOURS.
            items[:] = items[:3]
            assert find("Sematary", "Winchester") == {} and find("Sematary", "Winchester") == {}
            assert asked == ["Winchester", "Winchester"], asked
            # Сухой прогон не тратит квоту.
            globals()["ENABLED"] = False
            assert find("Kunteynir", "Метро") == {} and len(asked) == 2
            globals()["ENABLED"] = True
            # Отказ генератора (бесплатный ключ: поиска нет) не запоминается,
            # и следующий релиз того же запуска модель уже не зовёт.
            def refuse(*_):
                asked.append("отказ")
                raise RuntimeError("429: You exceeded your current quota")
            ask = refuse
            assert find("Kunteynir", "Метро") == {} and find("Yeat", "COCOON") == {}
            assert asked[2:] == ["отказ"], asked
            assert "метро" not in " ".join(state.read_json(config.WEB_VOICE_FILE, {})), "технический отказ не запоминается"
            # Найденное раньше отдаётся и после отказа поиска, и без ключа Google.
            os.environ.pop("GOOGLE_API_KEY")
            assert find("Buckshot & Ghost Mountain", "Winchester") == got
            globals()["_down"] = False

            # Путь облачного Claude: адрес и цитата — его, страницу качает код, сверяет verify.
            lied = {"url": "https://pitchfork.com/reviews/winchester", "quote": items[0]["quote"], "by": "critic"}
            assert accept("Ghost Mountain", "Winchester", [lied]) == {}, "цитаты нет на странице"
            assert state.read_json(config.WEB_VOICE_FILE, {})[key("Ghost Mountain", "Winchester")]["voice"] == {}
            real_one = {**lied, "quote": honest}
            claude = accept("Ghost Mountain", "Winchester", [lied, real_one])
            assert claude == {"who": "Pitchfork", "text": honest}, claude
            # Найденный голос не затирается, а пост его получает без ключа Google и без модели.
            reddit = {"url": "https://redirect.example/1", "quote": items[2]["quote"]}
            assert accept("Ghost Mountain", "Winchester", [reddit]) == claude
            assert find("Ghost Mountain", "Winchester") == claude and len(asked) == 3, asked
            # Ничего не нашёл — промах запоминается: список рутины его больше не отдаёт.
            assert accept("Kunteynir", "Метро", []) == {}
            today = state.iso()
            rows = [{"kind": "release", "fingerprint": f, "artist": a, "title": t, "released_at": today}
                    for f, a, t in (("a", "Ghost Mountain", "Winchester - Single"), ("b", "Kunteynir", "Метро"),
                                    ("c", "Yeat", "COCOON"))]
            wanted = voices_wanted(rows, set(), state.read_json(config.WEB_VOICE_FILE, {}), {})
            assert [w["artist"] for w in wanted] == ["Yeat"], wanted
    finally:
        ask, page, config.WEB_VOICE_FILE, env = real
        if env is None:
            os.environ.pop("GOOGLE_API_KEY", None)
        else:
            os.environ["GOOGLE_API_KEY"] = env
    print("Мнения в сети: выдумка и цитата не о релизе отвергнуты, дословная прошла, "
          "тексты песен мимо, найденное помнится, сухой прогон и отказ квоты модель больше не зовут; "
          "находка Claude принята только со страницы, отдаётся без ключа Google и не затирается.")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--selftest":
        raise SystemExit(_selftest())
    if args and args[0] == "--check" and len(args) > 2:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
        config.load_dotenv()
        print(find(args[1], args[2]) or "Проверенного мнения не нашлось.")
        raise SystemExit(0)
    print(__doc__)
