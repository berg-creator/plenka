"""Аватарки-обманки на тему плёнки.

Здесь обман и название канала — одно и то же. Дефект плёнки выглядит как
поломка устройства: царапина на киноплёнке неотличима от царапины на экране,
помехи VHS — от сбоя картинки. Человек тянется протереть экран или обновить,
а потом понимает, что это и есть «Плёнка».

    python -m src.make_avatar_film
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
    "/System/Library/Fonts/Supplemental/Arial Black.ttf",
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


def grain(img: Image.Image, strength: int = 18) -> Image.Image:
    noise = Image.new("L", img.size)
    noise.putdata([random.randint(0, strength) for _ in range(img.width * img.height)])
    noise = noise.filter(ImageFilter.GaussianBlur(0.4))
    return Image.composite(
        Image.new("RGB", img.size, (255, 255, 255)), img, noise.point(lambda v: v // 9)
    )


def variant_scratch(size: int) -> Image.Image:
    """Царапина на плёнке — она же царапина на экране.

    Вертикальная дрожащая линия, как на затёртой киноплёнке. В списке чатов
    читается как дефект дисплея, и рука сама тянется протереть.
    """
    img = Image.new("RGB", (size, size), (17, 16, 18))
    draw = ImageDraw.Draw(img)
    random.seed(11)

    # Основная царапина: почти вертикальная, с лёгким дрожанием по горизонтали
    x = size * 0.44
    prev = (x, 0.0)
    for y in range(0, size, 4):
        x += random.uniform(-0.9, 0.9)
        point = (x, float(y))
        draw.line([prev, point], fill=(232, 228, 220), width=max(2, int(size * 0.006)))
        prev = point

    # Вторая, слабее и короче — так бывает на реальной плёнке
    x2 = size * 0.63
    prev = (x2, size * 0.18)
    for y in range(int(size * 0.18), int(size * 0.86), 4):
        x2 += random.uniform(-0.7, 0.7)
        point = (x2, float(y))
        draw.line([prev, point], fill=(120, 117, 112), width=max(1, int(size * 0.003)))
        prev = point

    # Пылинки и точечные выпадения
    for _ in range(26):
        px = random.uniform(size * 0.15, size * 0.85)
        py = random.uniform(size * 0.15, size * 0.85)
        r = random.uniform(size * 0.002, size * 0.005)
        shade = random.choice([(210, 206, 199), (60, 58, 56)])
        draw.ellipse([px - r, py - r, px + r, py + r], fill=shade)

    return grain(img, 22)


def variant_vhs(size: int) -> Image.Image:
    """Помехи VHS: полосы трекинга и расслоение цвета.

    Выглядит как сбой изображения — кажется, что аватарка не прогрузилась
    или экран барахлит.
    """
    img = Image.new("RGB", (size, size), (18, 17, 20))
    draw = ImageDraw.Draw(img)
    random.seed(5)

    # Мягкие горизонтальные полосы развёртки
    for y in range(0, size, max(2, int(size * 0.012))):
        shade = random.randint(22, 34)
        draw.line([(0, y), (size, y)], fill=(shade, shade, shade + 3), width=1)

    # Полосы трекинга — рваные светлые ленты со смещением
    for _ in range(4):
        y = random.uniform(size * 0.2, size * 0.8)
        height = random.uniform(size * 0.03, size * 0.075)
        offset = random.uniform(-size * 0.05, size * 0.05)
        draw.rectangle([offset, y, size + offset, y + height], fill=(196, 192, 186))
        # Цветное расслоение по краям ленты
        draw.rectangle([offset - size * 0.012, y, size + offset, y + height * 0.28],
                       fill=(206, 60, 60))
        draw.rectangle([offset + size * 0.012, y + height * 0.72, size + offset, y + height],
                       fill=(60, 120, 206))

    # Тонкие обрывки шума
    for _ in range(40):
        y = random.uniform(0, size)
        x1 = random.uniform(0, size * 0.8)
        w = random.uniform(size * 0.02, size * 0.2)
        shade = random.randint(90, 190)
        draw.line([(x1, y), (x1 + w, y)], fill=(shade, shade, shade), width=max(1, int(size * 0.004)))

    return grain(img, 26)


def variant_chewed(size: int) -> Image.Image:
    """Зажевало ленту — как кассету в магнитофоне.

    Смятая петля магнитной ленты. Читается как «что-то сломалось».
    """
    img = Image.new("RGB", (size, size), (16, 15, 17))
    draw = ImageDraw.Draw(img)
    random.seed(21)

    center = size / 2
    # Несколько перепутанных петель ленты
    for i in range(5):
        radius = size * (0.13 + i * 0.055)
        squash = random.uniform(0.35, 0.72)
        angle = random.uniform(-0.5, 0.5)
        box = [
            center - radius,
            center - radius * squash,
            center + radius,
            center + radius * squash,
        ]
        loop = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        ldraw = ImageDraw.Draw(loop)
        shade = 150 - i * 16
        ldraw.ellipse(box, outline=(shade, shade - 4, shade - 8, 255),
                      width=max(3, int(size * 0.022)))
        loop = loop.rotate(math.degrees(angle), center=(center, center))
        img.paste(loop, (0, 0), loop)

    # Блик на ленте — она глянцевая
    draw = ImageDraw.Draw(img)
    draw.arc(
        [center - size * 0.30, center - size * 0.17, center + size * 0.30, center + size * 0.17],
        start=190, end=250, fill=(226, 222, 214), width=max(2, int(size * 0.01)),
    )

    return grain(img, 16)


def variant_leader(size: int) -> Image.Image:
    """Ракорд — круглый лидер киноплёнки с цифрой обратного отсчёта.

    Идеально ложится в круглую аватарку и притворяется индикатором загрузки
    или прицелом.
    """
    img = Image.new("RGB", (size, size), (198, 192, 178))
    draw = ImageDraw.Draw(img)
    center = size / 2

    # Затемнённый сектор, как на настоящем ракорде
    draw.pieslice([0, 0, size, size], start=-90, end=80, fill=(168, 162, 150))

    # Концентрические круги
    for radius, width in ((size * 0.44, 0.012), (size * 0.33, 0.009), (size * 0.20, 0.007)):
        draw.ellipse(
            [center - radius, center - radius, center + radius, center + radius],
            outline=(38, 36, 34), width=max(2, int(size * width)),
        )

    # Перекрестие
    draw.line([(center, 0), (center, size)], fill=(38, 36, 34), width=max(2, int(size * 0.009)))
    draw.line([(0, center), (size, center)], fill=(38, 36, 34), width=max(2, int(size * 0.009)))

    # Цифра отсчёта
    f = font(int(size * 0.30))
    box = draw.textbbox((0, 0), "3", font=f)
    draw.text(
        ((size - box[2]) / 2 - box[0], (size - box[3]) / 2 - box[1]),
        "3", font=f, fill=(30, 28, 26),
    )

    return grain(img, 20)


def main() -> int:
    parser = argparse.ArgumentParser(description="Аватарки-обманки на тему плёнки")
    parser.add_argument("--size", type=int, default=1000)
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    variants = {
        "film-1-scratch": variant_scratch,
        "film-2-vhs": variant_vhs,
        "film-3-chewed": variant_chewed,
        "film-4-leader": variant_leader,
    }
    for name, builder in variants.items():
        path = OUT_DIR / f"avatar-{name}.png"
        builder(args.size).save(path, "PNG")
        print(f"  ✓ {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
