"""ВКЛАДЫШ — карточка трека, которую пересылают другу с другой площадки.

Люди делятся музыкой каждый день, а сидят на разных площадках: один на Яндексе,
другой в Apple. Боты-конвертеры на этой боли растут сами, через пересылку, но рынок
забит качалками MP3, а качать каналу закрыто (прав нет, владелец 11.09.2026).
Поэтому не утилита, а вещь, как вкладыш кассеты: ссылка на трек с любой площадки
или «Артист — Трек» — в ответ одна карточка: обложка в рамке канала (card.cover),
все восемь площадок ссылками строкой, у артиста из базы канала — ближайший концерт
из Яндекс Афиши. Площадок все восемь, а не четыре, как в посте (publish.listen):
пост их перечисляет, а вкладыш затем и нужен, чтобы трек дошёл до любой.

Всё собрано из готового. Ссылку разбирает поиск ОТБОРА (otbor.by_link, otbor.lookup),
поэтому площадки у них одни. song.link не берём: его API мёртв. Модели здесь нет —
ответ мгновенный и бесплатный, поэтому и без подписки: замок «подпишись — получи»
убил бы пересылку, а реклама здесь — сама карточка с маркой канала и ссылкой на бота.
Подписку спрашивают кнопки под вкладышем — слежение и разбор вкуса (src/service.py).

Инлайн-режим (@plenka_fm_bot Артист — Трек в чужом чате) отложен: дежурство
разбирает события по одному, и запрос из чужого чата ждал бы за разбором модели
дольше, чем Telegram держит его открытым (NEXT.md, задача 57).

    python -m src.vkladysh --selftest           разбор, карточка, отказ на мусоре — без сети
    python -m src.vkladysh --dry-run "ССЫЛКА"   что бот ответит на ссылку или «Артист — Трек», без Telegram
"""

from __future__ import annotations

import argparse
import html
import logging
import sys
from urllib.parse import quote

from . import card, collect, config, otbor, publish, telegram
from .sources import afisha

log = logging.getLogger("vkladysh")

KICKER = "ВКЛАДЫШ"


def find(text: str) -> dict:
    """Трек по ссылке или «Артист — Трек»: артист, название, ссылка, обложка.
    Пусто — это не трек: куплет в несколько строк, альбом, мусор, нет в магазинах."""
    text = text.strip()
    if "\n" in text:
        return {}
    if link := otbor.URL.search(text):
        return otbor.by_link(link.group(0))
    parts = otbor.DASH.split(text, maxsplit=1)
    if len(parts) != 2 or not parts[0].strip() or not parts[1].strip(" \"«»"):
        return {}
    return otbor.lookup(parts[0].strip(), parts[1].strip(" \"«»"))


def concert(artist: str) -> str:
    """Строка о ближайшем концерте — только у артиста из базы канала: каждый запрос
    к Афише — две секунды ожидания, а вкладыш должен приходить сразу."""
    lead = otbor._credits(artist)[0]
    name = next((a["name"] for a in collect.load_artists() if afisha.same_name(a["name"], lead)), "")
    try:
        page = afisha.find_artist(name) if name else None
        shows = sorted(afisha.concerts(page), key=lambda c: c["day"]) if page else []
    except Exception as exc:  # noqa: BLE001 — без концерта вкладыш всё равно нужен
        log.info("Афиша не ответила (%s): %s", name, exc)
        return ""
    if not shows:
        return ""
    show, esc = shows[0], html.escape
    return f'▸ Концерт: <a href="{esc(show["url"])}">{esc(show["when"])}, {esc(show["city"])}</a>'


def platforms(track: dict) -> str:
    """Все площадки строкой: присланная ссылка — своей площадке, остальным — поиск."""
    query = quote(f"{track['artist']} {track['title']}", safe="")
    return f"{publish.LISTEN_HEAD}\n" + " · ".join(
        f'<a href="{html.escape(track["url"] if publish._host(search) == publish._host(track["url"]) else search.format(q=query))}">{label}</a>'
        for label, search in config.LISTEN_SERVICES)


def caption(track: dict, show: str = "") -> str:
    """Подпись под карточкой: имя, площадки строкой, концерт, откуда вкладыш."""
    parts = [f"<b>{html.escape(track['artist'])} — {html.escape(track['title'])}</b>", platforms(track)]
    if show:
        parts.append(show)
    # Ссылка с меткой: кому переслали вкладыш, делает свой — приходы видны в --sources.
    parts.append(f'<a href="https://t.me/{config.BOT_HANDLE.lstrip("@")}?start=vkladysh">{KICKER}</a>'
                 f" · {config.CHANNEL_HANDLE}")
    return "\n\n".join(parts)


def send(chat_id: str, track: dict) -> None:
    """Карточка с подписью; нет ни обложки, ни фото артиста — одна подпись."""
    text = caption(track, concert(track["artist"]))
    image = card.cover({"cover": track.get("cover", ""), "artist": track["artist"],
                        "track": track["title"], "kicker": KICKER})
    if image is None:
        telegram.send_message(chat_id, text)
        return
    telegram.send_photo_file(chat_id, image, text)
    image.unlink(missing_ok=True)  # карточка уже у человека


def _selftest() -> None:
    real = otbor.by_link, otbor.lookup, collect.load_artists, afisha.find_artist, afisha.concerts
    asked = []
    otbor.by_link = lambda url: asked.append(url) or {
        "artist": "Toxi$, Bushido Zho", "title": "Молния", "url": "https://music.yandex.ru/track/1", "cover": ""}
    otbor.lookup = lambda artist, title: asked.append((artist, title)) or {}
    collect.load_artists = lambda: [{"name": "Toxi$"}]
    afisha.find_artist = lambda name: "toxis"
    afisha.concerts = lambda page: [{"day": "2026-11-02", "when": "2 ноября", "city": "Москва", "url": "https://afisha.yandex.ru/e/2"},
                                    {"day": "2026-10-12", "when": "12 октября", "city": "Казань", "url": "https://afisha.yandex.ru/e/1"}]
    try:
        track = find("лови https://music.yandex.ru/track/1?utm=x")
        assert track["title"] == "Молния" and asked == ["https://music.yandex.ru/track/1?utm=x"], asked
        find("Bones — «Dirt»")
        assert asked[-1] == ("Bones", "Dirt"), asked
        for junk in ("привет", "Bones —", "строка — раз\nстрока — два", ""):
            assert find(junk) == {}, junk
        assert asked[-1] == ("Bones", "Dirt"), "мусор не должен уходить в магазины"

        show = concert(track["artist"])
        assert "12 октября, Казань" in show and "e/1" in show, show
        text = caption(track, show)
        assert text.startswith("<b>Toxi$, Bushido Zho — Молния</b>"), text
        assert 'href="https://music.yandex.ru/track/1"' in text, "ссылка человека — своей площадке"
        assert text.count("<a href") == len(config.LISTEN_SERVICES) + 2, "все площадки, концерт и метка"
        assert "Apple" in text and "?start=vkladysh" in text and config.CHANNEL_HANDLE in text, text
        assert telegram.visible_len(text) <= telegram.MAX_CAPTION
        collect.load_artists = lambda: []
        assert concert(track["artist"]) == "", "чужой артист — Афишу не спрашиваем"
    finally:
        otbor.by_link, otbor.lookup, collect.load_artists, afisha.find_artist, afisha.concerts = real
    print("vkladysh: ссылка и «Артист — Трек», отказ на мусоре, площадки и концерт в подписи — ок")


def main() -> int:
    parser = argparse.ArgumentParser(description="ВКЛАДЫШ: карточка трека со всеми площадками")
    parser.add_argument("--selftest", action="store_true", help="проверка без сети")
    parser.add_argument("--dry-run", metavar="ТЕКСТ", help="что бот ответит, без Telegram")
    args = parser.parse_args()
    if args.selftest:
        _selftest()
        return 0
    if args.dry_run:
        track = find(args.dry_run)
        if not track:
            print("Не трек: бот ответит прежним путём (разбор или «не разобрал»).")
            return 1
        print(caption(track, concert(track["artist"])))
        image = card.cover({"cover": track.get("cover", ""), "artist": track["artist"],
                            "track": track["title"], "kicker": KICKER})
        print(f"\nкарточка: {image or 'нет, уйдёт одна подпись'}")
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sys.exit(main())
