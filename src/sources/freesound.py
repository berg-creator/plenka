"""Петли и звуки с Freesound для генератора битов (src/bitgen.py) — только по официальному API.

Берём только CC0 (можно всё) и CC-BY (можно всё, но с подписью автора — она едет
в credits.txt бита). CC-BY-NC — мимо: в боте есть платное. Сайты без API
(Looperman и т. п.) сюда не парсим — их условия этого не разрешают.

Скачивается превью HQ (mp3 ~128–192 кбит/с): для оригинала Freesound требует OAuth
от имени пользователя. Для петли под мелодию этого хватает; оригиналы — следующий шаг.

Каждый звук качается один раз и ложится в библиотеку BITGEN_LIB
(по умолчанию ~/.cache/plenka_bitgen): файл и строка в library.json с автором,
лицензией, ссылкой, темпом, тональностью и числом тактов. Петля, у которой
длина не ложится в целое число тактов, — брак, в библиотеку не попадает.

Ключ — FREESOUND_TOKEN (https://freesound.org/apiv2/apply, «API key»).

    python -m src.sources.freesound --check                       ключ живой, сколько CC0-петель видно
    python -m src.sources.freesound --fetch "dark trap melody" --n 15   найти, скачать, разобрать
    python -m src.sources.freesound --list                        что в библиотеке
    python -m src.sources.freesound --approve 123 --reject 456    одобрить и убрать петли после прослушки
    python -m src.sources.freesound --selftest                    разбор темпа, тональности и лицензий — без сети
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import requests

API = "https://freesound.org/apiv2"
LICENSES = {
    "creativecommons.org/publicdomain/zero": "CC0",
    "creativecommons.org/licenses/by/": "CC-BY",
}
FIELDS = "id,name,username,license,url,previews,duration,tags,ac_analysis"
NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
FLAT = {"Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#"}


def lib_dir() -> Path:
    return Path(os.environ.get("BITGEN_LIB", Path.home() / ".cache/plenka_bitgen"))


def load() -> list[dict]:
    try:
        return json.loads((lib_dir() / "library.json").read_text())
    except (OSError, ValueError):
        return []


def save(lib: list[dict]) -> None:
    lib_dir().mkdir(parents=True, exist_ok=True)
    tmp = lib_dir() / "library.json.tmp"
    tmp.write_text(json.dumps(lib, ensure_ascii=False, indent=1))
    tmp.replace(lib_dir() / "library.json")


def license_of(url: str) -> str | None:
    """Адрес лицензии → CC0 / CC-BY; NC, ND, Sampling+ и прочее — None."""
    url = url or ""
    if "-nc" in url or "/nc" in url or "sampling" in url or "-nd" in url:
        return None
    for part, name in LICENSES.items():
        if part in url:
            return name
    return None


def bpm_from_text(*texts: str) -> float | None:
    """Темп из имени и тегов: «140bpm», «bpm-140», «140 BPM», «_140_»."""
    for t in texts:
        t = str(t).lower()
        m = re.search(r"(?<!\d)(\d{2,3}(?:\.\d)?)\s*-?_?bpm|bpm\s*-?_?(\d{2,3})(?!\d)", t)
        if m:
            v = float(m.group(1) or m.group(2))
            if 60 <= v <= 200:
                return v
    return None


def key_from_text(*texts: str) -> tuple[str | None, bool | None]:
    """Тональность из имени: «Fm», «F#min», «Bb minor», «C major», «_Am_»."""
    for t in texts:
        m = re.search(r"(?<![A-Za-z])([A-G])(#|b)?[ _-]?(min(?:or)?|maj(?:or)?|m)(?![a-z])", str(t))
        if m:
            name = m.group(1) + (m.group(2) or "")
            name = FLAT.get(name, name)
            return name, not m.group(3).lower().startswith("maj")
    return None, None


def analyse(path: Path) -> dict:
    """Свой замер, когда имени и тегов мало: темп (librosa) и тональность (профили Крумхансла)."""
    import librosa
    import numpy as np
    y, sr = librosa.load(str(path), sr=22050, mono=True)
    tempo = float(np.atleast_1d(librosa.beat.beat_track(y=y, sr=sr)[0])[0])
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr).mean(1)
    major = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
    minor = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
    best = max(((np.corrcoef(np.roll(prof, k), chroma)[0, 1], k, is_min)
                for prof, is_min in ((major, False), (minor, True)) for k in range(12)))
    return {"bpm": round(tempo, 1), "key": NAMES[best[1]], "minor": best[2], "key_conf": round(float(best[0]), 2),
            "seconds": round(len(y) / sr, 2)}


def bars_of(seconds: float, bpm: float) -> int | None:
    """Сколько тактов в петле; длина мимо целого числа тактов (±4 %) — не петля."""
    for b in (1, 2, 4, 8, 16):
        if seconds and abs(seconds - b * 4 * 60 / bpm) / seconds < 0.04:
            return b
    return None


def _get(path: str, **params) -> dict:
    token = os.environ.get("FREESOUND_TOKEN")
    if not token:
        raise SystemExit("нет FREESOUND_TOKEN: ключ — на https://freesound.org/apiv2/apply")
    r = requests.get(f"{API}/{path}", params={**params, "token": token}, timeout=30)
    r.raise_for_status()
    return r.json()


def search(query: str, n: int = 15, kind: str = "melody_loop") -> list[dict]:
    flt = 'license:("Creative Commons 0" OR "Attribution") duration:[3 TO 40]'
    if kind.endswith("loop"):
        flt += " tag:loop"
    data = _get("search/text/", query=query, filter=flt, fields=FIELDS, page_size=min(150, n * 3),
                sort="rating_desc")
    return data.get("results", [])


def fetch(query: str, n: int = 15, kind: str = "melody_loop") -> list[dict]:
    lib = load()
    have = {x["id"] for x in lib}
    added = []
    folder = lib_dir() / "freesound"
    folder.mkdir(parents=True, exist_ok=True)
    for s in search(query, n, kind):
        if len(added) >= n:
            break
        if s["id"] in have:
            continue
        lic = license_of(s.get("license", ""))
        if not lic:
            continue
        url = (s.get("previews") or {}).get("preview-hq-mp3")
        if not url:
            continue
        path = folder / f"{s['id']}.mp3"
        if not path.exists():
            r = requests.get(url, timeout=60)
            r.raise_for_status()
            path.write_bytes(r.content)
        ac = s.get("ac_analysis") or {}
        bpm = bpm_from_text(s["name"], " ".join(s.get("tags", [])))
        key, minor = key_from_text(s["name"])
        try:
            me = analyse(path)
        except Exception as e:  # без librosa — только имя и теги
            me = {"seconds": s.get("duration")}
            print(f"  {s['id']}: свой замер не вышел ({e.__class__.__name__})", file=sys.stderr)
        bpm = bpm or ac.get("ac_tempo") or me.get("bpm")
        if not key and ac.get("ac_tonality"):
            key, minor = key_from_text(ac["ac_tonality"].replace(" ", ""))
        if not key and me.get("key_conf", 0) >= 0.6:
            key, minor = me["key"], me["minor"]
        bars = bars_of(float(s.get("duration") or me.get("seconds") or 0), float(bpm)) if bpm else None
        if not bars:
            print(f"  {s['id']} «{s['name']}»: длина не в такт — мимо", file=sys.stderr)
            path.unlink(missing_ok=True)
            continue
        row = {"id": s["id"], "kind": kind, "path": str(path), "title": s["name"], "author": s["username"],
               "license": lic, "url": s["url"], "bpm": round(float(bpm), 1), "key": key, "minor": minor,
               "bars": bars, "tags": s.get("tags", [])[:12], "query": query, "approved": None}
        lib.append(row)
        added.append(row)
        print(f"  + {s['id']} «{s['name']}» — {s['username']} ({lic}), {row['bpm']} BPM, "
              f"{key or '?'}{'m' if minor else ''}, {bars} т.")
    save(lib)
    return added


def selftest() -> None:
    assert license_of("http://creativecommons.org/publicdomain/zero/1.0/") == "CC0"
    assert license_of("https://creativecommons.org/licenses/by/4.0/") == "CC-BY"
    assert license_of("https://creativecommons.org/licenses/by-nc/4.0/") is None
    assert license_of("http://creativecommons.org/licenses/sampling+/1.0/") is None
    assert bpm_from_text("Dark Bells Loop 140bpm Fm") == 140
    assert bpm_from_text("x", "loop bpm-92 piano") == 92
    assert bpm_from_text("Loop 2024") is None
    assert key_from_text("Dark Bells Loop 140bpm Fm") == ("F", True)
    assert key_from_text("piano_Bb_minor_90") == ("A#", True)
    assert key_from_text("guitar C major") == ("C", False)
    assert key_from_text("Drake Type Loop") == (None, None)
    assert bars_of(4 * 4 * 60 / 140, 140) == 4
    assert bars_of(8 * 4 * 60 / 70, 70) == 8
    assert bars_of(7.3, 140) is None
    print("freesound: ок")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--fetch")
    ap.add_argument("--n", type=int, default=15)
    ap.add_argument("--kind", default="melody_loop")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--approve", type=int, nargs="*")
    ap.add_argument("--reject", type=int, nargs="*")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.check:
        data = _get("search/text/", query="trap melody loop",
                    filter='license:"Creative Commons 0" tag:loop', fields="id", page_size=1)
        print(f"ключ живой: CC0-петель «trap melody loop» — {data.get('count')}")
    if a.fetch:
        print(f"добавлено: {len(fetch(a.fetch, a.n, a.kind))}")
    if a.approve or a.reject:
        lib = load()
        for x in lib:
            if x["id"] in (a.approve or []):
                x["approved"] = True
            if x["id"] in (a.reject or []):
                x["approved"] = False
        save(lib)
    if a.list:
        for x in load():
            mark = {True: "✅", False: "🗑", None: "·"}[x.get("approved")]
            print(f"{mark} {x['id']} {x['bpm']} BPM {x.get('key') or '?'}{'m' if x.get('minor') else ''} "
                  f"{x['bars']}т «{x['title']}» — {x['author']} ({x['license']})")


if __name__ == "__main__":
    sys.exit(main())
