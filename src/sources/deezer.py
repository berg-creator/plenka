"""Deezer API — бесплатный, без ключа. Второй независимый источник релизов.

Нужен как страховка: если артиста нет в iTunes или тот отдал пустоту,
Deezer часто знает о релизе.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .http import get_json

BASE = "https://api.deezer.com"
MIN_INTERVAL = 1.0  # Deezer ограничивает примерно 50 запросами за 5 секунд


def find_artist_id(name: str) -> int | None:
    data = get_json(
        f"{BASE}/search/artist",
        params={"q": name, "limit": 5},
        min_interval=MIN_INTERVAL,
    )
    if not data or not data.get("data"):
        return None

    target = name.casefold().strip()
    for item in data["data"]:
        if item.get("name", "").casefold().strip() == target:
            return item.get("id")
    return data["data"][0].get("id")


def recent_releases(artist_id: int, limit: int = 5) -> list[dict]:
    data = get_json(
        f"{BASE}/artist/{artist_id}/albums",
        params={"limit": limit},
        min_interval=MIN_INTERVAL,
    )
    if not data:
        return []

    releases = []
    for item in data.get("data", []):
        released = _parse_date(item.get("release_date"))
        if released is None:
            continue
        releases.append(
            {
                "source": "deezer",
                "artist": "",  # Deezer не кладёт имя артиста в этот ответ
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "cover": item.get("cover_big") or item.get("cover_medium") or "",
                "track_count": item.get("nb_tracks"),
                "released_at": released.isoformat(),
                "external_id": str(item.get("id", "")),
            }
        )
    return releases


def album_tracks(album_id: str | int) -> dict:
    """Треклист альбома: названия, длительности, жанр. То же, что у iTunes,
    и по той же причине — пост про релиз должен опираться на музыку,
    а не на один факт «вышло»."""
    data = get_json(f"{BASE}/album/{album_id}", min_interval=MIN_INTERVAL)
    if not data or data.get("error"):
        return {}

    tracks = [
        {"title": item.get("title", ""), "seconds": item.get("duration") or 0}
        for item in data.get("tracks", {}).get("data", [])
        if item.get("title")
    ]
    genres = [g.get("name", "") for g in data.get("genres", {}).get("data", [])]
    return {
        "tracks": tracks,
        "genre": next((g for g in genres if g), ""),
        "duration_sec": data.get("duration") or sum(t["seconds"] for t in tracks),
    }


def _parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
