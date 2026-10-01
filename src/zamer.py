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
с ударом). Слайд 808 — оценка: нота, конец которой плавно ушёл от середины на два полутона
и больше. Рисунок на два такта (дрилл) темп не находит — ему нужен `--bpm`; `on_grid` ниже 0,6
или клэп не на шаге 8 значат, что темп угадан неверно. Замер одного файла повторяется
с разбросом: demucs на MPS не детерминирован, у 808 гуляют «разных нот» ±1 и слайды ±0,3.

Отвергнуто: мерить без разделения, по полосам общего микса, — голос и мелодия дают онсеты
в полосе клэпа. Отвергнут librosa.feature.tempo: на рисунке бочки 0-6-10 он ошибался в полтора
раза и на 7%. Отвергнута сумма приростов спектра по частотам как онсет: хвост одного хэта она
читала дробью, а синус 808 в коротком окне — нотами.

Тяжёлое (demucs, librosa) есть только на Маке, как у src/quiz_ai.py, — запуск оттуда же:

    ~/.cache/whisper-venv/bin/python -m src.zamer --selftest             замер на синтетическом бите с известным рисунком
    ~/.cache/whisper-venv/bin/python -m src.zamer ФАЙЛ… --out zamer.json  замерить файлы, дописать в zamer.json
    ~/.cache/whisper-venv/bin/python -m src.zamer ФАЙЛ --bpm 142          темп известен (дрилл, двухтактный рисунок)
    ~/.cache/whisper-venv/bin/python -m src.zamer --table data/beats_zamer.json   сводка: медианы по группам

Чужой звук — только для замера: стемы пишутся во временную папку и удаляются сразу.
"""
from __future__ import annotations

import argparse
import json
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
    «та же частота, фаза идёт дальше» в долях уровня; плавный слайд фазу не сбивает и нотой не считается."""
    import librosa
    from scipy.signal import find_peaks
    x = librosa.stft(y, n_fft=2048, hop_length=2 * HOP)
    f = np.fft.rfftfreq(2048, 1 / SR)
    x = x[(f >= 30) & (f < 200)]
    mag, ph = np.abs(x), np.angle(x)
    dev = np.r_[0, 0, np.abs(x[:, 2:] - mag[:, 1:-1] * np.exp(1j * (2 * ph[:, 1:-1] - ph[:, :-2]))).sum(0)]
    rel = dev / (mag.sum(0) + .05 * np.percentile(mag.sum(0), 95))
    i, _ = find_peaks(rel, height=max(.3, .5 * np.percentile(rel, 99)), distance=round(.08 / FRAME / 2))
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
    )


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


def run(path: Path, hint: float | None = None, start: float | None = None) -> dict:
    """Замер файла: окно → demucs → рисунок; части — по всему файлу."""
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
        out = measure(stem["drums"], stem["bass"], stem["other"], hint)
        out.update(sections(full, sr, out["bpm"], at + out.pop("bar0")))
    return dict(file=path.name, **out)


COLS = (("bpm", "темп"), ("hat_per_bar", "хэт/такт"), ("hat_roll_bars", "такты с дробью"),
        ("hat_trip_bars", "с триолями"), ("hat_dyn", "хэт: разброс силы"), ("hat_pan", "хэт: разброс панорамы"),
        ("swing", "свинг %"), ("snare_per_bar", "клэп/такт"), ("kick_per_bar", "бочка/такт"),
        ("kick_loop", "петля бочки, т."), ("low_per_bar", "ударов низа/такт"),
        ("low_off", "низ мимо 1-й и 3-й доли"), ("b808_per_bar", "808/такт"),
        ("b808_len", "нота 808, 1/16"), ("b808_fill", "808 звучит"), ("b808_pitches", "разных нот 808"),
        ("b808_slides_per_8", "слайдов на 8 т."), ("b808_with_kick", "808 с бочкой"), ("mel_loop", "петля мелодии, т."),
        ("mel_voices", "нот разом"), ("mel_octaves", "октав занято"), ("mel_mute_bars", "такты без мелодии"),
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
        grids = [r["hat_grid"] for r in rs]
        out.append(f"{'сетка хэта':26} " + ", ".join(f"{g} — {grids.count(g)}" for g in sorted(set(grids), key=grids.count, reverse=True)))
        spots = [" и ".join(str(k) for k in r["snare_steps"]) or "нет" for r in rs]
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
    from scipy.signal import resample_poly
    sec = sections(resample_poly(drums.sum(0) + bass + other, 1, 4), 11025, 150, r["bar0"])
    assert sec["intro_bars"] == 2 and sec["drops"] == 0 and sec["map"] == "...." + "#" * 32 + "....", sec
    print("замер: темп, клэп, хэт с дробью, бочка, 808 со слайдом и части на синтетическом бите — в порядке")


def main() -> None:
    p = argparse.ArgumentParser(description="Замер рисунка бита: хэт, клэп, бочка, 808, свинг, части")
    p.add_argument("files", nargs="*", type=Path, metavar="ФАЙЛ", help="звук трека или бита")
    p.add_argument("--bpm", type=float, help="известный темп: для дрилла и рисунков на два такта")
    p.add_argument("--start", type=float, help="с какой секунды взять окно (по умолчанию с 25-й)")
    p.add_argument("--group", default="все", help="метка группы для сводки: чарт, type beat, сцена, наш")
    p.add_argument("--out", type=Path, help="куда дописать замеры (JSON-список)")
    p.add_argument("--table", type=Path, metavar="JSON", help="сводка по файлу замеров")
    p.add_argument("--selftest", action="store_true", help="проверить замер на синтетическом бите, без demucs")
    a = p.parse_args()
    if a.selftest:
        return selftest()
    if a.table:
        return print(table(json.loads(a.table.read_text("utf-8"))))
    for path in a.files:
        row = dict(group=a.group, **run(path, a.bpm, a.start))
        print(json.dumps(row, ensure_ascii=False))
        if a.out:
            rows = json.loads(a.out.read_text("utf-8")) if a.out.exists() else []
            a.out.write_text(json.dumps([r for r in rows if r["file"] != row["file"]] + [row], ensure_ascii=False, indent=1), "utf-8")
    if not a.files:
        p.print_help()


if __name__ == "__main__":
    main()
