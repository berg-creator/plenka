"""Шапка сообщества ВКонтакте в стиле выбранной аватарки.

Композиция — передняя панель кассетника: слева окно с катушками, по центру
название, справа кнопки управления и шкала уровня. Материал тот же, что
у аватарки: кремовый пластик со шлифовкой.

ВКонтакте показывает обложку размером 1590×400, но на телефонах края
срезаются, поэтому всё значимое держится в центральной части.

    python -m src.make_cover
"""

from __future__ import annotations

import argparse
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT_DIR = Path(__file__).resolve().parent.parent / "assets" / "avatar"

WIDTH, HEIGHT = 1590, 400
# На мобильных видна примерно центральная треть — за её пределы ничего важного.
SAFE_LEFT, SAFE_RIGHT = 0.22, 0.78

CREAM = (208, 198, 178)
CREAM_DARK = (128, 118, 100)
INK = (34, 31, 28)
ACCENT = (196, 58, 44)
TAPE_DARK = (58, 40, 28)
TAPE_MID = (96, 66, 42)

FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial Black.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
)


def font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            try:
                f = ImageFont.truetype(path, size)
                if f.getbbox("Ё")[2] > 0:
                    return f
            except OSError:
                continue
    return ImageFont.load_default(size)


def brushed(width: int, height: int, base: tuple[int, int, int]) -> Image.Image:
    """Горизонтальная шлифовка — на плоской панели она идёт вдоль."""
    img = Image.new("RGB", (width, height), base)
    draw = ImageDraw.Draw(img)
    random.seed(1990)
    for y in range(height):
        delta = random.randint(-7, 7)
        color = tuple(max(0, min(255, base[i] + delta)) for i in range(3))
        draw.line([(0, y), (width, y)], fill=color)
    for _ in range(900):
        x = random.uniform(0, width)
        y = random.uniform(0, height)
        length = random.uniform(20, 130)
        delta = random.randint(-10, 10)
        color = tuple(max(0, min(255, base[i] + delta)) for i in range(3))
        draw.line([(x, y), (x + length, y)], fill=color, width=1)
    return img.filter(ImageFilter.GaussianBlur(0.4))


def reel(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, fill_ratio: float) -> None:
    """Катушка с намотанной лентой."""
    outer = r * (0.55 + fill_ratio * 0.45)
    for i in range(18):
        rr = outer * (1 - i / 18 * 0.62)
        draw.ellipse([cx - rr, cy - rr, cx + rr, cy + rr],
                     outline=TAPE_MID if i % 2 else TAPE_DARK, width=3)
    hub = r * 0.26
    draw.ellipse([cx - hub, cy - hub, cx + hub, cy + hub], fill=(214, 210, 200))
    for i in range(6):
        a = 2 * math.pi * i / 6 - math.pi / 2
        x = cx + math.cos(a) * hub * 0.5
        y = cy + math.sin(a) * hub * 0.5
        t = hub * 0.30
        draw.polygon(
            [
                (x + math.cos(a) * t * 1.7, y + math.sin(a) * t * 1.7),
                (x + math.cos(a + 2.2) * t, y + math.sin(a + 2.2) * t),
                (x + math.cos(a - 2.2) * t, y + math.sin(a - 2.2) * t),
            ],
            fill=(40, 36, 32),
        )
    hole = hub * 0.34
    draw.ellipse([cx - hole, cy - hole, cx + hole, cy + hole], fill=(40, 36, 32))


def build(width: int = WIDTH, height: int = HEIGHT, *, with_slogan: bool = True) -> Image.Image:
    img = brushed(width, height, CREAM)
    draw = ImageDraw.Draw(img)

    # Верхняя и нижняя кромки корпуса — панель должна выглядеть отлитой
    draw.rectangle([0, 0, width, 4], fill=(232, 224, 208))
    draw.rectangle([0, height - 6, width, height], fill=(150, 140, 122))

    cx = width / 2

    # ── Название по центру ──
    title = font(int(height * 0.40))
    box = draw.textbbox((0, 0), "ПЛЁНКА", font=title)
    tx = cx - box[2] / 2 - box[0]
    ty = height * (0.26 if with_slogan else 0.30) - box[1]

    # Гравировка: тень вниз, затем сам знак
    draw.text((tx + 3, ty + 3), "ПЛЁНКА", font=title, fill=(236, 228, 212))
    draw.text((tx, ty), "ПЛЁНКА", font=title, fill=INK)

    if with_slogan:
        sub = font(int(height * 0.085))
        text = "ОТКУДА ВЗЯЛСЯ ВЕСЬ ЭТОТ ЗВУК"
        sbox = draw.textbbox((0, 0), text, font=sub)
        # Разрядка делает подпись похожей на трафаретную печать по корпусу
        draw.text((cx - sbox[2] / 2 - sbox[0], height * 0.70), text, font=sub,
                  fill=(96, 88, 76))

    # ── Окно с катушками слева ──
    win_left, win_right = width * 0.055, width * 0.215
    draw.rounded_rectangle([win_left, height * 0.28, win_right, height * 0.72],
                           radius=10, fill=(52, 47, 42), outline=(150, 140, 122), width=3)
    reel(draw, win_left + (win_right - win_left) * 0.30, height * 0.50, height * 0.15, 0.35)
    reel(draw, win_left + (win_right - win_left) * 0.70, height * 0.50, height * 0.15, 0.85)

    # ── Кнопки управления справа ──
    bx = width * 0.790
    by = height * 0.50
    gap = width * 0.042
    size = height * 0.135

    def triangle(x: float, flip: bool) -> None:
        d = -1 if flip else 1
        draw.polygon(
            [(x - size * 0.4 * d, by - size * 0.55), (x - size * 0.4 * d, by + size * 0.55),
             (x + size * 0.5 * d, by)],
            fill=INK,
        )

    triangle(bx, True)
    triangle(bx + gap * 0.55, True)
    draw.rectangle([bx + gap * 1.15, by - size * 0.55, bx + gap * 1.15 + size * 0.22,
                    by + size * 0.55], fill=INK)
    draw.rectangle([bx + gap * 1.15 + size * 0.42, by - size * 0.55,
                    bx + gap * 1.15 + size * 0.64, by + size * 0.55], fill=INK)
    triangle(bx + gap * 2.1, False)
    triangle(bx + gap * 2.65, False)

    # Красный огонёк записи
    led = height * 0.030
    lx, ly = width * 0.945, height * 0.30
    draw.ellipse([lx - led, ly - led, lx + led, ly + led], fill=ACCENT)
    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse(
        [lx - led * 3, ly - led * 3, lx + led * 3, ly + led * 3], fill=(*ACCENT, 70)
    )
    img = Image.alpha_composite(img.convert("RGBA"), glow.filter(ImageFilter.GaussianBlur(9))
                                ).convert("RGB")
    draw = ImageDraw.Draw(img)

    # ── Шкала уровня справа снизу ──
    x = width * 0.790
    y = height * 0.755
    for i in range(16):
        lit = i < 10
        color = (54, 158, 78) if i < 8 else ((206, 156, 36) if i < 12 else ACCENT)
        if not lit:
            # Погашенные сегменты — тёмные, а не выбеленные: так шкала читается
            color = tuple(int(v * 0.30 + 96) for v in color)
        draw.rectangle([x, y, x + width * 0.0085, y + height * 0.075], fill=color)
        x += width * 0.0118

    return img


def build_minimal(width: int = WIDTH, height: int = HEIGHT) -> Image.Image:
    """Минималистичный вариант: только фактура, название и красная черта.

    Спокойнее предыдущего и не спорит с аватаркой, на которой уже много деталей.
    """
    img = brushed(width, height, CREAM)
    draw = ImageDraw.Draw(img)
    cx = width / 2

    draw.rectangle([0, 0, width, 4], fill=(232, 224, 208))
    draw.rectangle([0, height - 6, width, height], fill=(150, 140, 122))

    title = font(int(height * 0.34))
    box = draw.textbbox((0, 0), "ПЛЁНКА", font=title)
    tx = cx - box[2] / 2 - box[0]
    ty = height * 0.30 - box[1]
    draw.text((tx + 3, ty + 3), "ПЛЁНКА", font=title, fill=(236, 228, 212))
    draw.text((tx, ty), "ПЛЁНКА", font=title, fill=INK)

    # Красная черта под названием — единственный акцент
    line_w = box[2] * 0.62
    ly = height * 0.685
    draw.rectangle([cx - line_w / 2, ly, cx + line_w / 2, ly + height * 0.022], fill=ACCENT)

    sub = font(int(height * 0.078))
    text = "ОТКУДА ВЗЯЛСЯ ВЕСЬ ЭТОТ ЗВУК"
    sbox = draw.textbbox((0, 0), text, font=sub)
    draw.text((cx - sbox[2] / 2 - sbox[0], height * 0.77), text, font=sub, fill=(104, 96, 82))

    return img


def main() -> int:
    parser = argparse.ArgumentParser(description="Шапка сообщества ВКонтакте")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    variants = {
        "cover-vk-1-panel.png": lambda: build(with_slogan=True),
        "cover-vk-2-plain.png": lambda: build(with_slogan=False),
        "cover-vk-3-minimal.png": build_minimal,
    }
    for name, builder in variants.items():
        image = builder()
        image.save(OUT_DIR / name, "PNG")
        print(f"  ✓ {name} — {image.width}×{image.height}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
