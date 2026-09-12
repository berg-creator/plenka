"""Публичные Telegram-каналы изданий — источник инфоповодов русской сцены.

RSS по русскому рэпу вымер: The Flow, Rap.ru, SRSLY и Hip-Hop.ru ленту
не отдают ни по одному адресу (причины проставлены в data/feeds.json),
а новости публикуют в своих Telegram-каналах. Читаем веб-превью
`t.me/s/<канал>` — обычную страницу, которую Telegram отдаёт всем без
авторизации ради поисковиков, — и разбираем регулярками: разметка превью
проще, чем повод тащить шестую зависимость в requirements.txt.

Отвергнуто: Bot API чужие каналы не читает вовсе, а ВКонтакте требует
личный токен — ключ сообщества отвечает на чужую стену ошибкой 27,
а личный ВК выдаёт руками, и он протухает.

Записи возвращаются в том же виде, что и у `feeds.fetch_recent`, поэтому
`collect.collect_news` разбирает их теми же фильтрами.

    python -m src.sources.telegram_web --check   какие каналы живы
"""

from __future__ import annotations

import html
import json
import re
import sys
from datetime import datetime, timedelta, timezone

from .feeds import FEEDS_FILE
from .http import get

PREVIEW = "https://t.me/s/{channel}"

# Превью отдаёт последние ~20 постов одной страницей: сообщение открывается
# data-post="канал/номер", а дальше внутри лежат текст, время и фото.
MESSAGE_SPLIT = 'class="tgme_widget_message_wrap'
POST_RE = re.compile(r'data-post="([^"]+)"')
# Вложенных div в тексте поста Telegram не делает — закрывающий тег первый же.
TEXT_RE = re.compile(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', re.DOTALL)
TIME_RE = re.compile(r'<time datetime="([^"]+)"')
PHOTO_RE = re.compile(r"background-image:url\('([^']+)'\)")
# Издания выносят суть поста в первый жирный абзац — он и работает заголовком.
BOLD_RE = re.compile(r"<b>(.*?)</b>", re.DOTALL)
BREAK_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")


def load_channels() -> list[dict]:
    if not FEEDS_FILE.exists():
        return []
    payload = json.loads(FEEDS_FILE.read_text(encoding="utf-8"))
    return [c for c in payload.get("telegram", []) if c.get("enabled", True)]


def fetch_recent(max_age_hours: int = 30) -> list[dict]:
    """Свежие посты всех включённых каналов."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    items: list[dict] = []

    for channel in load_channels():
        response = get(PREVIEW.format(channel=channel["channel"]), min_interval=1.0)
        if response is None:
            continue
        for post in parse(response.text, channel.get("name", "")):
            if post["_published"] >= cutoff:
                items.append({k: v for k, v in post.items() if k != "_published"})
    return items


def parse(page: str, outlet: str) -> list[dict]:
    """Разбирает страницу превью в записи того же вида, что отдаёт RSS."""
    posts: list[dict] = []

    for block in page.split(MESSAGE_SPLIT)[1:]:
        post_id = POST_RE.search(block)
        text = TEXT_RE.search(block)
        stamp = TIME_RE.search(block)
        if not (post_id and text and stamp):
            continue  # служебный блок: без текста, даты или номера поста

        body = _clean(text.group(1))
        if len(body) < 40:
            continue  # подписи вроде «Реклама» и голые ссылки инфоповодом не считаем

        bold = BOLD_RE.search(text.group(1))
        title = _clean(bold.group(1)) if bold else ""
        # Издания начинают пост жирной плашкой-эмодзи («💿», «🚀») — это не заголовок.
        if len(title) < 15:
            title = body.split(". ")[0]
        photo = PHOTO_RE.search(block)

        posts.append(
            {
                "source": "telegram",
                "outlet": outlet,
                "lang": "ru",
                "title": title[:200],
                "url": f"https://t.me/{post_id.group(1)}",
                "summary": body[:600],
                "cover": photo.group(1) if photo else "",
                "published_at": stamp.group(1),
                "external_id": f"tg:{post_id.group(1)}",
                "_published": datetime.fromisoformat(stamp.group(1)),
            }
        )
    return posts


def _clean(fragment: str) -> str:
    """Разметка превью — в простой текст: переносы строк моделью не читаются."""
    return " ".join(html.unescape(TAG_RE.sub("", BREAK_RE.sub(" ", fragment))).split())


def check() -> int:
    """Проверяет, что каналы живы и отдают посты. Возвращает число мёртвых."""
    dead = 0
    for channel in json.loads(FEEDS_FILE.read_text(encoding="utf-8")).get("telegram", []):
        mark = " " if channel.get("enabled", True) else "×"
        response = get(PREVIEW.format(channel=channel["channel"]), min_interval=0.5)
        posts = parse(response.text, channel.get("name", "")) if response else []
        if not posts:
            print(f" {mark}✗ {channel['name']:<22} постов не отдаёт — @{channel['channel']}")
            dead += 1
        else:
            last = max(p["published_at"] for p in posts)
            print(f" {mark}✓ {channel['name']:<22} {len(posts):>2} постов, последний {last[:16]}")
    return dead


def _selftest() -> None:
    page = (
        'class="tgme_widget_message_wrap"><div data-post="rapruchannel/1">'
        '<a class="tgme_widget_message_photo_wrap" style="background-image:url('
        "'https://cdn.telesco.pe/x.jpg')\"></a>"
        '<div class="tgme_widget_message_text js-message_text" dir="auto">'
        "<b>Артист выпустил альбом</b><br/><br/>Пластинка вышла ночью &laquo;без анонса&raquo;,"
        " и это первый его релиз за три года.</div>"
        '<time datetime="2026-09-12T07:46:23+00:00" class="time">07:46</time>'
        'class="tgme_widget_message_wrap"><div data-post="rapruchannel/2">'
        '<div class="tgme_widget_message_text">Реклама</div>'
        '<time datetime="2026-09-12T08:00:00+00:00" class="time">08:00</time>'
        'class="tgme_widget_message_wrap"><div data-post="rapruchannel/3">'
        '<div class="tgme_widget_message_text"><b>💿</b><br/>Артист объявил дату выхода'
        " пластинки. Первый альбом за три года.</div>"
        '<time datetime="2026-09-12T09:00:00+00:00" class="time">09:00</time>'
    )
    posts = parse(page, "RAP.RU")
    assert len(posts) == 2, f"разобрались не все посты: {posts}"
    assert posts[1]["title"].startswith("💿 Артист"), posts[1]["title"]
    post = posts[0]
    assert post["title"] == "Артист выпустил альбом", post["title"]
    assert post["url"] == "https://t.me/rapruchannel/1", post["url"]
    assert post["cover"] == "https://cdn.telesco.pe/x.jpg", post["cover"]
    assert "«без анонса»" in post["summary"], post["summary"]
    assert "<" not in post["summary"], post["summary"]
    assert post["external_id"] == "tg:rapruchannel/1", post["external_id"]
    print("✓ разбор превью: заголовок, ссылка, фото и чистый текст на месте")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    elif "--check" in sys.argv:
        print("Проверяю Telegram-каналы:\n")
        print(f"\nМолчащих каналов: {check()}")
    else:
        for item in fetch_recent():
            print(f"[{item['outlet']}] {item['title']}")
