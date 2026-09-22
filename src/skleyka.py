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
import math
import re
import statistics
import subprocess
import wave
from pathlib import Path

from . import clips, reels

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


def mix(vocal: Path, beat: Path, out: Path, style: str = "чисто", design: bool = False) -> Path:
    """Склейка в out/skleyka.wav, промежуточное — в out/work."""
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
    voice, lines = loudness(dry)[0], _lines(_envelope(dry))

    # Противофаза — по слышимой полосе: в ультразвуке и на самом низу бывает что угодно.
    heard = f"{FORMAT},highpass=f=60,lowpass=f=12000,"
    width = stereo(beat, heard)[0]
    flip = "pan=stereo|c0=c0|c1=-1*c1," if width < 0 else ""
    ducked = work / "beat.wav"
    _ffmpeg("-i", beat, "-i", dry, "-filter_complex",
            f"[0:a]{FORMAT},{flip}{MS},{_dip(lines, work / 'dip.cmd')}{BEAT_EQ},{LR}[b];"
            f"[1:a]volume={VOCAL_LUFS - voice:.2f}dB[v];[b][v]{DUCK}",
            *reels.VOICE_CODEC, ducked)
    print(f"  бит: корреляция каналов {width:+.2f}" + (", один канал перевёрнут" if flip else ""))
    ridden = _ride(dry, ducked, loudness(ducked)[0] + VOCAL_OVER_BEAT - voice, work)
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
        wets.append((wet, share))
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


def main() -> int:
    parser = argparse.ArgumentParser(description="СКЛЕЙКА: вокал и бит в черновой трек")
    parser.add_argument("--mix", nargs=2, type=Path, metavar=("ВОКАЛ", "БИТ"),
                        help="склеить две дорожки и сделать пару ДО/ПОСЛЕ одной громкости")
    parser.add_argument("--out", type=Path, default=Path("skleyka"), help="папка для результата")
    parser.add_argument("--style", choices=STYLES, default="чисто", help="набор эффектов")
    parser.add_argument("--design", action="store_true",
                        help="саунд-дизайн: вдох перед первым словом, фильтр на бите, броски, остановка плёнки")
    args = parser.parse_args()
    if args.mix:
        master = mix(*args.mix, args.out, args.style, args.design)
        compare(*args.mix, master, args.out)
        print(f"  готово: {master}, {args.out / 'do.mp3'}, {args.out / 'posle.mp3'}")
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
