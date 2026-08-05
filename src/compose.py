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
from pathlib import Path

from . import config, llm, state

log = logging.getLogger("compose")

BATCH_FILE = config.DATA / "pending_batch.json"
USED_FILE = config.DATA / "used_inbox.json"


# ─────────────────────────── очередь ───────────────────────────


def queue_size() -> int:
    return len(list(config.QUEUE.glob("*.json")))


def save_post(rubric_key: str, text: str, source: dict | None = None) -> Path:
    """Кладёт готовый пост в очередь. Имя файла задаёт порядок публикации."""
    config.QUEUE.mkdir(parents=True, exist_ok=True)
    stamp = state.now().strftime("%Y%m%d-%H%M%S")
    suffix = random.randint(1000, 9999)
    path = config.QUEUE / f"{stamp}-{suffix}-{rubric_key}.json"

    state.write_json(
        path,
        {
            "rubric": rubric_key,
            "text": text,
            "created_at": state.iso(),
            "source_url": (source or {}).get("url", ""),
            "cover": (source or {}).get("cover", ""),
            "artist": (source or {}).get("artist", ""),
        },
    )
    return path


# ─────────────────────────── планирование ───────────────────────────


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

    # Доли рубрик в пачке — из весов в config.RUBRICS.
    weights = {r.key: r.weight for r in config.RUBRICS if r.key != "legend"}
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

    # МЕМ — контекст из базы артистов, чтобы шутки были про нашу сцену.
    for _ in range(quota.get("meme", 0)):
        sample = random.sample(artists, min(12, len(artists)))
        add("meme", {"scene": [a["name"] for a in sample]}, {})

    # ОПРОС — тоже из базы артистов.
    for _ in range(quota.get("poll", 0)):
        sample = random.sample(artists, min(10, len(artists)))
        add("poll", {"artists": [a["name"] for a in sample]}, {})

    return jobs[:needed]


def _release_payload(item: dict) -> dict:
    return {
        "artist": item.get("artist", ""),
        "title": item.get("title", ""),
        "track_count": item.get("track_count"),
        "released_at": item.get("released_at", ""),
        "url": item.get("url", ""),
        "tags": item.get("tags", []),
        "tier": item.get("tier", ""),
    }


def _news_payload(item: dict) -> dict:
    return {
        "title": item.get("title", ""),
        "summary": item.get("summary", ""),
        "outlet": item.get("outlet", ""),
        "lang": item.get("lang", "en"),
        "url": item.get("url", ""),
        "artists": item.get("artists", []),
    }


# ─────────────────────────── режимы работы ───────────────────────────


def do_submit(needed: int) -> int:
    if BATCH_FILE.exists():
        pending = state.read_json(BATCH_FILE, {})
        print(f"Батч {pending.get('batch_id')} ещё не забран. Сначала выполни --fetch.")
        return 1

    jobs = plan(needed)
    if not jobs:
        print("Нечего генерировать: inbox пуст. Сначала запусти сбор.")
        return 0

    batch_id = llm.submit_batch([(cid, key, payload) for cid, key, payload, _ in jobs])
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

        save_post(job["rubric"], result["text"], source)
        if source.get("subtext_index") is not None:
            subtext_done.append(source["subtext_index"])
        created += 1

    mark_used(used)
    mark_subtext_used(subtext_done)
    BATCH_FILE.unlink()
    print(f"Создано постов: {created}. Отклонено моделью: {skipped}. В очереди: {queue_size()}.")
    return 0


def do_now(count: int) -> int:
    jobs = plan(count)
    if not jobs:
        print("Нечего генерировать: inbox пуст.")
        return 0

    created, used, subtext_done = 0, [], []
    for custom_id, rubric_key, payload, source in jobs:
        result = llm.generate_now(rubric_key, payload)
        if source.get("fingerprint"):
            used.append(source["fingerprint"])
        if result["skip"] or not result["text"]:
            print(f"  — {rubric_key}: пропущено ({result.get('reason', '')})")
            continue
        path = save_post(rubric_key, result["text"], source)
        if source.get("subtext_index") is not None:
            subtext_done.append(source["subtext_index"])
        created += 1
        print(f"  ✓ {rubric_key}: {path.name}")

    mark_used(used)
    mark_subtext_used(subtext_done)
    print(f"\nСоздано постов: {created}. В очереди: {queue_size()}.")
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
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    config.load_dotenv()

    needed = max(0, config.QUEUE_TARGET - queue_size())

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
