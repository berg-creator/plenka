"""Живой отзыв под роликом с треком на YouTube — второй чужой голос в посте о релизе.

Канал релиз не слушал и своего впечатления о звуке иметь не может, поэтому
посты выходят суховато-колкими. Реакция живых людей эту дыру закрывает так же,
как мнение издания: комментарий — проверяемый факт, а не выдумка. Идея владельца
от 12.09.2026 («как у коден крэйзи»). С 29.09.2026 сингл без чужого голоса
поста не получает вовсе (compose.release_jobs), так что от этого модуля
зависит, будет ли пост о сингле вообще.

До 29.09.2026 отзыв не находился почти никогда, по трём причинам:
- ключа не было: YOUTUBE_API_KEY не заведён, а GOOGLE_API_KEY с 20.09.2026 —
  ключ Gemini нового вида («AQ.…»), и YouTube Data API на него отвечает 401;
- брался один первый ролик выдачи, обычно официальный звук (канал «… - Topic»),
  а под ним комментарии закрыты. Отзывы живут под фанатскими записями концерта,
  сливами и клипами: у «Winchester» Buckshot их нашли руками именно там;
- порог в 5 лайков отсекал свежий релиз, которому несколько часов.

Поэтому поиск идёт через yt-dlp (он уже в requirements.txt, и из Actions
его выдача работает — ею же src/tracks.py находит видео трека), а не через
search API: тот стоит 100 единиц квоты из 10 000 в сутки, а выдача yt-dlp —
ноль. Из выдачи берутся до MAX_VIDEOS роликов, в названии которых стоят
и артист, и сам релиз: отзыв должен быть об этом треке, а не об артисте вообще.
Комментарии — через Data API, если ключ рабочий (1 единица на ролик), иначе
тем же yt-dlp. Прежний довод против разбора страницы («ломается от каждой
правки разметки») к yt-dlp не относится: разбор чинят его авторы, а pip
в каждом запуске ставит свежую версию. Квота в сутки: ≤5 единиц на релиз
за заход, 5 заходов (collect.yml 4 раза, urgent.yml раз), до 20 релизов
в пятницу — ≤500 единиц, и только при рабочем ключе.

Отвергнуто: комментарии под постами изданий в Telegram — пост о релизе там
есть ровно тогда, когда чужой голос уже нашёлся (compose.press_row), а своих
каналов артистов в data/artists.json нет; Reddit из датацентров отвечает
отказом и без OAuth не пускает.

Ник автора не берётся вовсе: репозиторий открытый, данные о людях в него
не кладутся никогда, а цитата работает и без подписи. Под роликами хватает мата
и оскорблений, поэтому отбор грубый: короткая человеческая реплика без брани,
ссылок и зазывов, и о самом треке (OF_TRACK), а не об артисте вообще —
остальное пропускаем. Из годных у русского артиста побеждает русская реплика
(канал русскоязычный), потом — по лайкам.

    python -m src.sources.youtube_comments --check "Buckshot & Ghost Mountain" "Winchester"
    python -m src.sources.youtube_comments --selftest
"""

from __future__ import annotations

import logging
import os
import re
import sys

from .http import get_json

log = logging.getLogger("youtube_comments")

API = "https://www.googleapis.com/youtube/v3"
WATCH = "https://www.youtube.com/watch?v="

# Реплика короче — не мнение, длиннее — не цитата: в пост о релизе
# помещается одна фраза (200–400 знаков на весь пост). «Лучший трек года» —
# уже мнение, «топ» — ещё нет.
MIN_LENGTH = 15
MIN_WORDS = 3
MAX_LENGTH = 160
# Лайки отделяют реакцию, которую разделяют многие, от случайной реплики.
# Релизу к посту несколько часов: 29.09.2026 годная реплика про «Winchester»
# набрала 4 лайка, и порог в 5 её отсёк бы.
MIN_LIKES = 3

# Сколько роликов выдачи смотреть и под сколькими читать комментарии.
SEARCH_RESULTS = 10
MAX_VIDEOS = 5
COMMENTS = 20

# Мат, оскорбления и расистские клички: в посте канала им не место,
# а под клипами они через один.
RUDE = re.compile(
    r"ху[ийеё]|пизд|бля|[её]бан|[её]бал|еблан|заеб|уеб|мудак|гандон|шлюх|сук[аиу]\b|"
    r"сучк|пидор|педик|долбо|нахуй|похуй|черножоп|ниггер|nigg|fuck|shit|bitch|cunt",
    re.IGNORECASE,
)
# Спам, самореклама и перекличка «кто в 2026?» — это не мнение о треке.
JUNK = re.compile(
    r"https?://|t\.me|@\w|подпиш|подпис(?:ка|ывай)|мой канал|instagram|telegram"
    r"|кто (?:тут |здесь |слушает )?в 20\d\d|who(?:'s| is)? (?:here|listening)",
    re.IGNORECASE,
)
# Ролики, где говорят не о самом треке: реакции, обзоры, минусовки, каверы.
NOT_ABOUT = re.compile(
    r"reaction|реакци|review|обзор|разбор|type beat|instrumental|инструментал|минус|karaoke|"
    r"slowed|sped up|nightcore|remix|ремикс|\bcover\b|кавер|tutorial|how to",
    re.IGNORECASE,
)
# Под каким роликом сказано — это часть подписи цитаты: «под клипом» про запись
# концерта была бы неправдой о том, кто и что слышал. Порядок важен: слив
# с концерта — запись концерта.
KINDS = (
    (re.compile(r"\blive\b|концерт|\s@\s|festival|фестивал|выступлени", re.I), "под записью концерта"),
    (re.compile(r"snippet|сниппет", re.I), "под сниппетом"),
    (re.compile(r"leak|слив|unreleased|неизданн", re.I), "под сливом"),
    (re.compile(r"lyric|текст", re.I), "под лирик-видео"),
    (re.compile(r"official (?:music )?video|music video|\bmv\b|клип", re.I), "под клипом"),
)
CYRILLIC = re.compile(r"[а-яё]", re.IGNORECASE)
# Отзыв должен быть о треке, а не об артисте вообще: «Ghostemane's REALLY back!»
# и «this mixtape is gonna be s tier» — мимо, «fell in love with this song» — да.
# Кроме слов «трек» и «песня» трек выдают обороты реакции на звук: «goes too hard»,
# «slaps», «качает». Местоимения («it», «this») не годятся: «this guy», «let's get it».
OF_TRACK = re.compile(
    r"song|track|banger|verse|hook|beat|chorus|goes (?:so |too |crazy )?hard|slaps|bangs|"
    r"hits different|on repeat|temazo|трек|песн|вещь|бэнгер|бит\b|куплет|припев|звуч|"
    r"кача[ею]т|пушка|шедевр|на репит",
    re.IGNORECASE,
)
# «Buckshot & Ghost Mountain» в названии ролика не встречается целиком.
COLLAB = re.compile(r"\s*(?:&|,|\+|\bx\b|\bfeat\.?|\bft\.?|\band\b|\bи\b)\s*", re.IGNORECASE)

# Ключ не тот, кончилась квота или API молчит — до конца запуска идём через yt-dlp,
# а не тратим по отказу на каждый ролик.
_api_failed = False


def key() -> str:
    """Ключ YouTube Data API. Отдельная переменная, но годится и общий
    ключ Google, если это обычный ключ Cloud-проекта с включённым YouTube Data API.
    Ключ Gemini вида «AQ.…» YouTube не принимает."""
    return (os.environ.get("YOUTUBE_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")).strip()


def _call(method: str, **params: str) -> dict | None:
    global _api_failed
    if _api_failed or not key():
        return None
    # Одна попытка: отказ ключа ретраями не лечится, а yt-dlp рядом.
    data = get_json(f"{API}/{method}", params={"key": key(), **params}, min_interval=0.3, retries=1)
    if not isinstance(data, dict):
        _api_failed = True
        return None
    return data


def search(query: str, count: int = SEARCH_RESULTS) -> list[dict]:
    """Ролики выдачи: [{id, title, channel, duration, description}]. Через yt-dlp — бесплатно
    по квоте. Описание — только начало, знаков двести: его отдаёт сама выдача, без захода
    на страницу ролика (им пользуется поиск бесплатных битов, src/skleyka.py)."""
    from yt_dlp import YoutubeDL

    try:
        with YoutubeDL({"quiet": True, "no_warnings": True, "extract_flat": True}) as ydl:
            found = ydl.extract_info(f"ytsearch{count}:{query}", download=False)
    except Exception as exc:  # noqa: BLE001 — без выдачи пост просто без отзыва
        log.warning("Поиск на YouTube не ответил: %s", exc)
        return []
    return [{"id": e.get("id", ""), "title": e.get("title") or "", "channel": e.get("channel") or "",
             "duration": e.get("duration") or 0, "description": e.get("description") or ""}
            for e in found.get("entries") or [] if e.get("id")]


def comments(video: str) -> list[dict]:
    """Верхние комментарии ролика: [{text, likes}], без ответов в ветках —
    ответ без реплики, на которую отвечают, читается не так."""
    data = _call("commentThreads", part="snippet", videoId=video, order="relevance",
                 maxResults=str(COMMENTS), textFormat="plainText")
    if data is not None:
        found = []
        for thread in data.get("items") or []:
            snippet = thread.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
            found.append({"text": snippet.get("textDisplay") or "", "likes": int(snippet.get("likeCount") or 0)})
        return found

    from yt_dlp import YoutubeDL

    opts = {
        "quiet": True, "no_warnings": True, "skip_download": True, "getcomments": True,
        "extractor_args": {"youtube": {"max_comments": [str(COMMENTS), str(COMMENTS), "0", "0"],
                                       "comment_sort": ["top"]}},
    }
    try:
        with YoutubeDL(opts) as ydl:
            # Без обработки форматов: комментарии отдаёт отложенный шаг разбора.
            info = ydl.extract_info(WATCH + video, download=False, process=False)
            post = info.get("__post_extractor")
            got = (post() if callable(post) else None) or {}
    except Exception as exc:  # noqa: BLE001 — один немой ролик не повод бросать остальные
        log.warning("Комментарии %s не прочитались: %s", video, exc)
        return []
    return [{"text": c.get("text") or "", "likes": int(c.get("like_count") or 0)}
            for c in got.get("comments") or [] if c.get("parent", "root") == "root"]


def suitable(text: str, likes: int) -> bool:
    """Годится ли реплика в пост: человеческая, без брани и спама."""
    flat = " ".join(text.split())
    return (
        MIN_LENGTH <= len(flat) <= MAX_LENGTH
        and len(flat.split()) >= MIN_WORDS
        and likes >= MIN_LIKES
        and not RUDE.search(flat)
        and not JUNK.search(flat)
        and flat != flat.upper()  # крик капсом цитировать нечего
    )


def word(name: str) -> re.Pattern:
    """Имя целым словом; пробелы и знаки между словами — любые или никаких:
    магазин пишет «Bucket List», ролик — «BUCKETLIST»."""
    words = r"\W*".join(re.escape(w) for w in name.replace("’", "'").split())
    return re.compile(rf"(?<!\w){words}(?!\w)", re.IGNORECASE)


def about(video: dict, names: list[str], release: str) -> bool:
    """Ролик о самом релизе: в названии — релиз, в названии или канале — артист.
    Официальный звук (канал «… - Topic») мимо: комментарии под ним закрыты."""
    title = video["title"].replace("’", "'")
    if video["channel"].endswith(" - Topic") or not word(release).search(title):
        return False
    if NOT_ABOUT.search(title) and not NOT_ABOUT.search(release):
        return False
    parts = {p for n in names for p in [n, *COLLAB.split(n)] if len(p.strip()) > 1}
    return any(word(p).search(f"{title} {video['channel']}") for p in parts)


def kind(title: str) -> str:
    return next((label for pattern, label in KINDS if pattern.search(title)), "под треком")


def top_comment(artist: str, title: str, names: list[str] | tuple = ()) -> dict:
    """Лучший годный отзыв о релизе с нескольких роликов выдачи.

    names — другие написания артиста (data/artists.json): магазин пишет
    «Smoky Mo», а ролик подписан «Смоки Мо». Возвращает {"text", "likes", "who"}
    или пустой словарь — тогда пост пишется без чужого голоса.
    """
    # «(feat. X)» и «[prod. Y]» в названии ролика пишут как попало.
    release = re.split(r"\s*[(\[]", title)[0].strip() or title.strip()
    if not (artist and release):
        return {}
    names = [artist, *names]
    # Русская реплика первой — только у русского артиста: под роликом Lil Peep
    # русский комментарий чаще про артиста вообще, чем про песню.
    russian = bool(CYRILLIC.search(" ".join([release, *names])))
    best: tuple[tuple[bool, int], dict] | None = None
    videos = [v for v in search(f"{artist} {release}") if about(v, names, release)][:MAX_VIDEOS]
    for video in videos:
        for comment in comments(video["id"]):
            text = " ".join(comment["text"].split())
            if not suitable(text, comment["likes"]) or not (OF_TRACK.search(text) or word(release).search(text)):
                continue
            rank = (russian and bool(CYRILLIC.search(text)), comment["likes"])
            if best is None or rank > best[0]:
                # Ник автора не берём: репозиторий открытый.
                best = (rank, {"text": text, "likes": comment["likes"],
                               "who": f"слушатель {kind(video['title'])} на YouTube"})
    return best[1] if best else {}


def check(artist: str = "Buckshot & Ghost Mountain", title: str = "Winchester") -> int:
    """Находится ли отзыв. Квоту тратит только при рабочем ключе: до 5 единиц."""
    print(f"Ключ YouTube: {'есть' if key() else 'нет'} — без рабочего ключа комментарии читает yt-dlp.")
    comment = top_comment(artist, title)
    if not comment:
        print(f"× {artist} — {title}: годного отзыва не нашлось.")
        return 1
    print(f"  {artist} — {title}: {comment['who']}: «{comment['text']}» ({comment['likes']} лайков)")
    return 0


def _selftest() -> int:
    """Отбор реплик и роликов без сети: выдача и комментарии подменены."""
    global search, comments
    assert suitable("Этот трек вытащил меня из осени, спасибо", 42)
    assert suitable("goes too hard cant wait for it to be officially released", 4), "свежему релизу хватит 4 лайков"
    assert suitable("лучший трек года", 3)
    assert not suitable("Этот трек вытащил меня из осени", 1), "мало лайков — не реакция"
    assert not suitable("ну и хуйня конечно", 900), "мат в пост не идёт"
    assert not suitable("подпишись на мой канал", 900), "спам в пост не идёт"
    assert not suitable("кто слушает в 2026 году?", 900), "перекличка — не мнение"
    assert not suitable("ОГОНЬ ОГОНЬ ОГОНЬ ОГОНЬ ОГОНЬ ОГОНЬ", 900), "крик капсом"
    assert not suitable("топ", 900), "слишком коротко"
    assert not suitable("огоооооооооонь!!!", 900), "одно слово — не мнение"
    assert OF_TRACK.search("goes too hard cant wait for it to be officially released"), "пример владельца от 29.09"

    real = search, comments
    search = lambda _q: [  # noqa: E731
        {"id": "topic", "title": "Winchester", "channel": "Buckshot - Topic"},
        {"id": "other", "title": "BUCKSHOT - PROPHET ***OFFICIAL VIDEO***", "channel": "BUCKSHOT"},
        {"id": "react", "title": "Buckshot - Winchester REACTION", "channel": "someone"},
        {"id": "live", "title": "unreleased buckshot “winchester” @ The Underground 4/6/24", "channel": "Aydan"},
        {"id": "leak", "title": "BUCKSHOT - WINCHESTER **FULL LEAK**", "channel": "BalloonBoiii"},
    ]
    pages = {
        "topic": [{"text": "этот трек лучше всего альбома целиком", "likes": 900}],
        "other": [{"text": "этот клип лучше всего что он делал", "likes": 900}],
        "react": [{"text": "реакция вообще огонь, смотрю второй раз", "likes": 900}],
        "live": [{"text": "this mixtape is gonna be s tier haunted mound", "likes": 54},
                 {"text": "fell in love with this song when I heard it live", "likes": 45},
                 {"text": "holy fuck thats the goat", "likes": 90},
                 {"text": "Ghostemane's REALLY back!", "likes": 80}],
        "leak": [{"text": "goes too hard cant wait for it to be officially released", "likes": 4}],
    }
    asked: list[str] = []
    comments = lambda v: asked.append(v) or pages[v]  # noqa: E731
    try:
        got = top_comment("Buckshot & Ghost Mountain", "Winchester (feat. Nobody)")
        assert got == {"text": "fell in love with this song when I heard it live", "likes": 45,
                       "who": "слушатель под записью концерта на YouTube"}, got
        assert asked == ["live", "leak"], f"Topic, чужой трек и реакция не читаются: {asked}"
        # У западного артиста русская реплика первой не встаёт.
        pages["leak"] = [{"text": "эта песня лучше всего что он выпускал", "likes": 3}]
        assert top_comment("Buckshot & Ghost Mountain", "Winchester")["likes"] == 45
        # У русского — встаёт, даже с тремя лайками против сорока пяти.
        # Магазин пишет латиницей, ролик — кириллицей и слитно: помогает написание из базы.
        search = lambda _q: [{"id": "leak", "title": "Смоки Мо — WINCHESTERLIVE", "channel": "фан"},  # noqa: E731
                             {"id": "live", "title": "Смоки Мо - Winchester Live", "channel": "фан"}]
        assert top_comment("Smoky Mo", "Winchester Live") == {}
        got = top_comment("Smoky Mo", "Winchester Live", ["Смоки Мо"])
        assert got == {"text": "эта песня лучше всего что он выпускал", "likes": 3,
                       "who": "слушатель под треком на YouTube"}, got
    finally:
        search, comments = real
    print("Отбор комментариев: брань, спам и крик отсеяны; ролики только о релизе, "
          "отзыв о треке, а не об артисте; лучший со всех: у русского артиста русский, потом по лайкам; подпись по виду ролика.")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--selftest":
        raise SystemExit(_selftest())
    if args and args[0] == "--check":
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
        raise SystemExit(check(*args[1:3]) if len(args) > 1 else check())
    print(__doc__)
