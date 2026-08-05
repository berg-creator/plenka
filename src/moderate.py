"""Модерация через бота: обрабатывает нажатия кнопок под превью постов.

Постоянно работающего сервера у проекта нет, поэтому нажатия не приходят
мгновенно — их забирает по расписанию этот скрипт. Между нажатием кнопки
и публикацией проходит до пятнадцати минут, и это единственное отличие
от «настоящего» бота.

    python -m src.moderate            обработать накопившиеся нажатия
    python -m src.moderate --dry-run  показать, что пришло, ничего не делая
"""

from __future__ import annotations

import argparse
import logging

from . import config, publish, state, telegram

log = logging.getLogger("moderate")

OFFSET_FILE = config.DATA / "tg_offset.json"


def handle(action: str, post_id: str) -> str:
    """Выполняет действие над постом. Возвращает текст ответа для всплывашки."""
    path = config.QUEUE / post_id

    if action == "skip":
        return "Оставил в очереди"

    if not path.exists():
        return "Поста уже нет в очереди"

    post = state.read_json(path, {})

    if action == "del":
        path.unlink()
        return "Удалил"

    if action == "pub":
        try:
            publish.send(post, config.secret("TELEGRAM_CHANNEL_ID"))
        except telegram.TelegramError as exc:
            log.error("Не удалось опубликовать %s: %s", post_id, exc)
            return f"Ошибка: {exc}"
        publish.record(post, path, "channel")
        publish.archive(path)
        return "Опубликовано в канал"

    return "Непонятная команда"


def main() -> int:
    parser = argparse.ArgumentParser(description="Обработка нажатий кнопок под постами")
    parser.add_argument("--dry-run", action="store_true", help="только показать события")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    config.load_dotenv()

    offset = state.read_json(OFFSET_FILE, {"offset": 0}).get("offset", 0)
    updates = telegram.get_updates(offset=offset)

    if not updates:
        print("Новых нажатий нет.")
        return 0

    admin = config.secret("TELEGRAM_ADMIN_ID")
    handled = 0
    last_id = offset

    for update in updates:
        last_id = max(last_id, update.get("update_id", 0) + 1)
        query = update.get("callback_query")
        if not query:
            continue

        data = query.get("data", "")
        if ":" not in data:
            continue
        action, post_id = data.split(":", 1)

        # Команды принимаются только от владельца канала.
        sender = str(query.get("from", {}).get("id", ""))
        if sender != str(admin):
            telegram.answer_callback(query["id"], "Это не твой канал")
            continue

        if args.dry_run:
            print(f"  {action} → {post_id}")
            continue

        result = handle(action, post_id)
        telegram.answer_callback(query["id"], result)

        message = query.get("message", {})
        if message.get("message_id"):
            telegram.edit_markup(admin, message["message_id"], None)

        print(f"  {post_id}: {result}")
        handled += 1

    if not args.dry_run:
        state.write_json(OFFSET_FILE, {"offset": last_id})
        print(f"Обработано нажатий: {handled}.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
