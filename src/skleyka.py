"""СКЛЕЙКА — вокал и бит в черновой трек: бот сводит две дорожки за пару минут.

Зачем. Артисту без денег свести трек негде: инженер берёт 3–10 тысяч, самому
учиться годами. Две дорожки, выгруженные с одного начала, — вокал и бит — бот
склеивает в трек, который не стыдно выложить, а выложенный ведёт прямо в ОТБОР.
Обещание честное: черновая склейка автоматом, не работа звукорежиссёра.
Имя СВЕДЕНИЕ сначала носили проценты совпадения (теперь ДВОЙНИК, src/svedenie.py),
поэтому СКЛЕЙКА —
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
   первым словом и на входах голоса, бит из-под фильтра до первого слова (если
   у бита там нет своего дропа), на входах
   после пауз — подъём шума и вырез бита перед сильной долей, броски дилея на концах
   фраз (каждый второй — на октаву ниже), остановка плёнки в конце. Всё синтезом
   ffmpeg, без чужих сэмплов, на доли и такты бита (grid), громкость приёмов — к биту.
7. Мастер — низ ниже 120 Гц в моно, склейка шины 2:1, жёсткий клиппер по верхушкам
   ударов и ограничитель до MASTER_LUFS, пик не выше CEILING dBTP.

Ручки бота — mix(..., voice=, echo=): голос к биту и доля эха, в дБ. Дорожки
по отдельности — mix(..., parts=): даблы за ведущим его же райдером, бэки шире
и дальше в отзвук, эдлибы — каждый выкрик в свою точку панорамы и в эхо (PARTS); место голосу — только в музыке,
вырезы саунд-дизайна — только барабанов и баса. Простой режим — две дорожки.

Промежуточное — во float: пики выше нуля между шагами не срезаются, режет только
мастер. Подгонку под референс (Matchering) сюда не тащим: это
новый пакет и обещание «как у звезды», которое черновая склейка не сдержит.

Проверка — на слух: ДО (простая сумма дорожек) и ПОСЛЕ одной громкости по LUFS.
Громкое всегда кажется лучше, и без этого сравнение нечестное.

Выход из лимита суток — только тому, кто в него упёрся: две кнопки под отказом,
бесплатная функция остаётся бесплатной. «Позвать артиста» — личная ссылка
?start=skleyka_r<код>, и склейка сверх лимита даётся за первую готовую склейку
приглашённого, а не за переход: переход второй аккаунт накрутит за минуту, склейка —
это подписка на канал и настоящие дорожки. «Больше склеек» — счёт в звёздах Telegram:
цифровой товар Telegram пускает только за звёзды (XTR), и платёжный провайдер для них
не нужен — ни договора, ни ключа, provider_token пустой; возврат по просьбе покупателя —
правило Telegram, поэтому /vozvrat владельца, а /paysupport покупателя (его Telegram
тоже требует) шлёт владельцу вопрос вместе с номерами платежей: переписываться
вручную не нужно. За звёзды — только число склеек.
Коды, бонусы и номера платежей — в SKLEYKA_FILE, приватном хранилище.

    python -m src.skleyka --mix ВОКАЛ БИТ --out ПАПКА   склейка и пара ДО/ПОСЛЕ одной громкости
    python -m src.skleyka --mix ВОКАЛ БИТ --out ПАПКА --style грязно --design
    python -m src.skleyka --mix ВОКАЛ БИТ --out ПАПКА --voice 2 --echo -4   ручки «голос громче», «эха меньше»
    python -m src.skleyka --mix ВОКАЛ БИТ --out ПАПКА --part бэк БЭКИ --part барабаны БАРАБАНЫ   по дорожкам
    python -m src.skleyka --mix ВОКАЛ БИТ --out ПАПКА --like ТРЕК   тембр, ширина и громкость — к чужому треку
"""

from __future__ import annotations

import argparse
import array
import contextlib
import html
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

from . import clips, config, llm, reels, state, telegram
from .sources import itunes

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
# Свой дроп бита: низ до 150 Гц (бочка и бас) за это окно вырастает на OWN_DROP дБ
# и больше — тогда фильтра нет. У Little Chicago's Finest бочка и бас входят на 8 с,
# за 1,7 с до первого слова (низ −65 → −29 дБ), и фильтр глушил готовый дроп —
# владелец 22.09: «эффект саунд-дизайна вообще лишний и безвкусный». У остальных
# четырёх треков низ в окне ровный (±5 дБ) или бит молчит.
OWN_DROP = 12.0
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
# «Как у <артиста>» — подгонка к 30-секундному превью его трека в магазине: октавы
# микса к 1 кГц, стороны к середине и громкость. Не Matchering: у того подгонка
# без предела, и чужой мастер перекраивал бы трек целиком, а здесь только наклон —
# колокола не больше LIKE_TONE дБ, стороны не больше LIKE_WIDTH, громкость в LIKE_LUFS.
# Превью — кусок трека, обычно припев: для наклона тембра и ширины его хватает,
# а для громкости берётся его EBU R128 в пределах ряда рэп-мастеров.
LIKE_TONE = 3.0
LIKE_WIDTH = 3.0
LIKE_LUFS = (-12.0, -8.0)
LIKE_PASSES = 2
# Стороны — выше 150 Гц: ниже 120 мастер и так сводит в моно.
LIKE_BAND = "highpass=f=150,"


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


def _sum(inputs: list[tuple[Path, float]], dest: Path, before: str = "anull") -> Path:
    """Дорожки с поправками громкости, дБ, — в одну dest; before — цепочка каждой до суммы."""
    _ffmpeg(*(arg for path, _ in inputs for arg in ("-i", path)), "-filter_complex",
            "".join(f"[{n}:a]{before},volume={gain:.2f}dB[s{n}];" for n, (_, gain) in enumerate(inputs))
            + "".join(f"[s{n}]" for n in range(len(inputs)))
            + f"amix=inputs={len(inputs)}:duration=longest:normalize=0", *reels.VOICE_CODEC, dest)
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
    доле первого слова. Слово с первой секунды или свой дроп у бита (OWN_DROP) —
    бит как есть."""
    length = beat[0]
    opened = _on_grid(first - 0.1, beat, math.ceil)
    sweep = opened - OPEN_BEATS * length
    if sweep < length:
        return beat_file
    shut = max(0.0, _on_grid(opened - FILTER_BEATS * length, beat))
    low, step = _envelope(beat_file, f"atrim=start={shut:.3f}:end={opened:.3f},lowpass=f=150,lowpass=f=150,"), round(2 * length * ENV_RATE)
    halves = [statistics.fmean(low[i:i + step]) for i in range(0, len(low), step)]
    if drop := next((k for k in range(1, len(halves)) if halves[k] - min(halves[:k]) >= OWN_DROP), None):
        print(f"  у бита свой дроп на {shut + drop * 2 * length:.1f} с — без фильтра до первого слова")
        return beat_file
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


# Где голос встаёт на бит. Оба файла склейка кладёт от нуля, и вокал, выгруженный
# не с начала проекта, уезжает: 26.09 у вокала на 34 с первое слово было на 2,8 с,
# а бас в бите на 2:33 входил на 13 с — голос звучал на вступлении, и человек
# написал, что он «не попадает в дроп». Где голос стоял в проекте, по звуку не узнать:
# читать на вступлении тоже можно. Поэтому сама склейка голос не двигает, а называет
# дроп и даёт его кнопкой (DROP_NOTE), и место голоса можно сказать словами (ручка at).
def drops(beat: Path, rhythm: tuple[float, float]) -> list[float]:
    """Дропы бита: доли, где низ до 120 Гц (бочка и бас) за такт после становится
    громче такта до на OWN_DROP дБ. Порог громкости после — на 20 дБ ниже громкой
    части, а не на 10: в первом такте после дропа у 808 бывают провалы."""
    _, trace = reels.meter(beat, "lowpass=f=120,")
    level = [m for _, m, _ in trace]
    n = max(1, round(4 * rhythm[0] / (trace[1][0] - trace[0][0])))
    loud = sorted(level)[int(0.9 * len(level))]
    rise = {i: statistics.fmean(level[i:i + n]) - statistics.fmean(level[i - n:i])
            for i in range(n, len(level) - n) if statistics.fmean(level[i:i + n]) >= loud - 20}
    found = []
    for i, r in rise.items():
        if r >= OWN_DROP and r >= max(rise.get(j, r) for j in range(i - n, i + n + 1)) and (not found or i - found[-1] > n):
            found.append(i)
    # Громкость M меряется окном 0,4 с: край дропа — на полокна раньше.
    return [round(_on_grid(trace[i][0] - 0.2, rhythm), 2) for i in found]


def first_word(vocal: Path) -> float:
    """Секунда первого слова в файле голоса."""
    lines = _lines(_envelope(vocal, f"{FORMAT},"))
    return round(lines[0][0], 2) if lines else 0.0


def _moved(path: Path, shift: float, dest: Path) -> Path:
    """Дорожка голоса на shift секунд позже (тишиной в начале) или раньше (срезом начала)."""
    _ffmpeg("-i", path, "-af", f"adelay=delays={1000 * shift:.0f}:all=1" if shift > 0
            else f"atrim=start={-shift:.3f},asetpts=PTS-STARTPTS", *reels.VOICE_CODEC, dest)
    return dest


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


def _master(total: Path, glue: str, master: Path, target: float = MASTER_LUFS) -> tuple[float, float, float]:
    """Мастер: низ в моно, склейка шины, клиппер и ограничитель до target LUFS —
    в master. Возвращает громкость, истинный пик и подъём.

    Клиппер и ограничитель съедают часть громкости, поэтому подъём подбирается
    замером. Пик волны лежит между отсчётами и на 44,1 кГц выходит до дБ выше
    порога, поэтому оба работают на учетверённой частоте. Клиппер упирается в ноль,
    и сигнал к нему подводится так, чтобы ноль пришёлся на CLIP дБ над порогом."""
    push, limit = target - loudness(total, glue)[0], CEILING - 0.3
    for _ in range(6):
        _ffmpeg("-i", total, "-af",
                f"{LOW_MONO},{glue}volume={push - limit - CLIP:.2f}dB,aresample={4 * RATE},{CLIPPER},"
                f"volume={limit + CLIP:.2f}dB,"
                f"alimiter=limit={10 ** (limit / 20):.4f}:attack=5:release=150:asc=1:level=0:latency=1,"
                f"aresample={RATE}",
                "-c:a", "pcm_s24le", master)
        level, peak = loudness(master)
        if abs(level - target) < 0.3 and peak <= CEILING:
            break
        push += target - level
        # Ровно на превышение порог сходится к потолку снизу бесконечно — с запасом 0,1 дБ.
        limit -= peak - CEILING + 0.1 if peak > CEILING else 0.0
    return level, peak, push


def _sides(path: Path) -> float:
    """Стороны к середине выше LIKE_BAND, дБ: чем больше, тем шире."""
    mid, side = _channels(path, f"{FORMAT},{LIKE_BAND}{MS},")[:2]
    return side - mid


def _shape(total: Path, gains: dict[int, float], wide: float, work: Path) -> Path:
    """Сумма склейки с колоколами gains и сторонами громче на wide дБ — в work/like.wav."""
    k, matched = 10 ** (wide / 20), work / "like.wav"
    _ffmpeg("-i", total, "-af", f"{_bells(gains)}pan=stereo|c0={(1 + k) / 2:.4f}*c0+{(1 - k) / 2:.4f}*c1"
            f"|c1={(1 - k) / 2:.4f}*c0+{(1 + k) / 2:.4f}*c1", *reels.VOICE_CODEC, matched)
    return matched


def mix(vocal: Path, beat: Path, out: Path, style: str = "чисто", design: bool = False,
        voice: float = 0.0, echo: float = 0.0, parts: list[tuple[str, Path]] = (), like: Path | None = None) -> Path:
    """Склейка в out/skleyka.wav, промежуточное — в out/work.

    parts — дорожки по отдельности, [(роль, файл)]: даблы, бэки и эдлибы встают вокруг
    ведущего vocal (voices); пришли барабаны или бас — место голосу делается только
    в остальном бите, а вырезы саунд-дизайна — только в них: музыка под вырезом идёт
    дальше. beat — весь бит вместе, по нему меряются темп, громкость и удары.

    Ручки бота: voice — голос к биту, дБ («голос громче / тише» — по ±2): сдвигает
    и баланс, и цель райдера, иначе в местах, где бит перекрывал голос, райдер
    съел бы поправку; echo — доля отзвука, дилея и бросков к своей, дБ («эха
    больше / меньше» — по ±4); дабл не эхо, его не трогает. like — превью трека, к которому
    подтянуть тембр, ширину и громкость («как у <артиста>», _like)."""
    look, work = STYLES[style], out / "work"
    work.mkdir(parents=True, exist_ok=True)
    print(f"  стиль «{style}»: {look['about']}" + (", саунд-дизайн" if design else "")
          + (f", голос {voice:+g} дБ" if voice else "") + (f", эхо {echo:+g} дБ" if echo else ""))

    clean = f"{FORMAT},{_center(vocal)}{HIGHPASS}"
    if tune := look.get("autotune") and _autotune(beat):
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
    # Барабаны и бас пришли отдельно — место голосу только в остальном бите.
    drums = [path for part, path in parts if part in ("барабаны", "бас")]
    music = [path for part, path in parts if part in ("бит", "музыка")] if drums else [beat]
    kit = _sum([(path, 0.0) for path in drums], work / "kit.wav", head.rstrip(",")) if drums else None
    room = None
    if music:
        whole = music[0] if len(music) == 1 else _sum([(path, 0.0) for path in music], work / "music.wav")
        room = _room(whole, dry, head, loudness(beat, head)[0] + VOCAL_OVER_BEAT + voice - sung, lines, work)
    ducked = _sum([(room, 0.0), (kit, 0.0)], work / "beat-parts.wav") if room and kit else room or kit
    under = loudness(ducked)[0]
    ridden = _ride(dry, ducked, under + VOCAL_OVER_BEAT + voice - sung, RIDE_TARGET + voice, work)
    level = loudness(ridden)[0]
    placed = voices([(part, path) for part, path in parts if part in PARTS], level, work / "ride.wav", work, tune or "")

    adlibs = [(path, gain) for path, gain, part in placed if part == "эдлиб"]
    rhythm = grid(beat) if design or adlibs or look.get("delay", ("",))[0] == "в темп" else None
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
    # Свой отзвук бэков и эдлибов: посыл каждой части — на её громкости в сумме плюс reverb,
    # и шина отзвука выходит той же громкостью, что посыл.
    if going := [(path, gain + PARTS[part]["reverb"]) for path, gain, part in placed if PARTS[part]["reverb"] is not None]:
        send, wet = _sum(going, work / "send-parts.wav"), work / "parts-room.wav"
        _ffmpeg("-i", send, "-filter_complex", _reverb(PARTS_ROOM), "-map", "[w]", "-ar", RATE, *reels.VOICE_CODEC, wet)
        wets.append((wet, loudness(send)[0] + echo))
    # Эхо эдлибов — своё, в темп, приседает под ведущим: повторы — в его паузах.
    for n, (path, gain) in enumerate(adlibs):
        wet = work / f"adlib-echo{n}.wav"
        _ffmpeg("-i", path, "-i", ridden, "-filter_complex", _tempo_delay(rhythm[0], level, "[1:a]"),
                "-map", "[w]", "-ar", RATE, *reels.VOICE_CODEC, wet)
        wets.append((wet, loudness(path)[0] + gain + ADLIB_ECHO + echo))
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
        # Вырез и фильтр до первого слова не пересекаются по времени (входы — через
        # 16 долей после него), поэтому порядок не важен, а вырез удобнее резать первым:
        # пришли барабаны и бас — только их.
        bed = ducked
        if downs:
            bed = _cut(kit or ducked, downs, length, work)
            if kit and room:
                bed = _sum([(room, 0.0), (bed, 0.0)], work / "beat-cut-parts.wav")
        bed = _opening(bed, first, rhythm, work)
        if downs:
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
    total = _sum([(ridden, 0.0), (bed, 0.0), *((path, gain) for path, gain, _ in placed), *gains.items()], work / "sum.wav")
    if tricks:
        print("  слышно: " + _audible(bed, [(name, path, gains.get(path, 0.0), spans, ref)
                                            for name, path, _, spans, ref in tricks if path and spans]))

    # «Как у <артиста>»: сверяется готовый мастер, а не сумма до него — клиппер
    # и ограничитель возвращали половину поправки, — и колокол в октаву недобирает
    # до своей середины, поэтому поправка доводится за LIKE_PASSES проходов мастера.
    master, target, gains, wide = out / "skleyka.wav", MASTER_LUFS, dict.fromkeys(TONE, 0.0), 0.0
    if like:
        theirs, their_sides = tone(like, FORMAT), _sides(like)
        target = max(LIKE_LUFS[0], min(LIKE_LUFS[1], loudness(like)[0]))
    for attempt in range(LIKE_PASSES + 1 if like else 1):
        source = _shape(total, gains, wide, work) if attempt else total
        level, peak, push = _master(source, _glue(source), master, target)
        if not like:
            break
        ours, miss_sides = tone(master, FORMAT), their_sides - _sides(master)
        miss = {f: theirs[f] - ours[f] for f in TONE}
        print(f"  к референсу, проход {attempt}: тембр отходит на {statistics.fmean(map(abs, miss.values())):.1f} дБ "
              f"в среднем, стороны — на {miss_sides:+.1f}")
        step = ({f: round(max(-LIKE_TONE, min(LIKE_TONE, gains[f] + miss[f])), 1) for f in TONE},
                round(max(-LIKE_WIDTH, min(LIKE_WIDTH, wide + miss_sides)), 1))
        if attempt == LIKE_PASSES or max(abs(step[1] - wide), *(abs(step[0][f] - gains[f]) for f in TONE)) < 0.5:
            break
        gains, wide = step
    if like:
        print("  как у референса: тембр " + (", ".join(f"{f} Гц {g:+.1f}" for f, g in gains.items() if g) or "как был")
              + f"; стороны {wide:+.1f} дБ; громкость {target:.1f} LUFS")
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


# ─────────────────────────── части голоса ───────────────────────────
#
# Даблы, бэки и эдлибы, присланные отдельно, не сваливаются в главный голос: у каждой
# роли у инженеров своё место (docs/research/2026-09-22/zvukorezhissura.md, раздел 6).
# Даблы тише и суше ведущего, низа срезано больше, эсок нет (KRUG, Podlesny Twins), и ведёт
# их тот же райдер — они идут за словами ведущего; два и больше — по краям на одном уровне
# (Сениор), один — в центре под ведущим. Бэки — очень широко (Goldberg) и дальше, в отзвук;
# эдлибы — по краям и в эхо: им можно меньше внятности и больше эффектов (Hoffman, Waves).
# Цифр громкости у инженеров нет, только «достаточно тихо» (KRUG): дБ к ведущему — выбор
# склейки. Одна дорожка бэков расходится в стороны расширителем Сениора (DOUBLE)
# без центра — центр остаётся ведущему (Heldens).
#
# Пространство. У ведущего отзвук и дилей — отдельные шины, подмешанные тихо: голос
# остаётся сухим и чётким (Firkins — 15 % мокрого, Schaeffer, Joshua). Бэки и эдлибы,
# наоборот, растворяются в своём отзвуке (владелец 22.09.2026: «на бэке оставляю дилей
# и реверб на той же шине… чтобы они растворялись»; Bainz — броски «100‑percent wet»):
# reverb — громкость их общего отзвука PARTS_ROOM к ним самим, дБ, мимо стиля ведущего;
# None — сухо, как даблы у KRUG. Ручка «эха» двигает и его.
#
# Эдлибы — «эй», «у», «йа» между строк — владелец 22.09.2026 сводил так: «по панировке
# раскидывал и эхо накидывал». Поэтому каждый выкрик встаёт в свою точку панорамы
# по кругу ADLIB_PANS — лево, право, ближе к центру слева и справа (_scatter), а у каждой
# дорожки эдлибов своё эхо в темп на ADLIB_ECHO дБ к ней: повторы приседают под
# ведущим и звучат в паузах, как броски саунд-дизайна. Полоса эдлибов уже, чем
# у ведущего, — 300 Гц … 5 кГц, как советует Rewak (Splice) отличать их от ведущего,
# и лёгкий перегруз (LaRay на эдлибах Cardi B — Sansamp): выкрик читается фоном,
# а не вторым ведущим.
PARTS = {
    "дабл": {"cut": 150, "gain": -8.0, "pan": 0.8, "deess": "deesser=i=0.8", "reverb": None},
    "бэк": {"cut": 200, "gain": -10.0, "pan": 0.9, "deess": DEESSER, "reverb": -14.0},
    "эдлиб": {"cut": 300, "gain": -6.0, "pan": 0.7, "deess": DEESSER, "reverb": -16.0,
              "color": "lowpass=f=5000,volume=6dB,asoftclip=type=atan:oversample=4,volume=-6dB"},
}
PARTS_ROOM = 1.2
ADLIB_PANS = (-0.7, 0.7, -0.4, 0.4)
ADLIB_PAUSE = 0.2
ADLIB_LONG = 2.0
ADLIB_ECHO = -8.0


def _pan(position: float) -> str:
    """Моно — в точку панорамы от −1 (левый край) до 1 с постоянной мощностью."""
    angle = (position + 1) * math.pi / 4
    return f"pan=stereo|c0={math.cos(angle):.4f}*c0|c1={math.sin(angle):.4f}*c0"


def _scatter(events: list[tuple[float, float]], first: int = 0) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """Громкость левого и правого канала по ходу дорожки, точки (секунда, дБ) для _gain_track:
    выкрик events[i] — в точку ADLIB_PANS[first + i] с постоянной мощностью. Точка меняется
    посреди паузы перед выкриком, за 5 мс: в тишине не щёлкает."""
    left, right = [], []
    for i, (start, _) in enumerate(events):
        angle = (ADLIB_PANS[(first + i) % len(ADLIB_PANS)] + 1) * math.pi / 4
        gains = (20 * math.log10(max(math.cos(angle), 1e-6)), 20 * math.log10(max(math.sin(angle), 1e-6)))
        at = 0.0
        if i:
            at = (events[i - 1][1] + start) / 2
            left.append((at, left[-1][1]))
            right.append((at, right[-1][1]))
            at += 0.005
        left.append((at, gains[0]))
        right.append((at, gains[1]))
    return left, right


def voices(parts: list[tuple[str, Path]], level: float, ride: Path | None, work: Path,
           tune: str = "") -> list[tuple[Path, float, str]]:
    """Части голоса сухими дорожками на своих местах: [(файл, поправка громкости в сумме, роль)].

    Цепочка — как у ведущего: срез, громкость к VOCAL_LUFS, компрессия, тембр по замеру,
    де-эссер своей роли; дальше — своя точка панорамы и своя громкость к ведущему level.
    tune — автотюн ведущего: ненастроенный дабл под настроенным голосом звучит фальшиво."""
    placed = []
    for n, (part, path) in enumerate(parts):
        look, same = PARTS[part], [i for i, (other, _) in enumerate(parts) if other == part]
        chain = f"{FORMAT},{_center(path)}highpass=f={look['cut']},pan=mono|c0=0.5*c0+0.5*c1" + (f",{tune}" if tune else "")
        squeezed, dry = work / f"part{n}-comp.wav", work / f"part{n}.wav"
        _ffmpeg("-i", path, "-af", f"{chain},volume={VOCAL_LUFS - loudness(path, chain + ',')[0]:.2f}dB,{VOCAL_CHAIN}",
                *reels.VOICE_CODEC, squeezed)
        tone = f"{_equalizer(squeezed, _lines(_envelope(squeezed)), work)}{look['deess']}" \
            + (f",{look['color']}" if "color" in look else "")
        events = _lines(_envelope(squeezed), VOICE_RANGE, ADLIB_PAUSE) if part == "эдлиб" else []
        # Длинные партии под видом эдлибов (сплошной бэк) по кругу встали бы на минуту
        # в одну сторону — такие расходятся в стороны, как бэки.
        scattered = len(events) > 1 and statistics.median(b - a for a, b in events) <= ADLIB_LONG
        if scattered:
            seconds = clips.probe_seconds(squeezed) + 1
            left, right = (_gain_track(points, seconds, work / f"part{n}-{side}.wav")
                           for side, points in zip("lr", _scatter(events, 2 * same.index(n))))
            _ffmpeg("-i", squeezed, "-i", left, "-i", right, "-filter_complex",
                    f"[0:a]{tone},aformat=channel_layouts=mono,pan=stereo|c0=c0|c1=c0[s];[1:a]aresample={RATE}[l];[2:a]aresample={RATE}[r];"
                    "[l][r]join=inputs=2:channel_layout=stereo[g];[s][g]amultiply,volume=2", *reels.VOICE_CODEC, dry)
        elif len(same) == 1 and part != "дабл":
            _ffmpeg("-i", squeezed, "-filter_complex", f"[0:a]{tone}[t];" + DOUBLE.replace("[0:a]", "[t]"),
                    "-map", "[w]", "-ar", RATE, *reels.VOICE_CODEC, dry)
        else:
            position = 0.0 if len(same) == 1 else look["pan"] * (1 if same.index(n) % 2 == 0 else -1)
            _ffmpeg("-i", squeezed, "-af", f"{tone},{_pan(position)}", *reels.VOICE_CODEC, dry)
        if part == "дабл" and ride:
            dry = _apply(dry, ride, work / f"part{n}-ride.wav")
        placed.append((dry, level + look["gain"] - loudness(dry)[0], part))
        where = (f"{len(events)} выкриков по панораме" if scattered
                 else "в стороны" if len(same) == 1 and part != "дабл" else "панорама")
        print(f"  {part}: {where}, {look['gain']:+.0f} дБ к ведущему")
    return placed


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
         "✏️ Важно, где входит голос или какой нужен звук, — напиши словами в любой момент до склейки.\n\n"
         "Как пришлёшь?")
PICK = "Отметь, что у тебя есть отдельно, — потом попрошу каждую дорожку по очереди."
# Дорожки, выгруженные с начала проекта, встают по местам сами, с затактом: где у голоса «раз»,
# по звуку не узнать — слог перед сильной долей и слог сразу после неё звучат одинаково (26.09).
FROM_START = "\n\nВыгружай все дорожки с начала проекта — тогда голос встанет в бит ровно так, как в проекте."
# Характер звука — до склейки: его выбирают, не слыша результата. Громкость голоса и эхо —
# поправки «чуть громче, чем сейчас», их без прослушки не выбрать: они кнопками под треком.
STYLE = ("Дорожки есть. Какой звук?\n\n✏️ Голос выгружен не с начала проекта или важно что-то ещё — "
         "напиши словами до выбора: «голос входит на дропе», «первое слово на 0:20».")
# Не ответил на вопрос о звуке — склейка идёт как лучше, чтобы человек не ждал зря.
STYLE_WAIT = 180
MORE = "Есть: {names}. Ещё файл — или дальше."
WISHED = "✏️ Записал — учту при склейке."
WISH_LATE = "✏️ Склейка уже идёт — поправишь словами под готовым треком."
WISH_FAILED = "✏️ Просьбу словами разобрать не вышло — склеил как есть. Поправь кнопками или словами ниже.\n"
ACCEPTED = "Принял: {parts}. Склеиваю — пришлю минут через {minutes}."
EXPIRED = "Дорожки не пришли до конца — заявку закрыл. Начать заново — /skleyka."
OLD = "Эта заявка уже закрыта. Начать заново — /skleyka."
CANCELLED = "Отменил. Захочешь склеить — /skleyka."
LIMIT = "Склеек в сутки — {count}. Следующую можно с {time} по Москве."
INVITE = ("Твоя ссылка для артиста:\n{link}\n\nПридёт по ней и склеит свой трек — получишь склейку "
          f"сверх лимита. Живёт {config.SKLEYKA_BONUS_DAYS} дней.")
BONUS = "👥 Артист по твоей ссылке склеил трек — у тебя склейка сверх лимита. Жми /skleyka."
BONUS_SENT = "Тот, кто позвал тебя в СКЛЕЙКУ, получил за твою склейку ещё одну."
THANKS = "Спасибо! {what} — жми /skleyka."
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
TUNE = ("Не так? Подкрути — пересоберу{left}. Или напиши словами, что поменять и где должен входить голос, — "
        "кнопкой «✏️ Написать словами» или ответом на это сообщение.\n\n"
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
# at — с какой секунды бита входит первое слово; None — как в присланном файле (_moved).
KNOBS = {"style": "чисто", "design": False, "voice": 0.0, "echo": 0.0, "swap": False, "like": None, "at": None}
# Кнопки идут через service.handle_callback: префикс service.CALLBACK_PREFIX
# и действие sk. Импортировать service отсюда нельзя — он импортирует нас.
PREFIX = "s:sk:"
# Два выхода — только под отказом по лимиту: платное предложение в первом же ответе
# отпугнуло бы тех, у кого нет денег на звукаря, а бесплатная функция остаётся бесплатной.
WAYS = [[{"text": "👥 Позвать артиста", "callback_data": f"{PREFIX}r"}],
        [{"text": "⭐️ Больше склеек", "callback_data": f"{PREFIX}s"}]]
# Товары за звёзды: payload счёта → название (до 32 знаков).
STARS = {"pack": f"+{config.SKLEYKA_PACK} склейки на сутки",
         "month": f"30 дней по {config.SKLEYKA_MONTH_PER_DAY} склеек в сутки"}
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
    for key, empty in (("drafts", {}), ("jobs", []), ("tracks", {}), ("used", {}), ("invite", {}), ("invited_by", {}),
                       ("bonus", {}), ("paid", {})):
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


def _allowance(data: dict, chat_id: str) -> tuple[list[str], int, list[str]]:
    """(склейки за сутки, лимит суток с купленным, живые бонусы за приглашённых)."""
    recent = sorted(stamp for stamp in data["used"].get(chat_id, []) if _age(stamp) < 86400)
    paid = data["paid"].get(chat_id, [])
    month = any(p["item"] == "month" and _age(p["at"]) < 30 * 86400 for p in paid)
    base = (config.SKLEYKA_MONTH_PER_DAY if month else config.SKLEYKA_PER_DAY) \
        + config.SKLEYKA_PACK * sum(p["item"] == "pack" and _age(p["at"]) < 86400 for p in paid)
    bonus = [stamp for stamp in data["bonus"].get(chat_id, []) if _age(stamp) < config.SKLEYKA_BONUS_DAYS * 86400]
    return recent, base, bonus


def _limit(data: dict, chat_id: str) -> str:
    """Отказ по суточному лимиту; пусто — можно. Бонусы сверх лимита — не больше
    SKLEYKA_BONUS_MAX за сутки: потраченные уже сидят в recent."""
    recent, base, bonus = _allowance(data, chat_id)
    allowed = base + min(len(bonus), config.SKLEYKA_BONUS_MAX)
    if len(recent) < allowed:
        return ""
    from .compose import MSK

    free = state._parse(recent[len(recent) - allowed]) + timedelta(days=1)
    return LIMIT.format(count=allowed, time=free.astimezone(MSK).strftime("%H:%M"))


def start(chat_id: str | int, user_id: str | int, *, admin: bool = False) -> None:
    """/skleyka, кнопка меню и ссылка ?start=skleyka: две строки и выбор кнопкой.
    Подписку проверяет service."""
    chat_id, data = str(chat_id), load()
    denied = "" if admin else _limit(data, chat_id)
    if denied:
        data["drafts"].pop(chat_id, None)
        save(data)
        telegram.send_message(chat_id, denied, buttons=WAYS)
        return
    data["drafts"][chat_id] = {"user": str(user_id), "admin": admin, "at": state.iso(), "plan": None,
                               "step": 0, "files": []}
    save(data)
    telegram.send_message(chat_id, INTRO, buttons=MODES)


def invited(chat_id: str | int, code: str) -> None:
    """Пришёл по ?start=skleyka_r<код>: запомнить, кто позвал. Бонус — не за переход,
    а за первую готовую склейку (_finish): переход второй аккаунт накрутит за минуту.
    Кто уже склеивал, приглашённым не считается — иначе знакомые менялись бы ссылками."""
    chat, data = str(chat_id), load()
    inviter = next((who for who, mine in data["invite"].items() if code and mine == code), None)
    if inviter and inviter != chat and chat not in data["used"]:
        data["invited_by"][chat] = inviter
        save(data)


def _reward(data: dict, track: dict) -> None:
    """Первая готовая склейка приглашённого — пригласившему бонус, обоим строка."""
    inviter = data["invited_by"].pop(track["chat"], None)
    if not inviter:
        return
    alive = [stamp for stamp in data["bonus"].get(inviter, []) if _age(stamp) < config.SKLEYKA_BONUS_DAYS * 86400]
    data["bonus"][inviter] = [*alive, state.iso()]
    telegram.send_message(inviter, BONUS)
    telegram.send_message(track["chat"], BONUS_SENT)


def paid(message: dict) -> None:
    """Оплата звёздами прошла. Повтор того же платежа ничего не добавляет."""
    payment, chat, data = message["successful_payment"], str(message["chat"]["id"]), load()
    charge = payment["telegram_payment_charge_id"]
    if any(p["charge"] == charge for payments in data["paid"].values() for p in payments):
        return
    item = payment.get("invoice_payload")
    data["paid"].setdefault(chat, []).append({"item": item, "charge": charge, "stars": payment.get("total_amount"),
                                              "at": state.iso()})
    save(data)
    telegram.send_message(chat, THANKS.format(what=STARS.get(item, "склейки добавил")))


def refund(charge: str) -> str:
    """/vozvrat <номер транзакции> — звёзды назад, купленное снимается. Без номера —
    последние платежи: номер человек видит у себя в истории звёзд."""
    data = load()
    payments = sorted(((p, chat) for chat, ps in data["paid"].items() for p in ps), key=lambda pair: pair[0]["at"])
    for p, chat in payments:
        if charge and p["charge"] == charge:
            try:
                telegram.refund_stars(chat, charge)
            except telegram.TelegramError as exc:
                return f"Не вернул: {exc}"
            data["paid"][chat].remove(p)
            save(data)
            telegram.send_message(chat, f"Вернули {p['stars']} ⭐️ за «{STARS.get(p['item'], p['item'])}».")
            return f"Вернул {p['stars']} ⭐️, «{STARS.get(p['item'], p['item'])}» снято."
    lines = [f"{p['at'][:16]} · {STARS.get(p['item'], p['item'])} · {p['stars']} ⭐️\n<code>{p['charge']}</code>"
             for p, _ in payments[-5:]]
    return ("Такого платежа нет. " if charge else "") + ("Последние:\n" + "\n".join(lines) if lines else "Платежей нет.")


def support(chat_id: str | int, text: str) -> str:
    """/paysupport — вопрос об оплате владельцу, с номерами платежей для /vozvrat."""
    chat = str(chat_id)
    own = [f"<code>{p['charge']}</code> · {p['stars']} ⭐️" for p in load()["paid"].get(chat, [])]
    telegram.send_message(config.secret("TELEGRAM_ADMIN_ID"), "\n".join(
        ["💫 Вопрос об оплате: " + (text or "без текста"), *own] if own else
        ["💫 Вопрос об оплате: " + (text or "без текста"), "Платежей у человека нет."]))
    return ("Передал владельцу. Если нужен возврат звёзд — вернём, об этом придёт сообщение сюда."
            if own else "Передал владельцу. Платежей звёздами от тебя не вижу — если платил, пришли "
            "/paysupport и номер транзакции из истории звёзд.")


def _invoices(chat_id: str) -> None:
    """Оба счёта сразу: экран выбора между двумя товарами был бы лишним шагом."""
    about = "Больше склеек — и только: стиль, ручки и саунд-дизайн те же, что бесплатно."
    for item, stars in (("pack", config.SKLEYKA_STARS_PACK), ("month", config.SKLEYKA_STARS_MONTH)):
        telegram.send_invoice(chat_id, STARS[item], about, item, stars)


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
                          + ("; можно несколькими файлами" if part in MULTI else "") + "."
                          + (FROM_START if step == 0 else ""), ask="Прикрепи файл")
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
                             "knobs": knobs, "tweaks": 0, "at": state.iso(),
                             **({"wish": draft["wish"]} if draft.get("wish") else {})}
    recent, base, bonus = _allowance(data, chat_id)
    if len(recent) >= base and bonus:
        # Сверх лимита — тратится бонус, ближайший к сгоранию; не склеилось — вернётся (_finish).
        data["bonus"][chat_id].remove(min(bonus))
        data["tracks"][track]["bonus"] = min(bonus)
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


def buttons(track: str, knobs: dict, swap: bool, drop: float | None = None) -> list[list[dict]]:
    """Ручки под готовой склейкой: просьба словами первой — 26.09 из семи склеек ни одной
    не поправили словами, о подсказке в тексте не знали; голос с дропа, если он входит
    раньше (DROP_NOTE); стиль, голос, эхо, саунд-дизайн; «поменять» — когда вокал понят
    по звуку; «В ОТБОР» — дорога дальше."""
    def cb(code: str) -> str:
        return f"{PREFIX}{track}:{code}"

    looks = [{"text": ("• " if knobs["style"] == name else "") + name, "callback_data": cb(f"c{n}")}
             for n, name in enumerate(STYLES)]
    rows = [[{"text": "✏️ Написать словами", "callback_data": cb("w")}],
            *([[{"text": f"🎯 голос с {_minutes(drop)} — на дроп", "callback_data": cb(f"a{drop:.2f}")}]] if drop else []),
            looks[:2], looks[2:],
            [{"text": "🔊 голос громче", "callback_data": cb("v+")}, {"text": "🔉 голос тише", "callback_data": cb("v-")}],
            [{"text": "➕ эха", "callback_data": cb("e+")}, {"text": "➖ эха", "callback_data": cb("e-")}],
            [{"text": "✨ саунд-дизайн: " + ("убрать" if knobs["design"] else "добавить"), "callback_data": cb("d")}]]
    if swap:
        rows.append([{"text": "↔ поменять вокал и бит", "callback_data": cb("sw")}])
    # Метка skleyka доходит до поста отбора: под ним строка про СКЛЕЙКУ (otbor.build_post).
    rows.append([{"text": "🎙 Выложил — в ОТБОР", "callback_data": "s:otbor:skleyka"}])
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
    elif code.startswith("a"):
        with contextlib.suppress(ValueError):
            new["at"] = round(float(code[1:]), 2)
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
    if knobs.get("like"):
        words.append(f"тембр, ширина и громкость — к «{knobs['like']['title']}»")
    if knobs.get("at") is not None:
        words.append(f"голос с {_minutes(knobs['at'])}")
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
    if len(head) != 1 and code == "w":
        # Telegram сам открывает ответ на этот вопрос, а метка в нём ведёт ответ в talk.
        telegram.send_message(chat_id, TALK_ASK, ask="голос входит на дропе")
        return
    if len(head) != 1:
        _tweak(data, chat_id, head, code, admin)
        return
    if head == "x":
        cancel(chat_id)
        telegram.send_message(chat_id, CANCELLED)
        return
    if head == "r":
        link = f"https://t.me/{config.BOT_HANDLE.lstrip('@')}?start=skleyka_r"
        link += data["invite"].setdefault(chat_id, secrets.token_hex(4))
        save(data)
        telegram.send_message(chat_id, INVITE.format(link=link))
        return
    if head == "s":
        _invoices(chat_id)
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


# Ответ словами на ручки готовой склейки — «голос тише на припеве, эха побольше».
# Модель (prompts/skleyka.md) только выбирает значения тех же ручек, что у кнопок,
# код держит их в пределах, а пересборка — та же, что с кнопки, и в тот же лимит.
# Ответ без пересборки лимита не тратит, но генератор общий с каналом, поэтому
# разговоров у трека не больше TALKS. Метка в тексте ручек (TUNE) — ответ на это
# сообщение идёт сюда, а не в разбор (src/service.py).
TALK_MARK = "напиши словами"
TALKS = 6
TALK_FAILED = "Не разобрал — подкрути кнопками выше."
TALKED = "Поговорили про этот трек достаточно — дальше кнопками выше."
LIKE_MISSING = "«{name}» в магазинах не нашёл — звук ни к чему не подтягивал."
LIKE_LOST = "Отрывок «{name}» не скачался — звук к нему не подтягивал.\n"
TALK_KNOBS = ("style", "design", "voice", "echo", "at")
TALK_ASK = ("✏️ Что поменять — напиши словами ответом на это сообщение: «голос входит на дропе», "
            "«голос на долю позже», «эха меньше», «погрязнее».")
DROP_NOTE = "Голос входит на {voice}, а бас в бите — на {drop}. Если голос уехал — жми «🎯 голос с {drop}».\n"


def heard(knobs: dict, answer: dict) -> dict:
    """Ручки из ответа модели: только известные и в пределах, остальное — как было."""
    new = dict(knobs)
    if answer.get("style") in STYLES:
        new["style"] = answer["style"]
    if isinstance(answer.get("design"), bool):
        new["design"] = answer["design"]
    for key, (low, high) in (("voice", (-VOICE_LIMIT, VOICE_LIMIT)), ("echo", ECHO_LIMITS)):
        with contextlib.suppress(KeyError, TypeError, ValueError):
            new[key] = float(max(low, min(high, round(float(answer[key])))))
    with contextlib.suppress(KeyError, TypeError, ValueError):
        at = float(answer["at"])
        new["at"] = None if at <= 0 else round(at, 2)  # 0 модель пишет и «не трогать»: безопаснее как в файле
    return new


def understood(knobs: dict, text: str, timing: dict | None) -> tuple[dict, str]:
    """Просьба словами — в ручки и ответ человеку (prompts/skleyka.md). timing — замер
    склейки (run_job): где первое слово в присланном файле, дропы бита, длина доли;
    по нему модель ставит голос «на дроп» или «на долю позже». До первой склейки
    замера нет в дежурстве, поэтому просьбу до склейки разбирает сама склейка."""
    now = {key: knobs.get(key) for key in TALK_KNOBS}
    now["at"] = -1 if now["at"] is None else now["at"]
    answer = llm.generate_skleyka({
        "request": text[:1000],
        "knobs": {**now, "like": (knobs.get("like") or {}).get("title", "")},
        "limits": {"voice": [-VOICE_LIMIT, VOICE_LIMIT], "echo": list(ECHO_LIMITS),
                   "style": {name: kind["about"] for name, kind in STYLES.items()}},
        "timing": timing and {**timing, "voice": timing["sent"] if knobs.get("at") is None else knobs["at"]}})
    new = heard(knobs, answer)
    words = html.escape(str(answer.get("reply", "")).strip())[:400]
    # «Как у <артиста>»: модель называет, чей трек, а сам трек ищет код — в магазине,
    # с превью и тем же исполнителем. Не нашёлся — подгонки нет, и человеку это сказано.
    asked, was = str(answer.get("like") or "").strip()[:100], knobs.get("like")
    if not asked:
        new["like"] = None
    elif not was or asked.casefold() != was["title"].casefold():
        try:
            new["like"] = itunes.find_song(asked) or was
        except Exception as exc:  # noqa: BLE001 — магазин недоступен, остальные ручки работают
            print(f"  склейка: трек для подгонки не нашёлся: {type(exc).__name__}")
            new["like"] = was
        if new["like"] is was:
            words = (f"{words}\n" if words else "") + LIKE_MISSING.format(name=html.escape(asked))
    return new, words


def wish(chat_id: str | int, text: str) -> bool:
    """Просьба словами до склейки: копится в заявке, а разбирает её сама склейка —
    там уже известны дропы бита и первое слово голоса (run_job). Заявка закрыта, а склейка
    ещё ждёт в очереди — просьба дописывается треку; уже склеивается — человеку сказано,
    где поправить. Ни заявки, ни склейки — текст не к склейке (False), он идёт в разборы."""
    chat_id, data = str(chat_id), load()
    job = next((job for job in data["jobs"] if data["tracks"].get(job["track"], {}).get("chat") == chat_id), None)
    if draft := _draft(data, chat_id):
        draft["at"] = state.iso()  # человек пишет — вопрос о звуке не закрывается сам (STYLE_WAIT)
    elif not job:
        return False
    elif job.get("started") or job.get("tweak"):
        telegram.send_message(chat_id, WISH_LATE)
        return True
    else:
        draft = data["tracks"][job["track"]]
    draft["wish"] = f"{draft.get('wish', '')}\n{text[:500]}".strip()[-1000:]
    save(data)
    telegram.send_message(chat_id, WISHED)
    return True


def talk(chat_id: str | int, text: str, reply: dict, *, admin: bool = False) -> None:
    """Просьба словами ответом на ручки: чей трек — по кнопкам того сообщения, а если
    Telegram их не приложил — последний трек человека."""
    chat_id, data = str(chat_id), load()
    codes = [button.get("callback_data", "") for row in (reply.get("reply_markup") or {}).get("inline_keyboard", [])
             for button in row]
    track_id = next((code[len(PREFIX):].partition(":")[0] for code in codes if code.startswith(PREFIX)), "") \
        or max((key for key, track in data["tracks"].items() if track["chat"] == chat_id),
               key=lambda key: data["tracks"][key]["at"], default="")
    track = data["tracks"].get(track_id)
    if not track or track["chat"] != chat_id:
        telegram.send_message(chat_id, STALE)
        return
    owner = admin or track.get("admin")
    if not owner and track["tweaks"] >= config.SKLEYKA_TWEAKS:
        telegram.send_message(chat_id, NO_TWEAKS)
        return
    if not owner and track.get("talks", 0) >= TALKS:
        telegram.send_message(chat_id, TALKED)
        return
    track["talks"] = track.get("talks", 0) + 1
    save(data)
    try:
        knobs, words = understood(track["knobs"], text, track.get("timing"))
    except Exception as exc:  # noqa: BLE001 — генератор недоступен, кнопки остаются
        print(f"  склейка: разговор не вышел: {type(exc).__name__}")
        telegram.send_message(chat_id, TALK_FAILED)
        return
    if knobs == track["knobs"]:
        telegram.send_message(chat_id, words or TALK_FAILED)
        return
    track.update(knobs=knobs, tweaks=track["tweaks"] + 1)
    minutes = _enqueue(data, track_id, knobs, tweak=True)
    save(data)
    telegram.send_message(chat_id, (f"{words}\n\n" if words else "") + REBUILD.format(what=look(knobs), minutes=minutes))


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
            "knobs": job["knobs"], "left": None if track.get("admin") else config.SKLEYKA_TWEAKS - track["tweaks"],
            "wish": None if job.get("tweak") else track.get("wish")}
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
    if not track:
        return
    if result.get("ok"):
        track.update({key: result[key] for key in ("timing", "knobs") if result.get(key)})
        if not job.get("tweak"):
            _reward(data, track)
        return
    used = data["used"].get(track["chat"], [])
    if job.get("tweak"):
        track["tweaks"] = max(0, track["tweaks"] - 1)
    elif used:
        used.pop()
        if "bonus" in track:
            data["bonus"].setdefault(track["chat"], []).append(track.pop("bonus"))
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
    seconds = round(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


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
    return paths[0] if len(paths) == 1 else _sum([(path, 0.0) for path in paths], dest, FORMAT)


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
            rhythm = grid(beat)
            timing = {"sent": first_word(vocal), "drops": drops(beat, rhythm), "beat": round(rhythm[0], 3),
                      "length": round(clips.probe_seconds(beat), 1)}
            result["timing"] = timing
            if spec.get("wish"):
                try:
                    knobs, words = understood(knobs, spec["wish"], timing)
                    note = (f"✏️ {words}\n" if words else "") + note
                    spec["knobs"] = result["knobs"] = knobs
                except Exception as exc:  # noqa: BLE001 — генератор недоступен, склейка идёт как есть
                    print(f"  склейка {spec['job']}: просьба не разобрана: {type(exc).__name__}")
                    note = WISH_FAILED + note
            voice = timing["sent"]
            if knobs.get("at") is not None:
                # Первое слово — на секунду at: все дорожки голоса сдвигаются вместе.
                voice = max(0.0, min(knobs["at"], timing["length"] - 1))
                shift = voice - timing["sent"]
                if abs(shift) >= 0.01:
                    print(f"  голос: первое слово {timing['sent']:.2f} → {voice:.2f} с")
                    parts = [(name, _moved(path, shift, work / f"moved{n}.wav") if part in VOCAL_SIDE else path, part)
                             for n, (name, path, part) in enumerate(parts)]
                    vocal = _bus(parts, True, work / "vocal.wav")
            # Голос входит больше чем за такт до первого дропа — назвать дроп и дать его кнопкой.
            drop = timing["drops"][0] if timing["drops"] and voice < timing["drops"][0] - 4 * rhythm[0] else None
            if drop:
                note += DROP_NOTE.format(voice=_minutes(voice), drop=_minutes(drop))
            lead = [p for p in parts if p[2] == "вокал"] or [p for p in parts if p[2] in VOCAL_SIDE]
            extra = {key: knobs[key] for key in ("voice", "echo") if knobs.get(key)}
            if like := knobs.get("like"):
                extra["like"] = reels._download(like["url"], work / "like.m4a", 10_000)
                if not extra["like"]:
                    note += LIKE_LOST.format(name=html.escape(like["title"]))
                    spec["knobs"] = dict(knobs, like=None)
            master = mix(_bus(lead, True, work / "lead.wav"), beat, work / "out", knobs["style"], knobs["design"],
                         parts=[(part, path) for name, path, part in parts if (name, path, part) not in lead], **extra)
            try:
                movie = story(vocal, beat, master, work)
            except Exception as exc:  # noqa: BLE001 — без ролика трек всё равно уходит
                print(f"  склейка {spec['job']}: ролик не собрался: {type(exc).__name__}")
                movie = None
            _send(spec, master, parts, note + (GUESSED if guessed else ""), service, work, movie, swap=guessed, drop=drop)
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
          swap: bool = False, drop: float | None = None) -> None:
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
                          buttons=buttons(spec["track"], knobs, swap=swap, drop=drop))


def _selftest() -> None:
    """Без сети: роли по имени и по звуку, куда идёт файл, заявка от дорожек до очереди,
    ручки и возврат лимита, лимит суток, отказы по тишине и длине."""
    sent: list[str] = []
    keys: list = []
    calls: list[tuple[str, dict]] = []
    real = (telegram.send_message, telegram.edit_markup, config.SKLEYKA_FILE, config.secret, llm.generate_skleyka,
            itunes.find_song, telegram._call)
    telegram.send_message = lambda chat, text, buttons=None, **_: sent.append(text) or keys.append(buttons) \
        or {"message_id": len(sent)}
    telegram._call = lambda method, payload, files=None: calls.append((method, payload)) or {}
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

        # Место голоса: первое слово сдвигается вместе с файлом; дроп — где входит низ.
        voice, beat = tmp / "voice.wav", tmp / "drop.wav"
        _ffmpeg("-f", "lavfi", "-i", "sine=f=440:d=3", "-af", "adelay=1000:all=1", voice)
        assert abs(first_word(voice) - 1.0) < 0.05, first_word(voice)
        assert abs(first_word(_moved(voice, 0.5, tmp / "later.wav")) - 1.5) < 0.05
        assert abs(first_word(_moved(voice, -0.5, tmp / "sooner.wav")) - 0.5) < 0.05
        _ffmpeg("-f", "lavfi", "-i", "anoisesrc=d=12:a=0.1", "-f", "lavfi", "-i", "sine=f=55:d=8", "-filter_complex",
                "[0:a]highpass=f=2000[h];[1:a]adelay=4000:all=1[s];[h][s]amix=inputs=2:duration=longest", beat)
        assert drops(beat, (0.5, 0.0)) == [4.0], drops(beat, (0.5, 0.0))

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
        wish(7, "голос входит на дропе")  # текст при открытой заявке — просьба, а не разбор
        assert sent[-1] == WISHED and load()["drafts"]["7"]["wish"] == "голос входит на дропе"
        callback(7, 7, "e")
        assert load()["drafts"]["7"]["knobs"]["design"]
        callback(7, 7, "y:1")
        data = load()
        assert sent[-1].startswith("Принял: вокал «take 1.wav», бит «take 2.wav»") and not data["drafts"]
        track = data["jobs"][0]["track"]
        assert data["tracks"][track]["knobs"] == dict(KNOBS, style="мелодично", design=True)
        assert [f["r"] for f in data["tracks"][track]["files"]] == ["вокал", "бит"]
        assert data["tracks"][track]["wish"] == "голос входит на дропе"
        # Склейка ждёт очереди — текст дописывается к треку; уже идёт — где поправить; нет ничего — в разборы.
        assert wish(7, "на втором дропе") and load()["tracks"][track]["wish"] == "голос входит на дропе\nна втором дропе"
        data = load()
        data["jobs"][0]["started"] = state.iso()
        save(data)
        assert wish(7, "погромче") and sent[-1] == WISH_LATE and "погромче" not in load()["tracks"][track]["wish"]
        assert not wish(8, "Bones")

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
        assert [row[0]["callback_data"] for row in buttons(track, KNOBS, swap=True)][-2:] == [f"{PREFIX}{track}:sw", "s:otbor:skleyka"]
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

        # Ответ словами: модель выбирает ручки, код держит пределы; ничего не поменялось —
        # только ответ, без пересборки; генератор упал — кнопки.
        answers: list = []

        def model(payload: dict) -> dict:
            answer = answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer

        llm.generate_skleyka = model
        props = llm.SKLEYKA_SCHEMA["properties"]
        assert set(props) == {*TALK_KNOBS, "like", "reply"} and all(name in props["style"]["description"] for name in STYLES)
        assert TALK_MARK in TUNE
        data["tracks"]["t1"] = {"chat": "7", "files": [], "knobs": dict(KNOBS), "tweaks": 0,
                                "at": state.iso(state.now() + timedelta(minutes=1))}
        save(data)
        menu = {"text": TUNE, "reply_markup": {"inline_keyboard": buttons("t1", KNOBS, swap=False)}}
        answers[:] = [{"style": "мелодично", "design": True, "voice": -9, "echo": "много", "reply": "Голос <тише>."}]
        talk(7, "автотюн", menu)
        data = load()
        assert data["jobs"][-1]["track"] == "t1" and data["tracks"]["t1"]["tweaks"] == 1
        assert data["jobs"][-1]["knobs"] == dict(KNOBS, style="мелодично", design=True, voice=-VOICE_LIMIT), data["jobs"][-1]
        assert sent[-1].startswith("Голос &lt;тише&gt;.\n\nПересобираю: «мелодично»"), sent[-1]
        jobs = len(data["jobs"])
        answers[:] = [{"style": "мелодично", "design": True, "voice": -6, "echo": 0, "reply": "Ширину не кручу."}]
        talk(7, "шире", {"text": TUNE})  # кнопок Telegram не приложил — последний трек человека
        assert sent[-1] == "Ширину не кручу." and load()["tracks"]["t1"]["tweaks"] == 1 and len(load()["jobs"]) == jobs
        # «Как у артиста»: трек ищет код, а не модель; не нашёлся — подгонки нет, и это сказано.
        itunes.find_song = lambda query: {"id": 1, "title": "Future — Mask Off", "url": "u"} if "Future" in query else {}
        answers[:] = [{"style": "мелодично", "design": True, "voice": -6, "echo": 0, "like": "Future", "reply": "Автотюн оставил."}]
        talk(7, "как у Future", menu)
        assert load()["tracks"]["t1"]["knobs"]["like"]["id"] == 1 and "к «Future — Mask Off»" in sent[-1], sent[-1]
        answers[:] = [{"style": "мелодично", "design": True, "voice": -6, "echo": 0, "like": "Никто", "reply": ""}]
        talk(7, "как у Никто", menu)
        assert sent[-1] == LIKE_MISSING.format(name="Никто") and load()["tracks"]["t1"]["knobs"]["like"]["id"] == 1, sent[-1]
        answers[:] = [{"style": "мелодично", "design": True, "voice": -6, "echo": 0, "like": "", "reply": "Убрал."}]
        talk(7, "как было", menu)
        assert load()["tracks"]["t1"]["knobs"]["like"] is None and load()["tracks"]["t1"]["tweaks"] == 3
        data = load()
        data["tracks"]["t1"]["tweaks"] = 1
        data["tracks"]["t1"]["timing"] = {"sent": 2.75, "drops": [12.95], "beat": 0.857, "length": 153.0}
        save(data)
        payloads: list = []
        llm.generate_skleyka = lambda payload: payloads.append(payload) or answers.pop(0)
        answers[:] = [{"style": "мелодично", "design": True, "voice": -6, "echo": 0, "at": 12.95, "like": "", "reply": "На дроп."}]
        talk(7, "голос раньше дропа", menu)
        assert payloads[-1]["timing"]["voice"] == 2.75 and payloads[-1]["knobs"]["at"] == -1, payloads[-1]
        assert load()["tracks"]["t1"]["knobs"]["at"] == 12.95 and "голос с 0:13" in sent[-1], sent[-1]
        llm.generate_skleyka = model
        data = load()
        data["tracks"]["t1"].update(tweaks=1, talks=0)
        save(data)
        answers[:] = [RuntimeError("сеть")]
        talk(7, "эха", menu)
        assert sent[-1] == TALK_FAILED
        talk(8, "эха", menu)
        assert sent[-1] == STALE, "чужая склейка"
        data = load()
        data["tracks"]["t1"]["talks"] = TALKS
        save(data)
        talk(7, "эха", menu)
        assert sent[-1] == TALKED and not answers

        # Лимит суток: две склейки — третья завтра; владельцу лимита нет.
        data["used"]["7"] = [state.iso(), state.iso()]
        save(data)
        start(7, 7)
        assert sent[-1].startswith("Склеек в сутки — 2.") and keys[-1] == WAYS, "упёрся — два выхода кнопками"
        start(1, 1, admin=True)
        assert sent[-1] == INTRO and keys[-1] == MODES

        # Позвал артиста: бонус не за переход, а за его первую готовую склейку, и один раз.
        callback(7, 7, "r")
        code = load()["invite"]["7"]
        assert sent[-1].startswith("Твоя ссылка") and f"t.me/plenka_fm_bot?start=skleyka_r{code}" in sent[-1]
        for chat, by in ((7, code), (40, code), (41, "чужой")):
            invited(chat, by)
        data = load()
        assert data["invited_by"] == {"40": "7"}, "сам себя и кто уже склеивал — не приглашённые"
        data["tracks"]["t40"] = {"chat": "40", "files": [], "knobs": dict(KNOBS), "tweaks": 0, "at": state.iso()}
        data["used"]["40"] = [state.iso()]
        for n in range(2):
            done = subprocess.Popen(["true"])
            done.wait()
            (tmp / f"ok{n}").mkdir()
            (tmp / f"ok{n}" / "result.json").write_text('{"ok": true}')
            _finish(data, done, {"id": f"j{n}", "track": "t40"}, tmp / f"ok{n}")
        assert len(data["bonus"]["7"]) == 1 and sent[-2:] == [BONUS, BONUS_SENT], "второй раз бонуса нет"
        save(data)
        invited(40, code)
        assert not load()["invited_by"], "склеивший по ссылке второй раз не приглашённый"
        assert not _limit(data, "7"), "бонус — склейка сверх лимита"
        start(7, 7)
        data = load()
        _queue(data, "7", data["drafts"]["7"])
        assert data["bonus"]["7"] == [] and _limit(data, "7"), "бонус потрачен"
        data["bonus"]["7"] = [state.iso(state.now() - timedelta(days=config.SKLEYKA_BONUS_DAYS + 1))]
        assert _limit(data, "7"), "бонус сгорел"
        save(data)

        # Звёзды: два счёта в XTR без провайдера; «да» перед списанием — сразу и первым;
        # платёж поднимает лимит, повтор того же платежа — нет; возврат снимает купленное.
        callback(7, 7, "s")
        invoices = [payload for method, payload in calls if method == "sendInvoice"]
        assert [(i["payload"], i["currency"], i["provider_token"]) for i in invoices] == \
            [("pack", "XTR", ""), ("month", "XTR", "")], invoices

        def payment(charge: str, n: int, item: str = "pack") -> dict:
            return {"update_id": n, "message": {"message_id": n, "chat": {"id": 7, "type": "private"}, "from": {"id": 7},
                    "successful_payment": {"currency": "XTR", "total_amount": 30, "invoice_payload": item,
                                           "telegram_payment_charge_id": charge}}}

        from . import moderate

        calls.clear()
        moderate.process([payment("c1", 1), {"update_id": 2, "pre_checkout_query": {"id": "q1"}}], {}, "1", False, 0)
        assert calls == [("answerPreCheckoutQuery", {"pre_checkout_query_id": "q1", "ok": True})], calls
        assert sent[-1].startswith("Спасибо! +3") and not _limit(load(), "7"), "пакет поднял лимит"
        data = load()
        data["used"]["7"] += [state.iso()] * 2
        save(data)
        assert _limit(data, "7").startswith("Склеек в сутки — 5.")
        paid(payment("c1", 3)["message"])
        assert _limit(load(), "7"), "повтор платежа"
        paid(payment("c2", 4, "month")["message"])
        assert not _limit(load(), "7"), "месяц — десять в сутки"
        assert refund("c9").startswith("Такого платежа нет") and "c2" in refund("")
        assert refund("c2").startswith("Вернул") and calls[-1] == (
            "refundStarPayment", {"user_id": "7", "telegram_payment_charge_id": "c2"}) and _limit(load(), "7")
        assert sent[-1].startswith("Вернули"), "о возврате пишем покупателю"
        assert support("7", "не пришло").startswith("Передал") and "c1" in sent[-1] and "не пришло" in sent[-1], \
            "вопрос об оплате — владельцу с номером"
        assert turn(KNOBS, "e+")["echo"] == ECHO_STEP and turn(dict(KNOBS, voice=VOICE_LIMIT), "v+")["voice"] == VOICE_LIMIT
        assert "с саунд-дизайном" in look(turn(KNOBS, "d")) and turn(KNOBS, "c1")["style"] == "мелодично"
        assert turn(KNOBS, "a12.95")["at"] == 12.95 and "голос с 0:13" in look(turn(KNOBS, "a12.95"))
        assert heard(KNOBS, {"at": 13})["at"] == 13 and heard(dict(KNOBS, at=13), {"at": -1})["at"] is None
        rows = buttons("t1", KNOBS, swap=False, drop=12.95)
        assert [rows[0][0]["callback_data"], rows[1][0]["callback_data"]] == [f"{PREFIX}t1:w", f"{PREFIX}t1:a12.95"]
        callback(7, 7, "t1:w")
        assert sent[-1] == TALK_ASK and TALK_MARK in TALK_ASK
        # Эдлибы: выкрики по очереди лево и право, точка меняется в паузе, а не на звуке.
        left, right = _scatter([(1.0, 1.5), (2.0, 2.3), (4.0, 4.2)])
        assert left[0][1] > right[0][1] and left[-1][1] > right[-1][1] and left[2][1] < right[2][1], (left, right)
        assert all(1.5 < t < 2.0 for t, _ in left[1:3]) and len(left) == len(right) == 5
    finally:
        (telegram.send_message, telegram.edit_markup, config.SKLEYKA_FILE, config.secret, llm.generate_skleyka,
         itunes.find_song, telegram._call) = real
        shutil.rmtree(tmp, ignore_errors=True)
    print("skleyka: роли по имени и звуку, маршрут файлов, вопросы по шагам и галочки, звук до склейки, "
          "ручки кнопками и словами, «как у артиста», лимиты, отказы, эдлибы по панораме, "
          "реферал за склейку и звёзды — ок")


def talk_check() -> list[str]:
    """Просьбы о месте голоса — живой генератор (prompts/skleyka.md): куда он ставит `at`
    по замеру 26.09 (первое слово на 2,75 с, дропы 12,94 и 45,2, доля 0,43). Из России
    Gemini не отвечает, поэтому проверка идёт в Actions (health.yml). Итог — промахи."""
    timing = {"sent": 2.75, "drops": [12.94, 45.2], "beat": 0.43, "length": 153.0}
    cases = [("голос должен входить на дропе", None, 12.94), ("первое слово на 0:20", None, 20.0),
             ("голос на втором дропе", None, 45.2), ("сделай голос на долю позже", 12.94, 13.37),
             ("верни голос как было в файле", 12.94, None), ("голос чуть громче", None, None)]
    misses = []
    for text, at, want in cases:
        got = understood(dict(KNOBS, at=at), text, timing)[0]["at"]
        ok = got == want or None not in (got, want) and abs(got - want) < 0.05
        print(f"  {'ок' if ok else 'ПРОМАХ'}: «{text}» → at {got} (ждали {want})")
        misses += [] if ok else [text]
    return misses


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
    parser.add_argument("--like", type=Path, metavar="ФАЙЛ",
                        help="трек, к которому подтянуть тембр, ширину и громкость («как у артиста»)")
    parser.add_argument("--part", nargs=2, action="append", default=[], metavar=("РОЛЬ", "ФАЙЛ"),
                        help="дорожка по отдельности: дабл, бэк, эдлиб, барабаны, бас, музыка (БИТ — всё вместе)")
    parser.add_argument("--job", type=Path, metavar="ФАЙЛ", help="склейка заявки из бота (её запускает дежурство)")
    parser.add_argument("--selftest", action="store_true", help="роли, маршрут, заявка, ручки, лимиты — без сети")
    parser.add_argument("--dry-run", action="store_true", help="заявки и склейки в очереди, ничего не делая")
    parser.add_argument("--talk-check", action="store_true",
                        help="просьбы о месте голоса — живому генератору: куда он ставит голос (только из Actions)")
    args = parser.parse_args()
    config.load_dotenv()
    if args.selftest:
        _selftest()
        return 0
    if args.talk_check:
        return 1 if talk_check() else 0
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
        if bad := [part for part, _ in args.part if part not in PARTS and part not in INSTRUMENTS]:
            parser.error(f"роли {', '.join(bad)} нет")
        master = mix(*args.mix, args.out, args.style, args.design, args.voice, args.echo,
                     [(part, Path(path)) for part, path in args.part], args.like)
        compare(*args.mix, master, args.out)
        print(f"  готово: {master}, {args.out / 'do.mp3'}, {args.out / 'posle.mp3'}")
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
