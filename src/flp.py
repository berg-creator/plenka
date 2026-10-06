"""ПРОЕКТ FL — готовый .flp бита: открыл двойным щелчком, а каналы, ноты, плейлист и микшер уже на месте.

Владелец 06.10.2026: «может ты сделаешь так чтобы вообще весь готовый проект был у меня. то есть я нажимал
на проект который ты собираешь в фл и там уже все написано и все эффекты лежат на каналах». До этого Мак клал
в «00 - Сегодня» партитуры, звуки, пресеты и записку (`noty.gather`), а проект владелец собирал руками: канал
на партию, звук, партитура в пианоролл, дорожка микшера, цепочка из записки.

Основа — пустой шаблон самого FL 20 с этого же Мака (Templates/Minimal/Empty): его события остаются как есть,
наши встают туда, куда их пишет сам FL. Порядок снят 06.10.2026 с проектов владельца (FL 20.8.3) и шаблонов FL:
ноты паттернов — до каналов, имена паттернов — после первого канала, имя дорожки микшера — перед её событиями,
плагин слота — перед номером слота. Отвергнуто: писать файл с нуля — FL капризен к составу и порядку событий,
а 500 дорожек плейлиста и 127 дорожек микшера с их параметрами пришлось бы выдумывать; и держать шаблон
в репозитории — файл чужой, а нужен только за Маком, где FL и так стоит.

Плагины — из базы плагинов FL (Presets/Plugin database), по файлу .fst на плагин: имя, обёртка и, у родных
плагинов, состояние по умолчанию. Так же устроен пресет дорожки микшера, который владелец открыл 06.10.2026:
эффект лёг на мастер. Эффект из `fx` встаёт в слот с настройками по умолчанию, а числа («срез низа до 150 Гц»)
остаются в записке: состояние у каждого плагина своё и закрытое, выдуманная ручка хуже нетронутой.
Serum у владельца — Audio Unit; его состояние — plist, где поле vstdata — файл .fxp целиком (снято с его
проекта), поэтому пресет бита, и свой тоже, лежит в канале сразу.

Одна партия — один паттерн на весь бит и одна дорожка плейлиста, части подписаны маркерами. Отвергнуто: резать
партию на паттерны по частям — долгие ноты 808 и слайды идут через стык частей, разрез оборвал бы их.

Звука сборка не слышит и FL не запускает: селфтест проверяет только, что файл читается обратно.

    python -m src.flp --selftest        проект читается обратно: темп, каналы, ноты партии, слоты и маршруты микшера
    python -m src.flp --read ФАЙЛ.flp   что в проекте: каналы и звуки, паттерны, клипы, дорожки микшера
"""
from __future__ import annotations

import argparse
import math
import plistlib
import re
import struct
import unicodedata
import wave
from pathlib import Path

from .noty import LIBRARY, N, _notes, _rows, _size, fsc, read_fsc

BASE = Path("/Applications/FL Studio 20.app/Contents/Resources/FL/Data/Templates/Minimal/Empty/Empty.flp")
DB = LIBRARY["KITS"].parent / "Presets" / "Plugin database"
SERUM = "Installed/Generators/AudioUnit/Serum.fst"      # именно Audio Unit: состояние ниже — его plist
SERUM_AU = b"REFXumuaXsfX"  # производитель, вид и плагин в обёртке FL — задом наперёд, как их пишет FL
BAR = 384                   # тиков в такте: PPQ 96, как в шаблоне и в партитурах (noty.TICK)
TRACKS = 500                # дорожек плейлиста в FL 20; клип помнит свою дорожку номером с конца
CLIPS = (("петля", "Петля — на весь бит.wav"), ("петля 2", "Петля 2 — на весь бит.wav"))    # дорожки `noty.loop_track`
MASTER = "весь бит"         # строка fx для мастера
PLUGIN = (201, 212, 203, 155, 128, 213)     # события плагина в .fst: имя, окно, подпись, значок, цвет, состояние
# Чем параметры аудиоклипа (событие 215) отличаются от сэмплера — снято с аудиоклипов проекта владельца
AUDIO = {0: b"\x8c\0\0\0", 11: b"\0", 44: b"\3", 48: bytes(4), 83: b"\1"}
FF = b"\xff" * 4


# --- события -----------------------------------------------------------------

def events(data: bytes) -> list[tuple[int, bytes]]:
    """События файла FL (.flp, .fst): номер и значение. Номер до 64 — байт, до 128 — два, до 192 — четыре,
    дальше — значение с длиной впереди."""
    assert data[:4] == b"FLhd" and data[14:18] == b"FLdt", "не файл FL"
    i, out = 22, []
    while i < len(data):
        e, i = data[i], i + 1
        n = 1 << (e >> 6)
        if e >= 192:
            n = shift = 0
            while True:
                n, shift, i = n | (data[i] & 0x7F) << shift, shift + 7, i + 1
                if data[i - 1] < 0x80:
                    break
        out.append((e, data[i:i + n]))
        i += n
    return out


def pack(ev: list[tuple[int, bytes]], channels: int, kind: int = 0) -> bytes:
    """События обратно в файл; kind — вид файла в заголовке: 0 — проект, 0x30 — пресет плагина."""
    body = b"".join(bytes([e]) + (_size(len(v)) + v if e >= 192 else v) for e, v in ev)
    return b"FLhd" + struct.pack("<IHHH", 6, kind, channels, 96) + b"FLdt" + struct.pack("<I", len(body)) + body


def _text(s: str) -> bytes:
    return (s + "\0").encode("utf-16-le")


def _int(n: int, size: int) -> bytes:
    return n.to_bytes(size, "little")


# --- сборка ------------------------------------------------------------------

def _serum(wrap: list[tuple[int, bytes]], fxp: Path) -> list[tuple[int, bytes]]:
    """Обёртка Serum из базы FL с пресетом внутри. Состояние Audio Unit — plist, где vstdata — файл .fxp целиком;
    запись состояния в обёртке — номер 53, перед plist ноль и его длина. Обёртка не Audio Unit — пресета в ней нет."""
    ev = dict(wrap)
    if SERUM_AU in ev.get(213, b""):
        state = plistlib.dumps({"ProgramNumber": 0, "manufacturer": int.from_bytes(b"XFER", "big"), "vstdata": fxp.read_bytes(),
                                "subtype": int.from_bytes(b"XfsX", "big"), "version": 1, "type": int.from_bytes(b"aumu", "big"),
                                "name": fxp.stem.split(" — ", 1)[-1]}, fmt=plistlib.FMT_BINARY, sort_keys=False)
        ev[213] += struct.pack("<IQIQ", 53, len(state) + 12, 0, len(state)) + state
    return [(e, ev[e]) for e in (201, 212, 213) if e in ev]


def _channel(proto: list[tuple[int, bytes]], i: int, ch: dict) -> list[tuple[int, bytes]]:
    """Канал стойки из шаблонного сэмплера: сэмплер со звуком, Serum с пресетом или аудиоклип."""
    plug, clip, out = dict(ch.get("plugin") or ()), ch.get("clip"), []
    for e, v in proto:
        if e == 64:
            v = _int(i, 2)
        elif e == 21:
            v = bytes([4 if clip else 2 if plug else 0])
        elif e == 203:
            v = _text(ch["name"])
        elif e == 22:
            v = bytes([ch["insert"]])
        elif e in (201, 212) and e in plug:
            v = plug[e]
        elif e == 143 and clip:
            v = _int(2, 4)
        elif e == 215 and clip and len(v) == 158:
            v = bytearray(v)
            for at, b in AUDIO.items():
                v[at:at + len(b)] = b
            v = bytes(v)
        out.append((e, v))
        if e == 128 and 213 in plug:
            out.append((213, plug[213]))
    if ch.get("sound"):
        out.append((196, _text(ch["sound"])))
    if ch.get("root") is not None:
        out.append((135, _int(ch["root"], 4)))
    return out


def _item(idx: int, ln: int, track: int, ends: bytes) -> bytes:
    """Клип плейлиста с начала бита: паттерн (номер от 0x5000) или аудиоклип (номер канала)."""
    return struct.pack("<IHHIHHHHI", 0, 0x5000, idx, ln, TRACKS - 1 - track, 0, 0x78, 0x40, 0x80806440) + ends


def project(base: bytes, bpm: float, channels: list[dict], inserts: dict[int, dict], markers=()) -> bytes:
    """Проект из шаблона FL. channels — каналы стойки по порядку: name, insert (дорожка микшера), у партии — part
    и notes, у сэмплера — sound (путь) и root, у Serum — plugin (события обёртки), у аудиоклипа — sound и clip
    (длина в тиках). Партия — паттерн на весь бит на своей дорожке плейлиста; каналы одной партии — слой.
    inserts — дорожки микшера: name, plugins (файлы .fst по слотам), to (куда вместо мастера). markers — (такт, имя)."""
    ev = events(base)
    first, arr = (next(i for i, (e, _) in enumerate(ev) if e == x) for x in (64, 99))
    head, proto, tail = ev[:first], ev[first:arr], ev[arr:]
    assert sum(e == 64 for e, _ in proto) == 1 and channels, "шаблон — с одним каналом, проект — хотя бы с одним"
    notes, names, items, tracks = [], [], [], []
    for p, part in enumerate(dict.fromkeys(c["part"] for c in channels if c.get("notes")), 1):
        mine = [(i, c["notes"]) for i, c in enumerate(channels) if c.get("notes") and c["part"] == part]
        body = b"".join(_rows(n, i) for i, n in mine)
        notes += [(65, _int(p, 2)), (224, b"".join(sorted((body[k:k + 24] for k in range(0, len(body), 24)), key=lambda r: r[3::-1])))]
        names += [(65, _int(p, 2)), (193, _text(part)), (150, _int(5656904, 4)), (157, FF), (158, FF), (164, bytes(4))]
        items.append(_item(0x5000 + p, math.ceil(max(n.pos + n.ln for _, ns in mine for n in ns) / 16) * BAR, len(tracks), FF * 2))
        tracks.append(part)
    for i, c in enumerate(channels):
        if c.get("clip"):
            items.append(_item(i, c["clip"], len(tracks), struct.pack("<ff", -1, -1)))
            tracks.append(c["name"])
    head = [(e, _int(round(bpm * 1000), 4) if e == 156 else b"\1" if e == 9 else v) for e, v in head]   # 9 — режим песни: Play играет плейлист
    at = next((i for i, (e, _) in enumerate(head) if e == 226), len(head))
    head[at:at] = notes
    rack = []
    for i, c in enumerate(channels):
        rack += _channel(proto, i, c) + (names if not i else [])
    out, ins = [], -1
    for e, v in tail:
        row = inserts.get(ins + (e == 236), {})
        if e == 233:
            v = b"".join(items)
        elif e == 236:
            ins += 1
            out += [(204, _text(row["name"]))] if row.get("name") else []
        elif e == 98 and ins >= 0 and int.from_bytes(v, "little") < len(row.get("plugins") or ()):
            slot = int.from_bytes(v, "little")
            out += [(k, struct.pack("<II", ins, slot) + w[8:] if k == 212 else w)
                    for k, w in events(row["plugins"][slot]) if k in PLUGIN]
        elif e == 235 and row.get("to"):
            v = bytes(i == row["to"] for i in range(len(v)))
        out.append((e, v))
        if e == 233:
            out += [x for bar, name in markers for x in ((148, _int((bar - 1) * BAR, 4)), (205, _text(name)))]
        elif e == 238 and int.from_bytes(v[:4], "little") <= len(tracks):
            out.append((239, _text(tracks[int.from_bytes(v[:4], "little") - 1])))
    return pack(head + rack + out, len(channels))


def read(data: bytes) -> dict:
    """Проект обратно — своим разбором: то, что сверяет селфтест и печатает --read."""
    out = {"bpm": 0.0, "channels": [], "patterns": {}, "clips": [], "markers": [], "inserts": {}}
    text = lambda v: v.decode("utf-16-le").rstrip("\0")
    ch = pat = plug = name = None
    ins = -1
    for e, v in events(data):
        n = int.from_bytes(v, "little") if e < 192 else 0
        if e == 156:
            out["bpm"] = n / 1000
        elif e == 65:
            pat = out["patterns"].setdefault(n, {"name": None, "notes": {}})
        elif e == 224:
            for c, note in _notes(v):
                pat["notes"].setdefault(c, []).append(note)
        elif e == 193:
            pat["name"] = text(v)
        elif e == 64:
            ch = {"name": "", "kind": "сэмплер", "sound": None, "insert": 0, "root": None, "state": b""}
            out["channels"].append(ch)
        elif e == 99:
            ch = None
        elif ch is not None:
            if e == 21:
                ch["kind"] = {0: "сэмплер", 2: "плагин", 4: "аудиоклип"}.get(n, str(n))
            elif e in (203, 196):
                ch["name" if e == 203 else "sound"] = text(v)
            elif e in (22, 135):
                ch["insert" if e == 22 else "root"] = n
            elif e == 213:
                ch["state"] = v
        elif e == 233:
            for k in range(0, len(v), 32):
                _, base, idx, ln, track = struct.unpack("<IHHIH", v[k:k + 14])
                out["clips"].append(("паттерн" if idx > base else "канал", idx - base if idx > base else idx, ln, TRACKS - 1 - track))
        elif e == 148:
            out["markers"].append([n // BAR + 1, ""])
        elif e == 205:
            out["markers"][-1][1] = text(v)
        elif e == 204:
            name = text(v)
        elif e == 236:
            ins += 1
            out["inserts"][ins], name = {"name": name, "slots": {}, "to": []}, None
        elif ins >= 0 and e in (201, 203):
            plug = text(v) or plug
        elif ins >= 0 and e == 98 and plug:
            out["inserts"][ins]["slots"][n], plug = plug, None
        elif ins >= 0 and e == 235:
            out["inserts"][ins]["to"] = [i for i, b in enumerate(v) if b]
    out["inserts"] = {i: x for i, x in out["inserts"].items() if x["name"] or x["slots"] or x["to"] not in ([], [0])}
    return out


# --- проект бита из папки «Сегодня» ---------------------------------------------

def _norm(s: str) -> str:
    return re.sub(r"[^a-zа-яё0-9]", "", unicodedata.normalize("NFC", str(s)).lower())


def _effects(folder: Path) -> dict[str, Path]:
    """Эффекты базы плагинов FL: имя без пробелов и знаков → файл .fst. Из одноимённых — ближний к корню:
    наверху лежит то, что владелец добавил в базу сам, глубже — разложенное FL по видам."""
    out = {}
    for f in sorted(folder.rglob("*.fst"), key=lambda f: (len(f.parts), f.name)) if folder.is_dir() else []:
        if len(_norm(f.stem)) > 2:          # имя из одних знаков совпало бы с любым звеном
            out.setdefault(_norm(f.stem), f)
    return out


def _chain(text: str, effects: dict[str, Path], buses: list[str]) -> tuple[list[Path], str | None]:
    """Цепочка из fx: звено, которое начинается с имени плагина из базы FL, — слот; «в шину …» — маршрут дорожки.
    Остальное («без обработки», «местами, такты 1 и 7», числа настроек) проекту не говорит ничего и остаётся записке."""
    plugins, bus = [], None
    for step in str(text).split("→"):
        low = unicodedata.normalize("NFC", step).strip().lower()
        if low.startswith("в шину"):
            bus = next((b for b in buses if low.startswith("в шину" + b[4:])), bus)
        else:
            plugins += [effects[n] for n in sorted(effects, key=len, reverse=True) if _norm(low).startswith(n)][:1]
    return plugins[:10], bus            # слотов на дорожке микшера FL 20 — десять


def _where(f: Path) -> str:
    """Путь звука, как его пишет сам FL: от папки данных пользователя."""
    home = LIBRARY["KITS"].parent
    return f"%FLStudioUserData%/{f.relative_to(home).as_posix()}" if f.is_relative_to(home) else str(f)


def today(kits: Path, serum: Path, plan: dict, base: Path = BASE, db: Path = DB) -> str:
    """Проект бита — в папку «Сегодня», из того, что в ней уже лежит: партитуры, звуки с именем партии впереди,
    дорожки петли и пресеты. plan — поля паспорта (`noty.build`): title, bpm, parts, tricks, fx, preset.
    Возвращает строку для записки: что в проекте есть и что осталось рукам."""
    if not base.exists():
        return "Проект FL не собран: на этой машине нет FL Studio 20."
    nfc = lambda s: unicodedata.normalize("NFC", str(s))
    scores = [(nfc(f.stem).split(" ", 1)[1], read_fsc(f)) for f in sorted(kits.glob("*.fsc"))]
    wavs = sorted((f for f in kits.iterdir() if f.suffix.lower() == ".wav"), key=lambda f: nfc(f.name))
    presets = sorted(serum.glob("*.fxp"), key=lambda f: nfc(f.name)) if serum.is_dir() else []
    fx = {nfc(k).strip().lower(): str(v) for k, v in plan["fx"].items()} if isinstance(plan.get("fx"), dict) else {}
    own = plan.get("preset") if isinstance(plan.get("preset"), dict) else {}
    wrap = [x for x in events((db / SERUM).read_bytes()) if x[0] in PLUGIN] if (db / SERUM).exists() else None
    buses = [k for k in fx if k.startswith("шина")]
    rows = [p for p, _ in scores] + [k for k, file in CLIPS if (kits / file).exists()] + buses     # дорожки микшера, с первой
    number = {r.lower(): i for i, r in enumerate(rows, 1)}
    channels, silent, roots = [], [], []
    for part, notes in scores:
        label = re.sub(r"[/\\:\0]", " ", part)[:40]             # имя партии впереди файла — как кладёт `noty.lay`
        tag = f"{label[:1].upper()}{label[1:]} — "
        mine = [f for f in wavs if nfc(f.name).startswith(tag)]
        mine = [f for f in mine if nfc(f.name).startswith(tag + "сеть — ")] or mine    # звук из сети лёг — партия играет им
        fxp = sorted((f for f in presets if nfc(f.name).startswith(tag)),           # свой пресет бита — раньше основы
                     key=lambda f: nfc(f.name) != f"{tag}{(own.get(part) or {}).get('имя')}.fxp")
        root = next((int(m[1]) for t in plan.get("tricks") or () if (m := re.match(
            rf"{re.escape(part)}\b.*?корневая нота канала\s*[—–-]?\s*(\d+)", nfc(t), re.I | re.S)) and int(m[1]) < 132), None)
        ch = {"part": part, "notes": notes, "insert": number[part.lower()], "name": part}
        if mine:
            channels += [ch | {"name": f"{part} {k + 1}" if k else part, "sound": _where(f), "root": root} for k, f in enumerate(mine)]
            roots += [f"{part} — {root}"] if root is not None else []
        elif fxp and wrap:
            channels.append(ch | {"plugin": _serum(wrap, fxp[0])})
        else:
            channels.append(ch)
            silent.append(part)
    for key, file in CLIPS:
        if (kits / file).exists():
            with wave.open(str(kits / file)) as w:
                ticks = round(w.getnframes() / w.getframerate() * plan["bpm"] / 60 * 96)
            channels.append({"name": Path(file).stem, "insert": number[key], "sound": _where(kits / file), "clip": ticks})
    effects, drums = _effects(db / "Effects"), next((b for b in buses if "барабан" in b), None)
    inserts, lost = {}, 0
    for i, row in enumerate([MASTER] + rows):
        plugins, bus = _chain(fx.get(row.lower(), ""), effects, buses)
        if row.lower() not in fx and any(row == p for p, _ in scores):      # у барабанов строки в fx нет: их шина — барабанная
            bus = drums
        loaded = []
        for f in plugins:
            try:
                loaded.append(f.read_bytes())
            except OSError:                 # файл базы выгружен в iCloud: фоновому процессу macOS его не отдаст
                lost += 1
        inserts[i] = {"name": row if i else None, "plugins": loaded, "to": number.get(bus) if i and bus != row.lower() else None}
    flat = str(plan.get("parts") or "")
    for _ in range(3):                      # пояснения в скобках — не части: «(петля молчит в тактах 24–25)»
        flat = re.sub(r"\([^()]*\)", "", flat)
    markers = [(int(m[2]), m[1].strip()) for m in re.finditer(r"([^,;]+?)\s+(\d+)\s*[–—-]\s*\d+", flat)]
    name = re.sub(r"[/\\:\0]", " ", str(plan.get("title") or "бит")).strip()[:80] + ".flp"
    data = project(base.read_bytes(), plan["bpm"], channels, inserts, markers)
    back = read(data)
    assert back["bpm"] == plan["bpm"] and len(back["channels"]) == len(channels), "проект записался не так"
    (kits / name).write_bytes(data)
    slots = sum(len(x["plugins"]) for x in inserts.values())
    return (f"Проект FL — «{name}» в этой же папке: каналов {len(channels)}, со звуками и нотами; партии — паттернами на весь бит "
            f"в плейлисте, части — маркерами; дорожки микшера подписаны и разведены по шинам. Эффектов в слотах — {slots}, "
            "все с настройками по умолчанию: числа из «Обработки» выстави сам, эффекты «местами» по тактам не расставлены."
            + (f" Корневая нота канала выставлена: {', '.join(roots)}." if roots else "")
            + (f" Без звука, поставь сам: {', '.join(silent)}." if silent else "")
            + (f" Эффектов не встало (файл базы плагинов не прочитался): {lost}." if lost else "")
            + " На слух проект не проверял никто. Папка «Сегодня» завтра перепишется вместе с проектом и его звуками: "
              "нужен бит дальше — File → Export → Zipped loop package, проект со звуками одним архивом.")


# --- проверка ----------------------------------------------------------------

def _fake() -> bytes:
    """Шаблон в миниатюре — для машин без FL (Actions): события Empty.flp в том же порядке, но дорожек восемь."""
    ev = [(199, b"20.7.0.1702\0"), (156, _int(140000, 4)), (9, b"\0"), (146, FF), (226, bytes(20)),
          (64, bytes(2)), (21, b"\0"), (201, _text("")), (212, bytes(52)), (203, _text("Sampler")), (155, bytes(4)),
          (128, bytes(4)), (0, b"\1"), (22, b"\1"), (215, bytes(158)), (143, _int(3, 4)), (20, b"\0"),
          (99, bytes(2)), (241, _text("Arrangement")), (233, b"")] + [(238, _int(i, 4) + bytes(62)) for i in range(1, 9)]
    for i in range(8):
        ev += [(236, bytes(12)), *((98, _int(s, 2)) for s in range(10)), (235, bytes([i > 0]) + bytes(126)), (154, FF), (147, FF)]
    return pack(ev + [(225, bytes(12)), (133, bytes(4))], 1)


def selftest() -> None:
    import tempfile
    notes = [N(0, 4, 31, 112), N(4, 2.5, 34, 90, pan=-50, fine=30), N(6, 1, 38, 100, slide=True), N(100 * 16, 8, 31)]
    plan = {"title": "А x Б — Проба", "bpm": 120, "parts": "вступление 1–8 (тихо, петля молчит в тактах 3–4), игра 9–104",
            "tricks": ["808 — «Тон D#1»: корневая нота канала — 27 по имени файла", "хэт: корневая нота канала — на слух"],
            "preset": {"мелодия": {"имя": "Свой"}},
            "fx": {"мелодия": "Pro-Q 4: срез низа до 150 Гц → без обработки → в шину музыки", "808": "в шину барабанов и 808",
                   "петля": "Fruity Soft Clipper, слегка → Нет такого плагина → Pro-Q 4",
                   "шина музыки": "Pro-Q 4, фильтр низких частот от 6 кГц", "шина барабанов и 808": "Fruity Soft Clipper — клиппер",
                   "весь бит": "Pro-Q 4 → Fruity Soft Clipper на мастере; местами: Pro-Q 4, такты 1 и 7"}}
    with tempfile.TemporaryDirectory(prefix="flp-") as tmp:
        kits, serum, db = (Path(tmp) / d for d in ("kits", "serum", "db"))
        for d in (kits, serum, db / "Effects" / "Dynamics", db / SERUM.rpartition("/")[0]):
            d.mkdir(parents=True)
        for i, part in enumerate(("808", "хэт", "мелодия"), 1):
            fsc(kits / f"{i:02} {part}.fsc", notes)
        for name in ("808 — Тон D#1.wav", "Хэт — а.wav", "Хэт — б.wav", "Петля — Чужая петля.wav", CLIPS[0][1]):
            with wave.open(str(kits / name), "wb") as w:        # две секунды: на 120 — такт
                w.setnchannels(1), w.setsampwidth(2), w.setframerate(8000), w.writeframes(bytes(32000))
        (serum / "Мелодия — Основа.fxp").write_bytes(b"CcnK-osnova")
        (serum / "Мелодия — Свой.fxp").write_bytes(b"CcnK-svoy")
        wrapper = lambda name, state: pack([(199, b"11.5.5\0"), (28, b"\3"), (201, _text("Fruity Wrapper")), (212, bytes(52)),
                                            (203, _text(name)), (213, state)], 2, 0x30)
        (db / "Effects" / "Pro-Q 4.fst").write_bytes(wrapper("Pro-Q 4", _int(8, 4)))
        (db / "Effects" / "Dynamics" / "Fruity Soft Clipper.fst").write_bytes(pack(
            [(199, b"11.5.5\0"), (201, _text("Fruity Soft Clipper")), (212, bytes(52)), (213, bytes(8))], 2, 0x30))
        (db / SERUM).write_bytes(wrapper("Serum", _int(8, 4) + SERUM_AU))
        for base in [_fake()] + [BASE.read_bytes()] * BASE.exists():        # на Маке — ещё и настоящий шаблон FL
            (Path(tmp) / "Empty.flp").write_bytes(base)
            line = today(kits, serum, plan, Path(tmp) / "Empty.flp", db)
            got = read((kits / "А x Б — Проба.flp").read_bytes())
            ch = got["channels"]
            assert got["bpm"] == 120 and [c["name"] for c in ch] == ["808", "хэт", "хэт 2", "мелодия", "Петля — на весь бит"], ch
            assert [c["kind"] for c in ch] == ["сэмплер"] * 3 + ["плагин", "аудиоклип"] and [c["insert"] for c in ch] == [1, 2, 2, 3, 4]
            assert ch[0]["sound"].endswith("/808 — Тон D#1.wav") and ch[0]["root"] == 27 and ch[1]["root"] is None, ch[:2]
            assert b"CcnK-svoy" in ch[3]["state"] and b"osnova" not in ch[3]["state"], "в Serum — свой пресет бита, а не основа"
            same = sorted(notes)                                    # ноты партии — те же: место, длина, высота, сила, панорама, слайд
            assert got["patterns"][1] == {"name": "808", "notes": {0: same}} and got["patterns"][2]["notes"] == {1: same, 2: same}
            assert got["clips"] == [("паттерн", 1, 101 * BAR, 0), ("паттерн", 2, 101 * BAR, 1), ("паттерн", 3, 101 * BAR, 2),
                                    ("канал", 4, BAR, 3)], got["clips"]
            assert got["markers"] == [[1, "вступление"], [9, "игра"]], got["markers"]
            mix = got["inserts"]
            assert mix[0] == {"name": None, "slots": {0: "Pro-Q 4", 1: "Fruity Soft Clipper"}, "to": []}, mix[0]
            assert mix[1] == {"name": "808", "slots": {}, "to": [6]} and mix[2]["to"] == [6], "808 и барабаны — в свою шину"
            assert mix[3] == {"name": "мелодия", "slots": {0: "Pro-Q 4"}, "to": [5]}, mix[3]
            assert mix[4] == {"name": "петля", "slots": {0: "Fruity Soft Clipper", 1: "Pro-Q 4"}, "to": [0]}, mix[4]
            assert mix[5]["slots"] == {0: "Pro-Q 4"} and mix[6] == {"name": "шина барабанов и 808", "slots": {0: "Fruity Soft Clipper"}, "to": [0]}
            assert "каналов 5" in line and "808 — 27" in line and "Эффектов в слотах — 7" in line, line
        assert "нет FL Studio" in today(kits, serum, plan, Path(tmp) / "нет.flp", db)
        from .noty import _project
        _project(Path(tmp) / "нет.json", kits, serum)           # сбой проекта — строка в записке, а не падение сбора папки
        assert "Проект FL не собрался" in (kits / "о бите.txt").read_text("utf-8")
    print("проект FL: шаблон, каналы со звуком и пресетом, ноты, клипы, маркеры, слоты и шины читаются обратно; сбой — строка в записке")


def main() -> None:
    ap = argparse.ArgumentParser(description="Проект FL Studio из нот, звуков и обработки бита")
    ap.add_argument("--selftest", action="store_true", help="проект читается обратно: темп, каналы, ноты, микшер")
    ap.add_argument("--read", metavar="ФАЙЛ", help="что лежит в проекте .flp")
    args = ap.parse_args()
    if args.selftest:
        selftest()
    elif args.read:
        got = read(Path(args.read).read_bytes())
        print(f"{got['bpm']:g} BPM")
        for i, c in enumerate(got["channels"]):
            print(f"канал {i}: {c['name']} — {c['kind']}, дорожка микшера {c['insert']}"
                  + (f", звук {c['sound']}" if c["sound"] else "") + (f", корневая нота {c['root']}" if c["root"] is not None else "")
                  + (f", состояние плагина {len(c['state'])} байт" if c["state"] else ""))
        for p, pat in got["patterns"].items():
            print(f"паттерн {p}: {pat['name']} — " + ", ".join(f"канал {c}: нот {len(n)}" for c, n in pat["notes"].items()))
        for kind, idx, ln, track in got["clips"]:
            print(f"клип: {kind} {idx}, тактов {ln / BAR:g}, дорожка плейлиста {track + 1}")
        print("маркеры: " + ", ".join(f"{bar} {name}" for bar, name in got["markers"]))
        for i, x in got["inserts"].items():
            print(f"микшер {i}: {x['name'] or ('мастер' if not i else '—')} — слоты: "
                  + (", ".join(f"{s + 1} {p}" for s, p in x["slots"].items()) or "пусто") + f"; идёт в {x['to']}")
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
