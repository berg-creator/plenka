"""Видеоряд для клипов: бесплатные стоки с чистой лицензией.

Почему не фрагменты музыкальных клипов. И ВКонтакте, и YouTube сверяют
видеоряд с базой правообладателей автоматически, а канал, который собирается
продавать рекламу, не может жить на страйках. Поэтому кадры берутся только
там, где лицензия разрешает коммерческое использование: Pixabay и Pexels.

Оба стока отдают видео по API, значит подбор идёт машиной, а не руками.
Ключ нужен один, любой из двух — что окажется в окружении, тем и работаем.
Нет ключа или нет сети — рисуем фон сами, канал не должен вставать
из-за чужого сервиса.

Скачанное не хранится в репозитории: ролики весят десятки мегабайт
и пересобираются в любой момент.

    python -m src.footage --check          проверить ключ и выдачу
    python -m src.footage --grab "smoke"   скачать один ролик на пробу
"""

from __future__ import annotations

import argparse
import atexit
import random
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from . import config

PIXABAY = "https://pixabay.com/api/videos/"
PEXELS = "https://api.pexels.com/videos/search"

WIDTH, HEIGHT = 1080, 1920

# Запросы к стокам, разложенные по смыслу связи. Слова подобраны так, чтобы
# выдача была тёмной и фактурной: чистое небо и улыбающиеся люди каналу
# не подходят, а дым, ночная дорога и плёночный шум — ровно то, что нужно.
QUERY_POOLS: dict[str, tuple[str, ...]] = {
    "tape": ("vhs tape", "old tv static", "cassette tape", "analog glitch", "film projector"),
    "night": ("night city driving", "neon street night", "car headlights night", "rain window night"),
    "heavy": ("concert crowd silhouette", "strobe light dark", "smoke stage light", "mosh pit"),
    "occult": ("fog forest dark", "smoke black background", "candle darkness", "abandoned building"),
    "hazy": ("clouds timelapse dark", "rain glass", "blurred lights bokeh", "underwater dark"),
    "default": ("dark smoke abstract", "film grain texture", "black ink water", "dust particles light"),
}

# По каким словам в связи выбирается пул. Порядок важен: первое совпадение
# выигрывает, поэтому частные приметы стоят выше общих.
POOL_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("tape", ("кассет", "тейп", "плёнк", "девяност", "лоу-фай", "аналог")),
    ("heavy", ("метал", "хардкор", "крик", "гитар", "панк", "трэш")),
    ("occult", ("витч", "хоррор", "блэк", "ужас", "индастриал", "дарквейв", "готик")),
    ("hazy", ("клауд", "размыт", "дрейн", "шугейз", "эмбиент", "туман")),
    ("night", ("фонк", "машин", "дрифт", "город", "улиц", "трэп")),
)


def pool_for(text: str, context: str = "") -> str:
    """Пул запросов по приметам в тексте.

    Сначала смотрим на сам кадр — у «мемфисских тейпов» должна быть плёнка,
    даже если связь в целом про фонк. Не нашли примет — берём приметы всей
    связи: они разбросаны по полям, и одного поля обычно не хватает.
    """
    for source in (text, context):
        if not source:
            continue
        lowered = source.lower()
        for pool, words in POOL_HINTS:
            if any(word in lowered for word in words):
                return pool
    return "default"


def query_for(text: str, context: str = "") -> str:
    return random.choice(QUERY_POOLS[pool_for(text, context)])


# --- поиск ---------------------------------------------------------------


def _pixabay(query: str, key: str) -> list[str]:
    response = requests.get(
        PIXABAY,
        params={
            "key": key,
            "q": query,
            "video_type": "film",
            "orientation": "vertical",
            "per_page": 20,
            "safesearch": "true",
        },
        timeout=30,
    )
    if response.status_code != 200:
        return []

    urls = []
    for hit in response.json().get("hits", []):
        streams = hit.get("videos", {})
        # medium раньше large намеренно. Кадр всё равно ужимается до 1080
        # в ширину, а large тянет десятки мегабайт: на четыре отрезка это
        # минуты ожидания вместо секунд.
        for size in ("medium", "small", "large"):
            url = streams.get(size, {}).get("url")
            if url:
                urls.append(url)
                break
    return urls


def _pexels(query: str, key: str) -> list[str]:
    response = requests.get(
        PEXELS,
        headers={"Authorization": key},
        params={"query": query, "orientation": "portrait", "per_page": 20, "size": "medium"},
        timeout=30,
    )
    if response.status_code != 200:
        return []

    urls = []
    for video in response.json().get("videos", []):
        files = sorted(
            (f for f in video.get("video_files", []) if f.get("width")),
            key=lambda f: abs(f.get("width", 0) - WIDTH),
        )
        if files:
            urls.append(files[0]["link"])
    return urls


def search(query: str) -> list[str]:
    """Адреса подходящих роликов. Пустой список — не беда, будет запасной фон."""
    pixabay_key = config.secret("PIXABAY_API_KEY", required=False)
    if pixabay_key:
        try:
            found = _pixabay(query, pixabay_key)
            if found:
                return found
        except requests.RequestException:
            pass

    pexels_key = config.secret("PEXELS_API_KEY", required=False)
    if pexels_key:
        try:
            return _pexels(query, pexels_key)
        except requests.RequestException:
            pass

    return []


# Что уже скачано за этот запуск. Запросы берутся из небольших пулов,
# поэтому в пачке клипов они повторяются — качать один файл по второму разу
# незачем.
_FETCHED: dict[str, Path] = {}
_RUN_DIR: Path | None = None


def _run_dir() -> Path:
    """Общая папка скачанного на весь запуск.

    Отдельно от временной папки клипа: та живёт один ролик, а сток нужен
    всей пачке. Удаляется на выходе из процесса — в репозитории и рядом
    с ним не остаётся ничего.
    """
    global _RUN_DIR
    if _RUN_DIR is None:
        _RUN_DIR = Path(tempfile.mkdtemp(prefix="plenka-stock-"))
        atexit.register(shutil.rmtree, _RUN_DIR, True)
    return _RUN_DIR


def prefetch(queries: list[str]) -> None:
    """Качает весь сток для клипа разом, а не по кадру.

    Отдача стока небыстрая — секунды на файл, и последовательно четыре кадра
    складываются в минуты. Запросы независимы, поэтому идут параллельно;
    дальше `fetch` разбирает готовое из кэша.
    """
    unique = [q for q in dict.fromkeys(queries) if q not in _FETCHED]
    if len(unique) < 2:
        return

    with ThreadPoolExecutor(max_workers=len(unique)) as pool:
        list(pool.map(fetch, unique))


def fetch(query: str, dest_dir: Path | None = None) -> Path | None:
    """Скачивает один подходящий ролик. None — если стока нет или он молчит."""
    cached = _FETCHED.get(query)
    if cached is not None and cached.exists():
        return cached

    dest_dir = dest_dir or _run_dir()
    urls = search(query)
    if not urls:
        return None

    # Берём из первых двух, а не тасуем всю выдачу: сток отдаёт её по
    # релевантности, и дальше второго места начинается «формально тоже
    # толпа» — под «семьдесят тысяч на стадионе» встаёт улица Сеула.
    # Разнообразие держат сами запросы: их в каждом пуле по пять.
    top = urls[:2]
    random.shuffle(top)
    for url in top:
        try:
            response = requests.get(url, timeout=120, stream=True)
            if response.status_code != 200:
                continue
            path = dest_dir / f"stock-{abs(hash(url)) % 10**8}.mp4"
            with path.open("wb") as handle:
                for chunk in response.iter_content(1 << 16):
                    handle.write(chunk)
            if path.stat().st_size > 100_000:
                _FETCHED[query] = path
                return path
            path.unlink(missing_ok=True)
        except requests.RequestException:
            continue

    return None


# --- изображения артистов ------------------------------------------------

# Имена берём только из курируемого data/artists.json. Вытаскивать их из
# текста догадкой нельзя: ошибёшься — и под разбором мемфиса окажется чужое
# лицо, а это хуже пустого кадра.


def known_names() -> list[str]:
    """Имена из базы, длинные первыми.

    Порядок важен: «Lil Peep» должен выиграть у «Lil B», иначе короткое имя
    заберёт совпадение себе.
    """
    from . import state

    names = [
        a.get("name", "")
        for a in state.read_json(config.ARTISTS_FILE, {}).get("artists", [])
        if a.get("name")
    ]
    return sorted(names, key=len, reverse=True)


def find_artist(text: str) -> str:
    """Первый артист из базы, упомянутый в тексте.

    Сверка идёт по границам слова: без них «Nas» находится внутри «Dynasty»,
    и разбор русского клауд-рэпа иллюстрируется фотографией из Квинса.
    """
    for name in known_names():
        if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text, re.IGNORECASE):
            return name
    return ""


def _blank(data: bytes) -> bool:
    """Картинка одного цвета или не картинка вовсе.

    Разброс яркости у настоящей фотографии — десятки, у заливки — ноль.
    Порог 8 оставляет запас на шум сжатия JPEG поверх заливки.
    """
    from io import BytesIO

    from PIL import Image, ImageStat

    try:
        return ImageStat.Stat(Image.open(BytesIO(data)).convert("L")).stddev[0] < 8
    except OSError:
        return True


def artist_image(text: str) -> Path | None:
    """Фотография артиста, упомянутого в тексте. None — если не нашли.

    Сначала портрет, потом обложка альбома: лицо в кадре работает лучше
    любого стока, обложка — второй по узнаваемости вариант.
    """
    name = find_artist(text)
    if not name:
        return None

    cached = _FETCHED.get(f"artist:{name}")
    if cached is not None and cached.exists():
        return cached

    from .sources import deezer

    for getter in (deezer.artist_picture, deezer.artist_cover):
        try:
            url = getter(name)
        except Exception:
            continue
        if not url:
            continue
        try:
            response = requests.get(url, timeout=60)
        except requests.RequestException:
            continue
        if response.status_code != 200 or len(response.content) < 10_000:
            continue
        # Однотонная картинка — не фотография. У Ye на Deezer вместо портрета
        # чёрный квадрат, и чёрная же обложка «Donda»: кадр «лица» выходил
        # пустым, а первым кадром ролика — пустым и превью.
        if _blank(response.content):
            continue

        path = _run_dir() / f"artist-{abs(hash(name)) % 10**8}.jpg"
        path.write_bytes(response.content)
        _FETCHED[f"artist:{name}"] = path
        return path

    return None


# --- терминал ------------------------------------------------------------

MONO_CANDIDATES = (
    "/System/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/Courier.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
)

# Настоящий вывод настоящих команд проекта — см. README. Врать тут нечего:
# канал действительно собирает новинки, пишет посты и публикует сам.
TERMINAL_LINES: tuple[tuple[str, str], ...] = (
    ("cmd", "python -m src.collect"),
    ("out", "iTunes . . . . . . . 14 находок"),
    ("out", "Deezer . . . . . . .  6"),
    ("out", "RSS, 14 лент . . . . 23"),
    ("out", "отобрано . . . . . .  9"),
    ("cmd", "python -m src.compose"),
    ("out", "ОТКУДА НОГИ  . . . . готово"),
    ("out", "ВЕРДИКТ  . . . . . . готово"),
    ("out", "МЕЖДУ СТРОК  . . . . готово"),
    ("cmd", "python -m src.publish"),
    ("out", "@plenka_fm . . . . . опубликовано"),
)


def mono_font(size: int):
    from PIL import ImageFont

    for path in MONO_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default(size)


def terminal(dest: Path, seconds: float, ffmpeg_bin: str) -> Path:
    """Терминал, в котором построчно проступает работа канала.

    Фон финального кадра. Сток под словами «канал работает сам» — картинка
    ни о чём, а здесь изображение наконец совпадает с текстом: это буквально
    то, что делает проект, и снято оно ни у кого не занято.

    Кадры рисуются с частотой 10 в секунду и растягиваются до 30 при сборке:
    построчное появление на глаз читается одинаково, а работы втрое меньше.
    """
    from PIL import Image, ImageDraw

    work = dest.parent / f"{dest.stem}-frames"
    work.mkdir(parents=True, exist_ok=True)

    source_fps = 10
    total = max(int(seconds * source_fps), 1)
    # Мельче и выше, чем хочется: под терминалом идёт блок с названием
    # канала, и вывод должен уместиться целиком над ним. Наполовину
    # закрытая строка читается как брак вёрстки, а не как слой.
    font = mono_font(30)
    line_step = 44
    top = int(HEIGHT * 0.085)
    left = int(WIDTH * 0.09)

    for index in range(total):
        # Последняя четверть — пауза на собранном экране, чтобы кадр
        # не обрывался в момент печати.
        progress = min(index / max(total * 0.75, 1), 1.0)
        shown = max(int(progress * len(TERMINAL_LINES)), 1)

        img = Image.new("RGB", (WIDTH, HEIGHT), (14, 13, 12))
        draw = ImageDraw.Draw(img)

        y = top
        for kind, text in TERMINAL_LINES[:shown]:
            if kind == "cmd":
                draw.text((left, y), "$", font=font, fill=(196, 58, 44))
                draw.text((left + 34, y), text, font=font, fill=(228, 222, 210))
            else:
                draw.text((left + 34, y), text, font=font, fill=(138, 132, 122))
            y += line_step

        # Курсор мигает раз в полсекунды — пять кадров на этой частоте.
        if index // 5 % 2 == 0:
            draw.rectangle([left + 34, y + 6, left + 34 + 20, y + 40], fill=(196, 58, 44))

        img.save(work / f"f{index:04d}.png", "PNG")

    subprocess.run(
        [
            ffmpeg_bin, "-y",
            "-framerate", str(source_fps),
            "-i", str(work / "f%04d.png"),
            "-vf", f"fps=30,format=yuv420p",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
            str(dest),
        ],
        capture_output=True,
        check=True,
    )
    shutil.rmtree(work, ignore_errors=True)
    return dest


# --- запасной фон --------------------------------------------------------


def procedural(dest: Path, seconds: float, ffmpeg_bin: str) -> Path:
    """Тёмный дышащий фон, нарисованный ffmpeg.

    Нужен, когда стока нет: без ключа, без сети или когда выдача пустая.
    Это не замена съёмке, а страховка — клип выйдет хоть и скромнее,
    но выйдет, и расписание не встанет.
    """
    subprocess.run(
        [
            ffmpeg_bin, "-y",
            "-f", "lavfi",
            # Основа заметно светлее итога: поверх ляжет обработка клипа,
            # а она давит яркость. Возьмёшь сразу тёмный цвет — получишь
            # чёрный прямоугольник вместо фактуры.
            "-i", f"color=c=0x2e2924:s={WIDTH}x{HEIGHT}:d={seconds}:r=30",
            "-vf",
            (
                "noise=alls=34:allf=t+u,"
                "boxblur=2:1,"
                "vignette=PI/3.5,"
                "format=yuv420p"
            ),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
            str(dest),
        ],
        capture_output=True,
        check=True,
    )
    return dest


def main() -> int:
    parser = argparse.ArgumentParser(description="Видеоряд для клипов")
    parser.add_argument("--check", action="store_true", help="проверить ключ и выдачу")
    parser.add_argument("--grab", metavar="ЗАПРОС", help="скачать один ролик на пробу")
    args = parser.parse_args()

    config.load_dotenv()

    if args.check:
        pixabay = bool(config.secret("PIXABAY_API_KEY", required=False))
        pexels = bool(config.secret("PEXELS_API_KEY", required=False))
        print(f"Ключ Pixabay: {'есть' if pixabay else 'нет'}")
        print(f"Ключ Pexels:  {'есть' if pexels else 'нет'}")
        if not (pixabay or pexels):
            print("\nБез ключа клипы соберутся на нарисованном фоне.")
            print("Ключ Pixabay: pixabay.com → профиль → Настройки → API.")
            return 0

        for pool, queries in QUERY_POOLS.items():
            found = search(queries[0])
            print(f"  {pool:<8} «{queries[0]}» → {len(found)} роликов")
        return 0

    if args.grab:
        with tempfile.TemporaryDirectory() as tmp:
            path = fetch(args.grab, Path(tmp))
            if not path:
                print("Ничего не нашлось.")
                return 1
            keep = config.ROOT / "assets" / "clips" / path.name
            keep.parent.mkdir(parents=True, exist_ok=True)
            keep.write_bytes(path.read_bytes())
            print(f"Скачано: {keep.relative_to(config.ROOT)} "
                  f"({keep.stat().st_size / 1024 / 1024:.1f} МБ)")
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
