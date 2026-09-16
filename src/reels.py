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

Субтитры ставятся сами: многие смотрят ролик без звука. Текст — `subtitle` строки,
а без него `say` как есть (в `subtitle` числа цифрами: «14 лет», голосу нужны
слова), кусками по 2–4 слова, время кусков — по буквам внутри речи строки,
найденной по дублю. Распознавание речи отвергнуто: оно тянет тяжёлую
зависимость, а текст и так известен дословно. Субтитр стоит на 68% высоты,
кеглем одним на весь ролик, толстой обводкой и мягким тёмным ореолом —
белое на белом иначе не читалось; где внизу картинки своя надпись (пустой файл-метка
`<кадр>-<n>.top` рядом), он уходит наверх, под метку канала. Метка
`<кадр>-<n>.nosub` у картинки выключает субтитры, пока она на экране: кадр сам
говорит текст (вырезки поста, заголовок статьи).

Поэтому ярлыков `text` и `label` в кадре больше нет, хотя сценарий их ещё
пишет: они повторяли речь, и текста в кадре было втрое больше, чем читается
(владелец, 15.09.2026). Карточка без надписи — просто соседний кадр. Остаётся
текст, который сам шутка или доказательство: `caption` мема, надписи
в картинках владельца.

Ролик ведёт в канал. По ходу всего основного ролика в левом верхнем углу
висит метка: значок Telegram и config.CHANNEL_HANDLE. После последнего кадра —
плашка PLATE_SECONDS: крутящийся аватар канала (avatar-wheel), адрес со значком
и под ним строка-приманка BAIT — зачем идти в бота (прислать свой трек в ОТБОР),
бит на ней затухает. Ссылка на бота — в описании, её требует проверка; метку
площадки (?start=yt, tt, vk) в каждое описание ставит `package`, и бот считает,
откуда пришли. TikTok ссылки
на чужие площадки режет в охвате, поэтому вторая версия — без метки и без
концовки вовсе: аватар без адреса никуда не зовёт (владелец, 16.09.2026). Она
кончается с последней строкой, звук гаснет за TIKTOK_FADE. Оба файла пишет
один проход ffmpeg, бот шлёт их подряд.

Всё своё в кадре — субтитры, мемная надпись, метка, концовка — внутри безопасной
зоны SAFE_*: её сняли 16.09.2026 с записи экрана, где Shorts срезал края
и закрывал метку стрелкой «назад», а субтитр во всю ширину — колонкой кнопок.

Звук самого трека — строка `track`: отрывок 30-секундного превью iTunes
(его без ключа отдаёт магазин, так же берёт отрывок СЛЕПАЯ ПРОСЛУШКА),
до TRACK_MAX секунд. Его подмешивают в бит до сведения, а бит на отрывке почти
молчит; голос строки, если есть, сверху. Строка без голоса длится ровно отрывок.
Ролик с чужим треком YouTube может отметить Content ID — ролик остаётся, доход
уходит правообладателю, поэтому отрывки короткие. Трек не нашёлся — играет бит.

Кадры делят строку поровну. Картинка с меткой `<кадр>-<n>.at` (внутри —
секунда от начала строки) начинается ровно тогда: так короткая вставка
попадает на своё слово, а кадры до неё делят время до метки.

Статичная картинка не стоит мёртвой: наезд на 7% за кадр (больше — надписи
у края картинки уезжают за кадр), направление чередуется от кадра к кадру.

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
# Первый комментарий — вопрос для спора, владелец закрепляет его сам. Длиннее
# под роликом сворачивается, и спорить уже не с чем.
COMMENT_MAX = 150
# Приманка — прислать свой трек в ОТБОР (GROWTH.md, «Третий актив», 16.09.2026),
# поэтому ссылка на бота в описании обязательна.
BOT_LINK = f"t.me/{config.BOT_HANDLE.lstrip('@')}"
PAUSE_MAX = 5.0
# Отрывок чужого трека (строка `track`): кусок 30-секундного превью iTunes.
# Короткий намеренно — трек в YouTube ловит Content ID, и доход с ролика уходит
# правообладателю; на отрывке бит почти молчит, а трек звучит громкостью бита.
PREVIEW_SECONDS = 30.0
TRACK_MAX = 10.0
TRACK_BEAT = 0.12
TRACK_LUFS = -14.0
# За сколько секунд бит стихает под наложенным звуком (overlay с beat меньше 1).
OVERLAY_EASE = 0.6

ID_FORMAT = re.compile(r"\d{8}-[a-z0-9-]+")
SLOT_FORMAT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}[+-]\d{2}:\d{2}")
HASHTAGS_AT_END = re.compile(r"(#\w+\s*)+$")

TODAY = "сегодня до 21:00 МСК"

# Нижняя граница кадра под фразой. Настоящую длину задаёт дубль (clips.narrate),
# эта нужна, чтобы и без дубля кадр было видно в превью.
SAY_SECONDS = 1.5
STILL_ZOOM = 0.07

# Безопасная зона кадра, доли ширины и высоты: всё своё текстовое и метка — внутри.
# Замер по записи экрана iPhone с опубликованным keef3 в Shorts, 16.09.2026:
# на высоком экране Shorts растягивает ролик и срезает по 4,5% ширины с боков;
# сверху до 12% высоты — панель со стрелкой «назад» и поиском (метка в углу
# сидела под стрелкой, значок срезан краем); справа от 81% ширины на 52–91%
# высоты — колонка лайка, комментариев и «поделиться»; снизу от 80% — канал,
# название и просмотры. У TikTok и VK Клипов так же: колонка справа, подпись
# снизу, — поэтому зона одна на все площадки, с запасом от каждой границы.
SAFE_LEFT, SAFE_RIGHT = 0.07, 0.80
SAFE_TOP, SAFE_BOTTOM = 0.13, 0.78
# Надпись по центру кадра не шире этой доли: правый край упирается в колонку кнопок.
SAFE_TEXT = 2 * min(0.5 - SAFE_LEFT, SAFE_RIGHT - 0.5)

# Плашка-концовка: длина, аватар и где по высоте адрес под ним; метка по ходу ролика.
PLATE_SECONDS = 1.3
PLATE_BG = (22, 21, 24)
WHEEL = config.ROOT / "assets" / "avatar" / "avatar-wheel.mp4"
# Аватар по ширине в SAFE_TEXT: шире — его правый бок уходит под кнопки.
PLATE_WHEEL = 640
PLATE_TOP = 530
ENDING_Y = 0.675
# Строка-приманка под адресом: зачем идти в канал. Низ — выше SAFE_BOTTOM с запасом.
BAIT = "пришли свой трек в бота"
BAIT_Y = 0.735
# Метка — левый верхний угол безопасной зоны: правее среза и ниже панели.
BADGE_XY = (round(SAFE_LEFT * 1080), round(SAFE_TOP * 1920))
BADGE_HEIGHT = 80
# Звук TikTok-версии гаснет, а не обрывается на последнем слове.
TIKTOK_FADE = 0.3
TELEGRAM_BLUE = (42, 171, 238)
NOSUB_MARK = ".nosub"
AT_MARK = ".at"
# Всё обрезается под 9:16. Шире этого — панорама, от которой в кадре осталась
# бы пятая часть, и только она встаёт целиком на размытую копию.
BLUR_WIDER = 2.4
# Мемная надпись (`caption`) — сверху, как в пересылаемых мемах, но под меткой.
CAPTION_TOP = 350
CAPTION_SIZES = ((150, 1), (128, 1), (112, 1), (96, 1), (88, 1), (112, 2), (96, 2), (80, 3))

# Субтитры: слов в куске, центр по высоте кадра — обычно и когда внизу своя
# надпись (тогда ниже метки). Кегль один на весь ролик: на keef3 кегль под
# длину куска скакал от куска к куску. Ширина — SAFE_TEXT, и кусок, который
# в две строки не лезет, режет chunks (SUB_LETTERS), а не мельчит шрифт:
# 88 точек и 18 букв — ни одного куска в три строки на всех сценариях 16.09.2026.
SUB_WORDS = 4
SUB_LETTERS = 18
SUB_SIZE = 88
# Белые буквы на белом (логотип GTA, футболка) сливались: обводка вдвое толще мемной
# и мягкий тёмный ореол под буквами, ~60% черноты. Кадр целиком не темнеет —
# картинка по решению владельца чистая.
SUB_STROKE = 9
SUB_HALO = 24
SUB_HALO_ALPHA = 150
SUB_LOW = 0.68
SUB_HIGH = 0.25
TOP_MARK = ".top"

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
           for field in ("label", "text", "query", "id", "template", "url", "caption", "video")):
        return [f"{where}: label, text, caption, query, id, template, url и video — строки"]
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
        if BOT_LINK not in description:
            errors.append(f"description: нет приманки со ссылкой {BOT_LINK} — строка из «Тянуть в Telegram» в брифе")

    comment = script.get("comment")
    if "comment" in script and not (_filled(comment) and len(comment) <= COMMENT_MAX):
        errors.append(f"comment: первый комментарий — непустая строка до {COMMENT_MAX} знаков")

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
        if "pause" in line and ("say" in line or "track" in line) or not {"say", "pause", "track"} & line.keys():
            errors.append(f"{where}: нужно say, track или pause — пауза без say и track")
        elif "say" in line and not _filled(line["say"]):
            errors.append(f"{where}: пустая фраза")
        elif "pause" in line and not (_number(line["pause"]) and 0 < line["pause"] <= PAUSE_MAX):
            errors.append(f"{where}: pause — секунды, больше нуля и не больше {PAUSE_MAX:g}")
        if "track" in line:
            errors += _track_problems(line["track"], where)
        if "overlay" in line:
            errors += _overlay_problems(line["overlay"], where)
        if not isinstance(line.get("hint", ""), str):
            errors.append(f"{where}: hint — строка")
        if "subtitle" in line and not ("say" in line and _filled(line["subtitle"])):
            errors.append(f"{where}: subtitle — непустая строка у фразы: её текст в субтитрах, числа цифрами")
        errors += _screens_problems(line.get("screen"), where, sources if isinstance(sources, list) else [])
    return errors


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _overlay_problems(overlay, where: str) -> list[str]:
    if not (isinstance(overlay, dict) and isinstance(overlay.get("file"), str) and MUSIC_FORMAT.fullmatch(overlay["file"])
            and not overlay["file"][:1].isdigit() and _number(overlay.get("at")) and _number(overlay.get("length"))
            and overlay["at"] >= 0 and 0 < overlay["length"] <= TRACK_MAX
            and (_number(overlay.get("beat", 1)) and 0 <= overlay.get("beat", 1) <= 1)):
        return [f"{where}: overlay — {{file: звук в папке ролика, имя не с цифры, at: секунда строки, "
                f"length: до {TRACK_MAX:g} с, beat: громкость бита под ним от 0 до 1, по умолчанию 1}}"]
    return []


def _track_problems(track, where: str) -> list[str]:
    if not isinstance(track, dict) or not (
        isinstance(track.get("id"), int) and not isinstance(track["id"], bool) and track["id"] > 0
        or _filled(track.get("query"))
    ):
        return [f"{where}: track — объект с id трека iTunes (число) или query «артист — трек»"]
    start, length = track.get("start", 0), track.get("length")
    if not (_number(start) and _number(length) and start >= 0 and 0 < length <= TRACK_MAX
            and start + length <= PREVIEW_SECONDS):
        return [f"{where}: у track length до {TRACK_MAX:g} с, start от 0, start + length не больше {PREVIEW_SECONDS:g}"]
    return []


def line_seconds(line: dict) -> float:
    """Длина строки до дублей: пауза, отрывок трека или нижняя граница фразы."""
    if "pause" in line:
        return float(line["pause"])
    length = float(line.get("track", {}).get("length", 0))
    base = max(SAY_SECONDS, length) if "say" in line else length
    # Строка дотягивается до конца наложенного звука: следующая фраза — сразу за его обрывом.
    over = line.get("overlay")
    return max(base, float(over["at"]) + float(over["length"])) if isinstance(over, dict) else base


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
    if "track" in line:
        text += "\n<i>поверх отрывка трека</i>"
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

    def pic(path: Path) -> dict:
        at = path.with_suffix(AT_MARK)
        return {"kind": PIC, "path": str(path), **({"at": float(at.read_text().strip())} if at.exists() else {}),
                **({"nosub": True} if path.with_suffix(NOSUB_MARK).exists() else {})}

    return {**script, "lines": [
        {**line, "screen": [pic(p) for p in found]} if (found := pictures(folder, number)) else line
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


def caption(layer, text: str, sizes=CAPTION_SIZES, stroke: int = 0, halo: int = 0):
    """Мемная надпись сверху кадра: белые буквы с чёрной обводкой и тенью.

    Узкий жирный Oswald, а не Arimo мемов канала (card.render_meme): поверх
    полноэкранного видео надпись должна читаться с первого взгляда, а в одну
    строку узкого шрифта та же фраза влезает заметно крупнее. Вид — как у мемов
    из пересылки: белые буквы, чёрная обводка. Отдельно от `text`: та надпись —
    ярлык фразы в нижней трети, а эта — реплика самого мема, её место сверху.
    Верх кадра под неё свободен не всегда: фото выбирай, где голова героя
    ниже верхней пятой части. Ширина — SAFE_TEXT вместе с обводкой.
    `sizes` — кегли по очереди с числом строк; у субтитров он один. `stroke` —
    обводка в точках (0 — по кеглю), `halo` — радиус широкого тёмного ореола (0 — без него).
    """
    from PIL import Image, ImageDraw, ImageFilter

    from . import card, stories

    ink = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(ink)
    # Одна строка крупно лучше двух, две — лучше мелкой одной. Тире не уезжает
    # на строку одно: на время переноса оно приклеено к слову знаком из личной
    # области Юникода — он не пробел и шире пробела, так что строка не вылезет.
    glued = text.strip().replace(" —", "\ue000—")
    for size, most in sizes:
        font, outline = stories.font(size, 600), stroke or max(4, size // 16)
        lines = [line.replace("\ue000", " ") for line in card._wrap(draw, glued, font, layer.width * SAFE_TEXT - 2 * outline)]
        if len(lines) <= most:
            break
    for number, line in enumerate(lines):
        draw.text(
            (layer.width / 2, CAPTION_TOP + number * size * 1.1), line, font=font, fill=(255, 255, 255, 255),
            anchor="ma", stroke_width=outline, stroke_fill=(0, 0, 0, 255),
        )
    shade = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    shade.putalpha(ink.getchannel("A").filter(ImageFilter.GaussianBlur(10)).point(lambda a: min(255, a * 2)))
    if halo:
        glow = Image.new("RGBA", layer.size, (0, 0, 0, 0))
        glow.putalpha(ink.getchannel("A").filter(ImageFilter.GaussianBlur(halo)).point(lambda a: min(SUB_HALO_ALPHA, a * 3)))
        layer = Image.alpha_composite(layer, glow)
    return Image.alpha_composite(Image.alpha_composite(layer, shade), ink)


def splits(line_screens: list[dict], length: float) -> list[float]:
    """Где кончается каждый кадр строки, секунды от её начала.

    Поровну, но кадр с `at` начинается в свою секунду: кадры перед ним делят
    время до неё. У первого кадра `at` не действует — строка с него и начинается.
    """
    out: list[float] = []
    start = 0
    for number in range(1, len(line_screens) + 1):
        at = line_screens[number]["at"] if number < len(line_screens) and "at" in line_screens[number] else None
        if number < len(line_screens) and at is None:
            continue
        begin = out[-1] if out else 0.0
        stop = length if at is None else min(max(at, begin), length)
        out += [begin + (stop - begin) * k / (number - start) for k in range(1, number - start + 1)]
        start = number
    return out


def storyboard(script: dict, work: Path, seconds: list[float] | None = None) -> list:
    """Кадры ролика по порядку: у строки их от одного до трёх.

    Заставки с маркой в конце, как у клипов, нет: крючок у сценария уже есть
    первой фразой, а три секунды заставки — это три секунды, на которых ролик
    пролистывают, и повтор по кругу начинался бы с неё, а не с крючка.

    `seconds` — длины строк, когда они уже известны по дублям. Строка делится
    между своими кадрами по splits. Границы округляются до кадра видео от начала
    ролика, а не у каждого кадра отдельно: на двух десятках склеек погрешность
    иначе копилась бы, и голос к концу уезжал от картинки.

    Карточка берёт соседний кадр — прежний, а у первой строки следующий.
    Надписей `text` и `label` нет: их заменили субтитры.
    """
    from PIL import Image

    from . import clips

    lengths = seconds or [line_seconds(line) for line in script["lines"]]
    ends = [splits(screens(line), length) for line, length in zip(script["lines"], lengths)]
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
        end = round((line_start + ends[index][part]) * clips.FPS) / clips.FPS
        nearest = list(range(number - 1, -1, -1)) + list(range(number + 1, len(plan)))
        fill = fills[number] or next((fills[i] for i in nearest if fills[i]), {})
        layer = Image.new("RGBA", (clips.WIDTH, clips.HEIGHT))
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


def _excerpt(track: dict, dest: Path) -> Path | None:
    """Отрывок трека из превью iTunes: кусок start…start+length громкостью TRACK_LUFS. None — трек не нашёлся.

    Превью, а не сам трек: его магазин отдаёт всем без ключа (тот же путь,
    что у СЛЕПОЙ ПРОСЛУШКИ, src/quiz.py), а длиннее отрывку и не надо.
    """
    from . import clips
    from .sources import itunes

    url = itunes.song_preview(track.get("id") or track["query"])
    if not url or not _download(url, dest, 10_000):
        log.warning("Отрывок трека %s не нашёлся — на его месте бит", track.get("id") or track["query"])
        return None
    start, length, cut = float(track.get("start", 0)), float(track["length"]), dest.with_suffix(".wav")
    # Края — короткой наплывкой: отрывок, обрезанный посреди волны, щёлкает.
    clips.run([clips.ffmpeg(), "-y", "-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", str(dest),
               "-af", f"afade=t=in:d=0.02,afade=t=out:st={max(length - 0.05, 0):.3f}:d=0.05",
               "-ar", "48000", "-ac", "2", str(cut)])
    # Громкость меряется окном 0,4 с: у секундного отрывка другой не будет, а тишина дала бы -70.
    gain = min(TRACK_LUFS - _meter(cut)[0], 12.0)
    out = dest.with_name(f"{dest.stem}-level.wav")
    clips.run([clips.ffmpeg(), "-y", "-i", str(cut), "-af", f"volume={gain:.1f}dB", str(out)])
    return out


def _under_tracks(beat: Path, pieces: list[tuple[Path, float, float]], work: Path,
                  overlays: list[tuple[Path, float, float, float]] = ()) -> Path:
    """Бит с отрывками треков: (файл, секунда начала, длина). На отрывке бит почти молчит.

    `overlays` — звук поверх бита (поле строки `overlay`): (файл, начало, длина, бит).
    Бит под ним стихает до своей доли плавно, за OVERLAY_EASE, — песня вступает
    «перед дропом», а не выключает подложку (владелец, gta6).
    Кусок песни в такт слову («…да под Шамана» — и сразу «Я ру…») нельзя вклеить
    в дубль: дубль длиннее — и субтитры фразы растягиваются на весь кусок, отставая
    от голоса (gta6, 16.09.2026). В бите он ещё и проседает под голосом владельца,
    как подложка, и остаётся стерео.

    Сведение до assemble, а не в нём: там голос сайдчейном проседает подложку,
    и отрывок под голосом строки проседает так же — голос остаётся сверху.
    """
    if not pieces and not overlays:
        return beat
    from . import clips

    windows = "+".join(f"between(t,{at:.3f},{at + length:.3f})" for _, at, length in pieces) or "0"
    level = "*".join(
        [f"if({windows},{TRACK_BEAT},1)"]
        + [f"if(between(t,{at:.3f},{at + length:.3f}),1-{1 - share:.3f}*min(1,(t-{at:.3f})/{OVERLAY_EASE}),1)"
           for _, at, length, share in overlays if share < 1]
    )
    inputs = [*pieces, *[(path, at, length) for path, at, length, _ in overlays]]
    delays = "".join(
        f"[{n}:a]atrim=0:{length:.3f},aformat=sample_rates=48000:channel_layouts=stereo,"
        f"adelay={at * 1000:.0f}|{at * 1000:.0f}[t{n}];"
        for n, (_, at, length) in enumerate(inputs, 1)
    )
    out = work / "beat-tracks.wav"
    clips.run([
        clips.ffmpeg(), "-y", "-i", str(beat), *[arg for path, _, _ in inputs for arg in ("-i", str(path))],
        "-filter_complex",
        f"[0:a]aformat=sample_rates=48000:channel_layouts=stereo,"
        f"volume='{level}':eval=frame[b];{delays}"
        f"[b]{''.join(f'[t{n}]' for n in range(1, len(inputs) + 1))}amix=inputs={len(inputs) + 1}:duration=first:normalize=0",
        str(out),
    ])
    return out


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


def chunks(say: str) -> list[str]:
    """Фраза кусками по 2–4 слова. Режется после трёх слов или на знаке
    препинания после двух, но одинокое последнее слово не остаётся — оно
    прирастает к куску. Тире отдельным «словом» не считается."""
    words: list[str] = []
    for word in say.split():
        if words and not any(ch.isalnum() for ch in word):
            words[-1] += f" {word}"
        else:
            words.append(word)
    out, current = [], []
    for index, word in enumerate(words):
        current.append(word)
        left = len(words) - index - 1
        # Длинные слова режутся раньше: «общественной безопасности» четырьмя
        # словами не влезают и в две строки SUB_SIZE, а кегль не мельчает.
        # Конец предложения держит кусок при себе: «сентября. После» — два разных смысла.
        ends = word.rstrip("»")[-1:] in ".!?"
        after = words[index + 1] if left else ""
        longer = left and len(current) >= 2 and sum(map(len, current + [after])) > SUB_LETTERS \
            and not after.rstrip("»")[-1:] in ".!?"
        if not left or len(current) == SUB_WORDS or (
            left != 1 and (ends or longer or len(current) == 3 or (len(current) == 2 and word[-1] in ",:;—"))
        ):
            out.append(" ".join(current))
            current = []
    return out


def cues(script: dict, seconds: list[float], takes: dict[int, float]) -> list[tuple[str, float, float]]:
    """Куски субтитров с временем: (текст, начало, конец) от начала ролика.

    `seconds` — длины строк, `takes` — длина обрезанного дубля по номеру кадра.
    Речь в дубле начинается через BEFORE_SPEECH и кончается за AFTER_SPEECH
    до конца (_trimmed), между ними время делится по буквам (и немного поровну):
    «по-расистски» говорится дольше, чем «и не».
    """
    out, start = [], 0.0
    for number, (line, length) in enumerate(zip(script["lines"], seconds), 1):
        take = takes.get(number, 0.0)
        if "say" in line and take > BEFORE_SPEECH + AFTER_SPEECH:
            begin, end = start + BEFORE_SPEECH, start + take - AFTER_SPEECH
            parts = chunks(line.get("subtitle") or line["say"])
            # Плюс четыре буквы на кусок: «не я.» по голосу короче четверти секунды, не прочитать.
            weights = [sum(ch.isalnum() for ch in part) + 4 for part in parts]
            done = 0
            for part, weight in zip(parts, weights):
                first = begin + (end - begin) * done / sum(weights)
                done += weight
                out.append((part, first, begin + (end - begin) * done / sum(weights)))
        start += length
    return out


def place(timing: list[tuple[str, float, float]], flat: list[dict], ends: list[float]) -> list[tuple[str, float, float, bool]]:
    """Куски субтитров с высотой: наверх, если хоть один кадр под куском с надписью внизу
    (кусок переходит через склейку — на пилоте «14 лет концерт» лёг бы на его книжку).
    Под кадром с nosub в начале куска — без субтитра."""
    placed = []
    for text, first, end in timing:
        starts = [0.0, *ends[:-1]]
        under = [screen for screen, a, b in zip(flat, starts, ends) if a < end and first < b] or flat[-1:]
        if not under[0].get("nosub"):
            placed.append((text, first, end, any(map(high, under))))
    return placed


def high(screen: dict) -> bool:
    """Субтитр наверх: внизу картинки своя надпись, у неё метка .top. Ярлыков сценария в кадре нет."""
    return screen["kind"] == PIC and Path(screen["path"]).with_suffix(TOP_MARK).exists()


def subtitle(text: str, up: bool):
    """Кадр субтитра: прозрачный 1080×1920, кусок стоит на своей высоте, кегль SUB_SIZE до двух строк."""
    from PIL import Image

    from . import clips

    ink = caption(Image.new("RGBA", (clips.WIDTH, clips.HEIGHT)), text, sizes=((SUB_SIZE, 2),),
                  stroke=SUB_STROKE, halo=SUB_HALO)
    left, top, right, bottom = ink.getbbox()
    frame = Image.new("RGBA", ink.size)
    frame.alpha_composite(ink.crop((0, top, clips.WIDTH, bottom)),
                          (0, round(clips.HEIGHT * (SUB_HIGH if up else SUB_LOW) - (bottom - top) / 2)))
    return frame


def telegram_icon(size: int):
    """Значок Telegram своим рисунком: голубой круг и белый бумажный самолётик."""
    from PIL import Image, ImageDraw

    big = size * 4
    icon = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(icon)
    draw.ellipse((0, 0, big - 1, big - 1), fill=(*TELEGRAM_BLUE, 255))

    def at(x: float, y: float) -> tuple[float, float]:
        return big / 2 + x * big / 2, big / 2 + y * big / 2

    draw.polygon([at(-0.56, -0.02), at(0.46, -0.42), at(0.28, 0.44)], fill=(255, 255, 255, 255))
    draw.polygon([at(-0.12, 0.14), at(0.32, -0.26), at(-0.08, 0.40)], fill=(200, 224, 242, 255))
    draw.polygon([at(-0.56, -0.02), at(-0.12, 0.14), at(0.46, -0.42)], fill=(255, 255, 255, 255))
    return icon.resize((size, size), Image.LANCZOS)


def handle_mark(height: int, pill: bool):
    """Значок Telegram и адрес канала одной строкой; `pill` — на полупрозрачной подложке."""
    from PIL import Image, ImageDraw

    from . import stories

    font = stories.font(round(height * 0.62), 600)
    draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    left, top, right, bottom = draw.textbbox((0, 0), config.CHANNEL_HANDLE, font=font)
    icon = round(height * 0.72)
    pad = round(height * 0.2)
    width = pad + icon + pad + (right - left) + pad * 2
    mark = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ink = ImageDraw.Draw(mark)
    if pill:
        ink.rounded_rectangle((0, 0, width - 1, height - 1), radius=height // 2, fill=(0, 0, 0, 120))
    mark.alpha_composite(telegram_icon(icon), (pad, (height - icon) // 2))
    ink.text((pad * 2 + icon - left, (height - (bottom - top)) / 2 - top), config.CHANNEL_HANDLE, font=font,
             fill=(255, 255, 255, 255), stroke_width=max(2, height // 30), stroke_fill=(0, 0, 0, 255))
    return mark


def badge():
    """Метка по ходу основного ролика: небольшая, в левом верхнем углу безопасной зоны."""
    from PIL import Image

    from . import clips

    frame = Image.new("RGBA", (clips.WIDTH, clips.HEIGHT))
    frame.alpha_composite(handle_mark(BADGE_HEIGHT, pill=True), BADGE_XY)
    return frame


def ending():
    """Адрес канала на плашке-концовке: крупно, со значком, под аватаром, и под ним приманка."""
    from PIL import Image, ImageDraw

    from . import clips, stories

    mark = handle_mark(150, pill=False)
    frame = Image.new("RGBA", (clips.WIDTH, clips.HEIGHT))
    frame.alpha_composite(mark, ((clips.WIDTH - mark.width) // 2, round(clips.HEIGHT * ENDING_Y - mark.height / 2)))
    ImageDraw.Draw(frame).text((clips.WIDTH / 2, clips.HEIGHT * BAIT_Y), BAIT, font=stories.font(64, 600), anchor="mm",
                               fill=(255, 255, 255, 255), stroke_width=3, stroke_fill=(0, 0, 0, 255))
    return frame


def plate(work: Path) -> Path:
    """Плашка-концовка: крутящийся аватар канала (assets/avatar/avatar-wheel.mp4) крупно, круглой маской.

    Настоящий аватар канала (его же отдаёт getChat @plenka_fm), а не нарисованная
    кассета: по нему канал узнают в Telegram, куда ролик и зовёт.
    """
    from . import clips

    out = work / "plate.mp4"
    side = PLATE_WHEEL
    clips.run([
        clips.ffmpeg(), "-y",
        "-f", "lavfi", "-i", f"color=c=0x{PLATE_BG[0]:02x}{PLATE_BG[1]:02x}{PLATE_BG[2]:02x}:s={clips.WIDTH}x{clips.HEIGHT}"
                             f":r={clips.FPS}:d={PLATE_SECONDS}",
        "-stream_loop", "-1", "-i", str(WHEEL),
        "-filter_complex",
        f"[1:v]scale={side}:{side},fps={clips.FPS},format=rgba,"
        f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='255*clip({side / 2 - 1}-hypot(X-{side / 2},Y-{side / 2}),0,1)'[w];"
        f"[0:v][w]overlay={(clips.WIDTH - side) // 2}:{PLATE_TOP}:shortest=1,format=yuv420p",
        "-t", f"{PLATE_SECONDS}", "-c:v", "libx264", "-crf", "20", str(out),
    ])
    return out


def tiktok(video: Path) -> Path:
    return video.with_name(f"{video.stem}-tiktok.mp4")


def burn(video: Path, placed: list[tuple[str, float, float, bool]], work: Path, ending_at: float) -> None:
    """Вжигает субтитры, метку и адрес на концовке одним проходом и пишет два файла: основной и для TikTok.

    Не в отрезки: кусок субтитра переходит через склейку кадров. Все куски —
    один вход: список кадров с длительностями (concat), пустой прозрачный кадр
    закрывает паузы; тридцать картинок-входов ffmpeg не тянул и вставал.
    Метка до `ending_at` и концовка после — только в основном файле. TikTok-версия
    кончается на `ending_at`, со звуком, гаснущим за TIKTOK_FADE: аватар без
    адреса никуда не зовёт (владелец, 16.09.2026), а оборванный на полудоле бит
    звучит поломкой.
    """
    from PIL import Image

    from . import clips

    blank = work / "sub-0.png"
    Image.new("RGBA", (clips.WIDTH, clips.HEIGHT)).save(blank)
    badge().save(work / "badge.png")
    ending().save(work / "ending.png")
    entries, now = [], 0.0
    for number, (text, first, end, up) in enumerate(placed, 1):
        # Щель короче кадра — не пауза, а погрешность деления строки: пустой
        # кадр нулевой длины сбивал concat, и субтитры до конца ролика пропадали.
        if first - now > 0.02:
            entries.append((blank, first - now))
        path = work / f"sub-{number}.png"
        subtitle(text, up).save(path)
        entries.append((path, end - max(first, now)))
        now = end
    entries.append((blank, 1.0))
    listing = work / "subs.txt"
    # Последний файл повторён без длительности — так concat учитывает длительность предпоследнего.
    listing.write_text("".join(f"file '{p}'\nduration {d:.3f}\n" for p, d in entries) + f"file '{blank}'\n",
                       encoding="utf-8")
    raw = work / "no-subs.mp4"
    video.replace(raw)
    encode = ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-movflags", "+faststart"]
    # Граница концовки — номером кадра, а не секундой: секунда в три знака округляется
    # вверх мимо кадра (34,967 > 34,9667), и первый кадр плашки мелькал в конце TikTok-версии.
    # В overlay граница — временем посередине между кадрами, а не `n`, и картинки идут
    # с частотой ролика: по умолчанию -loop даёт 25 кадров против 30, и ffmpeg в Actions
    # считал `n` не по тем кадрам — адрес на концовке горел на одном кадре из шести,
    # мигал (gta6, 16.09.2026). Локальный ffmpeg новее и этого не показывал.
    plate_frame = round(ending_at * clips.FPS)
    edge = (plate_frame - 0.5) / clips.FPS
    clips.run([
        # reinit_filter 0: отрезки ролика разные по цветовому диапазону (фото — pc, видео — tv),
        # и на каждой смене ffmpeg пересобирал граф, теряя вход субтитров до конца ролика.
        clips.ffmpeg(), "-y", "-reinit_filter", "0", "-i", str(raw), "-f", "concat", "-safe", "0", "-i", str(listing),
        "-loop", "1", "-framerate", f"{clips.FPS}", "-i", str(work / "badge.png"),
        "-loop", "1", "-framerate", f"{clips.FPS}", "-i", str(work / "ending.png"),
        "-filter_complex",
        "[1:v]format=rgba[s];[0:v][s]overlay=0:0:eof_action=pass:format=auto,split[b1][b2];"
        f"[2:v]format=rgba[m];[b1][m]overlay=0:0:shortest=1:enable='lt(t,{edge:.4f})'[marked];"
        f"[3:v]format=rgba[e];[marked][e]overlay=0:0:shortest=1:enable='gte(t,{edge:.4f})',format=yuv420p[main];"
        f"[b2]trim=end_frame={plate_frame},format=yuv420p[tt];"
        f"[0:a]atrim=end={ending_at:.3f},afade=t=out:st={max(ending_at - TIKTOK_FADE, 0):.3f}:d={TIKTOK_FADE}[ta]",
        "-map", "[main]", "-map", "0:a", *encode, "-c:a", "copy", str(video),
        "-map", "[tt]", "-map", "[ta]", *encode, "-c:a", "aac", "-b:a", "160k", str(tiktok(video)),
    ])


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
        lines = [clips.Shot(None, line_seconds(line), "", "") for line in script["lines"]]
        timed, voice = clips.narrate(lines, script, work, kind="reels", voices=takes, lead=0.0, tail=TAIL)
        shots = storyboard(script, work, [shot.seconds for shot in timed])
        flat = [screen for line in script["lines"] for screen in screens(line)]
        from PIL import Image

        # Концовка — отдельный кадр после последнего: аватар канала, адрес под ним вжигает burn.
        shots.append(clips.Shot(Image.new("RGBA", (clips.WIDTH, clips.HEIGHT)), PLATE_SECONDS, "", "",
                                backdrop=str(plate(work))))
        flat.append({"kind": "plate"})
        total = sum(shot.seconds for shot in shots)

        parts, used = [], []
        for index, (shot, screen) in enumerate(zip(shots, flat)):
            parts.append(work / f"part-{index}.mp4")
            # Склейки встык, без выхода из чёрного: при смене кадра каждые
            # две-три секунды он мигал бы темнотой.
            used.append(f"{screen['kind']}→" + clips.segment(
                shot, parts[-1], work, fade_in=False,
                grade="",
                fit=fit(screen, shot.backdrop),
                focus=float(screen.get("focus", 0.5)),
                zoom_out=bool(index % 2), zoom=STILL_ZOOM,
            ))
        print("  кадры:", ", ".join(used))
        print(f"  голос: {'есть' if voice else 'нет'}, длина {total:.1f} с")

        if voice:
            # Голос — до конца плашки тишиной: сайдчейн кончается вместе с голосом,
            # и -shortest срезал бы концовку.
            padded = work / "voice-padded.wav"
            clips.run([clips.ffmpeg(), "-y", "-i", str(voice), "-af", f"apad=whole_dur={total:.3f}", str(padded)])
            voice = padded
        starts = [sum(shot.seconds for shot in timed[:index]) for index in range(len(timed))]
        pieces = [(piece, at, line["track"]["length"]) for index, (line, at) in enumerate(zip(script["lines"], starts))
                  if "track" in line and (piece := _excerpt(line["track"], work / f"track-{index}.m4a"))]
        overlays = [(voices / line["overlay"]["file"], at + line["overlay"]["at"], line["overlay"]["length"],
                     float(line["overlay"].get("beat", 1)))
                    for line, at in zip(script["lines"], starts)
                    if "overlay" in line and voices and (voices / line["overlay"]["file"]).is_file()]
        clips.assemble(
            parts, _under_tracks(_beat(script, total, work), pieces, work, overlays), total, video, work, voice, 0.0,
            voice_grade=VOICE_CHAIN, duck=DUCK,
        )
        ends = [sum(shot.seconds for shot in shots[:index + 1]) for index in range(len(shots))]
        lengths = {int(take.stem): clips.probe_seconds(take) for take in takes.glob("*.wav")}
        placed = place(cues(script, [shot.seconds for shot in timed], lengths), flat, ends)
        burn(video, placed, work, ending_at=total - PLATE_SECONDS)
        print(f"  субтитры: {len(placed)} кусков, наверху {sum(p[3] for p in placed)}")

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

    def described(label: str) -> str:
        # Сценарий пишет одну ссылку, а по метке бот считает приходы с каждой площадки.
        text = re.sub(re.escape(BOT_LINK) + r"(\?start=\w+)?", f"{BOT_LINK}?start={label}", script["description"])
        return field(text)

    comment = f"Закрепи первым комментарием: {field(script['comment'])}\n\n" if script.get("comment") else ""
    return (
        f"<b>Название</b>\n{field(script['title'])}\n\n"
        f"<b>Описание YouTube</b>\n{described('yt')}\n\n"
        f"<b>ВКонтакте</b>\n{described('vk')}\n\n"
        f"<b>TikTok</b>\n{described('tt')}\n\n"
        f"<b>Теги</b>\n{field(', '.join(script['tags']))}\n\n"
        f"{comment}Выложить: <b>{when(script)}</b>"
    )


def deliver(script: dict, video: Path, cover: Path) -> None:
    """Пакет владельцу: ролик, превью файлом и текст полей."""
    from . import telegram

    admin = config.secret("TELEGRAM_ADMIN_ID")
    topic = f"<b>{html.escape(script['topic'], quote=False)}</b>"
    telegram.send_video_file(admin, video, f"{topic}\nдля YouTube и VK")
    if tiktok(video).exists():
        telegram.send_video_file(admin, tiktok(video), f"{topic}\nдля TikTok — без концовки и адреса канала")
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

    def inked(layer) -> tuple[int, int, int, int]:
        """Рамка белых букв надписи — без чёрной обводки и тени."""
        from PIL import Image

        ground = Image.new("RGBA", layer.size, (0, 0, 0, 255))
        return Image.alpha_composite(ground, layer).convert("L").point(lambda v: 255 if v > 240 else 0).getbbox()

    good = {
        "id": "20260914-test",
        "topic": "Проверка",
        "publish": "today",
        "sources": ["https://example.com/news"],
        "title": "Проверка формата",
        "description": f"Строка описания. Пришли свой трек в бота: {BOT_LINK}?start=yt #фонк #плёнка",
        "tags": ["фонк", "плёнка"],
        "comment": "Кто прав: артист или пилот?",
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
    broken(BOT_LINK, description="Описание без приманки #фонк")
    broken("comment", comment="х" * (COMMENT_MAX + 1))
    broken("comment", comment="")
    assert problems({k: v for k, v in good.items() if k != "comment"}, good["id"]) == []
    assert f"Закрепи первым комментарием: <code>{good['comment']}</code>" in package(good)
    assert "Закрепи" not in package({k: v for k, v in good.items() if k != "comment"})
    assert all(f"{BOT_LINK}?start={label} #фонк" in package(good) for label in ("yt", "vk", "tt")), "метки площадок"
    # Отрывок трека: строка без голоса длится ровно length, с голосом — не меньше фразы.
    clip = {"track": {"id": 1440818839, "start": 12, "length": 2}, "screen": {"kind": "stock", "query": "crowd"}}
    assert problems({**good, "lines": [*good["lines"], clip, {**clip, "say": "Поверх", "track": {"query": "a — b", "length": 1}}]},
                    good["id"]) == []
    assert line_seconds(clip) == 2 and line_seconds({**clip, "say": "ф", "track": {"length": 1}}) == SAY_SECONDS
    # Наложенный звук: строка тянется до его конца; имя с цифры сборка приняла бы за дубль.
    over = {"say": "Фраза", "overlay": {"file": "shaman.wav", "at": 2.2, "length": 3.6}, "screen": clip["screen"]}
    assert problems({**good, "lines": [*good["lines"], over]}, good["id"]) == []
    assert abs(line_seconds(over) - 5.8) < 1e-9 and line_seconds({"say": "ф"}) == SAY_SECONDS
    for overlay in ({"file": "4.wav", "at": 1, "length": 1}, {"file": "a.txt", "at": 1, "length": 1},
                    {"file": "a.wav", "at": -1, "length": 1}, {"file": "a.wav", "at": 1, "length": 11},
                    {"file": "a.wav", "at": 1, "length": 1, "beat": 2}):
        broken("overlay", lines=[{**over, "overlay": overlay}])
    assert spoken_frames({"lines": [clip, {"say": "ф"}]}) == [2] and "поверх отрывка" in line_text(1, 1, {**clip, "say": "ф"})
    for track, word in (({"id": 5, "length": 11}, "length"), ({"id": 5, "start": 25, "length": 6}, "start + length"),
                        ({"length": 2}, "id трека"), ({"id": 5.0, "length": 2}, "id трека"), ({"query": "a"}, "length")):
        broken(word, lines=[{**clip, "track": track}])
    broken("пауза без", lines=[{"pause": 1.0, "track": clip["track"], "screen": clip["screen"]}])
    broken("строки", lines=[{"say": "Фраза", "screen": {"kind": "photo", "url": good["sources"][0], "video": 5}}])
    broken("именем файла", id="20260915-other")
    broken("publish", publish="завтра")
    broken("tags", tags=["фонк, рэп"])
    broken("фразы", lines=[{"pause": 1.0, "screen": {"kind": "card", "text": "тишина"}}])
    broken("пауза без", lines=[{"say": "Фраза", "pause": 1.0, "screen": {"kind": "card", "text": "т"}}])
    broken("music", music="../beat.mp3")
    broken("music", music="beat.ogg")
    broken("subtitle", lines=[{"say": "Фраза", "subtitle": "", "screen": {"kind": "card", "text": "т"}}])
    assert problems({**good, "lines": [{"say": "Четырнадцать лет", "subtitle": "14 лет",
                                        "screen": {"kind": "card"}}]}, good["id"]) == []
    photo = {"kind": "photo", "url": good["sources"][0], "query": "concert crowd"}
    assert problems({**good, "lines": [{"say": "Фраза", "screen": [photo, {"kind": "gif", "query": "bye"}]}]}) == []
    for screen, word in (
        ({"kind": "video"}, "kind"),
        ({"kind": "meme", "template": "нет-такого"}, "шаблона"),
        ({"kind": "face", "name": "Канье"}, "artists.json"),
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
        # Мемная надпись ложится сверху, под меткой и в безопасной зоне по ширине.
        band = (0, CAPTION_TOP, 1080, CAPTION_TOP + 100)
        assert shots[4].layer.crop(band).getchannel("A").getextrema()[1] > 0
        box = inked(caption(shots[4].layer.copy(), "мемная подпись длиной почти во всю ширину кадра"))
        assert box[0] >= SAFE_LEFT * 1080 and box[2] <= SAFE_RIGHT * 1080, box
        assert box[1] > BADGE_XY[1] + BADGE_HEIGHT and box[3] <= SAFE_BOTTOM * 1920, box
        assert shots[3].layer.crop(band).getchannel("A").getextrema()[1] == 0
        # Ярлыков сценария нет: у лица с именем, стока и карточки с text слой пустой.
        assert all(shot.layer.getchannel("A").getextrema()[1] == 0 for shot in shots[:4])

        # Кадр с at начинается в свою секунду, кадры до него делят время до неё.
        assert splits([{}, {}], 4.0) == [2.0, 4.0] and splits([{"at": 1.0}, {}], 4.0) == [2.0, 4.0]
        assert splits([{}, {}, {"at": 3.0}], 4.0) == [1.5, 3.0, 4.0]
        assert splits([{}, {"at": 9.0}], 4.0) == [4.0, 4.0]

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
        # Метка .at несёт секунду начала, .nosub выключает субтитры строки.
        (pics / "1-3.at").write_text("0.7\n", encoding="utf-8")
        (pics / "1-10.nosub").touch()
        mine = with_pictures(good, Path(tmp))
        assert [s.get("at") for s in screens(mine["lines"][0])] == [None, 0.7, None]
        assert [bool(s.get("nosub")) for s in screens(mine["lines"][0])] == [False, False, True]
        (pics / "1-3.mp4").unlink()
        (pics / "1-10.nosub").unlink()
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

    # Субтитры: куски до четырёх слов покрывают фразу целиком, идут внутри
    # речи строки по порядку без наложений; одинокое слово в конце не остаётся.
    said = {"lines": [
        {"say": "Пишет: это был не я. И не город. Пилот повёл себя очень по-расистски."},
        {"pause": 1.0},
        {"say": "Идеальный концерт: сразу «спасибо, Чикаго, всем пока»."},
        {"say": "Как угрозу общественной безопасности."},
    ]}
    timing = cues(said, [4.5, 1.0, 3.8, 2.9], {1: 4.3, 3: 3.6, 4: 2.7})
    starts = {1: 0.0, 3: 5.5, 4: 9.3}
    for number, line in enumerate(said["lines"], 1):
        if "say" not in line:
            continue
        parts = chunks(line["say"])
        assert all(1 <= len(part.split()) <= SUB_WORDS for part in parts), parts
        assert " ".join(parts).split() == line["say"].split() and len(parts[-1].split()) > 1, parts
        mine = [(a, b) for text, a, b in timing if text in parts and starts[number] <= a < starts[number] + 4.5]
        assert len(mine) == len(parts), (mine, parts)
        begin, end = starts[number] + BEFORE_SPEECH, starts[number] + {1: 4.3, 3: 3.6, 4: 2.7}[number] - AFTER_SPEECH
        assert abs(mine[0][0] - begin) < 1e-9 and abs(mine[-1][1] - end) < 1e-9, (mine, begin, end)
    assert all(a < b <= c for (_, a, b), (_, c, _) in zip(timing, timing[1:])), timing
    # subtitle подменяет say; под кадром с nosub куска нет, под кадром с .top он наверху.
    numbers = {"lines": [{"say": "После четырнадцати лет", "subtitle": "После 14 лет"}]}
    assert [text for text, *_ in cues(numbers, [2.0], {1: 1.8})] == ["После 14 лет"]
    shown = place([("а", 0.1, 0.9), ("б", 1.2, 1.8), ("в", 2.1, 2.9)],
                  [{"kind": "stock"}, {"kind": PIC, "path": "нет.jpg", "nosub": True}, {"kind": "stock"}], [1.0, 2.0, 3.0])
    assert [(text, up) for text, _, _, up in shown] == [("а", False), ("в", False)], shown
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "2.top").touch()
        marked = {"kind": PIC, "path": str(Path(tmp) / "2.jpg")}
        shown = place([("через склейку", 0.8, 1.3), ("до", 0.1, 0.5)], [{"kind": "stock"}, marked], [1.0, 2.0])
        assert [up for *_, up in shown] == [True, False], shown
    assert chunks("Пишет: это был не я.") == ["Пишет: это был", "не я."] and chunks("Одно") == ["Одно"]
    assert chunks("Её включили в соседнем городе — полиция остановила шоу почти сразу.")[1] == "соседнем городе —"
    # Наверх — только над надписью внизу картинки (метка .top); ярлыки сценария больше не рисуются.
    assert not high({"kind": "face", "name": "Bones"}) and not high({"kind": "card", "text": "т"})
    assert not high({"kind": "gif", "query": "bye", "caption": "я боюсь"})
    with tempfile.TemporaryDirectory() as tmp:
        pic = Path(tmp) / "1-2.jpg"
        assert not high({"kind": PIC, "path": str(pic)})
        pic.with_suffix(TOP_MARK).touch()
        assert high({"kind": PIC, "path": str(pic)})
    # Куски keef3 и keef2 одного кегля (кегль не подбирается) и не выше двух строк; буквы не заходят
    # ни под интерфейс внизу, ни под колонку кнопок справа, а поднятые — под метку. Ореол может.
    for say in [line["say"] for line in said["lines"] if "say" in line] + ["Концерт перенесли на двадцать третье сентября."]:
        for part in chunks(say):
            low, up = inked(subtitle(part, False)), inked(subtitle(part, True))
            assert low[3] - low[1] < 2.5 * SUB_SIZE, part
            assert 0.5 * 1920 < low[1] and low[3] <= SAFE_BOTTOM * 1920 and up[1] > BADGE_XY[1] + BADGE_HEIGHT, (part, low, up)
            assert SAFE_LEFT * 1080 <= low[0] and low[2] <= SAFE_RIGHT * 1080, (part, low)
    # Тире не висит одно на второй строке: переносится вместе со словом.
    dash = subtitle("соседнем городе —", False)
    bottom = inked(dash)[3]
    last = inked(dash.crop((0, bottom - SUB_SIZE // 2, 1080, bottom)))
    assert last[2] - last[0] > 2 * SUB_SIZE, last
    # Белое на белом читается: вокруг букв на белом кадре тёмный ореол, а не только тонкая обводка.
    from PIL import Image

    sub = subtitle("Как угрозу", False)
    box, on_white = inked(sub), Image.alpha_composite(Image.new("RGBA", sub.size, (255, 255, 255, 255)), sub).convert("L")
    # В 20–28 точках от белых букв: у обводки в 4 точки или без ореола там уже светлее 100.
    assert on_white.crop((box[0], box[1] - 28, box[2], box[1] - 20)).getextrema()[0] < 100, "ореола над буквами нет"
    assert on_white.crop((box[2] + 20, box[1], box[2] + 28, box[3])).getextrema()[0] < 100, "ореола справа от букв нет"

    # Вжигание: кусок виден в своё время и на своей высоте, в паузе кадр чистый.
    with tempfile.TemporaryDirectory() as tmp:
        from PIL import Image

        from . import clips

        # Ролик из двух отрезков с разным цветовым диапазоном, как склейка фото и видео, и плашки с аватаром.
        # Второй отрезок на кадр короче: плашка встаёт на 89-й кадр (2,9667 с), а не на круглую секунду,
        # как в сборке. Звук — тон на весь ролик, отдельной дорожкой, как в clips.assemble: так
        # кадры начинаются с нуля, и слышно, как гаснет конец TikTok-версии.
        for name, fmt, seconds in (("a", "yuvj420p", "1.5"), ("b", "yuv420p", f"{44 / 30}")):
            clips.run([clips.ffmpeg(), "-y", "-f", "lavfi", "-i", "color=c=gray:s=1080x1920:r=30:d=1.5",
                       "-t", seconds, "-pix_fmt", fmt, "-c:v", "libx264", str(Path(tmp) / f"{name}.mp4")])
        spin = plate(Path(tmp))
        (Path(tmp) / "ab.txt").write_text("".join(f"file '{p}'\n" for p in (Path(tmp) / "a.mp4", Path(tmp) / "b.mp4", spin)),
                                          encoding="utf-8")
        video = Path(tmp) / "v.mp4"
        clips.run([clips.ffmpeg(), "-y", "-f", "concat", "-safe", "0", "-i", str(Path(tmp) / "ab.txt"),
                   "-f", "lavfi", "-i", "sine=f=440:r=48000", "-map", "0:v", "-map", "1:a", "-shortest",
                   "-c:v", "copy", "-c:a", "aac", str(video)])
        # Куски встык, как внутри строки: конец одного с погрешностью деления равен началу другого.
        burn(video, [("раз", 0.1, 0.3 + 1e-12, False), ("общественной безопасности.", 0.3, 0.9, False),
                     ("четыре", 0.9 - 1e-12, 1.0, False),
                     ("три", 2.0, 2.6, True)], Path(tmp), ending_at=89 / 30)

        def still(at: float, source: Path):
            """Кадр ролика на секунде `at`; отрицательная — последний кадр файла, ищется от конца."""
            frame = Path(tmp) / "still.png"
            # Кадр за концом файла ffmpeg не пишет — прежний снимок не должен пройти за новый.
            frame.unlink(missing_ok=True)
            clips.run([clips.ffmpeg(), "-y", "-sseof" if at < 0 else "-ss", f"{at}", "-i", str(source),
                       *(("-update", "1") if at < 0 else ("-frames:v", "1")), str(frame)])
            return Image.open(frame)

        def white(at: float, band: tuple[float, float], source: Path = video, columns=(0.0, 1.0)) -> bool:
            crop = still(at, source).convert("L").crop(
                (int(1080 * columns[0]), int(1920 * band[0]), int(1080 * columns[1]), int(1920 * band[1])))
            return crop.getextrema()[1] > 240

        # Верхняя полоса — ниже метки: белые буквы адреса в ней не должны считаться субтитром.
        low, top = (0.6, SAFE_BOTTOM), (0.2, 0.32)
        assert white(0.6, low) and not white(0.6, top), "первый кусок внизу"
        assert not white(1.4, low) and not white(1.4, top), "пауза без субтитра"
        assert white(2.3, top) and not white(2.3, low), "второй кусок наверху"

        def blue(at: float, source: Path) -> bool:
            x, y = BADGE_XY
            r, g, b = still(at, source).convert("RGB").crop((x, y, x + 100, y + 80)).resize((1, 1), Image.BOX).getpixel((0, 0))
            return b > r + 40

        def wheel(at: float, source: Path) -> bool:
            gray = still(at, source).convert("L")
            # Светлый аватар в центре плашки, тёмный фон за его кругом.
            return gray.getpixel((540 + 180, PLATE_TOP + PLATE_WHEEL // 2 + 180)) > 140 and gray.getpixel((60, PLATE_TOP)) < 60

        # Метка Telegram по ходу и концовка — аватар, адрес, приманка — только в основном,
        # и всё белое — в безопасной зоне: не ниже её и не правее, под колонкой кнопок.
        middle = (ENDING_Y - 0.03, ENDING_Y + 0.03)
        assert blue(0.7, video) and not blue(0.7, tiktok(video)), "метка только в основном ролике"
        assert wheel(3.6, video) and white(3.6, middle), "аватар и адрес на концовке"
        assert white(3.6, (BAIT_Y - 0.015, BAIT_Y + 0.015)), "приманка на концовке"
        # Кадр за кадром с первого кадра плашки: адрес мигал, горя на одном кадре из шести.
        for frame in range(89, 96):
            assert white(frame / 30 + 0.01, middle), (frame, "адрес мигает на концовке")
        for at in (0.6, 3.6):
            assert not white(at, (SAFE_BOTTOM, 1.0)), (at, "внизу — интерфейс площадки")
            assert not white(at, (0.0, 1.0), columns=(SAFE_RIGHT, 1.0)), (at, "справа — колонка кнопок")
        # TikTok-версия кончается с последней строкой: без плашки, звук гаснет, а не обрывается.
        assert abs(clips.probe_seconds(tiktok(video)) - (clips.probe_seconds(video) - PLATE_SECONDS)) < 0.1
        assert not wheel(-0.3, tiktok(video)) and wheel(3.0, video), "первый кадр плашки в TikTok-версии"
        sound = Path(tmp) / "tiktok.wav"
        clips.run([clips.ffmpeg(), "-y", "-i", str(tiktok(video)), "-ac", "1", "-ar", "8000", "-c:a", "pcm_s16le", str(sound)])
        with wave.open(str(sound)) as take:
            samples = array.array("h", take.readframes(take.getnframes()))

        def loudness(a: float, b: float) -> float:
            piece = samples[int(a * 8000):int(b * 8000)]
            return math.sqrt(sum(x * x for x in piece) / len(piece))

        assert loudness(2.92, 2.98) < loudness(2.0, 2.5) * 0.5, "звук TikTok-версии обрывается"
        # Аватар крутится: кольцо вокруг кнопки в первом и среднем кадре плашки разное.
        frames = []
        for at in ("0", "0.6"):
            clips.run([clips.ffmpeg(), "-y", "-ss", at, "-i", str(spin), "-frames:v", "1", str(Path(tmp) / "p.png")])
            c = PLATE_TOP + PLATE_WHEEL // 2
            frames.append(Image.open(Path(tmp) / "p.png").convert("L").crop((540 - 170, c - 170, 540 + 170, c + 170)))
        from PIL import ImageChops

        assert ImageChops.difference(*frames).getextrema()[1] > 60, "аватар стоит"

    # Бит берётся с места, где вступает низ, а не с тихого начала.
    with tempfile.TemporaryDirectory() as tmp:
        from . import clips

        track = Path(tmp) / "beat.wav"
        clips.run([clips.ffmpeg(), "-y", "-f", "lavfi", "-i", "sine=f=60:d=30",
                   "-af", "volume='if(lt(t,7),0.01,0.8)':eval=frame", str(track)])
        assert abs(beat_start(track) - 7.0) < 0.5, beat_start(track)

        # Отрывок трека: из превью вырезан свой кусок, в бите звучит в своё время, бит под ним тише.
        def tone(at: float, path: Path, window: tuple[float, float], hz: int) -> float:
            mono = Path(tmp) / "mono.wav"
            clips.run([clips.ffmpeg(), "-y", "-i", str(path), "-ac", "1", "-ar", "8000", "-c:a", "pcm_s16le", str(mono)])
            with wave.open(str(mono)) as sound:
                data = array.array("h", sound.readframes(sound.getnframes()))[int(window[0] * 8000):int(window[1] * 8000)]
            angle = 2 * math.pi * hz / 8000
            return math.hypot(sum(x * math.cos(angle * n) for n, x in enumerate(data)),
                              sum(x * math.sin(angle * n) for n, x in enumerate(data))) / len(data)

        preview = Path(tmp) / "preview.m4a"
        clips.run([clips.ffmpeg(), "-y", "-f", "lavfi", "-i", "sine=f=1000:d=30",
                   "-af", "volume='if(between(t,12,14),0.5,0.001)':eval=frame", "-c:a", "aac", str(preview)])
        from .sources import itunes

        real = itunes.song_preview, globals()["_download"]
        itunes.song_preview = lambda track: "https://example.com/preview.m4a"
        globals()["_download"] = lambda url, dest, smallest: dest.write_bytes(preview.read_bytes()) and dest
        try:
            piece = _excerpt({"id": 1, "start": 12, "length": 2}, Path(tmp) / "track-0.m4a")
        finally:
            itunes.song_preview, globals()["_download"] = real
        assert abs(clips.probe_seconds(piece) - 2.0) < 0.1 and tone(0, piece, (0.2, 1.8), 1000) > 1000, "вырезан не тот кусок"
        beat = Path(tmp) / "beat-bed.wav"
        clips.run([clips.ffmpeg(), "-y", "-f", "lavfi", "-i", "sine=f=200:d=6", "-ac", "2", "-ar", "44100", str(beat)])
        mixed = _under_tracks(beat, [(piece, 2.0, 2.0)], Path(tmp))
        assert _under_tracks(beat, [], Path(tmp)) == beat
        # Наложенный звук — на своём месте, а бит под ним не глохнет.
        over_dir = Path(tmp) / "over"
        over_dir.mkdir()
        layered = _under_tracks(beat, [], over_dir, [(piece, 2.0, 2.0, 1.0)])
        assert tone(0, layered, (2.3, 3.7), 1000) > 1000 and tone(0, layered, (0.5, 1.5), 1000) < 100, "наложение не на месте"
        assert tone(0, layered, (2.3, 3.7), 200) > tone(0, layered, (0.5, 1.5), 200) * 0.8, "бит под наложением заглох"
        # beat 0,5: к концу наложения бит вдвое тише, но не молчит, а после — снова целиком.
        halved_dir = Path(tmp) / "halved"
        halved_dir.mkdir()
        halved = _under_tracks(beat, [], halved_dir, [(piece, 2.0, 2.0, 0.5)])
        full, low = tone(0, halved, (0.5, 1.5), 200), tone(0, halved, (3.0, 3.9), 200)
        assert full * 0.35 < low < full * 0.65 and tone(0, halved, (4.5, 5.5), 200) > full * 0.8, (full, low)
        before, during = tone(0, mixed, (0.5, 1.5), 200), tone(0, mixed, (2.3, 3.7), 200)
        assert tone(0, mixed, (2.3, 3.7), 1000) > 1000 and tone(0, mixed, (0.5, 1.5), 1000) < 100, "отрывок не на месте"
        assert during < before * 0.2 and tone(0, mixed, (4.5, 5.5), 200) > before * 0.8, (before, during)

        # Кадр обрезается вокруг focus: у картинки «слева красное, справа
        # синее» кадр с focus 0 красный, с focus 1 синий.
        from PIL import Image

        half = Image.new("RGB", (1600, 900), (255, 0, 0))
        half.paste((0, 0, 255), (800, 0, 1600, 900))
        half.save(Path(tmp) / "half.png")
        empty = Image.new("RGBA", (clips.WIDTH, clips.HEIGHT))
        # Статичная картинка движется: первый и последний кадр отрезка разные, в обе стороны.
        ramp = Image.linear_gradient("L").resize((1080, 1920)).convert("RGB")
        ramp.save(Path(tmp) / "ramp.png")
        for out in (False, True):
            part = Path(tmp) / f"zoom-{out}.mp4"
            clips.segment(clips.Shot(empty, 0.5, "", "", backdrop=str(Path(tmp) / "ramp.png")), part, Path(tmp),
                          fade_in=False, grade="", zoom_out=out, zoom=STILL_ZOOM)
            edges = []
            for at in ("0", "0.45"):
                clips.run([clips.ffmpeg(), "-y", "-ss", at, "-i", str(part), "-frames:v", "1", str(Path(tmp) / "z.png")])
                edges.append(Image.open(Path(tmp) / "z.png").convert("L").getpixel((540, 5)))
            assert abs(edges[0] - edges[1]) > 4 and (edges[0] < edges[1]) == (not out), (out, edges)
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
