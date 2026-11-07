"""ГЕНЕРАТОР БИТОВ без Мака и FL: текст («trap 140 dark») → бит-JSON → звук.

Весь путь — на numpy/scipy, поэтому работает где угодно: на ВМ, в GitHub Actions,
в дежурстве бота. Ни FL Studio, ни плагинов, ни хранилища на Маке не нужно.

Как устроено:
  1. parse()    — разбор запроса словами: жанр, темп, тональность, вайб.
  2. generate() — бит-JSON: секции, ноты и удары каждой дорожки, звук и микшер.
                  Всё решает seed: тот же запрос и seed — тот же бит до байта,
                  «ещё вариант» — новый seed.
  3. render()   — синтез звуков (бочка, 808, снейр, хэты, колокол, пэд…),
                  раскладка по нотам, шины с эквалайзером, сайдчейном, ревером и
                  дилеем, мастер с лимитером и громкостью по LUFS.
  Бит-JSON — единственная истина: его же потом правит мини-приложение,
  а движок рендерит заново (--render).

Петли из сети (src/sources/freesound.py, только CC0 и CC-BY) встают вместо
синтезированной мелодии, если в библиотеке есть подходящая; автор и лицензия —
в credits.txt рядом с битом.

    python -m src.bitgen "trap 140 dark" --out out/        бит целиком: beat.mp3, beat.wav, beat.json
    python -m src.bitgen "drill фа минор" --seed 7 --short  превью ~30 с (вступление и хук)
    python -m src.bitgen "boom bap 90 chill" --stems        плюс дорожки отдельными wav
    python -m src.bitgen --render out/beat.json --out out2/  отрендерить правленый бит-JSON
    python -m src.bitgen --selftest                          разбор, детерминизм, рендер всех жанров — без сети
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from scipy import signal
from scipy.ndimage import maximum_filter1d, minimum_filter1d, uniform_filter1d

SR = 44100
VERSION = 1

# ─────────────────────────── разбор запроса ───────────────────────────

STYLES = {
    "trap": ("trap", "трэп", "треп", "трап"),
    "drill": ("drill", "дрилл", "дрил"),
    "boombap": ("boom bap", "boombap", "boom-bap", "бум бэп", "бумбэп", "бум-бэп", "олдскул", "oldschool"),
    "phonk": ("phonk", "фонк"),
}
VIBES = {
    "dark": ("dark", "тёмн", "темн", "мрачн", "злове", "жутк", "horror"),
    "sad": ("sad", "груст", "печал", "melanch", "меланх", "лирич", "emo"),
    "aggressive": ("aggress", "агресс", "жёстк", "жестк", "hard", "зл", "rage"),
    "chill": ("chill", "спокой", "чил", "мягк", "lofi", "lo-fi", "лоуфай", "лофай", "relax"),
}
STYLE_BPM = {"trap": (132, 150), "drill": (140, 146), "boombap": (86, 94), "phonk": (128, 145)}
STYLE_VIBE = {"trap": "dark", "drill": "dark", "boombap": "chill", "phonk": "aggressive"}
NOTE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11, "H": 11}
RU_NOTE = {"до": 0, "ре": 2, "ми": 4, "фа": 5, "соль": 7, "ля": 9, "си": 11}
NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def parse(text: str) -> dict:
    """Запрос словами → {style, bpm, key, minor, vibe}; чего нет в тексте — None."""
    low = text.lower()
    out = {"style": None, "bpm": None, "key": None, "minor": None, "vibe": None}
    for style, words in STYLES.items():
        if any(w in low for w in words):
            out["style"] = style
            break
    for vibe, words in VIBES.items():
        if any(re.search(r"(?<![а-яёa-z])" + re.escape(w), low) for w in words):
            out["vibe"] = vibe
            break
    for m in re.finditer(r"(?<!\d)(\d{2,3})(?!\d)", low):
        n = int(m.group(1))
        if 60 <= n <= 200:
            out["bpm"] = n
            break
    # Тональность латиницей: «Fm», «F#m», «Bb minor», «A major». Буква — заглавная,
    # чтобы «a» и «b» внутри слов не становились нотами.
    m = re.search(r"(?<![A-Za-z])([A-GH])(#|♯|b|♭)?\s*(m(?:in(?:or)?)?|maj(?:or)?|минор|мажор)?(?![A-Za-z])", text)
    if m and (m.group(2) or m.group(3) or re.search(r"\b(key|тональн)", low)):
        pc = NOTE[m.group(1)] + (1 if m.group(2) in ("#", "♯") else -1 if m.group(2) in ("b", "♭") else 0)
        out["key"] = NAMES[pc % 12]
        q = (m.group(3) or "m").lower()
        out["minor"] = not q.startswith(("maj", "мажор"))
    m = re.search(r"\b(до|ре|ми|фа|соль|ля|си)[\s-]*(диез|бемоль)?\s*(минор|мажор)", low)
    if m:
        pc = RU_NOTE[m.group(1)] + (1 if m.group(2) == "диез" else -1 if m.group(2) == "бемоль" else 0)
        out["key"] = NAMES[pc % 12]
        out["minor"] = m.group(3) == "минор"
    return out


# ─────────────────────────── генерация бит-JSON ───────────────────────────

SCALES = {
    "minor": [0, 2, 3, 5, 7, 8, 10],
    "harmonic": [0, 2, 3, 5, 7, 8, 11],
    "phrygian": [0, 1, 3, 5, 7, 8, 10],
    "dorian": [0, 2, 3, 5, 7, 9, 10],
    "major": [0, 2, 4, 5, 7, 9, 11],
}
# Прогрессии — ступени лада (0 — тоника), по аккорду на такт, петля в 4 такта.
PROGRESSIONS = {
    "dark": [[0, 0, 5, 4], [0, 5, 2, 6], [0, 1, 0, 5], [0, 5, 0, 4]],
    "sad": [[0, 5, 2, 6], [5, 6, 0, 0], [0, 3, 5, 4], [0, 2, 5, 6]],
    "aggressive": [[0, 0, 1, 0], [0, 6, 5, 6], [0, 0, 5, 1]],
    "chill": [[0, 3, 6, 2], [1, 4, 0, 5], [0, 5, 3, 4]],
}
MELODY_SOUND = {
    ("trap", "dark"): "bell", ("trap", "sad"): "keys", ("trap", "aggressive"): "pluck", ("trap", "chill"): "keys",
    ("drill", "dark"): "strings", ("drill", "sad"): "keys", ("drill", "aggressive"): "pluck", ("drill", "chill"): "bell",
    ("boombap", "dark"): "keys", ("boombap", "sad"): "keys", ("boombap", "aggressive"): "pluck", ("boombap", "chill"): "keys",
    ("phonk", "dark"): "cowbell", ("phonk", "sad"): "cowbell", ("phonk", "aggressive"): "cowbell", ("phonk", "chill"): "bell",
}
# Микшер по ролям: громкость дБ, панорама, срез низа и верха, посылы, сайдчейн от бочки.
MIX = {
    "kick":   dict(gain=-3, pan=0.0, hp=0, lp=0, rev=0.0, dly=0.0, duck=0.0),
    "snare":  dict(gain=-9, pan=0.0, hp=120, lp=0, rev=0.14, dly=0.0, duck=0.0),
    "clap":   dict(gain=-12, pan=0.0, hp=300, lp=0, rev=0.22, dly=0.0, duck=0.0),
    "hat":    dict(gain=-21, pan=0.12, hp=6000, lp=0, rev=0.04, dly=0.0, duck=0.0),
    "ohat":   dict(gain=-23, pan=-0.18, hp=5000, lp=0, rev=0.08, dly=0.0, duck=0.0),
    "perc":   dict(gain=-20, pan=-0.3, hp=400, lp=0, rev=0.2, dly=0.1, duck=0.0),
    "808":    dict(gain=-4, pan=0.0, hp=25, lp=5000, rev=0.0, dly=0.0, duck=0.35),
    "melody": dict(gain=-15, pan=0.0, hp=220, lp=0, rev=0.24, dly=0.18, duck=0.25),
    "pad":    dict(gain=-23, pan=0.0, hp=250, lp=3500, rev=0.3, dly=0.0, duck=0.3),
    "fx":     dict(gain=-17, pan=0.0, hp=60, lp=0, rev=0.35, dly=0.0, duck=0.0),
    "vinyl":  dict(gain=-30, pan=0.0, hp=300, lp=8000, rev=0.0, dly=0.0, duck=0.0),
}
ARRANGEMENT = [("intro", 4), ("hook", 8), ("verse", 16), ("hook", 8), ("verse", 16), ("hook", 8), ("outro", 4)]
SHORT = [("intro", 4), ("hook", 8)]
# Кто звучит в какой секции.
ROLES = {
    "intro": {"melody", "pad", "fx", "vinyl"},
    "hook": {"kick", "snare", "clap", "hat", "ohat", "perc", "808", "melody", "pad", "fx", "vinyl"},
    "verse": {"kick", "snare", "clap", "hat", "ohat", "perc", "808", "melody", "fx", "vinyl"},
    "outro": {"melody", "pad", "fx", "vinyl"},
}
DRUMS = {"kick", "snare", "clap", "hat", "ohat", "perc", "808"}


def _ev(t: float, n: int | None = None, v: float = 1.0, d: float = 0.25, **kw) -> dict:
    e = {"t": round(float(t), 4), "v": round(float(v), 3), "d": round(float(d), 4)}
    if n is not None:
        e["n"] = int(n)
    e.update(kw)
    return e


def _steps(steps, v=1.0, d=0.25):
    return [_ev(s * 0.25, v=v, d=d) for s in steps]


def _drums(style: str, rng: np.random.Generator, variant: int) -> dict:
    """Барабаны на 4 такта (16 долей): {роль: [события]}. variant 1 — куплет, проще хука."""
    out = {r: [] for r in ("kick", "snare", "clap", "hat", "ohat", "perc")}
    if style == "boombap":
        kicks = [[0, 10, 16, 23, 26], [0, 7, 10, 16, 26, 27], [0, 3, 10, 16, 22, 26]][rng.integers(3)]
        snares = [4, 12, 20, 28]
    elif style == "drill":
        kicks = [[0, 6, 16, 22, 27], [0, 10, 16, 19, 22], [0, 7, 16, 22, 26]][rng.integers(3)]
        snares = [8, 24] + ([30] if rng.random() < 0.6 else [27])
    else:  # trap, phonk — половинный размер: снейр на «три»
        kicks = [[0, 11, 16, 19, 26], [0, 3, 10, 16, 22, 26, 29], [0, 7, 10, 16, 19, 27],
                 [0, 6, 11, 14, 16, 26, 30]][rng.integers(4)]
        snares = [8, 24]
    if variant == 1:
        kicks = [k for k in kicks if k % 16 in (0, 10, 11, 6, 7) or rng.random() < 0.5]
    for bar2 in (0, 32):  # 2-тактовый рисунок дважды, во второй раз — сбивка в конце
        for k in kicks:
            s = bar2 + k
            if bar2 == 32 and k >= 26 and rng.random() < 0.4:
                s += 1
            out["kick"].append(_ev(s * 0.25, v=1.0 if k % 16 == 0 else 0.92, d=0.5))
        for s in snares:
            out["snare"].append(_ev((bar2 + s) * 0.25, v=1.0))
            out["clap"].append(_ev((bar2 + s) * 0.25, v=0.9))
    if style in ("trap", "phonk") and rng.random() < 0.7:  # призрачный снейр перед сменой
        out["snare"].append(_ev(63 * 0.25 - 0.125, v=0.45))
    out["snare"].sort(key=lambda e: e["t"])

    # Хэты.
    if style == "boombap":
        for s in range(0, 64, 2):
            out["hat"].append(_ev(s * 0.25, v=0.95 if s % 4 == 0 else 0.7))
            if rng.random() < 0.18:
                out["hat"].append(_ev((s + 1) * 0.25, v=0.4))
        for b in range(4):
            if rng.random() < 0.5:
                out["ohat"].append(_ev(b * 4 + 3.5, v=0.7, d=0.5))
    elif style == "drill":
        for bar in range(4):
            for s in (0, 3, 6, 8, 11, 14):
                out["hat"].append(_ev(bar * 4 + s * 0.25, v=0.9 if s in (0, 8) else 0.72))
            if rng.random() < 0.5:  # триольный «флик»
                base = bar * 4 + 3
                for i in range(3):
                    out["hat"].append(_ev(base + i / 3 * 0.5 + 0.5, v=0.5 + 0.15 * i))
    else:
        dens = 0.18 if variant == 1 else 0.33
        for beat in range(16):
            end_of_phrase = beat % 8 == 7
            roll = rng.random() < (0.55 if end_of_phrase else dens)
            if not roll:
                for h in (0, 0.5):
                    out["hat"].append(_ev(beat + h, v=0.9 if h == 0 else 0.7))
                continue
            div = [3, 4, 6, 8][rng.integers(4)] if end_of_phrase else [2, 3, 4][rng.integers(3)]
            start = 0.5 if (div >= 6 and rng.random() < 0.5) else 0.0
            if start:
                out["hat"].append(_ev(beat, v=0.9))
            span = 1 - start
            n = int(div * span)
            for i in range(n):
                v = 0.45 + 0.5 * (i / max(1, n - 1)) if div >= 6 else (0.85 if i == 0 else 0.62)
                out["hat"].append(_ev(beat + start + i * span / n, v=v))
        if rng.random() < 0.6:
            out["ohat"].append(_ev(7.5, v=0.6, d=0.5))
            out["ohat"].append(_ev(15.5, v=0.6, d=0.5))
    # Перкуссия: редкие удары мимо снейра.
    slots = [6, 13, 22, 29, 38, 45, 54, 61]
    for s in slots:
        if rng.random() < (0.35 if variant == 0 else 0.2):
            out["perc"].append(_ev(s * 0.25, v=0.8, pan=float(rng.choice([-0.35, 0.35]))))
    for r in out:
        out[r].sort(key=lambda e: e["t"])
    return out


def _deg(root: int, scale: list[int], d: int) -> int:
    return root + scale[d % 7] + 12 * (d // 7)


def _melody(rng, prog, scale, root_mid, sound) -> list[dict]:
    """Мотив на 2 такта и ответ на него — 4 такта мелодии."""
    rhythms = [
        [(0, 1.5), (1.5, 1), (2.5, 1.5), (4, 1.5), (5.5, 1), (6.5, 1.5)],
        [(0, .5), (.75, .5), (1.5, 1), (3, 1), (4, .5), (4.75, .5), (5.5, 1), (7, 1)],
        [(0, 2), (2, 1), (3, 1), (4, 3), (7, 1)],
        [(0, .75), (.75, .75), (1.5, .5), (2, 1), (3.5, .5), (4, .75), (4.75, .75), (5.5, 1.5), (7.5, .5)],
        [(i * .5, .5) for i in range(16)],  # арпеджио восьмыми
    ]
    pick = rhythms[rng.integers(len(rhythms))] if sound not in ("strings",) else rhythms[2]
    if sound == "cowbell":
        pick = [(i * .5, .5) for i in range(16) if i % 8 not in (3, 7) or rng.random() < .3]
    arp = len(pick) >= 14
    notes, prev = [], 9
    for phrase in (0, 1):
        for i, (t, d) in enumerate(pick):
            bar = int((t + phrase * 8) // 4)
            chord = prog[bar % 4]
            tones = [chord + k for k in (0, 2, 4)] + [chord + 7]
            tones = [x + 7 * o for x in tones for o in (0, 1) if 5 <= x + 7 * o <= 16]
            if phrase == 1 and i < len(pick) - 2:
                deg = notes[i]["deg"]  # повтор мотива, конец — новый
            elif arp:
                deg = sorted(tones)[(i + phrase) % len(tones)]
            else:
                w = np.array([1.0 / (1 + abs(x - prev)) ** 1.5 for x in tones])
                deg = int(rng.choice(tones, p=w / w.sum()))
                if phrase == 1 and i == len(pick) - 1:
                    deg = 7 if rng.random() < .6 else 11
            prev = deg
            notes.append(dict(t=t + phrase * 8, d=d * (0.9 if not arp else 0.8), deg=int(deg),
                              v=0.9 if t % 2 == 0 else 0.78))
    return [_ev(x["t"], _deg(root_mid, scale, x["deg"]), x["v"], x["d"]) for x in notes]


def _bass(style, rng, kicks, prog, scale, root_low) -> list[dict]:
    """808 по бочке: корень аккорда такта, длина до следующего удара, в дрилле — слайды."""
    out = []
    times = [e["t"] for e in kicks]
    for i, t in enumerate(times):
        nxt = times[i + 1] if i + 1 < len(times) else 16.0
        bar = int(t // 4)
        n = _deg(root_low, scale, prog[bar % 4])
        if n > root_low + 8:
            n -= 12
        d = max(0.25, nxt - t - 0.05)
        if style == "boombap":
            d = min(d, 0.9)
        e = _ev(t, n, 1.0, d)
        if t % 4 not in (0,) and rng.random() < 0.18 and d <= 1.0:
            e["n"], e["oct"] = n + 12, 1  # короткий удар октавой выше
        if style in ("drill", "phonk") and out and rng.random() < (0.45 if style == "drill" else 0.2):
            if out[-1]["n"] != e["n"]:
                e["from"] = out[-1]["n"]  # съезд из прошлой ноты
            elif rng.random() < 0.5:
                e["from"] = e["n"] + 12
        out.append(e)
    return out


def generate(text: str = "", seed: int | None = None, short: bool = False, overrides: dict | None = None,
             library: list[dict] | None = None) -> dict:
    """Запрос → бит-JSON. Всё случайное — от seed."""
    want = parse(text)
    want.update({k: v for k, v in (overrides or {}).items() if v is not None})
    if seed is None:
        seed = int(hashlib.sha1(f"{text}|{time.time()}".encode()).hexdigest()[:6], 16)
    rng = np.random.default_rng(seed)
    style = want["style"] or "trap"
    vibe = want["vibe"] or STYLE_VIBE[style]
    lo, hi = STYLE_BPM[style]
    bpm = want["bpm"] or int(rng.integers(lo, hi + 1))
    key = want["key"] or NAMES[int(rng.choice([5, 1, 8, 4, 9, 0, 6, 11, 2, 7]))]  # фа, до-диез, соль-диез…
    minor = want["minor"] if want["minor"] is not None else (vibe != "chill" or rng.random() < .7)
    if not minor:
        mode = "major"
    elif vibe == "dark":
        mode = ["harmonic", "phrygian", "minor"][rng.integers(3)]
    elif vibe == "chill":
        mode = "dorian"
    else:
        mode = "minor"
    scale = SCALES[mode]
    pc = NAMES.index(key)
    prog = PROGRESSIONS[vibe][rng.integers(len(PROGRESSIONS[vibe]))]
    sound = MELODY_SOUND[(style, vibe)]
    root_mid = 60 + pc if pc <= 6 else 48 + pc   # мелодия: октава вокруг до первой
    root_low = 24 + pc if pc >= 4 else 36 + pc   # 808: E1…D#2
    loop_hook, loop_verse = _drums(style, rng, 0), _drums(style, rng, 1)
    melody = _melody(rng, prog, scale, root_mid, sound)
    pad = [_ev(b * 4, None, 0.8, 4.0, chord=[_deg(root_mid - 12, scale, prog[b] + k) for k in (0, 2, 4)])
           for b in range(4)]
    bass_h = _bass(style, rng, loop_hook["kick"], prog, scale, root_low)
    bass_v = _bass(style, rng, loop_verse["kick"], prog, scale, root_low)

    sections = SHORT if short else ARRANGEMENT
    tracks = {r: [] for r in MIX}
    beat0 = 0.0
    sect_json = []
    for si, (name, bars) in enumerate(sections):
        sect_json.append({"name": name, "start": beat0, "bars": bars})
        loop = loop_hook if name == "hook" else loop_verse
        bass = bass_h if name == "hook" else bass_v
        nxt = sections[si + 1][0] if si + 1 < len(sections) else None
        stop_from = beat0 + bars * 4 - 2 if nxt == "hook" and name != "intro" else None  # стоп перед хуком
        for rep in range(bars // 4):
            off = beat0 + rep * 16
            parts = dict(loop, **{"808": bass, "melody": melody})
            for role, evs in parts.items():
                if role not in ROLES[name]:
                    continue
                if name == "verse" and role == "melody" and rep % 2 == 1 and sound != "cowbell":
                    evs = [e for e in evs if e["t"] < 8]  # в куплете мелодии меньше — место голосу
                for e in evs:
                    t = off + e["t"]
                    if stop_from is not None and role in DRUMS and t >= stop_from:
                        continue
                    tracks[role].append(dict(e, t=round(t, 4)))
            if "pad" in ROLES[name] or sound == "strings":
                if "pad" in ROLES[name]:
                    for e in pad:
                        tracks["pad"].append(dict(e, t=e["t"] + off))
        # Шумовые переходы: подъём в конец вступления и куплета, удар в начале хука.
        if nxt == "hook":
            tracks["fx"].append(_ev(beat0 + bars * 4 - 4, None, 0.9, 4.0, kind="riser"))
        if name == "hook":
            tracks["fx"].append(_ev(beat0, None, 1.0, 4.0, kind="impact"))
        beat0 += bars * 4
    if style == "boombap" or vibe == "chill":
        tracks["vinyl"].append(_ev(0, None, 1.0, beat0, kind="vinyl"))
    for r in tracks:
        tracks[r].sort(key=lambda e: e["t"])

    drive = {"aggressive": 3.2, "dark": 2.0, "sad": 1.5, "chill": 1.1}[vibe] + (1.5 if style == "phonk" else 0)
    spec = {
        "v": VERSION, "seed": int(seed), "query": text, "style": style, "vibe": vibe,
        "bpm": int(bpm), "key": key, "mode": mode, "minor": bool(minor),
        "swing": 0.58 if style == "boombap" else 0.0,
        "beats": beat0, "sections": sect_json,
        "sounds": {"melody": sound, "pad": "strings" if vibe in ("dark", "sad") else "pad",
                   "808": {"drive": round(drive, 2)}},
        "mix": {r: dict(MIX[r]) for r in MIX},
        "master": {"lufs": -8.5 if style == "boombap" else -7.0, "ceiling": -1.0,
                   "lofi": style == "boombap" or vibe == "chill"},
        "tracks": tracks, "credits": [],
    }
    if sound == "cowbell":
        spec["mix"]["melody"].update(gain=-16, hp=400, dly=0.12)
    if spec["master"]["lofi"]:
        spec["mix"]["melody"]["lp"] = 6500
    loop = _pick_loop(spec, library)
    if loop:
        spec["sounds"]["melody"] = {"loop": loop["path"], "bpm": loop.get("bpm"), "key": loop.get("key"),
                                    "bars": loop.get("bars", 4)}
        spec["credits"].append({k: loop.get(k) for k in ("title", "author", "license", "url")})
        roots = _loop_roots(loop)
        if roots:  # 808 — по низу петли такт за тактом, пэд молчит: своя гармония поверх чужой — грязь
            spec["loop_roots"] = roots
            for e in spec["tracks"]["808"]:
                pc = roots[int(e["t"] // 4) % len(roots)]
                e["n"] = 28 + (pc - 4) % 12 + 12 * e.get("oct", 0)  # E1…D#2
                e.pop("from", None)
            spec["tracks"]["pad"] = []
    return spec


def _loop_roots(loop: dict) -> list[int] | None:
    """Корень каждого такта петли: самая сильная нота низа (до 260 Гц) по хромаграмме."""
    try:
        import librosa
        y, sr = librosa.load(loop["path"], sr=22050, mono=True)
    except Exception:
        return None
    y = signal.sosfilt(signal.butter(4, 260 / (sr / 2), output="sos"), y)
    bars = int(loop.get("bars") or 4)
    per = len(y) // bars
    if per < sr // 4:
        return None
    out = []
    for b in range(min(bars, 4)):
        seg = y[b * per:(b + 1) * per]
        chroma = librosa.feature.chroma_cqt(y=seg, sr=sr, fmin=librosa.note_to_hz("C1"), n_octaves=4).mean(1)
        out.append(int(np.argmax(chroma)))
    return out


def _pick_loop(spec: dict, library: list[dict] | None) -> dict | None:
    """Петля из библиотеки под темп и тональность бита; не нашлось — мелодия синтезом."""
    if not library:
        return None
    rng = np.random.default_rng(spec["seed"] + 1)
    fits = []
    for x in library:
        if x.get("kind") != "melody_loop" or not x.get("bpm") or not Path(x.get("path", "")).exists():
            continue
        ratio = spec["bpm"] / x["bpm"]
        for r in (ratio, ratio / 2, ratio * 2):
            if 0.94 <= r <= 1.06:
                break
        else:
            continue
        if x.get("key") and x.get("minor") is not None and x["minor"] != spec["minor"]:
            continue
        fits.append(x)
    if not fits:
        return None
    x = fits[int(rng.integers(len(fits)))]
    if x.get("key"):  # бит встаёт в тональность петли, а не наоборот: петлю не корёжим
        spec["key"] = x["key"]
    return x


# ─────────────────────────── синтез звуков ───────────────────────────

def _t(sec: float) -> np.ndarray:
    return np.arange(int(sec * SR)) / SR


def _hz(midi: float) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


def _sos(kind: str, f: float | tuple, order: int = 2):
    nyq = SR / 2
    if isinstance(f, tuple):
        return signal.butter(order, [f[0] / nyq, min(f[1] / nyq, 0.99)], btype="band", output="sos")
    return signal.butter(order, min(f / nyq, 0.99), btype=kind, output="sos")


def _filt(x: np.ndarray, kind: str, f, order: int = 2) -> np.ndarray:
    return signal.sosfilt(_sos(kind, f, order), x, axis=0)


def _noise(n: int, rng) -> np.ndarray:
    return rng.standard_normal(n)


def _adsr(n: int, a: float = .005, r: float = .05, hold: int | None = None) -> np.ndarray:
    env = np.ones(n)
    na = max(1, int(a * SR))
    env[:na] = np.linspace(0, 1, na)
    nr = max(1, int(r * SR))
    end = n if hold is None else min(n, hold + nr)
    if hold is not None and hold < n:
        env[hold:end] = np.linspace(1, 0, end - hold)
        env[end:] = 0
    else:
        env[-nr:] *= np.linspace(1, 0, nr)
    return env


def kick(rng, drive=1.6) -> np.ndarray:
    t = _t(0.55)
    f = 48 + 120 * np.exp(-t / 0.028)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.32)
    click = _filt(_noise(len(t), rng), "high", 2500) * np.exp(-t / 0.003) * 0.35
    return np.tanh(drive * (body + click)) / np.tanh(drive)


def snare(rng) -> np.ndarray:
    t = _t(0.35)
    f = 175 + 60 * np.exp(-t / 0.02)
    tone = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.06)
    nz = _filt(_noise(len(t), rng), "band", (1200, 9000)) * np.exp(-t / 0.11)
    return np.tanh(1.3 * (0.55 * tone + 0.9 * nz))


def clap(rng) -> np.ndarray:
    t = _t(0.4)
    nz = _filt(_noise(len(t), rng), "band", (900, 4200))
    env = np.zeros(len(t))
    for d in (0, .009, .019, .028):
        k = t >= d
        env[k] += np.exp(-(t[k] - d) / (.006 if d < .028 else .13))
    return nz * env / np.abs(nz * env).max()


def hat(rng, open_: bool = False) -> np.ndarray:
    t = _t(0.5 if open_ else 0.09)
    x = sum(signal.square(2 * np.pi * f * t) for f in (317, 450, 540, 692, 805, 1023))
    x = _filt(x + 0.6 * _noise(len(t), rng), "high", 7000, 4)
    x *= np.exp(-t / (0.16 if open_ else 0.022))
    return x / (np.abs(x).max() + 1e-9)


def perc(rng) -> np.ndarray:
    t = _t(0.15)
    x = np.sin(2 * np.pi * 1650 * t) * np.exp(-t / 0.018) + 0.6 * np.sin(2 * np.pi * 820 * t) * np.exp(-t / 0.03)
    x += _filt(_noise(len(t), rng), "high", 3000) * np.exp(-t / 0.004) * 0.5
    return x / np.abs(x).max()


def bass808(note: int, dur: float, drive: float, from_: int | None = None) -> np.ndarray:
    n = int((dur + 0.06) * SR)
    t = np.arange(n) / SR
    f0 = _hz(note)
    if from_ is not None:
        f = _hz(from_) * (f0 / _hz(from_)) ** np.clip(t / 0.09, 0, 1)  # съезд за 90 мс
    else:
        f = f0 * (1 + 0.6 * np.exp(-t / 0.012))  # «щелчок» атаки
    x = np.sin(2 * np.pi * np.cumsum(f) / SR)
    env = np.exp(-t / 1.6) * _adsr(n, .002, .05, hold=int(dur * SR))
    x = np.tanh(drive * x * env) / np.tanh(drive)
    return x + 0.25 * np.sin(4 * np.pi * np.cumsum(f) / SR) * env * (drive > 2.5)


def tone(sound: str, note: int, dur: float, rng) -> np.ndarray:
    """Мелодические звуки: колокол (FM), клавиши, щипок (Карплус — Стронг), струнные, пэд, коровий колокол."""
    f = _hz(note)
    rel = {"bell": 1.2, "keys": .45, "pluck": .3, "strings": .5, "pad": .8, "cowbell": .12}[sound]
    n = int((dur + rel) * SR)
    t = np.arange(n) / SR
    hold = int(dur * SR)
    if sound == "bell":
        idx = 2.6 * np.exp(-t / .35)
        x = np.sin(2 * np.pi * f * t + idx * np.sin(2 * np.pi * f * 3.5 * t))
        x += .35 * np.sin(2 * np.pi * f * 2 * t) * np.exp(-t / .5)
        x *= np.exp(-t / 1.1) * _adsr(n, .002, rel, hold=n - 1)
    elif sound == "keys":
        x = sum(np.sin(2 * np.pi * f * k * (1 + .0004 * k * k) * t) * np.exp(-t * (1.2 + .9 * k)) / k ** 1.2
                for k in range(1, 9))
        x += .3 * np.sin(2 * np.pi * f * t + 1.2 * np.exp(-t / .2) * np.sin(2 * np.pi * f * t))
        x *= _adsr(n, .004, .25, hold=hold)
    elif sound == "pluck":
        p = max(2, int(SR / f))
        b = np.zeros(p + 2); b[0] = 1
        a = np.zeros(p + 2); a[0] = 1; a[p] = -.497; a[p + 1] = -.497
        burst = np.zeros(n); burst[:p] = _filt(rng.uniform(-1, 1, p), "low", min(9000, f * 8))
        x = signal.lfilter(b, a, burst) * _adsr(n, .001, .15, hold=hold)
    elif sound in ("strings", "pad"):
        x = np.zeros(n)
        vib = 1 + .003 * np.sin(2 * np.pi * 5.2 * t) * (sound == "strings")
        for det in (-.07, 0, .07) if sound == "pad" else (-.05, .04):
            ph = np.cumsum(f * 2 ** (det / 12) * vib) / SR + rng.random()
            x += 2 * (ph % 1) - 1
        x = _filt(x, "low", min(2800 if sound == "pad" else 3800, f * 10), 2)
        x *= _adsr(n, .35 if sound == "pad" else .18, rel, hold=hold)
    elif sound == "cowbell":
        r = f / 562
        x = signal.square(2 * np.pi * 562 * r * t) + signal.square(2 * np.pi * 845 * r * t)
        x = _filt(x, "band", (400 * r, 4000 * r)) * np.exp(-t / .09) * _adsr(n, .001, rel, hold=hold)
    else:
        raise ValueError(sound)
    return x / (np.abs(x).max() + 1e-9)


def riser(beats: float, spb: float, rng) -> np.ndarray:
    n = int(beats * spb * SR)
    t = np.arange(n) / n
    nz = _noise(n, rng)
    out = np.zeros(n)
    seg = 8
    for i in range(seg):  # шум с растущим срезом — склейка восьми полос
        lo_f = 300 * (2 ** (i * 4.5 / seg))
        part = _filt(nz, "band", (lo_f, lo_f * 2.5))
        w = np.clip(1 - np.abs(t * seg - i - .5), 0, 1)
        out += part * w
    out *= t ** 2
    out += .25 * np.sin(2 * np.pi * np.cumsum(200 + 900 * t ** 2) / SR) * t ** 3
    return out / (np.abs(out).max() + 1e-9)


def impact(rng) -> np.ndarray:
    t = _t(2.5)
    sub = np.sin(2 * np.pi * np.cumsum(55 * np.exp(-t / 1.2) + 28) / SR) * np.exp(-t / .8)
    crash = _filt(_noise(len(t), rng), "high", 4500) * np.exp(-t / .9) * .5
    return np.tanh(1.5 * (sub + crash))


def vinyl(n: int, rng) -> np.ndarray:
    hiss = _filt(_noise(n, rng), "band", (800, 6000)) * .15
    pops = np.zeros(n)
    idx = rng.integers(0, n, size=max(1, n // 6000))
    pops[idx] = rng.uniform(-1, 1, len(idx))
    pops = _filt(pops, "high", 1500)
    return hiss + pops


# ─────────────────────────── петля из сети ───────────────────────────

def _load_loop(info: dict, spec: dict, spb: float) -> np.ndarray | None:
    """Петля под темп бита: растяжение без смены высоты (librosa), если её нет — None."""
    try:
        import soundfile as sf
        y, sr = sf.read(info["loop"], always_2d=True)
    except Exception:
        try:
            y = _ffmpeg_read(info["loop"])
            sr = SR
        except Exception:
            return None
    y = y.mean(1)
    if sr != SR:
        y = signal.resample_poly(y, SR, sr)
    src_bpm = info.get("bpm") or spec["bpm"]
    ratio = spec["bpm"] / src_bpm
    for r in (ratio, ratio / 2, ratio * 2):
        if 0.94 <= r <= 1.06:
            ratio = r
            break
    if abs(ratio - 1) > 0.003:
        try:
            import librosa
            y = librosa.effects.time_stretch(y.astype(np.float32), rate=ratio)
        except Exception:
            y = signal.resample(y, int(len(y) / ratio))  # грубо: темп и высота вместе
    bars = info.get("bars") or max(1, round(len(y) / SR / (4 * spb)))
    want = int(bars * 4 * spb * SR)
    y = np.pad(y, (0, max(0, want - len(y))))[:want]
    fade = int(.004 * SR)
    y[-fade:] *= np.linspace(1, 0, fade)
    return y / (np.abs(y).max() + 1e-9)


def _ffmpeg_read(path: str) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32).reshape(-1, 2).astype(np.float64)


# ─────────────────────────── микшер и мастер ───────────────────────────

def _pan(x: np.ndarray, p: float) -> np.ndarray:
    a = (p + 1) * np.pi / 4
    return np.stack([x * np.cos(a), x * np.sin(a)], axis=1) * np.sqrt(2)


def _place(buf: np.ndarray, x: np.ndarray, at: int) -> None:
    if at >= len(buf) or at < 0:
        return
    end = min(len(buf), at + len(x))
    buf[at:end] += x[: end - at]


def _reverb_ir(rng, seconds: float = 2.2) -> np.ndarray:
    t = _t(seconds)
    ir = np.stack([_noise(len(t), rng), _noise(len(t), rng)], 1) * np.exp(-t / (seconds / 6.9))[:, None]
    ir = _filt(ir, "low", 6000)
    ir[: int(.018 * SR)] = 0  # предзадержка
    return ir / np.sqrt((ir ** 2).sum(0, keepdims=True))


def _delay(x: np.ndarray, spb: float) -> np.ndarray:
    step = int(.75 * spb * SR)  # пунктирная восьмая
    out = np.zeros_like(x)
    y = x
    for k in range(1, 6):
        y = _filt(y, "low", 4500) * .42
        side = k % 2  # пинг-понг
        shifted = np.zeros_like(x)
        shifted[step * k:, side] = y[: len(x) - step * k, side] if step * k < len(x) else 0
        shifted[step * k:, 1 - side] = .3 * y[: len(x) - step * k, 1 - side] if step * k < len(x) else 0
        out += shifted
    return out


def _duck(n: int, kicks: list[int], depth: float) -> np.ndarray:
    g = np.ones(n)
    if depth <= 0:
        return g
    t = _t(0.25)
    shape = 1 - depth * np.exp(-t / 0.07)
    for k in kicks:
        if k < n:
            e = min(n, k + len(shape))
            g[k:e] = np.minimum(g[k:e], shape[: e - k])
    return g


def lufs(x: np.ndarray) -> float:
    """Интегральная громкость по BS.1770 (K-взвешивание, стробирование)."""
    def biquad(kind, fc, q, gain=0.0):
        a_ = 10 ** (gain / 40)
        w = 2 * np.pi * fc / SR
        al = np.sin(w) / (2 * q)
        c = np.cos(w)
        if kind == "shelf":
            sa = 2 * np.sqrt(a_) * al
            b = [a_ * ((a_ + 1) + (a_ - 1) * c + sa), -2 * a_ * ((a_ - 1) + (a_ + 1) * c), a_ * ((a_ + 1) + (a_ - 1) * c - sa)]
            a = [(a_ + 1) - (a_ - 1) * c + sa, 2 * ((a_ - 1) - (a_ + 1) * c), (a_ + 1) - (a_ - 1) * c - sa]
        else:
            b = [(1 + c) / 2, -(1 + c), (1 + c) / 2]
            a = [1 + al, -2 * c, 1 - al]
        return np.array(b) / a[0], np.array(a) / a[0]
    y = x if x.ndim == 2 else x[:, None]
    for b, a in (biquad("shelf", 1500, 1 / np.sqrt(2), 4.0), biquad("hp", 38, .5)):
        y = signal.lfilter(b, a, y, axis=0)
    blk, hop = int(.4 * SR), int(.1 * SR)
    if len(y) < blk:
        return -70.0
    sq = np.cumsum(np.vstack([np.zeros((1, y.shape[1])), y ** 2]), axis=0)
    starts = np.arange(0, len(y) - blk + 1, hop)
    ms = ((sq[starts + blk] - sq[starts]) / blk).sum(1)
    ld = -0.691 + 10 * np.log10(ms + 1e-12)
    ms = ms[ld > -70]
    if not len(ms):
        return -70.0
    rel = -0.691 + 10 * np.log10(ms.mean()) - 10
    keep = ms[(-0.691 + 10 * np.log10(ms)) > rel]
    return float(-0.691 + 10 * np.log10(keep.mean()))


def _limit(x: np.ndarray, ceiling_db: float) -> np.ndarray:
    ceil = 10 ** (ceiling_db / 20)
    look = int(.004 * SR)
    peak = maximum_filter1d(np.abs(x).max(1), size=2 * look + 1)
    g = np.minimum(1.0, ceil / np.maximum(peak, 1e-9))
    g = minimum_filter1d(g, size=2 * look + 1)
    g = uniform_filter1d(g, size=look + 1)  # окно среднего уже окна минимума — g не выше нужного
    return np.clip(x * g[:, None], -ceil, ceil)


def _softclip(x: np.ndarray, knee: float = 0.75) -> np.ndarray:
    """До порога сигнал не тронут, выше — плавно к 1: срезает верхушки бочки и 808 без хруста."""
    a = np.abs(x)
    over = a > knee
    y = x.copy()
    y[over] = np.sign(x[over]) * (knee + (1 - knee) * np.tanh((a[over] - knee) / (1 - knee)))
    return y


def _glue(x: np.ndarray, thr_db: float = -14, ratio: float = 2.0) -> np.ndarray:
    env = np.abs(x).max(1)
    a = np.exp(-1 / (.03 * SR))
    env = signal.lfilter([1 - a], [1, -a], env)
    lvl = 20 * np.log10(env + 1e-9)
    over = np.maximum(0, lvl - thr_db)
    g = 10 ** (-over * (1 - 1 / ratio) / 20)
    return x * g[:, None]


def render(spec: dict, stems_dir: Path | None = None) -> np.ndarray:
    """Бит-JSON → стерео float, мастер уже на месте."""
    rng = np.random.default_rng(spec["seed"] + 99)
    spb = 60 / spec["bpm"]
    n = int((spec["beats"] * spb + 3.0) * SR)
    swing = spec.get("swing", 0.0)
    cache: dict = {}
    drums = {"kick": lambda: kick(rng), "snare": lambda: snare(rng), "clap": lambda: clap(rng),
             "hat": lambda: hat(rng), "ohat": lambda: hat(rng, True), "perc": lambda: perc(rng)}

    def at(t: float, role: str) -> int:
        if swing and abs((t * 4) % 2 - 1) < 1e-6:  # нечётная шестнадцатая
            t += (swing - .5) * .5
        jitter = rng.normal(0, .002) if role in ("hat", "ohat", "perc") else 0  # чуть живее сетки
        return max(0, int((t * spb + jitter) * SR))

    rev_bus = np.zeros((n, 2))
    dly_bus = np.zeros((n, 2))
    mix = np.zeros((n, 2))
    kicks = [at(e["t"], "kick") for e in spec["tracks"].get("kick", [])]
    melody_sound = spec["sounds"]["melody"]
    loop_audio = None
    if isinstance(melody_sound, dict) and melody_sound.get("loop"):
        loop_audio = _load_loop(melody_sound, spec, spb)
        if loop_audio is None:
            melody_sound = MELODY_SOUND[(spec["style"], spec["vibe"])]

    for role, evs in spec["tracks"].items():
        m = spec["mix"].get(role, MIX.get(role))
        buf = np.zeros(n)
        if role in drums:
            if role not in cache:
                cache[role] = drums[role]()
            for e in evs:
                _place(buf, cache[role] * e["v"], at(e["t"], role))
        elif role == "808":
            drive = spec["sounds"]["808"]["drive"]
            for e in evs:
                key = ("808", e["n"], round(e["d"] * spb, 3), e.get("from"))
                if key not in cache:
                    cache[key] = bass808(e["n"], e["d"] * spb, drive, e.get("from"))
                _place(buf, cache[key] * e["v"], at(e["t"], role))
        elif role == "melody":
            if loop_audio is not None:
                L = len(loop_audio)
                starts = sorted({int(e["t"] // 16) * 16 for e in evs})
                for s in starts:
                    _place(buf, loop_audio[: int(16 * spb * SR)] if L > 16 * spb * SR else loop_audio, at(s, role))
            else:
                for e in evs:
                    key = (melody_sound, e["n"], round(e["d"] * spb, 3))
                    if key not in cache:
                        cache[key] = tone(melody_sound, e["n"], e["d"] * spb, rng)
                    _place(buf, cache[key] * e["v"], at(e["t"], role))
        elif role == "pad":
            for e in evs:
                for note in e.get("chord", []):
                    key = (spec["sounds"]["pad"], note, round(e["d"] * spb, 3))
                    if key not in cache:
                        cache[key] = tone(spec["sounds"]["pad"], note, e["d"] * spb, rng)
                    _place(buf, cache[key] * e["v"] / 2, at(e["t"], role))
        elif role == "fx":
            for e in evs:
                x = riser(e["d"], spb, rng) * .7 if e.get("kind") == "riser" else impact(rng)
                _place(buf, x * e["v"], at(e["t"], role))
        elif role == "vinyl":
            for e in evs:
                _place(buf, vinyl(int(e["d"] * spb * SR), rng), at(e["t"], role))
        if not evs or not np.any(buf):
            continue
        if m["hp"]:
            buf = _filt(buf, "high", m["hp"])
        if m["lp"]:
            buf = _filt(buf, "low", m["lp"])
        if role in ("melody", "pad"):
            # Вступление и концовка — мелодия «из-за стены»: срез верха по маске секций.
            mask = np.zeros(n)
            for s in spec["sections"]:
                if s["name"] in ("intro", "outro"):
                    a, b = int(s["start"] * spb * SR), int((s["start"] + s["bars"] * 4) * spb * SR)
                    mask[a:b] = 1
            if mask.any():
                mask = uniform_filter1d(mask, int(.3 * SR))
                buf = buf * (1 - mask) + _filt(buf, "low", 900) * mask
        buf *= _duck(n, kicks, m["duck"])
        if role == "perc":
            st = np.zeros((n, 2))
            for e in evs:  # у каждого удара своя сторона
                i = at(e["t"], role)
                seg = buf[i: i + int(.15 * SR)]
                st[i: i + len(seg)] += _pan(seg, e.get("pan", m["pan"]))
        elif role == "pad":
            st = np.stack([buf, np.roll(buf, int(.012 * SR))], 1)  # шире: правый канал на 12 мс позже
        else:
            st = _pan(buf, m["pan"])
        st *= 10 ** (m["gain"] / 20)
        mix += st
        if m["rev"]:
            rev_bus += st * m["rev"]
        if m["dly"]:
            dly_bus += st * m["dly"]
        if stems_dir:
            _write_wav(stems_dir / f"{role}.wav", st)

    if np.any(dly_bus):
        mix += _delay(dly_bus, spb)
        rev_bus += _delay(dly_bus, spb) * .3
    if np.any(rev_bus):
        rev = signal.fftconvolve(_filt(rev_bus, "high", 300), _reverb_ir(rng), axes=0)[:n]
        mix += rev * .9

    # Мастер: срез инфранизов, склейка, мягкое ограничение, громкость по LUFS, лимитер.
    x = _filt(mix, "high", 28)
    if spec["master"].get("lofi"):
        x = 0.85 * x + 0.15 * _filt(x, "low", 7000)
    x = _glue(x / (np.abs(x).max() + 1e-9))
    target = spec["master"]["lufs"]
    for _ in range(4):
        x = _softclip(x * 10 ** ((target - lufs(x)) / 20))
        x = _limit(x, spec["master"]["ceiling"])
        if abs(lufs(x) - target) < 0.3:
            break
    end = int((spec["beats"] * spb + 2.5) * SR)
    x = x[:end]
    fade = int(2.0 * SR)
    x[-fade:] *= np.linspace(1, 0, fade)[:, None] ** 2
    return x


def _write_wav(path: Path, x: np.ndarray) -> None:
    import soundfile as sf
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), x.astype(np.float32), SR, subtype="PCM_24")


def title(spec: dict) -> str:
    mode = "m" if spec["minor"] else ""
    st = {"trap": "Trap", "drill": "Drill", "boombap": "Boom bap", "phonk": "Phonk"}[spec["style"]]
    return f"{st} · {spec['bpm']} · {spec['key']}{mode} · {spec['vibe']}"


def card(spec: dict) -> str:
    """Карточка бита для владельца: как понят запрос и из чего собран."""
    mel = spec["sounds"]["melody"]
    mel = f"петля «{spec['credits'][0]['title']}» — {spec['credits'][0]['author']}" if isinstance(mel, dict) else \
        {"bell": "колокол", "keys": "клавиши", "pluck": "щипок", "strings": "струнные",
         "cowbell": "коровий колокол"}[mel]
    secs = spec["beats"] * 60 / spec["bpm"]
    return (f"{title(spec)}\nмелодия: {mel}; лад: {spec['mode']}; seed {spec['seed']}\n"
            f"длина {int(secs // 60)}:{int(secs % 60):02d}")


def build(spec: dict, out: Path, stems: bool = False) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    x = render(spec, out / "stems" if stems else None)
    wav, mp3 = out / "beat.wav", out / "beat.mp3"
    _write_wav(wav, x)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(wav), "-b:a", "320k",
                    "-metadata", f"title={title(spec)}", "-metadata", "artist=ПЛЁНКА", str(mp3)], check=True)
    (out / "beat.json").write_text(json.dumps(spec, ensure_ascii=False, indent=1))
    if spec["credits"]:
        (out / "credits.txt").write_text("\n".join(
            f"{c['title']} — {c['author']} ({c['license']}) {c['url']}" for c in spec["credits"]) + "\n")
    return {"mp3": str(mp3), "wav": str(wav), "seconds": round(len(x) / SR, 1),
            "lufs": round(lufs(x), 1), "peak_db": round(20 * np.log10(np.abs(x).max()), 2),
            "render_s": round(time.time() - t0, 1)}


def library() -> list[dict]:
    path = Path(os.environ.get("BITGEN_LIB", Path.home() / ".cache/plenka_bitgen")) / "library.json"
    try:
        lib = json.loads(path.read_text())
    except (OSError, ValueError):
        return []
    return [x for x in lib if x.get("approved") is not False]


# ─────────────────────────── проверка ───────────────────────────

def selftest() -> None:
    p = parse("Trap, 140 BPM, dark vibe")
    assert p == {"style": "trap", "bpm": 140, "key": None, "minor": None, "vibe": "dark"}, p
    p = parse("дрилл фа минор 144 агрессивный")
    assert (p["style"], p["key"], p["minor"], p["bpm"], p["vibe"]) == ("drill", "F", True, 144, "aggressive"), p
    p = parse("boom bap 90 Bbm chill")
    assert (p["style"], p["key"], p["minor"], p["bpm"], p["vibe"]) == ("boombap", "A#", True, 90, "chill"), p
    p = parse("фонк C# minor")
    assert (p["style"], p["key"], p["minor"]) == ("phonk", "C#", True), p
    assert parse("Drake type beat")["key"] is None  # «D» в имени — не тональность
    a, b = generate("trap 140 dark", seed=5), generate("trap 140 dark", seed=5)
    assert json.dumps(a) == json.dumps(b), "тот же seed — другой бит"
    assert json.dumps(generate("trap 140 dark", seed=6)["tracks"]) != json.dumps(a["tracks"])
    assert a["bpm"] == 140 and a["style"] == "trap" and a["tracks"]["808"]
    assert not any(e["t"] < 16 for e in a["tracks"]["kick"]), "во вступлении бочки нет"
    full = generate("drill", seed=1)
    bars = full["beats"] / 4
    assert bars == 64, bars
    hook0 = next(s for s in full["sections"] if s["name"] == "hook" and s["start"] > 16)["start"]
    assert not any(hook0 - 2 <= e["t"] < hook0 for e in full["tracks"]["kick"]), "стоп перед хуком"
    assert any("from" in e for e in full["tracks"]["808"]), "в дрилле 808 съезжает"
    for style in STYLES:
        spec = generate(style, seed=3, short=True)
        spec["sections"] = spec["sections"][:2]
        x = render(spec)
        assert np.isfinite(x).all(), style
        peak = 20 * np.log10(np.abs(x).max())
        assert peak <= spec["master"]["ceiling"] + 0.05, (style, peak)
        loud = lufs(x)
        assert abs(loud - spec["master"]["lufs"]) < 2.0, (style, loud)
        print(f"  {title(spec)}: {len(x) / SR:.0f} с, {loud:.1f} LUFS, пик {peak:.2f} дБ")
    # Петля: под темп с запасом ±6 %, вдвое быстрее или медленнее — тоже; лад не тот — мимо.
    lib = [{"kind": "melody_loop", "bpm": 70, "key": "G", "minor": True, "path": __file__, "title": "x",
            "author": "a", "license": "CC0", "url": "u"},
           {"kind": "melody_loop", "bpm": 140, "key": "C", "minor": False, "path": __file__}]
    s = generate("trap 140 dark Fm", seed=2, library=lib)
    assert s["sounds"]["melody"]["bpm"] == 70 and s["key"] == "G" and s["credits"][0]["author"] == "a", s["sounds"]
    assert not generate("trap 120 dark", seed=2, library=lib)["credits"]
    print("bitgen: ок")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("text", nargs="?", default="")
    ap.add_argument("--seed", type=int)
    ap.add_argument("--out", type=Path, default=Path("out/bitgen"))
    ap.add_argument("--short", action="store_true", help="превью: вступление и хук")
    ap.add_argument("--stems", action="store_true")
    ap.add_argument("--no-loops", action="store_true", help="мелодия только синтезом")
    ap.add_argument("--render", type=Path, help="бит-JSON → звук")
    ap.add_argument("--send", action="store_true", help="mp3 владельцу в личку (TELEGRAM_BOT_TOKEN, TELEGRAM_ADMIN_ID)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.render:
        spec = json.loads(a.render.read_text())
    else:
        spec = generate(a.text, a.seed, a.short, library=None if a.no_loops else library())
    info = build(spec, a.out, a.stems)
    print(card(spec))
    print(json.dumps(info, ensure_ascii=False))
    if a.send:
        send(spec, info)


def send(spec: dict, info: dict) -> None:
    """Бит владельцу: плеер с карточкой, следом бит-JSON — чтобы повторить или поправить."""
    import html
    from . import config, telegram
    admin = config.secret("TELEGRAM_ADMIN_ID")
    lines = [f"🎛 <b>{html.escape(title(spec))}</b>", html.escape(card(spec).split("\n", 1)[1]),
             f"запрос: «{html.escape(spec['query'] or '—')}»"]
    for c in spec["credits"]:
        lines.append(f"петля: {html.escape(c['title'])} — {html.escape(c['author'])} ({c['license']})")
    lines.append(f"рендер {info['render_s']} с · {info['lufs']} LUFS")
    telegram.send_audio(admin, Path(info["mp3"]).read_bytes(), "\n".join(lines),
                        title=title(spec), performer="ПЛЁНКА · генератор", seconds=int(info["seconds"]))
    telegram.send_document(admin, Path(info["mp3"]).with_name("beat.json"),
                           f"бит-JSON, seed {spec['seed']}: python -m src.bitgen --render beat.json")


if __name__ == "__main__":
    sys.exit(main())
