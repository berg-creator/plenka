"""ЭКЗАМЕН СВЕДЕНИЯ — сведение бота против изданных релизов, по цифрам.

Зачем. Владелец не слушает пробы: студийных мониторов нет, а телефон и ноутбук
врут в низе и в верхе. Жалобу «голос не лежит в бите, пластиковый» слухом
не проверить, поэтому сведение сверяется с тем, что уже издано: 447 треков
СЛЕПОЙ ПРОСЛУШКИ разделены demucs на голос и музыку (кэш Мака,
~/.cache/plenka-quiz-ai/sep/htdemucs), и сумма двух дорожек — это и есть релиз,
эталон баланса, тембра, динамики и ширины.

Два прохода на одних и тех же треках (выборка — фиксированным seed, треки,
где голоса нет, пропускаются):

1. «Не испорти готовое»: голос и музыка одной длины — путь «из одного проекта»,
   бот должен отдать почти то же, что было.
2. «Сделай из сырого»: голос портится известной порчей — громкость −10…+6 дБ,
   колокол ±6 дБ на 250 Гц, полка ±5 дБ выше 5 кГц, — а к биту в конце 3 с тишины:
   длины расходятся больше SAME_PROJECT, и сведение идёт путём по умолчанию.
   Мерится, насколько бот вернул голос к эталону и насколько далеко он был
   испорченным.

Отклонение от эталона — по каждому треку, итог — медиана и квартили по трекам:
систематическая ошибка — та, у которой медиана заметна, а квартили по одну
сторону нуля. demucs разделяет не идеально, поэтому до десятых дБ под эталон
не подгоняем.

Эталоны — превью Deezer, MP3 128 кбит/с: декодер поднимает пик и режет верх,
поэтому мастер бота перед сравнением проходит тот же кодек (CODEC) — иначе след
кодека читался бы ошибкой сведения. По таким эталонам сверяются баланс до ~15 кГц,
громкость, динамика и место голоса; «воздух», пик и ширину по ним не настраиваем
(владелец, 03.10.2026). Отдельной строкой — пик мастера после AAC 128 кбит/с
к порогу AAC_PEAK: это не сравнение с эталоном, а ответ, переживёт ли мастер площадку.
AAC — кодировщиком Apple (aac_at): встроенный в ffmpeg сам выбрасывает пик, на мастере
с −2,0 dBTP дал +3,3, когда Apple −2,3 и MP3 −2,3, — мерился бы он, а не мастер.
Рядом — пик MP3 320 к потолку мастера: это файл, который бот отдаёт человеку и в канал,
и потолок должен держать он, а не WAV (09.10.2026: у 30 сведений из 80 MP3 был выше потолка).

Почему не прослушка вслепую и не Matchering: первое требует ушей и мониторов,
которых нет, второе — нового пакета и одного референса, а тут 40 релизов
и только ffmpeg. Почему не сравнивать сразу с медианой релизов, как TONE: медиана
не скажет, испортил ли бот конкретный трек, — эталон у каждого трека свой.

Работает только на Маке: кэш разделённых треков локальный, в Actions его нет.

    python -m src.ekzamen --tracks 40                 оба прохода, 4 сведения разом
    python -m src.ekzamen --tracks 40 --was СТАРЫЙ.json   было → стало после правки
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import random
import re
import statistics
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from . import skleyka
from .reels import VOICE_CODEC
from .skleyka import FORMAT, TONE, loudness, stereo, tone

SEP = Path.home() / ".cache" / "plenka-quiz-ai" / "sep" / "htdemucs"
# Громкость стема голоса ниже SILENT LUFS — голоса в треке нет (у ~27 из 447).
SILENT = -35.0
SPOIL_GAIN, SPOIL_BELL, SPOIL_SHELF, SPOIL_PAD = (-10.0, 6.0), 6.0, 5.0, 3.0
CODEC = {".mp3": "libmp3lame", ".m4a": "aac_at"}
AAC_PEAK = -1.0
# Полосы SPLIT, где место голосу решает разборчивость слов: 500–1000, 1000–2000, 2000–4000 Гц.
POCKET = (3, 4, 5)
PASSES = {"gotovoe": "не испорти готовое", "syroe": "сделай из сырого"}


def pick(count: int, seed: int) -> list[str]:
    """count треков с голосом, всегда одни и те же при том же seed."""
    ids = sorted(p.name for p in SEP.iterdir() if (p / "vocals.wav").exists())
    random.Random(seed).shuffle(ids)
    chosen = []
    for track in ids:
        if len(chosen) == count:
            break
        if loudness(SEP / track / "vocals.wav")[0] >= SILENT:
            chosen.append(track)
    return chosen


def _r128(path: Path) -> tuple[float, float, float]:
    """(громкость LUFS, разброс LRA LU, пик к громкости PLR дБ)."""
    err = skleyka._stderr("-i", path, "-af", "ebur128=peak=true:framelog=quiet")
    level = float(re.findall(r"I:\s+(-?[\d.]+) LUFS", err)[-1])
    lra = float(re.findall(r"LRA:\s+([\d.]+) LU", err)[-1])
    return level, lra, float(re.findall(r"Peak:\s+(-?[\d.]+) dBFS", err)[-1]) - level


def attack(path: Path) -> float:
    """Атака голоса, дБ: 90-й процентиль роста уровня по 10 мс за 20 мс внутри строк.
    Быстрый компрессор срезает именно фронты согласных, и слово звучит «пластиком»."""
    level = skleyka._envelope(path)
    rate = skleyka.ENV_RATE
    rises = sorted(level[i] - level[i - 2] for a, b in skleyka._lines(level)
                   for i in range(max(2, int(a * rate)), int(b * rate)))
    return rises[int(0.9 * (len(rises) - 1))]


def coded(path: Path, suffix: str) -> Path:
    """Звук после кодека 128 кбит/с — рядом, с расширением suffix; меряется прямо он."""
    dest = path.with_suffix(suffix)
    skleyka._ffmpeg("-i", path, "-c:a", CODEC[suffix], "-b:a", "128k", dest)
    return dest


def pocket(voice: Path, beat: Path) -> dict[int, float]:
    """Голос к биту по полосам POCKET, дБ: медиана разницы уровней середины по окнам
    0,1 с внутри строк голоса. Доля окон, где бит громче голоса целиком (masked),
    места в полосе не видит: +3,6 → +4,4 % у неё — шум. В бите эталона место голосу
    уже сделано, поэтому плюс у бота — глубина его провала поверх релиза."""
    over, under = (skleyka._bands(path, f"{skleyka.MID},") for path in (voice, beat))
    sung = skleyka._sung(skleyka._lines(skleyka._envelope(voice)), min(len(over[0]), len(under[0])), 0.1)
    return {b: statistics.median(over[b][i] - under[b][i] for i in sung) for b in POCKET}


def exam(track: str, spoil: bool, root: Path, seed: int) -> dict[str, float]:
    """Одно сведение и его отклонения от эталона: {метрика: бот − эталон}.
    Метрики «испорчено: …» — то же для испорченного голоса до бота."""
    vocal, beat = SEP / track / "vocals.wav", SEP / track / "no_vocals.wav"
    out = root / ("syroe" if spoil else "gotovoe") / track
    work = out / "work"
    work.mkdir(parents=True, exist_ok=True)
    feed_vocal, feed_beat = vocal, beat
    if spoil:
        rng = random.Random(f"{seed}:{track}")
        feed_vocal, feed_beat = out / "vocal-in.wav", out / "beat-in.wav"
        skleyka._ffmpeg("-i", vocal, "-af", f"volume={rng.uniform(*SPOIL_GAIN):.2f}dB,"
                        f"equalizer=f=250:t=o:w=1:g={rng.uniform(-SPOIL_BELL, SPOIL_BELL):.2f},"
                        f"highshelf=f=5000:g={rng.uniform(-SPOIL_SHELF, SPOIL_SHELF):.2f}", *VOICE_CODEC, feed_vocal)
        skleyka._ffmpeg("-i", beat, "-af", f"apad=pad_dur={SPOIL_PAD}", *VOICE_CODEC, feed_beat)
    with open(out / "log.txt", "w") as log, contextlib.redirect_stdout(log):
        skleyka.mix(feed_vocal, feed_beat, out)
    ref = skleyka._sum([(vocal, 0.0), (beat, 0.0)], out / "ref.wav")

    # Голос в сведении — после райдера и с шинами отзвука и дилея той громкости,
    # что ставит mix: доля шины к сухому голосу по EBU R128.
    ride, look = work / "vocal-ride.wav", skleyka.STYLES["чисто"]
    level = loudness(ride)[0]
    wets = [(work / f"{name}.wav", level + 20 * math.log10(look[name][1]) - loudness(work / f"{name}.wav")[0])
            for name in ("reverb", "delay") if name in look]
    heard = skleyka._sum([(ride, 0.0), *wets], work / "voice-mix.wav")

    got, want = _r128(heard), _r128(vocal)
    beat_level = loudness(beat)[0]
    result = {
        "баланс голоса к биту, дБ": got[0] - loudness(work / "beat.wav")[0] - (want[0] - beat_level),
        "разброс голоса LRA, LU": got[1] - want[1],
        "  разброс после компрессии": _r128(work / "vocal-comp.wav")[1] - want[1],
        "пик к громкости голоса PLR, дБ": got[2] - want[2],
        # Бит громче голоса больше чем на 2 дБ — доля окон 0,4 с с голосом, как считает райдер.
        "бит перекрывает голос, % окон": skleyka.masked(skleyka._gaps(heard, work / "beat.wav")[1])
                                         - skleyka.masked(skleyka._gaps(vocal, beat)[1]),
    }
    ours, theirs, edges = pocket(heard, work / "beat.wav"), pocket(vocal, beat), skleyka.SPLIT
    result |= {f"голос к биту {edges[b - 1]}–{edges[b]} Гц, дБ": ours[b] - theirs[b] for b in POCKET}
    fronts, spread = attack(vocal), skleyka.swing(vocal)
    result |= {"атака голоса, дБ за 20 мс": attack(heard) - fronts,
               "  атака после компрессии": attack(work / "vocal-comp.wav") - fronts,
               "размах голоса внутри строк, дБ": skleyka.swing(heard) - spread,
               "  размах после компрессии": skleyka.swing(work / "vocal-comp.wav") - spread,
               "  размах после райдера, без эха": skleyka.swing(ride) - spread}
    ours, theirs = tone(work / "vocal.wav", FORMAT), tone(vocal, FORMAT)
    result |= {f"тембр голоса {f} Гц, дБ": ours[f] - theirs[f] for f in TONE}
    result["тембр голоса, среднее |откл.|"] = statistics.fmean(abs(ours[f] - theirs[f]) for f in TONE)
    if spoil:
        spoiled = tone(feed_vocal, FORMAT)
        result |= {"испорчено: баланс, дБ": loudness(feed_vocal)[0] - beat_level - (want[0] - beat_level),
                   "испорчено: тембр голоса, среднее |откл.|":
                       statistics.fmean(abs(spoiled[f] - theirs[f]) for f in TONE)}
    raw = out / "skleyka.wav"
    master = coded(raw, ".mp3")
    ours, theirs = tone(master, FORMAT), tone(ref, FORMAT)
    result |= {f"тембр сведения {f} Гц, дБ": ours[f] - theirs[f] for f in TONE}
    got, want = _r128(master), _r128(ref)
    result |= {"разброс сведения LRA, LU": got[1] - want[1], "пик к громкости сведения PLR, дБ": got[2] - want[2],
               "  пик к громкости без MP3": _r128(raw)[2] - want[2],
               f"пик после AAC 128 к порогу {AAC_PEAK:+.0f} dBTP, дБ (не к эталону; выше нуля — запаса нет)":
                   loudness(coded(raw, ".m4a"))[1] - AAC_PEAK,
               f"пик MP3 320 к потолку {skleyka.CEILING:+.0f} dBTP, дБ (не к эталону; выше нуля — потолок не держится)":
                   skleyka._coded(raw) - skleyka.CEILING}
    (corr, loss), (corr0, loss0) = stereo(master), stereo(ref)
    result |= {"корреляция каналов": corr - corr0, "потеря в моно, LU": loss - loss0,
               "бит после места голосу, LU": loudness(work / "beat.wav")[0] - loudness(feed_beat)[0]}
    return result


def _safe(args: tuple[str, bool, Path, int]) -> tuple[str, bool, dict | str]:
    try:
        return args[0], args[1], exam(*args)
    except Exception as error:  # один сломанный трек не должен ронять экзамен
        return args[0], args[1], f"{type(error).__name__}: {error}"


def summary(results: dict[str, dict[str, dict]]) -> dict[str, dict[str, list[float]]]:
    """{проход: {метрика: [q1, медиана, q3]}} по трекам."""
    table = {}
    for name, tracks in results.items():
        metrics = next(iter(tracks.values()), {})
        table[name] = {m: statistics.quantiles([row[m] for row in tracks.values()], n=4) for m in metrics}
    return table


def main() -> int:
    parser = argparse.ArgumentParser(description="ЭКЗАМЕН СВЕДЕНИЯ: бот против изданных релизов")
    parser.add_argument("--tracks", type=int, default=40, help="сколько треков с голосом взять")
    parser.add_argument("--seed", type=int, default=28, help="выборка треков и порча — одни и те же при том же seed")
    parser.add_argument("--jobs", type=int, default=4, help="сведений разом")
    parser.add_argument("--out", type=Path, default=Path(tempfile.gettempdir()) / "plenka-ekzamen",
                        help="папка для сведений и итога")
    parser.add_argument("--was", type=Path, metavar="ФАЙЛ", help="итог прошлого экзамена — напечатать «было → стало»")
    args = parser.parse_args()
    if not SEP.exists():
        parser.error(f"нет {SEP}: экзамен идёт только на Маке, где разделены треки СЛЕПОЙ ПРОСЛУШКИ")
    tracks = pick(args.tracks, args.seed)
    results: dict[str, dict[str, dict]] = {name: {} for name in PASSES}
    with ProcessPoolExecutor(args.jobs) as pool:
        jobs = [(track, spoil, args.out, args.seed) for spoil in (False, True) for track in tracks]
        for track, spoil, got in pool.map(_safe, jobs):
            if isinstance(got, str):
                print(f"  {track}: не свелось — {got}")
                continue
            results["syroe" if spoil else "gotovoe"][track] = got
    table = summary(results)
    was = json.loads(args.was.read_text())["итог"] if args.was else {}
    for name, rows in table.items():
        print(f"\n{PASSES[name]} ({len(results[name])} треков): бот − эталон, медиана [квартили]")
        for metric, (q1, mid, q3) in rows.items():
            before = was.get(name, {}).get(metric)
            print(f"  {metric}: " + (f"{before[1]:+.2f} → " if before else "") + f"{mid:+.2f} [{q1:+.2f}…{q3:+.2f}]")
    report = args.out / "itog.json"
    report.write_text(json.dumps({"итог": table, "треки": results}, ensure_ascii=False, indent=1))
    print(f"\nитог: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
