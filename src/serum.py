"""СВОЙ ПРЕСЕТ — тембр Serum под утренний бит: основа из библиотеки, ручки числами, проверка самим плагином.

Владелец 06.10.2026: «пускай утренняя сборка не останавливается на моих скачанных библиотеках, а использует
интернет и собственные пресеты», раньше — «пресеты уникальные для меня». Чужие паки стоят у всех, а автор нот
звука не слышит и на Мак ничего не кладёт. Поэтому он пишет в паспорт бита только данные — поле preset:
на какую партию, имя, основа (пресет из списка data/beat_sounds.json) и ручки долями 0..1. Мак открывает основу
самим Serum без FL и без окна (библиотека pedalboard грузит VST3 в процесс), ставит ручки, пишет .fxp в папку
пресетов «00 - Сегодня» и проверяет то, что можно проверить числом: записанный файл открывается свежим плагином,
нота звучит, не тишина и не перегруз. На слух пресет не проверяет никто — записка так и говорит.

Пресет Serum 1 (.fxp) — 60 байт заголовка и zlib-чанк; тот же чанк лежит в состоянии VST3 полем IComponent
(base64 JUCE), поэтому файл читается и пишется без посредников.

Плагин играет в отдельном процессе и другим Python: pedalboard стоит только в окружении config.SERUM_PYTHON,
а помощник на Маке (src/tracks.py) живёт в .venv проекта, куда лишний пакет не ставим. Зависший плагин
получает срок, упавший — строку в записке; бит от своего пресета не зависит никогда. В Actions ни Serum,
ни pedalboard нет: сборка нот проверяет только форму поля (`flaws`), звук — дело Мака.

Ручки — короткий список `KNOBS`, а не все 349 параметров плагина: срез верха, огибающая громкости, расстройка,
шум и встроенные эффекты — то, что можно писать, не видя основы. Что ручка сделала с этой основой, показывает замер
до и после: он идёт в записку. Громкая нота чинится сама — мастер пресета убавляется: автор нот исправить её
не может, он узнал бы о ней только завтра. Тишина не чинится — пресет не кладётся.

Отвергнуто: .vstpreset — браузер Serum его не показывает. Отвергнуто: таблица волн с нуля и матрица модуляций —
через параметры плагина они не ставятся, а чанк пресета не разобран. Отвергнуто: сверять записанный файл
с собранным по яркости — у пресета со случайной фазой она гуляет от запуска к запуску на 16%; сверяются ручки.
Отвергнуто: класть в репозиторий сами пресеты и таблицы — они чужие и платные.

    python -m src.serum --check     плагин грузится, звучит, .fxp пишется и читается обратно (нужен SERUM_PYTHON)
    python -m src.serum --knobs     что значит доля каждой ручки: подписи самого плагина (нужен SERUM_PYTHON)
    python -m src.serum --make      собрать и проверить один пресет: задание JSON из stdin, итог — строкой JSON

Запускать тем Python, где стоит pedalboard: `.cache/serum-spike/venv/bin/python -m src.serum --check` (только Мак;
другое место — переменная SERUM_PYTHON).
"""
from __future__ import annotations

import argparse
import json
import re
import struct
import subprocess
import sys
import unicodedata
from pathlib import Path

VST3 = Path("/Library/Audio/Plug-Ins/VST3/Serum.vst3")
SR = 44100
NOTE, VEL, HOLD, LEN = 60, 100, 1.0, 2.0    # как в промере библиотеки (поле serum списка звуков): C5 в FL, секунда
PEAK = (.05, 1.0)       # пик одной ноты: тише — «тишина» (в библиотеке из 884 пресетов таких 4), выше — перегруз
QUIETER = 4             # попыток убавить мастер, пока пик громче CALM[1]
CALM = (.7, .85)        # мастер убавляется до пика 0.7, если пик выше 0.85: от запуска к запуску пик одного пресета
                        # гуляет на ±15% (случайная фаза), и 0.99 при сборке — это 1.1 у владельца
TAKES = 3               # запусков ноты на один замер
WAIT = 180              # секунд на один пресет: Serum грузится 11 с, пресет — две загрузки и до двух десятков нот
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _-]{0,26}")   # имя внутри .fxp — 27 знаков ASCII; оно же имя файла
ABC = ".ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+"     # base64 JUCE: свой алфавит, биты с младшего
REV = {c: i for i, c in enumerate(ABC)}
# Ручка → пределы доли 0..1. Выключатели (…_on, …_enable) — только 0 или 1. Что значит доля — `--knobs`
# и раздел «Свой пресет» брифа: подписи там сняты с самого плагина.
KNOBS = {
    "filter_on": (0, 1), "fil_cutoff_hz": (.4, 1), "fil_reso": (0, .6), "fil_driv": (0, 1),
    "env1_atk_ms": (0, .5), "env1_dec_s": (0, 1), "env1_sus_db": (0, 1), "env1_rel_ms": (0, .6),
    "a_unison": (0, .4), "a_unidet": (0, 1), "a_fine_cents": (.4, .6), "a_wtpos": (0, 1),
    "osc_b_on": (0, 1), "b_vol": (0, .85), "b_fine_cents": (.4, .6),
    "osc_n_on": (0, 1), "noise_level": (0, .6), "osc_s_on": (0, 1), "sub_osc_level": (0, .85),
    "dist_enable": (0, 1), "dist_drv": (0, .8), "dist_wet": (0, 1),
    "cho_enable": (0, 1), "cho_wet": (0, 1),
    "rev_enable": (0, 1), "verb_wet": (0, .6), "verbsize": (0, 1),
    "eq_enable": (0, 1), "eq_typh": (0, 1), "eq_frqh_hz": (.5, 1), "eq_volh_db": (0, 1),
}


def _switch(knob: str) -> bool:
    return knob.endswith(("_on", "_enable"))


def flaws(preset, listed: set[str]) -> list[str]:
    """Что не так с полем preset паспорта — по форме, без звука: это и сборка в Actions, и вторая проверка
    на Маке (задание пришло из make.py, а её писала модель: это данные, а не доверенный путь)."""
    if not isinstance(preset, dict) or not preset:
        return ["preset: нужен словарь «партия → {имя, основа, ручки}»"]
    out = []
    for part, p in preset.items():
        if not isinstance(p, dict) or set(p) != {"имя", "основа", "ручки"}:
            out.append(f"preset, {part}: нужны ровно три поля — «имя», «основа», «ручки»")
            continue
        if not isinstance(p["имя"], str) or not NAME.fullmatch(p["имя"]):
            out.append(f"preset, {part}: имя — латиница, цифры, пробел, дефис, до 27 знаков")
        base = unicodedata.normalize("NFC", str(p["основа"]))
        if not (base.startswith("Serum/") and base.endswith(".fxp") and base in listed):
            out.append(f"preset, {part}: основы «{base}» нет среди пресетов Serum в data/beat_sounds.json")
        knobs = p["ручки"]
        if not isinstance(knobs, dict) or not knobs:
            out.append(f"preset, {part}: не названо ни одной ручки")
            continue
        for k, v in knobs.items():
            if k not in KNOBS:
                out.append(f"preset, {part}: ручки «{k}» нет в списке serum.KNOBS")
            elif isinstance(v, bool) or not isinstance(v, (int, float)) or not KNOBS[k][0] <= v <= KNOBS[k][1]:
                out.append(f"preset, {part}: {k} = {v!r} — нужна доля от {KNOBS[k][0]:g} до {KNOBS[k][1]:g}")
            elif _switch(k) and v not in (0, 1):
                out.append(f"preset, {part}: {k} — выключатель, 0 или 1")
    return out


def label(part: str, name: str) -> str:
    """Имя файла в папке «Сегодня»: партия впереди, как у копий звуков (`noty.lay`)."""
    part = re.sub(r"[/\\:\0]", " ", str(part))[:40]
    return f"{part[:1].upper()}{part[1:]} — {name}.fxp"


def tune(preset, folder: Path, root: Path, listed: set[str]) -> list[str]:
    """Свои пресеты бита — в папку пресетов «Сегодня»; возвращает строки для записки, по одной на партию.
    Не падает ни при каком исходе: нет плагина, нет Python с pedalboard, плагин завис — строка, а не ошибка."""
    from . import config
    out = []
    for part, p in (preset.items() if isinstance(preset, dict) else []):
        bad = flaws({part: p}, listed)
        if bad:
            out.append(f"{part}: пресет не собрался: {bad[0]}")
            continue
        if not VST3.exists() or not config.SERUM_PYTHON.exists():
            out.append(f"{part}: пресет «{p['имя']}» не собран — на этой машине нет Serum или Python с pedalboard")
            continue
        base = unicodedata.normalize("NFC", p["основа"])
        job = {"base": str(root / base.partition("/")[2]), "knobs": p["ручки"], "name": p["имя"],
               "out": str(folder / label(part, p["имя"]))}
        try:
            got = subprocess.run([str(config.SERUM_PYTHON), "-m", "src.serum", "--make"], input=json.dumps(job),
                                 capture_output=True, text=True, timeout=WAIT, cwd=config.ROOT)
            row = json.loads(got.stdout.strip().splitlines()[-1])
            line = (f"собран и проверен: пик {row['peak']:.2f}, яркость {row['bright']} Гц, верха {row['air']:.1f}% "
                    f"(основа — {row['was']} Гц)"
                    + (f"; мастер пресета убавлен до {row['master']:.0%} — нота была громче {CALM[1]:g}" if row.get("master") else "")
                    + f" — файл «{label(part, p['имя'])}»") if row["ok"] else f"не собрался: {row['why']}"
        except (OSError, subprocess.SubprocessError, ValueError, LookupError, TypeError) as e:
            Path(job["out"]).unlink(missing_ok=True)
            line = f"не собрался: плагин не ответил ({type(e).__name__})"
        out.append(f"{part}: пресет «{p['имя']}» {line}")
    return out


# --- файл пресета: чанк состояния плагина и его обёртки ------------------------

def _dec(s: str) -> bytes:
    n, _, d = s.partition(".")
    out = bytearray()
    for i in range(0, len(d), 4):               # четыре знака — три байта
        out += sum(REV[c] << 6 * j for j, c in enumerate(d[i:i + 4])).to_bytes(3, "little")
    return bytes(out[:int(n)])


def _enc(b: bytes) -> str:
    out = []
    for i in range(0, len(b), 3):
        v = int.from_bytes(b[i:i + 3], "little")
        out.append("".join(ABC[v >> 6 * j & 63] for j in range(4)))
    return f"{len(b)}." + "".join(out)[:(len(b) * 8 + 5) // 6]


def pack(name: str, chunk: bytes) -> bytes:
    """Файл .fxp пресета Serum 1 из чанка состояния."""
    body = (b"FPCh" + struct.pack(">I", 1) + b"XfsX" + struct.pack(">II", 1, 1)
            + name.encode("ascii", "replace")[:27].ljust(28, b"\0") + struct.pack(">I", len(chunk)) + chunk)
    return b"CcnK" + struct.pack(">I", len(body)) + body


def unpack(data: bytes) -> tuple[str, bytes]:
    if data[:4] != b"CcnK" or data[8:12] != b"FPCh" or data[16:20] != b"XfsX":
        raise ValueError("не пресет Serum 1")
    n = struct.unpack(">I", data[56:60])[0]
    return data[28:56].split(b"\0")[0].decode("latin-1"), data[60:60 + n]


# --- плагин: только в процессе с pedalboard -----------------------------------

def _plugin():
    from pedalboard import load_plugin
    return load_plugin(str(VST3))


def load_fxp(p, path: str) -> None:
    xml = ('<?xml version="1.0" encoding="UTF-8"?> <VST3PluginState><IComponent>'
           + _enc(unpack(Path(path).read_bytes())[1]) + "</IComponent></VST3PluginState>").encode()
    p.raw_state = b"VC2!" + struct.pack("<I", len(xml)) + xml + b"\0"


def save_fxp(p, path: str, name: str) -> None:
    chunk = _dec(re.search(rb"<IComponent>(.*?)</IComponent>", p.raw_state).group(1).decode())
    Path(path).write_bytes(pack(name, chunk))


def sound(p):
    """Одна нота самим плагином: та же, которой промерена библиотека, — числа ложатся рядом с полем serum."""
    ev = [(bytes([0x90, NOTE, VEL]), 0.0), (bytes([0x80, NOTE, 0]), HOLD)]
    return p(ev, duration=LEN, sample_rate=SR, num_channels=2, buffer_size=512, reset=True)


def color(a) -> tuple[int, float]:
    """Яркость Гц и верха 6–16 кГц % по секунде, пока нота держится, — счёт `zamer.color` на numpy:
    те же окно 2048, шаг 512, срез 16 кГц и порог «звучит» (1/16 от 90-го процентиля)."""
    import numpy as np
    y = np.pad(a.mean(0)[:int(HOLD * SR)], 1024)
    idx = np.arange(2048)[None, :] + 512 * np.arange(1 + (len(y) - 2048) // 512)[:, None]
    spec = (np.abs(np.fft.rfft(y[idx] * (.5 - .5 * np.cos(2 * np.pi * np.arange(2048) / 2048)), axis=1)) ** 2).T
    f = np.fft.rfftfreq(2048, 1 / SR)
    spec, f = spec[f < 16000], f[f < 16000]
    e = spec.sum(0)
    on = e >= .0625 * np.percentile(e, 90)
    mag = np.sqrt(spec[:, on])
    return (round(float(np.median((f[:, None] * mag).sum(0) / (mag.sum(0) + 1e-12)))),
            round(float(100 * spec[f >= 6000][:, on].sum() / (spec[:, on].sum() + 1e-12)), 2))


def heard(p) -> tuple[float, int, float]:
    """Пик, яркость и верха ноты по трём запускам: случайная фаза двигает пик одного пресета на ±15%, яркость —
    до ±16% (`LD - Growly Saw`: 1369 и 1884 Гц подряд). Пик — худший из трёх, остальное — середина."""
    import numpy as np
    takes = [sound(p) for _ in range(TAKES)]
    peak = max(float(np.abs(a).max()) if np.isfinite(a).all() else float("inf") for a in takes)
    if not PEAK[0] <= peak < float("inf"):
        return peak, 0, 0.0
    tones = sorted(color(a) for a in takes)
    return peak, tones[TAKES // 2][0], sorted(t[1] for t in tones)[TAKES // 2]


def make(base: str, knobs: dict, out: str, name: str) -> dict:
    """Основа + ручки → .fxp и проверка: меряется не собранное, а записанный файл, открытый свежим плагином, —
    ручки в нём те же, нота не тишина и не перегруз."""
    p = _plugin()
    load_fxp(p, base)
    was = heard(p)[1]
    for k, v in knobs.items():
        p.parameters[k].raw_value = float(v)
    master = None
    for _ in range(QUIETER):                # громкость мастера — куб доли: «70% (-9.3 dB)»
        peak = heard(p)[0]
        if not CALM[1] < peak < float("inf"):
            break
        master = p.parameters["mastervol"].raw_value = p.parameters["mastervol"].raw_value * (CALM[0] / peak) ** (1 / 3)
    # Ручки хоста Serum применяет в обработке звука: без ноты между ручкой и записью файл выходит копией основы
    # (проба 06.10.2026) — последняя правка мастера иначе пропала бы
    sound(p)
    want = {k: (p.parameters[k].raw_value, p.parameters[k].string_value) for k in (*knobs, "mastervol")}
    save_fxp(p, out, name)
    q = _plugin()
    load_fxp(q, out)
    peak, bright, air = heard(q)
    # Ступенчатую ручку (голоса унисона) плагин при загрузке округляет: сверяем долю, а не сошлась — подпись плагина
    off = [k for k, (v, said) in want.items()
           if abs(q.parameters[k].raw_value - v) > .005 and q.parameters[k].string_value != said]
    why = ("в звуке не числа" if peak == float("inf") else
           f"тишина: пик ноты {peak:.3f}" if peak < PEAK[0] else
           f"перегруз: пик ноты {peak:.2f} и после убавленного мастера" if peak > PEAK[1] else
           f"записанный файл открылся с другими ручками: {', '.join(off)}" if off else "")
    if why:
        Path(out).unlink(missing_ok=True)
        return {"ok": False, "why": why}
    return {"ok": True, "peak": round(peak, 3), "bright": bright, "air": air, "was": was,
            "master": round(float(master), 3) if master else None}


def check() -> str:
    import os
    import tempfile
    x = os.urandom(1001)
    assert _dec(_enc(x)) == x and unpack(pack("check", x)) == ("check", x), "base64 JUCE или заголовок fxp"
    p = _plugin()
    p.parameters["fil_cutoff_hz"].raw_value, p.parameters["filter_on"].raw_value = .5, 1.0     # 425 Гц: не как у Init
    one = heard(p)
    assert one[0] >= PEAK[0], "тишина: Serum не звучит"
    with tempfile.TemporaryDirectory() as tmp:
        save_fxp(p, f"{tmp}/check.fxp", "check")
        q = _plugin()
        load_fxp(q, f"{tmp}/check.fxp")
    two = heard(q)
    assert q.parameters["filter_on"].raw_value == 1 and abs(q.parameters["fil_cutoff_hz"].raw_value - .5) < .005 \
        and abs(one[1] - two[1]) < .1 * one[1], f"fxp вернулся другим: {one} и {two}"
    return f"Serum {p.version}: звучит, fxp пишется и читается ({one[1]} и {two[1]} Гц, пик {two[0]:.2f})"


def knobs() -> str:
    """Подписи плагина на краях и в середине пределов каждой ручки — из них таблица раздела «Свой пресет» брифа."""
    p, out = _plugin(), []
    for k, (lo, hi) in KNOBS.items():
        said = []
        for v in ((lo, hi) if _switch(k) else (lo, lo + (hi - lo) / 4, (lo + hi) / 2, hi - (hi - lo) / 4, hi)):
            p.parameters[k].raw_value = v
            said.append(f"{v:g} — {p.parameters[k].string_value.strip()}")
        out.append(f"{k} ({p.parameters[k].label or ''}): " + "; ".join(said))
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description="Свой пресет Serum под бит: сборка и проверка самим плагином (только Мак)")
    ap.add_argument("--check", action="store_true", help="плагин грузится, звучит, .fxp пишется и читается обратно")
    ap.add_argument("--knobs", action="store_true", help="что значит доля каждой ручки, подписями плагина")
    ap.add_argument("--make", action="store_true", help="собрать и проверить пресет: задание JSON из stdin")
    a = ap.parse_args()
    if a.make:
        try:
            row = make(**json.loads(sys.stdin.read()))
        except Exception as e:              # битая основа, нет pedalboard, плагин не открылся — причина строкой
            row = {"ok": False, "why": f"{type(e).__name__}: {e}"[:200]}
        print(json.dumps(row, ensure_ascii=False))
    elif a.knobs:
        print(knobs())
    elif a.check:
        print(check())
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
