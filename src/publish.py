"""Публикатор: берёт следующий пост из очереди и отправляет его.

    python -m src.publish --check              проверить, что бот и канал настроены
    python -m src.publish --target admin       отправить следующий пост себе в личку
    python -m src.publish --target channel     опубликовать в канал
    python -m src.publish --dry-run            показать, что было бы отправлено

Публикатор смотрит не на часы, а на время последней публикации. Поэтому пропуск
запуска по расписанию (обычное дело для бесплатного планировщика GitHub) не ломает
ленту: следующий запуск просто увидит, что пауза затянулась, и опубликует пост.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

from . import card, config, footage, quality, state, telegram
from .sources import deezer, itunes

log = logging.getLogger("publish")


def next_post(releases: bool = False, dry_run: bool = False, skip_sent: bool = False) -> Path | None:
    """Следующий обычный пост — самый ранний файл очереди; с releases —
    пост о свежем релизе, готовый к своему выходу.

    skip_sent пропускает посты, уже ушедшие владельцу на утверждение
    (PUBLISH_TARGET=admin): пост остаётся в очереди, пока тот не нажмёт кнопку,
    и ежечасный выход релиза слал ему один и тот же пост каждый час.

    Решения владельца от 11.09.2026. Пост о релизе (config.RELEASE_RUBRICS)
    из обычной очереди не берётся: у него свой выход, раз в час по одному,
    самый весомый по score сборщика. Выходит он не раньше чем через
    config.RELEASE_TRACK_WAIT_HOURS после написания — окно на полный трек
    от владельца; трек пришёл — сразу. Дольше не ждёт, если так опоздал бы
    к сроку: тогда уходит с отрывком.

    Старше config.RELEASE_MAX_AGE_HOURS от выхода пост убирается из очереди
    при любом запуске, сухой прогон только пишет в лог. Даты выхода нет
    (посты до 11.09.2026) — считаем от created_at. Будущая дата не пускает:
    iTunes ставит выход на 07:00 UTC, поэтому сравниваются дни, а не часы.
    """
    now = state.now()
    max_age = timedelta(hours=config.RELEASE_MAX_AGE_HOURS)
    wait = timedelta(hours=config.RELEASE_TRACK_WAIT_HOURS)
    regular, ready = [], []
    for path in sorted(config.QUEUE.glob("*.json")):
        post = state.read_json(path, {})
        if skip_sent and post.get("approval_sent_at"):
            continue
        if post.get("rubric") not in config.RELEASE_RUBRICS:
            regular.append(path)
            continue
        released = state._parse(post.get("released_at") or post.get("created_at") or "")
        if released is None or released.date() > now.date():
            continue
        if now - released > max_age:
            log.warning("Релиз протух, %s: %s", "убрал бы" if dry_run else "убран из очереди", path.name)
            if not dry_run:
                path.unlink()
            continue
        written = state._parse(post.get("created_at") or "") or now
        if post.get("full_track_file_id") or now - written >= wait or now - released >= max_age - wait:
            ready.append((-(post.get("score") or 0), path))
    if releases:
        return min(ready)[1] if ready else None  # весомее — раньше, при равном весе — раньше написанный
    return regular[0] if regular else None


def night(moment: datetime) -> bool:
    """Тихие часы по Москве: config.QUIET_FROM_HOUR–QUIET_TO_HOUR."""
    from .compose import MSK

    hour = moment.astimezone(MSK).hour
    return hour >= config.QUIET_FROM_HOUR or hour < config.QUIET_TO_HOUR


def feed_day(moment: datetime):
    """Сутки ленты: по Москве, но с конца тихих часов, а не с полуночи.

    Ночной пост — хвост вчерашнего дня. С полуночной границей пятничные релизы
    сверх config.RELEASE_PER_DAY вышли в 00:04–02:08 субботы, съели её лимит
    и слоты, и субботняя лента днём молчала (26.09.2026).
    """
    from .compose import MSK

    return (moment.astimezone(MSK) - timedelta(hours=config.QUIET_TO_HOUR)).date()


def hushed(chat_id: str | int) -> bool:
    """Без звука ли выходит пост. Ночью — любой (config.QUIET_FROM_HOUR), а в канале ещё
    и каждый после первого за сутки ленты (владелец 06.10.2026).

    В канал приходят за ботом — за сведением и битом, — и четыре-пять уведомлений в день
    от такого канала читаются как повод отписаться. Звук достаётся первому посту дня;
    бит владельца выходит раньше прочих (moderate.publish_shift) и забирает его себе.
    Владельцу в личку пост идёт как раньше: там это не лента, а работа.
    """
    now = state.now()
    if night(now):
        return True
    if str(chat_id) != config.secret("TELEGRAM_CHANNEL_ID", required=False):
        return False
    items = state.read_json(config.POSTED_FILE, {"items": []}).get("items", [])
    last = state._parse(items[-1].get("published_at", "")) if items else None
    return bool(last and feed_day(last) == feed_day(now))


def releases_today() -> int:
    """Сколько постов о релизах вышло за сутки ленты (feed_day)."""
    today = feed_day(state.now())
    count = 0
    for item in state.read_json(config.POSTED_FILE, {"items": []}).get("items", []):
        published = state._parse(item.get("published_at", ""))
        if (item.get("rubric") in config.RELEASE_RUBRICS and published
                and feed_day(published) == today):
            count += 1
    return count


def due(post: dict) -> bool:
    """Пора ли публиковать обычный пост — исходя из времени прошлой публикации.

    Считаются все публикации, выходы релизов тоже: обычный пост вечнозелёный
    и уступает слот свежему релизу — релиз в счёте слотов идёт за обычный пост
    (владелец 22.09.2026: постов в ленте слишком много). Годовщину это не касается:
    завтра она уже не годовщина.

    Обычных постов за сутки — столько, сколько прошло часов config.PUBLISH_HOURS_MSK:
    дежурство проверяет выход каждые 10 минут, и без этого счёта лента получала бы
    пост каждые три часа. Ночью обычный пост не выходит вовсе.
    """
    from .compose import MSK

    posted = state.read_json(config.POSTED_FILE, {"items": []})
    items = posted.get("items", [])
    if post.get("rubric") != "legend":
        now = state.now().astimezone(MSK)
        if night(now):
            return False
        regular = sum(
            1 for item in items
            # Отбор (src/otbor.py), ролик (src/reels.py) и бит (src/bity.py) выходят мимо слотов
            # и обычному посту место не занимают.
            if item.get("rubric") not in ("news", "otbor", "reel", "beat")
            and (moment := state._parse(item.get("published_at", "")))
            and feed_day(moment) == feed_day(now)
        )
        if regular >= sum(hour <= now.hour for hour in config.PUBLISH_HOURS_MSK):
            return False
    if not items:
        return True

    last = state._parse(items[-1].get("published_at", ""))
    if last is None:
        return True
    return state.now() - last >= timedelta(hours=config.PUBLISH_INTERVAL_HOURS)


def release_due() -> bool:
    """Пора ли выпускать следующий пост о релизе — не чаще раза в час
    и не больше config.RELEASE_PER_DAY за сутки.

    Частоту раньше задавал ежечасный крон publish.yml, но он занимал группу
    state-write и вытеснял из очереди ожидающий сбор: у GitHub в группе ждёт
    ровно один запуск. Теперь выход идёт из дежурства (src/moderate.py), а час
    отсчитывается по журналу публикаций — так же, как интервал обычных постов.
    """
    if releases_today() >= config.RELEASE_PER_DAY:
        return False
    for item in reversed(state.read_json(config.POSTED_FILE, {"items": []}).get("items", [])):
        if item.get("rubric") not in config.RELEASE_RUBRICS:
            continue
        last = state._parse(item.get("published_at", ""))
        return last is None or state.now() - last >= timedelta(hours=config.RELEASE_EVERY_HOURS)
    return True


def deliver(post: dict, path: Path, target: str) -> None:
    """Отправка готового поста — одна на публикатор по расписанию и дежурство.

    В канал пост уходит насовсем, владельцу — на утверждение и с отметкой
    в файле: без неё следующий выход подал бы ему тот же пост снова.
    """
    if target == "channel":
        to_channel(post, path, config.secret("TELEGRAM_CHANNEL_ID"))
        return
    send_for_approval(post, path, config.secret("TELEGRAM_ADMIN_ID"))
    state.write_json(path, {**state.read_json(path, {}), "approval_sent_at": state.iso()})


def record(post: dict, path: Path, chat: str) -> None:
    posted = state.read_json(config.POSTED_FILE, {"items": []})
    posted.setdefault("items", []).append(
        {
            "file": path.name,
            "rubric": post.get("rubric", ""),
            "chat": chat,
            "published_at": state.iso(),
        }
    )
    # Храним последние 500 записей — этого хватает для аналитики и не раздувает файл.
    posted["items"] = posted["items"][-500:]
    # Отпечатки вышедших фото не обрезаются: повтор через год — тоже повтор,
    # а строка на пост за год не набирает и мегабайта (card.cover).
    if post.get("photo"):
        posted.setdefault("photos", []).append(post["photo"])
    state.write_json(config.POSTED_FILE, posted)


def archive(path: Path) -> None:
    config.ARCHIVE.mkdir(parents=True, exist_ok=True)
    path.rename(config.ARCHIVE / path.name)


def to_channel(post: dict, path: Path, chat_id: str) -> None:
    """Публикация в канал: Telegram, ВКонтакте, журнал, архив. Одна на три входа —
    расписание, кнопку «✅ В канал» (src/moderate.py) и срочные новости (src/urgent.py).

    Сообщение с текстом поста ложится в архивный JSON полем message: без него
    автопилот точности (src/review.py) вышедший пост поправить не может.
    ВКонтакте идёт после Telegram и на исход не влияет — пост уже вышел.
    """
    message = send(post, chat_id)
    crosspost_vk(post)
    record(post, path, "channel")
    if message:
        state.write_json(path, {**post, "message": message})
    archive(path)


def edit(post: dict) -> None:
    """Правит вышедший пост в канале по сообщению из to_channel (src/review.py).

    Текст готовится тем же путём, что в send: строка «▸ Слушать…» там развёрнута
    в ссылки на площадки, и в подпись она уехать не должна. Подпись длиннее лимита не режется
    молча, а отказывает: обрезанный пост хуже непоправленного.
    """
    message = post["message"]
    text = view(post.get("text", "").strip(), post)
    where = message["chat"], message["message_id"], text
    if message["kind"] != "caption":
        telegram.edit_text(*where, buttons=message.get("buttons"))
        return
    if telegram.visible_len(text) > telegram.MAX_CAPTION:
        raise telegram.TelegramError(
            f"подпись {telegram.visible_len(text)} знаков — больше {telegram.MAX_CAPTION}")
    telegram.edit_caption(*where, buttons=message.get("buttons"))


# Последняя строка поста о релизе («▸ Слушать в Apple Music», см. compose.name_button).
# В Telegram она разворачивается в ссылки на площадки, а в сохранённом тексте
# остаётся как есть: во ВКонтакте уходит запись целиком, и ссылку несёт она.
_LISTEN_LINE = re.compile(r'^▸\s*<a\s+href="([^"]+)"[^>]*>\s*Слушать[^<]*</a>[^\S\n]*$', re.MULTILINE)


def _host(url: str) -> str:
    return urlparse(url).netloc.casefold().removeprefix("www.")


LISTEN_HEAD = "▸ Слушать:"


def listen(text: str, artist: str, title: str) -> str:
    """Разворачивает строку «▸ Слушать…» в ссылки на площадки прямо в тексте.

    Кнопок под постом больше нет (решение владельца 12.09.2026): панель из восьми
    штук читалась в ленте раньше самого поста, а под постом с инлайн-клавиатурой
    Telegram не показывает «Комментарии» (bugs.telegram.org/c/41803). Ссылка
    в тексте обсуждению не мешает и жмётся тем же одним нажатием.

    Пост без этой строки не трогаем: «Источник» у новости ведёт на статью,
    «Смотреть на YouTube» — на видео, а не на релиз. Сервис, чей адрес совпал
    со ссылкой из поста, получает её саму — это точный релиз. Остальные ведут
    на поиск.
    """
    match = _LISTEN_LINE.search(text)
    query = quote(f"{artist} {title}".strip(), safe="")
    if not match or not query:
        return text

    link = match.group(1)
    # Магазин находки прибавляется к четвёрке пятым, если в неё не попал: там лежит
    # сам релиз, а не догадка поиска, и терять такую ссылку жалко. Площадки стоят
    # отдельной строкой под «Слушать:» — с приставкой «▸ Слушать — » пятая
    # на телефоне уезжала одна на новую строку, а без неё пять влезают.
    services = list(config.LISTEN_SERVICES[:4])
    services += [s for s in config.LISTEN_SERVICES[4:] if _host(s[1]) == _host(link)]
    line = f"{LISTEN_HEAD}\n" + " · ".join(
        f'<a href="{link if _host(search) == _host(link) else search.format(q=query)}">{label}</a>'
        for label, search in services
    )
    return re.sub(r"\n{3,}", "\n\n", _LISTEN_LINE.sub(lambda _: line, text)).strip()


TRACK_NOTE = "▸ Или в комментариях ↓"
# Площадок в посте нет — «или» не к чему, трек называется сам.
TRACK_ALONE = "▸ Полный трек — в комментариях ↓"
# Под разбором и новостью: треки концов связи или названного релиза (поле listen).
LISTEN_NOTE = "▸ Что послушать — в комментариях ↓"


def track_note(text: str, post: dict) -> str:
    """Строка о полном треке в комментариях — под площадками, когда трек у поста есть.

    Трек лежит первым комментарием (comments.seed), но из ленты этого не видно,
    и за ним в комментарии не заходят (владелец, 17.09.2026). Строку ставит код,
    а не модель: модель не знает, пришлёт ли трек помощник на Mac к выходу,
    а пустое обещание хуже молчания. Трек, приложенный после выхода, получает
    строку при правке поста (edit). Во ВКонтакте её нет: туда уходит сохранённый
    текст, а трека под записью там нет.

    Вид выбрал владелец: под «▸ Слушать:» площадки строкой, под ними
    «▸ Или в комментариях ↓» — второй способ наравне со «Слушать»; стрелка — на кнопку
    комментариев под постом.
    """
    if TRACK_NOTE in text or TRACK_ALONE in text or LISTEN_NOTE in text:
        return text
    # У разбора и новости комментарий есть всегда: не пришёл файл — там ссылки на площадки
    # (comments.seed), поэтому строка обещает «что послушать», а не «полный трек».
    if post.get("listen"):
        return f"{text}\n\n{LISTEN_NOTE}"
    if not post.get("full_track_file_id"):
        return text
    at = text.find(f"{LISTEN_HEAD}\n")
    if at < 0:
        return f"{text}\n\n{TRACK_ALONE}"
    end = text.find("\n", at + len(LISTEN_HEAD) + 1)
    end = len(text) if end < 0 else end
    return f"{text[:end]}\n{TRACK_NOTE}{text[end:]}"


def release_title(post: dict) -> str:
    """Название релиза для поиска в стримингах.

    Магазин отдаёт его по ссылке из строки «Слушать»: у альбома трек отрывка —
    лишь открывающий, а кнопка должна вести к релизу целиком. Магазин
    не ответил — ищем по треку, нет и его — по одному артисту.
    """
    match = _LISTEN_LINE.search(post.get("text", ""))
    if not match:
        return ""
    link, title = match.group(1), ""
    try:
        if album := itunes.album_id_from_url(link):
            title = itunes.album_tracks(album).get("album", "")
        elif album := deezer.album_id_from_url(link):
            title = deezer.album_tracks(album).get("album", "")
    except Exception as exc:  # магазин мог не ответить — пост важнее кнопок
        log.warning("Название релиза не получено: %s", exc)
    # Формат, который магазин приписывает к названию, поиск только путает.
    title = re.sub(r"\s+-\s+(Single|EP)$", "", title)
    return title or post.get("track", "")


# Имя артиста в посте — ссылка на его карточку в боте (владелец, 01.10.2026): кто он,
# последние релизы, площадки и «🔔 Следить» (src/vkladysh.py). Метка a_<id Deezer>.
ARTIST_LINK = f"https://t.me/{config.BOT_HANDLE.lstrip('@')}?start=a_{{}}"
# Теги и готовые ссылки: имя внутри них не ищем — ни в адресе, ни в строке площадок.
# Опись <code> тоже мимо: ссылку внутри неё Telegram молча снимает, и имя, впервые
# названное в описи, оставалось без карточки, хотя ниже стояло в тексте (01.10.2026).
_MARKUP = re.compile(r"<a\b[^>]*>.*?</a>|<(code|pre)\b[^>]*>.*?</\1>|<[^>]*>", re.DOTALL | re.IGNORECASE)


def _mention(text: str, name: str, taken: list[tuple[int, int]] = ()) -> tuple[int, int] | None:
    """Первое упоминание имени целым словом вне разметки и чужих ссылок.

    Слева — начало строки, пробел, тег или открывающая кавычка и скобка: «Nas» в «Nasty»
    не имя, а ссылку после другого знака telegram.sanitize отбил бы пустой строкой.
    """
    blocked = [m.span() for m in _MARKUP.finditer(text)] + list(taken)
    for match in re.finditer(rf"(?<![^\s>«(„“\"']){re.escape(name)}(?!\w)", text):
        if not any(start < match.end() and match.start() < end for start, end in blocked):
            return match.span()
    return None


def artist_ids(text: str, people, release: dict | None = None) -> dict[str, int]:
    """Единственная проверка ссылок на артистов: {как имя стоит в тексте: id Deezer}.

    people — имена из данных поста строкой и люди, которых назвала модель
    ({"shown": как в тексте, "name": как на площадках}, llm.POST_SCHEMA). Ссылка будет,
    только если shown стоит в тексте целым словом, а name Deezer знает точно, без учёта
    регистра (deezer.find_artist_id): похожий артист — чужая карточка под нашим именем,
    та же выдумка. Не нашёлся — ссылки нет. Зовётся при сохранении поста (compose.save_post),
    id ложатся полем links: при выходе и правке заново не ищем.

    release — находка сбора, о которой пост: её артистам id даёт сам релиз
    (collect.release_artists), а по имени их не ищем — точное имя бывает тёзкой.
    Названному моделью, кого нет ни в релизе, ни в базе, нужна страница со слушателями
    (config.PEOPLE_MIN_FANS): тёзка с альбомами, но без фанатов ссылки не получает.
    В магазин идём, только когда в тексте правда стоит чьё-то имя.
    """
    found: dict[str, int] = {}
    own: dict[str, int | None] | None = None
    for person in people or []:
        shown, name = (person.get("shown"), person.get("name")) if isinstance(person, dict) else (person, person)
        if not (isinstance(shown, str) and isinstance(name, str) and shown.strip() and name.strip()):
            continue
        shown = shown.strip()
        if shown in found or not _mention(text, shown):
            continue
        if release and own is None:
            from . import collect  # здесь, а не сверху: сбор тянет feedparser, а publish зовут и без него

            own = collect.release_artists(release)
        try:
            key = name.strip().casefold()
            # Названному моделью — порог фанатов: точное имя с альбомами бывает тёзкой.
            fans = (config.PEOPLE_MIN_FANS,) if isinstance(person, dict) else ()
            artist_id = own[key] if own and key in own else deezer.find_artist_id(name.strip(), *fans)
        except Exception as exc:  # noqa: BLE001 — Deezer молчит: ссылки нет, пост важнее
            log.info("Deezer не ответил про «%s»: %s", name, exc)
            continue
        if artist_id:
            found[shown] = artist_id
    return found


def artist_links(text: str, post: dict) -> str:
    """Имена артистов — ссылками на их карточки в боте, каждое по первому упоминанию.

    В тексте поста ссылок нет: их накладывает код при отправке и правке (send, edit).
    30.09.2026 автопилот точности (src/review.py) снял из поста ссылку, которой не было
    в данных, — лежи они в text, он снимал бы их и дальше. Имена — база канала с алиасами
    и поле links поста (artist_ids). Длинное первым: «Lil Uzi Vert» раньше «Uzi».
    Во ВКонтакте уходит сохранённый текст — ссылки на бота Telegram там не нужны.

    Подпись к фото короче 1024 знаков, и текст ради ссылок не режется: не влезло —
    ссылки снимаются с последней. Считаем так же, как отправка: после telegram.sanitize,
    по видимой длине, и сырой текст сообщения не длиннее telegram.MAX_TEXT, иначе
    send_message его обрежет.
    """
    ids = {name: artist["deezer_id"] for artist in state.read_json(config.ARTISTS_FILE, {}).get("artists", [])
           for name in (artist.get("name", ""), *artist.get("aliases", [])) if name and artist.get("deezer_id")}
    ids |= post.get("links") or {}
    spans: list[tuple[int, int, int]] = []
    for name in sorted(ids, key=len, reverse=True):
        if span := _mention(text, name, [(start, end) for start, end, _ in spans]):
            spans.append((*span, ids[name]))
    # Одна карточка — одна ссылка: у «Кино» и «Kino» она ставится на первое из упоминаний.
    first: dict[int, tuple[int, int, int]] = {}
    for span in sorted(spans):
        first.setdefault(span[2], span)
    spans = sorted(first.values())
    limit = telegram.MAX_CAPTION if telegram.visible_len(text) <= telegram.MAX_CAPTION else telegram.MAX_TEXT
    while True:
        linked = text
        for start, end, artist_id in reversed(spans):
            linked = f'{linked[:start]}<a href="{ARTIST_LINK.format(artist_id)}">{linked[start:end]}</a>{linked[end:]}'
        clean = telegram.sanitize(linked)
        if not spans or (telegram.visible_len(clean) <= limit and len(clean) <= telegram.MAX_TEXT):
            return linked
        spans.pop()


def view(text: str, post: dict) -> str:
    """Текст поста, каким его видит читатель Telegram: площадки строкой, строка о треке,
    имена артистов ссылками. Один путь для выхода, правки и сухого прогона."""
    return artist_links(track_note(listen(text, post.get("artist", ""), release_title(post)), post), post)


def _where(message: dict, kind: str, buttons: list[list[dict]] | None = None) -> dict:
    """Сообщение с текстом поста: чат, id, подпись это или текст, кнопки под ним.

    Кнопки запоминаются вместе с сообщением: правка без reply_markup их снимает,
    проверено вживую, а у вышедшего поста взять их больше неоткуда.
    """
    return {"chat": message["chat"]["id"], "message_id": message["message_id"], "kind": kind,
            "buttons": buttons or []}


def send(post: dict, chat_id: str) -> dict | None:
    """Отправляет пост нужным методом: опрос, фото с текстом, плеер или текст.

    Возвращает сообщение, в котором лежит текст поста (_where): по нему
    вышедший пост правится (edit). Опрос не правится — None.
    """
    text = post.get("text", "").strip()
    rubric = post.get("rubric", "")
    quiet = hushed(chat_id)

    if rubric == "poll":
        payload = _poll_payload(text)
        if payload:
            telegram.send_poll(
                chat_id,
                payload["question"],
                payload["options"],
                anonymous=payload.get("is_anonymous", True),
            )
            return
        log.warning("Опрос не разобран — отправляю как обычный текст")

    # Мем — картинка с надписью на ней, а под фото подпись канала: это вторая
    # реплика, а не повтор надписи (card.render_meme). Нет картинки или
    # не нарисовалась — мем уходит текстом целиком, надписи вместе с подписью.
    if rubric == "meme":
        image = card.meme(post)
        if image:
            try:
                return _where(telegram.send_photo_file(chat_id, image, text, quiet=quiet), "caption")
            except telegram.TelegramError as exc:
                log.warning("Мем с картинкой не ушёл (%s), отправляю текстом", exc)
        text = card.meme_text(post)

    # Ролик владельца (src/reels.py) — тем же файлом, что ушёл ему в личку, по file_id.
    if rubric == "reel":
        return _where(telegram.send_video_url(chat_id, post["video"], text, width=post.get("width", 0),
                                              height=post.get("height", 0), quiet=quiet), "caption")

    # Бит владельца (bity.air): значок бита кадром, ссылка на бота — в тексте. Имена артистов
    # ссылками на карточки здесь не становятся: ссылка в посте одна — за битом.
    if rubric == "beat":
        import tempfile

        from . import bity  # тянет за собой сведение и ролики — нужен только этому посту

        try:
            with tempfile.TemporaryDirectory(prefix="beat-") as tmp:
                shot = bity.shot(post["beat"], Path(tmp))
                return _where(telegram.send_photo_file(chat_id, shot, text, quiet=quiet), "caption")
        except Exception as exc:  # noqa: BLE001 — значок не нарисовался или не ушёл: бит выходит текстом
            log.warning("Бит со значком не ушёл (%s), отправляю текстом", exc)
        return _where(telegram.send_message(chat_id, text, quiet=quiet), "text")

    cover = post.get("cover", "")
    text = view(text, post)

    # Пост — всегда одна плитка ленты: картинка в рамке, текст, ссылки на площадки
    # строкой в нём же. Плеера рядом нет (решение владельца 12.09.2026): полный
    # трек уходит первым комментарием под постом (src/comments.py), а отрывок
    # магазина не уходит вовсе — вид ленты не должен зависеть от того, прислали
    # трек к этому релизу или нет.
    #
    # Картинка нужна любому посту: без медиа его в ленте проматывают. У релиза
    # это обложка, у разбора — фотография артиста из текста (card.cover).
    # Мем сюда доходит только когда своя картинка не нарисовалась, и чужое лицо
    # к нему не клеим: шутка уходит текстом.
    if telegram.visible_len(text) <= telegram.MAX_CAPTION:
        # Рамка канала: рубрика сверху, подпись снизу. Не нарисовалась
        # (нет сети, не нашли артиста) — обложка уходит как была, а без неё
        # пост идёт текстом.
        framed = card.cover(post, state.read_json(config.POSTED_FILE, {}).get("photos", [])) \
            if rubric != "meme" else None
        # Пустое photo — все кадры уже выходили в канале, и сырая обложка стала бы повтором.
        if framed or (cover and "photo" not in post):
            try:
                if framed:
                    photo = telegram.send_photo_file(chat_id, framed, text, quiet=quiet)
                else:
                    photo = telegram.send_photo(chat_id, cover, text, quiet=quiet)
                return _where(photo, "caption")
            except telegram.TelegramError as exc:
                # Обложка могла протухнуть — текст уходит обычным сообщением.
                log.warning("Фото не ушло (%s), текст уходит сообщением", exc)
                post.pop("photo", None)

    return _where(telegram.send_message(chat_id, text, quiet=quiet), "text")


def crosspost_vk(post: dict) -> None:
    """Дублирует пост во ВКонтакте, если сообщество подключено.

    Молчаливо пропускается, когда токен не задан: ВКонтакте — вторая площадка,
    и её отсутствие не должно мешать основному каналу. Ошибка публикации там
    тоже не роняет запуск — пост в Telegram уже вышел.
    """
    import os

    if not os.environ.get("VK_TOKEN", "").strip():
        return

    from . import vk

    # Опросы во ВКонтакте создаются иначе, чем в Telegram, — пока пропускаем. Ролик туда
    # групповым ключом не залить (clips.deliver): в VK Клипы его кладёт владелец сам.
    # Бит зовёт в бота Telegram — во ВКонтакте идти по такой ссылке некому. Трек из СВЕДЕНИЯ
    # (otbor.build_post, поле mixed) лежит только под постом в Telegram: площадок у него нет,
    # и запись во ВКонтакте звала бы слушать то, чего там не услышать.
    if post.get("rubric") in ("poll", "reel", "beat") or post.get("mixed"):
        return

    # У релиза и новости картинка — обложка по ссылке. У разбора и мема ссылки
    # нет вовсе: кадр нарисован у нас (card.cover, card.meme) и уходит файлом
    # с диска — раньше разбор появлялся во ВКонтакте голым текстом. Кадр
    # рисуется на копии поста: отпечаток уже проставлен при выходе в Telegram,
    # и второй проход не должен его переписать.
    if post.get("rubric") == "meme":
        text, photo = card.meme_text(post), card.meme(post)
    else:
        text = post.get("text", "")
        photo = post.get("cover", "") or card.cover(
            dict(post), state.read_json(config.POSTED_FILE, {}).get("photos", []))
    try:
        post_id = vk.post(
            text,
            photo=photo or "",
            artist=post.get("artist", ""),
            track=post.get("track", ""),
        )
        log.info("Продублировано во ВКонтакте, запись %s", post_id)
    except Exception as exc:
        log.warning("ВКонтакте не принял пост: %s", exc)


def send_for_approval(post: dict, path: Path, chat_id: str, label: str = "") -> None:
    """Показывает пост и подкладывает под него кнопки решения.

    Кнопки идут отдельным сообщением: пост может оказаться фотографией или
    опросом, а к ним клавиатуру приложить не всегда возможно.
    """
    rubric = config.RUBRIC_BY_KEY.get(post.get("rubric", ""))
    # label заменяет название рубрики в шапке — так срочная новость видна
    # в личке среди обычной очереди сразу, до чтения текста.
    title = label or (rubric.title if rubric else post.get("rubric", ""))

    telegram.send_message(chat_id, f"— — — <b>{title}</b> — — —")
    send(post, chat_id)
    # Про задержку сказано прямо: иначе кажется, что кнопка не сработала.
    telegram.send_message(
        chat_id,
        "Что делаем с постом?\n"
        "<i>Кнопка подумает пару минут — решения применяются по расписанию.</i>",
        buttons=telegram.approval_buttons(path.name),
    )


def _poll_payload(text: str) -> dict | None:
    return quality.poll(text)


def _selftest() -> None:
    """Площадки стримингов: строка «Слушать» разворачивается в ссылки в тексте.
    Пост — всегда одна плитка: фото в рамке с текстом, без кнопок и без плеера
    рядом (полный трек уходит первым комментарием, src/comments.py).
    send возвращает сообщение с текстом поста, to_channel кладёт его в архив.
    Посты о релизах: свой выход, сутки на всё, окно на трек, не больше двух
    за сутки ленты, обычный пост уступает им слот. Звук в канале — у первого
    поста за сутки ленты и не в тихие часы.

    Запуск: python -m src.publish --selftest
    """
    import os
    import tempfile
    from unittest import mock

    sent: list[tuple] = []
    real = (card.cover, telegram.send_photo, telegram.send_photo_file, telegram.send_audio,
            telegram.send_message, state.now, config.QUEUE, config.ARCHIVE, config.POSTED_FILE)
    card.cover = lambda post, seen=(): None

    # Запись: что ушло, подпись, без звука ли, есть ли кнопки. id сообщения — его номер.
    def message(*entry) -> dict:
        sent.append(entry)
        return {"message_id": len(sent), "chat": {"id": -100}}

    def photo(chat, url, caption, buttons=None, quiet=False):
        if "протухла" in url:
            raise telegram.TelegramError("обложка протухла")
        return message("фото", caption, quiet, bool(buttons))

    telegram.send_photo = photo
    telegram.send_photo_file = lambda chat, path, caption, buttons=None, quiet=False, **_: message(
        "кадр", caption, quiet, bool(buttons))
    telegram.send_audio = lambda chat, audio, caption, buttons=None, quiet=False, **_: message(
        "плеер", caption, quiet, bool(buttons))
    telegram.send_message = lambda chat, text, buttons=None, quiet=False, **_: message(
        "текст", text, quiet, bool(buttons))
    # Часы стоят на 15:00 UTC, то есть 18:00 по Москве: счёт за сутки не зависит
    # от времени прогона. Очередь и журнал публикаций — во временной папке.
    now = datetime(2026, 9, 11, 15, 0, tzinfo=timezone.utc)
    state.now = lambda: now
    tmp = tempfile.TemporaryDirectory()
    config.QUEUE, config.ARCHIVE, config.POSTED_FILE = (
        Path(tmp.name) / "queue", Path(tmp.name) / "archive", Path(tmp.name) / "posted.json")

    def ago(**delta: float) -> str:
        return state.iso(now - timedelta(**delta))

    def posted(*items: tuple[str, str]) -> None:
        state.write_json(config.POSTED_FILE, {"items": [{"rubric": r, "published_at": t} for r, t in items]})

    try:
        # Ссылка не из магазина: название релиза берётся из поста, без сети.
        post = {"text": "Текст.", "artist": "Bones", "cover": "https://x/c.jpg",
                "full_track_file_id": "ID"}
        # Строка «Слушать» в подпись сырой не уезжает: она развёрнута в площадки.
        send({**post, "text": 'Текст.\n\n▸ <a href="https://zvuk.com/release/1">Слушать</a>'}, "0")
        assert sent[0][1].startswith(f"Текст.\n\n{LISTEN_HEAD}\n<a href=") and sent[0][1].endswith(f"</a>\n{TRACK_NOTE}"), sent[0][1]
        sent.clear()
        # Пост — одна плитка, даже когда трек есть: он уйдёт в комментарии, о чём скажет строка.
        # Возвращается сообщение с текстом поста: по нему правит автопилот точности.
        where = send(post, "0")
        assert sent == [("фото", f"Текст.\n\n{TRACK_ALONE}", False, False)], sent
        assert where == {"chat": -100, "message_id": 1, "kind": "caption", "buttons": []}, where
        sent.clear()
        # Отрывок магазина в ленту не идёт вовсе — ни отдельно, ни вместо фото.
        where = send({**post, "full_track_file_id": "", "preview": "https://x/30s.m4a"}, "0")
        assert sent == [("фото", "Текст.", False, False)], sent
        assert where["message_id"] == 1 and where["kind"] == "caption" and not where["buttons"], where
        sent.clear()
        # Фото не ушло — текст обычным сообщением.
        where = send({**post, "cover": "https://x/протухла.jpg"}, "0")
        assert sent == [("текст", f"Текст.\n\n{TRACK_ALONE}", False, False)], sent
        assert where == {"chat": -100, "message_id": 1, "kind": "text", "buttons": []}, where
        sent.clear()
        # Без обложки и без кадра — текст обычным сообщением.
        where = send({**post, "cover": ""}, "0")
        assert sent == [("текст", f"Текст.\n\n{TRACK_ALONE}", False, False)] and where["kind"] == "text", where
        sent.clear()

        # Разбор приходит без обложки, но кадр ему находит card.cover по тексту:
        # пост без картинки в ленте проматывают.
        card.cover = lambda post, seen=(): Path("кадр.jpg") if post.get("rubric") != "meme" else None
        where = send({"text": "Текст.", "rubric": "lineage"}, "0")
        assert sent == [("кадр", "Текст.", False, False)], sent
        assert where["kind"] == "caption", where
        sent.clear()
        # А мему чужое лицо не клеим: своя картинка не нарисовалась — уходит текстом.
        send({"text": "Текст.", "rubric": "meme", "top": "ВЕРХ", "bottom": "НИЗ"}, "0")
        assert sent == [("текст", "ВЕРХ\nНИЗ\n\nТекст.", False, False)], sent
        sent.clear()
        # Все кадры поста уже выходили в канале — идёт текст, а не сырая обложка.
        card.cover = lambda post, seen=(): post.update(photo="")
        send({**post}, "0")
        assert sent == [("текст", f"Текст.\n\n{TRACK_ALONE}", False, False)], sent

        # Настоящая карточка: вышедший портрет узнаётся и уменьшенным и пережатым,
        # пост берёт следующий кадр артиста, а его отпечаток по выходе ложится в журнал.
        from PIL import Image

        # Мутный запасной кадр (гладкий градиент — как растянутая обложка) пропускается,
        # следующий, с резкими краями, встаёт (card.MIN_SHARPNESS).
        face, blurry, album, reposted = (Path(tmp.name) / f"{n}.jpg" for n in ("face", "blurry", "album", "reposted"))
        Image.radial_gradient("L").convert("RGB").resize((600, 600)).save(face)
        Image.linear_gradient("L").rotate(90).convert("RGB").resize((600, 600)).save(blurry)
        Image.effect_noise((600, 600), 80).convert("RGB").save(album)
        Image.open(face).resize((300, 300)).save(reposted, quality=40)
        seen = [card.fingerprint(Image.open(reposted))]
        with mock.patch.object(footage, "artist_images", lambda name: iter([blurry, album])):
            lineage = {"text": "Текст.", "rubric": "lineage", "artist": "Bones", "cover": face}
            assert real[0](lineage, seen) and lineage["photo"] == card.fingerprint(Image.open(album)), lineage
            record(lineage, Path("0-lineage.json"), "channel")
            seen += state.read_json(config.POSTED_FILE, {})["photos"]
            assert real[0](lineage, seen) is None and lineage["photo"] == "", lineage
        card.cover = lambda post, seen=(): None

        # В канал: сообщение с текстом ложится в архивный JSON, текст — как был.
        state.write_json(config.QUEUE / "0-release.json", post)
        with mock.patch.dict(os.environ, {"VK_TOKEN": ""}):
            to_channel(post, config.QUEUE / "0-release.json", "0")
        archived = state.read_json(config.ARCHIVE / "0-release.json", {})
        assert archived == {**post, "message": {"chat": -100, "message_id": 2, "kind": "caption", "buttons": []}}, archived
        assert not (config.QUEUE / "0-release.json").exists()

        # Во ВКонтакте у разбора ссылки на картинку нет: туда уходит тот же
        # нарисованный кадр файлом, иначе разбор появляется там голым текстом.
        from . import vk

        card.cover = lambda post, seen=(): Path("кадр.jpg")
        vk_sent: dict = {}
        with (mock.patch.dict(os.environ, {"VK_TOKEN": "x"}),
              mock.patch.object(vk, "post", lambda text, **kw: vk_sent.update(kw) or 5)):
            crosspost_vk({"text": "Текст.", "rubric": "lineage"})
        assert vk_sent["photo"] == Path("кадр.jpg"), vk_sent
        card.cover = lambda post, seen=(): None

        # Днём пост о релизе выходит со звуком, в 00:30 по Москве молчит любой пост.
        posted(("release", ago(hours=3)), ("verdict", ago(hours=2)))
        sent.clear()
        send({**post, "rubric": "release"}, "0")
        assert sent == [("фото", f"Текст.\n\n{TRACK_ALONE}", False, False)], sent
        state.now = lambda: datetime(2026, 9, 11, 21, 30, tzinfo=timezone.utc)
        sent.clear()
        send(post, "0")
        state.now = lambda: now
        assert sent == [("фото", f"Текст.\n\n{TRACK_ALONE}", True, False)], sent

        # Звук в канале — у одного поста за сутки ленты: первый звучит, следующие молчат,
        # вчерашний ночной пост звука не отнимает. Владельцу в личку — как раньше.
        with mock.patch.object(config, "secret", lambda name, required=True: "@канал"):
            assert hushed("@канал") and not hushed("1"), "в канале сегодня уже выходили"
            posted(("release", ago(hours=17)))
            assert not hushed("@канал"), "пост в час ночи — хвост вчерашнего дня"
            posted()
            assert not hushed("@канал")
            sent.clear()
            send({**post, "rubric": "release"}, "@канал")
            posted(("release", ago(minutes=1)))
            send({**post, "rubric": "release"}, "@канал")
            assert [entry[2] for entry in sent] == [False, True], sent
        posted(("release", ago(hours=3)), ("verdict", ago(hours=2)))

        # Обычный пост уступает слот свежему релизу: релиз в счёте слотов идёт
        # за обычный пост, но годовщина ждать не может.
        posted(("meme", ago(hours=5)), ("release", ago(hours=1)))
        assert not due({"rubric": "meme"})
        posted(("release", ago(hours=5)))
        assert not due({"rubric": "meme"}) and due({"rubric": "legend"})

        # Обычные посты — по часам выхода: в 18:00 МСК прошёл один час из двух.
        # Пропущенный наверстывается, лишний ждёт 19:00; новости, отбор и вчерашнее не в счёт.
        posted(("news", ago(hours=6)), ("otbor", ago(hours=4)))
        assert due({"rubric": "meme"})
        posted(("lineage", ago(hours=6)), ("news", ago(hours=4)))
        assert not due({"rubric": "meme"})
        posted(*[("meme", ago(hours=h)) for h in (26, 24, 22, 20)])
        assert due({"rubric": "meme"})
        # Ночью (00:30 МСК) обычный пост не выходит, годовщина — выходит.
        state.now = lambda: datetime(2026, 9, 11, 21, 30, tzinfo=timezone.utc)
        posted()
        assert not due({"rubric": "meme"}) and due({"rubric": "legend"})
        state.now = lambda: now

        for name, item in {
            "1-meme.json": {"rubric": "meme", "created_at": ago(days=6)},
            "2-release.json": {"rubric": "release", "released_at": ago(hours=5), "created_at": ago(hours=3),
                               "score": 80},
            # Написан полчаса назад — ждёт полный трек от владельца.
            "3-release.json": {"rubric": "release", "released_at": ago(hours=5), "created_at": ago(minutes=30),
                               "score": 95},
            # Вердикт старше суток от выхода — убирается.
            "4-verdict.json": {"rubric": "verdict", "released_at": ago(hours=30), "created_at": ago(hours=3),
                               "score": 100},
            # Пост до 11.09: даты выхода нет, трек есть — выходит сразу.
            "5-verdict.json": {"rubric": "verdict", "created_at": ago(hours=1), "full_track_file_id": "ID"},
            # До срока меньше окна на трек — ждать нельзя.
            "6-release.json": {"rubric": "release", "released_at": ago(hours=23), "created_at": ago(minutes=10),
                               "score": 70},
            # Выйдет послезавтра — не выходит и не убирается.
            "7-release.json": {"rubric": "release", "released_at": ago(days=-2), "created_at": ago(hours=3),
                               "score": 100},
        }.items():
            state.write_json(config.QUEUE / name, item)
        assert next_post(dry_run=True).name == "1-meme.json"  # обычный слот постов о релизах не берёт
        assert (config.QUEUE / "4-verdict.json").exists(), "сухой прогон удалил пост"
        order = []
        while path := next_post(releases=True):
            order.append(path.name)
            path.unlink()
        assert order == ["2-release.json", "6-release.json", "5-verdict.json"], order
        assert sorted(p.name for p in config.QUEUE.glob("*.json")) == [
            "1-meme.json", "3-release.json", "7-release.json"
        ]

        # Пост, ушедший владельцу на утверждение, второй раз ему не подаётся:
        # в личке он остаётся в очереди, пока тот не нажмёт кнопку, и ежечасный
        # выход слал один и тот же пост каждый час.
        state.write_json(config.QUEUE / "8-release.json",
                         {"rubric": "release", "released_at": ago(hours=5), "created_at": ago(hours=3),
                          "score": 90, "approval_sent_at": ago(hours=1)})
        assert next_post(releases=True, skip_sent=True) is None
        assert next_post(releases=True).name == "8-release.json"  # в канал он всё равно пойдёт
        assert next_post(skip_sent=True).name == "1-meme.json"
        with mock.patch.dict(os.environ, {"TELEGRAM_ADMIN_ID": "0"}):
            deliver({"rubric": "meme", "text": "Текст."}, config.QUEUE / "1-meme.json", "admin")
        assert state.read_json(config.QUEUE / "1-meme.json", {}).get("approval_sent_at")
        assert next_post(skip_sent=True) is None

        # Выход релиза — не чаще раза в час: интервал считает журнал публикаций,
        # а не крон (его убрали из publish.yml, выпускает дежурство).
        posted()
        assert release_due()
        posted(("release", ago(minutes=20)))
        assert not release_due()
        posted(("release", ago(minutes=20)), ("meme", ago(minutes=5)))
        assert not release_due(), "обычный пост не открывает выход релиза"
        posted(("release", ago(hours=2)), ("meme", ago(minutes=5)))
        assert release_due()
        # Больше config.RELEASE_PER_DAY за московские сутки не выходит; вчерашний
        # по Москве (22:00 МСК 10.09) в счёт не идёт.
        posted(("release", ago(hours=20)), ("verdict", ago(hours=4)))
        assert release_due()
        posted(("release", ago(hours=5)), ("verdict", ago(hours=4)))
        assert not release_due()
        # Ночные выходы (01:00–03:00 МСК) — хвост вчерашних суток: ни лимит релизов,
        # ни дневные слоты не съедают (26.09.2026 лента из-за них молчала весь день).
        posted(("release", ago(hours=17)), ("release", ago(hours=16)), ("verdict", ago(hours=15)))
        assert release_due() and due({"rubric": "meme"})
        print("выходы релизов: сутки, окно на трек, два в день, звук в канале — у одного поста за сутки, обычный слот уступает")
    finally:
        (card.cover, telegram.send_photo, telegram.send_photo_file, telegram.send_audio,
         telegram.send_message, state.now, config.QUEUE, config.ARCHIVE, config.POSTED_FILE) = real
        tmp.cleanup()

    def links(text: str) -> dict[str, str]:
        return {label: url for url, label in re.findall(r'<a href="([^"]+)">([^<]+)</a>', text)}

    apple = "https://music.apple.com/us/album/fuel-the-fire-single/6802784931?uo=4"
    post = f'<b>ЗАГОЛОВОК</b>\n\nТекст.\n\n▸ <a href="{apple}">Слушать в Apple Music</a>'
    text = listen(post, "Ghostface Playa", "Fuel the Fire")
    assert text.startswith(f"<b>ЗАГОЛОВОК</b>\n\nТекст.\n\n{LISTEN_HEAD}\n<a href="), text
    urls = links(text)
    # Четыре площадки строкой плюс пятый — магазин находки с точной ссылкой.
    assert list(urls) == ["Яндекс", "VK", "Звук", "Spotify", "Apple"], urls
    assert urls["Apple"] == apple
    assert urls["Spotify"] == "https://open.spotify.com/search/Ghostface%20Playa%20Fuel%20the%20Fire"
    # Ссылка Deezer точна только для Deezer; «/» и «&» в имени не ломают адрес поиска.
    deezer_link = "https://www.deezer.com/album/1057397272"
    urls = links(listen(f'▸ <a href="{deezer_link}">Слушать в Deezer</a>', "AC/DC & Co", "Back"))
    assert urls["Deezer"] == deezer_link and "Apple" not in urls, urls
    assert urls["Яндекс"] == "https://music.yandex.ru/search?text=AC%2FDC%20%26%20Co%20Back"
    # Магазин из четвёрки не задваивается: точная ссылка встаёт на своё место.
    urls = links(listen('▸ <a href="https://zvuk.com/release/1">Слушать в Звуке</a>', "Bones", "x"))
    assert list(urls) == ["Яндекс", "VK", "Звук", "Spotify"] and urls["Звук"] == "https://zvuk.com/release/1"
    # Новость и видео — не релиз: текст как был.
    for line in ('▸ <a href="https://www.nme.com/news">Источник — NME</a>',
                 '▸ <a href="https://youtu.be/abc">Смотреть на YouTube</a>'):
        news = f"Текст.\n\n{line}"
        assert listen(news, "Bones", "") == news, line
    # Полный трек в комментариях — строкой над площадками; нет трека — ни слова о нём.
    shown = track_note(text, {"full_track_file_id": "x"})
    assert shown == f"{text}\n{TRACK_NOTE}" and track_note(shown, {"full_track_file_id": "x"}) == shown
    assert track_note(text, {}) == text and track_note("Текст.", {"full_track_file_id": "x"}) == f"Текст.\n\n{TRACK_ALONE}"
    # У отбора под площадками ещё зов в бота: строка встаёт между ними.
    otbor = track_note(f"{text}\n\nПришли свой — @bot", {"full_track_file_id": "x"})
    assert otbor == f"{text}\n{TRACK_NOTE}\n\nПришли свой — @bot", otbor
    # Разбор и новость: что послушать лежит в комментариях всегда, файлом или ссылками.
    heard = track_note("Разбор.", {"listen": [{"artist": "Bones", "track": "HDMI"}]})
    assert heard == f"Разбор.\n\n{LISTEN_NOTE}" and track_note(heard, {"listen": [{}]}) == heard, heard
    print("площадки стримингов: все проверки прошли")

    # Имена артистов — ссылками на карточку в боте, только при выдаче (artist_links).
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "artists.json"
        state.write_json(base, {"artists": [{"name": "Nas", "deezer_id": 1}, {"name": "Lil Uzi Vert", "deezer_id": 3},
                                            {"name": "Uzi", "deezer_id": 4},
                                            {"name": "Кино", "aliases": ["Kino"], "deezer_id": 2}]})
        known = lambda name, min_fans=0: {"Pharrell Williams": 7, "Quavo": 8}.get(name)
        with mock.patch.object(config, "ARTISTS_FILE", base), mock.patch.object(deezer, "find_artist_id", known):
            # shown, которого нет в тексте, и имя, которого Deezer не знает, ссылки не получают.
            ids = artist_ids("Quavo позвал «Фаррелла Уильямса».", [
                "Quavo", {"shown": "Фаррелла Уильямса", "name": "Pharrell Williams"},
                {"shown": "Канье", "name": "Kanye West"}, {"shown": "позвал", "name": "Нет такого"}, "мусор", {"shown": 1}])
            assert ids == {"Quavo": 8, "Фаррелла Уильямса": 7}, ids
            # Артистам релиза id даёт сам релиз: тёзку по имени не ищем, кого в карточке релиза нет — без ссылки,
            # а в магазин идём, только когда имя правда стоит в тексте.
            from . import collect

            asked: list[dict] = []
            own = lambda item: asked.append(item) or {"ghost mountain": None, "buckshot": 99}
            with (mock.patch.object(collect, "release_artists", own),
                  mock.patch.object(deezer, "find_artist_id", {"Buckshot": 60450, "Ghost Mountain": 1, "Quavo": 8}.get)):
                assert artist_ids("Текст без имён.", ["Buckshot"], {"title": "X"}) == {} and not asked
                credited = artist_ids("Ghost Mountain и Buckshot позвали Quavo.",
                                      ["Ghost Mountain", "Buckshot", "Quavo"], {"title": "X"})
            assert credited == {"Buckshot": 99, "Quavo": 8} and len(asked) == 1, (credited, asked)
            link = ARTIST_LINK.format
            text = "Nasty — не Nas. Nas снова, Lil Uzi Vert без Uzi. <b>Кино</b> — это «Kino» и «Фаррелла Уильямса»."
            linked = artist_links(text, {"links": ids})
            assert linked.count(link(1)) == 1 and f'не <a href="{link(1)}">Nas</a>. Nas' in linked, linked
            assert f'<a href="{link(3)}">Lil Uzi Vert</a> без <a href="{link(4)}">Uzi</a>' in linked, linked
            assert linked.count(link(2)) == 1 and f'<b><a href="{link(2)}">Кино</a></b>' in linked, "одна карточка — одна ссылка"
            assert f'«<a href="{link(7)}">Фаррелла Уильямса</a>»' in linked, linked
            assert telegram.sanitize(linked) == linked and telegram.visible_len(linked) == telegram.visible_len(text)
            assert artist_links(f'<a href="https://nas.com/Nas">Nas</a>', {}) == '<a href="https://nas.com/Nas">Nas</a>'
            assert artist_links("<code>Nas · Uzi</code>\n\nNas дальше.", {}) == f'<code>Nas · Uzi</code>\n\n<a href="{link(1)}">Nas</a> дальше.'
            # Текст ради ссылок не режется: не влезло — ссылки снимаются с последней.
            extra = len(f'<a href="{link(1)}"></a>')
            long = "Nas и Uzi " + "а" * (telegram.MAX_TEXT - extra - 11)
            linked = artist_links(long, {})
            assert link(1) in linked and link(4) not in linked and len(linked) <= telegram.MAX_TEXT, len(linked)
            assert telegram.visible_len(linked) == len(long)
            caption = "Nas. " + "а" * (telegram.MAX_CAPTION - 5)
            assert telegram.visible_len(artist_links(caption, {})) == telegram.MAX_CAPTION
        # Страница без альбомов — не артист: поиск по имени её не отдаёт (Соня Мармеладова, 01.10.2026).
        pages = [{"id": 5, "name": "Соня", "nb_album": 0, "nb_fan": 29}, {"id": 6, "name": "соня", "nb_album": 2, "nb_fan": 1}]
        with mock.patch.object(config, "ARTISTS_FILE", base), mock.patch.object(deezer, "get_json", lambda *a, **kw: {"data": pages}):
            assert deezer.find_artist_id("Соня") == 6
            del pages[1]
            assert deezer.find_artist_id("Соня") is None, "пустая страница ссылкой не становится"
            # Тёзка с альбомами (SHYM, 01.10.2026): названному моделью ссылки нет, пока у страницы
            # нет слушателей; имя из данных поста и артист базы порога не знают.
            pages[:] = [{"id": 60648852, "name": "SHYM", "nb_album": 4, "nb_fan": 15}]
            model = [{"shown": "Shym", "name": "Shym"}, {"shown": "Nas", "name": "Nas"}]
            assert artist_ids("Бит — Shym, куплет — Nas.", model) == {"Nas": 1}
            assert artist_ids("Бит — Shym.", ["Shym"]) == {"Shym": 60648852}
            pages[0]["nb_fan"] = config.PEOPLE_MIN_FANS
            assert artist_ids("Бит — Shym.", model) == {"Shym": 60648852}
    print("имена артистов: ссылка одна на имя, внутри слова и без Deezer — нет, лимит соблюдён; "
          "артисты релиза — из самого релиза, пустая страница Deezer — не артист, "
          "названный моделью тёзка без слушателей — без ссылки")


def main() -> int:
    parser = argparse.ArgumentParser(description="Публикация постов в Telegram")
    parser.add_argument(
        "--target",
        choices=["admin", "channel"],
        default="admin",
        help="куда отправлять: admin — себе в личку (по умолчанию), channel — в канал",
    )
    parser.add_argument("--dry-run", action="store_true", help="показать пост, не отправляя")
    parser.add_argument("--check", action="store_true", help="проверить настройки бота")
    parser.add_argument("--selftest", action="store_true", help="проверить сборку кнопок стримингов")
    parser.add_argument("--force", action="store_true", help="игнорировать интервал между постами")
    parser.add_argument(
        "--releases", action="store_true",
        help="выход свежего релиза: один готовый пост о релизе, мимо обычных слотов",
    )
    parser.add_argument(
        "--preview-all",
        action="store_true",
        help="прислать себе в личку всю очередь целиком, ничего не публикуя",
    )
    args = parser.parse_args()

    if args.selftest:
        _selftest()
        return 0

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    config.load_dotenv()

    if args.check:
        name = telegram.check()
        print(f"Бот на связи: {name}")
        chat = config.secret("TELEGRAM_ADMIN_ID")
        telegram.send_message(chat, "<b>ПЛЁНКА</b> на связи. Проверка прошла успешно.")
        print("Тестовое сообщение отправлено тебе в личку.")
        return 0

    if args.preview_all:
        posts = sorted(config.QUEUE.glob("*.json"))
        if not posts:
            print("Очередь пуста.")
            return 0
        chat_id = config.secret("TELEGRAM_ADMIN_ID")
        telegram.send_message(
            chat_id,
            f"<b>Очередь на просмотр — {len(posts)} постов.</b>\n"
            f"Это превью: в канал ничего не ушло.",
        )
        for item in posts:
            send_for_approval(state.read_json(item, {}), item, chat_id)
        print(f"Отправлено на просмотр: {len(posts)} постов. Очередь не тронута.")
        return 0

    path = next_post(releases=args.releases, dry_run=args.dry_run,
                     skip_sent=args.target == "admin" and not args.dry_run)
    if path is None:
        print("Готовых постов о свежих релизах нет." if args.releases
              else "Очередь пуста. Запусти генерацию: python -m src.compose --submit")
        return 0

    post = state.read_json(path, {})

    if args.dry_run:
        print(f"\nФайл: {path.name}")
        print(f"Рубрика: {post.get('rubric')}")
        if post.get("rubric") in config.RELEASE_RUBRICS:
            print(f"Релизов за московские сутки: {releases_today()} из {config.RELEASE_PER_DAY}"
                  f"{', тихие часы — без звука' if night(state.now()) else ''}")
        # Картинку видно и без сети: имя артиста ищется в тексте тем же поиском,
        # что при отправке скачает фотографию (card.cover → footage.artist_image).
        portrait = "" if post.get("rubric") == "meme" else footage.find_artist(post.get("text", ""))
        print(f"Картинка: {post.get('cover') or (f'портрет артиста — {portrait}' if portrait else 'нет')}")
        if post.get("full_track_file_id"):
            full = "есть — уйдёт полным треком, а не отрывком"
        elif post.get("track_request"):
            full = f"запрошен у владельца {post['track_request'].get('sent_at', '')}, ответа нет"
        else:
            full = "нет"
        print(f"Полный трек: {full}")
        for piece in post.get("listen") or []:
            got = ("файл есть" if piece.get("full_track_file_id") else
                   "запрошен, файла нет — встанет ссылками на площадки" if piece.get("track_request") else
                   "не запрошен — встанет ссылками на площадки")
            print(f"В комментарии: {piece.get('artist', '')} — {piece.get('track', '')} ({got})")
        shown = view(post.get("text", ""), post)
        if telegram.visible_len(shown) > telegram.MAX_CAPTION:
            print(f"Вид: текстом — подпись к фото не больше {telegram.MAX_CAPTION} знаков, "
                  f"а в посте {telegram.visible_len(shown)}")
        elif post.get("cover") or portrait:
            track = " · полный трек уйдёт первым комментарием" if post.get("full_track_file_id") else ""
            print(f"Вид: картинка в рамке с текстом, одним сообщением{track}")
        else:
            print("Вид: текстом — картинки нет")
        print()
        if post.get("rubric") == "meme":
            print(f"Картинка: {post.get('picture') or 'нет — уйдёт текстом'}")
            print(f"Сверху: {post.get('top', '')}\nСнизу: {post.get('bottom', '')}\n")
        print(shown)
        return 0

    # Выход релиза интервала не ждёт: его срок — сутки от выхода релиза.
    if not (args.releases or args.force or due(post)):
        print(f"Рано: с прошлой публикации не прошло {config.PUBLISH_INTERVAL_HOURS} ч "
              "или сутки отданы релизам.")
        return 0

    if args.target == "channel":
        deliver(post, path, "channel")
        print(f"Опубликовано в канал: {path.name}. Осталось в очереди: {len(list(config.QUEUE.glob('*.json')))}")
    else:
        # В личку пост уходит с кнопками решения и остаётся в очереди,
        # пока ты не нажмёшь «В канал» или «Удалить».
        deliver(post, path, "admin")
        print(f"Отправлено на утверждение: {path.name}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
