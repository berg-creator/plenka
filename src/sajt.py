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

Главный пример — бесплатное сведение ботом, первым экраном (владелец 21.10.2026: «человек должен сразу,
как зашёл, начать пользоваться»), пары каталога — ниже, отдельным платным блоком звукорежиссёра: ДО там —
уже работа бота, и рядом с бесплатным примером их путали. Главная пара — assets/sajt/glavnyj-do|posle.mp3,
трек «Асапчик», записанный на телефон, ролик «ДО и ПОСЛЕ» 28.09.2026. В самом ролике ДО и ПОСЛЕ — соседние
куски трека (ДО — первая строка, дальше сразу ПОСЛЕ), а переключателю нужно одно место, поэтому ДО собран
из исходных дорожек артиста — лид, дабл и бит просто сложены, как ДО в `skleyka.story`, — на месте ПОСЛЕ
из ролика: 10,20–17,47 с трека, ровно два такта (66 BPM) от паузы до паузы голоса, чтобы петля не сбивала
сетку; выравнивание по взаимной корреляции — 0 мс, обе половины −14,4 LUFS.

Плеер ДО/ПОСЛЕ (владелец 21.10.2026: «один плеер вместо двух записей») — свой скрипт player.js на Web Audio:
обе записи играют разом, слышна одна, нажатие меняет громкости за 30 мс, и фраза не прыгает. Тег <audio>
так не умеет: два тега на телефоне расходятся на десятки миллисекунд. Без скрипта остаются два <audio>.
Шрифт заголовков — Oswald с Google Fonts (кириллица, display=swap, запасной — системный узкий), как в роликах.
Отвергнуто: генератор статических сайтов (Jekyll, Hugo, MkDocs) — новая зависимость и второй источник
правды о боте, а страниц тут две дюжины; библиотеки плеера и счётчики — сайт читается с телефона,
а Метрику владелец подключит сам, если захочет; приложение ВКонтакте — только если сайт приведёт людей (NEXT.md).

Адрес — GitHub Pages проекта, с подпутём /plenka/: ссылки между страницами относительные,
а канонический адрес и карта сайта — от SITE. Свой домен — сменить SITE, больше ничего.
robots.txt на адресе проекта лежит не в корне домена, и поисковики его там не читают: карту
сайта владелец отдаёт им сам в Вебмастере и Search Console; со своим доменом файл заработает.
Яндексу страницы из карты сайта называет IndexNow после каждой выкладки (`--ping`, шаг sajt.yml):
ему не нужен ни Вебмастер, ни вход владельца — права на сайт доказывает файл с ключом на самом сайте,
поэтому ключ открытый. Google IndexNow не принимает, а пинг карты сайта отключил в 2023 году —
ему карту отдаёт только Search Console.
Записи о «запрете слов» (slova, zamysel, shtraf) — только текст закона, как в боте: сайт к ним
не добавляет ни совета, ни «что делать».

    python -m src.sajt --build _site    собрать сайт в папку
    python -m src.sajt --selftest       страницы, ссылки, метки и границы — без сети
    python -m src.sajt --ping           назвать Яндексу страницы выложенного сайта (IndexNow)
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

from . import config, pamyatka, skleyka

SITE = "https://berg-creator.github.io/plenka/"
CODE = "https://github.com/berg-creator/plenka/blob/main/"
SOUND = config.ROOT / "assets" / "sajt"
MAIN = ("glavnyj-do.mp3", "glavnyj-posle.mp3")  # главный пример: бот свёл бесплатно
EXAMPLES_MAX = 3
FONTS = "https://fonts.googleapis.com/css2?family=Oswald:wght@500;600;700&display=swap"
# Подтверждение прав на сайт: тег пришлёт Вебмастер Яндекса и Search Console — вставить сюда значение
# content из их <meta>. Пусто — тега нет.
VERIFY = {"yandex-verification": "", "google-site-verification": "5N4ix15mKNEyY_K91yrGlyapvMQ0ocXvHlnzaDlegbc"}
INDEXNOW = "https://yandex.com/indexnow"
KEY = "77f668f6f32aa68ca3470f9473adadc5"  # ключ IndexNow: лежит файлом <KEY>.txt в корне сайта
# Метки ссылок в бота: раздел, куда ведёт ссылка, + «_sajt». Каждая стоит в service.SOURCES — сверяет селфтест.
START = {"skleyka": "skleyka_sajt", "bity": "bity_sajt", "ocenka": "ocenka_sajt", pamyatka.RUBRIC: "pamyatka_sajt"}
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


def page(path: str, title: str, description: str, body: str, player: bool = False) -> str:
    """Страница целиком. path — адрес от корня сайта («», «pamyatka/», «pamyatka/free/»).
    player — подключить плеер ДО/ПОСЛЕ: класс js ставится до отрисовки, только где Web Audio есть,
    иначе остаются обычные <audio> и вид не мигает."""
    up = "../" * path.count("/")
    home = up or "./"
    meta = "".join(f'<meta name="{name}" content="{esc(value)}">\n' for name, value in VERIFY.items() if value)
    # Открытый раздел подсвечен в шапке: сама страница раздела — «page», запись ПАМЯТКИ — «true» (она внутри раздела).
    here = ' aria-current="page"' if path in ("", "pamyatka/") else ' aria-current="true"'
    script = ("<script>if(window.AudioContext||window.webkitAudioContext)document.documentElement.className='js'</script>\n"
              f'<script src="{up}player.js" defer></script>\n') if player else ""
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
<meta name="theme-color" content="#17151b">
{meta}<link rel="icon" href="{up}icon.png" type="image/png">
<link rel="apple-touch-icon" href="{up}icon.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{html.escape(FONTS)}">
<link rel="stylesheet" href="{up}style.css">
{script}</head>
<body>
<header class="top"><div class="wrap bar">
<a class="brand" href="{home}" aria-label="ПЛЁНКА"><video src="{up}wheel.mp4" poster="{up}icon.png" width="32" height="32" autoplay muted loop playsinline aria-hidden="true"></video><span>ПЛЁНКА</span></a>
<nav><a href="{home}"{here if path == "" else ""}>Сведение</a><a href="{up}pamyatka/"{here if path.startswith("pamyatka/") else ""}>Памятка</a></nav>
<a class="go" href="{bot('skleyka')}"><span class="ico">🎛</span><span>Свести<span class="wide"> бесплатно</span></span></a>
</div></header>
<main>
{body}
</main>
<footer><div class="wrap">
<p>ПЛЁНКА — музыкальный канал <a href="https://t.me/{config.CHANNEL_HANDLE.lstrip('@')}">{config.CHANNEL_HANDLE}</a>
и бот <a href="{bot('skleyka')}">{config.BOT_HANDLE}</a> в Telegram.</p>
<p><a href="{home}">Сведение</a> · <a href="{up}pamyatka/">Памятка артиста</a> · <a href="{bot('bity')}">Биты</a> · <a href="{bot('ocenka')}">Оценка трека</a></p>
</div></footer>
</body>
</html>
"""


def button(href: str, words: str, small: str = "") -> str:
    """Кнопка в бота. Значок в начале строки — отдельно: в узком шрифте пробел за ним пропадал."""
    tail = f'<span class="small">{esc(small)}</span>' if small else ""
    icon, _, rest = words.partition(" ")
    label = f'<span class="ico">{esc(icon)}</span> <span>{esc(rest)}</span>' if rest and not icon[0].isalnum() else esc(words)
    return f'<p class="cta"><a class="button" href="{href}">{label}</a>{tail}</p>'


PLAY = ('<svg viewBox="0 0 24 24" aria-hidden="true"><path class="i-play" d="M8 5v14l11-7z"/>'
        '<path class="i-pause" d="M7 5h4v14H7zM13 5h4v14h-4z"/></svg>')


def player(files: tuple[str, str], sides: tuple[str, str], mark: str, caption: str, lazy: bool = False) -> str:
    """Плеер-переключатель: data-* читает player.js, внутри .ab-plain — запасной вид без скрипта."""
    do, posle = (f"zvuk/{name}" for name in files)
    return f"""<figure class="ab" data-do="{do}" data-posle="{posle}" data-do-label="{esc(sides[0])}" data-posle-label="{esc(sides[1])}"{' data-lazy' if lazy else ''}>
<p class="mark">{esc(mark)}</p>
<div class="ab-live">
<button class="ab-wave" type="button" aria-label="Переключить ДО и ПОСЛЕ"><span class="ab-side"><b class="ab-word">ДО</b><span class="ab-what">{esc(sides[0])}</span></span><canvas></canvas></button>
<div class="ab-ctrl">
<button class="ab-play" type="button" aria-label="Играть">{PLAY}</button>
<span class="ab-switch" role="group" aria-label="Что слушать"><button type="button" data-side="do" aria-pressed="true">ДО</button><button type="button" data-side="posle" aria-pressed="false">ПОСЛЕ</button></span>
<span class="ab-hint">Нажми на запись, чтобы сравнить</span>
</div>
</div>
<div class="ab-plain">
<p class="side">ДО — {esc(sides[0])}</p><audio controls preload="none" src="{do}"></audio>
<p class="side">ПОСЛЕ — {esc(sides[1])}</p><audio controls preload="none" src="{posle}"></audio>
</div>
<figcaption>{esc(caption)}</figcaption>
</figure>"""


def home() -> str:
    days, tweaks, mb = config.SKLEYKA_PER_DAY, config.SKLEYKA_TWEAKS, config.SKLEYKA_MAX_MB
    low, high = skleyka.BEAT_MINUTES
    rub, term = config.SKLEYKA_HAND_RUB[0], config.SKLEYKA_HAND_TERM
    styles = "".join(f"<li><b>{esc(name)}</b><span>{esc(about)}</span></li>" for name, about in skleyka.STYLE_HINTS.items())
    free = (f"Бесплатно — {plural(days, 'трек', 'трека', 'треков')} в сутки и "
            f"{plural(tweaks, 'пересборка', 'пересборки', 'пересборок')} на трек.")
    main = player(MAIN, ("голос просто положен на бит", "свёл бот"), "Бесплатно · бот",
                  "Записано на телефон. ДО — голос просто положен на бит, ПОСЛЕ — то же место, свёл бот. "
                  "Одной громкости.")
    pairs = "".join(player((f"primer-{n}-do.mp3", f"primer-{n}-posle.mp3"), ("свёл бот", "звукорежиссёр"),
                           f"Пример {n} · платно", "ДО — бот бесплатно, ПОСЛЕ — то же место у звукорежиссёра.",
                           lazy=True) for n in examples())
    paid = f"""<section class="paid"><div class="wrap"><div class="paid-box">
<div class="paid-text">
<p class="price">Платно · от {rub} ₽</p>
<h2>Хочешь ещё лучше — живой звукорежиссёр</h2>
<p>Это уже не бот: трек сводит человек, звукорежиссёр ПЛЁНКИ. От {rub} ₽, готово {esc(term)}.
Заказ — кнопкой «🎧 Отдать звукорежиссёру» под готовым треком в боте.</p>
<p class="note">В примерах ДО — кусок трека так, как его бесплатно свёл бот. ПОСЛЕ — то же место у звукорежиссёра.</p>
</div>
<div class="pairs">{pairs}</div>
</div></div></section>""" if pairs else ""
    body = f"""<section class="hero wrap">
<div class="hero-text">
<h1>Свести голос с битом <em>бесплатно</em> — в Telegram</h1>
<p class="lead">СВЕДЕНИЕ — бот ПЛЁНКИ: присылаешь вокал и бит, получаешь готовый трек. Автоматом, за несколько минут.</p>
{button(bot('skleyka'), '🎛 Свести бесплатно — в Telegram')}
</div>
{main}
<p class="note hero-note">Бот сводит подписчикам канала {config.CHANNEL_HANDLE}: без подписки он попросит подписаться. {free}</p>
</section>
<section class="block"><div class="wrap">
<h2>Как это работает</h2>
<ol class="steps">
<li><b>Открой бота</b> {config.BOT_HANDLE} и нажми «🎛 СВЕДЕНИЕ».</li>
<li><b>Пришли вокал и бит</b> Файлами WAV, FLAC или MP3 до {mb} МБ, по дорожкам (вокал, даблы, бэки, эдлибы, бит)
или ссылкой на Яндекс Диск, Dropbox, Google Диск. Выгружай дорожки с начала проекта — голос встанет в бит, как в проекте.</li>
<li><b>Получи готовый трек</b> Не так — поправь кнопками или напиши словами, как другу: «голос входит на дропе»,
«хочу погрязнее», «как у Travis Scott».</li>
</ol>
</div></section>
<section class="block"><div class="wrap">
<h2>Звук на выбор</h2>
<p class="sub">Выбираешь до сведения — кнопкой в боте.</p>
<ul class="styles">{styles}</ul>
</div></section>
<section class="block"><div class="wrap split">
<h2>Вопросы</h2>
<div class="faq">
<details><summary><h3>Это правда бесплатно?</h3></summary>
<p>Да. {free} Бит — от {low} до {high} минут. Упрёшься в лимит — позови артиста: за его первый трек тебе ещё один.
Или докупи треки за звёзды Telegram: {config.SKLEYKA_STARS_PACK} ⭐ — ещё {plural(config.SKLEYKA_PACK, 'трек', 'трека', 'треков')} на сутки,
{config.SKLEYKA_STARS_MONTH} ⭐ — 30 дней по {plural(config.SKLEYKA_MONTH_PER_DAY, 'трек', 'трека', 'треков')} в сутки.
За звёзды — только больше треков: звук тот же, что бесплатно.</p></details>
<details><summary><h3>Дорожки на облаке и в архиве?</h3></summary>
<p>Яндекс Диск, Dropbox или файл Google Диска — папкой или архивом zip, 7z, всего до {config.SKLEYKA_LINK_MB // 1024} ГБ
и {plural(config.SKLEYKA_LINK_FILES, 'файла', 'файлов', 'файлов')}. Делить на дорожки не надо: бот разложит по именам файлов —
vocal, beat, adlib, bass, kick… или по-русски.</p></details>
<details><summary><h3>Нет бита?</h3></summary>
<p>На шаге бита — «🔎 Нет бита — найти бесплатный»: бот найдёт на YouTube биты как у нужного артиста, которые продюсеры
отдают бесплатно и для релиза, и даст ссылки. А в «🎚 БИТЫ» — биты ПЛЁНКИ: бесплатно, можно в релиз, условия — у каждого бита.</p></details>
<details><summary><h3>Голос записан на чужом бите?</h3></summary>
<p>«🔁 Голос записан на чужом бите»: пришли старый бит — бот найдёт бесплатный того же темпа и перенесёт голос на него
(темп — до ±{skleyka.SWAP_TEMPO:.0%}).</p></details>
<details><summary><h3>Можно ли выпустить трек на free-бите?</h3></summary>
<p>Смотря что написано в описании бита — <a href="pamyatka/free/">разбор с цитатами закона</a> в ПАМЯТКЕ.</p></details>
</div>
</div></section>
<section class="block"><div class="wrap">
<h2>Ещё в боте</h2>
<ul class="doors">
<li><a href="{bot('bity')}"><b>🎚 БИТЫ</b><span>Биты ПЛЁНКИ, бесплатно, можно в релиз.</span></a></li>
<li><a href="{bot('ocenka')}"><b>📏 ОЦЕНКА</b><span>Пришли готовый трек: бот замерит его и скажет, чем он отличается от выпущенных релизов.</span></a></li>
<li><a href="pamyatka/"><b>⚖️ ПАМЯТКА</b><span>Права на бит и трек, запись голоса и что в законе о «запрете слов»: цитаты закона.</span></a></li>
</ul>
{button(bot('skleyka'), '🎛 Свести трек в боте')}
</div></section>
{paid}"""
    title = "Свести трек бесплатно: голос и бит в готовый трек | ПЛЁНКА"
    description = (f"Telegram-бот ПЛЁНКИ сводит вокал и бит в готовый трек: бесплатно, автоматом, за несколько минут. "
                   f"{plural(days, 'трек', 'трека', 'треков')} в сутки, правки словами.")
    return page("", title, description, body, player=True)


def _sources(items: list[str]) -> str:
    """Источник из кода бота — ссылкой на файл в открытом репозитории: правило проверяется там же."""
    def one(text: str) -> str:
        match = re.match(r"(src/[\w/]+\.py)(.*)", text, re.S)
        return f'<a href="{CODE}{match[1]}">{match[1]}</a>{esc(match[2])}' if match else esc(text)
    return "".join(f"<li>{one(text)}</li>" for text in items)


def memo(item: dict, items: list[dict]) -> str:
    """Запись ПАМЯТКИ: вопрос, запись тем же текстом, что в боте, источники, оговорка о юристе у записей
    о правах (в боте она — над их списком) и одна строка в бота — своя строка записи или призыв раздела.
    Сбоку на компьютере — все вопросы той же темы, открытый подсвечен: колонка для чтения узкая, и место справа пустовало."""
    door = item.get("start", "").partition("_")[0]
    words, where = (item["bot"], door) if item.get("bot") and door in START else (pamyatka.CALL, pamyatka.RUBRIC)
    text = "".join(f"<p>{esc(part)}</p>" for part in [item.get("short", ""), *item["text"]] if part)  # простой ответ — первым
    note = f'<p class="note">{esc(pamyatka.NOTE)}</p>' if item.get("topic") == pamyatka.LAW else ""
    here = ' aria-current="page"'
    near = "".join(f'<li><a href="../{other["id"]}/"{here if other is item else ""}>{esc(other.get("ask") or other["title"])}</a></li>'
                   for other in items if other.get("topic") == item.get("topic"))
    body = f"""<div class="wrap memo"><article class="read">
<p class="kicker"><a href="../">ПАМЯТКА</a> · {esc(pamyatka.TOPICS.get(item.get('topic'), ''))}</p>
<h1>{esc(item.get('ask') or item['title'])}</h1>
<p class="headline">{esc(item['title'][:1].upper() + item['title'][1:])}</p>
{text}
<h2>Источники</h2>
<ul class="sources">{_sources(item.get('sources', []))}</ul>
{note}
{button(bot(where), words, f'Telegram-бот {config.BOT_HANDLE}')}
<p class="back"><a href="../">← Все вопросы ПАМЯТКИ</a></p>
</article>
<aside class="near"><h2>{esc(pamyatka.TOPICS.get(item.get('topic'), 'ПАМЯТКА'))}</h2><ul class="list">{near}</ul></aside>
</div>"""
    title = f"{item.get('ask') or item['title']} — ПАМЯТКА артиста | ПЛЁНКА"
    return page(f"pamyatka/{item['id']}/", title, describe(" ".join([item.get("short", ""), *item["text"]])), body)


def memos(items: list[dict]) -> str:
    blocks = []
    for topic, name in pamyatka.TOPICS.items():
        rows = "".join(f'<li><a href="{item["id"]}/">{esc(item.get("ask") or item["title"])}</a></li>'
                       for item in items if item.get("topic") == topic)
        blocks.append(f'<div class="topic"><h2>{pamyatka.ICONS[topic]} {esc(name)}</h2>\n<ul class="list">{rows}</ul></div>')
    body = f"""<section class="wrap">
<div class="read">
<h1>ПАМЯТКА артиста</h1>
<p class="lead">{esc(pamyatka.INTRO)}</p>
<p class="note">{esc(pamyatka.NOTE)}</p>
</div>
<div class="topics">
{chr(10).join(blocks)}
</div>
{button(bot(pamyatka.RUBRIC), pamyatka.CALL, f'те же ответы в боте {config.BOT_HANDLE}')}
</section>"""
    title = "ПАМЯТКА артиста: права на бит и трек, запись голоса | ПЛЁНКА"
    description = (f"{plural(len(items), 'короткий ответ', 'коротких ответа', 'коротких ответов')} с цитатами закона: "
                   "можно ли выпустить трек на free-бите, как делить фит, что в законе о «запрете слов», как записать голос дома.")
    return page("pamyatka/", title, description, body)


# Цвета — из роликов ПЛЁНКИ: тёмный фон, тёплый жёлтый «ПОСЛЕ», волна от розово-красного к жёлтому.
# Тема одна, тёмная, как в роликах; волну рисует player.js теми же --rose и --gold.
CSS = """:root{--bg:#17151b;--panel:#211e26;--line:#34303b;--text:#f2ede4;--soft:#a9a2ae;--dim:#8c8695;
--gold:#ffb444;--rose:#ff3b6b;--on-gold:#1d1608;--paid:#1f1a12;--paid-line:#5c4727;
--head:"Oswald","Arial Narrow","Roboto Condensed",Impact,sans-serif;
--body:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;color-scheme:dark}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--text);font:17px/1.6 var(--body)}
a{color:var(--gold)}
a:focus-visible,button:focus-visible,summary:focus-visible{outline:2px solid var(--gold);outline-offset:3px}
.wrap{max-width:1180px;margin:0 auto;padding-left:16px;padding-right:16px}
h1,h2,h3{margin:0;text-wrap:balance}
h1,h2{font-family:var(--head);font-weight:700;letter-spacing:-.005em}
h1{font-size:clamp(40px,5vw,68px);line-height:1.02;margin-bottom:18px}
h2{font-size:clamp(28px,3.2vw,40px);line-height:1.1;margin-bottom:22px}
p{margin:0 0 14px}
.lead{font-size:19px;line-height:1.5;max-width:34em}
.note,.small,.sub{color:var(--soft);font-size:15px}
.cta{margin:26px 0 14px}
.button,.go{display:inline-flex;align-items:center;gap:10px;background:var(--gold);color:var(--on-gold);font-family:var(--head);
font-weight:600;text-decoration:none;border-radius:14px;transition:background .15s,transform .1s}
.ico{line-height:1}
.button{font-size:21px;padding:15px 26px;line-height:1.2}
.button:hover,.go:hover{background:#ffc66e}
.button:active,.go:active{background:#e89d2f;transform:translateY(1px)}
.small{display:block;margin-top:10px}
.top{position:sticky;top:0;z-index:5;background:rgba(23,21,27,.92);-webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px);
border-bottom:1px solid var(--line)}
.bar{display:flex;align-items:center;gap:22px;height:62px}
.brand{display:flex;align-items:center;gap:10px;margin-right:auto;color:var(--text);text-decoration:none;
font-family:var(--head);font-weight:700;font-size:23px;letter-spacing:.05em}
.brand video{border-radius:50%}
nav{display:flex;gap:22px}
nav a{color:var(--soft);text-decoration:none;padding:6px 0;border-bottom:2px solid transparent;transition:color .15s,border-color .15s}
nav a:hover{color:var(--text)}
nav a[aria-current]{color:var(--text);border-bottom-color:var(--gold)}
.go{font-size:17px;padding:8px 16px;white-space:nowrap;gap:7px}
h1 em{font-style:normal;color:var(--gold);background:linear-gradient(90deg,var(--rose),var(--gold));
-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}
.hero{display:grid;gap:26px;padding-top:26px;padding-bottom:48px}
.hero-note{margin:0}
.hero .cta{margin-top:22px}
.block{border-top:1px solid var(--line);padding:56px 0}
.steps{list-style:none;margin:0;padding:0;display:grid;gap:14px;counter-reset:step}
.steps li{counter-increment:step;background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:22px}
.steps li::before{content:counter(step);display:block;font-family:var(--head);font-weight:700;font-size:46px;line-height:1;
color:var(--gold);margin-bottom:14px}
.steps b{display:block;font-size:19px;margin-bottom:4px}
.sub{margin-top:-10px;margin-bottom:22px}
.styles{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.styles li{border-top:2px solid var(--line);padding:14px 2px 0}
.styles b{display:block;font-family:var(--head);font-weight:600;font-size:26px;line-height:1.2}
.styles span{color:var(--soft)}
.faq details{border-bottom:1px solid var(--line)}
.faq details:first-child{border-top:1px solid var(--line)}
summary{list-style:none;cursor:pointer;position:relative;padding:18px 44px 18px 0}
summary::-webkit-details-marker{display:none}
summary h3{font-size:19px;font-weight:650;line-height:1.35;transition:color .15s}
summary:hover h3{color:var(--gold)}
summary::after{content:"+";position:absolute;right:6px;top:10px;font-family:var(--head);font-size:32px;line-height:1;
color:var(--gold);transition:transform .2s}
details[open] summary::after{transform:rotate(45deg)}
details p{max-width:44em;padding-bottom:8px}
.doors{list-style:none;margin:0;padding:0;display:grid;gap:12px}
.doors a{display:block;height:100%;border:1px solid var(--line);border-radius:16px;padding:18px 20px;color:var(--text);
text-decoration:none;transition:border-color .15s,background-color .15s}
.doors a:hover,.doors a:active{border-color:var(--gold);background-color:var(--panel)}
.doors b{display:block;font-family:var(--head);font-weight:600;font-size:22px;margin-bottom:4px}
.doors b::after{content:"→";float:right;color:var(--dim);transition:color .15s,transform .15s}
.doors a:hover b::after{color:var(--gold);transform:translateX(3px)}
.doors span{color:var(--soft)}
.paid{padding:8px 0 64px}
.paid-box{background:var(--paid);border:1px solid var(--paid-line);border-radius:26px;padding:26px 18px;display:grid;gap:24px}
.price{display:inline-block;border:1px solid var(--gold);color:var(--gold);border-radius:999px;padding:3px 14px;font-size:15px;margin-bottom:18px}
.pairs{display:grid;gap:16px}
.paid .ab{background:#17130d;border-color:#3e3220}
.ab{margin:0;background:var(--panel);border:1px solid var(--line);border-radius:22px;padding:16px 16px 18px;
transition:border-color .3s;min-width:0}
.ab.is-after{border-color:rgba(255,180,68,.5)}
.mark{font-size:14px;color:var(--soft);margin-bottom:6px}
.ab-live{display:none}
.js .ab-live{display:block}
.js .ab-plain{display:none}
.js .ab-failed .ab-live{display:none}
.js .ab-failed .ab-plain{display:block}
.ab-wave{display:block;width:100%;padding:0;border:0;background:none;color:inherit;font:inherit;text-align:left;cursor:pointer;
-webkit-tap-highlight-color:transparent}
.ab-side{display:flex;align-items:baseline;flex-wrap:wrap;gap:4px 14px}
.ab-word{font-family:var(--head);font-weight:700;font-size:clamp(44px,5vw,66px);line-height:1;color:var(--dim);transition:color .3s}
.is-after .ab-word{color:var(--gold)}
.ab-what{color:var(--soft);font-size:16px}
.ab canvas{display:block;width:100%;height:120px;margin-top:12px}
.ab-ctrl{display:flex;align-items:center;flex-wrap:wrap;gap:10px 14px;margin-top:14px}
.ab-play{flex:none;width:52px;height:52px;border-radius:50%;border:0;background:var(--text);color:var(--bg);cursor:pointer;
display:grid;place-items:center}
.ab-play svg{width:24px;height:24px;fill:currentColor}
.ab-play:hover{background:#fff}.ab-play:active{transform:scale(.95)}
.ab-play .i-pause,.is-playing .ab-play .i-play{display:none}
.is-playing .ab-play .i-pause{display:inline}
.ab-switch{display:inline-flex;padding:3px;border:1px solid var(--line);border-radius:999px;background:var(--bg)}
.ab-switch button{border:0;background:none;color:var(--soft);font-family:var(--head);font-weight:600;font-size:17px;
padding:7px 16px;border-radius:999px;cursor:pointer;transition:color .3s,background-color .3s}
.ab-switch button:hover{color:var(--text)}
.ab-switch [data-side=do][aria-pressed=true]{background-color:#4c4754;color:var(--text)}
.ab-switch [data-side=posle][aria-pressed=true]{background:linear-gradient(90deg,var(--rose),var(--gold));color:var(--on-gold)}
.ab-hint{font-size:14px;color:var(--soft)}
.ab figcaption{font-size:14px;line-height:1.5;color:var(--soft);margin-top:14px}
.side{margin:10px 0 6px;font-size:15px;color:var(--soft)}
audio{width:100%}
.read{max-width:720px}
article.read{padding:28px 0 56px}
.read h1{font-size:clamp(32px,4.4vw,52px);line-height:1.08}
.read h2{font-size:26px;margin:36px 0 12px}
article.read p{font-size:18px;line-height:1.7}
.kicker{color:var(--soft);font-size:15px;margin-bottom:12px}
.kicker a{color:var(--soft)}
.headline{font-weight:700}
.sources{padding-left:20px;font-size:15px;color:var(--soft);overflow-wrap:anywhere}
.sources li{margin:6px 0}
.back{margin-top:24px}
section.wrap>.read{padding-top:28px}
.topics{display:grid;gap:8px 48px;margin-top:20px}
.topic h2{font-size:28px;margin:28px 0 8px}
.list{list-style:none;margin:0;padding:0}
.list a{display:block;padding:11px 0;border-bottom:1px solid var(--line);color:var(--text);text-decoration:none}
.list a:hover,.list a:active{color:var(--gold)}
.near .list a[aria-current]{color:var(--gold);font-weight:600;box-shadow:inset 3px 0 var(--gold);padding-left:12px}
.near h2{font-size:24px;margin-bottom:6px}
.near .list a{font-size:16px;padding:9px 0}
.near{padding-bottom:48px}
section.wrap>.cta{margin:40px 0 64px}
footer{border-top:1px solid var(--line);color:var(--soft);font-size:15px;padding:28px 0 44px}
footer a{color:var(--soft)}
@media (max-width:520px){.go .wide{display:none}.bar{gap:14px}nav{gap:14px}nav a{font-size:16px}.ab-hint{flex-basis:100%}
.hero{gap:18px;padding-top:22px}.lead{font-size:18px}.hero .cta{margin:18px 0 0}.hero .note{font-size:14px}
.button{font-size:18px;padding:14px 20px}
.ab-word{font-size:40px}.ab canvas{height:92px;margin-top:8px}.ab-ctrl{margin-top:10px}}
@media (min-width:700px){.wrap{padding-left:32px;padding-right:32px}.styles{grid-template-columns:repeat(4,minmax(0,1fr))}
.doors{grid-template-columns:repeat(3,minmax(0,1fr))}.paid-box{padding:40px}}
@media (min-width:900px){.hero{grid-template-columns:minmax(0,1fr) minmax(0,1fr);grid-template-areas:"text ab" "note ab";gap:0 64px;
padding-top:72px;padding-bottom:96px}.hero-text{grid-area:text;align-self:end}.hero>.ab{grid-area:ab;align-self:center}
.hero-note{grid-area:note;margin-top:4px}.ab{padding:22px 24px 24px}.ab canvas{height:150px}
.steps{grid-template-columns:repeat(3,minmax(0,1fr));gap:20px}.block{padding:80px 0}
.split{display:grid;grid-template-columns:300px minmax(0,1fr);gap:64px}
.paid-box{grid-template-columns:minmax(0,1fr) minmax(0,1.3fr);gap:56px;padding:56px;align-items:start}
.paid-text{position:sticky;top:96px}
.topics{display:block;columns:2;column-gap:56px}.topic{break-inside:avoid}.topic h2{margin-top:0;padding-top:28px}
.memo{display:grid;grid-template-columns:minmax(0,720px) minmax(0,1fr);gap:72px;align-items:start}
.near{position:sticky;top:90px;padding-top:40px}}
@media (max-width:430px){.brand span{display:none}}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
"""

# Плеер ДО/ПОСЛЕ. Обе записи одной длины играют разом через два усилителя, слышна одна: переключение меняет
# громкости за 30 мс, место в треке не теряется. Записи разбираются офлайн-контекстом — до нажатия звук
# не будится (Chrome ругается на AudioContext без жеста), живой контекст создаётся первым нажатием.
JS = r"""(function () {
  var AC = window.AudioContext || window.webkitAudioContext;
  var Off = window.OfflineAudioContext || window.webkitOfflineAudioContext;
  if (!AC || !Off || !window.fetch) return;
  var ctx = null, live = null, list = [];
  var calm = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;

  function sound() {
    if (!ctx) {
      // Без этого iPhone с выключенным звонком Web Audio не играет.
      if (navigator.audioSession) navigator.audioSession.type = 'playback';
      ctx = new AC();
    }
    if (ctx.state !== 'running') ctx.resume();
    return ctx;
  }

  function decode(url) {
    return fetch(url).then(function (r) {
      if (!r.ok) throw new Error(url + ' ' + r.status);
      return r.arrayBuffer();
    }).then(function (data) {
      return new Promise(function (ok, fail) { new Off(2, 1, 44100).decodeAudioData(data, ok, fail); });
    });
  }

  function peaks(buf, n) {
    var a = buf.getChannelData(0), b = buf.numberOfChannels > 1 ? buf.getChannelData(1) : a;
    var step = Math.floor(a.length / n), out = [];
    for (var i = 0; i < n; i++) {
      var sum = 0, k = 0;
      for (var j = i * step, e = j + step; j < e; j += 4, k++) {
        var v = (a[j] + b[j]) / 2;
        sum += v * v;
      }
      out.push(Math.sqrt(sum / Math.max(1, k)));
    }
    return out;
  }

  function Player(el) {
    var self = this;
    this.el = el; this.side = 'do'; this.mix = 0; this.want = false; this.playing = false; this.offset = 0;
    this.canvas = el.querySelector('canvas');
    this.word = el.querySelector('.ab-word');
    this.what = el.querySelector('.ab-what');
    this.hint = el.querySelector('.ab-hint');
    this.play_ = el.querySelector('.ab-play');
    this.keys = el.querySelectorAll('[data-side]');
    el.querySelector('.ab-wave').addEventListener('click', function () {
      if (self.playing) self.flip(self.side === 'do' ? 'posle' : 'do'); else self.play();
    });
    this.play_.addEventListener('click', function () { if (self.want) self.pause(); else self.play(); });
    Array.prototype.forEach.call(this.keys, function (key) {
      key.addEventListener('click', function () { self.flip(key.getAttribute('data-side')); if (!self.want) self.play(); });
    });
    this.draw();
  }

  Player.prototype.load = function () {
    var self = this, el = this.el;
    if (!this.loading) {
      this.loading = Promise.all([decode(el.getAttribute('data-do')), decode(el.getAttribute('data-posle'))])
        .then(function (bufs) {
          self.bufs = bufs;
          self.dur = Math.min(bufs[0].duration, bufs[1].duration);
          self.draw();
          return bufs;
        });
      // Не загрузилось — обычные <audio>: послушать можно и без переключателя.
      this.loading.catch(function () { el.classList.add('ab-failed'); });
    }
    return this.loading;
  };

  Player.prototype.play = function () {
    var self = this, c = sound();
    if (live && live !== this) live.pause();
    live = this; this.want = true; this.show();
    if (!this.bufs) this.hint.textContent = 'Загружаю запись…';
    this.load().then(function (bufs) {
      if (!self.want || self.playing) return;
      self.hint.textContent = 'Нажми на запись, чтобы сравнить';
      var t = c.currentTime + 0.05;
      self.nodes = bufs.map(function (buf, i) {
        var g = c.createGain(), s = c.createBufferSource();
        g.gain.value = (i === 0) === (self.side === 'do') ? 1 : 0;
        s.buffer = buf; s.loop = true; s.loopStart = 0; s.loopEnd = self.dur;
        s.connect(g); g.connect(c.destination); s.start(t, self.offset);
        return { g: g, s: s };
      });
      self.started = t - self.offset; self.playing = true; self.show(); self.tick();
    });
  };

  Player.prototype.pos = function () {
    if (!this.dur) return 0;
    return this.playing ? Math.max(0, ctx.currentTime - this.started) % this.dur : this.offset;
  };

  Player.prototype.pause = function () {
    this.want = false;
    if (this.playing) {
      this.offset = this.pos();
      this.nodes.forEach(function (x) { x.s.stop(); x.g.disconnect(); });
      this.playing = false;
    }
    this.show(); this.draw();
  };

  Player.prototype.flip = function (side) {
    if (side === this.side) return;
    this.side = side;
    if (this.playing) {
      var now = ctx.currentTime;
      this.nodes.forEach(function (x, i) {
        var p = x.g.gain;
        p.cancelScheduledValues(now); p.setValueAtTime(p.value, now);
        p.linearRampToValueAtTime((i === 0) === (side === 'do') ? 1 : 0, now + 0.03);
      });
    }
    this.show(); this.tick();
  };

  Player.prototype.show = function () {
    var after = this.side === 'posle';
    this.el.classList.toggle('is-after', after);
    this.el.classList.toggle('is-playing', this.want);
    this.word.textContent = after ? 'ПОСЛЕ' : 'ДО';
    this.what.textContent = this.el.getAttribute(after ? 'data-posle-label' : 'data-do-label');
    this.play_.setAttribute('aria-label', this.want ? 'Пауза' : 'Играть');
    var side = this.side;
    Array.prototype.forEach.call(this.keys, function (key) {
      key.setAttribute('aria-pressed', String(key.getAttribute('data-side') === side));
    });
  };

  Player.prototype.tick = function () {
    var self = this;
    if (this.raf) return;
    var last = performance.now();
    function step(now) {
      self.raf = 0;
      var goal = self.side === 'posle' ? 1 : 0, d = goal - self.mix;
      self.mix += calm ? d : Math.max(-1, Math.min(1, d / Math.abs(d || 1))) * Math.min(Math.abs(d), (now - last) / 280);
      last = now;
      self.draw();
      if (self.playing || self.mix !== goal) self.raf = requestAnimationFrame(step);
    }
    this.raf = requestAnimationFrame(step);
  };

  Player.prototype.draw = function () {
    var cv = this.canvas, w = cv.clientWidth, h = cv.clientHeight, dpr = window.devicePixelRatio || 1;
    if (!w || !h) return;
    if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) {
      cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
    }
    var g = cv.getContext('2d'), n = Math.max(30, Math.floor(w / 5)), mix = this.mix;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, h);
    if (this.bufs && (!this.bars || this.bars.n !== n)) {
      var a = peaks(this.bufs[0], n), b = peaks(this.bufs[1], n), top = 1e-6;
      for (var k = 0; k < n; k++) top = Math.max(top, a[k], b[k]);
      // Громкость окна, а не пик: у сведённого бита пики ровные, и волна читалась бы штрихкодом.
      var shape = function (v) { return Math.pow(v / top, 1.8); };
      this.bars = { n: n, a: a.map(shape), b: b.map(shape) };
    }
    var heard = this.playing || this.offset > 0, at = this.dur ? this.pos() / this.dur : 0, mid = h / 2;
    var grad = g.createLinearGradient(0, 0, w, 0);
    grad.addColorStop(0, '#ff3b6b'); grad.addColorStop(1, '#ffb444');
    var layers = [['#6f6979', 1 - mix], [grad, mix]];
    for (var l = 0; l < 2; l++) {
      if (layers[l][1] <= 0.01) continue;
      g.fillStyle = layers[l][0];
      for (var i = 0; i < n; i++) {
        var amp = this.bars ? this.bars.a[i] * (1 - mix) + this.bars.b[i] * mix : 0.03;
        var y = Math.max(1, amp * (mid - 2)), x = i * w / n;
        g.globalAlpha = layers[l][1] * (!heard || (i + 0.5) / n <= at ? 1 : 0.38);
        g.fillRect(x, mid - y, 3, y * 2);
      }
    }
    if (heard && this.dur) {
      g.globalAlpha = 1; g.fillStyle = '#f2ede4';
      g.fillRect(Math.min(w - 2, at * w), 0, 2, h);
    }
    g.globalAlpha = 1;
  };

  Array.prototype.forEach.call(document.querySelectorAll('.ab'), function (el) {
    var p = new Player(el);
    list.push(p);
    if (!el.hasAttribute('data-lazy')) p.load();
    else if ('IntersectionObserver' in window) {
      var io = new IntersectionObserver(function (seen) {
        if (seen.some(function (s) { return s.isIntersecting; })) { io.disconnect(); p.load(); }
      }, { rootMargin: '300px' });
      io.observe(el);
    }
  });
  window.addEventListener('resize', function () { list.forEach(function (p) { p.draw(); }); });
})();
"""


def build(out: Path) -> list[str]:
    """Собрать сайт в out, вернуть адреса страниц — те же, что в карте сайта."""
    items = pamyatka.load()
    pages = {"": home(), "pamyatka/": memos(items), **{f"pamyatka/{item['id']}/": memo(item, items) for item in items}}
    if out.exists() and any(out.iterdir()):
        # Чистится только прежняя сборка: опечатка в --build не должна стереть чужую папку.
        if not (out / "sitemap.xml").exists():
            raise SystemExit(f"{out} не пуста и не похожа на сборку сайта — не трогаю")
        shutil.rmtree(out)
    for path, text in pages.items():
        (out / path).mkdir(parents=True, exist_ok=True)
        (out / path / "index.html").write_text(text)
    (out / "style.css").write_text(CSS)
    (out / "player.js").write_text(JS)
    shutil.copy(SOUND / "icon.png", out / "icon.png")
    # колесо крутится, как аватарка канала: только кольцо, кнопки плеера стоят (src/make_avatar_video.py)
    shutil.copy(SOUND / "wheel.mp4", out / "wheel.mp4")
    (out / "zvuk").mkdir()
    sounds = [*MAIN, *(f"primer-{n}-{side}.mp3" for n in examples() for side in ("do", "posle"))]
    for name in sounds:
        shutil.copy(SOUND / name, out / "zvuk" / name)
    urls = "".join(f"<url><loc>{SITE}{path}</loc></url>\n" for path in pages)
    (out / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n'
                                     f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{urls}</urlset>\n')
    (out / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: {SITE}sitemap.xml\n")
    (out / f"{KEY}.txt").write_text(KEY)
    return list(pages)


def ping() -> None:
    """Назвать Яндексу страницы выложенного сайта: адреса — из живой карты сайта, а не из сборки."""
    fetch = lambda url: urllib.request.urlopen(url, timeout=30).read().decode()
    # Без ключа на сайте Яндекс отвергнет запрос не сразу, а молча при проверке — поэтому сверка до него.
    if fetch(f"{SITE}{KEY}.txt").strip() != KEY:
        raise SystemExit("sajt: ключа IndexNow на сайте нет — выкладка не дошла")
    urls = re.findall(r"<loc>([^<]+)</loc>", fetch(f"{SITE}sitemap.xml"))
    body = {"host": urllib.parse.urlsplit(SITE).netloc, "key": KEY, "keyLocation": f"{SITE}{KEY}.txt", "urlList": urls}
    request = urllib.request.Request(INDEXNOW, json.dumps(body).encode(), {"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(request, timeout=30) as answer:
        print(f"sajt: IndexNow ответил {answer.status}, страниц {len(urls)}")


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
            assert "@import" not in text and (("<script" in text) == (path == "")), f"скрипт — только плеер главной: {path}"
            low = text.casefold()
            assert not [genre for genre in GENRES if genre in low], f"канал жанрами не описываем: {path}"
            assert config.SKLEYKA_HAND_ENGINEER not in text, f"ник звукорежиссёра — только в боте: {path}"
            assert f'class="go" href="{bot("skleyka")}"' in text, f"кнопка «Свести» — в шапке каждой страницы: {path}"
            lit = re.findall(r'<a [^>]*aria-current="[^"]+">([^<]+)</a>', re.search(r"<nav>.+?</nav>", text)[0])
            assert lit == ["Сведение" if path == "" else "Памятка"], f"в шапке подсвечен открытый раздел: {path}: {lit}"
            # Ссылки: внутренние ведут на файлы сборки, в бота — метками сайта, известными service.SOURCES.
            for link in re.findall(r'(?:href|src|data-do|data-posle)="([^"]+)"', text):
                if link.startswith(f"https://t.me/{config.BOT_HANDLE.lstrip('@')}"):
                    label = link.partition("?start=")[2]
                    assert label in START.values() and label in service.SOURCES and "сайт" in service.SOURCES[label], link
                elif not link.startswith(("https://", "http://")):
                    target = (out / path / link).resolve()
                    assert (target / "index.html" if target.is_dir() else target).exists(), f"{path}: {link}"
                else:
                    assert link.startswith((SITE, CODE, "https://t.me/", "https://fonts.googleapis.com",
                                            "https://fonts.gstatic.com")), f"чужой адрес: {path}: {link}"
        home_text = (out / "index.html").read_text()
        assert f"{config.SKLEYKA_PER_DAY} трек" in home_text and config.CHANNEL_HANDLE in home_text, "лимит и подписка — из config"
        # Бот сводит ffmpeg, а не нейросетью: о сведении так не пишем.
        assert not re.search(r"нейросет|\bИИ\b", home_text), "сведение — не нейросеть"
        # Главный пример — первым экраном, плеер-переключатель с обоими файлами; под ним — платные пары каталога.
        assert examples() and all((out / "zvuk" / name).exists() for name in MAIN), "главный пример: оба файла"
        players = re.findall(r'<figure class="ab" data-do="([^"]+)" data-posle="([^"]+)"', home_text)
        assert players[0] == tuple(f"zvuk/{name}" for name in MAIN) and len(players) == 1 + len(examples()), players
        assert home_text.index('class="ab"') < home_text.index('class="block"') < home_text.index('class="paid"'), \
            "главный пример — в первом экране, звукорежиссёр — отдельным блоком внизу"
        doors = re.search(r'<ul class="doors">(.+?)</ul>', home_text, re.S)[1]
        assert doors.count("<li><a href=") == doors.count("<li>") == 3, "карточки «Ещё в боте» — все ссылки, подсвечиваются одинаково"
        assert home_text.count("<audio") == 2 * len(players), "без скрипта — два обычных <audio> на плеер"
        assert 'src="player.js"' in home_text and all(word in (out / "player.js").read_text()
                                                      for word in ("decodeAudioData", "audioSession", "aria-pressed"))
        assert all(" " not in name and re.fullmatch(r"(primer-\d+|glavnyj)-(do|posle)\.mp3", name)
                   for name in (p.name for p in (out / "zvuk").iterdir())), "в именах звука ни имён, ни названий"
        for item in items:
            text = (out / "pamyatka" / item["id"] / "index.html").read_text()
            assert all(esc(part) in text for part in item["text"]) and esc(item.get("ask") or item["title"]) in text, item["id"]
            assert (esc(pamyatka.NOTE) in text) == (item["topic"] == pamyatka.LAW), f"оговорка о юристе — у прав: {item['id']}"
            assert len(re.findall(r'class="button"', text)) == 1, f"одна строка в бота: {item['id']}"
            line = re.search(r'class="button"[^>]*>(.+?)</a>', text)[1]
            line = re.sub(r"<[^>]+>", "", line)
            assert len(html.unescape(line)) <= pamyatka.LINE_MAX, f"строка в бота длиннее строки телефона: {line}"
            if item["id"] in LAW_ONLY:
                article = re.search(r"<article[^>]*>(.+)</article>", text, re.S)[1]
                # Своя строка у такой записи — только в проверку текста (zamysel): это не совет, а функция бота.
                assert "что делать" not in article.casefold() and item.get("start", "tekst_").startswith("tekst_"), \
                    f"только текст закона: {item['id']}"
        article = lambda name: re.search(r"<article[^>]*>(.+)</article>", (out / "pamyatka" / name / "index.html").read_text(), re.S)[1]
        assert "start=bity_sajt" in article("free"), "запись про бит — в биты"
        assert "start=skleyka_sajt" in article("shum"), "запись о голосе — в сведение"
        assert "start=pamyatka_sajt" in article("slova"), "без своей строки — в раздел"
        sitemap = (out / "sitemap.xml").read_text()
        assert sitemap.count("<loc>") == len(paths) and f"<loc>{SITE}pamyatka/free/</loc>" in sitemap
        assert f"Sitemap: {SITE}sitemap.xml" in (out / "robots.txt").read_text()
        assert (out / f"{KEY}.txt").read_text() == KEY and re.fullmatch(r"[0-9a-f]{32}", KEY)
        assert plural(2, "трек", "трека", "треков") == "2 трека" and plural(11, "а", "б", "в") == "11 в" \
            and plural(21, "а", "б", "в") == "21 а" and plural(64, "а", "б", "в") == "64 б"
        assert describe("слово " * 60).endswith("…") and len(describe("слово " * 60)) <= 156
    print("sajt: селфтест пройден")


def main() -> None:
    parser = argparse.ArgumentParser(description="Открытый сайт бота ПЛЁНКИ для поисковиков")
    parser.add_argument("--build", type=Path, metavar="ПАПКА", help="собрать сайт в папку (она очищается)")
    parser.add_argument("--selftest", action="store_true", help="проверить сборку без сети")
    parser.add_argument("--ping", action="store_true", help="назвать Яндексу страницы выложенного сайта (IndexNow)")
    args = parser.parse_args()
    if args.selftest:
        _selftest()
    elif args.ping:
        ping()
    elif args.build:
        paths = build(args.build)
        print(f"sajt: {len(paths)} страниц в {args.build}")
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
