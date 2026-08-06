"""Deezer API — бесплатный, без ключа. Второй независимый источник релизов.

Нужен как страховка: если артиста нет в iTunes или тот отдал пустоту,
Deezer часто знает о релизе.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from .http import get_json

BASE = "https://api.deezer.com"
MIN_INTERVAL = 1.0  # Deezer ограничивает примерно 50 запросами за 5 секунд

# Адрес-заглушка: хеш пустой строки. Так Deezer отвечает, когда портрета нет.
EMPTY_PICTURE = "d41d8cd98f00b204e9800998ecf8427e"


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


def artist_picture(name: str) -> str:
    """Портрет артиста. У Last.fm картинки давно заглушены, у Deezer живые.

    Нужен карточке разбора: человек ждёт увидеть артиста, а не служебную
    плашку с текстом.
    """
    data = get_json(
        f"{BASE}/search/artist",
        params={"q": name, "limit": 8},
        min_interval=MIN_INTERVAL,
    )
    items = (data or {}).get("data") or []
    if not items:
        return ""

    # Только точное совпадение имени: взять «самого популярного из похожих»
    # значит однажды показать под разбором чужое лицо, а это та же выдумка,
    # что и выдуманный факт, только заметнее.
    #
    # А среди точных совпадений — самого слушаемого: у Deezer на каждое громкое
    # имя заведено по несколько дублей, и первой в выдаче обычно идёт пустышка
    # с десятком поклонников и без портрета.
    target = name.casefold().strip()
    exact = [i for i in items if i.get("name", "").casefold().strip() == target]
    if not exact:
        return ""

    best = max(exact, key=lambda i: i.get("nb_fan", 0))
    url = best.get("picture_xl") or best.get("picture_big") or ""
    # Когда портрета нет, Deezer отдаёт серый силуэт по адресу с хешем пустой
    # строки. Формально картинка есть, показывать её нельзя.
    return "" if EMPTY_PICTURE in url else url


def artist_cover(name: str) -> str:
    """Обложка собственного альбома артиста — запасной вариант для портрета.

    Именно собственного: у iTunes в свежих релизах попадаются гостевые куплеты,
    и на карточке про артиста оказывается чужая обложка. Deezer по артисту
    отдаёт только его релизы.
    """
    artist_id = find_artist_id(name)
    if not artist_id:
        return ""

    data = get_json(
        f"{BASE}/artist/{artist_id}/albums",
        params={"limit": 5},
        min_interval=MIN_INTERVAL,
    )
    for album in (data or {}).get("data") or []:
        url = album.get("cover_xl") or album.get("cover_big") or ""
        if url and EMPTY_PICTURE not in url:
            return url
    return ""


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


# Ссылка на релиз несёт его идентификатор: deezer.com/ru/album/123456
_ALBUM_URL = re.compile(r"deezer\.com/(?:[a-z]{2}/)?album/(\d+)")


def album_id_from_url(url: str) -> str:
    """Идентификатор альбома из ссылки — тем же способом, что у iTunes."""
    match = _ALBUM_URL.search(url or "")
    return match.group(1) if match else ""


def album_tracks(album_id: str | int) -> dict:
    """Треклист альбома: названия, длительности, жанр. То же, что у iTunes,
    и по той же причине — пост про релиз должен опираться на музыку,
    а не на один факт «вышло»."""
    data = get_json(f"{BASE}/album/{album_id}", min_interval=MIN_INTERVAL)
    if not data or data.get("error"):
        return {}

    tracks = [
        {
            "title": item.get("title", ""),
            "seconds": item.get("duration") or 0,
            # Тридцатисекундный отрывок для прослушивания — уходит в пост.
            "preview": item.get("preview", ""),
        }
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
