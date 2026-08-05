"""iTunes Search API — бесплатный, без ключа и без регистрации.

Даёт свежие релизы по id артиста, обложки и 30-секундные превью.
Заменяет вырезанный в феврале 2026 эндпоинт Spotify /browse/new-releases.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .http import get_json

SEARCH_URL = "https://itunes.apple.com/search"
LOOKUP_URL = "https://itunes.apple.com/lookup"

# iTunes не документирует жёсткий лимит, но при частых запросах отдаёт 403.
MIN_INTERVAL = 3.0


def find_artist_id(name: str) -> int | None:
    """Ищет id артиста по имени. Используется один раз при заполнении базы."""
    data = get_json(
        SEARCH_URL,
        params={"term": name, "entity": "musicArtist", "limit": 5},
        min_interval=MIN_INTERVAL,
    )
    if not data or not data.get("results"):
        return None

    target = name.casefold().strip()
    for item in data["results"]:
        if item.get("artistName", "").casefold().strip() == target:
            return item.get("artistId")
    # Точного совпадения нет — берём первый результат, но он требует проверки глазами.
    return data["results"][0].get("artistId")


def recent_releases(artist_id: int, limit: int = 5) -> list[dict]:
    """Последние альбомы артиста, свежие сверху."""
    data = get_json(
        LOOKUP_URL,
        params={
            "id": artist_id,
            "entity": "album",
            "limit": limit,
            "sort": "recent",
        },
        min_interval=MIN_INTERVAL,
    )
    if not data:
        return []

    releases = []
    for item in data.get("results", []):
        if item.get("wrapperType") != "collection":
            continue
        released = _parse_date(item.get("releaseDate"))
        if released is None:
            continue
        releases.append(
            {
                "source": "itunes",
                "artist": item.get("artistName", ""),
                "title": item.get("collectionName", ""),
                "url": item.get("collectionViewUrl", ""),
                "cover": (item.get("artworkUrl100") or "").replace("100x100", "600x600"),
                "track_count": item.get("trackCount"),
                "released_at": released.isoformat(),
                "external_id": str(item.get("collectionId", "")),
            }
        )
    return releases


def find_album(artist: str, title: str) -> int | None:
    """Ищет альбом по имени артиста и названию. Нужен, когда id релиза
    не сохранился, — например, при дозагрузке треклистов к старым находкам."""
    data = get_json(
        SEARCH_URL,
        params={"term": f"{artist} {title}", "entity": "album", "limit": 5},
        min_interval=MIN_INTERVAL,
    )
    if not data or not data.get("results"):
        return None

    target = title.casefold().strip()
    for item in data["results"]:
        if item.get("collectionName", "").casefold().strip() == target:
            return item.get("collectionId")
    return data["results"][0].get("collectionId")


def album_tracks(collection_id: str | int) -> dict:
    """Треклист альбома: названия, длительности, жанр.

    Единственная фактура о самой музыке, которую можно получить бесплатно
    и не выдумывая. Из неё видно то, что слышно и на слух: EP это или
    полноценник, есть ли фиты, кто затянул альбом до часа. Без неё пост
    про релиз может сказать только «вышло — идите слушать».
    """
    data = get_json(
        LOOKUP_URL,
        params={"id": collection_id, "entity": "song", "limit": 60},
        min_interval=MIN_INTERVAL,
    )
    if not data:
        return {}

    tracks: list[dict] = []
    genre = ""
    for item in data.get("results", []):
        if item.get("wrapperType") == "collection":
            genre = item.get("primaryGenreName", "") or genre
            continue
        if item.get("kind") != "song":
            continue
        millis = item.get("trackTimeMillis") or 0
        tracks.append(
            {
                "title": item.get("trackName", ""),
                "seconds": round(millis / 1000) if millis else 0,
            }
        )
        genre = genre or item.get("primaryGenreName", "")

    tracks = [t for t in tracks if t["title"]]
    return {
        "tracks": tracks,
        "genre": genre,
        "duration_sec": sum(t["seconds"] for t in tracks),
    }


def _parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
