"""Агент слежки за новинками.

Обходит источники, отсеивает уже виденное, оценивает важность находки
и складывает результат в data/inbox.jsonl — сырьё для генератора постов.

    python -m src.collect --dry-run     посмотреть, что нашлось, ничего не записывая
    python -m src.collect               рабочий режим
"""

from __future__ import annotations

import argparse
import logging
import re
from datetime import datetime, timedelta, timezone

from . import config, state
from .sources import deezer, feeds, itunes, youtube_rss

log = logging.getLogger("collect")

# Насколько свежим должен быть релиз, чтобы считаться новостью.
RELEASE_MAX_AGE_DAYS = 14

# Вес артиста по его месту в базе — влияет на приоритет в очереди постов.
# Русская сцена идёт наравне с ядром: своих новостей и релизов канал ждёт
# не меньше, чем западных.
TIER_SCORE = {"core": 100, "ru": 95, "scene": 80, "legend": 70, "ru_pop": 55}

# Слова, по которым новость без упоминания знакомого артиста всё же интересна.
NEWS_KEYWORDS_RU = (
    "умер", "скончал", "погиб", "арест", "суд", "иск", "биф", "конфликт",
    "воссоедин", "распад", "лейбл", "альбом", "тур", "отменил", "рекорд",
    "стрим", "чарт", "премьер", "клип", "интервью", "скандал",
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


def collect_releases(artists: list[dict], seen: state.Seen) -> list[dict]:
    """Свежие релизы по всем артистам, у которых заполнены id."""
    cutoff = state.now() - timedelta(days=RELEASE_MAX_AGE_DAYS)
    found: list[dict] = []

    for artist in artists:
        # ru_pop нужен только для новостей и шуток — их релизы канал не анонсирует.
        if artist.get("tier") == "ru_pop":
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
            seen.add(key)

            record = {
                "kind": "release",
                "fingerprint": key,
                "score": TIER_SCORE.get(artist.get("tier", "scene"), 50),
                "artist": artist["name"],
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
            return itunes.album_tracks(external_id)
        if item.get("source") == "deezer":
            return deezer.album_tracks(external_id)
    except Exception as exc:  # треклист — приятное дополнение, а не условие сбора
        log.warning("Треклист не получен (%s): %s", item.get("title", ""), exc)
    return {}


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
    """Новости из RSS. Приоритет тем, где упомянут знакомый артист."""
    try:
        entries = feeds.fetch_recent()
    except Exception as exc:
        log.warning("RSS недоступны (%s)", exc)
        return []

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
                "fingerprint": key,
                "score": score,
                "artists": [index[n]["name"] for n in mentioned],
                "outlet": entry.get("outlet", ""),
                "lang": entry.get("lang", "en"),
                "title": entry.get("title", ""),
                "summary": entry.get("summary", ""),
                "url": entry.get("url", ""),
                "released_at": entry.get("published_at"),
                "source": "rss",
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
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    config.load_dotenv()

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
        batch += collect_news(artists, seen)

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
