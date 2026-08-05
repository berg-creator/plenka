"""Разовое заполнение id артистов в data/artists.json.

Имена в базе написаны по-человечески, а каждому сервису нужен свой числовой id.
Скрипт ищет их автоматически и дописывает в файл. Запускается редко —
при первой сборке и после добавления новых артистов.

    python -m src.resolve_ids --missing        только те, у кого id ещё нет
    python -m src.resolve_ids --with-youtube   заодно искать каналы YouTube (медленно)
"""

from __future__ import annotations

import argparse

from . import config, state
from .sources import deezer, itunes, youtube_rss


def main() -> int:
    parser = argparse.ArgumentParser(description="Поиск id артистов в iTunes, Deezer, YouTube")
    parser.add_argument("--missing", action="store_true", help="только артисты без id")
    parser.add_argument("--with-youtube", action="store_true", help="искать ещё и каналы YouTube")
    parser.add_argument("--limit", type=int, default=0, help="ограничить число артистов за прогон")
    args = parser.parse_args()

    payload = state.read_json(config.ARTISTS_FILE, {"artists": []})
    artists = payload.get("artists", [])
    if not artists:
        print("data/artists.json пуст")
        return 1

    targets = [
        a
        for a in artists
        if not args.missing or not (a.get("itunes_id") and a.get("deezer_id"))
    ]
    if args.limit:
        targets = targets[: args.limit]

    print(f"Обрабатываю артистов: {len(targets)}\n")
    resolved = 0

    for index, artist in enumerate(targets, start=1):
        name = artist["name"]
        marks: list[str] = []

        if not artist.get("itunes_id"):
            try:
                found = itunes.find_artist_id(name)
            except Exception:
                found = None
            if found:
                artist["itunes_id"] = found
                marks.append("iTunes")

        if not artist.get("deezer_id"):
            try:
                found = deezer.find_artist_id(name)
            except Exception:
                found = None
            if found:
                artist["deezer_id"] = found
                marks.append("Deezer")

        if args.with_youtube and not artist.get("youtube_channel_id"):
            try:
                found = youtube_rss.find_channel_id(name)
            except Exception:
                found = None
            if found:
                artist["youtube_channel_id"] = found
                marks.append("YouTube")

        if marks:
            resolved += 1
            print(f"  [{index:>3}/{len(targets)}] {name:<28} → {', '.join(marks)}")
        else:
            print(f"  [{index:>3}/{len(targets)}] {name:<28} — ничего не найдено")

        # Промежуточное сохранение: прогон долгий, обрыв не должен терять работу.
        if index % 20 == 0:
            payload["artists"] = artists
            state.write_json(config.ARTISTS_FILE, payload)

    payload["artists"] = artists
    payload["ids_updated_at"] = state.iso()
    state.write_json(config.ARTISTS_FILE, payload)

    without_any = sum(1 for a in artists if not a.get("itunes_id") and not a.get("deezer_id"))
    print(f"\nОбновлено записей: {resolved}. Совсем без id осталось: {without_any}.")
    if without_any:
        print("Такие артисты просто не попадут в рубрику РЕЛИЗ — на новости это не влияет.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
