"""ДО ХИТА — раз в неделю короткий пост о том, как артист из СНГ, который сейчас на пике, пробился к первому хиту.

Решение владельца 20.10.2026: канал — для начинающих рэперов, а им полезнее чужих релизов история,
сколько шёл к хиту тот, кого они слушают: срок, что сработало, его собственные слова. Проба на четыре
недели: пост зовёт прислать свой трек в ОТБОР по ссылке ?start=otbor_dohita, и 17.11.2026 по счёту этой
метки (service --sources) рубрику оставят или снимут (NEXT.md).

Пост — шаблоном, без модели, из записи базы data/dohita.json: заголовок «ДО ХИТА · <АРТИСТ>: <срок>»,
строки записи, слова артиста в рамке, последней строкой — ссылка в ОТБОР. Модель историю артиста не знает,
а пересказ интервью своими словами — та же выдумка с чужой подписью. Поэтому у каждой строки записи
есть источники — адрес страницы и дословная цитата с неё, — и автопилот точности такой пост не правит
(review.TEMPLATE): править в нём нечего, а сломать есть что. Кадр — фото артиста через card.cover, как
у разбора; нет фото или все уже выходили — пост уходит текстом.

Базу пополняет автопилот точности (src/review.py, поле dohita файла правок), когда в запасе меньше
config.DOHITA_MIN_PENDING невышедших героев (review --dohita). Берёт запись код, а не рутина: здесь
проверяется форма без сети (shape) — артист из data/artists.json, сайт из списка review.trusted, числа
в строке только из её цитат или из Deezer, ни слова о звуке, длине треков и «рецепте успеха», пост не длиннее
LIMIT видимых знаков, — а при применении (unproven) каждая страница скачивается, цитата ищется на ней
слово в слово, страница называет артиста, а релиз из Deezer стоит у него с той же датой. Число релизов
до хита Deezer не подтверждает: даты ранних релизов там бывают поставлены задним числом, и из цитаты
Deezer в строку разрешён только год. Герой уже был — отказ; не прошла проверка — строка в лог, запись
отброшена молча. Записи, внесённые руками (by: hand), владелец утвердил сам, и строгой проверке они
не подлежат: «4-е место» у Toxi$ стоит в цитате словом «четвертое».

Выход — в дни config.DOHITA_DAYS с DOHITA_HOUR_MSK по Москве, не ночью, один пост в сутки ленты, герои
по порядку базы; путь — общий для своих форматов publish.offer: при PUBLISH_TARGET=admin владельцу
в личку на «✅», мимо слотов и без ВКонтакте (ссылка ведёт в бота Telegram). Отметка вышедшего —
dohita-<id>.json в content/archive, id — номер артиста в Deezer, поэтому его не менять. Владелец не нажал
в свои сутки — тот же герой выйдет в следующую пятницу. База кончилась — рубрика молчит, с последним
героем владельцу уходит строка.
Отвергнуто: срок до хита по датам Deezer (см. выше), пост от модели по найденным статьям (выдумка звучания
и «секретов успеха» — первое, что она пишет) и отдельный счётчик «кто следующий» (отметки в архиве уже знают).

    python -m src.dohita --selftest   без сети и Telegram
    python -m src.dohita --dry-run    кто в запасе и текст следующего поста, без записи и отправки
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from . import config, state

RUBRIC = "dohita"
TITLE = "ДО ХИТА"
START = "otbor_dohita"  # метка ссылки: открывает ОТБОР (service.SOURCES) и считается в service --sources
CALL = "Свой трек — в ОТБОР ПЛЁНКИ"  # со значком «▸ » — 28 знаков, pamyatka.LINE_MAX: одна строка телефона
LIMIT = 600  # видимых знаков поста
LINES, AFTER = 3, 2  # строк до рамки и после неё
QUOTE = (20, 400)  # длина цитаты источника
DEEZER = "https://api.deezer.com/artist/{}/albums"
RELEASE = re.compile(r"(.+), (\d{4})-\d{2}-\d{2}")  # цитата Deezer: «Название, ГГГГ-ММ-ДД»
RECIPE = re.compile(r"рецепт\w*|(?:формул|секрет)\w*\s+успех\w*", re.IGNORECASE)
ASK = "А ты сколько уже выпускаешь треки?"
LAST = "📌 Запас ДО ХИТА кончился: {artist} — последний герой базы. Новых приносит автопилот точности (review --dohita)."


def load(base: dict | None = None) -> list[dict]:
    """Герои базы. Без id, артиста, срока, строк или цитаты — не запись: базу правят и руками."""
    base = state.read_json(config.DOHITA_FILE, {"heroes": []}) if base is None else base
    return [hero for hero in base.get("heroes", []) if isinstance(hero, dict)
            and all(hero.get(field) for field in ("id", "artist", "deezer_id", "term", "lines", "quote"))]


def pending(base: dict | None = None) -> list[dict]:
    """Невышедшие герои в порядке базы."""
    return [hero for hero in load(base) if not (config.ARCHIVE / f"{RUBRIC}-{hero['id']}.json").exists()]


def build(hero: dict) -> dict:
    """Пост канала. Имя в заголовке заглавными: ссылку на карточку артиста (publish.artist_links) оно
    получает полем links — сверка имени там с учётом регистра."""
    say = lambda text: html.escape(text, quote=False)  # noqa: E731
    link = f"https://t.me/{config.BOT_HANDLE.lstrip('@')}?start={START}"
    parts = [f"<b>{TITLE} · {say(hero['artist'].upper())}: {say(hero['term'].upper())}</b>",
             *(say(line["text"]) for line in hero["lines"]),
             f"<blockquote>«{say(hero['quote']['text'])}»</blockquote>",
             *(say(line["text"]) for line in hero.get("after") or []),
             f'▸ <a href="{link}">{CALL}</a>']
    return {"rubric": RUBRIC, "id": hero["id"], "artist": hero["artist"], "kicker": TITLE, "comment": ASK,
            "links": {hero["artist"].upper(): hero["deezer_id"], hero["artist"]: hero["deezer_id"]},
            "text": "\n\n".join(parts)}


def visible(text: str) -> int:
    """Видимая длина, как telegram.visible_len: тот тянет requests, а shape зовёт облачный автор без него."""
    return len(html.unescape(re.sub(r"<[^>]+>", "", text)))


def aired(moment: datetime) -> bool:
    """Выходил ли пост рубрики в эти сутки ленты — по журналу публикаций, как у ПАМЯТКИ."""
    from . import publish

    today = publish.feed_day(moment)
    return any(item.get("rubric") == RUBRIC and (at := state._parse(item.get("published_at", "")))
               and publish.feed_day(at) == today
               for item in state.read_json(config.POSTED_FILE, {"items": []}).get("items", []))


def due(moment: datetime | None = None) -> bool:
    """День рубрики с DOHITA_HOUR_MSK по Москве, не ночью, и в эти сутки ленты пост ещё не выходил."""
    from . import publish
    from .compose import MSK

    moment = moment or state.now()
    local = moment.astimezone(MSK)
    return (local.weekday() in config.DOHITA_DAYS and local.hour >= config.DOHITA_HOUR_MSK
            and not publish.night(moment) and not aired(moment))


def air(target: str = "channel") -> str:
    """Выход из дежурства (moderate.publish_shift): id вышедшего героя (при target admin — поданного владельцу
    на «✅», publish.offer) или пустая строка. Не вышло — отметка снимается, следующий заход пробует снова."""
    from . import publish, telegram

    left = pending()
    if not left or not due():
        return ""
    post = build(left[0])
    if not publish.offer(post, f"{RUBRIC}-{post['id']}.json", target, label=TITLE):
        return ""
    if len(left) == 1:
        try:
            telegram.send_message(config.secret("TELEGRAM_ADMIN_ID"), LAST.format(artist=html.escape(post["artist"])))
        except telegram.TelegramError as exc:  # пост уже ушёл — строка владельцу его не отменяет
            print(f"  ДО ХИТА: строка о запасе не ушла: {str(exc)[:120]}")
    return post["id"]


def need(base: dict | None = None) -> int:
    """Сколько новых героев искать автопилоту точности. Ноль — не ищет: рубрика снята (DOHITA_DAYS пуст),
    в запасе хватает или искали меньше DOHITA_RETRY_HOURS назад."""
    base = state.read_json(config.DOHITA_FILE, {"heroes": []}) if base is None else base
    searched = state._parse(base.get("searched_at") or "")
    if not config.DOHITA_DAYS or searched and state.now() - searched < timedelta(hours=config.DOHITA_RETRY_HOURS):
        return 0
    return max(0, config.DOHITA_MIN_PENDING - len(pending(base)))


def taken(base: dict | None = None) -> list[str]:
    """Герои, которые в базе уже есть, — имена для рутины (review --dohita)."""
    return [hero["artist"] for hero in load(base)]


def _artist(hero: dict) -> dict | None:
    return next((artist for artist in state.read_json(config.ARTISTS_FILE, {"artists": []}).get("artists", [])
                 if artist.get("name") == hero.get("artist") and artist.get("deezer_id") == hero.get("deezer_id")), None)


def _sources(hero: dict) -> list[dict]:
    """Все источники записи: строк и рамки (слова в рамке — сама цитата своей страницы)."""
    return [*(source for line in [*hero["lines"], *(hero.get("after") or [])] for source in line["sources"]),
            {"url": hero["quote"]["url"], "quote": hero["quote"]["text"]}]


def shape(hero, sites: list[str]) -> str:
    """Что не так с героем из файла правок, насколько видно без сети. Пустая строка — годен по форме;
    страницы и Deezer сверит unproven при применении."""
    from . import quality
    from .review import _digits, _filled, _trusted

    if not isinstance(hero, dict):
        return "герой — это объект"
    if not _artist(hero):
        return "artist и deezer_id — как у артиста в data/artists.json, буква в букву"
    if not _filled(hero.get("term")):
        return "term: срок до хита словами — «три года»"
    frame = hero.get("quote")
    if not (isinstance(frame, dict) and _filled(frame.get("text")) and _filled(frame.get("url"))):
        return "quote: text — слова артиста для рамки, url — страница, где они стоят"
    lines, after = hero.get("lines"), hero.get("after", [])
    if not (isinstance(lines, list) and 1 <= len(lines) <= LINES and isinstance(after, list) and len(after) <= AFTER):
        return f"lines: от 1 до {LINES} строк до рамки, after: до {AFTER} после"
    deezer = DEEZER.format(hero["deezer_id"])
    known = _digits(hero["artist"])  # «Три 6 Мафия» — не число
    every: set[str] = set()
    if not all(isinstance(line, dict) and _filled(line.get("text")) and isinstance(line.get("sources"), list)
               and line["sources"] for line in [*lines, *after]):
        return "у каждой строки text и sources — хотя бы один источник"
    # Слова в рамке — сами цитата своей страницы: строка без текста с одним источником.
    for line in [*lines, *after, {"text": "", "sources": [{"url": frame["url"], "quote": frame["text"]}]}]:
        own: set[str] = set()
        for source in line["sources"]:
            if not (isinstance(source, dict) and _filled(source.get("url")) and _filled(source.get("quote"))):
                return "sources: url страницы и quote — дословная цитата с неё"
            if source["url"] == deezer:
                if not (match := RELEASE.fullmatch(source["quote"].strip())):
                    return f"цитата Deezer ({deezer}): «Название релиза, ГГГГ-ММ-ДД»"
                own.add(match.group(2))  # из Deezer — только год: счёт релизов по его датам врёт
                continue
            if not source["url"].startswith(("http://", "https://")) or not _trusted(source["url"], sites):
                return f"{urlparse(source['url']).netloc or source['url']}: этого сайта нет в списке sites из --dohita"
            if not QUOTE[0] <= len(source["quote"].strip()) <= QUOTE[1]:
                return f"quote: {QUOTE[0]}–{QUOTE[1]} знаков"
            own |= _digits(source["quote"])
        every |= own
        if extra := _digits(line["text"]) - own - known:
            return f"строка «{line['text'][:40]}»: чисел {', '.join(sorted(extra))} нет в её цитатах"
        ours = re.sub(r"«[^»]*»", "", line["text"]).lower()  # слова артиста в кавычках — его, а не наши
        if quality.INVENTED_SOUND.search(ours) or quality.DURATION.search(ours) or RECIPE.search(ours):
            return f"строка «{line['text'][:40]}»: о звуке, длине треков и «рецепте успеха» не пишем"
    if extra := _digits(hero["term"]) - every - known:
        return f"term: чисел {', '.join(sorted(extra))} нет в цитатах"
    if visible(build({**hero, "id": "-"})["text"]) > LIMIT:
        return f"пост длиннее {LIMIT} видимых знаков"
    return ""


def unproven(hero: dict, sites: list[str], page, albums) -> str:
    """Почему герою нельзя верить; пустая строка — подтвердился. Тут вся сеть, она передаётся снаружи:
    page — web_voice.page, albums — релизы артиста в Deezer.

    Рутине верим не больше, чем модели: страницу код качает сам, цитату ищет на ней по словам
    (review._words — сноски и разметка не мешают), и каждая страница должна называть артиста
    в заголовке или тексте — иначе правдивая цитата о другом человеке стала бы его историей.
    """
    from . import quality
    from .review import _named, _trusted, _words

    artist = _artist(hero) or {}
    names = [hero["artist"], *(artist.get("aliases") or [])]
    deezer = DEEZER.format(hero["deezer_id"])
    pages: dict[str, tuple[str, str] | None] = {}
    for source in _sources(hero):
        url, quote = source["url"], source["quote"].strip()
        if url == deezer:
            title, date = quote.rsplit(", ", 1)
            if not any(quality.norm(item.get("title", "")) == quality.norm(title) and item.get("release_date") == date
                       for item in albums(hero["deezer_id"])):
                return f"релиза «{quote}» у артиста в Deezer нет"
            continue
        if url not in pages:
            got = page(url)
            # Переадресация могла увести на чужой сайт — такой странице не верим тоже.
            pages[url] = (quality.norm(got[1]), quality.norm(got[2])) if got and _trusted(got[0], sites) else None
        if pages[url] is None:
            return f"страница {url} не скачалась"
        title, text = pages[url]
        if _words(quote) not in _words(text):
            return f"цитаты нет на странице {url} слово в слово"
        if not any(_named(name, title) or _named(name, text) for name in names):
            return f"страница {url} не называет {hero['artist']}"
    return ""


def take(found: list[dict], dry_run: bool, page=None, albums=None) -> None:
    """Новые герои из файла правок — в data/dohita.json. Форму уже проверил review.check.

    Не прошёл — строка в лог, а не красный запуск и не письмо владельцу: это промах автора, а не поломка.
    Герой, который в базе уже есть (тот же номер Deezer), второй раз не берётся. Ручные записи не трогаются:
    запись только дописывается. Проход запоминается и пустым — иначе искали бы каждые два часа.
    """
    from .review import trusted

    base = state.read_json(config.DOHITA_FILE, {"heroes": []})
    left = need(base)
    ids = {str(hero.get("deezer_id")) for hero in base.get("heroes", [])}
    if not dry_run and page is None:
        # Не наверху: --check зовёт облачный автор, а эти модули тянут requests.
        from .sources import deezer, web_voice

        page = web_voice.page
        albums = lambda artist_id: (deezer.get_json(f"{deezer.BASE}/artist/{artist_id}/albums",  # noqa: E731
                                                    params={"limit": 500}, min_interval=deezer.MIN_INTERVAL)
                                    or {}).get("data", [])
    sites = trusted()
    for hero in found:
        why = ("герой сейчас не нужен" if left <= 0 else "герой уже был" if str(hero["deezer_id"]) in ids
               else "" if dry_run else unproven(hero, sites, page, albums))
        if why:
            print(f"  — герой «{hero['artist']}»: {why}")
            continue
        if dry_run:
            print(f"  герой «{hero['artist']}»: сверился бы со страницами источников и Deezer")
            continue
        base.setdefault("heroes", []).append({"id": str(hero["deezer_id"]), "by": "auto", "added_at": state.iso(),
                                              **{field: hero[field] for field in ("artist", "deezer_id", "term", "lines", "quote")},
                                              "after": hero.get("after") or []})
        ids.add(str(hero["deezer_id"]))
        left -= 1
        print(f"  герой «{hero['artist']}» принят: {hero['term']}")
    if not dry_run:
        base["searched_at"] = state.iso()
        # Не state.write_json: тот сортирует ключи, а файл правят и читают руками.
        config.DOHITA_FILE.write_text(json.dumps(base, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _selftest() -> None:
    from unittest import mock

    from . import pamyatka, publish, review, service, telegram

    # Настоящая база: у каждого героя артист из базы канала, источники у каждой строки, пост в пределах.
    heroes = load()
    assert heroes and heroes[0]["artist"] == "Toxi$" and heroes[0]["id"] == "74526042", "первый герой — Toxi$"
    for hero in heroes:
        assert _artist(hero) and hero["id"] == str(hero["deezer_id"]), f"{hero['id']}: имя и номер Deezer — как в базе артистов"
        assert all(source.get("url") and source.get("quote") for source in _sources(hero)), f"{hero['id']}: источник без адреса"
        assert all(line["sources"] for line in [*hero["lines"], *(hero.get("after") or [])]), f"{hero['id']}: строка без источника"
        text = build(hero)["text"]
        assert visible(text) <= LIMIT, f"{hero['id']}: {visible(text)} знаков"
    toxi = build(heroes[0])
    assert toxi["text"].startswith("<b>ДО ХИТА · TOXI$: ТРИ ГОДА</b>"), toxi["text"][:60]
    assert "<blockquote>«Три года мне понадобилось, чтобы наступить на разные грабли»</blockquote>" in toxi["text"]
    tail = toxi["text"].rsplit("\n\n", 1)[1]
    assert tail == f'▸ <a href="https://t.me/{config.BOT_HANDLE.lstrip("@")}?start={START}">{CALL}</a>', tail
    assert visible(tail) <= pamyatka.LINE_MAX, "строка ОТБОРА рвётся на телефоне"
    assert START in service.SOURCES, "метка открывает ОТБОР и считается в service --sources"
    linked = publish.artist_links(toxi["text"], toxi)
    assert "start=a_74526042\">TOXI$</a>" in linked, "имя в заголовке — ссылкой на карточку"
    assert RUBRIC in config.OWN_RUBRICS and RUBRIC in review.TEMPLATE, "своё и автопилотом не правится"

    # Проверка героя из файла правок: форма без сети и сверка со страницами.
    sites = ["the-flow.ru", "wikipedia.org"]
    page_url = "https://the-flow.ru/a"
    good = {"artist": "Toxi$", "deezer_id": 74526042, "term": "два года",
            "lines": [{"text": "Первый релиз — в 2019-м, хит — в 2023-м.",
                       "sources": [{"url": DEEZER.format(74526042), "quote": "Welcome Slime, 2019-11-24"},
                                   {"url": page_url, "quote": "Видео рэпера завирусились в 2023 году"}]}],
            "quote": {"text": "Два года я просто пробовал всё подряд", "url": page_url}}
    assert shape(good, sites) == "", shape(good, sites)
    wrong = lambda **change: shape({**good, **change}, sites)  # noqa: E731
    line = good["lines"][0]
    assert "источник" in wrong(lines=[{"text": "Первый релиз — в 2019-м.", "sources": []}]), "строка без источника — отказ"
    assert "сайта нет" in wrong(lines=[{**line, "sources": [{"url": "https://blog.example/x", "quote": "Видео рэпера завирусились в 2023 году"}]}])
    assert "чисел 5" in wrong(lines=[{**line, "text": "До хита выпустил 5 релизов в 2019-м."}]), "число не из цитаты"
    assert "чисел 11" in wrong(lines=[{**line, "text": "Хит — с 11-го релиза, в 2019-м."}]), "из даты Deezer — только год"
    assert "звуке" in wrong(lines=[{**line, "text": "Бит в 2019-м был тёмный."}]) and "звуке" in wrong(
        lines=[{**line, "text": "Рецепт прост: в 2019-м начал."}]), "звук и «рецепт успеха» — отказ"
    assert "artists.json" in wrong(artist="Toxic"), "артист не из базы канала"
    assert "длиннее" in wrong(lines=[{**line, "text": "Долго " * 60 + "в 2019-м."}] * 3)

    words = "Toxi$: Видео рэпера завирусились в 2023 году. Два года я просто пробовал всё подряд, говорит он."
    pages = {page_url: (page_url, "Toxi$ — интервью", words)}
    releases = [{"title": "Welcome Slime", "release_date": "2019-11-24"}]
    assert unproven(good, sites, pages.get, lambda _: releases) == ""
    moved = {page_url: (page_url, "Интервью", words.replace("завирусились", "разлетелись"))}
    assert "слово в слово" in unproven(good, sites, moved.get, lambda _: releases), "цитаты нет на странице — отказ"
    nobody = {page_url: (page_url, "Интервью", words.replace("Toxi$: ", ""))}
    assert "не называет" in unproven(good, sites, nobody.get, lambda _: releases), "страница о другом"
    assert "Deezer нет" in unproven(good, sites, pages.get, lambda _: [{"title": "Welcome Slime", "release_date": "2020-01-01"}])
    assert "не скачалась" in unproven(good, sites, {}.get, lambda _: releases)

    assert review.check({"dohita": [good]}) == ([], {}), review.check({"dohita": [good]})
    assert review.check({"dohita": []}) == ([], {}), "искали и не нашли — годный файл"
    assert review.check({"dohita": [{**good, "lines": []}]})[0], "битый герой — файл не годен"

    real = state.now
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        friday = datetime.fromisoformat("2026-10-23T12:05:00+03:00")
        with mock.patch.multiple(config, ARCHIVE=root / "archive", POSTED_FILE=root / "posted.json", OFFERS=root / "offers",
                                 DOHITA_FILE=root / "dohita.json", QUEUE=root / "queue", OTBOR_POSTS=root / "otbor"):
            # Пополнение: принят, повтор — «уже был», при полном запасе и сразу после поиска не ищем.
            state.now = lambda: friday
            assert need({"heroes": []}) == config.DOHITA_MIN_PENDING
            with mock.patch.object(review, "trusted", lambda: sites):
                take([good], False, pages.get, lambda _: releases)
                stored = state.read_json(config.DOHITA_FILE, {})
                assert [hero["id"] for hero in stored["heroes"]] == ["74526042"] and stored["heroes"][0]["by"] == "auto"
                assert need() == 0, "искали только что"
                state.write_json(config.DOHITA_FILE, {"heroes": stored["heroes"]})
                assert need() == 1
                take([good], False, pages.get, lambda _: releases)
                assert len(state.read_json(config.DOHITA_FILE, {})["heroes"]) == 1, "герой уже был"
                state.write_json(config.DOHITA_FILE, {"heroes": []})
                take([{**good, "quote": {**good["quote"], "text": "Этих слов на странице нет вообще"}}], False,
                     pages.get, lambda _: releases)
                assert state.read_json(config.DOHITA_FILE, {})["heroes"] == [], "не подтвердился — отброшен молча"
            with mock.patch.object(config, "DOHITA_DAYS", ()):
                state.write_json(config.DOHITA_FILE, {"heroes": []})
                assert need() == 0, "рубрика снята — не ищем"

            # Выход: пятница с 12:00, не ночью, по одному; последний герой — строка владельцу.
            state.write_json(config.DOHITA_FILE, {"heroes": [heroes[0], {**heroes[0], "id": "2", "artist": "Big Baby Tape"}]})
            for moment, want in ((friday.replace(hour=11, minute=59), False), (friday, True),
                                 (friday - timedelta(days=1), False), (friday.replace(hour=23, minute=30), False)):
                state.now = lambda moment=moment: moment
                assert due() is want, moment
            state.now = lambda: friday
            sent, said = [], []
            with mock.patch.object(publish, "to_channel", lambda post, path, chat: sent.append(post)), \
                    mock.patch.object(telegram, "send_message", lambda chat, text, **_: said.append(text)), \
                    mock.patch.object(config, "secret", lambda *a, **k: "1"):
                assert air() == "74526042" and (config.ARCHIVE / "dohita-74526042.json").exists() and not said
                assert sent[0]["text"] == toxi["text"] and sent[0]["kicker"] == TITLE
                state.write_json(config.POSTED_FILE, {"items": [{"rubric": RUBRIC, "chat": "channel", "published_at": state.iso()}]})
                assert air() == "", "второй за сутки ленты не выходит"
                state.write_json(config.POSTED_FILE, {"items": []})
                # PUBLISH_TARGET=admin: владельцу кандидатом, в архив — только по его «✅».
                offered: list[str] = []
                with mock.patch.object(publish, "send_for_approval",
                                       lambda post, path, chat, label="": offered.append((path.name, label))):
                    assert air("admin") == "2" and air("admin") == "" and offered == [("dohita-2.json", TITLE)], offered
                assert not (config.ARCHIVE / "dohita-2.json").exists() and len(said) == 1 and "Big Baby Tape" in said[0]
                for path in config.OFFERS.glob("*.json"):
                    path.unlink()
                publish.to_channel = lambda *a: 1 / 0
                try:
                    air()
                except ZeroDivisionError:
                    pass
                assert not (config.ARCHIVE / "dohita-2.json").exists(), "сбой отправки снимает отметку"
                (config.ARCHIVE / "dohita-2.json").write_text("{}")
                assert air() == "" and len(said) == 1, "запас кончился — молчит"
    state.now = real
    print("dohita: самопроверка пройдена")


def main() -> int:
    parser = argparse.ArgumentParser(description="ДО ХИТА: как артист на пике пробился к первому хиту")
    parser.add_argument("--selftest", action="store_true", help="проверка без сети и Telegram")
    parser.add_argument("--dry-run", action="store_true", help="кто в запасе и текст следующего поста, без записи")
    args = parser.parse_args()
    if args.selftest:
        _selftest()
        return 0
    left = pending()
    print(f"В запасе: {', '.join(hero['artist'] for hero in left) or 'никого'}; сейчас можно выйти: {due()}; "
          f"автопилоту искать героев: {need()}")
    if left:
        post = build(left[0])
        print(f"Следующий пост ({visible(post['text'])} знаков):\n\n{post['text']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
