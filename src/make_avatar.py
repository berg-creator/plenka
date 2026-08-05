"""Генератор аватарки канала.

Рисуется кодом, а не в редакторе: так вариант можно переделать одной командой,
а не искать дизайнера ради смены оттенка.

    python -m src.make_avatar            собрать все варианты
    python -m src.make_avatar --size 500 другой размер

Результат кладётся в assets/avatar/. Подходит и для Telegram, и для ВКонтакте.
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT_DIR = Path(__file__).resolve().parent.parent / "assets" / "avatar"

# Системные шрифты macOS, от жирных к обычным.
FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Impact.ttf",
    "/System/Library/Fonts/Supplemental/Arial Black.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
)


def load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            try:
                font = ImageFont.truetype(path, size)
                # Проверяем, что шрифт умеет кириллицу: Impact её не содержит.
                if font.getbbox("Ё")[2] > 0:
                    return font
            except OSError:
                continue
    return ImageFont.load_default(size)


def add_grain(image: Image.Image, strength: int = 26) -> Image.Image:
    """Плёночное зерно — то самое шипение кассеты, только визуальное."""
    noise = Image.new("L", image.size)
    noise.putdata([random.randint(0, strength) for _ in range(image.width * image.height)])
    noise = noise.filter(ImageFilter.GaussianBlur(0.4))
    return Image.composite(
        Image.new("RGB", image.size, (255, 255, 255)), image, noise.point(lambda v: v // 8)
    )


# Telegram и ВКонтакте обрезают аватарку в круг, поэтому надпись должна
# укладываться в безопасную зону, иначе у крайних букв срежет края.
SAFE_ZONE = 0.66


def fit_text(draw: ImageDraw.ImageDraw, text: str, box: int) -> ImageFont.FreeTypeFont:
    """Подбирает кегль так, чтобы надпись целиком помещалась в круг."""
    size = box
    while size > 10:
        font = load_font(size)
        width = draw.textbbox((0, 0), text, font=font)[2]
        if width <= box * SAFE_ZONE:
            return font
        size -= 4
    return load_font(12)


def variant_tape(size: int) -> Image.Image:
    """Тёмный вариант: белая надпись на чёрном, зерно, красная полоса."""
    img = Image.new("RGB", (size, size), (11, 11, 12))
    draw = ImageDraw.Draw(img)

    font = fit_text(draw, "ПЛЁНКА", size)
    box = draw.textbbox((0, 0), "ПЛЁНКА", font=font)
    x = (size - box[2]) / 2 - box[0]
    y = (size - box[3]) / 2 - box[1]

    # Лёгкий красный сдвиг под соседним слоем — эффект расслоения VHS.
    draw.text((x + size * 0.008, y), "ПЛЁНКА", font=font, fill=(190, 30, 30))
    draw.text((x, y), "ПЛЁНКА", font=font, fill=(238, 238, 234))

    bar = int(size * 0.028)
    draw.rectangle([0, size - bar * 3, size, size - bar * 2], fill=(190, 30, 30))

    return add_grain(img)


def variant_light(size: int) -> Image.Image:
    """Светлый вариант: чёрная надпись на выцветшей бумаге."""
    img = Image.new("RGB", (size, size), (222, 216, 202))
    draw = ImageDraw.Draw(img)

    font = fit_text(draw, "ПЛЁНКА", size)
    box = draw.textbbox((0, 0), "ПЛЁНКА", font=font)
    x = (size - box[2]) / 2 - box[0]
    y = (size - box[3]) / 2 - box[1]

    draw.text((x, y), "ПЛЁНКА", font=font, fill=(24, 22, 20))

    bar = int(size * 0.03)
    draw.rectangle([size * 0.12, y + box[3] + bar, size * 0.88, y + box[3] + bar * 1.6],
                   fill=(24, 22, 20))

    return add_grain(img, strength=18)


def variant_reel(size: int) -> Image.Image:
    """Катушка: круг с отверстием, надпись по нижнему краю."""
    img = Image.new("RGB", (size, size), (14, 13, 15))
    draw = ImageDraw.Draw(img)

    center = size / 2
    for radius, color in (
        (size * 0.40, (32, 30, 34)),
        (size * 0.30, (20, 19, 22)),
        (size * 0.13, (198, 34, 34)),
        (size * 0.05, (14, 13, 15)),
    ):
        draw.ellipse(
            [center - radius, center - radius, center + radius, center + radius], fill=color
        )

    # Надпись ложится на катушку по центру: в круге низ обрезается.
    font = load_font(int(size * 0.155))
    box = draw.textbbox((0, 0), "ПЛЁНКА", font=font)
    draw.text(
        ((size - box[2]) / 2 - box[0], (size - box[3]) / 2 - box[1] + size * 0.30),
        "ПЛЁНКА",
        font=font,
        fill=(238, 238, 234),
    )

    return add_grain(img)


def main() -> int:
    parser = argparse.ArgumentParser(description="Генератор аватарки канала")
    parser.add_argument("--size", type=int, default=1000, help="сторона квадрата в пикселях")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    random.seed(7)  # одинаковое зерно при каждом запуске — результат воспроизводим

    variants = {
        "1-tape": variant_tape,
        "2-light": variant_light,
        "3-reel": variant_reel,
    }

    for name, builder in variants.items():
        path = OUT_DIR / f"avatar-{name}.png"
        builder(args.size).save(path, "PNG")
        print(f"  ✓ {path.relative_to(OUT_DIR.parent.parent)}")

    print(f"\nГотово. Размер: {args.size}×{args.size}. Файлы в {OUT_DIR.name}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
