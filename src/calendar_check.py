"""Проверка годовщин: если сегодня памятная дата — готовит пост рубрики ЛЕГЕНДА.

Такой пост нельзя отложить в общую очередь на неделю вперёд: он привязан к дню.
Поэтому генерируется синхронно и встаёт в начало очереди.

    python -m src.calendar_check --dry-run   посмотреть, что сегодня за дата
    python -m src.calendar_check             сгенерировать пост, если дата есть
"""

from __future__ import annotations

import argparse

from . import compose, config, llm, state

# Постим только круглые и близкие к круглым годовщины, иначе рубрика приедается.
def is_notable(years: int) -> bool:
    if years <= 0:
        return False
    return years % 5 == 0 or years in (1, 2, 3)


def today_events() -> list[dict]:
    payload = state.read_json(config.CALENDAR_FILE, {"events": []})
    today = state.now().strftime("%m-%d")
    year = state.now().year

    events = []
    for event in payload.get("events", []):
        if event.get("date") != today:
            continue
        years = year - int(event.get("year", year))
        if not is_notable(years):
            continue
        events.append({**event, "years_ago": years})
    return events


def main() -> int:
    parser = argparse.ArgumentParser(description="Годовщины и памятные даты")
    parser.add_argument("--dry-run", action="store_true", help="только показать")
    parser.add_argument("--any-year", action="store_true", help="не требовать круглой даты")
    args = parser.parse_args()

    config.load_dotenv()

    if args.any_year:
        payload = state.read_json(config.CALENDAR_FILE, {"events": []})
        today = state.now().strftime("%m-%d")
        events = [
            {**e, "years_ago": state.now().year - int(e.get("year", 0))}
            for e in payload.get("events", [])
            if e.get("date") == today
        ]
    else:
        events = today_events()

    if not events:
        print("Сегодня памятных дат нет.")
        return 0

    for event in events:
        label = {"death": "годовщина смерти", "birth": "день рождения", "album": "выход альбома"}
        print(f"Сегодня: {event['name']} — {label.get(event['event'], event['event'])}, "
              f"{event['years_ago']} лет назад")

        if args.dry_run:
            continue

        result = llm.generate_now("legend", event)
        if result["skip"] or not result["text"]:
            print(f"  модель отказалась: {result.get('reason', '')}")
            continue

        path = compose.save_post("legend", result["text"], {})
        # Дата привязана к сегодняшнему дню — пост должен выйти первым.
        priority = path.with_name("0000-" + path.name)
        path.rename(priority)
        print(f"  пост готов: {priority.name}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
