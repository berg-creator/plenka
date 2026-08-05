"""Истории ВКонтакте: рисуем карточку из поста и публикуем.

Истории живут сутки и показываются вверху ленты — это самый заметный
формат в сообществе, поэтому в них уходит короткая выжимка поста.

Ограничение платформы: **упоминания людей через API не ставятся**.
ВКонтакте позволяет отмечать в историях только вручную из приложения.
Зато в обычных постах упоминания работают — см. src/vk.py.

    python -m src.stories --preview     нарисовать карточку, не публикуя
    python -m src.stories --publish      нарисовать и опубликовать
"""

from __future__ import annotations

import argparse
import random
import re
import textwrap
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import config, state, vk

# Вертикальный формат историй.
WIDTH, HEIGHT = 1080, 1920

CREAM = (208, 198, 178)
INK = (34, 31, 28)
ACCENT = (196, 58, 44)

OUT_DIR = config.ROOT / "assets" / "stories"

FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Black.ttf",
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


def strip_html(text: str) -> str:
    """Убирает разметку. Ссылки вырезаются целиком: в истории они не кликаются."""
    text = re.sub(r'<a\s+href="[^"]*"[^>]*>.*?</a>', "", text, flags=re.DOTALL | re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# История живёт секунды: длинный текст в ней не читают.
STORY_LIMIT = 240


def shorten(text: str, limit: int = STORY_LIMIT) -> str:
    """Оставляет от поста ровно столько, сколько успевают прочитать.

    Режем по границе предложения, а не по символам: обрубленная фраза
    выглядит как ошибка вёрстки.
    """
    text = strip_html(text)
    if len(text) <= limit:
        return text

    sentences = re.split(r"(?<=[.!?])\s+", text)
    result = ""
    for sentence in sentences:
        if len(result) + len(sentence) + 1 > limit:
            break
        result = f"{result} {sentence}".strip()

    return result or text[:limit].rsplit(" ", 1)[0] + "…"


def background() -> Image.Image:
    """Кремовый пластик с фактурой — тот же материал, что у аватарки."""
    img = Image.new("RGB", (WIDTH, HEIGHT), CREAM)
    draw = ImageDraw.Draw(img)
    random.seed(42)
    for y in range(HEIGHT):
        delta = random.randint(-6, 6)
        draw.line([(0, y), (WIDTH, y)],
                  fill=tuple(max(0, min(255, CREAM[i] + delta)) for i in range(3)))
    for _ in range(1200):
        x, y = random.uniform(0, WIDTH), random.uniform(0, HEIGHT)
        length = random.uniform(30, 160)
        delta = random.randint(-9, 9)
        draw.line([(x, y), (x + length, y)],
                  fill=tuple(max(0, min(255, CREAM[i] + delta)) for i in range(3)), width=1)
    return img.filter(ImageFilter.GaussianBlur(0.4))


def render(text: str, rubric_title: str = "") -> Image.Image:
    """Собирает карточку: плашка рубрики, текст, подпись канала."""
    img = background()
    draw = ImageDraw.Draw(img)

    margin = int(WIDTH * 0.10)
    y = int(HEIGHT * 0.16)

    # Плашка с названием рубрики
    if rubric_title:
        f = font(38)
        box = draw.textbbox((0, 0), rubric_title, font=f)
        pad = 22
        draw.rectangle([margin, y, margin + box[2] + pad * 2, y + box[3] + pad * 1.4],
                       fill=ACCENT)
        draw.text((margin + pad, y + pad * 0.55), rubric_title, font=f, fill=(255, 255, 255))
        y += box[3] + pad * 3

    # Основной текст: кегль подбирается так, чтобы влезть без обрезки
    body = shorten(text)
    for size, per_line in ((78, 21), (68, 24), (60, 28), (52, 32), (44, 38)):
        f = font(size)
        lines: list[str] = []
        for paragraph in body.split("\n"):
            lines.extend(textwrap.wrap(paragraph, width=per_line) or [""])
        height = len(lines) * size * 1.42
        if y + height < HEIGHT * 0.82:
            break

    for line in lines:
        draw.text((margin, y), line, font=f, fill=INK)
        y += size * 1.42

    # Подпись канала внизу
    footer = font(40)
    label = "ПЛЁНКА"
    fbox = draw.textbbox((0, 0), label, font=footer)
    fy = HEIGHT - int(HEIGHT * 0.085)
    draw.text((margin, fy), label, font=footer, fill=INK)
    draw.rectangle([margin, fy - 18, margin + fbox[2], fy - 10], fill=ACCENT)

    return img


def publish(image_path: Path) -> str:
    """Загружает картинку и публикует историю от имени сообщества."""
    gid = vk.group_id()
    server = vk._call("stories.getPhotoUploadServer", add_to_news=1, group_id=gid)

    with image_path.open("rb") as handle:
        uploaded = requests.post(
            server["upload_url"], files={"file": ("story.jpg", handle, "image/jpeg")}, timeout=90
        ).json()

    if "response" not in uploaded and "upload_result" not in uploaded:
        raise vk.VKError(f"загрузка не удалась: {str(uploaded)[:200]}")

    result = vk._call("stories.save", upload_results=uploaded.get("response", uploaded).get(
        "upload_result", uploaded.get("upload_result", "")
    ))
    items = result.get("items", [])
    return str(items[0].get("id", "")) if items else "опубликовано"


def latest_post() -> dict | None:
    """Берёт свежий пост из очереди — для истории годится тот же материал."""
    posts = sorted(config.QUEUE.glob("*.json"))
    if not posts:
        return None
    return state.read_json(posts[0], {})


def main() -> int:
    parser = argparse.ArgumentParser(description="Истории ВКонтакте")
    parser.add_argument("--preview", action="store_true", help="только нарисовать карточку")
    parser.add_argument("--publish", action="store_true", help="нарисовать и опубликовать")
    parser.add_argument("--text", help="произвольный текст вместо поста из очереди")
    args = parser.parse_args()

    config.load_dotenv()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.text:
        text, title = args.text, ""
    else:
        post = latest_post()
        if not post:
            print("Очередь пуста — нечего показывать.")
            return 0
        text = post.get("text", "")
        rubric = config.RUBRIC_BY_KEY.get(post.get("rubric", ""))
        title = rubric.title if rubric else ""

    card = render(text, title)
    path = OUT_DIR / "story.jpg"
    card.convert("RGB").save(path, "JPEG", quality=92)
    print(f"Карточка готова: {path.relative_to(config.ROOT)} ({card.width}×{card.height})")

    if args.publish:
        try:
            story_id = publish(path)
            print(f"История опубликована: {story_id}")
        except Exception as exc:
            print(f"Не удалось опубликовать: {exc}")
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
