"""Единственный поллер бота: кнопки модерации, запросы к сервису, полные треки от владельца
и голоса СЛЕПОЙ ПРОСЛУШКИ.

Постоянно работающего сервера у проекта нет, поэтому события не приходят
мгновенно — их забирает по расписанию этот скрипт. Между нажатием кнопки
и публикацией проходит до пяти минут, и это единственное отличие
от «настоящего» бота.

**Почему всё в одном скрипте.** У бота один общий offset в getUpdates:
кто первый забрал событие, для того оно и исчезло. Два независимых опросчика
воровали бы события друг у друга, поэтому модерация, разборы ПРОЯВКИ
и прослушка разбираются здесь же — сообщения уходят в src/service.py,
пересылка отрывка и голоса в опросе под ним — в src/quiz.py.

    python -m src.moderate --serve 55  дежурить 55 минут, отвечая сразу
    python -m src.moderate --selftest  приём трека, первый комментарий, сохранение состояния — без сети

Дежурство — единственный режим. Оно держит соединение с Telegram открытым
(long polling), поэтому ответ приходит за секунды. Разовый разбор накопившегося
убран 04.10.2026: его не вызывал никто, а запуск без флагов на Маке был бы
вторым опросчиком и воровал бы события у дежурства.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from . import bity, comments, config, ocenka, otbor, publish, quiz, reels, service, skleyka, state, svedenie, telegram, tracks, urgent

log = logging.getLogger("moderate")

OFFSET_FILE = config.DATA / "tg_offset.json"

# Сколько секунд Telegram придерживает запрос, если событий нет. Больше —
# меньше пустых обращений; больше 50 сервер обрывает сам.
POLL_TIMEOUT = 25

# Как часто дежурство отправляет состояние в репозиторий.
PUSH_EVERY = 600

# Опрос, пока идёт или ждёт сведение (src/skleyka.py): очередь двигается на каждом круге.
SKLEYKA_POLL = 3

# Очередь сведения срывается столько секунд подряд — строка владельцу. Сторож (src/health.py)
# ходит раз в сутки и заметил бы то же с опозданием до суток, а дежурство видит на каждом круге.
STUCK_AFTER = 600
STUCK_FILE = config.DATA / "duty_alarm.json"


def handle(action: str, post_id: str) -> str:
    """Выполняет действие над постом. Возвращает текст ответа для всплывашки."""
    # Пост лежит в очереди, в срочных новостях (src/urgent.py) или ждёт выхода
    # в отборе (src/otbor.py): кнопки под ними одинаковые, а папки разные.
    path = next((folder / post_id for folder in (config.QUEUE, config.URGENT, config.OTBOR_POSTS)
                 if (folder / post_id).exists()), config.QUEUE / post_id)

    if action == "skip":
        return "Оставил в очереди"

    if not path.exists():
        return "Поста уже нет в очереди"

    post = state.read_json(path, {})

    if action == "del":
        path.unlink()
        return "Удалил"

    if action == "pub":
        # Одно нажатие публикует на обеих площадках, и сообщение поста
        # запоминается для правок автопилота — тем же путём, что по расписанию.
        try:
            publish.to_channel(post, path, config.secret("TELEGRAM_CHANNEL_ID"))
        except telegram.TelegramError as exc:
            log.error("Не удалось опубликовать %s: %s", post_id, exc)
            return f"Ошибка: {exc}"
        return "Опубликовано в канал и ВК"

    return "Непонятная команда"


# Звук этих кодеков Telegram играет плеером, и перекодировать его незачем:
# mp3 и AAC ложатся в новый файл теми же байтами, без потерь. Остальное — flac,
# wav, opus из webm, alac — сжимается в AAC.
PLAYABLE = {"mp3": ".mp3", "aac": ".m4a"}

WAIT_FILE = ("Жду аудиофайл: пришли сам трек ответом на запрос — mp3, m4a, видео "
             "или документом. По ссылке бот трек не скачивает.")


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


def _song_name(name: str) -> str:
    """Название без хвостов магазина: «Сияй (feat. X)» и «Сияй - Single» — это «сияй»."""
    return re.split(r"\s+[-–(\[]|\s*[(\[]", name, maxsplit=1)[0].casefold().strip()


def _store_cover(post: dict) -> str:
    """Обложка из iTunes по артисту и названию — последний шанс, когда её нет
    ни в посте, ни в файле. Сверяются и артист, и трек: поиск охотно отдаёт
    другую песню того же артиста, а с ней обложку другого релиза. Чужая обложка
    хуже никакой."""
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
    track = _song_name(post.get("track", ""))
    return next(
        (item.get("artworkUrl100", "").replace("100x100", "600x600") for item in results
         if item.get("artistName", "").casefold().strip() == artist
         and track and _song_name(item.get("trackName", "")) == track),
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
            # У разбора и новости запросов несколько — по одному на трек (tracks.pieces).
            if any((piece.get("track_request") or {}).get("message_id") == message_id
                   for piece in tracks.pieces(state.read_json(path, {}))):
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
    asked = message["reply_to_message"]["message_id"]
    path = _post_by_request(asked)
    if path is None:
        return "Не нашёл пост под этот запрос — похоже, его удалили из очереди."

    post = state.read_json(path, {})
    # Трек, о котором спрашивали: у релиза это сам пост, у разбора — один из listen.
    piece = next(p for p in tracks.pieces(post) if (p.get("track_request") or {}).get("message_id") == asked)
    name = f"«{piece.get('artist', '')} — {piece.get('track', '')}»"
    # Вышедший пост берёт трек, пока знает свою ветку комментариев (comments.seed
    # запоминает её, когда трека к выходу нет): Mac владельца ночью спит, и трек
    # приходит утром, когда пост уже в канале (18.09.2026).
    published = path.parent == config.ARCHIVE
    if published and (piece.get("full_track_file_id") or not post.get("thread")):
        how = "с полным треком" if piece.get("full_track_file_id") else "без ветки комментариев"
        return f"Пост {name} уже вышел — {how}. Этот файл к нему не приложить."

    try:
        with tempfile.TemporaryDirectory() as work:
            clip, seconds, thumb = normalize_track(track, piece, Path(work))
        # Подтверждение — сам плеер: владелец сразу слышит и видит то, что уйдёт в канал.
        sent = telegram.send_audio(
            admin, clip, f"Принял: {name}. Так трек выйдет в канале.",
            title=piece.get("track", ""), performer=piece.get("artist", ""),
            thumb=thumb, seconds=seconds,
        )
        if "audio" not in sent:
            raise RuntimeError("Telegram положил файл документом, а не плеером")
    except Exception as exc:  # noqa: BLE001 — сбой приёма не трогает пост и не роняет дежурство
        log.error("Трек к %s не принят: %s", path.name, exc)
        return f"Не смог принять трек к {name}: {exc}. Пост не тронут — пришли файл ещё раз."

    # В пост — file_id перезалитого файла: у присланного теги и обложка свои.
    piece["full_track_file_id"] = sent["audio"]["file_id"]
    if published:
        # Первым комментарием, как у трека к выходу, и строкой «▸ Или в комментариях ↓»
        # в самом посте: publish.edit ставит её, раз трек у поста есть.
        thread = post["thread"]
        try:
            # Под разбором вопрос уже задан вместе со ссылками на площадки (comments.seed).
            telegram.send_audio(thread["chat"], piece["full_track_file_id"],
                                comments.ask(post, post.get("rubric", ""), "трек") if piece is post else "",
                                reply_to=thread["message_id"])
        except telegram.TelegramError as exc:
            log.error("Трек к %s не встал в комментарии: %s", path.name, exc)
            return f"Трек к {name} не встал в комментарии: {exc}."
        state.write_json(path, post)
        try:
            # У разбора строка «что послушать — в комментариях» стоит с выхода: править нечего,
            # а Telegram на правку без изменений отвечает ошибкой.
            if piece is post:
                publish.edit(post)
        except telegram.TelegramError as exc:
            # Трек уже под постом — не повод его откатывать, строки просто нет.
            log.error("Строка о треке в пост %s не встала: %s", path.name, exc)
        push_state()
        return ""
    state.write_json(path, post)

    # В git сразу, а не через десять минут: публикатор живёт в другой группе
    # и берёт пост из репозитория, а не с этого диска. Заодно подтягивается чужое:
    # если пост тем временем ушёл в архив, ребейз уносит правку следом за файлом
    # (переименование без изменений git узнаёт), и здесь это видно по его пропаже.
    push_state()
    if not path.exists():
        return f"Не успел: пост {name} только что вышел с отрывком."
    return ""


INSIDE = ("member", "administrator", "creator")
# Сколько дней живёт отметка о действии в боте (config.TOUCH_FILE): столько же, сколько трек СВЕДЕНИЯ.
TOUCH_DAYS = 30


def touched(update: dict, admin: str) -> tuple[str, str] | None:
    """(id человека, метка действия) для события из лички бота; чужое событие и владелец — None.

    Журнал уходов знал только время: чем человек пользовался в боте перед тем, как уйти из канала,
    не помнил никто (владелец, 09.10.2026). Метка потом идёт в открытый журнал (member_row), поэтому
    личного в ней нет: команда — только известная сервису (service.parse_command), у /start — слово
    до «_» из известных наперёд меток ссылок и команд (после «_» идут коды и номера), у кнопки — два
    первых куска её данных, у остального — одно слово о виде сообщения. Текст сообщения в метку
    не идёт никогда.
    """
    message, query = update.get("message") or {}, update.get("callback_query") or {}
    user = (update.get("pre_checkout_query") or query or message).get("from", {}).get("id")
    if not user or str(user) == str(admin):
        return None
    if update.get("pre_checkout_query"):  # счёт звёздами бот шлёт только в личку
        return str(user), "оплата"
    if ((query.get("message") or message).get("chat") or {}).get("type") != "private":
        return None
    if query:
        data = ":".join(query.get("data", "").split(":")[:2])
        return str(user), data if re.fullmatch(r"[a-z]{1,8}(:[a-z_]{1,16})?", data) else "кнопка"
    text = message.get("text") or ""
    kind, body = service.parse_command(text)
    if message.get("successful_payment"):
        what = "оплата"
    elif message.get("web_app_data"):
        what = "мини-приложение"
    elif message.get("voice"):
        what = "голос"
    elif any(message.get(file) for file in ("document", "audio", "video", "photo", "animation", "video_note")):
        what = "файл"
    elif kind:  # имя команды — тем же шаблоном, что у parse_command: только буквы
        what = "/" + re.match(r"/([a-zA-Zа-яА-ЯёЁ_]+)", text).group(1).lower()
        tag = body.partition("_")[0]
        known = tag in service.COMMANDS or any(tag == label.partition("_")[0] for label in service.SOURCES)
        if kind == "menu" and known:
            what += f" {tag}"
    elif "://" in text or any(e.get("type") in ("url", "text_link") for e in message.get("entities") or []):
        what = "ссылка"
    else:
        what = "текст" if text else "прочее"
    return str(user), what


def touch_save(touch: dict) -> None:
    """Пишет отметки в приватное хранилище, выбросив те, что старше TOUCH_DAYS."""
    fresh = {user: mark for user, mark in touch.items()
             if min(skleyka._age(mark.get(key) or "") for key in ("at", "in")) < TOUCH_DAYS * 86400}
    state.write_json(config.TOUCH_FILE, fresh)


def member_row(event: dict, touch: dict | None = None) -> dict | None:
    """Строка журнала config.MEMBERS_FILE о вступлении в канал или уходе из него: время и направление.

    Историю действий Telegram показывает только админу в приложении и хранит двое суток, а бот
    уходы не записывал — после чего уходят из канала, не знал никто (06.10.2026). id человека
    в журнал не идёт: репозиторий открытый. Ушедшему, который сводил трек ботом, пишется, сколько
    часов прошло с его последнего готового трека (track_hours): так проверяется догадка «получил
    трек — отписался». Чат обсуждений шлёт те же события — в него попадают, оставив комментарий, —
    и в журнал они не идут.

    touch — отметки действий в боте (touched, приватный config.TOUCH_FILE): и пришедшему, и ушедшему
    строка называет последнее действие в боте (last) и сколько часов назад оно было (last_hours),
    ушедшему — ещё сколько часов он пробыл в канале (stay_hours). Время вступления пишется в ту же
    запись прямо здесь, уход его снимает.
    """
    if (event.get("chat") or {}).get("type") != "channel":
        return None
    was, now = ((event.get(side) or {}) for side in ("old_chat_member", "new_chat_member"))
    before, after = (side.get("status") in INSIDE or bool(side.get("is_member")) for side in (was, now))
    if before == after:
        return None
    moment = datetime.fromtimestamp(event["date"], timezone.utc) if event.get("date") else None
    row = {"at": state.iso(moment), "way": "in" if after else "out"}
    user = str((now.get("user") or {}).get("id"))
    if not after:
        done = [track["done"] for track in skleyka.load()["tracks"].values()
                if track.get("chat") == user and track.get("done")]
        if done:
            row["track_hours"] = round(skleyka._age(max(done)) / 3600, 1)
    try:
        mark = (touch or {}).get(user) or {}
        if mark.get("at"):
            row["last"], row["last_hours"] = mark.get("what", ""), round(skleyka._age(mark["at"]) / 3600, 1)
        if after and touch is not None:
            touch.setdefault(user, {})["in"] = row["at"]
        elif mark.get("in"):
            row["stay_hours"] = round(skleyka._age(mark.pop("in")) / 3600, 1)
    except Exception as exc:  # noqa: BLE001 — битая отметка строку журнала не отнимает; в лог — без id
        log.error("Действие в боте к строке журнала не приложено: %s", type(exc).__name__)
    return row


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
    # Отметки действий в боте (touched): файл читается раз на пачку и пишется раз, после разбора.
    # Не прочитался — пачка идёт без отметок: пустой словарь затёр бы прежние при записи.
    try:
        touch = state.read_json(config.TOUCH_FILE, {})
        before = json.dumps(touch, sort_keys=True)
    except Exception as exc:  # noqa: BLE001 — отметки не держат разбор событий; в лог — без id
        log.error("Отметки действий не прочитаны: %s", type(exc).__name__)
        touch = None

    # Оплату звёздами Telegram отменяет, если за 10 секунд не ответить «да», — такие
    # события вперёд пачки: разбор перед ними может идти дольше.
    for update in sorted(updates, key=lambda update: "pre_checkout_query" not in update):
        last_id = max(last_id, update.get("update_id", 0) + 1)
        try:
            who = touched(update, admin) if touch is not None else None
            if who:
                touch.setdefault(who[0], {}).update(at=state.iso(), what=who[1])
        except Exception as exc:  # noqa: BLE001 — отметка не держит разбор событий; в лог — без id
            log.error("Действие в боте не отмечено: %s", type(exc).__name__)

        # Оплата звёздами (src/skleyka.py): треки СВЕДЕНИЯ сверх лимита и задаток за ручное сведение.
        # «Нет» — только задатку по треку, где он уже внесён или от которого отказались (skleyka.checkout).
        # Проверка упала — без ответа Telegram отменит платёж сам: звёзды остаются у человека.
        checkout = update.get("pre_checkout_query")
        if checkout:
            print(f"  оплата звёздами: {checkout.get('invoice_payload')}")
            if not args.dry_run:
                try:
                    telegram.answer_pre_checkout(checkout["id"], skleyka.checkout(checkout.get("invoice_payload") or ""))
                except Exception as exc:  # noqa: BLE001 — опоздали или сбой проверки: платёж отменён
                    log.error("Оплата звёздами не подтверждена: %s", exc)
            continue

        # Вступление в канал или уход из него — строкой в журнал (member_row), без id.
        member = update.get("chat_member")
        if member:
            try:
                row = member_row(member, touch)
                if row:
                    print(f"  канал: {'пришёл' if row['way'] == 'in' else 'ушёл'}")
                    if not args.dry_run:
                        state.append_jsonl(config.MEMBERS_FILE, [row])
            except Exception as exc:  # noqa: BLE001 — журнал уходов не держит дежурство
                log.error("Вступление или уход не записаны: %s", exc)
            continue

        # Личное сообщение — это запрос к сервису разборов.
        message = update.get("message")
        if message and message.get("successful_payment"):
            print("  звёзды получены")
            if not args.dry_run:
                try:
                    skleyka.paid(message)
                except Exception as exc:  # noqa: BLE001 — сбой начисления не роняет дежурство
                    log.error("Звёзды не начислены: %s", exc)
            continue
        # Место голоса из мини-приложения СВЕДЕНИЯ (cloud/skleyka_app.py): sendData
        # с кнопки клавиатуры приходит сюда же сообщением без текста.
        if message and message.get("web_app_data"):
            print("  место голоса из мини-приложения")
            if not args.dry_run:
                try:
                    skleyka.moved(message, admin=str(admin) == str(message.get("from", {}).get("id")))
                except Exception as exc:  # noqa: BLE001 — сбой приёма не роняет дежурство
                    log.error("Место голоса не принято: %s", exc)
            continue
        # Человек пишет боту не словами о треке СВЕДЕНИЯ — кнопку приложения снимет первый
        # ответ бота (src/skleyka.py, unkey).
        if message and message.get("chat", {}).get("type") == "private" and not args.dry_run:
            try:
                skleyka.unkey(message)
            except Exception as exc:  # noqa: BLE001 — кнопка подождёт, дежурство не падает
                log.error("Кнопка приложения не снята: %s", exc)
        if message:
            # Пост, пересланный Telegram в чат обсуждений, — повод открыть ветку
            # комментариев первым. Под прослушкой первой идёт сама викторина
            # (src/quiz.py), вопрос там лишний. Под постом о релизе первым
            # комментарием идёт полный трек от владельца (comments.seed).
            # Это не запрос к сервису, дальше не идём.
            if comments.is_channel_post(
                message, config.secret("TELEGRAM_CHANNEL_ID", required=False)
            ):
                if args.dry_run:
                    print(f"  пост в чате обсуждений: {message.get('message_id')}")
                elif quiz.is_riddle(message):
                    try:
                        quiz.attach(message)
                    except Exception as exc:  # noqa: BLE001 — сбой не роняет дежурство
                        log.error("Викторина под прослушкой не встала: %s", exc)
                elif config.COMMENT_SEED:
                    # Пост вышел секунды назад, и что это за пост — записано
                    # в репозитории публикатором. Своё дерево дежурство обновляет
                    # раз в несколько минут, а комментарий нужен сейчас: перед
                    # ним подтягиваем состояние, иначе трек к посту опоздает.
                    # Публикатор коммитит не мгновенно, поэтому тем же способом
                    # comments.seed ждёт его и пробует ещё раз.
                    push_state()
                    comments.seed(message, refresh=push_state)
                continue

            # Бит ПЛЁНКИ (src/bity.py): файл владельца с подписью «бит …» — в каталог. Раньше роликов,
            # дорожек сведения, трека к посту и ОТБОРА: аудиофайл владельца ушёл бы в любой из них.
            if bity.wants(message, admin):
                print("  бит ПЛЁНКИ")
                if not args.dry_run:
                    try:
                        bity.add(message)
                    except Exception as exc:  # noqa: BLE001 — сбой каталога не роняет дежурство
                        log.error("Бит не принят: %s", exc)
                continue

            # Ответ владельца на фразу ролика (src/reels.py): голосовое, аудио или видео —
            # дубль, фото или картинка файлом — кадр, «собери» — сборка, прочий
            # текст — правка черновика для Мака (reels.note). Раньше
            # трека — аудиофайл ответом на фразу иначе пошёл бы искать пост,
            # и раньше сервиса — фото и текст ушли бы в разборы. Кадр ищется
            # по message_id, как пост у трека; не нашёлся — сообщение идёт дальше
            # прежним путём.
            if (
                message.get("reply_to_message")
                and (reel_reply := reels.reply_kind(message))
                and str(admin) == str(message.get("from", {}).get("id")) == str(
                    message.get("chat", {}).get("id")
                )
                and (reel := reels.line_of(message["reply_to_message"]["message_id"]))
            ):
                what = {"voice": "дубль", "picture": "картинка", "build": "«собери»", "comment": "правка"}[reel_reply]
                print(f"  {what} ролика {reel[0]}, кадр {reel[1]}")
                if not args.dry_run:
                    try:
                        reels.accept(message, reel, admin, push_state)
                    except Exception as exc:  # noqa: BLE001 — сбой приёма не роняет дежурство
                        log.error("Ответ на фразу ролика не принят: %s", exc)
                continue

            # Правка черновика ролика не ответом на «Что поправить?» (reels.fixing):
            # после «Исправить» текст владельца — правка, а не разбор сервиса.
            if (
                str(admin) == str(message.get("from", {}).get("id")) == str(message.get("chat", {}).get("id"))
                and (reel_id := reels.fixing(message))
            ):
                print(f"  правка ролика {reel_id}")
                if not args.dry_run:
                    try:
                        reels.accept(message, (reel_id, 0), admin, push_state)
                    except Exception as exc:  # noqa: BLE001 — сбой приёма не роняет дежурство
                        log.error("Правка ролика не принята: %s", exc)
                continue

            # Дорожки СВЕДЕНИЯ (src/skleyka.py): после /svedenie или ответом на её
            # инструкцию файлы — вокал и бит, а не трек в ОТБОР. Ответ на что-то
            # другое, например на запрос трека у владельца, идёт дальше своим путём.
            if skleyka.wants(message):
                print("  дорожка сведения")
                if not args.dry_run:
                    try:
                        skleyka.take(message)
                    except Exception as exc:  # noqa: BLE001 — чужой файл не роняет дежурство
                        log.error("Сведение не приняло дорожку: %s", exc)
                continue

            # Трек на ОЦЕНКУ (src/ocenka.py): файл после /ocenka или ответом на её приглашение.
            # Позже дорожек сведения — открытая заявка важнее — и раньше ОТБОРА: без отметки
            # оценки файл по-прежнему идёт в отбор.
            if ocenka.wants(message):
                print("  трек на оценку")
                if not args.dry_run:
                    try:
                        ocenka.take(message, admin=str(admin) == str(message.get("from", {}).get("id")))
                    except Exception as exc:  # noqa: BLE001 — чужой файл не роняет дежурство
                        log.error("Оценка не приняла файл: %s", exc)
                continue

            # Полный трек в ответ на запрос (compose.do_ask_tracks). Разбирается
            # до сервиса: это не просьба о разборе и лимит разборов не тратит.
            # Файл не ответом — тоже сюда: сервис молча пропустил бы его,
            # а владелец должен услышать, почему трек не принят.
            if track_file(message):
                owner = str(admin) == str(message.get("from", {}).get("id")) == str(
                    message.get("chat", {}).get("id")
                )
                # Файл в личке от кого угодно, кроме владельца с ответом на запрос
                # трека, — это трек в ОТБОР (src/otbor.py): файл открывает заявку
                # сам, а владелец может проверить отбор на себе.
                chat = message.get("chat", {})
                if chat.get("type") == "private" and (
                    not owner or (not message.get("reply_to_message") and otbor.active(chat.get("id")))
                ):
                    print("  файл в отбор")
                    if not args.dry_run:
                        try:
                            otbor.handle(message, admin=owner)
                        except Exception as exc:  # noqa: BLE001 — чужой файл не роняет дежурство
                            log.error("Отбор не принял файл: %s", exc)
                    continue
                # Прикладывать треки к постам может только владелец и только
                # у себя в личке: message_id в разных чатах совпадают, и ответ
                # из группы нашёл бы чужой пост. Чужой файл пропускаем молча.
                if not owner:
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

            # Текст или ссылка ответом на запрос трека: сервис принял бы это
            # за просьбу о разборе, а владелец ждал бы, что трек принят.
            if (
                message.get("reply_to_message")
                and str(admin) == str(message.get("from", {}).get("id")) == str(
                    message.get("chat", {}).get("id")
                )
                and _post_by_request(message["reply_to_message"]["message_id"])
            ):
                print("  не файл в ответ на запрос трека")
                if not args.dry_run:
                    telegram.send_message(admin, WAIT_FILE)
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

        # Голос в прослушке под постом: угадавший получит титул завтра (src/quiz.py).
        answer = update.get("poll_answer")
        if answer:
            if args.dry_run:
                print(f"  голос в опросе {answer.get('poll_id')}")
            else:
                quiz.take_answer(answer)
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
                # Кнопка другой функции, хоть «🎙 Этот трек — в канал ПЛЁНКИ» под треком, — работа над треком
                # кончилась. Свои кнопки СВЕДЕНИЯ снимают клавиатуру ответом сами (skleyka._tweak).
                if not data.startswith(skleyka.PREFIX) and query.get("message"):
                    skleyka.unkey(query["message"])
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

        message = query.get("message", {})
        # «📺 В канал» под роликом (src/reels.py): выходит видео того сообщения, где нажали.
        # «Всё ок» и «Исправить» под черновиком с Мака — записываются для Мака (reels.verdict).
        result = (reels.to_channel(post_id, message) if action == reels.CALLBACK
                  else reels.verdict(action, post_id, admin) if action in (reels.OK, reels.FIX)
                  else handle(action, post_id))
        telegram.answer_callback(query["id"], result)
        # Вышедший или удалённый пост — в git сразу, а не через десять минут:
        # ежечасный выход релизов (publish --releases) берёт очередь из git
        # и иначе выпустил бы тот же пост второй раз или удалённый.
        if action in ("pub", "del", reels.CALLBACK, reels.OK, reels.FIX):
            push_state()

        # Не вышло — кнопки остаются: нажать ещё раз проще, чем искать пост заново.
        if message.get("message_id") and not result.startswith("Ошибка"):
            telegram.edit_markup(admin, message["message_id"], None)

        print(f"  {post_id}: {result}")
        handled += 1

    if touch is not None and not dry_run:
        try:
            if json.dumps(touch, sort_keys=True) != before:
                touch_save(touch)
        except Exception as exc:  # noqa: BLE001 — отметки не держат разбор событий; в лог — без id
            log.error("Отметки действий не записаны: %s", type(exc).__name__)
    return handled, served, last_id


def publish_shift() -> None:
    """Выход постов — из дежурства, а не по крону.

    Крон publish.yml занимал общую группу state-write, где GitHub держит только
    один ожидающий запуск: выход релиза в :50 вытеснял из очереди сбор новинок
    или срочные новости, и находка опаздывала на шесть часов. Обычные слоты
    GitHub и вовсе создавал через раз: 13.09.2026 из четырёх вышел один.
    Дежурство идёт почти без дыр и так публикует по кнопке и пушит состояние,
    а когда пора — считают publish.release_due и publish.due по журналу публикаций.

    Сначала релиз: он свежий, а обычный пост вечнозелёный. Обычный пост — только
    в канал: владельцу на утверждение журнал не пишется, и due слал бы ему
    по посту каждые 10 минут. Крона у publish.yml больше нет: два публикатора
    на одной очереди выпустили бы один пост дважды.

    Поломка выхода смену не роняет: бот важнее одного поста, следующий заход
    через PUSH_EVERY попробует снова.
    """
    target = os.environ.get("PUBLISH_TARGET", "admin")
    # Бит недели — первым (bity.air, по понедельникам): так он забирает единственный звук дня
    # (publish.hushed); в воскресенье вечером тем же местом выходит итог недели (otbor.final).
    # Следом в тот же заход ничего не выходит — два поста подряд в ленте ни к чему.
    if target == "channel":
        try:
            if beat := bity.air() or otbor.final():
                print(f"Выход бита недели: {beat} → {target}")
                return
        except Exception as exc:  # noqa: BLE001 — бит не держит выход остальных постов
            log.error("Выход бита недели не удался: %s", exc)
        try:  # СОВЕТ НЕДЕЛИ: по четвергам, после бита — второй звук в день ему не достаётся (publish.hushed)
            from . import sovet

            if flaw := sovet.air():
                print(f"Выход совета недели: {flaw} → {target}")
                return
        except Exception as exc:  # noqa: BLE001 — совет не держит выход остальных постов
            log.error("Выход совета недели не удался: %s", exc)
        try:  # ПАМЯТКА: по средам и субботам, вместо поста о релизе — его в эти сутки держит publish.release_due
            from . import pamyatka

            if memo := pamyatka.air():
                print(f"Выход ПАМЯТКИ: {memo} → {target}")
                return
        except Exception as exc:  # noqa: BLE001 — памятка не держит выход остальных постов
            log.error("Выход ПАМЯТКИ не удался: %s", exc)
    if target == "channel":
        try:
            if track := skleyka.doposle_air():
                print(f"Выход ДО И ПОСЛЕ: трек {track} → {target}")
                return
        except Exception as exc:  # noqa: BLE001 — ролик не держит выход остальных постов
            log.error("Выход ДО И ПОСЛЕ не удался: %s", exc)
    try:
        otbor.shift(target)
    except Exception as exc:  # noqa: BLE001 — отбор не держит выход остальных постов
        log.error("Выход отбора не удался: %s", exc)
    path = publish.next_post(releases=True, skip_sent=target == "admin") if publish.release_due() else None
    label = "Выход релиза"
    if path is None and target == "channel":
        path, label = publish.next_post(), "Выход поста"
        if path is not None and not publish.due(state.read_json(path, {})):
            path = None
    if path is None:
        return
    try:
        publish.deliver(state.read_json(path, {}), path, target)
    except telegram.TelegramError as exc:
        log.error("%s не удался (%s): %s", label, path.name, exc)
        return
    print(f"{label}: {path.name} → {target}")


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
    # ДВОЙНИК заработал: тем, кто пришёл на «делаем» и ждёт, бот обещал написать
    # первым. Список одноразовый — рассылка удаляет его, и дальше проверка пустая.
    try:
        svedenie.notify_waiting()
    except Exception as exc:  # noqa: BLE001 — рассылка не держит дежурство
        log.error("Ждущие ДВОЙНИКА не оповещены: %s", exc)
    # Сведение, оборванное концом прошлой смены, доделывает эта (src/skleyka.py).
    try:
        skleyka.resume()
    except Exception as exc:  # noqa: BLE001 — сведение не держит дежурство
        log.error("Сведение прошлой смены не поднято: %s", exc)
    offset = state.read_json(OFFSET_FILE, {"offset": 0}).get("offset", 0)
    limits = service.load_state()
    total_handled, total_served = 0, 0

    print(f"Дежурство {minutes} мин. Бот отвечает сразу.")

    next_push = time.monotonic() + PUSH_EVERY

    while time.monotonic() < deadline:
        # Сведение идёт отдельным процессом: здесь — только очередь. Пока она не пуста,
        # Telegram опрашивается чаще, иначе готовый трек ждал бы следующую до 25 секунд.
        try:
            updates = telegram.get_updates(offset=offset, timeout=_ticks())
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
            publish_shift()
            urgent.shift()
            push_state()
            next_push = time.monotonic() + PUSH_EVERY
            # Идёт или ждёт сведение — смена дежурит дальше: иначе finish() до пяти минут
            # ждал бы его без опроса, и кнопки у всех крутились бы впустую. Открытая заявка — нет:
            # она в хранилище, её доведёт свежая смена, а 01.10.2026 пустая заявка от каждого
            # /svedenie продлевала старую смену на полчаса, и новая кнопка не доходила до бота.
            if code_changed() and not skleyka.busy(drafts=False) and not bity.busy() and not ocenka.busy():
                print("Код бота обновился — смена уступает место свежей.")
                break

    # Идущее сведение смена дожидается: человек ждёт трек, а следующая смена начнёт его заново.
    try:
        skleyka.finish()
    except Exception as exc:  # noqa: BLE001
        log.error("Сведение на конце смены не дождалось: %s", exc)
    try:
        ocenka.finish()
    except Exception as exc:  # noqa: BLE001
        log.error("Оценка на конце смены не дождалась: %s", exc)
    try:
        from . import pamyatka

        pamyatka.finish()  # текст на проверке дочитывается: машина с концом задания гасит процессы
    except Exception as exc:  # noqa: BLE001
        log.error("Проверка текста на конце смены не дождалась: %s", exc)
    push_state()
    print(f"Дежурство окончено. Нажатий: {total_handled}. Разборов: {total_served}.")
    return 0


_stuck_since = 0.0  # с какого момента очередь сведения срывается без единого удачного круга


def _ticks() -> int:
    """Двигает очереди сведения и роликов к битам; ответ — сколько секунд ждать Telegram.

    Очереди — каждая в своём try: сбой сведения иначе стопорил ролики к битам.
    """
    global _stuck_since
    try:
        if skleyka.tick():
            push_state()  # напоминание клиенту ушло — отметка о нём не должна потеряться со сменой
        wait = SKLEYKA_POLL if skleyka.busy() else POLL_TIMEOUT
        _stuck_since = 0.0
    except Exception as exc:  # noqa: BLE001 — сведение не держит дежурство
        log.error("Очередь сведения сорвалась: %s", exc)
        wait = POLL_TIMEOUT
        _stuck_since = _stuck_since or time.monotonic()
        if time.monotonic() - _stuck_since >= STUCK_AFTER:
            _alarm(f"Очередь сведения стоит {STUCK_AFTER // 60} мин.: {exc}")
    try:
        ocenka.tick()  # замер готового трека — отдельным процессом, как сведение
    except Exception as exc:  # noqa: BLE001 — оценка не держит дежурство
        log.error("Очередь оценки сорвалась: %s", exc)
    try:
        bity.tick()  # ролик к биту ПЛЁНКИ — тоже отдельным процессом
    except Exception as exc:  # noqa: BLE001 — ролик к биту не держит дежурство
        log.error("Очередь роликов к битам сорвалась: %s", exc)
    return wait


def _alarm(text: str) -> None:
    """Строка владельцу о поломке — не чаще раза в сутки: смен за день несколько, и каждая написала бы своё."""
    today = state.now().strftime("%Y-%m-%d")
    if state.read_json(STUCK_FILE, {}).get("day") == today:
        return
    state.write_json(STUCK_FILE, {"day": today})
    try:
        telegram.send_message(config.secret("TELEGRAM_ADMIN_ID"), text[:500])
    except Exception as exc:  # noqa: BLE001 — сигнал о поломке не роняет дежурство
        log.error("Владельцу не написано: %s", exc)


# Код дежурства: поменялся — идущая смена устарела. Список повторяет paths
# в moderate.yml, по которым пуш ставит в очередь свежую смену.
CODE = ("src/", "requirements.txt", ".github/workflows/moderate.yml")

# Коммит, с которым смена стартовала, — HEAD на момент импорта, до первого push_state.
# Не GITHUB_SHA: checkout берёт свежую main (ref: github.ref_name), и в неглубокой
# копии коммита, на котором запуск встал в очередь, нет вовсе — diff отвечал 128,
# и 18.09.2026 смена четыре часа не уступала место новому коду.
STARTED_AT = (subprocess.run(["git", "rev-parse", "HEAD"], cwd=config.ROOT, capture_output=True, text=True)
              .stdout.strip() if os.environ.get("GITHUB_ACTIONS") else "")


def code_changed() -> bool:
    """Подтянул ли push_state код новее того, с которым смена стартовала.

    Процесс держит в памяти модули, загруженные на старте, и новый код на диске
    для него не существует. Уступить место свежей смене — единственный способ
    до него дойти.
    """
    if not STARTED_AT:
        return False  # локально дежурство перезапускают руками
    diff = subprocess.run(["git", "diff", "--quiet", STARTED_AT, "HEAD", "--", *CODE], cwd=config.ROOT)
    if diff.returncode not in (0, 1):
        log.error("Код смены не сверить с %s: git diff вернул %s", STARTED_AT, diff.returncode)
    return diff.returncode == 1  # 0 — без изменений


def push_state() -> None:
    """Отправляет состояние в репозиторий прямо посреди дежурства.

    На GitHub машина после запуска исчезает, а состояние живёт только в git.
    Если дежурство оборвут — а его обрывают, запуск ограничен по времени, —
    несохранённый offset заставит бота ответить на те же сообщения второй раз.
    Локально ничего не делает: там файлы никуда не денутся.
    """
    if not os.environ.get("GITHUB_ACTIONS"):
        return

    # content/ тоже: кнопки, выходы и присланные треки меняют посты, а генерация
    # и автопилот точности берут их из git, а не с диска дежурства. Без этого удалённый
    # кнопкой пост до конца смены оставался бы в очереди для генерации.
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
            if command[1] == "add":
                # Файла нет на этой машине: загадку прослушки создаёт другая,
                # и появится он здесь только через pull. Выход на add отрезал бы
                # его навсегда — 12.09.2026 викторина так и ушла в канал.
                continue
            if command[1] == "pull":
                # Конфликт оставляет ребейз висеть: дерево застревает посреди
                # чужих коммитов до конца смены, и всё, что дежурство запишет
                # дальше, не уйдёт. Откат возвращает свой коммит и спрятанное.
                # Но коммит смены остаётся, и та же попытка конфликтует снова:
                # 29.09.2026 — 29 неудач подряд за четыре часа, состояние потеряно,
                # свежий код до бота не дошёл. Поэтому повтор — с версией смены
                # в спорных местах (в ребейзе theirs — это накладываемый, свой коммит).
                subprocess.run(["git", "rebase", "--abort"], cwd=cwd, capture_output=True)
                retry = subprocess.run([*command[:3], "-X", "theirs", *command[3:]],
                                       cwd=cwd, capture_output=True, text=True)
                if retry.returncode == 0:
                    log.warning("git pull: конфликт решён версией смены")
                    continue
                # Удалённый с той стороны файл -X theirs не решает.
                subprocess.run(["git", "rebase", "--abort"], cwd=cwd, capture_output=True)
                log.error("git pull: ребейз не сошёлся и откачен: %s", retry.stderr.strip()[:200])
            return


def _selftest() -> int:
    """Без сети: что считается треком, от кого и какого размера; под какой
    пересылкой поста в чат обсуждений встаёт первый комментарий.

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

    # Чужой файл в личке — трек в отбор; в группе — мимо, как и был.
    def routed(message: dict) -> str:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            process([{"update_id": 1, "message": message}], {}, "1", True, 0)
        return out.getvalue()

    private = {"id": 2, "type": "private"}
    assert "файл в отбор" in routed({**reply(2, video=video), "chat": private})
    assert "файл в отбор" not in routed(reply(2, chat=-100, video=video))
    # Владелец с ответом на запрос — приём трека к посту, а не отбор.
    assert "трек в ответ на 562" in routed({**reply(1, video=video), "chat": {"id": 1, "type": "private"}})

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

    # Обложка iTunes: хвосты магазина не мешают узнать тот же трек, другой — не он.
    assert _song_name("Сияй (feat. Скриптонит) - Single") == _song_name("Сияй") == "сияй"
    assert _song_name("Sorry Mama - Single") == "sorry mama" != _song_name("Sorry")

    from unittest import mock

    # Текст ответом на запрос трека — «жду аудиофайл», а не разбор вкуса.
    # Ответ на что-то другое идёт сервису, как раньше.
    with tempfile.TemporaryDirectory() as tmp, mock.patch.object(config, "QUEUE", Path(tmp)):
        state.write_json(Path(tmp) / "r.json", {"track_request": {"message_id": 562}})
        text = reply(1, text="https://youtu.be/x")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            process([{"update_id": 1, "message": text},
                     {"update_id": 2, "message": {**text, "reply_to_message": {"message_id": 9}}}],
                    {}, "1", True, 0)
        assert out.getvalue().count("не файл в ответ на запрос трека") == 1, out.getvalue()

    # Трек к вышедшему посту (Mac спал до выхода): встаёт первым комментарием в запомненную
    # ветку, а пост правится — publish.edit ставит строку «▸ Или в комментариях ↓».
    # Пост без ветки трек не берёт: положить его некуда.
    with (tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as queue,
          mock.patch.object(config, "ARCHIVE", Path(tmp)), mock.patch.object(config, "QUEUE", Path(queue))):
        sent, edited = [], []
        post = {"rubric": "release", "artist": "A", "track": "T", "track_request": {"message_id": 562},
                "thread": {"chat": -200, "message_id": 31}, "message": {"chat": -100, "message_id": 150}}
        state.write_json(Path(tmp) / "r.json", post)
        with (mock.patch.object(telegram, "send_chat_action", lambda *a, **k: None),
              mock.patch.dict(globals(), normalize_track=lambda *a: (b"x", 100, None)),
              mock.patch.object(telegram, "send_audio",
                                lambda chat, audio, caption, **kw: sent.append((chat, kw.get("reply_to")))
                                or {"audio": {"file_id": "F"}}),
              mock.patch.object(comments, "ask", lambda *a: "вопрос"),
              mock.patch.object(publish, "edit", edited.append)):
            assert attach_track(reply(1, audio={"file_id": "a", "mime_type": "audio/mpeg"}), "1") == ""
            assert sent == [("1", None), (-200, 31)], sent
            assert edited and edited[0]["full_track_file_id"] == "F"
            assert state.read_json(Path(tmp) / "r.json", {})["full_track_file_id"] == "F"
            # Второй трек к тому же посту и пост без ветки — отказ владельцу, без отправки.
            sent.clear()
            assert "уже вышел" in attach_track(reply(1, audio={"file_id": "a"}), "1") and not sent
            state.write_json(Path(tmp) / "r.json", {k: v for k, v in post.items() if k != "thread"})
            assert "уже вышел" in attach_track(reply(1, audio={"file_id": "a"}), "1") and not sent
            # Разбор: треков два, запрос у каждого свой — файл встаёт своему треку и уходит
            # в ветку без вопроса: он задан вместе со ссылками на площадки (comments.seed).
            captions = []
            lineage = {"rubric": "lineage", "artist": "A", "thread": {"chat": -200, "message_id": 31},
                       "listen": [{"artist": "Корень", "track": "R", "track_request": {"message_id": 561}},
                                  {"artist": "Наследник", "track": "H", "track_request": {"message_id": 562}}]}
            state.write_json(Path(tmp) / "r.json", lineage)
            with mock.patch.object(telegram, "send_audio", lambda chat, audio, caption, **kw:
                                   captions.append((chat, caption)) or {"audio": {"file_id": "F"}}):
                assert attach_track(reply(1, audio={"file_id": "a", "mime_type": "audio/mpeg"}), "1") == ""
            assert captions[1] == (-200, "") and "Наследник — H" in captions[0][1], captions
            assert len(edited) == 1, edited  # пост разбора не правится: строка в нём уже есть
            saved = state.read_json(Path(tmp) / "r.json", {})["listen"]
            assert "full_track_file_id" not in saved[0] and saved[1]["full_track_file_id"] == "F", saved
    print("приём трека: все проверки прошли")

    # Конфликт при подтягивании: ребейз откатывается, а не висит до конца смены.
    with tempfile.TemporaryDirectory() as tmp:
        def git(cwd, *args):
            subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                           cwd=cwd, check=True, capture_output=True)
        origin, mine, theirs = (Path(tmp) / name for name in ("origin", "mine", "theirs"))
        git(tmp, "init", "-q", "--bare", "-b", "main", str(origin))
        git(tmp, "clone", "-q", str(origin), str(theirs))
        for text, message in (("0", "начало"), ("1", "их")):
            (theirs / "offset.json").write_text(text)
            git(theirs, "add", ".")
            git(theirs, "commit", "-qm", message)
            if message == "начало":
                git(theirs, "push", "-q", "origin", "HEAD:main")
                git(tmp, "clone", "-q", str(origin), str(mine))
        git(theirs, "push", "-q", "origin", "HEAD:main")
        (mine / "offset.json").write_text("2")
        git(mine, "config", "user.name", "t")
        git(mine, "config", "user.email", "t@t")
        with contextlib.redirect_stderr(io.StringIO()):
            _push_repo(mine, ["."], "моё")
        assert not (mine / ".git" / "rebase-merge").exists()
        assert not (mine / ".git" / "rebase-apply").exists()
        assert (mine / "offset.json").read_text() == "2"
        sent = subprocess.run(["git", "show", "main:offset.json"], cwd=origin, capture_output=True, text=True)
        assert sent.stdout == "2", sent  # версия смены дошла до сервера, а не ждёт следующей попытки
        # Их коммит не потерян: версия смены легла поверх него.
        assert subprocess.run(["git", "rev-list", "--count", "main"], cwd=origin,
                              capture_output=True, text=True).stdout.strip() == "3"
    print("подтягивание: конфликт решён версией смены, ребейз не висит, состояние ушло")

    # Сбой сведения не стопорит ролики к битам, а стоящая очередь — одна строка владельцу в сутки.
    with tempfile.TemporaryDirectory() as tmp:
        called, told, clock = [], [], [1000.0]

        def broken():
            raise RuntimeError("сломано")
        with (mock.patch.object(skleyka, "tick", broken),
              mock.patch.object(bity, "tick", lambda: called.append(1)),
              mock.patch.object(telegram, "send_message", lambda chat, text, **kw: told.append(text)),
              mock.patch.object(config, "secret", lambda name, required=True: "1"),
              mock.patch.object(time, "monotonic", lambda: clock[0]),
              mock.patch(f"{__name__}.STUCK_FILE", Path(tmp) / "alarm.json"),
              mock.patch(f"{__name__}._stuck_since", 0.0),
              contextlib.redirect_stderr(io.StringIO())):
            assert _ticks() == POLL_TIMEOUT and called == [1] and not told
            clock[0] += STUCK_AFTER
            _ticks()
            clock[0] += STUCK_AFTER
            _ticks()
            assert len(called) == 3 and len(told) == 1 and "сломано" in told[0], (called, told)
            # Удачный круг гасит счёт: следующий сбой — снова первый.
            with mock.patch.object(skleyka, "tick", lambda: None), mock.patch.object(skleyka, "busy", lambda: True):
                assert _ticks() == SKLEYKA_POLL
            state.write_json(Path(tmp) / "alarm.json", {})
            _ticks()
            assert len(told) == 1, told
    print("очереди: сбой сведения ролики к битам не стопорит, владельцу — одна строка")

    # Загадку прослушки создаёт другая машина: у дежурства файла ещё нет,
    # add на нём падает, а подтянуть его всё равно надо.
    with tempfile.TemporaryDirectory() as tmp:
        origin, mine, theirs = (Path(tmp) / name for name in ("origin", "mine", "theirs"))
        git(tmp, "init", "-q", "--bare", "-b", "main", str(origin))
        git(tmp, "clone", "-q", str(origin), str(theirs))
        for name in ("README", "quiz.json"):
            (theirs / name).write_text("{}")
            git(theirs, "add", ".")
            git(theirs, "commit", "-qm", name)
            git(theirs, "push", "-q", "origin", "HEAD:main")
            if name == "README":
                git(tmp, "clone", "-q", str(origin), str(mine))
        with contextlib.redirect_stderr(io.StringIO()):
            _push_repo(mine, ["quiz.json"], "загадка")
        assert (mine / "quiz.json").exists()
    print("подтягивание: чужой новый файл доезжает, хотя add на нём упал")

    # Пересылки поста канала в чат обсуждений: под обычным постом первым
    # комментарием идёт вопрос, под постом с полным треком — сам трек плеером,
    # под отрывком прослушки — викторина.

    def forward(message_id: int, **body) -> dict:
        return {"update_id": message_id, "message": {
            "message_id": message_id, "chat": {"id": -1002}, "is_automatic_forward": True,
            "sender_chat": {"id": -1001, "type": "channel"}, **body,
        }}

    said, played, riddles = [], [], []
    tmp = tempfile.TemporaryDirectory()
    archive, posted = Path(tmp.name) / "archive", Path(tmp.name) / "posted.json"
    real = config.ARCHIVE, config.POSTED_FILE
    config.ARCHIVE, config.POSTED_FILE = archive, posted

    def published(post: dict) -> None:
        """Журнал публикаций и архив: по ним первый комментарий узнаёт пост."""
        state.write_json(archive / "last-release.json", post)
        state.write_json(posted, {"items": [{"file": "last-release.json", "rubric": "release",
                                             "published_at": state.iso()}]})

    def run(*updates: dict) -> None:
        with (
            mock.patch.dict(os.environ, {"TELEGRAM_CHANNEL_ID": "-1001"}),
            mock.patch.object(telegram, "send_message",
                              lambda chat, text, reply_to=None, **_: said.append(reply_to)),
            mock.patch.object(telegram, "send_audio",
                              lambda chat, audio, caption, reply_to=None, **_: played.append((audio, reply_to))),
            mock.patch.object(quiz, "attach", lambda message: riddles.append(message["message_id"])),
        ):
            process(list(updates), {}, "1", False, 0)

    try:
        post = forward(11, photo=[{"file_id": "p"}], caption="SMOKY MO ВЫПУСТИЛ СИНГЛ")
        riddle = forward(12, audio={"file_id": "r"}, caption="СЛЕПАЯ ПРОСЛУШКА\n\n30 секунд трека")
        # Трека к посту о релизе нет — вопроса нет (владелец, 18.09.2026), пост запоминает
        # ветку: трек, пришедший позже, встанет туда первым (attach_track).
        published({"rubric": "release"})
        run(post, riddle)
        assert said == [] and played == [] and riddles == [12], (said, played, riddles)
        assert state.read_json(archive / "last-release.json", {})["thread"] == {"chat": "-1002", "message_id": 11}
        # Трек есть — он и открывает ветку, плеером в ответ на ту же пересылку.
        said.clear()
        published({"rubric": "release", "full_track_file_id": "ID"})
        run(post)
        assert played == [("ID", 11)] and said == [], (played, said)
    finally:
        config.ARCHIVE, config.POSTED_FILE = real
        tmp.cleanup()
    print("первый комментарий: вопрос под обычным постом, полный трек — под релизом")

    # Вступления и уходы: в журнал — время и направление, id человека туда не попадает; ушедшему
    # после сведения — часы с готового трека; чат обсуждений и смена прав — мимо журнала.
    def moved(was: str, now: str, kind: str = "channel", user: int = 77) -> dict:
        return {"chat": {"id": -100, "type": kind}, "from": {"id": user},
                "date": int(datetime(2026, 10, 3, 13, 0, tzinfo=timezone.utc).timestamp()),
                "old_chat_member": {"user": {"id": user}, "status": was},
                "new_chat_member": {"user": {"id": user}, "status": now}}

    tracks = {"tracks": {"a": {"chat": "77", "done": "2026-10-03T10:00:00+00:00"},
                         "b": {"chat": "77", "done": "2026-10-03T12:00:00+00:00"}, "c": {"chat": "5"}}}
    with (tempfile.TemporaryDirectory() as folder,
          mock.patch.object(config, "MEMBERS_FILE", Path(folder) / "members.jsonl"),
          mock.patch.object(config, "TOUCH_FILE", Path(folder) / "touch.json"),
          mock.patch.object(skleyka, "load", lambda: tracks),
          mock.patch.object(state, "now", lambda: datetime(2026, 10, 3, 13, 30, tzinfo=timezone.utc)),
          contextlib.redirect_stdout(io.StringIO())):
        assert member_row(moved("left", "member")) == {"at": "2026-10-03T13:00:00+00:00", "way": "in"}
        assert member_row(moved("member", "left")) == {"at": "2026-10-03T13:00:00+00:00", "way": "out", "track_hours": 1.5}
        assert member_row(moved("member", "kicked", user=9)) == {"at": "2026-10-03T13:00:00+00:00", "way": "out"}
        assert member_row(moved("member", "administrator")) is None, "смена прав — не вступление"
        assert member_row(moved("member", "left", kind="supergroup")) is None, "чат обсуждений — не канал"
        events = [{"update_id": 4, "chat_member": moved("left", "member")},
                  {"update_id": 5, "chat_member": moved("member", "left")},
                  {"update_id": 6, "chat_member": moved("member", "left", kind="supergroup")}]
        assert process(events, {}, "1", True, 0) == (0, 0, 7) and not config.MEMBERS_FILE.exists(), "сухой прогон не пишет"
        assert process(events, {}, "1", False, 0) == (0, 0, 7)
        written = config.MEMBERS_FILE.read_text()
        assert [row["way"] for row in state.read_jsonl(config.MEMBERS_FILE)] == ["in", "out"] and "77" not in written, written
        assert state.read_json(config.TOUCH_FILE, None) == {}, "пришёл и ушёл в одной пачке — время вступления снято"

        # Последнее действие в боте: метка без личного — ни текста, ни кодов, ни номеров; владелец и чат обсуждений мимо.
        def wrote(text: str = "", user: int = 77, kind: str = "private", **body) -> dict:
            return {"message": {"chat": {"id": user, "type": kind}, "from": {"id": user}, "text": text, **body}}

        def pressed(data: str, user: int = 77) -> dict:
            return {"callback_query": {"id": "q", "from": {"id": user}, "data": data,
                                       "message": {"chat": {"id": user, "type": "private"}}}}

        labels = [(touched(update, "1") or ("", ""))[1] for update in (
            wrote("/start beat_ab12"), wrote("/start sv_ab12cd34"), wrote("/start 79161234567"), wrote("/otbor@plenka_bot"),
            wrote("/vopros звёзды не дошли, мой ник @lilpi"), wrote("/lilpi"), wrote("Bones — Dirt"),
            wrote("вот https://music.yandex.ru/album/1/track/2"), wrote(audio={"file_id": "F"}), wrote(voice={"file_id": "V"}),
            wrote(web_app_data={"data": "12.5"}), wrote(successful_payment={"invoice_payload": "hand:t5"}),
            pressed("s:beat:ab12"), pressed("s:sk:hg4070"), pressed("s:4070:x"), {"pre_checkout_query": {"from": {"id": 77}}},
            wrote("/otbor", user=1), pressed("pub:post", user=1), wrote("привет", kind="supergroup"), {"poll_answer": {}})]
        assert labels == ["/start beat", "/start sv", "/start", "/otbor", "/vopros", "текст", "текст", "ссылка", "файл", "голос",
                          "мини-приложение", "оплата", "s:beat", "s:sk", "кнопка", "оплата", "", "", "", ""], labels
        # Нажал кнопку и ушёл одной пачкой: отметка не теряется и время вступления не затирает; сухой прогон не пишет.
        came = {"update_id": 1, "chat_member": moved("left", "member")}
        left = [{"update_id": 2, **pressed("s:sk:u")}, {"update_id": 3, "chat_member": moved("member", "left")}]
        assert process([came], {}, "1", False, 0) == (0, 0, 2)
        assert state.read_json(config.TOUCH_FILE, {}) == {"77": {"in": "2026-10-03T13:00:00+00:00"}}
        with (mock.patch.object(service, "handle_callback", lambda query, limits: None),
              mock.patch.object(skleyka, "unkey", lambda message: None)):
            assert process(left, {}, "1", True, 0)[2] == 4 and "at" not in state.read_json(config.TOUCH_FILE, {})["77"]
            assert process(left, {}, "1", False, 0)[2] == 4
        assert state.read_json(config.TOUCH_FILE, {}) == {"77": {"at": "2026-10-03T13:30:00+00:00", "what": "s:sk"}}
        gone = list(state.read_jsonl(config.MEMBERS_FILE))[-1]
        assert gone == {"at": "2026-10-03T13:00:00+00:00", "way": "out", "track_hours": 1.5,
                        "last": "s:sk", "last_hours": 0.0, "stay_hours": 0.5}, gone
        assert "77" not in config.MEMBERS_FILE.read_text(), "id человека — только в приватном файле"
        # Вернувшемуся строка называет прежнее действие; отметка старше TOUCH_DAYS при записи уходит.
        old = {"5": {"at": "2026-09-01T00:00:00+00:00", "what": "текст"}, "77": {"at": "2026-10-03T10:30:00+00:00", "what": "/bity"}}
        assert member_row(moved("left", "member"), old) == {"at": "2026-10-03T13:00:00+00:00", "way": "in",
                                                            "last": "/bity", "last_hours": 3.0}
        touch_save(old)
        assert list(state.read_json(config.TOUCH_FILE, {})) == ["77"]
        # Сбой отметки разбор не роняет: события разобраны, строка журнала записана, в логе — ни id, ни текста.
        failed = []
        with mock.patch.object(log, "error", lambda *args: failed.append(args)):
            with mock.patch.object(state, "read_json", lambda path, default: {}[str(path)]):
                assert process([came], {}, "1", False, 0) == (0, 0, 2)
            with mock.patch.dict(globals(), {"touched": lambda update, admin: {}[update["chat_member"]["from"]["id"]],
                                             "touch_save": lambda touch: {}[next(iter(touch))]}):
                assert process([{"update_id": 3, "chat_member": moved("member", "left")}], {}, "1", False, 0) == (0, 0, 4)
            assert member_row(moved("member", "left", user=9), {"9": "битая"}) == {"at": "2026-10-03T13:00:00+00:00", "way": "out"}
        assert [row["way"] for row in state.read_jsonl(config.MEMBERS_FILE)][-2:] == ["in", "out"]
        assert [args[1] for args in failed] == ["KeyError"] * 3 + ["AttributeError"] and "77" not in str(failed), failed
    # Без строки в allowed_updates Telegram события не шлёт вовсе — прежние (платежи, опросы) на месте.
    with mock.patch.object(telegram, "_call", lambda method, payload: json.loads(payload["allowed_updates"])):
        asked = telegram.get_updates()
    assert set(asked) == {"message", "callback_query", "poll_answer", "pre_checkout_query", "chat_member"}, asked
    print("журнал канала: пришёл и ушёл — время и направление без id, часы с готового трека, чат обсуждений мимо; "
          "последнее действие в боте — меткой без текста и кодов, сколько пробыл в канале, сбой отметки разбор не роняет")

    # Выход из дежурства: бит владельца первым и один; дальше релиз; обычный пост — только в канал и когда пора.
    delivered = []
    for release_due, due, target, beat in ((True, True, "channel", ""), (False, True, "channel", ""),
                                           (False, False, "channel", ""), (False, True, "admin", "3"),
                                           (True, True, "channel", "3")):
        with (mock.patch.object(bity, "air", lambda: beat),
              mock.patch.object(publish, "release_due", lambda: release_due),
              mock.patch.object(publish, "due", lambda post: due),
              mock.patch.object(publish, "next_post", lambda releases=False, **_: Path(f"{releases}.json")),
              mock.patch.object(publish, "deliver", lambda post, path, to: delivered.append((path.name, to))),
              mock.patch.object(state, "read_json", lambda path, default: {}),
              mock.patch.dict(os.environ, {"PUBLISH_TARGET": target}),
              contextlib.redirect_stdout(io.StringIO())):
            publish_shift()
    assert delivered == [("True.json", "channel"), ("False.json", "channel")], delivered
    print("выход из дежурства: бит владельца первым и один, дальше релиз, обычный пост — в канал по часам")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Обработка событий бота")
    parser.add_argument(
        "--serve",
        type=int,
        metavar="МИНУТ",
        help="дежурить указанное время, отвечая сразу",
    )
    parser.add_argument("--selftest", action="store_true", help="проверить приём трека и первый комментарий без сети")
    args = parser.parse_args()

    if args.selftest:
        return _selftest()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    config.load_dotenv()

    if not args.serve:
        # Запуск без флагов раньше разбирал накопившееся — вторым опросчиком рядом с дежурством.
        parser.error("нужен --serve МИНУТ или --selftest")
    return serve(args.serve)


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
