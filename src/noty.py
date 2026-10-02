"""НОТЫ — заготовка бита для FL Studio: партии, где саунд-дизайн сделан расстановкой нот.

Владелец пишет type beat'ы для YouTube (src/bity.py) из нот, которые по утрам
приносит облачный Claude: тот пишет content/beats/<id>/make.py — паспорт бита INFO
и compose() с партиями, — пушит в ветку claude/beats-<id>, а beats.yml собирает
архив и шлёт владельцу в личку. Бриф автора — prompts/beats.md.

Главный формат — родная партитура FL (.fsc), а не MIDI. 01.10.2026 владелец собрал
первый бит из MIDI и руками дорисовал то, чего MIDI не несёт: раскидал хэты по
панораме и разбросал силу 808. У ноты в MIDI нет ни своей панорамы, ни своей
подстройки, слайда нет вовсе; в .fsc это поля ноты. Формат снят с партитур, лежащих
в самом FL Studio 20: заголовок, версия 11.5.0, запись ноты 24 байта. MIDI кладётся
рядом запасным путём — высота, длина и сила, остальное теряется.

Отвергнуто: панорама и пич контроллерами MIDI (CC10, pitch bend). Они на канал,
а не на ноту, и в канал-сэмплер FL при импорте не попадают.

Панорама, подстройка и слайд ноты работают только в родных каналах FL — сэмплере,
куда владелец кладёт барабаны и 808. Синтезатор-плагин (у владельца Serum: аккорды,
гитара, мелодия) их не слышит, а нота под слайдом звучала бы там фальшивой всю длину.
Поэтому в партиях синтезатора приёмы — только местом, длиной, высотой и силой нот,
и `problems` следит за этим.

make.py исполняется как код, а пишет его модель, читавшая сеть, — поэтому сборка
и отправка разведены: beats.yml собирает архив шагом без секретов, токен бота
видит только готовый архив.

Звуки и пресеты к нотам (владелец, 02.10.2026: «давать помимо миди сами пресеты и звуки
из моих библиотек»). Паспорт называет звук каждой партии полем sounds — путём внутри
библиотеки владельца. Сами файлы в репозиторий и в архив Telegram не идут: наборы чужие
и платные, а нужны только за Маком, где уже лежат. В репозитории — список имён
data/beat_sounds.json (сборка отказывает звуку, которого в нём нет), а помощник на Маке
(src/tracks.py, тот же круг раз в десять минут) копирует названное в папку «00 - Сегодня»
браузера FL и в такую же папку пресетов Serum. make.py на Маке исполняется только
в песочнице macOS — без сети, без записи мимо временной папки, без подпроцессов и без
чтения .env: рядом лежит ключ входа в Telegram владельца. Отвергнуто: исполнять как есть
(код пишет модель, читавшая сеть) и тянуть готовые партитуры из Actions (нужен второй вход).

Цвет (владелец, 02.10.2026: биты «слишком попсовые», один похож на музыку из Майнкрафта). Замер показал, что
сладкое сидело в нотах и именах звуков, а не в барабанах: круг из четырёх аккордов, мелодия колокольчиком
выше F6. Запрет словами в брифе автор не держит (так было с формой и мелодией), поэтому `sugar` бракует
числом то, что видно в нотах: регистр, число аккордов, размер мотива, терции второго голоса, долю тишины,
имена звуков на мелодии. Звука сборка не слышит: это отсев приторных нот, а не проверка, что бит хорош.
Отвергнуто: мерить «садится ли мелодия на звук аккорда» — при одном-двух аккордах и мотиве из трёх нот
доля высокая у любого бита, сладкое от сухого она не отличает.

Музыка петлёй (владелец, 02.10.2026: «да», через день). Разбор его проектов показал, что музыку он делает
гитарными петлями набора 01 через Gross Beat и Love Philter, а Serum почти не трогает. Обычный бит с 05.10.2026
называет петлю полем loop и партий музыки не несёт: ноты — барабаны, 808 и не больше одной партии сэмплером.
Злой и кино остаются партиями — характер и так чередуется через день, своего расписания у петли нет. Темп петли
берётся из имени файла: звук в KITS читать нельзя (заглушки iCloud), а петля без темпа в имени в список не идёт.
Отвергнуто: брать любые петли набора — Lex Luger и прочее с archive.org лежат в той же папке без лицензии.

    python -m src.noty --selftest          приёмы пианоролла, замер нот и запись партитуры FL и MIDI, без сети
    python -m src.noty --build ПАПКА       собрать и проверить бит из ПАПКА/make.py, без Telegram
    python -m src.noty --build ПАПКА --prev ФАЙЛ…   то же и сверка с make.py прошлых битов: та же форма, мелодия, цвет или смесь — отказ
    python -m src.noty --send АРХИВ        отправить собранный архив владельцу
    python -m src.noty --sounds            переписать data/beat_sounds.json: имена звуков и пресетов библиотеки (только Мак)
    python -m src.noty --gather            папка «00 - Сегодня»: ноты свежей ветки битов, её звуки и пресеты (только Мак)

Сетка — шестнадцатые: такт = 16, доля = 4.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import runpy
import shutil
import struct
import subprocess
import sys
import tempfile
import unicodedata
import zipfile
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

TICK = 24                 # тиков FL в шестнадцатой: PPQ 96, как в проектах владельца
PPQ, MIDI_TICK = 480, 120
# Черновик «всё вместе» играет любой плеер: тембр General MIDI — по слову в имени партии
# Мелодии в списке нет намеренно: до 02.10.2026 её играла музыкальная шкатулка (программа 10), и черновик
# звучал «Майнкрафтом» при любых нотах. Теперь она — рояль (0), как всякая неназванная партия
GM_TONAL = {"аккорд": 89, "гитар": 25, "808": 38, "бас": 38, "колокол": 14, "струн": 48, "флейт": 73, "медь": 61}
GM_DRUM = {"бочка": 36, "клэп": 39, "снейр": 38, "открыт": 46, "хэт": 42, "римшот": 37, "перк": 75, "крэш": 49}


SAMPLED = ("808", "бас")    # партии с высотой, которые владелец играет сэмплером, а не синтезатором
# Неожиданный ход (владелец, 02.10.2026: «удивлять слушателей»): один на бит, на стыке частей — prompts/beats.md
TWISTS = ("смена бита", "ложный вход", "половинный темп", "сдвиг вниз", "чужой тембр", "задом наперёд")
MOODS = ("обычный", "злой", "кино")
# Цвет музыки — гармония, мелодия, тембр — и референсы звука, с которых он снят (владелец, 02.10.2026;
# признаки каждого — prompts/beats.md, «Цвет»). Имена — про звук, а не про название бита: пара в названии — по спросу
COLORS = {"андер": ("андер",), "дым": ("A$AP Rocky",), "лёд": ("Yung Lean", "Black Kray"), "рифф": ("Lil Peep",),
          "пустота": ("Kanye West", "Lil Wayne", "50 Cent"), "ржавчина": ("Chief Keef", "Playboi Carti")}
SOUNDS = {name for names in COLORS.values() for name in names} | {"кино"}       # что можно смешивать
ALIEN = ("тембр", "приём мелодии", "рисунок перка", "оркестровый слой", "обработка")   # что берётся от чужого звука
FREE_DAY = 2                # среда: раз в неделю смесь свободная, день — по дате в id бита
# Сколько времени музыка молчит. У референсов она звучит 94% времени, у «Дифирамба» — 80%, у Lil Wayne
# и 50 Cent — 54 и 71%, у «Фосфора» — 100% (замер 02.10.2026)
QUIET = {"андер": .2, "пустота": .2}
HIGH = 77                   # F6: выше неё «Фосфор» держал мелодию 56% времени, «Фары» — 19%
# Колокольчик, шкатулка и плак на мелодии — по имени звука: «Bell - Crystal Eye» и «Pluck - Chosen» стояли в «Фосфоре»
SWEET = ("bell", "music box", "pluck", "glock", "chime", "celest", "kalimba", "toy", "колокол", "шкатул", "арф")
# Библиотека владельца на Маке. Путь звука в паспорте — «KITS/…» или «Serum/…»
LIBRARY = {"KITS": Path.home() / "Documents" / "Image-Line" / "FL Studio" / "KITS",
           "Serum": Path("/Library/Audio/Presets/Xfer Records/Serum Presets/Presets")}
# В список идёт то, что можно ставить в бит на раздачу. Оркестровых сэмплов Lex Luger (KITS/01) в нём нет:
# набор взят с archive.org без указанной лицензии — сборка откажет им, как любому неназванному звуку.
LISTED = (("KITS/09 - Scene 2026 Kit", "**/*.wav"), ("KITS/10 - Кино Kit", "**/*.wav"), ("Serum", "**/*.fxp"))
# Музыка петлёй. Папка Loops плоская: вид петли — приставка имени. Только MusicRadar — royalty-free по README набора
LOOPS = "KITS/01 - ASAP Rocky Kit/Loops"
LOOP_KINDS = ("Western Gtr", "Acoustic Gtr", "Country Crunk", "Ambient")
LOOP_TEMPO = .08            # отход темпа бита от темпа петли (или двойного): дальше растяжка слышна; мерка skleyka.SWAP_TEMPO
LOOP_FROM = "20261005"      # с этого дня обычный бит — петлёй: 03.10 и 04.10 — пробы злого и кино, они партиями
LISTED += ((LOOPS, "*.wav"),)
TODAY = "00 - Сегодня"      # папка копий на сегодня — в KITS и в User пресетов Serum; чистится только она


class N(NamedTuple):
    pos: float            # в шестнадцатых от начала бита
    ln: float             # длина в шестнадцатых
    key: int = 60         # C5 — родная высота сэмпла в FL
    vel: int = 100        # 1–127
    pan: int = 0          # −100 лево … 100 право
    fine: int = 0         # подстройка в центах, шаг FL — 10
    slide: bool = False   # слайд-нота FL: тянет звучащую под ней ноту к своей высоте


# --- приёмы пианоролла -------------------------------------------------------

def _at(x, i: int, n: int) -> float:
    """Значение или пара «от, до» — в точке i из n."""
    a, b = x if isinstance(x, tuple) else (x, x)
    return a + (b - a) * i / max(n - 1, 1)


def roll(pos: float, ln: float, n: int, key: int = 60, vel=(60, 110), pan=0, pitch: float = 0,
         curve: float = 1.0) -> list[N]:
    """Дробь: n ударов на отрезке. vel и pan — число или пара «от, до»; pitch — на сколько
    полутонов уедет высота к последнему удару; curve > 1 — удары сгущаются к концу (разгон),
    < 1 — редеют (пластинка встаёт)."""
    at = [ln * (i / n) ** (1 / curve) for i in range(n + 1)]
    out = []
    for i in range(n):
        p = _at((0, pitch), i, n)
        out.append(N(pos + at[i], at[i + 1] - at[i], key + round(p), round(_at(vel, i, n)),
                     round(_at(pan, i, n)), round((p - round(p)) * 10) * 10))
    return out


def spread(notes: list[N], width: int = 55, seed: int = 0) -> list[N]:
    """Панорама вразброс: так владелец 01.10.2026 сам раскидал хэты (до ±56)."""
    r = random.Random(seed)
    return [n._replace(pan=r.randint(-width, width)) for n in notes]


def ping(notes: list[N], width: int = 60) -> list[N]:
    """Лево-право через удар."""
    return [n._replace(pan=width if i % 2 else -width) for i, n in enumerate(notes)]


def human(notes: list[N], vel: int = 8, seed: int = 0) -> list[N]:
    """Сила вразброс: одинаковые удары подряд звучат машиной."""
    r = random.Random(seed)
    return [n._replace(vel=max(1, min(127, n.vel + r.randint(-vel, vel)))) for n in notes]


def flam(note: N, gap: float = .25, vel: float = .55) -> list[N]:
    """Форшлаг: тихий удар прямо перед основным."""
    return [note._replace(pos=note.pos - gap, ln=gap, vel=round(note.vel * vel)), note]


def echo(notes: list[N], step: float, times: int = 3, decay: float = .6, width: int = 0,
         pitch: int = 0) -> list[N]:
    """Эхо нотами: повторы через step, каждый тише, по панораме в стороны поочерёдно
    и на pitch полутонов дальше от исходной высоты."""
    out = list(notes)
    for k in range(1, times + 1):
        out += [n._replace(pos=n.pos + step * k, vel=max(1, round(n.vel * decay ** k)),
                           pan=width * (-1) ** k, key=n.key + pitch * k) for n in notes]
    return out


def strum(pos: float, ln: float, keys, gap: float = .25, vel=(70, 100)) -> list[N]:
    """Аккорд перебором: ноты входят по очереди снизу вверх и звучат до общего конца."""
    return [N(pos + i * gap, ln - i * gap, k, round(_at(vel, i, len(keys)))) for i, k in enumerate(keys)]


def chop(pos: float, keys, pattern: str, vel: int = 90) -> list[N]:
    """Аккорд, рубленный ритмом: pattern по шестнадцатым, «x» — удар, «-» — тянется, «.» — тишина."""
    out, i = [], 0
    while i < len(pattern):
        j = i + 1
        while pattern[i] == "x" and j < len(pattern) and pattern[j] == "-":
            j += 1
        if pattern[i] == "x":
            out += [N(pos + i, j - i, k, vel) for k in keys]
        i = j
    return out


def grace(note: N, step: int = -1, ln: float = .5, vel: float = .75) -> list[N]:
    """Подъезд к ноте для синтезатора: короткая нота рядом, основная — сразу за ней."""
    return [note._replace(ln=ln, key=note.key + step, vel=round(note.vel * vel)),
            note._replace(pos=note.pos + ln, ln=note.ln - ln)]


def glide(pos: float, ln: float, key: int, to: int, at: float = 0, over: float = 1, vel: int = 110) -> list[N]:
    """Нота с подъездом, только для сэмплера: с позиции at высота за over шестнадцатых уезжает
    к to и там остаётся. Конец ноты 808 вверх — at ближе к концу."""
    return [N(pos, ln, key, vel), N(pos + at, over, to, vel, slide=True)]


def hits(pos: float, pattern: str, key: int = 60, vel: int = 100, ln: float = 1, ghost: float = .45,
         accent: float = 1.15) -> list[N]:
    """Рисунок строкой, по знаку на шестнадцатую: «x» — удар, «X» — акцент, «o» — тихий призрак, прочее — тишина;
    «|» между тактами пропускается. Так рисунки записаны в замере (data/beats_zamer.json): переносятся как есть."""
    scale = {"x": 1, "X": accent, "o": ghost}
    return [N(pos + i, ln, key, max(1, min(127, round(vel * scale[c]))))
            for i, c in enumerate(pattern.replace("|", "")) if c in scale]


def mute(notes: list[N], start: float, end: float) -> list[N]:
    """Вдох: в отрезке не звучит ничего. Ноты, начатые в нём, убираются, а тянущиеся в него — обрываются:
    808, гудящий сквозь паузу, паузу съедает."""
    out = []
    for n in notes:
        if start <= n.pos < end:
            continue
        out.append(n._replace(ln=start - n.pos) if n.pos < start < n.pos + n.ln else n)
    return out


def reverse(notes: list[N], start: float, end: float) -> list[N]:
    """Фраза задом наперёд: ноты отрезка зеркалом по времени — последняя звучит первой, длины те же."""
    return sorted(n._replace(pos=start + end - n.pos - n.ln) for n in notes if start <= n.pos < end)


def flat(notes: list[N]) -> list[N]:
    """Ноты без слайдов, для MIDI: нота под слайдом обрывается, дальше до её конца звучит
    высота слайда — внахлёст, чтобы канал с Mono и Porta подъехал сам."""
    out = [n for n in notes if not n.slide]
    for s in sorted(n for n in notes if n.slide):
        base = max((n for n in out if n.pos <= s.pos < n.pos + n.ln), default=None)
        if base is None:
            continue
        out.remove(base)                     # ponytail: слайд тянет одну ноту; аккорд слайдом — когда понадобится
        if s.pos > base.pos:
            out.append(base._replace(ln=s.pos - base.pos + .25))
        out.append(base._replace(pos=s.pos, ln=base.pos + base.ln - s.pos, key=s.key))
    return out


# --- запись ------------------------------------------------------------------

def _var(n: int) -> bytes:
    """Длина MIDI: старшие семь бит первыми."""
    out = [n & 0x7F]
    while (n := n >> 7):
        out.append(n & 0x7F | 0x80)
    return bytes(reversed(out))


def fsc(path: Path, notes: list[N]) -> None:
    """Партитура FL: одна партия, ложится в открытый пианоролл."""
    body = b"".join(struct.pack("<IHHIHHBBBBBBBB", round(n.pos * TICK), 0x4008 if n.slide else 0x4000, 0,
                                max(1, round(n.ln * TICK)), n.key, 0, 120 + round(n.fine / 10), 0, 64, 0,
                                64 + round(n.pan * .64), n.vel, 128, 128) for n in sorted(notes))
    size, ln = len(body), b""
    while True:                              # длина события FL: младшие семь бит первыми
        ln, size = ln + bytes([size & 0x7F | (0x80 if size > 0x7F else 0)]), size >> 7
        if not size:
            break
    data = b"\xc7\x0711.5.0\0" + b"\x1c\x03" + b"\x41\x00\x00" + b"\xe0" + ln + body
    path.write_bytes(b"FLhd" + struct.pack("<IHHH", 6, 0x10, 1, 96) + b"FLdt" + struct.pack("<I", len(data)) + data)


def read_fsc(path: Path) -> list[N]:
    """Партитура обратно в ноты: проверка, что записалось то, что сочинено."""
    data = path.read_bytes()
    assert data[:4] == b"FLhd" and data[14:18] == b"FLdt", path.name
    i = data.index(b"\x41\x00\x00\xe0") + 4
    size = shift = 0
    while True:
        size, shift, i = size | (data[i] & 0x7F) << shift, shift + 7, i + 1
        if data[i - 1] < 0x80:
            break
    assert i + size == len(data) and size % 24 == 0, path.name
    out = []
    for k in range(i, len(data), 24):
        pos, flags, _, ln, key, _, fine, _, _, _, pan, vel, _, _ = struct.unpack("<IHHIHHBBBBBBBB", data[k:k + 24])
        out.append(N(pos / TICK, ln / TICK, key, vel, round((pan - 64) / .64), (fine - 120) * 10, bool(flags & 8)))
    return out


def _track(name: str, notes: list[N], ch: int = 0, prog: int | None = None, drum: int | None = None) -> bytes:
    ev = [(0, 0, bytes([0xC0 | ch, prog]))] if prog is not None else []
    for n in flat(notes):                    # снятие раньше взятия: повтор одной ноты встык не глохнет
        key, a = drum or n.key, round(n.pos * MIDI_TICK)
        ev += [(a, 2, bytes([0x90 | ch, key, n.vel])),
               (max(a + 1, round((n.pos + n.ln) * MIDI_TICK)), 1, bytes([0x80 | ch, key, 0]))]
    body, now = b"", 0
    for tick, _, data in sorted(ev, key=lambda e: e[:2]):
        body, now = body + _var(tick - now) + data, tick
    body += b"\x00\xff\x2f\x00"
    return b"MTrk" + struct.pack(">I", len(body)) + body


def mid(path: Path, bpm: int, *tracks: bytes) -> None:
    tempo = (b"\x00\xff\x51\x03" + struct.pack(">I", 60_000_000 // bpm)[1:]
             + b"\x00\xff\x58\x04\x04\x02\x18\x08" + b"\x00\xff\x2f\x00")
    path.write_bytes(b"MThd" + struct.pack(">IHHH", 6, 1, 1 + len(tracks), PPQ)
                     + b"MTrk" + struct.pack(">I", len(tempo)) + tempo + b"".join(tracks))


def read_mid(path: Path) -> tuple[int, int]:
    """Сколько нот взято и сколько снято."""
    data, i, on, off = path.read_bytes(), 14, 0, 0
    assert data[:4] == b"MThd", path.name
    while i < len(data):
        assert data[i:i + 4] == b"MTrk", path.name
        end, i = i + 8 + struct.unpack(">I", data[i + 4:i + 8])[0], i + 8
        while i < end:
            while data[i] >= 0x80:
                i += 1
            st, i = data[i + 1], i + 1
            if st == 0xFF:
                i += 3 + data[i + 2]
            elif st & 0xF0 == 0xC0:
                i += 2
            else:
                on, off, i = on + (st & 0xF0 == 0x90), off + (st & 0xF0 == 0x80), i + 3
    return on, off


# --- бит целиком -------------------------------------------------------------

def problems(info: dict, tracks: dict[str, list[N]], free: bool = False) -> list[str]:
    """Что не так с битом. Пусто — годен. free — день свободной смеси (`_free`)."""
    out, end = [], info["bars"] * 16
    # form … fx обязательны здесь, а не в сверке с прошлым битом: beats.yml собирает без --prev,
    # и «Фосфор» 02.10.2026 ушёл владельцу без единого из этих полей
    out += [f"в паспорте нет поля {k}" for k in ("title", "bpm", "key", "scale", "bars", "skeleton", "like", "parts", "tricks",
                                                 "form", "melody", "mood", "twist", "color", "mix", "sounds", "fx")
            if not info.get(k) and not (k == "melody" and info.get("loop"))]      # у бита петлёй мелодии нет
    out += [f"{word} «{info[k]}» — не из списка: {', '.join(names)}"
            for k, word, names in (("twist", "неожиданный ход", TWISTS), ("mood", "характер", MOODS), ("color", "цвет", COLORS))
            if info.get(k) and info[k] not in names]
    # Малая секунда и тритон к тонике — острые ноты, которых бит без сахара и ждёт: им длина разрешена
    scale = set(info["scale"]) | {(info["scale"][0] + 1) % 12, (info["scale"][0] + 6) % 12}
    for name, notes in tracks.items():
        if not notes:
            out.append(f"{name}: партия пустая")
        for n in notes + flat(notes):
            where = f"{name}, такт {int(n.pos // 16) + 1}"
            if n.pos < 0 or n.pos + n.ln > end + 1e-6 or n.ln <= 0:
                out.append(f"{where}: нота вне бита")
            if not (1 <= n.vel <= 127 and -100 <= n.pan <= 100 and -1200 <= n.fine <= 1200 and 0 <= n.key <= 127):
                out.append(f"{where}: сила, панорама, подстройка или высота вне пределов")
        # Короткая нота мимо тональности — проходящая или подъезд; длинная — ошибка
        out += [f"{name}, такт {int(n.pos // 16) + 1}: длинная нота мимо тональности ({n.key})"
                for n in flat(notes) if name in info.get("tonal", ()) and n.key % 12 not in scale and n.ln > 1]
        if name in info.get("tonal", ()) and not any(w in name for w in SAMPLED) \
                and any(n.pan or n.fine or n.slide for n in notes):
            out.append(f"{name}: панорама, подстройка и слайд ноты в синтезаторе не работают — только в сэмплере")
    # Замер 01.10.2026: у лидеров бочка стоит под 808 в каждой пятой ноте, в первом бите владельца — под каждой
    if info.get("bpm") and shape(info, tracks).get("бочка под 808", 0) > .7:
        out.append("бочка стоит почти под каждой нотой 808: у лидеров замера — под 10–30%, низ ведёт сам 808")
    tricky = sum(1 for notes in tracks.values()
                 if any(n.pan or n.fine or n.slide or n.ln < .5 for n in notes) or len({n.vel for n in notes}) > 3)
    if tricky < 3:
        out.append(f"саунд-дизайн нотами только в {tricky} партиях: нужен хотя бы в трёх")
    if info.get("sounds"):              # звук назван — он должен быть в списке библиотеки: иначе Маку нечего копировать
        listed = known()
        out += [f"{part}: звука «{n}» нет в списке data/beat_sounds.json"
                for part, names in info["sounds"].items() for n in _names(names) if _nfc(n) not in listed]
        out += [f"{name}: партии не назван звук в sounds" for name in tracks if name not in info["sounds"]]
    if info.get("fx"):
        out += [f"{name}: партии не названа обработка в fx" for name in tracks
                if name in info.get("tonal", ()) and name not in info["fx"]]
    if info.get("mix"):
        out += _mix(info, free)
    if info.get("loop"):
        out += _loop(info, tracks)
    return (out + sugar(info, tracks))[:20]


def loop_bpm(name: str) -> int | None:
    """Темп петли из имени файла: «AC_NylStr85A-01» — 85, «K02Organ110E-03» — 110. None — петля не из разрешённых
    видов, без темпа в имени (аккорды Western Gtr) или это барабаны и бас: у бита они свои."""
    stem = name.rsplit("/", 1)[-1]
    if not stem.startswith(tuple(f"{k} - " for k in LOOP_KINDS)) or re.search("Beat|Bass|Drum", stem):
        return None
    return next((int(d) for d in re.findall(r"(?<!\d)\d{2,3}(?!\d)", stem) if 60 <= int(d) <= 200), None)


def _loop(info: dict, tracks: dict[str, list[N]]) -> list[str]:
    """Музыка петлёй: петля — из разрешённых, темп бита — её темп или вдвое быстрее, партий музыки рядом
    не больше одной, и та сэмплером. Нот у петли нет: где она играет и чем обработана — словами в parts и fx."""
    loop, tempo = _nfc(str(info["loop"])), loop_bpm(str(info["loop"]))
    if not (loop.startswith(LOOPS + "/") and tempo and loop in known()):
        return [f"loop: «{loop}» — не из разрешённых петель: {LOOPS}, виды {', '.join(LOOP_KINDS)}, "
                "с темпом в имени — точное имя бери из data/beat_sounds.json"]
    out = []
    if info.get("bpm") and min(abs(info["bpm"] / (tempo * k) - 1) for k in (1, 2)) > LOOP_TEMPO:
        out.append(f"loop: темп бита {info['bpm']} не сходится с темпом петли {tempo} — бит в её темпе "
                   f"или вдвое быстрее, отход не больше {LOOP_TEMPO:.0%}")
    if info.get("mood") != "обычный":
        out.append("loop: петлёй — только обычный бит; злой и кино — партиями")
    music = [name for name in tracks if name in info.get("tonal", ()) and not any(w in name for w in SAMPLED)]
    if len(music) > 1 or any(s.startswith("Serum/") for name in music for s in _names((info.get("sounds") or {}).get(name, ()))):
        out.append(f"loop: рядом с петлёй партии музыки ({', '.join(music)}) — не больше одной, и та сэмплером, а не Serum")
    if "петля" not in (info.get("fx") or {}):
        out.append("loop: в fx нет строки «петля» — цепочки обработки петли")
    return out


def _free(name: str) -> bool:
    """День свободной смеси — по дате, с которой начинается id бита: календарь автора и сборки один."""
    try:
        return datetime.strptime(name[:8], "%Y%m%d").weekday() == FREE_DAY
    except ValueError:
        return False


def _mix(info: dict, free: bool) -> list[str]:
    """Смешение «основа + одно чужое» (владелец, 02.10.2026: «мешать лучшие жанры друг с другом и немного
    экспериментировать»). Основа — референс своего цвета, от другого звука — ровно один элемент: два чужих
    разом — уже не type beat пары, а третий жанр. Раз в неделю, в свободный день, счёт не ведётся."""
    mix = info["mix"] if isinstance(info["mix"], dict) else {}
    base, alien, what = (_names(mix.get(k) or ()) for k in ("основа", "чужое", "элемент"))
    if not (base and alien and what):
        return ["mix: нужны «основа», «чужое» и «элемент»"]
    out = [f"mix: «{n}» — не из списка звуков: {', '.join(sorted(SOUNDS))}" for n in base + alien if n not in SOUNDS]
    out += [f"mix: элемент «{w}» — не из списка: {', '.join(ALIEN)}" for w in what if w not in ALIEN]
    if free or out:
        return out
    mine = COLORS.get(info.get("color"), ())
    if len(alien) > 1 or len(what) > 1:
        out.append("mix: два чужих элемента разом — брак; свободная смесь — только в бите среды")
    if len(base) > 1 or base[0] not in mine:
        out.append(f"mix: основа — один референс своего цвета ({', '.join(mine)})")
    if set(alien) & set(mine):
        out.append("mix: чужое — звук другого цвета, а не своего")
    return out


def sugar(info: dict, tracks: dict[str, list[N]]) -> list[str]:
    """Приторное в нотах и именах звуков. Пусто — сухо. Пороги сняты с двух битов, которые владелец 02.10.2026
    назвал попсовыми: «Фосфор» ими бракуется. Последние 16 тактов «смены бита» не в счёт: там другой бит."""
    from statistics import median

    out, kino = [], info.get("mood") == "кино"
    end = (info["bars"] - (16 if info.get("twist") == "смена бита" else 0)) * 16
    music = {name: [n for n in flat(notes) if n.pos < end] for name, notes in tracks.items()
             if name in info.get("tonal", ()) and not any(w in name for w in SAMPLED)}
    music = {name: notes for name, notes in music.items() if notes}
    for name, notes in music.items():
        high = sum(n.ln for n in notes if n.key >= HIGH) / sum(n.ln for n in notes)
        if high > .25:
            out.append(f"{name}: {high:.0%} времени на F6 и выше — наверху не дольше четверти, главный регистр ниже C6")
        sweet = [s for s in _names((info.get("sounds") or {}).get(name, ())) if any(w in _nfc(s).lower().replace("cowbell", "") for w in SWEET)]      # ковбелл — не колокольчик
        if sweet and ("мелод" in name or median(n.key for n in notes) >= 72):
            out.append(f"{name}: звук «{sweet[0]}» — колокольчик, шкатулка или плак наверху; бери тёмное семейство")
    # Аккорд такта — классы высот партий гармонии. Один-два аккорда или петля в 1–2 такта дают не больше двух
    # разных по составу тактов; круг из четырёх со сменой каждый такт — четыре
    harmony = [n for name, notes in music.items() if "аккорд" in name or "пэд" in name for n in notes] \
        or [n for name, notes in music.items() if "гитар" in name for n in notes]
    kinds = {frozenset(n.key % 12 for n in harmony if min(n.pos + n.ln, b + 16) - max(n.pos, b) >= .5)
             for b in range(0, end, 16)} - {frozenset()}
    if len(kinds) > 2:
        out.append(f"гармония: {len(kinds)} разных по составу тактов — один-два аккорда на бит или петля в 1–2 такта")
    # Мотив — классы высот, а не высоты: тот же мотив октавой ниже остаётся тем же мотивом, а подъезды
    # короче шестнадцатой — украшение. У темы «кино» нот на одну больше
    tones = {n.key % 12 for n in _lead(tracks) if n.pos < end and n.ln >= 1}
    if len(tones) > 4 + kino:
        out.append(f"мелодия: в мотиве {len(tones)} разных нот — нужно 2–{4 + kino}")
    # Второй голос параллельно в терцию или сексту — удвоение, от которого мелодия слащавая
    voices = sorted(n for name, notes in music.items() if "мелод" in name for n in notes)
    both = close = 0
    for i, a in enumerate(voices):
        for b in voices[i + 1:]:
            if b.pos >= a.pos + a.ln:
                break
            t = min(a.pos + a.ln, b.pos + b.ln) - b.pos
            both, close = both + t, close + t * (abs(a.key - b.key) % 12 in (3, 4, 8, 9))
    if both >= 16 and close > .5 * both:
        out.append(f"мелодия: голоса идут в терцию или сексту {close / both:.0%} общего времени — "
                   "второй голос в октаву, квинту или не разом с первым")
    # Тишина — паузы от доли и длиннее, где молчит вся музыка (808 не в счёт): щель между короткими нотами
    # закроет хвост пресета. У «кино» остинато не молчит — там порога нет
    quiet = till = 0
    for a, b in sorted((n.pos, n.pos + n.ln) for notes in music.values() for n in notes) + [(end, end)]:
        quiet, till = quiet + (a - till if a - till >= 4 else 0), max(till, b)
    need = QUIET.get(info.get("color"), .1)
    if music and not kino and quiet / end < need:
        out.append(f"музыка молчит {quiet / end:.0%} времени — нужно не меньше {need:.0%}: такты и полтакта, где её нет вовсе")
    return out


def shape(info: dict, tracks: dict[str, list[N]]) -> dict:
    """Рисунок бита числами — теми же, какими src/zamer.py меряет чужие биты: автор сверяет свои ноты
    со скелетом из prompts/beats.md, не слыша звука. Такты считаются только те, где играют барабаны."""
    from statistics import median, pstdev

    def part(*words, skip=()):
        return [n for name, notes in tracks.items() if any(w in name for w in words)
                and not any(w in name for w in skip) for n in notes if not n.slide]

    hat, kick, clap = part("хэт", skip=("открыт",)), part("бочка"), part("клэп", "снейр")
    bass = [n for name, notes in tracks.items() if any(w in name for w in SAMPLED) for n in flat(notes)]
    slides = sum(n.slide for name, notes in tracks.items() if any(w in name for w in SAMPLED) for n in notes)
    live = sorted({int(n.pos // 16) for n in hat + kick + clap})
    if not live:
        return {}

    def per_bar(notes):
        return median(sum(int(n.pos // 16) == b for n in notes) for b in live)

    def gaps(b):
        at = sorted(n.pos for n in hat if int(n.pos // 16) == b)
        return [y - x for x, y in zip(at, at[1:])]

    rolls = sum(sum(g <= .55 for g in gaps(b)) >= 2 for b in live)
    trips = sum(sum(abs(g - t) < .05 for g in gaps(b) for t in (1 / 3, 2 / 3, 4 / 3)) >= 2 for b in live)
    sounding = sum(min(n.ln, 16 - n.pos % 16) for n in bass if int(n.pos // 16) in live)
    return {
        "тактов": info["bars"], "секунд": round(info["bars"] * 240 / info["bpm"]),
        "хэт/такт": per_bar(hat), "такты с дробью": round(rolls / len(live), 2),
        "с триолями": round(trips / len(live), 2), "хэт: разброс панорамы": round(pstdev([n.pan for n in hat]), 1) if hat else 0,
        "бочка/такт": per_bar(kick), "808/такт": per_bar(bass),
        "нота 808, 1/16": round(median(n.ln for n in bass), 1) if bass else 0,
        "808 звучит": round(sounding / (16 * len(live)), 2), "разных нот 808": len({n.key for n in bass}),
        "слайдов на 8 т.": round(slides / len(live) * 8, 1),
        "бочка под 808": round(sum(any(abs(k.pos - n.pos) < .01 for k in kick) for n in bass) / len(bass), 2) if bass else 0,
        "такты без барабанов": info["bars"] - len(live),
    }


def _lead(tracks: dict[str, list[N]]) -> list[N]:
    return sorted(n for name, notes in tracks.items() if "мелод" in name and "контр" not in name for n in flat(notes))


def echoes(info: dict, tracks: dict[str, list[N]], old: dict, old_tracks: dict[str, list[N]]) -> list[str]:
    """Чем бит повторяет прошлый. Пусто — не повторяет. 02.10.2026 второй бит подряд вышел с тем же порядком
    частей и той же мелодией в другой тональности: запрет словами в брифе автор не удержал, поэтому сверяет код."""
    was = f"«{old.get('title', 'прошлый бит')}»"
    out = [f"{word} «{info[k]}» — как в {was}: возьми другое"
           for k, word in (("form", "форма"), ("melody", "приём мелодии"), ("twist", "неожиданный ход"), ("color", "цвет"),
                           ("loop", "петля"))
           if info.get(k) and info[k] == old.get(k)]
    pair = [[_names(m.get(k) or ()) for k in ("основа", "чужое")] for m in (info.get("mix"), old.get("mix")) if isinstance(m, dict)]
    if len(pair) == 2 and pair[0] == pair[1]:
        out.append(f"смесь «{' + '.join(n for names in pair[0] for n in names)}» — как в {was}: возьми другую")

    def order(i):                       # «вступление 1–4, припев 5–12» → вступление, припев
        return re.findall(r"[а-яё]+(?=\s*\d)", str(i.get("parts", "")).lower())

    if order(info) and order(info) == order(old):
        out.append(f"части идут в том же порядке, что в {was}: {', '.join(order(info))}")
    a, b = _lead(tracks), _lead(old_tracks)
    if len(a) > 3 and len(b) > 3:
        def bars(notes):                # рисунок такта: места нот в нём
            return [tuple(round(n.pos % 16, 2) for n in notes if int(n.pos // 16) == x) for x in sorted({int(n.pos // 16) for n in notes})]

        def moves(notes):               # пары соседних ходов в полутонах — тональность не важна
            step = [y.key - x.key for x, y in zip(notes, notes[1:])]
            return set(zip(step, step[1:]))

        rhythm = sum(x in set(bars(b)) for x in bars(a)) / len(bars(a))
        same = len(moves(a) & moves(b)) / len(moves(a))
        # ponytail: пороги сняты с одной пары («Фары» и «134»: 62% и 31–38%, у несхожих партий — до 12% и 15%);
        # начнут браковать несхожее на слух — мерить по фразам, а не по тактам
        if rhythm >= .5 and same >= .25:
            out.append(f"мелодия повторяет {was}: ритм тот же в {rhythm:.0%} тактов, ходы те же на {same:.0%} — "
                       "другой приём, другая длина фразы, другое начало")
    return out


def _sounds(info: dict) -> dict:
    """Звуки паспорта вместе с петлёй: Мак кладёт её в папку «Сегодня» наравне с остальными."""
    return (info.get("sounds") or {}) | ({"петля": info["loop"]} if info.get("loop") else {})


def about(info: dict) -> str:
    """Записка владельцу: она же подпись к архиву."""
    return "\n".join([
        f"🎹 {info['title']}", f"{info['bpm']} BPM, {info['key']}, {info['bars']} тактов", "",
        f"Скелет: {info['skeleton']}",
        *([f"Форма: {info.get('form', '—')}; мелодия: {info.get('melody') or ('петля' if info.get('loop') else '—')}; характер: {info.get('mood', '—')}"
           + (f"; неожиданный ход: {info['twist']}" if info.get("twist") else "")]
          if info.get("form") or info.get("melody") or info.get("mood") else []),
        *([f"Цвет: {info['color']}"] if info.get("color") else []),
        *([f"Смесь: основа — {', '.join(_names(m.get('основа') or ()))}; от чужого звука "
           f"({', '.join(_names(m.get('чужое') or ()))}) — {', '.join(_names(m.get('элемент') or ()))}"]
          if isinstance(m := info.get("mix"), dict) else []),
        f"С чего снято: {info['like']}", f"Части: {info['parts']}", "",
        "Что сделано нотами:", *(f"• {t}" for t in info["tricks"]), "",
        *(["Звуки и пресеты — в папке «00 - Сегодня» в браузере FL и в меню Serum → User (нужно Rescan); "
           "их кладёт Мак, когда не спит:",
           *(f"• {part} — {n}" for part, names in _sounds(info).items() for n in _names(names)), ""] if _sounds(info) else []),
        *([f"Музыка — петлёй: темп в её имени — {loop_bpm(info['loop'])}, растяни её к темпу бита без смены высоты. "
           "Тональность снята с имени петли, на слух не сверена: не строит — сдвинь партитуру 808 целиком.", ""]
          if info.get("loop") else []),
        *(["Обработка — цепочки из интервью продюсеров и замера. Ни пресетов, ни эффектов автор нот не слышал: "
           "это с чего начать, а не как должно звучать:",
           *(f"• {part} — {chain}" for part, chain in info["fx"].items()), ""] if info.get("fx") else []),
        "Папка fl — партитуры FL Studio: перетащи файл в пианоролл своего канала "
        "(или меню пианоролла → File → Open score). В них панорама, подстройка и слайды каждой ноты — "
        "они работают в сэмплере (барабаны, 808), синтезатору идут только ноты и сила.",
        "Папка midi — запасной путь: только высота, длина и сила; 808 со слайдами там — ноты внахлёст, "
        "включи на канале Mono и Porta.",
        f"Готовый бит — боту с подписью: бит {info['title']}, {info['bpm']} {info['key']}",
    ])


def build(folder: Path, out: Path, prev: tuple[Path, ...] = ()) -> Path:
    """Архив бита из ПАПКА/make.py; рядом — записка .txt, она же подпись при отправке.
    prev — make.py прошлых битов: повтор их формы или мелодии — тоже брак."""
    made = runpy.run_path(str(folder / "make.py"))
    info, tracks = made["INFO"], made["compose"]()
    bad = problems(info, tracks, _free(folder.name))
    if folder.name[:8].isdigit() and folder.name[:8] >= LOOP_FROM and info.get("mood") == "обычный" and not info.get("loop"):
        bad.append("обычный бит — петлёй (поле loop): музыка через день петлёй, через день партиями")
    for path in prev:
        try:
            old = runpy.run_path(str(path))
            bad += echoes(info, tracks, old["INFO"], old["compose"]())
        except Exception as e:          # прошлый бит писан под старый noty — не повод остаться без сегодняшнего
            print(f"{path}: не прочитан ({e}) — сверка без него")
    if bad:
        raise SystemExit("Бит не годен:\n" + "\n".join(bad))
    root = out / folder.name
    (root / "fl").mkdir(parents=True, exist_ok=True)
    (root / "midi").mkdir(exist_ok=True)
    draft = []
    for i, (name, notes) in enumerate(tracks.items(), 1):
        fsc(root / "fl" / f"{i:02} {name}.fsc", notes)
        mid(root / "midi" / f"{i:02} {name}.mid", info["bpm"], _track(name, notes))
        assert sorted(read_fsc(root / "fl" / f"{i:02} {name}.fsc")) == sorted(
            n._replace(pos=round(n.pos * TICK) / TICK, ln=max(1, round(n.ln * TICK)) / TICK,
                       pan=round(round(n.pan * .64) / .64), fine=round(n.fine / 10) * 10)
            for n in notes), f"{name}: партитура записалась не так"
        on, off = read_mid(root / "midi" / f"{i:02} {name}.mid")
        assert on == off == len(flat(notes)), f"{name}: MIDI записался не так"
        if name in info.get("tonal", ()):
            draft.append(_track(name, notes, len(draft) % 9, next((p for k, p in GM_TONAL.items() if k in name), 0)))
        else:
            draft.append(_track(name, notes, 9, drum=next((p for k, p in GM_DRUM.items() if k in name), 42)))
        tricks = [w for w, yes in (("панорама", any(n.pan for n in notes)), ("подстройка", any(n.fine for n in notes)),
                                   ("слайды", any(n.slide for n in notes)),
                                   ("дроби", any(n.ln < .5 for n in notes))) if yes]
        print(f"{i:02} {name:16} нот {len(notes):4}, сил {len({n.vel for n in notes}):2}  {', '.join(tricks)}")
    print("замер нот: " + ", ".join(f"{k} {v:g}" for k, v in shape(info, tracks).items()))
    mid(root / "00 всё вместе (черновик).mid", info["bpm"], *draft)
    (root / "о бите.txt").write_text(about(info), encoding="utf-8")
    archive = out / f"{folder.name}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(root.rglob("*")):
            z.write(f, f.relative_to(out))
    archive.with_suffix(".txt").write_text(about(info), encoding="utf-8")
    archive.with_suffix(".sounds.json").write_text(json.dumps(_sounds(info), ensure_ascii=False), encoding="utf-8")
    print(f"{info['bpm']} BPM, {info['bars']} тактов, {info['bars'] * 240 / info['bpm']:.0f} с → {archive}")
    return archive


def _nfc(name: str) -> str:
    """Имена с диска Мака бывают разложенными («й» двумя знаками), автор пишет слитно — сравниваем слитно."""
    return unicodedata.normalize("NFC", name)


def _names(names) -> list[str]:
    return [names] if isinstance(names, str) else [str(n) for n in names]


def known() -> set[str]:
    """Звуки и пресеты, которые можно назвать в паспорте: список имён из репозитория."""
    from . import config
    return set(json.loads(config.BEAT_SOUNDS.read_text("utf-8"))["sounds"]) if config.BEAT_SOUNDS.exists() else set()


def library() -> list[str]:
    """Имена звуков и пресетов библиотеки владельца. Только обход имён: чтение файла в KITS скачало бы
    его из iCloud — две трети библиотеки там заглушки."""
    out = set()
    for base, pattern in LISTED:
        key, _, sub = base.partition("/")
        root = LIBRARY[key] / sub
        out |= {_nfc(f"{base}/{f.relative_to(root).as_posix()}") for f in root.glob(pattern)
                if TODAY not in f.parts and (base != LOOPS or loop_bpm(f.name))}
    return sorted(out)


def lay(built: Path | None, sounds: dict, kits: Path, serum: Path,
        roots: dict[str, Path] | None = None, listed: set[str] | None = None) -> list[str]:
    """Папки «Сегодня»: партитуры и записка собранного бита и копии названных звуков — сэмплы в kits,
    пресеты в serum, имя партии впереди. Прошлые файлы обеих папок убираются: там только копии.
    Оригиналы открываются лишь на чтение. sounds пришёл из make.py — это данные, а не доверенный путь:
    копируется только то, что есть в списке. Возвращает, что не легло, — оно же дописано в записку."""
    roots, listed, missed = roots or LIBRARY, known() if listed is None else listed, []
    for folder in (kits, serum):
        assert folder.name == TODAY, f"{folder}: чистится только папка «{TODAY}»"
        folder.mkdir(parents=True, exist_ok=True)
        for old in folder.iterdir():
            if old.is_file() or old.is_symlink():
                old.unlink()
    for f in sorted((built / "fl").glob("*.fsc")) if built else []:
        shutil.copyfile(f, kits / f.name)
    for part, names in (sounds.items() if isinstance(sounds, dict) else []):
        label = re.sub(r"[/\\:\0]", " ", str(part))[:40]
        for name in map(_nfc, _names(names)):
            key, _, rel = name.partition("/")
            if name not in listed or key not in roots:
                missed.append(f"{label}: «{name}» — нет в списке библиотеки")
                continue
            src = roots[key] / rel
            dst = (serum if key == "Serum" else kits) / f"{label[:1].upper()}{label[1:]} — {src.name}"
            try:
                shutil.copyfile(src, dst)           # заглушку iCloud чтение скачает — так и надо
            except OSError as e:
                dst.unlink(missing_ok=True)
                missed.append(f"{label}: «{name}» — " + ("нет на диске" if isinstance(e, FileNotFoundError)
                                                        else "не прочитался: выгружен в iCloud и не скачался"))
    note = (built / "о бите.txt").read_text("utf-8") if built and (built / "о бите.txt").exists() else ""
    (kits / "о бите.txt").write_text(note + ("\n\nНе легло в папку:\n" + "\n".join(f"• {m}" for m in missed) if missed else ""),
                                     encoding="utf-8")
    return missed


def _sandboxed(folder: Path, tmp: Path) -> None:
    """Сборка бита в песочнице macOS: make.py писала модель, читавшая сеть, а на Маке рядом ключ входа
    в Telegram владельца. Сети нет, подпроцессов нет, запись — только в tmp, .env и приватное состояние
    не читаются, окружение пустое. В Actions ту же роль играет шаг без секретов (beats.yml)."""
    from . import config
    profile = ("(version 1)(allow default)(deny network*)(deny process-fork)(deny file-write*)"
               f'(allow file-write* (subpath "{tmp}"))(allow file-write* (literal "/dev/null"))'
               f'(deny file-read* (literal "{config.ROOT / ".env"}"))(deny file-read* (subpath "{config.PRIVATE}"))')
    subprocess.run(["/usr/bin/sandbox-exec", "-p", profile, sys.executable, "-B", "-m", "src.noty",
                    "--build", str(folder), "--out", str(tmp / "out")], cwd=config.ROOT, check=True, timeout=300,
                   env={"PATH": "/usr/bin:/bin", "HOME": str(tmp), "TMPDIR": str(tmp)}, capture_output=True, text=True)


def gather(kits: Path | None = None, serum: Path | None = None) -> str:
    """Свежая ветка claude/beats-* → папки «Сегодня» в браузере FL и в пресетах Serum. Собранное второй
    раз не трогается: помощник на Маке заходит сюда раз в десять минут. Спал Мак — соберёт, проснувшись."""
    from . import config

    def git(*args: str) -> str:
        return subprocess.run(["git", "-C", str(config.ROOT), *args], capture_output=True, text=True,
                              check=True, timeout=120).stdout

    kits, serum = kits or LIBRARY["KITS"] / TODAY, serum or LIBRARY["Serum"] / "User" / TODAY
    if not kits.parent.is_dir() or not serum.parent.is_dir():
        return "библиотеки FL или пресетов Serum на этой машине нет"
    git("fetch", "-q", "origin", "+refs/heads/claude/beats-*:refs/remotes/origin/claude/beats-*")
    heads = dict(line.split() for line in git("for-each-ref", "--format=%(refname:short) %(objectname)",
                                              "refs/remotes/origin/claude/beats-*").splitlines())
    ids = {ref.removeprefix("origin/claude/beats-"): sha for ref, sha in heads.items()
           if re.fullmatch(r"origin/claude/beats-[0-9a-z-]+", ref)}
    if not ids:
        return "веток с битами нет"
    beat = max(ids)                                 # id начинается с даты
    mark = f"{beat} {ids[beat]}"
    if (kits / ".бит").exists() and (kits / ".бит").read_text("utf-8") == mark:
        return f"{beat}: уже собрано"
    with tempfile.TemporaryDirectory(prefix="noty-") as tmp:
        tmp = Path(tmp).resolve()
        (tmp / beat).mkdir()
        (tmp / beat / "make.py").write_text(git("show", f"origin/claude/beats-{beat}:content/beats/{beat}/make.py"), "utf-8")
        try:
            _sandboxed(tmp / beat, tmp)
            missed = lay(tmp / "out" / beat, json.loads((tmp / "out" / f"{beat}.sounds.json").read_text("utf-8")), kits, serum)
            done = "ноты на месте" + (f", не легло звуков: {len(missed)}" if missed else "")
        except (subprocess.SubprocessError, OSError, ValueError) as e:      # не собрался — записка, а не падение
            lay(None, {}, kits, serum)
            why = (getattr(e, "stderr", "") or getattr(e, "stdout", "") or str(e)).strip()[-1500:]
            (kits / "о бите.txt").write_text(f"{beat}: ноты на Маке не собрались — возьми архив из Telegram.\n\n{why}", "utf-8")
            done = "ноты не собрались, в папке записка"
    (kits / ".бит").write_text(mark, "utf-8")
    return f"{beat}: {done}"


def _pages(text: str, limit: int = 4000) -> list[str]:
    """Записка по сообщениям Telegram (4096 знаков), по строкам: со звуками и обработкой она в одно не влезает."""
    out = [""]
    for line in text.splitlines(keepends=True):
        if len(out[-1]) + len(line) > limit:
            out.append("")
        out[-1] += line
    return [page for page in out if page.strip()]


def send(archive: Path) -> None:
    """Архив и следом записка: в подпись к файлу (1024 знака) она не влезает."""
    from . import config, telegram
    text = archive.with_suffix(".txt").read_text("utf-8")
    telegram.send_document(config.secret("TELEGRAM_ADMIN_ID"), archive, "\n".join(text.splitlines()[:2]))
    for page in _pages(text):
        telegram.send_message(config.secret("TELEGRAM_ADMIN_ID"), page)


def selftest() -> None:
    r = roll(0, 4, 16, vel=(40, 120), pan=(-80, 80), pitch=-12, curve=2)
    assert len(r) == 16 and r[0].vel == 40 and r[-1].vel == 120 and r[0].pan == -80 and r[-1].pan == 80
    assert r[0].key == 60 and r[-1].key == 48, "высота дроби съезжает на октаву"
    assert r[0].ln > r[-1].ln * 3 and abs(r[-1].pos + r[-1].ln - 4) < 1e-9, "разгон: удары сгущаются, конец на месте"
    assert roll(0, 2, 4, pitch=1.5)[1].fine == 50, "дробный пич — подстройкой"
    assert [n.pan for n in ping([N(i, 1) for i in range(4)])] == [-60, 60, -60, 60]
    assert spread([N(i, 1) for i in range(40)]) == spread([N(i, 1) for i in range(40)]), "разброс повторяем"
    assert len({n.pan for n in spread([N(i, 1) for i in range(40)])}) > 10
    assert all(92 <= n.vel <= 108 for n in human([N(i, 1) for i in range(40)]))
    f = flam(N(8, 1, vel=100))
    assert f[0].pos == 7.75 and f[0].vel == 55 and f[1] == N(8, 1, vel=100)
    e = echo([N(0, 1, 72)], 3, times=2, decay=.5, width=70, pitch=12)
    assert [(n.pos, n.vel, n.pan, n.key) for n in e] == [(0, 100, 0, 72), (3, 50, -70, 84), (6, 25, 70, 96)]
    s = strum(0, 16, (56, 59, 63))
    assert [n.pos for n in s] == [0, .25, .5] and all(n.pos + n.ln == 16 for n in s) and s[0].vel < s[-1].vel
    c = chop(16, (56, 59), "x-.x..x-")
    assert [(n.pos, n.ln) for n in c if n.key == 56] == [(16, 2), (19, 1), (22, 2)]
    g = glide(0, 8, 32, 44, at=6, over=2)
    assert g[1].slide and g[1].pos == 6 and g[1].ln == 2 and g[1].key == 44
    assert sorted(flat(g)) == [N(0, 6.25, 32, 110), N(6, 2, 44, 110)], "в MIDI слайд — вторая нота внахлёст"
    assert grace(N(4, 4, 71)) == [N(4, .5, 70, 75), N(4.5, 3.5, 71)]
    h = hits(16, "x.o.|X...", vel=100)
    assert [(n.pos, n.vel) for n in h] == [(16, 100), (18, 45), (20, 115)], "рисунок строкой: удар, призрак, акцент"
    assert mute([N(0, 12, 32), N(8, 1), N(12, 4, 32)], 8, 12) == [N(0, 8, 32), N(12, 4, 32)], "вдох обрывает хвост 808"
    assert reverse([N(0, 2, 60), N(4, 1, 62), N(20, 1)], 0, 8) == [N(3, 1, 62), N(6, 2, 60)], "фраза задом наперёд"
    beat = {"хэт": hits(0, "x.x.x.x.x.x.x.x.") + hits(16, "x.x.x.x.x.x.") + roll(28, 4, 8),
            "клэп": [N(8, 1), N(24, 1)], "бочка": [N(0, 1)], "808": [N(0, 6, 32), N(6, 2, 35), N(16, 12, 32), N(24, 4, 44, slide=True)]}
    sh = shape(dict(bars=3, bpm=120), beat)
    assert (sh["хэт/такт"], sh["такты с дробью"], sh["808/такт"], sh["разных нот 808"], sh["слайдов на 8 т."]) == (11, .5, 2, 3, 4), sh
    assert sh["бочка под 808"] == .25 and sh["такты без барабанов"] == 1 and sh["секунд"] == 6 and sh["808 звучит"] == .63, sh
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        notes = r + g + [N(20, 2, 61, 90, -50, 30)]
        fsc(tmp / "a.fsc", notes)
        back = read_fsc(tmp / "a.fsc")
        assert len(back) == len(notes) and sum(n.slide for n in back) == 1
        assert N(20, 2, 61, 90, -50, 30) in back, "панорама и подстройка ноты доезжают до партитуры"
        data = (tmp / "a.fsc").read_bytes()         # заголовок — как у партитур из самого FL
        assert data[:22] == b"FLhd\x06\0\0\0\x10\0\x01\0\x60\0FLdt" + struct.pack("<I", len(data) - 22)
        mid(tmp / "a.mid", 156, _track("a", notes))
        assert read_mid(tmp / "a.mid") == (len(flat(notes)),) * 2
        (tmp / "beat").mkdir()
        one = min(known())                          # любой звук из списка: имена в нём меняет только Мак владельца
        (tmp / "beat" / "make.py").write_text(
            "from src.noty import N, roll, spread, glide\n"
            "INFO = dict(title='A x B — Тест', bpm=140, key='Fm', scale=[5, 7, 8, 10, 0, 1, 3], bars=2, skeleton='сцена',\n"
            "            like='x', parts='x', tricks=['x'], tonal=['808'], form='песня', melody='один аккорд', mood='злой',\n"
            "            twist='ложный вход', color='ржавчина', fx={'808': 'Fruity Fast Dist'},\n"
            "            mix={'основа': 'Chief Keef', 'чужое': 'кино', 'элемент': 'оркестровый слой'},\n"
            f"            sounds=dict.fromkeys(('808', 'хэт', 'клэп'), {one!r}))\n"
            "def compose():\n"
            "    return {'808': glide(0, 16, 29, 41, at=12, over=4), 'хэт': spread([N(i, 1) for i in range(32)]),\n"
            "            'клэп': [N(8, 1)] + roll(28, 4, 16)}\n", encoding="utf-8")
        archive = build(tmp / "beat", tmp / "out")
        names = zipfile.ZipFile(archive).namelist()
        assert "beat/fl/02 хэт.fsc" in names and "beat/midi/01 808.mid" in names and "beat/о бите.txt" in names
        note = archive.with_suffix(".txt").read_text("utf-8")
        assert "бит A x B — Тест, 140 Fm" in note and "Цвет: ржавчина" in note and "автор нот не слышал" in note, note
        assert "основа — Chief Keef; от чужого звука (кино) — оркестровый слой" in note, note
        try:                            # собранный бит против самого себя: та же форма, цвет и смесь — отказ
            build(tmp / "beat", tmp / "out", prev=(tmp / "beat" / "make.py",))
            raise AssertionError("повтор прошлого бита должен браковаться")
        except SystemExit as e:
            assert all(w in str(e) for w in ("форма «песня»", "цвет «ржавчина»", "смесь «Chief Keef + кино»")) \
                and "в том же порядке" not in str(e), e                                           # parts='x' — частей не названо
        (tmp / "20261005-a-b-140-fm").mkdir()               # обычный бит с 05.10.2026 без петли — отказ
        (tmp / "20261005-a-b-140-fm" / "make.py").write_text(
            (tmp / "beat" / "make.py").read_text("utf-8").replace("mood='злой'", "mood='обычный'"), encoding="utf-8")
        try:
            build(tmp / "20261005-a-b-140-fm", tmp / "out")
            raise AssertionError("обычный бит без петли должен браковаться")
        except SystemExit as e:
            assert "обычный бит — петлёй" in str(e), e
        # Папка «Сегодня» на временных папках: звук найден, не найден, не читается, чужой путь, старое убрано, оригинал цел
        lib, pres, kits, serum = tmp / "lib", tmp / "pres", tmp / "lib" / TODAY, tmp / "pres" / "User" / TODAY
        (lib / "k" / "Stub.wav").mkdir(parents=True)        # не читается, как заглушка iCloud без сети
        (pres / "User" / "p").mkdir(parents=True)
        kits.mkdir()
        (lib / "k" / "Kick.wav").write_bytes(b"k")
        (pres / "User" / "p" / "Lead.fxp").write_bytes(b"p")
        (kits / "старое.wav").write_bytes(b"x")
        listed = {"KITS/k/Kick.wav", "KITS/k/Gone.wav", "KITS/k/Stub.wav", "Serum/User/p/Lead.fxp"}
        missed = lay(tmp / "out" / "beat", {"бочка": "KITS/k/Kick.wav", "мелодия": ["Serum/User/p/Lead.fxp"], "хэт": "KITS/k/Gone.wav",
                                            "клэп": "KITS/k/Stub.wav", "перк": "KITS/../../etc/passwd"},
                     kits, serum, {"KITS": lib, "Serum": pres}, listed)
        assert (kits / "Бочка — Kick.wav").read_bytes() == b"k" and (serum / "Мелодия — Lead.fxp").read_bytes() == b"p"
        assert (kits / "02 хэт.fsc").exists() and not (kits / "старое.wav").exists() and (lib / "k" / "Kick.wav").read_bytes() == b"k"
        assert [m.split(":")[0] for m in missed] == ["хэт", "клэп", "перк"] and "нет на диске" in missed[0] \
            and "не прочитался" in missed[1] and "нет в списке" in missed[2], missed
        assert "Не легло в папку" in (kits / "о бите.txt").read_text("utf-8") and len(list(kits.iterdir())) == 5, list(kits.iterdir())
        assert lay(tmp / "out" / "beat", {}, kits, serum, {"KITS": lib, "Serum": pres}, listed) == [], "бит без поля звуков"
        assert sorted(f.suffix for f in kits.iterdir()) == [".fsc", ".fsc", ".fsc", ".txt"] and not list(serum.iterdir())
        assert json.loads((tmp / "out" / "beat.sounds.json").read_text("utf-8")) == dict.fromkeys(("808", "хэт", "клэп"), one)
    tune = [N(b * 16 + p, 2, k) for b in range(4) for p, k in ((0, 67), (6, 63), (8, 65), (12, 67))]
    song = dict(title="A — Б", form="песня", melody="линия", mood="обычный", twist="ложный вход", sounds={"мелодия": "x"},
                parts="вступление 1–4, припев 5–12, конец 13–16", color="лёд")
    rep = "\n".join(echoes(song, {"мелодия": tune}, song, {"мелодия": [n._replace(key=n.key + 6) for n in tune]}))
    assert all(w in rep for w in ("форма «песня»", "приём мелодии «линия»", "неожиданный ход «ложный вход»", "цвет «лёд»",
                                  "в том же порядке", "мелодия повторяет")), rep
    other = song | dict(form="блоки по 16", melody="зов — ответ", twist="сдвиг вниз", parts="вступление 1–8, блок 9–24", color="дым")
    assert not echoes(other, {"мелодия": [N(b * 16 + p, 1, k) for b in range(4) for p, k in ((2, 60), (3, 72), (10, 61))]},
                      song, {"мелодия": tune}), "другая форма и другая мелодия — не повтор"
    info = dict(title="t", bpm=140, key="Fm", scale=[5, 7, 8, 10, 0, 1, 3], bars=1, like="x", parts="x", tricks=["x"], skeleton="x",
                tonal=["мелодия"])
    plain = {"мелодия": [N(0, 4, 69)], "хэт": [N(i, 1) for i in range(16)], "бочка": [N(0, 1), N(20, 1)]}
    bad = "\n".join(problems(info, plain))
    assert "мимо тональности" in bad and "вне бита" in bad and "только в 0 партиях" in bad
    assert all(f"нет поля {k}" in bad for k in ("form", "mood", "color", "mix", "fx")), "паспорт проверяется и без --prev"
    assert "мимо тональности" not in "\n".join(problems(info, {"мелодия": [N(0, 4, 66), N(4, 4, 71)]})), "♭2 и ♭5 — можно долго"
    assert "не из списка" in "\n".join(problems(info | {"twist": "сальто"}, plain)), "ход — только из списка"
    assert "характер «добрый» — не из списка" in "\n".join(problems(info | {"mood": "добрый"}, plain))
    assert "в синтезаторе не работают" in "\n".join(problems(info, {"мелодия": glide(0, 4, 65, 77)}))
    assert "синтезатор" not in "\n".join(problems(info | {"tonal": ["808"]}, {"808": glide(0, 4, 29, 41)}))
    doubled = {"808": [N(i * 4, 3, 29) for i in range(4)], "бочка": [N(i * 4, 1) for i in range(4)]}
    assert "под каждой нотой 808" in "\n".join(problems(info | {"tonal": ["808"]}, doubled))
    named = "\n".join(problems(info | {"sounds": {"мелодия": "KITS/такого нет.wav"}}, plain))
    assert "нет в списке" in named and "хэт: партии не назван звук" in named, named
    assert "Звуки и пресеты" in about(info | {"twist": "ложный вход", "form": "x", "sounds": {"хэт": ["KITS/a.wav"]}}) \
        and "неожиданный ход: ложный вход" in about(info | {"twist": "ложный вход", "form": "x"})
    # Цвет: сладкое бракуется, сухое проходит. Сладкий — «Фосфор» в четырёх тактах: круг из четырёх аккордов,
    # мелодия наверху в семь нот, второй голос в терцию, колокольчик, ни одной паузы
    paper = dict(bars=4, tonal=["аккорды", "мелодия", "контрмелодия", "808"], mood="обычный", color="лёд")
    sweet = {"аккорды": [N(b * 16, 16, k + r) for b, r in enumerate((0, 8, 3, 10)) for k in (50, 53, 57)],
             "мелодия": [N(i * 4, 4, k) for i, k in enumerate((81, 79, 77, 84, 86, 82, 76) * 2)],
             "контрмелодия": [N(i * 4, 4, k - 3) for i, k in enumerate((81, 79, 77, 84, 86, 82, 76) * 2)],
             "808": [N(0, 64, 26)]}
    said = "\n".join(sugar(paper | {"sounds": {"мелодия": "Serum/User/Bells/Bell - Crystal Eye.fxp"}}, sweet))
    assert all(w in said for w in ("мелодия: 86% времени на F6", "4 разных по составу тактов", "в мотиве 7 разных нот",
                                   "в терцию или сексту 100%", "музыка молчит 0%", "колокольчик, шкатулка или плак")), said
    dry = {"аккорды": [N(b * 16, 16, k) for b in (0, 1, 2) for k in (50, 57)],              # один аккорд, такт тишины
           "мелодия": [N(b * 16 + p, 2, k) for b in (0, 1, 2) for p, k in ((0, 62), (6, 63), (10, 50))],     # три ноты, одна — ♭2
           "контрмелодия": [N(b * 16 + 6, 2, 51) for b in (0, 2)], "808": [N(0, 64, 26)]}       # второй голос — октавой ниже
    assert sugar(paper | {"sounds": {"мелодия": "Serum/Leads/LD Dirty Lead [SW].fxp"}}, dry) == [], sugar(paper, dry)
    half = {**dry, "аккорды": dry["аккорды"] + [N(48, 8, 50)]}                           # тишины полтакта из четырёх
    assert not sugar(paper | {"color": "андер"}, dry) and not sugar(paper, half), "тишины хватает"
    assert "молчит 12% времени — нужно не меньше 20%" in "\n".join(sugar(paper | {"color": "андер"}, half)), "андеру тишины нужно больше"
    assert not sugar(paper | {"mood": "кино"}, {"мелодия": [N(i * 12, 12, k) for i, k in enumerate((50, 53, 55, 57, 58))]}), \
        "кино: остинато не молчит, в теме пять нот"
    assert "в мотиве 5" in "\n".join(sugar(paper | {"twist": "смена бита", "bars": 20},
                                             {"мелодия": [N(i * 12, 12, k) for i, k in enumerate((50, 53, 55, 57, 58))]}))
    one = dict(color="лёд", mix={"основа": "Yung Lean", "чужое": "кино", "элемент": "оркестровый слой"})
    two = one | {"mix": one["mix"] | {"чужое": ["кино", "Chief Keef"], "элемент": ["оркестровый слой", "тембр"]}}
    assert _mix(one, False) == [] and _mix(two, True) == [] and "два чужих элемента" in _mix(two, False)[0]
    assert "основа — один референс своего цвета" in _mix(one | {"color": "дым"}, False)[0]
    assert "не из списка звуков" in _mix(one | {"mix": one["mix"] | {"чужое": "Boulevard Depo"}}, False)[0]
    assert "чужое — звук другого цвета" in _mix(one | {"mix": one["mix"] | {"чужое": "Black Kray"}}, False)[0]
    # Музыка петлёй: без партий музыки проходит; чужая папка, чужой темп, злой бит и набор партий Serum — брак
    assert loop_bpm("Acoustic Gtr - AC_12Str120A-01.wav") == 120 and loop_bpm("Country Crunk - K01AcouMix84C-02.wav") == 84
    assert not loop_bpm("Western Gtr - WW_AcouG_Chord-Amin.wav") and not loop_bpm("Country Crunk - K02Beat110-01.wav") \
        and not loop_bpm("Lex Luger - Strings140.wav"), "без темпа, барабаны и чужой набор — не петли"
    loop = min((n for n in known() if n.startswith(LOOPS) and loop_bpm(n) == 85), default="")
    assert loop, "в data/beat_sounds.json нет петель: перепиши список на Маке — noty --sounds"
    drums = {"808": glide(0, 16, 29, 41, at=12, over=4), "хэт": spread([N(i, 1) for i in range(32)]), "клэп": [N(8, 1)] + roll(28, 4, 16)}
    looped = dict(title="t", bpm=170, key="Am", scale=[9, 11, 0, 2, 4, 5, 7], bars=2, skeleton="сцена", like="x", parts="x",
                  tricks=["x"], tonal=["808"], form="песня", mood="обычный", twist="ложный вход", color="рифф", loop=loop,
                  mix={"основа": "Lil Peep", "чужое": "кино", "элемент": "обработка"}, sounds=dict.fromkeys(drums, loop),
                  fx={"808": "Fruity Fast Dist", "петля": "Gross Beat → Fruity Love Philter"})
    assert problems(looped, drums) == [] and problems(looped | {"bpm": 88}, drums) == [], problems(looped, drums)
    assert "Музыка — петлёй: темп в её имени — 85" in about(looped) and f"• петля — {loop}" in about(looped)
    assert "не сходится с темпом петли 85" in "\n".join(problems(looped | {"bpm": 140}, drums))
    for alien in ("KITS/01 - ASAP Rocky Kit/Loops/Lex Luger - Strings140.wav", loop.replace(LOOPS, "KITS/09 - Scene 2026 Kit")):
        assert "не из разрешённых петель" in "\n".join(problems(looped | {"loop": alien}, drums)), alien
    full = {**drums, "аккорды": [N(0, 8, 57)], "мелодия": [N(8, 2, 60)]}
    said = "\n".join(problems(looped | {"tonal": ["808", "аккорды", "мелодия"], "mood": "злой", "fx": {"808": "x"},
                                        "sounds": dict.fromkeys(full, loop)}, full))
    assert all(w in said for w in ("не больше одной", "только обычный бит", "нет строки «петля»")), said
    assert "петля «" in "\n".join(echoes(looped, drums, looped, drums)), "та же петля, что в прошлом бите, — повтор"
    assert _pages("а\n" * 3000) == ["а\n" * 2000, "а\n" * 1000] and _pages("коротко") == ["коротко"], "длинная записка — частями"
    assert _free("20261007-a-b-140-fm") and not _free("20261003-a-b-140-fm") and not _free("beat"), "свободная смесь — по средам"
    print("ноты: приёмы, партитура FL, MIDI, отбраковка, цвет (сладкое — брак, сухое проходит), смесь «основа + одно чужое», "
          "сверка с прошлым битом, неожиданный ход, музыка петлёй, звуки по списку и папка «Сегодня» — в порядке")


def main() -> None:
    p = argparse.ArgumentParser(description="Ноты для бита: партитуры FL Studio и MIDI")
    p.add_argument("--selftest", action="store_true", help="проверить приёмы и запись файлов, без сети")
    p.add_argument("--build", metavar="ПАПКА", type=Path, help="собрать архив из ПАПКА/make.py")
    p.add_argument("--prev", metavar="ФАЙЛ", type=Path, nargs="+", default=(),
                   help="make.py прошлых битов: та же форма, приём, цвет, смесь или сама мелодия — бит не годен")
    p.add_argument("--out", metavar="КУДА", type=Path, help="куда положить архив (по умолчанию — временная папка)")
    p.add_argument("--send", metavar="АРХИВ", type=Path, help="отправить собранный архив владельцу")
    p.add_argument("--sounds", action="store_true", help="переписать список имён звуков и пресетов библиотеки (только Мак)")
    p.add_argument("--gather", action="store_true", help="собрать папку «00 - Сегодня»: ноты свежего бита и его звуки (только Мак)")
    a = p.parse_args()
    if a.selftest:
        selftest()
    elif a.build:
        build(a.build, a.out or Path(tempfile.mkdtemp(prefix="noty-")), tuple(a.prev))
    elif a.send:
        send(a.send)
    elif a.sounds:
        from . import config, state
        names = library()
        if not names:
            raise SystemExit("Библиотеки на этой машине нет — список не тронут.")
        old = json.loads(config.BEAT_SOUNDS.read_text("utf-8")) if config.BEAT_SOUNDS.exists() else {}
        # незнакомые поля файла остаются: рядом с именами лежит то, что о звуках намерено
        config.BEAT_SOUNDS.write_text(json.dumps(old | {"date": state.now().strftime("%Y-%m-%d"), "sounds": names},
                                                 ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"{len(names)} имён → {config.BEAT_SOUNDS}")
    elif a.gather:
        print(gather())
    else:
        p.print_help()


if __name__ == "__main__":
    main()
