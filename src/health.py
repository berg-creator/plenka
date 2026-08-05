"""Сторож: следит, чтобы канал не встал молча.

Проверяет три вещи — не опустела ли очередь, не зависла ли публикация,
не перестал ли поступать материал. Если что-то не так, пишет тебе в личку.
Без этого поломка обнаруживается только когда канал уже неделю молчит.
"""

from __future__ import annotations

import argparse
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
    else:
        issues.append("❗ Сбор ни разу не отработал: inbox отсутствует.")

    return issues


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
