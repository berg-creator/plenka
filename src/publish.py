"""Публикатор: берёт следующий пост из очереди и отправляет его.

    python -m src.publish --check              проверить, что бот и канал настроены
    python -m src.publish --target admin       отправить следующий пост себе в личку
    python -m src.publish --target channel     опубликовать в канал
    python -m src.publish --dry-run            показать, что было бы отправлено

Публикатор смотрит не на часы, а на время последней публикации. Поэтому пропуск
запуска по расписанию (обычное дело для бесплатного планировщика GitHub) не ломает
ленту: следующий запуск просто увидит, что пауза затянулась, и опубликует пост.
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import timedelta
from pathlib import Path

from . import config, state, telegram

log = logging.getLogger("publish")


def next_post() -> Path | None:
    """Самый ранний пост в очереди — порядок задаётся именем файла."""
    posts = sorted(config.QUEUE.glob("*.json"))
    return posts[0] if posts else None


def due() -> bool:
    """Пора ли публиковать — исходя из времени прошлой публикации."""
    posted = state.read_json(config.POSTED_FILE, {"items": []})
    items = posted.get("items", [])
    if not items:
        return True

    last = state._parse(items[-1].get("published_at", ""))
    if last is None:
        return True
    return state.now() - last >= timedelta(hours=config.PUBLISH_INTERVAL_HOURS)


def record(post: dict, path: Path, chat: str) -> None:
    posted = state.read_json(config.POSTED_FILE, {"items": []})
    posted.setdefault("items", []).append(
        {
            "file": path.name,
            "rubric": post.get("rubric", ""),
            "chat": chat,
            "published_at": state.iso(),
        }
    )
    # Храним последние 500 записей — этого хватает для аналитики и не раздувает файл.
    posted["items"] = posted["items"][-500:]
    state.write_json(config.POSTED_FILE, posted)


def archive(path: Path) -> None:
    config.ARCHIVE.mkdir(parents=True, exist_ok=True)
    path.rename(config.ARCHIVE / path.name)


def send(post: dict, chat_id: str) -> None:
    """Отправляет пост нужным методом: опрос, фото с подписью или текст."""
    text = post.get("text", "").strip()
    rubric = post.get("rubric", "")

    if rubric == "poll":
        payload = _poll_payload(text)
        if payload:
            telegram.send_poll(
                chat_id,
                payload["question"],
                payload["options"],
                anonymous=payload.get("is_anonymous", True),
            )
            return
        log.warning("Опрос не разобран — отправляю как обычный текст")

    cover = post.get("cover", "")
    if cover and len(text) <= telegram.MAX_CAPTION:
        try:
            telegram.send_photo(chat_id, cover, text)
            return
        except telegram.TelegramError as exc:
            # Обложка могла протухнуть или быть недоступной — текст важнее картинки.
            log.warning("Фото не ушло (%s), отправляю текстом", exc)

    telegram.send_message(chat_id, text)


def crosspost_vk(post: dict) -> None:
    """Дублирует пост во ВКонтакте, если сообщество подключено.

    Молчаливо пропускается, когда токен не задан: ВКонтакте — вторая площадка,
    и её отсутствие не должно мешать основному каналу. Ошибка публикации там
    тоже не роняет запуск — пост в Telegram уже вышел.
    """
    import os

    if not os.environ.get("VK_TOKEN", "").strip():
        return

    from . import vk

    # Опросы во ВКонтакте создаются иначе, чем в Telegram, — пока пропускаем.
    if post.get("rubric") == "poll":
        return

    try:
        post_id = vk.post(post.get("text", ""), photo_url=post.get("cover", ""))
        log.info("Продублировано во ВКонтакте, запись %s", post_id)
    except Exception as exc:
        log.warning("ВКонтакте не принял пост: %s", exc)


def send_for_approval(post: dict, path: Path, chat_id: str) -> None:
    """Показывает пост и подкладывает под него кнопки решения.

    Кнопки идут отдельным сообщением: пост может оказаться фотографией или
    опросом, а к ним клавиатуру приложить не всегда возможно.
    """
    rubric = config.RUBRIC_BY_KEY.get(post.get("rubric", ""))
    title = rubric.title if rubric else post.get("rubric", "")

    telegram.send_message(chat_id, f"— — — <b>{title}</b> — — —")
    send(post, chat_id)
    telegram.send_message(
        chat_id,
        "Что делаем с постом?",
        buttons=telegram.approval_buttons(path.name),
    )


def _poll_payload(text: str) -> dict | None:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    question = (data.get("question") or "").strip()
    options = [str(o).strip() for o in data.get("options", []) if str(o).strip()]
    if not question or len(options) < 2:
        return None
    return {"question": question, "options": options, "is_anonymous": data.get("is_anonymous", True)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Публикация постов в Telegram")
    parser.add_argument(
        "--target",
        choices=["admin", "channel"],
        default="admin",
        help="куда отправлять: admin — себе в личку (по умолчанию), channel — в канал",
    )
    parser.add_argument("--dry-run", action="store_true", help="показать пост, не отправляя")
    parser.add_argument("--check", action="store_true", help="проверить настройки бота")
    parser.add_argument("--force", action="store_true", help="игнорировать интервал между постами")
    parser.add_argument(
        "--preview-all",
        action="store_true",
        help="прислать себе в личку всю очередь целиком, ничего не публикуя",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    config.load_dotenv()

    if args.check:
        name = telegram.check()
        print(f"Бот на связи: {name}")
        chat = config.secret("TELEGRAM_ADMIN_ID")
        telegram.send_message(chat, "<b>ПЛЁНКА</b> на связи. Проверка прошла успешно.")
        print("Тестовое сообщение отправлено тебе в личку.")
        return 0

    if args.preview_all:
        posts = sorted(config.QUEUE.glob("*.json"))
        if not posts:
            print("Очередь пуста.")
            return 0
        chat_id = config.secret("TELEGRAM_ADMIN_ID")
        telegram.send_message(
            chat_id,
            f"<b>Очередь на просмотр — {len(posts)} постов.</b>\n"
            f"Это превью: в канал ничего не ушло.",
        )
        for item in posts:
            send_for_approval(state.read_json(item, {}), item, chat_id)
        print(f"Отправлено на просмотр: {len(posts)} постов. Очередь не тронута.")
        return 0

    path = next_post()
    if path is None:
        print("Очередь пуста. Запусти генерацию: python -m src.compose --submit")
        return 0

    post = state.read_json(path, {})

    if args.dry_run:
        print(f"\nФайл: {path.name}")
        print(f"Рубрика: {post.get('rubric')}")
        print(f"Обложка: {post.get('cover') or 'нет'}\n")
        print(post.get("text", ""))
        return 0

    if not args.force and not due():
        print(f"Рано: с прошлой публикации не прошло {config.PUBLISH_INTERVAL_HOURS} ч.")
        return 0

    chat_id = (
        config.secret("TELEGRAM_ADMIN_ID")
        if args.target == "admin"
        else config.secret("TELEGRAM_CHANNEL_ID")
    )

    if args.target == "channel":
        send(post, chat_id)
        crosspost_vk(post)
        record(post, path, "channel")
        archive(path)
        print(f"Опубликовано в канал: {path.name}. Осталось в очереди: {len(list(config.QUEUE.glob('*.json')))}")
    else:
        # В личку пост уходит с кнопками решения и остаётся в очереди,
        # пока ты не нажмёшь «В канал» или «Удалить».
        send_for_approval(post, path, chat_id)
        print(f"Отправлено на утверждение: {path.name}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
