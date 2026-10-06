"""ЭКВАЛАЙЗЕР — Pro-Q 4 на дорожке микшера: срез ненужного по роли, состояние пишет сам плагин.

Владелец 06.10.2026: «вообще не забывай про эквализацию всех инструментов и чистку не нужных частот», «низ у басса
бы еще мощней сделать и чтоб четко по середине был до 100 герц». До этого проект FL (src/flp.py) нёс эквалайзер только
там, где его назвал автор нот, и с настройками по умолчанию: «срез низа до 150 Гц» владелец выставлял руками.

Плагин — FabFilter Pro-Q 4: им владелец режет сам, и только у него число в файле подтверждается не догадкой. Он
открывается без FL и без окна (pedalboard грузит VST3 в процесс, как Serum в src/serum.py), ручки ставятся именами
и герцами, состояние отдаёт он сам. Сверено 06.10.2026 (`--check`): срез 150 Гц, записанный в состояние, другой
экземпляр плагина читает ручкой как 150 Гц, а синус 150 Гц выходит из него тише на 3,0 дБ, 75 Гц — на 24 дБ.
Отвергнуто: Fruity Parametric EQ 2 — родной, но шкалу его частоты подтвердить нечем: вне FL он не открывается,
а формула, которой читались чужие проекты (20 Гц × 1000^доля), заводские пресеты FL «30Hz + 18kHz cut» и «40Hz cut»
читает как 23,9 и 32,2 Гц. Четверть мимо у среза 808 — это съеденный или оставленный низ.

У 808 в нём рецепт самого владельца (BASS): срез низа на канале Side и полка низа на канале Mid с динамикой — так он
сводит низ к центру и поднимает его в своих битах. Отвергнуто: моно всей дорожки ручкой разведения FL — он снял её
в нашем проекте и не трогает ни в одном своём; полка Stereo с чужого проекта — она поднимала и края.

В проект плагин встаёт видом VST2 — тем, каким владелец ставит его сам: 56 экземпляров в 40 последних его проектах.
Кусок состояния у VST2 и VST3 один: «FFBS», версия, 576 чисел — 24 полосы по 23 ручки и 24 общих, — потом хвост.
Числа пишет плагин; хвост у VST2 — сведения о пресете, он взят таким, каким его сохранил FL (TAIL). Отвергнуто:
Audio Unit — pedalboard на нём падает, а plist его состояния пришлось бы писать с догадки; собирать числа куска
самим — значение каждой ручки (наклон 24 дБ на октаву — 3,99) пришлось бы снимать с плагина, а он и так под рукой.

Плагин работает отдельным процессом и другим Python, как Serum: pedalboard стоит только в config.SERUM_PYTHON.
Не ответил или записал не то, что просили, — в слоте остаётся Pro-Q 4 без настроек, числа уходят в записку. В Actions
плагина нет: селфтест проекта (`flp --selftest`) подставляет кусок в миниатюре. Звука сборка не слышит: числа срезов —
отправная точка, а не сведение.

    python -m src.proq --check   плагин ставит срезы всех ролей, другой экземпляр читает их ручками, кусок VST2 режет звук
    python -m src.proq --make    состояния по заданиям: JSON из stdin — списки полос, итог — строкой JSON

Запускать тем Python, где стоит pedalboard: `.cache/serum-spike/venv/bin/python -m src.proq --check` (только Мак).
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import re
import struct
import subprocess
import sys
from pathlib import Path

from . import config
from .serum import _dec, _enc

VST3 = Path("/Library/Audio/Plug-Ins/VST3/FabFilter Pro-Q 4.vst3")
KEY = "fabfilterproq4"      # имя в базе плагинов FL (`flp._effects`): под ним — VST2, под «Pro-Q 4» — Audio Unit
ID = b"p4QF"                # номер плагина VST2 в обёртке FL, задом наперёд
EQS = ("proq", "parametriceq", "7bandeq", "equo")   # эквалайзеры базы: свой постоянный в цепочке автора — второго не ставим
SR = 44100
WAIT = 120                  # секунд на все дорожки бита: плагин грузится около секунды
BAND, BANDS, COUNT = 23, 24, 576    # ручек у полосы, полос, чисел в куске
# Вид полосы в куске — номером, в порядке списка самого плагина
SHAPES = ("Bell", "Low Shelf", "Low Cut", "High Shelf", "High Cut", "Notch", "Band Pass", "Tilt Shelf", "Flat Tilt", "All Pass")
RU = {"Low Cut": "срез низа", "High Cut": "срез верха", "Low Shelf": "полка низа", "High Shelf": "полка верха", "Bell": "колокол"}
SLOPE = "24 dB/oct"         # наклон срезов: при срезе 180 Гц на 100 Гц остаётся −20 дБ, при 12 дБ на октаву — −10
# Срез низа по роли, Гц (владелец: «чистку не нужных частот»). Низ бита — только 808 и бочка, поэтому у музыки ниже
# 100 Гц не остаётся ничего: 180 — между двумя чтениями среза на шине мелодии чужого проекта 04 (пересборка
# M3tamorphosis; разбор.md, п. 11): 172 Гц формулой разборщика и около 200, если заводские пресеты FL названы точно.
# На барабанах в шести чужих проектах эквалайзера нет — числа обычные для сведения, не снятые ни с чего.
MUSIC = 180
DRUMS = (("бочка", 30), ("клэп", 120), ("снейр", 120), ("хэт", 350), ("открыт", 350), ("крэш", 350), ("римшот", 200), ("перк", 200))
# Куда смотрит полоса — номером в куске, в порядке списка самого плагина (ручка «stereo placement»); без слова — Stereo
PLACES = ("Left", "Right", "Stereo", "Mid", "Side")
# 808: срез гула под нижней нотой (до1 — 32,7 Гц — теряет на нём полдецибела) и рецепт самого владельца — так стоит
# Pro-Q 4 на дорожке 808 в его битах BEAT 1 и BEAT 3 (Beats 4 PLENKA, 01.10 и 03.10.2026; каналы названы плагином):
# срез низа 99 Гц на Side — «чтоб четко по середине был до 100 герц» — и полка низа 99 Гц на Mid, +2,6 и +1,5 дБ,
# с динамикой на столько же вниз — «низ у басса мощней». Взят BEAT 1. Динамика — пятое число полосы: порог «Auto», как
# у него; полка прибавляет тихому, а на громкой ноте сходит к нулю (синус −12 дБ: 0 дБ, −52 дБ: +2,4 — `--check`).
# Наклон среза у него круче нашего (в куске 6 и 9 против 3,99 у 24 дБ на октаву) — оставлен общий SLOPE. Верх не режется.
# До 06.10.2026 здесь стояла полка чужого проекта 06, +2,5 дБ на 155 Гц Stereo, а моно делала ручка разведения дорожки:
# её владелец снял в автосохранении нашего проекта и не трогает ни в одном своём бите.
BASS = (("Low Cut", 25.0, 0.0), ("Low Cut", 99.0, 0.0, "Side"), ("Low Shelf", 99.0, 2.6, "Mid", -2.6))
# Слова автора нот в звене fx — вместо числа роли: «срез низа до 150 Гц», «фильтр низких частот от 6 кГц»
WORDS = re.compile(r"(срез низа|фильтр высоких частот|срез верха|фильтр низких частот)\s+(?:до|от|ниже|выше|с|на)?\s*"
                   r"(\d+(?:[.,]\d+)?)\s*(к?)гц", re.I)
# Хвост куска у VST2 — сведения о пресете. Снят с проекта владельца, который сохранил FL: у шести экземпляров он один.
# У VST3 хвост другой («FFpr» и два числа), а числа перед ним те же.
_s = lambda s: struct.pack("<I", len(s)) + s
TAIL = (b"FQ4p" + struct.pack("<I", 3) + _s(b"Default Setting") + struct.pack("<iI", -1, 1) + _s(b"Pro-Q") + struct.pack("<I", 1)
        + b"CuSV" + struct.pack("<II", 1, 3) + _s(b"AUTHOR") + _s(b"FabFilter") + _s(b"DESCRIPTION")
        + _s(b"This preset is loaded when you open a new instance.\n\nYou can customize the Default Setting preset as you like, "
             b"and save it via the preset options menu > Save As Default.") + _s(b"TAGS") + _s(b"Default,Clean,Start"))


def bands(row: str, kind: str | None, words: str = "") -> list[tuple]:
    """Полосы эквалайзера дорожки: вид, герцы, дБ и, если полоса не Stereo, — канал (Mid, Side) и динамика в дБ.
    kind — роль дорожки из `flp.today`; у шины и мастера её нет, и своих срезов там нет — только названные автором.
    words — звено fx с эквалайзером автора: его срез встаёт вместо среза роли, полосы на Mid и Side остаются."""
    out = (list(BASS) if kind == "808" else [("Low Cut", float(MUSIC), 0.0)] if kind == "музыка"
           else [("Low Cut", float(hz), 0.0) for w, hz in DRUMS if w in row.lower()][:1] if kind else [])
    for what, n, kilo in WORDS.findall(words):
        shape, hz = ("Low Cut" if what.lower() in ("срез низа", "фильтр высоких частот") else "High Cut",
                     float(n.replace(",", ".")) * (1000 if kilo else 1))
        if 10 <= hz <= 30000:               # пределы ручки плагина
            out = [b for b in out if b[0] != shape or len(b) > 3] + [(shape, hz, 0.0)]
    return sorted(out, key=lambda b: b[1])


def say(bands) -> str:
    """Полосы словами записки: «срез низа 25 Гц, срез низа 99 Гц (Side), полка низа 99 Гц +2.6 дБ (Mid, динамика -2.6 дБ)».
    Герцы — до трёх значащих цифр: ручка плагина ходит шагами, и 6 кГц из его состояния читаются как 6000,6 Гц."""
    return ", ".join(f"{RU.get(s, s)} {float(f'{hz:.3g}'):g} Гц" + (f" {db:+.1f} дБ" if abs(db) >= .05 else "")
                     + (f" ({at}" + (f", динамика {dyn:+.1f} дБ" if abs(dyn) >= .05 else "") + ")" if at != "Stereo" or abs(dyn) >= .05 else "")
                     for s, hz, db, at, dyn in map(_full, bands))


def _full(band) -> tuple:
    """Полоса пятью числами: недостающие канал и динамика — Stereo и 0."""
    return tuple(band) + ("Stereo", 0.0)[len(band) - 3:]


def read(chunk: bytes) -> list[tuple]:
    """Включённые полосы куска состояния. У полосы по порядку: занята, включена, двоичный логарифм герц, дБ, добротность,
    вид, наклон, канал, колонки, динамика в дБ — имена и порядок ручек отдал сам плагин, числа сверены им же (`--check`).
    Канал и динамика — только у полосы, где они не Stereo и не 0. Не кусок Pro-Q 4 — пусто."""
    if chunk[:4] != b"FFBS" or len(chunk) < 12 + 4 * COUNT:
        return []
    x = struct.unpack_from(f"<{BAND * BANDS}f", chunk, 12)
    name = lambda names, v: names[int(v)] if 0 <= v < len(names) else f"№ {v:g}"
    out = [(name(SHAPES, x[k + 5]), 2 ** x[k + 2], x[k + 3], name(PLACES, x[k + 7]), x[k + 9])
           for k in range(0, len(x), BAND) if x[k] and x[k + 1]]
    return [b if abs(b[4]) >= .05 else b[:4] if b[3] != "Stereo" else b[:3] for b in out]


def _same(got, want) -> bool:
    return len(got) == len(want) and all(a[0] == b[0] and abs(a[1] - b[1]) <= .005 * b[1] and abs(a[2] - b[2]) < .05
                                         and a[3] == b[3] and abs(a[4] - b[4]) < .05 for a, b in zip(map(_full, got), map(_full, want)))


def _ask(jobs: list) -> list[bytes]:
    got = subprocess.run([str(config.SERUM_PYTHON), "-m", "src.proq", "--make"], input=json.dumps(jobs),
                         capture_output=True, text=True, timeout=WAIT, cwd=config.ROOT)
    return [base64.b64decode(s) for s in json.loads(got.stdout.strip().splitlines()[-1])]


def states(jobs: list, ask=_ask) -> list[bytes | None]:
    """Куски состояния VST2, по одному на задание — список полос (`bands`). None — плагин не ответил (нет его, нет
    pedalboard, вышел срок) или в куске не то, что просили: кусок читается обратно и сверяется до того, как лечь в проект."""
    try:
        raw = ask(jobs) if jobs else []
    except (OSError, subprocess.SubprocessError, ValueError, LookupError, TypeError):
        raw = []
    raw = [c[:12 + 4 * COUNT] + TAIL for c in raw] + [b""] * (len(jobs) - len(raw))
    return [c if _same(read(c), job) else None for c, job in zip(raw, jobs)]


# --- плагин: только в процессе с pedalboard -----------------------------------

def _put(p, chunk: bytes) -> None:
    xml = ('<?xml version="1.0" encoding="UTF-8"?> <VST3PluginState><IComponent>' + _enc(chunk)
           + "</IComponent></VST3PluginState>").encode()
    p.raw_state = b"VC2!" + struct.pack("<I", len(xml)) + xml + b"\0"


def make(jobs: list) -> list[bytes]:
    """Состояния самим плагином: на задание — свежий экземпляр, полосы по порядку, ручки именами и герцами."""
    import numpy as np
    from pedalboard import load_plugin
    out = []
    for job in jobs:
        p = load_plugin(str(VST3))
        for k, (shape, hz, db, *more) in enumerate(job, 1):
            for knob, v in (("used", "Used"), ("shape", shape), ("frequency", float(hz)), ("gain", float(db)),
                            *((("slope", SLOPE),) if shape.endswith("Cut") else ()),
                            *((("stereo_placement", more[0]),) if more else ()),
                            *((("dynamic_range", float(more[1])), ("threshold", "Auto")) if len(more) > 1 else ())):
                setattr(p, f"band_{k}_{knob}", v)
        p(np.zeros((2, SR // 10), dtype=np.float32), SR)    # ручка VST3 доходит до плагина только со звуком: до него состояние прежнее
        out.append(_dec(re.search(rb"<IComponent>(.*?)</IComponent>", p.raw_state).group(1).decode()))
    return out


def _gain(p, hz: float, side: bool = False, amp: float = .25) -> float:
    """На сколько децибел плагин меняет синус этой частоты; меряется вторая секунда — фильтр уже установился.
    side — синус в противофазе: его слышит только канал Side; amp — размах: тихий синус динамику полосы не будит."""
    import numpy as np
    x = (amp * np.sin(2 * math.pi * hz * np.arange(SR * 2) / SR)).astype(np.float32)
    y = p(np.stack([x, -x if side else x]), SR, reset=True)
    return 20 * math.log10(max(float(np.sqrt((y[:, SR:] ** 2).mean())), 1e-9) / float(np.sqrt((x[SR:] ** 2).mean())))


def check() -> str:
    """Срезы всех ролей: плагин пишет состояние, другой экземпляр читает его ручками, третий — куском VST2, каким он
    ляжет в проект, — режет синус. Ручками кусок VST2 не читается (чужой хвост), поэтому он меряется звуком: срез
    на Side — синусом в противофазе, полка с динамикой — тихим и громким."""
    from pedalboard import load_plugin
    rows = [("808", "808", ""), ("бочка", "барабаны", ""), ("клэп", "барабаны", ""), ("хэт", "барабаны", ""), ("перк", "барабаны", ""),
            ("мелодия", "музыка", ""), ("шина музыки", None, "Pro-Q 4: срез низа до 150 Гц, срез верха от 6 кГц")]
    jobs = [bands(*r) for r in rows]
    raw, done, lines = make(jobs), states(jobs, make), []
    for (row, _, _), job, c, vst2 in zip(rows, jobs, raw, done):
        q = load_plugin(str(VST3))
        _put(q, c)
        knobs = [(str(getattr(q, f"band_{k}_shape")), float(getattr(q, f"band_{k}_frequency")), float(getattr(q, f"band_{k}_gain")),
                  str(getattr(q, f"band_{k}_stereo_placement")), float(getattr(q, f"band_{k}_dynamic_range"))) for k in range(1, len(job) + 1)]
        assert _same(knobs, job) and str(q.band_1_used) == "Used" and str(getattr(q, f"band_{len(job) + 1}_used")) == "Unused", (row, knobs)
        assert all(str(getattr(q, f"band_{k}_slope")) == SLOPE for k, b in enumerate(job, 1) if b[0].endswith("Cut")), row
        assert vst2 and _same(read(vst2), job) and vst2.endswith(TAIL), f"{row}: кусок читается не так, как просили"
        q = load_plugin(str(VST3))
        _put(q, vst2)
        heard = []
        for shape, hz, db, place, dyn in map(_full, job):
            at = {"Low Cut": hz / 2, "High Cut": hz * 2, "Low Shelf": hz / 2.5}[shape]
            g = _gain(q, at, place == "Side", .0025 if dyn else .25)        # полка с динамикой меряется тихим синусом
            assert g < -18 if shape.endswith("Cut") else db - 1 < g < db + .3, f"{row}: {RU[shape]} {hz:g} Гц — на {at:g} Гц {g:+.1f} дБ"
            if len(job) == 1:                           # одна полоса — срез ровно на своей частоте: −3 дБ
                assert abs(_gain(q, hz) + 3) < .5, f"{row}: на {hz:g} Гц не −3 дБ"
            heard.append(f"{at:g} Гц {g:+.1f} дБ" + (f" ({place})" if place != "Stereo" else ""))
            if place == "Side":                         # срез краёв центр не трогает, выше себя и края не трогает
                assert _gain(q, at) > -3 and abs(_gain(q, hz * 4, True)) < .5, f"{row}: срез Side задел центр или верх"
            if dyn:                                     # динамика вниз: громкому синусу полка прибавляет меньше
                loud = _gain(q, at)
                assert loud < g - 1, f"{row}: динамика полки не слышна — громко {loud:+.1f} дБ, тихо {g:+.1f}"
                heard.append(f"громко {loud:+.1f} дБ")
        assert abs(_gain(q, 1000)) < .3, f"{row}: 1 кГц задет"
        lines.append(f"{row}: {say(job)} — ручки плагина те же; звуком: {', '.join(heard)}, 1 кГц {_gain(q, 1000):+.1f} дБ")
    return "Pro-Q 4 без FL: состояние пишет и читает сам плагин\n" + "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Срезы Pro-Q 4 по ролям дорожек: состояние пишет сам плагин (только Мак)")
    ap.add_argument("--check", action="store_true", help="срезы всех ролей: плагин пишет, читает обратно и режет звук")
    ap.add_argument("--make", action="store_true", help="состояния по заданиям: JSON из stdin")
    args = ap.parse_args()
    if args.check:
        print(check())
    elif args.make:
        print(json.dumps([base64.b64encode(c).decode() for c in make(json.loads(sys.stdin.read()))]))
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
