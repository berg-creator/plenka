"""RSS музыкальных изданий — источник инфоповодов.

Список лент лежит в data/feeds.json. Некоторые издания меняют адреса лент,
поэтому есть команда проверки: `python -m src.sources.feeds --check`.
"""

from __future__ import annotations

import json
import re
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
                    "cover": _entry_image(entry),
                    "published_at": published.isoformat(),
                    "external_id": entry.get("id") or entry.get("link", ""),
                }
            )
    return items


# Дежурная картинка сайта вместо статьи: «Афиша» отдаёт в ленте share_img_v2.png,
# «Лента» на неартикульных страницах — свой lenta_og.png. Логотип издания под
# нашей новостью — не иллюстрация, а серая плитка, и текст без картинки честнее.
# ponytail: отбор по имени файла. Начнёт пропускать чужие заглушки — сверять размер.
GENERIC_IMAGE = ("logo", "default", "placeholder", "share_img", "share-img", "_og.", "/og-")


def _usable(picture: str) -> str:
    """Ссылка на картинку, если она похожа на иллюстрацию статьи, иначе пусто."""
    if not picture.startswith("http"):
        return ""
    return "" if any(mark in picture.lower() for mark in GENERIC_IMAGE) else picture


def _entry_image(entry) -> str:
    """Картинка записи, если лента её отдала.

    Новость без картинки уходит в канал голым текстом и в ленте теряется
    среди постов с обложками. Своей картинки у неё быть не может — рисовать
    иллюстрацию к чужой новости значит выдумывать, — поэтому берём ту,
    что издание приложило само, и ничего не подставляем, когда её нет.
    """
    for media in (entry.get("media_content") or []) + (entry.get("media_thumbnail") or []):
        if picture := _usable(str(media.get("url", "")).strip()):
            return picture
    for link in entry.get("links") or []:
        if str(link.get("type", "")).startswith("image/"):
            return _usable(str(link.get("href", "")).strip())
    return ""


# Картинка статьи в разметке страницы. og:image кладут все издания — по нему
# ссылку на новость показывают соцсети, и картинка там ровно та, которой
# издание эту новость проиллюстрировало.
OG_IMAGE = re.compile(
    r'<meta[^>]+(?:property|name)=["\']og:image["\'][^>]*content=["\']([^"\']+)["\']'
    r'|<meta[^>]+content=["\']([^"\']+)["\'][^>]*(?:property|name)=["\']og:image["\']',
    re.IGNORECASE,
)


def page_image(url: str) -> str:
    """Картинка новости со страницы издания — когда лента её не отдала.

    Формат картинки в RSS никто не соблюдает: «Интермедиа» кладёт её в свой
    `<image>` внутри записи, а feedparser такой тег не отдаёт вовсе — новость
    про Kai Angel 12.09.2026 вышла в канал голым текстом, и это повторялось.
    Разбирать чужие самодельные теги пришлось бы для каждой ленты отдельно,
    поэтому берём og:image: он есть у всех и означает то же самое.

    Своей картинки у новости быть не может — рисовать иллюстрацию к чужому
    событию значит выдумывать. Нет og:image — пост уходит текстом, как раньше.
    """
    if not url.startswith("http"):
        return ""
    response = get(url, min_interval=0.5)
    if response is None:
        return ""
    found = OG_IMAGE.search(response.text)
    if not found:
        return ""
    return _usable((found.group(1) or found.group(2) or "").strip())


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


def _selftest() -> None:
    """Картинка статьи: свой тег «Интермедиа» мимо, og:image и дежурный логотип."""
    import feedparser

    rss = (
        '<?xml version="1.0"?><rss version="2.0"><channel><title>t</title><item>'
        "<title>Kai Angel совместил в «Shh!» рэп и гитарную музыку</title>"
        "<link>https://www.intermedia.ru/news/406629</link><description>d</description>"
        "<pubDate>Sat, 12 Sep 2026 11:58:00 +0300</pubDate>"
        "<image><url>https://cdn1.intermedia.ru/img/406629.jpg</url></image>"
        "</item></channel></rss>"
    )
    entry = feedparser.parse(rss).entries[0]
    # Свой тег «Интермедиа» feedparser не отдаёт вовсе — отсюда новость про
    # Kai Angel и вышла 12.09.2026 голым текстом. Выручает page_image.
    assert _entry_image(entry) == "", _entry_image(entry)

    page = '<meta property="og:image" content="https://cdn1.intermedia.ru/img/406629.jpg">'
    assert OG_IMAGE.search(page).group(1).endswith("406629.jpg")
    assert OG_IMAGE.search("<meta content='https://x.ru/a.jpg' name='og:image'/>").group(2)
    assert not OG_IMAGE.search('<meta property="og:title" content="нет картинки">')

    assert _usable("https://www.intermedia.ru/img/news_x350/406629.jpg?t=1")
    # Логотип издания — не иллюстрация: «Афиша» и «Лента» отдают его дежурно.
    assert not _usable("https://daily.afisha.ru/static/share_img_v2.png")
    assert not _usable("https://icdn.lenta.ru/assets/webpack/images/lenta_og.873.png")
    assert not _usable("/img/relative.jpg")
    print("✓ картинка новости: свой тег мимо, og:image находится, логотип отсеян")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
        raise SystemExit(0)
    if "--check" in sys.argv:
        print("Проверяю RSS-ленты:\n")
        dead_count = check()
        print(f"\nНедоступных лент: {dead_count}")
        sys.exit(0)
    for item in fetch_recent():
        print(f"[{item['outlet']}] {item['title']}")
