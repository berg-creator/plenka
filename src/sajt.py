"""Открытый сайт бота ПЛЁНКИ — дверь из поиска в Telegram.

Человек ищет «свести трек бесплатно», «свести голос с битом», «можно ли выпустить трек на free-бите»,
а Telegram в поиске Яндекса и Google не виден: бот и канал поисковики не читают. Поэтому сайт
(владелец 20.10.2026) — главная о СВЕДЕНИИ и по странице на каждую запись ПАМЯТКИ, и все ссылки
с них ведут в бота метками *_sajt: `service --sources | grep сайт` считает переходы с сайта отдельно.

Сайт собирается из данных репозитория, а не пишется руками: лимиты и форматы — из config и skleyka,
записи — из data/pamyatka.json тем же текстом, что в боте, примеры ДО/ПОСЛЕ — из каталога
data/hand_examples.json. Правка в боте меняет сайт тем же коммитом, и сайт не может обещать то,
чего бот не делает. Пара примера — MP3 128 кбит/с в assets/sajt/primer-<номер>-do|posle.mp3,
номер — место пары в каталоге: в каталоге file_id Telegram, а ссылку на файл Telegram отдаёт
с ключом бота, поэтому звук лежит в репозитории, без имён и названий.

Отвергнуто: генератор статических сайтов (Jekyll, Hugo, MkDocs) — новая зависимость и второй
источник правды о боте, а страниц тут две дюжины; JavaScript, внешние шрифты и счётчики — сайт
читается с телефона, плеер — тег <audio>, а Метрику владелец подключит сам, если захочет;
приложение ВКонтакте — только если сайт приведёт людей (NEXT.md).

Адрес — GitHub Pages проекта, с подпутём /plenka/: ссылки между страницами относительные,
а канонический адрес и карта сайта — от SITE. Свой домен — сменить SITE, больше ничего.
robots.txt на адресе проекта лежит не в корне домена, и поисковики его там не читают: карту
сайта владелец отдаёт им сам в Вебмастере и Search Console; со своим доменом файл заработает.
Записи о «запрете слов» (slova, zamysel, shtraf) — только текст закона, как в боте: сайт к ним
не добавляет ни совета, ни «что делать».

    python -m src.sajt --build _site    собрать сайт в папку
    python -m src.sajt --selftest       страницы, ссылки, метки и границы — без сети
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

from . import config, pamyatka, skleyka

SITE = "https://berg-creator.github.io/plenka/"
CODE = "https://github.com/berg-creator/plenka/blob/main/"
SOUND = config.ROOT / "assets" / "sajt"
EXAMPLES_MAX = 3
# Подтверждение прав на сайт: тег пришлёт Вебмастер Яндекса и Search Console — вставить сюда значение
# content из их <meta>. Пусто — тега нет.
VERIFY = {"yandex-verification": "", "google-site-verification": ""}
# Метки ссылок в бота: раздел, куда ведёт ссылка, + «_sajt». Каждая стоит в service.SOURCES — сверяет селфтест.
START = {"skleyka": "skleyka_sajt", "bity": "bity_sajt", pamyatka.RUBRIC: "pamyatka_sajt"}
LAW_ONLY = ("slova", "zamysel", "shtraf")  # записи о «запрете слов»: только текст закона, как в боте
GENRES = ("тёмный звук", "фонк", "эмо-рэп", "дрейн")  # канал жанрами не описываем (CLAUDE.md)


def bot(where: str) -> str:
    return f"https://t.me/{config.BOT_HANDLE.lstrip('@')}?start={START[where]}"


def plural(n: int, one: str, few: str, many: str) -> str:
    tail = n % 100
    word = many if 11 <= tail <= 14 else one if n % 10 == 1 else few if 2 <= n % 10 <= 4 else many
    return f"{n} {word}"


def esc(text: str) -> str:
    return html.escape(text, quote=False)


def describe(text: str, limit: int = 155) -> str:
    """meta description — первые слова текста, до limit знаков, по границе слова."""
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0].rstrip(",.:;—- ") + "…"


def examples() -> list[int]:
    """Номера пар каталога, у которых в assets/sajt лежат оба куска, — не больше EXAMPLES_MAX."""
    pairs = json.loads(config.SKLEYKA_HAND_EXAMPLES.read_text()) if config.SKLEYKA_HAND_EXAMPLES.exists() else []
    found = [n for n in range(1, len(pairs) + 1)
             if all((SOUND / f"primer-{n}-{side}.mp3").exists() for side in ("do", "posle"))]
    return found[:EXAMPLES_MAX]


def page(path: str, title: str, description: str, body: str) -> str:
    """Страница целиком. path — адрес от корня сайта («», «pamyatka/», «pamyatka/free/»)."""
    up = "../" * path.count("/")
    meta = "".join(f'<meta name="{name}" content="{esc(value)}">\n' for name, value in VERIFY.items() if value)
    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{html.escape(description)}">
<link rel="canonical" href="{SITE}{path}">
<meta property="og:type" content="website">
<meta property="og:title" content="{html.escape(title)}">
<meta property="og:description" content="{html.escape(description)}">
<meta property="og:url" content="{SITE}{path}">
<meta property="og:image" content="{SITE}icon.png">
<meta property="og:locale" content="ru_RU">
{meta}<link rel="icon" href="{up}icon.png" type="image/png">
<link rel="apple-touch-icon" href="{up}icon.png">
<link rel="stylesheet" href="{up}style.css">
</head>
<body>
<header class="top"><a class="brand" href="{up or './'}"><img src="{up}icon.png" alt="" width="32" height="32">ПЛЁНКА</a>
<nav><a href="{up or './'}">Сведение</a><a href="{up}pamyatka/">Памятка</a></nav></header>
<main>
{body}
</main>
<footer>
<p>ПЛЁНКА — музыкальный канал <a href="https://t.me/{config.CHANNEL_HANDLE.lstrip('@')}">{config.CHANNEL_HANDLE}</a>
и бот <a href="{bot('skleyka')}">{config.BOT_HANDLE}</a> в Telegram.</p>
</footer>
</body>
</html>
"""


def button(href: str, words: str, small: str = "") -> str:
    tail = f'<span class="small">{esc(small)}</span>' if small else ""
    return f'<p class="cta"><a class="button" href="{href}">{esc(words)}</a>{tail}</p>'


def home() -> str:
    days, tweaks, mb = config.SKLEYKA_PER_DAY, config.SKLEYKA_TWEAKS, config.SKLEYKA_MAX_MB
    low, high = skleyka.BEAT_MINUTES
    rub, term = config.SKLEYKA_HAND_RUB[0], config.SKLEYKA_HAND_TERM
    styles = "".join(f"<li><b>{esc(name)}</b> — {esc(about)}</li>" for name, about in skleyka.STYLE_HINTS.items())
    pairs = "".join(f"""<figure class="pair"><figcaption>Пример {n}</figcaption>
<p class="side">ДО — свёл бот</p><audio controls preload="metadata" src="zvuk/primer-{n}-do.mp3"></audio>
<p class="side">ПОСЛЕ — свёл звукорежиссёр</p><audio controls preload="metadata" src="zvuk/primer-{n}-posle.mp3"></audio>
</figure>""" for n in examples())
    heard = f"""<section>
<h2>Как звучит: ДО и ПОСЛЕ</h2>
<p>ДО — кусок трека так, как его бесплатно свёл бот. ПОСЛЕ — то же место у живого звукорежиссёра ПЛЁНКИ:
это платно, от {rub} ₽, готово {esc(term)} — кнопка «🎧 Отдать звукорежиссёру» под готовым треком в боте.</p>
{pairs}
</section>""" if pairs else ""
    free = (f"Бесплатно — {plural(days, 'трек', 'трека', 'треков')} в сутки и "
            f"{plural(tweaks, 'пересборка', 'пересборки', 'пересборок')} на трек.")
    body = f"""<section class="hero">
<h1>Свести голос с битом бесплатно — в Telegram</h1>
<p class="lead">СВЕДЕНИЕ — бот ПЛЁНКИ сводит вокал и бит в готовый трек. Бесплатно, автоматом, за несколько минут.</p>
{button(bot('skleyka'), '🎛 Свести трек в боте', f'{config.BOT_HANDLE} · нужен Telegram')}
<p class="note">Бот сводит подписчикам канала {config.CHANNEL_HANDLE}: без подписки он попросит подписаться. {free}</p>
</section>
<section>
<h2>Три шага</h2>
<ol class="steps">
<li><b>Открой бота</b> {config.BOT_HANDLE} и нажми «🎛 СВЕДЕНИЕ».</li>
<li><b>Пришли вокал и бит</b> — файлами WAV, FLAC или MP3 до {mb} МБ, по дорожкам (вокал, даблы, бэки, эдлибы, бит)
или ссылкой на Яндекс Диск, Dropbox, Google Диск. Выгружай дорожки с начала проекта — голос встанет в бит, как в проекте.</li>
<li><b>Получи готовый трек.</b> Не так — поправь кнопками или напиши словами, как другу: «голос входит на дропе»,
«хочу погрязнее», «как у Travis Scott».</li>
</ol>
<p>Звук выбираешь до сведения:</p>
<ul class="styles">{styles}</ul>
</section>
{heard}
<section>
<h2>Вопросы</h2>
<h3>Это правда бесплатно?</h3>
<p>Да. {free} Бит — от {low} до {high} минут. Упрёшься в лимит — позови артиста: за его первый трек тебе ещё один.
Или докупи треки за звёзды Telegram: {config.SKLEYKA_STARS_PACK} ⭐ — ещё {plural(config.SKLEYKA_PACK, 'трек', 'трека', 'треков')} на сутки,
{config.SKLEYKA_STARS_MONTH} ⭐ — 30 дней по {plural(config.SKLEYKA_MONTH_PER_DAY, 'трек', 'трека', 'треков')} в сутки.
За звёзды — только больше треков: звук тот же, что бесплатно.</p>
<h3>Дорожки на облаке и в архиве?</h3>
<p>Яндекс Диск, Dropbox или файл Google Диска — папкой или архивом zip, 7z, всего до {config.SKLEYKA_LINK_MB // 1024} ГБ
и {plural(config.SKLEYKA_LINK_FILES, 'файла', 'файлов', 'файлов')}. Делить на дорожки не надо: бот разложит по именам файлов —
vocal, beat, adlib, bass, kick… или по-русски.</p>
<h3>Нет бита?</h3>
<p>На шаге бита — «🔎 Нет бита — найти бесплатный»: бот найдёт на YouTube биты как у нужного артиста, которые продюсеры
отдают бесплатно и для релиза, и даст ссылки. А в «🎚 БИТЫ» — биты ПЛЁНКИ: бесплатно, можно в релиз, условия — у каждого бита.</p>
<h3>Голос записан на чужом бите?</h3>
<p>«🔁 Голос записан на чужом бите»: пришли старый бит — бот найдёт бесплатный того же темпа и перенесёт голос на него
(темп — до ±{skleyka.SWAP_TEMPO:.0%}).</p>
<h3>Можно ли выпустить трек на free-бите?</h3>
<p>Смотря что написано в описании бита — <a href="pamyatka/free/">разбор с цитатами закона</a> в ПАМЯТКЕ.</p>
</section>
<section>
<h2>Ещё в боте</h2>
<ul class="doors">
<li><a href="{bot('bity')}">🎚 БИТЫ</a> — биты ПЛЁНКИ, бесплатно, можно в релиз.</li>
<li>📏 ОЦЕНКА — пришли готовый трек: бот замерит его и скажет, чем он отличается от выпущенных релизов.</li>
<li><a href="pamyatka/">⚖️ ПАМЯТКА</a> — права на бит и трек, запись голоса и что в законе о «запрете слов»: цитаты закона.</li>
</ul>
{button(bot('skleyka'), '🎛 Свести трек в боте')}
</section>"""
    title = "Свести трек бесплатно: голос и бит в готовый трек | ПЛЁНКА"
    description = (f"Telegram-бот ПЛЁНКИ сводит вокал и бит в готовый трек: бесплатно, автоматом, за несколько минут. "
                   f"{plural(days, 'трек', 'трека', 'треков')} в сутки, правки словами.")
    return page("", title, description, body)


def _sources(items: list[str]) -> str:
    """Источник из кода бота — ссылкой на файл в открытом репозитории: правило проверяется там же."""
    def one(text: str) -> str:
        match = re.match(r"(src/[\w/]+\.py)(.*)", text, re.S)
        return f'<a href="{CODE}{match[1]}">{match[1]}</a>{esc(match[2])}' if match else esc(text)
    return "".join(f"<li>{one(text)}</li>" for text in items)


def memo(item: dict) -> str:
    """Запись ПАМЯТКИ: вопрос, запись тем же текстом, что в боте, источники, оговорка о юристе у записей
    о правах (в боте она — над их списком) и одна строка в бота — своя строка записи или призыв раздела."""
    door = item.get("start", "").partition("_")[0]
    words, where = (item["bot"], door) if item.get("bot") and door in START else (pamyatka.CALL, pamyatka.RUBRIC)
    text = "".join(f"<p>{esc(part)}</p>" for part in item["text"])
    note = f'<p class="note">{esc(pamyatka.NOTE)}</p>' if item.get("topic") == pamyatka.LAW else ""
    body = f"""<article>
<p class="kicker">ПАМЯТКА · {esc(pamyatka.TOPICS.get(item.get('topic'), ''))}</p>
<h1>{esc(item.get('ask') or item['title'])}</h1>
<p class="headline">{esc(item['title'][:1].upper() + item['title'][1:])}</p>
{text}
<h2>Источники</h2>
<ul class="sources">{_sources(item.get('sources', []))}</ul>
{note}
{button(bot(where), words, f'Telegram-бот {config.BOT_HANDLE}')}
<p><a href="../">← Все вопросы ПАМЯТКИ</a></p>
</article>"""
    title = f"{item.get('ask') or item['title']} — ПАМЯТКА артиста | ПЛЁНКА"
    return page(f"pamyatka/{item['id']}/", title, describe(" ".join(item["text"])), body)


def memos(items: list[dict]) -> str:
    blocks = []
    for topic, name in pamyatka.TOPICS.items():
        rows = "".join(f'<li><a href="{item["id"]}/">{esc(item.get("ask") or item["title"])}</a></li>'
                       for item in items if item.get("topic") == topic)
        blocks.append(f'<h2>{pamyatka.ICONS[topic]} {esc(name)}</h2>\n<ul class="list">{rows}</ul>')
    body = f"""<section>
<h1>ПАМЯТКА артиста</h1>
<p class="lead">{esc(pamyatka.INTRO)}</p>
<p class="note">{esc(pamyatka.NOTE)}</p>
{chr(10).join(blocks)}
{button(bot(pamyatka.RUBRIC), pamyatka.CALL, f'те же ответы в боте {config.BOT_HANDLE}')}
</section>"""
    title = "ПАМЯТКА артиста: права на бит и трек, запись голоса | ПЛЁНКА"
    description = (f"{plural(len(items), 'короткий ответ', 'коротких ответа', 'коротких ответов')} с цитатами закона: "
                   "можно ли выпустить трек на free-бите, как делить фит, что в законе о «запрете слов», как записать голос дома.")
    return page("pamyatka/", title, description, body)


CSS = """:root{--bg:#ebe6da;--card:#f6f3ec;--ink:#22211f;--soft:#5d5a54;--line:#d3ccbd;--red:#c8372b;--on-red:#fff}
@media (prefers-color-scheme:dark){:root{--bg:#1b1a18;--card:#262421;--ink:#ece7db;--soft:#aaa395;--line:#3a3732;--red:#e0503f}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:17px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif}
a{color:var(--red)}
.top,main,footer{max-width:680px;margin:0 auto;padding:0 16px}
.top{display:flex;align-items:center;justify-content:space-between;gap:12px;padding-top:14px;padding-bottom:14px}
.brand{display:flex;align-items:center;gap:8px;font-weight:800;letter-spacing:.06em;color:var(--ink);text-decoration:none}
.brand img{border-radius:50%}
nav a{margin-left:14px;color:var(--soft);text-decoration:none}
h1{font-size:30px;line-height:1.15;margin:18px 0 12px}
h2{font-size:22px;line-height:1.25;margin:34px 0 10px}
h3{font-size:18px;margin:22px 0 4px}
.lead{font-size:19px}
.note,.small,.kicker{color:var(--soft);font-size:15px}
.kicker{margin:22px 0 0;letter-spacing:.04em}
.headline{font-weight:700}
.cta{margin:22px 0}
.button{display:inline-block;background:var(--red);color:var(--on-red);font-weight:700;text-decoration:none;
padding:14px 22px;border-radius:999px;font-size:18px}
.small{display:block;margin-top:8px}
.steps,.styles,.doors,.list,.sources{padding-left:22px}
.steps li,.doors li,.list li{margin:8px 0}
.sources{font-size:15px;color:var(--soft);overflow-wrap:anywhere}
.pair{margin:16px 0;padding:14px 16px;background:var(--card);border:1px solid var(--line);border-radius:14px}
.pair figcaption{font-weight:700}
.side{margin:12px 0 6px;font-size:15px;color:var(--soft)}
audio{width:100%}
footer{margin-top:40px;padding-top:16px;padding-bottom:32px;border-top:1px solid var(--line);color:var(--soft);font-size:15px}
@media (min-width:720px){h1{font-size:38px}}
"""


def build(out: Path) -> list[str]:
    """Собрать сайт в out, вернуть адреса страниц — те же, что в карте сайта."""
    items = pamyatka.load()
    pages = {"": home(), "pamyatka/": memos(items), **{f"pamyatka/{item['id']}/": memo(item) for item in items}}
    if out.exists() and any(out.iterdir()):
        # Чистится только прежняя сборка: опечатка в --build не должна стереть чужую папку.
        if not (out / "sitemap.xml").exists():
            raise SystemExit(f"{out} не пуста и не похожа на сборку сайта — не трогаю")
        shutil.rmtree(out)
    for path, text in pages.items():
        (out / path).mkdir(parents=True, exist_ok=True)
        (out / path / "index.html").write_text(text)
    (out / "style.css").write_text(CSS)
    shutil.copy(SOUND / "icon.png", out / "icon.png")
    (out / "zvuk").mkdir()
    for n in examples():
        for side in ("do", "posle"):
            shutil.copy(SOUND / f"primer-{n}-{side}.mp3", out / "zvuk" / f"primer-{n}-{side}.mp3")
    urls = "".join(f"<url><loc>{SITE}{path}</loc></url>\n" for path in pages)
    (out / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n'
                                     f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{urls}</urlset>\n')
    (out / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: {SITE}sitemap.xml\n")
    return list(pages)


def _selftest() -> None:
    from . import service  # здесь, а не наверху: сборке на Actions поллер бота не нужен
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "site"
        paths = build(out)
        items = pamyatka.load()
        assert len(paths) == len(items) + 2 and all(f"pamyatka/{item['id']}/" in paths for item in items), paths
        titles, descriptions = set(), set()
        for path in paths:
            text = (out / path / "index.html").read_text()
            title = re.search(r"<title>(.+?)</title>", text)[1]
            description = re.search(r'<meta name="description" content="(.+?)">', text)[1]
            assert title not in titles and description not in descriptions and 20 < len(description) <= 200, path
            titles.add(title), descriptions.add(description)
            assert f'<link rel="canonical" href="{SITE}{path}">' in text and 'name="viewport"' in text, path
            assert "<script" not in text and "@import" not in text, f"без скриптов и внешних шрифтов: {path}"
            low = text.casefold()
            assert not [genre for genre in GENRES if genre in low], f"канал жанрами не описываем: {path}"
            assert config.SKLEYKA_HAND_ENGINEER not in text, f"ник звукорежиссёра — только в боте: {path}"
            # Ссылки: внутренние ведут на файлы сборки, в бота — метками сайта, известными service.SOURCES.
            for link in re.findall(r'(?:href|src)="([^"]+)"', text):
                if link.startswith(f"https://t.me/{config.BOT_HANDLE.lstrip('@')}"):
                    label = link.partition("?start=")[2]
                    assert label in START.values() and label in service.SOURCES and "сайт" in service.SOURCES[label], link
                elif not link.startswith(("https://", "http://")):
                    target = (out / path / link).resolve()
                    assert (target / "index.html" if target.is_dir() else target).exists(), f"{path}: {link}"
                else:
                    assert link.startswith((SITE, CODE, "https://t.me/")), f"чужой адрес: {path}: {link}"
        home_text = (out / "index.html").read_text()
        assert f"{config.SKLEYKA_PER_DAY} трек" in home_text and config.CHANNEL_HANDLE in home_text, "лимит и подписка — из config"
        assert home_text.count("<audio") == 2 * len(examples()) and examples(), "плееры ДО/ПОСЛЕ из каталога"
        assert all(" " not in name and re.fullmatch(r"primer-\d+-(do|posle)\.mp3", name)
                   for name in (p.name for p in (out / "zvuk").iterdir())), "в именах звука ни имён, ни названий"
        for item in items:
            text = (out / "pamyatka" / item["id"] / "index.html").read_text()
            assert all(esc(part) in text for part in item["text"]) and esc(item.get("ask") or item["title"]) in text, item["id"]
            assert (esc(pamyatka.NOTE) in text) == (item["topic"] == pamyatka.LAW), f"оговорка о юристе — у прав: {item['id']}"
            assert len(re.findall(r'class="button"', text)) == 1, f"одна строка в бота: {item['id']}"
            line = re.search(r'class="button"[^>]*>(.+?)</a>', text)[1]
            assert len(html.unescape(line)) <= pamyatka.LINE_MAX, f"строка в бота длиннее строки телефона: {line}"
            if item["id"] in LAW_ONLY:
                article = re.search(r"<article>(.+)</article>", text, re.S)[1]
                assert "что делать" not in article.casefold() and not item.get("bot"), f"только текст закона: {item['id']}"
        assert re.search(r"start=bity_sajt", (out / "pamyatka" / "free" / "index.html").read_text()), "запись про бит — в биты"
        assert "start=skleyka_sajt" in (out / "pamyatka" / "shum" / "index.html").read_text(), "запись о голосе — в сведение"
        assert "start=pamyatka_sajt" in (out / "pamyatka" / "slova" / "index.html").read_text(), "без своей строки — в раздел"
        sitemap = (out / "sitemap.xml").read_text()
        assert sitemap.count("<loc>") == len(paths) and f"<loc>{SITE}pamyatka/free/</loc>" in sitemap
        assert f"Sitemap: {SITE}sitemap.xml" in (out / "robots.txt").read_text()
        assert plural(2, "трек", "трека", "треков") == "2 трека" and plural(11, "а", "б", "в") == "11 в" \
            and plural(21, "а", "б", "в") == "21 а" and plural(64, "а", "б", "в") == "64 б"
        assert describe("слово " * 60).endswith("…") and len(describe("слово " * 60)) <= 156
    print("sajt: селфтест пройден")


def main() -> None:
    parser = argparse.ArgumentParser(description="Открытый сайт бота ПЛЁНКИ для поисковиков")
    parser.add_argument("--build", type=Path, metavar="ПАПКА", help="собрать сайт в папку (она очищается)")
    parser.add_argument("--selftest", action="store_true", help="проверить сборку без сети")
    args = parser.parse_args()
    if args.selftest:
        _selftest()
    elif args.build:
        paths = build(args.build)
        print(f"sajt: {len(paths)} страниц в {args.build}")
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
