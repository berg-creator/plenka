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


def _parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
