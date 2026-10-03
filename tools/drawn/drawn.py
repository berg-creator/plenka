"""Рисованный ролик одной папкой: кадры FLUX, оживление LTX, листы самопроверки и бит — общие для любого ролика.

Ролик skleyka-3 (сентябрь 2026) делался скриптами в ~/.cache/imggen/keef/: слова кадров сидели
в ветках case у run.sh и anim.sh, и второй ролик значил бы копию обоих скриптов с чужими правками
внутри. Теперь скрипт один, а всё своё у ролика — в drawn.json его папки: слова кадров, движение
клипов, якоря, сиды. Правила рисовки и известный брак — в prompts/drawn.md, читать до первого кадра.

Почему не модуль src/: здесь запускаются модели, которые стоят только на Маке владельца (FLUX.2 klein
через mflux, LTX 2.5, ACE-Step), а конвейеру в Actions они не нужны. Сам drawn.py — на стандартной
библиотеке и идёт любым python3; PIL, numpy и cv2 нужны только помощникам рядом (stab.py, freeze.py,
merge.py, motion.py, half.sh) — их зовёт окружение ~/.cache/imggen/.venv.

make не делает всё разом намеренно: большая часть брака родом из картинок, а клип — восемь минут Мака.
Первый запуск рисует кадры и останавливается, второй — оживляет, кладёт листы и собирает ролик.
Черновик владельцу уходит третьим шагом, руками и после листов: отправку без проверки владелец
25.09.2026 уже ловил на трёх руках в кадре.

Папка ролика (весов и картинок в репозитории нет, папка живёт в ~/.cache/imggen/<ролик>/):
    drawn.json           слова кадров и клипов; образец — example.json рядом
    style.png            кадр-образец стиля; <кадр>.png — кадры, hr/ — они же в размере клипа
    anim/<кадр>.mp4      клипы; прошлые попытки кадров и клипов — в old/ рядом
    build/               сценарий <id>.json, дубли 1.ogg…, pics/<кадр>.mp4 — что идёт в ролик
    check/               листы самопроверки

Запуск:
    python tools/drawn/drawn.py make ПАПКА                 чего ещё нет: кадры → стоп; клипы, листы, сборка
    python tools/drawn/drawn.py shot ПАПКА 1-1 [--seed 8]  кадр заново, ~1 мин
    python tools/drawn/drawn.py anim ПАПКА 1-1 [--seed 11] клип заново, ~8 мин
    python tools/drawn/drawn.py check ПАПКА [1-1 …]        листы кадров и замер движения
    python tools/drawn/drawn.py beat ИМЯ "настроение" --bpm 128   свой бит в data/private/audio/
    python tools/drawn/drawn.py make ПАПКА --dry-run       какие команды ушли бы, без моделей
    python tools/drawn/drawn.py --selftest                 образец читается, якоря на месте, лист собирается
"""
from __future__ import annotations

import argparse
import fcntl
import json
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
CACHE = Path.home() / ".cache"
FLUX = CACHE / "imggen/.venv/bin/mflux-generate-flux2-edit"
PY = CACHE / "imggen/.venv/bin/python"
LTX = CACHE / "ltx/engine/.venv/bin/ltx-2-mlx"
LTX_MODEL = CACHE / "ltx/ltx-2.5-mlx-q8"
ACE_PY = CACHE / "acestep/repo/.venv/bin/python"

# 864×1536: в 576×1024 глаз — несколько пикселей, LTX пересобирает его в каждом кадре, и зрачки плывут
W, H = 864, 1536
# больше 49 кадров в 864×1536 Маку не по памяти (25.09.2026 падали 57 и 65, плитки не спасают)
FRAMES = 49
# 7742 прошёл проверку глаз: на 7741 один глаз закрывался раньше другого
SEED_SHOT, SEED_ANIM = 7, 7742
# якорь конца слабый: композицию держит, движение пускает; та же картинка с силой 1.0 — стоп-кадр
END = 0.4
# клип LTX выходит 832×1536 (864 режется по центру): продолжение с последнего кадра клипа идёт
# с "size": [832, 1536], иначе кадр растянут на 4% и на склейке скачок
SHEET = (0, 12, 24, 30, 36, 48)
FULL, PART = 920, 780  # плитка листа: полный кадр и область; больше читающий всё равно ужмёт
# ponytail: без поля look клип режется на три полосы — лица, руки, ноги; у сцены с двумя людьми
# мелкое движение одного тонет в полосе, тогда области персонажей называет look в drawn.json
BANDS = {"верх": [0, 0, 1, 0.4], "середина": [0, 0.3, 1, 0.75], "низ": [0, 0.6, 1, 1]}


def words(text: str, shared: dict) -> str:
    """Подставляет {ИМЯ} из vars. Переменные ссылаются друг на друга, поэтому по кругу."""
    for _ in range(5):
        new = text
        for name, value in shared.items():
            new = new.replace("{" + name + "}", value)
        if new == text:
            break
        text = new
    if left := re.search(r"\{[A-Z_]+\}", text):
        raise SystemExit(f"в drawn.json нет переменной {left[0]}")
    return text


def shot_cmd(doc: dict, folder: Path, key: str, seed: int | None = None) -> list[str]:
    frame = doc["frames"][key]
    return ["caffeinate", "-dims", str(FLUX), "--model", "flux2-klein-4b", "-q", "8",
            "--image-paths", *[str(folder / ref) for ref in frame["refs"]],
            "--width", str(W), "--height", str(H), "--steps", "4",
            "--seed", str(seed or frame.get("seed", SEED_SHOT)),
            "--prompt", words(frame["prompt"], doc.get("vars", {})),
            "--output", str(folder / f"{key}.png"), "--no-metadata"]


def anchors(clip: dict, key: str) -> list[list]:
    """Кадры-опоры клипа: [кадр, номер, сила]. По умолчанию свой кадр первым и он же слабо в конце."""
    if "anchors" in clip:
        return clip["anchors"]
    end = clip.get("end", END)
    return [[key, 0, 1.0]] + ([[key, clip.get("frames", FRAMES) - 1, end]] if end else [])


def anim_cmd(doc: dict, folder: Path, key: str, seed: int | None = None) -> list[str]:
    anim, shared = doc["anim"], doc.get("vars", {})
    clip = anim["clips"][key]
    w, h = clip.get("size", (W, H))
    cmd = ["caffeinate", "-dims", str(LTX), "generate", "--model", str(LTX_MODEL), "--distilled", "--low-ram",
           "-W", str(w), "-H", str(h), "-f", str(clip.get("frames", FRAMES)), "--frame-rate", "24",
           "-s", str(seed or clip.get("seed", SEED_ANIM))]
    for name, at, force in anchors(clip, key):
        cmd += ["-i", str(folder / "hr" / f"{name}-{w}.png"), str(at), str(force)]
    prompt = ", ".join(words(part, shared) for part in (anim["base"], clip["move"], clip.get("rules", anim["rules"])))
    return cmd + ["-p", prompt, "-o", str(folder / "anim" / f"{key}.mp4")]


def busy(cmd: list[str]) -> None:
    """FLUX и LTX вместе в память Мака не помещаются (13 и 44 ГБ): второй запуск ждёт первого.

    Замок — flock, а не файл-метка: метку упавший запуск оставлял, и соседний ждал её час (25.09.2026).
    """
    with open(CACHE / "imggen/.busy", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        subprocess.run(cmd, check=True)


def keep(path: Path) -> None:
    """Прежний кадр или клип — в old/: одобренное владельцем новая попытка не затирает."""
    if path.exists():
        (path.parent / "old").mkdir(exist_ok=True)
        path.rename(path.parent / "old" / f"{path.stem}-{time.strftime('%d%H%M%S')}{path.suffix}")


def shot(doc: dict, folder: Path, key: str, seed: int | None, dry: bool) -> None:
    cmd = shot_cmd(doc, folder, key, seed)
    if dry:
        return print(shlex.join(cmd))
    keep(folder / f"{key}.png")  # mflux не перезаписывает, а пишет рядом _1.png
    busy(cmd)


def anim(doc: dict, folder: Path, key: str, seed: int | None, dry: bool) -> None:
    cmd, clip = anim_cmd(doc, folder, key, seed), doc["anim"]["clips"][key]
    if dry:
        return print(shlex.join(cmd))
    (folder / "hr").mkdir(exist_ok=True)
    w, h = clip.get("size", (W, H))
    for name, _, _ in anchors(clip, key):
        src, big = folder / f"{name}.png", folder / "hr" / f"{name}-{w}.png"
        if not big.exists() or big.stat().st_mtime < src.stat().st_mtime:
            # чужой размер режется по центру, а не сжимается: сжатый кадр не совпадёт с клипом, скачок на шве
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-vf",
                            f"scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,crop={w}:{h}", big], check=True)
    out = folder / "anim" / f"{key}.mp4"
    out.parent.mkdir(exist_ok=True)
    keep(out)
    busy(cmd)
    if clip.get("stab"):  # без якоря конца LTX ведёт камеру сам, а наезд владелец запретил
        subprocess.run([PY, HERE / "stab.py", out], check=True)


def sheet(clip: Path, box: list[float], out: Path, size: int) -> None:
    """Лист 3×2: кадры SHEET, вырезана область box (доли кадра), плитка не больше size."""
    count = int(subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v", "-show_entries",
                                "stream=nb_read_frames", "-of", "csv=p=0", clip],
                               capture_output=True, text=True, check=True).stdout.strip().rstrip(","))
    picks = sorted({min(i, count - 1) for i in SHEET})
    x0, y0, x1, y1 = box
    look = (f"select='{'+'.join(f'eq(n,{i})' for i in picks)}',crop=iw*{x1 - x0}:ih*{y1 - y0}:iw*{x0}:ih*{y0},"
            f"scale={size}:{size}:force_original_aspect_ratio=decrease,tile=3x{-(-len(picks) // 3)}")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", clip, "-vf", look, "-frames:v", "1", "-q:v", "3", out], check=True)


def check(doc: dict, folder: Path, keys: list[str]) -> None:
    """Листы каждого клипа: полный кадр и области персонажей; рядом — замер движения по области.

    Смотрится то, что идёт в ролик (build/pics), а не сырой клип: шов и заморозка кладутся после оживления.
    Шаг около нуля в хвосте — клип стоит; «шаг мин» около нуля — повтор кадра (бывает после half.sh).
    """
    (folder / "check").mkdir(exist_ok=True)
    for key in keys:
        clip = next((p for p in (folder / "build/pics" / f"{key}.mp4", folder / "anim" / f"{key}.mp4") if p.exists()), None)
        if not clip:
            print(f"{key}: клипа нет")
            continue
        sheet(clip, [0, 0, 1, 1], folder / "check" / f"{key}-кадр.jpg", FULL)
        for name, box in (doc["anim"]["clips"].get(key, {}).get("look") or BANDS).items():
            sheet(clip, box, folder / "check" / f"{key}-{name}.jpg", PART)
            if PY.exists():
                print(f"{key} {name}: ", end="", flush=True)
                subprocess.run([PY, HERE / "motion.py", clip, *map(str, box)])
    print(f"листы — {folder / 'check'}: у каждого человека считать руки, ноги и ступни, смотреть зрачки (prompts/drawn.md)")


def make(doc: dict, folder: Path, dry: bool) -> None:
    drawn = [key for key in doc["frames"] if not (folder / f"{key}.png").exists()]
    for key in drawn:  # порядок файла — порядок отрисовки: правка кадра стоит после самого кадра
        shot(doc, folder, key, None, dry)
    if drawn and not dry:
        return print(f"нарисованы {', '.join(drawn)} — посмотреть каждый до оживления и запустить make снова")
    for key in doc["anim"]["clips"]:
        clip, pic = folder / "anim" / f"{key}.mp4", folder / "build/pics" / f"{key}.mp4"
        if not clip.exists():
            anim(doc, folder, key, None, dry)
        if not pic.exists() and not dry:
            pic.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(clip, pic)
    if dry:
        return
    check(doc, folder, list(doc["anim"]["clips"]))
    build = folder / "build"
    script = next(iter(sorted(build.glob("*.json"))), None)
    if not script or not any(build.glob("1.*")):
        return print(f"сборка ждёт сценарий {build}/<id>.json и дубли 1.ogg…")
    cmd = [str(REPO / ".venv/bin/python"), "-m", "src.reels", "--preview", str(script), "--voice", str(build)]
    if Path(cmd[0]).exists():
        subprocess.run(cmd, cwd=REPO, check=True)
    print("после листов — черновик владельцу:\n  " + shlex.join(cmd + ["--draft"]))


def selftest() -> None:
    doc = json.loads((HERE / "example.json").read_text(encoding="utf-8"))
    folder, seen = Path("/ролик"), {"style"}
    for key, frame in doc["frames"].items():
        cmd = shot_cmd(doc, folder, key)
        assert "{" not in cmd[cmd.index("--prompt") + 1], key
        # кадр рисуется по образцам, которые к его очереди уже есть: правка идёт после своего кадра
        assert all(Path(ref).stem in seen for ref in frame["refs"]), (key, frame["refs"])
        seen.add(key)
    seed = lambda cmd: cmd[cmd.index("--seed") + 1]
    assert seed(shot_cmd(doc, folder, "3-2")) == "8" and seed(shot_cmd(doc, folder, "3-2", 11)) == "11"
    for key, clip in doc["anim"]["clips"].items():
        assert all(name in doc["frames"] and at < FRAMES for name, at, _ in anchors(clip, key)), key
        assert "{" not in anim_cmd(doc, folder, key)[-3], key
    assert anchors({}, "1-1") == [["1-1", 0, 1.0], ["1-1", 48, 0.4]]
    assert anchors({"end": 0}, "1-1") == [["1-1", 0, 1.0]]
    assert anchors({"end": 0.7, "frames": 41}, "1-1")[1] == ["1-1", 40, 0.7]
    assert anchors(doc["anim"]["clips"]["4-1"], "4-1")[1] == ["4-2", 32, 1.0]
    more = dict(doc, anim=dict(doc["anim"], clips={"4-1b": {"move": "keeps rapping", "anchors": [["4-1end", 0, 1.0]], "size": [832, 1536]}}))
    cmd = anim_cmd(more, folder, "4-1b")
    assert cmd[cmd.index("-W") + 1] == "832" and "/ролик/hr/4-1end-832.png" in cmd, cmd[:20]
    # 3-2 идёт своим шагом: общие правила без «slow steady motion», иначе мужики входят как в воде
    assert "slow steady motion" in anim_cmd(doc, folder, "1-1")[-3] and "slow steady motion" not in anim_cmd(doc, folder, "3-2")[-3]
    try:
        words("{STYLE} и {NOPE}", doc["vars"])
        raise AssertionError("неизвестная переменная прошла")
    except SystemExit:
        pass
    with tempfile.TemporaryDirectory() as tmp:
        clip, out = Path(tmp) / "anim" / "1-1.mp4", Path(tmp) / "check" / "1-1-верх.jpg"
        clip.parent.mkdir()
        # d=1 обязателен: источник lavfi без длины бесконечен (30.09.2026 — 560 ГБ диска)
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"testsrc=d=1:s={W}x{H}:r=24", "-pix_fmt", "yuv420p", clip], check=True)
        check({"anim": {"clips": {}}}, Path(tmp), ["1-1", "9-9"])
        size = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0", out],
                              capture_output=True, text=True, check=True).stdout.strip().rstrip(",")
        width, height = map(int, size.split(","))
        assert width == 3 * PART and height < PART, size  # 24 кадра — три плитки (0, 12, 23) в один ряд
        keep(clip)
        assert not clip.exists() and len(list((clip.parent / "old").glob("1-1-*.mp4"))) == 1
    print("selftest drawn: ок")


def main() -> int:
    if sys.argv[1:2] == ["beat"]:  # бит идёт окружением ACE-Step, свои флаги разбирает beat.py
        return subprocess.run([ACE_PY, HERE / "beat.py", *sys.argv[2:]]).returncode
    parser = argparse.ArgumentParser(description="Рисованный ролик: кадры, оживление, листы самопроверки")
    parser.add_argument("what", nargs="?", choices=["make", "shot", "anim", "check"], help="что сделать")
    parser.add_argument("folder", nargs="?", type=Path, help="папка ролика с drawn.json")
    parser.add_argument("keys", nargs="*", help="кадры: 1-1 3-2 …")
    parser.add_argument("--seed", type=int, help="другой сид для этой попытки")
    parser.add_argument("--dry-run", action="store_true", help="показать команды, модели не запускать")
    parser.add_argument("--selftest", action="store_true", help="образец читается, якоря на месте, лист собирается")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        return 0
    if not args.what or not args.folder:
        parser.error("нужны действие и папка ролика")
    folder = args.folder.expanduser().resolve()
    doc = json.loads((folder / "drawn.json").read_text(encoding="utf-8"))
    if args.what == "make":
        make(doc, folder, args.dry_run)
    elif args.what == "check":
        check(doc, folder, args.keys or list(doc["anim"]["clips"]))
    else:
        for key in args.keys or parser.error("какой кадр?"):
            (shot if args.what == "shot" else anim)(doc, folder, key, args.seed, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
