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

    python -m src.noty --selftest          приёмы пианоролла, замер нот и запись партитуры FL и MIDI, без сети
    python -m src.noty --build ПАПКА       собрать и проверить бит из ПАПКА/make.py, без Telegram
    python -m src.noty --build ПАПКА --prev ФАЙЛ…   то же и сверка с make.py прошлых битов: та же форма или мелодия — отказ
    python -m src.noty --send АРХИВ        отправить собранный архив владельцу

Сетка — шестнадцатые: такт = 16, доля = 4.
"""
from __future__ import annotations

import argparse
import random
import re
import runpy
import struct
import tempfile
import zipfile
from pathlib import Path
from typing import NamedTuple

TICK = 24                 # тиков FL в шестнадцатой: PPQ 96, как в проектах владельца
PPQ, MIDI_TICK = 480, 120
# Черновик «всё вместе» играет любой плеер: тембр General MIDI — по слову в имени партии
GM_TONAL = {"аккорд": 89, "гитар": 25, "мелод": 10, "808": 38, "бас": 38, "колокол": 14, "струн": 48, "флейт": 73}
GM_DRUM = {"бочка": 36, "клэп": 39, "снейр": 38, "открыт": 46, "хэт": 42, "римшот": 37, "перк": 75, "крэш": 49}


SAMPLED = ("808", "бас")    # партии с высотой, которые владелец играет сэмплером, а не синтезатором


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

def problems(info: dict, tracks: dict[str, list[N]]) -> list[str]:
    """Что не так с битом. Пусто — годен."""
    out, end = [], info["bars"] * 16
    out += [f"в паспорте нет поля {k}" for k in ("title", "bpm", "key", "scale", "bars", "skeleton", "like", "parts", "tricks")
            if not info.get(k)]
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
                for n in flat(notes) if name in info.get("tonal", ()) and n.key % 12 not in info["scale"] and n.ln > 1]
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
    return out[:20]


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
    out = [f"в паспорте нет поля {k}" for k in ("form", "melody", "mood") if not info.get(k)]
    out += [f"{word} «{info[k]}» — как в {was}: возьми другое" for k, word in (("form", "форма"), ("melody", "приём мелодии"))
            if info.get(k) and info[k] == old.get(k)]

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


def about(info: dict) -> str:
    """Записка владельцу: она же подпись к архиву."""
    return "\n".join([
        f"🎹 {info['title']}", f"{info['bpm']} BPM, {info['key']}, {info['bars']} тактов", "",
        f"Скелет: {info['skeleton']}",
        *([f"Форма: {info.get('form', '—')}; мелодия: {info.get('melody', '—')}; характер: {info.get('mood', '—')}"]
          if info.get("form") or info.get("melody") or info.get("mood") else []), f"С чего снято: {info['like']}", f"Части: {info['parts']}", "",
        "Что сделано нотами:", *(f"• {t}" for t in info["tricks"]), "",
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
    bad = problems(info, tracks)
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
    print(f"{info['bpm']} BPM, {info['bars']} тактов, {info['bars'] * 240 / info['bpm']:.0f} с → {archive}")
    return archive


def send(archive: Path) -> None:
    """Архив и следом записка: в подпись к файлу (1024 знака) она не влезает."""
    from . import config, telegram
    text = archive.with_suffix(".txt").read_text("utf-8")
    telegram.send_document(config.secret("TELEGRAM_ADMIN_ID"), archive, "\n".join(text.splitlines()[:2]))
    telegram.send_message(config.secret("TELEGRAM_ADMIN_ID"), text)


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
        (tmp / "beat" / "make.py").write_text(
            "from src.noty import N, roll, spread, glide\n"
            "INFO = dict(title='A x B — Тест', bpm=140, key='Fm', scale=[5, 7, 8, 10, 0, 1, 3], bars=2, skeleton='сцена',\n"
            "            like='x', parts='x', tricks=['x'], tonal=['808'])\n"
            "def compose():\n"
            "    return {'808': glide(0, 16, 29, 41, at=12, over=4), 'хэт': spread([N(i, 1) for i in range(32)]),\n"
            "            'клэп': [N(8, 1)] + roll(28, 4, 16)}\n", encoding="utf-8")
        archive = build(tmp / "beat", tmp / "out")
        names = zipfile.ZipFile(archive).namelist()
        assert "beat/fl/02 хэт.fsc" in names and "beat/midi/01 808.mid" in names and "beat/о бите.txt" in names
        assert "бит A x B — Тест, 140 Fm" in archive.with_suffix(".txt").read_text("utf-8")
        try:                            # собранный бит против самого себя: та же форма — отказ
            build(tmp / "beat", tmp / "out", prev=(tmp / "beat" / "make.py",))
            raise AssertionError("повтор прошлого бита должен браковаться")
        except SystemExit as e:
            assert "в паспорте нет поля form" in str(e) and "в том же порядке" not in str(e), e   # parts='x' — частей не названо
    tune = [N(b * 16 + p, 2, k) for b in range(4) for p, k in ((0, 67), (6, 63), (8, 65), (12, 67))]
    song = dict(title="A — Б", form="песня", melody="линия", mood="обычный", parts="вступление 1–4, припев 5–12, конец 13–16")
    rep = "\n".join(echoes(song, {"мелодия": tune}, song, {"мелодия": [n._replace(key=n.key + 6) for n in tune]}))
    assert all(w in rep for w in ("форма «песня»", "приём мелодии «линия»", "в том же порядке", "мелодия повторяет")), rep
    other = song | dict(form="блоки по 16", melody="зов — ответ", parts="вступление 1–8, блок 9–24")
    assert not echoes(other, {"мелодия": [N(b * 16 + p, 1, k) for b in range(4) for p, k in ((2, 60), (3, 72), (10, 61))]},
                      song, {"мелодия": tune}), "другая форма и другая мелодия — не повтор"
    info = dict(title="t", bpm=140, key="Fm", scale=[5, 7, 8, 10, 0, 1, 3], bars=1, like="x", parts="x", tricks=["x"], skeleton="x",
                tonal=["мелодия"])
    plain = {"мелодия": [N(0, 4, 66)], "хэт": [N(i, 1) for i in range(16)], "бочка": [N(0, 1), N(20, 1)]}
    bad = "\n".join(problems(info, plain))
    assert "мимо тональности" in bad and "вне бита" in bad and "только в 0 партиях" in bad
    assert "в синтезаторе не работают" in "\n".join(problems(info, {"мелодия": glide(0, 4, 65, 77)}))
    assert "синтезатор" not in "\n".join(problems(info | {"tonal": ["808"]}, {"808": glide(0, 4, 29, 41)}))
    doubled = {"808": [N(i * 4, 3, 29) for i in range(4)], "бочка": [N(i * 4, 1) for i in range(4)]}
    assert "под каждой нотой 808" in "\n".join(problems(info | {"tonal": ["808"]}, doubled))
    print("ноты: приёмы, партитура FL, MIDI, отбраковка и сверка с прошлым битом — в порядке")


def main() -> None:
    p = argparse.ArgumentParser(description="Ноты для бита: партитуры FL Studio и MIDI")
    p.add_argument("--selftest", action="store_true", help="проверить приёмы и запись файлов, без сети")
    p.add_argument("--build", metavar="ПАПКА", type=Path, help="собрать архив из ПАПКА/make.py")
    p.add_argument("--prev", metavar="ФАЙЛ", type=Path, nargs="+", default=(),
                   help="make.py прошлых битов: та же форма, приём или сама мелодия — бит не годен")
    p.add_argument("--out", metavar="КУДА", type=Path, help="куда положить архив (по умолчанию — временная папка)")
    p.add_argument("--send", metavar="АРХИВ", type=Path, help="отправить собранный архив владельцу")
    a = p.parse_args()
    if a.selftest:
        selftest()
    elif a.build:
        build(a.build, a.out or Path(tempfile.mkdtemp(prefix="noty-")), tuple(a.prev))
    elif a.send:
        send(a.send)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
