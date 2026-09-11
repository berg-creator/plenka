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
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote, urlparse

from . import card, config, state, telegram
from .sources import deezer, itunes

log = logging.getLogger("publish")


def next_post(dry_run: bool = False) -> Path | None:
    """Следующий пост: свежий релиз, иначе самый ранний файл очереди.

    Порядок задаёт имя файла, а релиз пишется в конец очереди — при двадцати
    постах и четырёх слотах «вышел альбом» выходил дней через пять. Решение
    владельца от 11.09.2026: релиз не старше config.RELEASE_FRESH_HOURS идёт
    вперёд, в тех же слотах и без отдельных сообщений, из нескольких — самый
    весомый по score сборщика. Полного трека не ждём: не прислан к слоту —
    пост уходит с отрывком, свежесть важнее.

    Релиз старше config.RELEASE_STALE_DAYS из очереди убирается: «вышел»
    про релиз недельной давности врёт. Даты выхода нет (посты до 11.09.2026) —
    считаем от created_at. Будущая дата вперёд не пускает: iTunes ставит выход
    на 07:00 UTC, поэтому сравниваются дни, а не часы. Сухой прогон
    ничего не удаляет, только пишет в лог.
    """
    now = state.now()
    queue, fresh = [], []
    for path in sorted(config.QUEUE.glob("*.json")):
        post = state.read_json(path, {})
        released = state._parse(post.get("released_at") or post.get("created_at") or "")
        if post.get("rubric") == "release" and released is not None:
            if now - released > timedelta(days=config.RELEASE_STALE_DAYS):
                log.warning("Релиз протух, %s: %s", "убрал бы" if dry_run else "убран из очереди", path.name)
                if not dry_run:
                    path.unlink()
                continue
            if released.date() <= now.date() and now - released <= timedelta(hours=config.RELEASE_FRESH_HOURS):
                fresh.append((-(post.get("score") or 0), path))
        queue.append(path)
    if fresh:
        return min(fresh)[1]  # весомее — раньше, при равном весе — раньше написанный
    return queue[0] if queue else None


def due() -> bool:
    """Пора ли публиковать — исходя из времени прошлой публикации."""
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


# Последняя строка поста о релизе («▸ Слушать в Apple Music», см. compose.name_button).
# В Telegram её место занимает ряд кнопок стримингов, а из сохранённого текста
# она не пропадает: у записи ВКонтакте кнопок нет, и ссылку туда несёт она.
_LISTEN_LINE = re.compile(r'^▸\s*<a\s+href="([^"]+)"[^>]*>\s*Слушать[^<]*</a>\s*$', re.MULTILINE)


def _host(url: str) -> str:
    return urlparse(url).netloc.casefold().removeprefix("www.")


def listen(text: str, artist: str, title: str) -> tuple[str, list[list[dict]]]:
    """Убирает из текста строку «▸ Слушать…» и собирает вместо неё кнопки
    стримингов из config.LISTEN_SERVICES.

    Пост без этой строки не трогаем: «Источник» у новости ведёт на статью,
    «Смотреть на YouTube» — на видео, а не на релиз. Сервис, чей адрес совпал
    со ссылкой из поста, получает её саму — это точный релиз. Остальные ведут
    на поиск.
    """
    match = _LISTEN_LINE.search(text)
    query = quote(f"{artist} {title}".strip(), safe="")
    if not match or not query:
        return text, []

    link = match.group(1)
    buttons = [
        {"text": label, "url": link if _host(search) == _host(link) else search.format(q=query)}
        for label, search in config.LISTEN_SERVICES
    ]
    text = re.sub(r"\n{3,}", "\n\n", _LISTEN_LINE.sub("", text)).strip()
    # По три в ряд: при четырёх подписи обрезались у всех, кроме VK.
    return text, [buttons[i : i + 3] for i in range(0, len(buttons), 3)]


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


def send(post: dict, chat_id: str) -> None:
    """Отправляет пост нужным методом: опрос, отрывок трека, фото или текст."""
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
                telegram.send_photo_file(chat_id, image, text)
                return
            except telegram.TelegramError as exc:
                log.warning("Мем с картинкой не ушёл (%s), отправляю текстом", exc)
        text = card.meme_text(post)

    cover = post.get("cover", "")
    text, buttons = listen(text, post.get("artist", ""), release_title(post))

    # Обложка крупно, музыка следом. Фото и аудио в одно сообщение Telegram
    # не кладёт, а у плеера обложка — иконка на палец. Решение владельца
    # от 11.09.2026: текст и кнопки стримингов под фото, плеер — следующим
    # сообщением, без подписи и без второго уведомления.
    if cover and len(text) <= telegram.MAX_CAPTION:
        try:
            # Рамка канала: рубрика сверху, подпись снизу. Не нарисовалась
            # (нет сети, битый файл) — обложка уходит как была.
            framed = card.cover(post)
            if framed:
                telegram.send_photo_file(chat_id, framed, text, buttons=buttons)
            else:
                telegram.send_photo(chat_id, cover, text, buttons=buttons)
        except telegram.TelegramError as exc:
            # Обложка могла протухнуть — тогда текст уезжает вместе с музыкой.
            log.warning("Фото не ушло (%s), пробую с музыкой", exc)
        else:
            send_music(post, chat_id, "", quiet=True)
            return

    if not send_music(post, chat_id, text, buttons):
        telegram.send_message(chat_id, text, buttons=buttons)


def send_music(
    post: dict, chat_id: str, caption: str, buttons: list[list[dict]] | None = None,
    *, quiet: bool = False,
) -> bool:
    """Полный трек от владельца, иначе отрывок магазина. False — не ушло ничего."""
    if len(caption) > telegram.MAX_CAPTION:
        return False

    # Полный трек, присланный владельцем (src/moderate.py), важнее отрывка.
    # Файл уже лежит у Telegram и уходит по file_id: качать нечего, а название
    # и артиста при повторе Telegram берёт из самого файла — переданные поверх
    # он игнорирует, проверено вживую. Поэтому дежурство при приёме заливает трек
    # заново, уже с названием, артистом и обложкой из поста.
    full_track = post.get("full_track_file_id", "")
    if full_track:
        try:
            telegram.send_audio(chat_id, full_track, caption, buttons=buttons, quiet=quiet)
            return True
        except telegram.TelegramError as exc:
            log.warning("Полный трек не ушёл (%s), пробую отрывком", exc)

    preview = post.get("preview", "")
    if not preview:
        return False
    # Ссылка Deezer на отрывок живёт часы, пост в очереди — дни: перед
    # отправкой берём у магазина свежую, а не сохранённую при генерации.
    from .compose import fresh_preview

    preview = fresh_preview(post) or preview
    try:
        telegram.send_audio(
            chat_id,
            preview,
            caption,
            title=post.get("track", ""),
            performer=post.get("artist", ""),
            cover_url=post.get("cover", ""),
            buttons=buttons,
            quiet=quiet,
        )
        return True
    except telegram.TelegramError as exc:
        # Ссылка на отрывок живёт не вечно.
        log.warning("Отрывок не ушёл: %s", exc)
        return False


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
    """Кнопки стримингов: строка «Слушать» уходит, точная ссылка остаётся точной.
    Пост с обложкой и музыкой — два сообщения: фото с текстом, следом тихий плеер.

    Запуск: python -m src.publish --selftest
    """
    sent: list[tuple] = []
    real = card.cover, telegram.send_photo, telegram.send_audio
    card.cover = lambda post: None
    telegram.send_photo = lambda chat, url, caption, buttons=None: sent.append(("фото", caption))
    telegram.send_audio = lambda chat, audio, caption, buttons=None, quiet=False, **_: sent.append(
        ("плеер", caption, quiet)
    )
    try:
        post = {"text": "Текст.", "cover": "https://x/c.jpg", "full_track_file_id": "ID"}
        send(post, "0")
        assert sent == [("фото", "Текст."), ("плеер", "", True)], sent
        sent.clear()
        # Без обложки текст едет с плеером, и уведомление у него обычное.
        send({**post, "cover": ""}, "0")
        assert sent == [("плеер", "Текст.", False)], sent
    finally:
        card.cover, telegram.send_photo, telegram.send_audio = real

    apple = "https://music.apple.com/us/album/fuel-the-fire-single/6802784931?uo=4"
    post = f'<b>ЗАГОЛОВОК</b>\n\nТекст.\n\n▸ <a href="{apple}">Слушать в Apple Music</a>'
    text, rows = listen(post, "Ghostface Playa", "Fuel the Fire")
    assert text == "<b>ЗАГОЛОВОК</b>\n\nТекст.", text
    urls = {b["text"]: b["url"] for row in rows for b in row}
    assert len(urls) == len(config.LISTEN_SERVICES) and all(len(row) <= 3 for row in rows)
    assert urls["Apple"] == apple
    assert urls["Spotify"] == "https://open.spotify.com/search/Ghostface%20Playa%20Fuel%20the%20Fire"
    # Ссылка Deezer точна только для Deezer; «/» и «&» в имени не ломают адрес поиска.
    deezer_link = "https://www.deezer.com/album/1057397272"
    _, rows = listen(f'▸ <a href="{deezer_link}">Слушать в Deezer</a>', "AC/DC & Co", "Back")
    urls = {b["text"]: b["url"] for row in rows for b in row}
    assert urls["Deezer"] == deezer_link
    assert urls["Apple"] == "https://music.apple.com/search?term=AC%2FDC%20%26%20Co%20Back"
    # Новость и видео — не релиз: текст как был, кнопок нет.
    for line in ('▸ <a href="https://www.nme.com/news">Источник — NME</a>',
                 '▸ <a href="https://youtu.be/abc">Смотреть на YouTube</a>'):
        news = f"Текст.\n\n{line}"
        assert listen(news, "Bones", "") == (news, []), line
    print("кнопки стримингов: все проверки прошли")

    # Очередь во временной папке: свежий релиз вперёд по весу, протухший убирается,
    # сухой прогон ничего не трогает.
    import tempfile

    now = state.now()

    def ago(**delta: float) -> str:
        return state.iso(now - timedelta(**delta))

    real_queue = config.QUEUE
    with tempfile.TemporaryDirectory() as tmp:
        config.QUEUE = Path(tmp)
        try:
            for name, post in {
                "1-meme.json": {"rubric": "meme", "created_at": ago(days=6)},
                "2-release.json": {"rubric": "release", "released_at": ago(hours=10), "score": 80},
                "3-release.json": {"rubric": "release", "released_at": ago(hours=5), "score": 95},
                "4-release.json": {"rubric": "release", "released_at": ago(days=4), "score": 100},
                "5-release.json": {"rubric": "release", "created_at": ago(hours=1)},  # пост до 11.09
                "6-release.json": {"rubric": "release", "released_at": ago(hours=60), "score": 100},
                "7-release.json": {"rubric": "release", "released_at": ago(days=-2), "score": 100},
            }.items():
                state.write_json(config.QUEUE / name, post)
            assert next_post(dry_run=True).name == "3-release.json"
            assert (config.QUEUE / "4-release.json").exists(), "сухой прогон удалил пост"
            order = []
            while path := next_post():
                order.append(path.name)
                path.unlink()
            # 4 протух и убран; 6 уже не свежий, 7 ещё не вышел — оба в обычном порядке.
            assert order == ["3-release.json", "2-release.json", "5-release.json",
                             "1-meme.json", "6-release.json", "7-release.json"], order
        finally:
            config.QUEUE = real_queue
    print("очередь: свежий релиз вперёд, протухший убран")


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

    path = next_post(dry_run=args.dry_run)
    if path is None:
        print("Очередь пуста. Запусти генерацию: python -m src.compose --submit")
        return 0

    post = state.read_json(path, {})

    if args.dry_run:
        print(f"\nФайл: {path.name}")
        print(f"Рубрика: {post.get('rubric')}")
        print(f"Обложка: {post.get('cover') or 'нет'}")
        # Отрывок меняет способ отправки, а не только вид поста, — в сухом
        # прогоне это видно должно быть сразу.
        print(f"Отрывок: {post.get('preview') or 'нет'}")
        if post.get("full_track_file_id"):
            full = "есть — уйдёт полным треком, а не отрывком"
        elif post.get("track_request"):
            full = f"запрошен у владельца {post['track_request'].get('sent_at', '')}, ответа нет"
        else:
            full = "нет"
        print(f"Полный трек: {full}")
        if post.get("cover") and (post.get("full_track_file_id") or post.get("preview")):
            print("Вид: обложка в рамке с текстом и кнопками, следом плеер без уведомления")
        print()
        if post.get("rubric") == "meme":
            print(f"Картинка: {post.get('picture') or 'нет — уйдёт текстом'}")
            print(f"Сверху: {post.get('top', '')}\nСнизу: {post.get('bottom', '')}\n")
        text, buttons = listen(post.get("text", ""), post.get("artist", ""), release_title(post))
        print(text)
        for row in buttons:
            print("  " + " · ".join(f"[{b['text']}]" for b in row))
        return 0

    if not args.force and not due():
        print(f"Рано: с прошлой публикации не прошло {config.PUBLISH_INTERVAL_HOURS} ч.")
        return 0

    chat_id = (
        config.secret("TELEGRAM_ADMIN_ID")
        if args.target == "admin"
        else config.secret("TELEGRAM_CHANNEL_ID")
    )

    if args.target == "channel":
        send(post, chat_id)
        crosspost_vk(post)
        record(post, path, "channel")
        archive(path)
        print(f"Опубликовано в канал: {path.name}. Осталось в очереди: {len(list(config.QUEUE.glob('*.json')))}")
    else:
        # В личку пост уходит с кнопками решения и остаётся в очереди,
        # пока ты не нажмёшь «В канал» или «Удалить».
        send_for_approval(post, path, chat_id)
        print(f"Отправлено на утверждение: {path.name}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
