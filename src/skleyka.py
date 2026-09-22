"""СКЛЕЙКА — вокал и бит в черновой трек: бот сводит две дорожки за пару минут.

Зачем. Артисту без денег свести трек негде: инженер берёт 3–10 тысяч, самому
учиться годами. Две дорожки, выгруженные с одного начала, — вокал и бит — бот
склеивает в трек, который не стыдно выложить, а выложенный ведёт прямо в ОТБОР.
Обещание честное: черновая склейка автоматом, не работа звукорежиссёра.
Имя СВЕДЕНИЕ занято процентами совпадения (src/svedenie.py), поэтому СКЛЕЙКА —
монтаж плёнки.

Как. Только ffmpeg: он уже стоит в дежурстве, а считать хватает машины Actions.
Громкость дорожек на входе любая — телефон, студия, бит с YouTube, — поэтому
каждый уровень выставляется по замеру EBU R128, а не коэффициентом:

1. Вокал приводится к VOCAL_LUFS, и только потом компрессия VOCAL_CHAIN — её пороги
   отсчитаны от этого уровня. Иначе тихая запись прошла бы мимо компрессора,
   а громкая сплющилась.
2. Тембр вокала выравнивается к сведённому рэп-вокалу (TONE) по замеру октав:
   домашние записи расходятся на 10 дБ, и одна полка на всех не годится.
3. Бит проседает под голос слегка: провал на 2–4 кГц и сайдчейн ratio 2 с быстрым
   отпуском (DUCK). Приглушение из роликов (reels.DUCK, ratio 6) для песни
   глубоко — бит начал бы качаться насосом.
4. Баланс — по EBU R128: вокал на VOCAL_OVER_BEAT LU относительно бита.
5. Отзвук и дилей — шинами из роликов (reels.REVERB, reels.DELAY), доля к сухому
   голосу по замеру, как в reels.studio.
6. Мастер — клиппер по верхушкам ударов и ограничитель до MASTER_LUFS, пик
   не выше CEILING dBTP.

Промежуточное — во float: пики выше нуля между шагами не срезаются, режет только
мастер. Подгонку под референс (Matchering) сюда не тащим: это
новый пакет и обещание «как у звезды», которое черновая склейка не сдержит.

Проверка — на слух: ДО (простая сумма дорожек) и ПОСЛЕ одной громкости по LUFS.
Громкое всегда кажется лучше, и без этого сравнение нечестное.

    python -m src.skleyka --mix ВОКАЛ БИТ --out ПАПКА   склейка и пара ДО/ПОСЛЕ одной громкости
"""

from __future__ import annotations

import argparse
import math
import re
import subprocess
from pathlib import Path

from . import clips, reels

RATE = 44100
# Любой формат на входе: моно становится стерео, частота — 44,1 кГц. Неслышимое
# срезается сразу: замер громкости его считает, а MP3 выбрасывает. В бите
# Little Chicago's Finest ультразвук над 20 кГц завышал громкость на 5 LU —
# вокал встал бы под мусор, а MP3 вышел бы на 5 дБ тише замера.
FORMAT = f"aformat=sample_fmts=flt:sample_rates={RATE}:channel_layouts=stereo,highpass=f=20,lowpass=f=20000"
MP3 = ["-c:a", "libmp3lame", "-b:a", "320k"]

# --- вокал ------------------------------------------------------------------
# Низ ниже 90 Гц — гул и хлопки на «п» и «б».
HIGHPASS = "highpass=f=90"
VOCAL_LUFS = -18.0
# Компрессия плотнее дикторской (reels.VOICE_CHAIN, ratio 3 почти вхолостую):
# быстрый ловит пики (порог −16 дБ), второй ровняет строку (−26 дБ, ratio 3).
# При VOCAL_LUFS голос в строке идёт около −20 дБ, и второй давит 3–4 дБ постоянно.
VOCAL_CHAIN = (
    "acompressor=threshold=0.158:ratio=4:attack=1:release=60,"
    "acompressor=threshold=0.05:ratio=3:attack=10:release=150:knee=4"
)
# Тембр — после компрессии и по замеру, а не одной полкой на всех: домашние
# записи расходятся на 10 дБ. У конденсатора вплотную середина бубнит (у Little
# Chicago's Finest полоса 250 Гц на 5 дБ выше 1 кГц), у телефона её нет вовсе,
# а компрессия поднимает тихое — и гул, и шипящие. Цель — октавы голоса к 1 кГц
# у сведённого рэп-вокала (Grants — PunchDrunk из MedleyDB: 125 Гц −17,
# 250 Гц −7, 2 кГц −4, 4 кГц −8, 8 кГц −11; воздуха у нас на 2 дБ больше — голос
# у него тёмный). Вниз — не больше 9 дБ, вверх —
# только разборчивость, 2–4 кГц, и не больше 3 дБ: поднятый низ гудит,
# поднятый верх шипит.
TONE = {125: -15, 250: -6, 500: 0, 2000: -4, 4000: -7, 8000: -9}
TONE_CUT = -9.0
TONE_BOOST = {2000: 3.0, 4000: 3.0}
# Де-эссер последним: подъём разборчивости и компрессия сами добавляют свиста.
DEESSER = "deesser=i=0.5"
# Доля шин к сухому голосу по громкости. В роликах владелец взял втрое меньше
# (reels.REVERB_SHARE), но там голос один, а здесь под ним плотный бит.
REVERB_SHARE = 0.07
DELAY_SHARE = 0.05

# --- бит --------------------------------------------------------------------
# Место под голос: провал 1,5 дБ в полосе 2–4 кГц, где разборчивость.
BEAT_EQ = "equalizer=f=2800:t=o:w=1.3:g=-1.5"
# Порог −20 дБ от вокала на VOCAL_LUFS: в строке бит проседает на 1–2 дБ
# и за 0,1 с возвращается в паузе. С порогом −24 дБ сжатый голос проваливал
# бит на 3,3 дБ, а на громких словах — на 5.
DUCK = "sidechaincompress=threshold=0.1:ratio=2:attack=5:release=100"

# --- мастер -----------------------------------------------------------------
# Вокал к биту по EBU R128. Бит без пауз, а у вокала паузы отсекает сам замер,
# так что 0 — голос в строке вровень с битом. В сведённом Grants — PunchDrunk
# голос на 1,7 LU тише бита, а здесь бит ещё и уступает ему место (BEAT_EQ, DUCK).
VOCAL_OVER_BEAT = -1.0
MASTER_LUFS = -10.0
CEILING = -1.0
# Сырые барабаны выше громкости на 15–17 дБ, и один ограничитель давил бы
# на ударах по 6 дБ и больше — насосом на весь трек. Верхушки ударов до CLIP дБ
# над порогом срезает клиппер: на миллисекундном ударе искажение не слышно.
# У готового бита с YouTube пики и так низкие, и клиппер почти не работает.
CLIP = 2.0


def _ffmpeg(*args) -> None:
    clips.run([clips.ffmpeg(), "-y", "-hide_banner", *map(str, args)])


def _stderr(*args) -> str:
    return subprocess.run([clips.ffmpeg(), "-hide_banner", "-nostats", *map(str, args), "-f", "null", "-"],
                          capture_output=True, text=True).stderr


def loudness(path: Path, chain: str = "") -> tuple[float, float]:
    """Громкость по EBU R128 и истинный пик: (LUFS, dBTP). Тишина — (−70, −inf)."""
    err = _stderr("-i", path, "-af", f"{chain}ebur128=peak=true:framelog=quiet")
    level = re.findall(r"I:\s+(-?[\d.]+) LUFS", err)
    peak = re.findall(r"Peak:\s+(-?[\d.]+|-inf) dBFS", err)
    return (float(level[-1]) if level else -70.0), (float(peak[-1]) if peak else -math.inf)


def tone(path: Path, chain: str) -> dict[int, float]:
    """Октавы голоса к полосе 1 кГц, дБ, за один проход.

    Полосы режутся крутыми фильтрами, 36 дБ на октаву: у пологих соседняя
    протекает, и гул 250 Гц читался бы в полосе 125.
    """
    bands = [*TONE, 1000]
    graph = (
        f"[0:a]{chain},asplit={len(bands)}{''.join(f'[i{f}]' for f in bands)};"
        + "".join(
            f"[i{f}]" + ",".join([f"highpass=f={f / 2 ** 0.5:.0f}"] * 3 + [f"lowpass=f={min(f * 2 ** 0.5, 20000):.0f}"] * 3)
            + f",astats@{f}=measure_perchannel=none:measure_overall=RMS_level[o{f}];"
            for f in bands
        )
        + "".join(f"[o{f}]" for f in bands) + f"amix=inputs={len(bands)}"
    )
    level = {int(f): float(db) for f, db in re.findall(
        r"\[astats@(\d+) @ \w+\] RMS level dB: (-?[\d.]+|-inf)", _stderr("-i", path, "-filter_complex", graph))}
    return {f: level[f] - level[1000] for f in TONE}


def _bells(gains: dict[int, float]) -> str:
    return "".join(f"equalizer=f={f}:t=o:w=1:g={g:.1f}," for f, g in gains.items() if g)


def _equalizer(vocal: Path) -> str:
    """Поправка тембра к TONE колоколами по октавам. Меряется голос уже с де-эссером,
    а соседние колокола задевают друг друга, поэтому замер повторяется
    по поправленному голосу."""
    gains = dict.fromkeys(TONE, 0.0)
    for _ in range(2):
        for f, db in tone(vocal, _bells(gains) + DEESSER).items():
            gains[f] = max(TONE_CUT, min(TONE_BOOST.get(f, 0.0), gains[f] + TONE[f] - db))
    print("  тембр: " + ", ".join(f"{f} Гц {g:+.1f}" for f, g in gains.items() if g))
    return _bells(gains)


def mix(vocal: Path, beat: Path, out: Path) -> Path:
    """Склейка в out/skleyka.wav, промежуточное — в out/work."""
    work = out / "work"
    work.mkdir(parents=True, exist_ok=True)
    dry, ducked, total = work / "vocal.wav", work / "beat.wav", work / "sum.wav"

    squeezed, clean = work / "vocal-comp.wav", f"{FORMAT},{HIGHPASS}"
    _ffmpeg("-i", vocal, "-af", f"{clean},volume={VOCAL_LUFS - loudness(vocal, clean + ',')[0]:.2f}dB,{VOCAL_CHAIN}",
            *reels.VOICE_CODEC, squeezed)
    _ffmpeg("-i", squeezed, "-af", _equalizer(squeezed) + DEESSER, *reels.VOICE_CODEC, dry)
    voice = loudness(dry)[0]
    _ffmpeg("-i", beat, "-i", dry, "-filter_complex",
            f"[0:a]{FORMAT},{BEAT_EQ}[b];[1:a]volume={VOCAL_LUFS - voice:.2f}dB[v];[b][v]{DUCK}",
            *reels.VOICE_CODEC, ducked)
    lift = loudness(ducked)[0] + VOCAL_OVER_BEAT - voice

    gains = [lift, 0.0]
    for name, graph, share in (("reverb", reels.REVERB, REVERB_SHARE), ("delay", reels.DELAY, DELAY_SHARE)):
        wet = work / f"{name}.wav"
        _ffmpeg("-i", dry, "-filter_complex", graph, "-map", "[w]", "-ar", RATE, *reels.VOICE_CODEC, wet)
        gains.append(voice + lift + 20 * math.log10(share) - loudness(wet)[0])
    parts = [dry, ducked, work / "reverb.wav", work / "delay.wav"]
    _ffmpeg(*(arg for part in parts for arg in ("-i", part)), "-filter_complex",
            "".join(f"[{n}:a]volume={gain:.2f}dB[s{n}];" for n, gain in enumerate(gains))
            + "".join(f"[s{n}]" for n in range(len(parts)))
            + f"amix=inputs={len(parts)}:duration=longest:normalize=0",
            *reels.VOICE_CODEC, total)

    # Клиппер и ограничитель съедают часть громкости, поэтому подъём подбирается
    # замером. Пик волны лежит между отсчётами и на 44,1 кГц выходит до дБ выше
    # порога, поэтому оба работают на учетверённой частоте. Клиппер режет по нулю,
    # и сигнал к нему подводится так, чтобы ноль пришёлся на CLIP дБ над порогом.
    master, push, limit = out / "skleyka.wav", MASTER_LUFS - loudness(total)[0], CEILING - 0.3
    for _ in range(4):
        _ffmpeg("-i", total, "-af",
                f"volume={push - limit - CLIP:.2f}dB,aresample={4 * RATE},asoftclip=type=hard,"
                f"volume={limit + CLIP:.2f}dB,"
                f"alimiter=limit={10 ** (limit / 20):.4f}:attack=5:release=150:asc=1:level=0:latency=1,"
                f"aresample={RATE}",
                "-c:a", "pcm_s24le", master)
        level, peak = loudness(master)
        if abs(level - MASTER_LUFS) < 0.3 and peak <= CEILING:
            break
        push += MASTER_LUFS - level
        limit -= max(peak - CEILING, 0.0)
    print(f"  вокал {lift:+.1f} дБ к биту, шины {gains[2]:+.1f}/{gains[3]:+.1f} дБ, "
          f"мастер {level:.1f} LUFS, пик {peak:.1f} dBTP, подъём {push:+.1f} дБ")
    return master


def compare(vocal: Path, beat: Path, master: Path, out: Path) -> tuple[Path, Path]:
    """ДО и ПОСЛЕ одной громкости по LUFS: out/do.mp3 — простая сумма, out/posle.mp3 — склейка.

    Уровень — громкость склейки, а если простая сумма там уже упирается в пик,
    то ниже, где она ещё не клиппует: ДО без ограничителя, иначе сравнивался бы
    ограничитель, а не склейка.
    """
    plain = out / "work" / "plain.wav"
    _ffmpeg("-i", vocal, "-i", beat, "-filter_complex",
            f"[0:a]{FORMAT}[v];[1:a]{FORMAT}[b];[v][b]amix=inputs=2:duration=longest:normalize=0",
            *reels.VOICE_CODEC, plain)
    (raw, peak), glued = loudness(plain), loudness(master)[0]
    level = min(glued, raw + CEILING - peak)
    pair = out / "do.mp3", out / "posle.mp3"
    for source, now, dest in ((plain, raw, pair[0]), (master, glued, pair[1])):
        _ffmpeg("-i", source, "-af", f"volume={level - now:.2f}dB", *MP3, dest)
    print(f"  ДО и ПОСЛЕ на {level:.1f} LUFS")
    return pair


def main() -> int:
    parser = argparse.ArgumentParser(description="СКЛЕЙКА: вокал и бит в черновой трек")
    parser.add_argument("--mix", nargs=2, type=Path, metavar=("ВОКАЛ", "БИТ"),
                        help="склеить две дорожки и сделать пару ДО/ПОСЛЕ одной громкости")
    parser.add_argument("--out", type=Path, default=Path("skleyka"), help="папка для результата")
    args = parser.parse_args()
    if args.mix:
        master = mix(*args.mix, args.out)
        compare(*args.mix, master, args.out)
        print(f"  готово: {master}, {args.out / 'do.mp3'}, {args.out / 'posle.mp3'}")
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
