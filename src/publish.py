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

from . import card, config, state, telegram
from .sources import deezer, itunes

log = logging.getLogger("publish")


def next_post(releases: bool = False, dry_run: bool = False) -> Path | None:
    """Следующий обычный пост — самый ранний файл очереди; с releases —
    пост о свежем релизе, готовый к своему выходу.

    Решения владельца от 11.09.2026. Пост о релизе (config.RELEASE_RUBRICS)
    в четыре обычных слота не идёт: у него свой выход, раз в час по одному,
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


def releases_today(loud: bool = False) -> int:
    """Сколько постов о релизах вышло за сегодня. Сутки московские: аудитория русская.

    loud — только вышедшие не в тихие часы: ночной пост молчал и в счёт трёх
    со звуком не идёт. Объём ленты (due) считает все.
    """
    from .compose import MSK

    today = state.now().astimezone(MSK).date()
    count = 0
    for item in state.read_json(config.POSTED_FILE, {"items": []}).get("items", []):
        published = state._parse(item.get("published_at", ""))
        if (item.get("rubric") in config.RELEASE_RUBRICS and published
                and published.astimezone(MSK).date() == today and not (loud and night(published))):
            count += 1
    return count


def due(post: dict) -> bool:
    """Пора ли публиковать обычный пост — исходя из времени прошлой публикации.

    Считаются все публикации, выходы релизов тоже: обычный пост вечнозелёный
    и уступает слот свежему релизу. А сутки, где постов о релизах больше
    config.RELEASE_LOUD_PER_DAY, отданы им целиком — одного интервала мало:
    в пятницу девять выходов кончаются к полудню, и вечерние слоты добавили бы
    ленте ещё два поста сверх девяти. Решения владельца от 11.09.2026.
    Годовщину это не касается: завтра она уже не годовщина.
    """
    if post.get("rubric") != "legend" and releases_today() > config.RELEASE_LOUD_PER_DAY:
        return False
    posted = state.read_json(config.POSTED_FILE, {"items": []})
    items = posted.get("items", [])
    if not items:
        return True

    last = state._parse(items[-1].get("published_at", ""))
    if last is None:
        return True
    return state.now() - last >= timedelta(hours=config.PUBLISH_INTERVAL_HOURS)


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
    text = listen(post.get("text", "").strip(), post.get("artist", ""), release_title(post))
    where = message["chat"], message["message_id"], text
    if message["kind"] != "caption":
        telegram.edit_text(*where, buttons=message.get("buttons"))
        return
    if len(text) > telegram.MAX_CAPTION:
        raise telegram.TelegramError(f"подпись {len(text)} знаков — больше {telegram.MAX_CAPTION}")
    telegram.edit_caption(*where, buttons=message.get("buttons"))


# Последняя строка поста о релизе («▸ Слушать в Apple Music», см. compose.name_button).
# В Telegram она разворачивается в ссылки на площадки, а в сохранённом тексте
# остаётся как есть: во ВКонтакте уходит запись целиком, и ссылку несёт она.
_LISTEN_LINE = re.compile(r'^▸\s*<a\s+href="([^"]+)"[^>]*>\s*Слушать[^<]*</a>\s*$', re.MULTILINE)


def _host(url: str) -> str:
    return urlparse(url).netloc.casefold().removeprefix("www.")


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
    # Четыре площадки — строка, которая на телефоне ещё не переносится. Магазин
    # находки прибавляется пятым, если в четвёрку не попал: там лежит сам релиз,
    # а не догадка поиска, и терять такую ссылку жалко.
    services = list(config.LISTEN_SERVICES[:4])
    services += [s for s in config.LISTEN_SERVICES[4:] if _host(s[1]) == _host(link)]
    line = "▸ Слушать — " + " · ".join(
        f'<a href="{link if _host(search) == _host(link) else search.format(q=query)}">{label}</a>'
        for label, search in services
    )
    return re.sub(r"\n{3,}", "\n\n", _LISTEN_LINE.sub(lambda _: line, text)).strip()


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
                return _where(telegram.send_photo_file(chat_id, image, text, quiet=night(state.now())), "caption")
            except telegram.TelegramError as exc:
                log.warning("Мем с картинкой не ушёл (%s), отправляю текстом", exc)
        text = card.meme_text(post)

    cover = post.get("cover", "")
    text = listen(text, post.get("artist", ""), release_title(post))
    # С четвёртого поста о релизе за сутки — без звука: в пятницу их до девяти,
    # а девять уведомлений подряд отписывают быстрее, чем радуют. В тихие часы
    # молчит любой пост (config.QUIET_FROM_HOUR).
    quiet = night(state.now()) or (
        post.get("rubric") in config.RELEASE_RUBRICS
        and releases_today(loud=True) >= config.RELEASE_LOUD_PER_DAY
    )

    # Пост — всегда одна плитка ленты: обложка в рамке, текст, ссылки на площадки
    # строкой в нём же. Плеера рядом нет (решение владельца 12.09.2026): полный
    # трек уходит первым комментарием под постом (src/comments.py), а отрывок
    # магазина не уходит вовсе — вид ленты не должен зависеть от того, прислали
    # трек к этому релизу или нет.
    if cover and telegram.visible_len(text) <= telegram.MAX_CAPTION:
        try:
            # Рамка канала: рубрика сверху, подпись снизу. Не нарисовалась
            # (нет сети, битый файл) — обложка уходит как была.
            framed = card.cover(post)
            if framed:
                photo = telegram.send_photo_file(chat_id, framed, text, quiet=quiet)
            else:
                photo = telegram.send_photo(chat_id, cover, text, quiet=quiet)
            return _where(photo, "caption")
        except telegram.TelegramError as exc:
            # Обложка могла протухнуть — текст уходит обычным сообщением.
            log.warning("Фото не ушло (%s), текст уходит сообщением", exc)

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

    # Опросы во ВКонтакте создаются иначе, чем в Telegram, — пока пропускаем.
    if post.get("rubric") == "poll":
        return

    # Мем сюда уходит текстом, надписи и подпись подряд: vk.post картинку
    # с диска не берёт, только ссылку, а мемная нарисована у нас.
    text = card.meme_text(post) if post.get("rubric") == "meme" else post.get("text", "")
    try:
        post_id = vk.post(text, photo_url=post.get("cover", ""))
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
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    question = (data.get("question") or "").strip()
    options = [str(o).strip() for o in data.get("options", []) if str(o).strip()]
    if not question or len(options) < 2:
        return None
    return {"question": question, "options": options, "is_anonymous": data.get("is_anonymous", True)}


def _selftest() -> None:
    """Площадки стримингов: строка «Слушать» разворачивается в ссылки в тексте.
    Пост — всегда одна плитка: фото в рамке с текстом, без кнопок и без плеера
    рядом (полный трек уходит первым комментарием, src/comments.py).
    send возвращает сообщение с текстом поста, to_channel кладёт его в архив.
    Посты о релизах: свой выход, сутки на всё, окно на трек, звук у первых трёх
    за московские сутки и не в тихие часы, обычный пост уступает им слот.

    Запуск: python -m src.publish --selftest
    """
    import os
    import tempfile
    from unittest import mock

    sent: list[tuple] = []
    real = (card.cover, telegram.send_photo, telegram.send_audio, telegram.send_message, state.now,
            config.QUEUE, config.ARCHIVE, config.POSTED_FILE)
    card.cover = lambda post: None

    # Запись: что ушло, подпись, без звука ли, есть ли кнопки. id сообщения — его номер.
    def message(*entry) -> dict:
        sent.append(entry)
        return {"message_id": len(sent), "chat": {"id": -100}}

    def photo(chat, url, caption, buttons=None, quiet=False):
        if "протухла" in url:
            raise telegram.TelegramError("обложка протухла")
        return message("фото", caption, quiet, bool(buttons))

    telegram.send_photo = photo
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
        assert sent[0][1].startswith("Текст.\n\n▸ Слушать — <a href="), sent[0][1]
        sent.clear()
        # Пост — одна плитка, даже когда трек есть: он уйдёт в комментарии.
        # Возвращается сообщение с текстом поста: по нему правит автопилот точности.
        where = send(post, "0")
        assert sent == [("фото", "Текст.", False, False)], sent
        assert where == {"chat": -100, "message_id": 1, "kind": "caption", "buttons": []}, where
        sent.clear()
        # Отрывок магазина в ленту не идёт вовсе — ни отдельно, ни вместо фото.
        where = send({**post, "full_track_file_id": "", "preview": "https://x/30s.m4a"}, "0")
        assert sent == [("фото", "Текст.", False, False)], sent
        assert where["message_id"] == 1 and where["kind"] == "caption" and not where["buttons"], where
        sent.clear()
        # Фото не ушло — текст обычным сообщением.
        where = send({**post, "cover": "https://x/протухла.jpg"}, "0")
        assert sent == [("текст", "Текст.", False, False)], sent
        assert where == {"chat": -100, "message_id": 1, "kind": "text", "buttons": []}, where
        sent.clear()
        # Без обложки — тоже текст обычным сообщением.
        where = send({**post, "cover": ""}, "0")
        assert sent == [("текст", "Текст.", False, False)] and where["kind"] == "text", where

        # В канал: сообщение с текстом ложится в архивный JSON, текст — как был.
        state.write_json(config.QUEUE / "0-release.json", post)
        with mock.patch.dict(os.environ, {"VK_TOKEN": ""}):
            to_channel(post, config.QUEUE / "0-release.json", "0")
        archived = state.read_json(config.ARCHIVE / "0-release.json", {})
        assert archived == {**post, "message": {"chat": -100, "message_id": 2, "kind": "caption", "buttons": []}}, archived
        assert not (config.QUEUE / "0-release.json").exists()

        # Четвёртый пост о релизе за московские сутки — молча, и фото, и плеер.
        # Вчерашний по Москве (22:00 МСК 10.09) в счёт не идёт.
        release = {**post, "rubric": "release"}
        posted(("release", ago(hours=20)), ("release", ago(hours=3)), ("verdict", ago(hours=2)))
        sent.clear()
        send(release, "0")
        assert sent == [("фото", "Текст.", False, False)], sent
        posted(("release", ago(hours=3)), ("verdict", ago(hours=2)), ("release", ago(hours=1)))
        sent.clear()
        send(release, "0")
        assert sent == [("фото", "Текст.", True, False)], sent

        # Тихие часы: ночные выходы (01:00–03:00 МСК) в счёт трёх со звуком не идут,
        # а в 00:30 по Москве молчит любой пост.
        posted(*[("release", ago(hours=h)) for h in (17, 16, 15)])
        sent.clear()
        send(release, "0")
        assert sent == [("фото", "Текст.", False, False)], sent
        state.now = lambda: datetime(2026, 9, 11, 21, 30, tzinfo=timezone.utc)
        sent.clear()
        send(post, "0")
        state.now = lambda: now
        assert sent == [("фото", "Текст.", True, False)], sent

        # Обычный пост уступает слот свежему релизу; сутки с четырьмя релизами
        # отданы им целиком, но годовщина ждать не может.
        posted(("meme", ago(hours=5)), ("release", ago(hours=1)))
        assert not due({"rubric": "meme"})
        posted(*[("release", ago(hours=h)) for h in (7, 6, 5)])
        assert due({"rubric": "meme"})
        posted(*[("release", ago(hours=h)) for h in (8, 7, 6, 5)])
        assert not due({"rubric": "meme"}) and due({"rubric": "legend"})

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
        print("выходы релизов: сутки, окно на трек, звук у трёх, обычный слот уступает")
    finally:
        (card.cover, telegram.send_photo, telegram.send_audio, telegram.send_message, state.now,
         config.QUEUE, config.ARCHIVE, config.POSTED_FILE) = real
        tmp.cleanup()

    def links(text: str) -> dict[str, str]:
        return {label: url for url, label in re.findall(r'<a href="([^"]+)">([^<]+)</a>', text)}

    apple = "https://music.apple.com/us/album/fuel-the-fire-single/6802784931?uo=4"
    post = f'<b>ЗАГОЛОВОК</b>\n\nТекст.\n\n▸ <a href="{apple}">Слушать в Apple Music</a>'
    text = listen(post, "Ghostface Playa", "Fuel the Fire")
    assert text.startswith("<b>ЗАГОЛОВОК</b>\n\nТекст.\n\n▸ Слушать — "), text
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
    print("площадки стримингов: все проверки прошли")


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

    path = next_post(releases=args.releases, dry_run=args.dry_run)
    if path is None:
        print("Готовых постов о свежих релизах нет." if args.releases
              else "Очередь пуста. Запусти генерацию: python -m src.compose --submit")
        return 0

    post = state.read_json(path, {})

    if args.dry_run:
        print(f"\nФайл: {path.name}")
        print(f"Рубрика: {post.get('rubric')}")
        if post.get("rubric") in config.RELEASE_RUBRICS:
            count, quiet_hours = releases_today(loud=True), night(state.now())
            loud = not quiet_hours and count < config.RELEASE_LOUD_PER_DAY
            print(f"Звук: {'да' if loud else 'нет'} (со звуком за московские сутки: {count}"
                  f"{', сейчас тихие часы' if quiet_hours else ''})")
        print(f"Обложка: {post.get('cover') or 'нет'}")
        if post.get("full_track_file_id"):
            full = "есть — уйдёт полным треком, а не отрывком"
        elif post.get("track_request"):
            full = f"запрошен у владельца {post['track_request'].get('sent_at', '')}, ответа нет"
        else:
            full = "нет"
        print(f"Полный трек: {full}")
        if post.get("cover"):
            track = " · полный трек уйдёт первым комментарием" if post.get("full_track_file_id") else ""
            print(f"Вид: обложка в рамке с текстом, одним сообщением{track}")
        print()
        if post.get("rubric") == "meme":
            print(f"Картинка: {post.get('picture') or 'нет — уйдёт текстом'}")
            print(f"Сверху: {post.get('top', '')}\nСнизу: {post.get('bottom', '')}\n")
        print(listen(post.get("text", ""), post.get("artist", ""), release_title(post)))
        return 0

    # Выход релиза интервала не ждёт: его срок — сутки от выхода релиза.
    if not (args.releases or args.force or due(post)):
        print(f"Рано: с прошлой публикации не прошло {config.PUBLISH_INTERVAL_HOURS} ч "
              "или сутки отданы релизам.")
        return 0

    chat_id = (
        config.secret("TELEGRAM_ADMIN_ID")
        if args.target == "admin"
        else config.secret("TELEGRAM_CHANNEL_ID")
    )

    if args.target == "channel":
        to_channel(post, path, chat_id)
        print(f"Опубликовано в канал: {path.name}. Осталось в очереди: {len(list(config.QUEUE.glob('*.json')))}")
    else:
        # В личку пост уходит с кнопками решения и остаётся в очереди,
        # пока ты не нажмёшь «В канал» или «Удалить».
        send_for_approval(post, path, chat_id)
        print(f"Отправлено на утверждение: {path.name}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
