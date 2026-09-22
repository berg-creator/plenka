"""Агент слежки за новинками.

Обходит источники, отсеивает уже виденное, оценивает важность находки
и складывает результат в data/inbox.jsonl — сырьё для генератора постов.

    python -m src.collect --dry-run     посмотреть, что нашлось, ничего не записывая
    python -m src.collect               рабочий режим
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone

from . import config, state
from .sources import deezer, feeds, itunes, telegram_web, youtube_rss

log = logging.getLogger("collect")

# Насколько свежим должен быть релиз, чтобы считаться новостью.
RELEASE_MAX_AGE_DAYS = 14

# Вес артиста по его месту в базе — влияет на приоритет в очереди постов.
# Русская сцена идёт наравне с ядром: своих новостей и релизов канал ждёт
# не меньше, чем западных.
# auto — найденные сами (src/newcomers.py): своя сцена, но не проверенная вкусом.
TIER_SCORE = {"core": 100, "ru": 95, "scene": 80, "legend": 70, "auto": 65, "ru_pop": 55}

# Сколько дней тишины терпит сбор у найденного сами, прежде чем перестать искать его релизы.
DORMANT_DAYS = 183

# Слова, по которым новость без упоминания знакомого артиста всё же интересна.
NEWS_KEYWORDS_RU = (
    "умер", "скончал", "погиб", "арест", "суд", "иск", "биф", "конфликт",
    "воссоедин", "распад", "лейбл", "альбом", "тур", "отменил", "рекорд",
    "стрим", "чарт", "премьер", "клип", "интервью", "скандал", "сниппет",
)
NEWS_KEYWORDS_EN = (
    "dies", "died", "death", "arrested", "lawsuit", "sues", "beef", "feud",
    "reunion", "reunite", "breaks up", "split", "signs to", "announces",
    "tour", "cancels", "record", "chart", "premiere", "returns",
)

# Имена, которые совпадают с обычными словами: «Кино» ловит любую новость про
# кинематограф, Tool — про инструменты, ATL — про Атланту. Для них одного
# упоминания мало, нужен ещё и музыкальный контекст.
AMBIGUOUS_NAMES = frozenset(
    {
        "кино", "каста", "дора", "аквариум", "платина", "три дня дождя",
        "tool", "bones", "nas", "atl", "germ", "ramirez", "salem", "korn",
        "city morgue", "goth money", "ghost mountain", "amber london",
    }
)

# Слова, подтверждающие, что речь о музыке.
MUSIC_CONTEXT = (
    "альбом", "трек", "песн", "группа", "музык", "концерт", "тур", "сингл",
    "клип", "рэп", "рок", "метал", "лейбл", "пластинк", "выступ", "сцен",
    "album", "track", "song", "band", "music", "concert", "tour", "single",
    "rap", "rock", "metal", "label", "record", "lp", "ep", "release",
)

# Гастрольные новости западных артистов русскому слушателю бесполезны:
# до России эти туры не доезжают. Такие материалы либо отсеиваются,
# либо идут с низким приоритетом — как повод пошутить, а не как анонс.
TOUR_MARKERS_EN = (
    "tour dates", "announce tour", "announces tour", "on tour", "tour of",
    "north american tour", "european tour", "uk tour", "world tour",
    "residency", "festival lineup", "tickets on sale", "live dates",
)
TOUR_MARKERS_RU = ("тур по сша", "тур по европе", "гастроли", "билеты в продаж")

# Жанры, которые каналу чужие: попадают только через ложные совпадения имён.
OFF_TOPIC_MARKERS = (
    "prog-rock", "progressive rock", "jazz fusion", "classical music",
    "opera", "symphony", "прог-рок", "симфони", "оперн", "джаз-фьюжн",
)

# Слова, по которым видно, что новость вообще не о музыке: общекультурные ленты
# приносят много кино, театра и литературы.
NON_MUSIC_MARKERS = (
    "фильм", "трейлер", "кинопрокат", "прокат", "режиссёр", "режиссер",
    "сериал", "аниме", "мультфильм", "актёр", "актер", "роль в", "кинофестивал",
    "спектакл", "театр", "балет", "выставк", "музей", "роман", "книг",
)


def load_artists() -> list[dict]:
    payload = state.read_json(config.ARTISTS_FILE, {"artists": []})
    return payload.get("artists", [])


def in_collect(artist: dict) -> bool:
    """Ищет ли сбор релизы артиста.

    ru_pop нужен только для новостей и шуток — их релизы канал не анонсирует.
    Найденный сами (поле seen_at, src/newcomers.py) — пока о нём пишут:
    полгода тишины, и магазины о нём больше не спрашиваем, а в базе он ещё
    полгода — по ней ищутся фото и ссылки. Тот же фильтр держит слежение
    (service.watched_releases): кого сбор не ищет, того ищет рассылка.
    """
    if artist.get("tier") == "ru_pop":
        return False
    seen = artist.get("seen_at")
    return not seen or seen >= (state.now() - timedelta(days=DORMANT_DAYS)).date().isoformat()


def collect_releases(artists: list[dict], seen: state.Seen) -> list[dict]:
    """Свежие релизы по всем артистам, у которых заполнены id."""
    cutoff = state.now() - timedelta(days=RELEASE_MAX_AGE_DAYS)
    found: list[dict] = []

    for artist in artists:
        if not in_collect(artist):
            continue

        raw: list[dict] = []
        try:
            if artist.get("itunes_id"):
                raw += itunes.recent_releases(artist["itunes_id"])
            if artist.get("deezer_id"):
                raw += deezer.recent_releases(artist["deezer_id"])
        except Exception as exc:  # источник может отвалиться — это не повод падать
            log.warning("%s: релизы не получены (%s)", artist["name"], exc)
            continue

        for item in raw:
            released = _parse(item.get("released_at"))
            if released is None or released < cutoff:
                continue

            key = state.fingerprint("release", artist["name"], item.get("title", ""))
            if key in seen:
                continue

            credit, credit_ids = store_credit(item)
            if not credit:
                continue  # магазин не ответил — виденным не помечаем, сверим в следующий обход
            seen.add(key)
            tracked_id = artist.get(f"{item.get('source')}_id")
            if not own_release(artist["name"], tracked_id, credit, credit_ids, artist.get("aliases")):
                log.info("%s: «%s» — релиз %s, не берём", artist["name"], item.get("title", ""), credit)
                continue

            record = {
                "kind": "release",
                "fingerprint": key,
                "score": TIER_SCORE.get(artist.get("tier", "scene"), 50),
                # Подпись — как в магазине, а не имя из списка слежения.
                "artist": credit,
                # По кому релиз нашёлся: по нему бот узнаёт релиз для подписчиков
                # (src/service.py), а compose — что подпись уже сверена.
                "tracked": artist["name"],
                "tier": artist.get("tier"),
                "tags": artist.get("tags", []),
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "cover": item.get("cover", ""),
                "track_count": item.get("track_count"),
                "released_at": item.get("released_at"),
                "source": item.get("source"),
                "external_id": item.get("external_id", ""),
                "collected_at": state.iso(),
            }
            record.update(fetch_tracks(item))
            found.append(record)
    return found


# Название релиза издание ставит в кавычки: «…», “…” или "…".
_QUOTED = re.compile(r"«([^»]+)»|“([^”]+)”|\"([^\"]+)\"")


def releases_from_news(news: list[dict], artists: list[dict], seen: state.Seen) -> list[dict]:
    """Релизы, которые назвала новость издания, а сбор по базе не нашёл.

    17.09.2026 The Flow написал «Ежемесячные “Rich Flex Babangida”» — микстейп
    Славы КПСС и Максима Плакина. В Deezer он записан на отдельного артиста
    «Ежемесячные», которого в data/artists.json нет, и collect_releases, идущий
    по id из базы, его не увидел. Релиза в inbox не было, urgent.fresh_news
    не узнала в новости релиз, и она вышла срочной новостью — без площадок
    и без запроса трека. Дописывать каждого такого артиста в базу руками —
    догонять уже вышедший пост, поэтому релиз ищется по самой новости:
    название из кавычек в заголовке — в поиск Deezer (iTunes RU этот микстейп
    не находит вовсе). Дальше релиз идёт обычным путём: compose --fresh пишет
    пост, новость встаёт в него цитатой, а срочной не выходит.

    Берётся только точное совпадение: название альбома равно названию
    из кавычек, а новость называет исполнителя из магазина — это решает
    compose.press_row, та же сверка, по которой срочные новости узнают дубль.
    Похожий альбом хуже никакого: на «Поцелуи» Nkeeei и Yanix поиск Deezer отдаёт
    пять одноимённых альбомов ВИА ГРА, «Небраски» и других, а их самих — нет.
    Пропущенный релиз обойдётся срочной новостью, а чужой — постом под чужим
    именем с чужим треклистом.

    Только новости с артистом из сбора (in_collect): его вес ставит релизу
    приоритет, а релизы ru_pop канал не анонсирует. Подпись и tracked —
    магазинные: история и подписчики Славы КПСС к «Ежемесячным» не относятся.
    Если же релиз его собственный (own_release), tracked — он, и отпечаток
    совпадает с тем, что дал бы collect_releases: seen дубль не пропустит.
    """
    from .compose import press_row  # compose сам импортирует collect

    cutoff = state.now() - timedelta(days=RELEASE_MAX_AGE_DAYS)
    by_name = {a["name"]: a for a in artists}
    found: list[dict] = []
    for row in news:
        named = [by_name[n] for n in row.get("artists", []) if n in by_name and in_collect(by_name[n])]
        if row.get("source") != "telegram" or not named:
            continue
        for match in _QUOTED.finditer(row.get("title", "")):
            quoted = next(group for group in match.groups() if group)
            try:
                hits = deezer.search_albums(quoted)
                # ponytail: карточка на каждый альбом с тем же названием — на частом названии
                # до 25 запросов за новость; сверять имя ещё по поиску, если сбор начнёт тормозить.
                items = [deezer.album_release(h["id"]) for h in hits
                         if itunes._norm(h.get("title", "")) == itunes._norm(quoted)]
            except Exception as exc:  # магазин отвалился — новость выйдет как раньше
                log.warning("«%s»: поиск релиза не удался (%s)", quoted, exc)
                continue
            for item in items:
                released = _parse(item.get("released_at"))
                if released is None or released < cutoff:
                    continue
                credit = item["artist"]
                owner = next((a for a in named if own_release(
                    a["name"], a.get("deezer_id"), credit, item["artist_ids"], a.get("aliases"))), None)
                # Исполнитель не из базы должен стоять в заголовке: в новости «Слава КПСС
                # разобрал «X»» автор чужого альбома назван только в пересказе, и канал
                # анонсировал бы чужой релиз с весом Славы КПСС.
                if not owner and not re.search(rf"(?<!\w){re.escape(credit)}(?!\w)", row.get("title", ""), re.IGNORECASE):
                    continue
                tracked = owner["name"] if owner else credit
                best = max(named, key=lambda a: TIER_SCORE.get(a.get("tier", "scene"), 50))
                record = {
                    "kind": "release",
                    "fingerprint": state.fingerprint("release", tracked, item["title"]),
                    "score": TIER_SCORE.get(best.get("tier", "scene"), 50),
                    "artist": credit,
                    "tracked": tracked,
                    "tier": best.get("tier"),
                    "tags": best.get("tags", []),
                    **{k: item[k] for k in
                       ("title", "url", "cover", "track_count", "released_at", "source", "external_id")},
                    "collected_at": state.iso(),
                }
                if record["fingerprint"] in seen or not press_row(record, [row], by_name):
                    continue
                seen.add(record["fingerprint"])
                record.update(fetch_tracks(item))
                log.info("%s: «%s» — релиз из новости %s", credit, item["title"], row.get("outlet", ""))
                found.append(record)
    return found


def store_credit(item: dict) -> tuple[str, list]:
    """Исполнитель релиза, как он значится в магазине, и id основных артистов.

    iTunes кладёт исполнителя прямо в список релизов, Deezer — только
    в карточку альбома. Без поля artist карточка ищется по id или по ссылке:
    так compose сверяет старые находки, у которых подпись взята из списка слежения.
    """
    if item.get("artist"):
        return item["artist"], item.get("artist_ids", [])
    source = itunes if item.get("source") == "itunes" else deezer
    album = item.get("external_id") or source.album_id_from_url(item.get("url", ""))
    try:
        return source.album_credit(album) if album else ("", [])
    except Exception as exc:  # магазин мог не ответить — релиз сверим в другой раз
        log.warning("Исполнитель не получен (%s): %s", item.get("title", ""), exc)
        return "", []


def own_release(name: str, tracked_id: int | None, credit: str, credit_ids: list,
                aliases: list[str] | None = None) -> bool:
    """Основной ли исполнитель релиза тот, за кем мы следим.

    По id артиста магазин отдаёт не только его релизы. У iTunes там же чужие
    синглы, куда его позвали на фит («Gunda Manu — Hurry Up (feat. City Morgue)»),
    и сольники участников группы (Inspectah Deck у Wu-Tang Clan). Сборщик
    подписывал их именем из списка слежения, и канал сообщал, что у City Morgue
    вышел трек, где City Morgue только гость.

    Гостевой релиз не берём вовсе, а не помечаем «позвали на фит»: признак
    пришлось бы протащить через все рубрики и бота, и один недосмотр в промпте
    вернёт ту же ложь. Совместный релиз («HNTR & Juicy J») — наш: артист в нём
    один из основных, а подпись остаётся полной, как в магазине.

    Сначала сверяется id основного исполнителя: он переживает разницу написаний
    («Smoky Mo» у iTunes, «Смоки Мо» у нас). Соавторов iTunes по id не отдаёт,
    их ищем по имени — целиком, между разделителями «, » и « & », иначе
    «Juicy J» нашёлся бы в «Juicy Jones».

    Магазин подписывает артиста по-своему, и у совместного релиза наше имя
    в подписи не встречается вовсе: «Ramil\' & Basta» вместо «Баста»,
    «Vito & Smoky Mo» вместо «Смоки Мо» — оба релиза канал терял. Поэтому
    рядом с именем сверяются магазинные написания из поля aliases
    (data/artists.json). Они собраны разово по подписям сольников самого
    артиста, где id совпал; новому артисту алиас дописывается руками,
    когда магазин зовёт его иначе.
    """
    if tracked_id and tracked_id in credit_ids:
        return True
    folded = _fold(credit)
    for known in [name, *(aliases or [])]:
        if re.search(rf"(?:^|, | & ){re.escape(_fold(known))}(?:, | & |$)", folded):
            return True
    return False


def _fold(text: str) -> str:
    """Имя без регистра и диакритики: iTunes пишет «JAŸ-Z», у нас «JAY-Z»."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold().strip()


def fetch_tracks(item: dict) -> dict:
    """Треклист релиза — фактура о самой музыке.

    Запрос делается только на новую находку (несколько штук за запуск), поэтому
    лимиты источников это не задевает. Пустой ответ не беда: рубрики умеют
    писать и без треклиста, просто короче.
    """
    external_id = item.get("external_id")
    if not external_id:
        return {}

    try:
        if item.get("source") == "itunes":
            data = itunes.album_tracks(external_id)
            return data if data.get("tracks") else deezer_tracks(item) or data
        if item.get("source") == "deezer":
            return deezer.album_tracks(external_id)
    except Exception as exc:  # треклист — приятное дополнение, а не условие сбора
        log.warning("Треклист не получен (%s): %s", item.get("title", ""), exc)
    return {}


def _bare(title: str) -> str:
    """«That's It (feat. Future) [from GTAVI: The Album] - Single» → «thats it»."""
    return itunes._norm(re.split(r"\s*[(\[]", title, maxsplit=1)[0])


def deezer_tracks(item: dict) -> dict:
    """Треклист из Deezer, когда iTunes отдал релиз без песен.

    Так вышел «That's It» Yung Lean & Metro Boomin (17.09.2026): без названия
    и длины трека запрос трека не ушёл, и пост остался без него. Deezer подписывает
    тот же релиз иначе («feat. Future & Metro Boomin»), поэтому сверяются название
    до скобок, артист и число треков — чужой релиз хуже никакого.
    """
    names = [n for n in re.split(r"\s*(?:,|&|\bfeat\.?|\bx\b)\s*", item.get("artist", ""), flags=re.I) if n]
    bare = _bare(item.get("title", ""))
    # Ищем по одним именам: свежий релиз поиск Deezer по названию ещё не знает
    # («Yung Lean That's It» — пусто), а по «Yung Lean Metro Boomin» находит.
    for album in deezer.search_albums(" ".join(names), limit=25):
        artist = itunes._norm(album.get("artist", {}).get("name", ""))
        if _bare(album.get("title", "")) == bare and artist in map(itunes._norm, names):
            data = deezer.album_tracks(album["id"])
            if len(data.get("tracks") or []) == item.get("track_count"):
                return data
    return {}


def _needs_tracks(row: dict) -> bool:
    """Нужно ли лезть за треклистом. Кроме релизов совсем без него сюда
    попадают и те, чей треклист собран до появления отрывков: названия там
    есть, а отрывка нет. В ленту он не идёт (пост — одна плитка), но им
    запрос трека владельцу даёт услышать, что именно искать (compose.do_ask_tracks).
    """
    if row.get("kind") != "release":
        return False
    tracks = row.get("tracks") or []
    if not tracks:
        return True
    return not any(track.get("preview") for track in tracks)


def backfill_tracks() -> int:
    """Дозагружает треклисты к релизам, найденным до появления этой фактуры.

    Разовая операция после обновления: без неё посты по старым находкам
    получатся заметно беднее новых. Файл переписывается целиком — inbox
    небольшой, а частичная дозапись строк тут опаснее.
    """
    rows = list(state.read_jsonl(config.INBOX_FILE))
    pending = [r for r in rows if _needs_tracks(r)]
    if not pending:
        print("Треклисты и отрывки уже на месте.")
        return 0

    filled = 0
    for row in pending:
        source = row.get("source")
        try:
            # Идентификатор ищем по нарастающей надёжности: сохранённый,
            # затем из ссылки на магазин, и только в последнюю очередь поиском
            # по названию — он точный и на релизах с фитами в заголовке молчит.
            if source == "deezer":
                album_id = row.get("external_id") or deezer.album_id_from_url(row.get("url", ""))
                data = deezer.album_tracks(album_id) if album_id else {}
            else:
                album_id = (
                    row.get("external_id")
                    or itunes.album_id_from_url(row.get("url", ""))
                    or itunes.find_album(row.get("artist", ""), row.get("title", ""))
                )
                data = itunes.album_tracks(album_id) if album_id else {}
        except Exception as exc:
            log.warning("%s — %s: %s", row.get("artist"), row.get("title"), exc)
            continue

        if not data.get("tracks"):
            continue

        # Последняя проверка на подмену: у сингла один трек, у альбома — сколько
        # обещал источник. Разошлось — значит, нашёлся не тот релиз, и лучше
        # остаться без треклиста, чем врать в посте.
        expected = row.get("track_count")
        if expected and len(data["tracks"]) != expected:
            log.warning(
                "%s — %s: найдено %d треков вместо %s, треклист отброшен",
                row.get("artist"), row.get("title"), len(data["tracks"]), expected,
            )
            continue

        row.update(data)
        filled += 1
        print(f"  ✓ {row.get('artist')} — {row.get('title')}: {len(data['tracks'])} треков")

    config.INBOX_FILE.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    print(f"\nДозагружено треклистов: {filled} из {len(pending)}.")
    return 0


def collect_videos(artists: list[dict], seen: state.Seen) -> list[dict]:
    found: list[dict] = []
    for artist in artists:
        channel = artist.get("youtube_channel_id")
        if not channel:
            continue
        try:
            videos = youtube_rss.recent_videos(channel)
        except Exception as exc:
            log.warning("%s: ролики не получены (%s)", artist["name"], exc)
            continue

        for item in videos:
            key = state.fingerprint("video", item.get("external_id", ""))
            if key in seen:
                continue
            seen.add(key)
            found.append(
                {
                    "kind": "video",
                    "fingerprint": key,
                    "score": 50,
                    "artist": artist["name"],
                    "tier": artist.get("tier"),
                    "tags": artist.get("tags", []),
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "released_at": item.get("published_at"),
                    "source": "youtube",
                    "collected_at": state.iso(),
                }
            )
    return found


def collect_news(artists: list[dict], seen: state.Seen) -> list[dict]:
    """Новости из RSS и Telegram-каналов. Приоритет тем, где упомянут знакомый артист."""
    entries: list[dict] = []
    # Источники разнесены по своим try: RSS по русской сцене вымер, и падение
    # одного пути не должно уносить второй — новости остались только в Telegram.
    try:
        entries += feeds.fetch_recent(config.NEWS_MAX_AGE_HOURS)
    except Exception as exc:
        log.warning("RSS недоступны (%s)", exc)
    try:
        entries += telegram_web.fetch_recent(config.NEWS_MAX_AGE_HOURS)
    except Exception as exc:
        log.warning("Telegram-каналы недоступны (%s)", exc)

    # Индекс имён в нижнем регистре для быстрого поиска упоминаний.
    index = {a["name"].casefold(): a for a in artists}
    found: list[dict] = []

    for entry in entries:
        key = state.fingerprint("news", entry.get("external_id", "") or entry.get("url", ""))
        if key in seen:
            continue

        haystack = f"{entry.get('title', '')} {entry.get('summary', '')}".casefold()

        # Новости про кино, театр и книги приходят из общекультурных лент — отсеиваем.
        if any(marker in haystack for marker in NON_MUSIC_MARKERS):
            continue

        has_music_context = any(word in haystack for word in MUSIC_CONTEXT)
        mentioned = [
            name
            for name in index
            if name and _mentions(haystack, name, has_music_context)
        ]

        # Чужие жанры отсеиваем целиком: они попадают сюда только по
        # случайному совпадению имени вроде Tool или Nas.
        if any(marker in haystack for marker in OFF_TOPIC_MARKERS):
            continue

        keywords = NEWS_KEYWORDS_RU if entry.get("lang") == "ru" else NEWS_KEYWORDS_EN
        has_keyword = any(word in haystack for word in keywords)
        # Сниппет — кусок неизданного трека, который артист выложил сам. Для этой
        # аудитории повод не меньше релиза, и звук к нему есть: под постом он
        # ложится первым комментарием (comments.seed). Метку ставим здесь, по
        # данным, а не по готовому тексту — слова «сниппет» модель может и не
        # написать, а звук под постом зависит не от её формулировки.
        # Ищем только в заголовке: в тексте слово стоит и там, где новость о другом
        # («в одном из сниппетов к релизу» у анонса альбома, «первым выпустил сниппет»
        # в споре о плагиате) — за 12–15.09.2026 так ошибались две метки из трёх.
        is_snippet = "сниппет" in entry.get("title", "").casefold()

        # Гастроли за рубежом интересны, только если это событие само по себе
        # (воссоединение, прощальный тур) — иначе это анонс не для нашей аудитории.
        is_tour = any(m in haystack for m in TOUR_MARKERS_EN + TOUR_MARKERS_RU)
        # Слова в заголовке часто разделены («announces 2026 UK and Ireland tour»),
        # поэтому точных фраз мало — проверяем ещё и по сочетанию слов.
        if not is_tour and ("tour" in haystack or "shows" in haystack):
            is_tour = any(w in haystack for w in ("announce", "dates", "tickets", "warm-up"))
        is_big_event = any(
            w in haystack for w in ("reunion", "reunite", "farewell", "final tour",
                                    "воссоедин", "прощальн", "распад")
        )
        if is_tour and not is_big_event:
            continue

        if mentioned:
            best = max(
                (TIER_SCORE.get(index[n].get("tier", "scene"), 50) for n in mentioned),
                default=50,
            )
            score = min(best + 10, 100)
        elif has_keyword:
            score = 30
        else:
            continue  # шум — в inbox не кладём

        seen.add(key)
        found.append(
            {
                "kind": "news",
                "snippet": is_snippet,
                "fingerprint": key,
                "score": score,
                "artists": [index[n]["name"] for n in mentioned],
                "outlet": entry.get("outlet", ""),
                "lang": entry.get("lang", "en"),
                "title": entry.get("title", ""),
                "summary": entry.get("summary", ""),
                "url": entry.get("url", ""),
                # Картинка со страницы издания — только для отобранных новостей
                # и только когда лента её не отдала: лишний заход по сети на шум
                # не нужен, а без картинки пост теряется в ленте.
                "cover": entry.get("cover", "") or feeds.page_image(entry.get("url", "")),
                "released_at": entry.get("published_at"),
                # Откуда пришла новость, видно по записи: посту о релизе нужно
                # мнение издания (compose.outside_voice), а чужой RSS этим
                # изданием не является. Раньше здесь стояло «rss» для всех.
                "source": entry.get("source", "rss"),
                "collected_at": state.iso(),
            }
        )
    return found


def _mentions(haystack: str, name: str, has_music_context: bool) -> bool:
    """Упомянут ли артист в тексте.

    Проверка идёт по границам слов, иначе «Nas» находится внутри «Nashville».
    Для имён, совпадающих с обычными словами, дополнительно требуется
    музыкальный контекст — одного слова «Кино» в заголовке недостаточно.
    """
    if name in AMBIGUOUS_NAMES and not has_music_context:
        return False
    pattern = rf"(?<!\w){re.escape(name)}(?!\w)"
    return re.search(pattern, haystack) is not None


def _parse(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def main() -> int:
    parser = argparse.ArgumentParser(description="Агент слежки за музыкальными новинками")
    parser.add_argument("--dry-run", action="store_true", help="показать находки, ничего не записывая")
    parser.add_argument("--skip-releases", action="store_true", help="не опрашивать iTunes/Deezer")
    parser.add_argument("--skip-news", action="store_true", help="не читать RSS")
    parser.add_argument(
        "--backfill-tracks",
        action="store_true",
        help="дозагрузить треклисты к релизам, найденным раньше",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    config.load_dotenv()

    if args.backfill_tracks:
        return backfill_tracks()

    artists = load_artists()
    if not artists:
        print("База артистов пуста — заполни data/artists.json")
        return 1

    seen = state.Seen()
    batch: list[dict] = []

    if not args.skip_releases:
        batch += collect_releases(artists, seen)
        batch += collect_videos(artists, seen)
    if not args.skip_news:
        news = collect_news(artists, seen)
        batch += news
        if not args.skip_releases:
            batch += releases_from_news(news, artists, seen)

    batch.sort(key=lambda item: item["score"], reverse=True)

    if args.dry_run:
        print(f"\nНайдено новых материалов: {len(batch)}\n")
        for item in batch[:40]:
            label = {"release": "РЕЛИЗ", "video": "КЛИП", "news": "НОВОСТЬ"}[item["kind"]]
            who = item.get("artist") or ", ".join(item.get("artists", [])) or item.get("outlet", "")
            print(f"  [{item['score']:>3}] {label:<8} {who} — {item['title'][:70]}")
        if not batch:
            print("  (пусто — либо всё уже собрано ранее, либо не заполнены id артистов)")
        return 0

    state.append_jsonl(config.INBOX_FILE, batch)
    removed = seen.prune()
    seen.save()

    print(f"Добавлено в inbox: {len(batch)}. Очищено старых отпечатков: {removed}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
