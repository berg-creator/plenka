"""Новенькие: база артистов пополняется сама — из того, о ком пишет пресса сцены.

data/artists.json собран руками в августе 2026-го, и новые имена попадали туда
тоже только руками. Цена была видна по находкам: Kai Angel за 12 дней семь раз
был в новостях The Flow и «Интермедиа» и каждый раз получал 30 из 100 — его
не было в базе, а его релизы сбор не искал вовсе. Владелец 17.09.2026: «нельзя
ориентироваться только на моих любимых».

Раз в сутки шаг проходит новости inbox за две недели и берёт из заголовка то,
что стоит перед глаголом события или кавычкой: «Kai Angel выпустил альбом»,
«Yeat Drops Apparent Diss», «Soda Luv “Прими как есть”». Модель не нужна —
имя подтверждает не разбор фразы, а три проверки подряд:

- его назвали два разных издания, и одно из них — рэп-пресса (SCENE_OUTLETS).
  Рубрика одного издания («Обзор», «Клип дня») двух изданий не наберёт,
  а инди из Stereogum и эстрада из «Интермедиа» без рэп-прессы не проходят;
- iTunes знает артиста ровно под этим именем, и жанр у него — рэп. Жанр
  отсекает Zivert и Troye Sivan, точное имя — обычные слова;
- со строчной буквы имя в новостях не встречается. Future — это ещё и «the
  future», и такое имя ловило бы новости мимо артиста: сбор и ПРОЯВКА ищут
  имена целым словом, а collect.AMBIGUOUS_NAMES ведётся руками.

Отвергнуто:
- похожие артисты Deezer у ядра базы — тот же вкус владельца, только шире.
  Замер 17.09.2026 по 110 артистам core/scene/ru: чаще всех в соседях сама же
  база под другим написанием (LSP, Morgenshtern, Гуф), следом эстрада и русский
  рок (Макс Корж, ДДТ, Земфира), а Kai Angel и Yeat — ни разу;
- топ стриминга — общий чарт, а канал на другую аудиторию (prompts/reels.md,
  «Удержание»);
- списки слежения подписчиков: любимец одного человека стал бы постом канала,
  от этого уже отказались в service.watched_releases.

Новые идут уровнем auto: оценка ниже ядра и сцены, выше ru_pop
(collect.TIER_SCORE). Кого рэп-пресса за 30 дней назвала в PROMOTE_NEWS
новостях, переходит в scene. Кого полгода нет ни в новостях, ни в релизах, выпадает
из сбора (collect.in_collect), но остаётся в файле — по нему ищутся фото
и ссылки. Поле seen_at — день, когда о новеньком писали последний раз.

Потолок: сбор спрашивает iTunes раз в 3 секунды на артиста, и тысяча имён
растянула бы его с девяти минут до часа. Пока рост держат само правило
(за август–сентябрь 2026-го — 9 имён, без него было бы 17 с Netflix и SNL)
и полгода тишины; упрётся — опрашивать новеньких реже, а не резать правило.

    python -m src.newcomers --dry-run    кого добавил бы и почему, без записи
    python -m src.newcomers --selftest   правила на выдуманных новостях, без сети
    python -m src.newcomers              рабочий режим, раз в сутки из collect.yml
"""

from __future__ import annotations

import argparse
import re
from datetime import datetime, timedelta

from . import collect, config, state
from .sources import deezer, http, itunes

# Рэп-пресса из data/feeds.json: без неё имя из общих изданий не берётся.
SCENE_OUTLETS = frozenset({"The Flow", "RAP.RU", "РЭП СМИ", "HipHopDX", "Рэп Мьюзик"})
WINDOW_DAYS = 14
PROMOTE_DAYS = 30
PROMOTE_NEWS = 4

RU_VERB = (r"(?:выпус|выпуск|представ|показа|анонс|дропн|записа|перен[её]с|отмени|объяви|сня|"
           r"поеха|верну|возвращ|готов|рассказа|откры|объедин|удали|пожертв|тизер|призна|стал|"
           r"ед[еу]т|выступ|получи|заяви|ответи|извини|подели|запусти|умер|скончал|задержа|"
           r"арестова|подал|подтверди|собира|засвети)\w*")
EN_VERB = (r"(?:(?:Drop|Share|Announce|Release|Unveil|Return|Tease|Premiere|Debut|Detail|Reveal|"
           r"Cancel|Postpone|Link|Join|Appear|Cover|Confirm|Sign|Say|Talk|Address|Respond|Enlist|"
           r"Tap|Recruit|Preview|Celebrate|Play|Perform|Bring|Deliver|Launch|Hop|Diss|Team|"
           r"Collaborate|Kick|Head|Call|Get|Make|Go|Want|Speak)(?:s|es)?|Is|Are|Was|Were|Has|Have|Will)")
QUOTES = "\"«“„"
HEAD = {
    lang: re.compile(rf"^(.{{2,60}}?)\s+(?:{verb}(?!\w)|[{QUOTES}])")
    for lang, verb in (("ru", RU_VERB), ("en", EN_VERB))
}
SPLIT = re.compile(r",\s*|\s+(?:и|x|&|feat\.?|ft\.?|and|with)\s+", re.IGNORECASE)
ROLE = re.compile(r"^(?:рэпер\w*|певи\w*|певец|группа|продюсер\w*|rapper|singer|producer)\s+", re.IGNORECASE)
# Те же знаки, что пропускает метка знатока в СЛЕПОЙ ПРОСЛУШКЕ (quiz.title).
NAME = re.compile(r"[\w $/&'.:-]+")
RAP = re.compile(r"hip-hop|rap", re.IGNORECASE)


def heads(title: str, lang: str = "ru") -> list[str]:
    """Имена в начале заголовка: до глагола события или до кавычки."""
    match = HEAD["en" if lang == "en" else "ru"].match(title.strip())
    if not match:
        return []
    names = []
    for part in SPLIT.split(match.group(1)):
        part = ROLE.sub("", part.strip(" .:—–-"))
        # Со строчной начинается слово, а не имя: «Лордоранж и другие концерты».
        if 0 < len(part) <= 30 and len(part.split()) <= 4 and not part[0].islower() \
                and re.search(r"[^\W\d_]", part) and NAME.fullmatch(part):
            names.append(part)
    return names


def said(name: str, text: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text, re.IGNORECASE) is not None


def ordinary(name: str, texts: list[str]) -> bool:
    """Имя встречается и обычным словом, со строчной: «the future» у Future."""
    lower = name.lower()
    return lower != name and any(re.search(rf"(?<!\w){re.escape(lower)}(?!\w)", t) for t in texts)


def known_names(artists: list[dict]) -> set[str]:
    return {collect._fold(n) for a in artists
            for n in (a.get("name"), a.get("search_name"), *(a.get("aliases") or [])) if n}


def since(days: int, now: datetime) -> str:
    return state.iso(now - timedelta(days=days))


def candidates(news: list[dict], artists: list[dict], now: datetime) -> list[dict]:
    """Имена вне базы, которые за WINDOW_DAYS назвали два издания, одно — рэп-пресса."""
    fresh = [r for r in news if r.get("collected_at", "") >= since(WINDOW_DAYS, now)]
    known = known_names(artists)
    texts = [f"{r.get('title', '')} {r.get('summary', '')}" for r in news]
    found: dict[str, dict] = {}
    checked: set[str] = set()
    for row in fresh:
        for name in heads(row.get("title", ""), row.get("lang", "ru")):
            key = collect._fold(name)
            if key in known or key in checked:
                continue
            checked.add(key)
            hits = [r for r in fresh if said(name, r.get("title", ""))]
            outlets = sorted({r.get("outlet", "") for r in hits})
            if len(outlets) < 2 or not SCENE_OUTLETS & set(outlets):
                continue
            if ordinary(name, texts):
                print(f"  · {name}: ещё и обычное слово — в базу только руками")
                continue
            found[key] = {"name": name, "outlets": outlets, "news": len(hits)}
    return list(found.values())


def store(name: str) -> dict | None:
    """Артист в магазинах ровно под этим именем и с рэпом в жанре iTunes.

    Берётся первое точное совпадение выдачи, и жанр проверяется у него, а не
    ищется среди тёзок: иначе новость о поп-певице привела бы в базу безвестного
    рэпера с тем же именем, и канал анонсировал бы его релизы.
    """
    data = http.get_json(itunes.SEARCH_URL, params={"term": name, "entity": "musicArtist", "limit": 5},
                         min_interval=itunes.MIN_INTERVAL) or {}
    same = [i for i in data.get("results") or [] if collect._fold(i.get("artistName", "")) == collect._fold(name)]
    if not same or not RAP.search(same[0].get("primaryGenreName") or ""):
        return None
    return {"name": same[0]["artistName"], "itunes_id": same[0]["artistId"],
            "deezer_id": deezer.find_artist_id(same[0]["artistName"])}


def refresh(artists: list[dict], rows: list[dict], now: datetime) -> list[str]:
    """seen_at и переход в scene у тех, кого база нашла сама."""
    notes = []
    news = [r for r in rows if r.get("kind") == "news"]
    for artist in artists:
        if "seen_at" not in artist:
            continue  # собранных руками не трогаем
        name = artist["name"]
        dates = [r.get("collected_at", "") for r in news if said(name, r.get("title", ""))]
        dates += [r.get("collected_at", "") for r in rows
                  if r.get("kind") == "release" and name in (r.get("tracked"), r.get("artist"))]
        if dates:
            artist["seen_at"] = max(artist["seen_at"], max(dates)[:10])
        # В scene переводит рэп-пресса, а не шум: Macklemore за сентябрь 2026-го
        # попал в 22 новости, и все — про тур Эда Ширана и Палестину.
        loud = sum(1 for r in news if r.get("outlet") in SCENE_OUTLETS
                   and r.get("collected_at", "") >= since(PROMOTE_DAYS, now) and said(name, r.get("title", "")))
        if artist.get("tier") == "auto" and loud >= PROMOTE_NEWS:
            artist["tier"] = "scene"
            notes.append(f"  ↑ {name}: рэп-пресса за {PROMOTE_DAYS} дней — {loud} раз, теперь scene")
        if not collect.in_collect(artist):
            notes.append(f"  · {name}: тишина с {artist['seen_at']} — вне сбора")
    return notes


def run(dry_run: bool) -> int:
    payload = state.read_json(config.ARTISTS_FILE, {"artists": []})
    artists = payload["artists"]
    now = state.now()
    today = now.date().isoformat()
    if not dry_run and payload.get("grown_at") == today:
        print("База сегодня уже пополнялась.")
        return 0

    rows = list(state.read_jsonl(config.INBOX_FILE))
    added = []
    for cand in candidates([r for r in rows if r.get("kind") == "news"], artists, now):
        found = store(cand["name"])
        why = f"новостей {cand['news']}: {', '.join(cand['outlets'])}"
        if not found:
            print(f"  ✗ {cand['name']} ({why}): в iTunes нет рэпера с таким именем")
            continue
        if collect._fold(found["name"]) in known_names(artists + added):
            continue
        added.append({**found, "tags": [], "tier": "auto", "seen_at": today})
        print(f"  + {found['name']} ({why})")

    notes = refresh(artists + added, rows, now)
    if notes:
        print("\n".join(notes))
    print(f"Новых: {len(added)}. В базе станет: {len(artists) + len(added)}.")
    if dry_run:
        return 0
    payload["artists"] = artists + added
    payload["grown_at"] = today
    state.write_json(config.ARTISTS_FILE, payload)
    return 0


def _selftest() -> int:
    """Без сети: извлечение имён, два издания и рэп-пресса, обычные слова, переход и тишина."""
    from datetime import timezone
    from unittest import mock

    assert heads("Kai Angel выпустил альбом «Shh…»") == ["Kai Angel"]
    assert heads("Yeat Drops Apparent Travis Scott Diss Track", "en") == ["Yeat"]
    assert heads("Soda Luv “Прими как есть”") == ["Soda Luv"]
    assert heads("Nkeeei и Yanix выпустили трек") == ["Nkeeei", "Yanix"]
    assert heads("Рэпер Брутто рассказал о концепции") == ["Брутто"]
    assert heads("Трагическая мечта о Западе: о чем новый альбом Kai Angel") == []
    assert heads("Бабочек Плач, Дрыгогиг и другие концерты недели выступят") == ["Бабочек Плач", "Дрыгогиг"]

    now = datetime(2026, 9, 17, 12, tzinfo=timezone.utc)
    day = lambda d: f"2026-09-{d:02d}T10:00:00+00:00"  # noqa: E731
    news = [
        {"title": "Kai Angel выпустил альбом «Shh…»", "outlet": "Интермедиа", "collected_at": day(6)},
        {"title": "Kai Angel выпустил клип", "outlet": "The Flow", "collected_at": day(12)},
        {"title": "Zivert выпустила сингл «Лето»", "outlet": "Интермедиа", "collected_at": day(10)},
        {"title": "Zivert представила клип", "outlet": "Lenta Музыка", "collected_at": day(11)},
        {"title": "Обзор «Новые клипы недели»", "outlet": "Интермедиа", "collected_at": day(12)},
        {"title": "Обзор «Альбомы»", "outlet": "Интермедиа", "collected_at": day(13)},
        {"title": "Обзор «Старое»", "outlet": "RAP.RU", "collected_at": "2026-08-01T10:00:00+00:00"},
        {"title": "Future выпустил трек", "outlet": "The Flow", "collected_at": day(14)},
        {"title": "Future Shares New Song", "outlet": "Pitchfork", "collected_at": day(15), "lang": "en"},
        {"title": "Why the future of rap is local", "outlet": "Stereogum", "collected_at": day(15), "lang": "en"},
        {"title": "Баста выпустил трек", "outlet": "The Flow", "collected_at": day(15)},
        {"title": "Баста представил клип", "outlet": "Интермедиа", "collected_at": day(16)},
    ]
    base = [{"name": "Баста", "tier": "ru_pop"}]
    names = [c["name"] for c in candidates(news, base, now)]
    # Обзор — рубрика одного издания, рэп-пресса писала его месяц назад; у Zivert
    # рэп-прессы нет; Future ещё и обычное слово; Баста уже в базе.
    assert names == ["Kai Angel"], names

    catalog = {"Kai Angel": ("Kai Angel", "Hip-Hop/Rap"), "Zivert": ("Zivert", "Pop")}

    def fake_get(url, params=None, **kw):
        hit = catalog.get(params["term"])
        return {"results": [{"artistName": hit[0], "artistId": 7, "primaryGenreName": hit[1]}] if hit else []}

    with mock.patch.object(http, "get_json", fake_get), mock.patch.object(deezer, "find_artist_id", lambda n: 9):
        assert store("Kai Angel") == {"name": "Kai Angel", "itunes_id": 7, "deezer_id": 9}
        assert store("Zivert") is None, "поп-певица прошла жанр"
        assert store("Обзор") is None

    fresh = {"name": "Kai Angel", "tier": "auto", "seen_at": "2026-09-06"}
    quiet = {"name": "Ghost Name", "tier": "auto", "seen_at": "2026-02-01"}
    loud = [{"kind": "news", "title": f"Kai Angel выпустил трек {i}", "outlet": "The Flow",
             "collected_at": day(10 + i)} for i in range(PROMOTE_NEWS)]
    noise = {"kind": "news", "title": "Kai Angel пожертвовал миллион", "outlet": "NME", "collected_at": day(16)}
    with mock.patch.object(state, "now", lambda: now):
        refresh([fresh], loud[1:] + [noise], now)
        assert fresh["tier"] == "auto" and fresh["seen_at"] == "2026-09-16", "шум общих изданий перевёл в scene"
        notes = refresh([fresh, quiet, {"name": "Bones", "tier": "core"}], loud, now)
        assert fresh["tier"] == "scene", fresh
        assert not collect.in_collect(quiet) and collect.in_collect(fresh), notes
        assert collect.in_collect({"name": "Bones", "tier": "core"})
        assert not collect.in_collect({"name": "Баста", "tier": "ru_pop"})
    print("newcomers: самопроверка пройдена")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="База артистов пополняется сама — по прессе сцены")
    parser.add_argument("--dry-run", action="store_true", help="кого добавил бы и почему, без записи")
    parser.add_argument("--selftest", action="store_true", help="проверка правил без сети")
    args = parser.parse_args()
    return _selftest() if args.selftest else run(args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
