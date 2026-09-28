"""«Где ИИ» — воскресная прослушка: четыре куска, один сделала нейросеть.

По воскресеньям src/quiz.py вместо «угадай артиста» выпускает раунд отсюда:
одно вертикальное видео ~30 секунд, четыре куска по 8 секунд, а на экране
с первого кадра вся игра — «один из них — нейросеть» и четыре плитки А Б В Г,
играющая подсвечена, под ней полоска на 8 секунд и живая волна звука. Звук
с нулевой секунды, без заставки: зацепка в Shorts решается в первую секунду.
Куски сшиты равномощным кроссфейдом по 0,5 с из их собственных краёв, плитка
переключается на середине перехода мягко (владелец, 27.09.2026). Варианты —
та же неанонимная викторина в комментариях, угадавшим назавтра титул
«слышит ИИ». Вторая версия — для YouTube Shorts: призыв писать букву
в комментариях, ответ на плитках в конце и метка с плашкой канала, как
у роликов (src/reels.py); звук до последнего кадра, чтобы повтор шёл гладко.
Концовка зовёт не за раундами, а бесплатно свести трек в боте (владелец,
28.09.2026): прослушку смотрят ради игры, а польза канала — СВЕДЕНИЕ.
Её бот шлёт владельцу в личку с заголовком и описанием: заливку роликов
владелец оставил себе.

**ИИ-кусок — из выпущенного трека, а не своя генерация.** Свои пробы ACE-Step
владелец раскусил 26.09.2026 («ИИ сильно палится»). Доказательство, что трек
сделала нейросеть, — две метки сразу (src/sources/ai_labels.py): Яндекс
«Трек полностью создан с использованием ИИ» и детектор Deezer. «Частично»
и «возможно» не годятся никогда: назвать нейросетью живого артиста —
обвинение. Метки сверяются дважды: при сборке раунда и в Actions перед
выходом; снятая метка выбрасывает раунд из запаса.

**Настоящие — только треки 2015–2022 годов** по дате магазина. Ответ
«остальные — люди» прочтёт весь канал, а отсутствие метки человека
не доказывает. До 2023-го поющих нейросетей не было; раньше 2015-го
выдала бы сама запись — сведение того времени слышно.

**Запас готовит Mac, выпускает Actions.** Чтобы ИИ не выделялся, куски
режутся по паузе в голосе и сравниваются по высоте голоса — для этого нужны
demucs, pyin и распознавание речи. Они тяжёлые и есть только на Маке
владельца (окружение ~/.cache/whisper-venv), а в requirements.txt им не место.
Раз в неделю launchd запускает `--stock`: готовых раундов меньше LOW —
ищет новые треки и собирает до TARGET. Mac может спать неделями, запас это
прощает. Раунд лежит в приватном хранилище (config.PRIVATE/quiz_ai): четыре
обработанных куска и round.json. Из открытого репозитория ответ прочёл бы
кто угодно. Видео рендерит Actions в момент выхода — ffmpeg и Pillow, без drawtext:
у ffmpeg из Homebrew его нет, а шрифты канала Pillow уже рисует.

**Чтобы ИИ не выдал себя звуком.** Тройка настоящих — того же жанра Deezer
(и Яндекса, если он знает артиста) и той же манеры (читка или распев, по слогам
в секунду), по-русски (язык определяет распознавание), не на слуху (не выше
10 000-го места в рейтинге Яндекса: узнанный голос отвечает методом исключения),
ИИ по высоте голоса внутри тройки, а не с краю; яркость и ширину стерео ИИ подтягиваем к краю
настоящих, только если он явный выброс, — не вышло, раунд не собирается.
Обработка одна на все куски: срез выше 16 кГц, мягкое сжатие, −14 LUFS,
лимитер, AAC 256k, теги стёрты. Превью все с Deezer — один и тот же MP3
у ИИ и у людей, кодек ответа не выдаст. Мат ищется по полному тексту куска
и превью: мат в треке — трек не идёт.

**Ответ не утекает.** Букву ИИ выбирает Actions при выходе: случайная, но не та,
что в прошлый раз (прошлая лежит в приватном quiz.json). Ни буквы, ни имени,
ни состава раунда в логах Actions нет в любом режиме: лог открытого
репозитория публичен. В видео и звуке — ни имён, ни тегов, ни обложек.

    python -m src.quiz_ai --stock          на Маке: пополнить запас до TARGET, если в нём меньше LOW
    python -m src.quiz_ai --dry-run        на Маке: что собралось бы, без записи в хранилище
    python -m src.quiz_ai --install        на Маке: запуск --stock раз в неделю через launchd
    python -m src.quiz_ai --selftest       буква, мат, даты, пояснение — без сети
    python -m src.quiz --ai --target admin     раунд из запаса себе в личку (обе версии)

Тяжёлое (--stock, --dry-run) запускать python'ом из ~/.cache/whisper-venv.
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import math
import os
import plistlib
import random
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from itertools import combinations
from pathlib import Path

from . import config, state, telegram
from .sources import ai_labels

log = logging.getLogger("quiz_ai")

STOCK = "quiz_ai"
LETTERS = "АБВГ"
QUESTION = "Где ИИ?"
# Метка в чате: до 16 знаков без эмодзи (quiz.TAG_LIMIT).
TAG = "слышит ИИ"
LOW, TARGET = 4, 6

PIECE, XFADE, SWITCH = 8.0, 0.5, 0.3
# Ответ YouTube-версии держится до плашки канала; строка факта — первые секунды.
ANSWER, FACT_UNTIL = 3.75, 3.0
W, H, FPS = 1080, 1920, 30
BG = (22, 21, 24)  # фон плашки роликов (reels.PLATE_BG): один вид у всего видео канала
INK = (240, 236, 228)
DIM = (128, 124, 132)
TILE = (40, 38, 44)
TRACK = (70, 66, 74)
ACCENT = (255, 94, 58)
# Плитки 2×2 в безопасной ширине: 2·316 + 16 = 648 = reels.SAFE_TEXT · 1080.
TILE_W, TILE_H, TILE_GAP, ROW_GAP, GRID_Y = 316, 250, 16, 40, 800
GRID_X = (W - 2 * TILE_W - TILE_GAP) // 2
BAR_H, WAVE_W, WAVE_H = 10, 260, 80
# Строка факта, а под ответом — трек ИИ: между заголовком и плитками.
TEXT_Y = 610
TITLE = ("ОДИН ИЗ НИХ —", "НЕЙРОСЕТЬ")
# Правда о каждом раунде: у каждого ИИ-трека запаса метка Яндекса. Статистики «90 % не угадывают» нет.
FACT = "ИИ-трек выпущен и лежит в Яндекс Музыке"
CTA = "Пиши букву в комментах — ответ в конце"
# Вместо «ещё раунды в канале» — СВЕДЕНИЕ; 617 точек при безопасных 648 (reels.SAFE_TEXT).
BAIT = "сведём трек бесплатно"

INTRO = (
    "<b>ГДЕ ИИ?</b>\n\n"
    "Четыре куска по 8 секунд. Один — из выпущенного трека, который целиком сделала нейросеть, "
    "остальные три — живые артисты, треки до 2023 года. Угадай, где ИИ, — {where}.\n\n"
    "Угадал — завтра титул «слышит ИИ»."
)
PROOF = " Яндекс: полностью создан с ИИ (заявил правообладатель). Deezer: выявлен ИИ-контент."
YT_TITLE = "Где ИИ? Три живых артиста и одна нейросеть #shorts"


def sunday(moment: datetime | None = None) -> bool:
    """Воскресенье по Москве: запуск в 12:00 UTC GitHub задерживает на часы."""
    moment = moment or datetime.now(timezone.utc)
    return moment.astimezone(timezone(timedelta(hours=3))).weekday() == 6


def letter(last: int | None) -> int:
    """Буква ИИ: случайная, но не прошлая — та уже раскрыта опросом."""
    return random.choice([i for i in range(len(LETTERS)) if i != last])


def explanation(mark: str, artist: str, track: str) -> str:
    """Пояснение викторины: буква, трек и чем доказано. Telegram режет на 200."""
    room = telegram.MAX_EXPLANATION - len(PROOF) - len(f"ИИ — {mark}: {artist} — «»")
    if len(track) > room:
        track = track[:max(room - 1, 1)] + "…"
    return f"ИИ — {mark}: {artist} — «{track}»{PROOF}"[:telegram.MAX_EXPLANATION]


def youtube_text(ai: dict) -> str:
    """Подпись к YouTube-версии в личке: заголовок и описание — в <code>, копировать нажатием."""
    who = html.escape(f"{ai['artist']} — «{ai['track']}»")
    return (
        "<b>ГДЕ ИИ — версия для YouTube Shorts</b>, с ответом в конце. Залить руками; "
        "лучше в понедельник — до тех пор в канале идёт викторина.\n\n"
        f"Заголовок:\n<code>{YT_TITLE}</code>\n\n"
        "Описание:\n<code>Четыре куска по 8 секунд: три — живые артисты, треки до 2023 года, "
        "один — из выпущенного трека, который целиком сделала нейросеть. Ответ — в конце.\n"
        f"ИИ: {who}. Яндекс Музыка: «Трек полностью создан с использованием ИИ» (заявил правообладатель). "
        "Deezer: выявлен ИИ-контент.\n"
        f"Свести свой трек бесплатно: кидай вокал и бит — t.me/{config.BOT_HANDLE.lstrip('@')}?start=skleyka_yt\n"
        f"Новый раунд каждое воскресенье — t.me/{config.CHANNEL_HANDLE.lstrip('@')}</code>"
    )


# ─────────────────────────── выход (Actions) ───────────────────────────


def stock(root: Path | None = None) -> list[Path]:
    """Готовые раунды, старые первыми."""
    folder = root or config.PRIVATE / STOCK
    found = [p.parent for p in folder.glob("*/round.json")]
    return sorted(found, key=lambda p: state.read_json(p / "round.json", {}).get("made", ""))


def next_round() -> tuple[Path, dict] | None:
    """Первый раунд запаса с живыми метками. Снятая метка выбрасывает раунд.

    Площадка не ответила — не выбрасываем ничего: неделя уходит загадке
    про артиста, а запас ждёт следующего воскресенья.
    """
    for folder in stock():
        data = state.read_json(folder / "round.json", {})
        try:
            ok = ai_labels.confirmed(data["ai"]["ya_id"], data["ai"]["dz_album"])
        except ai_labels.Unknown:
            log.warning("«Где ИИ»: площадка не ответила, метки не сверены — раунд ждёт следующей недели")
            return None
        except (KeyError, TypeError):
            ok = False
        if ok:
            return folder, data
        # Без имени и номера: лог открытого репозитория публичен.
        log.warning("«Где ИИ»: у раунда из запаса метка ИИ не подтвердилась — раунд выброшен")
        shutil.rmtree(folder, ignore_errors=True)
    log.info("«Где ИИ»: в запасе нет раунда")
    return None


def item(last: int | None) -> dict | None:
    """Раунд к выходу: порядок кусков, оба видео и викторина. None — запас пуст."""
    found = next_round()
    if not found:
        return None
    folder, data = found
    correct = letter(last)
    real = [folder / f"real-{i}.m4a" for i in (1, 2, 3)]
    random.shuffle(real)
    order = real[:correct] + [folder / "ai.m4a"] + real[correct:]
    out = Path(tempfile.mkdtemp(prefix="where-ai-"))
    ai = data["ai"]
    return {
        "kind": "ai",
        "folder": str(folder),
        "question": QUESTION,
        "options": list(LETTERS),
        "correct": correct,
        "explanation": explanation(LETTERS[correct], ai["artist"], ai["track"]),
        "tag": TAG,
        "seconds": round(timeline(False)["total"]),
        "youtube_seconds": round(timeline(True)["total"]),
        "video": render(order, out / "gde-ii.mp4"),
        "youtube": render(order, out / "gde-ii-shorts.mp4", answer=(correct, ai)),
        "youtube_text": youtube_text(ai),
    }


def timeline(answer: bool) -> dict:
    """Где что звучит: начала кусков, середины переходов (там меняется плитка) и длины.

    Кроссфейд съедает по XFADE на стык, поэтому куски начинаются через 7,5 с.
    С ответом: последний кусок перетекает в повтор ИИ-куска под карточкой ответа,
    и тот звучит до конца плашки — повтор Shorts начинается без провала в тишину.
    """
    from .reels import PLATE_SECONDS

    starts = [i * (PIECE - XFADE) for i in range(len(LETTERS))]
    switches = [s + XFADE / 2 for s in starts[1:]]
    end = starts[-1] + PIECE
    if not answer:
        return {"starts": starts, "switches": switches, "main": end, "total": end}
    switches.append(end - XFADE / 2)
    main = switches[-1] + ANSWER
    total = main + PLATE_SECONDS
    return {"starts": starts, "switches": switches, "main": main, "total": total, "replay": total - (end - XFADE)}


def _tile(i: int) -> tuple[int, int]:
    return GRID_X + i % 2 * (TILE_W + TILE_GAP), GRID_Y + i // 2 * (TILE_H + ROW_GAP)


def _wrap(draw, text: str, font, width: float) -> list[str]:
    lines = [""]
    for word in text.split():
        probe = f"{lines[-1]} {word}".strip()
        if draw.textlength(probe, font=font) <= width or not lines[-1]:
            lines[-1] = probe
        else:
            lines.append(word)
    return lines


def _canvas(path: Path, paint, rgba: bool = False) -> Path:
    """Кадр 1080×1920; paint(draw, block) рисует. Всё — в безопасной зоне Shorts (reels.SAFE_*):
    иначе надпись уедет под панель поиска, колонку кнопок или подпись канала."""
    from PIL import Image, ImageDraw

    from .reels import SAFE_TEXT

    image = Image.new("RGBA" if rgba else "RGB", (W, H), (0, 0, 0, 0) if rgba else BG)
    draw = ImageDraw.Draw(image)
    width = W * SAFE_TEXT

    def block(text: str, y: float, font, fill, gap: int = 12, center_x: float = W / 2) -> float:
        """Абзац по центру, перенос по словам; y — верх букв, возвращает низ."""
        for line in _wrap(draw, text, font, width):
            while len(line) > 2 and draw.textlength(line, font=font) > width:
                line = line[:-2] + "…"  # одно слово шире зоны — режем, а не роняем выход
            left, top, right, bottom = draw.textbbox((0, 0), line, font=font)
            draw.text((center_x - (left + right) / 2, y - top), line, font=font, fill=fill)
            y += bottom - top + gap
        return y

    paint(draw, block)
    image.save(path)
    return path


def _fit(text: str, size: int, width: float, **kw):
    """Самый крупный шрифт не больше size, в котором строка влезает в width."""
    from . import stories

    while size > 20 and stories.font(size, **kw).getlength(text) > width:
        size -= 2
    return stories.font(size, **kw)


def _frame(path: Path, active: int | None = None, answer: tuple[int, dict] | None = None) -> Path:
    """Кадр игры: заголовок, плитки А Б В Г; active — играющая, answer — плитки ответа."""
    from . import stories
    from .reels import SAFE_TEXT, SAFE_TOP

    def paint(draw, block) -> None:
        title = _fit(max(TITLE, key=len), 110, W * SAFE_TEXT)
        y = H * SAFE_TOP + 110  # ниже метки канала YouTube-версии (reels.BADGE_*)
        for line in TITLE:
            y = block(line, y, title, INK, 16)
        if answer:
            correct, ai = answer
            y = block(f"{ai['artist']} — «{ai['track']}»", TEXT_Y, stories.font(42, 600, text=True), INK)
            block("метки ИИ: Яндекс Музыка и Deezer", y + 4, stories.font(34, 400, text=True), DIM)
        for i, mark in enumerate(LETTERS):
            x, top = _tile(i)
            on = i == (answer[0] if answer else active)
            draw.rounded_rectangle((x, top, x + TILE_W, top + TILE_H), radius=28, fill=ACCENT if on else TILE)
            middle = x + TILE_W / 2
            if not answer:
                block(mark, top + 28, stories.font(150), INK if on else DIM, center_x=middle)
                if on:  # дорожка полоски прогресса; сама полоска едет поверх (render)
                    y = top + TILE_H + 12
                    draw.rounded_rectangle((x, y, x + TILE_W, y + BAR_H), radius=BAR_H // 2, fill=TRACK)
                continue
            # Буква — мелко в углу, крупно — вердикт: «Б ИИ» рядом читалось одним словом.
            draw.text((x + 22, top + 14), mark, font=stories.font(44), fill=INK if on else DIM)
            if on:
                block("ИИ", top + 42, stories.font(130), INK, center_x=middle)
            else:
                block("человек", top + 100, stories.font(48, 500, text=True), DIM, center_x=middle)

    return _canvas(path, paint)


def _layer(path: Path, text: str, y: float, font, fill=INK) -> Path:
    """Прозрачный слой с абзацем — строка факта и призыв, которые приходят и уходят."""
    return _canvas(path, lambda draw, block: block(text, y, font, fill), rgba=True)


def _switch_expr(values: list, switches: list[float]) -> str:
    """Выражение ffmpeg по времени: values[i] между i-й и (i+1)-й сменой плиток."""
    expr = str(values[-1])
    for value, at in zip(reversed(values[:-1]), reversed(switches)):
        expr = f"if(lt(t,{at}),{value},{expr})"
    return expr


def render(order: list[Path], out: Path, answer: tuple[int, dict] | None = None) -> Path:
    """Видео раунда; с answer — YouTube-версия: призыв, ответ на плитках, метка и плашка канала."""
    from . import stories
    from .reels import badge, ending, plate

    work = out.parent
    plan = timeline(bool(answer))
    starts, switches, main = plan["starts"], plan["switches"], plan["main"]
    frames = [_frame(work / f"{out.stem}-{i}.png", active=i) for i in range(len(LETTERS))]
    if answer:
        frames.append(_frame(work / f"{out.stem}-answer.png", answer=answer))
    fact = _layer(work / "fact.png", FACT, TEXT_Y, stories.font(40, 600, text=True))
    inputs = [["-loop", "1", "-framerate", str(FPS), "-t", f"{main}", "-i", str(f)] for f in frames]
    inputs.append(["-loop", "1", "-framerate", str(FPS), "-t", f"{FACT_UNTIL}", "-i", str(fact)])
    from PIL import Image

    Image.new("RGB", (TILE_W, BAR_H), ACCENT).save(work / "bar.png")
    Image.new("RGB", (TILE_W, BAR_H), BG).save(work / "mask.png")
    for name in ("bar.png", "mask.png"):
        inputs.append(["-loop", "1", "-framerate", str(FPS), "-t", f"{main}", "-i", str(work / name)])
    n = len(frames)
    fact_i, bar_i, mask_i = n, n + 1, n + 2
    if answer:
        cta = _layer(work / "cta.png", CTA, 1380, stories.font(44, 500, text=True))
        badge().save(work / "badge.png")
        ending(icon=True, text=BAIT).save(work / "ending.png")
        for layer in (cta, work / "badge.png"):
            inputs.append(["-loop", "1", "-framerate", str(FPS), "-t", f"{main}", "-i", str(layer)])
        inputs.append(["-loop", "1", "-framerate", str(FPS), "-t", f"{plan['total'] - main}", "-i", str(work / "ending.png")])
        inputs.append(["-i", str(plate(work, plan["total"] - main))])
    sounds = list(order) + ([order[answer[0]]] if answer else [])
    first_sound = sum(1 for _ in inputs)
    inputs += [["-i", str(sound)] for sound in sounds]

    graph = ["[0:v]format=rgba[v0]"]
    for i in range(1, n):  # плитка меняется мягко, на середине звукового перехода
        graph.append(f"[{i}:v]format=rgba,fade=t=in:st={switches[i - 1] - SWITCH / 2}:d={SWITCH}:alpha=1[f{i}]")
        graph.append(f"[v{i - 1}][f{i}]overlay[v{i}]")
    last = f"v{n - 1}"
    graph.append(f"[{bar_i}:v]split={len(LETTERS)}" + "".join(f"[b{i}]" for i in range(len(LETTERS))))
    graph.append(f"[{mask_i}:v]split={len(LETTERS)}" + "".join(f"[m{i}]" for i in range(len(LETTERS))))
    bounds = [0.0] + switches[:len(LETTERS) - 1] + [switches[len(LETTERS) - 1] if answer else main]
    for i in range(len(LETTERS)):
        # Полоска прогресса выезжает из-под маски цвета фона слева от плитки: drawbox
        # время не понимает, а overlay двигает слой по t.
        x, top = _tile(i)
        y, on = top + TILE_H + 12, f"between(t,{bounds[i]},{bounds[i + 1]})"
        slide = f"{x - TILE_W}+{TILE_W}*min(1,max(0,(t-{starts[i]})/{PIECE}))"
        graph.append(f"[{last}][b{i}]overlay=x='{slide}':y={y}:enable='{on}'[p{i}]")
        graph.append(f"[p{i}][m{i}]overlay=x={x - TILE_W}:y={y}:enable='{on}'[q{i}]")
        last = f"q{i}"
    # Звук: куски целиком, стыки — равномощным кроссфейдом из их собственных краёв.
    for i, _ in enumerate(sounds):
        length = plan["replay"] if answer and i == len(order) else PIECE
        tail = f",afade=t=out:st={length - 0.4}:d=0.4" if answer and i == len(order) else ""
        graph.append(f"[{first_sound + i}:a]atrim=0:{length},asetpts=PTS-STARTPTS,"
                     f"aformat=sample_rates=44100:channel_layouts=stereo{tail}[s{i}]")
    mixed = "s0"
    for i in range(1, len(sounds)):
        graph.append(f"[{mixed}][s{i}]acrossfade=d={XFADE}:c1=qsin:c2=qsin[x{i}]")
        mixed = f"x{i}"
    graph.append(f"[{mixed}]alimiter=limit=0.95:level=false,asplit[aout][awave]")
    # Волна живёт в играющей плитке, под ответом — в плитке ИИ.
    graph.append(f"[awave]showwaves=s={WAVE_W}x{WAVE_H}:mode=cline:draw=full:rate={FPS}:colors=0xF0ECE4[wave]")
    active = list(range(len(LETTERS))) + ([answer[0]] if answer else [])
    xs = [_tile(i)[0] + (TILE_W - WAVE_W) // 2 for i in active]
    ys = [_tile(i)[1] + TILE_H - WAVE_H - 18 for i in active]
    graph.append(f"[{last}][wave]overlay=x='{_switch_expr(xs, switches)}':y='{_switch_expr(ys, switches)}'"
                 f":enable='lt(t,{main})'[w]")
    graph.append(f"[{fact_i}:v]format=rgba,fade=t=out:st={FACT_UNTIL - 0.5}:d=0.5:alpha=1[fact]")
    # overlay тянет выход до самого длинного входа, а волна идёт и под плашкой — режем по основной части.
    graph.append(f"[w][fact]overlay=enable='lt(t,{FACT_UNTIL})',trim=duration={main}[g]")
    if answer:
        cta_i, badge_i, end_i, plate_i = n + 3, n + 4, n + 5, n + 6
        graph.append(f"[g][{cta_i}:v]overlay=enable='lt(t,{switches[-1]})'[c]")
        graph.append(f"[c][{badge_i}:v]overlay,format=yuv420p,setsar=1[body]")
        graph.append(f"[{plate_i}:v][{end_i}:v]overlay,format=yuv420p,setsar=1[tail]")
        graph.append("[body][tail]concat=n=2:v=1:a=0[v]")
    else:
        graph.append("[g]format=yuv420p,setsar=1[v]")
    command = ["ffmpeg", "-y", "-v", "error"] + [arg for group in inputs for arg in group]
    command += ["-filter_complex", ";".join(graph), "-map", "[v]", "-map", "[aout]",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(FPS),
                "-c:a", "aac", "-b:a", "192k", "-map_metadata", "-1", "-movflags", "+faststart",
                "-t", f"{plan['total']}", str(out)]
    subprocess.run(command, check=True, capture_output=True)
    return out


# ─────────────────────────── запас (Mac) ───────────────────────────

WORK = Path.home() / ".cache" / "plenka-quiz-ai"
POOL = WORK / "pool.json"
MAC_STATE = WORK / "state"
STATE_REPO = os.environ.get("STATE_REPO") or "berg-creator/plenka-state"
LABEL = "fm.plenka.quiz-ai"
LOG_FILE = Path.home() / "Library" / "Logs" / "plenka-quiz-ai.log"

LEN, LUFS = 8.0, -14.0
# Голос в первые 60 мс среза тише громкой части куска хотя бы на столько: срез в паузе, а не в слове.
DIP = -13.0
WHISPER = "mlx-community/whisper-large-v3-turbo"
REAL_FROM, REAL_TO = "2015-01-01", "2023-01-01"
# Артист, выпускавшийся раньше, — чаще всего перевыпуск старых записей под новой датой.
ARTIST_FROM = "2012-01-01"
# Ранг трека Deezer: у хитов сотни тысяч. Узнанный настоящий артист отвечает за ИИ методом исключения.
REAL_RANK, AI_RANK = 120_000, 300_000
# Настоящий артист не выше этого места в месячном рейтинге Яндекс Музыки: знаменитость
# узнают по голосу. Ленинград — 48-й, Олег Митяев — 1675-й, Zero People — 10662-й.
YA_TOP = 10_000
# Поклонников на Deezer не больше: у Ленинграда 201 тысяча, у Джизуса 37 тысяч.
DZ_FANS = 20_000
# Сколько настоящих каждого жанра держать измеренными: из них подбирается тройка.
POOL_PER_GROUP = 40
# Слогов в секунду: быстрее — читка, медленнее — распев (KarDinaLL 5,0, поп-баллады около 2,5).
READING = 4.0
# Жанры Deezer (и Яндекса — у альбома без жанра на Deezer) — в три группы: тройке нужна одна.
GROUPS = {116: "рэп", 132: "поп", 106: "поп", 113: "поп", 110: "поп", 165: "поп",
          152: "рок", 85: "рок", 86: "рок", 154: "рок", 464: "рок"}
YA_GROUPS = {"rap": "рэп", "rusrap": "рэп", "foreignrap": "рэп", "phonkgenre": "рэп", "pop": "поп",
             "ruspop": "поп", "dance": "поп", "electronics": "поп", "rnb": "поп", "rock": "рок",
             "rusrock": "рок", "alternative": "рок", "prog": "рок", "metal": "рок", "punk": "рок", "indie": "рок"}
# Поиск Deezer словами: рэп с двумя метками нашёлся 27.09.2026 только так — такие артисты
# выпускаются сами, в каталогах дистрибьюторов их нет. Слова разные, чтобы не только рэп.
WORDS = ("район деньги улица братья бит трэп флоу любовь сердце ночь больно забудь мама дождь небо "
         "звёзды танцуй город душа слёзы холод дым луна весна лето зима море дорога дом друг мечта "
         "огонь свет пустота время память тишина гитара рок панк").split()
SEARCH_WORDS = 20
CYRILLIC = re.compile(r"[а-яё]", re.I)
# Мат — по полному тексту: в прошлом наборе «ебать» и «трахать» сидели за обрезом строки в 70 знаков.
MAT = re.compile(r"(?:^|[^а-яё])(?:на|по|ни|за|от|до|вы)?ху[йеёяию]|пизд|(?:^|[^а-яё])бля|(?:^|[^а-яё])[её]б"
                 r"|[аоуыиъ][её]б[аеёиоуюлн]|муда[кч]|пид[оа]р", re.I)
# Что распознавание пишет на музыке без слов: это не голос, а его выдумка.
HALLUCINATIONS = ("субтитр", "продолжение следует", "подпиш", "спасибо за просмотр", "редактор", "dimatorzok", "аминь")


def old_enough(date: str) -> bool:
    """Настоящий кусок — только из трека 2015–2022 годов по дате магазина."""
    return REAL_FROM <= (date or "") < REAL_TO


def manner(syl: float) -> str:
    return "читка" if syl >= READING else "распев"


def _run(*command) -> subprocess.CompletedProcess:
    return subprocess.run([str(c) for c in command], capture_output=True, text=True, check=True)


def _dz(path: str, **params) -> dict:
    from .sources.http import get_json

    data = get_json(f"https://api.deezer.com/{path}", params=params or None, min_interval=0.12)
    return data if isinstance(data, dict) and "error" not in data else {}


def _norm(text: str) -> str:
    return re.sub(r"[^0-9a-zа-яё]+", "", (text or "").lower().replace("ё", "е"))


def _ya_find(artist: str, track: str) -> dict | None:
    """Тот же трек на Яндексе: артист среди исполнителей, название — сперва точно, потом вхождением."""
    found = ai_labels.yandex_search(f"{artist} {track}")
    for strict in (True, False):
        for t in found:
            if _norm(artist) not in [_norm(a["name"]) for a in t.get("artists", [])]:
                continue
            a, b = _norm(t["title"]), _norm(track)
            if a == b or not strict and (a in b or b in a):
                return t
    return None


def search(pool: dict, words: list[str]) -> None:
    """Новые кандидаты: ИИ с двумя метками и настоящие 2015–2022 без метки Deezer."""
    found = {}
    for word in words:
        for index in (0, 100):
            for t in _dz("search", q=word, limit=100, index=index).get("data") or []:
                name = t["title"] + t["artist"]["name"]
                # Украинский и белорусский мимо: кусок на другом языке выделялся бы сам.
                if CYRILLIC.search(name) and not re.search("[іїєґў]", name, re.I):
                    found[str(t["id"])] = t
    fresh = [t for key, t in found.items() if key not in pool["ai"] and key not in pool["real"] and key not in pool["skip"]]
    labels = ai_labels.deezer([t["album"]["id"] for t in fresh])
    ai = real = 0
    for t in fresh:
        key, album = str(t["id"]), labels.get(str(t["album"]["id"]), {})
        base = {"dz_track": key, "dz_album": str(t["album"]["id"]), "artist": t["artist"]["name"],
                "track": t["title_short"], "rank": t["rank"], "date": album.get("date", "")}
        if album.get("ai") is True and t["rank"] < AI_RANK:
            ya = _ya_find(base["artist"], base["track"])
            if ya and ai_labels.yandex(ya["id"]).startswith(ai_labels.FULL):
                pool["ai"][key] = {**base, "ya_id": str(ya["id"]), "ya_genre": (ya.get("albums") or [{}])[0].get("genre")}
                ai += 1
            else:
                pool["skip"].append(key)
        elif album.get("ai") is False and old_enough(album.get("date", "")) and t["rank"] < REAL_RANK:
            pool["real"][key] = base
            real += 1
    print(f"Поиск: {len(found)} треков, новых ИИ с двумя метками {ai}, настоящих 2015–2022 {real}", flush=True)


def _group(item: dict) -> str | None:
    if "group" not in item:
        genres = (_dz(f"album/{item['dz_album']}").get("genres") or {}).get("data") or []
        item["group"] = GROUPS.get(genres[0]["id"]) if genres else YA_GROUPS.get(item.get("ya_genre") or "")
    return item["group"]


def _preview(item: dict) -> Path | None:
    import requests

    path = WORK / "previews" / f"{item['dz_track']}.mp3"
    if not path.exists():
        # Ссылка превью подписана и живёт недолго — берём свежую в момент скачивания.
        url = _dz(f"track/{item['dz_track']}").get("preview")
        if not url:
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(requests.get(url, timeout=30).content)
    return path


def _asr(path: Path, language: str | None = "ru") -> tuple[list[dict], str]:
    """Строки распознавания и язык; language=None — язык определяет сама модель."""
    import mlx_whisper

    result = mlx_whisper.transcribe(str(path), path_or_hf_repo=WHISPER, language=language, word_timestamps=True,
                                    condition_on_previous_text=False)
    lines = [s for s in result["segments"] if len(re.sub(r"[^а-яё ]", "", s["text"].lower()).strip()) > 3
             and not any(h in s["text"].lower() for h in HALLUCINATIONS)]
    return lines, result.get("language") or language or ""


def _vocals(path: Path) -> Path:
    """Голос отдельно от бита (demucs): по нему видно, где кончается строка."""
    stem = WORK / "sep" / "htdemucs" / path.stem / "vocals.wav"
    if not stem.exists():
        _run(sys.executable, "-m", "demucs", "--two-stems=vocals", "-n", "htdemucs", "-d", "mps", "-o", WORK / "sep", path)
    return stem


def _envelope(path: Path):
    import librosa
    import numpy as np

    y, sr = librosa.load(_vocals(path), sr=22050, mono=True)
    rms = librosa.feature.rms(y=y, frame_length=1024, hop_length=220)[0]
    rms = np.convolve(rms, np.ones(3) / 3, mode="same")
    return 20 * np.log10(rms / (rms.max() + 1e-9) + 1e-9), 220 / sr


def _phrase_starts(path: Path) -> list[float]:
    """Начала фраз: концы пауз отделённого голоса (перенесено из ручного набора round.py).

    Пауза — голос тише −18 дБ от пика дольше 0,25 с; второй, мягкий порог (−12 дБ, 0,15 с) —
    для плотного трэпа, где реверб и эдлибы не дают голосу упасть ниже. Порог голос
    пересекает уже на слове, поэтому начало — от дна паузы, где голос поднялся на 6 дБ.
    Ищем по огибающей, а не по строкам распознавания: превью из одного припева
    распознавание сворачивает в одну строку с нуля секунд, и срезать было не по чему.
    """
    import numpy as np

    db, hop = _envelope(path)
    found: list[float] = []
    for level, shortest in ((-18, 0.25), (-12, 0.15)):
        quiet, since = db < level, None
        for i in range(len(db)):
            if quiet[i] and since is None:
                since = i
            elif not quiet[i] and since is not None:
                if (i - since) * hop >= shortest:
                    low = since + int(np.argmin(db[since:i]))
                    rise = low + int(np.argmax(db[low:i + 1] > db[low] + 6))
                    at = max(0.0, rise * hop - 0.03)
                    if all(abs(at - f) > 0.3 for f in found):
                        found.append(at)
                since = None
    return sorted(found)


def _dip(path: Path, s: float) -> float:
    import numpy as np

    db, hop = _envelope(path)
    head = db[int(s / hop):int((s + 0.06) / hop) + 1].mean()
    return float(head - np.percentile(db[int(s / hop):int((s + LEN) / hop)], 90))


def _pitch(path: Path, s: float) -> float | None:
    """Средняя высота голоса в срезе, Гц: пол и регистр без прослушивания."""
    import librosa
    import numpy as np

    y, sr = librosa.load(_vocals(path), sr=22050, mono=True, offset=s, duration=LEN)
    f0, voiced, _ = librosa.pyin(y, fmin=65, fmax=700, sr=sr)
    f0 = f0[voiced & ~np.isnan(f0)]
    return round(float(np.median(f0)), 1) if len(f0) else None


def _tempo(path: Path) -> float:
    import librosa

    y, sr = librosa.load(str(_vocals(path)).replace("vocals.wav", "no_vocals.wav"), sr=22050, mono=True)
    return round(float(librosa.beat.beat_track(y=y, sr=sr)[0][0]), 1)


def _loudness(path: Path) -> float:
    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    return float(re.findall(r"I:\s+(-?[\d.]+) LUFS", err)[-1])


def _process(src: Path, start: float, out: Path, extra: str = "") -> None:
    """Одна цепочка на все куски: срез выше 16 кГц, мягкое сжатие, −14 LUFS, лимитер, AAC 256k.
    Теги стираются: в превью зашиты имя артиста и название."""
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp.wav")
    chain = (extra + "," if extra else "") + "lowpass=f=16000,acompressor=threshold=-20dB:ratio=2.5:attack=15:release=150"
    _run("ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{LEN}", "-i", src, "-ac", "2", "-ar", "44100",
         "-af", chain, tmp)
    gain = LUFS - _loudness(tmp)
    _run("ffmpeg", "-y", "-v", "error", "-i", tmp, "-map_metadata", "-1",
         "-af", f"volume={gain:.2f}dB,alimiter=limit=0.89:level=false,afade=t=in:d=0.015,afade=t=out:st={LEN - 0.25}:d=0.25",
         "-c:a", "aac_at", "-b:a", "256k", out)
    tmp.unlink()


def _heard(src: Path, start: float) -> tuple[str, float]:
    """Полный текст куска и сколько секунд в нём поют — по отделённому голосу: без бита
    распознавание слышит слова, которые в миксе глотает. Секунда тишины спереди:
    без неё голос в сильном автотюне распознавание принимало за тишину."""
    pad = WORK / "pieces" / "heard.wav"
    _run("ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{LEN}", "-i", _vocals(src),
         "-af", "adelay=1000:all=1", pad)
    segments, _ = _asr(pad)
    text = " ".join(s["text"].strip() for s in segments)
    span = segments[-1]["end"] - segments[0]["start"] if segments else 0.0
    return text, max(span, 2.0)


def measure(item: dict) -> dict:
    """Срез 8 секунд из превью и его замеры, один раз на трек; {"why": …} — не годится."""
    if "m" not in item:
        try:
            item["m"] = _measure(item)
        except Exception as exc:  # noqa: BLE001 — один трек не срывает сборку всего запаса
            item["m"] = {"why": f"сбой замера: {str(exc)[:80]}"}
    return item["m"]


def _measure(item: dict) -> dict:
    src = _preview(item)
    if not src:
        return {"why": "превью нет"}
    duration = float(_run("ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", src).stdout)
    # Весь превью — по отделённому голосу: по миксу распознавание то слышит поющий голос, то нет.
    # Мат где угодно в превью — повод не брать трек целиком. Язык — не по кириллице в названии:
    # 27.09.2026 так в раунд прошла болгарская песня, а чужой язык выдаёт кусок сам.
    segments, language = _asr(_vocals(src), language=None)
    words = " ".join(s["text"] for s in segments)
    if language != "ru":
        return {"why": f"язык {language or 'не определился'}"}
    if len(_norm(words)) < 8:
        return {"why": "голоса нет"}
    if MAT.search(words.lower()):
        return {"why": "мат в превью"}
    tried = 0
    for s in _phrase_starts(src):
        if not 0.5 <= s <= duration - LEN - 0.1:
            continue
        head = _dip(src, s)
        if head >= DIP:
            continue
        tried += 1
        if tried > 4:
            break
        text, span = _heard(src, s)
        if MAT.search(text.lower()):
            return {"why": "мат в куске"}
        if len(_norm(text)) < 8 or len(text.split()) < 3:
            continue
        hz = _pitch(src, s)
        if not hz:
            return {"why": "высота голоса не измерилась"}
        piece = WORK / "pieces" / f"{item['dz_track']}.m4a"
        _process(src, s, piece)
        syl = round(float(len(re.findall("[аеёиоуыэюя]", text.lower())) / span), 2)
        return {"start": round(s, 2), "piece": str(piece), "text": text, "syl": syl, "hz": hz,
                "bpm": _tempo(src), "dip": round(head, 1)}
    return {"why": "нет строки, начатой после паузы"}


def distance(r: dict, a: dict) -> float:
    """Насколько настоящий кусок не похож на ИИ по темпу и высоте голоса (в октавах).
    Темп сверяется и вдвое: трэп в 72 и 144 BPM — один и тот же ход."""
    beat = min(abs(math.log2(r["bpm"] * k / a["bpm"])) for k in (0.5, 1, 2)) if r["bpm"] and a["bpm"] else 1.0
    return 2 * beat + abs(math.log2(r["hz"] / a["hz"]))


def triple(ai: dict, real: list[dict]) -> list[dict] | None:
    """Три настоящих к ИИ: ближайшие по темпу и голосу, разные артисты, ИИ по высоте внутри.

    ИИ с краю тройки — самый высокий или самый низкий голос раунда — выдаёт себя
    так же, как чужой жанр. Такой раунд не собирается.
    """
    a = ai["m"]
    near = sorted(real, key=lambda r: distance(r["m"], a))
    unique, seen = [], {_norm(ai["artist"])}
    for r in near:
        if _norm(r["artist"]) not in seen:
            unique.append(r)
            seen.add(_norm(r["artist"]))
    best = None
    for combo in combinations(unique[:10], 3):
        voices = [r["m"]["hz"] for r in combo]
        if min(voices) < a["hz"] < max(voices):
            score = sum(distance(r["m"], a) for r in combo)
            if best is None or score < best[0]:
                best = (score, list(combo))
    return best[1] if best else None


def _features(path: Path) -> tuple[float, float]:
    """Яркость (спектральный центроид, Гц) и ширина стерео (боковой к центру) готового куска."""
    import librosa
    import numpy as np

    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "2", "-ar", "44100", "-"],
                         capture_output=True, check=True).stdout
    x = np.frombuffer(raw, np.float32).reshape(-1, 2)
    mid, side = x.mean(1), (x[:, 0] - x[:, 1]) / 2
    return (float(librosa.feature.spectral_centroid(y=mid, sr=44100).mean()),
            float(np.sqrt((side**2).mean() / (mid**2).mean())))


def match(ai: dict, real: list[dict], out: Path) -> dict | None:
    """ИИ-кусок в out; подгоняется, только если он явный выброс по яркости или ширине.

    Превью выпущенного и сведённого трека — такая же правда, как у настоящих,
    поэтому трогаем лишь выброс: яркость за краем трёх настоящих больше чем
    на 15 %, ширина — на 25 %. Тянем к ближайшему краю, не к середине: правка
    наименьшая. Не дотянули — None, раунд не собирается.
    """
    feats = [_features(Path(r["m"]["piece"])) for r in real]
    cs, ws = [f[0] for f in feats], [f[1] for f in feats]
    src = _preview(ai)
    shutil.copy(ai["m"]["piece"], out)
    c0, w0 = c, w = _features(out)
    want = max(cs) if c0 > max(cs) * 1.15 else min(cs) if c0 < min(cs) / 1.15 else None
    m = (max(ws) if w0 > max(ws) * 1.25 else min(ws) if w0 < min(ws) / 1.25 else w0) / w0 if w0 else 1.0
    m, g = round(min(2.0, max(0.3, m)), 2), 0.0
    if want or m != 1.0:
        lo, hi = -12.0, 8.0
        for _ in range(7 if want else 1):  # полка верхов — делением пополам по центроиду
            g = (lo + hi) / 2 if want else 0.0
            _process(src, ai["m"]["start"], out, extra=f"extrastereo=m={m:.2f},treble=g={g:.1f}:f=2500")
            c, w = _features(out)
            lo, hi = (lo, g) if c > (want or c) else (g, hi)
    if not (min(cs) / 1.15 <= c <= max(cs) * 1.15 and min(ws) / 1.25 <= w <= max(ws) * 1.25):
        return None
    return {"treble_db": round(g, 1), "width": m, "bright": [round(c0), round(c)], "real_bright": [round(min(cs)), round(max(cs))],
            "wide": [round(w0, 2), round(w, 2)], "real_wide": [round(min(ws), 2), round(max(ws), 2)]}


def _famous(item: dict) -> bool:
    """Артист на слуху: в месячном рейтинге Яндекс Музыки выше YA_TOP.

    Узнанный голос отвечает за ИИ методом исключения. Поклонники на Deezer
    не мерка: в России его слушают мало, и у Олега Митяева их меньше пяти тысяч,
    а в рейтинге Яндекса он 1675-й. Нет артиста в поиске — не на слуху.
    """
    if "ya_parts" not in item:
        # «Глеб Самойлоff & The Matrixx» целиком Яндекс не находит, а Глеба Самойлова — да.
        parts = [p for p in re.split(r"\s*(?:&|,|/|\bfeat\.?|\bft\.?|\bx\b)\s*", item["artist"], flags=re.I) if p]
        item["ya_parts"], item["ya_rank"], item["ya_genres"] = parts, 0, []
        for part in dict.fromkeys([item["artist"], *parts]):
            found = ((ai_labels._yandex("search", text=part, type="artist", page=0).get("artists") or {})
                     .get("results") or [])
            for a in found:
                if _norm(a.get("name", "")) == _norm(part):
                    rank = (a.get("ratings") or {}).get("month") or 0
                    if rank and (not item["ya_rank"] or rank < item["ya_rank"]):
                        item["ya_rank"] = rank
                    item["ya_genres"] = item["ya_genres"] or a.get("genres") or []
                    break
    if "fans" not in item:
        # Кого Яндекс не знает, того могли снять с него: «Время и Стекло» там нет. На Deezer
        # их каталог перезалит под новым артистом с 2 тысячами поклонников, а у старого,
        # пустого, их 78 тысяч, — поэтому берём самого известного тёзку.
        item["fans"] = max([a.get("nb_fan", 0) for part in item["ya_parts"]
                            for a in _dz("search/artist", q=part, limit=10).get("data") or []
                            if _norm(a.get("name", "")) == _norm(part)] or [0])
    return 0 < item["ya_rank"] <= YA_TOP or item["fans"] >= DZ_FANS


def _modern(item: dict) -> bool:
    """Первый релиз артиста на Deezer — не раньше ARTIST_FROM.

    Дата альбома — это дата перевыпуска: 27.09.2026 так в тройку встал Муслим Магомаев
    «2019 года» — сборник записей шестидесятых. Звук той эпохи выдаёт человека сам.
    """
    if "first" not in item:
        artist = (_dz(f"track/{item['dz_track']}").get("artist") or {}).get("id")
        dates = [a.get("release_date") or "" for a in _dz(f"artist/{artist}/albums", limit=100).get("data") or []] if artist else []
        item["first"] = min([d for d in dates if d] or [""])
    return item["first"] >= ARTIST_FROM


def _same_scene(item: dict, group: str) -> bool:
    """Жанры артиста по Яндексу — из той же группы.

    Жанр альбома Deezer ставит тот, кто выкладывал, и «Pop» у него — и бард,
    и эстрада, и церковный распев: 27.09.2026 к поп-ИИ так вставали Олег Митяев
    и «Тропарь Животворящему Кресту». Кого Яндекс не знает — того не берём.
    """
    return any(YA_GROUPS.get(g) == group for g in item.get("ya_genres") or [])


def _fill(pool: dict, group: str, used: set[str]) -> list[dict]:
    """Измеренные годные настоящие этого жанра; не хватает — меряет ещё."""
    real = list(pool["real"].values())
    random.shuffle(real)

    def fits(r: dict) -> bool:
        return (state.fingerprint(r["artist"]) not in used and _group(r) == group and not _famous(r)
                and _same_scene(r, group) and _modern(r))

    ready = [r for r in real if r.get("group") == group and "hz" in r.get("m", {}) and fits(r)]
    for r in real:
        if len(ready) >= POOL_PER_GROUP:
            break
        if "m" in r or not fits(r):
            continue
        print(f"   мерю настоящего: {r['artist']} — {r['track']} ({r['date'][:4]}): "
              f"{measure(r).get('why') or 'годен'}", flush=True)
        if "hz" in r["m"]:
            ready.append(r)
        _save_pool(pool)
    return ready


def _load_pool() -> dict:
    return {"ai": {}, "real": {}, "skip": [], **state.read_json(POOL, {})}


def _save_pool(pool: dict) -> None:
    state.write_json(POOL, pool)


def _git(*args: str, cwd: Path = MAC_STATE) -> str:
    return _run("git", "-C", cwd, *args).stdout


def _checkout() -> Path:
    """Своя копия приватного хранилища — только папка запаса; git ходит ключом владельца из связки."""
    if not (MAC_STATE / ".git").exists():
        MAC_STATE.parent.mkdir(parents=True, exist_ok=True)
        _run("git", "clone", "-q", "--depth", "1", "--filter=blob:none", "--no-checkout",
             f"https://github.com/{STATE_REPO}.git", MAC_STATE)
        _git("sparse-checkout", "set", "--no-cone", f"/{STOCK}/")
        _git("checkout", "-q")
    else:
        _git("pull", "-q", "--rebase", "--autostash")
    return MAC_STATE / STOCK


def _push(message: str) -> None:
    _git("add", "-A", STOCK)
    if subprocess.run(["git", "-C", str(MAC_STATE), "diff", "--cached", "--quiet"]).returncode == 0:
        return
    _git("commit", "-q", "-m", message)
    _git("pull", "-q", "--rebase", "--autostash")
    _git("push", "-q")


def build(pool: dict, root: Path, want: int, dry_run: bool) -> int:
    """Собирает до want раундов из пула. Возвращает, сколько собрал."""
    used = set(state.read_json(root / "used.json", {}).get("artists", []))
    ais = [a for a in pool["ai"].values() if state.fingerprint(a["artist"]) not in used and not a.get("m", {}).get("why")]
    random.shuffle(ais)
    made = 0
    for ai in ais:
        if made >= want:
            break
        if state.fingerprint(ai["artist"]) in used or not _group(ai):
            continue
        try:  # метки — до тяжёлых замеров: снятая сегодня метка не стоит demucs
            if not ai_labels.confirmed(ai["ya_id"], ai["dz_album"]):
                ai["m"] = {"why": "метка снята"}
                continue
        except ai_labels.Unknown:
            continue
        print(f"ИИ: {ai['artist']} — {ai['track']} ({ai['group']})", flush=True)
        a = measure(ai)
        _save_pool(pool)
        if a.get("why"):
            print(f"   не годится: {a['why']}", flush=True)
            continue
        real = [r for r in _fill(pool, ai["group"], used) if manner(r["m"]["syl"]) == manner(a["syl"])]
        three = triple(ai, real)
        if not three:
            print(f"   тройки нет: {len(real)} настоящих той же манеры ({manner(a['syl'])}), ИИ {a['hz']:.0f} Гц", flush=True)
            continue
        folder = (Path(tempfile.mkdtemp()) if dry_run else root) / uuid.uuid4().hex[:8]
        folder.mkdir(parents=True)
        fix = match(ai, three, folder / "ai.m4a")
        if fix is None:
            print("   ИИ выбивается по яркости или ширине и не подтянулся — раунд не собран", flush=True)
            shutil.rmtree(folder)
            continue
        for i, r in enumerate(three, 1):
            shutil.copy(r["m"]["piece"], folder / f"real-{i}.m4a")
        keep = ("start", "hz", "syl", "bpm", "text")
        data = {
            "made": state.iso(),
            "ai": {**{k: ai[k] for k in ("artist", "track", "ya_id", "dz_album", "dz_track", "group")},
                   **{k: a[k] for k in keep}, "manner": manner(a["syl"]), "match": fix,
                   "yandex": f"https://music.yandex.ru/track/{ai['ya_id']}",
                   "deezer": f"https://www.deezer.com/track/{ai['dz_track']}"},
            "real": [{**{k: r[k] for k in ("artist", "track", "date", "dz_track")}, **{k: r["m"][k] for k in keep}}
                     for r in three],
        }
        state.write_json(folder / "round.json", data)
        print(f"   раунд {folder.name}: ИИ {a['hz']:.0f} Гц {a['syl']} слог/с; "
              + "; ".join(f"{r['artist']} ({r['date'][:4]}) {r['m']['hz']:.0f} Гц" for r in three), flush=True)
        used |= {state.fingerprint(x["artist"]) for x in [ai, *three]}
        made += 1
        if not dry_run:
            state.write_json(root / "used.json", {"artists": sorted(used)})
    return made


def run(dry_run: bool) -> int:
    root = _checkout()
    ready = len(stock(root))
    print(f"В запасе {ready} раундов (нужно не меньше {LOW}, собираем до {TARGET}).", flush=True)
    if ready >= LOW and not dry_run:
        return 0
    pool = _load_pool()
    search(pool, random.sample(WORDS, SEARCH_WORDS))
    _save_pool(pool)
    made = build(pool, root, max(TARGET - ready, 1 if dry_run else 0), dry_run)
    _save_pool(pool)
    if made and not dry_run:
        _push(f"прослушка «где ИИ»: запас +{made}")
    print(f"{'Собралось бы' if dry_run else 'Собрано'}: {made}. В запасе теперь {ready + (0 if dry_run else made)}.")
    return 0


def install() -> int:
    """launchd раз в неделю, в субботу днём — накануне выхода. Спал Mac — пройдёт при пробуждении."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        print("Нужен ffmpeg: brew install ffmpeg")
        return 1
    plist = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    plist.write_bytes(plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": [sys.executable, "-m", "src.quiz_ai", "--stock"],
        "WorkingDirectory": str(config.ROOT),
        "StartCalendarInterval": {"Weekday": 6, "Hour": 13, "Minute": 0},
        # У launchd PATH голый: без него не найдутся ни git, ни ffmpeg из Homebrew.
        "EnvironmentVariables": {"PATH": f"{Path(ffmpeg).parent}:/usr/bin:/bin"},
        "StandardOutPath": str(LOG_FILE),
        "StandardErrorPath": str(LOG_FILE),
    }))
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", domain, str(plist)], capture_output=True)
    subprocess.run(["launchctl", "bootstrap", domain, str(plist)], check=True)
    print(f"Готово: запас «где ИИ» проверяется по субботам в 13:00. Журнал — {LOG_FILE}")
    return 0


def _selftest() -> int:
    """Без сети: буква, мат, даты настоящих, пояснение, снятая метка.

    Запуск: python -m src.quiz_ai --selftest (его же зовёт python -m src.quiz --selftest).
    """
    from unittest import mock

    msk = timezone(timedelta(hours=3))
    assert sunday(datetime(2026, 10, 4, 12, tzinfo=timezone.utc))
    assert sunday(datetime(2026, 10, 4, 20, 30, tzinfo=timezone.utc))  # 23:30 МСК — ещё воскресенье
    assert not sunday(datetime(2026, 10, 4, 21, 30, tzinfo=timezone.utc))  # по Москве уже понедельник
    assert not sunday(datetime(2026, 10, 3, 12, tzinfo=msk))

    for last in (None, 0, 1, 2, 3):
        picks = {letter(last) for _ in range(200)}
        assert last not in picks and len(picks) == (4 if last is None else 3), (last, picks)

    clean = "Я вырос там, где карманы пусты, амбиции полны, и небо над районом серое, как стены у тебя"
    assert not MAT.search(clean.lower())
    for word in ("небо", "тебя", "себе", "рублями", "корабля", "страхуем", "победа", "ребёнок", "художник", "обеими"):
        assert not MAT.search(word), word
    # Ругань за 70-м знаком: по обрезанной строке её не было видно.
    tail = clean + " и мне похуй"
    assert len(clean) > 70 and MAT.search(tail[:70].lower()) is None and MAT.search(tail.lower())
    for word in ("блять", "заебал", "ебать", "пиздец", "нахуй", "уебан", "съебал", "мудак"):
        assert MAT.search(word), word

    assert old_enough("2022-12-31") and old_enough("2015-01-01")
    assert not old_enough("2023-01-01") and not old_enough("2026-09-03") and not old_enough("2014-12-31")
    assert not old_enough("")
    assert manner(5.0) == "читка" and manner(2.5) == "распев"

    for artist, track in (("KarDinaLL", "Имя к нулю"), ("ЛИКА ВЕТРОВА, LILMISSYOU, АЙРА НЕЙТ", "О" * 150)):
        text = explanation("В", artist, track)
        assert len(telegram.sanitize(text)) <= telegram.MAX_EXPLANATION, len(text)
        assert text.startswith("ИИ — В:") and "Deezer" in text and "правообладатель" in text

    a = {"artist": "ИИ", "m": {"hz": 143, "bpm": 140}}
    real = [{"artist": f"x{i}", "m": {"hz": hz, "bpm": 140}} for i, hz in enumerate((150, 145, 138, 160, 120))]
    three = triple(a, real)
    voices = [r["m"]["hz"] for r in three]
    assert min(voices) < 143 < max(voices), voices
    # Все настоящие ниже ИИ — ИИ был бы с краю, раунда нет.
    assert triple(a, [{"artist": f"y{i}", "m": {"hz": hz, "bpm": 140}} for i, hz in enumerate((100, 110, 120))]) is None

    # Стыки: кусок начинается через 7,5 с, плитка меняется на середине кроссфейда,
    # YouTube-версия звучит до последнего кадра.
    from .reels import PLATE_SECONDS

    plan, full = timeline(False), timeline(True)
    assert plan["starts"] == [0.0, 7.5, 15.0, 22.5] and plan["switches"] == [7.75, 15.25, 22.75]
    assert plan["total"] == 30.5 and full["switches"][-1] == 30.25
    assert abs(full["total"] - (30.25 + ANSWER + PLATE_SECONDS)) < 1e-9
    assert abs(30.5 + full["replay"] - XFADE - full["total"]) < 1e-9
    assert _switch_expr([1, 2, 3], [7.75, 15.25]) == "if(lt(t,7.75),1,if(lt(t,15.25),2,3))"

    # Истёкший ключ Deezer — сбой (Unknown), а не «метки нет»; снятый альбом — «метки нет».
    class Answer:
        status_code = 200

        def __init__(self, body: dict):
            self.body = body

        def json(self) -> dict:
            return self.body

    expired = Answer({"errors": [{"type": "JwtTokenInvalidError"}], "data": {"a0": None}})
    missing = Answer({"errors": [{"type": "AlbumNotFoundError"}], "data": {"a0": None}})
    with mock.patch.object(ai_labels.time, "sleep"), \
            mock.patch.object(ai_labels.requests, "get", return_value=Answer({"jwt": "k"})):
        with mock.patch.object(ai_labels.requests, "post", return_value=expired):
            try:
                ai_labels.deezer(["5"])
                raise AssertionError("истёкший ключ принят за «метки нет»")
            except ai_labels.Unknown:
                pass
        with mock.patch.object(ai_labels.requests, "post", return_value=missing):
            assert ai_labels.deezer(["5"])["5"]["ai"] is None

    # Снятая метка выбрасывает раунд, сбой площадки — нет; в логе ни имени, ни номера.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for name, made in (("r1", "2026-09-01"), ("r2", "2026-09-02")):
            state.write_json(root / STOCK / name / "round.json",
                             {"made": made, "ai": {"artist": "Секретный ИИ", "track": "Тайна", "ya_id": "1", "dz_album": "2"}})
        records: list[str] = []
        handler = logging.Handler()
        handler.emit = lambda record: records.append(record.getMessage())
        log.addHandler(handler)
        try:
            with mock.patch.object(config, "PRIVATE", root), \
                 mock.patch.object(ai_labels, "confirmed", side_effect=ai_labels.Unknown("сеть")):
                assert next_round() is None and len(stock()) == 2
            with mock.patch.object(config, "PRIVATE", root), \
                 mock.patch.object(ai_labels, "confirmed", side_effect=[False, True]):
                folder, data = next_round()
                assert folder.name == "r2" and [p.name for p in stock()] == ["r2"]
            with mock.patch.object(config, "PRIVATE", root), \
                 mock.patch.object(ai_labels, "confirmed", return_value=False):
                assert next_round() is None and stock() == []
        finally:
            log.removeHandler(handler)
        assert records and not any("Секретный" in r or "Тайна" in r or "r1" in r for r in records), records
    print("где ИИ: все проверки прошли")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Прослушка «где ИИ»: запас раундов на Маке")
    parser.add_argument("--stock", action="store_true", help="пополнить запас, если раундов меньше нормы")
    parser.add_argument("--dry-run", action="store_true", help="что собралось бы, без записи в хранилище")
    parser.add_argument("--install", action="store_true", help="запуск --stock раз в неделю через launchd")
    parser.add_argument("--selftest", action="store_true", help="проверки без сети")
    args = parser.parse_args()
    if args.selftest:
        return _selftest()
    if args.install:
        return install()
    if args.stock or args.dry_run:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
        config.load_dotenv()
        # Код подтягивается сам, но только в чистой копии: launchd запускает его неделями
        # без людей, а рабочую папку с чужими правками трогать нельзя.
        dirty = _run("git", "-C", config.ROOT, "status", "--porcelain", "--untracked-files=no").stdout
        if not dirty:
            subprocess.run(["git", "-C", str(config.ROOT), "pull", "-q", "--ff-only"], capture_output=True)
        print(state.iso(), flush=True)
        return run(args.dry_run)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
