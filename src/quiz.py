"""СЛЕПАЯ ПРОСЛУШКА — викторина по тридцатисекундному отрывку.

Единственная рубрика канала, где от читателя требуется действие, а не чтение.
Пост состоит из двух сообщений: отрывок трека и нативная викторина Telegram
с четырьмя вариантами. Правильный ответ и пояснение Telegram покажет сам,
без нашего участия.

Отрывки — официальные превью iTunes, те самые, что магазин отдаёт всем для
прослушивания. Токенов рубрика не тратит вовсе: все факты берутся из магазина,
придумывать тут нечего.

Главная забота — не проговориться раньше времени. В аудио не уходит ни имя
исполнителя, ни название трека, ни обложка: любое из этого превращает
викторину в объявление ответа.

    python -m src.quiz --preview     показать, что уйдёт в канал
    python -m src.quiz --publish     опубликовать
"""

from __future__ import annotations

import argparse
import logging
import random

from . import config, state, telegram
from .sources import itunes

log = logging.getLogger("quiz")

STATE_FILE = config.DATA / "quiz.json"

# Сколько артистов пробуем, прежде чем сдаться: у каждого запроса к магазину
# своя пауза, и перебирать всю базу ради одного поста незачем.
ATTEMPTS = 8
OPTIONS = 4
# Сколько последних загадок помним, чтобы не повторяться.
MEMORY = 60

INTRO = (
    "🎧 <b>СЛЕПАЯ ПРОСЛУШКА</b>\n\n"
    "Тридцать секунд. Узнаешь — respect, не узнаешь — не страшно, "
    "варианты подобраны так, чтобы было не очевидно."
)

QUESTION = "Кто это?"


def _used() -> set[str]:
    return set(state.read_json(STATE_FILE, {"used": []})["used"])


def _remember(mark: str) -> None:
    used = state.read_json(STATE_FILE, {"used": []})["used"]
    used.append(mark)
    state.write_json(STATE_FILE, {"used": used[-MEMORY:]})


def decoys(target: dict, artists: list[dict], count: int = OPTIONS - 1) -> list[str]:
    """Ложные варианты — из соседних сцен, а не наугад.

    Если подставить кого попало, викторина решается методом исключения:
    среди мемфисского рэпа сразу видно случайную поп-звезду. Поэтому берём
    тех, у кого есть общий тег с загаданным, и только если таких не хватило,
    добираем случайными.
    """
    tags = set(target.get("tags", []))
    name = target["name"]

    kin = [a for a in artists if a["name"] != name and tags & set(a.get("tags", []))]
    random.shuffle(kin)
    picked = [a["name"] for a in kin[:count]]

    if len(picked) < count:
        rest = [a["name"] for a in artists if a["name"] != name and a["name"] not in picked]
        random.shuffle(rest)
        picked += rest[: count - len(picked)]

    return picked[:count]


def pick() -> dict | None:
    """Готовит загадку: отрывок, ответ и три ложных варианта."""
    artists = state.read_json(config.ARTISTS_FILE, {"artists": []})["artists"]
    tracked = [a for a in artists if a.get("itunes_id")]
    if not tracked:
        return None

    used = _used()
    random.shuffle(tracked)

    for artist in tracked[:ATTEMPTS]:
        try:
            releases = itunes.recent_releases(artist["itunes_id"], limit=3)
        except Exception as exc:  # noqa: BLE001 — магазин мог не ответить
            log.info("Релизы «%s» не достались: %s", artist["name"], exc)
            continue

        for release in releases:
            album_id = itunes.album_id_from_url(release.get("url", ""))
            if not album_id:
                continue
            try:
                tracks = itunes.album_tracks(album_id).get("tracks", [])
            except Exception as exc:  # noqa: BLE001
                log.info("Треки «%s» не достались: %s", release.get("title", ""), exc)
                continue

            playable = [t for t in tracks if t.get("preview")]
            random.shuffle(playable)
            for track in playable:
                mark = state.fingerprint(artist["name"], track["title"])
                if mark in used:
                    continue

                options = decoys(artist, artists) + [artist["name"]]
                random.shuffle(options)
                return {
                    "artist": artist["name"],
                    "track": track["title"],
                    "album": release.get("title", ""),
                    "year": (release.get("released_at") or "")[:4],
                    "preview": track["preview"],
                    "options": options,
                    "correct": options.index(artist["name"]),
                    "mark": mark,
                }

    return None


def explanation(item: dict) -> str:
    """Пояснение к ответу. Только проверяемые факты из магазина.

    Двести знаков — жёсткий предел Telegram, поэтому ни одного лишнего слова.
    """
    parts = [f"{item['artist']} — «{item['track']}»"]

    # У синглов магазин зовёт альбом так же, как трек, только с приставкой
    # «- Single». Повторять это в пояснении незачем — остаётся один год.
    album = item["album"]
    single = album.casefold().startswith(item["track"].casefold())
    if album and not single:
        parts.append(f"{album}, {item['year']}" if item["year"] else album)
    elif item["year"]:
        parts.append(item["year"])

    return ". ".join(parts)[: telegram.MAX_EXPLANATION]


def publish(item: dict, target: str) -> None:
    """Отправляет отрывок и следом викторину.

    Двумя сообщениями, а не одним: подпись к аудио и опрос в Telegram
    несовместимы, а опрос без отрывка бессмысленен.
    """
    telegram.send_audio(
        target,
        item["preview"],
        INTRO,
        # Ни имени, ни названия, ни обложки: всё это и есть ответ.
        title=QUESTION,
        performer="ПЛЁНКА",
    )
    telegram.send_quiz(
        target,
        QUESTION,
        item["options"],
        item["correct"],
        explanation=explanation(item),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Слепая прослушка")
    parser.add_argument("--preview", action="store_true", help="показать, не отправляя")
    parser.add_argument(
        "--target",
        choices=["admin", "channel"],
        help="куда отправлять: admin — себе в личку, channel — в канал",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    config.load_dotenv()

    item = pick()
    if not item:
        print("Не нашлось трека с отрывком — попробуй позже.")
        return 1

    print(f"\nОтвет:    {item['artist']} — {item['track']}")
    print(f"Варианты: {', '.join(item['options'])}")
    print(f"Верный:   {item['correct'] + 1}")
    print(f"Пояснение: {explanation(item)}")
    print(f"Отрывок:  {item['preview'][:60]}…")

    if not args.target:
        print("\nОтправить себе: python -m src.quiz --target admin")
        return 0

    to_channel = args.target == "channel"
    target = config.secret("TELEGRAM_CHANNEL_ID" if to_channel else "TELEGRAM_ADMIN_ID")
    publish(item, target)
    _remember(item["mark"])
    print(f"\nОтправлено: {'в канал' if to_channel else 'в личку'}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
