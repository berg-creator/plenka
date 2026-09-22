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
   а громкая сплющилась. Голос, записанный в один канал стерео, встаёт в центр.
2. Тембр вокала выравнивается к сведённому рэп-вокалу (TONE) по замеру октав:
   домашние записи расходятся на 10 дБ, и одна полка на всех не годится.
3. Бит: каналы в противофазе переворачиваются, место под голос — провал на 2–4 кГц
   только в середине (M/S), края не тронуты, и бит остаётся широким. Сайдчейн
   ratio 2 с быстрым отпуском (DUCK): приглушение из роликов (reels.DUCK, ratio 6)
   для песни глубоко — бит качался бы насосом.
4. Баланс — вровень по EBU R128, а по ходу трека голос ведёт райдер: где бит
   его перекрывает, голос плавно поднимается. Один баланс на весь трек владелец
   услышал с первой прослушки: «где-то будто слишком громкий бит».
5. Стиль (STYLES) — набор эффектов, названный словом, понятным без знания
   сведения. Отзвук, дилей и дабл — шинами, доля к сухому голосу по замеру,
   как в reels.studio.
6. Саунд-дизайн — по флагу: вдох перевёрнутого отзвука перед первым словом,
   бит из-под фильтра до первого слова, броски дилея на концах строк, остановка
   плёнки в конце. Всё синтезом ffmpeg, без чужих сэмплов, и всё — на доли
   бита (grid).
7. Мастер — низ ниже 120 Гц в моно, клиппер по верхушкам ударов и ограничитель
   до MASTER_LUFS, пик не выше CEILING dBTP.

Промежуточное — во float: пики выше нуля между шагами не срезаются, режет только
мастер. Подгонку под референс (Matchering) сюда не тащим: это
новый пакет и обещание «как у звезды», которое черновая склейка не сдержит.

Проверка — на слух: ДО (простая сумма дорожек) и ПОСЛЕ одной громкости по LUFS.
Громкое всегда кажется лучше, и без этого сравнение нечестное.

    python -m src.skleyka --mix ВОКАЛ БИТ --out ПАПКА   склейка и пара ДО/ПОСЛЕ одной громкости
    python -m src.skleyka --mix ВОКАЛ БИТ --out ПАПКА --style грязно --design
"""

from __future__ import annotations

import argparse
import array
import contextlib
import json
import math
import re
import secrets
import shutil
import statistics
import subprocess
import sys
import tempfile
import wave
from datetime import timedelta
from pathlib import Path

from . import clips, config, reels, state, telegram

RATE = 44100
# Любой формат на входе: моно становится стерео, частота — 44,1 кГц. Неслышимое
# срезается сразу: замер громкости его считает, а MP3 выбрасывает. В бите
# Little Chicago's Finest ультразвук над 20 кГц завышал громкость на 5 LU —
# вокал встал бы под мусор, а MP3 вышел бы на 5 дБ тише замера.
FORMAT = f"aformat=sample_fmts=flt:sample_rates={RATE}:channel_layouts=stereo,highpass=f=20,lowpass=f=20000"
MP3 = ["-c:a", "libmp3lame", "-b:a", "320k"]
# Середина и бока (M/S): середина — в левом канале, бока — в правом. Фильтр
# с c=FL между MS и LR трогает только середину, с c=FR — только бока.
MS = "pan=stereo|c0=0.5*c0+0.5*c1|c1=0.5*c0-0.5*c1"
LR = "pan=stereo|c0=c0+c1|c1=c0-c1"

# --- вокал ------------------------------------------------------------------
# Низ ниже 90 Гц — гул и хлопки на «п» и «б».
HIGHPASS = "highpass=f=90"
VOCAL_LUFS = -18.0
# Микрофон во входе 1 звуковой карты пишет стереодорожку с голосом в одном
# канале: каналы расходятся больше чем на LOPSIDED дБ — громкий идёт в оба.
LOPSIDED = 6.0
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

# --- бит --------------------------------------------------------------------
# Место под голос: провал BEAT_DIP дБ в полосе 2–4 кГц, где разборчивость, —
# только в середине, где стоит голос, и только пока голос звучит (Гиббс в Sound
# On Sound включает провалы под голос так же). Края бита не тронуты: ширина
# остаётся, а в паузах бит звучит целиком.
BEAT_DIP = -2.0
BEAT_EQ = "equalizer@dip=f=2800:t=o:w=1.3:g=0:c=FL"
# Порог −20 дБ от вокала на VOCAL_LUFS: в строке бит проседает на 1–2 дБ
# и за 0,1 с возвращается в паузе. С порогом −24 дБ сжатый голос проваливал
# бит на 3,3 дБ, а на громких словах — на 5.
DUCK = "sidechaincompress=threshold=0.1:ratio=2:attack=5:release=100"

# --- баланс -----------------------------------------------------------------
# Вокал к биту по EBU R128. Бит без пауз, а у вокала паузы отсекает сам замер,
# так что 0 — голос в строке вровень с битом.
VOCAL_OVER_BEAT = 0.0
# Райдер — как звукорежиссёр с фейдером голоса: громкость голоса окнами 0,4 с
# (EBU R128 M) против бита в те же окна. Где голос отстаёт от бита больше чем
# на RIDE_TARGET, он поднимается до RIDE_MAX дБ (у Waves Vocal Rider по умолчанию
# те же ±6); подъём держится RIDE_HOLD и сглажен на RIDE_SMOOTH, чтобы голос
# не прыгал по слогам, а в паузах голоса возвращается к нулю — иначе поднятыми
# остались бы вдохи и шум. Вниз не ведём: громкие места ровняют компрессоры.
# С одним балансом на весь трек бит перекрывал голос больше чем на 2 дБ в 21–23%
# окон на трёх рэп-треках учебной библиотеки, с райдером — в 3–5%. Простое
# среднее без удержания сглаживало подъём на провале и оставляло 9–13%.
RIDE_TARGET = 0.0
RIDE_MAX = 6.0
RIDE_HOLD = 0.5
RIDE_SMOOTH = 1.0
# Голос звучит в окне, если оно громче общей громкости голоса минус RIDE_GATE LU.
RIDE_GATE = 10.0

# --- стили ------------------------------------------------------------------
# «Грязно»: полоса 300 Гц – 4,5 кГц и перегруз мягким клиппером на +9 дБ.
# Клиппер считает на учетверённой частоте: гармоники выше 22 кГц иначе
# завернулись бы обратно в слышимое свистом.
DIRT = "highpass=f=300,lowpass=f=4500,volume=9dB,asoftclip=type=atan:oversample=4,volume=-9dB"
# «Близко»: третья ступень компрессии, голос ровный, как у самого микрофона.
DENSE = "acompressor=threshold=0.03:ratio=6:attack=3:release=60:knee=4"
# Дабл моно-голосу — по Сениору (Sound On Sound): копии в разные края со сдвигом
# 11 и 13 мс, высота гуляет на ±5 центов (vibrato: глубина 0,5 на 0,4 Гц — замер
# ±5,4 цента), на 15 дБ тише голоса. Второго дубля у артиста нет, и дабл из той же
# записи — старый студийный приём (ADT); без расстройки копия слилась бы
# с голосом гребёнкой.
DOUBLE = (
    "[0:a]highpass=f=150,pan=mono|c0=0.5*c0+0.5*c1,asplit[a][b];"
    "[a]adelay=11,vibrato=f=0.4:d=0.5[l];[b]adelay=13,vibrato=f=0.55:d=0.36[r];"
    "[l][r]amerge=inputs=2[w]"
)
DOUBLE_SHARE = 10 ** (-15 / 20)
# Стиль — набор эффектов, названный по звучанию словом, которое понятно без
# знания сведения: человек, не отличающий компрессор от эквалайзера, выбирает,
# как ему слышится. Не жанр и не «как у X»: чужой звук не копируем.
# Отзвук — (секунды, доля), дилей — (вид, доля), доля — громкость шины
# к сухому голосу. В роликах владелец взял втрое меньше (reels.REVERB_SHARE),
# но там голос один, а здесь под ним плотный бит.
STYLES = {
    "чисто": {"about": "голос сверху, немного воздуха",
              "reverb": (0.8, 0.07), "delay": ("коротко", 0.05)},
    "мелодично": {"about": "автотюн, широкий отзвук и эхо в темп", "autotune": True,
                  "reverb": (1.2, 0.12), "delay": ("в темп", 0.08)},
    "грязно": {"about": "перегруз и узкая полоса", "color": DIRT,
               "reverb": (0.8, 0.04), "delay": ("коротко", 0.05)},
    "близко": {"about": "сухо и плотно, голос у самого уха, с даблом", "dense": True, "double": True},
}
# Автотюн — x42 fat1 из apt-пакета x42-plugins. Проба в Actions 22.09.2026: в ffmpeg
# 6.1 из apt есть и lv2, и ladspa, грузятся и fat1, и autotalent, но fat1 ставит
# ноту точно (ровный синус — ±0,1 Гц от ноты), а autotalent — на 11–25 центов
# ниже: его детектор завышает высоту, и голос звучал бы фальшиво к биту. Скорость
# 0,02 с — самая быстрая у fat1: ретюн у Lil Uzi Vert 5–20 мс, до 50 мс звучит
# естественно (Sound On Sound, Antares). Ноты — тональности бита (scale): без неё
# голос тянется к любому из двенадцати полутонов. Плагин моно, поэтому голос
# сводится в одну дорожку и обратно; задержку в 1056 отсчётов ffmpeg 6.1 не снимает —
# её убирают apad и atrim. Двоеточие в адресе плагина экранировано для обоих уровней
# разбора фильтра. На Маке ffmpeg собран без lv2 — там стиль идёт без автотюна.
AUTOTUNE = (r"apad=pad_len=1056,pan=mono|c0=0.5*c0+0.5*c1,"
            r"lv2=p=http\\://gareus.org/oss/lv2/fat1:c=mode=2|tuning=440|corr=1|filter=0.02|bias=0|fastmode=0|offset=0|{notes},"
            r"pan=stereo|c0=c0|c1=c0,atrim=start_sample=1056,asetpts=N/SR/TB")
NOTES = "до до# ре ре# ми фа фа# соль соль# ля ля# си".split()

# --- саунд-дизайн -----------------------------------------------------------
# Огибающая для сетки бита и строк голоса — по 10 мс.
ENV_RATE = 100
# Голос звучит, пока громче своего почти самого громкого места минус VOICE_RANGE дБ.
VOICE_RANGE = 30.0
# Вдох: первое слово задом наперёд уходит в отзвук на BREATH_SECONDS, отзвук
# разворачивается обратно и нарастает к слову за BREATH_BEATS долей.
BREATH_SECONDS = 2.5
BREATH_BEATS = 2
BREATH_SHARE = 0.5
# Бит до первого слова: за FILTER_BEATS долей закрывается фильтром до FILTER_LOW Гц
# и за OPEN_BEATS долей открывается к сильной доле первого слова.
FILTER_LOW = 400
FILTER_BEATS = 8
OPEN_BEATS = 2
# Броски: последнее слово строки перед паузой длиннее THROW_PAUSE — в дилей в темп,
# не больше THROWS на трек, перед самыми длинными паузами: у инженеров бросков
# 3–4 на трек (Profitt в Sound On Sound), на каждой строке они стали бы кашей.
THROW_PAUSE = 0.4
THROW_WORD = 0.3
THROWS = 4
THROW_SHARE = 0.4
# Остановка плёнки: с последней доли, где бит ещё играет в полную силу, скорость
# падает до нуля за STOP_BEATS долей.
STOP_BEATS = 2

# --- мастер -----------------------------------------------------------------
# Низ ниже 120 Гц — в моно: бока бита и отзвука там только мутят и пропадают
# в телефоне и клубе, где низ из одного динамика.
LOW_MONO = f"{MS},highpass=f=120:c=FR,highpass=f=120:c=FR,{LR}"
# Громкость — в ряду рэп-мастеров (−10…−6 LUFS у инженеров из Mix With
# The Masters и Sound On Sound). Пик −2 dBTP: Spotify требует его от мастера
# громче −14 LUFS, иначе при выравнивании громкости трек исказится.
MASTER_LUFS = -10.0
CEILING = -2.0
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


def _channels(path: Path, chain: str = "") -> list[float]:
    """Громкость каждого канала, дБ RMS. Тишина — −150."""
    err = _stderr("-i", path, "-af", f"{chain}astats=measure_perchannel=RMS_level:measure_overall=none")
    return [max(-150.0, float(db)) for db in re.findall(r"RMS level dB: (-?[\d.]+|-inf)", err)]


def stereo(path: Path, chain: str = "") -> tuple[float, float]:
    """Корреляция каналов и потеря громкости в моно, LU.

    Корреляция — 1 у моно, 0 у несвязанных каналов, меньше нуля — противофаза,
    которая в моно (телефон, колонка) гасит сама себя.
    """
    mid, side = (10 ** (db / 10) for db in _channels(path, f"{chain}{MS},")[:2])
    folded = f"{chain}pan=stereo|c0=0.5*c0+0.5*c1|c1=0.5*c0+0.5*c1,"
    return (mid - side) / (mid + side), loudness(path, chain)[0] - loudness(path, folded)[0]


def _center(vocal: Path) -> str:
    """Голос из одного канала стерео — в оба; иначе ничего."""
    left, right = _channels(vocal, f"{FORMAT},")[:2]
    loud = int(right > left)
    return f"pan=stereo|c0=c{loud}|c1=c{loud}," if abs(left - right) > LOPSIDED else ""


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


def _envelope(path: Path, chain: str = "") -> list[float]:
    """Уровень по 10 мс, дБ: средний модуль сигнала, сведённого в моно."""
    raw = subprocess.run([clips.ffmpeg(), "-v", "error", "-i", str(path), "-af", f"{chain}aresample=4000",
                          "-ac", "1", "-f", "f32le", "-"], capture_output=True, check=True).stdout
    x, step = array.array("f", raw), 4000 // ENV_RATE
    return [20 * math.log10(sum(map(abs, x[i:i + step])) / step + 1e-6) for i in range(0, len(x) - step + 1, step)]


def _rise(path: Path, chain: str) -> list[float]:
    """Удары: рост уровня за 20 мс по 10 мс, к среднему — полосы сравнимы между собой."""
    level = _envelope(path, chain)
    rise = [0.0, 0.0] + [max(0.0, level[i] - level[i - 2]) for i in range(2, len(level))]
    mean = statistics.fmean(rise) or 1.0
    return [r / mean for r in rise]


def grid(beat: Path) -> tuple[float, float]:
    """Сетка бита: длина доли и где первая доля, секунды.

    Меряется минута с начала места, где качает низ (reels.beat_start). Темп — в пределах
    60–120 ударов в минуту: быстрый бит считается вдвое медленнее, и каждая доля
    сетки остаётся сильной. Темп — автокорреляция ударов на долю и на две, три,
    четыре доли вперёд, по всей полосе и по низу, где бочка и 808, одно на другое:
    мягкий бит Coruscate по низу не читается вовсе (низ равен на всех темпах,
    и решает вся полоса), а где бочка держит пульс, решает она. Одна автокорреляция
    по низу с шагом 10 мс дала Coruscate 82,6 вместо 80 — к концу трека эхо ушло бы
    с доли, — поэтому темп и первая доля уточняются гребёнкой с шагом 0,02 удара
    в минуту. Выбирать гребёнкой и сам темп нельзя: на медленной сетке лежат только
    самые громкие удары, и у M.E.R.C. Music она выбрала 80 вместо 107.
    """
    offset = reels.beat_start(beat)
    cut = f"atrim=start={offset:.2f}:duration=60,"
    full, low = _rise(beat, cut), _rise(beat, cut + "lowpass=f=120,lowpass=f=120,")

    def score(rise: list[float]) -> list[float]:
        acf = [sum(a * b for a, b in zip(rise, rise[k:])) for k in range(ENV_RATE * 4 + 2)]
        return [sum(acf[int(m * p)] + (acf[int(m * p) + 1] - acf[int(m * p)]) * (m * p % 1) for m in range(1, 5))
                for p in (60 * ENV_RATE / bpm for bpm in BPM)]

    both = [f * lo for f, lo in zip(score(full), score(low))]
    bpm = BPM[max(range(len(BPM)), key=both.__getitem__)]

    def comb(period: float) -> tuple[float, float, int]:
        return max((statistics.fmean(full[round(s + k * period)] for k in range(int((len(full) - 1 - s) / period) + 1)),
                    period, s) for s in range(int(period)))

    _, period, start = max(comb(60 * ENV_RATE / (bpm + d / 50)) for d in range(-10, 11))
    return period / ENV_RATE, offset + start / ENV_RATE


BPM = [60 + 0.1 * i for i in range(601)]


# Профили тональностей Крумхансла — Кесслер: насколько каждая ступень звучит
# «своей» в мажоре и миноре, от тоники.
MAJOR = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
MINOR = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]


def scale(beat: Path) -> list[int]:
    """Ноты тональности бита, 0 — до: к ним автотюн тянет голос.

    Громкость каждого полутона от до большой октавы до си второй — узкими
    полосами за один проход ffmpeg, по октавам в сумму, и сравнение с профилями
    MAJOR и MINOR на всех двенадцати тониках. Параллельные мажор и минор делят
    одни ноты, так что их путаница автотюну не мешает. Без тональности автотюн
    тянул бы голос к ближайшему из двенадцати полутонов, в том числе чужому биту.
    """
    notes = range(36, 84)
    graph = (f"[0:a]pan=mono|c0=0.5*c0+0.5*c1,asplit={len(notes)}" + "".join(f"[i{n}]" for n in notes) + ";"
             + "".join(f"[i{n}]" + f"bandpass=f={440 * 2 ** ((n - 69) / 12):.2f}:t=q:w=25," * 2
                       + f"astats@{n}=measure_perchannel=none:measure_overall=RMS_level[o{n}];" for n in notes)
             + "".join(f"[o{n}]" for n in notes) + f"amix=inputs={len(notes)}")
    chroma = [0.0] * 12
    for n, db in re.findall(r"\[astats@(\d+) @ \w+\] RMS level dB: (-?[\d.]+)", _stderr("-i", beat, "-filter_complex", graph)):
        chroma[int(n) % 12] += 10 ** (float(db) / 10)
    _, tonic, steps = max((statistics.correlation([chroma[(tonic + i) % 12] for i in range(12)], profile), tonic, steps)
                          for tonic in range(12)
                          for profile, steps in ((MAJOR, (0, 2, 4, 5, 7, 9, 11)), (MINOR, (0, 2, 3, 5, 7, 8, 10))))
    return sorted((tonic + step) % 12 for step in steps)


def _on_grid(t: float, beat: tuple[float, float], how=round) -> float:
    """Доля сетки у момента t: ближайшая (round), следующая (math.ceil) или прошлая (math.floor)."""
    length, start = beat
    return start + how((t - start) / length) * length


def _lines(level: list[float]) -> list[tuple[float, float]]:
    """Строки голоса по огибающей: (начало, конец), секунды. Паузы короче
    THROW_PAUSE — внутри строки, щелчки короче 0,1 с — не голос."""
    top, lines = sorted(level)[int(len(level) * 0.95)], []
    for i, db in enumerate(level):
        if db <= top - VOICE_RANGE:
            continue
        if lines and i - lines[-1][1] < THROW_PAUSE * ENV_RATE:
            lines[-1][1] = i + 1
        else:
            lines.append([i, i + 1])
    return [(a / ENV_RATE, b / ENV_RATE) for a, b in lines if b - a >= 0.1 * ENV_RATE]


def _gain_track(points: list[tuple[float, float]], seconds: float, path: Path) -> Path:
    """Огибающая громкости дорожкой WAV для amultiply: точки (секунда, дБ),
    между ними — по прямой, 1000 отсчётов в секунду.

    WAV из stdlib только целочисленный, а усиление бывает больше единицы,
    поэтому в файле оно вдвое меньше, а _apply умножает обратно — запас до +6 дБ.
    """
    values, j = array.array("h"), 0
    for n in range(int(seconds * 1000) + 1000):
        t = n / 1000
        while j + 1 < len(points) and points[j + 1][0] <= t:
            j += 1
        (t0, g0), (t1, g1) = points[j], points[min(j + 1, len(points) - 1)]
        db = g0 if t1 <= t0 or t <= t0 else g0 + (g1 - g0) * min(1.0, (t - t0) / (t1 - t0))
        values.append(min(32767, round(16384 * 10 ** (db / 20))))
    with wave.open(str(path), "wb") as track:
        track.setnchannels(1)
        track.setsampwidth(2)
        track.setframerate(1000)
        track.writeframes(values.tobytes())
    return path


def _apply(source: Path, track: Path, dest: Path, before: str = "anull") -> Path:
    """Громкость source по огибающей _gain_track. Огибающая короче звука обрежет его."""
    _ffmpeg("-i", source, "-i", track, "-filter_complex",
            f"[0:a]{before}[s];[1:a]aresample={RATE},pan=stereo|c0=c0|c1=c0[g];[s][g]amultiply,volume=2",
            *reels.VOICE_CODEC, dest)
    return dest


def _gaps(vocal: Path, beat: Path, lift: float = 0.0) -> tuple[list[float], list[float | None]]:
    """Голос против бита окнами 0,4 с через каждые 0,1 с: середина окна
    и разница в LU; None — голос в этом окне не звучит."""
    whole, voice = reels.meter(vocal)
    _, under = reels.meter(beat)
    n = min(len(voice), len(under))
    return ([voice[i][0] - 0.2 for i in range(n)],
            [voice[i][1] + lift - under[i][1] if voice[i][1] > whole - RIDE_GATE else None for i in range(n)])


def masked(gaps: list[float | None]) -> float:
    """Доля окон с голосом, где бит громче него больше чем на 2 дБ, %."""
    sung = [gap for gap in gaps if gap is not None]
    return 100 * sum(gap < -2 for gap in sung) / max(len(sung), 1)


def _ride(dry: Path, beat: Path, lift: float, work: Path) -> Path:
    """Голос с общим подъёмом lift и райдером (RIDE_*) — в work/vocal-ride.wav."""
    times, gaps = _gaps(dry, beat, lift)
    want = [0.0 if gap is None else max(0.0, min(RIDE_MAX, RIDE_TARGET - gap)) for gap in gaps]
    hold, smooth = round(RIDE_HOLD * 5), round(RIDE_SMOOTH * 5)
    peak = [max(want[max(0, i - hold):i + hold + 1]) for i in range(len(want))]
    ride = [statistics.fmean(peak[max(0, i - smooth):i + smooth + 1]) for i in range(len(peak))]
    track = _gain_track(list(zip(times, ride)), clips.probe_seconds(dry) + 1, work / "ride.wav")
    out = _apply(dry, track, work / "vocal-ride.wav", f"volume={lift:.2f}dB")
    print(f"  райдер: бит громче голоса больше чем на 2 дБ в {masked(gaps):.0f}% окон → "
          f"{masked(_gaps(out, beat)[1]):.0f}%, голос поднят в среднем на {statistics.fmean(ride):.1f} дБ")
    return out


def _reverb(seconds: float, before: str = "highpass=f=300,lowpass=f=7000,adelay=25|25", after: str = "anull") -> str:
    """Отзвук, как reels.REVERB, нужной длины: свёртка с розовым шумом, гаснущим
    на 60 дБ за seconds, у каналов шум свой — отзвук вокруг голоса."""
    return (
        f"anoisesrc=r={RATE}:d={seconds}:c=pink:seed=1[n1];"
        f"anoisesrc=r={RATE}:d={seconds}:c=pink:seed=2[n2];"
        f"[n1][n2]amerge=inputs=2,asetnsamples=64,volume='exp(-6.9*t/{seconds})':eval=frame[ir];"
        f"[0:a]{before}[in];[in][ir]afir,{after}[w]"
    )


def _tempo_delay(length: float, under: float | None = None) -> str:
    """Дилей в темп от стены к стене: слева повторы через четверть, справа — через
    восьмую (главный и второй у инженеров Sound On Sound), по три с затуханием;
    на возврат — полоса 200 Гц – 5 кГц (Элмхёрст в Mix With The Masters).

    under — громкость голоса, LUFS: под голосом дилей приседает на 8–10 дБ
    (2:1, атака сразу, отпуск 150 мс, как у Сениора) и раскрывается в паузах.
    Иначе повторы ложились бы на следующие слова и мутили их."""
    head, tail = "[0:a]", "[w]"
    if under is not None:
        head = "[0:a]asplit[x][k];[x]"
        tail = f"[d];[d][k]sidechaincompress=threshold={10 ** ((under - 18) / 20):.4f}:ratio=2:attack=0.01:release=150[w]"
    return (
        f"{head}highpass=f=200,lowpass=f=5000,pan=mono|c0=0.5*c0+0.5*c1,asplit[a][b];"
        + "".join(f"[{side}]aecho=in_gain=0:out_gain=1:delays={d:.0f}|{2 * d:.0f}|{3 * d:.0f}"
                  f":decays=0.6|0.36|0.2[{side}{side}];" for side, d in (("a", 1000 * length), ("b", 500 * length)))
        + "[aa][bb]amerge=inputs=2" + tail
    )


def _autotune(beat: Path) -> str:
    """Автотюн к нотам тональности бита; пусто — плагина в этой сборке ffmpeg нет."""
    probe = subprocess.run([clips.ffmpeg(), "-v", "error", "-f", "lavfi", "-i", f"anullsrc=r={RATE}:cl=stereo",
                            "-t", "0.1", "-af", AUTOTUNE.format(notes="m00=1"), "-f", "null", "-"], capture_output=True)
    if probe.returncode:
        print("  автотюн: нет в этой сборке ffmpeg, стиль идёт без него")
        return ""
    notes = scale(beat)
    print("  автотюн к нотам бита: " + " ".join(NOTES[n] for n in notes))
    return AUTOTUNE.format(notes="|".join(f"m{n:02d}={int(n in notes)}" for n in range(12)))


def _dip(lines: list[tuple[float, float]], path: Path) -> str:
    """Провал бита под голос (BEAT_DIP) — командами фильтру: пока голос звучит,
    туда и обратно за 50 мс, чтобы не щёлкало."""
    steps = [f"{max(0.0, start - 0.05 + 0.01 * k):.2f} equalizer@dip g {BEAT_DIP * k / 5:.2f};\n"
             f"{end + 0.01 * k:.2f} equalizer@dip g {BEAT_DIP * (1 - k / 5):.2f};"
             for start, end in lines for k in range(1, 6)]
    path.write_text("\n".join(steps))
    return f"asendcmd=f='{path}'," if steps else ""


def _breath(voice: Path, first: float, beat: tuple[float, float], work: Path) -> Path | None:
    """Вдох перед первым словом: слово задом наперёд уходит в отзвук, отзвук
    разворачивается обратно и нарастает к слову с доли за BREATH_BEATS до него."""
    length = beat[0]
    start = _on_grid(first - BREATH_BEATS * length, beat)
    swell = first - start
    if start < 0 or swell < length:
        return None
    out = work / "breath.wav"
    _ffmpeg("-i", voice, "-filter_complex", _reverb(
        BREATH_SECONDS,
        f"atrim=start={first:.3f}:end={first + length:.3f},asetpts=PTS-STARTPTS,areverse,apad=pad_dur={BREATH_SECONDS}",
        f"areverse,atrim=start={BREATH_SECONDS - swell:.3f}:end={BREATH_SECONDS:.3f},asetpts=PTS-STARTPTS,"
        f"afade=t=in:d={swell:.3f},afade=t=out:st={swell - 0.03:.3f}:d=0.03,adelay={1000 * start:.0f}|{1000 * start:.0f}"),
        "-map", "[w]", "-ar", RATE, *reels.VOICE_CODEC, out)
    return out


def _opening(beat_file: Path, first: float, beat: tuple[float, float], work: Path) -> Path:
    """Бит до первого слова — из-под фильтра: за FILTER_BEATS долей закрывается
    до FILTER_LOW Гц за одну долю и за OPEN_BEATS долей открывается к сильной
    доле первого слова. Слово с первой секунды — бит как есть."""
    length = beat[0]
    opened = _on_grid(first - 0.1, beat, math.ceil)
    sweep = opened - OPEN_BEATS * length
    if sweep < length:
        return beat_file
    shut = max(0.0, _on_grid(opened - FILTER_BEATS * length, beat))
    closed = shut + length if shut else 0.0
    steps = []
    for n in range(int((opened - shut) / 0.02)):
        t = shut + n * 0.02
        low = (FILTER_LOW * (20000 / FILTER_LOW) ** ((t - sweep) / (opened - sweep)) if t >= sweep
               else 20000 * (FILTER_LOW / 20000) ** ((t - shut) / length) if t < closed else FILTER_LOW)
        steps.append(f"{n * 0.02:.2f} lowpass@open f {low:.0f};")
    (work / "opening.cmd").write_text("\n".join(steps))
    out, parts = work / "beat-open.wav", [f"atrim=start={shut:.4f}:end={opened:.4f},asetpts=PTS-STARTPTS,"
                                          f"asendcmd=f='{work / 'opening.cmd'}',lowpass@open=f={20000 if shut else FILTER_LOW}:t=q:w=1.2",
                                          f"atrim=start={opened:.4f},asetpts=PTS-STARTPTS"]
    if shut:
        parts.insert(0, f"atrim=end={shut:.4f}")
    _ffmpeg("-i", beat_file, "-filter_complex",
            f"[0:a]asplit={len(parts)}{''.join(f'[i{n}]' for n in range(len(parts)))};"
            + "".join(f"[i{n}]{part}[o{n}];" for n, part in enumerate(parts))
            + "".join(f"[o{n}]" for n in range(len(parts))) + f"concat=n={len(parts)}:v=0:a=1",
            *reels.VOICE_CODEC, out)
    return out


def _throws(voice: Path, lines: list[tuple[float, float]], length: float, work: Path) -> Path | None:
    """Броски: последнее слово строки перед самыми длинными паузами — в дилей в темп."""
    if not lines:
        return None
    pauses = [(lines[i + 1][0] if i + 1 < len(lines) else math.inf) - end for i, (_, end) in enumerate(lines)]
    ends = sorted(end for _, (_, end) in sorted(zip(pauses, lines), reverse=True)[:THROWS])
    print("  броски: " + ", ".join(f"{end:.1f}" for end in ends) + " с")
    points = [(0.0, -120.0)]
    for end in ends:
        points += [(end - THROW_WORD - 0.01, -120.0), (end - THROW_WORD, 0.0), (end + 0.03, 0.0), (end + 0.04, -120.0)]
    send = _apply(voice, _gain_track(points, clips.probe_seconds(voice) + 1, work / "throw.wav"), work / "throw-send.wav")
    out = work / "throws.wav"
    _ffmpeg("-i", send, "-filter_complex", _tempo_delay(length), "-map", "[w]", "-ar", RATE, *reels.VOICE_CODEC, out)
    return out


def _stop_at(beat_file: Path, lines: list[tuple[float, float]], beat: tuple[float, float]) -> float | None:
    """Доля для остановки плёнки — в конце последнего куска, где бит играет
    в полную силу хотя бы STOP_BEATS долей подряд, и после последней строки.
    Одиночный финальный удар после тихой концовки куском не считается:
    в Little Chicago's Finest плёнка тормозила именно его."""
    _, trace = reels.meter(beat_file)
    loud = sorted(m for _, m, _ in trace)[int(len(trace) * 0.9)] - 6
    runs = []
    for t, m, _ in trace:
        if m < loud:
            continue
        if runs and t - runs[-1][1] < 0.15:
            runs[-1][1] = t
        else:
            runs.append([t, t])
    full = [end - 0.2 for start, end in runs if end - start >= STOP_BEATS * beat[0]]
    at = _on_grid(full[-1] - STOP_BEATS * beat[0] / 2, beat, math.floor) if full else 0.0
    return at if lines and at > lines[-1][1] else None


def _tape_stop(master: Path, at: float, length: float, work: Path) -> None:
    """Остановка плёнки с доли at: скорость падает до нуля за STOP_BEATS долей, дальше
    трек кончается. ffmpeg меняет скорость только на весь файл, поэтому хвост
    читается заново с плавающей скоростью здесь же."""
    span = STOP_BEATS * length
    raw = subprocess.run([clips.ffmpeg(), "-v", "error", "-ss", f"{at:.4f}", "-t", f"{span:.4f}", "-i", str(master),
                          "-f", "f32le", "-ac", "2", "-"], capture_output=True, check=True).stdout
    x, tail, pos, total = array.array("f", raw), array.array("f"), 0.0, int(span * RATE)
    for n in range(total):
        i = int(pos)
        if 2 * i + 3 >= len(x):
            break
        frac = pos - i
        tail.extend((x[2 * i] * (1 - frac) + x[2 * i + 2] * frac, x[2 * i + 1] * (1 - frac) + x[2 * i + 3] * frac))
        pos += 1 - n / total
    (work / "stop.raw").write_bytes(tail.tobytes())
    stopped = work / "stopped.wav"
    _ffmpeg("-i", master, "-f", "f32le", "-ar", RATE, "-ac", 2, "-i", work / "stop.raw", "-filter_complex",
            f"[0:a]atrim=end={at:.4f}[a];[1:a]afade=t=out:st={len(tail) / 2 / RATE - 0.02:.4f}:d=0.02[b];"
            "[a][b]concat=n=2:v=0:a=1", "-c:a", "pcm_s24le", stopped)
    stopped.replace(master)


def mix(vocal: Path, beat: Path, out: Path, style: str = "чисто", design: bool = False,
        voice: float = 0.0, echo: float = 0.0) -> Path:
    """Склейка в out/skleyka.wav, промежуточное — в out/work. voice — голос к биту,
    echo — отзвук и дилей к своей доле, оба в дБ: ручки бота «громче/тише» и «эха»."""
    look, work = STYLES[style], out / "work"
    work.mkdir(parents=True, exist_ok=True)
    print(f"  стиль «{style}»: {look['about']}" + (", саунд-дизайн" if design else ""))

    clean = f"{FORMAT},{_center(vocal)}{HIGHPASS}"
    if look.get("autotune") and (tune := _autotune(beat)):
        clean += f",{tune}"
    squeezed, dry = work / "vocal-comp.wav", work / "vocal.wav"
    _ffmpeg("-i", vocal, "-af", f"{clean},volume={VOCAL_LUFS - loudness(vocal, clean + ',')[0]:.2f}dB,{VOCAL_CHAIN}"
            + (f",{DENSE}" if look.get("dense") else ""), *reels.VOICE_CODEC, squeezed)
    _ffmpeg("-i", squeezed, "-af", _equalizer(squeezed) + DEESSER + (f",{look['color']}" if "color" in look else ""),
            *reels.VOICE_CODEC, dry)
    sung, lines = loudness(dry)[0], _lines(_envelope(dry))

    # Противофаза — по слышимой полосе: в ультразвуке и на самом низу бывает что угодно.
    heard = f"{FORMAT},highpass=f=60,lowpass=f=12000,"
    width = stereo(beat, heard)[0]
    flip = "pan=stereo|c0=c0|c1=-1*c1," if width < 0 else ""
    ducked = work / "beat.wav"
    _ffmpeg("-i", beat, "-i", dry, "-filter_complex",
            f"[0:a]{FORMAT},{flip}{MS},{_dip(lines, work / 'dip.cmd')}{BEAT_EQ},{LR}[b];"
            f"[1:a]volume={VOCAL_LUFS - sung:.2f}dB[v];[b][v]{DUCK}",
            *reels.VOICE_CODEC, ducked)
    print(f"  бит: корреляция каналов {width:+.2f}" + (", один канал перевёрнут" if flip else ""))
    ridden = _ride(dry, ducked, loudness(ducked)[0] + VOCAL_OVER_BEAT + voice - sung, work)
    level = loudness(ridden)[0]

    rhythm = grid(beat) if design or look.get("delay", ("",))[0] == "в темп" else None
    if rhythm:
        print(f"  темп {60 / rhythm[0]:.1f} ударов в минуту, первая доля {rhythm[1]:.2f} с")
    sends = []
    if "reverb" in look:
        seconds, share = look["reverb"]
        sends.append(("reverb", _reverb(seconds), share))
    if "delay" in look:
        kind, share = look["delay"]
        sends.append(("delay", reels.DELAY if kind == "коротко" else _tempo_delay(rhythm[0], level), share))
    if look.get("double") and stereo(dry)[0] > 0.98:
        sends.append(("double", DOUBLE, DOUBLE_SHARE))
    wets = []
    for name, graph, share in sends:
        wet = work / f"{name}.wav"
        _ffmpeg("-i", ridden, "-filter_complex", graph, "-map", "[w]", "-ar", RATE, *reels.VOICE_CODEC, wet)
        wets.append((wet, share if name == "double" else share * 10 ** (echo / 20)))
    design = design and bool(lines)
    if design:
        print(f"  саунд-дизайн: первое слово {lines[0][0]:.2f} с")
        ducked = _opening(ducked, lines[0][0], rhythm, work)
        wets += [(wet, share) for wet, share in ((_breath(ridden, lines[0][0], rhythm, work), BREATH_SHARE),
                                                 (_throws(ridden, lines, rhythm[0], work), THROW_SHARE)) if wet]
    parts = [(ridden, 0.0), (ducked, 0.0)] + [(wet, level + 20 * math.log10(share) - loudness(wet)[0]) for wet, share in wets]
    total = work / "sum.wav"
    _ffmpeg(*(arg for part, _ in parts for arg in ("-i", part)), "-filter_complex",
            "".join(f"[{n}:a]volume={gain:.2f}dB[s{n}];" for n, (_, gain) in enumerate(parts))
            + "".join(f"[s{n}]" for n in range(len(parts)))
            + f"amix=inputs={len(parts)}:duration=longest:normalize=0",
            *reels.VOICE_CODEC, total)

    # Клиппер и ограничитель съедают часть громкости, поэтому подъём подбирается
    # замером. Пик волны лежит между отсчётами и на 44,1 кГц выходит до дБ выше
    # порога, поэтому оба работают на учетверённой частоте. Клиппер режет по нулю,
    # и сигнал к нему подводится так, чтобы ноль пришёлся на CLIP дБ над порогом.
    master, push, limit = out / "skleyka.wav", MASTER_LUFS - loudness(total)[0], CEILING - 0.3
    for _ in range(6):
        _ffmpeg("-i", total, "-af",
                f"{LOW_MONO},volume={push - limit - CLIP:.2f}dB,aresample={4 * RATE},asoftclip=type=hard,"
                f"volume={limit + CLIP:.2f}dB,"
                f"alimiter=limit={10 ** (limit / 20):.4f}:attack=5:release=150:asc=1:level=0:latency=1,"
                f"aresample={RATE}",
                "-c:a", "pcm_s24le", master)
        level, peak = loudness(master)
        if abs(level - MASTER_LUFS) < 0.3 and peak <= CEILING:
            break
        push += MASTER_LUFS - level
        # Ровно на превышение порог сходится к потолку снизу бесконечно — с запасом 0,1 дБ.
        limit -= peak - CEILING + 0.1 if peak > CEILING else 0.0
    if design and (at := _stop_at(ducked, lines, rhythm)) is not None:
        _tape_stop(master, at, rhythm[0], work)
        print(f"  остановка плёнки с {at:.2f} с")
    corr, loss = stereo(master)
    print(f"  мастер {level:.1f} LUFS, пик {peak:.1f} dBTP, подъём {push:+.1f} дБ; "
          f"корреляция каналов {corr:+.2f}, в моно тише на {loss:.1f} LU")
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
    print(f"  ДО и ПОСЛЕ на {level:.1f} LUFS; " + ", ".join(
        f"{name}: корреляция {corr:+.2f}, в моно −{loss:.1f} LU"
        for name, (corr, loss) in (("ДО", stereo(plain)), ("ПОСЛЕ", stereo(master)))))
    return pair


# ─────────────────────────── части голоса ───────────────────────────
#
# Даблы, бэки и эдлибы, присланные отдельно, не сваливаются в главный голос: у каждой
# роли у инженеров своё место (docs/research/2026-09-22/zvukorezhissura.md, раздел 6).
# Даблы тише и суше ведущего, низа срезано больше, эсок нет (KRUG, Podlesny Twins), и ведёт
# их тот же райдер — они идут за словами ведущего; два и больше — по краям на одном уровне
# (Сениор), один — в центре под ведущим. Бэки — очень широко (Goldberg) и дальше, в отзвук;
# эдлибы — по краям и в эхо: им можно меньше внятности и больше эффектов (Hoffman, Waves).
# Цифр громкости у инженеров нет, только «достаточно тихо» (KRUG): дБ к ведущему — выбор
# склейки. Одна дорожка бэков или эдлибов расходится в стороны расширителем Сениора (DOUBLE)
# без центра — центр остаётся ведущему (Heldens). reverb и delay — посыл к доле ведущего, раз.
PARTS = {
    "дабл": {"cut": 180, "gain": -8.0, "pan": 0.8, "deess": "deesser=i=0.8", "reverb": 0.0, "delay": 0.0},
    "бэк": {"cut": 200, "gain": -10.0, "pan": 0.9, "deess": DEESSER, "reverb": 2.0, "delay": 0.0},
    "эдлиб": {"cut": 200, "gain": -6.0, "pan": 0.7, "deess": DEESSER, "reverb": 1.0, "delay": 2.0},
}


def _pan(position: float) -> str:
    """Моно — в точку панорамы от −1 (левый край) до 1 с постоянной мощностью."""
    angle = (position + 1) * math.pi / 4
    return f"pan=stereo|c0={math.cos(angle):.4f}*c0|c1={math.sin(angle):.4f}*c0"


def voices(parts: list[tuple[str, Path]], level: float, ride: Path | None, work: Path) -> list[tuple[Path, float, str]]:
    """Части голоса сухими дорожками на своих местах: [(файл, поправка громкости в сумме, роль)].

    Цепочка — как у ведущего: срез, громкость к VOCAL_LUFS, компрессия, тембр по замеру,
    де-эссер своей роли; дальше — своя точка панорамы и своя громкость к ведущему level."""
    placed = []
    for n, (part, path) in enumerate(parts):
        look, same = PARTS[part], [i for i, (other, _) in enumerate(parts) if other == part]
        chain = f"{FORMAT},{_center(path)}highpass=f={look['cut']},pan=mono|c0=0.5*c0+0.5*c1"
        squeezed, dry = work / f"part{n}-comp.wav", work / f"part{n}.wav"
        _ffmpeg("-i", path, "-af", f"{chain},volume={VOCAL_LUFS - loudness(path, chain + ',')[0]:.2f}dB,{VOCAL_CHAIN}",
                *reels.VOICE_CODEC, squeezed)
        tone = f"{_equalizer(squeezed)}{look['deess']}"
        if len(same) == 1 and part != "дабл":
            _ffmpeg("-i", squeezed, "-filter_complex", f"[0:a]{tone}[t];" + DOUBLE.replace("[0:a]", "[t]"),
                    "-map", "[w]", "-ar", RATE, *reels.VOICE_CODEC, dry)
        else:
            position = 0.0 if len(same) == 1 else look["pan"] * (1 if same.index(n) % 2 == 0 else -1)
            _ffmpeg("-i", squeezed, "-af", f"{tone},{_pan(position)}", *reels.VOICE_CODEC, dry)
        if part == "дабл" and ride:
            dry = _apply(dry, ride, work / f"part{n}-ride.wav")
        placed.append((dry, level + look["gain"] - loudness(dry)[0], part))
        print(f"  {part}: {'в стороны' if len(same) == 1 and part != 'дабл' else 'панорама'}, "
              f"{look['gain']:+.0f} дБ к ведущему")
    return placed


def _sends(ridden: Path, placed: list[tuple[Path, float, str]], key: str, work: Path) -> Path:
    """Что уходит в отзвук или дилей: ведущий и части со своими посылами (PARTS).
    Ни одна часть туда не посылает — просто ведущий."""
    going = [(path, gain + 20 * math.log10(PARTS[part][key])) for path, gain, part in placed if PARTS[part][key]]
    if not going:
        return ridden
    source = work / f"send-{key}.wav"
    inputs = [(ridden, 0.0), *going]
    _ffmpeg(*(arg for path, _ in inputs for arg in ("-i", path)), "-filter_complex",
            "".join(f"[{n}:a]volume={gain:.2f}dB[s{n}];" for n, (_, gain) in enumerate(inputs))
            + "".join(f"[s{n}]" for n in range(len(inputs))) + f"amix=inputs={len(inputs)}:duration=longest:normalize=0",
            *reels.VOICE_CODEC, source)
    return source


# ─────────────────────────── бот ───────────────────────────
#
# /skleyka или ссылка ?start=skleyka открывает заявку, дорожки приходят файлами —
# альбомом или по одной. Поллер у бота один (src/moderate.py), и считать сам он
# не может: пока идёт ffmpeg, бот не отвечал бы никому. Поэтому склейка — отдельный
# процесс (python -m src.skleyka --job ФАЙЛ): он сам качает дорожки, склеивает
# и шлёт готовое, а дежурство на каждом круге (tick) смотрит, кончил ли он,
# и даёт ход следующей заявке. Склейка одна за раз: две разом делили бы машину
# и шли бы обе вдвое дольше.

# Инструкции почти нет: человек выбирает кнопкой, как пришлёт, а дальше бот сам
# спрашивает дорожки по одной — «шаг 1 из 2, пришли вокал». Роль дорожки — это вопрос,
# на который она пришла ответом, и называть файлы не нужно (владелец, 22.09.2026:
# «очень много текста, ни хрена не понятно и ни одной кнопки»). Стиль и ручки — после,
# под готовым треком.
ASK_MARK = "· пришли"
INTRO = ("🎛 <b>СКЛЕЙКА</b> — сведу вокал с битом в готовый трек. Бесплатно, автоматом, за несколько минут.\n\n"
         "Как пришлёшь?")
PICK = "Отметь, что у тебя есть отдельно, — потом попрошу каждую дорожку по очереди."
# Характер звука — до склейки: его выбирают, не слыша результата. Громкость голоса и эхо —
# поправки «чуть громче, чем сейчас», их без прослушки не выбрать: они кнопками под треком.
STYLE = "Дорожки есть. Какой звук?"
# Не ответил на вопрос о звуке — склейка идёт как лучше, чтобы человек не ждал зря.
STYLE_WAIT = 180
MORE = "Есть: {names}. Ещё файл — или дальше."
ACCEPTED = "Принял: {parts}. Склеиваю — пришлю минут через {minutes}."
EXPIRED = "Дорожки не пришли до конца — заявку закрыл. Начать заново — /skleyka."
OLD = "Эта заявка уже закрыта. Начать заново — /skleyka."
CANCELLED = "Отменил. Захочешь склеить — /skleyka."
LIMIT = "Склеек в сутки — две на человека. Следующую можно с {time} по Москве."
TOO_BIG = f"«{{name}}» больше {config.SKLEYKA_MAX_MB} МБ. Пришли FLAC или MP3 320 — они легче."
BAD = "«{name}» не читается. Пришли WAV, FLAC или MP3 — /skleyka."
SILENT = "В «{name}» тишина — похоже, выгрузилась пустая дорожка. Пришли заново — /skleyka."
LENGTH = "Бит длится {length}, а склеиваю треки от 1 до 8 минут. Другой — /skleyka."
NEED = "Нужны и вокал, и бит, а {what}. Пришли все дорожки заново — /skleyka."
FAILED = "Не склеилось — что-то сломалось у меня. Попробуй ещё раз: /skleyka. Лимит на сутки не потрачен."
STALE = "Эта склейка устарела — пришли дорожки заново: /skleyka."
NO_TWEAKS = "Пересборки этого трека кончились. Новая склейка — /skleyka."
SAME = "Так уже и есть."
REBUILD = "Пересобираю: {what}. Пришлю минут через {minutes}."
READY = ("🎛 <b>Склейка готова</b> — {look}.\n{parts}.\n{note}"
         "Это черновая склейка автоматом, не студия. Громкость как у релизов; WAV для площадок — следующим файлом.")
MISMATCH = "Дорожки разной длины ({a} и {b}): если голос уехал от бита — выгрузи обе с самого начала проекта.\n"
GUESSED = "Вокал и бит пришли одним альбомом — где что, понял по звуку. Перепутал — жми «↔ поменять».\n"
TUNE = ("Не так? Подкрути — пересоберу{left}.\n\n"
        "Выложишь трек на площадки — жми «В ОТБОР»: он выйдет в канале с твоим именем.")

# Альбом в Telegram — до десяти файлов: хватает на вокал, даблы, бэки, эдлибы и бит по частям.
MAX_PARTS = 10
# Альбом приходит пачкой: следующий вопрос или «есть, ещё — или дальше» — когда QUIET секунд
# не приходит новых файлов. Тишина DRAFT_MINUTES — заявка закрыта.
QUIET = 2
DRAFT_MINUTES = 30
# Сколько минут занимает склейка на машине дежурства: скачать, свести, отправить.
MINUTES = 4
# Склейку, оборванную концом смены, следующая доделывает, если ей меньше часа;
# склейку, что идёт дольше JOB_MINUTES, дежурство снимает.
RESUME_MINUTES = 60
JOB_MINUTES = 20
# Кнопки пересборки живут неделю: номера сообщений с дорожками дольше хранить незачем.
TRACK_DAYS = 7
# Ручки: голос к биту и доля эха, дБ, — шаг и пределы.
VOICE_STEP, VOICE_LIMIT = 2.0, 6.0
ECHO_STEP, ECHO_LIMITS = 4.0, (-12.0, 8.0)
KNOBS = {"style": "чисто", "design": False, "voice": 0.0, "echo": 0.0, "swap": False}
# Кнопки идут через service.handle_callback: префикс service.CALLBACK_PREFIX
# и действие sk. Импортировать service отсюда нельзя — он импортирует нас.
PREFIX = "s:sk:"
MODES = [[{"text": "🎤 Вокал + бит", "callback_data": f"{PREFIX}m:1"}],
         [{"text": "🎚 По дорожкам — даблы, бэки, инструменты", "callback_data": f"{PREFIX}m:2"}]]
# Части в том порядке, в каком бот их спрашивает; что можно прислать несколькими файлами.
ORDER = ("вокал", "дабл", "бэк", "эдлиб", "бит", "барабаны", "бас", "музыка")
MULTI = ("дабл", "бэк", "эдлиб", "барабаны", "бас", "музыка")
INSTRUMENTS = ("барабаны", "бас", "музыка")
LABELS = {"вокал": "Лид-вокал", "дабл": "Даблы", "бэк": "Бэки", "эдлиб": "Эдлибы",
          "бит": "Бит целиком", "барабаны": "Барабаны", "бас": "Бас / 808", "музыка": "Мелодия"}
TOGGLES = {"d": "дабл", "b": "бэк", "a": "эдлиб", "w": "бит", "k": "барабаны", "s": "бас", "m": "музыка"}
ASKS = {"вокал": "вокал", "дабл": "даблы", "бэк": "бэки", "эдлиб": "эдлибы", "бит": "бит",
        "барабаны": "барабаны", "бас": "бас или 808", "музыка": "мелодию — всё из бита, кроме барабанов и баса"}
# Стиль словами для кнопки — коротко: полное about не влезает в кнопку на телефоне.
STYLE_HINTS = {"чисто": "голос сверху", "мелодично": "автотюн", "грязно": "перегруз", "близко": "сухо, плотно"}
NAMES = {"вокал": "вокал", "дабл": "даблы", "бэк": "бэки", "эдлиб": "эдлибы", "бит": "бит",
         "барабаны": "барабаны", "бас": "бас", "музыка": "мелодия"}

# Чья дорожка — по имени файла, как их называют в проектах. Сначала частные роли
# («бэк», «808»), потом общие («вокал», «бит»): в «lead synth» есть «lead», но это синт.
# Слово сверяется с началом: «hat» в «whats my name» — не хэт.
ROLES = (
    ("эдлиб", ("эдлиб", "адлиб", "adlib", "ad lib", "adl")),
    ("дабл", ("дабл", "double", "dbl", "dub")),
    ("бэк", ("бэк", "бек", "back", "bgv", "bvox", "harm", "гармон", "хор", "подпев")),
    ("барабаны", ("drum", "барабан", "kick", "бочк", "snare", "снейр", "снэр", "clap", "hat", "hihat", "хэт", "хет",
                  "perc", "перкус")),
    ("бас", ("808", "bass", "бас", "sub", "саб")),
    ("музыка", ("melod", "мелод", "keys", "piano", "пиан", "synth", "синт", "pad", "пэд", "guitar", "гитар", "sample",
                "сэмпл", "семпл", "string", "loop", "луп", "chord", "аккорд", "music", "музык")),
    ("вокал", ("вокал", "vocal", "vox", "voc", "acapella", "acappella", "a cappella", "акапел", "голос", "lead",
               "лид", "rap", "рэп", "реп")),
    ("бит", ("бит", "beat", "минус", "instr", "инстр", "karaoke", "караоке")),
)
VOCAL_SIDE = ("вокал", "дабл", "бэк", "эдлиб")
AUDIO_EXT = (".wav", ".wave", ".flac", ".mp3", ".m4a", ".aac", ".aif", ".aiff", ".ogg", ".opus", ".mp4")


def role(name: str) -> str:
    """Роль дорожки по имени файла; пусто — имя не говорит."""
    words = re.findall(r"[a-zа-я0-9]+", name.lower().replace("ё", "е"))
    joined = " ".join(words)
    return next((part for part, keys in ROLES
                 if any(key in joined if " " in key else any(w.startswith(key) for w in words) for key in keys)), "")


def _low(path: Path) -> float:
    """Низ ниже 120 Гц к всей громкости, дБ: у бита там бочка и 808, у голоса почти пусто."""
    mono = f"{FORMAT},pan=mono|c0=0.5*c0+0.5*c1,"
    return _channels(path, f"{mono}lowpass=f=120,lowpass=f=120,")[0] - _channels(path, mono)[0]


def sides(files: list[tuple[str, Path]], swap: bool = False) -> tuple[list[tuple[str, Path, str]], bool]:
    """Роль каждой дорожки: (имя, путь, роль), и понят ли вокал по звуку, а не по имени.

    Имя не сказало — решает низ: из безымянных вокал та, где его меньше всего, а если
    вокал назван, безымянные уходят в бит. swap меняет вокал и бит местами — кнопка
    «поменять», когда их всего две."""
    parts = [(name, path, role(name)) for name, path in files]
    guessed = False
    unknown = [n for n, (*_, part) in enumerate(parts) if not part]
    if unknown:
        if not any(part in VOCAL_SIDE for *_, part in parts):
            first = min(unknown, key=lambda n: _low(parts[n][1]))
            parts[first] = (*parts[first][:2], "вокал")
            unknown.remove(first)
            guessed = True
        for n in unknown:
            parts[n] = (*parts[n][:2], "бит")
    if swap and len(parts) == 2:
        parts = [(name, path, "бит" if part in VOCAL_SIDE else "вокал") for name, path, part in parts]
    # Прислали даблы и эдлибы, а главный голос назвали иначе — ведущим становится самый громкий.
    if not any(part == "вокал" for *_, part in parts) and any(part in VOCAL_SIDE for *_, part in parts):
        lead = max((n for n, (*_, part) in enumerate(parts) if part in VOCAL_SIDE), key=lambda n: loudness(parts[n][1])[0])
        parts[lead] = (*parts[lead][:2], "вокал")
    return parts, guessed


def _item(message: dict) -> dict:
    """Дорожка из сообщения: номер сообщения, file_id, имя, размер, альбом; {} — не звук.
    WAV многие шлют документом без типа, поэтому годится и расширение имени."""
    document = message.get("document") or {}
    kind = str(document.get("mime_type", ""))
    found = message.get("audio") or (document if kind.startswith(("audio/", "video/"))
                                     or str(document.get("file_name", "")).lower().endswith(AUDIO_EXT) else {})
    if not found:
        return {}
    name = found.get("file_name") or " — ".join(filter(None, (found.get("performer"), found.get("title")))) or "дорожка"
    return {"m": message["message_id"], "f": found["file_id"], "n": name[:60], "s": found.get("file_size", 0),
            "g": message.get("media_group_id", "")}


def load() -> dict:
    data = state.read_json(config.SKLEYKA_FILE, {})
    for key, empty in (("drafts", {}), ("jobs", []), ("tracks", {}), ("used", {})):
        data.setdefault(key, empty)
    return data


def save(data: dict) -> None:
    state.write_json(config.SKLEYKA_FILE, data)


def _age(stamp: str) -> float:
    """Сколько секунд прошло с отметки."""
    moment = state._parse(stamp)
    return (state.now() - moment).total_seconds() if moment else math.inf


def _draft(data: dict, chat_id: str) -> dict | None:
    """Открытая заявка человека; протухшая — как нет."""
    draft = data["drafts"].get(chat_id)
    return draft if draft and _age(draft["at"]) < DRAFT_MINUTES * 60 else None


def active(chat_id: str | int) -> bool:
    """Открыта ли у человека заявка: тогда его файлы — дорожки склейки, а не трек в ОТБОР."""
    return _draft(load(), str(chat_id)) is not None


def cancel(chat_id: str | int) -> None:
    data = load()
    if data["drafts"].pop(str(chat_id), None) is not None:
        save(data)


def wants(message: dict) -> bool:
    """Дорожка ли это склейки: файл в личке при открытой заявке или ответом на вопрос
    склейки. Ответ на что-то другое — запрос трека у владельца, фразу ролика — идёт
    своим путём (src/moderate.py)."""
    if message.get("chat", {}).get("type") != "private" or not _item(message):
        return False
    reply = message.get("reply_to_message")
    if reply:
        return ASK_MARK in (reply.get("text") or "")
    return active(message["chat"]["id"])


def _limit(data: dict, chat_id: str) -> str:
    """Отказ по суточному лимиту; пусто — можно."""
    recent = sorted(stamp for stamp in data["used"].get(chat_id, []) if _age(stamp) < 86400)
    if len(recent) < config.SKLEYKA_PER_DAY:
        return ""
    from .compose import MSK

    return LIMIT.format(time=(state._parse(recent[0]) + timedelta(days=1)).astimezone(MSK).strftime("%H:%M"))


def start(chat_id: str | int, user_id: str | int, *, admin: bool = False) -> None:
    """/skleyka, кнопка меню и ссылка ?start=skleyka: две строки и выбор кнопкой.
    Подписку проверяет service."""
    chat_id, data = str(chat_id), load()
    denied = "" if admin else _limit(data, chat_id)
    if denied:
        data["drafts"].pop(chat_id, None)
        save(data)
        telegram.send_message(chat_id, denied)
        return
    data["drafts"][chat_id] = {"user": str(user_id), "admin": admin, "at": state.iso(), "plan": None,
                               "step": 0, "files": []}
    save(data)
    telegram.send_message(chat_id, INTRO, buttons=MODES)


def _ask(chat_id: str, draft: dict) -> None:
    """Вопрос шага: «Шаг 1 из 2 · пришли вокал». Ответом Telegram сам открывает ответ
    на это сообщение, в поле ввода — подсказка. Шаги кончились — вопрос о звуке."""
    plan, step = draft["plan"], draft["step"]
    if step >= len(plan):
        draft["asked"], draft["knobs"] = "style", dict(KNOBS)
        telegram.send_message(chat_id, STYLE, buttons=_styles(draft["knobs"]))
        return
    part = plan[step]
    what = "лид-вокал — главный голос" if part == "вокал" and len(plan) > 2 else ASKS[part]
    telegram.send_message(chat_id, f"<b>Шаг {step + 1} из {len(plan)}</b> {ASK_MARK} {what}"
                          + ("; можно несколькими файлами" if part in MULTI else "") + ".", ask="Прикрепи файл")
    draft["asked"] = step


def _checklist(pick: list[str]) -> list[list[dict]]:
    """Галочки «что есть отдельно»: лид всегда, бит — целиком или по инструментам."""
    def box(part: str, code: str) -> dict:
        return {"text": ("✅ " if part in pick else "▫️ ") + LABELS[part], "callback_data": f"{PREFIX}t:{code}"}

    return [[{"text": "✅ " + LABELS["вокал"], "callback_data": f"{PREFIX}t:l"}],
            [box("дабл", "d"), box("бэк", "b"), box("эдлиб", "a")],
            [box("бит", "w")],
            [box("барабаны", "k"), box("бас", "s"), box("музыка", "m")],
            [{"text": "▶ Дальше", "callback_data": f"{PREFIX}n"}, {"text": "✖ Отмена", "callback_data": f"{PREFIX}x"}]]


def _styles(knobs: dict) -> list[list[dict]]:
    """Вопрос о звуке: стиль начинает склейку, саунд-дизайн — галочка, «как лучше» — стиль
    по умолчанию для тех, кто не знает."""
    looks = [{"text": f"{name} — {STYLE_HINTS[name]}", "callback_data": f"{PREFIX}y:{n}"} for n, name in enumerate(STYLES)]
    return [looks[:2], looks[2:],
            [{"text": ("✅" if knobs["design"] else "▫️") + " саунд-дизайн: переходы и эффекты",
              "callback_data": f"{PREFIX}e"}],
            [{"text": "🤷 Как лучше", "callback_data": f"{PREFIX}y:-"}]]


def toggle(pick: list[str], code: str) -> list[str]:
    """Галочка нажата: бит целиком и бит по инструментам друг друга снимают, без бита нельзя."""
    part = TOGGLES.get(code)
    if not part:
        return pick
    chosen = set(pick) - {part} if part in pick else set(pick) | {part}
    if part in chosen:
        chosen -= set(INSTRUMENTS) if part == "бит" else {"бит"} if part in INSTRUMENTS else set()
    if not chosen & {"бит", *INSTRUMENTS}:
        chosen.add("бит")
    return [part for part in ORDER if part in chosen or part == "вокал"]


def take(message: dict) -> None:
    """Дорожка в заявку: её роль — шаг, на котором она пришла. Прислал файлы, не выбрав
    режим, — это «вокал + бит» по порядку. Одиночный шаг кончается файлом, в шаге
    с несколькими файлами дальше ведёт кнопка."""
    chat_id = str(message["chat"]["id"])
    item, data = _item(message), load()
    draft = _draft(data, chat_id)
    if not draft:
        telegram.send_message(chat_id, OLD)
        return
    if item["s"] > config.SKLEYKA_MAX_MB * 2**20:
        telegram.send_message(chat_id, TOO_BIG.format(name=item["n"]))
        return
    if draft["plan"] is None:
        draft.update(plan=["вокал", "бит"], step=0, asked=0)
    if draft["step"] >= len(draft["plan"]) or len(draft["files"]) >= MAX_PARTS \
            or any(known["m"] == item["m"] for known in draft["files"]):
        return
    part = draft["plan"][draft["step"]]
    draft["files"].append(dict(item, r=part))
    if part not in MULTI:
        draft["step"] += 1
    draft["at"] = state.iso()
    save(data)


def _what(parts: list[tuple[str, str]]) -> str:
    """«вокал «a.wav», даблы «b.wav» и «c.wav», бит «d.wav»» по (имя, роль)."""
    groups: dict[str, list[str]] = {}
    for name, part in parts:
        groups.setdefault(part, []).append(f"«{name}»")
    return ", ".join(f"{NAMES[part]} {' и '.join(groups[part])}" for part in ORDER if part in groups)


def _enqueue(data: dict, track: str, knobs: dict, tweak: bool = False) -> int:
    """Склейка трека с этими ручками — в очередь; сколько минут ждать. tweak — пересборка
    кнопкой: не вышла — возвращается пересборка, а не склейка суток."""
    data["jobs"].append({"id": secrets.token_hex(3), "track": track, "knobs": knobs, "at": state.iso(), "tweak": tweak})
    return MINUTES * len(data["jobs"])


def _queue(data: dict, chat_id: str, draft: dict) -> None:
    """Все шаги пройдены — склейка в очередь, заявка закрыта."""
    track, files = secrets.token_hex(3), draft["files"]
    knobs = draft.get("knobs") or dict(KNOBS)
    data["tracks"][track] = {"chat": chat_id, "admin": draft.get("admin", False), "files": files,
                             "knobs": knobs, "tweaks": 0, "at": state.iso()}
    data["used"].setdefault(chat_id, []).append(state.iso())
    del data["drafts"][chat_id]
    minutes = _enqueue(data, track, dict(knobs))
    telegram.send_message(chat_id, ACCEPTED.format(parts=_what([(f["n"], f["r"]) for f in files]), minutes=minutes))


def _drafts(data: dict) -> bool:
    """Заявки на круге дежурства: файлы перестали приходить — следующий вопрос, «есть,
    ещё — или дальше» или склейка в очередь; тишина DRAFT_MINUTES — заявка закрыта."""
    changed = False
    for chat_id, draft in list(data["drafts"].items()):
        quiet, plan = _age(draft["at"]), draft.get("plan")
        if quiet >= DRAFT_MINUTES * 60:
            del data["drafts"][chat_id]
            if draft["files"]:
                telegram.send_message(chat_id, EXPIRED)
            changed = True
            continue
        if not plan or quiet < QUIET:
            continue
        step = draft["step"]
        have = [f for f in draft["files"] if step < len(plan) and f["r"] == plan[step]]
        if draft.get("asked") == "style":
            if quiet < STYLE_WAIT:
                continue
            _queue(data, chat_id, draft)
        elif draft.get("asked") != step:
            _ask(chat_id, draft)
        elif plan[step] in MULTI and len(have) > draft.get("acked", 0):
            telegram.send_message(chat_id, MORE.format(names=", ".join(f"«{f['n']}»" for f in have)),
                                  buttons=[[{"text": "▶ Дальше", "callback_data": f"{PREFIX}n"}]])
            draft["acked"] = len(have)
        else:
            continue
        changed = True
    return changed


def buttons(track: str, knobs: dict, swap: bool) -> list[list[dict]]:
    """Ручки под готовой склейкой: стиль, голос, эхо, саунд-дизайн; «поменять» —
    когда вокал понят по звуку; «В ОТБОР» — дорога дальше."""
    def cb(code: str) -> str:
        return f"{PREFIX}{track}:{code}"

    looks = [{"text": ("• " if knobs["style"] == name else "") + name, "callback_data": cb(f"c{n}")}
             for n, name in enumerate(STYLES)]
    rows = [looks[:2], looks[2:],
            [{"text": "🔊 голос громче", "callback_data": cb("v+")}, {"text": "🔉 голос тише", "callback_data": cb("v-")}],
            [{"text": "➕ эха", "callback_data": cb("e+")}, {"text": "➖ эха", "callback_data": cb("e-")}],
            [{"text": "✨ саунд-дизайн: " + ("убрать" if knobs["design"] else "добавить"), "callback_data": cb("d")}]]
    if swap:
        rows.append([{"text": "↔ поменять вокал и бит", "callback_data": cb("sw")}])
    rows.append([{"text": "🎙 Выложил — в ОТБОР", "callback_data": "s:otbor"}])
    return rows


def turn(knobs: dict, code: str) -> dict:
    """Ручки после нажатия кнопки code."""
    new = dict(knobs)
    if code.startswith("c") and code[1:].isdigit() and int(code[1:]) < len(STYLES):
        new["style"] = list(STYLES)[int(code[1:])]
    elif code in ("v+", "v-"):
        new["voice"] = max(-VOICE_LIMIT, min(VOICE_LIMIT, knobs["voice"] + (VOICE_STEP if code == "v+" else -VOICE_STEP)))
    elif code in ("e+", "e-"):
        new["echo"] = max(ECHO_LIMITS[0], min(ECHO_LIMITS[1], knobs["echo"] + (ECHO_STEP if code == "e+" else -ECHO_STEP)))
    elif code == "d":
        new["design"] = not knobs["design"]
    elif code == "sw":
        new["swap"] = not knobs["swap"]
    return new


def look(knobs: dict) -> str:
    """Что за склейка — словами для человека."""
    words = [f"«{knobs['style']}»: {STYLES[knobs['style']]['about']}"]
    if knobs["voice"]:
        words.append(f"голос {'громче' if knobs['voice'] > 0 else 'тише'} на {abs(knobs['voice']):.0f} дБ")
    if knobs["echo"]:
        words.append("эха " + ("больше" if knobs["echo"] > 0 else "меньше"))
    if knobs["design"]:
        words.append("с саунд-дизайном")
    return ", ".join(words)


def callback(chat_id: str | int, user_id: str | int, subject: str, *, admin: bool = False,
             message_id: int | None = None) -> None:
    """Кнопки склейки. Под готовым треком — пересборка с новыми ручками новой заявкой,
    файлы снова у Telegram: сами дорожки бот не хранит. До склейки — выбор режима (m),
    галочки дорожек (t), «Дальше» (n), «Отмена» (x), стиль (y) и саунд-дизайн (e) —
    message_id: сообщение с нажатой кнопкой, его кнопки меняются на месте."""
    chat_id = str(chat_id)
    head, _, code = subject.partition(":")
    data = load()
    if len(head) != 1:
        _tweak(data, chat_id, head, code, admin)
        return
    if head == "x":
        cancel(chat_id)
        telegram.send_message(chat_id, CANCELLED)
        return
    draft = _draft(data, chat_id)
    if not draft:
        telegram.send_message(chat_id, OLD)
        return
    if head == "m" and draft["plan"] is None:
        if code == "1":
            draft.update(plan=["вокал", "бит"], step=0)
            _ask(chat_id, draft)
        else:
            draft["pick"] = ["вокал", "бит"]
            draft["menu"] = telegram.send_message(chat_id, PICK, buttons=_checklist(draft["pick"]))["message_id"]
    elif head == "t" and "pick" in draft and draft["plan"] is None:
        draft["pick"] = toggle(draft["pick"], code)
        telegram.edit_markup(chat_id, draft["menu"], _checklist(draft["pick"]))
    elif head == "n" and draft["plan"] is None and "pick" in draft:
        telegram.edit_markup(chat_id, draft["menu"], None)
        draft.update(plan=draft["pick"], step=0)
        _ask(chat_id, draft)
    elif head == "e" and draft.get("asked") == "style":
        draft["knobs"]["design"] = not draft["knobs"]["design"]
        telegram.edit_markup(chat_id, message_id, _styles(draft["knobs"]))
    elif head == "y" and draft.get("asked") == "style":
        if code.isdigit() and int(code) < len(STYLES):
            draft["knobs"]["style"] = list(STYLES)[int(code)]
        telegram.edit_markup(chat_id, message_id, None)
        _queue(data, chat_id, draft)
    elif head == "n" and draft["plan"] and draft["step"] < len(draft["plan"]) \
            and any(f["r"] == draft["plan"][draft["step"]] for f in draft["files"]):
        draft.update(step=draft["step"] + 1, acked=0)
        _ask(chat_id, draft)
    else:
        return
    if chat_id in data["drafts"]:
        draft["at"] = state.iso()
    save(data)


def _tweak(data: dict, chat_id: str, track_id: str, code: str, admin: bool) -> None:
    """Пересборка готовой склейки с ручкой code."""
    track = data["tracks"].get(track_id)
    if not track or track["chat"] != chat_id:
        telegram.send_message(chat_id, STALE)
        return
    if not (admin or track.get("admin")) and track["tweaks"] >= config.SKLEYKA_TWEAKS:
        telegram.send_message(chat_id, NO_TWEAKS)
        return
    knobs = turn(track["knobs"], code)
    if knobs == track["knobs"]:
        telegram.send_message(chat_id, SAME)
        return
    track.update(knobs=knobs, tweaks=track["tweaks"] + 1)
    minutes = _enqueue(data, track_id, knobs, tweak=True)
    save(data)
    telegram.send_message(chat_id, REBUILD.format(what=look(knobs), minutes=minutes))


# Склейка, что идёт сейчас: (процесс, заявка, папка). Одна на дежурство.
_RUNNING: tuple[subprocess.Popen, dict, Path] | None = None


def busy() -> bool:
    """Ждёт ли что-то хода: тогда дежурство опрашивает Telegram чаще."""
    data = load()
    return bool(_RUNNING or data["jobs"] or data["drafts"])


def tick() -> None:
    """Круг дежурства: заявки — в работу, кончившаяся склейка — прочь из очереди,
    следующая — в ход. Ошибка здесь не должна ронять дежурство — ловит вызывающий."""
    global _RUNNING
    data = load()
    changed = _drafts(data)
    if _RUNNING and (_RUNNING[0].poll() is not None or _age(_RUNNING[1]["started"]) > JOB_MINUTES * 60):
        _finish(data, *_RUNNING)
        _RUNNING, changed = None, True
    if not _RUNNING and data["jobs"]:
        _RUNNING, changed = _spawn(data, data["jobs"][0]), True
    for track_id, track in list(data["tracks"].items()):
        if _age(track["at"]) > TRACK_DAYS * 86400:
            del data["tracks"][track_id]
            changed = True
    if changed:
        save(data)


def _spawn(data: dict, job: dict) -> tuple[subprocess.Popen, dict, Path]:
    """Склейку — в отдельный процесс; заявке — отметку, что пошла."""
    track = data["tracks"][job["track"]]
    work = Path(tempfile.mkdtemp(prefix="skleyka-"))
    spec = {"job": job["id"], "track": job["track"], "chat": track["chat"], "files": track["files"],
            "knobs": job["knobs"], "left": None if track.get("admin") else config.SKLEYKA_TWEAKS - track["tweaks"]}
    (work / "job.json").write_text(json.dumps(spec, ensure_ascii=False))
    job["started"] = state.iso()
    print(f"  склейка {job['id']}: пошла, в очереди ещё {len(data['jobs']) - 1}")
    return subprocess.Popen([sys.executable, "-m", "src.skleyka", "--job", str(work / "job.json")],
                            cwd=config.ROOT), job, work


def _finish(data: dict, process: subprocess.Popen, job: dict, work: Path) -> None:
    """Склейка кончилась или зависла: прочь из очереди. Готового нет — лимит суток
    человеку возвращается, а если процесс упал молча, ему пишем здесь."""
    if process.poll() is None:
        process.kill()
        process.wait()
    result = state.read_json(work / "result.json", {})
    shutil.rmtree(work, ignore_errors=True)
    data["jobs"] = [queued for queued in data["jobs"] if queued["id"] != job["id"]]
    track = data["tracks"].get(job["track"], {})
    print(f"  склейка {job['id']}: {'готова' if result.get('ok') else result.get('why') or 'упала'}")
    if result.get("ok") or not track:
        return
    used = data["used"].get(track["chat"], [])
    if job.get("tweak"):
        track["tweaks"] = max(0, track["tweaks"] - 1)
    elif used:
        used.pop()
    if not result:
        telegram.send_message(track["chat"], FAILED)


def resume() -> None:
    """Начало смены: склейка, оборванная прошлой сменой, снова в очередь, если ей
    меньше часа, — дорожки снова у Telegram; старше — извиниться и снять."""
    data = load()
    for job in list(data["jobs"]):
        if "started" not in job:
            continue
        if _age(job["at"]) < RESUME_MINUTES * 60:
            del job["started"]
            continue
        data["jobs"].remove(job)
        if track := data["tracks"].get(job["track"]):
            telegram.send_message(track["chat"], FAILED)
    save(data)


def finish(seconds: int = 300) -> None:
    """Конец смены: идущую склейку дождаться, но не дольше seconds — иначе её
    доделает следующая смена (resume)."""
    global _RUNNING
    if not _RUNNING:
        return
    with contextlib.suppress(subprocess.TimeoutExpired):
        _RUNNING[0].wait(seconds)
    if _RUNNING[0].poll() is None:
        _RUNNING[0].kill()
        shutil.rmtree(_RUNNING[2], ignore_errors=True)
    else:
        data = load()
        _finish(data, *_RUNNING)
        save(data)
    _RUNNING = None


def _minutes(seconds: float) -> str:
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"


def check(parts: list[tuple[str, Path, str]]) -> tuple[str, str]:
    """(отказ, оговорка): отказ — склейки не будет, оговорка — будет, но с примечанием."""
    vocal = [name for name, _, part in parts if part in VOCAL_SIDE]
    if len(vocal) in (0, len(parts)):
        return NEED.format(what="вокала не нашёл" if not vocal else "бита не нашёл: все дорожки названы голосом"), ""
    length = {}
    for name, path, _ in parts:
        length[name] = clips.probe_seconds(path)
        if not length[name]:
            return BAD.format(name=name), ""
        if loudness(path)[0] < -60:
            return SILENT.format(name=name), ""
    voice = max(length[name] for name, _, part in parts if part in VOCAL_SIDE)
    beat = max(length[name] for name, _, part in parts if part not in VOCAL_SIDE)
    if not 60 <= beat <= 480:
        return LENGTH.format(length=_minutes(beat)), ""
    return "", MISMATCH.format(a=_minutes(voice), b=_minutes(beat)) if abs(voice - beat) > 2 else ""


def _bus(parts: list[tuple[str, Path, str]], vocal: bool, dest: Path) -> Path:
    """Дорожки одной стороны — в одну, как их выгрузил артист: каждая со своим уровнем.
    Одна — как есть."""
    paths = [path for _, path, part in parts if (part in VOCAL_SIDE) == vocal]
    if len(paths) == 1:
        return paths[0]
    _ffmpeg(*(arg for path in paths for arg in ("-i", path)), "-filter_complex",
            "".join(f"[{n}:a]{FORMAT}[i{n}];" for n in range(len(paths))) + "".join(f"[i{n}]" for n in range(len(paths)))
            + f"amix=inputs={len(paths)}:duration=longest:normalize=0", *reels.VOICE_CODEC, dest)
    return dest


def _service(login: contextlib.ExitStack):
    """Служебный вход — только если понадобится, и один на всю склейку."""
    client = []

    def get():
        if not client:
            client.append(login.enter_context(telegram.service_login()))
        return client[0]
    return get


def _fetch(spec: dict, folder: Path, service) -> list[tuple[str, Path]]:
    """Дорожки у Telegram: до 20 МБ — Bot API, больше — служебным входом. На диске
    они под номерами: имя файла человека не попадает ни в пути, ни в журнал."""
    folder.mkdir(parents=True, exist_ok=True)
    files = []
    for n, item in enumerate(spec["files"]):
        suffix = Path(item["n"]).suffix.lower()
        dest = folder / f"{n}{suffix if suffix in AUDIO_EXT else ''}"
        if item["s"] and item["s"] <= telegram.MAX_DOWNLOAD:
            dest.write_bytes(telegram.download_file(item["f"]))
        else:
            dest = telegram.fetch_big(service(), item["m"], dest)
        files.append((item["n"], dest))
    return files


def _roles(items: list[dict], files: list[tuple[str, Path]], swap: bool) -> tuple[list[tuple[str, Path, str]], bool]:
    """Роль дорожки — шаг, на который она пришла. Вокал и бит одним альбомом — по имени
    и звуку (sides): порядок в альбоме тот, в каком человек отметил файлы, ему верить нельзя.
    Второе — понята ли роль по звуку: тогда под треком кнопка «поменять»."""
    album = len(items) == 2 and items[0].get("g") and items[0].get("g") == items[1].get("g")
    if album or not all(item.get("r") for item in items):
        return sides(files, swap)
    parts = [(name, path, item["r"]) for (name, path), item in zip(files, items)]
    return parts, False


def run_job(spec_path: Path) -> int:
    """Склейка одной заявки целиком — в отдельном процессе дежурства. Итог — в result.json
    рядом: дежурство по нему решает, вернуть ли человеку лимит."""
    spec = json.loads(spec_path.read_text())
    work, chat, knobs = spec_path.parent, spec["chat"], spec["knobs"]
    result = {"ok": False}
    try:
        with contextlib.ExitStack() as login:
            service = _service(login)
            files = _fetch(spec, work / "in", service)
            parts, guessed = _roles(spec["files"], files, knobs.get("swap", False))
            refusal, note = check(parts)
            if refusal:
                telegram.send_message(chat, refusal)
                result["why"] = "отказ"
                return 0
            vocal, beat = _bus(parts, True, work / "vocal.wav"), _bus(parts, False, work / "beat.wav")
            extra = {key: knobs[key] for key in ("voice", "echo") if knobs.get(key)}
            master = mix(vocal, beat, work / "out", knobs["style"], knobs["design"], **extra)
            try:
                movie = story(vocal, beat, master, work)
            except Exception as exc:  # noqa: BLE001 — без ролика трек всё равно уходит
                print(f"  склейка {spec['job']}: ролик не собрался: {type(exc).__name__}")
                movie = None
            _send(spec, master, parts, note + (GUESSED if guessed else ""), service, work, movie, swap=guessed)
            result["ok"] = True
    except Exception as exc:  # noqa: BLE001 — человеку честный ответ, в журнал — без его данных
        print(f"  склейка {spec['job']}: сбой {type(exc).__name__}: {str(exc)[:200]}")
        telegram.send_message(chat, FAILED)
        result["why"] = "сбой"
    finally:
        (work / "result.json").write_text(json.dumps(result))
    return 0


# Ролик для сторис: те же 7,5 секунды сначала ДО, потом ПОСЛЕ, одной громкости —
# слышно, что сделала склейка, а не насколько стало громче (как в compare). Внизу —
# адрес бота: кто увидел сторис, склеит свой трек сам.
STORY_HALF = 7.5
STORY_CAPTION = "Для сторис: ДО и ПОСЛЕ одной громкости."


def _ink(words: str, size: int, top: float, dest: Path) -> Path:
    """Надпись прозрачным кадром 1080×1920 шрифтом роликов канала: drawtext в ffmpeg
    на Маке нет, а Pillow есть везде."""
    from PIL import Image, ImageDraw

    from . import stories

    frame = Image.new("RGBA", (clips.WIDTH, clips.HEIGHT))
    ImageDraw.Draw(frame).text((clips.WIDTH / 2, clips.HEIGHT * top), words, font=stories.font(size, 600),
                               fill="white", anchor="mt")
    frame.save(dest)
    return dest


def story(vocal: Path, beat: Path, master: Path, work: Path) -> Path:
    """Ролик 9:16 на 15 с: самый громкий кусок склейки — ДО и ПОСЛЕ, волна и адрес бота.
    Надписи — в безопасной зоне площадок (reels.SAFE_*)."""
    _, trace = reels.meter(master)
    n = round(STORY_HALF / 0.1)  # ebur128 отмечает громкость каждые 0,1 с
    loud = [m for _, m, _ in trace]
    best = max(range(max(1, len(loud) - n)), key=lambda i: sum(loud[i:i + n]))
    cut = f"atrim=start={max(0.0, trace[best][0] - 0.4):.2f}:duration={STORY_HALF},asetpts=PTS-STARTPTS"
    before, after, out = work / "story-do.wav", work / "story-posle.wav", work / "story.mp4"
    _ffmpeg("-i", vocal, "-i", beat, "-filter_complex",
            f"[0:a]{FORMAT},{cut}[v];[1:a]{FORMAT},{cut}[b];[v][b]amix=inputs=2:normalize=0", *reels.VOICE_CODEC, before)
    _ffmpeg("-i", master, "-af", f"{FORMAT},{cut}", *reels.VOICE_CODEC, after)
    (raw, peak), glued = loudness(before), loudness(after)[0]
    level = min(glued, raw + CEILING - peak)
    labels = [_ink(words, size, top, work / f"ink{n}.png") for n, (words, size, top) in enumerate(
        (("ДО", 220, reels.SAFE_TOP + 0.04), ("ПОСЛЕ", 220, reels.SAFE_TOP + 0.04),
         (f"склеено в {config.BOT_HANDLE}", 64, reels.SAFE_BOTTOM - 0.07)))]
    _ffmpeg("-i", before, "-i", after, *(arg for label in labels for arg in ("-loop", "1", "-i", label)),
            "-filter_complex",
            f"[0:a]volume={level - raw:.2f}dB[a0];[1:a]volume={level - glued:.2f}dB[a1];"
            "[a0][a1]concat=n=2:v=0:a=1,asplit[a][w];"
            f"[w]showwaves=s={clips.WIDTH}x560:mode=cline:rate=30:colors=white,format=rgba[wave];"
            f"color=c=0x101010:s={clips.WIDTH}x{clips.HEIGHT}:r=30:d={2 * STORY_HALF}[bg];"
            "[bg][wave]overlay=0:(H-h)/2[s0];"
            f"[s0][2:v]overlay=0:0:enable='lt(t,{STORY_HALF})'[s1];"
            f"[s1][3:v]overlay=0:0:enable='gte(t,{STORY_HALF})'[s2];"
            "[s2][4:v]overlay=0:0:shortest=1[v]",
            "-map", "[v]", "-map", "[a]", "-t", 2 * STORY_HALF, "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-preset", "veryfast", "-c:a", "aac", "-b:a", "192k", out)
    return out


def _send(spec: dict, master: Path, parts: list, note: str, service, work: Path, movie: Path | None,
          swap: bool = False) -> None:
    """MP3 плеером — его пересылают, WAV документом — его льют на площадки, ручки — отдельным
    сообщением: кнопки на плеере ушли бы вместе с пересылкой."""
    chat, knobs = spec["chat"], spec["knobs"]
    lead = next(name for name, _, part in parts if part in VOCAL_SIDE)
    title = Path(lead).stem[:60]
    mp3 = work / "skleyka.mp3"
    _ffmpeg("-i", master, *MP3, mp3)
    what = _what([(name, part) for name, _, part in parts])
    telegram.send_audio(chat, mp3.read_bytes(), READY.format(look=look(knobs), parts=what[:1].upper() + what[1:], note=note),
        title=title, performer=f"склейка · {config.BOT_HANDLE}")
    wav = work / f"{title} (склейка).wav"
    master.replace(wav)
    if wav.stat().st_size <= telegram.MAX_UPLOAD:
        telegram.send_document(chat, wav)
    else:
        telegram.send_big(service(), chat, wav, "", via=spec["files"][0]["m"])
    if movie:
        telegram.send_video_file(chat, movie, STORY_CAPTION, seconds=round(2 * STORY_HALF))
    left = spec["left"]
    telegram.send_message(chat, TUNE.format(left="" if left is None else f" — осталось {left} из {config.SKLEYKA_TWEAKS}"),
                          buttons=buttons(spec["track"], knobs, swap=swap))


def _selftest() -> None:
    """Без сети: роли по имени и по звуку, куда идёт файл, заявка от дорожек до очереди,
    ручки и возврат лимита, лимит суток, отказы по тишине и длине."""
    sent: list[str] = []
    real = (telegram.send_message, telegram.edit_markup, config.SKLEYKA_FILE, config.secret)
    telegram.send_message = lambda chat, text, **_: sent.append(text) or {"message_id": len(sent)}
    telegram.edit_markup = lambda chat, message, markup: None
    config.secret = lambda name, required=True: "1" if name == "TELEGRAM_ADMIN_ID" else ""
    tmp = Path(tempfile.mkdtemp(prefix="skleyka-test-"))
    config.SKLEYKA_FILE = tmp / "skleyka.json"
    try:
        for name, want in (("vocal.wav", "вокал"), ("Beat (prod. X).mp3", "бит"), ("whats my name fool.wav", ""),
                           ("Hi-Hat.wav", "барабаны"), ("808.wav", "бас"), ("lead synth.wav", "музыка"),
                           ("BGV 1.wav", "бэк"), ("ad-lib.wav", "эдлиб"), ("минусовка.mp3", "бит"), ("Дабл 2.wav", "дабл")):
            assert role(name) == want, (name, role(name))

        # Роли по звуку: у бита низ, у голоса — середина.
        low, mid = tmp / "a.wav", tmp / "b.wav"
        _ffmpeg("-f", "lavfi", "-i", "sine=f=55:d=6", "-f", "lavfi", "-i", "anoisesrc=d=6:a=0.05", "-filter_complex",
                "amix=inputs=2", low)
        _ffmpeg("-f", "lavfi", "-i", "anoisesrc=d=6:a=0.3", "-af", "highpass=f=300,lowpass=f=3000", mid)
        parts, guessed = sides([("take1.wav", low), ("take2.wav", mid)])
        assert guessed and [part for *_, part in parts] == ["бит", "вокал"], parts
        assert [part for *_, part in sides([("take1.wav", low), ("take2.wav", mid)], swap=True)[0]] == ["вокал", "бит"]
        assert not sides([("vocal.wav", low), ("beat.wav", mid)])[1], "имя сильнее звука"

        # Отказы: тишина, короткий бит; разная длина — оговорка, а не отказ.
        quiet, short, long = tmp / "q.wav", tmp / "s.wav", tmp / "l.wav"
        _ffmpeg("-f", "lavfi", "-i", "anullsrc=d=70", quiet)
        _ffmpeg("-f", "lavfi", "-i", "sine=f=220:d=70", long)
        assert check([("v", quiet, "вокал"), ("b", long, "бит")])[0] == SILENT.format(name="v")
        assert check([("v", long, "вокал"), ("d", long, "дабл")])[0].startswith("Нужны и вокал, и бит, а бита")
        assert check([("v", low, "вокал"), ("b", mid, "бит")])[0].startswith("Бит длится 0:06")
        _ffmpeg("-f", "lavfi", "-i", "sine=f=440:d=66", short)
        refusal, note = check([("v", short, "вокал"), ("b", long, "бит")])
        assert not refusal and note.startswith("Дорожки разной длины (1:06 и 1:10)"), note

        # Куда идёт файл: при открытой заявке и ответом на вопрос склейки — сюда; без заявки
        # и ответом на другое (запрос трека владельца) — мимо, в ОТБОР и attach_track.
        def file(n: int, name: str, chat: int = 7, reply: str | None = None, album: str = "") -> dict:
            message = {"message_id": n, "chat": {"id": chat, "type": "private"}, "from": {"id": chat},
                       "document": {"file_id": f"f{n}", "file_name": name, "file_size": 1000, "mime_type": "audio/wav"}}
            if reply is not None:
                message["reply_to_message"] = {"message_id": 1, "text": reply}
            if album:
                message["media_group_id"] = album
            return message

        def later(chat: str, seconds: float = QUIET + 1) -> None:
            """Файлы перестали приходить: круг дежурства видит тишину."""
            data = load()
            data["drafts"][chat]["at"] = state.iso(state.now() - timedelta(seconds=seconds))
            _drafts(data)
            save(data)

        assert not wants(file(2, "vocal.wav"))
        start(7, 7)
        assert sent[-1] == INTRO and wants(file(3, "a.wav")) and not wants(file(3, "a.wav", reply="Пришли трек"))
        assert not wants({"message_id": 4, "chat": {"id": 7, "type": "private"}, "text": "привет"})

        # «Вокал + бит»: вопрос за вопросом, роль — шаг, имена файлов не нужны; потом — звук.
        callback(7, 7, "m:1")
        assert sent[-1].startswith("<b>Шаг 1 из 2</b> · пришли вокал") and wants(file(3, "a.wav", reply=sent[-1]))
        take(file(3, "take 1.wav"))
        take(file(3, "take 1.wav"))  # повтор того же сообщения — дорожка одна
        later("7")
        assert sent[-1].startswith("<b>Шаг 2 из 2</b> · пришли бит"), sent[-1]
        take(file(5, "take 2.wav"))
        later("7")
        assert sent[-1] == STYLE and load()["drafts"]["7"]["asked"] == "style"
        callback(7, 7, "e")
        assert load()["drafts"]["7"]["knobs"]["design"]
        callback(7, 7, "y:1")
        data = load()
        assert sent[-1].startswith("Принял: вокал «take 1.wav», бит «take 2.wav»") and not data["drafts"]
        track = data["jobs"][0]["track"]
        assert data["tracks"][track]["knobs"] == dict(KNOBS, style="мелодично", design=True)
        assert [f["r"] for f in data["tracks"][track]["files"]] == ["вокал", "бит"]

        # Не выбрал звук — склейка идёт как лучше, человек не ждёт зря.
        start(11, 11)
        take(file(20, "a.wav", chat=11, album="g1"))
        take(file(21, "b.wav", chat=11, album="g1"))  # альбомом, не выбрав режим — «вокал + бит» по порядку
        later("11")
        assert sent[-1] == STYLE
        later("11", STYLE_WAIT + 1)
        files = load()["tracks"][load()["jobs"][-1]["track"]]["files"]
        assert [f["r"] for f in files] == ["вокал", "бит"] and files[0]["g"] == files[1]["g"] == "g1"

        # «По дорожкам»: галочки, потом шаг за шагом; где файлов несколько — «Дальше».
        start(9, 9)
        callback(9, 9, "m:2")
        assert sent[-1] == PICK
        assert toggle(["вокал", "бит"], "k") == ["вокал", "барабаны"], "инструменты снимают бит целиком"
        assert toggle(["вокал", "барабаны"], "k") == ["вокал", "бит"], "без бита нельзя"
        assert toggle(["вокал", "барабаны", "бас"], "w") == ["вокал", "бит"]
        for code in ("d", "k", "s"):
            callback(9, 9, f"t:{code}")
        callback(9, 9, "n")
        assert load()["drafts"]["9"]["plan"] == ["вокал", "дабл", "барабаны", "бас"]
        assert sent[-1].startswith("<b>Шаг 1 из 4</b> · пришли лид-вокал")
        take(file(30, "x.wav", chat=9))
        later("9")
        assert sent[-1].startswith("<b>Шаг 2 из 4</b> · пришли даблы; можно несколькими файлами")
        take(file(31, "d1.wav", chat=9))
        take(file(32, "d2.wav", chat=9))
        later("9")
        assert sent[-1] == MORE.format(names="«d1.wav», «d2.wav»")
        callback(9, 9, "n")
        assert sent[-1].startswith("<b>Шаг 3 из 4</b> · пришли барабаны")
        callback(9, 9, "n")  # без файла дальше не пускает
        assert load()["drafts"]["9"]["step"] == 2
        take(file(33, "kick.wav", chat=9))
        callback(9, 9, "n")
        take(file(34, "808.wav", chat=9))
        callback(9, 9, "n")
        later("9")
        callback(9, 9, "y:-")
        assert sent[-1].startswith("Принял: вокал «x.wav», даблы «d1.wav» и «d2.wav», барабаны «kick.wav», бас «808.wav»")
        callback(9, 9, "n")
        assert sent[-1] == OLD, "закрытая заявка"
        start(12, 12)
        callback(12, 12, "x")
        assert sent[-1] == CANCELLED and not active(12)
        data = load()
        data["jobs"], data["used"] = data["jobs"][:1], {"7": data["used"]["7"]}
        save(data)

        # Ручки: голос громче — новая заявка той же склейки; нажатие без перемены — «уже так».
        callback(7, 7, f"{track}:v+")
        data = load()
        assert data["jobs"][-1]["knobs"]["voice"] == VOICE_STEP and data["tracks"][track]["tweaks"] == 1
        callback(7, 7, f"{track}:c1")
        assert sent[-1] == SAME, "мелодично уже выбрано до склейки"
        callback(8, 8, f"{track}:v+")
        assert sent[-1] == STALE, "чужая склейка"
        for _ in range(config.SKLEYKA_TWEAKS):
            callback(7, 7, f"{track}:v-")
        assert sent[-1] == NO_TWEAKS
        assert [row[0]["callback_data"] for row in buttons(track, KNOBS, swap=True)][-2:] == [f"{PREFIX}{track}:sw", "s:otbor"]
        assert _roles([{"r": "вокал", "g": "a"}, {"r": "бит", "g": "a"}], [("take1.wav", low), ("take2.wav", mid)],
                      False) == ([("take1.wav", low, "бит"), ("take2.wav", mid, "вокал")], True), "альбом — по звуку"

        # Не склеилось молча — извиниться и вернуть склейку суток; упала пересборка — вернуть её.
        data = load()
        for job in data["jobs"][:2]:
            gone = subprocess.Popen(["true"])
            gone.wait()
            (tmp / job["id"]).mkdir()
            _finish(data, gone, job, tmp / job["id"])
        assert sent[-1] == FAILED and data["used"]["7"] == [] and data["tracks"][track]["tweaks"] == 2
        save(data)

        # Лимит суток: две склейки — третья завтра; владельцу лимита нет.
        data["used"]["7"] = [state.iso(), state.iso()]
        save(data)
        start(7, 7)
        assert sent[-1].startswith("Склеек в сутки — две"), sent[-1]
        start(1, 1, admin=True)
        assert sent[-1] == INTRO
        assert turn(KNOBS, "e+")["echo"] == ECHO_STEP and turn(dict(KNOBS, voice=VOICE_LIMIT), "v+")["voice"] == VOICE_LIMIT
        assert "с саунд-дизайном" in look(turn(KNOBS, "d")) and turn(KNOBS, "c1")["style"] == "мелодично"
    finally:
        telegram.send_message, telegram.edit_markup, config.SKLEYKA_FILE, config.secret = real
        shutil.rmtree(tmp, ignore_errors=True)
    print("skleyka: роли по имени и звуку, маршрут файлов, вопросы по шагам и галочки, звук до склейки, "
          "ручки, лимиты, отказы — ок")


def main() -> int:
    parser = argparse.ArgumentParser(description="СКЛЕЙКА: вокал и бит в черновой трек")
    parser.add_argument("--mix", nargs=2, type=Path, metavar=("ВОКАЛ", "БИТ"),
                        help="склеить две дорожки и сделать пару ДО/ПОСЛЕ одной громкости")
    parser.add_argument("--out", type=Path, default=Path("skleyka"), help="папка для результата")
    parser.add_argument("--style", choices=STYLES, default="чисто", help="набор эффектов")
    parser.add_argument("--design", action="store_true",
                        help="саунд-дизайн: вдох перед первым словом, фильтр на бите, броски, остановка плёнки")
    parser.add_argument("--job", type=Path, metavar="ФАЙЛ", help="склейка заявки из бота (её запускает дежурство)")
    parser.add_argument("--selftest", action="store_true", help="роли, маршрут, заявка, ручки, лимиты — без сети")
    parser.add_argument("--dry-run", action="store_true", help="заявки и склейки в очереди, ничего не делая")
    args = parser.parse_args()
    config.load_dotenv()
    if args.selftest:
        _selftest()
        return 0
    if args.job:
        return run_job(args.job)
    if args.dry_run:
        data = load()
        print(f"Заявок открыто: {len(data['drafts'])}, склеек в очереди: {len(data['jobs'])}, "
              f"треков с ручками: {len(data['tracks'])}")
        for job in data["jobs"]:
            print(f"  {job['id']}: {look(job['knobs'])}" + (" — идёт" if "started" in job else ""))
        return 0
    if args.mix:
        master = mix(*args.mix, args.out, args.style, args.design)
        compare(*args.mix, master, args.out)
        print(f"  готово: {master}, {args.out / 'do.mp3'}, {args.out / 'posle.mp3'}")
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
