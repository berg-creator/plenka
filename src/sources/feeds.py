"""RSS музыкальных изданий — источник инфоповодов.

Список лент лежит в data/feeds.json. Некоторые издания меняют адреса лент,
поэтому есть команда проверки: `python -m src.sources.feeds --check`.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser

from .http import get

FEEDS_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "feeds.json"


def load_feeds() -> list[dict]:
    if not FEEDS_FILE.exists():
        return []
    payload = json.loads(FEEDS_FILE.read_text(encoding="utf-8"))
    return [f for f in payload.get("feeds", []) if f.get("enabled", True)]


def fetch_recent(max_age_hours: int = 30) -> list[dict]:
    """Свежие записи из всех включённых лент."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    items: list[dict] = []

    for feed in load_feeds():
        response = get(feed["url"], min_interval=1.0)
        if response is None:
            continue

        parsed = feedparser.parse(response.content)
        for entry in parsed.entries[:25]:
            published = _entry_date(entry)
            if published is None or published < cutoff:
                continue
            items.append(
                {
                    "source": "rss",
                    "outlet": feed.get("name", ""),
                    "lang": feed.get("lang", "en"),
                    "title": (entry.get("title") or "").strip(),
                    "url": entry.get("link", ""),
                    "summary": _clean(entry.get("summary", ""))[:600],
                    "published_at": published.isoformat(),
                    "external_id": entry.get("id") or entry.get("link", ""),
                }
            )
    return items


def _entry_date(entry) -> datetime | None:
    for field in ("published_parsed", "updated_parsed"):
        value = entry.get(field)
        if value:
            return datetime(*value[:6], tzinfo=timezone.utc)
    return None


def _clean(html: str) -> str:
    """Грубая чистка HTML — для контекста LLM разметка не нужна."""
    text: list[str] = []
    inside_tag = False
    for char in html:
        if char == "<":
            inside_tag = True
        elif char == ">":
            inside_tag = False
        elif not inside_tag:
            text.append(char)
    return " ".join("".join(text).split())


def check() -> int:
    """Проверяет, что ленты живы и отдают записи. Возвращает число мёртвых."""
    dead = 0
    for feed in json.loads(FEEDS_FILE.read_text(encoding="utf-8")).get("feeds", []):
        response = get(feed["url"], min_interval=0.5)
        if response is None:
            print(f"  ✗ {feed['name']:<22} недоступна — {feed['url']}")
            dead += 1
            continue
        parsed = feedparser.parse(response.content)
        count = len(parsed.entries)
        if count == 0:
            print(f"  ✗ {feed['name']:<22} пустая лента — {feed['url']}")
            dead += 1
        else:
            print(f"  ✓ {feed['name']:<22} {count} записей")
    return dead


if __name__ == "__main__":
    if "--check" in sys.argv:
        print("Проверяю RSS-ленты:\n")
        dead_count = check()
        print(f"\nНедоступных лент: {dead_count}")
        sys.exit(0)
    for item in fetch_recent():
        print(f"[{item['outlet']}] {item['title']}")
