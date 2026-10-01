"""iTunes Search API — бесплатный, без ключа и без регистрации.

Даёт свежие релизы по id артиста, обложки и 30-секундные превью.
Заменяет вырезанный в феврале 2026 эндпоинт Spotify /browse/new-releases.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from .http import get_json

SEARCH_URL = "https://itunes.apple.com/search"
LOOKUP_URL = "https://itunes.apple.com/lookup"

# iTunes не документирует жёсткий лимит, но при частых запросах отдаёт 403.
MIN_INTERVAL = 3.0


def find_artist_id(name: str, *, exact: bool = False) -> int | None:
    """Ищет id артиста по имени. Используется один раз при заполнении базы.

    exact — только точное совпадение: подписке бота первый результат выдачи
    не годится, глаз его не проверит, и весть пришла бы о чужом артисте.
    """
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
    return None if exact else data["results"][0].get("artistId")


def resolve_name(name: str) -> str:
    """Правильное написание имени артиста по приблизительному.

    Нужно потому, что поиск Last.fm ищет по подстроке: на «Chef Keef» он
    возвращает другие опечатки того же имени, но не самого Chief Keef.
    У iTunes сравнение нечёткое, и такие ошибки он переживает — заодно
    переводит «молчат дома» в «Molchat Doma».
    """
    data = get_json(
        SEARCH_URL,
        params={"term": name, "entity": "musicArtist", "limit": 1},
        min_interval=MIN_INTERVAL,
    )
    results = (data or {}).get("results") or []
    return results[0].get("artistName", "") if results else ""


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

    return [release for item in data.get("results", []) if (release := _release(item))]


def _release(item: dict) -> dict:
    """Альбом из ответа магазина в виде находки сбора. Пусто — не альбом или без даты выхода."""
    released = _parse_date(item.get("releaseDate"))
    if item.get("wrapperType") != "collection" or released is None:
        return {}
    return {
        "source": "itunes",
        "artist": item.get("artistName", ""),
        "artist_ids": [item.get("artistId")],
        "title": item.get("collectionName", ""),
        "url": item.get("collectionViewUrl", ""),
        "cover": (item.get("artworkUrl100") or "").replace("100x100", "600x600"),
        "track_count": item.get("trackCount"),
        "released_at": released.isoformat(),
        "external_id": str(item.get("collectionId", "")),
    }


def album_release(collection_id: str | int) -> dict:
    """Релиз по id альбома в том же виде, что recent_releases, — пара к deezer.album_release:
    ВКЛАДЫШУ (src/vkladysh.py) прислали ссылку на альбом, и артист заранее неизвестен."""
    data = get_json(LOOKUP_URL, params={"id": collection_id}, min_interval=MIN_INTERVAL)
    return next((release for item in (data or {}).get("results", []) if (release := _release(item))), {})


def album_credit(collection_id: str | int) -> tuple[str, list[int]]:
    """Исполнитель релиза, как он значится в магазине, и id основного артиста.

    Второго основного артиста («HNTR & Juicy J») iTunes по id не отдаёт —
    только первого, поэтому соавторов src/collect.py ищет по имени в подписи.
    """
    data = get_json(LOOKUP_URL, params={"id": collection_id}, min_interval=MIN_INTERVAL)
    for item in (data or {}).get("results", []):
        if item.get("wrapperType") == "collection":
            return item.get("artistName", ""), [item.get("artistId")]
    return "", []


# Ссылка на релиз несёт его идентификатор: .../album/asthebluntburnsslow/6794327130
_ALBUM_URL = re.compile(r"music\.apple\.com/[^/]+/album/[^/]+/(\d+)")


def album_id_from_url(url: str) -> str:
    """Идентификатор альбома из ссылки магазина.

    Надёжнее поиска по названию: тот требует точного совпадения и на релизах
    со скобками, фитами и изданиями в названии не находит ничего.
    """
    match = _ALBUM_URL.search(url or "")
    return match.group(1) if match else ""


def _albums(artist: str, title: str) -> list[dict]:
    """Записи магазина об альбоме по имени артиста и названию, в порядке выдачи.

    Совпадение требуется точное — и по названию, и по артисту. Похожий результат
    здесь хуже, чем никакого: поиск охотно отдаёт чужой альбом с тем же названием,
    и в пост уходит треклист, которого у релиза нет.

    Ищем альбомы вместе с песнями (entity=album,song): одному альбомному поиску часть
    каталога не видна вовсе — «Berg Chopper INTRO» и «Pharaoh Phuneral» он отдаёт пустыми
    и по названию, и по артисту, хотя альбомы в магазине есть (01.10.2026). Вместе с песнями
    магазин возвращает и сам альбом, тем же запросом.
    """
    data = get_json(
        SEARCH_URL,
        params={"term": f"{artist} {title}", "entity": "album,song", "limit": 10},
        min_interval=MIN_INTERVAL,
    )
    return [item for item in (data or {}).get("results") or []
            if item.get("wrapperType") == "collection"
            and _norm(item.get("collectionName", "")) == _norm(title)
            and _norm(item.get("artistName", "")) == _norm(artist)]


def find_album(artist: str, title: str) -> int | None:
    """Id альбома по имени артиста и названию. Нужен, когда id релиза
    не сохранился, — например, при дозагрузке треклистов к старым находкам."""
    return next((item.get("collectionId") for item in _albums(artist, title)), None)


def find_release(artist: str, title: str) -> dict:
    """Альбом по имени сразу релизом, как album_release: ВКЛАДЫШУ нужны ссылка и дата,
    а второй запрос к магазину — это три секунды паузы. Одноимённый сингл уступает альбому."""
    return _release(max(_albums(artist, title), key=lambda item: (item.get("trackCount") or 0) > 1, default={}))


# Магазины дописывают к названию тип релиза и издание: «- Single», «(Deluxe)».
# Для сверки это шум.
_EDITION = re.compile(
    r"\s*[-–—(\[]?\s*(single|ep|deluxe|explicit|remastered\s*\d*|bonus track version|"
    r"deluxe edition|expanded edition)\s*[)\]]?\s*$",
    re.IGNORECASE,
)


def _norm(value: str) -> str:
    previous = None
    text = value.strip()
    while previous != text:  # изданий может быть несколько: «(Deluxe) - Single»
        previous = text
        text = _EDITION.sub("", text).strip(" -–—")
    return re.sub(r"[^\w\s]", "", text.casefold()).strip()


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
    genre = album = ""
    for item in data.get("results", []):
        if item.get("wrapperType") == "collection":
            genre = item.get("primaryGenreName", "") or genre
            album = item.get("collectionName", "")
            continue
        if item.get("kind") != "song":
            continue
        millis = item.get("trackTimeMillis") or 0
        tracks.append(
            {
                "title": item.get("trackName", ""),
                "seconds": round(millis / 1000) if millis else 0,
                # Тридцатисекундный отрывок, который магазин отдаёт всем для
                # прослушивания. Он и уходит в пост: канал про музыку должен
                # давать её услышать, а не только про неё рассказывать.
                "preview": item.get("previewUrl", ""),
            }
        )
        genre = genre or item.get("primaryGenreName", "")

    tracks = [t for t in tracks if t["title"]]
    return {
        "tracks": tracks,
        "genre": genre,
        "duration_sec": sum(t["seconds"] for t in tracks),
        "album": album,  # не «title» — см. deezer.album_tracks
    }


def song_preview(track: int | str) -> str:
    """30-секундное превью трека: по trackId или по запросу «артист — трек». Пусто — не нашлось.

    Нужно роликам (src/reels.py, строка `track`). По запросу берётся первый
    трек с превью — может оказаться кавер, поэтому сценарию лучше давать id.
    """
    if isinstance(track, int):
        data = get_json(LOOKUP_URL, params={"id": track}, min_interval=MIN_INTERVAL)
    else:
        data = get_json(SEARCH_URL, params={"term": track.replace("—", " "), "entity": "song", "limit": 5},
                        min_interval=MIN_INTERVAL)
    return next((item["previewUrl"] for item in (data or {}).get("results", []) if item.get("previewUrl")), "")


def find_song(query: str) -> dict:
    """Трек с превью по запросу «артист» или «артист — трек»: {id, title, url}; пусто — не нашлось.

    Нужно СВЕДЕНИЮ: «как у <артиста>» подтягивает звук к превью (src/skleyka.py).
    Магазин российский: в американском «Баста» записан как Basta, а западные
    артисты есть в обоих. Исполнитель — точно названный: первым в выдаче бывает
    чужой трек с тем же словом или сборник; минусовки мимо — у них нет голоса.
    Не нашёлся по имени в песнях («Future» тонет в песнях с этим словом) —
    самые популярные песни артиста из его карточки.
    """
    artist, _, title = (part.strip() for part in query.partition("—"))
    want = artist.casefold()

    def pick(items: list[dict], exact: bool) -> dict:
        for item in items:
            name, track = item.get("artistName", "").casefold(), item.get("trackName", "")
            if (item.get("previewUrl") and not re.search(r"(?i)instrumental|karaoke|a ?cappella|минус", track)
                    and (name == want if exact else want in name) and title.casefold() in track.casefold()):
                return {"id": item["trackId"], "title": f"{item['artistName']} — {track}", "url": item["previewUrl"]}
        return {}

    if not want:
        return {}
    if title:
        # Названный трек бывает только в одном магазине: SICKO MODE в российском нет.
        for country in ("ru", "us"):
            songs = (get_json(SEARCH_URL, params={"term": f"{artist} {title}", "entity": "song", "limit": 50,
                                                  "country": country}, min_interval=MIN_INTERVAL) or {}).get("results", [])
            if found := pick(songs, exact=False):
                return found
        return {}
    songs = (get_json(SEARCH_URL, params={"term": artist, "entity": "song", "attribute": "artistTerm", "limit": 50,
                                          "country": "ru"}, min_interval=MIN_INTERVAL) or {}).get("results", [])
    if found := pick(songs, exact=True):
        return found
    artists = (get_json(SEARCH_URL, params={"term": artist, "entity": "musicArtist", "limit": 5, "country": "ru"},
                        min_interval=MIN_INTERVAL) or {}).get("results", [])
    card = next((item["artistId"] for item in artists if item.get("artistName", "").casefold() == want), None)
    if not card:
        return {}
    top = get_json(LOOKUP_URL, params={"id": card, "entity": "song", "limit": 10, "country": "ru"}, min_interval=MIN_INTERVAL)
    return pick((top or {}).get("results", []), exact=False)


def _parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
