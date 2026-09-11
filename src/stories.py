"""Истории ВКонтакте: рисуем карточку из поста и публикуем.

Истории живут сутки и показываются вверху ленты — это самый заметный
формат в сообществе, поэтому в них уходит короткая выжимка поста.

Ограничение платформы: **упоминания людей через API не ставятся**.
ВКонтакте позволяет отмечать в историях только вручную из приложения.
Зато в обычных постах упоминания работают — см. src/vk.py.

Выходит раз в сутки по расписанию (.github/workflows/stories.yml). Показанные
посты запоминаются в data/stories.json: голова очереди меняется медленнее,
чем выходят истории, и без этой отметки одна карточка крутилась бы неделю.

    python -m src.stories --preview     нарисовать карточку, не публикуя
    python -m src.stories --publish      нарисовать и опубликовать
"""

from __future__ import annotations

import argparse
import random
import re
import textwrap
from functools import lru_cache
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import config, state, vk

# Вертикальный формат историй.
WIDTH, HEIGHT = 1080, 1920

# Нижняя часть вертикального кадра занята интерфейсом площадки: подпись,
# аватарка, кнопки. У Reels, Shorts, VK Клипов и историй эта полоса разной
# высоты, но 380 пикселей перекрывают худший случай. Ничего своего ниже
# этой черты не рисуем — иначе подпись канала уезжает под чужие кнопки.
SAFE_BOTTOM = 380

# Поле и вертикальный ритм — общие для всех поверхностей канала:
# истории, карточки бота, кадры клипов свёрстаны по одной сетке.
MARGIN = int(WIDTH * 0.078)
MARK_Y = HEIGHT - SAFE_BOTTOM - 62

CREAM = (208, 198, 178)
INK = (26, 23, 20)
ACCENT = (196, 58, 44)
# Текст поверх фотографии. Не белый: чистый белый на затёртой картинке
# выглядит наклейкой поверх видео, а не частью кадра.
LIGHT = (239, 234, 224)
MUTED = (146, 138, 126)

OUT_DIR = config.ROOT / "assets" / "stories"

# Шрифты лежат в репозитории, а не берутся из системы. Раньше на macOS
# рисовалось Arial, а на раннере GitHub Actions — Liberation Sans, и вёрстка,
# подобранная глазами локально, в автопубликации разъезжалась. Плюс Arial —
# главная примета сгенерированной картинки: его ставят по умолчанию все.
#
# Oswald — узкий гротеск: длинное русское слово влезает в строку целиком
# на ширине 1080, ради этого он и выбран. Golos Text — читаемый текст
# с родной кириллицей. Оба переменные, поэтому вес задаётся числом,
# а не отдельным файлом на каждое начертание.
FONTS = config.ROOT / "assets" / "fonts"
DISPLAY_FONT = FONTS / "Oswald.ttf"
TEXT_FONT = FONTS / "GolosText.ttf"


@lru_cache(maxsize=128)
def font(size: int, weight: int = 700, *, text: bool = False) -> ImageFont.FreeTypeFont:
    """Шрифт нужного кегля и веса. `text=True` — для чтения, иначе заголовочный.

    Кешируется: карточка перебирает кегли в подборе, и каждый раз читать
    файл с диска незачем.
    """
    path = TEXT_FONT if text else DISPLAY_FONT
    f = ImageFont.truetype(str(path), size)
    f.set_variation_by_axes([weight])
    return f


def tracked(
    draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, f, fill, track: float = 0
) -> float:
    """Строка с разрядкой между буквами. Возвращает правый край.

    Pillow межбуквенного интервала не умеет, а разряженные капсы — половина
    узнаваемости мелких подписей: без них ярлык читается как подпись
    к фотографии, а не как марка канала.
    """
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=f, fill=fill)
        x += draw.textlength(ch, font=f) + track
    return x


def kicker(
    draw: ImageDraw.ImageDraw, xy: tuple[int, int], label: str, size: int = 40, fill=ACCENT
) -> int:
    """Название рубрики: красная линейка и разряженные капсы рядом.

    Раньше рубрика была белым текстом на красной плашке. Плашка читается как
    ярлык новостного агрегатора и одинаково выглядит у сотни каналов; линейка
    с разрядкой — приём музыкальной прессы и не спорит с фотографией.

    Линейка красная всегда, а цвет букв задаётся: поверх обложки красное
    по красному пропадает, и там текст ставится светлым. Возвращает высоту
    занятого места.
    """
    if not label:
        return 0
    x, y = xy
    f = font(size, 600)
    draw.rectangle([x, y + size * 0.42, x + size * 1.4, y + size * 0.42 + 6], fill=ACCENT)
    tracked(draw, (x + size * 1.9, y), label.upper(), f, fill, size * 0.14)
    return int(size * 1.6)


def mark(draw: ImageDraw.ImageDraw, xy: tuple[int, int], fill=LIGHT, size: int = 38) -> None:
    """Подпись канала: имя разрядкой, следом адрес приглушённым."""
    x, y = xy
    end = tracked(draw, (x, y), "ПЛЁНКА", font(size, 700), fill, size * 0.22)
    tracked(draw, (end + size * 0.9, y), "@plenka_fm", font(size, 400), MUTED, size * 0.1)


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


def first_sentence(text: str, limit: int = 95) -> str:
    """Первая законченная фраза поста — подпись к картинке.

    Берём именно фразу целиком: обрубок посреди слова читается как поломка,
    а не как лаконичность.
    """
    clean = strip_html(text)
    sentences = re.split(r"(?<=[.!?])\s+", clean)
    first = sentences[0].strip() if sentences else clean

    if len(first) <= limit:
        return first
    # Фраза слишком длинная — режем по слову и честно ставим многоточие.
    return first[:limit].rsplit(" ", 1)[0].rstrip(",;:—-") + "…"


def background(width: int = WIDTH, height: int = HEIGHT) -> Image.Image:
    """Кремовый пластик с фактурой — тот же материал, что у аватарки.

    Размер параметром: этой же фактурой рисуются карточки разбора в боте,
    а у них другой формат.
    """
    img = Image.new("RGB", (width, height), CREAM)
    draw = ImageDraw.Draw(img)
    random.seed(42)
    for y in range(height):
        delta = random.randint(-6, 6)
        draw.line([(0, y), (width, y)],
                  fill=tuple(max(0, min(255, CREAM[i] + delta)) for i in range(3)))
    for _ in range(int(1200 * width * height / (WIDTH * HEIGHT))):
        x, y = random.uniform(0, width), random.uniform(0, height)
        length = random.uniform(30, 160)
        delta = random.randint(-9, 9)
        draw.line([(x, y), (x + length, y)],
                  fill=tuple(max(0, min(255, CREAM[i] + delta)) for i in range(3)), width=1)
    return img.filter(ImageFilter.GaussianBlur(0.4))


def cover_background(url: str) -> Image.Image | None:
    """Обложка альбома во весь экран: размытый фон плюс сама обложка по центру.

    Историю смотрят, а не читают, поэтому картинка всегда важнее текста.
    """
    try:
        response = requests.get(url, timeout=30)
        if response.status_code != 200:
            return None
        from io import BytesIO

        cover = Image.open(BytesIO(response.content)).convert("RGB")
    except Exception:
        return None

    # Фон: обложка, растянутая на весь кадр и сильно размытая
    ratio = max(WIDTH / cover.width, HEIGHT / cover.height)
    blurred = cover.resize((int(cover.width * ratio * 1.2), int(cover.height * ratio * 1.2)))
    left = (blurred.width - WIDTH) // 2
    top = (blurred.height - HEIGHT) // 2
    background_img = blurred.crop((left, top, left + WIDTH, top + HEIGHT))
    background_img = background_img.filter(ImageFilter.GaussianBlur(38))

    # Затемняем, иначе белый текст не читается
    shade = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    background_img = Image.blend(background_img, shade, 0.45)

    # Сама обложка — крупным квадратом в верхней трети
    side = int(WIDTH * 0.78)
    sharp = cover.resize((side, side), Image.LANCZOS)
    x = (WIDTH - side) // 2
    y = int(HEIGHT * 0.17)

    # Тень под обложкой, чтобы она не сливалась с фоном
    shadow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rectangle(
        [x + 12, y + 18, x + side + 12, y + side + 18], fill=(0, 0, 0, 150)
    )
    background_img = Image.alpha_composite(
        background_img.convert("RGBA"), shadow.filter(ImageFilter.GaussianBlur(26))
    ).convert("RGB")

    background_img.paste(sharp, (x, y))
    return background_img


def render_photo(text: str, cover_url: str, rubric_title: str = "") -> Image.Image | None:
    """История с обложкой: картинка во весь экран, текста минимум."""
    img = cover_background(cover_url)
    if img is None:
        return None

    draw = ImageDraw.Draw(img)
    kicker(draw, (MARGIN, int(HEIGHT * 0.09)), rubric_title, 44, LIGHT)

    # Подпись — только первая фраза целиком: обрыв на полуслове выглядит браком
    caption = first_sentence(text, limit=95)
    lines = textwrap.wrap(caption, width=26)[:3]
    f = font(74)
    step = int(74 * 1.02)
    y = MARK_Y - 92 - len(lines) * step
    for line in lines:
        draw.text((MARGIN + 3, y + 4), line, font=f, fill=(0, 0, 0))
        draw.text((MARGIN, y), line, font=f, fill=LIGHT)
        y += step

    mark(draw, (MARGIN, MARK_Y))
    return img


def render(text: str, rubric_title: str = "") -> Image.Image:
    """Текстовая карточка — запасной вариант, когда картинки нет."""
    img = background()
    draw = ImageDraw.Draw(img)

    y = int(HEIGHT * 0.13)
    y += kicker(draw, (MARGIN, y), rubric_title, 44) + int(HEIGHT * 0.045)

    # Основной текст: кегль подбирается так, чтобы влезть без обрезки.
    # Читаемый шрифт, а не заголовочный: здесь текст читают, а не считывают.
    body = shorten(text)
    for size, per_line in ((70, 24), (62, 27), (54, 31), (46, 36), (40, 42)):
        f = font(size, 600, text=True)
        lines: list[str] = []
        for paragraph in body.split("\n"):
            lines.extend(textwrap.wrap(paragraph, width=per_line) or [""])
        height = len(lines) * size * 1.38
        if y + height < MARK_Y - 80:
            break

    for line in lines:
        draw.text((MARGIN, y), line, font=f, fill=INK)
        y += size * 1.38

    mark(draw, (MARGIN, MARK_Y), fill=INK)
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


def used_keys() -> set[str]:
    """Отпечатки постов, уже показанных в историях."""
    history = state.read_json(config.STORIES_FILE, {"items": []})
    return {item.get("key", "") for item in history.get("items", [])}


def remember(post: dict, story_id: str) -> None:
    """Записывает показанный пост, чтобы завтра не повторить его же."""
    history = state.read_json(config.STORIES_FILE, {"items": []})
    history.setdefault("items", []).append(
        {
            "key": state.fingerprint(post.get("text", "")),
            "rubric": post.get("rubric", ""),
            "story_id": story_id,
            "published_at": state.iso(),
        }
    )
    history["items"] = history["items"][-500:]
    state.write_json(config.STORIES_FILE, history)


def pick_post() -> dict | None:
    """Выбирает материал для истории: свежий пост, ещё не побывавший в сторис.

    Пост с обложкой предпочтительнее текстового — историю смотрят, а не читают.
    На автозапуске это единственная защита от того, чтобы каждый день
    показывать одну и ту же карточку: голова очереди меняется медленнее,
    чем выходят истории.
    """
    seen = used_keys()
    fallback: dict | None = None

    for path in sorted(config.QUEUE.glob("*.json")):
        post = state.read_json(path, {})
        if not post.get("text") or state.fingerprint(post.get("text", "")) in seen:
            continue
        if post.get("cover"):
            return post
        fallback = fallback or post

    return fallback


def main() -> int:
    parser = argparse.ArgumentParser(description="Истории ВКонтакте")
    parser.add_argument("--preview", action="store_true", help="только нарисовать карточку")
    parser.add_argument("--publish", action="store_true", help="нарисовать и опубликовать")
    parser.add_argument("--text", help="произвольный текст вместо поста из очереди")
    args = parser.parse_args()

    config.load_dotenv()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    cover_url = ""
    post: dict | None = None
    if args.text:
        text, title = args.text, ""
    else:
        post = pick_post()
        if not post:
            print("Нет нового материала — сегодня без истории.")
            return 0

        text = post.get("text", "")
        cover_url = post.get("cover", "")
        rubric = config.RUBRIC_BY_KEY.get(post.get("rubric", ""))
        title = rubric.title if rubric else ""

    card = None
    if cover_url:
        card = render_photo(text, cover_url, title)
        if card is None:
            print("Обложка не загрузилась — делаю текстовую карточку.")
    if card is None:
        card = render(text, title)
    path = OUT_DIR / "story.jpg"
    card.convert("RGB").save(path, "JPEG", quality=92)
    print(f"Карточка готова: {path.relative_to(config.ROOT)} ({card.width}×{card.height})")

    if args.publish:
        # Без ключа ВКонтакте вторая площадка просто выключена — это не поломка.
        # Тот же принцип, что у кросспостинга в src/publish.py.
        if not config.secret("VK_TOKEN", required=False):
            print("VK_TOKEN не задан — истории пропущены.")
            return 0

        try:
            story_id = publish(path)
        except Exception as exc:
            print(f"Не удалось опубликовать: {exc}")
            return 1

        print(f"История опубликована: {story_id}")
        if post:
            remember(post, story_id)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
