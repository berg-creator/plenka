"""Карточка разбора вкуса — то, что человек пересылает друзьям.

Ради этой картинки всё и затевалось: текстовый ответ бота остаётся в личке,
а карточка уходит в чужие сторис вместе с подписью канала. Материал и цвета
те же, что у аватарки и историй ВКонтакте, — сервис должен выглядеть частью
канала, а не отдельной поделкой.

    python -m src.card --preview    нарисовать пробную карточку
    python -m src.card --meme-preview generated.json --out /tmp/memes
                                    мемы из ответов модели или постов очереди
"""

from __future__ import annotations

import argparse
import json
import re
import textwrap
from functools import lru_cache
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import config, footage, stories

# Вертикаль 4:5 — формат, который Telegram и ВКонтакте показывают крупно
# и не режут в ленте.
WIDTH, HEIGHT = 1080, 1350

OUT_DIR = config.ROOT / "assets" / "cards"

# Больше шести имён карточка не вмещает, а мелкий шрифт в ленте не читается.
MAX_ARTISTS = 6


def _fit(
    draw: ImageDraw.ImageDraw,
    text: str,
    limit: int,
    sizes: tuple[tuple[int, int], ...],
    *,
    text_font: bool = False,
):
    """Подбирает кегль так, чтобы блок влез в отведённую высоту.

    `text_font` — шрифт для чтения: список артистов мелкий, и заголовочный
    жирный в таком кегле слипается.
    """
    for size, per_line in sizes:
        f = stories.font(size, 600 if text_font else 700, text=text_font)
        lines = textwrap.wrap(text, width=per_line)
        if len(lines) * size * 1.34 <= limit:
            return f, lines, size
    f = stories.font(sizes[-1][0], 600 if text_font else 700, text=text_font)
    return f, textwrap.wrap(text, width=sizes[-1][1])[:6], sizes[-1][0]


def render(verdict: str, artists: list[str], *, label: str = "ПРОЯВКА") -> Image.Image:
    """Карточка: рубрика, список артистов, приговор вкусу, подпись канала.

    Рубрика и подпись — те же `stories.kicker` и `stories.mark`, что у историй
    и обложек: карточку пересылают из лички, и в чужих сторис она должна
    читаться как кадр канала, а не как отдельная поделка.
    """
    img = stories.background(WIDTH, HEIGHT)
    draw = ImageDraw.Draw(img)

    y = int(HEIGHT * 0.09)
    y += stories.kicker(draw, (stories.MARGIN, y), label, 42) + int(HEIGHT * 0.04)

    # Кого прислали. Список — повод узнать себя в чужой карточке.
    if artists:
        shown = ", ".join(artists[:MAX_ARTISTS])
        if len(artists) > MAX_ARTISTS:
            shown += f" и ещё {len(artists) - MAX_ARTISTS}"
        f, lines, size = _fit(
            draw, shown, HEIGHT * 0.16, ((34, 46), (30, 53), (26, 62)), text_font=True
        )
        for line in lines[:4]:
            draw.text((stories.MARGIN, y), line, font=f, fill=(118, 108, 92))
            y += size * 1.34
        y += int(HEIGHT * 0.035)

    # Приговор — главное на карточке. Короткая фраза не должна прижиматься
    # к списку артистов, поэтому блок центрируется в оставшемся поле.
    # Межстрочный плотный: крупный заголовок с разреженными строками
    # распадается на отдельные фразы.
    bottom = HEIGHT * 0.82
    f, lines, size = _fit(
        draw, verdict, bottom - y, ((84, 18), (74, 21), (64, 25), (54, 30), (46, 35))
    )
    block = len(lines) * size * 1.14
    y += max(0, (bottom - y - block) / 2)

    for line in lines:
        draw.text((stories.MARGIN, y), line, font=f, fill=stories.INK)
        y += size * 1.14

    stories.mark(draw, (stories.MARGIN, HEIGHT - int(HEIGHT * 0.095)), fill=stories.INK, size=36)
    return img


def photo_backdrop(source: str | Path) -> Image.Image | None:
    """Фотография во весь кадр 4:5 с уводом низа в чёрное.

    Общая для разбора бота (render_on_photo) и обложки поста (cover): скачать,
    обрезать и затемнить — одно действие, и в двух копиях они со временем разошлись бы.
    Ссылка приходит от магазина, готовый файл — от footage (портрет артиста уже
    скачан), поэтому берутся оба вида.
    """
    try:
        if isinstance(source, Path):
            data = source.read_bytes()
        else:
            response = requests.get(source, timeout=30)
            if response.status_code != 200:
                return None
            data = response.content
        photo = Image.open(BytesIO(data)).convert("RGB")
    except Exception:  # noqa: BLE001 — без картинки вызывающий уйдёт запасным путём
        return None

    # Кадрируем по центру: портреты приходят квадратными, а карточка вытянутая.
    ratio = max(WIDTH / photo.width, HEIGHT / photo.height)
    scaled = photo.resize((int(photo.width * ratio), int(photo.height * ratio)), Image.LANCZOS)
    left = (scaled.width - WIDTH) // 2
    top = int((scaled.height - HEIGHT) * 0.3)  # лицо обычно выше центра
    img = scaled.crop((left, top, left + WIDTH, top + HEIGHT))

    # Затемняем низ, иначе белый текст не прочитается. Обложки бывают пёстрыми
    # до ряби, поэтому к низу уходим почти в чёрное — читаемость важнее картинки.
    # Верх притемняем тоже, но слабо: там стоит рубрика, а обложки бывают
    # ярко-красными — по такой красная линейка не читается вовсе.
    shade = Image.new("L", (WIDTH, HEIGHT), 0)
    draw_shade = ImageDraw.Draw(shade)
    for y in range(HEIGHT):
        down = max(0.0, (y / HEIGHT - 0.18) / 0.82)
        up = max(0.0, (0.16 - y / HEIGHT) / 0.16)
        draw_shade.line([(0, y), (WIDTH, y)], fill=int(max(242 * down**1.25, 120 * up)))
    return Image.composite(Image.new("RGB", (WIDTH, HEIGHT), (12, 10, 9)), img, shade)


def cover(post: dict) -> Path | None:
    """Обложка поста для ленты: та же фотография, но в рамке канала.

    Квадрат 600×600 из магазина одинаково выглядит у всех, кто пересказывает
    релизы, и в ленте не опознаётся. Вертикаль 4:5 занимает больше экрана,
    а рубрика и подпись сверху и снизу делают чужую обложку кадром канала.

    Вклейку на кремовой бумаге пробовали и отказались: обложка — главное,
    что есть у поста про музыку, и оправа отнимает у неё место, ничего
    не добавляя. Подпись канала внизу работает как водяной знак и без оправы.

    Артист и трек берутся из полей поста, а не из его текста: подпись под
    картинкой и так стоит рядом, и повторять её на самой картинке незачем.
    Нет обложки или не скачалась — None, и публикация уходит прежним путём.

    У разборов (ОТКУДА НОГИ, МЕЖДУ СТРОК) обложки нет вовсе, а пост без медиа
    в ленте проматывают — поэтому кадром становится фотография артиста,
    упомянутого в тексте (footage.artist_image, тот же поиск, что у клипов).
    Внизу тогда стоит его имя: лицо без подписи ленте ничего не говорит.
    """
    source: str | Path = post.get("cover", "")
    artist, name = post.get("artist", ""), post.get("release") or post.get("track", "")
    if not source:
        text = post.get("text", "")
        source, artist, name = footage.artist_image(text) or "", footage.find_artist(text), ""

    img = photo_backdrop(source) if source else None
    if img is None:
        return None

    rubric = config.RUBRIC_BY_KEY.get(post.get("rubric", ""))
    draw = ImageDraw.Draw(img)
    stories.kicker(draw, (stories.MARGIN, int(HEIGHT * 0.07)), rubric.title if rubric else "", 40,
                   stories.LIGHT)

    # Подписывается сам релиз; ведущий трек — только когда названия релиза нет
    # (посты до 12.09.2026 его не сохраняли).
    caption = " — ".join(part for part in (artist, name) if part)
    if caption:
        f, lines, size = _fit(
            draw, caption, HEIGHT * 0.3, ((88, 17), (74, 21), (62, 25), (52, 30))
        )
        y = HEIGHT - int(HEIGHT * 0.155) - len(lines) * size * 1.02
        for line in lines:
            draw.text((stories.MARGIN + 2, y + 3), line, font=f, fill=(0, 0, 0))
            draw.text((stories.MARGIN, y), line, font=f, fill=stories.LIGHT)
            y += size * 1.02

    stories.mark(draw, (stories.MARGIN, HEIGHT - int(HEIGHT * 0.085)), size=36)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "cover.jpg"
    img.save(path, "JPEG", quality=90)
    return path


def render_on_photo(verdict: str, photo_url: str, *, label: str = "ПРОЯВКА") -> Image.Image | None:
    """Карточка на портрете артиста.

    Человек спрашивает про артиста и ждёт увидеть артиста — служебная плашка
    с текстом на его месте выглядит как слайд из презентации. Фотография
    занимает весь кадр, текста на ней минимум: карточку смотрят, а не читают.
    """
    img = photo_backdrop(photo_url)
    if img is None:
        return None

    draw = ImageDraw.Draw(img)
    # Буквы рубрики светлые: по красной обложке красное пропало бы.
    stories.kicker(draw, (stories.MARGIN, int(HEIGHT * 0.07)), label, 40, stories.LIGHT)

    # Приговор — внизу, по нижней границе кадра.
    f, lines, size = _fit(draw, verdict, HEIGHT * 0.34, ((78, 19), (68, 22), (58, 26), (50, 31)))
    y = HEIGHT - int(HEIGHT * 0.155) - len(lines) * size * 1.06
    for line in lines:
        draw.text((stories.MARGIN + 2, y + 3), line, font=f, fill=(0, 0, 0))
        draw.text((stories.MARGIN, y), line, font=f, fill=stories.LIGHT)
        y += size * 1.06

    stories.mark(draw, (stories.MARGIN, HEIGHT - int(HEIGHT * 0.085)), size=36)
    return img


def save(
    verdict: str,
    artists: list[str],
    *,
    label: str = "ПРОЯВКА",
    name: str = "card",
    photo_url: str = "",
) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{name}.jpg"

    image = render_on_photo(verdict, photo_url, label=label) if photo_url else None
    if image is None:
        image = render(verdict, artists, label=label)

    image.convert("RGB").save(path, "JPEG", quality=90)
    return path


# ─────────────────────────── мем ───────────────────────────

# Надпись на меме — обычный гротеск нормального начертания, как в мемах
# из чатов и тиктока: жирные капсы Impact читаются как мем десятого года.
# Здесь привычный «телефонный» рисунок Arial нужен намеренно — по нему мем
# и узнают, — поэтому не Golos Text кадра, а Arimo: свободный близнец Arial
# с кириллицей. Лежит в репозитории рядом со шрифтами кадра (stories.FONTS):
# системный Arial есть на macOS, а на раннере Actions его нет.
MEME_FONT = stories.FONTS / "Arimo-Regular.ttf"


@lru_cache(maxsize=16)
def _meme_font(size: int) -> ImageFont.FreeTypeFont:
    """Кешируется: надпись перебирает кегли, и читать файл каждый раз незачем."""
    return ImageFont.truetype(str(MEME_FONT), size)


# Кегль и сколько строк на нём можно: одна строка лучше двух, пока кегль
# не мельчает, две — лучше мелкой одной.
MEME_SIZES = ((80, 1), (72, 1), (64, 1), (58, 1), (64, 2), (58, 2), (52, 2))
MEME_PAD = int(WIDTH * 0.045)
MEME_MARK = "ПЛЁНКА @plenka_fm"
MEME_MARK_SIZE = 30

# Эмодзи в Arimo нет, и на их месте рисуются пустые квадраты.
_EMOJI = re.compile("[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U00002B00-\U00002BFF\U0000FE0F\U0000200D]")


def _wrap(draw: ImageDraw.ImageDraw, text: str, f, width: float) -> list[str]:
    """Перенос по ширине в пикселях: textwrap считает буквы, а «Ш» втрое
    шире «і», и подбор по буквам то не добивает строку, то выносит за край."""
    lines: list[str] = []
    for paragraph in text.split("\n"):
        line = ""
        for word in paragraph.split():
            if line and draw.textlength(f"{line} {word}", font=f) > width:
                lines.append(line)
                line = word
            else:
                line = f"{line} {word}".strip()
        if line:
            lines.append(line)
    return lines


def _meme_block(draw: ImageDraw.ImageDraw, text: str):
    """Строки, шрифт и кегль одной надписи под ширину картинки."""
    text = _EMOJI.sub("", stories.strip_html(text or "")).strip()
    if not text:
        return [], None, 0
    for size, max_lines in MEME_SIZES:
        f = _meme_font(size)
        lines = _wrap(draw, text, f, WIDTH - 2 * MEME_PAD)
        if len(lines) <= max_lines:
            break
    if len(lines) == 2:
        # Делим поровну: слово, висящее на второй строке в одиночку, читается
        # как ошибка вёрстки. Шире жадного переноса не выйдет — его разбиение
        # тоже среди вариантов.
        words = text.split()
        cut = min(
            range(1, len(words)),
            key=lambda i: max(
                draw.textlength(" ".join(words[:i]), font=f),
                draw.textlength(" ".join(words[i:]), font=f),
            ),
        )
        lines = [" ".join(words[:cut]), " ".join(words[cut:])]
    return lines, f, size


def render_meme(top: str, bottom: str, picture: str) -> Image.Image | None:
    """Мем: шаблон из каталога, надпись прямо на нём, водяной знак в углу.

    Вид взят у мемов, которые пересылают в чатах: белый обычный гротеск
    по центру, сверху подводка, снизу поворот. Под картинкой идёт подпись
    канала — отдельная реплика, её отправляет publish.send.

    Отвергнуты два вида: шутка на белой плашке над шаблоном и чистый шаблон
    с белой полосой под ним. Белое поле читается как рамка чужого сайта
    и обрезается при пересылке, поэтому знак канала стоит на самой
    картинке: полупрозрачный, в нижнем углу, под нижней надписью — так
    они не пересекаются при любой длине строки.

    Нет шаблона — None, и мем уходит текстом.
    """
    source = config.MEME_TEMPLATES / f"{picture}.jpg"
    if not picture or not source.exists():
        return None
    img = Image.open(source).convert("RGB")
    img = img.resize((WIDTH, round(img.height * WIDTH / img.width)), Image.LANCZOS)
    draw = ImageDraw.Draw(img)

    placed = []  # (y, строка, шрифт, кегль)
    lines, f, size = _meme_block(draw, top)
    for i, line in enumerate(lines):
        placed.append((MEME_PAD + i * size * 1.15, line, f, size))
    lines, f, size = _meme_block(draw, bottom)
    start = img.height - MEME_PAD - MEME_MARK_SIZE * 1.6 - len(lines) * size * 1.15
    for i, line in enumerate(lines):
        placed.append((start + i * size * 1.15, line, f, size))

    # Под буквами мягкая тень: тонкая обводка на светлом фоне теряется,
    # а толстая превращает надпись в тот самый Impact.
    shadow = Image.new("L", img.size, 0)
    shade = ImageDraw.Draw(shadow)
    for y, line, f, size in placed:
        shade.text((WIDTH / 2, y), line, font=f, fill=150, anchor="ma", stroke_width=size // 9)
    img.paste((0, 0, 0), (0, 0, *img.size), shadow.filter(ImageFilter.GaussianBlur(6)))

    draw = ImageDraw.Draw(img)
    for y, line, f, size in placed:
        draw.text(
            (WIDTH / 2, y), line, font=f, fill=(255, 255, 255), anchor="ma",
            stroke_width=max(2, size // 26), stroke_fill=(0, 0, 0),
        )

    # Знак полупрозрачный: пересланная картинка несёт адрес канала,
    # но не превращается в рекламу.
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).text(
        (WIDTH - MEME_PAD, img.height - MEME_PAD), MEME_MARK,
        font=_meme_font(MEME_MARK_SIZE), fill=(255, 255, 255, 170),
        anchor="rd", stroke_width=2, stroke_fill=(0, 0, 0, 110),
    )
    return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")


def meme_text(meme: dict) -> str:
    """Мем одним текстом: надписи с картинки и подпись под ней.

    Так мем уходит, когда картинки нет (ВКонтакте, сбой отрисовки), и так его
    проверяет quality — по всему, что увидит читатель.
    """
    on_picture = "\n".join(
        s.strip() for s in (meme.get("top"), meme.get("bottom")) if isinstance(s, str) and s.strip()
    )
    return "\n\n".join(p for p in (on_picture, (meme.get("text") or "").strip()) if p)


def meme(post: dict) -> Path | None:
    """Картинка мема для ленты. None — шаблона нет или он не открылся."""
    try:
        img = render_meme(post.get("top", ""), post.get("bottom", ""), post.get("picture", ""))
    except OSError:  # битый шаблон не должен ронять публикацию
        return None
    if img is None:
        return None
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "meme.jpg"
    img.save(path, "JPEG", quality=90)
    return path


def meme_preview(paths: list[Path], out: Path) -> int:
    """Мемы из файлов — посмотреть глазами до публикации. Файл — пост очереди
    или список ответов модели: поля у них одни и те же."""
    out.mkdir(parents=True, exist_ok=True)
    count = 0
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        for item in data if isinstance(data, list) else [data]:
            image = render_meme(item.get("top", ""), item.get("bottom", ""), item.get("picture", ""))
            if image is None:
                print(f"— нет шаблона «{item.get('picture', '')}»")
                continue
            count += 1
            target = out / f"meme-{count}-{item['picture']}.jpg"
            image.save(target, "JPEG", quality=90)
            print(f"{target}\n  подпись: {item.get('text', '')}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Карточка разбора вкуса")
    parser.add_argument("--verdict", default="ты слушаешь Мемфис через три пересадки и не знал")
    parser.add_argument("--artists", default="Bones, Sematary, Slipknot, Bladee, PHARAOH")
    parser.add_argument(
        "--meme-preview",
        nargs="+",
        type=Path,
        metavar="JSON",
        help="нарисовать мемы из файлов: пост очереди или список ответов модели",
    )
    parser.add_argument("--out", type=Path, default=OUT_DIR, help="куда класть картинки мемов")
    args = parser.parse_args()

    if args.meme_preview:
        return meme_preview(args.meme_preview, args.out)

    path = save(args.verdict, [a.strip() for a in args.artists.split(",") if a.strip()])
    print(f"Карточка готова: {path.relative_to(config.ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
