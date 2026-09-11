"""Единственный поллер бота: кнопки модерации, запросы к сервису и полные треки от владельца.

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
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import requests

from . import comments, config, publish, reels, service, state, telegram

log = logging.getLogger("moderate")

OFFSET_FILE = config.DATA / "tg_offset.json"

# Сколько секунд Telegram придерживает запрос, если событий нет. Больше —
# меньше пустых обращений; больше 50 сервер обрывает сам.
POLL_TIMEOUT = 25

# Как часто дежурство отправляет состояние в репозиторий.
PUSH_EVERY = 600


def handle(action: str, post_id: str) -> str:
    """Выполняет действие над постом. Возвращает текст ответа для всплывашки."""
    # Пост лежит либо в очереди, либо в срочных новостях (src/urgent.py):
    # кнопки под ними одинаковые, а папки разные.
    path = config.QUEUE / post_id
    if not path.exists():
        path = config.URGENT / post_id

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


# Звук этих кодеков Telegram играет плеером, и перекодировать его незачем:
# mp3 и AAC ложатся в новый файл теми же байтами, без потерь. Остальное — flac,
# wav, opus из webm, alac — сжимается в AAC.
PLAYABLE = {"mp3": ".mp3", "aac": ".m4a"}


def track_file(message: dict) -> dict:
    """Файл со звуком из сообщения: музыка, видео или документ аудио- или видеотипа.

    mp3 часто шлют документом, ролик с ютуба — видео или mp4-файлом. Годится всё,
    откуда ffmpeg достанет звук: в пост уходит не присланный файл, а перезалитый
    (normalize_track).
    """
    document = message.get("document") or {}
    if str(document.get("mime_type", "")).startswith(("audio/", "video/")):
        return document
    return message.get("audio") or message.get("video") or {}


def _ff(tool: str, *args: str) -> str:
    """ffmpeg или ffprobe; возвращает stdout. Причину отказа оба пишут последней
    строкой stderr — она и уходит в ошибку, а оттуда владельцу."""
    found = shutil.which(tool)
    if not found:
        raise RuntimeError(f"{tool} не найден (локально: brew install ffmpeg)")
    result = subprocess.run(
        [found, "-v", "error", *args], capture_output=True, text=True, errors="replace"
    )
    if result.returncode != 0:
        reason = (result.stderr.strip().splitlines() or ["без объяснений"])[-1]
        raise RuntimeError(f"{tool} не справился: {reason}")
    return result.stdout


def _store_cover(post: dict) -> str:
    """Обложка из iTunes по артисту и названию — последний шанс, когда её нет
    ни в посте, ни в файле. Артист сверяется точно: чужая обложка хуже никакой."""
    try:
        results = requests.get(
            "https://itunes.apple.com/search",
            params={"term": f"{post.get('artist', '')} {post.get('track', '')}",
                    "entity": "song", "limit": 10},
            timeout=20,
        ).json().get("results", [])
    except Exception:  # noqa: BLE001 — без обложки трек всё равно принимается
        return ""
    artist = post.get("artist", "").casefold().strip()
    return next(
        (item.get("artworkUrl100", "").replace("100x100", "600x600") for item in results
         if item.get("artistName", "").casefold().strip() == artist),
        "",
    )


def normalize_track(track: dict, post: dict, work: Path) -> tuple[bytes, int, bytes | None]:
    """Звук из присланного файла, готовый к плееру: (файл, секунды, обложка).

    По file_id как есть присланное в канал не годится: mp3 файлом, wav и flac
    Telegram кладёт в ленту документом, ролик — видео, а у обычного mp3 название
    и артист из тегов скачанного файла, часто кривых, и обложки может не быть
    вовсе. Поменять это у файла, уже лежащего у Telegram, нельзя: превью и теги
    принимаются только при новой загрузке.

    Поэтому перезаливается любой файл, хороший mp3 тоже: один путь на все форматы,
    и в канале всегда название, артист и обложка из поста. Качество не страдает —
    mp3 и AAC копируются без перекодирования (PLAYABLE), меняется только обёртка
    с тегами.
    """
    source = work / "source"
    source.write_bytes(telegram.download_file(track["file_id"]))

    streams = json.loads(_ff(
        "ffprobe", "-show_entries",
        "stream=index,codec_type,codec_name:stream_disposition=attached_pic",
        "-of", "json", str(source),
    )).get("streams", [])
    sound = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if sound is None:
        raise RuntimeError("в файле нет звука")

    codec = sound.get("codec_name", "")
    out = work / f"track{PLAYABLE.get(codec, '.m4a')}"
    _ff(
        "ffmpeg", "-y", "-i", str(source), "-map", f"0:{sound['index']}",
        # Теги присланного файла выбрасываем целиком и пишем свои, из поста.
        "-map_metadata", "-1",
        "-metadata", f"title={post.get('track', '')}",
        "-metadata", f"artist={post.get('artist', '')}",
        *(["-c:a", "copy"] if codec in PLAYABLE else ["-c:a", "aac", "-b:a", "256k"]),
        # moov в начало файла: плеер начинает играть, не дожидаясь загрузки целиком.
        *(["-movflags", "+faststart"] if out.suffix == ".m4a" else []),
        str(out),
    )
    try:
        seconds = round(float(_ff(
            "ffprobe", "-show_entries", "format=duration", "-of", "csv=p=0", str(out)
        )))
    except ValueError:
        seconds = 0  # плеер покажет 0:00, но играть будет

    # Обложка поста — официальная, из магазина, и берётся всегда, когда есть.
    # Вшитая в скачанный mp3 бывает от сборника, с водяным знаком сайта или вовсе
    # от другого релиза, поэтому она только вторая. iTunes — последний шанс.
    thumb = telegram._thumbnail(post["cover"]) if post.get("cover") else None
    pic = next((s for s in streams if (s.get("disposition") or {}).get("attached_pic")), None)
    if thumb is None and pic:
        cover = work / "cover.jpg"
        try:
            # Рамки Telegram для превью: JPEG, до 320 пикселей по стороне и 200 КБ.
            _ff(
                "ffmpeg", "-y", "-i", str(source), "-map", f"0:{pic['index']}",
                "-frames:v", "1", "-q:v", "3",
                "-vf", "scale=320:320:force_original_aspect_ratio=decrease:force_divisible_by=2",
                str(cover),
            )
            thumb = cover.read_bytes()
        except RuntimeError:
            pass  # битая картинка в тегах — не повод отказать в треке
    if thumb is None:
        found = _store_cover(post)
        thumb = telegram._thumbnail(found) if found else None
    return out.read_bytes(), seconds, thumb


def _post_by_request(message_id: int) -> Path | None:
    """Пост, к которому ушёл запрос трека (compose.do_ask_tracks).

    Смотрим и архив: ответ мог прийти, когда пост уже вышел, — и тогда владельцу
    надо сказать это прямо, а не «не нашёл».
    """
    for folder in (config.QUEUE, config.ARCHIVE):
        for path in folder.glob("*.json"):
            request = state.read_json(path, {}).get("track_request") or {}
            if request.get("message_id") == message_id:
                return path
    return None


def attach_track(message: dict, admin: str) -> str:
    """Прикладывает к посту полный трек, присланный владельцем. Возвращает ответ ему —
    пустой, если ответом стал сам плеер.

    Храним только file_id: репозиторий открытый, а Telegram отдаёт файл по нему
    сколько угодно раз — класть сам трек рядом с постом незачем и нельзя.
    """
    track = track_file(message)
    # Молча файл не пропадает: владелец ждёт «принял» или причину отказа.
    if not message.get("reply_to_message"):
        return "Не понял, к какому посту этот файл: пришли его ответом на запрос трека."
    # Размер приходит в апдейте: что Telegram боту всё равно не отдаст, не качаем.
    if track.get("file_size", 0) > telegram.MAX_DOWNLOAD:
        return ("Файл больше 20 МБ — Telegram не отдаёт боту такие; "
                "пришли аудио или видео пониже качеством.")

    telegram.send_chat_action(admin, "upload_voice")
    # Запрос мог уйти минуту назад из другой задачи (compose, urgent), а дерево
    # дежурства подтягивается раз в десять минут: без свежей очереди бот ответил
    # бы «не нашёл пост» на настоящий запрос.
    push_state()
    path = _post_by_request(message["reply_to_message"]["message_id"])
    if path is None:
        return "Не нашёл пост под этот запрос — похоже, его удалили из очереди."

    post = state.read_json(path, {})
    name = f"«{post.get('artist', '')} — {post.get('track', '')}»"
    if path.parent == config.ARCHIVE:
        how = "с полным треком" if post.get("full_track_file_id") else "с отрывком"
        return f"Пост {name} уже вышел — {how}. Этот файл к нему не приложить."

    try:
        with tempfile.TemporaryDirectory() as work:
            clip, seconds, thumb = normalize_track(track, post, Path(work))
        # Подтверждение — сам плеер: владелец сразу слышит и видит то, что уйдёт в канал.
        sent = telegram.send_audio(
            admin, clip, f"Принял: {name}. Так трек выйдет в канале.",
            title=post.get("track", ""), performer=post.get("artist", ""),
            thumb=thumb, seconds=seconds,
        )
        if "audio" not in sent:
            raise RuntimeError("Telegram положил файл документом, а не плеером")
    except Exception as exc:  # noqa: BLE001 — сбой приёма не трогает пост и не роняет дежурство
        log.error("Трек к %s не принят: %s", path.name, exc)
        return f"Не смог принять трек к {name}: {exc}. Пост не тронут — пришли файл ещё раз."

    # В пост — file_id перезалитого файла: у присланного теги и обложка свои.
    post["full_track_file_id"] = sent["audio"]["file_id"]
    state.write_json(path, post)

    # В git сразу, а не через десять минут: публикатор живёт в другой группе
    # и берёт пост из репозитория, а не с этого диска. Заодно подтягивается чужое:
    # если пост тем временем ушёл в архив, ребейз уносит правку следом за файлом
    # (переименование без изменений git узнаёт), и здесь это видно по его пропаже.
    push_state()
    if not path.exists():
        return f"Не успел: пост {name} только что вышел с отрывком."
    return ""


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

            # Дубль фразы ролика (src/reels.py): голосовое или аудио владельца
            # в ответ на фразу сценария. Раньше трека — аудиофайл ответом на фразу
            # иначе пошёл бы искать пост. Кадр ищется по message_id, как пост
            # у трека; не нашёлся — сообщение идёт дальше прежним путём.
            if (
                message.get("reply_to_message")
                and reels.take_file(message)
                and str(admin) == str(message.get("from", {}).get("id")) == str(
                    message.get("chat", {}).get("id")
                )
                and (reel := reels.line_of(message["reply_to_message"]["message_id"]))
            ):
                print(f"  дубль ролика {reel[0]}, кадр {reel[1]}")
                if not args.dry_run:
                    try:
                        reels.accept(message, reel, admin, push_state)
                    except Exception as exc:  # noqa: BLE001 — сбой приёма не роняет дежурство
                        log.error("Дубль ролика не принят: %s", exc)
                continue

            # Полный трек в ответ на запрос (compose.do_ask_tracks). Разбирается
            # до сервиса: это не просьба о разборе и лимит разборов не тратит.
            # Файл не ответом — тоже сюда: сервис молча пропустил бы его,
            # а владелец должен услышать, почему трек не принят.
            if track_file(message):
                # Прикладывать треки к постам может только владелец и только
                # у себя в личке: message_id в разных чатах совпадают, и ответ
                # из группы нашёл бы чужой пост. Чужой файл пропускаем молча.
                if not str(admin) == str(message.get("from", {}).get("id")) == str(
                    message.get("chat", {}).get("id")
                ):
                    continue
                if args.dry_run:
                    print(f"  трек в ответ на {(message.get('reply_to_message') or {}).get('message_id')}")
                    continue
                try:
                    reply = attach_track(message, admin)
                    if reply:
                        telegram.send_message(admin, reply)
                    print(f"  трек: {reply or 'принят, плеер ушёл владельцу'}")
                except Exception as exc:  # noqa: BLE001 — сбой приёма не роняет дежурство
                    log.error("Трек не приложен: %s", exc)
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
    # Смена часами ждёт в очереди и стартует со снимка репозитория на момент
    # постановки, а предыдущая за это время записала свой offset. Без свежего
    # дерева первый же коммит offset конфликтует при ребейзе, и до конца смены
    # не проходит ни один pull и ни один push — так 11.09 бот полдня жил
    # со старой очередью и старым кодом.
    push_state()
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
            if code_changed():
                print("Код бота обновился — смена уступает место свежей.")
                break

    push_state()
    print(f"Дежурство окончено. Нажатий: {total_handled}. Разборов: {total_served}.")
    return 0


# Код дежурства: поменялся — идущая смена устарела. Список повторяет paths
# в moderate.yml, по которым пуш ставит в очередь свежую смену.
CODE = ("src/", "requirements.txt", ".github/workflows/moderate.yml")


def code_changed() -> bool:
    """Подтянул ли push_state код новее того, с которым смена стартовала.

    Процесс держит в памяти модули, загруженные на старте, и новый код на диске
    для него не существует. Уступить место свежей смене — единственный способ
    до него дойти.
    """
    start = os.environ.get("GITHUB_SHA")
    if not start:
        return False  # локально дежурство перезапускают руками
    diff = subprocess.run(["git", "diff", "--quiet", start, "HEAD", "--", *CODE], cwd=config.ROOT)
    return diff.returncode == 1  # 0 — без изменений, 128 — git не смог сравнить


def push_state() -> None:
    """Отправляет состояние в репозиторий прямо посреди дежурства.

    На GitHub машина после запуска исчезает, а состояние живёт только в git.
    Если дежурство оборвут — а его обрывают, запуск ограничен по времени, —
    несохранённый offset заставит бота ответить на те же сообщения второй раз.
    Локально ничего не делает: там файлы никуда не денутся.
    """
    if not os.environ.get("GITHUB_ACTIONS"):
        return

    # content/ тоже: кнопки и присланные треки меняют посты, а публикатор
    # по расписанию берёт их из git, а не с диска дежурства. Без этого удалённый
    # кнопкой пост до конца смены оставался бы в очереди для публикатора.
    _push_repo(config.ROOT, ["data/", "content/"], "дежурство: разборы и состояние бота")

    # Списки слежения живут в отдельном приватном репозитории — он с этим
    # никак не связан и отправляется своим коммитом.
    if config.PRIVATE.exists() and (config.PRIVATE / ".git").exists():
        _push_repo(config.PRIVATE, ["."], "слежение: списки обновлены")


def _push_repo(cwd, paths: list[str], message: str) -> None:
    branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=cwd,
        capture_output=True,
        text=True,
    ).stdout.strip() or "main"

    commands = (
        ["git", "add", *paths],
        ["git", "commit", "-m", message],
        # Пока идёт смена, в ветку пишут и другие задачи — публикация, сбор.
        # Поэтому перед отправкой всегда подтягиваем чужое.
        ["git", "pull", "--rebase", "--autostash", "origin", branch],
        ["git", "push", "origin", f"HEAD:{branch}"],
    )
    for command in commands:
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
        if result.returncode != 0:
            # Коммитить нечего — обычное дело, и тишина в логе тут уместнее ошибки.
            # Но чужое подтянуть всё равно надо: иначе дерево дежурства устаревает
            # на всю смену, и ответ на присланный трек опирался бы на очередь
            # многочасовой давности.
            if command[1] == "commit":
                continue
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


def _selftest() -> int:
    """Приём трека без сети: что считается треком, от кого и какого размера.

    Запуск: python -m src.moderate --selftest
    """
    import contextlib
    import io

    def reply(sender: int, chat: int = 0, **file) -> dict:
        return {"message_id": 7, "from": {"id": sender}, "chat": {"id": chat or sender},
                "reply_to_message": {"message_id": 562}, **file}

    # Ролик с ютуба доходит и видео, и mp4-файлом; flac и mp3 — как пришли.
    video = {"file_id": "v", "mime_type": "video/mp4"}
    assert track_file(reply(1, video=video))["file_id"] == "v"
    assert track_file(reply(1, document={"file_id": "d", "mime_type": "video/mp4"}))["file_id"] == "d"
    assert track_file(reply(1, document={"file_id": "f", "mime_type": "audio/flac"}))["file_id"] == "f"
    assert track_file(reply(1, audio={"file_id": "a", "mime_type": "audio/mpeg"}))["file_id"] == "a"
    # Pdf или фото ответом на запрос — не трек, а обычное сообщение сервису.
    assert not track_file(reply(1, document={"file_id": "p", "mime_type": "application/pdf"}))
    assert not track_file(reply(1, photo=[{"file_id": "x"}]))

    def taken(message: dict) -> bool:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            process([{"update_id": 1, "message": message}], {}, "1", True, 0)
        return "трек в ответ на 562" in out.getvalue()

    # От владельца в личке — в приём; чужой файл и свой, но из группы, — мимо.
    assert taken(reply(1, video=video))
    assert not taken(reply(2, video=video))
    assert not taken(reply(1, chat=-100, video=video))

    # Файл не ответом на запрос — тоже в приём: сервис пропустил бы его молча.
    alone = {"message_id": 8, "from": {"id": 1}, "chat": {"id": 1}, "video": video}
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        process([{"update_id": 1, "message": alone}], {}, "1", True, 0)
    assert "трек в ответ на None" in out.getvalue()
    assert "ответом на запрос" in attach_track(alone, "1")

    # Больше 20 МБ не качаем: ответ сразу, без сети и без поиска поста.
    big = reply(1, document={"file_id": "b", "mime_type": "audio/flac", "file_size": 21 * 2**20})
    assert "больше 20 МБ" in attach_track(big, "1")
    print("приём трека: все проверки прошли")
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
    parser.add_argument("--selftest", action="store_true", help="проверить приём трека без сети")
    args = parser.parse_args()

    if args.selftest:
        return _selftest()

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
