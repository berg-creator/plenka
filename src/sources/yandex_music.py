"""Яндекс Музыка без входа: что человек лайкнул и кто стоит рядом с артистом.

Зачем. ДВОЙНИК (src/svedenie.py) считает, на сколько музыка человека совпала
с артистом, а единственный список, который человек отдаёт одной ссылкой, —
его «Мне нравится» в Яндекс Музыке. Открытый API отвечает без ключа и без
входа: лайки открытой фонотеки, плейлист по ссылке, артист и его круг.

Чужие лайки Яндекс не отдаёт никому, в том числе лайки самого артиста.
Поэтому «вкус артиста» здесь — он сам и `similarArtists` из brief-info, а его
личный плейлист берётся, только если он у артиста правда есть («С любовью,
Toxi$», «Баста респектует»). По номеру владельца свой плейлист от подборки
Яндекса не отличить — видно по названию, в нём стоит имя артиста.

Почему через Облако. С серверов GitHub Яндекс отвечает 451: адреса США он
не обслуживает, а бот живёт в Actions. Запросы идут через свою функцию
в Яндекс Облаке (cloud/yandex_music_proxy.py) — секреты YANDEX_FUNCTION_URL
и YANDEX_FUNCTION_KEY. Без них (Mac владельца) ходим напрямую, тем же путём.
Общий http.get не подошёл: функции нужен свой заголовок с ключом, а Яндексу —
свой User-Agent, подпись python-requests он встречает 403.

Подводные камни, проверенные 18–19.09.2026: `search` без `page=0` отвечает 400;
из 335 запросов подряд два получили 429, поэтому повтор после паузы
обязателен; `tracks?track-ids=` берёт до 300 штук за раз — при 400 адрес
длиннее 8 КБ и ответ 414. Лайки идут в два шага (список id, потом сами треки):
`playlists/3` отдаёт всё одним запросом, но своей страницей, и у большой
фонотеки часть списка потерялась бы молча.

Закрытая фонотека, чужой логин и опечатка в ссылке отвечают одинаково (401),
поэтому ошибка здесь одна — None, а бот показывает, где открыть доступ.

    python -m src.sources.yandex_music --check "https://music.yandex.ru/users/music-blog/playlists/3"
    python -m src.sources.yandex_music --artist "Toxi$"
"""

from __future__ import annotations

import argparse
import logging
import re
import time
from typing import Any

import requests

from .. import config

log = logging.getLogger("yandex_music")

UPSTREAM = "https://api.music.yandex.net/"
# Подпись python-requests Яндекс встречает 403; в Облаке тот же UA ставит функция.
UA = "plenka-bot"
BATCH = 300
TIMEOUT = 15
# «Мне нравится» — плейлист с этим номером у любого пользователя.
LIKES_KIND = "3"

# Ссылка, которую человек кидает боту: «Мне нравится», свой плейлист старого
# вида (users/<логин>/playlists/<номер>) или нового (playlists/<uuid>).
LINK = re.compile(
    r"music\.yandex\.\w+/(?:users/(?P<login>[^/?\s]+)/(?:playlists/(?P<kind>\d+)|(?P<liked>tracks))"
    r"|playlists/(?P<uuid>[0-9a-f-]{36}))",
    re.IGNORECASE,
)

# Редакционные подборки Яндекса про артиста — не его выбор, а витрина.
EDITORIAL = ("лучшее:", "в стиле:", "похожее:")


def _get(path: str, **params: Any) -> Any | None:
    """GET к API. Возвращает поле result или None на любом отказе."""
    url, headers = UPSTREAM + path, {"User-Agent": UA}
    function = config.secret("YANDEX_FUNCTION_URL", required=False)
    if function:
        url, params = function, {"_path": path, **params}
        headers["X-Plenka-Key"] = config.secret("YANDEX_FUNCTION_KEY", required=False)

    for attempt in range(3):
        try:
            response = requests.get(url, params=params, headers=headers, timeout=TIMEOUT)
        except requests.RequestException as exc:
            log.warning("Яндекс Музыка %s: %s", path, exc)
            return None
        if response.status_code == 200:
            try:
                return response.json().get("result")
            except ValueError:
                log.warning("Яндекс Музыка %s: ответ не JSON", path)
                return None
        if response.status_code != 429:
            log.info("Яндекс Музыка %s: %s", path, response.status_code)
            return None
        time.sleep(2**attempt)
    return None


def _track(raw: dict) -> dict:
    """Трек в том виде, в каком его считает ДВОЙНИК."""
    return {
        "id": str(raw.get("id") or raw.get("realId") or ""),
        "title": raw.get("title") or "",
        "artists": [{"id": a.get("id"), "name": a.get("name", "")} for a in raw.get("artists") or []],
        # Убранное из каталога остаётся в лайках: в счёт оно не идёт, но видно поимённо.
        "available": bool(raw.get("available")),
    }


def tracks(ids: list[str]) -> list[dict]:
    """Треки по id, пачками по 300: длиннее — адрес не влезает и Яндекс отвечает 414."""
    found: list[dict] = []
    for start in range(0, len(ids), BATCH):
        chunk = _get("tracks", **{"track-ids": ",".join(ids[start : start + BATCH])})
        found += [_track(t) for t in chunk or []]
    return found


def likes(login: str) -> list[dict] | None:
    """«Мне нравится» открытой фонотеки. None — фонотека закрыта или логина нет."""
    liked = _get(f"users/{login}/likes/tracks")
    ids = [str(t["id"]) for t in ((liked or {}).get("library") or {}).get("tracks", []) if t.get("id")]
    if not ids:
        return None
    return tracks(ids)


def playlist(owner: str, kind: str) -> list[dict] | None:
    """Плейлист по владельцу и номеру — треки приходят целиком, одним запросом."""
    data = _get(f"users/{owner}/playlists/{kind}")
    if data is None:
        return None
    return [_track(t["track"]) for t in data.get("tracks", []) if t.get("track")]


def by_link(url: str) -> list[dict] | None:
    """Треки по ссылке, которую человек кинул боту. None — не читается."""
    match = LINK.search(url)
    if not match:
        return None
    if uuid := match.group("uuid"):
        data = _get(f"playlist/{uuid}")
        return None if data is None else [_track(t["track"]) for t in data.get("tracks", []) if t.get("track")]
    kind = LIKES_KIND if match.group("liked") else match.group("kind")
    if kind == LIKES_KIND:
        return likes(match.group("login"))
    return playlist(match.group("login"), kind)


def _own_playlist(name: str, playlists: list[dict]) -> dict | None:
    """Плейлист, который собрал сам артист: его имя в названии, и это не витрина Яндекса."""
    for item in playlists:
        title = (item.get("title") or "").casefold()
        if name.casefold() in title and not title.startswith(EDITORIAL):
            return {"owner": str(item.get("uid")), "kind": str(item.get("kind")), "title": item.get("title")}
    return None


def _photo(artist: dict) -> str:
    """Портрет артиста. Пусто — Яндекс отдал мозаику из обложек или ничего."""
    cover = artist.get("cover") or {}
    if cover.get("type") != "from-artist-photos" or not cover.get("uri"):
        return ""
    return "https://" + cover["uri"].replace("%%", "1000x1000")


def info(artist_id: int | str) -> dict | None:
    """Артист по id: имя, круг (сам и similarArtists), свой плейлист, портрет."""
    data = _get(f"artists/{artist_id}/brief-info")
    if not data or not data.get("artist"):
        return None
    artist = data["artist"]
    # Сам артист приходит с id строкой, а соседи и исполнители треков — числом
    # (проверено 21.09.2026). Без приведения сам артист не входил в свой круг:
    # «ты на N% Toxi$» не засчитывал треки самого Toxi$.
    return {
        "id": int(artist["id"]),
        "name": artist.get("name", ""),
        "circle": [int(artist["id"]), *(int(a["id"]) for a in data.get("similarArtists", []) if a.get("id"))],
        "playlist": _own_playlist(artist.get("name", ""), data.get("playlists") or []),
        "photo": _photo(artist),
    }


def artist(name: str) -> dict | None:
    """Артист по имени. None — Яндекс такого не знает."""
    # Без page=0 поиск отвечает 400.
    found = _get("search", type="artist", text=name, page=0)
    results = ((found or {}).get("artists") or {}).get("results") or []
    return info(results[0]["id"]) if results else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Яндекс Музыка без входа: лайки, плейлист, артист")
    parser.add_argument("--check", metavar="ССЫЛКА", help="что бот прочитает по ссылке на плейлист")
    parser.add_argument("--artist", metavar="ИМЯ", help="артист, его круг и свой плейлист")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    config.load_dotenv()

    if args.check:
        found = by_link(args.check)
        if found is None:
            print("Не читается: закрытая фонотека, чужой логин или не та ссылка.")
            return 1
        alive = [t for t in found if t["available"]]
        print(f"Треков: {len(found)}, доступны: {len(alive)}")
        for track in alive[:10]:
            print(f"  {', '.join(a['name'] for a in track['artists']) or '—'} — {track['title']}")
        return 0

    if args.artist:
        data = artist(args.artist)
        if not data:
            print("Яндекс такого артиста не знает.")
            return 1
        print(f"{data['name']} (id {data['id']}), в круге {len(data['circle'])}")
        print("  свой плейлист:", data["playlist"]["title"] if data["playlist"] else "нет")
        print("  портрет:", data["photo"] or "нет")
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
