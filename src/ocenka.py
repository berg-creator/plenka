"""ОЦЕНКА — готовый трек против выпущенных релизов, по числам.

Зачем. Человек с готовым треком до сих пор мог только отдать его в ОТБОР; о самом
звуке бот ему не говорил ничего. Здесь он присылает файл, бот меряет его и отвечает,
где трек стоит рядом с релизами, а где нет: «у тебя столько, у релизов от и до, что
с этим сделать на сведении или мастере». Под ответом — одна дверь: СВЕДЕНИЕ ботом,
прежней кнопкой; к звукорежиссёру ведёт кнопка под сведённым треком, и ответ её называет.

Что меряется. Самые громкие 30 секунд трека — громкость, пик, ширина, низ по бокам
и четыре полосы частот к середине — и, по всему файлу, тишина в начале и в конце.
Кусок, а не трек целиком, потому что такие эталоны: отрывок релиза в магазине — это
30 секунд из тела трека, и какие именно, заранее не узнать (у сверенного 09.10.2026 —
с 0:48, не с 0:30). Поэтому у трека берётся самое громкое место: по 46 целым трекам
его громкость расходится с куском с 0:30 на 0,3 дБ в медиане — в двадцать раз меньше
ширины норм. Замеры — готовые из сведения и его экзамена (ekzamen._r128,
skleyka.stereo, _sides, _channels, _bands), теми же фильтрами ffmpeg, что уже
работают в Actions.

Нормы — data/mix_norms.json: границы, где лежат 9 релизов из 10 (5-й и 95-й
процентили; у замеров с одной границей — 95-й), сколько релизов и дата. Пересчёт —
`--norms` на Маке, тем же кодом, что меряет трек человека: отрывки релизов из кэша
СЛЕПОЙ ПРОСЛУШКИ (группа «рэп»: в бот несут голос на бите, а у гитарной музыки низ
и середина другие) и целые треки из названных папок. Имён в файле нет. Тишина
в начале и конце нормируется только по целым трекам — у отрывка краёв нет.
Трек меряется как пришёл, без пережатия: эталоны сами MP3, граница пика снята
с них же — MP3 релиза в неё укладывается, а WAV получает запас.

Что отвергнуто.
— Разделять голос и бит (demucs): новая тяжёлая зависимость и 2–4 минуты машины
  дежурства на трек, не пробовалось. Поэтому главного — тихий ли голос и попадает ли
  он в бит — бот не слышит и говорит об этом в каждом ответе прямо.
— Балл «7 из 10»: одно число из десятка несравнимых замеров было бы выдумкой.
— Модель: числа и границы встают в шаблон; пересказ добавил бы суждений о звуке,
  которых никто не мерил. По той же причине в советах нет последствий («на площадке
  проиграет») — только число, границы и что повернуть.
— Пережимать трек в MP3 128, как лежат эталоны: LAME на этом битрейте убавляет
  уровень на 0,4 дБ (синус 1 кГц, 09.10.2026), и громкость в ответе расходилась бы
  с измерителем человека.
— Размах громкости (LRA): у 30 секунд он говорит, попал ли в кусок тихий такт, —
  у отрывков релизов от 0,7 до 11,9 LU, такой границей ничего не поймать.
— Срезанные вершины и всё выше 15 кГц: эталоны — MP3, полки вершин в них смазаны,
  а верх срезан кодеком. Корреляция каналов и потеря громкости в моно — та же
  ширина другими словами: вторая строка упрёка за одну причину. Потеря в моно
  называется числом внутри строки о ширине.

Как идёт в боте. /ocenka или кнопка меню ставят отметку «ждём трек» на WAIT_MINUTES:
файл, присланный после этого без ответа, идёт сюда, а не в ОТБОР (wants, раньше
отбора в moderate.process); открытая заявка СВЕДЕНИЯ важнее — там файл это дорожка.
Отметка, очередь и счёт суток — данные о человеке, только config.OCENKA_FILE
в приватном хранилище. Скачивание и замер — отдельным процессом (--job), как
сведение: дежурство — единственный поллер. Файл больше 20 МБ берётся служебным
входом бота, а ключ входа нельзя открывать дважды, поэтому такая оценка ждёт, пока
не идут сведение и ролик бита, а они — пока идёт она (logged). Файл человека живёт
во временной папке процесса и стирается сразу после замера.

    python -m src.ocenka --check ФАЙЛ       замер и текст ответа, без Telegram
    python -m src.ocenka --selftest         замеры на синтетике, маршрут файла, лимит — без сети
    python -m src.ocenka --norms [ПАПКА|ФАЙЛ ...]   пересчитать data/mix_norms.json (только Мак)
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import math
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from datetime import timedelta
from pathlib import Path

from . import bity, clips, config, ekzamen, otbor, skleyka, state, telegram
from .skleyka import ENV_RATE, FORMAT, MS

PIECE = 30.0  # длина куска и отрывка-эталона, с
MINUTES = (1, 10)  # отбор берёт 1–8; оценке сет не страшен, а замер десяти минут — те же секунды
WAIT_MINUTES = 30  # столько живёт отметка «ждём трек»: найти файл и залить WAV
JOB_MINUTES = 5  # замер — секунды; дольше — процесс завис на скачивании
REFUSED = 3  # код выхода --job: трек не мерился, человеку уже сказано почему
FLOOR = -60.0  # тише — «нет вовсе»: у моно-файла сторон нет, и −150 дБ в ответе — не число
# Середина, к которой меряются полосы: в ней и голос, и музыка, она есть у любого трека.
MID = (300, 3000)
BANDS = {"low": (0, 100), "lowmid": (100, 300), "pres": (3000, 6000), "top": (6000, 15000)}
QUIZ = Path.home() / ".cache" / "plenka-quiz-ai"  # кэш СЛЕПОЙ ПРОСЛУШКИ: pool.json и отрывки релизов
WHOLE = 60.0  # эталон длиннее — целый трек: у него есть начало и конец

OPENED, DONE = "ОЦЕНКА: открыта", "ОЦЕНКА: ответ выдан"  # счётчик service --sources
MARK = "Пришли готовый трек файлом"
INTRO = ("📏 <b>ОЦЕНКА</b> — замерю готовый трек и скажу, чем он отличается от выпущенных релизов.\n\n"
         f"{MARK} — голос уже на бите, MP3 или WAV, от {MINUTES[0]} до {MINUTES[1]} минут.\n\n"
         "Меряю громкость, пик, ширину, низ и баланс частот. Голос отдельно от бита в готовом файле "
         "не слышу: тихий ли он и попадает ли в бит — не скажу.")
DRAFT = "\n\nУ тебя открыта заявка СВЕДЕНИЯ — пришли трек ответом на это сообщение, иначе файл уйдёт в неё."
ACCEPTED = "Принял. Меряю — ответ через минуту-две."
HELD = "Принял. Файл большой — замерю, как только освободится очередь сведения."
BUSY = "Твой трек уже меряю — дождись ответа."
LIMIT = "Оценок в сутки — {count}. Следующая — с {time} по Москве."
TOO_BIG = f"Файл больше {config.SKLEYKA_MAX_MB} МБ. Пришли MP3 320 или FLAC — они легче."
LENGTH = f"В треке {{length}}, а меряю от {MINUTES[0]} до {MINUTES[1]} минут. Другой — /ocenka."
BAD = "Файл не читается. Пришли MP3, WAV или FLAC — /ocenka."
SILENT = "В файле тишина — похоже, выгрузился пустой трек. Пришли заново — /ocenka."
FAILED = ("Не вышло — что-то сломалось у меня. Попробуй ещё раз: /ocenka. Оценка на сутки не потрачена. "
          "Снова не вышло — напиши /vopros.")
HEAD = ("📏 <b>ОЦЕНКА</b>\n\nСравнил самые громкие 30 секунд трека (с {at}) с тридцатью секундами каждого "
        "из {count} выпущенных релизов. Границы — где лежат 9 релизов из 10. Частоты — в дБ к середине, 300–3000 Гц.")
CLEAN = "Отличий от релизов не нашёл."
DEAF = ("<b>Чего не слышу.</b> Голос отдельно от бита: тихий ли он и попадает ли в бит, по готовому файлу "
        "не измерить. Пришли вокал и бит отдельно — сведу сам, кнопка ниже. Под сведённым треком будет "
        "и «🎧 Отдать звукорежиссёру» — сведёт человек.")
# Кнопка существующая: открывает заявку СВЕДЕНИЯ (service: s:skleyka). Кнопки звукорежиссёра здесь нет:
# skleyka.HAND_BUTTON берёт последний готовый трек бота и выставила бы счёт задатка по нему, а не по файлу,
# присланному на оценку. Дорога к звукорежиссёру — из-под сведённого трека, DEAF её называет.
KEYS = [[{"text": "🎛 Свести ботом — вокал и бит", "callback_data": "s:skleyka"}]]
# Замер → (имя в строке «как у релизов», строка упрёка, совет ниже границы, совет выше границы).
# В советах — только что повернуть: последствий бот не мерил.
LINES = {
    "lufs": ("громкость", "<b>Громкость</b> — {v} LUFS, у релизов {r}.",
             "Трек тише: на мастере подними громкость лимитером.", "Трек громче: на мастере ослабь лимитер."),
    "peak": ("пик", "<b>Пик</b> — {v} дБ, у релизов {r}.", "", "На мастере опусти потолок лимитера."),
    "sides": ("ширина", "<b>Ширина</b> — стороны {v} дБ к центру, у релизов {r}.",
              "Узкое стерео: на сведении разведи по сторонам даблы, бэки или музыку.",
              "Широкое стерео{mono}: на сведении сузь его."),
    "lowside": ("низ в центре", "<b>Низ по бокам</b> — ниже 100 Гц стороны {v} дБ к центру, у релизов {r}.",
                "", "На сведении собери бас и бочку в центр."),
    "low": ("низ", "<b>Низ, до 100 Гц</b> — {v} дБ, у релизов {r}.",
            "Низа меньше: на сведении прибавь 808 и бочку.",
            "Низа больше: на сведении убавь 808 и бочку или подрежь низ эквалайзером."),
    "lowmid": ("100–300 Гц", "<b>100–300 Гц</b> — {v} дБ, у релизов {r}.",
               "Полосы меньше: на сведении прибавь её эквалайзером.",
               "Полосы больше: на сведении подрежь её эквалайзером — на бите и на голосе."),
    "pres": ("3–6 кГц", "<b>3–6 кГц</b> — {v} дБ, у релизов {r}.",
             "Полосы меньше: на сведении прибавь её на голосе.",
             "Полосы больше: на сведении убавь её — на голосе, хэтах и синтезаторах."),
    "top": ("верх", "<b>Верх, 6–15 кГц</b> — {v} дБ, у релизов {r}.",
            "Верха меньше: на сведении прибавь его полкой от 6 кГц.",
            "Верха больше: на сведении убавь его — деэссер на голос, хэты тише."),
    "head": ("начало", "<b>Пустое начало</b> — {v} с тишины до первого звука, у релизов {r} с.",
             "", "Обрежь при выгрузке."),
    "tail": ("конец", "<b>Тишина в конце</b> — {v} с, у релизов {r} с.", "", "Обрежь при выгрузке."),
}
UPPER = ("peak", "lowside", "head", "tail")  # граница одна, сверху: «меньше» здесь не изъян
# Три полосы из четырёх ушли в одну сторону — причина одна, и она в середине, к которой они меряются:
# одна строка вместо трёх-четырёх. Бит без голоса так получал пять упрёков разом (09.10.2026).
MID_LESS = ("<b>Середина, 300–3000 Гц</b> — тише остальных полос, чем у релизов. К ней: {bands}. "
            "На сведении прибавь середину — в ней голос и основа музыки.")
MID_MORE = ("<b>Середина, 300–3000 Гц</b> — громче остальных полос, чем у релизов. К ней: {bands}. "
            "На сведении убавь середину или прибавь низ и верх.")
# Граница «9 из 10» стоит на каждом замере отдельно, а замеров десять: хотя бы одно отличие набирает
# почти половина самих релизов (09.10.2026 — 63 из 142). Без этой строки одно отличие читалось бы приговором.
COMMON = ("\n\nХотя бы одно отличие есть у {flagged} из {count} этих релизов: одно отличие ещё не значит, "
          "что трек сведён плохо.")
MONO = "<b>Ширина</b> — трек моно, сторон нет; у релизов стороны {r} дБ к центру."  # вместо «−60 дБ»


# ─────────────────────────── замер ───────────────────────────

def edges(path: Path) -> tuple[float, float, float] | None:
    """(с какой секунды самые громкие PIECE секунд, тишина в начале, тишина в конце) — за один
    проход по файлу; None — в файле тишина. Тишина — как в контроле сведения (skleyka._sound)."""
    level = skleyka._envelope(path, f"{FORMAT},")
    sound = skleyka._lines(level, skleyka.STILL, skleyka.GAP) if level else []
    if not sound or max(level) <= -100:
        return None
    flat, span = [10 ** (db / 20) for db in level], round(PIECE * ENV_RATE)
    total = best = sum(flat[:span])
    start = 0
    for i in range(span, len(flat)):
        total += flat[i] - flat[i - span]
        if total > best:
            best, start = total, i - span + 1
    return start / ENV_RATE, sound[0][0], len(level) / ENV_RATE - sound[-1][1]


def _power(levels: list[float]) -> float:
    """Средняя мощность по окнам, дБ."""
    return 10 * math.log10(max(sum(10 ** (db / 10) for db in levels) / max(len(levels), 1), 1e-15))


def measure(piece: Path) -> dict[str, float]:
    """Замеры куска: громкость LUFS, истинный пик дБ, стороны к центру выше 150 Гц и ниже 100 Гц,
    потеря громкости в моно LU, полосы BANDS к середине MID, дБ."""
    lufs, _, plr = ekzamen._r128(piece)
    mid, side = skleyka._channels(piece, f"{FORMAT},{skleyka._band(*BANDS['low'])},{MS},")[:2]
    cuts = [skleyka._band(*band) for band in (MID, *BANDS.values())]
    middle, *bands = (_power(band) for band in skleyka._bands(piece, f"{FORMAT},", cuts=cuts, step=1.0))
    found = {"lufs": lufs, "peak": lufs + plr, "sides": skleyka._sides(piece), "lowside": side - mid,
             "mono": skleyka.stereo(piece, f"{FORMAT},")[1], **{name: db - middle for name, db in zip(BANDS, bands)}}
    return {name: round(max(value, FLOOR), 1) for name, value in found.items()}


def gauge(path: Path) -> dict[str, float] | None:
    """Все замеры файла: кусок — measure, плюс at (начало куска), head и tail; None — тишина.
    Кусок режется в WAV с плавающей точкой: у декодированного MP3 пик выше нуля, и 24 бита его срезали бы."""
    if not (found := edges(path)):
        return None
    with tempfile.TemporaryDirectory(prefix="ocenka-") as work:
        piece = Path(work) / "piece.wav"
        skleyka._ffmpeg("-ss", f"{found[0]:.2f}", "-t", PIECE, "-i", path, "-vn", "-ac", 2, "-ar", skleyka.RATE,
                        "-c:a", "pcm_f32le", piece)
        return {**measure(piece), "at": found[0], "head": round(found[1], 1), "tail": round(found[2], 1)}


# ─────────────────────────── ответ ───────────────────────────

def _n(value: float, signed: bool = True) -> str:
    """Число человеку: запятая и настоящий минус; у секунд знака нет."""
    return f"{value:{'+' if signed else ''}.1f}".replace("-", "−").replace(".", ",")


def _side(found: dict, norms: dict, name: str) -> int | None:
    """Где замер к границам релизов: −1 ниже, 0 внутри, +1 выше; None — замера или нормы нет."""
    low, high = norms.get(name) or (None, None)
    if name not in found or high is None:
        return None
    return 1 if found[name] > high else -1 if low is not None and found[name] < low else 0


def blame(found: dict, norms: dict) -> dict[str, int]:
    """Замеры вне границ: {имя: −1 ниже, +1 выше}; «mid» — середина, когда три полосы из четырёх
    ушли в одну сторону: −1 — она тише остальных, +1 — громче."""
    out = {name: side for name in LINES if (side := _side(found, norms, name))}
    for side in (1, -1):
        tilted = [name for name in BANDS if out.get(name) == side]
        if len(tilted) >= 3:
            out = {name: value for name, value in out.items() if name not in tilted} | {"mid": -side}
    return out


def report(found: dict, norms: dict) -> str:
    """Ответ человеку: что вне границ — строкой с числом, границами и советом, остальное — списком."""
    bounds, rows = norms["norms"], []
    for name, side in blame(found, bounds).items():
        if name == "mid":
            bands = ", ".join(f"{LINES[band][0]} {_n(found[band])} дБ ({'у релизов ' * (not n)}"
                              f"{'до' if side < 0 else 'от'} {_n(bounds[band][side < 0])})"
                              for n, band in enumerate(b for b in BANDS if _side(found, bounds, b) == -side))
            rows.append("• " + (MID_LESS if side < 0 else MID_MORE).format(bands=bands))
            continue
        _, line, less, more = LINES[name]
        low, high = bounds[name]
        signed = name not in ("head", "tail")
        limits = f"не {'выше' if signed else 'дольше'} {_n(high, signed)}" if name in UPPER \
            else f"от {_n(low)} до {_n(high)}"
        line = MONO if name == "sides" and found[name] <= FLOOR else line
        mono = f", а в моно трек теряет {_n(found['mono'], False)} LU громкости" if found.get("mono", 0) >= 0.1 else ""
        rows.append(f"• {line.format(v=_n(found[name], signed), r=limits)} {(more if side > 0 else less).format(mono=mono)}")
    fine = [LINES[name][0] for name in LINES if _side(found, bounds, name) == 0]
    common = COMMON.format(flagged=norms["flagged"], count=norms["releases"]) if norms.get("flagged") else ""
    return "\n\n".join(filter(None, (
        HEAD.format(at=skleyka._minutes(found["at"]), count=norms["releases"]),
        "<b>Отличается от релизов</b>\n" + "\n".join(rows) + common if rows else CLEAN,
        f"<b>Как у релизов:</b> {', '.join(fine)}." if fine else "",
        DEAF)))


def load_norms() -> dict:
    return state.read_json(config.MIX_NORMS, {})


def assess(path: Path) -> tuple[str, bool]:
    """(текст человеку, мерился ли трек): отказ по длине, битому файлу и тишине — тоже текст."""
    length = clips.probe_seconds(path)
    if not length:
        return BAD, False
    if not MINUTES[0] * 60 <= length <= MINUTES[1] * 60:
        return LENGTH.format(length=skleyka._minutes(length)), False
    try:
        found = gauge(path)
    except subprocess.CalledProcessError:  # длину контейнер назвал, а звука в нём нет
        return BAD, False
    return (report(found, load_norms()), True) if found else (SILENT, False)


# ─────────────────────────── бот ───────────────────────────

def load() -> dict:
    data = state.read_json(config.OCENKA_FILE, {})
    for key, empty in (("wait", {}), ("used", {}), ("jobs", [])):
        data.setdefault(key, empty)
    return data


def save(data: dict) -> None:
    """Протухшее — прочь при каждой записи: отметки старше WAIT_MINUTES и счёт старше суток."""
    data["wait"] = {chat: at for chat, at in data["wait"].items() if skleyka._age(at) < WAIT_MINUTES * 60}
    data["used"] = {chat: live for chat, stamps in data["used"].items()
                    if (live := [at for at in stamps if skleyka._age(at) < 86400])}
    state.write_json(config.OCENKA_FILE, data)


def _refusal(data: dict, chat_id: str, admin: bool) -> str:
    """Почему сейчас нельзя: трек этого человека уже в очереди или суточный лимит; пусто — можно."""
    if any(job["chat"] == chat_id for job in data["jobs"]):
        return BUSY
    recent = sorted(at for at in data["used"].get(chat_id, []) if skleyka._age(at) < 86400)
    if admin or len(recent) < config.OCENKA_PER_DAY:
        return ""
    from .compose import MSK

    free = state._parse(recent[-config.OCENKA_PER_DAY]) + timedelta(days=1)
    return LIMIT.format(count=config.OCENKA_PER_DAY, time=free.astimezone(MSK).strftime("%H:%M"))


def start(chat_id: str | int, *, admin: bool = False) -> None:
    """/ocenka и кнопка меню: отметка «ждём трек» и что прислать. Открытую заявку ОТБОРА закрывает,
    как любая другая команда: иначе следующий файл ушёл бы в неё."""
    chat_id, data = str(chat_id), load()
    if refusal := _refusal(data, chat_id, admin):
        telegram.send_message(chat_id, refusal)
        return
    otbor.cancel(chat_id)
    data["wait"][chat_id] = state.iso()
    save(data)
    telegram.send_message(chat_id, INTRO + (DRAFT if skleyka.active(chat_id) else ""))


def wants(message: dict) -> bool:
    """Трек ли это на оценку: файл в личке ответом на приглашение или при живой отметке. Заявка ОТБОРА,
    открытая после отметки, важнее: человек передумал. Заявку СВЕДЕНИЯ дежурство спрашивает раньше."""
    if message.get("chat", {}).get("type") != "private" or not skleyka._item(message):
        return False
    if reply := message.get("reply_to_message"):
        return MARK in (reply.get("text") or "")
    chat_id = str(message["chat"]["id"])
    return skleyka._age(load()["wait"].get(chat_id, "")) < WAIT_MINUTES * 60 and not otbor.active(chat_id)


def _big(job: dict) -> bool:
    """Нужен ли файлу служебный вход: Bot API отдаёт до 20 МБ (skleyka._fetch)."""
    return not job["s"] or job["s"] > telegram.MAX_DOWNLOAD


def _held(job: dict) -> bool:
    """Большой файл ждёт, пока служебный вход занят сведением или роликом бита."""
    return _big(job) and (skleyka.busy(drafts=False) or bity.rendering())


def take(message: dict, *, admin: bool = False) -> None:
    """Файл на оценку — в очередь; замер начнёт tick. Отметка гаснет с первым файлом; слишком большой
    её оставляет — человек пришлёт файл легче. От имени файла хранится только расширение."""
    chat_id, item, data = str(message["chat"]["id"]), skleyka._item(message), load()
    data["wait"].pop(chat_id, None)
    if not (text := _refusal(data, chat_id, admin)):
        if item["s"] > config.SKLEYKA_MAX_MB * 1024 * 1024:
            text, data["wait"][chat_id] = TOO_BIG, state.iso()
        else:
            job = {"chat": chat_id, "m": item["m"], "f": item["f"], "s": item["s"], "at": state.iso(),
                   "n": "x" + Path(item["n"]).suffix.lower()}
            data["jobs"].append(job)
            text = HELD if _held(job) else ACCEPTED
    save(data)
    telegram.send_message(chat_id, text)


# Оценка, что идёт сейчас: (процесс, задание, папка). Одна на дежурство.
_RUNNING: tuple[subprocess.Popen, dict, Path] | None = None


def busy() -> bool:
    """Идёт или ждёт оценка: смена тогда не уступает свежему коду."""
    return bool(_RUNNING or load()["jobs"])


def logged() -> bool:
    """Идёт ли оценка большого файла: она держит служебный вход, сведение и ролик бита ждут."""
    return bool(_RUNNING and _RUNNING[0].poll() is None and _big(_RUNNING[1]))


def tick() -> None:
    """Круг дежурства: кончившаяся оценка — прочь из очереди и в счёт суток, следующая — в ход.
    Очередь лежит в хранилище: оценку, оборванную концом смены, начнёт заново следующая.
    ponytail: смена, убитая между ответом и этим кругом, даст человеку второй ответ; мешает — писать
    отметку «отвечено» из процесса."""
    global _RUNNING
    if _RUNNING and (_RUNNING[0].poll() is not None or skleyka._age(_RUNNING[1]["started"]) > JOB_MINUTES * 60):
        (process, job, work), _RUNNING = _RUNNING, None
        if process.poll() is None:
            process.kill()
        shutil.rmtree(work, ignore_errors=True)
        data = load()
        data["jobs"] = [j for j in data["jobs"] if (j["chat"], j["m"]) != (job["chat"], job["m"])]
        if process.returncode == 0:
            data["used"].setdefault(job["chat"], []).append(state.iso())
            skleyka._count(DONE)
        elif process.returncode != REFUSED:
            telegram.send_message(job["chat"], FAILED)
        save(data)
    if _RUNNING or not (job := next((j for j in load()["jobs"] if not _held(j)), None)):
        return
    work = Path(tempfile.mkdtemp(prefix="ocenka-"))
    (work / "job.json").write_text(json.dumps(job))
    job["started"] = state.iso()
    print("  оценка: пошла")
    _RUNNING = subprocess.Popen([sys.executable, "-m", "src.ocenka", "--job", str(work / "job.json")],
                                cwd=config.ROOT), job, work


def finish(seconds: int = 60) -> None:
    """Конец смены: идущую оценку дождаться — человек ждёт ответа секунды, а не следующую смену."""
    if _RUNNING:
        with contextlib.suppress(subprocess.TimeoutExpired):
            _RUNNING[0].wait(seconds)
        if _RUNNING[0].poll() is not None:
            tick()


def run_job(spec: Path) -> int:
    """Процесс одной оценки: скачать, замерить, ответить. Вход закрывается до замера, файл человека
    стирается сразу после него. Код выхода: 0 — замер выдан, REFUSED — отказ уже сказан, прочее — сбой."""
    job, work = json.loads(spec.read_text()), spec.parent / "in"
    try:
        with contextlib.ExitStack() as login:
            path = skleyka._fetch({"files": [job]}, work, skleyka._service(login))[0][1]
        text, measured = assess(path)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    telegram.send_message(job["chat"], text, buttons=KEYS if measured else None)
    return 0 if measured else REFUSED


# ─────────────────────────── нормы ───────────────────────────

def _percentile(values: list[float], share: float) -> float:
    values = sorted(values)
    return values[round(share * (len(values) - 1))]


def _etalon(path: str) -> dict | None:
    """Замер одного эталона для пула процессов; None — файл не читается или в нём тишина."""
    with contextlib.suppress(Exception):
        if found := gauge(Path(path)):
            return {**found, "whole": clips.probe_seconds(Path(path)) > WHOLE}
    return None


def make_norms(extra: list[str]) -> dict:
    """Нормы по отрывкам релизов из кэша СЛЕПОЙ ПРОСЛУШКИ (группа «рэп», настоящие, не ИИ) и по целым
    трекам из extra — файлы и папки. Начало и конец — только по целым. Имена никуда не пишутся."""
    pool = json.loads((QUIZ / "pool.json").read_text())["real"]
    files = [QUIZ / "previews" / f"{track}.mp3" for track, item in pool.items() if item.get("group") == "рэп"]
    for path in map(Path, extra):
        files += sorted(p for p in path.iterdir() if p.suffix.lower() in skleyka.AUDIO_EXT) if path.is_dir() else [path]
    with ProcessPoolExecutor(8) as workers:
        rows = [row for row in workers.map(_etalon, [str(p) for p in files if p.exists()]) if row]
    whole = [row for row in rows if row["whole"]]
    norms = {}
    for name in LINES:
        values = [row[name] for row in (whole if name in ("head", "tail") else rows)]
        if values:
            norms[name] = [None if name in UPPER else _percentile(values, 0.05), _percentile(values, 0.95)]
    tally = Counter(min(len(blame(row, norms)), 2) for row in rows)
    print(f"Релизов {len(rows)}: отрывков {len(rows) - len(whole)}, целых {len(whole)}. "
          f"Сами по этим нормам: без упрёка {tally[0]}, один {tally[1]}, два и больше {tally[2]}.")
    return {"measured": state.now().strftime("%Y-%m-%d"), "releases": len(rows), "pieces": len(rows) - len(whole),
            "whole": len(whole), "flagged": tally[1] + tally[2], "norms": norms}


# ─────────────────────────── самопроверка ───────────────────────────

def _selftest() -> int:
    """Синтетика через ffmpeg, свои нормы и подменённый Telegram: сети и настоящего бота здесь нет."""
    norms = {"releases": 141, "norms": {"lufs": [-14.0, -6.0], "peak": [None, 2.0], "sides": [-16.0, -3.0],
                                       "lowside": [None, -9.0], "low": [-4.0, 11.0], "lowmid": [-9.0, 2.0],
                                       "pres": [-20.0, -10.0], "top": [-20.0, -7.0], "head": [None, 1.0], "tail": [None, 5.0]}}
    tau = 2 * math.pi

    def synth(dest: Path, gain: float = 1.0, seconds: int = 62, flip: int = 1, mid: float = 0.2) -> Path:
        """Трек из синусов: 60 Гц — низ, 200, 1000 и 4500, 9000 Гц — по центру, 1700 Гц в противофазе —
        стороны. flip=-1 — и низ в противофазе: ушёл в бока."""
        rest = f"0.16*sin(W*200*t)+{mid}*sin(W*1000*t)+0.06*sin(W*4500*t)+0.03*sin(W*9000*t)"
        left = f"{gain}*(0.25*sin(W*60*t)+{rest}+0.07*sin(W*1700*t))"
        right = f"{gain}*({flip}*0.25*sin(W*60*t)+{rest}-0.07*sin(W*1700*t))"
        skleyka._ffmpeg("-f", "lavfi", "-i", f"aevalsrc='{left}|{right}':s={skleyka.RATE}:d={seconds}".replace("W", f"{tau:.6f}"),
                        "-c:a", "pcm_f32le", dest)
        return dest

    with tempfile.TemporaryDirectory(prefix="ocenka-test-") as tmp:
        tmp = Path(tmp)
        # 1. Замеры: нормальный трек — без упрёков, у каждого изъяна — своя строка и только она.
        fine = gauge(synth(tmp / "fine.wav"))
        assert not blame(fine, norms["norms"]), fine
        text = report(fine, norms)
        assert CLEAN in text and DEAF in text and "из 141 выпущенных" in text and "Как у релизов:</b> громкость, пик" in text
        assert "балл" not in text.lower() and "из 10</b>" not in text

        quiet = gauge(synth(tmp / "quiet.wav", gain=0.2))
        assert blame(quiet, norms["norms"]) == {"lufs": -1}, quiet
        text = report(quiet, norms)
        assert f"<b>Громкость</b> — {_n(quiet['lufs'])} LUFS, у релизов от −14,0 до −6,0. Трек тише" in text, text
        assert "Как у релизов:</b> пик, ширина" in text and CLEAN not in text and "Хотя бы одно" not in text
        assert "есть у 63 из 141 этих релизов" in report(quiet, norms | {"flagged": 63})
        assert "Хотя бы одно" not in report(fine, norms | {"flagged": 63})

        # Срезанный: громкость выше границы, вершины упёрлись в ноль — 16 бит режут всё, что выше.
        skleyka._ffmpeg("-i", tmp / "fine.wav", "-af", "volume=14dB", "-c:a", "pcm_s16le", tmp / "clipped.wav")
        clipped = gauge(tmp / "clipped.wav")
        assert blame(clipped, norms["norms"]).get("lufs") == 1 and clipped["peak"] > -0.5, clipped
        assert "Трек громче: на мастере ослабь лимитер." in report(clipped, norms)
        loud = dict(fine, peak=3.1)
        assert "<b>Пик</b> — +3,1 дБ, у релизов не выше +2,0. На мастере опусти потолок" in report(loud, norms)

        # Бас в противофазе: в бока ушёл только низ, ширина выше 150 Гц почти та же (срез ширины пологий).
        bass = gauge(synth(tmp / "bass.wav", flip=-1))
        assert blame(bass, norms["norms"]) == {"lowside": 1} and abs(bass["sides"] - fine["sides"]) < 3, bass
        assert "<b>Низ по бокам</b>" in report(bass, norms) and "собери бас и бочку в центр" in report(bass, norms)

        # Одна причина — одна строка: громкая середина роняет все четыре полосы, тихая — поднимает.
        thick = gauge(synth(tmp / "thick.wav", gain=0.5, mid=0.6))
        assert blame(thick, norms["norms"])["mid"] == 1 and not set(BANDS) & set(blame(thick, norms["norms"])), thick
        text = report(thick, norms)
        assert "<b>Середина, 300–3000 Гц</b> — громче остальных полос" in text and text.count("•") == len(blame(thick, norms["norms"]))
        assert f"низ {_n(thick['low'])} дБ (у релизов от −4,0), 100–300 Гц {_n(thick['lowmid'])} дБ (от −9,0)" in text, text
        thin = dict(fine, low=12.0, lowmid=3.0, pres=-8.0)
        assert blame(thin, norms["norms"]) == {"mid": -1}
        text = report(thin, norms)
        assert "тише остальных полос, чем у релизов. К ней: низ +12,0 дБ (у релизов до +11,0), 100–300 Гц +3,0 дБ (до +2,0), " \
               "3–6 кГц −8,0 дБ (до −10,0). На сведении прибавь середину" in text, text
        assert "ширина, низ в центре, верх, начало, конец." in text, "полосы из строки о середине в «как у релизов» не идут"
        assert blame(dict(fine, low=12.0, top=-5.0), norms["norms"]) == {"low": 1, "top": 1}, "две полосы — две строки"

        # Моно: сторон нет — словами, а не «−60 дБ»; широкий трек называет потерю в моно.
        skleyka._ffmpeg("-i", tmp / "fine.wav", "-af", skleyka.MID, "-ac", 2, "-c:a", "pcm_f32le", tmp / "mono.wav")
        mono = gauge(tmp / "mono.wav")
        assert mono["sides"] == FLOOR and MONO.format(r="от −16,0 до −3,0") + " Узкое стерео:" in report(mono, norms)
        assert "Широкое стерео, а в моно трек теряет 2,4 LU громкости: на сведении сузь его." in report(dict(fine, sides=-1.0, mono=2.4), norms)

        # Края: тишина в начале и в конце — по всему файлу; кусок берётся из громкого места.
        skleyka._ffmpeg("-i", tmp / "fine.wav", "-af", "adelay=4000:all=1,apad=pad_dur=9", "-c:a", "pcm_f32le",
                        tmp / "edges.wav")
        padded = gauge(tmp / "edges.wav")
        assert blame(padded, norms["norms"]) == {"head": 1, "tail": 1} and padded["at"] >= 3.9, padded
        text = report(padded, norms)
        assert "<b>Пустое начало</b> — 4,0 с тишины до первого звука, у релизов не дольше 1,0 с. Обрежь" in text, text
        assert "<b>Тишина в конце</b> — 9,0 с" in text
        assert "head" not in blame(padded, {k: v for k, v in norms["norms"].items() if k != "head"}), "нет нормы — нет упрёка"

        # Отказы до замера: короткий, длинный, пустой и нечитаемый файл.
        real_norms, config.MIX_NORMS = config.MIX_NORMS, tmp / "norms.json"
        state.write_json(config.MIX_NORMS, norms)
        try:
            assert assess(synth(tmp / "short.wav", seconds=20)) == (LENGTH.format(length="0:20"), False)
            skleyka._ffmpeg("-f", "lavfi", "-i", "anullsrc=d=70", "-c:a", "pcm_s16le", tmp / "silent.wav")
            assert assess(tmp / "silent.wav") == (SILENT, False)
            (tmp / "text.mp3").write_text("не звук")
            assert assess(tmp / "text.mp3") == (BAD, False)
            assert assess(tmp / "quiet.wav") == (report(quiet, norms), True)
            # MP3 того же трека — те же строки: кодек упрёка не добавляет.
            skleyka._ffmpeg("-i", tmp / "fine.wav", "-c:a", "libmp3lame", "-b:a", "128k", tmp / "fine.mp3")
            assert not blame(gauge(tmp / "fine.mp3"), norms["norms"]), gauge(tmp / "fine.mp3")
        finally:
            config.MIX_NORMS = real_norms

        # 2. Настоящие нормы: числа на месте, имён нет, релизов не меньше сорока.
        shipped = load_norms()
        assert shipped["releases"] >= 40 and set(shipped["norms"]) == set(LINES), shipped.get("releases")
        assert set(shipped) == {"measured", "releases", "pieces", "whole", "flagged", "norms"}, "в файле норм — только числа"
        assert all(high is not None and (low is None) == (name in UPPER) for name, (low, high) in shipped["norms"].items())

        # 3. Бот: отметка, маршрут файла, лимит, очередь. Telegram и процесс замера подменены.
        sent: list[tuple] = []
        real = (telegram.send_message, config.OCENKA_FILE, config.SKLEYKA_FILE, config.OTBOR_FILE, subprocess.Popen,
                skleyka._count, state.now)
        telegram.send_message = lambda chat, text, **kw: sent.append((str(chat), text, kw.get("buttons")))
        config.OCENKA_FILE, config.SKLEYKA_FILE, config.OTBOR_FILE = (tmp / f"{n}.json" for n in ("oc", "sk", "ot"))
        counted: list[str] = []
        skleyka._count = counted.append

        def file(chat: int, message_id: int, size: int = 5_000_000, reply: str = "", name: str = "Мой трек.mp3") -> dict:
            return {"message_id": message_id, "chat": {"id": chat, "type": "private"}, "from": {"id": chat},
                    "audio": {"file_id": f"F{message_id}", "file_name": name, "file_size": size},
                    **({"reply_to_message": {"text": reply}} if reply else {})}

        def route(message: dict) -> str:
            """Порядок дежурства (moderate.process): дорожка сведения, оценка, отбор."""
            return "дорожки" if skleyka.wants(message) else "оценка" if wants(message) else "отбор"

        class Done:
            def __init__(self, code: int | None):
                self.returncode = code

            def poll(self):
                return self.returncode

            def kill(self):
                self.returncode = -9

        global _RUNNING
        try:
            import inspect

            from . import moderate

            flow = inspect.getsource(moderate.process)
            assert flow.index("bity.wants(message, admin)") < flow.index("skleyka.wants(message)") \
                < flow.index("ocenka.wants(message)") < flow.index("track_file(message)"), "бит и сведение раньше, отбор позже"

            assert route(file(7, 1)) == "отбор", "без отметки файл — трек в отбор"
            start(7)
            assert sent[-1] == ("7", INTRO, None) and MARK in INTRO and "не слышу" in INTRO
            assert route(file(7, 2)) == "оценка" and route(file(8, 2)) == "отбор", "отметка — только у своего чата"
            assert route({**file(7, 2), "chat": {"id": 7, "type": "group"}}) == "отбор", "в группе оценки нет"
            assert not wants({"message_id": 3, "chat": {"id": 7, "type": "private"}, "text": "вот трек"}), "текст — не файл"
            # Заявка СВЕДЕНИЯ открыта — файл без ответа идёт в дорожки, ответом на приглашение — в оценку.
            data = skleyka.load()
            data["drafts"]["7"] = {"at": state.iso(), "files": [], "user": "7"}
            skleyka.save(data)
            assert skleyka.active(7) and route(file(7, 2)) == "дорожки" and route(file(7, 2, reply=INTRO)) == "оценка"
            start(7)
            assert sent[-1][1] == INTRO + DRAFT
            skleyka.cancel(7)
            # Заявка ОТБОРА, открытая после отметки, забирает файл; /ocenka закрывает её сам.
            draft = otbor.load()
            draft["drafts"]["7"] = {"at": state.iso()}
            otbor.save(draft)
            assert route(file(7, 2)) == "отбор"
            start(7)
            assert not otbor.active(7) and route(file(7, 2)) == "оценка"
            # Отметка гаснет сама через WAIT_MINUTES.
            state.now = lambda: real[6]() + timedelta(minutes=WAIT_MINUTES + 1)
            assert route(file(7, 2)) == "отбор"
            state.now = real[6]

            # Файл принят: отметка гаснет с ним, второй файл — уже в отбор; в хранилище — без имени файла.
            spawned: list[list] = []
            subprocess.Popen = lambda args, **_: spawned.append(args) or Done(None)
            take(file(7, 2))
            assert sent[-1] == ("7", ACCEPTED, None) and route(file(7, 4)) == "отбор"
            assert "Мой трек" not in config.OCENKA_FILE.read_text() and load()["jobs"][0]["n"] == "x.mp3"
            start(7)
            assert sent[-1][1] == BUSY, "пока трек меряется, второй не берём"
            tick()
            assert spawned[-1][1:4] == ["-m", "src.ocenka", "--job"] and busy() and not logged()
            assert json.loads(Path(spawned[-1][4]).read_text())["f"] == "F2"
            tick()
            assert len(spawned) == 1, "оценка идёт — вторая не начинается"
            # Замер выдан: из очереди прочь, в счёт суток — раз, папка стёрта.
            work = _RUNNING[2]
            _RUNNING[0].returncode = 0
            tick()
            assert not busy() and len(load()["used"]["7"]) == 1 and counted == [DONE] and not work.exists()
            # Отказ процесса (не та длина) суток не тратит и второго сообщения не шлёт; сбой — FAILED.
            for code, said in ((REFUSED, ACCEPTED), (1, FAILED)):
                start(7)
                take(file(7, 5))
                tick()
                _RUNNING[0].returncode = code
                tick()
                assert sent[-1][1] == said and len(load()["used"]["7"]) == 1, code
            # Лимит суток: после третьей оценки — отказ со временем; владельцу лимита нет; через сутки — снова можно.
            data = load()
            data["used"]["7"] = [state.iso()] * config.OCENKA_PER_DAY
            save(data)
            start(7)
            assert sent[-1][1].startswith(f"Оценок в сутки — {config.OCENKA_PER_DAY}. Следующая — с ") and not load()["wait"]
            take(file(7, 6, reply=INTRO))
            assert sent[-1][1].startswith("Оценок в сутки") and not load()["jobs"], "лимит держит и файл ответом"
            start(7, admin=True)
            assert sent[-1][1] == INTRO
            state.now = lambda: real[6]() + timedelta(days=1, minutes=1)
            start(7)
            assert sent[-1][1] == INTRO and not load()["used"], "счёт старше суток стёрт"
            state.now = real[6]
            # Слишком большой файл: отказ, отметка остаётся — следующий файл снова сюда.
            take(file(7, 7, size=(config.SKLEYKA_MAX_MB + 1) * 1024 * 1024))
            assert sent[-1][1] == TOO_BIG and route(file(7, 8)) == "оценка" and not load()["jobs"]
            # Большой файл ждёт, пока служебный вход занят сведением, и держит его сам, пока идёт.
            data = skleyka.load()
            data["jobs"].append({"id": "j1", "track": "t1"})
            skleyka.save(data)
            take(file(7, 8, size=40_000_000, name="трек.wav"))
            take(file(9, 9))
            assert [s[1] for s in sent[-2:]] == [HELD, ACCEPTED]
            tick()
            assert json.loads(Path(spawned[-1][4]).read_text())["chat"] == "9" and not logged(), "малый файл большого не ждёт"
            _RUNNING[0].returncode = 0
            tick()
            assert not _RUNNING and [j["chat"] for j in load()["jobs"]] == ["7"], "сведение идёт — большой стоит"
            data = skleyka.load()
            data["jobs"].clear()
            skleyka.save(data)
            tick()
            assert logged() and json.loads(Path(spawned[-1][4]).read_text())["n"] == "x.wav"
            # Зависший процесс убивается, человеку — FAILED; конец смены дожидается идущей оценки.
            _RUNNING[1]["started"] = state.iso(real[6]() - timedelta(minutes=JOB_MINUTES + 1))
            killed = _RUNNING[0]
            tick()
            assert killed.returncode == -9 and sent[-1] == ("7", FAILED, None) and not busy()
            take(file(7, 10))
            tick()
            _RUNNING[0].wait = lambda seconds: setattr(_RUNNING[0], "returncode", 0)
            finish()
            assert not busy() and counted.count(DONE) == 3

            # Процесс оценки: файл скачан подменой, ответ с кнопкой СВЕДЕНИЯ, файла после нет.
            subprocess.Popen = real[4]  # дальше замер настоящий: ffmpeg зовётся через subprocess
            real_fetch, config.MIX_NORMS = skleyka._fetch, tmp / "norms.json"

            def fetch(spec: dict, folder: Path, service) -> list:
                folder.mkdir(parents=True)
                shutil.copy(tmp / spec["files"][0]["f"], folder / "0.wav")
                return [(spec["files"][0]["n"], folder / "0.wav")]

            skleyka._fetch = fetch
            try:
                for name, code, keys in (("quiet.wav", 0, KEYS), ("short.wav", REFUSED, None)):
                    (tmp / "job.json").write_text(json.dumps({"chat": "7", "m": 1, "f": name, "s": 1, "n": "x.wav"}))
                    assert run_job(tmp / "job.json") == code and sent[-1][2] == keys and not (tmp / "in").exists()
                assert sent[-2][1] == report(quiet, norms)
            finally:
                skleyka._fetch, config.MIX_NORMS = real_fetch, real_norms
            assert len(KEYS) == 1 and KEYS[0][0]["callback_data"] == "s:skleyka"  # счёт задатка отсюда не выставить
            assert all(len(text) < 4096 for _, text, _ in sent)
        finally:
            (telegram.send_message, config.OCENKA_FILE, config.SKLEYKA_FILE, config.OTBOR_FILE, subprocess.Popen,
             skleyka._count, state.now) = real
            _RUNNING = None
    print("ОК: нормальный трек без упрёков, тихий, срезанный, бас по бокам, моно и пустые края — каждый своей строкой, "
          "три полосы в одну сторону — одной строкой о середине; "
          "отказы по длине, тишине и битому файлу; MP3 упрёка не добавляет; нормы — только числа, релизов не меньше 40; "
          "файл с отметкой — в оценку, без неё и после срока — в отбор, при заявке сведения — в дорожки; лимит суток, "
          "очередь по одному, большой файл ждёт сведение; сбой и зависание — отказ без траты суток (Telegram подменён)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="ОЦЕНКА: готовый трек против выпущенных релизов")
    parser.add_argument("--check", metavar="ФАЙЛ", help="замер файла и текст ответа, без Telegram")
    parser.add_argument("--norms", nargs="*", metavar="ПУТЬ", help="пересчитать нормы: кэш прослушки и целые треки "
                                                                   "из названных папок и файлов (только Мак)")
    parser.add_argument("--job", metavar="ФАЙЛ", help="одна оценка из очереди — зовёт дежурство")
    parser.add_argument("--selftest", action="store_true", help="самопроверка без сети")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if args.selftest:
        return _selftest()
    if args.job:
        return run_job(Path(args.job))
    if args.norms is not None:
        state.write_json(config.MIX_NORMS, make_norms(args.norms))
        print(f"Нормы записаны: {config.MIX_NORMS}")
        return 0
    if args.check:
        text, measured = assess(Path(args.check))
        if measured:
            print("Замер:", json.dumps(gauge(Path(args.check)), ensure_ascii=False))
        print(text)
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
