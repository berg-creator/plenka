"""Генератор постов: превращает сырьё из inbox в готовую очередь публикаций.

Работает в три режима:

    python -m src.compose --dry-run    показать план: что и по каким рубрикам будет создано
    python -m src.compose --submit     отправить пачку в Batch API (вдвое дешевле)
    python -m src.compose --fetch      забрать готовое из батча и разложить в очередь
    python -m src.compose --now N      сгенерировать N постов сразу, без батча (для отладки)

Батч устроен асинхронно специально: GitHub Actions не должен часами ждать ответа,
поэтому один запуск отправляет задание, а следующий забирает результат.
"""

from __future__ import annotations

import argparse
import logging
import random
import re
from datetime import timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from . import card, config, llm, quality, state, telegram
from .sources import deezer, itunes

log = logging.getLogger("compose")

BATCH_FILE = config.DATA / "pending_batch.json"
USED_FILE = config.DATA / "used_inbox.json"

# Кнопка обязана называть площадку: «Слушать» не говорит, что откроется —
# Apple Music, Deezer или YouTube, а это три разных приложения, и человек
# вправе знать это до нажатия. Просить об этом модель мало: она называет
# площадку через раз, поэтому подпись ставится по домену ссылки.
BUTTON_LABELS = {
    "music.apple.com": "Слушать в Apple Music",
    "deezer.com": "Слушать в Deezer",
    "youtube.com": "Смотреть на YouTube",
    "youtu.be": "Смотреть на YouTube",
}

# Только строка-кнопка целиком: ссылки внутри текста поста не трогаем.
_BUTTON_LINE = re.compile(r'(?m)^(▸\s*<a\s+href="([^"]+)"[^>]*>)([^<]*)(</a>)\s*$')


# ─────────────────────────── очередь ───────────────────────────


def queue_size() -> int:
    return len(list(config.QUEUE.glob("*.json")))


def save_post(
    rubric_key: str,
    text: str,
    source: dict | None = None,
    folder: Path | None = None,
    meme: dict | None = None,
) -> Path:
    """Кладёт готовый пост в очередь. Имя файла задаёт порядок публикации.

    folder уводит пост мимо очереди — так пишутся срочные новости
    (config.URGENT): они выходят в день события, а не когда до них дойдёт
    очередь, и публикатору по расписанию их видеть незачем.

    meme — ответ модели на мем: надписи на картинке и ключ шаблона.
    """
    # Чистим разметку сразу при сохранении, чтобы в очереди лежал тот же текст,
    # который уйдёт в канал, — иначе просмотр очереди врёт.
    if rubric_key != "poll":  # опрос хранится как JSON, его трогать нельзя
        text = name_button(telegram.sanitize(text))

    folder = folder or config.QUEUE
    folder.mkdir(parents=True, exist_ok=True)
    stamp = state.now().strftime("%Y%m%d-%H%M%S")
    suffix = random.randint(1000, 9999)
    path = folder / f"{stamp}-{suffix}-{rubric_key}.json"

    lead = _lead_track(source or {})
    post = {
        "rubric": rubric_key,
        "text": text,
        "created_at": state.iso(),
        "source_url": (source or {}).get("url", ""),
        "cover": (source or {}).get("cover", ""),
        "artist": (source or {}).get("artist", ""),
        "preview": lead.get("preview", ""),
        "track": lead.get("title", ""),
    }
    if rubric_key == "meme":
        # Надписи лежат отдельно от подписи: они рисуются поверх шаблона,
        # а подпись уходит текстом под фото (card.render_meme).
        meme = meme or {}
        post |= {
            "top": _plain(meme.get("top")),
            "bottom": _plain(meme.get("bottom")),
            "picture": known_picture(meme.get("picture")),
        }
    state.write_json(path, post)
    return path


def _plain(value: object) -> str:
    """Строка из ответа модели, годная и для картинки, и для HTML-текста.
    GigaChat схему не соблюдает и вместо строки может прислать что угодно."""
    return telegram.sanitize(value).strip() if isinstance(value, str) else ""


def known_picture(key: object) -> str:
    """Ключ мемной картинки, если он есть в каталоге, иначе пустая строка.

    Незнакомый ключ не бракует пост, а оставляет мем без картинки — он уйдёт
    текстом: надписи и подпись подряд. Шутка — содержание, картинка — оправа:
    выбрасывать годный текст из-за опечатки в ключе дороже, чем выпустить его
    без картинки. К тому же перегенерации у батча нет — ответ приходит один,
    и бракованный ключ там было бы нечем исправить. А приходит такой ключ
    в основном от GigaChat: схему ответа он не соблюдает.
    """
    keys = {m["key"] for m in state.read_json(config.MEMES_FILE, {"memes": []})["memes"]}
    return key if isinstance(key, str) and key in keys else ""


def name_button(text: str) -> str:
    """Подставляет в кнопку название площадки по домену ссылки.

    Незнакомый домен остаётся как есть: у новостей в кнопке стоит имя издания,
    и вывести его из адреса нельзя — «lenta.ru» это ещё не «Лента.ру».
    Выдумывать название по домену — то же враньё, только машинное.
    """

    def rename(match: re.Match[str]) -> str:
        host = urlparse(match.group(2)).netloc.casefold().removeprefix("www.")
        label = next(
            (name for domain, name in BUTTON_LABELS.items()
             if host == domain or host.endswith("." + domain)),
            "",
        )
        return f"{match.group(1)}{label}{match.group(4)}" if label else match.group(0)

    return _BUTTON_LINE.sub(rename, text)


def _lead_track(source: dict) -> dict:
    """Трек, который уйдёт в пост отрывком. Берём первый с отрывком:
    у сингла он единственный, у альбома открывающий — тот, которым релиз
    сам себя представляет. Выбирать «лучший» нам не по чему.
    """
    for track in source.get("tracks") or []:
        if track.get("preview"):
            return track
    return {}


# ─────────────────────────── планирование ───────────────────────────


def generate_checked(rubric_key: str, payload: dict, attempts: int = 3) -> dict:
    """Генерирует пост и проверяет его качество, повторяя при явном браке.

    Модель нестабильна: то вернёт служебный JSON вместо текста, то закончит
    школьным выводом. Повторная попытка обходится дешевле, чем плохой пост
    в канале.
    """
    issues: list[str] = ["не удалось сгенерировать"]

    for attempt in range(attempts):
        result = llm.generate_now(rubric_key, payload)
        if result["skip"] or not result["text"]:
            return result  # модель осознанно отказалась — это не брак

        # Мем проверяется целиком: подпись под картинкой одна короче любого
        # поста, а брак ищется во всём, что увидит читатель.
        checked = card.meme_text(result) if rubric_key == "meme" else result["text"]
        issues = quality.problems(checked, rubric_key)
        if not issues:
            return result

        log.info(
            "Попытка %d для «%s» забракована: %s",
            attempt + 1,
            rubric_key,
            "; ".join(issues),
        )

    return {
        "skip": True,
        "text": "",
        "reason": f"брак после {attempts} попыток: " + "; ".join(issues),
    }


def load_inbox_unused() -> list[dict]:
    """Материалы из inbox, которые ещё не превращались в посты."""
    used = set(state.read_json(USED_FILE, []))
    items = [i for i in state.read_jsonl(config.INBOX_FILE) if i["fingerprint"] not in used]
    items.sort(key=lambda i: i.get("score", 0), reverse=True)
    return items


def mark_used(fingerprints: list[str]) -> None:
    used = set(state.read_json(USED_FILE, []))
    used.update(fingerprints)
    state.write_json(USED_FILE, sorted(used))


def mark_subtext_used(indices: list[int]) -> None:
    """Помечает разобранные треки. Делается только после успешной генерации,
    чтобы сорванный батч не съел материал впустую."""
    if not indices:
        return
    payload = state.read_json(config.SUBTEXT_FILE, {"items": []})
    for index in indices:
        if 0 <= index < len(payload["items"]):
            payload["items"][index]["used"] = True
    state.write_json(config.SUBTEXT_FILE, payload)


def plan(needed: int) -> list[tuple[str, str, dict, dict]]:
    """Составляет задания: (custom_id, ключ рубрики, данные для модели, исходник).

    Рубрики, которым нужно сырьё (релизы, новости), берут его из inbox.
    Рубрики, которые сырья не требуют (мемы, опросы), генерируются из базы артистов.
    """
    inbox = load_inbox_unused()
    artists = state.read_json(config.ARTISTS_FILE, {"artists": []})["artists"]
    lineage = state.read_json(config.LINEAGE_FILE, {"links": []})["links"]

    releases = [i for i in inbox if i["kind"] in ("release", "video")]
    news = [i for i in inbox if i["kind"] == "news"]

    jobs: list[tuple[str, str, dict, dict]] = []
    counter = 0

    def add(rubric_key: str, payload: dict, source: dict) -> None:
        nonlocal counter
        counter += 1
        jobs.append((f"job-{counter:03d}-{rubric_key}", rubric_key, payload, source))

    # Доли рубрик в пачке — из весов в config.RUBRICS. Нулевой вес означает
    # «в очередь не пишем вовсе»: такие рубрики привязаны ко дню и делаются
    # отдельными запусками (ЛЕГЕНДА — календарь, ИНФОПОВОД — src/urgent.py).
    # Раньше их отсекали по имени, а пол max(1, …) всё равно возвращал единицу,
    # и в очередь просачивалась новость, которая к своей публикации протухала.
    weights = {r.key: r.weight for r in config.RUBRICS if r.weight > 0}
    total_weight = sum(weights.values())
    quota = {key: max(1, round(needed * w / total_weight)) for key, w in weights.items()}

    for item in releases[: quota.get("release", 0)]:
        add("release", _release_payload(item), item)

    for item in news[: quota.get("news", 0)]:
        add("news", _news_payload(item), item)

    # ВЕРДИКТ — берём свежие релизы, которые не ушли в рубрику РЕЛИЗ.
    verdict_pool = releases[quota.get("release", 0) :]
    for item in verdict_pool[: quota.get("verdict", 0)]:
        payload = _release_payload(item)
        payload["stance"] = random.choice(["respect", "roast"])
        payload["subject"] = f"{item.get('artist', '')} — {item.get('title', '')}"
        add("verdict", payload, item)

    # ОТКУДА НОГИ — из курируемой базы связей, сырьё из inbox не нужно.
    random.shuffle(lineage)
    for link in lineage[: quota.get("lineage", 0)]:
        add("lineage", link, {})

    # МЕЖДУ СТРОК — только из курируемой базы: цитаты не должны быть выдуманы.
    subtext = state.read_json(config.SUBTEXT_FILE, {"items": []})["items"]
    unused = [(i, item) for i, item in enumerate(subtext) if not item.get("used")]
    for index, item in unused[: quota.get("subtext", 0)]:
        payload = {
            "artist": item.get("artist", ""),
            "track": item.get("track", ""),
            "lines": item.get("lines", []),
            "notes": item.get("notes", []),
            "angle": item.get("angle", ""),
        }
        add("subtext", payload, {"subtext_index": index})

    # МЕМ — контекст из базы артистов, чтобы шутки были про нашу сцену,
    # и каталог картинок. Картинку выбирает модель: она — реакция на поворот,
    # а поворот появляется только вместе с текстом.
    catalog = state.read_json(config.MEMES_FILE, {"memes": []})["memes"]
    pictures = [{"key": m["key"], "when": m["when"]} for m in catalog]
    for _ in range(quota.get("meme", 0)):
        sample = random.sample(artists, min(12, len(artists)))
        # Каталог тасуется на каждый мем: модель тянется к первым строкам
        # списка, и картинки из его конца иначе не выпадали бы никогда.
        shuffled = random.sample(pictures, len(pictures))
        add("meme", {"scene": [a["name"] for a in sample], "pictures": shuffled}, {})

    # ОПРОС — тоже из базы артистов.
    for _ in range(quota.get("poll", 0)):
        sample = random.sample(artists, min(10, len(artists)))
        add("poll", {"artists": [a["name"] for a in sample]}, {})

    return jobs[:needed]


def _release_payload(item: dict) -> dict:
    """Данные о релизе для модели.

    Кроме служебных полей сюда идёт треклист: единственное, что позволяет
    писать про музыку, ничего не выдумывая. Хронометраж, длина треков и фиты —
    это то, что слышно и на слух, но проверяется по данным.
    """
    payload = {
        "artist": item.get("artist", ""),
        "title": item.get("title", ""),
        "track_count": item.get("track_count"),
        "released_at": item.get("released_at", ""),
        "url": item.get("url", ""),
        "tags": item.get("tags", []),
        "tier": item.get("tier", ""),
    }

    tracks = item.get("tracks") or []
    if tracks:
        payload["tracks"] = [
            {"title": t.get("title", ""), "length": _mmss(t.get("seconds", 0))} for t in tracks
        ]
        payload["shortest_track"] = _mmss(min(t.get("seconds", 0) for t in tracks))
        payload["longest_track"] = _mmss(max(t.get("seconds", 0) for t in tracks))
        payload["features"] = _features(tracks)
    if item.get("duration_sec"):
        payload["total_length"] = _mmss(item["duration_sec"])
    if item.get("genre"):
        payload["genre_by_store"] = item["genre"]

    return payload


def _mmss(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}"


# Гости прячутся в названиях треков — «(feat. X)», «with X», «prod. by X».
# Продюсера отделяем от фита: для рэпа это разные новости.
_FEAT = re.compile(r"[(\[]?\s*(?:feat\.?|ft\.?|with|при участии)\s+([^)\]]+)[)\]]?", re.IGNORECASE)


def _features(tracks: list[dict]) -> list[str]:
    names: list[str] = []
    for track in tracks:
        for match in _FEAT.finditer(track.get("title", "")):
            name = match.group(1).strip(" .,&")
            if name and name not in names:
                names.append(name)
    return names[:8]


# Даты в новостях — по Москве: канал русский, и новость, вышедшая в 23:30
# по UTC, для его читателя уже завтрашняя.
MSK = timezone(timedelta(hours=3), "MSK")


def _news_payload(item: dict) -> dict:
    # Сегодняшнего числа модель не знает и подставляет наугад: 11.09 в канал
    # ушла новость с датой «26.09». Поэтому обе даты приходят отсюда,
    # а других в посте быть не может (prompts/rubrics/news.md).
    published = state._parse(item.get("released_at", ""))
    return {
        "title": item.get("title", ""),
        "summary": item.get("summary", ""),
        "outlet": item.get("outlet", ""),
        "lang": item.get("lang", "en"),
        "url": item.get("url", ""),
        "artists": item.get("artists", []),
        "published": published.astimezone(MSK).strftime("%d.%m.%Y") if published else "",
        "today": state.now().astimezone(MSK).strftime("%d.%m.%Y"),
    }


# ─────────────────────────── режимы работы ───────────────────────────


def do_submit(needed: int) -> int:
    # У бесплатного провайдера батча нет и не нужно — генерируем сразу.
    if not llm.supports_batch():
        print(f"Генератор: {llm.describe()} — работаю без батча.")
        return do_now(needed)

    if BATCH_FILE.exists():
        pending = state.read_json(BATCH_FILE, {})
        print(f"Батч {pending.get('batch_id')} ещё не забран. Сначала выполни --fetch.")
        return 1

    jobs = plan(needed)
    if not jobs:
        print("Нечего генерировать: inbox пуст. Сначала запусти сбор.")
        return 0

    try:
        batch_id = llm.submit_batch([(cid, key, payload) for cid, key, payload, _ in jobs])
    except Exception as exc:
        # Батч есть только у Клода. Раз он не принял пачку — пишем поштучно,
        # там на каждом посте сработает запасной генератор.
        log.warning("Батч не отправился (%s). Генерирую поштучно.", exc)
        return do_now(len(jobs), jobs)

    state.write_json(
        BATCH_FILE,
        {
            "batch_id": batch_id,
            "submitted_at": state.iso(),
            "jobs": [
                {"custom_id": cid, "rubric": key, "source": src}
                for cid, key, _, src in jobs
            ],
        },
    )
    print(f"Отправлено заданий: {len(jobs)}. Батч: {batch_id}")
    return 0


def do_fetch() -> int:
    if not llm.supports_batch():
        return 0  # у бесплатного провайдера забирать нечего
    if not BATCH_FILE.exists():
        print("Нет отправленного батча.")
        return 0

    pending = state.read_json(BATCH_FILE, {})
    batch_id = pending["batch_id"]
    status = llm.batch_status(batch_id)

    if status != "ended":
        print(f"Батч {batch_id} ещё в работе (статус: {status}). Загляну позже.")
        return 0

    results = llm.fetch_batch(batch_id)
    created, skipped = 0, 0
    used: list[str] = []
    subtext_done: list[int] = []

    for job in pending["jobs"]:
        result = results.get(job["custom_id"])
        if not result:
            continue
        source = job.get("source") or {}
        if source.get("fingerprint"):
            used.append(source["fingerprint"])

        if result["skip"] or not result["text"]:
            skipped += 1
            log.info("Пропущен %s: %s", job["custom_id"], result.get("reason", ""))
            continue

        save_post(job["rubric"], result["text"], source, meme=result)
        if source.get("subtext_index") is not None:
            subtext_done.append(source["subtext_index"])
        created += 1

    mark_used(used)
    mark_subtext_used(subtext_done)
    BATCH_FILE.unlink()
    print(f"Создано постов: {created}. Отклонено моделью: {skipped}. В очереди: {queue_size()}.")
    return 0


def do_now(count: int, jobs: list[tuple[str, str, dict, dict]] | None = None) -> int:
    # Готовые задания приходят, когда сюда свалились из сорвавшегося батча:
    # план уже составлен, второй раз тасовать рубрики незачем.
    jobs = plan(count) if jobs is None else jobs
    if not jobs:
        print("Нечего генерировать: inbox пуст.")
        return 0

    created, used, subtext_done = 0, [], []
    for custom_id, rubric_key, payload, source in jobs:
        result = generate_checked(rubric_key, payload)
        if source.get("fingerprint"):
            used.append(source["fingerprint"])
        if result["skip"] or not result["text"]:
            print(f"  — {rubric_key}: пропущено ({result.get('reason', '')})")
            continue
        path = save_post(rubric_key, result["text"], source, meme=result)
        if source.get("subtext_index") is not None:
            subtext_done.append(source["subtext_index"])
        created += 1
        print(f"  ✓ {rubric_key}: {path.name}")

    mark_used(used)
    mark_subtext_used(subtext_done)
    print(f"\nСоздано постов: {created}. В очереди: {queue_size()}.")
    return 0


def _lead_from_url(url: str) -> dict:
    """Открывающий трек релиза по ссылке на него в магазине. Идентификатор
    у поста уже сохранён в ссылке, поэтому разыскивать релиз заново не нужно."""
    album = itunes.album_id_from_url(url)
    if album:
        return _lead_track(itunes.album_tracks(album))
    album = deezer.album_id_from_url(url)
    if album:
        return _lead_track(deezer.album_tracks(album))
    return {}


def do_backfill_music() -> int:
    """Дописывает отрывок к постам, которые уже лежат в очереди.

    Посты, написанные до появления музыки в канале, ушли бы немыми — а они
    про релизы, где звук и есть содержание. Текст не трогаем: меняется только
    то, чем пост отправится.
    """
    touched, skipped = 0, 0
    for path in sorted(config.QUEUE.glob("*.json")):
        post = state.read_json(path, {})
        if post.get("preview") or not post.get("source_url"):
            continue

        try:
            lead = _lead_from_url(post["source_url"])
        except Exception as exc:  # магазин мог не ответить — это не повод падать
            log.warning("%s: %s", path.name, exc)
            continue

        if not lead:
            skipped += 1
            continue

        post["preview"] = lead["preview"]
        post["track"] = lead.get("title", "")
        state.write_json(path, post)
        touched += 1
        print(f"  ✓ {post.get('rubric', ''):<8} {post.get('artist', '')} — {lead.get('title', '')}")

    print(f"\nПостов с музыкой: {touched}. Без неё осталось: {skipped}.")
    return 0


def needs_track(post: dict) -> bool:
    """Музыкальный пост без полного трека, про который владельца ещё не спрашивали."""
    return bool(post.get("artist") and post.get("track")) and not (
        post.get("full_track_file_id") or post.get("track_request")
    )


def do_ask_tracks() -> int:
    """Просит владельца прислать полные треки к музыкальным постам очереди.

    Отрывок в тридцать секунд — это витрина магазина, а не музыка. Искать
    и скачивать треки сами мы не стали: легального источника нет, поэтому файл
    присылает владелец — ответом на это сообщение, а принимает его src/moderate.py.

    Отдельный шаг после генерации, а не вызов из save_post: один проход покрывает
    и свежие посты, и лежавшие в очереди до появления запросов, а сорвавшийся
    на Telegram запуск просто повторится завтра — пост к тому моменту уже в очереди.
    Очередь расписана на неделю вперёд, так что на ответ есть дни, а не минуты.
    """
    admin = config.secret("TELEGRAM_ADMIN_ID")
    asked = 0
    for path in sorted(config.QUEUE.glob("*.json")):
        post = state.read_json(path, {})
        if not needs_track(post):
            continue

        rubric = config.RUBRIC_BY_KEY.get(post.get("rubric", ""))
        sent = telegram.send_message(
            admin,
            f"<b>Нужен полный трек</b> · {rubric.title if rubric else post.get('rubric', '')}\n"
            f"{post['artist']} — {post['track']}\n"
            f"<code>{path.name}</code>\n\n"
            "Ответь на это сообщение аудиофайлом — пост выйдет с полным треком "
            "вместо 30-секундного отрывка.",
        )
        # Отметка пишется сразу после каждой отправки: оборвись запуск на середине,
        # уже спрошенное второй раз не спросится. По message_id дежурство
        # найдёт пост, когда придёт ответ.
        post["track_request"] = {"message_id": sent["message_id"], "sent_at": state.iso()}
        state.write_json(path, post)
        asked += 1
        print(f"  ? {post['artist']} — {post['track']}  ({path.name})")

    print(f"Запрошено полных треков: {asked}.")
    return 0


def _selftest() -> int:
    """Проверка подписи кнопки: молча уехавшая подпись врёт читателю,
    а заодно рушит последнюю строку поста. Запуск: python -m src.compose --selftest
    """
    def button(url: str, label: str = "Слушать") -> str:
        return f'текст\n\n▸ <a href="{url}">{label}</a>'

    assert name_button(button("https://music.apple.com/us/album/x/1")).endswith(
        ">Слушать в Apple Music</a>"
    )
    assert name_button(button("https://www.deezer.com/album/1")).endswith(">Слушать в Deezer</a>")
    assert name_button(button("https://youtu.be/abc")).endswith(">Смотреть на YouTube</a>")
    assert name_button(button("https://m.youtube.com/watch?v=1")).endswith(
        ">Смотреть на YouTube</a>"
    )
    # Издание в новости трогать нельзя: имя там стоит своё, не выводимое из домена.
    assert name_button(button("https://the-flow.ru/news/1", "Источник — The Flow")).endswith(
        ">Источник — The Flow</a>"
    )
    # Домен-подделка в пути не должна выдать себя за площадку.
    assert name_button(button("https://evil.ru/?x=deezer.com")).endswith(">Слушать</a>")
    # Ссылка внутри текста — не кнопка, её название остаётся авторским.
    inline = 'в <a href="https://music.apple.com/us/album/x/1">этом альбоме</a> всё ясно'
    assert name_button(inline) == inline

    print("кнопка: все проверки прошли")
    return 0


def do_dry_run(needed: int) -> int:
    jobs = plan(needed)
    print(f"\nВ очереди сейчас: {queue_size()}. Нужно добрать: {needed}.\n")
    if not jobs:
        print("Заданий нет — inbox пуст. Запусти `python -m src.collect`.")
        return 0
    for _, rubric_key, payload, _ in jobs:
        title = payload.get("title") or payload.get("subject") or payload.get("modern") or "—"
        print(f"  {config.RUBRIC_BY_KEY[rubric_key].title:<12} {str(title)[:60]}")
    print(f"\nВсего заданий: {len(jobs)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Генератор постов канала")
    parser.add_argument("--dry-run", action="store_true", help="показать план без затрат")
    parser.add_argument("--submit", action="store_true", help="отправить батч (дёшево)")
    parser.add_argument("--fetch", action="store_true", help="забрать готовый батч")
    parser.add_argument("--now", type=int, metavar="N", help="сгенерировать N постов сразу")
    parser.add_argument(
        "--backfill-music",
        action="store_true",
        help="дописать отрывки к постам, которые уже в очереди",
    )
    parser.add_argument(
        "--ask-tracks",
        action="store_true",
        help="попросить у владельца полные треки к музыкальным постам очереди (каждый — один раз)",
    )
    parser.add_argument("--selftest", action="store_true", help="проверить подпись кнопки")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    config.load_dotenv()

    needed = max(0, config.QUEUE_TARGET - queue_size())

    if args.selftest:
        return _selftest()
    if args.ask_tracks:
        return do_ask_tracks()
    if args.backfill_music:
        return do_backfill_music()
    if args.dry_run:
        return do_dry_run(needed or config.QUEUE_TARGET)
    if args.now:
        return do_now(args.now)
    if args.fetch:
        return do_fetch()
    if args.submit:
        if needed <= 0:
            print(f"Очередь полна ({queue_size()} постов) — генерировать нечего.")
            return 0
        return do_submit(needed)

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
