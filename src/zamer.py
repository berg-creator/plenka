"""ЗАМЕР — рисунок чужого бита цифрами: сетка хэта, место клэпа, бочка, 808, свинг, части.

01.10.2026 знакомый владельца сказал, что первый бит звучит неактуально. Ноты рутины
(src/noty.py, prompts/beats.md) писались «усреднённым трэпом» из памяти модели, а с образцов
снимались только темп и тональность. Этот модуль снимает с готового звука сам рисунок —
чтобы скелет в брифе стоял на цифрах дня, а не на вкусе модели. Замер стареет: кого мерить,
берётся из чартов и выдачи YouTube на день работы (NEXT.md, задача «замер раз в месяц»).

Как меряет. Из трека вырезается окно 90 секунд (вступление пропущено), demucs делит его на
барабаны, бас, остальное и голос. В стеме барабанов берутся огибающие трёх полос и их онсеты —
места, где огибающая резко выросла: выше 7 кГц — хэт (вместе с верхом клэпа и перкуссии),
1–5 кГц без низа под ударом — клэп или снейр, ниже 110 Гц вместе с ударом в 150–1000 Гц — бочка.
Такт — самый короткий период, с которым клэп повторяет сам себя (темп 100–200), сетка восьмых
уточняет темп до сотых; клэп ставится на шаг 8 из 16, как его рисуют в FL, а если он бьёт
дважды в такт — на шаги 4 и 12. В стеме баса ноты 808 ищутся по сбою фазы: новая нота сэмплера
начинает синус заново, даже когда громкость и высота те же; длина ноты — до следующей или
до тишины, высота — yin. Части — по всему файлу: где низ играет, а где молчит, по полтакта.
На бите владельца, ноты которого известны, замер вернул их рисунок такт в такт
(бочка и 808 на шагах 0-6-10 и 0-3-6-11-14, клэп на 8, темп 156,7 при 156,66 в проекте).

Чего замер не умеет, и это не оценивается на глаз: число слоёв мелодии (вместо него — длина
петли в тактах, сколько нот звучит разом и сколько октав занято), перкуссия и открытый хэт
отдельно от закрытого, тихая бочка под 808 (demucs отдаёт её низ басу — видна только бочка
с ударом), нота баса с медленной атакой после паузы (фазу она не сбивает, такой бас
недосчитывается). Слайд 808 — оценка: нота, конец которой плавно ушёл от середины на два полутона
и больше. Рисунок на два такта (дрилл) темп не находит — ему нужен `--bpm`; `on_grid` ниже 0,6
или клэп не на шаге 8 значат, что темп угадан неверно. Замер одного файла повторяется
с разбросом: demucs на MPS не детерминирован, у 808 гуляют «разных нот» ±1 и слайды ±0,3.

Отвергнуто: мерить без разделения, по полосам общего микса, — голос и мелодия дают онсеты
в полосе клэпа. Отвергнут librosa.feature.tempo: на рисунке бочки 0-6-10 он ошибался в полтора
раза и на 7%. Отвергнута сумма приростов спектра по частотам как онсет: хвост одного хэта она
читала дробью, а синус 808 в коротком окне — нотами.

Петли (`--loops`, владелец 05.10.2026: мелодии поверх петли «катастрофически не хватает»). Чтобы писать ноты
поверх гитарной петли, надо знать, какие ноты в ней звучат, а имя файла этого не говорит: буква после темпа —
в лучшем случае опорная нота, у `AC_SixStr120C-01` и `-02` под одной буквой разные наборы нот. Поэтому каждая
разрешённая петля (`noty.loop_bpm`) меряется по звуку — длина в тактах, звучащие ноты, оценка тоники, строй,
опора каждого такта — и ложится в `data/beat_sounds.json` полем `loops`; сборка бита берёт ноты оттуда.
В список идут петли ровно в 1, 2, 4 или 8 тактов: 2,5 такта (`AC_RevRev85`) на сетку не ложатся, а 3, 5 и 6 —
это 2 или 4 такта и хвост ревера, который пришлось бы накладывать на следующий повтор.
Отвергнуто: `chroma_cqt` как есть — три полосы CQT на полутон складываются окном, и громкая нота «звучит»
в обоих соседних полутонах; берётся одна центральная полоса.

Корень одиночного звука (`--root`, 06.10.2026: банк одиночных звуков, в именах которого нот нет). Сэмплеру нужна
корневая нота канала — на какой ноте звук записан: партия от неверного корня фальшивит вся, и на слух её до владельца
не проверяет никто. Поэтому замер либо уверен, либо молчит (`root`): pyin держит одну высоту, в хроме нет чужих нот,
основной тон слышен в спектре — не сошлось хоть одно, ноты нет, и звук в список сборки не идёт.
Отвергнуто: брать громчайший класс высот хромы — у аккорда и у колокола с негармоничными призвуками он тоже есть.

Тяжёлое (demucs, librosa) есть только на Маке, как у src/quiz_ai.py, — запуск оттуда же:

    ~/.cache/whisper-venv/bin/python -m src.zamer --selftest             замер на синтетическом бите с известным рисунком
    ~/.cache/whisper-venv/bin/python -m src.zamer ФАЙЛ… --out zamer.json  замерить файлы, дописать в zamer.json
    ~/.cache/whisper-venv/bin/python -m src.zamer ФАЙЛ --bpm 142          темп известен (дрилл, двухтактный рисунок)
    ~/.cache/whisper-venv/bin/python -m src.zamer ФАЙЛ --color            ещё и цвет музыки: яркость, регистр, ноты, аккорды, шум
    ~/.cache/whisper-venv/bin/python -m src.zamer --table data/beats_zamer.json   сводка: медианы по группам
    ~/.cache/whisper-venv/bin/python -m src.zamer --loops                переписать замер петель в data/beat_sounds.json (только Мак)
    ~/.cache/whisper-venv/bin/python -m src.zamer --loops "11 - Сеть"    то же, но только петли с этим словом в имени: прочие не читаются
    ~/.cache/whisper-venv/bin/python -m src.zamer --root ФАЙЛ…           корневая нота одиночных звуков; «неуверенно» — в список не идёт

Чужой звук — только для замера: стемы пишутся во временную папку и удаляются сразу.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

SR, HOP = 44100, 128                       # кадр 2,9 мс: 1/64 на 160 BPM — 23 мс
WINDOW = 90                                # секунд под demucs: дольше — диск и время, а рисунок тот же
FRAME = HOP / SR
GRIDS = {2: "1/8", 1: "1/16", .5: "1/32", .25: "1/64", 4 / 3: "1/8T", 2 / 3: "1/16T", 1 / 3: "1/32T"}
# Нота в петле «звучит», если её энергия — от 8% энергии самой громкой. Снято с 487 петель набора 01 (05.10.2026):
# при 8% у петли чаще всего 5–7 нот (медиана 6), при 3% — у каждой шестой все 12, при 20% — медиана 4
LOOP_NOTE = .08
LOOP_BARS = (1, 2, 4, 8)
# Профили Крумхансла — Кесслера: насколько каждая ступень «своя» в мажоре и в миноре, от тоники
KEYS = {"мажор": (6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88),
        "минор": (6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17)}
# Корень одиночного звука — когда замеру верить. Пороги сняты с 56 звуков банка Glorified (06.10.2026): у 37 сошлось всё,
# у остальных высота плывёт или скачет на октаву, в хроме чужая нота (аккорд, колокол) или основного тона нет
# ponytail: один банк синтезатора, все звуки в «до». На живых записях и других нотах пороги не проверены
ROOT_SURE = .85                            # доля громких кадров, где pyin слышит высоту, и доля из них на одной ноте
ROOT_CENTS = 25                            # дальше от ноты — звук между двумя нотами
ROOT_ALIEN = .25                           # вес чужого класса высот от веса корня; квинта и большая терция — его обертоны
ROOT_FUND = .1                             # доля основного тона в энергии первых десяти гармоник
DATALESS = 0x40000000                      # st_flags заглушки iCloud (SF_DATALESS): чтение повисло бы на скачивании


def _run(*cmd) -> None:
    subprocess.run([str(c) for c in cmd], check=True, capture_output=True)


def _band(y: np.ndarray, lo: float, hi: float, win: float) -> np.ndarray:
    """Огибающая полосы: среднеквадратичное в окне win секунд, по значению на кадр. lo=0 — всё ниже hi, hi=0 — всё выше lo."""
    from scipy.ndimage import uniform_filter1d
    from scipy.signal import butter, sosfiltfilt
    kind, edge = ("bandpass", [lo, hi]) if lo and hi else ("highpass", lo) if lo else ("lowpass", hi)
    x = sosfiltfilt(butter(4, edge, kind, fs=SR, output="sos"), y)
    return np.sqrt(np.maximum(uniform_filter1d(x * x, max(1, int(win * SR))), 0))[::HOP]


def _nov(env: np.ndarray, lag: float, floor: float = .03) -> np.ndarray:
    """Прирост логарифма огибающей за lag секунд. floor — пол в долях почти-максимума: шорох в тишине не онсет."""
    lg, k = np.log(env / (np.percentile(env, 99.7) or 1) + floor), max(1, round(lag / FRAME))
    return np.r_[np.zeros(k), np.maximum(0, lg[k:] - lg[:-k])]


def _onsets(env: np.ndarray, rise: float, gap: float, lag: float, rel: float = 0) -> tuple[np.ndarray, np.ndarray]:
    """Онсеты полосы: время в секундах и уровень сразу после удара в долях почти-максимума.
    Меряется рост самой огибающей, а не сумма приростов по частотам: хвост шумового удара
    дрожит в каждой частоте, и сумма приростов принимала один хэт за дробь."""
    from scipy.signal import find_peaks
    i, _ = find_peaks(_nov(env, lag), height=rise, distance=max(1, round(gap / FRAME)))
    lvl = np.array([env[j:j + 10].max() for j in i]) / (np.percentile(env, 99.7) or 1)
    return i[lvl >= rel] * FRAME, lvl[lvl >= rel]


def _retrig(y: np.ndarray) -> np.ndarray:
    """Начала нот 808, секунды. Новая нота сэмплера сбивает фазу синуса, даже когда громкость ровная
    и высота та же, — рост огибающей такого не видит. Меряется отклонение спектра низа от предсказания
    «та же частота, фаза идёт дальше» в долях уровня; плавный слайд фазу не сбивает и нотой не считается.
    Окон два, и нота — где сбой видят оба. В окне 46 мс соседние гармоники суба ниже 45 Гц сидят в одном бине,
    бин бьётся с частотой основного тона, и предсказание не сходится на ровной ноте: долгий суб «НЕО» Платины
    читался как 11 нот в такт (08.10.2026). Окно 93 мс гармоники разделяет, но размазывает быстрый слайд
    и съезд высоты в атаке 808 — одно оно считало бы нотой их. Поэтому пик и момент — по короткому, как раньше,
    а длинное только подтверждает; сбой фазы в нём вдвое ниже (доля шага в окне) — вдвое ниже и порог.
    Ноту с медленной атакой после паузы не видит ни одно: фазу она не сбивает."""
    import librosa
    from scipy.ndimage import maximum_filter1d
    from scipy.signal import find_peaks

    def off(n_fft):
        x = librosa.stft(y, n_fft=n_fft, hop_length=2 * HOP)
        f = np.fft.rfftfreq(n_fft, 1 / SR)
        x = x[(f >= 30) & (f < 200)]
        mag, ph = np.abs(x), np.angle(x)
        dev = np.r_[0, 0, np.abs(x[:, 2:] - mag[:, 1:-1] * np.exp(1j * (2 * ph[:, 1:-1] - ph[:, :-2]))).sum(0)]
        rel = dev / (mag.sum(0) + .05 * np.percentile(mag.sum(0), 95))
        return rel, np.percentile(rel, 99)

    (rel, top), (wide, wide_top) = off(2048), off(4096)
    seen = maximum_filter1d(wide, 9) >= max(.15, .25 * wide_top)      # ±4 кадра (23 мс): окна ставят пик не в один кадр
    i, _ = find_peaks(np.where(seen, rel, 0), height=max(.3, .5 * top), distance=round(.08 / FRAME / 2))
    return i * 2 * FRAME


def _fit(env: np.ndarray, lo: float, hi: float, step: float) -> tuple[float, float, float]:
    """Темп и фаза сетки восьмых, на которую онсеты ложатся лучше всего: (оценка, bpm, фаза в секундах)."""
    from scipy.ndimage import maximum_filter1d
    env = maximum_filter1d(env, 5)
    best = (0.0, lo, 0.0)
    for bpm in np.arange(lo, hi, step):
        e = 30 / bpm
        k = np.arange(int(len(env) * FRAME / e) - 2) * e
        for ph in np.arange(0, e, 2 * FRAME):
            s = env[np.round((ph + k) / FRAME).astype(int)].mean()
            if s > best[0]:
                best = (s, float(bpm), float(ph))
    return best


def tempo(drums: np.ndarray, snare: np.ndarray, hint: float | None) -> tuple[float, float]:
    """Темп в записи «клэп раз в такт» и фаза шестнадцатых. drums — онсеты всех полос, snare — удары клэпа.
    Такт — самый короткий период, с которым клэп повторяет сам себя; сетка восьмых его уточняет.
    librosa.feature.tempo здесь не годится: на рисунке бочки 0-6-10 он ошибается в полтора раза и на 7%."""
    if hint:
        bpm = hint
    else:
        x = snare - snare.mean()
        lags = np.arange(round(240 / 200 / FRAME), min(round(240 / 100 / FRAME), len(x) // 2))    # темп 100–200
        ac = np.array([np.dot(x[:-n], x[n:]) for n in lags])
        if ac.max() <= 0:
            raise SystemExit("клэп не повторяется — темп не найти, подскажите --bpm")
        first = int(np.flatnonzero(ac >= .8 * ac.max())[0])        # начало первого высокого пика, вершина — рядом
        bpm = 240 / (lags[first + int(ac[first:first + 12].argmax())] * FRAME)
    _, bpm, _ = _fit(drums, bpm * .98, bpm * 1.02, .1)
    _, bpm, ph = _fit(drums, bpm - .15, bpm + .15, .01)
    return bpm, ph % (15 / bpm)


def measure(drums: np.ndarray, bass: np.ndarray, other: np.ndarray, hint: float | None = None) -> dict:
    """Рисунок по стемам окна. drums — стерео (2, n): по нему меряется панорама хэта; остальное — моно."""
    import librosa
    mono = drums.mean(0)
    # Окно низа — 40 мс: в окне короче периода синус 40 Гц «дышит», и хвост бочки читается дробью
    low, mid, high = _band(mono, 0, 110, .04), _band(mono, 1000, 5000, .03), _band(mono, 7000, 0, .006)
    every = sum(n / (n.max() or 1) for n in (_nov(low, .02), _nov(mid, .012), _nov(high, .006)))
    # Клэп или снейр — громкие удары в 1–5 кГц без низа под ними: у бочки с щелчком середина бывает
    # громче клэпа, но под ней низ. Клэп, сложенный с бочкой, узнаётся по хвосту: щелчок бочки
    # гаснет за 20 мс, шум клэпа через 60–90 мс ещё звучит
    from scipy.ndimage import gaussian_filter1d
    mt, ml = _onsets(mid, .5, .05, .012)
    at = np.round(mt / FRAME).astype(int)
    under = np.array([low[i:i + 12].max() for i in at]) / (np.percentile(low, 99.7) or 1)
    tail = np.array([mid[i + 20:i + 31].mean() if i + 31 < len(mid) else 0 for i in at])
    dry = under < .4
    if not dry.any():                                      # низ гудит под всем (сэмпл, протёкший 808) — берём громкие
        dry = np.ones(len(mt), bool)
    if not len(mt):
        raise SystemExit("клэп не найден: в полосе 1–5 кГц нет ударов")
    clap = dry & (ml >= .5 * np.percentile(ml[dry], 95))
    strong = mt[clap | (~dry & (tail >= .8 * np.median(tail[clap])))]
    # Бочка — рост низа вместе с ударом в 150–1000 Гц и не под клэпом: 808, протёкший в стем барабанов,
    # растёт без удара, а низ толстого снейра бочкой не считается. Время берётся по удару — он острее
    lt, _ = _onsets(low, .5, .08, .02, rel=.3)
    pt, _ = _onsets(_band(mono, 150, 1000, .01), .5, .05, .01, rel=.15)
    kt = np.array([pt[np.abs(pt - t).argmin()] for t in lt
                   if len(pt) and np.abs(pt - t).min() < .045 and (not len(strong) or np.abs(strong - t).min() > .045)])
    train = np.zeros(len(mid))
    train[np.round(strong / FRAME).astype(int)] = 1
    bpm, ph = tempo(every, gaussian_filter1d(train, 4), hint)
    q = 15 / bpm                                           # шестнадцатая, секунд

    def step(t):                                           # место на сетке шестнадцатых, дробное
        return (np.asarray(t) - ph) / q

    spots = np.round(step(strong)).astype(int) % 16
    mode = int(np.bincount(spots, minlength=16).argmax()) if len(spots) else 8
    shift = (mode - 8) % 16                                # клэп — на шаге 8: так такт рисуют в FL
    # Клэп дважды в такт (быстрее такт не записать: темп вышел бы за 200) — это клэп на 2-й и 4-й доле
    if len(spots) and (spots == (mode + 8) % 16).sum() >= .6 * (spots == mode).sum():
        shift = (mode - 4) % 16

    def bar_step(t):
        x = np.round(step(t) - shift).astype(int)
        return x // 16, x % 16

    ht, hh = _onsets(high, .4, .015, .006, rel=.06)
    kb, ks = bar_step(kt)
    hb, _ = bar_step(ht)
    sb, ss = bar_step(strong)
    n_bars = int(len(mid) * FRAME / (16 * q))
    live = [b for b in range(1, n_bars - 1) if (kb == b).sum() >= 1 or (hb == b).sum() >= 4]
    if len(live) < 4:
        raise SystemExit("в окне меньше четырёх тактов с барабанами — мерить нечего")

    every_t = np.r_[ht, strong, kt]
    on_grid = float(np.mean(np.abs(step(every_t) - np.round(step(every_t))) < .2)) if len(every_t) else 0

    def two_bars(bars_of, steps_of):
        """Самый частый рисунок на два такта строкой: x — удар, по знаку на шестнадцатую."""
        pairs = [tuple("".join("x" if ((bars_of == b + k) & (steps_of == i)).any() else "." for i in range(16))
                       for k in (0, 1)) for b in live if b + 1 in live]
        best = max(set(pairs), key=pairs.count) if pairs else ("", "")
        return "|".join(best), round(pairs.count(best) / max(len(pairs), 1), 2)

    def per_bar(b_of):
        return [int((b_of == b).sum()) for b in live]

    # Хэт: сетка — самый частый промежуток между ударами; дробь — два промежутка 1/32 и мельче в такте
    ioi = np.diff(ht) / q
    cls = np.array([min(GRIDS, key=lambda g: abs(np.log(max(x, 1e-3) / g))) for x in ioi])
    near = np.array([abs(np.log(max(x, 1e-3) / c)) < .18 for x, c in zip(ioi, cls)], bool)
    ib = hb[:-1]
    grid = max((2, 1, 4 / 3, 2 / 3), key=lambda g: int(((cls == g) & near).sum())) if len(cls) else None
    rolls = [b for b in live if ((ib == b) & near & (cls <= .5)).sum() >= 2]
    trips = [b for b in live if ((ib == b) & near & np.isin(cls, (4 / 3, 2 / 3, 1 / 3))).sum() >= 2]
    at = np.clip(np.round(ht / FRAME).astype(int) + 2, 0, len(high) - 1)
    el, er = (_band(drums[0], 7000, 0, .006)[at] ** 2, _band(drums[1], 7000, 0, .006)[at] ** 2)
    pan = (er - el) / np.maximum(er + el, 1e-12) * 100
    # Свинг: где внутри восьмой стоит удар между долями; 50 — ровно, 67 — триоль
    # (только среди ударов, идущих шестнадцатыми: дробь 1/32 свингом не считается)
    frac = (step(ht) - shift) % 2 / 2
    gap = np.r_[9, ioi, 9]
    even = (gap[:-1] > .6) & (gap[:-1] < 1.4) & (gap[1:] > .6) & (gap[1:] < 1.4)
    off = frac[even & (frac > .3) & (frac < .8)]

    # Бочка: петля — наименьшее число тактов, через которое рисунок повторяется в 70% случаев
    pat = {b: tuple(sorted(set(ks[kb == b]))) for b in live}
    loop = next((n for n in (1, 2, 4, 8)
                 if (p := [pat[b] == pat[b - n] for b in live if b - n in pat]) and np.mean(p) >= .7), None)
    hist = np.bincount(ks[np.isin(kb, live)], minlength=16) / len(live)
    has_kick = len(kt) >= len(live) / 4               # реже раза в четыре такта — отдельной бочки нет, низ держит 808

    # 808: ноты — от онсета до следующего или до тишины
    b_env = _band(bass, 0, 160, .04)
    loud = b_env >= .12 * np.percentile(b_env, 95)
    bt = _retrig(bass)
    f = np.fft.rfftfreq(4096, 1 / SR)
    bt = bt[[bool(loud[min(round(t / FRAME) + 12, len(loud) - 1)]) for t in bt]] if len(bt) else bt
    ends = []
    for i, t in enumerate(bt):
        a = min(round(t / FRAME) + 12, len(loud) - 1)
        quiet = np.flatnonzero(~loud[a:])
        stop = (a + quiet[0]) * FRAME if len(quiet) else len(loud) * FRAME
        ends.append(min(stop, bt[i + 1]) if i + 1 < len(bt) else stop)
    ends = np.array(ends)
    bb, _ = bar_step(bt) if len(bt) else (np.array([], int), None)
    keep = np.isin(bb, live)
    lens = (ends - bt)[keep] / q if len(bt) else np.array([])
    y22 = librosa.resample(bass, orig_sr=SR, target_sr=22050)
    semi = 12 * np.log2(librosa.yin(y22, fmin=27, fmax=180, sr=22050, frame_length=2048, hop_length=256) / 440) + 69
    pitches, slides = [], 0
    for t, e in zip(bt[keep], ends[keep]):
        p = semi[round(t / (256 / 22050)) + 3:round(e / (256 / 22050))]
        if len(p) < 8:
            continue
        mid_p, end_p = np.median(p[len(p) * 3 // 10:len(p) * 7 // 10]), np.median(p[-max(3, len(p) // 7):])
        pitches.append(round(float(mid_p)))
        between = (p - mid_p) / (end_p - mid_p) if abs(end_p - mid_p) >= 2 else np.array([])
        slides += bool(len(between) and ((between > .25) & (between < .75)).any())
    with_kick = np.mean([np.abs(kt - t).min() < .045 for t in bt[keep]]) if has_kick and keep.any() else None
    # Удары низа — бочка и 808 вместе: demucs делит их не всегда, а рисунок низа один
    hits = np.sort(np.r_[bt, [t for t in kt if not len(bt) or np.abs(bt - t).min() > .05]])
    lb, ls = bar_step(hits) if len(hits) else (np.array([], int), np.array([], int))
    low_hist = np.bincount(ls[np.isin(lb, live)], minlength=16) / len(live)
    bar_of_frame = (np.round(step(np.arange(len(loud)) * FRAME) - shift - .5).astype(int)) // 16

    # Мелодия: петля по хроме тактов, одновременные ноты, занятые октавы
    chroma = librosa.feature.chroma_cqt(y=librosa.resample(other, orig_sr=SR, target_sr=22050), sr=22050, hop_length=512)
    ct = np.arange(chroma.shape[1]) * 512 / 22050
    cb = np.floor((step(ct) - shift) / 16).astype(int)
    bars = {b: chroma[:, cb == b].mean(1) for b in live if (cb == b).any()}

    def sim(n):
        v = [float(np.dot(bars[b], bars[b - n]) / (np.linalg.norm(bars[b]) * np.linalg.norm(bars[b - n]) or 1))
             for b in bars if b - n in bars]
        return np.mean(v) if v else 0

    sims = {n: sim(n) for n in (1, 2, 4, 8)}
    o_env = _band(other, 60, 8000, .05)
    sounding = np.interp(ct, np.arange(len(o_env)) * FRAME, (o_env >= .25 * np.percentile(o_env, 90)).astype(float)) > .5
    voices = (chroma[:, sounding] >= .6).sum(0) if sounding.any() else np.array([0])
    o_spec = np.abs(librosa.stft(other, n_fft=4096, hop_length=2048)) ** 2
    octs = np.array([o_spec[(f >= lo) & (f < 2 * lo)].sum() for lo in (65, 130, 261, 523, 1046, 2093, 4186)])
    mute = np.mean([o_env[bar_of_frame == b].mean() < .25 * np.median(o_env) for b in live if (bar_of_frame == b).any()])

    rise = [float(np.mean(x)) if len(x) else 0 for x in np.array_split(
        [o_env[bar_of_frame == b].mean() for b in live if (bar_of_frame == b).any()], 3)]   # мелодия по третям окна

    return dict(
        bpm=round(bpm, 1), bars=len(live), bar0=round(ph + shift * q, 4), on_grid=round(on_grid, 2),
        hat_per_bar=statistics.median(per_bar(hb)), hat_grid=GRIDS.get(grid, "нет"),
        hat_roll_bars=round(len(rolls) / len(live), 2), hat_trip_bars=round(len(trips) / len(live), 2),
        hat_dyn=round(float(np.std(hh) / np.mean(hh)), 2) if len(hh) else None,
        hat_pan=round(float(np.std(pan)), 1) if len(pan) else None,
        swing=round(float(np.median(off)) * 100, 1) if len(off) >= 8 else None,
        snare_per_bar=statistics.median(per_bar(sb)),
        snare_steps={int(k): round(float(v), 2) for k in range(16)
                     if (v := (ss[np.isin(sb, live)] == k).sum() / len(live)) >= .2},
        kick_per_bar=statistics.median(per_bar(kb)) if has_kick else 0, kick_loop=loop if has_kick else None,
        kick_steps={int(k): round(float(v), 2) for k, v in enumerate(hist) if v >= .3} if has_kick else {},
        low_per_bar=statistics.median(per_bar(lb)),
        low_steps={int(k): round(float(v), 2) for k, v in enumerate(low_hist) if v >= .3},
        low_off=round(float(1 - low_hist[[0, 8]].sum() / max(low_hist.sum(), 1e-9)), 2),
        low_2bars=two_bars(lb, ls)[0], low_2bars_share=two_bars(lb, ls)[1],
        clap_2bars=two_bars(sb, ss)[0], clap_2bars_share=two_bars(sb, ss)[1],
        b808_per_bar=statistics.median(per_bar(bb)) if len(bb) else 0,
        b808_len=round(float(np.median(lens)), 1) if len(lens) else None,
        b808_fill=round(float(np.mean([loud[bar_of_frame == b].mean() for b in live if (bar_of_frame == b).any()])), 2),
        b808_pitches=len(set(pitches)), b808_range=(max(pitches) - min(pitches)) if pitches else None,
        b808_slides_per_8=round(slides / len(live) * 8, 1),
        b808_with_kick=round(float(with_kick), 2) if with_kick is not None else None,
        mel_loop=next((n for n in (1, 2, 4, 8) if sims[n] >= max(sims.values()) - .02), None),
        mel_voices=float(np.median(voices)), mel_octaves=int((octs >= octs.max() * 10 ** -1.5).sum()),
        mel_mute_bars=round(float(mute), 2),
        # Кино (02.10.2026): остинато — соседние такты похожи по хроме; нарастание — мелодия к концу окна громче.
        # ponytail: окно 90 секунд, а не весь трек, и громкость, а не число слоёв — слои demucs не делит
        mel_same=round(float(sims[1]), 2), mel_rise=round(float(20 * np.log10((rise[-1] + 1e-9) / (rise[0] + 1e-9))), 1),
    )


def color(other: np.ndarray, bpm: float | None, bar0: float = 0.0) -> dict:
    """Цвет музыки (стем other): яркость, регистр, плотность нот, смены аккорда, шум, верха, заполнение.
    02.10.2026 владелец назвал свои биты приторными и дал референсы звука. Рисунок барабанов тут ни при чём:
    сравнивать надо тембр и гармонию, а их `measure` не снимает. bar0 — начало любого такта, секунды.

    Каждая мера грубая, и читать числа надо с этим:
    регистр — медиана самой громкой полутоновой полосы CQT по кадрам: в аккорде это самый громкий голос
    (обычно низ пэда), а не мелодия, и бывает обертон вместо основного тона;
    атаки — рост CQT в 65 Гц – 4 кГц, только громкие ноты (до −30 дБ от пика): хэт, протёкший в стем,
    мимо, а протёкший голос и вибрато пэда считаются;
    аккорд такта — ближайшее из 24 трезвучий по хроме такта: смена внутри такта не видна, одноголосая
    мелодия без аккорда прыгает между трезвучиями, а ошибка темпа вдвое меняет и число вдвое;
    шум — плоскостность спектра в 100–8000 Гц, верха — доля энергии 6–16 кГц. Выше 16 кГц не смотрим:
    превью магазина сжато, и срез кодека читался бы тембром. Такта нет (bpm пуст) — меры «на такт» пустые."""
    import librosa
    spec = np.abs(librosa.stft(other, n_fft=2048, hop_length=512)) ** 2
    f = np.fft.rfftfreq(2048, 1 / SR)
    spec, f = spec[f < 16000], f[f < 16000]
    e = spec.sum(0)
    if not e.max():
        return {}
    on = e >= .0625 * np.percentile(e, 90)                 # музыка звучит: порог тот же, что у `sounding` в measure
    mag, band = np.sqrt(spec[:, on]), spec[(f >= 100) & (f < 8000)][:, on]
    flat = np.exp(np.log(band + 1e-10).mean(0)) / (band.mean(0) + 1e-10)
    cq = np.abs(librosa.cqt(librosa.resample(other, orig_sr=SR, target_sr=22050), sr=22050, hop_length=512,
                            fmin=librosa.midi_to_hz(36), n_bins=72, tuning=None))    # строй трека — по звуку: сэмплы бывают расстроены
    loud = cq.sum(0) >= .25 * np.percentile(cq.sum(0), 90)
    note = int(np.median(36 + cq[:, loud].argmax(0)))
    # Всё тише −30 дБ от пика — в пол: при −40 дрожание шумового дна читалось атаками (182 вместо 128
    # на синтетике). Цена: тихий слой под громким в счёт не идёт
    hits = librosa.onset.onset_detect(onset_envelope=librosa.onset.onset_strength(
        S=librosa.amplitude_to_db(cq, ref=np.max, top_db=30), sr=22050), sr=22050, hop_length=512)
    out = dict(col_bright=round(float(np.median((f[:, None] * mag).sum(0) / mag.sum(0)))),
               col_note=note, col_note_name=str(librosa.midi_to_note(note, unicode=False)),
               col_notes_sec=round(len(hits) / (len(other) / SR), 2), col_notes_bar=None, col_chords_8=None,
               col_flat=round(float(np.median(flat)), 4),
               col_air=round(float(spec[f >= 6000][:, on].sum() / spec[:, on].sum()), 4),
               col_fill=round(float(on.mean()), 2))
    if bpm:
        bar = 240 / bpm
        chroma = librosa.feature.chroma_cqt(C=cq, sr=22050, hop_length=512, fmin=librosa.midi_to_hz(36), bins_per_octave=12)
        cb = np.floor((np.arange(chroma.shape[1]) * 512 / 22050 - bar0) / bar).astype(int)
        # ponytail: 24 мажорных и минорных трезвучия, такт целиком; септаккорды и смены в полтакта — когда понадобятся
        tri = np.array([np.roll([1, 0, 0, m, 1 - m, 0, 0, 1, 0, 0, 0, 0], r) for m in (0, 1) for r in range(12)])
        chords = [int((tri @ chroma[:, (cb == b) & loud].mean(1)).argmax())
                  for b in range(cb.min() + 1, cb.max()) if ((cb == b) & loud).any()]     # крайние такты окна неполные
        out.update(col_notes_bar=round(len(hits) / (len(other) / SR / bar), 1),
                   col_chords_8=round(sum(a != b for a, b in zip(chords, chords[1:])) / max(len(chords) - 1, 1) * 8, 1))
    return out


def _cqt(y: np.ndarray, sr: int, tune: float) -> np.ndarray:
    """Энергия по октавам от C1, нотам и кадрам: 36 полос на октаву, из трёх полос полутона — только центральная."""
    import librosa
    return np.abs(librosa.cqt(y, sr=sr, fmin=librosa.note_to_hz("C1"), n_bins=36 * 7, bins_per_octave=36,
                              tuning=tune, hop_length=512))[0::3].reshape(7, 12, -1) ** 2


def root(y: np.ndarray, sr: int) -> int | None:
    """Корневая нота одиночного звука — номер, который ждёт канал FL (60 — C5). None — замер неуверенный.
    Три признака, и нужны все. Высота: pyin слышит её почти во всех громких кадрах, и почти все они на одной ноте —
    звук с вибрато в полтона, глиссандо и скачками на октаву отпадает. Хрома: громчайший класс высот — тот же, чужих нот
    нет; квинта и большая терция чужими не считаются — это 3-я и 5-я гармоники самой ноты. Основной тон: на найденной
    высоте есть энергия — у квинты и мажорного трезвучия pyin находит общий период двух нот, ниже обеих, и там пусто.

    ponytail: октава — оценка. У слоёного звука (струнные в две октавы) корнем выйдет нижний слой, даже когда верхний
    громче; ошибётся — партия зазвучит октавой выше или ниже, но не фальшиво. Понадобится точнее — сравнивать чётные
    и нечётные гармоники."""
    import librosa
    y = librosa.effects.trim(librosa.resample(y, orig_sr=sr, target_sr=22050), top_db=45)[0]
    y = np.pad(y, (0, max(8192 - len(y), 0)))                   # короткий плак: окну спектра нужна полная длина
    f0, voiced, _ = librosa.pyin(y, fmin=32.7, fmax=2093, sr=22050, frame_length=4096, hop_length=512)
    rms = librosa.feature.rms(y=y, frame_length=4096, hop_length=512)[0][:len(f0)]
    loud = rms > rms.max() * .1
    if not loud.any() or (voiced & loud).sum() < ROOT_SURE * loud.sum():
        return None
    midi = librosa.hz_to_midi(f0[voiced & loud])
    mid = float(np.median(midi))
    note = round(mid)
    if abs(mid - note) * 100 > ROOT_CENTS or (np.abs(midi - mid) < .35).mean() < ROOT_SURE:
        return None
    pcs = _cqt(y, 22050, mid - note).sum((0, 2))
    if pcs.argmax() != note % 12 or max(pcs[(note + k) % 12] for k in range(1, 12) if k not in (4, 7)) >= ROOT_ALIEN * pcs.max():
        return None
    power = (np.abs(librosa.stft(y, n_fft=8192, hop_length=1024)) ** 2).mean(1)
    freqs, hz = librosa.fft_frequencies(sr=22050, n_fft=8192), librosa.midi_to_hz(mid)
    parts = [float(power[slice(*np.searchsorted(freqs, (h * hz * .977, h * hz * 1.0235)) + (0, 1))].max(initial=0))
             for h in range(1, 11)]                             # гармоника — пик в ±40 центов от кратной частоты
    return note if parts[0] >= ROOT_FUND * sum(parts) else None


def loop(y: np.ndarray, sr: int, bpm: float) -> dict | None:
    """Замер петли: такты, веса двенадцати нот, звучащие ноты, тоника и лад, строй, опора каждого такта.
    None — петля не в 1, 2, 4 или 8 тактов по темпу из имени: на сетку бита такая не ложится.

    ponytail: наивная хрома, и читать её надо с этим. Обертон громкой ноты считается нотой: квинта (3-я гармоника),
    большая терция (5-я) и малая септима (7-я) — у ля «звучат» ми, до-диез и соль, даже когда их никто не играл.
    Опора такта — самый громкий класс высот в C2–B3, а не нижняя нота аккорда: мелодия в этом регистре её перевесит.
    Тоника — ближайший из 24 профилей мажора и минора: у петли на одном аккорде это аккорд, а не тональность,
    уверенность — отрыв от второго по счёту. Строй — оценка librosa, у петли с шумом или перебором гуляет на десятки
    центов. Станет мало — мультипитч (basic-pitch) вместо хромы и f0 баса (pyin по нижней полосе) вместо опоры."""
    import librosa
    from .noty import NOTES
    bars = len(y) / sr * bpm / 240
    if round(bars) not in LOOP_BARS or abs(bars - round(bars)) > .02:
        return None
    bars = round(bars)
    tune = float(librosa.estimate_tuning(y=y, sr=sr))
    c = _cqt(y, sr, tune)
    weights = c.sum((0, 2)) / max(c.sum((0, 2)).max(), 1e-12)
    fit = sorted(((float(np.corrcoef(np.sqrt(weights), np.roll(profile, tonic))[0, 1]), tonic, mode)
                  for mode, profile in KEYS.items() for tonic in range(12)), reverse=True)
    edges = np.linspace(0, c.shape[2], bars + 1).astype(int)
    return {"bars": bars, "weights": [round(float(w), 2) for w in weights],
            "notes": [NOTES[i] for i in range(12) if weights[i] >= LOOP_NOTE],
            "tonic": NOTES[fit[0][1]], "mode": fit[0][2], "sure": round(fit[0][0] - fit[1][0], 2), "tune": round(tune * 100),
            "roots": [NOTES[int(c[1:3, :, a:b].sum((0, 2)).argmax())] for a, b in zip(edges, edges[1:])]}


def loops(word: str = "") -> str:
    """Замер всех разрешённых петель библиотеки владельца → поле loops в data/beat_sounds.json, строкой на петлю,
    как лежит промер Serum: вложенные списки при записи с отступом дали бы тридцать строк на петлю.
    Заглушку iCloud не читаем — чтение повисает на скачивании; её прошлый замер остаётся. word — мерить только петли
    с этим словом в имени, у прочих замер прежний: новый набор не повод перечитывать старые."""
    import librosa
    from . import config, noty
    data = json.loads(config.BEAT_SOUNDS.read_text("utf-8"))
    rows, old, skipped = {}, data.get("loops", {}), {"заглушка iCloud": 0, "не 1, 2, 4 или 8 тактов": 0}
    for name in sorted(n for n in data["sounds"] if n.startswith((noty.LOOPS + "/", noty.NET_LOOPS + "/", noty.GLORY_LOOPS + "/"))
                       and noty.loop_bpm(n)):
        path = noty.LIBRARY["KITS"] / name.partition("/")[2]
        if word.lower() not in name.lower() or not path.exists() or os.stat(path).st_flags & DATALESS:
            skipped["заглушка iCloud"] += word.lower() in name.lower()
            rows |= {name: old[name]} if name in old else {}
            continue
        y, sr = librosa.load(path, sr=None)
        m = loop(y, sr, noty.loop_bpm(name))
        if not m:
            skipped["не 1, 2, 4 или 8 тактов"] += 1
            continue
        rows[name] = " | ".join((str(m["bars"]), " ".join(m["notes"]), f"{m['tonic']} {m['mode']} {m['sure']:.2f}", f"{m['tune']:+d}",
                                 " ".join(m["roots"]), " ".join(str(round(w * 100)) for w in m["weights"])))
    about = ("замер звука петли (zamer --loops), поля через « | »: такты по темпу из имени | звучащие ноты (энергия от "
             f"{LOOP_NOTE:.0%} самой громкой) | тоника, лад и уверенность (отрыв от второго по счёту профиля) | строй, центы | "
             "опора каждого такта петли (громчайшая нота в C2–B3) | веса нот от C до B, самая громкая — 100. "
             "Обертоны громкой ноты считаются нотами, тоника и строй — оценка")
    config.BEAT_SOUNDS.write_text(json.dumps(data | {"loops_about": about, "loops": rows}, ensure_ascii=False, indent=1) + "\n",
                                  encoding="utf-8")
    return f"петель замерено: {len(rows)}; мимо — " + ", ".join(f"{k}: {v}" for k, v in skipped.items())


def sections(full: np.ndarray, sr: int, bpm: float, bar0: float) -> dict:
    """Части по всему треку: где низ (бочка и 808) играет, а где выключен. Сетка — по полтакта."""
    half = 120 / bpm
    lo = np.abs(np.fft.rfft(full[:len(full) // 1024 * 1024].reshape(-1, 1024) * np.hanning(1024), axis=1))
    f = np.fft.rfftfreq(1024, 1 / sr)
    e = (lo[:, (f >= 30) & (f < 120)] ** 2).sum(1)
    t = (np.arange(len(e)) + .5) * 1024 / sr
    loud = np.abs(full) > .02 * np.abs(full).max()
    start, stop = np.flatnonzero(loud)[[0, -1]] / sr
    # Первая сильная доля трека; затакт короче четверти такта к ней и относится
    first = bar0 + np.ceil((start - bar0) / (2 * half) - .25) * 2 * half
    n = int((stop - first) / half)
    seg = np.array([e[(t >= first + i * half) & (t < first + (i + 1) * half)].mean() for i in range(n)])
    on = seg >= .2 * np.percentile(seg, 80)
    # Три длины тишины низа: «вдох» в полтакта внутри рисунка, выключение на такт-полтора и часть без низа
    # (два такта и дольше: вступление, мост). Вдохи склеиваются с игрой, остальное считается
    runs, i = [], 0
    while i < n:
        j = i
        while j < n and on[j] == on[i]:
            j += 1
        runs.append([bool(on[i]), (j - i) / 2, i / 2])
        i = j
    inner = [(o, ln, at) for k, (o, ln, at) in enumerate(runs) if 0 < k < len(runs) - 1]
    breaths = [at for o, ln, at in inner if not o and ln < 1]
    drops = [at for o, ln, at in inner if not o and 1 <= ln < 2]
    parts = [ln for o, ln, at in inner if not o and ln >= 2]
    marks = sorted(at for o, ln, at in inner if not o and ln >= 1)
    played = sum(ln for o, ln, at in runs if o) or 1
    return dict(seconds=round(float(stop - start)), total_bars=round(n / 2),
                intro_bars=runs[0][1] if runs and not runs[0][0] else 0,
                breaths_per_8=round(len(breaths) / played * 8, 1), drops=len(drops),
                quiet_parts=len(parts), quiet_part_bars=statistics.median(parts) if parts else 0,
                drop_every=statistics.median(np.diff(marks).tolist()) if len(marks) > 1 else None,
                map="".join("#" if o else "." for o in on))     # по знаку на полтакта: # — низ играет


def run(path: Path, hint: float | None = None, start: float | None = None, with_color: bool = False) -> dict:
    """Замер файла: окно → demucs → рисунок; части — по всему файлу. with_color — ещё и цвет музыки."""
    import librosa
    import soundfile as sf
    with tempfile.TemporaryDirectory(prefix="zamer-") as tmp:
        tmp = Path(tmp)
        # -t стоит перед своим -i: память ffmpeg-infinite-source
        _run("ffmpeg", "-v", "error", "-y", "-t", 900, "-i", path, "-ac", 1, "-ar", 11025, tmp / "full.wav")
        full, sr = sf.read(tmp / "full.wav", dtype="float32")
        length = len(full) / sr
        at = start if start is not None else max(0, min(25, length - WINDOW - 5))
        _run("ffmpeg", "-v", "error", "-y", "-ss", at, "-t", WINDOW, "-i", path, "-ac", 2, "-ar", SR, tmp / "win.wav")
        _run(sys.executable, "-m", "demucs", "-n", "htdemucs", "-d", "mps", "-o", tmp, tmp / "win.wav")
        stem = {n: librosa.load(tmp / "htdemucs" / "win" / f"{n}.wav", sr=SR, mono=n != "drums")[0]
                for n in ("drums", "bass", "other")}
        if stem["drums"].ndim == 1:
            stem["drums"] = np.stack([stem["drums"]] * 2)
        try:
            out = measure(stem["drums"], stem["bass"], stem["other"], hint)
            out.update(sections(full, sr, out["bpm"], at + out["bar0"]))
        except SystemExit as e:                            # клэпа нет — рисунка нет, а цвет меряется и без такта
            if not with_color:
                raise
            out = dict(bpm=hint, no_pattern=str(e))
        if with_color:
            out.update(color(stem["other"], out["bpm"], out.get("bar0", 0)))
        out.pop("bar0", None)
    return dict(file=path.name, **out)


COLS = (("bpm", "темп"), ("hat_per_bar", "хэт/такт"), ("hat_roll_bars", "такты с дробью"),
        ("hat_trip_bars", "с триолями"), ("hat_dyn", "хэт: разброс силы"), ("hat_pan", "хэт: разброс панорамы"),
        ("swing", "свинг %"), ("snare_per_bar", "клэп/такт"), ("kick_per_bar", "бочка/такт"),
        ("kick_loop", "петля бочки, т."), ("low_per_bar", "ударов низа/такт"),
        ("low_off", "низ мимо 1-й и 3-й доли"), ("b808_per_bar", "808/такт"),
        ("b808_len", "нота 808, 1/16"), ("b808_fill", "808 звучит"), ("b808_pitches", "разных нот 808"),
        ("b808_slides_per_8", "слайдов на 8 т."), ("b808_with_kick", "808 с бочкой"), ("mel_loop", "петля мелодии, т."),
        ("mel_voices", "нот разом"), ("mel_octaves", "октав занято"), ("mel_mute_bars", "такты без мелодии"),
        ("mel_same", "соседние такты похожи"), ("mel_rise", "мелодия к концу громче, дБ"),
        ("col_bright", "яркость музыки, Гц"), ("col_note", "регистр, MIDI"), ("col_notes_sec", "атак музыки в секунду"),
        ("col_notes_bar", "атак музыки на такт"), ("col_chords_8", "смен аккорда на 8 т."),
        ("col_flat", "шум (плоскостность)"), ("col_air", "доля верхов 6–16 кГц"), ("col_fill", "музыка звучит"),
        ("seconds", "длина, с"), ("total_bars", "тактов"), ("intro_bars", "вступление, т."),
        ("breaths_per_8", "вдохов в полтакта на 8 т."), ("drops", "выключений на такт"),
        ("drop_every", "выключение раз в, т."), ("quiet_parts", "частей без низа"),
        ("quiet_part_bars", "часть без низа, т."))


def table(rows: list[dict] | dict) -> str:
    """Сводка: медиана (и разброс от — до) по группам; сетка хэта и место клэпа — самые частые."""
    groups: dict[str, list[dict]] = {}
    for r in rows["rows"] if isinstance(rows, dict) else rows:      # data/beats_zamer.json или рабочий список --out
        groups.setdefault(r.get("style") or r.get("group", "все"), []).append(r)
    out = []
    for g, rs in groups.items():
        out.append(f"\n== {g}: {len(rs)}")
        for key, name in COLS:
            v = sorted(r[key] for r in rs if r.get(key) is not None)
            if v:
                out.append(f"{name:26} {statistics.median(v):g}  ({v[0]:g} … {v[-1]:g})"
                           + (f", не измерено у {len(rs) - len(v)}" if len(v) < len(rs) else ""))
        grids = [r.get("hat_grid", "нет") for r in rs]
        out.append(f"{'сетка хэта':26} " + ", ".join(f"{g} — {grids.count(g)}" for g in sorted(set(grids), key=grids.count, reverse=True)))
        spots = [" и ".join(str(k) for k in r.get("snare_steps", ())) or "нет" for r in rs]
        out.append(f"{'клэп на шагах':26} " + ", ".join(f"{s} — {spots.count(s)}" for s in sorted(set(spots), key=spots.count, reverse=True)))
    return "\n".join(out)


def selftest() -> None:
    """Синтетический бит с известным рисунком: 150 BPM, клэп на 8, хэт восьмыми с дробью 1/32 в каждом
    четвёртом такте, бочка 0-6-10, 808 теми же нотами со слайдом вверх на октаву в конце четвёрки."""
    rng, q = np.random.default_rng(0), 15 / 150
    n = int(20 * 16 * q * SR)
    t = np.arange(n) / SR
    drums, bass = np.zeros((2, n)), np.zeros(n)

    def hit(at, sound, pan=0.0):
        i = int(at * SR)
        m = min(len(sound), n - i)
        drums[0, i:i + m] += sound[:m] * (1 - pan) / 2
        drums[1, i:i + m] += sound[:m] * (1 + pan) / 2

    def noise(ms, lo, hi):
        x = np.fft.rfft(rng.standard_normal(int(ms / 1000 * SR)))
        fr = np.fft.rfftfreq(int(ms / 1000 * SR), 1 / SR)
        x[(fr < lo) | (fr > hi)] = 0
        y = np.fft.irfft(x)
        return y / np.abs(y).max() * np.exp(-np.arange(len(y)) / (len(y) / 4))

    kick = np.sin(2 * np.pi * 60 * np.arange(int(.09 * SR)) / SR) * np.exp(-np.arange(int(.09 * SR)) / (.03 * SR))
    for b in range(2, 18):
        o = b * 16 * q
        for s in (0, 6, 10):
            hit(o + s * q, kick)
        hit(o + 8 * q, noise(70, 1000, 5000) * .9)
        hats = [s for s in range(0, 16, 2)]
        hats = [s for s in hats if s < 12] + [12 + k / 2 for k in range(8)] if b % 4 == 3 else hats
        for k, s in enumerate(hats):
            hit(o + s * q, noise(18, 8000, 15000) * (.5 if k % 2 else .3), pan=.6 if k % 2 else -.6)
        for s, ln in ((0, 6), (6, 4), (10, 6)):
            i, m = int((o + s * q) * SR), int(ln * q * SR * .95)
            f0 = np.full(m, 55.0)
            if b % 4 == 3 and s == 10:
                f0[m // 2:] = np.minimum(110, 55 * 2 ** (np.arange(m - m // 2) / (.1 * SR)))
            bass[i:i + m] = np.sin(2 * np.pi * np.cumsum(f0) / SR) * np.minimum(1, np.arange(m)[::-1] / 400)
    other = np.sin(2 * np.pi * 440 * t) * .2
    r = measure(drums, bass, other)
    assert abs(r["bpm"] - 150) < .3, r["bpm"]
    assert r["snare_steps"] == {8: 1.0} and r["snare_per_bar"] == 1, r["snare_steps"]
    assert r["hat_grid"] == "1/8" and r["hat_roll_bars"] == .25 and r["hat_trip_bars"] == 0, r
    assert r["kick_per_bar"] == 3 and set(r["kick_steps"]) == {0, 6, 10} and r["kick_loop"] == 1, r
    assert r["low_per_bar"] == 3 and set(r["low_steps"]) == {0, 6, 10}, r
    assert r["low_2bars"] == "x.....x...x.....|x.....x...x....." and r["clap_2bars"] == "........x.......|........x.......", r
    assert r["b808_per_bar"] == 3 and 3.5 <= r["b808_len"] <= 6 and r["b808_with_kick"] == 1, r
    assert 1.5 <= r["b808_slides_per_8"] <= 2.5 and r["hat_pan"] > 30 and r["swing"] is None, r
    assert r["mel_same"] > .95 and abs(r["mel_rise"]) < 1, r      # ровный тон: такты одинаковы, громкость не растёт
    from scipy.signal import resample_poly
    sec = sections(resample_poly(drums.sum(0) + bass + other, 1, 4), 11025, 150, r["bar0"])
    assert sec["intro_bars"] == 2 and sec["drops"] == 0 and sec["map"] == "...." + "#" * 32 + "....", sec
    # Долгий суб без спада, как в «НЕО» Платины: нота на такт, высота меняется по тактам (C1, D1, F1), у звука
    # вторая и третья гармоники. В окне 46 мс они бьются внутри бина — ровная нота читалась как десять нот в такт
    sub = np.zeros(n)
    for b in range(2, 18):
        i, m = int(b * 16 * q * SR), int(16 * q * SR)
        p = 2 * np.pi * (32.7, 36.71, 43.65)[b % 3] * np.arange(m) / SR
        edge = np.minimum(1, np.minimum(np.arange(m), np.arange(m)[::-1]) / 220)       # 5 мс: сэмплер нот не щёлкает
        sub[i:i + m] = (np.sin(p) + .3 * np.sin(2 * p) + .5 * np.sin(3 * p)) * edge
    r = measure(drums, sub, other)
    assert r["b808_per_bar"] == 1 and r["b808_len"] >= 12 and r["b808_fill"] == 1 and r["b808_pitches"] == 3, r
    # Цвет: редкий низкий синус, один на такт, против частых высоких нот со сменой высоты по тактам и шумом
    bar, m = 2.0, int(32 * SR)
    tt = np.arange(m) / SR
    low_tone = np.sin(2 * np.pi * 110 * tt) * np.exp(-(tt % bar) / .4) * np.minimum(1, (tt % bar) / .01)
    hi_f = np.where((tt // bar) % 2 == 0, 1046.5, 1480.0)
    hi_tone = (np.sin(2 * np.pi * np.cumsum(hi_f) / SR) * np.exp(-(tt % .25) / .05) * np.minimum(1, (tt % .25) / .005) * .3
               + rng.standard_normal(m) * .03)
    a, b = color(low_tone, 120), color(hi_tone, 120)
    assert a["col_note"] == 45 and b["col_note"] in (84, 90) and b["col_bright"] > 5 * a["col_bright"], (a, b)
    assert .5 <= a["col_notes_bar"] <= 2 and 6 <= b["col_notes_bar"] <= 10, (a, b)
    assert a["col_chords_8"] == 0 and b["col_chords_8"] >= 7, (a, b)
    assert b["col_flat"] > 10 * a["col_flat"] and b["col_air"] > 10 * a["col_air"], (a, b)
    # Петля из синусов известных нот: два такта на 120 — ля минор (A2, C4, E4) и соль мажор (G2, B3, D4)
    tt = np.arange(2 * SR) / SR

    def chord(*hz):
        return sum(np.sin(2 * np.pi * f * tt) for f in hz) * np.minimum(1, tt / .01) * np.minimum(1, tt[::-1] / .01)

    two = np.concatenate([chord(110, 261.63, 329.63), chord(98, 246.94, 293.66)])
    m = loop(two, SR, 120)
    assert m["bars"] == 2 and m["notes"] == ["C", "D", "E", "G", "A", "B"] and m["roots"] == ["A", "G"], m
    assert abs(m["tune"]) <= 10 and len(m["weights"]) == 12 and max(m["weights"]) == 1, m      # строй чистых синусов — до −6: оценка
    assert loop(two[:int(2.5 * SR)], SR, 120) is None and loop(np.tile(two, 3)[:10 * SR], SR, 120) is None, \
        "такт с четвертью и пять тактов — не петля"
    # Корень одиночного звука: нота с обертонами — её номер; аккорд, квинта без основного тона и съезд высоты — замер молчит
    one = np.arange(SR) / SR

    def tone(hz):
        return sum(np.sin(2 * np.pi * hz * h * one) / h for h in range(1, 6))

    assert root(tone(220), SR) == 57 and root(tone(261.63), SR) == 60, "ля малой октавы — 57, до первой — 60 (C5 в FL)"
    assert root(tone(220) + tone(261.63), SR) is None, "малая терция — две ноты, корня нет"
    assert root(np.sin(2 * np.pi * 261.63 * one) + np.sin(2 * np.pi * 392 * one), SR) is None, \
        "квинта: общий период — до октавой ниже, а звука там нет"
    assert root(np.sin(2 * np.pi * np.cumsum(220 * 2 ** one) / SR), SR) is None, "высота съезжает на октаву — корня нет"
    print("замер: темп, клэп, хэт с дробью, бочка, 808 со слайдом, долгий суб нотой в такт, части, цвет музыки, ноты петли и корень одиночного звука "
          "на синтетике — в порядке")


def main() -> None:
    p = argparse.ArgumentParser(description="Замер рисунка бита: хэт, клэп, бочка, 808, свинг, части")
    p.add_argument("files", nargs="*", type=Path, metavar="ФАЙЛ", help="звук трека или бита")
    p.add_argument("--bpm", type=float, help="известный темп: для дрилла и рисунков на два такта")
    p.add_argument("--start", type=float, help="с какой секунды взять окно (по умолчанию с 25-й)")
    p.add_argument("--group", default="все", help="метка группы для сводки: чарт, type beat, сцена, наш")
    p.add_argument("--out", type=Path, help="куда дописать замеры (JSON-список)")
    p.add_argument("--table", type=Path, metavar="JSON", help="сводка по файлу замеров")
    p.add_argument("--color", action="store_true", help="ещё и цвет музыки: яркость, регистр, плотность нот, смены аккорда, шум, верха")
    p.add_argument("--loops", nargs="?", const="", metavar="СЛОВО",
                   help="замерить разрешённые петли библиотеки в data/beat_sounds.json; со словом — только петли с ним в имени (только Мак)")
    p.add_argument("--root", action="store_true", help="корневая нота одиночных звуков ФАЙЛ…: номер и имя ноты в FL или «неуверенно»")
    p.add_argument("--selftest", action="store_true", help="проверить замер на синтетическом бите, без demucs")
    a = p.parse_args()
    if a.selftest:
        return selftest()
    if a.table:
        return print(table(json.loads(a.table.read_text("utf-8"))))
    if a.loops is not None:
        return print(loops(a.loops))
    if a.root:
        import librosa
        from .noty import NOTES
        for path in a.files:
            note = root(*librosa.load(path, sr=None))
            print("неуверенно" if note is None else f"{note} ({NOTES[note % 12]}{note // 12})", path.name)
        return
    for path in a.files:
        row = dict(group=a.group, **run(path, a.bpm, a.start, a.color))
        print(json.dumps(row, ensure_ascii=False))
        if a.out:
            rows = json.loads(a.out.read_text("utf-8")) if a.out.exists() else []
            a.out.write_text(json.dumps([r for r in rows if r["file"] != row["file"]] + [row], ensure_ascii=False, indent=1), "utf-8")
    if not a.files:
        p.print_help()


if __name__ == "__main__":
    main()
