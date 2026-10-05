"""СЕТЬ — набор 11 пополняется сам, а бит называет звук адресом.

Владелец 06.10.2026: «пускай утренняя сборка не останавливается на моих скачанных библиотеках, а использует
интернет». До этого дня набор `KITS/11 - Сеть Kit` дважды собирали руками. Здесь то же без рук, двумя путями.

Ночной шаг (`noty --net`, только Мак): следующий источник из `data/net_sources.json` — скачать, отобрать замером,
положить в набор, переписать список имён и замер петель. Источник попадает в список только с лицензией, записанной
дословно в `data/private/set11-sources.md`: шаг ничего не ищет сам, он разбирает очередь, которую собрал человек
или сессия, открывшая страницу лицензии. Пределы — константами: файлов и мегабайт за ночь, потолок всего набора;
упёрся — молчит. Что взято и когда, помнит файл-отметка в самом наборе, а не в копии репозитория: копий на Маке
несколько, набор один.

Звук по адресу (поле паспорта `net`): автор нот умеет искать в сети, но make.py пишет модель — адрес это данные,
а не доверенный путь. Мак качает только прямой WAV и только с адресов, названных в списке полем `from` (узел
и папка, а не один узел: на archive.org рядом с разрешённым лежат слитые платные наборы), без переходов на другой
адрес, с потолком размера, и кладёт файл в «Сегодня» лишь после того же отбора. Чужой адрес, не WAV, тишина или
перегруз — строка в записке, бит от этого не падает: партия играет звуком из `sounds`. Сборка (`noty.problems`)
проверяет форму поля и адрес без сети; в Actions ничего не качается.

Отбор — стандартной библиотекой: помощник на Маке живёт в окружении без numpy. Формат, длина, пик, срезанные
вершины, тишина, шум в паузах; у петли — целые такты по темпу, а ноты — замером `zamer.loop` (питон с librosa,
отдельным процессом). На слух не проверяется ничего — так записка и говорит владельцу.

Отвергнуто: искать источники самому шагу (лицензию должен прочесть тот, кто за неё отвечает); разрешать узел целиком;
перегонять mp3 и ogg в WAV (потерянного верха не вернуть); класть звуки в репозиторий (MusicRadar запрещает
раздавать файлы дальше, в git идут только имена); отправлять имена с Мака самому — автоматической записи в main
с Мака нет, и заводить её без владельца нельзя: шаг меняет `data/beat_sounds.json` в рабочей копии.

    python -m src.noty --net --dry-run   что взял бы ночной шаг, без загрузки звука и записи
    python -m src.noty --net             взять следующий источник в набор 11 (только Мак)
"""
from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import time
import wave
import zipfile
from array import array
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from . import config

MB = 1 << 20
SOURCES = config.DATA / "net_sources.json"
STAGE = config.ROOT / ".cache" / "set11" / "net"        # распакованные кандидаты архива, вне git
MARK = ".сеть.json"                 # отметка в самом наборе: что взято и по каким дням
ZAMER = Path.home() / ".cache" / "whisper-venv" / "bin" / "python"      # питон с librosa: ноты петли

# Пределы ночного шага. Мерится то, что легло в набор; архив источника качается целиком во временную папку
# и удаляется (по частям — вдесятеро медленнее, проба 06.10.2026), ему свой потолок
NIGHT_FILES, NIGHT_MB = 30, 50
KIT_MB = 600                        # набор 11 целиком; дальше шаг молчит
ARCHIVE_MB = 500
SOUND_MB = 30                       # один звук: больше — это не звук, а запись
FAILS = 3                           # ночей подряд источник не скачался — из очереди вон
NET_MAX = 4                         # адресов в паспорте одного бита

# Отбор. Пороги сверены с 345 файлами набора, отобранными руками 06.10.2026 (см. set11-sources.md)
RATE = 44100
SECONDS = (.05, 40)                 # длиннее — кусок записи, а не звук и не петля
QUIET = (-25, -40)                  # пик и средний уровень, дБ: ниже — тишина
CEILING, CLIP_RUN, CLIPS = 32700, 3, 3      # вершина у потолка столько отсчётов подряд — срез; срезов больше — перегруз
PAUSE, NOISE, HISS = -30, -50, 25   # столько окон по 20 мс подряд ровный (в 3 дБ) фон между этими уровнями от пика — шум
BARS = (1, 2, 4, 8)                 # как zamer.LOOP_BARS: тот модуль тянет numpy, которого у помощника нет


def sources() -> list[dict]:
    return json.loads(SOURCES.read_text("utf-8"))["sources"] if SOURCES.exists() else []


def gauge(path: Path) -> dict:
    """Замер файла: частота, биты, длина, пик и средний уровень (дБ), срезанные вершины, ровный фон в паузе (дБ от пика).
    Только PCM 16 и 24 бита: остальное `wave` не читает или FL не ждёт. Считается по старшим 16 битам отсчёта."""
    with wave.open(str(path), "rb") as w:
        ch, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
        raw = w.readframes(w.getnframes())
    if width not in (2, 3):
        raise wave.Error(f"{width * 8} бит")
    raw = raw[:len(raw) - len(raw) % (width * ch)]
    top = bytearray(len(raw) // width * 2)
    top[0::2], top[1::2] = raw[width - 2::width], raw[width - 1::width]
    pcm = array("h", bytes(top))
    if sys.byteorder == "big":
        pcm.byteswap()
    if not pcm:
        raise wave.Error("пустой")
    peak = max(max(pcm), -min(pcm))
    flat = 0
    for chan in ([pcm[c::ch] for c in range(ch)] if peak >= CEILING else []):
        run = 0
        for x in chan:
            if -CEILING < x < CEILING:
                flat, run = flat + (run >= CLIP_RUN), 0
            else:
                run += 1
        flat += run >= CLIP_RUN
    db = lambda x, ref=32768: round(20 * math.log10(max(x, 1e-3) / ref), 1)
    win = max(1, int(rate * .02)) * ch                      # окна по 20 мс, уровень каждого — от пика
    lv = [db(math.sqrt(math.sumprod(c, c) / len(c)), max(peak, 1)) for c in (pcm[i:i + win] for i in range(0, len(pcm) - win + 1, win))]
    hiss = next((round(sum(span) / HISS, 1) for span in (lv[i:i + HISS] for i in range(len(lv) - HISS + 1))
                 if NOISE < min(span) and max(span) < PAUSE and max(span) - min(span) < 3), None)
    return {"rate": rate, "bits": width * 8, "dur": len(pcm) / ch / rate, "peak": db(peak), "flat": flat,
            "rms": db(math.sqrt(math.sumprod(pcm, pcm) / len(pcm))), "hiss": hiss}


def flaws(path: Path, bpm: int | None = None) -> str:
    """Почему файл не годится в набор; пусто — годен. bpm — петля: длина должна ложиться в целые такты.
    ponytail: шум — это полсекунды ровного тихого фона; у звука короче и у петли без пауз он не виден вовсе, а тихую
    ровную ноту после громкого удара отбор примет за шум. Самое тихое окно не годится: у половины отобранных руками
    барабанов хвост обрезан на −35…−45 дБ. Станет мало — спектр паузы (нужен numpy, то есть питон замера)."""
    try:
        g = gauge(path)
    except (wave.Error, EOFError, OSError, ValueError) as e:
        return f"не WAV 16 или 24 бита ({e})"
    if g["rate"] < RATE:
        return f"частота {g['rate']} Гц"
    if not SECONDS[0] <= g["dur"] <= SECONDS[1]:
        return f"длина {g['dur']:.2f} с"
    if g["peak"] < QUIET[0] or g["rms"] < QUIET[1]:
        return f"тишина: пик {g['peak']} дБ, средний уровень {g['rms']} дБ"
    if g["flat"] > CLIPS:
        return f"перегруз: срезанных вершин {g['flat']}"
    if g["hiss"] is not None:
        return f"шум: ровный фон в паузе {g['hiss']} дБ от пика"
    bars = g["dur"] * bpm / 240 if bpm else 1
    if round(bars) not in BARS or abs(bars - round(bars)) > .02:
        return f"петля не в целых тактах: {bars:.2f} при {bpm} BPM"
    return ""


def allowed(url) -> str:
    """Почему по адресу качать нельзя; пусто — можно. Без сети: только форма адреса и список источников."""
    if not isinstance(url, str) or len(url) > 400:
        return "адрес не строка"
    u, path = urlsplit(url), unquote(urlsplit(url).path)
    if u.scheme != "https" or u.query or u.fragment or "@" in u.netloc or not path.lower().endswith(".wav"):
        return "нужен прямой адрес WAV по https, без параметров"
    if ".." in path or "\\" in path or "//" in path:
        return "адрес с переходом по папкам"
    if not any(url.startswith(s["from"]) for s in sources() if s.get("from")):
        return "адрес не из data/net_sources.json"
    return ""


def form(net, parts) -> list[str]:
    """Поле паспорта net глазами сборки: словарь «партия → адрес», партия есть в бите, адрес из списка."""
    if not isinstance(net, dict) or len(net) > NET_MAX:
        return [f"net — словарь «партия → адрес WAV», не больше {NET_MAX} адресов"]
    return [f"net, {part}: " + ("такой партии в compose() нет" if part not in parts else allowed(url))
            for part, url in net.items() if part not in parts or allowed(url)]


def note(net) -> list[str]:
    """Строки записки о звуках по адресу. Что из них легло на самом деле, дописывает Мак в записку папки «Сегодня»."""
    if not isinstance(net, dict) or not net:
        return []
    return ["Звук из сети — Мак скачает его в «00 - Сегодня», если адрес разрешён и файл прошёл отбор (WAV, не тишина, "
            "без перегруза); не прошёл — партия играет звуком из списка выше. На слух звук из сети не проверен никем:",
            *(f"• {part} — {url}" for part, url in net.items()), ""]


def _download(url: str, dest: Path, cap: int, seconds: int = 120) -> Path:
    """Файл по https без переходов на другой адрес и не больше cap байт. curl, а не requests: умеет повтор
    и потолок размера, а у помощника он в PATH."""
    try:
        subprocess.run(["curl", "-sSf", "--proto", "=https", "--retry", "2", "--connect-timeout", "20", "--max-time", str(seconds),
                        "--max-filesize", str(cap), "-o", str(dest), url], check=True, capture_output=True, timeout=seconds * 3 + 60)
        if dest.stat().st_size > cap:
            raise OSError(f"больше {cap // MB} МБ")
    except (OSError, subprocess.SubprocessError) as e:
        dest.unlink(missing_ok=True)
        raise OSError((getattr(e, "stderr", b"") or b"").decode("utf-8", "replace").strip()[-200:] or str(e)) from e
    return dest


def _get(url: str) -> bytes:
    return subprocess.run(["curl", "-sSf", "--proto", "=https", "--max-time", "60", url], check=True, capture_output=True,
                          timeout=90).stdout


def today(net, kits: Path) -> list[str]:
    """Звуки по адресам паспорта → папка «Сегодня». Возвращает, что не легло; оно же и что легло — в записке.
    Не падает: бит без звука из сети остаётся битом."""
    took, missed = [], []
    for part, url in list(net.items())[:NET_MAX] if isinstance(net, dict) else []:
        label = re.sub(r"[/\\:\0]", " ", str(part))[:40]
        why = allowed(url)
        if not why:
            name = re.sub(r"[^\w .()#+-]", " ", unquote(urlsplit(url).path).rsplit("/", 1)[-1])[-80:]
            dst = kits / f"{label[:1].upper()}{label[1:]} — сеть — {name}"
            try:
                why = flaws(_download(url, dst, SOUND_MB * MB))
            except Exception as e:  # noqa: BLE001 — любой сбой загрузки и разбора: пропуск строкой
                why = f"не скачался ({e})"
            if why:
                dst.unlink(missing_ok=True)
            else:
                took.append(f"{label} — {dst.name}")
        if why:
            missed.append(f"{label}: звук из сети пропущен — {why}: {str(url)[:200]}")
    text = ("\n\nЗвуки из сети (отбор — замером, на слух не проверены):\n" + "\n".join(f"• {t}" for t in took) if took else "") \
        + ("\n\nИз сети не легло:\n" + "\n".join(f"• {m}" for m in missed) if missed else "")
    if text and kits.is_dir():
        with (kits / "о бите.txt").open("a", encoding="utf-8") as f:
            f.write(text)
    return missed


def _notes(path: Path, bpm: int) -> int | None:
    """Сколько нот звучит в петле — `zamer.loop`. None — питона с librosa на машине нет или замер не вышел.
    ponytail: процесс на петлю, секунды уходят на импорт librosa; станет тесно — мерить пачкой."""
    code = ("import sys, json, librosa; from src import zamer; y, sr = librosa.load(sys.argv[1], sr=None); "
            "m = zamer.loop(y, sr, float(sys.argv[2])); print(json.dumps(len(m['notes']) if m else 0))")
    try:
        out = subprocess.run([str(ZAMER), "-c", code, str(path), str(bpm)], cwd=config.ROOT, capture_output=True, text=True, timeout=300)
        return int(out.stdout.strip().splitlines()[-1]) if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


def _plan(src: dict, stage: Path) -> list[tuple[str, int, str, int | None]]:
    """Кандидаты источника: путь в нём, размер, папка набора и темп петли. list — оглавление репозитория GitHub,
    файлы качаются по одному; archive — zip целиком, из него в черновик только подходящее под шаблоны."""
    def rule(path: str):
        return next(((r["folder"], int(m["bpm"]) if "bpm" in m.groupdict() else None)
                     for r in src["take"] if (m := re.search(r["match"], path))), None)
    if src.get("list"):
        found = [(e["path"], e.get("size", 0)) for e in json.loads(_get(src["list"]))["tree"] if e.get("type") == "blob"]
    else:
        if not stage.is_dir():
            part = STAGE / f"{src['id']}.part"      # оборванная распаковка не должна сойти за готовый черновик
            shutil.rmtree(part, ignore_errors=True)
            part.mkdir(parents=True)
            with zipfile.ZipFile(_download(src["archive"], STAGE / f"{src['id']}.zip", ARCHIVE_MB * MB, 3600)) as z:
                for i in z.infolist():      # extract сам срезает «..» и корень из имени
                    if not i.is_dir() and "__MACOSX" not in i.filename and i.file_size <= SOUND_MB * MB and rule(i.filename):
                        z.extract(i, part)
            (STAGE / f"{src['id']}.zip").unlink()
            part.rename(stage)
        found = [(p.relative_to(stage).as_posix(), p.stat().st_size) for p in stage.rglob("*") if p.is_file()]
    return sorted((path, size, *rule(path)) for path, size in found if path.lower().endswith(".wav") and rule(path))


def night(dry: bool = False, kit: Path | None = None, srcs: list[dict] | None = None, day: str = "") -> tuple[str, list[Path]]:
    """Один источник очереди — в набор 11, в пределах ночи и набора. Возвращает строку для журнала и что легло.
    Раз в день: вторая попытка за сутки молчит, даже если первая сорвалась, — иначе помощник, заходящий раз
    в десять минут, качал бы архив всю ночь."""
    from . import noty
    kit = kit or noty.LIBRARY["KITS"] / noty.NET.partition("/")[2]
    if not kit.is_dir():
        return "набора 11 на этой машине нет", []
    day = day or time.strftime("%Y-%m-%d")          # сутки Мака, не UTC: иначе ночь в Москве делилась бы на два дня в 03:00
    mark = {"done": {}, "nights": {}, "fails": {}} | (json.loads((kit / MARK).read_text("utf-8")) if (kit / MARK).exists() else {})
    room = min(NIGHT_MB * MB, KIT_MB * MB - sum(f.stat().st_size for f in kit.rglob("*.wav")))
    src = next((s for s in (sources() if srcs is None else srcs) if s.get("take") and s["id"] not in mark["done"]), None)
    if day in mark["nights"] and not dry:
        return "сегодня шаг уже был", []
    if room <= 0 or not src:
        return (f"набор 11 дошёл до {KIT_MB} МБ" if src else "очередь источников пуста") + ": шаг молчит", []

    def save() -> None:
        if not dry:
            (kit / MARK).write_text(json.dumps(mark, ensure_ascii=False, indent=1), "utf-8")
    mark["nights"][day] = [0, 0]
    save()
    stage = STAGE / src["id"]
    try:
        if dry and not src.get("list") and not stage.is_dir():
            return (f"{src['name']}: скачал бы архив {src['archive']} (до {ARCHIVE_MB} МБ, во временную папку) и взял бы "
                    f"до {NIGHT_FILES} файлов и {room // MB} МБ по шаблонам: " + "; ".join(r["match"] for r in src["take"])), []
        plan = _plan(src, stage)
    except Exception as e:  # noqa: BLE001 — сеть, битый архив, чужой формат оглавления: источник подождёт
        mark["fails"][src["id"]] = mark["fails"].get(src["id"], 0) + 1
        if mark["fails"][src["id"]] >= FAILS:
            mark["done"][src["id"]] = f"не скачался {FAILS} ночи подряд"
        save()
        return f"{src['name']}: не скачался ({e})", []
    took, used, bad, rest = [], 0, [], False
    with tempfile.TemporaryDirectory(prefix="set11-") as tmp:
        for path, size, folder, bpm in plan:
            stem = Path(path).stem
            dst = kit / folder / f"{src['name']} - {stem}{f' {bpm} BPM' if bpm else ''}.wav"
            if dst.exists():
                continue
            if folder == "Loops" and not bpm or size > SOUND_MB * MB:
                bad.append(f"{stem}: " + ("петля без темпа" if size <= SOUND_MB * MB else f"больше {SOUND_MB} МБ"))
                continue
            if len(took) >= NIGHT_FILES or used + size > room:
                rest = True
                break
            if not dry:
                try:
                    file = _download(src["from"] + quote(path), Path(tmp) / "звук.wav", SOUND_MB * MB) if src.get("list") else stage / path
                    why = flaws(file, bpm)
                    if bpm and not why:
                        n = _notes(file, bpm)
                        if n is None:           # нет питона замера — виновата машина, а не петля: источник ждёт, черновик цел
                            rest = True
                            bad.append(f"{stem}: ноты петли не замерены — источник ждёт")
                            break
                        why = "" if noty.LOOP_NOTES[0] <= n <= noty.LOOP_NOTES[1] else f"нот {n} — не {noty.LOOP_NOTES[0]}–{noty.LOOP_NOTES[1]}"
                except OSError as e:
                    rest, why = True, f"не скачался ({e})"         # файл попробует следующая ночь
                if why:
                    bad.append(f"{stem}: {why}")
                    if not src.get("list"):
                        file.unlink(missing_ok=True)
                    continue
                dst.parent.mkdir(exist_ok=True)
                shutil.move(file, dst)
            took.append(dst)
            used += size
    mark["nights"][day] = [len(took), used]
    if not rest:
        mark["done"][src["id"]] = day
        if not dry:
            shutil.rmtree(stage, ignore_errors=True)
    save()
    return (f"{src['name']}: {'взял бы' if dry else 'легло'} {len(took)} файлов, {used / MB:.0f} МБ"
            + (", остальное — следующей ночью" if rest else ", источник разобран")
            + "".join(f"\n  + {f.parent.name}/{f.name}" for f in took)
            + (f"\n  не прошли отбор: {len(bad)}" + "".join(f"\n  − {b}" for b in bad) if bad else "")), ([] if dry else took)


def run(dry: bool = False) -> str:
    """Ночной шаг целиком: источник в набор, потом список имён и замер петель в рабочей копии. В main их несёт
    не шаг: автоматической записи в открытый репозиторий с Мака нет."""
    said, took = night(dry)
    if took:
        subprocess.run([sys.executable, "-m", "src.noty", "--sounds"], cwd=config.ROOT, check=True, capture_output=True, timeout=600)
        if any(f.parent.name == "Loops" for f in took) and ZAMER.exists():
            subprocess.run([str(ZAMER), "-m", "src.zamer", "--loops", took[0].name.split(" - ")[0]], cwd=config.ROOT,
                           check=True, capture_output=True, timeout=3600)
        said += f"\nсписок имён переписан: {config.BEAT_SOUNDS} — в main его несёт коммит, не этот шаг"
    return said


def selftest() -> None:
    """Без сети: отбор на синтетике, адреса, пределы ночи. Загрузку подменяет копия файла."""
    from . import noty
    global _download, _get, _notes, STAGE
    def tone(path: Path, seconds: float = 1.0, gain: float = .5, width: int = 2, clip: bool = False, hiss: float = 0.0) -> Path:
        """Синус 220 Гц; clip — усилен вчетверо и срезан; hiss — вторая половина: тишина с шумом этой силы."""
        full, n, out = (1 << (8 * width - 1)) - 1, int(44100 * seconds), bytearray()
        for i in range(n):
            x = gain * math.sin(i * 2 * math.pi * 220 / 44100) * (4 if clip else 1)
            if hiss and i > n // 2:
                x = hiss * (((i * 1103515245 + 12345) >> 8) % 2001 - 1000) / 1000
            out += int(max(-1, min(1, x)) * full).to_bytes(width, "little", signed=True)
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1), w.setsampwidth(width), w.setframerate(44100), w.writeframes(bytes(out))
        return path

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        good = tone(tmp / "годный.wav")
        assert not flaws(good) and not flaws(tone(tmp / "24.wav", width=3)) and gauge(tmp / "24.wav")["bits"] == 24, flaws(good)
        assert "тишина" in flaws(tone(tmp / "тихо.wav", gain=.001)) and "перегруз" in flaws(tone(tmp / "срез.wav", clip=True)), \
            "тишина и срезанные вершины — брак"
        assert "шум" in flaws(tone(tmp / "шум.wav", 2, hiss=.008)) and not flaws(tone(tmp / "пауза.wav", 2, hiss=.00001)), \
            "шум в паузе — брак, чистая пауза проходит"
        assert "не WAV" in flaws(tone(tmp / "8.wav", width=1)) and "длина" in flaws(tone(tmp / "миг.wav", seconds=.01))
        (tmp / "чужое.wav").write_bytes(b"ID3" + bytes(4000))
        assert "не WAV" in flaws(tmp / "чужое.wav") and "не WAV" in flaws(tmp / "нет.wav"), "mp3 под именем wav и пропажа — брак"
        assert not flaws(tone(tmp / "петля.wav", seconds=4), 120) and "тактах" in flaws(tone(tmp / "полтора.wav", seconds=3), 120), \
            "петля — целые такты по темпу из имени"

        ok, alien = "https://freewavesamples.com/files/Kawai-K1r-Aah-C4.wav", "https://example.com/files/Aah.wav"
        assert not allowed(ok) and "net_sources" in allowed(alien) and "net_sources" in allowed(ok.replace("/files/", "/files.example.com/"))
        assert allowed(ok.replace("https", "http")) and allowed(ok + "?x=1") and allowed(ok[:-4] + ".mp3") and allowed(7) \
            and "папкам" in allowed(ok.replace("Kawai", "../../x")) and "папкам" in allowed(ok.replace("Kawai", "%2e%2e/x")), \
            "не https, параметры, не WAV и выход из папки — отказ"
        assert form({"мелодия": ok}, {"мелодия": []}) == [] and "net_sources" in form({"мелодия": alien}, {"мелодия": []})[0] \
            and "партии" in form({"хор": ok}, {"мелодия": []})[0] and form([ok], {}) and form(dict.fromkeys("абвгд", ok), {}), \
            "сборка: чужой адрес, чужая партия и не словарь — брак, разрешённый адрес проходит"
        assert "На слух звук из сети не проверен" in "\n".join(note({"мелодия": ok})) and note(None) == [] == note({})
        for s in sources():
            assert all(s.get(k) for k in ("id", "name", "page", "terms", "taken")), s.get("id")
            assert re.fullmatch(r"https://[^/]+/.+/", s.get("from", "https://x/y/")), f"{s['id']}: from — https, узел и папка, со слэшем в конце"
            assert all(r["folder"] and re.compile(r["match"]) for r in s.get("take", ())), s["id"]
            assert not s.get("take") or (s.get("list") and s.get("from")) or s.get("archive", "").startswith("https://"), s["id"]
            assert "CC BY" not in s["terms"] or (any(mark == f"/{s['name']} - " for mark, _ in noty.CREDIT) and not s.get("from")), \
                f"{s['id']}: CC BY — автора в noty.CREDIT; по адресу из паспорта такой источник не берётся, пока записка не умеет назвать автора"

        real, calls = (_download, _get, _notes, STAGE), []
        fake = {ok: good, ok.replace("Kawai", "Clip"): tmp / "срез.wav"}
        def _download(url, dest, cap, seconds=120):         # noqa: F811 — подмена на время проверки
            calls.append(url)
            if url not in fake and not url.startswith("https://x.test/"):
                raise OSError("404")
            return Path(shutil.copyfile(fake.get(url, good), dest))
        try:
            kits = tmp / noty.TODAY
            kits.mkdir()
            (kits / "о бите.txt").write_text("записка", "utf-8")
            missed = today({"мелодия": ok, "хор": alien, "перк": ok.replace("Kawai", "Clip"), "пэд": ok.replace("Kawai", "Нет")}, kits)
            text = (kits / "о бите.txt").read_text("utf-8")
            assert (kits / "Мелодия — сеть — Kawai-K1r-Aah-C4.wav").exists() and len(list(kits.glob("*.wav"))) == 1, list(kits.iterdir())
            assert len(missed) == 3 and alien not in calls and len(calls) == 3, "чужой адрес не качается вовсе"
            assert text.startswith("записка") and "на слух не проверены" in text and "хор: звук из сети пропущен — адрес не из" in text \
                and "перегруз" in text and "не скачался" in text and "iCloud" not in text, text
            assert today(None, kits) == [] == today({}, kits)

            kit, size = tmp / "11", good.stat().st_size
            kit.mkdir()
            tree = json.dumps({"tree": [{"path": f"Strings/sus/V_{i:02}.wav", "type": "blob", "size": size} for i in range(40)]
                               + [{"path": "Strings/sus/readme.txt", "type": "blob", "size": 9}]}).encode()
            _get = lambda url: tree                          # noqa: E731
            src = [{"id": "проба", "name": "Проба", "from": "https://x.test/", "list": "https://x.test/tree",
                    "take": [{"folder": "Strings", "match": r"^Strings/sus/.*\.wav$"}]}]
            said, none = night(True, kit, src, "2026-10-06")
            assert f"взял бы {NIGHT_FILES} файлов" in said and none == [] and not list(kit.iterdir()), "сухой прогон не пишет ничего"
            said, took = night(False, kit, src, "2026-10-06")
            assert len(took) == NIGHT_FILES == len(list((kit / "Strings").glob("Проба - V_*.wav"))) and "следующей ночью" in said, said
            assert night(False, kit, src, "2026-10-06") == ("сегодня шаг уже был", []), "второй раз за сутки шаг молчит"
            said, took = night(False, kit, src, "2026-10-07")
            assert len(took) == 10 and "источник разобран" in said and "пуста" in night(False, kit, src, "2026-10-08")[0], said
            # Архив: в черновик идёт только подходящее под шаблон, петля — с темпом в имени, в целых тактах и с нотами по замеру
            with zipfile.ZipFile(tmp / "набор.zip", "w") as z:
                for name, file in (("Pack/Loops/Str_120bpm_01.wav", tmp / "петля.wav"), ("Pack/Loops/Str_120bpm_02.wav", tmp / "полтора.wav"),
                                   ("Pack/Loops/Str_120bpm_03.wav", tmp / "срез.wav"), ("Pack/Drums/Beat_120bpm.wav", good), ("Pack/readme.txt", good)):
                    z.write(file, name)
            fake["https://x.test/pack.zip"], STAGE = tmp / "набор.zip", tmp / "черновик"
            _notes = lambda path, bpm: 4                     # noqa: E731 — замер нот живёт в другом питоне
            pack = [{"id": "архив", "name": "Архив", "archive": "https://x.test/pack.zip",
                     "take": [{"folder": "Loops", "match": r"/Loops/[^/]+_(?P<bpm>\d+)bpm_\d+\.wav$"}]}]
            said, took = night(False, kit, pack, "2026-10-08")
            assert [f.name for f in took] == ["Архив - Str_120bpm_01 120 BPM.wav"] and noty.loop_bpm(f"{noty.NET_LOOPS}/{took[0].name}") == 120 \
                and "тактах" in said and "перегруз" in said and "Beat" not in said and not list(STAGE.iterdir()), said
            _notes = lambda path, bpm: 11                    # noqa: E731
            assert "нот 11" in night(False, kit, [pack[0] | {"id": "ноты", "name": "Ноты"}], "2026-10-11")[0], "петля с лишними нотами — мимо"
            _notes = lambda path, bpm: None                  # noqa: E731
            said = night(False, kit, [pack[0] | {"id": "ждёт", "name": "Ждёт"}], "2026-10-12")[0]
            assert "источник ждёт" in said and "следующей ночью" in said and (STAGE / "ждёт").is_dir(), "нет питона замера — петли целы, источник в очереди"
            limits = NIGHT_MB, KIT_MB
            try:
                globals().update(NIGHT_MB=size * 3.5 / MB, KIT_MB=10 ** 6)
                assert len(night(False, kit, [src[0] | {"id": "мб", "name": "Мб"}], "2026-10-09")[1]) == 3, "мегабайты ночи держатся"
                globals().update(NIGHT_MB=limits[0], KIT_MB=size * 43 / MB)
                assert "шаг молчит" in night(False, kit, [src[0] | {"id": "край", "name": "Край"}], "2026-10-10")[0], "потолок набора"
            finally:
                globals().update(NIGHT_MB=limits[0], KIT_MB=limits[1])
        finally:
            _download, _get, _notes, STAGE = real
    print("сеть: отбор бракует тишину, перегруз, шум в паузе, не WAV и петлю не в тактах; адрес с чужого узла — пропуск строкой, "
          "с разрешённого — принят; пределы ночи и набора держатся, второй раз за сутки шаг молчит — в порядке")
