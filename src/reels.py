"""Ролики с живым голосом владельца: сценарий по фразам → голосовые → пакет для заливки.

Формат для YouTube Shorts, TikTok и VK Клипов. Заливает владелец сам: групповым
ключом ВКонтакте видео не залить (см. clips.deliver), у TikTok открытой заливки
нет вовсе. Поэтому автоматика заканчивается пакетом в личке — ролик, превью
и текст полей, где каждое поле копируется одним касанием.

Голос живой, а не синтез (src/host.py), по тому же доводу, по которому из кадра
убрали нарисованную ведущую: машинное площадки метят, а живого человека
в этом не обвинить.

Путь одного ролика:

1. Сценарий (content/reels/<id>.json, бриф автора — prompts/reels.md) приходит
   пушем в ветку claude/reels-*. Облачный автор в main пушить не может, и ветка
   служит почтовым ящиком: воркфлоу reels.yml забирает сценарий в приватное
   хранилище, рассылает фразы и удаляет ветку.
2. Фразы уходят владельцу по одной, на каждую он отвечает голосовым. Сообщение
   на фразу, а не одно на весь текст: ответ на конкретное сообщение сам говорит,
   какой это кадр. Одно длинное голосовое пришлось бы резать по паузам, то есть
   гадать, где кончилась фраза, а неудачную фразу — перезаписывать с остальными.
3. Дубли лежат в приватном хранилище (STATE_DIR/reels/<id>/): голос человека —
   ровно то, чему в открытом репозитории не место.
4. Последний дубль запускает сборку отдельным запуском воркфлоу. Не в дежурстве:
   ffmpeg и сток — это минуты, а дежурство — единственный опросчик бота,
   и всё это время бот молчал бы.

Сборка — те же примитивы, что у клипов (src/clips.py): надписи, narrate с папкой
записанных фраз, склейка. А вид другой, и это решения владельца от 14.09.2026:
камкордерная обработка и затемнение превращали ролик в тёмную кашу, где мем
был маленькой картинкой посреди чёрного поля. Здесь картинка чистая и на весь
экран, под голосом качает бит, а сам голос проходит дикторскую обработку,
а не телефонную полосу. Марки канала в кадре нет вовсе: крутящаяся плёнка
в углу висела над каждым мемом и спорила с ним, а узнаёт ролик голос.

Каждый кадр обрезается под 9:16 вокруг главного (поле `focus`): горизонтальный
мем целиком поверх своей размытой копии смотрелся вставкой из чужой ленты.
Размытая подложка осталась только для панорам, от которых обрезка оставила бы
щель, — это запасной путь, а не вид ролика. Лица кадр не ищет: без OpenCV,
которого в зависимостях нет и не будет, это гадание, а автор сценария видит
гифку и одним числом говорит, где в ней герой.

Эффектов нет: голос робота и «слетевшую пластинку» владелец послушал на keef3
15.09.2026 и отверг оба. Бит — поле сценария `music`, без него любимый бит
владельца (BEAT), и только когда нет и его — случайный.

Картинки к фразе владелец может прислать сам — ответом на фразу, как голос.
Они заменяют кадры строки целиком, по порядку прихода, и режутся по центру
под 9:16, без размытой подложки: выбор его, и сборка его не переспрашивает.
Подпись к фото — не надпись в кадр, а комментарий для Claude, как картинку
переделать; она ложится рядом файлом .txt. Сборка по картинке не запускается:
владелец шлёт их пачкой и говорит «собери», когда закончил.

Кадры меняются каждые две-три секунды: у одной фразы их может быть до трёх.
Видео-мемы берутся с GIPHY по запросу при сборке — просьба владельца. Чистой
лицензии, как у стока (src/footage.py), у них нет, поэтому они живут только
здесь: ролик заливает сам владелец, а автоматика канала их не касается.
Реальные кадры события — фотографии со страниц источников по og:image, той же
дорогой, что картинка новости в канале. Видео чужих роликов не берутся вовсе.

    python -m src.reels --check content/reels/20260914-kanye.json    проверка без сети
    python -m src.reels --send content/reels/20260914-kanye.json --dry-run
    python -m src.reels --preview content/reels/20260914-kanye.json --voice ПАПКА
    python -m src.reels --build 20260914-kanye --dry-run             собрать, пакет в терминал
    python -m src.reels --selftest
"""

from __future__ import annotations

import argparse
import array
import html
import json
import logging
import math
import os
import random
import re
import subprocess
import tempfile
import wave
from datetime import datetime
from pathlib import Path

# Только лёгкое на уровне модуля: --check зовёт облачный автор перед пушем,
# и Pillow, ffmpeg или ключи ему для проверки полей не нужны. Сборка и Telegram
# подтягиваются там, где используются.
from . import config, state

log = logging.getLogger("reels")

KINDS = ("face", "photo", "stock", "gif", "meme", "card")
# Кадр из картинки владельца. Не в KINDS: сценарий его не заказывает,
# его подставляет сборка (with_pictures).
PIC = "pic"
# Бит по умолчанию: владелец выбрал его на сборке keef3 14.09.2026.
BEAT = "sound4stock-underground-urban-hip-hop-beat-464280.mp3"
MUSIC_FORMAT = re.compile(r"[\w.-]+\.(mp3|wav)")
BUILD_WORD = "собери"
# Кадров на фразу. Больше трёх на две-три секунды речи — уже мельтешение,
# глаз не успевает понять ни одного.
SCREENS_MAX = 3
GIPHY_ID = re.compile(r"[A-Za-z0-9]+")

# Название YouTube режет на ста знаках. Описание на площадках коротких роликов —
# подпись под видео; держим его в рамке подписи Telegram, 1024 знака: длиннее
# под роликом всё равно не читают, а пакет владельцу гарантированно влезает
# в одно сообщение. Теги YouTube принимает до пятисот знаков на все разом.
TITLE_MAX = 100
DESCRIPTION_MAX = 1024
TAGS_MAX = 500
PAUSE_MAX = 5.0

ID_FORMAT = re.compile(r"\d{8}-[a-z0-9-]+")
SLOT_FORMAT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}[+-]\d{2}:\d{2}")
HASHTAGS_AT_END = re.compile(r"(#\w+\s*)+$")

TODAY = "сегодня до 21:00 МСК"

# Нижняя граница кадра под фразой. Настоящую длину задаёт дубль (clips.narrate),
# эта нужна, чтобы и без дубля кадр было видно в превью.
SAY_SECONDS = 1.5
# До скольких знаков надпись идёт крупным кеглем.
BIG_TEXT = 20

# Карточка стоит на размытом соседнем кадре: чёрный прямоугольник в ленте
# выглядел провалом, а размытие оставляет цвет и не спорит с надписью.
CARD_BLUR = "gblur=sigma=30"
# Всё обрезается под 9:16. Шире этого — панорама, от которой в кадре осталась
# бы пятая часть, и только она встаёт целиком на размытую копию.
BLUR_WIDER = 2.4
# Мемная надпись (`caption`) — сверху, как в пересылаемых мемах, но ниже вкладок
# Shorts и TikTok: верхние двести с лишним точек занимает их интерфейс.
CAPTION_TOP = 260
CAPTION_PAD = 60
CAPTION_SIZES = ((150, 1), (128, 1), (112, 1), (96, 1), (88, 1), (112, 2), (96, 2), (80, 3))

GIPHY_SEARCH = "https://api.giphy.com/v1/gifs/search"
# Видео по id отдаётся без ключа: автор может закрепить конкретный мем.
GIPHY_MEDIA = "https://media.giphy.com/media/{}/giphy.mp4"
# og:image меньше этого — логотип издания, а не фотография (у XXL — 14 КБ).
PHOTO_MIN_BYTES = 30_000

# --- звук -----------------------------------------------------------------
# Дубль чистится до склейки: срез гула ниже 100 Гц и мягкий шумодав. На дублях
# 20260914-keef3 шипение выше 1,5 кГц в паузах падает на 9–12 дБ, а речь
# в той же полосе не меняется; агрессивнее (anlmdn) — голос уходит под воду.
DENOISE = "highpass=f=100,afftdn=nr=12:nf=-50:tn=1"
# Каждая фраза выравнивается по громкости: дубли пишутся в разное время
# и на разном расстоянии от телефона, у keef3 разброс был семь дБ.
VOICE_LUFS = -16.0
# Где кончается тишина: окна по 10 мс громче порога, подряд не меньше 40 мс.
# Порог — от выровненной речи, а не от нуля: фон с шумом громче -45 дБ, по
# которым резали раньше, и полсекунды тишины перед словом оставались.
# Короткий щелчок до фразы в четыре окна не укладывается.
SPEECH_DB = -38.0
SPEECH_RUN = 4
# Запас вокруг речи: до слова — чтобы не съесть атаку, после — затухание.
BEFORE_SPEECH = 0.08
AFTER_SPEECH = 0.15
# Воздух после дубля до склейки.
TAIL = 0.2
# Дикторская цепочка на склеенную дорожку: лёгкая компрессия, полка верхов
# и де-эссер после неё — подъём верхов сам добавляет свиста на «с» и «ш».
VOICE_CHAIN = (
    "acompressor=threshold=0.1:ratio=3:attack=5:release=80:makeup=2,"
    "highshelf=f=4500:g=2.5,deesser=i=0.4"
)
# Громкость бита до приглушения. Выше голоса по среднему: в паузах бит должен
# качать в полную силу, а разборчивость под речью держит сайдчейн.
BEAT_LUFS = -15.0
DUCK = "sidechaincompress=threshold=0.03:ratio=6:attack=10:release=250"


# --- проверка -------------------------------------------------------------


def _filled(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _slot(value) -> bool:
    if not isinstance(value, str) or not SLOT_FORMAT.fullmatch(value):
        return False
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


def _artist_names() -> set[str]:
    return {a.get("name", "") for a in state.read_json(config.ARTISTS_FILE, {}).get("artists", [])}


def _template_ok(template) -> bool:
    return _filled(template) and (config.MEME_TEMPLATES / f"{template}.jpg").is_file()


def screens(line: dict) -> list[dict]:
    """Кадры строки: `screen` бывает одним кадром или списком до трёх."""
    screen = line["screen"]
    return screen if isinstance(screen, list) else [screen]


def _screens_problems(screen, where: str, sources: list) -> list[str]:
    if not isinstance(screen, list):
        return _screen_problems(screen, where, sources)
    if not 1 <= len(screen) <= SCREENS_MAX:
        return [f"{where}: в screen от одного до {SCREENS_MAX} кадров"]
    return [error for number, one in enumerate(screen, 1)
            for error in _screen_problems(one, f"{where}, кадр {number}", sources)]


def _screen_problems(screen, where: str, sources: list) -> list[str]:
    if not isinstance(screen, dict):
        return [f"{where}: нет screen — что в кадре"]
    kind = screen.get("kind")
    if kind not in KINDS:
        return [f"{where}: screen.kind «{kind}» — бывает только {', '.join(KINDS)}"]
    if any(field in screen and not isinstance(screen[field], str)
           for field in ("label", "text", "query", "id", "template", "url", "caption")):
        return [f"{where}: label, text, caption, query, id, template и url — строки"]
    focus = screen.get("focus", 0.5)
    if isinstance(focus, bool) or not isinstance(focus, (int, float)) or not 0 <= focus <= 1:
        return [f"{where}: focus — где по ширине главное, число от 0 (левый край) до 1 (правый)"]
    if kind == "face":
        name = screen.get("name")
        if not _filled(name):
            return [f"{where}: у face нет name"]
        if name not in _artist_names():
            # По этому имени ищется фотография: «Канье» вместо «Kanye West»
            # оставит кадр без лица, а чужое похожее имя — с чужим лицом.
            return [f"{where}: «{name}» нет в data/artists.json — имя ровно как там, или кадр stock/card"]
    elif kind == "photo" and screen.get("url") not in sources:
        # Фото события — только со страницы, откуда взяты факты: картинка
        # с чужой страницы могла бы показать не то событие.
        return [f"{where}: у photo url — ссылка ровно из sources, картинка берётся с этой страницы"]
    elif kind in ("stock", "gif") and not _filled(screen.get("query")):
        return [f"{where}: у {kind} нет query — запрос по-английски"]
    elif kind == "gif" and "id" in screen and not GIPHY_ID.fullmatch(screen["id"]):
        return [f"{where}: id — код GIPHY из латиницы и цифр, как в конце ссылки на гифку"]
    elif kind in ("meme", "gif") and (kind == "meme" or "template" in screen) and not _template_ok(screen.get("template")):
        return [f"{where}: шаблона мема «{screen.get('template')}» нет в assets/meme/templates/"]
    elif kind == "card" and not _filled(screen.get("text")):
        return [f"{where}: у card нет text — надпись и есть кадр"]
    return []


def problems(script, name: str = "") -> list[str]:
    """Что не так со сценарием — понятными фразами. Пустой список — годен.

    Проверяется только то, что ломает конвейер или не пройдёт на площадке,
    и ничего, что требует сети: у облачного автора может не быть ни ключей,
    ни доступа наружу. Сверку фактов по источникам валидатор не заменяет —
    он требует источник, но прочитать его не может.
    """
    if not isinstance(script, dict):
        return ["сценарий — это JSON-объект"]
    errors = []

    reel_id = script.get("id")
    if not isinstance(reel_id, str) or not ID_FORMAT.fullmatch(reel_id):
        errors.append("id: вида ГГГГММДД-слово строчной латиницей, например 20260914-kanye")
    elif name and name != reel_id:
        errors.append(f"id «{reel_id}» не совпадает с именем файла «{name}.json»")

    if not _filled(script.get("topic")):
        errors.append("topic: нет темы")
    if script.get("publish") != "today" and not _slot(script.get("publish")):
        errors.append("publish: «today» или слот вида 2026-09-14T18:00+03:00")

    sources = script.get("sources")
    if not isinstance(sources, list) or not sources:
        errors.append("sources: нужен хотя бы один источник — ролик читают вслух, факт без источника не проходит")
    elif not all(isinstance(url, str) and url.startswith(("https://", "http://")) for url in sources):
        errors.append("sources: каждый источник — ссылка с http")

    title = script.get("title")
    if not _filled(title):
        errors.append("title: нет названия")
    elif len(title) > TITLE_MAX:
        errors.append(f"title: {len(title)} знаков, YouTube режет на {TITLE_MAX}")

    description = script.get("description")
    if not _filled(description):
        errors.append("description: нет описания")
    else:
        if len(description) > DESCRIPTION_MAX:
            errors.append(f"description: {len(description)} знаков, предел {DESCRIPTION_MAX}")
        if not HASHTAGS_AT_END.search(description.strip()):
            errors.append("description: в конце нужны хэштеги, например «… #фонк #рэп»")

    tags = script.get("tags")
    if not isinstance(tags, list) or not tags or not all(_filled(tag) for tag in tags):
        errors.append("tags: нужен список непустых строк")
    elif any("," in tag for tag in tags):
        errors.append("tags: запятая внутри тега — в пакете теги идут через запятую и разъедутся")
    elif len(", ".join(tags)) > TAGS_MAX:
        errors.append(f"tags: {len(', '.join(tags))} знаков вместе, YouTube принимает {TAGS_MAX}")

    # Есть ли файл, валидатор не знает: биты лежат в приватном хранилище,
    # которого у облачного автора нет. Нет файла — сборка возьмёт BEAT.
    if "music" in script and not (isinstance(script["music"], str) and MUSIC_FORMAT.fullmatch(script["music"])):
        errors.append(f"music: имя файла бита из plenka-state/audio, например {BEAT}")

    lines = script.get("lines") if isinstance(script.get("lines"), list) else []
    if not any(isinstance(line, dict) and _filled(line.get("say")) for line in lines):
        errors.append("lines: нет ни одной фразы — нужен хотя бы один say с текстом")
    for number, line in enumerate(lines, 1):
        where = f"строка {number}"
        if not isinstance(line, dict):
            errors.append(f"{where}: строка — это объект")
            continue
        if ("say" in line) == ("pause" in line):
            errors.append(f"{where}: нужно ровно одно из say и pause")
        elif "say" in line and not _filled(line["say"]):
            errors.append(f"{where}: пустая фраза")
        elif "pause" in line and not (
            isinstance(line["pause"], (int, float))
            and not isinstance(line["pause"], bool)
            and 0 < line["pause"] <= PAUSE_MAX
        ):
            errors.append(f"{where}: pause — секунды, больше нуля и не больше {PAUSE_MAX:g}")
        if not isinstance(line.get("hint", ""), str):
            errors.append(f"{where}: hint — строка")
        errors += _screens_problems(line.get("screen"), where, sources if isinstance(sources, list) else [])
    return errors


def load(path: Path) -> tuple[dict, list[str]]:
    """Сценарий из файла и его ошибки.

    Не state.read_json: тот прячет битый файл в .broken и молча отдаёт пустое —
    для состояния это спасение, а проверке нужно сказать, где JSON сломан.
    """
    try:
        script = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return {}, [f"не прочитать {path}: {exc.strerror}"]
    except json.JSONDecodeError as exc:
        return {}, [f"{path.name}: не JSON — строка {exc.lineno}, {exc.msg}"]
    return script, problems(script, path.stem)


def spoken_frames(script: dict) -> list[int]:
    """Номера кадров с голосом, с единицы. Паузы владелец не записывает."""
    return [number for number, line in enumerate(script["lines"], 1) if "say" in line]


def when(script: dict) -> str:
    return TODAY if script["publish"] == "today" else script["publish"]


# --- рассылка ------------------------------------------------------------


def header(script: dict) -> str:
    """Шапка рассылки: тема, срок, как записывать и где сверить факты."""
    sources = " · ".join(
        f'<a href="{html.escape(url)}">{number}</a>' for number, url in enumerate(script["sources"], 1)
    )
    return (
        f"<b>РОЛИК · {html.escape(script['topic'], quote=False)}</b>\n"
        f"Выложить: <b>{when(script)}</b>\n"
        f"<code>{script['id']}</code>\n\n"
        f"Фраз: {len(spoken_frames(script))}, каждая ниже отдельным сообщением. "
        "На каждую ответь голосовым: свайп влево по фразе и запись. Одна фраза — "
        "одно голосовое, тишину по краям сборка срежет сама. Отпускай кнопку через "
        "полсекунды после последнего слова, иначе его конец обрежется. "
        "Не понравился дубль — "
        "ответь на ту же фразу ещё раз.\n\n"
        "Картинки к фразе — тоже ответом на неё, фото или файлом: встанут вместо "
        "кадров по порядку. В подписи к фото можно написать, как её переделать, — "
        "в кадр подпись не попадёт. Прислал картинки — ответь на любую фразу "
        "словом «собери».\n\n"
        "Когда придут все голосовые, ролик соберётся сам и вернётся сюда с превью "
        "и текстом для заливки.\n\n"
        f"Сверить факты до записи: {sources}"
    )


def line_text(number: int, total: int, line: dict) -> str:
    text = f"<b>{number}/{total}</b> — {html.escape(line['say'], quote=False)}"
    if _filled(line.get("hint")):
        text += f"\n<i>{html.escape(line['hint'], quote=False)}</i>"
    return text


def send(script: dict, dry_run: bool) -> int:
    """Кладёт сценарий в приватное хранилище и рассылает фразы владельцу.

    Разосланный второй раз не уходит: перезапуск воркфлоу или повторный пуш
    той же ветки завалил бы личку дублями, а ответы на старые сообщения
    перестали бы находиться. Исправленный сценарий — под новым id.
    """
    folder = config.PRIVATE / "reels" / script["id"]
    if (folder / "sent.json").exists():
        print(f"Сценарий {script['id']} уже разослан — исправленный присылай под новым id.")
        return 0

    frames = spoken_frames(script)
    messages = [header(script)] + [
        line_text(number, len(frames), script["lines"][frame - 1])
        for number, frame in enumerate(frames, 1)
    ]
    if dry_run:
        print("\n\n———\n\n".join(messages))
        return 0

    from . import telegram

    admin = config.secret("TELEGRAM_ADMIN_ID")
    telegram.send_message(admin, messages[0])
    lines = {
        str(telegram.send_message(admin, text)["message_id"]): frame
        for frame, text in zip(frames, messages[1:])
    }
    # Отметка — после всей рассылки: есть sent.json, значит ушло всё. Оборвался
    # запуск посередине — перезапуск разошлёт заново, а не оставит полсценария.
    state.write_json(folder / "script.json", script)
    state.write_json(folder / "sent.json", {"sent_at": state.iso(), "lines": lines})
    print(f"Разослан {script['id']}: фраз {len(lines)}.")
    return 0


# --- приём дублей ---------------------------------------------------------


def take_file(message: dict) -> dict:
    """Голосовое, аудио или аудиофайл документом. Пустой словарь — голоса нет."""
    document = message.get("document") or {}
    if str(document.get("mime_type", "")).startswith("audio/"):
        return document
    return message.get("voice") or message.get("audio") or {}


def take_picture(message: dict) -> dict:
    """Фото (самое крупное из размеров) или картинка документом. Пустой — картинки нет."""
    document = message.get("document") or {}
    if str(document.get("mime_type", "")).startswith("image/"):
        return document
    return max(message.get("photo") or [{}], key=lambda size: size.get("width", 0) * size.get("height", 0))


def reply_kind(message: dict) -> str:
    """Что пришло ответом на фразу: voice, picture, build или пустая строка."""
    if take_file(message):
        return "voice"
    if take_picture(message):
        return "picture"
    if str(message.get("text", "")).strip(" .!").lower() == BUILD_WORD:
        return "build"
    return ""


def _lookup(message_id: int) -> tuple[str, int] | None:
    for sent in sorted((config.PRIVATE / "reels").glob("*/sent.json")):
        frame = state.read_json(sent, {}).get("lines", {}).get(str(message_id))
        if frame:
            return sent.parent.name, frame
    return None


def line_of(message_id: int) -> tuple[str, int] | None:
    """Ролик и номер кадра фразы, на которую ответили. None — это не фраза ролика.

    Ищется по разосланному, как приём трека ищет пост по track_request. Не нашлось —
    один раз подтягиваем приватное хранилище: рассылает другой воркфлоу, а
    дежурство, склонировавшее хранилище часы назад, узнало бы о новом ролике
    только на следующей отправке состояния — владелец же записывает сразу.
    """
    found = _lookup(message_id)
    if found is None and (config.PRIVATE / ".git").exists():
        subprocess.run(
            ["git", "pull", "--rebase", "--autostash"], cwd=config.PRIVATE, capture_output=True
        )
        found = _lookup(message_id)
    return found


def start_build(reel_id: str) -> bool:
    """Запускает сборку отдельным запуском reels.yml. False — не запустилась.

    workflow_dispatch — единственное, что встроенному GITHUB_TOKEN разрешено
    запускать (прочие его события новых запусков не создают), так что отдельный
    ключ не нужен: хватает права actions: write у воркфлоу бота.
    """
    import requests

    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not (token and repo):
        log.warning("Сборка %s не запущена: нет GITHUB_TOKEN. Руками: python -m src.reels --build %s", reel_id, reel_id)
        return False
    try:
        response = requests.post(
            f"https://api.github.com/repos/{repo}/actions/workflows/reels.yml/dispatches",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            json={"ref": os.environ.get("GITHUB_REF_NAME", "main"), "inputs": {"id": reel_id}},
            timeout=30,
        )
    except requests.RequestException as exc:
        log.error("Сборка %s не запущена: %s", reel_id, exc)
        return False
    if not response.ok:
        log.error("Сборка %s не запущена: GitHub ответил %s %s", reel_id, response.status_code, response.text[:200])
    return response.ok


def _save_picture(data: bytes, folder: Path, frame: int, comment: str) -> Path:
    """Картинка владельца в pics/<кадр>-<n>.jpg, подпись — рядом в .txt. OSError — не картинка.

    Пересохраняется в JPEG не больше 2160 точек, как фото события (_photo):
    документом приходит и PNG, и снимок с телефона в двенадцать мегапикселей.
    Поворот по EXIF — до пересохранения, иначе снятое боком ляжет боком.
    """
    import io

    from PIL import Image, ImageOps

    image = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    image.thumbnail((2160, 2160))
    pics = folder / "pics"
    pics.mkdir(parents=True, exist_ok=True)
    count = max((int(p.stem.split("-")[1]) for p in pictures(folder, frame)), default=0) + 1
    dest = pics / f"{frame}-{count}.jpg"
    image.save(dest, "JPEG", quality=92)
    if comment.strip():
        dest.with_suffix(".txt").write_text(comment.strip() + "\n", encoding="utf-8")
    return dest


def pictures(folder: Path, frame: int) -> list[Path]:
    """Картинки и видео к кадру по порядку: 7-2 раньше 7-10.

    Видео (<кадр>-<n>.mp4) бот от владельца не принимает — его кладёт Claude,
    переделывая присланное: «Киф выходит, машет и уходит перемоткой» картинкой
    не сделать. Сборка режет его под 9:16, как гифку, и крутит по кругу.
    """
    found = [p for p in (folder / "pics").glob(f"{frame}-*") if p.suffix in (".jpg", ".mp4")]
    return sorted(found, key=lambda p: int(p.stem.split("-")[1]))


def with_pictures(script: dict, folder: Path | None) -> dict:
    """Копия сценария, где кадры строк с картинками владельца заменены ими.

    Сам сценарий не меняется: картинку можно убрать из pics, и строка вернётся
    к кадрам автора.
    """
    if folder is None:
        return script
    return {**script, "lines": [
        {**line, "screen": [{"kind": PIC, "path": str(p)} for p in found]} if (found := pictures(folder, number)) else line
        for number, line in enumerate(script["lines"], 1)
    ]}


def accept(message: dict, reel: tuple[str, int], admin: str, push) -> None:
    """Кладёт дубль или картинку на место кадра и отвечает владельцу; «собери» и полный комплект — в сборку.

    `push` — отправка состояния из дежурства (moderate.push_state): сборка идёт
    на другой машине и берёт дубли из приватного хранилища, поэтому последний
    дубль уезжает туда до запуска, а не через десять минут.
    """
    from . import telegram

    reel_id, frame = reel
    folder = config.PRIVATE / "reels" / reel_id
    frames = spoken_frames(state.read_json(folder / "script.json", {"lines": []}))
    number = f"{frames.index(frame) + 1}/{len(frames)}" if frame in frames else str(frame)
    again = any(folder.glob(f"{frame}.*"))
    kind = reply_kind(message)

    if kind == "build":
        push()
        reply = "Собираю" if start_build(reel_id) else (
            f"Сборка не запустилась. Actions → «Ролики» → Run workflow, id <code>{reel_id}</code>")
        telegram.send_message(admin, reply, reply_to=message["message_id"])
        return

    if kind == "picture":
        comment = str(message.get("caption") or "")
        try:
            _save_picture(telegram.download_file(take_picture(message)["file_id"]), folder, frame, comment)
            reply = f"Картинка к {number} принята" + (", комментарий записан" if comment.strip() else "")
        except telegram.TelegramError as exc:
            reply = f"Картинка к {number} не принята: {exc}. Пришли ещё раз."
        except OSError:
            reply = f"Картинка к {number} не принята: не открывается. Пришли фото или JPEG/PNG файлом."
        telegram.send_message(admin, reply, reply_to=message["message_id"])
        return

    take = take_file(message)
    try:
        data = telegram.download_file(take["file_id"])
    except telegram.TelegramError as exc:
        telegram.send_message(admin, f"Дубль {number} не принят: {exc}. Пришли ещё раз.", reply_to=message["message_id"])
        return
    # Прежний дубль удаляется целиком: пришёл m4a вместо ogg — и narrate взял бы
    # первый по алфавиту файл, то есть, возможно, старый.
    for old in folder.glob(f"{frame}.*"):
        old.unlink()
    # Расширение — для глаз: ffmpeg узнаёт формат по содержимому.
    (folder / f"{frame}{Path(take.get('file_name', 'take.ogg')).suffix or '.ogg'}").write_bytes(data)

    if any(not any(folder.glob(f"{n}.*")) for n in frames):
        reply = f"{'Перезаписал' if again else 'Принял'} {number}"
    else:
        push()
        if start_build(reel_id):
            reply = f"Перезаписал {number}, пересобираю" if again else "Все фразы есть, собираю"
        else:
            reply = (f"Все фразы есть, но сборка не запустилась. Actions → «Ролики» → "
                     f"Run workflow, id <code>{reel_id}</code>")
    telegram.send_message(admin, reply, reply_to=message["message_id"])


# --- сборка ---------------------------------------------------------------


def _download(url: str, dest: Path, smallest: int) -> Path | None:
    """Файл по ссылке или None. Меньше `smallest` байт — не то, что просили."""
    import requests

    from .sources.http import BROWSER_UA

    try:
        response = requests.get(url, timeout=60, headers={"User-Agent": BROWSER_UA})
    except requests.RequestException:
        return None
    if not response.ok or len(response.content) < smallest:
        return None
    dest.write_bytes(response.content)
    return dest


def _gif(screen: dict, work: Path) -> Path | None:
    """Видео-мем с GIPHY: по id, иначе первый годный по запросу. None — не нашлось.

    Ключ нужен только поиску, и поиск идёт, только если гифку по id не отдали:
    автор выбрал её глазами, а выдача поиска меняется. Ошибка в лог пишется
    без адреса запроса: в адресе стоит сам ключ. Из выдачи берётся первый,
    а не случайный: GIPHY сортирует по смыслу, и пересборка того же сценария
    не должна менять мем.
    """
    import requests

    dest = work / f"gif-{abs(hash((screen.get('id'), screen['query']))) % 10**8}.mp4"
    if dest.exists():
        return dest
    if screen.get("id") and _download(GIPHY_MEDIA.format(screen["id"]), dest, 10_000):
        log.info("Видео-мем %s скачан по id: %d КБ", screen["id"], dest.stat().st_size // 1024)
        return dest
    key = config.secret("GIPHY_API_KEY", required=False)
    found = []
    if key:
        try:
            response = requests.get(GIPHY_SEARCH, timeout=30, params={
                "api_key": key, "q": screen["query"], "limit": 5, "rating": "pg-13", "lang": "en",
            })
            if response.ok:
                found = response.json().get("data") or []
            else:
                log.warning("GIPHY ответил %s на «%s»", response.status_code, screen["query"])
        except (requests.RequestException, ValueError) as exc:
            log.warning("GIPHY недоступен (%s) на «%s»", type(exc).__name__, screen["query"])
    originals = [item.get("images", {}).get("original", {}) for item in found]
    # Вертикальные и квадратные вперёд, порядок выдачи внутри сохраняется:
    # у горизонтальной гифки обрезка под 9:16 оставляет треть.
    for original in sorted(
        (o for o in originals if o.get("mp4")),
        key=lambda o: int(o.get("width") or 0) > int(o.get("height") or 0) * 1.2,
    ):
        if _download(original["mp4"], dest, 10_000):
            log.info("Видео-мем «%s» найден поиском: %d КБ", screen["query"], dest.stat().st_size // 1024)
            return dest
    log.warning(
        "Видео-мем «%s» не нашёлся%s — вместо него %s", screen["query"],
        "" if key or screen.get("id") else " (нет GIPHY_API_KEY)",
        "мем-картинка" if screen.get("template") else "сток",
    )
    return None


def _photo(url: str, work: Path) -> Path | None:
    """Фотография события со страницы источника, по og:image. None — не нашлось.

    Пересохраняется в JPEG не больше 2160 точек: издания отдают PNG под
    чужим расширением и снимки агентств по шесть тысяч точек, а ffmpeg
    узнаёт картинку по расширению и на таком спотыкается.
    """
    from PIL import Image

    from .sources import feeds

    dest = work / f"photo-{abs(hash(url)) % 10**8}.jpg"
    if dest.exists():
        return dest
    picture = feeds.page_image(url)
    raw = _download(picture, work / "photo.raw", PHOTO_MIN_BYTES) if picture else None
    try:
        image = Image.open(raw).convert("RGB") if raw else None
    except OSError:
        image = None
    if image is None:
        log.warning("На %s нет годной фотографии — вместо неё сток", url)
        return None
    image.thumbnail((2160, 2160))
    image.save(dest, "JPEG", quality=92)
    return dest


def _fill(screen: dict, work: Path) -> dict:
    """Чем закрыть кадр — поля clips.Shot: subject, backdrop или query.

    Не нашлось своего — откат по цепочке, сборка не падает: фото события →
    сток, видео-мем → мем-картинка из template → сток по тому же запросу.
    """
    kind = screen["kind"]
    if kind == PIC:
        return {"backdrop": screen["path"]}
    if kind == "face":
        return {"subject": screen["name"]}
    if kind == "meme":
        return {"backdrop": str(config.MEME_TEMPLATES / f"{screen['template']}.jpg")}
    found = _photo(screen["url"], work) if kind == "photo" else _gif(screen, work) if kind == "gif" else None
    if found:
        return {"backdrop": str(found)}
    if kind == "gif" and screen.get("template"):
        return {"backdrop": str(config.MEME_TEMPLATES / f"{screen['template']}.jpg")}
    return {"query": screen.get("query", "")}


def caption(layer, text: str):
    """Мемная надпись сверху кадра: белые буквы с чёрной обводкой и тенью.

    Узкий жирный Oswald, а не Arimo мемов канала (card.render_meme): поверх
    полноэкранного видео надпись должна читаться с первого взгляда, а в одну
    строку узкого шрифта та же фраза влезает заметно крупнее. Вид — как у мемов
    из пересылки: белые буквы, чёрная обводка. Отдельно от `text`: та надпись —
    ярлык фразы в нижней трети, а эта — реплика самого мема, её место сверху.
    Верх кадра под неё свободен не всегда: фото выбирай, где голова героя
    ниже верхней пятой части.
    """
    from PIL import Image, ImageDraw, ImageFilter

    from . import card, stories

    ink = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(ink)
    # Одна строка крупно лучше двух, две — лучше мелкой одной.
    for size, most in CAPTION_SIZES:
        font = stories.font(size, 600)
        lines = card._wrap(draw, text.strip(), font, layer.width - 2 * CAPTION_PAD)
        if len(lines) <= most:
            break
    for number, line in enumerate(lines):
        draw.text(
            (layer.width / 2, CAPTION_TOP + number * size * 1.1), line, font=font, fill=(255, 255, 255, 255),
            anchor="ma", stroke_width=max(4, size // 16), stroke_fill=(0, 0, 0, 255),
        )
    shade = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    shade.putalpha(ink.getchannel("A").filter(ImageFilter.GaussianBlur(10)).point(lambda a: min(255, a * 2)))
    return Image.alpha_composite(Image.alpha_composite(layer, shade), ink)


def storyboard(script: dict, work: Path, seconds: list[float] | None = None) -> list:
    """Кадры ролика по порядку: у строки их от одного до трёх.

    Заставки с маркой в конце, как у клипов, нет: крючок у сценария уже есть
    первой фразой, а три секунды заставки — это три секунды, на которых ролик
    пролистывают, и повтор по кругу начинался бы с неё, а не с крючка.

    `seconds` — длины строк, когда они уже известны по дублям. Строка делится
    между своими кадрами поровну. Границы округляются до кадра видео от начала
    ролика, а не у каждого кадра отдельно: на двух десятках склеек погрешность
    иначе копилась бы, и голос к концу уезжал от картинки.

    Карточка стоит на размытом соседнем кадре — прежнем, а у первой строки
    на следующем.
    """
    from PIL import Image

    from . import clips

    lengths = seconds or [float(line.get("pause") or SAY_SECONDS) for line in script["lines"]]
    plan = [
        (index, part, len(screens(line)), screen)
        for index, line in enumerate(script["lines"])
        for part, screen in enumerate(screens(line))
    ]
    fills = [None if screen["kind"] == "card" else _fill(screen, work) for *_, screen in plan]

    shots, line_start, done = [], 0.0, 0.0
    for number, (index, part, count, screen) in enumerate(plan):
        if part == 0 and index:
            line_start += lengths[index - 1]
        end = round((line_start + lengths[index] * (part + 1) / count) * clips.FPS) / clips.FPS
        nearest = list(range(number - 1, -1, -1)) + list(range(number + 1, len(plan)))
        fill = fills[number] or next((fills[i] for i in nearest if fills[i]), {})
        # У лица надпись по умолчанию — имя: холодная лента не обязана узнавать
        # человека в лицо. Пустой text убирает надпись совсем.
        body = screen.get("text", screen.get("name", ""))
        label = screen.get("label", "")
        layer = (
            clips.overlay(label, body, big=len(body) <= BIG_TEXT, clean=True)
            if label or body
            else Image.new("RGBA", (clips.WIDTH, clips.HEIGHT))
        )
        if _filled(screen.get("caption")):
            layer = caption(layer, screen["caption"])
        shots.append(clips.Shot(
            layer, end - done, fill.get("subject", ""), script.get("topic", ""),
            backdrop=fill.get("backdrop", ""), query=fill.get("query", ""),
        ))
        done = end
    return shots


def _meter(path: Path, before: str = "") -> tuple[float, list[tuple[float, float, float]]]:
    """Громкость по EBU R128: общая в LUFS и ход по времени — (t, M, S).

    M меряется окном 0,4 с, S — тремя секундами. Звука нет — -70, как у тишины.
    """
    from . import clips

    stderr = subprocess.run(
        [clips.ffmpeg(), "-hide_banner", "-nostats", "-i", str(path), "-af", f"{before}ebur128", "-f", "null", "-"],
        capture_output=True, text=True,
    ).stderr
    trace = [
        (float(t), float(m), float(s))
        for t, m, s in re.findall(r"t: *([\d.]+) +TARGET:\S+ LUFS +M: *(-?[\d.]+) +S: *(-?[\d.]+)", stderr)
    ]
    total = re.findall(r"I:\s+(-?[\d.]+) LUFS", stderr)
    return (float(total[-1]) if total else -70.0), trace


def beat_start(track: Path) -> float:
    """Откуда брать бит: сильная доля в начале самого длинного места, где качает низ.

    У битов со стока вступление без баса длится от трёх до двадцати пяти
    секунд, а посреди трека бывает брейк без бочки: отступ одним числом
    попадал то в тишину, то в провал. Поэтому трек меряется ниже 120 Гц,
    где бочка и 808: громким считается всё в пределах 6 дБ от почти самого
    громкого места, и берётся самый длинный такой кусок. Трёхсекундное окно
    замечает его с опозданием, поэтому сама доля ищется коротким.
    """
    _, trace = _meter(track, "lowpass=f=120,")
    if not trace:
        return 0.0
    loud = sorted(s for _, _, s in trace)[int(len(trace) * 0.9)] - 6
    best, since = (0.0, 0.0), None
    for t, _, s in [*trace, (trace[-1][0] + 0.1, 0.0, -120.0)]:
        if s >= loud and since is None:
            since = t
        elif s < loud and since is not None:
            best, since = max(best, (t - since, -since)), None
    start = -best[1]
    onset = next((t - 0.4 for t, m, _ in trace if start - 3 <= t <= start and m >= loud), start)
    return max(0.0, onset)


def _speech(path: Path) -> tuple[float, float]:
    """Где в чистом дубле речь: начало и конец, секунды. Речи нет — весь файл."""
    with wave.open(str(path)) as take:
        rate = take.getframerate()
        samples = array.array("h", take.readframes(take.getnframes()))
    step = rate // 100
    gate = (32768 * 10 ** (SPEECH_DB / 20)) ** 2
    loud = [
        sum(x * x for x in samples[i:i + step]) / step > gate
        for i in range(0, len(samples) - step + 1, step)
    ]
    runs = [i for i in range(len(loud) - SPEECH_RUN + 1) if all(loud[i:i + SPEECH_RUN])]
    if not runs:
        return 0.0, len(samples) / rate
    return runs[0] / 100, (runs[-1] + SPEECH_RUN) / 100


def _trimmed(script: dict, voices: Path | None, work: Path) -> Path:
    """Дубли, готовые к склейке: чистые, одной громкости и без тишины по краям.

    Голосовое начинается раньше речи и кончается позже: палец жмёт запись,
    человек вдыхает, отпускает. По полсекунды с краёв на семи фразах — лишние
    семь секунд тишины в ролике на сорок, а короткие ролики пролистывают
    как раз на провалах. Берутся только фразы: пауза остаётся немой, даже если
    в папке случайно лежит файл под её номером.

    Порядок — шумодав, громкость, поиск речи. Край ищется по порогу от уже
    выровненной речи: абсолютный порог в -45 дБ, по которому резали раньше,
    тише фона с шумом, и тишина перед словом оставалась целиком.
    """
    from . import clips

    out = work / "takes"
    out.mkdir(exist_ok=True)
    for frame in spoken_frames(script) if voices else []:
        take = clips.voice_take(voices, frame - 1)
        if take is None:
            continue
        # Больше чем на 20 дБ не поднимаем: пустой дубль превратился бы в рёв шума.
        gain = min(VOICE_LUFS - _meter(take, f"{DENOISE},")[0], 20.0)
        clean = work / f"clean-{frame}.wav"
        clips.run([
            clips.ffmpeg(), "-y", "-i", str(take), "-af", f"{DENOISE},volume={gain:.1f}dB",
            "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(clean),
        ])
        start, end = _speech(clean)
        clips.run([
            clips.ffmpeg(), "-y", "-i", str(clean),
            "-af", f"atrim=start={max(0.0, start - BEFORE_SPEECH):.3f}:end={end + AFTER_SPEECH:.3f}",
            str(out / f"{frame}.wav"),
        ])
    return out


def bed(script: dict) -> Path | None:
    """Подложка: бит из поля `music`, иначе BEAT, иначе случайный. None — битов нет нигде.

    Ищется сначала в приватном хранилище, потом в assets/audio. Биты лежат
    в приватном хранилище, а не в открытом репозитории: лицензия Pixabay
    разрешает музыку в роликах, но не раздачу самих файлов.
    """
    from . import clips

    folders = [folder for folder in (config.PRIVATE / "audio", clips.AUDIO_DIR) if folder.is_dir()]
    for name in (script.get("music"), BEAT):
        found = next((folder / name for folder in folders if name and (folder / name).is_file()), None)
        if found:
            return found
        if name:
            log.warning("Бита %s нет ни в %s, ни в assets/audio", name, config.PRIVATE / "audio")
    tracks = sorted(p for folder in folders for p in folder.glob("*") if p.suffix in {".mp3", ".wav"})
    return random.choice(tracks) if tracks else None


def _beat(script: dict, total: float, work: Path) -> Path:
    """Кусок бита на весь ролик, с сильной доли и нужной громкости.

    Громкость меряется на самом куске, а не на треке: тихое вступление
    занижало бы среднее, и бит выходил бы громче задуманного.
    """
    from . import clips

    track, music = bed(script), work / "beat.wav"
    if track is None:
        # Ролик без музыки лучше, чем никакого: голос в нём главное.
        # Тишина вместо подложки — чтобы склейка шла тем же путём.
        log.warning("Подложки нет ни в %s, ни в assets/audio — ролик без музыки", config.PRIVATE / "audio")
        clips.run([clips.ffmpeg(), "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                   "-t", f"{total}", str(music)])
        return music
    start, raw = beat_start(track), work / "beat-raw.wav"
    clips.run([clips.ffmpeg(), "-y", "-ss", f"{start:.2f}", "-i", str(track), "-t", f"{total + 1:.2f}", str(raw)])
    gain = BEAT_LUFS - _meter(raw)[0]
    clips.run([clips.ffmpeg(), "-y", "-i", str(raw), "-af", f"volume={gain:.1f}dB", str(music)])
    print(f"  бит: {track.name} с {start:.1f} с, {gain:+.1f} дБ")
    return music


def aspect(path: str) -> float:
    """Ширина к высоте картинки или видео. 0 — не узнать, и тогда кадр обрезается."""
    import shutil

    probe = shutil.which("ffprobe")
    if not probe:
        return 0.0
    size = subprocess.run(
        [probe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", path],
        capture_output=True, text=True,
    ).stdout.strip().split(",")
    try:
        return int(size[0]) / int(size[1])
    except (ValueError, IndexError, ZeroDivisionError):
        return 0.0


def fit(screen: dict, backdrop: str) -> str:
    """Как кадр ложится в 9:16: crop — обрезка, blur — целиком на размытой копии.

    Картинка владельца режется всегда, даже панорама: полосы и размытую
    подложку он не хочет, а что в кадре главное — решил сам, присылая.
    """
    return "blur" if screen["kind"] != PIC and backdrop and aspect(backdrop) > BLUR_WIDER else "crop"


def build(script: dict, voices: Path | None) -> tuple[Path, Path]:
    """Собирает ролик и превью. Возвращает (ролик, превью).

    `voices` — папка дублей; её pics/ с картинками владельца заменяет кадры строк.
    """
    from . import clips

    clips.OUT_DIR.mkdir(parents=True, exist_ok=True)
    video = clips.OUT_DIR / f"reel-{script['id']}.mp4"
    cover = video.with_suffix(".jpg")

    script = with_pictures(script, voices)
    with tempfile.TemporaryDirectory(prefix="plenka-reel-") as tmp:
        work = Path(tmp)
        # Сперва голос: длина строки — это длина её дубля, а кадры делят её потом.
        takes = _trimmed(script, voices, work)
        lines = [clips.Shot(None, float(line.get("pause") or SAY_SECONDS), "", "") for line in script["lines"]]
        timed, voice = clips.narrate(lines, script, work, kind="reels", voices=takes, lead=0.0, tail=TAIL)
        shots = storyboard(script, work, [shot.seconds for shot in timed])
        flat = [screen for line in script["lines"] for screen in screens(line)]
        total = sum(shot.seconds for shot in shots)

        parts, used = [], []
        for index, (shot, screen) in enumerate(zip(shots, flat)):
            parts.append(work / f"part-{index}.mp4")
            # Склейки встык, без выхода из чёрного: при смене кадра каждые
            # две-три секунды он мигал бы темнотой.
            used.append(f"{screen['kind']}→" + clips.segment(
                shot, parts[-1], work, fade_in=False,
                grade=CARD_BLUR if screen["kind"] == "card" else "",
                fit=fit(screen, shot.backdrop),
                focus=float(screen.get("focus", 0.5)),
            ))
        print("  кадры:", ", ".join(used))
        print(f"  голос: {'есть' if voice else 'нет'}, длина {total:.1f} с")

        clips.assemble(
            parts, _beat(script, total, work), total, video, work, voice, 0.0, voice_grade=VOICE_CHAIN, duck=DUCK
        )

    # Превью вынимается из готового ролика, а не рисуется отдельно: так оно
    # по построению совпадает с первым кадром, который площадка возьмёт обложкой.
    clips.run([clips.ffmpeg(), "-y", "-i", str(video), "-frames:v", "1", "-q:v", "2", str(cover)])
    return video, cover


def package(script: dict) -> str:
    """Текст для заливки: каждое поле — отдельный <code>, копируется касанием.

    Отдельным сообщением, а не подписью к ролику: подпись в Telegram обрезается
    на 1024 знаках, а название, описание и теги вместе туда не влезают.
    """
    def field(value: str) -> str:
        return f"<code>{html.escape(value, quote=False)}</code>"

    return (
        f"<b>Название</b>\n{field(script['title'])}\n\n"
        f"<b>Описание</b>\n{field(script['description'])}\n\n"
        f"<b>Теги</b>\n{field(', '.join(script['tags']))}\n\n"
        f"Выложить: <b>{when(script)}</b>"
    )


def deliver(script: dict, video: Path, cover: Path) -> None:
    """Пакет владельцу: ролик, превью файлом и текст полей."""
    from . import telegram

    admin = config.secret("TELEGRAM_ADMIN_ID")
    telegram.send_video_file(admin, video, f"<b>{html.escape(script['topic'], quote=False)}</b>")
    # Превью документом, а не фото: фото Telegram пережимает до 1280 точек
    # по длинной стороне, а обложке нужен кадр 1080×1920 как есть. Отправки
    # документа в telegram.py нет — метод API зовётся напрямую.
    with cover.open("rb") as handle:
        telegram._call("sendDocument", {"chat_id": admin}, files={"document": (cover.name, handle, "image/jpeg")})
    telegram.send_message(admin, package(script))


# --- проверка -------------------------------------------------------------


def _selftest() -> None:
    """Без сети: валидатор, раскадровка, выбор бита, поиск речи в дубле и разбор ответов на фразу.

    Запуск: python -m src.reels --selftest
    """
    import contextlib
    import io

    from . import host, moderate

    good = {
        "id": "20260914-test",
        "topic": "Проверка",
        "publish": "today",
        "sources": ["https://example.com/news"],
        "title": "Проверка формата",
        "description": "Строка описания. #фонк #плёнка",
        "tags": ["фонк", "плёнка"],
        "music": BEAT,
        "lines": [
            {"say": "Первая фраза", "hint": "ровно", "screen": {"kind": "face", "name": "Bones"}},
            {"say": "Вторая", "screen": {"kind": "card", "label": "17/08", "text": "два концерта"}},
            {"pause": 1.0, "screen": {"kind": "meme", "template": "this-is-fine"}},
            {"say": "Третья", "screen": [
                {"kind": "stock", "query": "stadium empty seats"},
                {"kind": "gif", "query": "waving goodbye", "template": "this-is-fine",
                 "focus": 0.3, "caption": "я боюсь только его"},
            ]},
        ],
    }
    assert problems(good, good["id"]) == [], problems(good, good["id"])

    def broken(word: str, **change) -> None:
        found = problems({**good, **change}, good["id"])
        assert any(word in error for error in found), (word, found)

    broken("sources", sources=[])
    broken("title", title="х" * 101)
    broken("хэштеги", description="Описание без хэштегов в конце")
    broken("именем файла", id="20260915-other")
    broken("publish", publish="завтра")
    broken("tags", tags=["фонк, рэп"])
    broken("фразы", lines=[{"pause": 1.0, "screen": {"kind": "card", "text": "тишина"}}])
    broken("ровно одно", lines=[{"say": "Фраза", "pause": 1.0, "screen": {"kind": "card", "text": "т"}}])
    broken("music", music="../beat.mp3")
    broken("music", music="beat.ogg")
    photo = {"kind": "photo", "url": good["sources"][0], "query": "concert crowd"}
    assert problems({**good, "lines": [{"say": "Фраза", "screen": [photo, {"kind": "gif", "query": "bye"}]}]}) == []
    for screen, word in (
        ({"kind": "video"}, "kind"),
        ({"kind": "meme", "template": "нет-такого"}, "шаблона"),
        ({"kind": "face", "name": "Канье"}, "artists.json"),
        ({"kind": "card"}, "text"),
        ({"kind": "stock"}, "query"),
        ({"kind": "gif"}, "query"),
        ({"kind": "gif", "query": "bye", "id": "../x"}, "GIPHY"),
        ({"kind": "gif", "query": "bye", "focus": 1.5}, "focus"),
        ({"kind": "card", "text": "т", "caption": 5}, "строки"),
        ({"kind": "gif", "query": "bye", "template": "нет-такого"}, "шаблона"),
        ({**photo, "url": "https://other.example/page"}, "sources"),
        ([{"kind": "card", "text": "т"}] * 4, "от одного до"),
        ([{"kind": "card", "text": "т"}, {"kind": "stock"}], "кадр 2"),
    ):
        broken(word, lines=[{"say": "Фраза", "screen": screen}])

    # Раскадровка: кадр на каждый screen, строка делится между своими кадрами,
    # границы стоят на кадрах видео и в сумме дают ровно длину ролика.
    # Без ключа GIPHY видео-мем уходит в свою мем-картинку, карточка берёт
    # фон соседнего кадра.
    os.environ.pop("GIPHY_API_KEY", None)
    with tempfile.TemporaryDirectory() as tmp:
        shots, spoken = storyboard(good, Path(tmp), [2.0, 1.5, 1.0, 2.5]), host.lines(good, kind="reels")
        assert len(spoken) == len(good["lines"]) and len(shots) == 5, (len(spoken), len(shots))
        assert spoken[2] == "" and spoken_frames(good) == [1, 2, 4]
        assert abs(sum(shot.seconds for shot in shots) - 7.0) < 1e-9
        assert all(abs(shot.seconds * 30 - round(shot.seconds * 30)) < 1e-6 for shot in shots)
        assert abs(shots[3].seconds - 1.25) < 0.04 and shots[1].subject == "Bones"
        assert shots[4].backdrop.endswith("this-is-fine.jpg"), shots[4]
        assert shots[0].layer.size == (1080, 1920)
        # Мемная надпись ложится сверху, ниже вкладок площадки.
        band = (0, CAPTION_TOP, 1080, CAPTION_TOP + 100)
        assert shots[4].layer.crop(band).getchannel("A").getextrema()[1] > 0
        assert shots[3].layer.crop(band).getchannel("A").getextrema()[1] == 0

        # Картинки владельца заменяют кадры строки по порядку прихода (7-2 раньше
        # 7-10), время строки делится поровну, надписей поверх нет — ни ярлыка
        # автора, ни подписи-комментария.
        from PIL import Image

        pics = Path(tmp) / "pics"
        pics.mkdir()
        for name in ("1-10", "1-2", "3-1"):
            Image.new("RGB", (800, 800)).save(pics / f"{name}.jpg")
        (pics / "1-2.txt").write_text("обрежь пониже", encoding="utf-8")
        # Видео встаёт в тот же ряд по номеру, .txt кадром не считается.
        (pics / "1-3.mp4").write_bytes(b"")
        mine = with_pictures(good, Path(tmp))
        assert [Path(s["path"]).name for s in screens(mine["lines"][0])] == ["1-2.jpg", "1-3.mp4", "1-10.jpg"]
        (pics / "1-3.mp4").unlink()
        mine = with_pictures(good, Path(tmp))
        assert mine["lines"][1] == good["lines"][1] and "path" in screens(mine["lines"][2])[0]
        assert "path" not in screens(good["lines"][0])[0] and with_pictures(good, None) is good
        shots = storyboard(mine, Path(tmp), [2.0, 1.5, 1.0, 2.5])
        assert len(shots) == 6 and abs(shots[0].seconds - 1.0) < 0.04 and shots[0].backdrop.endswith("1-2.jpg")
        assert all(shot.layer.getchannel("A").getextrema()[1] == 0 for shot in (shots[0], shots[1], shots[3]))
        # Широкая картинка владельца режется, а не встаёт на размытую подложку.
        Image.new("RGB", (3000, 800)).save(Path(tmp) / "wide.jpg")
        wide = str(Path(tmp) / "wide.jpg")
        assert fit({"kind": PIC}, wide) == "crop" and fit({"kind": "meme"}, wide) == "blur"

    # Бит: из music, без него — любимый владельца, нет и его — любой из папки.
    saved = config.PRIVATE
    with tempfile.TemporaryDirectory() as tmp:
        config.PRIVATE = Path(tmp)
        try:
            (Path(tmp) / "audio").mkdir()
            for name in (BEAT, "other.mp3"):
                (Path(tmp) / "audio" / name).touch()
            assert bed({"music": "other.mp3"}).name == "other.mp3"
            assert bed({}).name == BEAT and bed({"music": "gone.mp3"}).name == BEAT
            (Path(tmp) / "audio" / BEAT).unlink()
            assert bed({}).parent.name == "audio"
        finally:
            config.PRIVATE = saved

    # Речь в дубле: щелчок до фразы не считается её началом, края — по порогу.
    with tempfile.TemporaryDirectory() as tmp:
        rate, path = 48000, Path(tmp) / "take.wav"
        loud = [int(3000 * math.sin(i * 0.05)) for i in range(rate)]
        click = [9000] * (rate // 100)
        samples = [0] * (rate // 5) + click + [0] * (rate * 3 // 10) + loud + [0] * (rate // 2)
        with wave.open(str(path), "wb") as take:
            take.setnchannels(1), take.setsampwidth(2), take.setframerate(rate)
            take.writeframes(array.array("h", samples).tobytes())
        start, end = _speech(path)
        assert abs(start - 0.51) < 0.02 and abs(end - 1.51) < 0.02, (start, end)

    # Бит берётся с места, где вступает низ, а не с тихого начала.
    with tempfile.TemporaryDirectory() as tmp:
        from . import clips

        track = Path(tmp) / "beat.wav"
        clips.run([clips.ffmpeg(), "-y", "-f", "lavfi", "-i", "sine=f=60:d=30",
                   "-af", "volume='if(lt(t,7),0.01,0.8)':eval=frame", str(track)])
        assert abs(beat_start(track) - 7.0) < 0.5, beat_start(track)

        # Кадр обрезается вокруг focus: у картинки «слева красное, справа
        # синее» кадр с focus 0 красный, с focus 1 синий.
        from PIL import Image

        half = Image.new("RGB", (1600, 900), (255, 0, 0))
        half.paste((0, 0, 255), (800, 0, 1600, 900))
        half.save(Path(tmp) / "half.png")
        empty = Image.new("RGBA", (clips.WIDTH, clips.HEIGHT))
        for focus, channel in ((0.0, 0), (1.0, 2)):
            part = Path(tmp) / f"focus-{focus}.mp4"
            clips.segment(clips.Shot(empty, 0.2, "", "", backdrop=str(Path(tmp) / "half.png")), part, Path(tmp),
                          fade_in=False, grade="", focus=focus)
            clips.run([clips.ffmpeg(), "-y", "-i", str(part), "-frames:v", "1", str(Path(tmp) / "frame.png")])
            pixel = Image.open(Path(tmp) / "frame.png").convert("RGB").getpixel((540, 960))
            assert pixel[channel] > 200, (focus, pixel)

    # Ответ голосовым на фразу находит ролик и кадр — и в разборе дежурства тоже.
    saved = config.PRIVATE
    with tempfile.TemporaryDirectory() as tmp:
        config.PRIVATE = Path(tmp)
        try:
            state.write_json(Path(tmp) / "reels" / good["id"] / "sent.json", {"lines": {"562": 4}})
            voice = {"message_id": 9, "from": {"id": 1}, "chat": {"id": 1},
                     "reply_to_message": {"message_id": 562}, "voice": {"file_id": "v"}}
            assert take_file(voice)["file_id"] == "v" and reply_kind(voice) == "voice"
            assert take_file({"document": {"file_id": "d", "mime_type": "audio/mp4"}})["file_id"] == "d"
            assert not take_file({"document": {"file_id": "p", "mime_type": "application/pdf"}})
            assert line_of(562) == (good["id"], 4)
            assert line_of(563) is None

            def routed(message: dict) -> str:
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    moderate.process([{"update_id": 1, "message": message}], {}, "1", True, 0)
                return out.getvalue()

            assert f"дубль ролика {good['id']}, кадр 4" in routed(voice)
            # Чужое голосовое и аудио в ответ на запрос трека идут прежним путём.
            assert "дубль ролика" not in routed({**voice, "from": {"id": 2}, "chat": {"id": 2}})
            track = {**voice, "voice": None, "audio": {"file_id": "a"}, "reply_to_message": {"message_id": 700}}
            assert "трек в ответ на 700" in routed(track)

            # Фото — самый крупный размер, картинка документом, «собери» текстом.
            photo = {**voice, "voice": None, "photo": [{"file_id": "s", "width": 90, "height": 90},
                                                       {"file_id": "l", "width": 1280, "height": 1280}]}
            assert take_picture(photo)["file_id"] == "l" and reply_kind(photo) == "picture"
            assert reply_kind({"document": {"file_id": "p", "mime_type": "image/png"}}) == "picture"
            build_word = {**voice, "voice": None, "text": "Собери!"}
            assert reply_kind(build_word) == "build" and reply_kind({**build_word, "text": "собери ролик"}) == ""
            assert f"картинка ролика {good['id']}, кадр 4" in routed(photo)
            assert f"«собери» ролика {good['id']}, кадр 4" in routed(build_word)

            # Приём: картинка ложится в pics, подпись — рядом .txt, без подписи
            # файла нет; «собери» отправляет состояние и запускает сборку.
            from PIL import Image

            from . import telegram

            picture = io.BytesIO()
            Image.new("RGB", (1280, 720), (0, 128, 0)).save(picture, "PNG")
            replies, pushed, built = [], [], []
            real = telegram.download_file, telegram.send_message, globals()["start_build"]
            telegram.download_file = lambda file_id: picture.getvalue()
            telegram.send_message = lambda chat, text, **kw: replies.append(text)
            globals()["start_build"] = lambda reel_id: built.append(reel_id) or True
            try:
                state.write_json(Path(tmp) / "reels" / good["id"] / "script.json", good)
                folder = Path(tmp) / "reels" / good["id"]
                accept({**photo, "caption": "сделай вертикально"}, (good["id"], 4), "1", lambda: pushed.append(1))
                accept(photo, (good["id"], 4), "1", lambda: pushed.append(1))
                assert replies == ["Картинка к 3/3 принята, комментарий записан", "Картинка к 3/3 принята"], replies
                assert (folder / "pics" / "4-1.txt").read_text(encoding="utf-8") == "сделай вертикально\n"
                assert (folder / "pics" / "4-2.jpg").is_file() and not (folder / "pics" / "4-2.txt").exists()
                assert Image.open(folder / "pics" / "4-1.jpg").format == "JPEG" and not pushed and not built
                telegram.download_file = lambda file_id: b"heic"
                accept({**photo, "photo": None, "document": {"file_id": "x", "mime_type": "image/heic"}},
                       (good["id"], 4), "1", lambda: None)
                assert "не открывается" in replies[-1] and not (folder / "pics" / "4-3.jpg").exists()
                accept(build_word, (good["id"], 4), "1", lambda: pushed.append(1))
                assert pushed == [1] and built == [good["id"]] and replies[-1] == "Собираю"
            finally:
                telegram.download_file, telegram.send_message, globals()["start_build"] = real
        finally:
            config.PRIVATE = saved


def main() -> int:
    parser = argparse.ArgumentParser(description="Ролики с живым голосом владельца")
    parser.add_argument("--check", metavar="ФАЙЛ", help="проверить сценарий без сети")
    parser.add_argument("--send", metavar="ФАЙЛ", help="сохранить сценарий и разослать фразы владельцу")
    parser.add_argument("--build", metavar="ID", help="собрать из дублей приватного хранилища и прислать пакет")
    parser.add_argument("--preview", metavar="ФАЙЛ", help="собрать ролик из файла, никуда не отправляя")
    parser.add_argument("--voice", metavar="ПАПКА", help="дубли для --preview: 1.ogg, 2.m4a… по номеру строки, картинки владельца в pics/")
    parser.add_argument("--dry-run", action="store_true", help="ничего не писать и не отправлять, показать")
    parser.add_argument("--selftest", action="store_true", help="валидатор, раскадровка и разбор ответа без сети")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.selftest:
        _selftest()
        print("Сценарий, раскадровка, бит и ответы на фразу: все проверки прошли.")
        return 0

    if args.check or args.send or args.preview:
        path = Path(args.check or args.send or args.preview)
        script, errors = load(path)
        for error in errors:
            print(f"  ✗ {error}")
        if errors:
            print(f"Сценарий {path.name} не годен: ошибок {len(errors)}.")
            return 1
        if args.check:
            print(f"Сценарий {path.name} годен: фраз {len(spoken_frames(script))}, строк {len(script['lines'])}, "
                  f"кадров {sum(len(screens(line)) for line in script['lines'])}.")
            return 0

    config.load_dotenv()

    if args.send:
        return send(script, args.dry_run)

    if args.preview:
        voices = Path(args.voice) if args.voice else None
    elif args.build:
        # id уходит в путь — только проверенного вида, никаких «../».
        if not ID_FORMAT.fullmatch(args.build):
            print("id вида 20260914-kanye.")
            return 1
        voices = config.PRIVATE / "reels" / args.build
        script = state.read_json(voices / "script.json", {})
        if not script:
            print(f"Нет сценария {args.build} в {voices}.")
            return 1
    else:
        parser.print_help()
        return 0

    from . import clips

    try:
        video, cover = build(script, voices)
    except clips.ClipError as exc:
        print(f"Ролик не собрался: {exc}")
        return 1
    size = video.stat().st_size / 1024 / 1024
    print(f"Готов: {video.relative_to(config.ROOT)} ({size:.1f} МБ), превью {cover.relative_to(config.ROOT)}")

    if args.preview or args.dry_run:
        print(f"\nПакет владельцу — ролик, превью файлом и текст:\n\n{package(script)}")
        return 0
    deliver(script, video, cover)
    print("Пакет ушёл владельцу.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
