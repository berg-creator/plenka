"""Аватарки в эстетике нулевых: глянец, градиенты, блики.

Визуальный язык той эпохи — скевоморфизм: кнопки блестят, у всего есть
отражение и объём. Плюс приём обмана: кнопка записи читается как индикатор
прямого эфира, колесо плеера — как элемент управления.

    python -m src.make_avatar_2000s
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


def radial(size: int, inner: tuple[int, int, int], outer: tuple[int, int, int],
           center: tuple[float, float] | None = None) -> Image.Image:
    """Радиальный градиент — основа глянцевого вида нулевых."""
    cx, cy = center or (size / 2, size / 2)
    img = Image.new("RGB", (size, size), outer)
    draw = ImageDraw.Draw(img)
    steps = 90
    max_r = size * 0.75
    for i in range(steps, 0, -1):
        t = i / steps
        r = max_r * t
        color = tuple(int(outer[c] + (inner[c] - outer[c]) * (1 - t)) for c in range(3))
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)
    return img


def gloss(img: Image.Image, strength: float = 0.55) -> Image.Image:
    """Блик-полумесяц в верхней части — фирменная деталь кнопок нулевых."""
    size = img.width
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    draw.ellipse(
        [size * 0.16, size * 0.06, size * 0.84, size * 0.52],
        fill=(255, 255, 255, int(180 * strength)),
    )
    layer = layer.filter(ImageFilter.GaussianBlur(size * 0.035))
    return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")


def variant_rec(size: int) -> Image.Image:
    """Кнопка записи: глянцевый красный круг.

    Читается как индикатор прямого эфира — кажется, что прямо сейчас
    идёт запись. Круглая форма ложится в аватарку идеально.
    """
    img = radial(size, (250, 90, 84), (128, 12, 16))
    draw = ImageDraw.Draw(img)

    # Тёмный ободок, отделяющий кнопку от корпуса
    draw.ellipse([2, 2, size - 2, size - 2], outline=(52, 8, 10), width=int(size * 0.035))

    img = gloss(img, 0.6)
    draw = ImageDraw.Draw(img)

    # Внутренний круг записи
    r = size * 0.17
    c = size / 2
    draw.ellipse([c - r, c - r, c + r, c + r], fill=(255, 255, 255))

    return img


def variant_clickwheel(size: int) -> Image.Image:
    """Колесо плеера нулевых.

    Кольцо с подписями по сторонам и кнопкой в центре. Чистая ностальгия,
    к тому же круглое по природе.
    """
    img = radial(size, (250, 250, 250), (206, 206, 210))
    draw = ImageDraw.Draw(img)

    c = size / 2
    outer = size * 0.47
    inner = size * 0.17

    draw.ellipse([c - outer, c - outer, c + outer, c + outer],
                 outline=(178, 178, 184), width=max(2, int(size * 0.006)))

    # Центральная кнопка с лёгким углублением
    hub = radial(size, (238, 238, 240), (198, 198, 204))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([c - inner, c - inner, c + inner, c + inner], fill=255)
    img.paste(hub, (0, 0), mask)
    draw = ImageDraw.Draw(img)
    draw.ellipse([c - inner, c - inner, c + inner, c + inner],
                 outline=(170, 170, 176), width=max(2, int(size * 0.005)))

    # Подписи по кругу
    f = font(int(size * 0.075))
    grey = (110, 110, 116)
    labels = {
        "MENU": (c, c - outer * 0.70),
        "▶︎▶︎": (c + outer * 0.66, c),
        "◀︎◀︎": (c - outer * 0.66, c),
        "▶︎ ❙❙": (c, c + outer * 0.70),
    }
    for text, (x, y) in labels.items():
        box = draw.textbbox((0, 0), text, font=f)
        draw.text((x - box[2] / 2 - box[0], y - box[3] / 2 - box[1]), text, font=f, fill=grey)

    return img


def variant_cd(size: int) -> Image.Image:
    """Компакт-диск с радужным отливом.

    Символ перехода от кассет к цифре — и очень узнаваемая картинка нулевых.
    """
    img = Image.new("RGB", (size, size), (12, 12, 14))
    draw = ImageDraw.Draw(img)
    c = size / 2
    outer = size * 0.47

    # Радужный отлив: секторы с плавным переходом оттенка
    sectors = 220
    palette = [
        (86, 132, 210), (120, 96, 200), (196, 96, 168),
        (214, 132, 96), (196, 196, 96), (110, 196, 140),
    ]
    for i in range(sectors):
        angle = 360 * i / sectors
        t = (i / sectors) * len(palette)
        a, b = palette[int(t) % len(palette)], palette[(int(t) + 1) % len(palette)]
        f = t - int(t)
        color = tuple(int(a[k] + (b[k] - a[k]) * f) for k in range(3))
        draw.pieslice([c - outer, c - outer, c + outer, c + outer],
                      start=angle, end=angle + 360 / sectors + 1, fill=color)

    # Затемнение к центру — диск не светится равномерно
    shade = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shade)
    for i in range(40):
        t = i / 40
        r = outer * (1 - t * 0.62)
        sdraw.ellipse([c - r, c - r, c + r, c + r], fill=(0, 0, 0, int(6 + t * 5)))
    img = Image.alpha_composite(img.convert("RGBA"), shade).convert("RGB")
    draw = ImageDraw.Draw(img)

    # Прозрачное кольцо и отверстие
    ring = size * 0.155
    draw.ellipse([c - ring, c - ring, c + ring, c + ring], fill=(206, 208, 212))
    hole = size * 0.072
    draw.ellipse([c - hole, c - hole, c + hole, c + hole], fill=(12, 12, 14))

    return gloss(img, 0.35)


def variant_deck(size: int) -> Image.Image:
    """Дека магнитофона: окно кассеты, индикаторы, глянцевый корпус.

    Собирательный образ музыкального центра нулевых.
    """
    img = radial(size, (58, 58, 64), (18, 18, 21))
    draw = ImageDraw.Draw(img)
    random.seed(2000)

    # Окно деки
    draw.rounded_rectangle(
        [size * 0.13, size * 0.30, size * 0.87, size * 0.70],
        radius=size * 0.03, fill=(26, 26, 30), outline=(96, 96, 104),
        width=max(2, int(size * 0.006)),
    )

    # Две катушки за стеклом
    for cx, ratio in ((size * 0.33, 0.42), (size * 0.67, 0.80)):
        cy = size * 0.50
        r = size * 0.10 * (0.6 + ratio * 0.7)
        for i in range(12):
            rr = r * (1 - i / 12 * 0.6)
            draw.ellipse([cx - rr, cy - rr, cx + rr, cy + rr],
                         outline=(92, 64, 40) if i % 2 else (58, 40, 26),
                         width=max(2, int(size * 0.005)))
        hub = size * 0.028
        draw.ellipse([cx - hub, cy - hub, cx + hub, cy + hub], fill=(198, 196, 190))

    # Индикатор уровня: зелёные и красные сегменты
    x = size * 0.18
    y = size * 0.775
    for i in range(14):
        lit = i < 9
        color = (72, 210, 96) if i < 7 else ((228, 176, 48) if i < 10 else (226, 62, 52))
        if not lit:
            color = tuple(int(v * 0.22) for v in color)
        draw.rectangle([x, y, x + size * 0.035, y + size * 0.048], fill=color)
        x += size * 0.048

    # Красный огонёк питания
    draw.ellipse([size * 0.80, size * 0.20, size * 0.855, size * 0.255], fill=(232, 60, 52))

    return gloss(img, 0.28)


def main() -> int:
    parser = argparse.ArgumentParser(description="Аватарки в эстетике нулевых")
    parser.add_argument("--size", type=int, default=1000)
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    variants = {
        "00s-1-rec": variant_rec,
        "00s-2-wheel": variant_clickwheel,
        "00s-3-cd": variant_cd,
        "00s-4-deck": variant_deck,
    }
    for name, builder in variants.items():
        path = OUT_DIR / f"avatar-{name}.png"
        builder(args.size).save(path, "PNG")
        print(f"  ✓ {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
