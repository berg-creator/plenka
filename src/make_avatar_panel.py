"""Аватарка-панель управления плеером.

Задача — не иконка, а похожая на настоящую деталь: шлифованный металл,
фаска по краю, утопленные кнопки с тенями, выгравированные символы.
Форма круглая, поэтому в аватарку ложится без обрезки.

    python -m src.make_avatar_panel
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


def brushed_metal(size: int, base: tuple[int, int, int], contrast: int = 16) -> Image.Image:
    """Радиальная шлифовка — то, по чему металл узнаётся с первого взгляда."""
    img = Image.new("RGB", (size, size), base)
    draw = ImageDraw.Draw(img)
    center = size / 2
    random.seed(77)

    # Концентрические штрихи разной яркости
    radius = size * 0.72
    step = max(1, int(size * 0.0022))
    r = radius
    while r > 0:
        delta = random.randint(-contrast, contrast)
        color = tuple(max(0, min(255, base[i] + delta)) for i in range(3))
        draw.ellipse([center - r, center - r, center + r, center + r],
                     outline=color, width=step)
        r -= step

    # Лёгкие радиальные росчерки поверх
    for _ in range(220):
        angle = random.uniform(0, 2 * math.pi)
        r1 = random.uniform(size * 0.10, size * 0.70)
        r2 = r1 + random.uniform(size * 0.02, size * 0.10)
        delta = random.randint(-contrast, contrast)
        color = tuple(max(0, min(255, base[i] + delta)) for i in range(3))
        draw.line(
            [
                (center + math.cos(angle) * r1, center + math.sin(angle) * r1),
                (center + math.cos(angle) * r2, center + math.sin(angle) * r2),
            ],
            fill=color,
            width=max(1, int(size * 0.0018)),
        )

    return img.filter(ImageFilter.GaussianBlur(size * 0.0012))


def bevel(img: Image.Image, inset: float, light: int = 90, dark: int = 110) -> Image.Image:
    """Фаска по краю: светлая сверху, тёмная снизу — даёт объём."""
    size = img.width
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    box = [inset, inset, size - inset, size - inset]
    width = max(2, int(size * 0.016))
    draw.arc(box, start=150, end=330, fill=(255, 255, 255, light), width=width)
    draw.arc(box, start=330, end=150, fill=(0, 0, 0, dark), width=width)
    layer = layer.filter(ImageFilter.GaussianBlur(size * 0.006))
    return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")


def sunk_button(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float,
                fill: tuple[int, int, int]) -> None:
    """Утопленная кнопка: тень сверху, мягкая подсветка снизу.

    Подсветка намеренно приглушена: чистый белый выглядит нарисованным,
    а не отражением света на пластике.
    """
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)
    draw.arc([cx - r, cy - r, cx + r, cy + r], start=150, end=330,
             fill=(0, 0, 0), width=max(2, int(r * 0.11)))
    highlight = tuple(min(255, int(v * 1.35) + 26) for v in fill)
    draw.arc([cx - r, cy - r, cx + r, cy + r], start=340, end=140,
             fill=highlight, width=max(1, int(r * 0.05)))


def sym_play(draw: ImageDraw.ImageDraw, cx: float, cy: float, s: float, color) -> None:
    draw.polygon([(cx - s * 0.42, cy - s * 0.62), (cx - s * 0.42, cy + s * 0.62),
                  (cx + s * 0.62, cy)], fill=color)


def sym_pause(draw: ImageDraw.ImageDraw, cx: float, cy: float, s: float, color) -> None:
    w = s * 0.26
    draw.rectangle([cx - s * 0.46, cy - s * 0.60, cx - s * 0.46 + w, cy + s * 0.60], fill=color)
    draw.rectangle([cx + s * 0.20, cy - s * 0.60, cx + s * 0.20 + w, cy + s * 0.60], fill=color)


def sym_prev(draw: ImageDraw.ImageDraw, cx: float, cy: float, s: float, color) -> None:
    for shift in (-0.34, 0.26):
        draw.polygon([(cx + s * (shift + 0.30), cy - s * 0.55),
                      (cx + s * (shift + 0.30), cy + s * 0.55),
                      (cx + s * shift, cy)], fill=color)
    draw.rectangle([cx - s * 0.62, cy - s * 0.55, cx - s * 0.52, cy + s * 0.55], fill=color)


def sym_next(draw: ImageDraw.ImageDraw, cx: float, cy: float, s: float, color) -> None:
    for shift in (-0.30, 0.30):
        draw.polygon([(cx + s * (shift - 0.30), cy - s * 0.55),
                      (cx + s * (shift - 0.30), cy + s * 0.55),
                      (cx + s * shift, cy)], fill=color)
    draw.rectangle([cx + s * 0.52, cy - s * 0.55, cx + s * 0.62, cy + s * 0.55], fill=color)


def sym_plus(draw: ImageDraw.ImageDraw, cx: float, cy: float, s: float, color) -> None:
    t = s * 0.22
    draw.rectangle([cx - s * 0.55, cy - t / 2, cx + s * 0.55, cy + t / 2], fill=color)
    draw.rectangle([cx - t / 2, cy - s * 0.55, cx + t / 2, cy + s * 0.55], fill=color)


def sym_minus(draw: ImageDraw.ImageDraw, cx: float, cy: float, s: float, color) -> None:
    t = s * 0.22
    draw.rectangle([cx - s * 0.55, cy - t / 2, cx + s * 0.55, cy + t / 2], fill=color)


def engraved(base: Image.Image, painter, cx: float, cy: float, s: float) -> Image.Image:
    """Гравировка: тёмный знак со светлой подсветкой снизу."""
    size = base.width
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    painter(d, cx, cy + s * 0.06, s, (255, 255, 255, 90))   # блик под знаком
    painter(d, cx, cy, s, (18, 18, 20, 235))                # сам знак
    return Image.alpha_composite(base.convert("RGBA"), layer).convert("RGB")


def build(size: int, base_color: tuple[int, int, int], ring_color: tuple[int, int, int],
          center_color: tuple[int, int, int], accent: tuple[int, int, int] | None) -> Image.Image:
    """Собирает панель: металл, фаска, четыре символа по кругу, центральная кнопка."""
    img = brushed_metal(size, base_color)
    c = size / 2

    # Внешний ободок корпуса
    draw = ImageDraw.Draw(img)
    draw.ellipse([1, 1, size - 2, size - 2], outline=ring_color, width=max(3, int(size * 0.022)))
    img = bevel(img, size * 0.012)

    # Символы управления по четырём сторонам
    radius = size * 0.335
    glyph = size * 0.088
    positions = {
        sym_prev: (c - radius, c),
        sym_next: (c + radius, c),
        sym_plus: (c, c - radius),
        sym_minus: (c, c + radius),
    }
    for painter, (x, y) in positions.items():
        img = engraved(img, painter, x, y, glyph)

    # Центральная кнопка: воспроизведение и пауза рядом
    draw = ImageDraw.Draw(img)
    hub = size * 0.20
    sunk_button(draw, c, c, hub, center_color)

    inner = brushed_metal(size, center_color, contrast=10)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([c - hub * 0.94, c - hub * 0.94, c + hub * 0.94, c + hub * 0.94],
                                 fill=255)
    img.paste(inner, (0, 0), mask)

    # Тонкая тень по верхнему краю кнопки — она сидит в углублении
    draw = ImageDraw.Draw(img)
    shade = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(shade).arc(
        [c - hub, c - hub, c + hub, c + hub], start=150, end=330,
        fill=(0, 0, 0, 190), width=max(2, int(size * 0.009)),
    )
    shade = shade.filter(ImageFilter.GaussianBlur(size * 0.004))
    img = Image.alpha_composite(img.convert("RGBA"), shade).convert("RGB")

    img = engraved(img, sym_play, c - size * 0.052, c, size * 0.062)
    img = engraved(img, sym_pause, c + size * 0.055, c, size * 0.062)

    # Точка индикатора — деталь, которая делает панель «живой»
    if accent:
        draw = ImageDraw.Draw(img)
        led = size * 0.020
        lx, ly = c + radius * 0.72, c - radius * 0.72
        draw.ellipse([lx - led, ly - led, lx + led, ly + led], fill=accent)
        glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        ImageDraw.Draw(glow).ellipse(
            [lx - led * 2.6, ly - led * 2.6, lx + led * 2.6, ly + led * 2.6],
            fill=(*accent, 70),
        )
        glow = glow.filter(ImageFilter.GaussianBlur(size * 0.012))
        img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")

    return img


def variant_silver(size: int) -> Image.Image:
    """Шлифованный алюминий — панель музыкального центра."""
    return build(size, (168, 170, 174), (96, 98, 102), (150, 152, 156), (226, 74, 58))


def variant_graphite(size: int) -> Image.Image:
    """Тёмный графит с красным индикатором."""
    return build(size, (58, 58, 62), (26, 26, 29), (44, 44, 48), (232, 66, 52))


def variant_cream(size: int) -> Image.Image:
    """Кремовый пластик — кассетник из девяностых."""
    return build(size, (208, 198, 178), (128, 118, 100), (192, 182, 162), (196, 58, 44))


def main() -> int:
    parser = argparse.ArgumentParser(description="Аватарка-панель управления плеером")
    parser.add_argument("--size", type=int, default=1000)
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    variants = {
        "panel-1-silver": variant_silver,
        "panel-2-graphite": variant_graphite,
        "panel-3-cream": variant_cream,
    }
    for name, builder in variants.items():
        path = OUT_DIR / f"avatar-{name}.png"
        builder(args.size).save(path, "PNG")
        print(f"  ✓ {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
