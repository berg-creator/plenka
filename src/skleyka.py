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
2. Тембр вокала выравнивается к сведённому рэп-вокалу (TONE) по замеру октав —
   на весь трек и по ходу трека: домашние записи расходятся на 10 дБ, а куски
   одной записи — на 6–7, и одна полка на всех не годится.
3. Бит: каналы в противофазе переворачиваются; место голосу — как soothe с голосом
   в сайдчейне: середина бита приседает по полосам выше 120 Гц ключом от тех же
   полос голоса, глубже всего в 1–4 кГц и только пока голос звучит (ROOM_*).
   Низ и края не тронуты: бочка и 808 качают, бит остаётся широким.
4. Баланс — вровень по EBU R128, а по ходу трека голос ведёт райдер: где бит
   его перекрывает, голос плавно поднимается. Один баланс на весь трек владелец
   услышал с первой прослушки: «где-то будто слишком громкий бит».
5. Стиль (STYLES) — набор эффектов, названный словом, понятным без знания
   сведения. Отзвук, дилей и дабл — шинами, доля к сухому голосу по замеру,
   как в reels.studio.
6. Саунд-дизайн — по флагу и по всему треку: вдох перевёрнутого отзвука перед
   первым словом и на входах голоса, бит из-под фильтра до первого слова, на входах
   после пауз — подъём шума и вырез бита перед сильной долей, броски дилея на концах
   фраз (каждый второй — на октаву ниже), остановка плёнки в конце. Всё синтезом
   ffmpeg, без чужих сэмплов, на доли и такты бита (grid), громкость приёмов — к биту.
7. Мастер — низ ниже 120 Гц в моно, склейка шины 2:1, жёсткий клиппер по верхушкам
   ударов и ограничитель до MASTER_LUFS, пик не выше CEILING dBTP.

Ручки бота — mix(..., voice=, echo=): голос к биту и доля эха, в дБ.

Промежуточное — во float: пики выше нуля между шагами не срезаются, режет только
мастер. Подгонку под референс (Matchering) сюда не тащим: это
новый пакет и обещание «как у звезды», которое черновая склейка не сдержит.

Проверка — на слух: ДО (простая сумма дорожек) и ПОСЛЕ одной громкости по LUFS.
Громкое всегда кажется лучше, и без этого сравнение нечестное.

    python -m src.skleyka --mix ВОКАЛ БИТ --out ПАПКА   склейка и пара ДО/ПОСЛЕ одной громкости
    python -m src.skleyka --mix ВОКАЛ БИТ --out ПАПКА --style грязно --design
    python -m src.skleyka --mix ВОКАЛ БИТ --out ПАПКА --voice 2 --echo -4   ручки «голос громче», «эха меньше»
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
# Тембр по ходу трека: куски одной записи пишутся по-разному — у Little Chicago's
# Finest на 176–192 с полоса 500 Гц на 5 дБ выше 1 кГц, на 160–168 — на 5 ниже,
# и одна поправка на весь трек оставляла на 2:58 «коробку» (владелец: «плотность
# пропала, начал звучать дёшево»). Поэтому к общей поправке — своя по окнам
# TONE_STEP с: октавы к 1 кГц, сглаженные на TONE_SPAN с по окнам с голосом,
# тянутся к среднему тембру уже поправленного голоса. Это и есть TONE там, где
# общая поправка его достала, а где упёрлась в предел — окна не тащат за предел
# весь трек. Не дальше TONE_LOCAL дБ от общей, вверх — не выше TONE_BOOST.
# Замер: на 176–192 с стало +2,8, на 160–168 — −2,3 (дальше не пускает TONE_LOCAL);
# куски по 3 с на пяти треках отходят от среднего тембра на 1,1–1,4 дБ вместо 2,4–3,0.
TONE_STEP = 0.5
TONE_SPAN = 3.0
TONE_LOCAL = 4.0
# Де-эссер последним: подъём разборчивости и компрессия сами добавляют свиста.
DEESSER = "deesser=i=0.5"

# --- бит --------------------------------------------------------------------
# Место голосу — как soothe с голосом в сайдчейне (руководство soothe2: «carve out
# space for the vocals by using them as the sidechain key input… with the mid/side
# stereo mode»; Jaycen Joshua ставит подавитель резонансов на шину музыки с голосом
# в ключе, Podlesny Twins — Soothe на мелодии «на частоты вокала»): середина бита
# (M/S) по полосам выше 120 Гц приседает компрессорами с ключом от тех же полос
# голоса — только там и тогда, где голос звучит. Ниже 120 Гц голоса нет (срез
# HIGHPASS), и бочка с 808 не трогаются вовсе; края бита тоже. Полосы — крутые
# фильтры по SPLIT, 24 дБ на октаву: полоса 120–250 Гц ниже 120 почти не задевает.
SPLIT = (120, 250, 500, 1000, 2000, 4000, 8000)
# Глубина полосы — маскировка: насколько полоса бита громче той же полосы голоса
# при балансе склейки в десятой части окон с голосом, где бит перекрывает его
# сильнее всего (ROOM_SHARE): медиана почти везде отрицательна — голос в середине
# громче бита, — и места не делалось бы вовсе, а место нужно именно там, где бит
# голос накрывает. Потолок ROOM_CAP: больше всего в 1–4 кГц, где разборчивость,
# мало в 120–250 Гц — это тело бита — и выше 8 кГц. Отпуск длиннее на низких
# полосах: быстрый на 120 Гц качал бы саму волну. Ratio 1,25 и порог на 5 глубин
# ниже обычного слога: провал почти один на громком и на тихом слоге, как у soothe,
# который режет, пока в ключе есть голос, и как у Сениора (1,04:1, не больше 2 дБ).
# С ratio 2 тихие слоги — а бит перекрывает именно их — получали вдвое меньше
# громких: у Little Chicago's Finest в 1–2 кГц 1,8 дБ против 4,0 на медиане.
# Замер на трёх треках против прежнего провала 2,8 кГц и сайдчейна на весь бит:
# голос к биту в 1–2 кГц по медиане +8,7 / +7,6 / +4,8 дБ вместо +5,8 / +5,6 / +2,6
# (Little Chicago's Finest, M.E.R.C. Music, projectquestion), в 2–4 кГц +10,1 / +8,9 /
# +9,8 вместо +8,4 / +7,0 / +7,8; бит громче голоса по EBU R128 в 13 / 11 / 14% окон
# с голосом вместо 11 / 12 / 13%: низ больше не приседает, и общую громкость
# место почти не трогает — её ведёт райдер.
ROOM_CAP = (1.5, 2.0, 3.0, 5.0, 5.0, 3.0, 1.5)
ROOM_RELEASE = (250, 200, 150, 100, 80, 60, 50)
ROOM_SHARE = 0.9
ROOM_RATIO = 1.25

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
# Саунд-дизайн — по всему треку, а не только во вступлении и в конце: после прослушки 2
# владелец его почти не услышал («его мало, вообще будто нет») и в пример дал
# A$AP Rocky. Всё синтезом ffmpeg, без чужих сэмплов, на доли и такты бита (grid),
# а громкость каждого приёма — к биту (*_DB, LU к громкости бита по EBU R128): его
# и должно быть слышно поверх бита.
# Вдох: слово задом наперёд уходит в отзвук на BREATH_SECONDS, отзвук разворачивается
# обратно и нарастает к слову за BREATH_BEATS долей. Перед первым словом и на входах.
BREATH_SECONDS = 2.5
BREATH_BEATS = 2
BREATH_DB = -2.0
# Бит до первого слова: за FILTER_BEATS долей закрывается фильтром до FILTER_LOW Гц
# и за OPEN_BEATS долей открывается к сильной доле первого слова.
FILTER_LOW = 400
FILTER_BEATS = 8
OPEN_BEATS = 2
# Фразы для саунд-дизайна размечаются строже, чем окна с голосом: эдлибы, подпевки
# и хвосты отзвука в стеме тише главного голоса на 15 дБ и больше. С общим порогом
# (VOICE_RANGE) у Little Chicago's Finest на 4:41 выходило 5 строк без единой паузы
# длиннее 0,8 с; с PHRASE_RANGE и паузой от PHRASE_PAUSE — 35 фраз, и четыре самые
# длинные паузы, 0,65–0,81 с, — ровно начала частей трека.
PHRASE_RANGE = 15.0
PHRASE_PAUSE = 0.25
# Входы голоса после паузы от ENTRY_BEATS доли — самые длинные паузы первыми,
# не чаще раза в ENTRY_BARS тактов. Двух долей мало где дождёшься: у Little
# Chicago's Finest части начинаются после 1,2–1,5 доли. На входе бит вырезается
# на последнюю долю перед сильной долей (McCloskey о DaBaby в Sound On Sound:
# «maximum impact… have nothing happening just before it»; полная тишина звучала
# плохо — хвосты отзвука и дилея остаются, они на своих шинах), за такт до выреза
# нарастает шум, в первое слово — вдох.
ENTRY_BEATS = 1
ENTRY_BARS = 8
# Подъём шума: белый шум, фильтр открывается от RISE_LOW до RISE_HIGH Гц, громкость
# растёт на RISE_RANGE дБ за такт и обрывается на вырезе.
RISE_LOW = 300
RISE_HIGH = 12000
RISE_RANGE = 24
RISE_DB = -6.0
# Броски: последнее слово фразы — в дилей в темп, перед самыми длинными паузами
# первыми, не чаще раза в THROW_BARS тактов и не больше THROWS. Каждый второй —
# на октаву ниже: asetrate вдвое вниз и atempo 2 — высота падает, длина та же
# (rubberband в ffmpeg на Маке нет). Пауза за фразой бывает и в четверть секунды,
# поэтому повторы приседают под всем голосом (Bainz о Young Thug в Sound On Sound:
# дилей «side-chained to the vocal, so it only sounds when the vocal isn't there»).
THROW_WORD = 0.3
THROWS = 12
THROW_BARS = 4
THROW_DB = -1.0
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
# Клиппер жёсткий: мягкие (asoftclip tanh и atan) на той же громкости и том же пике
# держат удар хуже — они гнут всю волну с нескольких дБ ниже потолка, а не одни
# верхушки. Замер по ударам бочки у Little Chicago's Finest на −10 LUFS и −2 dBTP:
# верхушка удара к окружению теряет 1,4 дБ с жёстким, 1,9 с tanh и 2,5 с atan,
# атака бочки к телу — 0,4 / 0,8 / 0,9 дБ, остаток искажений −24 / −22 / −19 дБ;
# у M.E.R.C. Music верхушка — 0,7 / 1,2 дБ (жёсткий / tanh). Низ ниже 100 Гц у всех
# один (±0,1 дБ): «жёсткий съедает бас» (Шеперд) — о клиппинге на много дБ, а тут два.
CLIP = 2.0
CLIPPER = "asoftclip=type=hard"
# Склейка шины перед клиппером — компрессор 2:1, атака 30 мс, отпуск 200 мс: атака
# пропускает удар, отпуск успевает за долей, и голос с битом сжимаются вместе, а не
# каждый сам по себе. Порог — по замеру, чтобы сжатие было GLUE дБ по EBU R128
# (на пяти треках вышло 1,6–1,7).
GLUE = 1.5


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


def _equalizer(vocal: Path, lines: list[tuple[float, float]], work: Path) -> str:
    """Поправка тембра к TONE колоколами по октавам: общая на весь трек и своя по ходу
    трека — командами asendcmd колоколам equalizer@t…, шагами по 0,1 с, чтобы
    не щёлкало. Меряется голос уже с де-эссером, а соседние колокола задевают друг
    друга, поэтому каждый замер повторяется по поправленному голосу."""
    gains = dict.fromkeys(TONE, 0.0)
    for _ in range(2):
        for f, db in tone(vocal, _bells(gains) + DEESSER).items():
            gains[f] = max(TONE_CUT, min(TONE_BOOST.get(f, 0.0), gains[f] + TONE[f] - db))
    print("  тембр: " + ", ".join(f"{f} Гц {g:+.1f}" for f, g in gains.items() if g))
    # Колокол есть и у 1 кГц: поправка окна меняет только форму, а общую мощность
    # окна возвращает он — иначе окна, где 1 кГц провален, теряли бы громкость
    # целиком, и райдер поднимал бы голос вдвое чаще (у Little Chicago's Finest бит
    # перекрывал голос в 37% окон вместо 20%).
    octaves = sorted([*TONE, 1000])
    cmd, local = work / "tone.cmd", "".join(f"equalizer@t{f}=f={f}:t=o:w=1:g=0," for f in octaves)
    extra, ref, drift = {f: {} for f in octaves}, {}, []
    split = [f / 2 ** 0.5 for f in octaves] + [octaves[-1] * 2 ** 0.5]
    for again in range(2):
        chain = _bells(gains) + (f"asendcmd=f='{cmd}',{local}" if again else "") + f"{DEESSER},{MID},"
        power = dict(zip(octaves, ([10 ** (db / 10) for db in band] for band in _bands(vocal, chain, split, TONE_STEP)[1:])))
        sung = _sung(lines, len(power[1000]), TONE_STEP)
        if not sung:
            return _bells(gains)
        ref = ref or {f: 10 * math.log10(sum(power[f][i] for i in sung) / sum(power[1000][i] for i in sung)) for f in TONE}
        miss = []
        for w in sung:
            near = [i for i in sung if abs(i - w) * TONE_STEP <= TONE_SPAN / 2]
            total = {f: sum(power[f][i] for i in near) + 1e-15 for f in octaves}
            shape = {f: ref.get(f, 0.0) - 10 * math.log10(total[f] / total[1000]) for f in octaves}
            level = -10 * math.log10(sum(total[f] * 10 ** (shape[f] / 10) for f in octaves) / sum(total.values()))
            miss += [abs(shape[f]) for f in TONE]
            for f in octaves:
                # Вверх — не выше TONE_BOOST, как и общая; у 1 кГц общего колокола нет.
                top = TONE_BOOST.get(f, 0.0) - gains[f] if f in TONE else TONE_LOCAL
                extra[f][w] = max(-TONE_LOCAL, min(TONE_LOCAL, top, extra[f].get(w, 0.0) + shape[f] + level))
        drift.append(statistics.fmean(miss))
        # Между окнами с голосом — по прямой, до первого и после последнего — как у них.
        times, rows, sent = [(w + 0.5) * TONE_STEP for w in sung], [], {}
        for n in range(round(len(power[1000]) * TONE_STEP * 10) + 1):
            t, row = n / 10, []
            k = min(max(0, sum(x <= t for x in times) - 1), len(times) - 2)
            for f in octaves:
                a, b = extra[f][sung[k]], extra[f][sung[min(k + 1, len(sung) - 1)]]
                share = 0.0 if len(times) < 2 else min(1.0, max(0.0, (t - times[k]) / (times[k + 1] - times[k])))
                value = round(a + (b - a) * share, 1)
                if sent.get(f) != value:
                    sent[f] = value
                    row.append(f"equalizer@t{f} g {value}")
            if row:
                rows.append(f"{t:.1f} " + ", ".join(row) + ";")
        cmd.write_text("\n".join(rows))
    reach = {f: (min(extra[f].values()), max(extra[f].values())) for f in octaves}
    print(f"  тембр по ходу: окна отходили от среднего на {drift[0]:.1f} дБ, после поправки — на {drift[1]:.1f}; "
          + ", ".join(f"{f} Гц {lo:+.1f}…{hi:+.1f}" for f, (lo, hi) in reach.items()))
    return _bells(gains) + f"asendcmd=f='{cmd}',{local}"


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
    """Сетка бита: длина доли и где сильная доля такта, секунды.

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
    Первая доля — сильная доля такта: из четырёх фаз сетки та, где сильнее бьёт
    низ (бочка), и такты — через каждые четыре доли от неё.
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

    def kick(phase: int) -> float:
        return statistics.fmean(low[round(start + (4 * k + phase) * period)]
                                for k in range(int((len(low) - 1 - start - phase * period) / (4 * period)) + 1))

    return period / ENV_RATE, offset + (start + max(range(4), key=kick) * period) / ENV_RATE


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


def _lines(level: list[float], below: float = VOICE_RANGE, pause: float = 0.4) -> list[tuple[float, float]]:
    """Строки голоса по огибающей: (начало, конец), секунды. Голос — громче почти
    самого громкого места минус below дБ; паузы короче pause — внутри строки,
    щелчки короче 0,1 с — не голос."""
    top, lines = sorted(level)[int(len(level) * 0.95)], []
    for i, db in enumerate(level):
        if db <= top - below:
            continue
        if lines and i - lines[-1][1] < pause * ENV_RATE:
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


def _ride(dry: Path, beat: Path, lift: float, target: float, work: Path) -> Path:
    """Голос с общим подъёмом lift и райдером (RIDE_*) к цели target — голос к биту
    в окне, дБ, — в work/vocal-ride.wav."""
    times, gaps = _gaps(dry, beat, lift)
    want = [0.0 if gap is None else max(0.0, min(RIDE_MAX, target - gap)) for gap in gaps]
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


def _tempo_delay(length: float, under: float | None = None, key: str = "") -> str:
    """Дилей в темп от стены к стене: слева повторы через четверть, справа — через
    восьмую (главный и второй у инженеров Sound On Sound), по три с затуханием;
    на возврат — полоса 200 Гц – 5 кГц (Элмхёрст в Mix With The Masters).

    under — громкость голоса, LUFS: под голосом дилей приседает на 8–10 дБ
    (2:1, атака сразу, отпуск 150 мс, как у Сениора) и раскрывается в паузах.
    Иначе повторы ложились бы на следующие слова и мутили их. key — вход с голосом
    для ключа («[1:a]»), если на входе дилея не весь голос, а только броски."""
    head, tail = "[0:a]", "[w]"
    if under is not None:
        head = "[0:a]" if key else "[0:a]asplit[x][k];[x]"
        tail = (f"[d];[d]{key or '[k]'}sidechaincompress=threshold={10 ** ((under - 18) / 20):.4f}:ratio=2:attack=0.01:"
                "release=150[w]")
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


def _band(low: float, high: float, order: int = 3) -> str:
    """Полоса low–high крутыми фильтрами: order раз по 12 дБ на октаву с каждой
    стороны; 0 — без этой стороны."""
    return ",".join([f"highpass=f={low:.0f}"] * order * bool(low) + [f"lowpass=f={high:.0f}"] * order * bool(high)) or "anull"


def _bands(path: Path, chain: str = "", split=SPLIT, step: float = 0.1) -> list[list[float]]:
    """Уровень полос по окнам step секунд, дБ RMS, за один проход: полосы между
    частотами split, 36 дБ на октаву, как в tone, нулевая — ниже первой частоты.
    Тишина — −150."""
    edges = (0, *split, 0)
    n = len(edges) - 1
    graph = (f"[0:a]{chain}asplit={n}" + "".join(f"[i{k}]" for k in range(n)) + ";"
             + "".join(f"[i{k}]{_band(edges[k], edges[k + 1])},asetnsamples={round(RATE * step)},astats=metadata=1:reset=1:"
                       f"measure_perchannel=none:measure_overall=RMS_level,"
                       f"ametadata@{k}=print:key=lavfi.astats.Overall.RMS_level[o{k}];" for k in range(n))
             + "".join(f"[o{k}]" for k in range(n)) + f"amix=inputs={n}")
    levels = [[] for _ in range(n)]
    for k, db in re.findall(r"\[ametadata@(\d+) @ \w+\] lavfi\.astats\.Overall\.RMS_level=(-?[\d.]+|-inf)",
                            _stderr("-i", path, "-filter_complex", graph)):
        levels[int(k)].append(max(-150.0, float(db)))
    return levels


def _sung(lines: list[tuple[float, float]], n: int, step: float) -> list[int]:
    """Окна по step секунд, середина которых — в строке голоса."""
    return [i for i in range(n) if any(a <= (i + 0.5) * step < b for a, b in lines)]


MID = "pan=mono|c0=0.5*c0+0.5*c1"


def _room(beat: Path, dry: Path, head: str, lift: float, lines: list[tuple[float, float]], work: Path) -> Path:
    """Бит с местом голосу — в work/beat.wav: полосы середины SPLIT приседают ключом
    от тех же полос голоса (ROOM_*). head — цепочка бита до M/S, lift — на сколько
    голос в склейке громче себя сухого против бита, дБ.

    Провал — разность «сжатая полоса − полоса», прибавленная к целой середине:
    без голоса она ноль, и бит выходит бит в бит (замер: −146 дБ), а бока не тронуты
    вовсе. Полоса для провала — bandpass второго порядка на октаву: у него
    вещественная часть равна квадрату модуля, и x − k·BP(x) — честный колокол
    вниз; у крутых фильтров фаза на краях полосы уходит за 90°, и та же разность
    там поднимала бит (+0,1 дБ на куске с голосом вместо провала). Ключу крутизна
    нужна — он крутыми фильтрами. acrossover с sidechaincompress в ffmpeg 8.1
    зависал в половине прогонов (docs/research/2026-09-22/asap-rocky.md), фильтры —
    ни разу."""
    under, over = _bands(beat, f"{head}{MID},"), _bands(dry, f"{MID},")
    sung = _sung(lines, min(len(under[0]), len(over[0])), 0.1)
    depth, key = {}, {}
    for b in range(1, len(SPLIT) + 1):
        masking = sorted(under[b][i] - over[b][i] - lift for i in sung)
        cut = max(0.0, min(ROOM_CAP[b - 1], masking[int(ROOM_SHARE * (len(masking) - 1))])) if sung else 0.0
        if cut:
            depth[b], key[b] = cut, statistics.median(over[b][i] for i in sung) - cut * ROOM_RATIO / (ROOM_RATIO - 1)
    out = work / "beat.wav"
    if not depth:
        print("  место голосу: бит голос не перекрывает")
        _ffmpeg("-i", beat, "-af", head.rstrip(","), *reels.VOICE_CODEC, out)
        return out
    edges = (*SPLIT, 20000)
    for again in range(2):
        # Порог у компрессора не ниже −60 дБ, а верх голоса тише, поэтому порог стоит
        # на −20 дБ, а ключ поднимается до него. Ключ — голос, дополненный тишиной ровно
        # до длины бита (amix по первому входу): кончись голос раньше, сайдчейн оборвал
        # бы бит.
        _ffmpeg("-i", beat, "-i", dry, "-filter_complex",
                f"[0:a]{head}asplit[b][z];[b]{MS},channelsplit[m][s];[m]asplit={len(depth) + 1}[m0]"
                + "".join(f"[p{b}]" for b in depth) + f";[z]volume=0,{MID}[zero];[1:a]{MID}[v];"
                f"[zero][v]amix=inputs=2:duration=first:normalize=0,asplit={len(depth)}" + "".join(f"[k{b}]" for b in depth) + ";"
                + "".join(f"[p{b}]bandpass=f={(edges[b - 1] * edges[b]) ** 0.5:.0f}:t=q:w=1.41,asplit[x{b}][y{b}];"
                          f"[k{b}]{_band(edges[b - 1], edges[b] if b < len(SPLIT) else 0, 2)},volume={-20 - key[b]:.2f}dB[q{b}];"
                          f"[x{b}][q{b}]sidechaincompress=threshold=0.1:ratio={ROOM_RATIO}:attack=5:release={ROOM_RELEASE[b - 1]}:"
                          f"knee=1[c{b}];[y{b}]volume=-1[n{b}];" for b in depth)
                + "[m0]" + "".join(f"[c{b}][n{b}]" for b in depth)
                + f"amix=inputs={2 * len(depth) + 1}:normalize=0[M];[M][s]amerge=inputs=2,{LR}", *reels.VOICE_CODEC, out)
        # Колокола соседних полос складываются, а детектор с быстрой атакой читает слог
        # выше среднего окна: без поправки провал выходил в 1,4–2,3 раза глубже задуманного.
        # Поэтому замер провала по окнам с голосом и один пересчёт порогов.
        done = _bands(out, f"{MID},")
        got = {b: statistics.median(under[b][i] - done[b][i] for i in sung) for b in depth}
        if not again:
            key = {b: key[b] + (got[b] - depth[b]) * ROOM_RATIO / (ROOM_RATIO - 1) for b in depth}
    print("  место голосу: " + ", ".join(f"{edges[b - 1]}–{edges[b]} Гц −{got[b]:.1f} (задумано −{depth[b]:.1f})"
                                          for b in depth) + " дБ")
    return out


def _breaths(voice: Path, words: list[float], beat: tuple[float, float], work: Path) -> tuple[Path | None, list]:
    """Вдохи перед словами words: слово задом наперёд уходит в отзвук, отзвук
    разворачивается обратно и нарастает к слову с доли за BREATH_BEATS до него.
    Возвращает шину и окна вдохов."""
    length, s, spans = beat[0], BREATH_SECONDS, []
    for word in words:
        start = _on_grid(word - BREATH_BEATS * length, beat)
        if start >= 0 and word - start >= length:
            spans.append((start, word))
    if not spans:
        return None, []
    n, out = len(spans), work / "breath.wav"
    _ffmpeg("-i", voice, "-filter_complex",
            f"anoisesrc=r={RATE}:d={s}:c=pink:seed=1[n1];anoisesrc=r={RATE}:d={s}:c=pink:seed=2[n2];"
            f"[n1][n2]amerge=inputs=2,asetnsamples=64,volume='exp(-6.9*t/{s})':eval=frame,asplit={n}"
            + "".join(f"[r{k}]" for k in range(n)) + f";[0:a]asplit={n}" + "".join(f"[v{k}]" for k in range(n)) + ";"
            + "".join(f"[v{k}]atrim=start={word:.3f}:end={word + length:.3f},asetpts=PTS-STARTPTS,areverse,"
                      f"highpass=f=300,lowpass=f=7000,apad=pad_dur={s}[i{k}];[i{k}][r{k}]afir,areverse,"
                      f"atrim=start={s - (word - start):.3f}:end={s:.3f},asetpts=PTS-STARTPTS,afade=t=in:d={word - start:.3f},"
                      f"afade=t=out:st={word - start - 0.03:.3f}:d=0.03,adelay={1000 * start:.0f}|{1000 * start:.0f}[o{k}];"
                      for k, (start, word) in enumerate(spans))
            + "".join(f"[o{k}]" for k in range(n)) + f"amix=inputs={n}:normalize=0:duration=longest[w]",
            "-map", "[w]", "-ar", RATE, *reels.VOICE_CODEC, out)
    return out, spans


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


def _spread(moments: list[tuple[float, float]], gap: float, limit: int = 99) -> list[float]:
    """Моменты (вес, секунда) — самые весомые первыми, не ближе gap секунд друг
    к другу, не больше limit."""
    picked = []
    for _, t in sorted(moments, reverse=True):
        if len(picked) < limit and all(abs(t - c) >= gap for c in picked):
            picked.append(t)
    return sorted(picked)


def _throws(voice: Path, ends: list[float], length: float, work: Path) -> Path | None:
    """Броски: последнее слово фразы у концов ends — в дилей в темп, каждый второй —
    на октаву ниже; повторы приседают под голосом."""
    if not ends:
        return None
    tracks = []
    for name, part in (("throw", ends[::2]), ("throw-low", ends[1::2])):
        points = [(0.0, -120.0)]
        for end in part:
            points += [(end - THROW_WORD - 0.01, -120.0), (end - THROW_WORD, 0.0), (end + 0.03, 0.0), (end + 0.04, -120.0)]
        tracks.append(_gain_track(points, clips.probe_seconds(voice) + 1, work / f"{name}.wav"))
    send, out = work / "throw-send.wav", work / "throws.wav"
    _ffmpeg("-i", voice, "-i", tracks[0], "-i", tracks[1], "-filter_complex",
            f"[1:a]aresample={RATE},pan=stereo|c0=c0|c1=c0[g1];[2:a]aresample={RATE},pan=stereo|c0=c0|c1=c0[g2];"
            f"[0:a]asplit[a][b];[a][g1]amultiply,volume=2[h];"
            f"[b][g2]amultiply,volume=2,asetrate={RATE // 2},aresample={RATE},atempo=2[l];"
            "[h][l]amix=inputs=2:normalize=0:duration=first", *reels.VOICE_CODEC, send)
    _ffmpeg("-i", send, "-i", voice, "-filter_complex", _tempo_delay(length, loudness(voice)[0], "[1:a]"),
            "-map", "[w]", "-ar", RATE, *reels.VOICE_CODEC, out)
    return out


def _snap(beat_file: Path, t: float, length: float) -> float:
    """Доля сетки t — к удару низа (бочке) в пределах четверти доли: живой бит гуляет
    вокруг сетки на ±60 мс (Coruscate), а вырез должен вернуть бит ровно на удар.
    Удара рядом нет — остаётся доля сетки."""
    rise = _rise(beat_file, f"atrim=start={max(0.0, t - length):.3f}:duration={2 * length:.3f},lowpass=f=120,lowpass=f=120,")
    zero, reach = round(min(t, length) * ENV_RATE), round(length / 4 * ENV_RATE)
    near = range(max(2, zero - reach), min(len(rise), zero + reach + 1))
    best = max(near, key=rise.__getitem__, default=zero)
    # Рост уровня считается по окнам 10 мс через одно: удар начался окном раньше.
    return t + (best - 1 - zero) / ENV_RATE if near and rise[best] > 3 else t


def _cut(beat_file: Path, downs: list[float], length: float, work: Path) -> Path:
    """Вырез бита на долю перед каждой сильной долей из downs: уходит за 10 мс
    до доли, возвращается за 5 мс до сильной — её удар целиком."""
    points = [(0.0, 0.0)]
    for down in downs:
        points += [(down - length - 0.03, 0.0), (down - length - 0.01, -120.0), (down - 0.02, -120.0), (down - 0.005, 0.0)]
    return _apply(beat_file, _gain_track(points, clips.probe_seconds(beat_file) + 1, work / "cut.wav"), work / "beat-cut.wav")


def _risers(ends: list[float], length: float, work: Path) -> Path | None:
    """Подъёмы: стерео белый шум на такт до каждого момента ends — фильтр открывается
    от RISE_LOW до RISE_HIGH Гц, громкость растёт на RISE_RANGE дБ, в конце обрыв.
    Один такт синтезируется и ставится копиями."""
    bar = 4 * length
    starts = [end - bar for end in ends if end >= bar]
    if not starts:
        return None
    (work / "rise.cmd").write_text("\n".join(f"{n * 0.02:.2f} lowpass@rise f {RISE_LOW * (RISE_HIGH / RISE_LOW) ** (n * 0.02 / bar):.0f};"
                                             for n in range(int(bar / 0.02))))
    out = work / "risers.wav"
    _ffmpeg("-filter_complex",
            f"anoisesrc=r={RATE}:d={bar:.3f}:c=white:seed=3[n1];anoisesrc=r={RATE}:d={bar:.3f}:c=white:seed=4[n2];"
            f"[n1][n2]amerge=inputs=2,highpass=f=200,asendcmd=f='{work / 'rise.cmd'}',lowpass@rise=f={RISE_LOW},"
            f"asetnsamples=256,volume='pow(10,{RISE_RANGE / 20}*(t/{bar:.3f}-1))':eval=frame,"
            f"afade=t=out:st={bar - 0.01:.3f}:d=0.01,asplit={len(starts)}" + "".join(f"[r{k}]" for k in range(len(starts))) + ";"
            + "".join(f"[r{k}]adelay={1000 * t:.0f}|{1000 * t:.0f}[d{k}];" for k, t in enumerate(starts))
            + "".join(f"[d{k}]" for k in range(len(starts))) + f"amix=inputs={len(starts)}:normalize=0:duration=longest",
            *reels.VOICE_CODEC, out)
    return out


def _audible(bed: Path, parts: list[tuple[str, Path, float, list, list]]) -> str:
    """Слышимость приёмов: громкость каждого в его окнах к биту в окнах ref, LU —
    энергетическое среднее окон EBU R128 M (0,4 с), чьи середины лежат в окне.
    Для выреза шина — сам бит: насколько он тише в вырезе, чем такт до него.
    Окна, где бит молчит (вдох в вступлении без бита), не в счёт: там не с чем сравнивать."""
    def level(trace, spans) -> float:
        hits = [10 ** (m / 10) for t, m, _ in trace if any(a <= t - 0.2 <= b for a, b in spans)]
        return 10 * math.log10(statistics.fmean(hits)) if hits else -120.0
    whole, under = reels.meter(bed)
    report = []
    for name, path, gain, spans, ref in parts:
        pairs = [(span, back) for span, back in zip(spans, ref) if level(under, [back]) >= whole - 20]
        if pairs:
            spans, ref = zip(*pairs)
            report.append(f"{name} {level(reels.meter(path)[1] if path != bed else under, spans) + gain - level(under, ref):+.0f}")
    return ", ".join(report) + " LU к биту"


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


def _glue(total: Path) -> str:
    """Склейка шины (GLUE) с порогом по замеру: сжатие GLUE дБ по EBU R128."""
    level = loudness(total)[0]
    threshold, drop = level - 2 * GLUE, 0.0
    for _ in range(4):
        chain = f"acompressor=threshold={10 ** (threshold / 20):.5f}:ratio=2:attack=30:release=200,"
        drop = level - loudness(total, chain)[0]
        if abs(drop - GLUE) < 0.2:
            break
        threshold -= 2 * (GLUE - drop)
    print(f"  склейка шины: 2:1, сжатие {drop:.1f} дБ")
    return chain


def _master(total: Path, glue: str, master: Path) -> tuple[float, float, float]:
    """Мастер: низ в моно, склейка шины, клиппер и ограничитель до MASTER_LUFS —
    в master. Возвращает громкость, истинный пик и подъём.

    Клиппер и ограничитель съедают часть громкости, поэтому подъём подбирается
    замером. Пик волны лежит между отсчётами и на 44,1 кГц выходит до дБ выше
    порога, поэтому оба работают на учетверённой частоте. Клиппер упирается в ноль,
    и сигнал к нему подводится так, чтобы ноль пришёлся на CLIP дБ над порогом."""
    push, limit = MASTER_LUFS - loudness(total, glue)[0], CEILING - 0.3
    for _ in range(6):
        _ffmpeg("-i", total, "-af",
                f"{LOW_MONO},{glue}volume={push - limit - CLIP:.2f}dB,aresample={4 * RATE},{CLIPPER},"
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
    return level, peak, push


def mix(vocal: Path, beat: Path, out: Path, style: str = "чисто", design: bool = False,
        voice: float = 0.0, echo: float = 0.0) -> Path:
    """Склейка в out/skleyka.wav, промежуточное — в out/work.

    Ручки бота: voice — голос к биту, дБ («голос громче / тише» — по ±2): сдвигает
    и баланс, и цель райдера, иначе в местах, где бит перекрывал голос, райдер
    съел бы поправку; echo — доля отзвука, дилея и бросков к своей, дБ («эха
    больше / меньше» — по ±4); дабл не эхо, его не трогает."""
    look, work = STYLES[style], out / "work"
    work.mkdir(parents=True, exist_ok=True)
    print(f"  стиль «{style}»: {look['about']}" + (", саунд-дизайн" if design else "")
          + (f", голос {voice:+g} дБ" if voice else "") + (f", эхо {echo:+g} дБ" if echo else ""))

    clean = f"{FORMAT},{_center(vocal)}{HIGHPASS}"
    if look.get("autotune") and (tune := _autotune(beat)):
        clean += f",{tune}"
    squeezed, dry = work / "vocal-comp.wav", work / "vocal.wav"
    _ffmpeg("-i", vocal, "-af", f"{clean},volume={VOCAL_LUFS - loudness(vocal, clean + ',')[0]:.2f}dB,{VOCAL_CHAIN}"
            + (f",{DENSE}" if look.get("dense") else ""), *reels.VOICE_CODEC, squeezed)
    lines = _lines(_envelope(squeezed))
    _ffmpeg("-i", squeezed, "-af", _equalizer(squeezed, lines, work) + DEESSER + (f",{look['color']}" if "color" in look else ""),
            *reels.VOICE_CODEC, dry)
    sung = loudness(dry)[0]

    # Противофаза — по слышимой полосе: в ультразвуке и на самом низу бывает что угодно.
    heard = f"{FORMAT},highpass=f=60,lowpass=f=12000,"
    width = stereo(beat, heard)[0]
    flip = "pan=stereo|c0=c0|c1=-1*c1," if width < 0 else ""
    head = f"{FORMAT},{flip}"
    print(f"  бит: корреляция каналов {width:+.2f}" + (", один канал перевёрнут" if flip else ""))
    ducked = _room(beat, dry, head, loudness(beat, head)[0] + VOCAL_OVER_BEAT + voice - sung, lines, work)
    under = loudness(ducked)[0]
    ridden = _ride(dry, ducked, under + VOCAL_OVER_BEAT + voice - sung, RIDE_TARGET + voice, work)
    level = loudness(ridden)[0]

    rhythm = grid(beat) if design or look.get("delay", ("",))[0] == "в темп" else None
    if rhythm:
        print(f"  темп {60 / rhythm[0]:.1f} ударов в минуту, сильная доля {rhythm[1]:.2f} с")
    sends = []
    if "reverb" in look:
        seconds, share = look["reverb"]
        sends.append(("reverb", _reverb(seconds), share))
    if "delay" in look:
        kind, share = look["delay"]
        sends.append(("delay", reels.DELAY if kind == "коротко" else _tempo_delay(rhythm[0], level), share))
    if look.get("double") and stereo(dry)[0] > 0.98:
        sends.append(("double", DOUBLE, DOUBLE_SHARE))
    wets = []  # (шина, громкость в склейке по EBU R128)
    for name, graph, share in sends:
        wet = work / f"{name}.wav"
        _ffmpeg("-i", ridden, "-filter_complex", graph, "-map", "[w]", "-ar", RATE, *reels.VOICE_CODEC, wet)
        wets.append((wet, level + 20 * math.log10(share) + (0.0 if name == "double" else echo)))
    bed, tricks = ducked, []
    if design and lines:
        length, first = rhythm[0], lines[0][0]
        phrases, trace = _lines(_envelope(ridden), PHRASE_RANGE, PHRASE_PAUSE), reels.meter(ducked)[1]

        def playing(a: float, b: float) -> bool:
            """Бит играет в полную силу: без него вырезать нечего, а подъём уходит в тишину."""
            return max((m for t, m, _ in trace if a <= t - 0.2 <= b), default=-120.0) >= under - 10

        # Вход — не раньше четырёх тактов после первого слова: там своё вступление;
        # и там, где бит играет и до выреза, и после сильной доли — своя пауза в бите
        # (у Coruscate на 259 с) вырезу не место.
        entries, downs = [], []
        for t in _spread([(nxt[0] - prev[1], nxt[0]) for prev, nxt in zip(phrases, phrases[1:])
                          if nxt[0] - prev[1] >= ENTRY_BEATS * length and nxt[0] >= first + 16 * length],
                         ENTRY_BARS * 4 * length):
            down = _snap(ducked, _on_grid(t, (4 * length, rhythm[1])), length)
            if playing(down - 2 * length, down - length) and playing(down, down + length):
                entries.append(t)
                downs.append(down)
        ends = _spread([(nxt[0] - prev[1], prev[1]) for prev, nxt in zip(phrases, [*phrases[1:], (math.inf,)])],
                       THROW_BARS * 4 * length, THROWS)
        print(f"  саунд-дизайн: первое слово {first:.2f} с, входы " + (", ".join(f"{t:.1f}" for t in entries) or "—")
              + f" с; бросков {len(ends)}, на октаву ниже {len(ends) // 2}")
        bed = _opening(ducked, first, rhythm, work)
        if downs:
            bed = _cut(bed, downs, length, work)
            tricks.append(("вырезы", bed, None, [(d - length + 0.2, d - 0.2) for d in downs],
                           [(d - 5 * length, d - length) for d in downs]))
        # Бит вступает позже голоса (у Coruscate — на 29,9 с, после акапеллы с 10 с):
        # в его первую долю — тоже подъём, вырезать там нечего.
        start = next((t - 0.4 for t, m, _ in trace if m >= under - 10), 0.0)
        rises = [d - length for d in downs]
        if start > first + 4 * length:
            rises.append(_snap(ducked, _on_grid(start, rhythm), length))
            print(f"  бит вступает на {rises[-1]:.2f} с — подъём в его первую долю")
        breath, spans = _breaths(ridden, [first, *entries], rhythm, work)
        tricks += [("вдохи", breath, under + BREATH_DB, spans, spans),
                   ("подъёмы", _risers(sorted(rises), length, work), under + RISE_DB,
                    [(d - 2 * length, d - length) for d in downs], [(d - 2 * length, d - length) for d in downs]),
                   ("броски", _throws(ridden, ends, length, work), under + THROW_DB + echo,
                    [(e, e + 3 * length) for e in ends], [(e, e + 3 * length) for e in ends])]
        wets += [(path, target) for _, path, target, _, _ in tricks if path and target is not None]
    gains = {wet: target - loudness(wet)[0] for wet, target in wets}
    parts = [(ridden, 0.0), (bed, 0.0), *gains.items()]
    total = work / "sum.wav"
    _ffmpeg(*(arg for part, _ in parts for arg in ("-i", part)), "-filter_complex",
            "".join(f"[{n}:a]volume={gain:.2f}dB[s{n}];" for n, (_, gain) in enumerate(parts))
            + "".join(f"[s{n}]" for n in range(len(parts)))
            + f"amix=inputs={len(parts)}:duration=longest:normalize=0",
            *reels.VOICE_CODEC, total)
    if tricks:
        print("  слышно: " + _audible(bed, [(name, path, gains.get(path, 0.0), spans, ref)
                                            for name, path, _, spans, ref in tricks if path and spans]))

    master = out / "skleyka.wav"
    level, peak, push = _master(total, _glue(total), master)
    if design and lines and (at := _stop_at(ducked, lines, rhythm)) is not None:
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
                        help="саунд-дизайн: вдохи, фильтр и вырезы бита, подъёмы, броски, остановка плёнки")
    parser.add_argument("--voice", type=float, default=0.0, help="голос к биту, дБ (ручки бота — по ±2)")
    parser.add_argument("--echo", type=float, default=0.0, help="доля отзвука, дилея и бросков, дБ (ручки бота — по ±4)")
    args = parser.parse_args()
    if args.mix:
        master = mix(*args.mix, args.out, args.style, args.design, args.voice, args.echo)
        compare(*args.mix, master, args.out)
        print(f"  готово: {master}, {args.out / 'do.mp3'}, {args.out / 'posle.mp3'}")
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
