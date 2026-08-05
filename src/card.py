"""Карточка разбора вкуса — то, что человек пересылает друзьям.

Ради этой картинки всё и затевалось: текстовый ответ бота остаётся в личке,
а карточка уходит в чужие сторис вместе с подписью канала. Материал и цвета
те же, что у аватарки и историй ВКонтакте, — сервис должен выглядеть частью
канала, а не отдельной поделкой.

    python -m src.card --preview    нарисовать пробную карточку
"""

from __future__ import annotations

import argparse
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw

from . import config, stories

# Вертикаль 4:5 — формат, который Telegram и ВКонтакте показывают крупно
# и не режут в ленте.
WIDTH, HEIGHT = 1080, 1350

OUT_DIR = config.ROOT / "assets" / "cards"

# Больше шести имён карточка не вмещает, а мелкий шрифт в ленте не читается.
MAX_ARTISTS = 6


def _fit(draw: ImageDraw.ImageDraw, text: str, limit: int, sizes: tuple[tuple[int, int], ...]):
    """Подбирает кегль так, чтобы блок влез в отведённую высоту."""
    for size, per_line in sizes:
        f = stories.font(size)
        lines = textwrap.wrap(text, width=per_line)
        if len(lines) * size * 1.34 <= limit:
            return f, lines, size
    f = stories.font(sizes[-1][0])
    return f, textwrap.wrap(text, width=sizes[-1][1])[:6], sizes[-1][0]


def render(verdict: str, artists: list[str], *, label: str = "ПРОЯВКА") -> Image.Image:
    """Карточка: плашка рубрики, список артистов, приговор вкусу, подпись канала."""
    img = stories.background(WIDTH, HEIGHT)
    draw = ImageDraw.Draw(img)

    margin = int(WIDTH * 0.10)
    y = int(HEIGHT * 0.10)

    # Плашка сверху
    plate = stories.font(40)
    box = draw.textbbox((0, 0), label, font=plate)
    pad = 20
    draw.rectangle(
        [margin, y, margin + box[2] + pad * 2, y + box[3] + pad * 1.5], fill=stories.ACCENT
    )
    draw.text((margin + pad, y + pad * 0.6), label, font=plate, fill=(255, 255, 255))
    y += box[3] + pad * 3.4

    # Кого прислали. Список — повод узнать себя в чужой карточке.
    if artists:
        shown = ", ".join(artists[:MAX_ARTISTS])
        if len(artists) > MAX_ARTISTS:
            shown += f" и ещё {len(artists) - MAX_ARTISTS}"
        f, lines, size = _fit(draw, shown, HEIGHT * 0.16, ((36, 42), (32, 48), (28, 56)))
        for line in lines[:4]:
            draw.text((margin, y), line, font=f, fill=(110, 100, 86))
            y += size * 1.34
        y += int(HEIGHT * 0.035)

    # Приговор — главное на карточке. Короткая фраза не должна прижиматься
    # к списку артистов, поэтому блок центрируется в оставшемся поле.
    bottom = HEIGHT * 0.84
    f, lines, size = _fit(
        draw, verdict, bottom - y, ((76, 19), (66, 22), (58, 26), (50, 30), (42, 36))
    )
    block = len(lines) * size * 1.34
    y += max(0, (bottom - y - block) / 2)

    for line in lines:
        draw.text((margin, y), line, font=f, fill=stories.INK)
        y += size * 1.34

    # Подпись канала внизу
    footer = stories.font(38)
    fy = HEIGHT - int(HEIGHT * 0.085)
    draw.rectangle([margin, fy - 16, margin + 96, fy - 8], fill=stories.ACCENT)
    draw.text((margin, fy), "ПЛЁНКА", font=footer, fill=stories.INK)

    handle = "@plenka_fm"
    hbox = draw.textbbox((0, 0), handle, font=footer)
    draw.text((WIDTH - margin - hbox[2], fy), handle, font=footer, fill=(110, 100, 86))

    return img


def save(verdict: str, artists: list[str], *, label: str = "ПРОЯВКА", name: str = "card") -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{name}.jpg"
    render(verdict, artists, label=label).convert("RGB").save(path, "JPEG", quality=90)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Карточка разбора вкуса")
    parser.add_argument("--verdict", default="ты слушаешь Мемфис через три пересадки и не знал")
    parser.add_argument("--artists", default="Bones, Sematary, Slipknot, Bladee, PHARAOH")
    args = parser.parse_args()

    path = save(args.verdict, [a.strip() for a in args.artists.split(",") if a.strip()])
    print(f"Карточка готова: {path.relative_to(config.ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
