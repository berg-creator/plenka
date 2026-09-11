"""Ролики с живым голосом владельца: сценарий по фразам → голосовые → пакет для заливки.

Формат для YouTube Shorts, TikTok и VK Клипов. Заливает владелец сам: групповым
ключом ВКонтакте видео не залить (см. clips.deliver), у TikTok открытой заливки
нет вовсе. Поэтому автоматика заканчивается пакетом в личке — ролик, превью
и текст полей, где каждое поле копируется одним касанием.

Голос живой, а не синтез (src/host.py), по тому же доводу, по которому из кадра
убрали нарисованную ведущую: машинное площадки метят, а живого человека
в этом не обвинить.

Путь одного ролика:

1. Сценарий (content/reels/<id>.json, бриф автора — prompts/reels.md) приходит
   пушем в ветку claude/reels-*. Облачный автор в main пушить не может, и ветка
   служит почтовым ящиком: воркфлоу reels.yml забирает сценарий в приватное
   хранилище, рассылает фразы и удаляет ветку.
2. Фразы уходят владельцу по одной, на каждую он отвечает голосовым. Сообщение
   на фразу, а не одно на весь текст: ответ на конкретное сообщение сам говорит,
   какой это кадр. Одно длинное голосовое пришлось бы резать по паузам, то есть
   гадать, где кончилась фраза, а неудачную фразу — перезаписывать с остальными.
3. Дубли лежат в приватном хранилище (STATE_DIR/reels/<id>/): голос человека —
   ровно то, чему в открытом репозитории не место.
4. Последний дубль запускает сборку отдельным запуском воркфлоу. Не в дежурстве:
   ffmpeg и сток — это минуты, а дежурство — единственный опросчик бота,
   и всё это время бот молчал бы.

Сборка — те же примитивы, что у клипов (src/clips.py): надписи, камкордерная
обработка, narrate с папкой записанных фраз, склейка. Своё здесь только то,
чего у клипов нет: кадр на каждую строку сценария, мем целиком на вертикальном
холсте и первый кадр без затемнения — он же превью.

    python -m src.reels --check content/reels/20260914-kanye.json    проверка без сети
    python -m src.reels --send content/reels/20260914-kanye.json --dry-run
    python -m src.reels --preview content/reels/20260914-kanye.json --voice ПАПКА
    python -m src.reels --build 20260914-kanye --dry-run             собрать, пакет в терминал
    python -m src.reels --selftest
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import os
import random
import re
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

# Только лёгкое на уровне модуля: --check зовёт облачный автор перед пушем,
# и Pillow, ffmpeg или ключи ему для проверки полей не нужны. Сборка и Telegram
# подтягиваются там, где используются.
from . import config, state

log = logging.getLogger("reels")

KINDS = ("face", "stock", "meme", "card")

# Название YouTube режет на ста знаках. Описание на площадках коротких роликов —
# подпись под видео; держим его в рамке подписи Telegram, 1024 знака: длиннее
# под роликом всё равно не читают, а пакет владельцу гарантированно влезает
# в одно сообщение. Теги YouTube принимает до пятисот знаков на все разом.
TITLE_MAX = 100
DESCRIPTION_MAX = 1024
TAGS_MAX = 500
PAUSE_MAX = 5.0

ID_FORMAT = re.compile(r"\d{8}-[a-z0-9-]+")
SLOT_FORMAT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}[+-]\d{2}:\d{2}")
HASHTAGS_AT_END = re.compile(r"(#\w+\s*)+$")

TODAY = "сегодня до 21:00 МСК"

# Нижняя граница кадра под фразой. Настоящую длину задаёт дубль (clips.narrate),
# эта нужна, чтобы и без дубля кадр было видно в превью.
SAY_SECONDS = 1.5
# До скольких знаков надпись идёт крупным кеглем.
BIG_TEXT = 20
# Основа холста под мем и карточку — светлее, чем кажется нужным: камкордерная
# обработка поверх давит яркость, и сразу тёмный цвет стал бы чёрной дырой
# (тот же довод у footage.procedural).
DARK = (46, 41, 36)
# Мем встаёт ниже счётчика кассеты и выше надписи.
MEME_TOP = 240


# --- проверка -------------------------------------------------------------


def _filled(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _slot(value) -> bool:
    if not isinstance(value, str) or not SLOT_FORMAT.fullmatch(value):
        return False
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


def _artist_names() -> set[str]:
    return {a.get("name", "") for a in state.read_json(config.ARTISTS_FILE, {}).get("artists", [])}


def _screen_problems(screen, where: str) -> list[str]:
    if not isinstance(screen, dict):
        return [f"{where}: нет screen — что в кадре"]
    kind = screen.get("kind")
    if kind not in KINDS:
        return [f"{where}: screen.kind «{kind}» — бывает только {', '.join(KINDS)}"]
    if any(field in screen and not isinstance(screen[field], str) for field in ("label", "text")):
        return [f"{where}: label и text — строки"]
    if kind == "face":
        name = screen.get("name")
        if not _filled(name):
            return [f"{where}: у face нет name"]
        if name not in _artist_names():
            # По этому имени ищется фотография: «Канье» вместо «Kanye West»
            # оставит кадр без лица, а чужое похожее имя — с чужим лицом.
            return [f"{where}: «{name}» нет в data/artists.json — имя ровно как там, или кадр stock/card"]
    elif kind == "stock" and not _filled(screen.get("query")):
        return [f"{where}: у stock нет query — запрос к стоку, по-английски"]
    elif kind == "meme":
        template = screen.get("template")
        if not _filled(template) or not (config.MEME_TEMPLATES / f"{template}.jpg").is_file():
            return [f"{where}: шаблона мема «{template}» нет в assets/meme/templates/"]
    elif kind == "card" and not _filled(screen.get("text")):
        return [f"{where}: у card нет text — надпись и есть кадр"]
    return []


def problems(script, name: str = "") -> list[str]:
    """Что не так со сценарием — понятными фразами. Пустой список — годен.

    Проверяется только то, что ломает конвейер или не пройдёт на площадке,
    и ничего, что требует сети: у облачного автора может не быть ни ключей,
    ни доступа наружу. Сверку фактов по источникам валидатор не заменяет —
    он требует источник, но прочитать его не может.
    """
    if not isinstance(script, dict):
        return ["сценарий — это JSON-объект"]
    errors = []

    reel_id = script.get("id")
    if not isinstance(reel_id, str) or not ID_FORMAT.fullmatch(reel_id):
        errors.append("id: вида ГГГГММДД-слово строчной латиницей, например 20260914-kanye")
    elif name and name != reel_id:
        errors.append(f"id «{reel_id}» не совпадает с именем файла «{name}.json»")

    if not _filled(script.get("topic")):
        errors.append("topic: нет темы")
    if script.get("publish") != "today" and not _slot(script.get("publish")):
        errors.append("publish: «today» или слот вида 2026-09-14T18:00+03:00")

    sources = script.get("sources")
    if not isinstance(sources, list) or not sources:
        errors.append("sources: нужен хотя бы один источник — ролик читают вслух, факт без источника не проходит")
    elif not all(isinstance(url, str) and url.startswith(("https://", "http://")) for url in sources):
        errors.append("sources: каждый источник — ссылка с http")

    title = script.get("title")
    if not _filled(title):
        errors.append("title: нет названия")
    elif len(title) > TITLE_MAX:
        errors.append(f"title: {len(title)} знаков, YouTube режет на {TITLE_MAX}")

    description = script.get("description")
    if not _filled(description):
        errors.append("description: нет описания")
    else:
        if len(description) > DESCRIPTION_MAX:
            errors.append(f"description: {len(description)} знаков, предел {DESCRIPTION_MAX}")
        if not HASHTAGS_AT_END.search(description.strip()):
            errors.append("description: в конце нужны хэштеги, например «… #фонк #рэп»")

    tags = script.get("tags")
    if not isinstance(tags, list) or not tags or not all(_filled(tag) for tag in tags):
        errors.append("tags: нужен список непустых строк")
    elif any("," in tag for tag in tags):
        errors.append("tags: запятая внутри тега — в пакете теги идут через запятую и разъедутся")
    elif len(", ".join(tags)) > TAGS_MAX:
        errors.append(f"tags: {len(', '.join(tags))} знаков вместе, YouTube принимает {TAGS_MAX}")

    lines = script.get("lines") if isinstance(script.get("lines"), list) else []
    if not any(isinstance(line, dict) and _filled(line.get("say")) for line in lines):
        errors.append("lines: нет ни одной фразы — нужен хотя бы один say с текстом")
    for number, line in enumerate(lines, 1):
        where = f"строка {number}"
        if not isinstance(line, dict):
            errors.append(f"{where}: строка — это объект")
            continue
        if ("say" in line) == ("pause" in line):
            errors.append(f"{where}: нужно ровно одно из say и pause")
        elif "say" in line and not _filled(line["say"]):
            errors.append(f"{where}: пустая фраза")
        elif "pause" in line and not (
            isinstance(line["pause"], (int, float))
            and not isinstance(line["pause"], bool)
            and 0 < line["pause"] <= PAUSE_MAX
        ):
            errors.append(f"{where}: pause — секунды, больше нуля и не больше {PAUSE_MAX:g}")
        if not isinstance(line.get("hint", ""), str):
            errors.append(f"{where}: hint — строка")
        errors += _screen_problems(line.get("screen"), where)
    return errors


def load(path: Path) -> tuple[dict, list[str]]:
    """Сценарий из файла и его ошибки.

    Не state.read_json: тот прячет битый файл в .broken и молча отдаёт пустое —
    для состояния это спасение, а проверке нужно сказать, где JSON сломан.
    """
    try:
        script = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return {}, [f"не прочитать {path}: {exc.strerror}"]
    except json.JSONDecodeError as exc:
        return {}, [f"{path.name}: не JSON — строка {exc.lineno}, {exc.msg}"]
    return script, problems(script, path.stem)


def spoken_frames(script: dict) -> list[int]:
    """Номера кадров с голосом, с единицы. Паузы владелец не записывает."""
    return [number for number, line in enumerate(script["lines"], 1) if "say" in line]


def when(script: dict) -> str:
    return TODAY if script["publish"] == "today" else script["publish"]


# --- рассылка ------------------------------------------------------------


def header(script: dict) -> str:
    """Шапка рассылки: тема, срок, как записывать и где сверить факты."""
    sources = " · ".join(
        f'<a href="{html.escape(url)}">{number}</a>' for number, url in enumerate(script["sources"], 1)
    )
    return (
        f"<b>РОЛИК · {html.escape(script['topic'], quote=False)}</b>\n"
        f"Выложить: <b>{when(script)}</b>\n"
        f"<code>{script['id']}</code>\n\n"
        f"Фраз: {len(spoken_frames(script))}, каждая ниже отдельным сообщением. "
        "На каждую ответь голосовым: свайп влево по фразе и запись. Одна фраза — "
        "одно голосовое, тишину по краям сборка срежет сама. Не понравился дубль — "
        "ответь на ту же фразу ещё раз.\n\n"
        "Когда придут все, ролик соберётся сам и вернётся сюда с превью "
        "и текстом для заливки.\n\n"
        f"Сверить факты до записи: {sources}"
    )


def line_text(number: int, total: int, line: dict) -> str:
    text = f"<b>{number}/{total}</b> — {html.escape(line['say'], quote=False)}"
    if _filled(line.get("hint")):
        text += f"\n<i>{html.escape(line['hint'], quote=False)}</i>"
    return text


def send(script: dict, dry_run: bool) -> int:
    """Кладёт сценарий в приватное хранилище и рассылает фразы владельцу.

    Разосланный второй раз не уходит: перезапуск воркфлоу или повторный пуш
    той же ветки завалил бы личку дублями, а ответы на старые сообщения
    перестали бы находиться. Исправленный сценарий — под новым id.
    """
    folder = config.PRIVATE / "reels" / script["id"]
    if (folder / "sent.json").exists():
        print(f"Сценарий {script['id']} уже разослан — исправленный присылай под новым id.")
        return 0

    frames = spoken_frames(script)
    messages = [header(script)] + [
        line_text(number, len(frames), script["lines"][frame - 1])
        for number, frame in enumerate(frames, 1)
    ]
    if dry_run:
        print("\n\n———\n\n".join(messages))
        return 0

    from . import telegram

    admin = config.secret("TELEGRAM_ADMIN_ID")
    telegram.send_message(admin, messages[0])
    lines = {
        str(telegram.send_message(admin, text)["message_id"]): frame
        for frame, text in zip(frames, messages[1:])
    }
    # Отметка — после всей рассылки: есть sent.json, значит ушло всё. Оборвался
    # запуск посередине — перезапуск разошлёт заново, а не оставит полсценария.
    state.write_json(folder / "script.json", script)
    state.write_json(folder / "sent.json", {"sent_at": state.iso(), "lines": lines})
    print(f"Разослан {script['id']}: фраз {len(lines)}.")
    return 0


# --- приём дублей ---------------------------------------------------------


def take_file(message: dict) -> dict:
    """Голосовое, аудио или аудиофайл документом. Пустой словарь — голоса нет."""
    document = message.get("document") or {}
    if str(document.get("mime_type", "")).startswith("audio/"):
        return document
    return message.get("voice") or message.get("audio") or {}


def _lookup(message_id: int) -> tuple[str, int] | None:
    for sent in sorted((config.PRIVATE / "reels").glob("*/sent.json")):
        frame = state.read_json(sent, {}).get("lines", {}).get(str(message_id))
        if frame:
            return sent.parent.name, frame
    return None


def line_of(message_id: int) -> tuple[str, int] | None:
    """Ролик и номер кадра фразы, на которую ответили. None — это не фраза ролика.

    Ищется по разосланному, как приём трека ищет пост по track_request. Не нашлось —
    один раз подтягиваем приватное хранилище: рассылает другой воркфлоу, а
    дежурство, склонировавшее хранилище часы назад, узнало бы о новом ролике
    только на следующей отправке состояния — владелец же записывает сразу.
    """
    found = _lookup(message_id)
    if found is None and (config.PRIVATE / ".git").exists():
        subprocess.run(
            ["git", "pull", "--rebase", "--autostash"], cwd=config.PRIVATE, capture_output=True
        )
        found = _lookup(message_id)
    return found


def start_build(reel_id: str) -> bool:
    """Запускает сборку отдельным запуском reels.yml. False — не запустилась.

    workflow_dispatch — единственное, что встроенному GITHUB_TOKEN разрешено
    запускать (прочие его события новых запусков не создают), так что отдельный
    ключ не нужен: хватает права actions: write у воркфлоу бота.
    """
    import requests

    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not (token and repo):
        log.warning("Сборка %s не запущена: нет GITHUB_TOKEN. Руками: python -m src.reels --build %s", reel_id, reel_id)
        return False
    try:
        response = requests.post(
            f"https://api.github.com/repos/{repo}/actions/workflows/reels.yml/dispatches",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            json={"ref": os.environ.get("GITHUB_REF_NAME", "main"), "inputs": {"id": reel_id}},
            timeout=30,
        )
    except requests.RequestException as exc:
        log.error("Сборка %s не запущена: %s", reel_id, exc)
        return False
    if not response.ok:
        log.error("Сборка %s не запущена: GitHub ответил %s %s", reel_id, response.status_code, response.text[:200])
    return response.ok


def accept(message: dict, reel: tuple[str, int], admin: str, push) -> None:
    """Кладёт дубль на место кадра и отвечает владельцу; полный комплект — в сборку.

    `push` — отправка состояния из дежурства (moderate.push_state): сборка идёт
    на другой машине и берёт дубли из приватного хранилища, поэтому последний
    дубль уезжает туда до запуска, а не через десять минут.
    """
    from . import telegram

    reel_id, frame = reel
    folder = config.PRIVATE / "reels" / reel_id
    frames = spoken_frames(state.read_json(folder / "script.json", {"lines": []}))
    number = f"{frames.index(frame) + 1}/{len(frames)}" if frame in frames else str(frame)
    again = any(folder.glob(f"{frame}.*"))

    take = take_file(message)
    try:
        data = telegram.download_file(take["file_id"])
    except telegram.TelegramError as exc:
        telegram.send_message(admin, f"Дубль {number} не принят: {exc}. Пришли ещё раз.", reply_to=message["message_id"])
        return
    # Прежний дубль удаляется целиком: пришёл m4a вместо ogg — и narrate взял бы
    # первый по алфавиту файл, то есть, возможно, старый.
    for old in folder.glob(f"{frame}.*"):
        old.unlink()
    # Расширение — для глаз: ffmpeg узнаёт формат по содержимому.
    (folder / f"{frame}{Path(take.get('file_name', 'take.ogg')).suffix or '.ogg'}").write_bytes(data)

    if any(not any(folder.glob(f"{n}.*")) for n in frames):
        reply = f"{'Перезаписал' if again else 'Принял'} {number}"
    else:
        push()
        if start_build(reel_id):
            reply = f"Перезаписал {number}, пересобираю" if again else "Все фразы есть, собираю"
        else:
            reply = (f"Все фразы есть, но сборка не запустилась. Actions → «Ролики» → "
                     f"Run workflow, id <code>{reel_id}</code>")
    telegram.send_message(admin, reply, reply_to=message["message_id"])


# --- сборка ---------------------------------------------------------------


def _card_canvas(work: Path) -> Path:
    from PIL import Image

    from . import clips

    path = work / "card.png"
    if not path.exists():
        Image.new("RGB", (clips.WIDTH, clips.HEIGHT), DARK).save(path)
    return path


def _meme_canvas(template: str, work: Path) -> Path:
    """Мем целиком на вертикальном холсте.

    Шаблоны в основном горизонтальные, а кадр — 9:16: обрезка по центру,
    как у фотографий, оставила бы от мема середину без половины героев.
    Мем вписывается в верхние две трети — ниже надпись и интерфейс площадки.
    """
    from PIL import Image

    from . import clips

    meme = Image.open(config.MEME_TEMPLATES / f"{template}.jpg").convert("RGB")
    box_w, box_h = clips.WIDTH, int(clips.HEIGHT * 0.55)
    scale = min(box_w / meme.width, box_h / meme.height)
    meme = meme.resize((round(meme.width * scale), round(meme.height * scale)), Image.LANCZOS)
    canvas = Image.new("RGB", (clips.WIDTH, clips.HEIGHT), DARK)
    canvas.paste(meme, ((box_w - meme.width) // 2, MEME_TOP + (box_h - meme.height) // 2))
    path = work / f"meme-{template}.png"
    canvas.save(path)
    return path


def storyboard(script: dict, work: Path, seconds: list[float] | None = None) -> list:
    """Кадр на каждую строку сценария — и ничего сверх.

    Заставки с маркой в конце, как у клипов, нет: крючок у сценария уже есть
    первой фразой, а три секунды заставки — это три секунды, на которых ролик
    пролистывают, и повтор по кругу начинался бы с неё, а не с крючка.

    `seconds` — длины кадров, когда они уже известны по дублям: счётчик кассеты
    показывает настоящее время кадра в ролике, а без второго прохода он врал бы
    на разницу между нижней границей и записанной фразой.
    """
    from . import clips

    shots, at = [], 0.0
    for index, line in enumerate(script["lines"]):
        screen = line["screen"]
        length = seconds[index] if seconds else float(line.get("pause") or SAY_SECONDS)
        # У лица надпись по умолчанию — имя: холодная лента не обязана узнавать
        # человека в лицо. Пустой text убирает надпись совсем.
        body = screen.get("text", screen.get("name", ""))
        label = screen.get("label", "")
        layer = (
            clips.overlay(label, body, big=len(body) <= BIG_TEXT, at=at)
            if label or body
            else clips.cut_overlay(at)
        )
        backdrop = ""
        if screen["kind"] == "meme":
            backdrop = str(_meme_canvas(screen["template"], work))
        elif screen["kind"] == "card":
            backdrop = str(_card_canvas(work))
        # face ищется по имени (subject), stock — своим запросом (query).
        shots.append(clips.Shot(
            layer, length, screen.get("name", ""), script.get("topic", ""),
            backdrop=backdrop, query=screen.get("query", ""),
        ))
        at += length
    return shots


def _trimmed(script: dict, voices: Path | None, work: Path) -> Path:
    """Дубли без тишины по краям — в своей папке под теми же номерами.

    Голосовое начинается раньше речи и кончается позже: палец жмёт запись,
    человек вдыхает, отпускает. По полсекунды с краёв на семи фразах — лишние
    семь секунд тишины в ролике на сорок, а короткие ролики пролистывают
    как раз на провалах. Берутся только фразы: пауза остаётся немой, даже если
    в папке случайно лежит файл под её номером.
    """
    from . import clips

    out = work / "takes"
    out.mkdir(exist_ok=True)
    edge = "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.1"
    for frame in spoken_frames(script) if voices else []:
        take = clips.voice_take(voices, frame - 1)
        if take is not None:
            clips.run([
                clips.ffmpeg(), "-y", "-i", str(take),
                "-af", f"{edge},areverse,{edge},areverse", str(out / f"{frame}.wav"),
            ])
    return out


def bed() -> Path | None:
    """Подложка: сначала приватное хранилище, потом assets/audio. None — нет нигде."""
    from . import clips

    for folder in (config.PRIVATE / "audio", clips.AUDIO_DIR):
        tracks = sorted(p for p in folder.glob("*") if p.suffix in {".mp3", ".wav"}) if folder.is_dir() else []
        if tracks:
            return random.choice(tracks)
    return None


def build(script: dict, voices: Path | None) -> tuple[Path, Path]:
    """Собирает ролик и превью. Возвращает (ролик, превью)."""
    from . import clips

    clips.OUT_DIR.mkdir(parents=True, exist_ok=True)
    video = clips.OUT_DIR / f"reel-{script['id']}.mp4"
    cover = video.with_suffix(".jpg")

    with tempfile.TemporaryDirectory(prefix="plenka-reel-") as tmp:
        work = Path(tmp)
        shots, voice = clips.narrate(
            storyboard(script, work), script, work, kind="reels", voices=_trimmed(script, voices, work)
        )
        shots = storyboard(script, work, [shot.seconds for shot in shots])
        total = sum(shot.seconds for shot in shots)

        parts, kinds = [], []
        for index, shot in enumerate(shots):
            parts.append(work / f"part-{index}.mp4")
            kinds.append(clips.segment(shot, parts[-1], work, fade_in=index > 0))
        print("  кадры:", ", ".join(kinds))
        print(f"  голос: {'есть' if voice else 'нет'}, длина {total:.1f} с")

        music, start = bed(), clips.AUDIO_SKIP_SECONDS
        if music is None:
            # Ролик без музыки лучше, чем никакого: голос в нём главное.
            # Тишина вместо подложки — чтобы склейка шла тем же путём.
            log.warning("Подложки нет ни в %s, ни в assets/audio — ролик без музыки", config.PRIVATE / "audio")
            music, start = work / "silence.wav", 0.0
            clips.run([clips.ffmpeg(), "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                       "-t", f"{total}", str(music)])
        clips.assemble(parts, music, total, video, work, voice, start)

    # Превью вынимается из готового ролика, а не рисуется отдельно: так оно
    # по построению совпадает с первым кадром, который площадка возьмёт обложкой.
    clips.run([clips.ffmpeg(), "-y", "-i", str(video), "-frames:v", "1", "-q:v", "2", str(cover)])
    return video, cover


def package(script: dict) -> str:
    """Текст для заливки: каждое поле — отдельный <code>, копируется касанием.

    Отдельным сообщением, а не подписью к ролику: подпись в Telegram обрезается
    на 1024 знаках, а название, описание и теги вместе туда не влезают.
    """
    def field(value: str) -> str:
        return f"<code>{html.escape(value, quote=False)}</code>"

    return (
        f"<b>Название</b>\n{field(script['title'])}\n\n"
        f"<b>Описание</b>\n{field(script['description'])}\n\n"
        f"<b>Теги</b>\n{field(', '.join(script['tags']))}\n\n"
        f"Выложить: <b>{when(script)}</b>"
    )


def deliver(script: dict, video: Path, cover: Path) -> None:
    """Пакет владельцу: ролик, превью файлом и текст полей."""
    from . import telegram

    admin = config.secret("TELEGRAM_ADMIN_ID")
    telegram.send_video_file(admin, video, f"<b>{html.escape(script['topic'], quote=False)}</b>")
    # Превью документом, а не фото: фото Telegram пережимает до 1280 точек
    # по длинной стороне, а обложке нужен кадр 1080×1920 как есть. Отправки
    # документа в telegram.py нет — метод API зовётся напрямую.
    with cover.open("rb") as handle:
        telegram._call("sendDocument", {"chat_id": admin}, files={"document": (cover.name, handle, "image/jpeg")})
    telegram.send_message(admin, package(script))


# --- проверка -------------------------------------------------------------


def _selftest() -> None:
    """Без сети: валидатор, раскадровка и разбор ответа-голосового.

    Запуск: python -m src.reels --selftest
    """
    import contextlib
    import io

    from PIL import Image

    from . import host, moderate

    good = {
        "id": "20260914-test",
        "topic": "Проверка",
        "publish": "today",
        "sources": ["https://example.com/news"],
        "title": "Проверка формата",
        "description": "Строка описания. #фонк #плёнка",
        "tags": ["фонк", "плёнка"],
        "lines": [
            {"say": "Первая фраза", "hint": "ровно", "screen": {"kind": "face", "name": "Bones"}},
            {"say": "Вторая", "screen": {"kind": "card", "label": "17/08", "text": "два концерта"}},
            {"pause": 1.0, "screen": {"kind": "meme", "template": "this-is-fine"}},
            {"say": "Третья", "screen": {"kind": "stock", "query": "stadium empty seats"}},
        ],
    }
    assert problems(good, good["id"]) == [], problems(good, good["id"])

    def broken(word: str, **change) -> None:
        found = problems({**good, **change}, good["id"])
        assert any(word in error for error in found), (word, found)

    broken("sources", sources=[])
    broken("title", title="х" * 101)
    broken("хэштеги", description="Описание без хэштегов в конце")
    broken("именем файла", id="20260915-other")
    broken("publish", publish="завтра")
    broken("tags", tags=["фонк, рэп"])
    broken("фразы", lines=[{"pause": 1.0, "screen": {"kind": "card", "text": "тишина"}}])
    broken("ровно одно", lines=[{"say": "Фраза", "pause": 1.0, "screen": {"kind": "card", "text": "т"}}])
    for screen, word in (
        ({"kind": "gif"}, "kind"),
        ({"kind": "meme", "template": "нет-такого"}, "шаблона"),
        ({"kind": "face", "name": "Канье"}, "artists.json"),
        ({"kind": "card"}, "text"),
        ({"kind": "stock"}, "query"),
    ):
        broken(word, lines=[{"say": "Фраза", "screen": screen}])

    # Раскадровка: кадр на строку, у паузы нет фразы и длина ровно из сценария.
    with tempfile.TemporaryDirectory() as tmp:
        shots, spoken = storyboard(good, Path(tmp)), host.lines(good, kind="reels")
        assert len(shots) == len(good["lines"]) == len(spoken), (len(shots), len(spoken))
        assert spoken[2] == "" and shots[2].seconds == 1.0, (spoken[2], shots[2].seconds)
        assert spoken_frames(good) == [1, 2, 4]
        assert Image.open(shots[2].backdrop).size == (1080, 1920)

    # Ответ голосовым на фразу находит ролик и кадр — и в разборе дежурства тоже.
    saved = config.PRIVATE
    with tempfile.TemporaryDirectory() as tmp:
        config.PRIVATE = Path(tmp)
        try:
            state.write_json(Path(tmp) / "reels" / good["id"] / "sent.json", {"lines": {"562": 4}})
            voice = {"message_id": 9, "from": {"id": 1}, "chat": {"id": 1},
                     "reply_to_message": {"message_id": 562}, "voice": {"file_id": "v"}}
            assert take_file(voice)["file_id"] == "v"
            assert take_file({"document": {"file_id": "d", "mime_type": "audio/mp4"}})["file_id"] == "d"
            assert not take_file({"document": {"file_id": "p", "mime_type": "application/pdf"}})
            assert line_of(562) == (good["id"], 4)
            assert line_of(563) is None

            def routed(message: dict) -> str:
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    moderate.process([{"update_id": 1, "message": message}], {}, "1", True, 0)
                return out.getvalue()

            assert f"дубль ролика {good['id']}, кадр 4" in routed(voice)
            # Чужое голосовое и аудио в ответ на запрос трека идут прежним путём.
            assert "дубль ролика" not in routed({**voice, "from": {"id": 2}, "chat": {"id": 2}})
            track = {**voice, "voice": None, "audio": {"file_id": "a"}, "reply_to_message": {"message_id": 700}}
            assert "трек в ответ на 700" in routed(track)
        finally:
            config.PRIVATE = saved


def main() -> int:
    parser = argparse.ArgumentParser(description="Ролики с живым голосом владельца")
    parser.add_argument("--check", metavar="ФАЙЛ", help="проверить сценарий без сети")
    parser.add_argument("--send", metavar="ФАЙЛ", help="сохранить сценарий и разослать фразы владельцу")
    parser.add_argument("--build", metavar="ID", help="собрать из дублей приватного хранилища и прислать пакет")
    parser.add_argument("--preview", metavar="ФАЙЛ", help="собрать ролик из файла, никуда не отправляя")
    parser.add_argument("--voice", metavar="ПАПКА", help="дубли для --preview: 1.ogg, 2.m4a… по номеру строки")
    parser.add_argument("--dry-run", action="store_true", help="ничего не писать и не отправлять, показать")
    parser.add_argument("--selftest", action="store_true", help="валидатор, раскадровка и разбор ответа без сети")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.selftest:
        _selftest()
        print("Сценарий, раскадровка и разбор голосового: все проверки прошли.")
        return 0

    if args.check or args.send or args.preview:
        path = Path(args.check or args.send or args.preview)
        script, errors = load(path)
        for error in errors:
            print(f"  ✗ {error}")
        if errors:
            print(f"Сценарий {path.name} не годен: ошибок {len(errors)}.")
            return 1
        if args.check:
            print(f"Сценарий {path.name} годен: фраз {len(spoken_frames(script))}, кадров {len(script['lines'])}.")
            return 0

    config.load_dotenv()

    if args.send:
        return send(script, args.dry_run)

    if args.preview:
        voices = Path(args.voice) if args.voice else None
    elif args.build:
        # id уходит в путь — только проверенного вида, никаких «../».
        if not ID_FORMAT.fullmatch(args.build):
            print("id вида 20260914-kanye.")
            return 1
        voices = config.PRIVATE / "reels" / args.build
        script = state.read_json(voices / "script.json", {})
        if not script:
            print(f"Нет сценария {args.build} в {voices}.")
            return 1
    else:
        parser.print_help()
        return 0

    from . import clips

    try:
        video, cover = build(script, voices)
    except clips.ClipError as exc:
        print(f"Ролик не собрался: {exc}")
        return 1
    size = video.stat().st_size / 1024 / 1024
    print(f"Готов: {video.relative_to(config.ROOT)} ({size:.1f} МБ), превью {cover.relative_to(config.ROOT)}")

    if args.preview or args.dry_run:
        print(f"\nПакет владельцу — ролик, превью файлом и текст:\n\n{package(script)}")
        return 0
    deliver(script, video, cover)
    print("Пакет ушёл владельцу.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
