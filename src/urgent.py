"""Срочные новости: пост выходит в день события, минуя очередь.

Обычная очередь пишется на неделю вперёд, и новость в ней протухает раньше,
чем доходит до канала: «умер такой-то» через шесть дней читается странно.
Поэтому инфоповоды вынуты из очереди совсем (вес рубрики в config.RUBRICS —
ноль) и живут здесь: запуск берёт свежее из inbox, пишет пост и сразу
публикует его — задержка и есть то, ради чего рубрика вынута отдельно.

Модерацию убрали намеренно: владелец всё равно отвечал на кнопки «в канал»,
а каждый час ожидания стоит новости половины ценности. Ошибку в канале
чинит удаление поста, пропущенный инфоповод не чинится ничем.
Владельцу уходит уведомление в личку — уже после публикации, чтобы он знал,
что вышло, и мог снять руками.

Готовые посты пишутся в content/urgent/, а не в очередь: попади они туда,
публикатор выдал бы их в ленту сам, уже несвежими. Опубликованное уезжает
в архив тем же путём, что и посты очереди; sweep() подчищает то, что осталось
лежать при выключенном автопилоте.

    python -m src.urgent --dry-run             что нашлось, без затрат
    python -m src.urgent                       написать и опубликовать в канал
    python -m src.urgent --target admin        то же, но себе в личку с кнопками
    python -m src.urgent -n 5                  взять за раз больше новостей
"""

from __future__ import annotations

import argparse
import logging
import os
from datetime import timedelta

from . import compose, config, publish, state, telegram

log = logging.getLogger("urgent")


def fresh_news(max_age_hours: int) -> list[dict]:
    """Неиспользованные новости из inbox, вышедшие достаточно недавно.

    Сбор идёт каждые 6 часов и складывает в inbox всё подряд, включая старое
    из медленных лент. Срочной новость считается только пока она новость.
    """
    cutoff = state.now() - timedelta(hours=max_age_hours)
    items = []
    for item in compose.load_inbox_unused():
        if item.get("kind") != "news":
            continue
        published = state._parse(item.get("released_at") or "")
        if published is None or published < cutoff:
            continue
        items.append(item)
    return items


def sweep() -> int:
    """Убирает срочные посты, по которым так и не приняли решение.

    Возраст берём из самого поста, а не из времени файла: в GitHub Actions
    репозиторий каждый раз выкачивается заново, и mtime у всех файлов —
    момент checkout.
    """
    if not config.URGENT.exists():
        return 0
    cutoff = state.now() - timedelta(hours=config.URGENT_TTL_HOURS)
    removed = 0
    for path in sorted(config.URGENT.glob("*.json")):
        created = state._parse(state.read_json(path, {}).get("created_at", ""))
        if created is None or created < cutoff:
            path.unlink()
            removed += 1
    return removed


def run(limit: int, dry_run: bool, target: str) -> int:
    # Свежесть решает: сначала самые новые, а уже потом те, что интереснее
    # по нашим меткам. Иначе горячая новость без знакомых имён проигрывает
    # вчерашней про артиста из списка слежения.
    news = sorted(
        fresh_news(config.URGENT_MAX_AGE_HOURS),
        key=lambda i: i.get("released_at") or "",
        reverse=True,
    )[:limit]
    if not news:
        print("Свежих новостей нет — inbox пуст или всё уже разобрано.")
        return 0

    if dry_run:
        for item in news:
            print(f"  [{item.get('score', 0):>3}] {item.get('outlet', '')}: "
                  f"{item.get('title', '')[:70]}")
        print(f"\nВышло бы в канал: {len(news)}. Модель не вызывалась.")
        return 0

    chat = config.secret("TELEGRAM_CHANNEL_ID" if target == "channel" else "TELEGRAM_ADMIN_ID")
    sent, used, titles = 0, [], []

    for item in news:
        result = compose.generate_checked("news", compose._news_payload(item))

        if result["skip"] or not result["text"]:
            # Отвергнутая моделью новость завтра свежее не станет — забираем
            # материал из inbox, чтобы не платить за неё второй раз.
            used.append(item["fingerprint"])
            print(f"  — пропущено ({result.get('reason', '')}): {item.get('title', '')[:50]}")
            continue

        path = compose.save_post("news", result["text"], item, folder=config.URGENT)
        post = state.read_json(path, {})

        if target == "admin":
            publish.send_for_approval(post, path, chat, label="🔴 СРОЧНАЯ НОВОСТЬ")
        else:
            publish.send(post, chat)
            publish.crosspost_vk(post)
            publish.record(post, path, target)
            publish.archive(path)

        # Отпечаток гасим только после удачной отправки: упавшая сеть не должна
        # съедать инфоповод молча — на следующем запуске он ещё будет свежим.
        used.append(item["fingerprint"])
        titles.append(item.get("title", "")[:70])
        sent += 1
        print(f"  ✓ {path.name}: {item.get('title', '')[:50]}")

    compose.mark_used(used)

    # Личка — канал связи, а не пульт: сообщаем уже о случившемся, одним
    # сообщением на запуск, чтобы владелец видел ленту канала не постфактум.
    if sent and target == "channel":
        try:
            telegram.send_message(
                config.secret("TELEGRAM_ADMIN_ID"),
                "🔴 <b>СРОЧНОЕ УШЛО В КАНАЛ</b>\n\n"
                + "\n".join(f"· {t}" for t in titles)
                + "\n\n<i>снять — руками в канале</i>",
            )
        except Exception as exc:  # noqa: BLE001 — пост уже вышел, отчёт не критичен
            log.warning("Уведомление владельцу не ушло: %s", exc)

    print(f"\nОпубликовано: {sent}.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Срочные новости в день события")
    parser.add_argument("--dry-run", action="store_true", help="показать находки без затрат")
    parser.add_argument(
        "--target",
        choices=["admin", "channel"],
        default=os.environ.get("PUBLISH_TARGET", "channel"),
        help="куда: channel — сразу в канал (по умолчанию), admin — себе в личку с кнопками",
    )
    parser.add_argument(
        "-n",
        type=int,
        default=config.URGENT_PER_RUN,
        metavar="N",
        help=f"сколько новостей взять за раз (по умолчанию {config.URGENT_PER_RUN})",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    config.load_dotenv()

    # В сухом прогоне не удаляем ничего: он на то и сухой.
    expired = 0 if args.dry_run else sweep()
    if expired:
        print(f"Протухло и убрано: {expired}.")

    return run(args.n, args.dry_run, args.target)


if __name__ == "__main__":
    raise SystemExit(main())
