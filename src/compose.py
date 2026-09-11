"""Генератор постов: превращает сырьё из inbox в готовую очередь публикаций.

Работает в три режима:

    python -m src.compose --dry-run    показать план: что и по каким рубрикам будет создано
    python -m src.compose --submit     отправить пачку в Batch API (вдвое дешевле)
    python -m src.compose --fetch      забрать готовое из батча и разложить в очередь
    python -m src.compose --now N      сгенерировать N постов сразу, без батча (для отладки)
    python -m src.compose --fresh      сразу написать посты о свежих релизах (запуски urgent.yml)

Батч устроен асинхронно специально: GitHub Actions не должен часами ждать ответа,
поэтому один запуск отправляет задание, а следующий забирает результат.
"""

from __future__ import annotations

import argparse
import logging
import random
import re
from collections.abc import Iterable
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from urllib.parse import quote_plus, urlparse

from . import card, collect, config, llm, quality, state, telegram
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
        # По ним публикатор ставит свежий релиз вперёд очереди (publish.next_post).
        "released_at": (source or {}).get("released_at") or "",
        "score": (source or {}).get("score") or 0,
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
    attempt_payload = payload

    for attempt in range(attempts):
        result = llm.generate_now(rubric_key, attempt_payload)
        if result["skip"] or not result["text"]:
            return result  # модель осознанно отказалась — это не брак

        # Мем проверяется целиком: подпись под картинкой одна короче любого
        # поста, а брак ищется во всём, что увидит читатель.
        checked = card.meme_text(result) if rubric_key == "meme" else result["text"]
        issues = quality.problems(checked, rubric_key, payload)
        if not issues:
            return result

        log.info(
            "Попытка %d для «%s» забракована: %s",
            attempt + 1,
            rubric_key,
            "; ".join(issues),
        )
        # Вслепую модель повторяет тот же брак: 11.09.2026 и GigaChat, и Claude
        # трижды подряд вставили «16 треков», и пост пропал. Поэтому причина
        # отказа уходит в следующую попытку рядом с данными.
        attempt_payload = {**payload, "прошлый_вариант_забракован_за": issues}

    # Опись и её пересказ — длинно, но не враньё, а пост о релизе обещан в течение
    # суток. 11.09.2026 GigaChat и Haiku трижды подряд вставляли «16 треков»
    # и с причиной на руках, и пост пропадал. Если брак только такой, выходит
    # последняя попытка, а строка описи из неё вырезается.
    if all(issue.startswith(quality.INVENTORY_ISSUES) for issue in issues):
        log.warning("«%s» выходит с браком описи: %s", rubric_key, "; ".join(issues))
        return {**result, "text": re.sub(r"\n*<code>[^<]*</code>", "", result["text"])}

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


def store_checked(item: dict, artists: dict[str, dict]) -> bool:
    """Подпись релиза сверена с магазином — проверка при чтении inbox.

    До исправления сборщик подписывал релиз тем, по кому он нашёлся, и в inbox
    остались «City Morgue — Hurry Up (feat. City Morgue)», где City Morgue
    только гость, и сольники Inspectah Deck под именем Wu-Tang Clan. Переписать
    эти строки нельзя: inbox объявлен merge=union, и правка вернулась бы дублем.
    Поэтому старую находку сверяем с магазином по id из ссылки, а новую сборщик
    уже сверил сам — у неё есть поле tracked. Магазин не ответил — релиз
    пропускаем: лучше без поста, чем пост под чужим именем.
    """
    if item["kind"] != "release" or item.get("tracked"):
        return True
    name = item.get("artist", "")
    credit, credit_ids = collect.store_credit({**item, "artist": ""})
    tracked_id = artists.get(name, {}).get(f"{item.get('source')}_id")
    if not credit or not collect.own_release(name, tracked_id, credit, credit_ids):
        # ponytail: отсеянное не помечается использованным и сверяется заново каждую ночь.
        # Таких находок конечное число — новые сборщик не пропускает; пометить, если начнёт тормозить.
        log.warning("Отсеян релиз «%s — %s»: в магазине %s", name, item.get("title", ""), credit or "не найден")
        return False
    # tracked — как у сборщика: по нему release_key узнаёт артиста и после того,
    # как подпись сменилась на магазинную («Smoky Mo» вместо «Смоки Мо»).
    item["artist"], item["tracked"] = credit, name
    return True


def release_key(item: dict) -> tuple[str, str]:
    """Один релиз под названиями двух магазинов: «Arsenal - Single» у iTunes
    и «Arsenal» у Deezer. Артист — тот, по кому находка нашлась: у старых строк
    inbox без поля tracked в artist стоит он же."""
    return collect._fold(item.get("tracked") or item.get("artist", "")), itunes._norm(item.get("title", ""))


def fresh_releases(inbox: Iterable[dict], used: set[str]) -> list[dict]:
    """Релизы и клипы под посты, по убыванию веса: вышедшие не больше суток назад.

    Решение владельца от 11.09.2026: от выхода релиза до поста — не больше
    config.RELEASE_MAX_AGE_HOURS, и ВЕРДИКТА это касается так же, как РЕЛИЗА:
    мнение о релизе недельной давности каналу не нужно.

    Предзаказ не берётся: магазин отдаёт релиз за недели до выхода, а пост
    скажет «вышел» — 11.09.2026 так ушёл вердикт на сингл J Dilla. Сравниваются
    дни, а не часы: iTunes ставит выход на 07:00 UTC, и сингл, который магазин
    уже отдал, иначе до утра считался бы будущим.

    Дубль из второго магазина отсеивается и тогда, когда пост написан по первому:
    inbox объявлен merge=union и не переписывается, поэтому сверяем при чтении.
    """
    now = state.now()
    rows = list(inbox)
    taken = {release_key(i) for i in rows if i["fingerprint"] in used}
    fresh: list[dict] = []
    for item in sorted(rows, key=lambda i: i.get("score", 0), reverse=True):
        if item["kind"] not in ("release", "video") or item["fingerprint"] in used:
            continue
        released = state._parse(item.get("released_at") or "")
        if released is None or released.date() > now.date() or release_key(item) in taken:
            continue
        if now - released > timedelta(hours=config.RELEASE_MAX_AGE_HOURS):
            continue
        taken.add(release_key(item))
        fresh.append(item)
    return fresh


def plan(needed: int) -> list[tuple[str, str, dict, dict]]:
    """Составляет задания: (custom_id, ключ рубрики, данные для модели, исходник).

    Посты о релизах сюда не входят — их пишет do_fresh при находке.
    Рубрики, которые сырья не требуют (мемы, опросы), генерируются из базы артистов.
    """
    inbox = load_inbox_unused()
    artists = state.read_json(config.ARTISTS_FILE, {"artists": []})["artists"]
    lineage = state.read_json(config.LINEAGE_FILE, {"links": []})["links"]

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
    # РЕЛИЗА и ВЕРДИКТА здесь нет тоже: пост о релизе пишет do_fresh при находке,
    # а их веса делят между собой (release_jobs).
    weights = {
        r.key: r.weight for r in config.RUBRICS if r.weight > 0 and r.key not in config.RELEASE_RUBRICS
    }
    total_weight = sum(weights.values())
    quota = {key: max(1, round(needed * w / total_weight)) for key, w in weights.items()}

    for item in news[: quota.get("news", 0)]:
        add("news", _news_payload(item), item)

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


def previous_releases(item: dict, inbox: Iterable[dict], artists: dict[str, dict], limit: int = 5) -> list[dict]:
    """Прошлые релизы того же артиста из inbox: последние limit, от старых к новым.

    Без них модель сочиняла прошлое сама: 11.09.2026 GigaChat написал у Смоки Мо
    «уже третий сингл подряд», а за лето их было четыре. Но это не дискография,
    а то, что канал нашёл с августа 2026, — «первый за год» и «вернулся» из этого
    не выводятся, и промпты рубрик говорят об этом прямо.

    Старые строки inbox подписаны тем, по кому нашлись, и среди них чужие синглы
    с его фитом — у City Morgue таких девять. Поэтому каждая сверяется с магазином
    так же, как свежий релиз: история из чужих релизов — та же выдумка. Дубль
    второго магазина схлопывается по release_key, строки inbox не переписываются.
    """
    released = state._parse(item.get("released_at") or "")
    if released is None:
        return []
    artist = release_key(item)[0]
    candidates = []
    for row in inbox:
        when = state._parse(row.get("released_at") or "")
        if row.get("kind") == "release" and when and when.date() < released.date() and release_key(row)[0] == artist:
            candidates.append((when, row))

    taken = {release_key(item)}
    earlier: list[dict] = []
    # ponytail: сверка старой строки — запрос к магазину на каждый пост; кешировать, если сбор начнёт тормозить.
    for when, row in sorted(candidates, key=lambda c: c[0], reverse=True):
        if len(earlier) == limit:
            break
        if release_key(row) in taken or not store_checked(dict(row), artists):
            continue
        taken.add(release_key(row))
        earlier.append({
            "title": row.get("title", ""),
            "released_at": when.date().isoformat(),
            "track_count": row.get("track_count") or len(row.get("tracks") or []) or None,
        })
    return earlier[::-1]


def _release_payload(item: dict, inbox: Iterable[dict] = (), artists: dict[str, dict] | None = None) -> dict:
    """Данные о релизе для модели.

    Кроме служебных полей сюда идёт треклист: единственное, что позволяет
    писать про музыку, ничего не выдумывая. Хронометраж, длина треков и фиты —
    это то, что слышно и на слух, но проверяется по данным.

    inbox и artists дают историю артиста (previous_releases). Нет истории —
    нет и поля: пустой список модель читает как «раньше ничего не выпускал».
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
    earlier = previous_releases(item, inbox, artists or {})
    if earlier:
        payload["previous_releases"] = earlier

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
    # Отметки ставятся и при обрыве на середине: шаг compose --fresh в сборе
    # не срывает сохранение, и уже написанные посты уедут в git, а неотмеченное
    # под ними сырьё следующий запуск написал бы второй раз.
    try:
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
    finally:
        mark_used(used)
        mark_subtext_used(subtext_done)
    print(f"\nСоздано постов: {created}. В очереди: {queue_size()}.")
    return 0


def release_jobs(
    items: list[dict], inbox: Iterable[dict] = (), artists: dict[str, dict] | None = None
) -> list[tuple[str, str, dict, dict]]:
    """Одно задание на релиз: РЕЛИЗ («вышел») или сразу ВЕРДИКТ (мнение).

    Решение владельца от 11.09.2026: два поста о том же релизе — дубль, поэтому
    рубрика одна, жребием по весам release и verdict из config.RUBRICS.
    Сторона вердикта — тоже жребий: разнос или респект, без вежливой середины.
    inbox и artists — для истории артиста в данных (previous_releases).
    """
    weights = [config.RUBRIC_BY_KEY[key].weight for key in config.RELEASE_RUBRICS]
    rows = list(inbox)
    jobs = []
    for item in items:
        rubric = random.choices(config.RELEASE_RUBRICS, weights)[0]
        payload = _release_payload(item, rows, artists)
        if rubric == "verdict":
            payload["stance"] = random.choice(["respect", "roast"])
            payload["subject"] = f"{item.get('artist', '')} — {item.get('title', '')}"
        jobs.append((rubric, rubric, payload, item))
    return jobs


def do_fresh(dry_run: bool) -> int:
    """Посты о свежих релизах — сразу при находке, мимо ночной пачки.

    Решения владельца от 11.09.2026: от выхода релиза до поста — не больше суток,
    а ночная пачка клала пост в конец очереди, и «вышел альбом» выходил дней
    через пять. Поэтому каждый сбор (collect.yml и urgent.yml) пишет пост о каждом
    свежем релизе, без квоты рубрики, а выходит он своим выходом
    (publish --releases), не занимая четырёх обычных слотов.

    Без батча намеренно: его ответ ждать часами, а это и есть потерянная свежесть.
    Путь тот же, что у --now, поэтому находки помечаются использованными
    и второй раз не пишутся. Полный трек просит следующий шаг, compose --ask-tracks:
    запрос трека живёт в одном месте.
    """
    artists = state.read_json(config.ARTISTS_FILE, {"artists": []})["artists"]
    by_name = {a["name"]: a for a in artists}
    rows = list(state.read_jsonl(config.INBOX_FILE))
    fresh = fresh_releases(rows, set(state.read_json(USED_FILE, [])))
    jobs = release_jobs([i for i in fresh if store_checked(i, by_name)], rows, by_name)
    if dry_run:
        for _, rubric, payload, _ in jobs:
            print(f"  {config.RUBRIC_BY_KEY[rubric].title:<8} {payload['artist']} — {payload['title']}"
                  f"  (выход {payload['released_at'][:10]},"
                  f" прошлых релизов: {len(payload.get('previous_releases', []))})")
        print(f"\nСвежих релизов к посту: {len(jobs)}. Рубрика — жребий по весам. Модель не вызывалась.")
        return 0
    if not jobs:
        print("Свежих релизов нет.")
        return 0
    return do_now(len(jobs), jobs)


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


def fresh_preview(post: dict) -> str:
    """Свежая ссылка на отрывок прямо перед отправкой.

    Deezer подписывает ссылку на превью сроком в несколько часов, а пост лежит
    в очереди днями: сохранённая при генерации к публикации уже мертва.
    Магазин не ответил — пустая строка, и вызывающий берёт сохранённую.
    """
    url = post.get("source_url", "")
    if not url:
        return ""
    try:
        return _lead_from_url(url).get("preview", "")
    except Exception:  # noqa: BLE001 — сеть магазина не должна ронять отправку
        return ""


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


def where_to_find(post: dict) -> list[list[dict]]:
    """Кнопки под запросом трека: где трек лежит, чтобы владелец не искал руками.

    Только площадки, где музыка живёт законно: страница релиза в магазине,
    откуда он и попал в канал, и поиск на YouTube, SoundCloud и Bandcamp —
    у части андеграунда там бесплатная загрузка от самого автора. Ссылок
    на файлообменники и конвертеры здесь нет намеренно: скачивает владелец сам,
    и выбор источника — его, а не бота.
    """
    query = quote_plus(f"{post.get('artist', '')} {post.get('track', '')}".strip())
    rows = []
    store = post.get("source_url", "")
    if store.startswith("http"):
        host = urlparse(store).netloc.lower()
        name = next(
            (label.split(" в ")[-1].split(" на ")[-1] for domain, label in BUTTON_LABELS.items()
             if host == domain or host.endswith("." + domain)),
            "Магазин",
        )
        rows.append([{"text": name, "url": store}])
    rows.append([
        {"text": "YouTube", "url": f"https://www.youtube.com/results?search_query={query}"},
        {"text": "SoundCloud", "url": f"https://soundcloud.com/search?q={query}"},
        {"text": "Bandcamp", "url": f"https://bandcamp.com/search?q={query}"},
    ])
    return rows


def do_ask_tracks() -> int:
    """Просит владельца прислать полные треки к музыкальным постам очереди.

    Отрывок в тридцать секунд — это витрина магазина, а не музыка. Искать
    и скачивать треки сами мы не стали: легального источника нет, поэтому файл
    присылает владелец — ответом на это сообщение, а принимает его src/moderate.py.

    Отдельный шаг после генерации, а не вызов из save_post: один проход покрывает
    и свежие посты, и лежавшие в очереди до появления запросов, а сорвавшийся
    на Telegram запуск просто повторится завтра — пост к тому моменту уже в очереди.
    Трек просят только к постам о релизах, а те ждут ответа
    config.RELEASE_TRACK_WAIT_HOURS и уходят с отрывком (publish.next_post),
    поэтому шаг идёт сразу за compose --fresh, в том же запуске.
    """
    admin = config.secret("TELEGRAM_ADMIN_ID")
    asked = 0
    for path in sorted(config.QUEUE.glob("*.json")):
        post = state.read_json(path, {})
        if not needs_track(post):
            continue

        rubric = config.RUBRIC_BY_KEY.get(post.get("rubric", ""))
        text = (
            f"<b>Нужен полный трек</b> · {rubric.title if rubric else post.get('rubric', '')}\n"
            f"{post['artist']} — {post['track']}\n"
            f"<code>{path.name}</code>\n\n"
            "Ответь на это сообщение аудиофайлом — пост выйдет с полным треком "
            "вместо 30-секундного отрывка. Где трек лежит — кнопками ниже."
        )
        buttons = where_to_find(post)
        sent = None
        preview = fresh_preview(post) or post.get("preview", "")
        if preview:
            # Отрывок прямо в запросе: владелец слышит, что ищет, и не скачает
            # одноимённый трек другого артиста или чужой ремикс. Ответ на аудио
            # дежурство находит так же, как на текст, — по message_id.
            try:
                sent = telegram.send_audio(
                    admin, preview, text,
                    title=post["track"], performer=post["artist"],
                    cover_url=post.get("cover", ""), buttons=buttons,
                )
            except telegram.TelegramError as exc:
                print(f"  отрывок не ушёл ({exc}) — запрос текстом")
        if sent is None:
            sent = telegram.send_message(admin, text, buttons=buttons)
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
    """Проверка подписей. Кнопки: молча уехавшая подпись врёт читателю,
    а заодно рушит последнюю строку поста. Релиза: чужой фит под именем гостя
    врёт ещё громче. Запуск: python -m src.compose --selftest
    """
    # Брак описи не губит пост о релизе: модель упёрлась в «16 треков» —
    # причина уходит в повтор, а выходит последняя попытка без строки описи.
    seen: list[dict] = []

    def stubborn_model(key: str, payload: dict) -> dict:
        seen.append(payload)
        text = "<b>KIZARU ВЫПУСТИЛ CA$HEY</b>\n\n16 треков без единого гостя.\n\n<code>16 треков · 38 минут</code>"
        return {"skip": False, "reason": "", "text": text}

    real_generate, llm.generate_now = llm.generate_now, stubborn_model
    try:
        stubborn = generate_checked("release", {"tracks": [{}] * 16})
    finally:
        llm.generate_now = real_generate
    assert not stubborn["skip"] and "<code>" not in stubborn["text"], stubborn
    assert len(seen) == 3 and "прошлый_вариант_забракован_за" in seen[-1], seen
    print("брак описи: причина уходит в повтор, пост выходит без строки описи")

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
    # Поиск трека: амперсанд в имени не должен разорвать адрес на два параметра,
    # а магазин называется площадкой, а не глаголом из кнопки поста.
    found = where_to_find({"artist": "Simon & Garfunkel", "track": "Mrs Robinson",
                           "source_url": "https://music.apple.com/us/album/x/1"})
    assert found[0][0]["text"] == "Apple Music", found[0][0]
    assert "&" not in found[1][0]["url"].split("?", 1)[1], found[1][0]["url"]
    assert [b["text"] for b in found[1]] == ["YouTube", "SoundCloud", "Bandcamp"]
    assert where_to_find({"artist": "A", "track": "B"})[0][0]["text"] == "YouTube"

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

    # Релиз подписан исполнителем из магазина, а не тем, по кому нашёлся.
    # Случаи — из очереди 11.09.2026: гости и сольник ушли под чужим именем.
    own = collect.own_release
    assert not own("City Morgue", 1361386830, "Gunda Manu", [6807911177])  # Hurry Up (feat. City Morgue)
    assert not own("City Morgue", 1361386830, "Horuba Music", [6808604562])  # Slow Time (feat. City Morgue)
    assert not own("Juicy J", 6392055, "CORTIS", [1831651635])  # MOTION (feat. Juicy J)
    assert not own("Wu-Tang Clan", 200986, "Inspectah Deck", [769718])  # Dragon's Breath и два сингла
    assert not own("Juicy J", None, "Juicy Jones", [])
    assert own("City Morgue", 1361386830, "City Morgue, ZillaKami & SosMula", [1361386830])
    assert own("Juicy J", 6392055, "HNTR & Juicy J", [901890750])  # второй основной — по имени
    assert own("Wu-Tang Clan", 200986, "Inspectah Deck, Wu-Tang Clan & CZARFACE", [769718])
    assert own("Смоки Мо", 366970924, "Smoky Mo", [366970924])  # написание разное, id тот же
    assert own("JAY-Z", None, "JAŸ-Z", [])

    # Сборщик и старые находки inbox — на подменённом магазине, без сети.
    listing = [
        {"source": "itunes", "artist": "Gunda Manu", "artist_ids": [6807911177],
         "title": "Hurry Up (feat. City Morgue) - Single", "released_at": state.iso()},
        {"source": "itunes", "artist": "City Morgue, ZillaKami & SosMula", "artist_ids": [1361386830],
         "title": "My Bloody America", "released_at": state.iso()},
    ]
    store = {"6809132448": ("Gunda Manu", [6807911177]),
             "6795547804": ("Inspectah Deck", [769718]),
             "6797938184": ("Michael Bibi, KETTAMA & Wu-Tang Clan", [685311477])}

    def old(artist: str, title: str, album: str) -> dict:
        return {"kind": "release", "source": "itunes", "artist": artist, "title": title,
                "url": f"https://music.apple.com/us/album/x/{album}?uo=4", "external_id": None}

    guest = old("City Morgue", "Hurry Up (feat. City Morgue) - Single", "6809132448")
    solo = old("Wu-Tang Clan", "Shaolin Rebel 2 (feat. Siahlaw) - Single", "6795547804")
    joint = old("Wu-Tang Clan", "MYSTERY OF RAW - Single", "6797938184")
    artists = {"City Morgue": {"itunes_id": 1361386830}, "Wu-Tang Clan": {"itunes_id": 200986}}

    real = itunes.recent_releases, itunes.album_credit
    itunes.recent_releases = lambda _id: listing
    itunes.album_credit = lambda album: store[album]
    try:
        found = collect.collect_releases([{"name": "City Morgue", "itunes_id": 1361386830}], set())
        assert not store_checked(guest, artists)
        assert not store_checked(solo, artists)
        assert store_checked(joint, artists)
        # Чужой сингл с его фитом в историю артиста не попадает: сверка та же, что у свежего.
        guest_before = {**guest, "released_at": state.iso(state.now() - timedelta(days=3))}
        assert previous_releases(found[0], [guest_before], artists) == []
    finally:
        itunes.recent_releases, itunes.album_credit = real
    assert [(r["artist"], r["tracked"]) for r in found] == [
        ("City Morgue, ZillaKami & SosMula", "City Morgue")
    ], found
    assert joint["artist"] == "Michael Bibi, KETTAMA & Wu-Tang Clan", joint
    assert joint["tracked"] == "Wu-Tang Clan", joint  # иначе release_key не узнал бы артиста
    assert store_checked({"kind": "release", "artist": "X", "tracked": "X"}, {})  # уже сверена сборщиком

    print("релиз: гости и сольники участников под чужим именем не проходят")

    # Свежесть и дубли — на синтетическом inbox, без сети; пост пишется во временную папку.
    import tempfile

    now = state.now()
    tonight = datetime.combine(now.date(), time(23, 59), tzinfo=timezone.utc)

    def found(fingerprint: str, title: str, released: datetime, score: int = 95,
              source: str = "itunes") -> dict:
        return {"kind": "release", "fingerprint": fingerprint, "score": score, "source": source,
                "artist": "Slipknot", "tracked": "Slipknot", "title": title,
                "released_at": state.iso(released)}

    inbox = [
        found("preorder", "The Black Parade (Deluxe Edition)", now + timedelta(days=42)),
        # Старше суток — ни РЕЛИЗА, ни ВЕРДИКТА: старые вердикты не нужны.
        found("old", "In My Lifetime", now - timedelta(hours=25)),
        found("single", "Arsenal - Single", now - timedelta(hours=20)),
        found("twin", "Arsenal", now - timedelta(hours=23), source="deezer"),
        # iTunes ставит выход на 07:00 UTC: сегодняшний сингл уже в магазине, он не будущий.
        found("today", "OUTLAST - Single", tonight, score=100),
    ]
    fresh = fresh_releases(inbox, set())
    assert [i["fingerprint"] for i in fresh] == ["today", "single"], fresh
    # Пост по «Arsenal - Single» уже написан — Deezer-двойник назад не вернётся.
    assert [i["fingerprint"] for i in fresh_releases(inbox, {"single"})] == ["today"]

    # Один пост на релиз: РЕЛИЗ или ВЕРДИКТ по весам, у вердикта — сторона.
    jobs = release_jobs(fresh * 20)
    assert len(jobs) == 40 and {rubric for _, rubric, _, _ in jobs} == set(config.RELEASE_RUBRICS), jobs
    assert all(p["stance"] in ("respect", "roast") for _, rubric, p, _ in jobs if rubric == "verdict")
    # Ночной plan о релизах не пишет вовсе — ни свежих, ни старых.
    assert not [rubric for _, rubric, _, _ in plan(config.QUEUE_TARGET) if rubric in config.RELEASE_RUBRICS]

    # История артиста — из того же inbox: последние 5 раньше релиза, от старых к новым.
    def before(fingerprint: str, title: str, days: int, artist: str = "Slipknot",
               source: str = "itunes", **extra: object) -> dict:
        return {"kind": "release", "fingerprint": fingerprint, "source": source, "artist": artist,
                "tracked": artist, "title": title, "track_count": 1,
                "released_at": state.iso(now - timedelta(days=days)), **extra}

    current = before("current", "Arsenal II - Single", 0)
    history = [
        before("psycho", "Psychosocial - Single", 70),
        before("duality", "Duality - Single", 60),
        before("snuff", "Snuff - Single", 50),
        before("unsainted", "Unsainted - Single", 40),
        before("wanyk", "We Are Not Your Kind", 30, source="deezer", track_count=None, tracks=[{}] * 14),
        before("yen", "Yen - Single", 20),
        before("yen-deezer", "Yen", 20, source="deezer"),  # тот же сингл во втором магазине
        before("bother", "Bother - Single", 10, artist="Stone Sour"),
        before("preorder", "Sic - Single", -30),
        before("twin", "Arsenal II", 0, source="deezer"),
        current,
    ]
    earlier = previous_releases(current, history, {})
    assert [r["title"] for r in earlier] == [
        "Duality - Single", "Snuff - Single", "Unsainted - Single", "We Are Not Your Kind", "Yen - Single",
    ], earlier
    assert earlier[3] == {"title": "We Are Not Your Kind", "track_count": 14,
                          "released_at": (now - timedelta(days=30)).date().isoformat()}, earlier
    assert _release_payload(current, history, {})["previous_releases"] == earlier
    assert "previous_releases" not in _release_payload(before("debut", "Debut", 0, artist="Nobody"), history, {})
    print("история: последние 5 раньше релиза, дубль магазина один раз, чужой артист и предзаказ мимо")

    with tempfile.TemporaryDirectory() as tmp:
        saved = state.read_json(save_post("release", "Текст.", inbox[2], folder=Path(tmp)), {})
    assert (saved["released_at"], saved["score"]) == (inbox[2]["released_at"], 95), saved

    print("релиз: предзаказ, старше суток и дубль магазина не пишутся, на релиз один пост")
    return 0


def do_dry_run(needed: int) -> int:
    jobs = plan(needed)
    print(f"\nВ очереди сейчас: {queue_size()}. Нужно добрать: {needed}.\n")
    if not jobs:
        print("Заданий нет — inbox пуст. Запусти `python -m src.collect`.")
        return 0
    for _, rubric_key, payload, _ in jobs:
        title = payload.get("subject") or payload.get("title") or payload.get("modern") or "—"
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
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="сразу написать посты о свежих релизах, без батча (с --dry-run — только показать)",
    )
    parser.add_argument(
        "--selftest", action="store_true",
        help="проверить подпись кнопки и исполнителя, свежесть и дубли релизов",
    )
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
    if args.fresh:
        return do_fresh(args.dry_run)
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
