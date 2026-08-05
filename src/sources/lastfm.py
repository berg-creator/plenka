"""Last.fm API — бесплатный ключ. Даёт похожих артистов и теги.

Это топливо для двух вещей: рубрики «ОТКУДА НОГИ» (кто на кого похож и от кого
растёт) и автоматического расширения списка отслеживаемых артистов.
"""

from __future__ import annotations

import os

from .http import get_json

BASE = "https://ws.audioscrobbler.com/2.0/"
MIN_INTERVAL = 0.3


def _key() -> str:
    key = os.environ.get("LASTFM_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "Не задан LASTFM_API_KEY. Бесплатный ключ: last.fm/api/account/create"
        )
    return key


def _call(method: str, **params: str) -> dict | None:
    payload = {"method": method, "api_key": _key(), "format": "json", **params}
    data = get_json(BASE, params=payload, min_interval=MIN_INTERVAL)
    if not isinstance(data, dict) or "error" in data:
        return None
    return data


def similar_artists(name: str, limit: int = 12) -> list[dict]:
    """Похожие артисты с коэффициентом близости (0..1)."""
    data = _call("artist.getsimilar", artist=name, limit=str(limit), autocorrect="1")
    if not data:
        return []

    results = []
    for item in data.get("similarartists", {}).get("artist", []):
        try:
            match = float(item.get("match", 0))
        except (TypeError, ValueError):
            match = 0.0
        results.append({"name": item.get("name", ""), "match": match})
    return [r for r in results if r["name"]]


def artist_tags(name: str, limit: int = 8) -> list[str]:
    data = _call("artist.gettoptags", artist=name, autocorrect="1")
    if not data:
        return []
    tags = data.get("toptags", {}).get("tag", [])
    return [t.get("name", "") for t in tags[:limit] if t.get("name")]


def artist_bio(name: str) -> str:
    """Короткая справка об артисте — контекст для генерации поста."""
    data = _call("artist.getinfo", artist=name, autocorrect="1", lang="en")
    if not data:
        return ""
    summary = data.get("artist", {}).get("bio", {}).get("summary", "")
    # Last.fm подмешивает в конец ссылку «Read more on Last.fm» — она не нужна.
    return summary.split("<a href")[0].strip()
