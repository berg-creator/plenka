"""Единственный поллер бота: нажатия кнопок модерации и запросы к сервису.

Постоянно работающего сервера у проекта нет, поэтому события не приходят
мгновенно — их забирает по расписанию этот скрипт. Между нажатием кнопки
и публикацией проходит до пяти минут, и это единственное отличие
от «настоящего» бота.

**Почему всё в одном скрипте.** У бота один общий offset в getUpdates:
кто первый забрал событие, для того оно и исчезло. Два независимых опросчика
воровали бы события друг у друга, поэтому модерация и разборы ПРОЯВКИ
разбираются здесь же — сообщения уходят в src/service.py.

    python -m src.moderate             обработать накопившееся и выйти
    python -m src.moderate --serve 55  дежурить 55 минут, отвечая сразу
    python -m src.moderate --dry-run   показать, что пришло, ничего не делая

Дежурство — основной режим. Оно держит соединение с Telegram открытым
(long polling), поэтому ответ приходит за секунды. Разовый запуск остался
для отладки и на случай, если дежурство почему-то не идёт.
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import time

from . import comments, config, publish, service, state, telegram

log = logging.getLogger("moderate")

OFFSET_FILE = config.DATA / "tg_offset.json"

# Сколько секунд Telegram придерживает запрос, если событий нет. Больше —
# меньше пустых обращений; больше 50 сервер обрывает сам.
POLL_TIMEOUT = 25

# Как часто дежурство отправляет состояние в репозиторий.
PUSH_EVERY = 600


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


def process(updates: list[dict], limits: dict, admin: str, dry_run: bool, offset: int) -> tuple:
    """Разбирает пачку событий. Возвращает (нажатий, разборов, новый offset).

    Вынесено из main отдельно, потому что режимов два: разовый запуск по крону
    и постоянное дежурство. Логика у них одна, отличается только то, как часто
    её зовут.
    """
    handled = 0
    served = 0
    last_id = offset
    args = argparse.Namespace(dry_run=dry_run)

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

    return handled, served, last_id


def serve(minutes: int) -> int:
    """Дежурство: держим соединение открытым и отвечаем сразу.

    Telegram сам придерживает запрос до появления событий (long polling),
    поэтому цикл не крутится вхолостую — он спит внутри getUpdates. Ответ
    приходит за секунды вместо десятков минут, которые даёт крон.

    Состояние пишется на диск после каждой пачки: запуск в любой момент могут
    оборвать, и уже отвеченные события не должны разбираться заново.
    """
    admin = config.secret("TELEGRAM_ADMIN_ID")
    deadline = time.monotonic() + minutes * 60
    offset = state.read_json(OFFSET_FILE, {"offset": 0}).get("offset", 0)
    limits = service.load_state()
    total_handled, total_served = 0, 0

    print(f"Дежурство {minutes} мин. Бот отвечает сразу.")

    next_push = time.monotonic() + PUSH_EVERY

    while time.monotonic() < deadline:
        try:
            updates = telegram.get_updates(offset=offset, timeout=POLL_TIMEOUT)
        except telegram.TelegramError as exc:
            # Обрыв связи не повод заканчивать дежурство: подождём и вернёмся.
            log.warning("Опрос сорвался: %s", exc)
            time.sleep(5)
            continue

        if updates:
            handled, served, offset = process(updates, limits, admin, False, offset)
            total_handled += handled
            total_served += served

            state.write_json(OFFSET_FILE, {"offset": offset})
            service.save_state(limits)

        if time.monotonic() >= next_push:
            push_state()
            next_push = time.monotonic() + PUSH_EVERY

    push_state()
    print(f"Дежурство окончено. Нажатий: {total_handled}. Разборов: {total_served}.")
    return 0


def push_state() -> None:
    """Отправляет состояние в репозиторий прямо посреди дежурства.

    На GitHub машина после запуска исчезает, а состояние живёт только в git.
    Если дежурство оборвут — а его обрывают, запуск ограничен по времени, —
    несохранённый offset заставит бота ответить на те же сообщения второй раз.
    Локально ничего не делает: там файлы никуда не денутся.
    """
    if not os.environ.get("GITHUB_ACTIONS"):
        return

    commands = (
        ["git", "add", "data/"],
        ["git", "commit", "-m", "дежурство: разборы и состояние бота"],
        ["git", "pull", "--rebase", "--autostash", "origin", "HEAD"],
        ["git", "push"],
    )
    for command in commands:
        result = subprocess.run(command, cwd=config.ROOT, capture_output=True, text=True)
        if result.returncode != 0:
            # Коммитить нечего — обычное дело, тишина в логе тут уместнее ошибки.
            if command[1] != "commit":
                log.warning("git %s: %s", command[1], result.stderr.strip()[:200])
            return


def once(dry_run: bool) -> int:
    """Разовый разбор накопившегося — режим для крона."""
    offset = state.read_json(OFFSET_FILE, {"offset": 0}).get("offset", 0)
    updates = telegram.get_updates(offset=offset)

    if not updates:
        print("Новых событий нет.")
        return 0

    admin = config.secret("TELEGRAM_ADMIN_ID")
    limits = service.load_state()
    handled, served, last_id = process(updates, limits, admin, dry_run, offset)

    if not dry_run:
        state.write_json(OFFSET_FILE, {"offset": last_id})
        service.save_state(limits)
        print(f"Обработано нажатий: {handled}. Выдано разборов: {served}.")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Обработка событий бота")
    parser.add_argument("--dry-run", action="store_true", help="только показать события")
    parser.add_argument(
        "--serve",
        type=int,
        metavar="МИНУТ",
        help="дежурить указанное время, отвечая сразу",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    config.load_dotenv()

    if args.serve:
        return serve(args.serve)
    return once(args.dry_run)


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
