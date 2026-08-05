"""YouTube через публичные RSS-ленты каналов — без API-ключа и без квот.

Официальный YouTube Data API даёт всего 10 000 единиц квоты в сутки и требует
проекта в Google Cloud. Лента вида feeds/videos.xml отдаёт последние 15 роликов
канала бесплатно и без регистрации — для отслеживания клипов этого достаточно.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import feedparser

from .http import get

FEED_URL = "https://www.youtube.com/feeds/videos.xml"
CHANNEL_ID_RE = re.compile(r'"(?:channelId|externalId)":"(UC[\w-]{22})"')


def find_channel_id(query: str) -> str | None:
    """Достаёт id канала со страницы результатов поиска.

    Хрупкий способ (зависит от разметки YouTube), поэтому используется
    единоразово при заполнении базы, а не в рабочем цикле.
    """
    response = get(
        "https://www.youtube.com/results",
        params={"search_query": f"{query} topic"},
        min_interval=2.0,
    )
    if response is None:
        return None
    match = CHANNEL_ID_RE.search(response.text)
    return match.group(1) if match else None


def recent_videos(channel_id: str, max_age_hours: int = 48) -> list[dict]:
    response = get(FEED_URL, params={"channel_id": channel_id}, min_interval=1.0)
    if response is None:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    parsed = feedparser.parse(response.content)

    videos = []
    for entry in parsed.entries:
        published = entry.get("published_parsed")
        if not published:
            continue
        moment = datetime(*published[:6], tzinfo=timezone.utc)
        if moment < cutoff:
            continue
        videos.append(
            {
                "source": "youtube",
                "artist": entry.get("author", ""),
                "title": (entry.get("title") or "").strip(),
                "url": entry.get("link", ""),
                "published_at": moment.isoformat(),
                "external_id": entry.get("yt_videoid") or entry.get("id", ""),
            }
        )
    return videos
