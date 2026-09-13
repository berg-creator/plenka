"""Сторож: следит, чтобы канал не встал молча.

Проверяет пять вещей — не опустела ли очередь, не зависла ли публикация,
не перестал ли поступать материал, не иссякли ли входящие новости
и не падали ли запуски воркфлоу за сутки.
Если что-то не так, пишет тебе в личку. Без этого поломка обнаруживается
только когда канал уже неделю молчит.
"""

from __future__ import annotations

import argparse
import os
from datetime import timedelta

from . import config, state, telegram


def problems() -> list[str]:
    issues: list[str] = []

    queue = len(list(config.QUEUE.glob("*.json")))
    if queue == 0:
        issues.append("❗ Очередь пуста — публиковать нечего.")
    elif queue < config.QUEUE_MIN:
        issues.append(f"⚠️ В очереди осталось {queue} постов — скоро кончатся.")

    posted = state.read_json(config.POSTED_FILE, {"items": []}).get("items", [])
    if posted:
        last = state._parse(posted[-1].get("published_at", ""))
        if last and state.now() - last > timedelta(hours=config.PUBLISH_INTERVAL_HOURS * 3):
            hours = int((state.now() - last).total_seconds() // 3600)
            issues.append(f"⚠️ Последняя публикация была {hours} ч назад — похоже, публикация встала.")

    if config.INBOX_FILE.exists():
        inbox = list(state.read_jsonl(config.INBOX_FILE))
        fresh = [
            i
            for i in inbox
            if (parsed := state._parse(i.get("collected_at", ""))) is not None
            and state.now() - parsed < timedelta(days=2)
        ]
        if not fresh:
            issues.append("⚠️ За двое суток не нашлось ни одной новинки — проверь источники.")

        # Срочные новости живут только на inbox: встанет сбор — рубрика замолчит,
        # а очередь ещё неделю будет делать вид, что канал в порядке. Сбор ходит
        # раз в 6 часов, поэтому два пустых прогона подряд — уже не совпадение.
        news = [
            i
            for i in inbox
            if i.get("kind") == "news"
            and (parsed := state._parse(i.get("collected_at", ""))) is not None
            and state.now() - parsed < timedelta(hours=12)
        ]
        if not news:
            issues.append("⚠️ Новостей не приходило 12 часов — сбор встал или ленты умерли.")
    else:
        issues.append("❗ Сбор ни разу не отработал: inbox отсутствует.")

    if failed := failed_runs():
        issues.append("⚠️ Упали запуски за сутки: " + ", ".join(failed))

    return issues


def failed_runs() -> list[str]:
    """Красные запуски воркфлоу за сутки: «Бот ×2 (ссылка)».

    Файлы состояния упавший запуск не трогает, поэтому проверки выше его не видят:
    12.09.2026 смена бота падала на каждом посте о релизе, а очередь и публикация
    выглядели здоровыми. Разбор выдумок пропускаем — о своей поломке он пишет сам.
    Без GITHUB_REPOSITORY (локальный запуск) проверка молча пропускается.
    """
    import requests

    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        return []
    token = os.environ.get("GITHUB_TOKEN")
    since = (state.now() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        response = requests.get(
            f"https://api.github.com/repos/{repo}/actions/runs",
            params={"status": "failure", "created": f">={since}", "per_page": 100},
            headers={"Authorization": f"Bearer {token}"} if token else {},
            timeout=30,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        return [f"не узнать у GitHub ({exc})"]
    runs: dict[str, list[str]] = {}
    for run in response.json().get("workflow_runs", []):
        if not run.get("path", "").endswith("review.yml"):
            runs.setdefault(run["name"], []).append(run["html_url"])
    return [f"{name} ×{len(urls)} ({urls[0]})" for name, urls in runs.items()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка состояния канала")
    parser.add_argument("--quiet", action="store_true", help="молчать, если всё в порядке")
    args = parser.parse_args()

    config.load_dotenv()
    issues = problems()

    queue = len(list(config.QUEUE.glob("*.json")))
    posted = state.read_json(config.POSTED_FILE, {"items": []}).get("items", [])

    if not issues:
        summary = f"✅ Всё работает. В очереди: {queue}. Опубликовано всего: {len(posted)}."
        print(summary)
        if not args.quiet:
            telegram.send_message(config.secret("TELEGRAM_ADMIN_ID"), summary)
        return 0

    report = "<b>ПЛЁНКА — состояние</b>\n\n" + "\n".join(issues)
    report += f"\n\nВ очереди: {queue}. Опубликовано всего: {len(posted)}."
    print(report)
    telegram.send_message(config.secret("TELEGRAM_ADMIN_ID"), report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
