"""Единственный поллер бота: нажатия кнопок модерации и запросы к сервису.

Постоянно работающего сервера у проекта нет, поэтому события не приходят
мгновенно — их забирает по расписанию этот скрипт. Между нажатием кнопки
и публикацией проходит до пяти минут, и это единственное отличие
от «настоящего» бота.

**Почему всё в одном скрипте.** У бота один общий offset в getUpdates:
кто первый забрал событие, для того оно и исчезло. Два независимых опросчика
воровали бы события друг у друга, поэтому модерация и разборы ПРОЯВКИ
разбираются здесь же — сообщения уходят в src/service.py.

    python -m src.moderate            обработать накопившиеся события
    python -m src.moderate --dry-run  показать, что пришло, ничего не делая
"""

from __future__ import annotations

import argparse
import logging

from . import comments, config, publish, service, state, telegram

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

        # Одно нажатие публикует на обеих площадках. ВКонтакте идёт после
        # Telegram и не влияет на исход: если там не выйдет, пост уже вышел.
        publish.crosspost_vk(post)

        publish.record(post, path, "channel")
        publish.archive(path)
        return "Опубликовано в канал и ВК"

    return "Непонятная команда"


def main() -> int:
    parser = argparse.ArgumentParser(description="Обработка событий бота")
    parser.add_argument("--dry-run", action="store_true", help="только показать события")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    config.load_dotenv()

    offset = state.read_json(OFFSET_FILE, {"offset": 0}).get("offset", 0)
    updates = telegram.get_updates(offset=offset)

    if not updates:
        print("Новых событий нет.")
        return 0

    admin = config.secret("TELEGRAM_ADMIN_ID")
    handled = 0
    last_id = offset

    limits = service.load_state()
    served = 0

    for update in updates:
        last_id = max(last_id, update.get("update_id", 0) + 1)

        # Личное сообщение — это запрос к сервису разборов.
        message = update.get("message")
        if message:
            # Пост, пересланный Telegram в чат обсуждений, — повод открыть ветку
            # комментариев первым. Это не запрос к сервису, дальше не идём.
            if config.COMMENT_SEED and comments.is_channel_post(
                message, config.secret("TELEGRAM_CHANNEL_ID", required=False)
            ):
                if args.dry_run:
                    print(f"  пост в чате обсуждений: {message.get('message_id')}")
                else:
                    comments.seed(message)
                continue

            if args.dry_run:
                print(f"  сообщение от {message.get('from', {}).get('id')}: "
                      f"{(message.get('text') or '')[:60]}")
                continue
            if served >= config.SERVICE_PER_RUN:
                # Событие уже забрано из очереди Telegram и просто пропадёт,
                # поэтому человеку честно говорим, что запрос надо повторить.
                _tell_busy(message)
                continue
            try:
                if service.handle_message(message, limits):
                    served += 1
            except Exception as exc:  # noqa: BLE001 — чужой запрос не роняет запуск
                log.error("Сервис не справился с сообщением: %s", exc)
            continue

        query = update.get("callback_query")
        if not query:
            continue

        data = query.get("data", "")
        if ":" not in data:
            continue

        # Кнопки сервиса разбираются до проверки на владельца: их нажимают
        # читатели, и «это не твой канал» в ответ на «Разобрать вкус» —
        # ровно то, чего быть не должно.
        if data.startswith(service.CALLBACK_PREFIX):
            if args.dry_run:
                print(f"  кнопка сервиса: {data}")
                continue
            try:
                service.handle_callback(query, limits)
            except Exception as exc:  # noqa: BLE001 — чужое нажатие не роняет запуск
                log.error("Кнопка сервиса не сработала: %s", exc)
            continue

        action, post_id = data.split(":", 1)

        # Кнопки модерации принимаются только от владельца канала.
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
        service.save_state(limits)
        print(f"Обработано нажатий: {handled}. Выдано разборов: {served}.")

    return 0


def _tell_busy(message: dict) -> None:
    chat_id = str(message.get("chat", {}).get("id", ""))
    if not chat_id:
        return
    try:
        telegram.send_message(chat_id, "Проявочная занята. Пришли запрос ещё раз через пару минут.")
    except telegram.TelegramError:
        pass


if __name__ == "__main__":
    raise SystemExit(main())
