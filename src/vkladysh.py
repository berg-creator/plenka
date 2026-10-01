"""ВКЛАДЫШ — карточка трека, которую пересылают другу с другой площадки.

Люди делятся музыкой каждый день, а сидят на разных площадках: один на Яндексе,
другой в Apple. Боты-конвертеры на этой боли растут сами, через пересылку, но рынок
забит качалками MP3, а качать каналу закрыто (прав нет, владелец 11.09.2026).
Поэтому не утилита, а вещь, как вкладыш кассеты: ссылка на трек с любой площадки
или «Артист — Трек» — в ответ одна карточка: обложка в рамке канала (card.cover),
все восемь площадок ссылками строкой, у артиста из базы канала — ближайший концерт
из Яндекс Афиши. Площадок все восемь, а не четыре, как в посте (publish.listen):
пост их перечисляет, а вкладыш затем и нужен, чтобы трек дошёл до любой.

Всё собрано из готового. Ссылку разбирает поиск ОТБОРА (otbor.by_link, otbor.lookup),
поэтому площадки у них одни. song.link не берём: его API мёртв. Модели здесь нет —
ответ мгновенный и бесплатный, поэтому и без подписки: замок «подпишись — получи»
убил бы пересылку, а реклама здесь — сама карточка с маркой канала и ссылкой на бота.
Подписку спрашивают кнопки под вкладышем — слежение и разбор вкуса (src/service.py).

Альбом — та же карточка, а не вторая: ссылка на альбом (Deezer, и короткая тоже, Apple Music,
Яндекс Музыка, Spotify) или «Артист — Альбом» раньше кончались разбором вкуса или
«не разобрал», хотя другу пересылают и альбомы. Словарь у него тот же, что у трека, плюс
число треков и дата выхода — в виде релиза сбора (deezer.album_release), поэтому подпись,
площадки, отправка и кнопки бота общие. Прямая ссылка на альбом — каждой площадке, где он
нашёлся по имени (Apple Music, Яндекс, Deezer): поиск по «Артист Название» первым отдаёт
что угодно, у альбома «INTRO» — трек «Intro». Остальным площадкам — поиск: без ключа или
входа альбом там не найти. Тип релиза не пишем: альбом от EP iTunes не отличает.

Трек важнее альбома: «Артист — Название» чаще про трек. Но когда артист назвал так и альбом,
текстом альбом иначе не достать — под карточкой трека кнопка «💿 Альбом» (ловит
service.handle_callback). Сингл магазины заводят альбомом из одного трека — он остаётся
треком. По ссылке, наоборот, сперва спрашивается альбом: площадка одна, и второй запрос
к ней — это пауза (у iTunes три секунды). Площадки спрашиваются разом, а не по очереди:
до 01.10.2026 ссылка на альбом Apple стоила пяти секунд, а ненайденный текст шёл к разбору
вкуса на три секунды позже.

КАРТОЧКА АРТИСТА — тот же вкладыш, но об артисте: имя в посте канала ведёт
в бота ссылкой ?start=a_<id Deezer> (publish.artist_links), и бот сразу отвечает
фото, кто это, тремя последними релизами и площадками. «Кто это» — первое предложение
Википедии, и только если оно о музыканте: своих сведений карточка не добавляет, а у «Bones»
и «Кино» первая статья — про кости и про кинематограф. Под карточкой «🔔 Следить» —
кнопка СЛЕЖУ (src/service.py), второго списка слежения нет, — и «🎞 Разбор вкуса», та же,
что под карточкой трека: разбор идёт по имени артиста.

Инлайн-режим (@plenka_fm_bot Артист — Трек в чужом чате) отложен: дежурство
разбирает события по одному, и запрос из чужого чата ждал бы за разбором модели
дольше, чем Telegram держит его открытым (NEXT.md, задача 57).

    python -m src.vkladysh --selftest           разбор, карточка, альбом, отказ на мусоре — без сети
    python -m src.vkladysh --dry-run "ССЫЛКА"   что бот ответит на ссылку (трек, альбом) или «Артист — Название», без Telegram
    python -m src.vkladysh --artist 12345       карточка артиста по id Deezer, без Telegram
"""

from __future__ import annotations

import argparse
import html
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

from . import card, collect, config, otbor, publish, state, telegram
from .sources import afisha, deezer, itunes, yandex_music
from .sources.http import get, get_json

log = logging.getLogger("vkladysh")

KICKER = "ВКЛАДЫШ"


# Ссылка на трек Яндекса тоже несёт album/<id>, но за ним идёт /track/ — это не альбом.
YANDEX_ALBUM = re.compile(r"music\.yandex\.\w+/album/(\d+)(?!\d|/track)")
SPOTIFY_ALBUM = re.compile(r"open\.spotify\.com/(?:intl-\w+/)?album/(\w+)")
# Что за короткой ссылкой Deezer, трек или альбом, скажет только редирект.
DEEZER_SHORT = re.compile(r"https?://(?:link\.deezer\.com|deezer\.page\.link)/")
# iTunes дописывает к названию тип релиза — «Ночь - Single», «INTRO - EP»:
# в названии трека и в поиске по другим площадкам это шум.
STORE_TAIL = re.compile(r"\s+-\s+(?:Single|EP)$")


def find(text: str) -> dict:
    """Трек или альбом по ссылке или «Артист — Название»: артист, название, ссылка, обложка;
    у альбома ещё track_count, released_at и links — прямые ссылки других площадок.
    У трека, чьим именем артист назвал и альбом, — album: код для кнопки «💿 Альбом».
    Пусто — ни то ни другое: куплет в несколько строк, мусор, нет в магазинах."""
    text = text.strip()
    if "\n" in text:
        return {}
    if link := otbor.URL.search(text):
        url = link.group(0)
        if DEEZER_SHORT.match(url) and (page := get(url)):
            url = page.url
        # Альбом первым: ссылка на альбом, спрошенная сперва как трек, стоила второго запроса
        # к той же площадке, а у iTunes между двумя — три секунды паузы.
        return album(album_code(url)) or otbor.by_link(url)
    parts = otbor.DASH.split(text, maxsplit=1)
    if len(parts) != 2 or not parts[0].strip() or not parts[1].strip(" \"«»"):
        return {}
    artist, title = parts[0].strip(), parts[1].strip(" \"«»")
    # Трек и альбом ищутся разом: по очереди ненайденное шло к разбору вкуса на три секунды позже.
    # ponytail: трек ждёт все три поиска альбома — упавшая площадка задержит карточку на ретраи
    # http.get (до 7 с); станет мешать — ждать альбомы с таймаутом и отдавать трек без кнопки.
    with ThreadPoolExecutor() as pool:
        track, albums = pool.submit(otbor.lookup, artist, title), pool.submit(_stores, artist, title)
    track, albums = track.result(), albums.result()
    if not track:
        return _album(albums)
    # Трек важнее альбома: «Артист — Название» чаще про трек. Альбом с тем же именем — кнопкой.
    code = next((album_code(a["url"]) for a in albums if (a.get("track_count") or 0) > 1), "")
    return {**track, "album": code} if code else track


def album_code(url: str) -> str:
    """Площадка буквой и id альбома: «d554626402». Пусто — ссылка не на альбом.
    Кодом, а не ссылкой, альбом живёт в кнопке «💿 Альбом»: в callback_data 64 байта,
    и ссылка Apple с названием в адресе туда не влезает."""
    if number := deezer.album_id_from_url(url):
        return f"d{number}"
    if (number := itunes.album_id_from_url(url)) and not re.search(r"[?&]i=\d", url):  # ?i= — трек альбома
        return f"a{number}"
    return next((letter + match.group(1) for letter, pattern in (("y", YANDEX_ALBUM), ("s", SPOTIFY_ALBUM))
                 if (match := pattern.search(url))), "")


def album(code: str) -> dict:
    """Альбом по коду album_code — с его площадки, прямые ссылки остальных добирает поиск по имени."""
    store, number = code[:1], code[1:]
    try:
        if store == "d":
            found = deezer.album_release(number)
        elif store == "a":
            found = itunes.album_release(number)
        elif store == "y":
            # Через yandex_music._get, а не http: с адресов GitHub Яндекс отвечает 451, функция Облака — нет.
            found = _yandex(yandex_music._get(f"albums/{number}") or {})
        elif store == "s":
            # Тем же путём, что трек Spotify, — встраиваемый плеер. Даты выхода он не отдаёт.
            entity = otbor.spotify("album", number)
            found = {"artist": entity.get("subtitle", ""), "title": entity.get("name", ""),
                     "url": f"https://open.spotify.com/album/{number}", "cover": entity.get("cover", ""),
                     "track_count": len(entity.get("trackList") or []), "released_at": ""}
        else:
            return {}
    except Exception as exc:  # noqa: BLE001 — чужая страница не роняет бота
        log.info("Альбом не разобрался (%s): %s", code, exc)
        return {}
    if not (found.get("artist") and found.get("title")):
        return {}
    lead = otbor._credits(found["artist"])[0]
    return _album([found, *_stores(lead, STORE_TAIL.sub("", found["title"]), skip=store)])


def _yandex(data: dict) -> dict:
    """Альбом Яндекса, по id или из поиска, в виде релиза сбора."""
    return {"artist": ", ".join(a.get("name", "") for a in data.get("artists") or []),
            "title": data.get("title") or "", "url": f"https://music.yandex.ru/album/{data.get('id')}",
            "cover": f"https://{data['coverUri'].replace('%%', '600x600')}" if data.get("coverUri") else "",
            "track_count": data.get("trackCount"), "released_at": data.get("releaseDate") or ""}


def _stores(artist: str, title: str, skip: str = "") -> list[dict]:
    """Альбом по имени в Apple Music, Яндекс Музыке и Deezer — разом, а не по очереди:
    вкладыш должен приходить сразу. Сверка точная, как у трека (otbor._match): чужой альбом
    с тем же названием хуже никакого. skip — площадка, с которой альбом уже взят."""
    term = f"{artist} {title}"

    def pick(found: list[dict]) -> dict:
        # Сингл и альбом с одним названием — дело обычное; альбом важнее, сингл найдётся и треком.
        return max((item for item in found if otbor._match(item["artist"], item["title"], artist, title)),
                   key=lambda item: (item["track_count"] or 0) > 1, default={})

    def yandex() -> dict:
        found = (yandex_music._get("search", type="album", text=term, page=0) or {}).get("albums") or {}
        return pick([_yandex(item) for item in found.get("results") or []])

    def from_deezer() -> dict:
        # Дату выхода поиск Deezer не отдаёт: альбом, который есть только там, выйдет без неё.
        return pick([{"artist": item.get("artist", {}).get("name", ""), "title": item.get("title", ""), "url": item.get("link", ""),
                      "cover": item.get("cover_big") or "", "track_count": item.get("nb_tracks"), "released_at": ""}
                     for item in deezer.search_albums(term, limit=10)])

    # Яндекс первым: его данные идут в карточку «Артист — Альбом», а iTunes считает в треки и видео альбома.
    calls = {"y": yandex, "a": lambda: itunes.find_release(artist, title), "d": from_deezer}
    with ThreadPoolExecutor() as pool:
        jobs = [pool.submit(call) for letter, call in calls.items() if letter != skip]
    return [found for job in jobs if (found := job.result())]


def _album(found: list[dict]) -> dict:
    """Карточка альбома: данные первой площадки, ссылки остальных — в links (platforms).
    Сингл магазины заводят альбомом из одного трека — он остаётся треком, без числа треков."""
    if not found:
        return {}
    first = {**found[0], "links": [item["url"] for item in found[1:]]}
    if first.get("track_count") == 1:
        first.update(track_count=None, title=STORE_TAIL.sub("", first["title"]))
    return first


def concert(artist: str) -> str:
    """Строка о ближайшем концерте — только у артиста из базы канала: запрос
    к Афише — секунда-две, а вкладыш должен приходить сразу."""
    lead = otbor._credits(artist)[0]
    name = next((a["name"] for a in collect.load_artists() if afisha.same_name(a["name"], lead)), "")
    try:
        shows = sorted(afisha.upcoming(name), key=lambda c: c["day"]) if name else []
    except Exception as exc:  # noqa: BLE001 — без концерта вкладыш всё равно нужен
        log.info("Афиша не ответила (%s): %s", name, exc)
        return ""
    if not shows:
        return ""
    show, esc = shows[0], html.escape
    return f'▸ Концерт: <a href="{esc(show["url"])}">{esc(show["when"])}, {esc(show["city"])}</a>'


def platforms(track: dict) -> str:
    """Все площадки строкой: прямая ссылка — площадкам, где трек или альбом нашёлся, остальным — поиск.
    Поиск по «Артист Название» первым отдаёт что угодно: у альбома «INTRO» — трек «Intro»."""
    query = quote(f"{track['artist']} {track['title']}".strip(), safe="")
    direct = {publish._host(url): url for url in (*track.get("links", ()), track["url"])}
    return f"{publish.LISTEN_HEAD}\n" + " · ".join(
        f'<a href="{html.escape(direct.get(publish._host(search)) or search.format(q=query))}">{label}</a>'
        for label, search in config.LISTEN_SERVICES)


def _day(iso: str) -> str:
    """2024-03-06T… → 06.03.2024."""
    return ".".join(reversed(iso[:10].split("-")))


def caption(track: dict, show: str = "") -> str:
    """Подпись под карточкой: имя, у альбома — сколько треков и когда вышел, площадки строкой,
    концерт, откуда вкладыш."""
    head = f"<b>{html.escape(track['artist'])} — {html.escape(track['title'])}</b>"
    if track.get("track_count"):  # альбом: у трека этого поля нет
        # «Релиз», а не «вышел»: предзаказ тоже находится, и дата у него впереди.
        head += f"\nТреков: {track['track_count']}" + (
            f" · релиз {_day(track['released_at'])}" if track.get("released_at") else "")
    parts = [head, platforms(track)]
    if show:
        parts.append(show)
    # Ссылка с меткой: кому переслали вкладыш, делает свой — приходы видны в --sources.
    parts.append(f'<a href="https://t.me/{config.BOT_HANDLE.lstrip("@")}?start=vkladysh">{KICKER}</a>'
                 f" · {config.CHANNEL_HANDLE}")
    return "\n\n".join(parts)


def send(chat_id: str, track: dict) -> None:
    """Карточка с подписью; нет ни обложки, ни фото артиста — одна подпись."""
    with ThreadPoolExecutor() as pool:  # Афиша и обложка качаются разом: каждая — секунда-две
        show = pool.submit(concert, track["artist"])
        image = card.cover({"cover": track.get("cover", ""), "artist": track["artist"],
                            "track": track["title"], "kicker": KICKER})
    text = caption(track, show.result())
    if image is None:
        telegram.send_message(chat_id, text)
        return
    telegram.send_photo_file(chat_id, image, text)
    image.unlink(missing_ok=True)  # карточка уже у человека


ARTIST_KICKER = "КАРТОЧКА АРТИСТА"
# Первое предложение Википедии — о музыканте? Иначе строки «кто это» нет вовсе.
MUSICIAN = re.compile(r"рэпер|реп-исполнител|певец|певица|музыкант|продюсер|битмейкер|диджей|групп[аыу]|дуэт|"
                      r"rapper|singer|musician|producer|\bband\b|\bduo\b|\bDJ\b", re.IGNORECASE)


def first_sentence(text: str) -> str:
    """Первое предложение без скобок: в них настоящее имя, даты и «род.», на чьей точке
    предложение оборвалось бы. Точка после слова короче трёх букв — сокращение, не конец.
    Знаки ударения русской Википедии («Куэ́йво») в подписи читаются как мусор — снимаем."""
    text = text.replace("\u0301", "")
    while (bare := re.sub(r"\s*\([^()]*\)", "", text)) != text:
        text = bare
    for match in re.finditer(r"(\S+)[.!?](?=\s+[A-ZА-ЯЁ«\"]|\s*$)", text):
        if len(match.group(1)) > 2:
            return text[:match.end()].strip()
    return text.strip()


def who(name: str) -> str:
    """Кто это — первое предложение Википедии: сперва русской, потом английской."""
    for lang in ("ru", "en"):
        page = get_json(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/"
                        f"{quote(name.replace(' ', '_'), safe='')}", identify_as_bot=True, retries=2)
        if not page or page.get("type") != "standard":
            continue  # нет статьи или страница неоднозначности
        sentence = first_sentence(page.get("extract", ""))
        if MUSICIAN.search(sentence):
            return sentence
    return ""


def artist(artist_id: int | str) -> dict:
    """Карточка артиста по id Deezer: имя, фото, кто это, три последних релиза, подпись.
    Пусто — Deezer такого не знает или не ответил."""
    data = get_json(f"{deezer.BASE}/artist/{artist_id}", min_interval=deezer.MIN_INTERVAL) or {}
    if not data.get("name"):
        return {}
    picture = data.get("picture_xl") or data.get("picture_big") or ""
    today = state.now().strftime("%Y-%m-%d")
    releases, titles = [], set()
    # Предзаказ — ещё не релиз; у Deezer один альбом бывает заведён дважды.
    for release in sorted(deezer.recent_releases(int(artist_id), limit=50),
                          key=lambda r: r["released_at"], reverse=True):
        if release["released_at"][:10] <= today and release["title"].casefold() not in titles and len(releases) < 3:
            titles.add(release["title"].casefold())
            releases.append(release)
    found = {"id": int(artist_id), "name": data["name"], "url": data.get("link", ""),
             "photo": "" if deezer.EMPTY_PICTURE in picture else picture,
             "who": who(data["name"]), "releases": releases}
    found["caption"] = artist_caption(found)
    if telegram.visible_len(found["caption"]) > telegram.MAX_CAPTION:
        found["caption"] = artist_caption({**found, "who": ""})  # длинная Википедия уступает релизам
    return found


def artist_caption(found: dict) -> str:
    """Подпись карточки: имя и кто это, последние релизы, площадки, откуда карточка."""
    esc = html.escape
    parts = [f"<b>{esc(found['name'])}</b>" + (f"\n{esc(found['who'])}" if found.get("who") else "")]
    if found["releases"]:
        parts.append("Последние релизы:\n" + "\n".join(
            f'▸ <a href="{esc(r["url"])}">{esc(r["title"])}</a> · {_day(r["released_at"])}'
            for r in found["releases"]))
    parts.append(platforms({"artist": found["name"], "title": "", "url": found["url"]}))
    parts.append(f'<a href="{publish.ARTIST_LINK.format(found["id"])}">{ARTIST_KICKER}</a> · {config.CHANNEL_HANDLE}')
    return "\n\n".join(parts)


def send_artist(chat_id: str, found: dict, buttons: list[list[dict]]) -> None:
    """Фото артиста с подписью; фото нет или Telegram его не забрал — одна подпись."""
    if found["photo"]:
        try:
            telegram.send_photo(chat_id, found["photo"], found["caption"], buttons=buttons)
            return
        except telegram.TelegramError as exc:
            log.info("Фото артиста не ушло (%s): %s", found["name"], exc)
    telegram.send_message(chat_id, found["caption"], buttons=buttons)


def _selftest() -> None:
    from types import SimpleNamespace

    real = (otbor.by_link, otbor.lookup, otbor.spotify, collect.load_artists, afisha.upcoming,
            deezer.search_albums, deezer.album_release, itunes.find_release, itunes.album_release, yandex_music._get, get)
    asked, albums = [], []
    # Магазины самопроверки. Трек «Intro» есть у Bones и у Berg Chopper, альбом «INTRO» — только
    # у Berg Chopper, на всех площадках; ссылка на альбом треком не разбирается.
    otbor.by_link = lambda url: asked.append(url) or ({} if "/album/" in url else {
        "artist": "Toxi$, Bushido Zho", "title": "Молния", "url": "https://music.yandex.ru/track/1", "cover": ""})
    otbor.lookup = lambda artist, title: asked.append((artist, title)) or (
        {"artist": artist, "title": "Intro", "url": "https://music.apple.com/us/song/1", "cover": ""}
        if title.casefold() == "intro" else {})
    release = {"artist": "Berg Chopper", "title": "INTRO", "url": "https://www.deezer.com/album/554626402",
               "cover": "", "track_count": 18, "released_at": "2024-03-06T00:00:00+00:00"}
    apple = {**release, "url": "https://music.apple.com/us/album/intro/1734584671?uo=4"}
    deezer.search_albums = lambda query, limit=25: albums.append(query) or [
        {"id": 7, "title": "Intro", "artist": {"name": "Чужой"}, "link": "https://www.deezer.com/album/7", "nb_tracks": 9},
        {"id": 8, "title": "Intro", "artist": {"name": "Berg Chopper"}, "link": "https://www.deezer.com/album/8", "nb_tracks": 1},
        {"id": 554626402, "title": "INTRO (Deluxe)", "artist": {"name": "Berg Chopper"}, "link": release["url"], "nb_tracks": 18}]
    deezer.album_release = lambda number: dict(release) if str(number) == "554626402" else {}
    itunes.find_release = lambda artist, title: dict(apple) if artist == "Berg Chopper" else {}
    itunes.album_release = lambda number: dict(apple) if str(number) == "1734584671" else {
        **apple, "artist": "Bones", "title": "Dirt - Single", "url": "https://music.apple.com/us/album/dirt-single/99", "track_count": 1}
    disc = {"id": 30026308, "title": "INTRO", "artists": [{"name": "Berg Chopper"}], "trackCount": 18,
            "releaseDate": "2024-03-06T00:00:00+03:00", "coverUri": "avatars.yandex.net/x/%%"}
    yandex_music._get = lambda path, **params: {"albums/30026308": disc, "search": {"albums": {"results": [disc]}}}.get(path)
    otbor.spotify = lambda kind, number: {"name": "INTRO", "subtitle": "Berg Chopper", "trackList": [{}] * 18,
                                          "cover": "https://i.scdn.co/x"} if (kind, number) == ("album", "4eLPsY") else {}
    globals()["get"] = lambda url: SimpleNamespace(url="https://www.deezer.com/album/554626402?host=0")
    collect.load_artists = lambda: [{"name": "Toxi$"}]
    afisha.upcoming = lambda name: [{"day": "2026-11-02", "when": "2 ноября", "city": "Москва", "url": "https://afisha.yandex.ru/e/2"},
                                {"day": "2026-10-12", "when": "12 октября", "city": "Казань", "url": "https://afisha.yandex.ru/e/1"}]
    try:
        track = find("лови https://music.yandex.ru/track/1?utm=x")
        assert track["title"] == "Молния" and asked == ["https://music.yandex.ru/track/1?utm=x"], asked
        find("Bones — «Dirt»")
        assert asked[-1] == ("Bones", "Dirt"), asked
        for junk in ("привет", "Bones —", "строка — раз\nстрока — два", ""):
            assert find(junk) == {}, junk
        assert asked[-1] == ("Bones", "Dirt") and albums == ["Bones Dirt"], "мусор не должен уходить в магазины"

        # Альбом ссылкой: та же подпись, плюс треки и дата; прямые ссылки — всем площадкам, где он нашёлся.
        album_ = find("https://www.deezer.com/ru/album/554626402?utm=x")
        assert album_ == {**release, "links": ["https://music.yandex.ru/album/30026308", apple["url"]]}, album_
        assert albums == ["Bones Dirt"], "свою площадку второй раз не спрашиваем"
        text = caption(album_)
        assert text.startswith("<b>Berg Chopper — INTRO</b>\nТреков: 18 · релиз 06.03.2024\n\n"), text
        for direct in ('deezer.com/album/554626402">Deezer', 'album/intro/1734584671?uo=4">Apple', 'album/30026308">Яндекс'):
            assert direct in text, f"прямая ссылка на альбом: {direct}"
        assert "open.spotify.com/search/Berg%20Chopper%20INTRO" in text, "остальным площадкам — поиск"
        assert text.count("<a href") == len(config.LISTEN_SERVICES) + 1, text
        yandex = find("https://music.yandex.ru/album/30026308")
        assert yandex["url"] == "https://music.yandex.ru/album/30026308" and yandex["cover"].endswith("/600x600"), yandex
        assert 'album/30026308">Яндекс' in caption(yandex) and "релиз 06.03.2024" in caption(yandex)
        assert yandex["links"] == [apple["url"], release["url"]], "одноимённый сингл Deezer уступает альбому"
        assert find("https://music.yandex.ru/album/404") == {}, "Яндекс не ответил — карточки нет"
        assert not YANDEX_ALBUM.search("https://music.yandex.ru/album/30026308/track/5"), "ссылка на трек — не альбом"
        # Короткая ссылка Deezer раскрывается редиректом; альбом Spotify — из плеера, даты у него нет.
        assert find("https://link.deezer.com/s/abc") == album_, "короткая ссылка Deezer"
        spotify = find("https://open.spotify.com/album/4eLPsY?si=1")
        assert spotify["track_count"] == 18 and len(spotify["links"]) == 3, spotify
        assert "Треков: 18\n" in caption(spotify) and 'spotify.com/album/4eLPsY">Spotify' in caption(spotify)
        assert find("https://open.spotify.com/album/404") == {}

        # «Артист — Альбом»: трека с таким именем нет — альбом; чужой альбом с тем же названием не берём.
        named = find("Berg Chopper — INTRO (Deluxe)")
        assert named["track_count"] == 18 and named["links"] == [apple["url"], release["url"]], named
        assert named["url"] == "https://music.yandex.ru/album/30026308", "карточка — из данных Яндекса"
        assert find("Чужой — Никакой") == {}
        # Трек важнее альбома, альбом с тем же именем — кнопкой «💿 Альбом»; нет такого альбома — нет и кнопки.
        both = find("Berg Chopper — INTRO")
        assert both["title"] == "Intro" and both["album"] == "y30026308" and "track_count" not in both, both
        assert album(both["album"])["track_count"] == 18 and album("x1") == {} and album("") == {}
        assert "album" not in find("Bones — Intro") and "Треков" not in caption(track)
        # Сингл магазин заводит альбомом из одного трека — он остаётся треком; ?i= — трек альбома.
        single = find("https://music.apple.com/us/album/dirt-single/99")
        assert single["title"] == "Dirt" and "Треков" not in caption(single), single
        assert album_code("https://music.apple.com/us/album/intro/1734584671?i=5") == ""

        show = concert(track["artist"])
        assert "12 октября, Казань" in show and "e/1" in show, show
        text = caption(track, show)
        assert text.startswith("<b>Toxi$, Bushido Zho — Молния</b>"), text
        assert 'href="https://music.yandex.ru/track/1"' in text, "ссылка человека — своей площадке"
        assert text.count("<a href") == len(config.LISTEN_SERVICES) + 2, "все площадки, концерт и метка"
        assert "Apple" in text and "?start=vkladysh" in text and config.CHANNEL_HANDLE in text, text
        assert telegram.visible_len(text) <= telegram.MAX_CAPTION
        collect.load_artists = lambda: []
        assert concert(track["artist"]) == "", "чужой артист — Афишу не спрашиваем"
    finally:
        (otbor.by_link, otbor.lookup, otbor.spotify, collect.load_artists, afisha.upcoming,
         deezer.search_albums, deezer.album_release, itunes.find_release, itunes.album_release, yandex_music._get,
         globals()["get"]) = real
    print("vkladysh: ссылка и «Артист — Трек», отказ на мусоре, площадки и концерт в подписи — ок")
    print("альбом: ссылка (и короткая Deezer, и Spotify) и «Артист — Альбом», прямые ссылки трёх площадок, "
          "трек важнее альбома и несёт кнопку «💿 Альбом», сингл остаётся треком — ок")

    # КАРТОЧКА АРТИСТА: Википедия только о музыканте, три последних релиза без предзаказа и дублей.
    assert first_sentence("Oxxxymiron (род. 31 января 1985, Ленинград) — российский рэпер. Основатель лейбла.") \
        == "Oxxxymiron — российский рэпер."
    assert first_sentence("Куэ\u0301йво — рэпер.") == "Куэйво — рэпер."
    assert first_sentence("Quavo (born April 2, 1991) is an American rapper from Georgia. He is") \
        == "Quavo is an American rapper from Georgia."
    pages = {"ru": {"type": "standard", "extract": "Кости — твёрдые органы скелета. Их много."},
             "en": {"type": "standard", "extract": "Bones (born 1994) is an American rapper and producer."}}
    wiki = lambda url, **kw: pages[url[8:10]] if "wikipedia" in url else {
        "name": "Bones", "link": "https://www.deezer.com/artist/5", "picture_xl": "https://x/p.jpg"}
    rows = [{"title": t, "url": f"https://www.deezer.com/album/{n}", "released_at": d} for n, (t, d) in enumerate(
        (("Old", "2020-01-01"), ("Later", "2099-01-01"), ("Dirt", "2026-09-01"), ("DIRT", "2026-08-31"),
         ("Tape", "2026-05-02"), ("Mid", "2024-03-03")))]
    real = globals()["get_json"], deezer.recent_releases
    globals()["get_json"], deezer.recent_releases = wiki, lambda artist_id, limit=5: rows
    try:
        found = artist(5)
        pages["en"]["extract"] = "Bones is a 2001 American horror film."
        assert artist(5)["who"] == "", "не о музыканте — строки нет"
    finally:
        globals()["get_json"], deezer.recent_releases = real
    assert found["who"] == "Bones is an American rapper and producer.", found["who"]
    assert [r["title"] for r in found["releases"]] == ["Dirt", "Tape", "Mid"], found["releases"]
    text = found["caption"]
    assert text.startswith("<b>Bones</b>\nBones is an American rapper") and "Dirt</a> · 01.09.2026" in text, text
    assert 'href="https://www.deezer.com/artist/5">Deezer' in text and "search?text=Bones\"" in text, text
    assert publish.ARTIST_LINK.format(5) in text and telegram.visible_len(text) <= telegram.MAX_CAPTION
    print("карточка артиста: Википедия только о музыканте, три последних релиза, площадки — ок")


def main() -> int:
    parser = argparse.ArgumentParser(description="ВКЛАДЫШ: карточка трека или альбома со всеми площадками")
    parser.add_argument("--selftest", action="store_true", help="проверка без сети")
    parser.add_argument("--dry-run", metavar="ТЕКСТ", help="что бот ответит, без Telegram")
    parser.add_argument("--artist", metavar="ID", help="карточка артиста по id Deezer, без Telegram")
    args = parser.parse_args()
    if args.artist:
        found = artist(args.artist)
        print(f"{found['caption']}\n\nфото: {found['photo'] or 'нет'}" if found else "Deezer такого артиста не знает.")
        return 0 if found else 1
    if args.selftest:
        _selftest()
        return 0
    if args.dry_run:
        track = find(args.dry_run)
        if not track:
            print("Не трек и не альбом: бот ответит прежним путём (разбор или «не разобрал»).")
            return 1
        print(caption(track, concert(track["artist"])))
        image = card.cover({"cover": track.get("cover", ""), "artist": track["artist"],
                            "track": track["title"], "kicker": KICKER})
        print(f"\nкарточка: {image or 'нет, уйдёт одна подпись'}")
        if track.get("album"):
            print(f"кнопка «💿 Альбом»: {track['album']}")
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sys.exit(main())
