"""Аватарки-обманки: мимикрия под элементы интерфейса.

Идея в том, чтобы аватарка на секунду притворилась чем-то системным —
несработавшей картинкой, выключенным звуком, вечной загрузкой, соринкой
на экране. Человек реагирует рефлекторно (обновить, протереть, проверить
звук) и только потом понимает, что его обманули. Этой секунды хватает,
чтобы канал запомнился.

    python -m src.make_avatar_trick

Файлы кладутся в assets/avatar/. Всё рисуется с запасом под круглую
обрезку, которую делают и Telegram, и ВКонтакте.
"""

from __future__ import annotations

import argparse
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT_DIR = Path(__file__).resolve().parent.parent / "assets" / "avatar"

FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
)


def font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default(size)


def centered(draw: ImageDraw.ImageDraw, text: str, f: ImageFont.FreeTypeFont, size: int, y: float):
    box = draw.textbbox((0, 0), text, font=f)
    draw.text(((size - box[2]) / 2 - box[0], y), text, font=f, fill=(140, 140, 145))


def variant_broken_image(size: int) -> Image.Image:
    """«Картинка не загрузилась».

    Самый сильный обман: первое, что делает человек, — пытается обновить
    страницу. Серый фон и знакомый значок сломанного изображения.
    """
    img = Image.new("RGB", (size, size), (58, 58, 60))
    draw = ImageDraw.Draw(img)

    s = size / 100  # единица масштаба, чтобы рисовать в процентах

    # Рамка «фотографии»
    left, top, right, bottom = 28 * s, 32 * s, 72 * s, 68 * s
    draw.rounded_rectangle([left, top, right, bottom], radius=3 * s,
                           outline=(150, 150, 155), width=int(2.2 * s))

    # Горы и солнце — классический значок изображения
    draw.ellipse([left + 6 * s, top + 6 * s, left + 13 * s, top + 13 * s],
                 fill=(150, 150, 155))
    draw.polygon(
        [
            (left + 4 * s, bottom - 4 * s),
            (left + 17 * s, top + 17 * s),
            (left + 28 * s, bottom - 4 * s),
        ],
        fill=(150, 150, 155),
    )
    draw.polygon(
        [
            (left + 20 * s, bottom - 4 * s),
            (left + 31 * s, top + 21 * s),
            (right - 4 * s, bottom - 4 * s),
        ],
        fill=(120, 120, 126),
    )

    # Трещина: диагональ, разрывающая рамку
    draw.line(
        [(left + 2 * s, bottom + 2 * s), (right - 2 * s, top - 2 * s)],
        fill=(58, 58, 60),
        width=int(3.4 * s),
    )

    return img


def variant_muted(size: int) -> Image.Image:
    """«Звук выключен».

    Для музыкального канала это ещё и шутка: музыка, которую вы не слышите.
    Рефлекс — полезть проверять громкость.
    """
    img = Image.new("RGB", (size, size), (16, 16, 18))
    draw = ImageDraw.Draw(img)
    s = size / 100
    white = (236, 236, 232)

    # Корпус динамика
    draw.rectangle([32 * s, 42 * s, 42 * s, 58 * s], fill=white)
    draw.polygon(
        [(42 * s, 42 * s), (56 * s, 30 * s), (56 * s, 70 * s), (42 * s, 58 * s)],
        fill=white,
    )

    # Перечёркивание
    draw.line([(60 * s, 38 * s), (76 * s, 62 * s)], fill=(214, 40, 40), width=int(4.2 * s))
    draw.line([(76 * s, 38 * s), (60 * s, 62 * s)], fill=(214, 40, 40), width=int(4.2 * s))

    return img


def variant_loading(size: int) -> Image.Image:
    """«Вечная загрузка».

    Кажется, что канал ещё не прогрузился. Спиннер замер навсегда.
    """
    img = Image.new("RGB", (size, size), (24, 24, 26))
    draw = ImageDraw.Draw(img)
    s = size / 100

    center = size / 2
    radius = 24 * s
    segments = 12

    for i in range(segments):
        angle = 2 * math.pi * i / segments - math.pi / 2
        # Затухание по кругу — как у системного индикатора
        shade = int(70 + 165 * (i / segments))
        x1 = center + math.cos(angle) * radius * 0.55
        y1 = center + math.sin(angle) * radius * 0.55
        x2 = center + math.cos(angle) * radius
        y2 = center + math.sin(angle) * radius
        draw.line([(x1, y1), (x2, y2)], fill=(shade, shade, shade + 4), width=int(3.6 * s))

    centered(draw, "0%", font(int(11 * s)), size, center + radius + 6 * s)
    return img


def variant_speck(size: int) -> Image.Image:
    """«Соринка на экране».

    Тёмный кружок и одна ворсинка. Люди пытаются смахнуть её пальцем —
    самый физический из всех обманов.
    """
    img = Image.new("RGB", (size, size), (18, 18, 20))
    draw = ImageDraw.Draw(img)
    s = size / 100

    # Ворсинка: ломаная кривая, чуть изогнутая
    points = [
        (36 * s, 62 * s),
        (44 * s, 52 * s),
        (52 * s, 47 * s),
        (60 * s, 44 * s),
        (66 * s, 38 * s),
    ]
    draw.line(points, fill=(206, 202, 194), width=max(2, int(1.6 * s)), joint="curve")
    # Утолщение у основания — так выглядит настоящий волосок
    draw.line(points[:2], fill=(206, 202, 194), width=max(3, int(2.4 * s)))

    # Мягкая тень под ворсинкой, чтобы читалась как объём
    shadow = Image.new("RGB", (size, size), (18, 18, 20))
    sdraw = ImageDraw.Draw(shadow)
    sdraw.line(
        [(x + 1.4 * s, y + 1.4 * s) for x, y in points],
        fill=(8, 8, 9),
        width=max(3, int(2.6 * s)),
        joint="curve",
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(2.2 * s))
    img = Image.blend(img, shadow, 0.5)

    draw = ImageDraw.Draw(img)
    draw.line(points, fill=(212, 208, 200), width=max(2, int(1.6 * s)), joint="curve")

    # Пара пылинок для достоверности
    random.seed(3)
    for _ in range(7):
        x = random.uniform(28 * s, 72 * s)
        y = random.uniform(28 * s, 72 * s)
        r = random.uniform(0.3 * s, 0.7 * s)
        draw.ellipse([x - r, y - r, x + r, y + r], fill=(150, 148, 143))

    return img


def variant_unread(size: int) -> Image.Image:
    """«Одно непрочитанное».

    Мимикрия под бейдж уведомления. В списке чатов рядом окажется настоящий
    счётчик — и на секунду их станет два.
    """
    img = Image.new("RGB", (size, size), (20, 20, 22))
    draw = ImageDraw.Draw(img)
    s = size / 100

    radius = 21 * s
    center = size / 2
    draw.ellipse(
        [center - radius, center - radius, center + radius, center + radius],
        fill=(228, 46, 46),
    )

    f = font(int(26 * s))
    box = draw.textbbox((0, 0), "1", font=f)
    draw.text(
        ((size - box[2]) / 2 - box[0], (size - box[3]) / 2 - box[1]),
        "1",
        font=f,
        fill=(255, 255, 255),
    )
    return img


def main() -> int:
    parser = argparse.ArgumentParser(description="Аватарки-обманки")
    parser.add_argument("--size", type=int, default=1000)
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    variants = {
        "trick-1-broken": variant_broken_image,
        "trick-2-muted": variant_muted,
        "trick-3-loading": variant_loading,
        "trick-4-speck": variant_speck,
        "trick-5-unread": variant_unread,
    }
    for name, builder in variants.items():
        path = OUT_DIR / f"avatar-{name}.png"
        builder(args.size).save(path, "PNG")
        print(f"  ✓ {path.name}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
