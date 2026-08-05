"""Аватарки: магнитная лента и кассета.

Здесь обыгрывается именно аудиоплёнка. Два приёма работают лучше всего:
катушка кассеты в круглой аватарке неотличима от индикатора загрузки,
а натянутая лента — от артефакта на экране.

    python -m src.make_avatar_tape
"""

from __future__ import annotations

import argparse
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT_DIR = Path(__file__).resolve().parent.parent / "assets" / "avatar"

# Магнитная лента узнаётся по цвету: тёмная бронза с тёплым отливом.
TAPE_DARK = (58, 40, 28)
TAPE_MID = (96, 66, 42)
TAPE_LIGHT = (146, 104, 64)
TAPE_SHEEN = (206, 168, 116)

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


def grain(img: Image.Image, strength: int = 16) -> Image.Image:
    noise = Image.new("L", img.size)
    noise.putdata([random.randint(0, strength) for _ in range(img.width * img.height)])
    noise = noise.filter(ImageFilter.GaussianBlur(0.4))
    return Image.composite(
        Image.new("RGB", img.size, (255, 255, 255)), img, noise.point(lambda v: v // 10)
    )


def variant_hub(size: int) -> Image.Image:
    """Катушка кассеты — она же индикатор загрузки.

    Зубчатая сердцевина и намотанная лента. В мелком кружке читается как
    крутящийся спиннер: кажется, что аватарка ещё грузится.
    """
    img = Image.new("RGB", (size, size), (14, 13, 15))
    draw = ImageDraw.Draw(img)
    center = size / 2
    random.seed(4)

    # Намотанная лента: плотные кольца от края к центру
    outer = size * 0.46
    inner = size * 0.19
    rings = 46
    for i in range(rings):
        t = i / rings
        radius = outer - (outer - inner) * t
        # Чередование оттенков даёт ощущение витков
        shade = TAPE_MID if i % 2 else TAPE_DARK
        if i % 9 == 0:
            shade = TAPE_LIGHT
        draw.ellipse(
            [center - radius, center - radius, center + radius, center + radius],
            outline=shade,
            width=max(2, int(size * 0.007)),
        )

    # Блик на намотке — лента глянцевая
    gloss = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(gloss)
    gdraw.arc(
        [center - outer * 0.92, center - outer * 0.92, center + outer * 0.92, center + outer * 0.92],
        start=205, end=265, fill=(*TAPE_SHEEN, 150), width=int(size * 0.05),
    )
    gloss = gloss.filter(ImageFilter.GaussianBlur(size * 0.012))
    img.paste(gloss, (0, 0), gloss)

    draw = ImageDraw.Draw(img)

    # Сердцевина катушки — светлый пластик
    draw.ellipse(
        [center - inner, center - inner, center + inner, center + inner],
        fill=(212, 208, 198),
    )

    # Зубцы, за которые цепляется механизм: главная узнаваемая деталь
    teeth = 6
    tooth_len = inner * 0.52
    tooth_w = inner * 0.19
    for i in range(teeth):
        angle = 2 * math.pi * i / teeth - math.pi / 2
        x = center + math.cos(angle) * (inner * 0.44)
        y = center + math.sin(angle) * (inner * 0.44)
        draw.polygon(
            [
                (x + math.cos(angle) * tooth_len, y + math.sin(angle) * tooth_len),
                (x + math.cos(angle + 2.2) * tooth_w, y + math.sin(angle + 2.2) * tooth_w),
                (x + math.cos(angle - 2.2) * tooth_w, y + math.sin(angle - 2.2) * tooth_w),
            ],
            fill=(14, 13, 15),
        )

    # Центральное отверстие
    hole = inner * 0.30
    draw.ellipse([center - hole, center - hole, center + hole, center + hole], fill=(14, 13, 15))

    return grain(img)


def variant_strand(size: int) -> Image.Image:
    """Лента, натянутая через кадр.

    Одна блестящая полоса магнитной ленты наискось. В списке чатов читается
    как царапина или артефакт на экране — рука тянется стереть.
    """
    img = Image.new("RGB", (size, size), (15, 14, 16))
    draw = ImageDraw.Draw(img)
    random.seed(9)

    # Лента идёт по диагонали с лёгким провисанием
    points = []
    for i in range(61):
        t = i / 60
        x = size * (0.06 + 0.88 * t)
        sag = math.sin(t * math.pi) * size * 0.085
        y = size * (0.30 + 0.34 * t) + sag
        points.append((x, y))

    width = int(size * 0.062)

    # Тень под лентой
    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    sdraw.line([(x + size * 0.012, y + size * 0.018) for x, y in points],
               fill=(0, 0, 0, 170), width=width, joint="curve")
    shadow = shadow.filter(ImageFilter.GaussianBlur(size * 0.016))
    img.paste(shadow, (0, 0), shadow)

    draw = ImageDraw.Draw(img)
    draw.line(points, fill=TAPE_DARK, width=width, joint="curve")
    draw.line([(x, y - width * 0.18) for x, y in points], fill=TAPE_MID,
              width=int(width * 0.55), joint="curve")
    # Блик вдоль верхнего края — лента отражает свет узкой полосой
    draw.line([(x, y - width * 0.30) for x, y in points], fill=TAPE_SHEEN,
              width=max(2, int(width * 0.14)), joint="curve")

    # Пылинки, чтобы фон не выглядел стерильным
    for _ in range(14):
        px = random.uniform(size * 0.1, size * 0.9)
        py = random.uniform(size * 0.1, size * 0.9)
        r = random.uniform(size * 0.002, size * 0.004)
        draw.ellipse([px - r, py - r, px + r, py + r], fill=(96, 94, 90))

    return grain(img)


def variant_window(size: int) -> Image.Image:
    """Окно кассеты: две катушки за прозрачной вставкой.

    Самый узнаваемый силуэт аудиокассеты. В кружке пара катушек читается
    почти как пара глаз — этого хватает, чтобы зацепить взгляд.
    """
    img = Image.new("RGB", (size, size), (22, 21, 24))
    draw = ImageDraw.Draw(img)
    random.seed(15)

    # Корпус кассеты
    draw.rounded_rectangle(
        [size * 0.06, size * 0.24, size * 0.94, size * 0.76],
        radius=size * 0.035,
        fill=(32, 30, 34),
        outline=(58, 55, 60),
        width=max(2, int(size * 0.006)),
    )

    # Прозрачное окно
    draw.rounded_rectangle(
        [size * 0.16, size * 0.34, size * 0.84, size * 0.66],
        radius=size * 0.02,
        fill=(46, 43, 48),
    )

    # Две катушки: левая почти пустая, правая полная — кассета доиграна
    for cx, fill_ratio in ((size * 0.33, 0.30), (size * 0.67, 0.86)):
        cy = size * 0.50
        outer = size * 0.125 * (0.55 + fill_ratio * 0.75)
        rings = 16
        for i in range(rings):
            radius = outer * (1 - i / rings * 0.62)
            shade = TAPE_MID if i % 2 else TAPE_DARK
            draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius],
                         outline=shade, width=max(2, int(size * 0.005)))
        hub = size * 0.035
        draw.ellipse([cx - hub, cy - hub, cx + hub, cy + hub], fill=(208, 204, 196))
        hole = hub * 0.42
        draw.ellipse([cx - hole, cy - hole, cx + hole, cy + hole], fill=(22, 21, 24))

    # Участок ленты между катушками
    draw.line([(size * 0.33, size * 0.62), (size * 0.67, size * 0.62)],
              fill=TAPE_DARK, width=max(3, int(size * 0.014)))

    return grain(img)


def variant_out_of_tape(size: int) -> Image.Image:
    """«Плёнка кончилась»: пустая катушка и оборванный хвост.

    Читается как ошибка — будто контент закончился или не подгрузился.
    """
    img = Image.new("RGB", (size, size), (16, 15, 17))
    draw = ImageDraw.Draw(img)
    center = size / 2
    random.seed(31)

    # Пустая катушка: только сердцевина, ленты нет
    inner = size * 0.17
    draw.ellipse([center - inner, center - inner, center + inner, center + inner],
                 fill=(206, 202, 192))
    teeth = 6
    for i in range(teeth):
        angle = 2 * math.pi * i / teeth - math.pi / 2
        x = center + math.cos(angle) * (inner * 0.44)
        y = center + math.sin(angle) * (inner * 0.44)
        draw.polygon(
            [
                (x + math.cos(angle) * inner * 0.52, y + math.sin(angle) * inner * 0.52),
                (x + math.cos(angle + 2.2) * inner * 0.19, y + math.sin(angle + 2.2) * inner * 0.19),
                (x + math.cos(angle - 2.2) * inner * 0.19, y + math.sin(angle - 2.2) * inner * 0.19),
            ],
            fill=(16, 15, 17),
        )
    hole = inner * 0.30
    draw.ellipse([center - hole, center - hole, center + hole, center + hole], fill=(16, 15, 17))

    # Оборванный хвост ленты, уходящий за край
    points = [
        (center + inner * 0.9, center - inner * 0.2),
        (size * 0.72, size * 0.34),
        (size * 0.86, size * 0.22),
        (size * 1.02, size * 0.16),
    ]
    draw.line(points, fill=TAPE_DARK, width=max(3, int(size * 0.030)), joint="curve")
    draw.line([(x, y - size * 0.008) for x, y in points], fill=TAPE_SHEEN,
              width=max(2, int(size * 0.007)), joint="curve")

    return grain(img)


def main() -> int:
    parser = argparse.ArgumentParser(description="Аватарки: магнитная лента")
    parser.add_argument("--size", type=int, default=1000)
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    variants = {
        "tape-1-hub": variant_hub,
        "tape-2-strand": variant_strand,
        "tape-3-window": variant_window,
        "tape-4-empty": variant_out_of_tape,
    }
    for name, builder in variants.items():
        path = OUT_DIR / f"avatar-{name}.png"
        builder(args.size).save(path, "PNG")
        print(f"  ✓ {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
