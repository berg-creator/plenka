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

Ручки — короткий список `KNOBS`, а не все 2397 параметров плагина (2048 из них — MIDI CC по каналам): срез верха,
огибающая громкости, расстройка, шум и встроенные эффекты — то, что можно писать, не видя основы, — и с 22.10.2026
то, что просят рецепты пресетов продюсеров (`data/private/биты/serum-разведка.md`, раздел 4): тип фильтра, warp,
октавы и полутоны, огибающие 2 и 3, LFO, сила слотов модуляции, макросы, Hyper/Dimension, компрессор, дилей,
фильтр эффектов. Что ручка сделала с этой основой, показывает замер до и после: он идёт в записку. Громкая нота
чинится сама — мастер пресета убавляется: автор нот исправить её не может, он узнал бы о ней только завтра.
Тишина не чинится — пресет не кладётся.

Режим (тип фильтра, warp, дисторшн, дилей, форма саба, компрессор) пишется именем — подписью самого плагина
(`MODES`, «fil_type»: «Peak 12»), а не долей: у фильтра 96 режимов на шкале 0..1, ступень — 0,0105, и доля,
посчитанная на глаз, попала бы в соседний. Имя Мак переводит в середину ступени, `--check` сверяет каждое имя
подписью плагина. Ступени с числом — долей: октава −4..+4 — (октавы + 4) / 8, полутон −12..+12 — (полутоны + 12) / 24;
+22 полутона у B — b_octave_oct 0.75 и b_semi_semitones 10/24. Подписи слов рецептов в Serum 1: «Peak» — Peak 12 или
Peak 24, «S&H» — SampHold или SampHold-, «Bend» — Bend +, Bend - или Bend +/-, «FM (from Sub)» — FM (Sub), у B
вместо «FM (from B)» — FM (from A), «ping-pong» — Ping-Pong; Allpasses, Combs, Reverb, Ring Mod, Low 24, PWM, Sync,
Quantize, FM (from B), Zero-Square, Downsample — так и подписаны. У PWM сила warp перевёрнута: a_warp 0 — 100%.

Сила модуляции — только сила: env2/env3, LFO (rate, rise, delay, smooth) и mod_N_amt (−100..+100, 0.5 — ноль)
меняют то, что основа уже куда-то ведёт; проводку «откуда → куда» параметры не ставят, и без неё ручка молчит.
lfo*_rate в режиме BPM — ступени: 0.25 — 4 такта, 0.3 — 2, 0.4 — такт, 0.5 — 1/4; у основы со свободным LFO — герцы.
Дилей звучит только с dly_enable 1 (dly_wet по умолчанию 30%). hyp_enable один на Hyper и Dimension: включённый,
он заводит и Hyper с его hyp_wet (по умолчанию 50%) — для одного Dimension hyp_wet 0. Нет среди параметров: режима
ревера (Hall/Plate), Mono/Legato портаменто (есть только его время, porttime_ms), выбора шума и таблицы волн.

Отвергнуто: .vstpreset — браузер Serum его не показывает. Отвергнуто: таблица волн с нуля и проводка модуляций —
через параметры плагина они не ставятся, а чанк пресета не разобран. Отвергнуто: сверять записанный файл
с собранным по яркости — у пресета со случайной фазой она гуляет от запуска к запуску на 16%; сверяются ручки.
Отвергнуто: класть в репозиторий сами пресеты и таблицы — они чужие и платные.

Таблица волн из живого звука (`--table`, 22.10.2026; владелец 21.10.2026: «делать свои уникальные звуки» из живых записей
из сети). Способ — тот же, которым 02.10.2026 собраны таблицы Tables/PLENKA из голоса владельца: кода тогда в репозиторий
не положили, он восстановлен по README той папки и по самим файлам и сверен с ними — из тех же записей голоса кадры
совпали с шестью таблицами PLENKA по косинусу в среднем на 0,92–0,99. Звонкий участок по pyin, период уточнён поиском
(шаг pyin — 10 центов, у яркого тона это разводит соседние периоды), период с переходом в предыдущий, 2048 отсчётов,
основная гармоника с нуля на подъёме, пик 0,98; рвут кусок тихое, непериодичное и кадр, резко не похожий на соседа.
Таблица кладётся в Serum файлом, а в пресет её снаружи не вписать — чанк пресета не разобран: владелец выбирает её
в осцилляторе кликом. Отказ — строкой: короткий звонкий кусок, рваная таблица и почти синус (свисток, звонок — у них
узнаваемы удар и спад, а не период, и такой кадр в Serum уже есть). На слух таблицу не проверяет никто.

    python -m src.serum --check     плагин грузится, звучит, .fxp пишется и читается обратно, Audio Unit берёт пресет
                                    из состояния, которое сборка кладёт в проект FL (нужен SERUM_PYTHON)
    python -m src.serum --knobs     что значит доля каждой ручки: подписи самого плагина (нужен SERUM_PYTHON)
    python -m src.serum --make      собрать и проверить один пресет: задание JSON из stdin, итог — строкой JSON
    ~/.cache/whisper-venv/bin/python -m src.serum --table ЗВУК… [--out ПАПКА]   звук → таблица волн (Tables/PLENKA Live)
    ~/.cache/whisper-venv/bin/python -m src.serum --selftest   таблица на синтетике: без сети и без Serum

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
AU = Path("/Library/Audio/Plug-Ins/Components/Serum.component")    # им Serum стоит в проекте FL
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
    "filter_on": (0, 1), "fil_cutoff_hz": (.4, 1), "fil_reso": (0, 1), "fil_driv": (0, 1),
    "fil_var": (0, 1), "fil_mix": (0, 1),
    "env1_atk_ms": (0, .5), "env1_dec_s": (0, 1), "env1_sus_db": (0, 1), "env1_rel_ms": (0, .6),
    "a_unison": (0, .4), "a_unidet": (0, 1), "a_fine_cents": (.4, .6), "a_wtpos": (0, 1),
    "osc_b_on": (0, 1), "b_vol": (0, .85), "b_fine_cents": (.4, .6),
    "osc_n_on": (0, 1), "noise_level": (0, .6), "osc_s_on": (0, 1), "sub_osc_level": (0, .85),
    "dist_enable": (0, 1), "dist_drv": (0, .8), "dist_wet": (0, 1),
    "cho_enable": (0, 1), "cho_wet": (0, 1),
    "rev_enable": (0, 1), "verb_wet": (0, .6), "verbsize": (0, 1),
    "eq_enable": (0, 1), "eq_typh": (0, 1), "eq_frqh_hz": (.5, 1), "eq_volh_db": (0, 1),
    # с 22.10.2026 — для рецептов разведки; режимы этих же блоков — в MODES
    "a_warp": (0, 1), "b_warp": (0, 1), "a_octave_oct": (0, 1), "a_semi_semitones": (0, 1),
    "b_octave_oct": (0, 1), "b_semi_semitones": (0, 1), "suboscoctave_oct": (0, 1), "porttime_ms": (0, .75),
    "hyp_enable": (0, 1), "hyp_wet": (0, 1), "hypdim_size": (0, 1), "hypdim_mix": (0, 1),
    "comp_enable": (0, 1), "comp_wet": (0, 1), "dly_enable": (0, 1), "dly_wet": (0, .6),
    "fx_fil_enable": (0, 1), "fx_fil_freq_hz": (0, 1), "fx_fil_reso": (0, 1), "fx_fil_wet": (0, 1),
    **{f"env{n}_{k}": (0, 1) for n in (2, 3) for k in ("atk_ms", "dec_s", "sus", "rel_ms")},
    **{f"lfo{n}_{k}": (0, 1) for n in range(1, 9) for k in ("rate", "rise", "delay", "smooth")},
    **{(f"mod_{n}_amt" if n < 10 else f"mod{n}_amt"): (0, 1) for n in range(1, 33)},     # так их зовёт плагин
    **{f"macro_{n}": (0, 1) for n in range(1, 5)},
}
FILTERS = ("MG Low 6, MG Low 12, MG Low 18, MG Low 24, Low 6, Low 12, Low 18, Low 24, High 6, High 12, High 18, "
           "High 24, Band 12, Band 24, Peak 12, Peak 24, Notch 12, Notch 24, LH 6, LH 12, LB 12, LP 12, LN 12, HB 12, "
           "HP 12, HN 12, BP 12, BN 12, PP 12, PN 12, NN 12, L/B/H 12, L/B/H 24, L/P/H 12, L/P/H 24, L/N/H 12, "
           "L/N/H 24, B/P/N 12, B/P/N 24, Cmb +, Cmb -, Cmb L6+, Cmb L6-, Cmb H6+, Cmb H6-, Cmb HL6+, Cmb HL6-, Flg +, "
           "Flg -, Flg L6+, Flg L6-, Flg H6+, Flg H6-, Flg HL6+, Flg HL6-, Phs 12+, Phs 12-, Phs 24+, Phs 24-, Phs 36+, "
           "Phs 36-, Phs 48+, Phs 48-, Phs 48L6+, Phs 48L6-, Phs 48H6+, Phs 48H6-, Phs 48HL6+, Phs 48HL6-, FPhs 12HL6+, "
           "FPhs 12HL6-, Low EQ 6, Low EQ 12, Band EQ 12, High EQ 6, High EQ 12, Ring Mod, Ring Modx2, SampHold, "
           "SampHold-, Combs, Allpasses, Reverb, French LP, German LP, Add Bass, Formant-I, Formant-II, Formant-III, "
           "Bandreject, Dist.Comb 1 LP, Dist.Comb 1 BP, Dist.Comb 2 LP, Dist.Comb 2 BP, Scream LP, Scream BP").split(", ")
WARPS = ("Off, Sync, Sync 1/2 Win., Sync Window, Bend +, Bend -, Bend +/-, PWM, Asym +, Asym -, Asym +/-, Flip, Mirror, "
         "Remap 1, Remap 2, Remap 3, Remap 4, Quantize, FM (from {0}), AM (from {0}), RM (from {0}), FM (Noise), FM (Sub)")
DISTS = ("Tube, SoftClip, HardClip, Diode 1, Diode 2, Lin.Fold, Sin Fold, Zero-Square, Downsample, Asym, Rectify, "
         "X-Shaper, X-Shaper (Asym), Sine Shaper, Stomp Box, Tape Sat.").split(", ")
# Режим → имя подписью плагина → доля середины его ступени (снято 22.10.2026 проходом шкалы с шагом 0,0005;
# `--check` сверяет каждое имя). У warp 23 режима на 24 ступенях: выше 0,978 подпись плагина — мусор.
MODES = {k: {n: i / d for i, n in enumerate(names)} for k, names, d in (
    ("fil_type", FILTERS, 95), ("fx_fil_type", FILTERS, 95),
    ("warposca", WARPS.format("B").split(", "), 23), ("warposcb", WARPS.format("A").split(", "), 23),
    ("dist_mode", DISTS, 15), ("dly_mode", ("Normal", "Ping-Pong", "Tap->Delay"), 2),
    ("suboscshape", ("Sine", "RoundRect", "Triangle", "Saw", "Square", "Pulse"), 5),
    ("cmpmbnd", ("Normal", "MultBand"), 1))}


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
            if k in MODES:
                if not isinstance(v, str) or v not in MODES[k]:
                    near = [n for n in MODES[k] if str(v).strip().lower() in n.lower()][:4]
                    out.append(f"preset, {part}: {k} = {v!r} — режим пишется именем подписи плагина, такого нет"
                               + (f"; похожие: {', '.join(near)}" if near else f"; имена — serum.MODES[«{k}»]"))
            elif k not in KNOBS:
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
        p.parameters[k].raw_value = MODES[k][v] if k in MODES else float(v)
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
    wrong = []
    for k, names in MODES.items():          # каждое имя режима — подпись плагина на своей доле
        was = p.parameters[k].raw_value
        for n, v in names.items():
            p.parameters[k].raw_value = v
            if p.parameters[k].string_value.strip() != n:
                wrong.append(f"{k} «{n}» ({p.parameters[k].string_value.strip()})")
        p.parameters[k].raw_value = was
    assert not wrong, f"подписи плагина разошлись с serum.MODES: {', '.join(wrong[:5])}"
    p.parameters["fil_cutoff_hz"].raw_value, p.parameters["filter_on"].raw_value = .5, 1.0     # 425 Гц: не как у Init
    # новая ручка и режим: резонанс выше прежнего предела 0.6 и тип фильтра именем
    p.parameters["fil_reso"].raw_value, p.parameters["fil_type"].raw_value = .9, MODES["fil_type"]["Peak 12"]
    one = heard(p)
    assert one[0] >= PEAK[0], "тишина: Serum не звучит"
    with tempfile.TemporaryDirectory() as tmp:
        save_fxp(p, f"{tmp}/check.fxp", "check")
        q = _plugin()
        load_fxp(q, f"{tmp}/check.fxp")
        # Проект FL держит Serum как Audio Unit, а тот пресет с длиной «весь файл» (так пишет библиотека) молча
        # не берёт: 10.10.2026 четыре канала «Ржавчины» открылись с Init. Грузим в него то, что кладёт сборка проекта.
        from pedalboard import load_plugin
        from . import flp
        raw = Path(f"{tmp}/check.fxp").read_bytes()
        Path(f"{tmp}/lib.fxp").write_bytes(raw[:4] + struct.pack(">I", len(raw)) + raw[8:])
        a = load_plugin(str(AU))
        init = [v.raw_value for v in a.parameters.values()]
        a.raw_state = flp.au_state(Path(f"{tmp}/lib.fxp"))
        assert [v.raw_value for v in a.parameters.values()] != init, "Audio Unit не взял пресет из состояния проекта FL"
    two = heard(q)
    assert q.parameters["filter_on"].raw_value == 1 and abs(q.parameters["fil_cutoff_hz"].raw_value - .5) < .005 \
        and abs(one[1] - two[1]) < .1 * one[1], f"fxp вернулся другим: {one} и {two}"
    kind = q.parameters["fil_type"].string_value.strip()
    assert kind == "Peak 12" and abs(q.parameters["fil_reso"].raw_value - .9) < .005, f"fxp вернул fil_type «{kind}»"
    return (f"Serum {p.version}: звучит, fxp пишется и читается ({one[1]} и {two[1]} Гц, пик {two[0]:.2f}; fil_type "
            f"читается подписью «{kind}», fil_reso 0.9), {sum(map(len, MODES.values()))} имён режимов сверены подписями "
            "плагина, Audio Unit берёт пресет из состояния проекта FL")


def knobs() -> str:
    """Подписи плагина на краях и в середине пределов каждой ручки — из них таблица раздела «Свой пресет» брифа."""
    p = _plugin()
    for k in ("warposca", "warposcb"):      # без режима warp сила подписана «no Warp type»
        p.parameters[k].raw_value = MODES[k]["Bend +"]
    out = [f"{k} (режим, пишется именем): " + ", ".join(names) for k, names in MODES.items()]
    for k, (lo, hi) in KNOBS.items():
        said = []
        for v in ((lo, hi) if _switch(k) else (lo, lo + (hi - lo) / 4, (lo + hi) / 2, hi - (hi - lo) / 4, hi)):
            p.parameters[k].raw_value = v
            # подписи силы warp, rise и delay LFO плагин обновляет только в обработке звука
            p([], duration=.02, sample_rate=SR, num_channels=2, buffer_size=512, reset=False)
            said.append(f"{v:g} — {p.parameters[k].string_value.strip()}")
        out.append(f"{k} ({p.parameters[k].label or ''}): " + "; ".join(said))
    return "\n".join(out)


# --- таблица волн из живого звука (`--table`) ------------------------------------
# Способ тот же, что у Tables/PLENKA из голоса владельца (02.10.2026; кода в репозитории не было — восстановлен по README
# той папки и по самим файлам): звонкий участок по pyin режется на периоды, период с переходом в предыдущий (шов без
# щелчка) приводится к FRAME отсчётам, без постоянной составляющей, основная гармоника начинается с нуля на подъёме,
# пик кадра PEAK_TABLE. Тихое и непериодичное не берётся, из годного — самый длинный кусок подряд; кадры идут по времени.
TABLES = Path("/Library/Audio/Presets/Xfer Records/Serum Presets/Tables")
FRAME, FRAMES = 2048, (64, 32)      # отсчётов в кадре и кадров в таблице, как у PLENKA; годных периодов меньше 32 — таблицы нет
PEAK_TABLE = .98
LOUD = .1                           # RMS ниже этой доли от громчайшего окна — хвост, пауза, смычка
PERIODIC = .8                       # похожесть периода на следующий за ним: ниже — шум, а не тон
JUMP = .7                           # похожесть кадра на соседа ниже — кусок рвётся. ponytail: оценка по README PLENKA (худшая
                                    # соседняя пара там 0,761), не опыт; порог исходного кода не записан
CAP = 4000                          # кадров на кусок при поиске: длиннее — с шагом в несколько периодов
SIMILAR = .8                        # средняя похожесть соседних кадров таблицы: ниже — рваная, не кладётся (README PLENKA)
SINE = .95                          # доля основной гармоники в кадрах: выше — почти синус, такой в Serum уже есть (свисток, звонок)
PITCH = (60.0, 4000.0)              # где pyin ищет основной тон, Гц: от низкого гула до свиста чайника
TAPS = 16                           # полуокно sinc: дробные отсчёты без среза верха у свиста в 3 кГц (15 отсчётов на период)
JUNK = b"JUNK" + struct.pack("<I", 28) + bytes(28)      # как у заводских таблиц и PLENKA
CLM = b"<!>2048 10000000 wavetable (PLENKA)"           # 2048 в кадре, переход между кадрами линейный


def _at(y, pos):
    """Отсчёты y в дробных местах pos — окном sinc: линейная середина между отсчётами срезала бы верх у высокого тона."""
    import numpy as np
    k = np.arange(1 - TAPS, TAPS + 1)
    i = np.floor(pos).astype(int)[:, None] + k
    d = pos[:, None] - i
    return (y[np.clip(i, 0, len(y) - 1)] * np.sinc(d) * (.5 + .5 * np.cos(np.pi * d / TAPS))).sum(1)


def _cos(a, b) -> float:
    import numpy as np
    return float((a * b).sum() / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))


def _period(y, t: float, P: float) -> tuple[float, float]:
    """Период точнее pyin и его похожесть на следующий. У pyin шаг высоты — 10 центов: у яркого тона (сигнал будильника,
    гармоники до двадцатой) период на 1% мимо разводит соседние периоды, и звук выглядел бы шумом. Поиск ±3%, потом ±0,5%."""
    import numpy as np
    u = np.arange(256) / 256
    for span in (.03, .005):
        best = max(P * (1 + np.linspace(-span, span, 13)), key=lambda q: _cos(_at(y, t + u * q), _at(y, t + q + u * q)))
        P = float(best)
    return P, _cos(_at(y, t + u * P), _at(y, t + P + u * P))


def _frame(y, t: float, P: float, ref=None):
    """Период с t длиной P (отсчёты, дробные) → кадр. Переход: к концу периода вес уходит в период перед ним, и конец
    кадра встаёт ровно перед его началом — шва нет. Кадр начинается с нуля основной гармоники на подъёме, как у PLENKA;
    с `ref` — сдвинут по кругу туда, где больше всего похож на предыдущий: так спасается кадр, который по основной
    гармонике перевернулся (у гудка из нескольких тонов её фаза скачет от периода к периоду)."""
    import numpy as np
    u = np.arange(FRAME) / FRAME
    c = (1 - u) * _at(y, t + u * P) + u * _at(y, t + u * P - P)
    X = np.fft.rfft(c - c.mean())
    X[0] = 0
    k = np.arange(len(X))
    if ref is None:
        X *= np.exp(1j * k * (-np.pi / 2 - np.angle(X[1])))                 # основная гармоника — синус с нуля
    else:
        X *= np.exp(-2j * np.pi * k * np.argmax(np.fft.irfft(np.fft.rfft(ref) * np.conj(X), FRAME)) / FRAME)
    c = np.fft.irfft(X, FRAME)
    return c * PEAK_TABLE / (np.abs(c).max() + 1e-12)


def wavetable(y, sr: int) -> tuple:
    """Звук (моно, float) → кадры таблицы и замер. ValueError с причиной — таблицы из этого звука нет."""
    import librosa
    import numpy as np
    hop = 256
    f0, voiced, _ = librosa.pyin(y, fmin=PITCH[0], fmax=PITCH[1], sr=sr, frame_length=2048, hop_length=hop)
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=hop)[0][:len(f0)]
    good = voiced & (rms > LOUD * rms.max()) & np.isfinite(f0)
    if not good.any():
        raise ValueError("высоты нет: pyin не слышит тона в громких местах")
    runs, t, cur = [], 0.0, []          # периоды подряд: место и длина; тихий или непериодичный рвёт кусок
    while True:
        i = min(int(t / hop + .5), len(f0) - 1)
        P = sr / f0[i] if good[i] else hop
        if t + 2 * P + TAPS >= len(y):
            break
        ok = good[i] and t >= P + TAPS
        if ok:
            P, same = _period(y, t, P)
            ok = same >= PERIODIC and t + 2 * P + TAPS < len(y)
        if ok:
            cur.append((t, P))
        elif cur:
            runs, cur = runs + [cur], []
        t += P
    # Кадр, резко не похожий на соседа, тоже рвёт кусок: у двутонального гудка фаза основной гармоники прыгает,
    # и кадр выходит перевёрнутым. Кадров не больше CAP — у свиста в 3 кГц периодов девять тысяч за три секунды
    pieces = []
    for run in runs + [cur]:
        run, frames, start = run[::-(-len(run) // CAP) or 1], [], 0
        for k, (t, P) in enumerate(run):
            frames.append(_frame(y, t, P))
            if k > start and _cos(frames[-2], frames[-1]) < JUMP:
                frames[-1] = _frame(y, t, P, frames[-2])
                if _cos(frames[-2], frames[-1]) < JUMP:
                    pieces.append((run[start:k], frames[start:k]))
                    start, frames[-1] = k, _frame(y, t, P)
        pieces.append((run[start:], frames[start:]))
    best, frames = max(pieces, key=lambda p: len(p[0]), default=([], []))
    n = next((n for n in FRAMES if len(best) >= n), 0)
    if not n:
        raise ValueError(f"звонкий кусок короткий: {len(best)} периодов подряд, нужно {FRAMES[-1]}")
    idx = [int(round(k)) for k in np.linspace(0, len(best) - 1, n)]
    pick, frames = [best[k] for k in idx], np.stack([frames[k] for k in idx])
    near = [_cos(a, b) for a, b in zip(frames, frames[1:])]
    fund = np.abs(np.fft.rfft(frames, axis=1)) ** 2
    info = {"frames": n, "similar": round(float(np.mean(near)), 3), "worst": round(float(min(near)), 3),
            "from": round(pick[0][0] / sr, 3), "to": round((pick[-1][0] + pick[-1][1]) / sr, 3),
            "hz": round(float(np.median([sr / P for _, P in pick]))), "sine": round(float((fund[:, 1] / fund[:, 1:].sum(1)).mean()), 2)}
    if info["similar"] < SIMILAR:
        raise ValueError(f"таблица рваная: похожесть соседних кадров {info['similar']} — ниже {SIMILAR}")
    if info["sine"] >= SINE:
        raise ValueError(f"почти синус: основная гармоника — {info['sine']:.0%} кадра, такой в Serum уже есть")
    return frames, info


def write_table(path: Path, frames) -> None:
    """Таблица — WAV 44100 Гц, 32 бит float, моно, с чанком clm: так их читает Serum (сверено с заводскими и PLENKA)."""
    data = frames.astype("<f4").tobytes()
    clm = CLM.ljust(48)
    body = (JUNK + b"fmt " + struct.pack("<IHHIIHH", 16, 3, 1, SR, SR * 4, 4, 32) + b"clm " + struct.pack("<I", len(clm))
            + clm + b"data" + struct.pack("<I", len(data)) + data)
    path.write_bytes(b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WAVE" + body)


def read_table(path: Path) -> tuple:
    """Таблица → (строка clm, кадры). Обратная сторона `write_table` — ею селфтест и сверка готового файла."""
    import numpy as np
    raw, at, clm, frames = path.read_bytes(), 12, "", None
    fmt = None
    while at + 8 <= len(raw):
        cid, n = raw[at:at + 4], struct.unpack("<I", raw[at + 4:at + 8])[0]
        chunk = raw[at + 8:at + 8 + n]
        if cid == b"fmt ":
            fmt = struct.unpack("<HHIIHH", chunk[:16])
        elif cid == b"clm ":
            clm = chunk.decode("ascii", "replace").strip()
        elif cid == b"data":
            frames = np.frombuffer(chunk, "<f4")
        at += 8 + n + (n & 1)
    assert fmt == (3, 1, SR, SR * 4, 4, 32) and frames is not None and len(frames) % FRAME == 0, f"не таблица Serum: {fmt}"
    return clm, frames.reshape(-1, FRAME)


def table(src: Path, out: Path) -> dict:
    """Один звук → одна таблица в out. Итог — замер: кадров, похожесть соседних (средняя и худшая), секунды звука,
    тон Гц и доля основной гармоники (1 — чистый синус)."""
    import librosa
    y, sr = librosa.load(str(src), sr=None, mono=True)
    frames, info = wavetable(y, sr)
    write_table(out, frames)
    clm, back = read_table(out)
    assert clm.startswith("<!>2048") and back.shape == frames.shape
    return info


def table_selftest() -> str:
    """Без сети и без Serum: синтетика. Тон с меняющимся тембром и плавающей высотой даёт таблицу, которая читается
    обратно тем же форматом, что PLENKA; шум, тишина и чистый синус таблицы не дают; кадр — без шва, без постоянной составляющей,
    основная гармоника с нуля на подъёме."""
    import tempfile
    import numpy as np
    sr, sec = 44100, 1.5
    t = np.arange(int(sr * sec)) / sr
    hz = 440 * 2 ** (.3 * t / sec / 12)                     # плывёт на треть полутона, как свист, который набирает силу
    ph = 2 * np.pi * np.cumsum(hz) / sr
    y = .6 * np.sin(ph) + .3 * (t / sec) * np.sin(3 * ph + .7) + .1 * np.sin(5 * ph) + .2
    frames, info = wavetable(y.astype("float32"), sr)
    assert info["frames"] == 64 and info["similar"] >= .95 and 430 <= info["hz"] <= 450, info
    assert np.allclose(np.abs(frames).max(1), PEAK_TABLE, atol=1e-3) and np.abs(frames.mean(1)).max() < 1e-3, "пик и ноль"
    X = np.fft.rfft(frames, axis=1)
    assert np.allclose(np.angle(X[:, 1]), -np.pi / 2, atol=1e-3), "фаза основной гармоники"
    seam = np.abs(frames[:, 0] - frames[:, -1]).max()
    assert seam < .05, f"шов кадра {seam}"
    third = np.abs(X[:, 3]) / np.abs(X[:, 1])
    assert third[-1] > third[0] * 2, "кадры идут по времени звука: тембр растёт к концу"
    for bad, why in ((np.random.default_rng(1).normal(0, .3, sr).astype("float32"), "шум"),
                     (np.zeros(sr, "float32"), "тишина"), (.5 * np.sin(ph[:sr]).astype("float32"), "синус")):
        try:
            wavetable(bad, sr)
            raise AssertionError(f"{why} дал таблицу")
        except ValueError:
            pass
    with tempfile.TemporaryDirectory() as tmp:
        write_table(Path(tmp) / "t.wav", frames)
        raw = (Path(tmp) / "t.wav").read_bytes()
        clm, back = read_table(Path(tmp) / "t.wav")
        assert raw[12:20] == b"JUNK\x1c\x00\x00\x00" and clm == CLM.decode() and np.array_equal(back, frames.astype("<f4"))
        assert len(raw) == 12 + 36 + 24 + 56 + 8 + 64 * FRAME * 4, "длина файла как у таблицы PLENKA на 64 кадра"
    return f"таблица волн: {info['frames']} кадров, похожесть {info['similar']}, шум, тишина и синус — отказ, формат читается обратно"


def main() -> None:
    ap = argparse.ArgumentParser(description="Свой пресет Serum под бит: сборка и проверка самим плагином (только Мак)")
    ap.add_argument("--check", action="store_true", help="плагин грузится, звучит, .fxp пишется и читается обратно")
    ap.add_argument("--knobs", action="store_true", help="что значит доля каждой ручки, подписями плагина")
    ap.add_argument("--make", action="store_true", help="собрать и проверить пресет: задание JSON из stdin")
    ap.add_argument("--table", nargs="+", type=Path, metavar="ЗВУК", help="звук → таблица волн Serum, как у Tables/PLENKA (нужен Python с librosa)")
    ap.add_argument("--out", type=Path, help="с --table: папка таблиц (по умолчанию Tables/PLENKA Live)")
    ap.add_argument("--selftest", action="store_true", help="таблица волн на синтетике: без сети и без Serum")
    a = ap.parse_args()
    if a.selftest:
        print(table_selftest())
    elif a.table:
        out = a.out or TABLES / "PLENKA Live"
        out.mkdir(parents=True, exist_ok=True)
        for src in a.table:
            dst = out / f"{src.stem}.wav"
            try:
                print(json.dumps({"file": dst.name} | table(src, dst), ensure_ascii=False))
            except ValueError as e:
                print(json.dumps({"file": dst.name, "why": str(e)}, ensure_ascii=False))
    elif a.make:
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
