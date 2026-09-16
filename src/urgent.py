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
    python -m src.urgent -n 5                  опубликовать за раз больше новостей
    python -m src.urgent --selftest            порядок срочного и замена отброшенной — без сети
"""

from __future__ import annotations

import argparse
import logging
import os
from datetime import timedelta

from . import compose, config, publish, state, telegram
from .sources import deezer

log = logging.getLogger("urgent")


def fresh_news(max_age_hours: int) -> list[dict]:
    """Неиспользованные новости из inbox, вышедшие достаточно недавно.

    Сбор идёт каждые 6 часов и складывает в inbox всё подряд, включая старое
    из медленных лент. Срочной новость считается только пока она новость.

    Новость издания о релизе, который канал сам нашёл в магазине, — не срочная:
    о нём выходит свой пост, и эта новость стоит в нём цитатой
    (compose.outside_voice). Отдельно она повторила бы пост о релизе.
    Отпечатки у них разные (release против news), seen.json такое не ловит.
    """
    cutoff = state.now() - timedelta(hours=max_age_hours)
    rows = list(state.read_jsonl(config.INBOX_FILE))
    releases = [r for r in rows if r.get("kind") == "release"]
    artists = {a["name"]: a for a in state.read_json(config.ARTISTS_FILE, {"artists": []})["artists"]}
    items = []
    for item in compose.load_inbox_unused():
        if item.get("kind") != "news":
            continue
        published = state._parse(item.get("released_at") or "")
        if published is None or published < cutoff:
            continue
        if any(compose.press_row(r, [item], artists) for r in releases):
            log.info("Новость о релизе из сбора, пойдёт цитатой в его пост: %s", item.get("title", "")[:60])
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


def with_portrait(item: dict) -> dict:
    """Новость с портретом первого названного артиста, у которого он есть.

    Без картинки срочная новость уходила голым текстом и терялась в ленте
    среди постов с обложками. Портрет ищется так же, как у разборов бота:
    только точное имя из базы и только настоящее фото. Лицо постороннего
    под новостью хуже, чем новость без лица, поэтому не нашли никого —
    пост уходит текстом, как раньше.
    """
    for name in item.get("artists") or []:
        try:
            picture = deezer.artist_picture(name)
        except Exception as exc:  # noqa: BLE001 — без портрета новость всё равно выйдет
            log.info("Портрет «%s» не нашёлся: %s", name, exc)
            continue
        if picture:
            return {**item, "cover": picture, "artist": name}
    return item


def priority(item: dict) -> tuple:
    """Порядок срочного: сниппет, потом новость о своём артисте, потом русская
    сцена из Telegram-каналов изданий, потом остальное; внутри — свежее раньше.

    Одна свежесть отдавала места западной эстраде: 11–13.09.2026 в канал ушли
    Slipknot, Mastodon и Turnstile, а сниппет ICEGERGERT трижды проиграл новостям
    посвежее (Charli XCX, Lady Gaga) и протух. Русские RSS (Интермедиа) — это
    эстрада, модель их отбрасывает, поэтому сцена здесь — именно Telegram.

    Но и одна Telegram-лента вперёд всех хоронила западную сцену целиком:
    13–15.09.2026 вышли «Королевский XVII выпустил трек» и ещё четыре новости
    без знакомого имени (score 30), а «Chief Keef перенёс концерт в Чикаго» (100)
    и артисты в GTA 6 (90) не дошли до модели ни разу. Score от 90 — в новости
    назван артист ядра, русской сцены или сцены (collect.TIER_SCORE + 10);
    легенды вроде Slipknot (80) остаются за Telegram.
    """
    return (bool(item.get("snippet")), item.get("score", 0) >= 90,
            item.get("source") == "telegram", item.get("released_at") or "")


def due(runs: list[dict]) -> bool:
    """Пора ли срочному заходу: час из config.URGENT_HOURS_MSK прошёл,
    а запуска urgent.yml после него нет.

    Отменённый запуск не в счёт — его вытеснил из очереди state-write другой.
    Упавший в счёт: повтор каждые 10 минут жёг бы генерацию на той же поломке,
    а о красном запуске и так скажет health.
    """
    from .compose import MSK

    now = state.now().astimezone(MSK)
    hours = [hour for hour in config.URGENT_HOURS_MSK if hour <= now.hour]
    if not hours:
        return False
    slot = now.replace(hour=hours[-1], minute=0, second=0, microsecond=0)
    return not any(
        run.get("conclusion") != "cancelled"
        and (created := state._parse(run.get("created_at", ""))) and created >= slot
        for run in runs
    )


def shift() -> None:
    """Срочный заход — из дежурства, а не по крону (см. config.URGENT_HOURS_MSK).

    Дежурство идёт почти без дыр, поэтому оно раз в 10 минут спрашивает GitHub
    о последних запусках urgent.yml и, когда пора, запускает его через
    workflow_dispatch — как сборку ролика (reels.start_build). Сам заход
    в дежурстве не идёт: обход лент и генерация занимают минут восемь,
    и всё это время бот молчал бы. Локально, без GITHUB_TOKEN, ничего не делает.
    """
    import requests

    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not (token and repo):
        return
    api = f"https://api.github.com/repos/{repo}/actions/workflows/urgent.yml"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    try:
        response = requests.get(f"{api}/runs", params={"per_page": 5}, headers=headers, timeout=30)
        response.raise_for_status()
        if not due(response.json().get("workflow_runs", [])):
            return
        requests.post(f"{api}/dispatches", headers=headers, timeout=30,
                      json={"ref": os.environ.get("GITHUB_REF_NAME", "main")}).raise_for_status()
    except requests.RequestException as exc:
        # Смену не роняем: следующий заход через 10 минут попробует снова.
        log.error("Срочный заход не запущен: %s", exc)
        return
    print("Срочный заход: urgent.yml запущен")


def run(limit: int, dry_run: bool, target: str) -> int:
    # Отброшенная моделью новость места не занимает: берём следующую, пока
    # не выйдет limit постов. Попыток втрое больше — столько запуск и тратил,
    # когда брал три новости сразу.
    news = sorted(fresh_news(config.URGENT_MAX_AGE_HOURS), key=priority, reverse=True)[:limit * 3]
    if not news:
        print("Свежих новостей нет — inbox пуст или всё уже разобрано.")
        return 0

    if dry_run:
        for item in news:
            print(f"  [{item.get('score', 0):>3}] {item.get('outlet', '')}: "
                  f"{item.get('title', '')[:70]}")
        print(f"\nВышло бы в канал: до {limit}, по порядку, пока модель не возьмёт. Модель не вызывалась.")
        return 0

    chat = config.secret("TELEGRAM_CHANNEL_ID" if target == "channel" else "TELEGRAM_ADMIN_ID")
    sent, used, titles = 0, [], []

    for item in news:
        if sent >= limit:
            break
        result = compose.generate_checked("news", compose._news_payload(item))

        if result["skip"] or not result["text"]:
            # Отвергнутая моделью новость завтра свежее не станет — забираем
            # материал из inbox, чтобы не платить за неё второй раз.
            used.append(item["fingerprint"])
            print(f"  — пропущено ({result.get('reason', '')}): {item.get('title', '')[:50]}")
            continue

        path = compose.save_post("news", result["text"], with_portrait(item), folder=config.URGENT)
        post = state.read_json(path, {})

        if target == "admin":
            publish.send_for_approval(post, path, chat, label="🔴 СРОЧНАЯ НОВОСТЬ")
        else:
            publish.to_channel(post, path, chat)

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


def _selftest() -> int:
    """Сниппет и сцена раньше свежей западной новости; отброшенная моделью
    уступает место следующей, и выходит ровно limit постов."""
    from pathlib import Path
    from unittest import mock

    items = [
        {"fingerprint": "west", "source": "rss", "released_at": "2026-09-12T19:00", "score": 80},
        {"fingerprint": "scene", "source": "telegram", "released_at": "2026-09-12T10:00", "score": 30},
        {"fingerprint": "snippet", "source": "telegram", "snippet": True, "released_at": "2026-09-11T21:00"},
        {"fingerprint": "west-old", "source": "rss", "released_at": "2026-09-12T08:00"},
        {"fingerprint": "keef", "source": "rss", "released_at": "2026-09-11T08:00", "score": 100},
    ]
    assert [i["fingerprint"] for i in sorted(items, key=priority, reverse=True)] == \
        ["snippet", "keef", "scene", "west", "west-old"]
    items.pop()

    # Заход: утренний час прошёл, а запуска после него нет — пора; отменённый не в счёт.
    from datetime import datetime, timezone
    with mock.patch.object(state, "now", lambda: datetime(2026, 9, 16, 9, 5, tzinfo=timezone.utc)):  # 12:05 МСК
        assert due([]) and due([{"created_at": "2026-09-16T08:00:00Z", "conclusion": "cancelled"}])
        assert not due([{"created_at": "2026-09-16T06:10:00Z", "conclusion": None}])
        assert due([{"created_at": "2026-09-16T05:59:00Z", "conclusion": "success"}])
    with mock.patch.object(state, "now", lambda: datetime(2026, 9, 16, 5, 0, tzinfo=timezone.utc)):  # 08:00 МСК
        assert not due([])

    asked, used = [], []
    def generate(rubric: str, payload: dict) -> dict:
        asked.append(payload["fingerprint"])
        return {"skip": payload["fingerprint"] == "snippet", "text": "Текст.", "reason": "мимо"}

    with (mock.patch.object(config, "secret", lambda name: "0"),
          mock.patch.object(compose, "generate_checked", generate),
          mock.patch.object(compose, "_news_payload", lambda item: item),
          mock.patch.object(compose, "save_post", lambda *a, **k: Path("post.json")),
          mock.patch.object(compose, "mark_used", used.extend),
          mock.patch.object(state, "read_json", lambda path, default: {}),
          mock.patch.object(publish, "send_for_approval", lambda *a, **k: None),
          # globals(), а не «src.urgent»: под -m модуль живёт как __main__.
          mock.patch.dict(globals(), {"fresh_news": lambda hours: items, "with_portrait": lambda item: item})):
        run(1, False, "admin")
    assert asked == ["snippet", "scene"] and used == ["snippet", "scene"], (asked, used)
    print("срочное: сниппет, свой артист и сцена первыми, отброшенная уступает место, заход по часам")
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
        help=f"сколько новостей опубликовать за раз (по умолчанию {config.URGENT_PER_RUN})",
    )
    parser.add_argument("--selftest", action="store_true", help="порядок срочного и замена отброшенной — без сети")
    args = parser.parse_args()
    if args.selftest:
        return _selftest()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    config.load_dotenv()

    # В сухом прогоне не удаляем ничего: он на то и сухой.
    expired = 0 if args.dry_run else sweep()
    if expired:
        print(f"Протухло и убрано: {expired}.")

    return run(args.n, args.dry_run, args.target)


if __name__ == "__main__":
    raise SystemExit(main())
