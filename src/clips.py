"""Вертикальные клипы для VK Клипов и YouTube Shorts.

Собираются не из очереди постов, а напрямую из data/lineage.json. Причина
в структуре: у связи есть отдельные поля «современное» и «предок», и из них
получается та самая раскадровка «а вы знали, что это отсюда» — единственная
механика канала, которая работает на холодную аудиторию. Разбирать ту же
мысль обратно из готового текста поста было бы гаданием.

Очередь постов при этом не тратится: клипы и лента живут независимо.

Устройство кадра: снизу картинка, сверху короткая надпись. Текста намеренно
мало — в ленте коротких роликов читают два-три слова, остальное пролистывают.
Длинные формулировки из lineage.json режутся до сути (см. `short`), полную
мысль человек получит в канале.

Что попадает в кадр, решается по смыслу, а не наугад. Порядок такой:
фотография названного артиста → сток по приметам связи → нарисованный фон.
Первое сильнее прочего: под словом «SpaceGhostPurrp» должен быть
SpaceGhostPurrp, а не абстрактный ночной город.

Нарисованной ведущей в кадре больше нет: одно и то же синтетическое лицо
из ролика в ролик читается площадками как машинный контент, а зрителем —
как реклама. Осталось то, ради чего она заводилась, — закадровый голос
(см. src/host.py): на экране ярлык в два слова, в наушниках вся мысль.

Форматов три. «ОТКУДА НОГИ» разбирает связь из data/lineage.json.
«А ВЫ ЗНАЛИ» (`--facts`) перечисляет факты про названного артиста
из data/facts.json — там, где разбор требует дослушать до третьего кадра,
факты держат с первой секунды, и на холодной ленте это решает.
Новостной (`--news`) берёт свежую новость прямо из data/inbox.jsonl:
у канала она и так есть, но уходит только текстом, а в ленте роликов
новость понимают с первой секунды — там ей и место. Крючок несёт саму
новость, а не вопрос: у разбора связи есть право на «дослушай до третьего
кадра», у новости его нет.

Обработка — камкордерная: посаженное разрешение, фиолетовый увод, развод
по каналам, зерно, развёртка. Ориентир — клипы Raider Klan и раннего
Goth Money: у этой сцены картинка не монохромная и чистая, а цветная
и затёртая. Без такой обработки разные исходники читаются как нарезка
чужого, а не как канал.

Ручная сборка стоит рядом с автоматической, а не вместо неё: `--from`
берёт готовый item из файла, `--voice` — записанные фразы из папки, и тогда
ни модель, ни синтез в ролике не участвуют. Нужна она там, где цена ошибки
выше выигрыша от автомата: в новости про живых людей одна выдуманная цифра
стоит дороже десяти несобранных роликов.

    python -m src.clips --preview        собрать один клип, никуда не отправляя
    python -m src.clips --facts          формат «А ВЫ ЗНАЛИ»: факты подряд
    python -m src.clips --news           формат «НОВОСТЬ»: свежее из inbox
    python -m src.clips --news --from data/news_clip.json --voice assets/voice/news-guf/
    python -m src.clips --build 3        собрать три
    python -m src.clips --publish        собрать и выложить во ВКонтакте

Нужен ffmpeg. Локально: brew install ffmpeg. В Actions ставится сам.
"""

from __future__ import annotations

import argparse
import random
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from . import compose, config, footage, host, llm, state, stories

OUT_DIR = config.ROOT / "assets" / "clips"
AUDIO_DIR = config.ROOT / "assets" / "audio"

WIDTH, HEIGHT = stories.WIDTH, stories.HEIGHT
FPS = 30

# Раскадровка. Шестнадцать секунд: короткие ролики досматривают до конца,
# а досмотр — главный сигнал для алгоритма.
HOOK_SECONDS = 4.0
TURN_SECONDS = 4.0
LINK_SECONDS = 5.0
FACT_SECONDS = 6.0
CUT_SECONDS = 1.0
OUTRO_SECONDS = 3.0

# Картинка кадра-врезки. Реакция вместо слов: она стоит ровно на короткой
# реплике и работает только пока короткая — растянутая до обычного кадра,
# это уже не врезка, а пауза.
CUT_IMAGE = "assets/meme/ok.png"

# Первые секунды бесплатных битов часто заняты голосовой биркой продюсера
# или долгим вступлением. И то и другое убивает начало ролика, поэтому
# подложку берём не сначала.
AUDIO_SKIP_SECONDS = 8.0

# Месяцы в родительном падеже: дата новости стоит кикером первого кадра,
# а locale в Actions английская — «29 АВГУСТА» оттуда не возьмёшь.
MONTHS = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)

CREAM = stories.CREAM
INK = stories.INK
ACCENT = stories.ACCENT
LIGHT = stories.LIGHT

# Сетка общая с историями и карточками: поле, строка подписи канала
# и черта, от которой заголовок растёт вверх. Держать её в одном месте
# обязательно — иначе блоки начинают наезжать при любой правке кегля.
MARGIN = stories.MARGIN
MARK_Y = stories.MARK_Y
HEAD_BOTTOM = MARK_Y - 96

# Обработка, которая сводит разные исходники к одному виду.
GRADE = (
    # Разрешение сначала роняем, потом поднимаем обратно. Это главное, что
    # отличает камкордер от цифры: мягкость и потеря мелких деталей. Без
    # этого шага любая обработка поверх остаётся «чистым видео с фильтром».
    "scale=540:-2,scale=1080:1920,"
    # Цвет уводим в фиолетовый: поднимаем красный и синий, роняем зелёный.
    # Обесцвечивать нельзя — у этой сцены картинка цветная и передержанная,
    # а не монохромная.
    "eq=saturation=0.78:contrast=1.34:brightness=-0.05,"
    "colorbalance=rs=0.08:gs=-0.05:bs=0.15:rm=0.05:gm=-0.03:bm=0.09,"
    # Развод по каналам — то, чем затёртая копия отличается от оригинала.
    "rgbashift=rh=-5:bh=5,"
    "vignette=PI/3.4,"
    "noise=alls=11:allf=t"
)

# Речь проходит свою обработку — по той же причине, что картинка. Узкая
# полоса, как у телефонной линии, съедает то, чем машинный голос выдаёт
# себя: слишком чистые верха и ровный низ. Заодно голос садится в один ряд
# с затёртым изображением, а не висит поверх него студийной дорожкой.
VOICE_GRADE = "highpass=f=180,lowpass=f=6800,acompressor=threshold=0.08:ratio=4,volume=1.7"

# Громкость под площадку. Ютуб и Клипы приглушают то, что громче их нормы,
# но тихое не поднимают: ролик на -23 LUFS так и играет в ленте тише соседних,
# а тихое в ленте пролистывают, не разобравшись. -14 LUFS — норма ютуба,
# запас по пику -1.5 дБ оставлен под то, что площадка пережмёт звук ещё раз.
MASTER = "loudnorm=I=-14:TP=-1.5:LRA=11"


class ClipError(RuntimeError):
    pass


def ffmpeg() -> str:
    """Путь к ffmpeg или понятная ошибка вместо невнятного падения ниже."""
    found = shutil.which("ffmpeg")
    if not found:
        raise ClipError(
            "ffmpeg не найден. Локально: brew install ffmpeg. "
            "В GitHub Actions он ставится шагом workflow."
        )
    return found


def probe_seconds(path: Path) -> float:
    """Сколько длится файл. 0.0 — если ffprobe не спросить.

    Нужна только для речи: пока фразу не синтезируешь, её длина неизвестна,
    а кадр под неё подгоняется, а не наоборот.
    """
    probe = shutil.which("ffprobe")
    if not probe:
        return 0.0
    result = subprocess.run(
        [probe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def silence_back(path: Path) -> float:
    """Когда в подложке снова начинается музыка после паузы. 0.0 — если её нет.

    Бит, записанный под раскадровку, замолкает на врезке и возвращается
    на финале. Позиция паузы ищется в самом файле, а не задаётся числом:
    подложку перепишут — число разъедется молча, и музыка вернётся не там.
    """
    result = subprocess.run(
        [ffmpeg(), "-i", str(path), "-af", "silencedetect=noise=-38dB:d=0.35", "-f", "null", "-"],
        capture_output=True,
        text=True,
    )
    found = re.findall(r"silence_end: ([\d.]+)", result.stderr)
    return float(found[0]) if found else 0.0


def run(args: list[str]) -> None:
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        # ffmpeg пишет причину в конец stderr, туда и смотрим.
        tail = "\n".join(result.stderr.strip().splitlines()[-6:])
        raise ClipError(f"ffmpeg не справился:\n{tail}")


# --- текст ---------------------------------------------------------------

# Хвостовые служебные слова: после обрезки фразы они повисают в воздухе
# и читаются как обрыв — «Фонк в СНГ как».
TAIL_WORDS = {
    "и", "а", "но", "из", "как", "в", "во", "на", "с", "со", "для", "от",
    "по", "у", "к", "о", "об", "же", "вся", "весь", "всё", "это", "тот",
    "вообще", "целая", "целый", "сам", "сама", "свой", "своя",
}


def short(text: str, limit: int = 4) -> str:
    """Режет формулировку из lineage.json до заголовка в пару слов.

    База писалась под текстовые посты, там фразы развёрнутые. В ролике
    нужен ярлык: «Дрифт-фонк», а не «Дрифт-фонк, который играет в каждом
    втором ролике с машинами». Полную мысль человек прочитает в канале.

    Порядок реза: сначала по знаку препинания, потом по «и» — если фраза
    всё ещё длинная, вторая её половина обычно уточнение.
    """
    text = re.split(r"[,:;(—]", text)[0].strip()

    if len(text.split()) > limit and " и " in text:
        head = text.split(" и ")[0].strip()
        if head:
            text = head

    words = text.split()[:limit]
    while words and words[-1].lower().strip(".") in TAIL_WORDS:
        words.pop()

    return " ".join(words) or text


# --- надписи -------------------------------------------------------------


def scrim(draw: ImageDraw.ImageDraw, top: int) -> None:
    """Затемнение от середины кадра к низу.

    Раньше подложка была полосой вокруг надписи — она читалась как плашка
    и обрезала фотографию поперёк. Сплошной увод в чёрный к низу выглядит
    как свет в кадре, а не как наклейка, и держит худший случай: белую майку
    или засвеченный сток под белым текстом.
    """
    for y in range(top, HEIGHT):
        t = (y - top) / max(1, HEIGHT - top)
        draw.line([(0, y), (WIDTH, y)], fill=(0, 0, 0, int(216 * t ** 1.5)))


def scanlines(draw: ImageDraw.ImageDraw) -> None:
    """Строчная развёртка поверх кадра.

    Рисуется в тот же прозрачный слой, что и надпись: отдельный фильтр
    ffmpeg на каждый отрезок стоил бы прохода кодирования, а результат
    тот же. Шаг в три пикселя на 1920 в высоту читается как развёртка,
    а не как полосатая рябь.
    """
    for y in range(0, HEIGHT, 3):
        draw.line([(0, y), (WIDTH, y)], fill=(0, 0, 0, 26))


def counter(draw: ImageDraw.ImageDraw, at: float) -> None:
    """Счётчик кассеты в углу: сторона и время от начала ролика.

    Мелкая деталь, которая делает больше, чем кажется: у ленты коротких
    роликов все кадры чужие, и опознают канал по постоянным элементам,
    а не по содержанию. Время настоящее — это позиция кадра в ролике.
    """
    label = f"SIDE A · {int(at) // 60:02d}:{int(at) % 60:02d}"
    f = stories.font(34, 500)
    x = MARGIN
    draw.rectangle([x, 152, x + 12, 186], fill=ACCENT)
    stories.tracked(draw, (x + 30, 148), label, f, (206, 200, 190), 3)


def fit(draw: ImageDraw.ImageDraw, text: str, sizes, box: int):
    """Подбирает кегль так, чтобы надпись влезла по ширине."""
    import textwrap

    for size, per_line in sizes:
        font = stories.font(size)
        # Слово не рвём никогда: ни по дефису, ни посередине. «Дрифт-фонк»,
        # разъехавшийся на «Дрифт-фон» и «к», — это вся суть кадра насмарку.
        # Не влезло — цикл возьмёт кегль меньше, для того он и нужен.
        lines = (
            textwrap.wrap(
                text, width=per_line, break_on_hyphens=False, break_long_words=False
            )
            or [text]
        )
        widest = max(draw.textbbox((0, 0), line, font=font)[2] for line in lines)
        if widest <= box:
            return font, lines, size
    return font, lines, size


def overlay(label: str, body: str, *, big: bool = True, at: float = 0.0) -> Image.Image:
    """Прозрачный слой с надписью — ложится поверх кадра со стока.

    Надпись стоит в нижней трети и прижата влево, а не по центру кадра.
    Причина не в красоте: по центру текст ложится ровно на лицо, а именно
    лицо — то, ради чего кадр выбирали. Внизу остаётся полоса под интерфейс
    площадки (`stories.SAFE_BOTTOM`), туда не заходит ничего своего.
    """
    layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    box = WIDTH - MARGIN * 2
    # Кегли крупнее прежних: узкий гротеск на ту же ширину влезает целиком,
    # а в ленте роликов размер надписи — это и есть громкость голоса.
    sizes = (
        ((186, 11), (160, 13), (136, 16), (112, 19), (94, 23), (78, 28))
        if big
        else ((104, 20), (90, 24), (78, 28), (66, 33), (56, 39))
    )
    font, lines, size = fit(draw, body, sizes, box)

    step = int(size * 0.98)  # плотный интерлиньяж: заголовок стоит блоком
    top = HEAD_BOTTOM - len(lines) * step
    kicker_y = top - 74

    # Подложка начинается выше рубрики, а не выше заголовка: рубрика мельче
    # всего в кадре и первой пропадает на светлой фотографии.
    scrim(draw, max(0, kicker_y - int(HEIGHT * 0.18)))
    # Развёртка идёт до надписи: полосы должны лежать на кадре, а не резать
    # буквы. Текст поверх них остаётся чистым и читается с телефона.
    scanlines(draw)
    counter(draw, at)

    if label:
        # Буквы светлые, линейка красная: после камкордерной обработки
        # красный текст такого кегля садится в кадр и не читается.
        stories.kicker(draw, (MARGIN, kicker_y), label, 42, LIGHT)

    y = top
    for line in lines:
        # Тень под каждой строкой: сток непредсказуем, контраст нужен всегда.
        draw.text((MARGIN + 4, y + 5), line, font=font, fill=(0, 0, 0, 170))
        draw.text((MARGIN, y), line, font=font, fill=LIGHT)
        y += step

    stories.mark(draw, (MARGIN, MARK_Y))
    return layer.filter(ImageFilter.GaussianBlur(0.3))


def cut_overlay(at: float = 0.0) -> Image.Image:
    """Слой кадра-врезки: ни кикера, ни надписи.

    Картинка врезки говорит сама, надпись поверх неё только мешает.
    Развёртка и счётчик остаются: без них кадр выпадает из ряда и читается
    как чужая вставка, а не как секунда того же ролика.
    """
    layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    scanlines(draw)
    counter(draw, at)
    return layer


def outro_overlay(at: float = 0.0) -> Image.Image:
    """Финальный кадр: марка канала во всю ширину и адрес.

    Последние секунды решают, подпишется человек или пролистнёт, поэтому
    здесь только название и адрес — без объяснений, которые всё равно
    не дочитывают.
    """
    layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    scrim(draw, int(HEIGHT * 0.30))
    scanlines(draw)
    counter(draw, at)

    name = stories.font(200, 700)
    top = MARK_Y - 330

    stories.kicker(draw, (MARGIN, top - 80), "откуда взялся тёмный звук", 40, LIGHT)
    draw.text((MARGIN + 5, top + 6), "ПЛЁНКА", font=name, fill=(0, 0, 0, 170))
    stories.tracked(draw, (MARGIN, top), "ПЛЁНКА", name, LIGHT, 6)

    stories.tracked(
        draw, (MARGIN, MARK_Y), "@plenka_fm", stories.font(58, 600), ACCENT, 4
    )
    return layer


@dataclass(frozen=True)
class Shot:
    """Кадр раскадровки: надпись, длительность и о чём он.

    `subject` — текст именно этого кадра, по нему ищется артист. `context` —
    вся связь целиком, по ней подбирается сток, когда артиста в кадре нет.
    """

    layer: Image.Image
    seconds: float
    subject: str
    context: str
    # Чем закрыть фон вместо обычного поиска: "terminal" у финального кадра
    # или путь к своей картинке у врезки — от корня репозитория.
    backdrop: str = ""
    # Свой запрос к стоку вместо подбора по приметам. Нужен там, где кадр
    # написан заранее: под «семьдесят тысяч» должна быть толпа стадиона,
    # а не то, что выпало по слову «фонк».
    query: str = ""


def storyboard(link: dict) -> list[Shot]:
    """Раскадровка связи: крючок, поворот, объяснение, финал.

    Каждый шаг — надпись, длительность и запрос к стоку. Порядок неслучаен:
    сначала знакомое, что человек слышал и без канала, потом переворот,
    и только третьим кадром объяснение, когда интерес уже есть.
    """
    modern = link.get("modern", "")
    ancestor = link.get("ancestor", "")
    connection = link.get("connection", "")
    whole = " ".join((modern, ancestor, connection))

    # Кто в кадре важнее, чем что в кадре. Если в тексте назван артист
    # из базы — показываем его, а не абстрактный сток: под словом
    # «SpaceGhostPurrp» должен быть SpaceGhostPurrp, а не ночной город.
    #
    # Ведущая этому правилу не мешает: в крючок она встаёт только тогда,
    # когда артиста в тексте нет и на его месте всё равно оказался бы
    # безымянный сток. Зато объяснение — её кадр по существу: там нечего
    # показывать, кроме человека, который это говорит.
    return [
        Shot(
            overlay("ОТКУДА НОГИ", short(modern), at=0.0),
            HOOK_SECONDS,
            modern,
            whole,
        ),
        Shot(
            overlay("А НАЧАЛОСЬ ЗДЕСЬ", short(ancestor), at=HOOK_SECONDS),
            TURN_SECONDS,
            ancestor,
            whole,
        ),
        Shot(
            overlay(
                "СВЯЗЬ",
                short(connection, 7).capitalize(),
                big=False,
                at=HOOK_SECONDS + TURN_SECONDS,
            ),
            LINK_SECONDS,
            connection,
            whole,
        ),
        # Финал — терминал: там написано, что канал работает сам, и это
        # единственное место, где изображение буквально подтверждает текст.
        Shot(
            outro_overlay(HOOK_SECONDS + TURN_SECONDS + LINK_SECONDS),
            OUTRO_SECONDS,
            "",
            whole,
            backdrop="terminal",
        ),
    ]


def storyboard_facts(item: dict) -> list[Shot]:
    """Раскадровка «А ВЫ ЗНАЛИ»: имя, факты подряд, финал.

    Второй формат рядом с «ОТКУДА НОГИ» и на своей базе — data/facts.json.
    Разбор связи A→B требует, чтобы человек дослушал до третьего кадра;
    перечисление фактов про названного человека держит внимание с первой
    секунды и потому заходит холодной ленте коротких роликов.

    Ключевая разница с разбором связи — в кадре имя, а не жанр. Поэтому
    и запрос к стоку идёт «имя + факт»: под фактом должно стоять лицо
    того, о ком он, а не абстрактный дым. Ради этого имена в базе пишутся
    так же, как в data/artists.json, — латиницей.

    Фактов три-четыре, длина ролика плавает: голос (`host.fact_lines`)
    считает фразы по той же записи.
    """
    artist = item.get("artist", "")
    facts = [f for f in item.get("facts", []) if f]
    whole = " ".join([artist, *facts])

    shots = [
        Shot(overlay("А ВЫ ЗНАЛИ", short(artist, 3), at=0.0), HOOK_SECONDS, artist, whole)
    ]

    at = HOOK_SECONDS
    for index, fact in enumerate(facts):
        shots.append(
            Shot(
                overlay(f"ФАКТ {index + 1}", short(fact, 7).capitalize(), big=False, at=at),
                FACT_SECONDS,
                # Имя впереди факта: артист ищется по всей строке, и без имени
                # кадр про «первый трек на телефон» ушёл бы в случайный сток.
                f"{artist} {fact}",
                whole,
            )
        )
        at += FACT_SECONDS

    shots.append(Shot(outro_overlay(at), OUTRO_SECONDS, artist, whole, backdrop="terminal"))
    return shots


def news_date(item: dict) -> str:
    """Дата новости словами — кикер первого кадра.

    Дата в кадре работает как штамп на плёнке: она сообщает, что ролик
    сегодняшний, до того как зритель разберёт слова. Даты нет — кикер
    остаётся просто «НОВОСТЬ», врать про день нельзя.
    """
    when = state._parse(item.get("released_at") or "")
    return f"{when.day} {MONTHS[when.month - 1]}" if when else "новость"


def storyboard_news(item: dict) -> list[Shot]:
    """Раскадровка новостного ролика: дата, что было, деталь, реплика,
    врезка, финал.

    Крючок несёт саму новость, а не вопрос. У разбора связи есть право
    на «дослушай до третьего кадра» — там мысль без развязки не работает.
    У новости этого права нет: через сутки она никому не нужна, и первые
    четыре секунды должны сказать всё, ради чего ролик снят.

    Строки пишет модель по схеме llm.CLIP_SCHEMA строго из заголовка
    и краткого содержания — ролик читают вслух, и выдуманная цифра стоит
    дороже пропущенной. Последний кадр отдан оценке канала: оценку,
    в отличие от факта, выдумать нельзя.

    Лицо у каждого кадра своё — список `faces` по кадрам. Одно фото на все
    четыре кадра читается как зависшая картинка, а в новости про концерт
    двоих ещё и врёт: половину ролика говорят не про того, кто в кадре.
    Списка нет — во всех кадрах артист новости, как было.

    Имена пишутся ровно как в data/artists.json, иначе footage.find_artist
    их не узнает и под новостью про Ghostemane встанет случайный дым.
    """
    artist = item.get("artist", "")
    # Лицо и запрос к стоку — по кадру. Пустое лицо означает «здесь сток»:
    # одно и то же фото на четыре кадра стоит в ленте как заставка, а ролик
    # держат сменой картинки не меньше, чем словами.
    faces = item.get("faces", [])
    stock = item.get("stock", [])
    lines = [line for line in item.get("lines", []) if line]
    labels = [label for label in item.get("labels", []) if label]
    whole = " ".join((item.get("title", ""), item.get("summary", "")))

    # Кикер, надпись, крупно ли, сколько висит. Двадцать четыре секунды:
    # деталь получает больше всех, потому что она единственное место,
    # где ролик сообщает что-то сверх заголовка.
    plan = (
        (news_date(item), short(labels[0], 3), True, HOOK_SECONDS),
        ("ЧТО БЫЛО", short(labels[1], 4), False, LINK_SECONDS),
        ("ДЕТАЛЬ", short(labels[2], 4), False, FACT_SECONDS),
        # Реплика канала режется из той же фразы, которую читает голос:
        # отдельной надписи под неё в схеме нет — на экране обрывок,
        # в наушниках вся мысль.
        ("И ЧТО", short(lines[2], 5), False, LINK_SECONDS),
    )

    shots, at = [], 0.0
    for index, (kicker, body, big, seconds) in enumerate(plan):
        face = faces[index] if index < len(faces) else artist
        query = stock[index] if index < len(stock) else ""
        shots.append(Shot(overlay(kicker, body, big=big, at=at), seconds, face, whole, query=query))
        at += seconds

    # Врезка после реплики: секунда картинки под «ну ок». Ролик к этому
    # месту состоит из одних говорящих кадров, и пауза на реакцию — то,
    # чем живая лента отличается от сводки новостей.
    shots.append(Shot(cut_overlay(at), CUT_SECONDS, "", whole, backdrop=CUT_IMAGE))
    at += CUT_SECONDS

    # Финал по умолчанию терминальный — там написано, что канал работает сам.
    # Своим запросом («vhs tape») его подменяют поштучно: кассета говорит
    # то же самое картинкой, но годится не всякой новости.
    outro = item.get("outro", "")
    shots.append(
        Shot(
            outro_overlay(at),
            OUTRO_SECONDS,
            "" if outro else artist,
            whole,
            backdrop="" if outro else "terminal",
            query=outro,
        )
    )
    return shots


# --- сборка --------------------------------------------------------------


def segment(shot: Shot, out: Path, work: Path, *, fade_in: bool = True) -> str:
    """Один отрезок: изображение или видео снизу, надпись сверху.

    Приоритет источника: фотография названного артиста → сток по смыслу
    связи → нарисованный фон. Возвращает, что в итоге легло в кадр, —
    это единственный способ узнать со стороны, чем сборка обошлась.

    Фотография статична, поэтому ей нужен наезд: замерший кадр в ленте
    коротких роликов читается как зависшее видео.
    """
    png = work / f"{out.stem}.png"
    shot.layer.save(png, "PNG")

    still = None
    if shot.backdrop == "terminal":
        kind = "терминал"
        source = footage.terminal(work / f"{out.stem}-bg.mp4", shot.seconds, ffmpeg())
    elif shot.backdrop:
        # Своя картинка вместо поиска — врезка. Путь от корня репозитория;
        # абсолютный pathlib подставит как есть.
        kind = "врезка"
        still = source = config.ROOT / shot.backdrop
    elif (still := footage.artist_image(shot.subject) if shot.subject else None) is not None:
        kind = "артист"
        source = still
    else:
        kind = "сток"
        source = footage.fetch(shot.query or footage.query_for(shot.subject, shot.context))
        if source is None:
            kind = "фон"
            source = footage.procedural(work / f"{out.stem}-bg.mp4", shot.seconds, ffmpeg())

    if still is not None:
        feed = ["-loop", "1", "-framerate", str(FPS), "-i", str(source)]
        # Наезд от 1.0 к 1.12 за отрезок: медленно, чтобы не отвлекать
        # от надписи, но достаточно, чтобы кадр не выглядел замершим.
        step = 0.12 / (shot.seconds * FPS)
        motion = (
            f"scale={WIDTH * 2}:-2,"
            f"zoompan=z='min(zoom+{step:.6f},1.12)'"
            f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d=1:s={WIDTH}x{HEIGHT}:fps={FPS},"
        )
    else:
        feed = ["-stream_loop", "-1", "-i", str(source)]
        motion = ""

    # Выход из чёрного — мягкая склейка между кадрами. Первому кадру ролика
    # с превью (src/reels.py) он вредит: обложка, взятая площадкой из первого
    # кадра, вышла бы чёрной.
    fade = "fade=t=in:st=0:d=0.12," if fade_in else ""

    run([
        ffmpeg(), "-y", *feed,
        "-i", str(png),
        "-t", f"{shot.seconds}",
        "-filter_complex",
        (
            f"[0:v]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={WIDTH}:{HEIGHT},setsar=1,fps={FPS},{motion}{GRADE}[bg];"
            f"[bg][1:v]overlay=0:0,{fade}format=yuv420p[v]"
        ),
        "-map", "[v]", "-an",
        "-c:v", "libx264", "-preset", "medium", "-crf", "23",
        "-maxrate", "6M", "-bufsize", "12M",
        "-g", str(FPS * 2), "-keyint_min", str(FPS),
        str(out),
    ])
    png.unlink(missing_ok=True)
    return kind


def voice_piece(source: Path | None, seconds: float, dest: Path) -> Path:
    """Речь одного кадра, добитая тишиной ровно до его длины.

    Выравнивание тишиной, а не сдвигами при сведении: куски одинакового
    формата и точной длины склеиваются встык, и дорожка совпадает с видео
    по построению. Считать смещения руками — лишний способ ошибиться.
    """
    feed = (
        # Небольшая задержка в начале: кадр должен смениться раньше, чем
        # зазвучит фраза, иначе речь наезжает на предыдущую сцену.
        ["-i", str(source)] if source else ["-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono"]
    )
    run([
        ffmpeg(), "-y", *feed,
        "-af", "adelay=200|200,apad" if source else "anull",
        "-t", f"{seconds}",
        "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le",
        str(dest),
    ])
    return dest


def voice_take(folder: Path, index: int) -> Path | None:
    """Готовая запись под кадр: имя — номер кадра в раскадровке, с единицы.

    Живой голос вместо синтеза, когда ролик собирается руками. Файла нет —
    кадр молчит, и синтез сюда не подставляется: один машинный голос
    посреди записанных фраз слышно сразу, и это хуже тишины.
    """
    found = sorted(folder.glob(f"{index + 1}.*"))
    return found[0] if found else None


def narrate(
    shots: list[Shot],
    link: dict,
    work: Path,
    *,
    kind: str = "lineage",
    voices: Path | None = None,
) -> tuple[list[Shot], Path | None]:
    """Озвучивает раскадровку и подгоняет кадры под речь.

    Длительность из раскадровки — нижняя граница, а не точная: фраза,
    обрезанная на полуслове, хуже, чем её отсутствие. Поэтому кадр
    растягивается под то, что в нём говорят, и ролик выходит длиннее
    шестнадцати секунд ровно настолько, насколько длинная связь.

    Синтеза нет — возвращаем раскадровку как была и None вместо дорожки:
    ролик собирается молча, расписание из-за чужого сервиса не встаёт.
    """
    spoken = host.lines(link, kind=kind)
    stretched, pieces, voiced = [], [], False

    for index, (shot, text) in enumerate(zip(shots, spoken)):
        if voices is not None:
            said = voice_take(voices, index)
        else:
            said = host.speak(text, work / f"said-{index}.wav") if text else None
        seconds = shot.seconds
        if said is not None:
            voiced = True
            # Полсекунды сверх речи: фраза не должна упираться в склейку.
            # Врезке хватает четверти: с обычным запасом секундный кадр
            # растягивается вдвое и перестаёт быть врезкой.
            tail = 0.25 if shot.backdrop not in ("", "terminal") else 0.7
            seconds = max(seconds, probe_seconds(said) + tail)
        stretched.append(replace(shot, seconds=seconds))
        pieces.append(voice_piece(said, seconds, work / f"voice-{index}.wav"))

    if not voiced:
        return shots, None

    listing = work / "voice.txt"
    listing.write_text("".join(f"file '{p}'\n" for p in pieces), encoding="utf-8")
    track = work / "voice.wav"
    run([ffmpeg(), "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(track)])
    return stretched, track


def pick_audio(mood: str) -> Path:
    """Подложка из нужной группы. Если группа пуста — берём что есть."""
    tracks = sorted(AUDIO_DIR.glob(f"{mood}-*.mp3")) + sorted(AUDIO_DIR.glob(f"{mood}-*.wav"))
    if not tracks:
        tracks = sorted(p for p in AUDIO_DIR.iterdir() if p.suffix in {".mp3", ".wav"})
    if not tracks:
        raise ClipError(
            f"В {AUDIO_DIR.relative_to(config.ROOT)} нет подложек. "
            "Как их собрать — в assets/audio/README.md."
        )
    return random.choice(tracks)


def assemble(
    parts: list[Path],
    audio: Path,
    total: float,
    out: Path,
    work: Path,
    voice: Path | None = None,
    start: float = AUDIO_SKIP_SECONDS,
    louder_at: float = 0.0,
) -> None:
    """Склейка отрезков и звук.

    Видео копируется потоком: обработка и надписи уже вжжены в отрезки,
    пережимать второй раз — терять качество на ровном месте.

    Под речью подложка приглушается вчетверо и навсегда, а не по громкости
    голоса: автоматическое приглушение слышно как насос, и на шестнадцати
    секундах оно заметнее, чем польза от него. Разница мерялась, а не бралась
    на слух: между речью и подложкой нужно около 6 дБ, иначе в наушниках
    в метро слов не разобрать.
    """
    listing = work / "parts.txt"
    listing.write_text("".join(f"file '{p}'\n" for p in parts), encoding="utf-8")

    fade_start = max(total - 1.2, 0.1)
    # Подложка идёт кольцом: своя короче ролика, а библиотечная длиннее —
    # лишние круги отрежет -t. Сдвиг делается фильтром, а не -ss: при -ss
    # каждый следующий круг начался бы с того же места, а не сначала.
    length = probe_seconds(audio)
    loops = int((start + total) // length) + 1 if length else 1
    # На финале подложка выходит вперёд: слов там меньше, а последние секунды
    # решают, подпишется человек или пролистнёт. Ступенькой, а не наплывом —
    # музыка после паузы входит уже громче, и перехода не слышно.
    quiet = 0.24 if voice else 0.85
    level = (
        f"volume='if(gte(t,{louder_at:.2f}),{quiet * 1.35:.2f},{quiet:.2f})':eval=frame"
        if louder_at
        else f"volume={quiet}"
    )
    bed = (
        f"atrim=start={start:.3f},asetpts=N/SR/TB,"
        f"afade=t=in:st=0:d=0.4,afade=t=out:st={fade_start}:d=1.2,{level}"
    )

    if voice is None:
        sound = ["-af", f"{bed},{MASTER}"]
    else:
        sound = [
            "-i", str(voice),
            "-filter_complex",
            f"[1:a]{bed}[bed];[2:a]{VOICE_GRADE}[vox];"
            # Лимитер на выходе: сумма двух дорожек упирается в потолок,
            # а перегруз на телефонном динамике слышен как треск.
            f"[bed][vox]amix=inputs=2:duration=first:normalize=0,"
            f"alimiter=limit=0.92,{MASTER}[a]",
            "-map", "0:v", "-map", "[a]",
        ]

    run([
        ffmpeg(), "-y",
        "-f", "concat", "-safe", "0", "-i", str(listing),
        "-stream_loop", str(loops), "-i", str(audio),
        *sound,
        "-t", f"{total}",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "160k",
        "-movflags", "+faststart",
        "-shortest",
        str(out),
    ])


# --- выбор материала -----------------------------------------------------

# Настроение подложки под смысл ролика. У связей про хоррор-кор и мемфис
# звук должен быть тяжелее, чем у разбора эмо-рэпа.
MOOD_HINTS = (
    ("aggressive", ("хоррор", "метал", "крик", "агресс", "жёст", "трэп-метал")),
    ("nostalgic", ("девяност", "кассет", "плёнк", "винил", "старо", "нулев")),
)


def mood_for(link: dict) -> str:
    haystack = " ".join(
        str(link.get(field, "")) for field in ("modern", "ancestor", "connection")
    ).lower()
    for mood, words in MOOD_HINTS:
        if any(word in haystack for word in words):
            return mood
    return "dark"


def used_keys() -> set[str]:
    history = state.read_json(config.CLIPS_FILE, {"items": []})
    return {item.get("key", "") for item in history.get("items", [])}


def clip_key(link: dict, kind: str) -> str:
    """Отпечаток записи с учётом формата.

    Формат в ключе намеренно: базы у форматов разные, но история одна,
    и без пометки ключи трёх баз могли бы совпасть. У новости отпечаток
    уже посчитан сборщиком — берём его, а не заголовок: одну и ту же
    новость ленты пишут разными словами.
    """
    if kind == "facts":
        return state.fingerprint(link.get("artist", ""), "facts")
    if kind == "news":
        return state.fingerprint(link.get("fingerprint", ""), "news")
    return state.fingerprint(link.get("modern", ""), link.get("ancestor", ""))


def remember(link: dict, filename: str, video_id: str = "", kind: str = "lineage") -> None:
    history = state.read_json(config.CLIPS_FILE, {"items": []})
    history.setdefault("items", []).append(
        {
            "key": clip_key(link, kind),
            "modern": link.get("modern", "") or link.get("artist", "") or link.get("title", ""),
            "file": filename,
            "video_id": video_id,
            "built_at": state.iso(),
        }
    )
    history["items"] = history["items"][-500:]
    state.write_json(config.CLIPS_FILE, history)


def pending_links(limit: int) -> list[dict]:
    """Связи, из которых клипов ещё не делали.

    База небольшая и пополняется руками, поэтому когда она кончится — это
    не ошибка, а сигнал, что пора дописать связей.
    """
    data = state.read_json(config.LINEAGE_FILE, {})
    seen = used_keys()
    fresh = [
        link
        for link in data.get("links", [])
        if link.get("modern")
        and link.get("ancestor")
        and clip_key(link, "lineage") not in seen
    ]
    return fresh[:limit]


def pending_facts(limit: int) -> list[dict]:
    """Записи из data/facts.json, из которых роликов ещё не делали."""
    data = state.read_json(config.FACTS_FILE, {})
    seen = used_keys()
    fresh = [
        item
        for item in data.get("items", [])
        if item.get("artist")
        and item.get("facts")
        and clip_key(item, "facts") not in seen
    ]
    return fresh[:limit]


def pending_news(limit: int) -> list[dict]:
    """Свежие новости, из которых роликов ещё не делали, — уже с текстом.

    Inbox читается напрямую, а не через compose.load_inbox_unused: срочные
    новости (src/urgent.py) помечают материал использованным в тот же день,
    и клипу не досталось бы ничего. Историю форматы делят одну — clips.json,
    поэтому один и тот же инфоповод в ролик дважды не попадёт.

    Модель зовётся прямо здесь, а не при сборке: пустую новость — мерч,
    промо, чужая сцена — она отбрасывает сама, и перебирать кандидатов
    до первого годного больше негде.
    """
    cutoff = state.now() - timedelta(hours=config.URGENT_MAX_AGE_HOURS)
    seen = used_keys()

    fresh = []
    for item in state.read_jsonl(config.INBOX_FILE):
        published = state._parse(item.get("released_at") or "")
        if item.get("kind") != "news" or published is None or published < cutoff:
            continue
        if clip_key(item, "news") not in seen:
            fresh.append(item)
    fresh.sort(key=lambda i: i.get("score", 0), reverse=True)

    ready = []
    for item in fresh:
        if len(ready) >= limit:
            break
        # Список имён из базы уходит модели целиком: источник пишет
        # «Три 6 Мафия», а фотография ищется по «Three 6 Mafia», и перевод
        # в написание базы — её работа.
        told = llm.generate_clip(
            {**compose._news_payload(item), "known": footage.known_names()}
        )
        # Трёх строк нет — считаем отказом: раскадровка на пять кадров
        # из двух фраз не собирается, а достраивать её самим означало бы
        # дописать за модель то, чего в новости нет.
        if told.get("skip") or len(told.get("lines", [])) < 3 or len(told.get("labels", [])) < 3:
            print(f"  — мимо ({told.get('reason', 'мало строк')}): {item.get('title', '')[:50]}")
            continue
        ready.append({**item, **told})

    return ready


def build(
    link: dict,
    *,
    kind: str = "lineage",
    voices: Path | None = None,
    music: Path | None = None,
) -> Path:
    """Собирает один клип и возвращает путь к готовому файлу."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    frames = {"facts": storyboard_facts, "news": storyboard_news}.get(kind, storyboard)(link)

    stamp = state.now().strftime("%Y%m%d-%H%M%S")
    name = f"{stamp}-{state.fingerprint(link.get('modern', '') or link.get('artist', ''))[:8]}"
    out = OUT_DIR / f"{name}.mp4"

    # Скачанный сток и промежуточные отрезки живут только на время сборки:
    # десятки мегабайт, которые незачем держать ни в репозитории, ни рядом.
    # Сток качается разом на весь клип: последовательно четыре кадра
    # ждали бы отдачу по очереди.
    with tempfile.TemporaryDirectory(prefix="plenka-clip-") as tmp:
        work = Path(tmp)

        # Речь синтезируется до кадров: от её длины зависит, сколько каждый
        # кадр висит на экране, а значит и вся раскадровка.
        frames, voice = narrate(frames, link, work, kind=kind, voices=voices)
        total = sum(shot.seconds for shot in frames)

        parts, kinds = [], []
        for index, shot in enumerate(frames):
            part = work / f"{name}-{index}.mp4"
            kinds.append(segment(shot, part, work))
            parts.append(part)
        print('  кадры:', ', '.join(kinds))
        print(f"  голос: {'есть' if voice else 'нет'}, длина {total:.1f} с")

        # Своя подложка встаёт по паузе, а не с начала: бит под этот ролик
        # написан так, что музыка молчит на врезке и возвращается на финале.
        # Библиотечной подложке сдвигать нечего — у неё режется только
        # вступление с биркой продюсера.
        bed, start = music or pick_audio(mood_for(link)), AUDIO_SKIP_SECONDS
        outro_at = total - frames[-1].seconds
        if music:
            back, length = silence_back(music), probe_seconds(music)
            start = (back - outro_at) % length if back and length else 0.0
            print(f"  подложка: {bed.name}, музыка возвращается на {outro_at:.1f} с")
        assemble(parts, bed, total, out, work, voice, start, outro_at)

    return out


def deliver(path: Path, link: dict, kind: str = "lineage") -> dict:
    """Отправляет готовый ролик в Telegram.

    Прямой заливки во ВКонтакте здесь нет намеренно: `video.save` отвечает
    групповому ключу «User authorization failed» при любом наборе прав
    и параметров — метод требует пользовательский токен. То же семейство
    ограничений, что у `wall.get` и `photos.getAll` (см. src/vk.py).

    Ролик приходит в Telegram, оттуда перекладывается в Клипы руками —
    минута на штуку. У ручной публикации есть и выигрыш: из приложения
    к ролику цепляется музыка из каталога ВКонтакте, а через API она
    не цепляется никак.
    """
    from . import telegram

    # Адресат — владелец в личку, не канал: ролик ему нужно переложить
    # руками, а в ленте канала вертикальное видео только мешает постам.
    if kind == "news":
        # Дата и срок прямо в подписи: у новостного ролика нет запаса,
        # завтра его выкладывать уже незачем — а разбор связи полежит.
        caption = (
            f"<b>{short(link.get('artist', '') or link.get('title', ''), 6)}</b>"
            f" · новость от {news_date(link)}"
            "\n\nВыложить в Клипы ВКонтакте и в Shorts <b>сегодня</b>: "
            "завтра новость уже мёртвая."
        )
    else:
        caption = (
            f"<b>{short(link.get('modern', '') or link.get('artist', ''), 6)}</b>"
            + (f" → {short(link['ancestor'], 6)}" if link.get("ancestor") else "")
            + "\n\nПереложить в Клипы ВКонтакте и в Shorts."
        )
    return telegram.send_video_file(config.secret("TELEGRAM_ADMIN_ID"), path, caption)


def _selftest() -> None:
    """Кадров в раскадровке ровно столько же, сколько фраз у голоса.

    Единственное место, где два файла обязаны сойтись числом: кадр без фразы
    висит молча, фраза без кадра пропадает совсем. Проверяется на всей базе —
    у связей разное число фактов, и расходятся они именно на краях.
    """
    for link in state.read_json(config.LINEAGE_FILE, {}).get("links", []):
        shots, spoken = storyboard(link), host.lines(link)
        assert len(shots) == len(spoken), (link.get("modern"), len(shots), len(spoken))

    for item in state.read_json(config.FACTS_FILE, {}).get("items", []):
        shots, spoken = storyboard_facts(item), host.lines(item, kind="facts")
        assert len(shots) == len(spoken), (item.get("artist"), len(shots), len(spoken))
        # Имя должно находиться в базе артистов, иначе под фактом встанет
        # случайный сток вместо лица — ради этого имена и пишутся латиницей.
        assert footage.find_artist(item["artist"]), f"нет в artists.json: {item['artist']}"

    # Новостной формат проверяется на выдуманной записи: строки для него
    # пишет модель, и звать её ради счёта кадров незачем.
    told = {
        "title": "Проверка", "summary": "Проверка", "released_at": state.iso(),
        "artist": "Bones",
        "lines": ["Что случилось", "Ещё подробность", "И что с того"],
        "labels": ["Первое", "Второе", "Третье"],
    }
    shots, spoken = storyboard_news(told), host.lines(told, kind="news")
    assert len(shots) == len(spoken), (len(shots), len(spoken))
    # Врезка зашита в раскадровку, и без файла кадр упадёт уже в ffmpeg.
    assert (config.ROOT / CUT_IMAGE).exists(), CUT_IMAGE


def main() -> int:
    parser = argparse.ArgumentParser(description="Клипы для VK и Shorts")
    parser.add_argument("--build", type=int, default=1, help="сколько клипов собрать")
    parser.add_argument("--preview", action="store_true", help="собрать, никуда не отправляя")
    parser.add_argument("--publish", action="store_true", help="собрать и выложить во ВКонтакте")
    parser.add_argument("--facts", action="store_true", help="формат «А ВЫ ЗНАЛИ» вместо разбора связи")
    parser.add_argument("--news", action="store_true", help="новостной формат из свежего inbox")
    parser.add_argument("--from", dest="source", metavar="ФАЙЛ", help="готовый item из JSON вместо inbox и модели")
    parser.add_argument("--voice", metavar="ПАПКА", help="готовые записи 1..N вместо синтеза")
    parser.add_argument("--music", metavar="ФАЙЛ", help="своя подложка вместо assets/audio")
    parser.add_argument("--selftest", action="store_true", help="проверка раскадровок без сборки")
    args = parser.parse_args()

    config.load_dotenv()

    if args.selftest:
        _selftest()
        print("Раскадровки и фразы сходятся.")
        return 0

    kind = "news" if args.news else "facts" if args.facts else "lineage"
    if args.source:
        # Ручная сборка: текст уже написан и сверен, модель не зовём.
        source = Path(args.source)
        if not source.exists():
            print(f"Нет файла {source}.")
            return 1
        links = [state.read_json(source, {})]
    else:
        links = {"news": pending_news, "facts": pending_facts}.get(kind, pending_links)(args.build)
    if not links:
        if kind == "news":
            print("Свежих новостей нет: inbox пуст, ролики уже сделаны или новости пустые.")
        else:
            base = "facts.json" if kind == "facts" else "lineage.json"
            print(f"Всё из {base} уже разошлось по клипам — пора пополнить базу.")
        return 0

    for link in links:
        try:
            path = build(
                link,
                kind=kind,
                voices=Path(args.voice) if args.voice else None,
                music=Path(args.music) if args.music else None,
            )
        except ClipError as exc:
            print(f"Не собрался клип «{(link.get('modern') or link.get('artist', ''))[:40]}»: {exc}")
            return 1

        size = path.stat().st_size / 1024 / 1024
        print(f"Готов: {path.relative_to(config.ROOT)} ({size:.1f} МБ)")

        video_id = ""
        if args.publish:
            try:
                video_id = str(deliver(path, link, kind).get("message_id", ""))
                print(f"Отправлен в Telegram: {video_id}")
            except Exception as exc:
                print(f"Не удалось отправить: {exc}")

        # Превью связь не расходует: посмотрел, не понравилось — собери заново.
        # База пополняется руками, разбрасываться её строками нельзя.
        if not args.preview:
            remember(link, path.name, video_id, kind)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
