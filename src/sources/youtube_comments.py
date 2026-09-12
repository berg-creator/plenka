"""Живой отзыв под клипом на YouTube — второй чужой голос в посте о релизе.

Канал релиз не слушал и своего впечатления о звуке иметь не может, поэтому
посты выходят суховато-колкими. Реакция живых людей эту дыру закрывает так же,
как мнение издания, и стоит дешевле: комментарий — проверяемый факт, а не
выдумка. Идея владельца от 12.09.2026 («как у коден крэйзи»).

Комментарии — единственная живая реакция, до которой можно дотянуться ключом,
а не парсингом: страница YouTube отдаёт их отдельным запросом-продолжением,
и разбор ломался бы при каждой правке разметки. Квота Data API — 10 000 единиц
в сутки: поиск видео стоит 100, сами комментарии — 1, то есть 101 единица
на пост о релизе и около сотни постов в день при полном расходе квоты.

Ник автора не берётся вовсе: репозиторий открытый, данные о людях в него
не кладутся никогда, а цитата работает и без подписи. Под клипами хватает мата
и оскорблений, поэтому отбор грубый: короткая человеческая реплика без брани,
ссылок и зазывов, с заметным числом лайков — остальное пропускаем.

Без ключа модуль молча отвечает пустым: посты пишутся как раньше.

    python -m src.sources.youtube_comments --check "Баста" "Сияй"
"""

from __future__ import annotations

import logging
import os
import re
import sys

from .http import get_json

log = logging.getLogger("youtube_comments")

API = "https://www.googleapis.com/youtube/v3"

# Реплика короче — не мнение, длиннее — не цитата: в пост о релизе
# помещается одна фраза (200–400 знаков на весь пост).
MIN_LENGTH = 25
MAX_LENGTH = 160
# Лайки отделяют реакцию, которую разделяют многие, от случайной реплики.
MIN_LIKES = 5

# Мат, оскорбления и расистские клички: в посте канала им не место,
# а под клипами они через один.
RUDE = re.compile(
    r"ху[ийеё]|пизд|бля|[её]бан|[её]бал|еблан|заеб|уеб|мудак|гандон|шлюх|сук[аиу]\b|"
    r"сучк|пидор|педик|долбо|нахуй|похуй|черножоп|ниггер|nigg|fuck|shit|bitch|cunt",
    re.IGNORECASE,
)
# Спам и самореклама: ссылки, упоминания, зазывы подписаться.
JUNK = re.compile(r"https?://|t\.me|@\w|подпиш|подпис(?:ка|ывай)|мой канал|instagram|telegram", re.IGNORECASE)


def key() -> str:
    """Ключ YouTube Data API. Отдельная переменная, но годится и общий
    ключ Google: в Cloud-проекте это один ключ с включённым YouTube Data API."""
    return (os.environ.get("YOUTUBE_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")).strip()


def _call(method: str, **params: str) -> dict | None:
    data = get_json(f"{API}/{method}", params={"key": key(), **params}, min_interval=0.3)
    if isinstance(data, dict) and "error" in data:
        # Кончилась квота или не включён API — не повод ронять запуск.
        log.warning("YouTube %s: %s", method, data["error"].get("message", ""))
        return None
    return data if isinstance(data, dict) else None


def find_video(query: str) -> str:
    """Идентификатор первого ролика по запросу. Дорогая часть: 100 единиц квоты."""
    data = _call("search", part="id", q=query, type="video", maxResults="1", order="relevance")
    items = (data or {}).get("items") or []
    return items[0].get("id", {}).get("videoId", "") if items else ""


def suitable(text: str, likes: int) -> bool:
    """Годится ли реплика в пост: человеческая, без брани и спама."""
    flat = " ".join(text.split())
    return (
        MIN_LENGTH <= len(flat) <= MAX_LENGTH
        and likes >= MIN_LIKES
        and not RUDE.search(flat)
        and not JUNK.search(flat)
        and flat != flat.upper()  # крик капсом цитировать нечего
    )


def top_comment(artist: str, title: str) -> dict:
    """Самый заметный годный комментарий под клипом релиза.

    Возвращает {"text": …, "likes": …} или пустой словарь: нет ключа,
    нет ролика, нет годных реплик — пост пишется без чужого голоса.
    """
    if not key():
        return {}
    video = find_video(f"{artist} {title}")
    if not video:
        return {}
    data = _call(
        "commentThreads", part="snippet", videoId=video, order="relevance",
        maxResults="20", textFormat="plainText",
    )
    for thread in (data or {}).get("items") or []:
        snippet = thread.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
        text = " ".join((snippet.get("textDisplay") or "").split())
        likes = int(snippet.get("likeCount") or 0)
        if suitable(text, likes):
            # Ник автора не берём: репозиторий открытый.
            return {"text": text, "likes": likes}
    return {}


def check(artist: str = "Баста", title: str = "Сияй") -> int:
    """Есть ли ключ и отвечает ли API. Тратит 101 единицу квоты из 10 000."""
    if not key():
        print("× Ключа нет (YOUTUBE_API_KEY или GOOGLE_API_KEY). Посты пишутся без живых отзывов.")
        return 1
    comment = top_comment(artist, title)
    if not comment:
        print(f"× {artist} — {title}: годного комментария не нашлось (или API молчит).")
        return 1
    print(f"  {artist} — {title}: «{comment['text']}» ({comment['likes']} лайков)")
    return 0


def _selftest() -> int:
    """Отбор реплик: брань, спам и крик отсеиваются, человеческое проходит."""
    assert suitable("Этот трек вытащил меня из осени, спасибо", 42)
    assert not suitable("Этот трек вытащил меня из осени", 1), "мало лайков — не реакция"
    assert not suitable("ну и хуйня конечно", 900), "мат в пост не идёт"
    assert not suitable("подпишись на мой канал", 900), "спам в пост не идёт"
    assert not suitable("ОГОНЬ ОГОНЬ ОГОНЬ ОГОНЬ ОГОНЬ ОГОНЬ", 900), "крик капсом"
    assert not suitable("топ", 900), "слишком коротко"
    print("Отбор комментариев: брань, спам и крик отсеяны, человеческое прошло.")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--selftest":
        raise SystemExit(_selftest())
    if args and args[0] == "--check":
        raise SystemExit(check(*args[1:3]) if len(args) > 1 else check())
    print(__doc__)
