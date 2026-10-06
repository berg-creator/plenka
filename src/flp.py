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
эффект лёг на мастер. Числа из `fx` («срез низа до 150 Гц») остаются в записке: состояние у каждого плагина своё
и закрытое, выдуманная ручка хуже нетронутой. Настройка берётся только готовой — пресетом FL по имени
(Plugin presets/Effects, «Плагин «Пресет»»): состояние плагина целиком, как его сохранил сам FL.

Владелец о первом проекте, 06.10.2026: «бит в целом тихий. петля совсем плоха и не в тему, бас слабый как
и бочка. саунд дизайна не увидел никакого». Отсюда три вещи. Уровни дорожек, ограничитель на мастере, перегруз
и отсечка 808 — по шести чужим проектам FL под его рефы (data/private/биты/проекты-из-сети/разбор.md); числа
и откуда они — у констант LEVEL, DRIVE, LIMIT. Эффект «местами» — звено `fx` с «в тактах …» на конце: клип
автоматизации на mix слота, 100% в названных тактах и 0% в остальных, ступенями — так же mix слота Gross Beat
ведёт демо-проект из поставки FL («Gross Beat - Mix level»). Канал клипа целиком берётся из шаблона FL
(SFX transitions), меняются имя, номер и точки. Ячейка Gross Beat («Momentary: 1/2 Speed») — два числа в начале
состояния: порядок «ячейка времени, ячейка громкости, доля времени, доля громкости» — это порядок параметров
плагина в тех же демо (Time slot — 0, Time mix — 2, Volume mix — 3). Отвергнуто: автоматизировать ручки самих
плагинов — номер ручки у каждого свой и снимается только с примера, а mix слота один на всех.

Проект, сохранённый владельцем в «Сегодня», утром не стирается (`keep`): папка переезжает рядом, пути звуков
в проекте переписываются, остальное — байт в байт.
Serum у владельца — Audio Unit; его состояние — plist, где поле vstdata — файл .fxp целиком (снято с его
проекта), поэтому пресет бита, и свой тоже, лежит в канале сразу.

Одна партия — один паттерн на весь бит и одна дорожка плейлиста, части подписаны маркерами. Отвергнуто: резать
партию на паттерны по частям — долгие ноты 808 и слайды идут через стык частей, разрез оборвал бы их.

Звука сборка не слышит и FL не запускает: селфтест проверяет только, что файл читается обратно.

    python -m src.flp --selftest        проект читается обратно: темп, каналы, ноты партии, слоты, уровни и маршруты микшера,
                                        пресет и ячейка Gross Beat, клип автоматизации; сохранённая папка переезжает с путями
    python -m src.flp --read ФАЙЛ.flp   что в проекте: каналы и звуки, паттерны, клипы, дорожки микшера
"""
from __future__ import annotations

import argparse
import math
import plistlib
import re
import shutil
import struct
import subprocess
import time
import unicodedata
import wave
from pathlib import Path

from .noty import GM_DRUM, LIBRARY, N, SAMPLED, _notes, _rows, _size, fsc, read_fsc

BASE = Path("/Applications/FL Studio 20.app/Contents/Resources/FL/Data/Templates/Minimal/Empty/Empty.flp")
DB = LIBRARY["KITS"].parent / "Presets" / "Plugin database"
SERUM = "Installed/Generators/AudioUnit/Serum.fst"      # именно Audio Unit: состояние ниже — его plist
SERUM_AU = b"REFXumuaXsfX"  # производитель, вид и плагин в обёртке FL — задом наперёд, как их пишет FL
BAR = 384                   # тиков в такте: PPQ 96, как в шаблоне и в партитурах (noty.TICK)
TRACKS = 500                # дорожек плейлиста в FL 20; клип помнит свою дорожку номером с конца
CLIPS = (("петля", "Петля — на весь бит.wav"), ("петля 2", "Петля 2 — на весь бит.wav"))    # дорожки `noty.loop_track`
MASTER = "весь бит"         # строка fx для мастера
PLUGIN = (201, 212, 203, 155, 128, 213)     # события плагина в .fst: имя, окно, подпись, значок, цвет, состояние
# Шаблон из поставки FL 20 с клипами автоматизации (та же сборка, что у Empty): оттуда канал клипа целиком
AUTO = BASE.parents[2] / "Utility" / "SFX transitions" / "SFX transitions.flp"
# Пресеты плагинов: свои владельца раньше заводских
PRESETS = (LIBRARY["KITS"].parent / "Presets" / "Plugin presets" / "Effects", BASE.parents[3] / "Patches" / "Plugin presets" / "Effects")
# Уровни дорожек микшера, % фейдера: 100 — 0 дБ, предел FL — 125. Сняты 06.10.2026 с шести чужих проектов FL под рефы
# владельца (разбор.md, «Что общего», п. 4): 808 поднят в 5 из 6 — фейдер 111–125% (проекты 01, 03, 06), мелодия ниже
# него в 3 из 6 — 50–71%, 57%, 75–100%. Взята пара проекта 03 (пересборка New Tank): 125 и 57. Барабаны — 100: клэп, снейр
# и хэт стоят там на 88–125%, в обе стороны; бочка «вдвое тише» (45–50%) — только где она лежит под каждой нотой 808
# и сжимает его дорожку, а у нас рисунок бочки свой.
LEVEL = {"808": 125, "музыка": 57}
# Перегруз 808: Fruity Soft Clipper, порог 23 из 127 и post 111 из 160 — дорожка 808 проекта 02 (пересборка Stop Breathing),
# слот 4 (перегруз на 808 — в 2 проектах из 6). Состояние плагина — эти два числа: в заводском Default.fst — 100 и 128.
DRIVE = ("fruitysoftclipper", struct.pack("<II", 23, 111))
# Ограничитель на мастере — в 4 проектах из 6; Fruity Limiter последним слотом — в 03 и 06, там он по умолчанию.
# Владелец: «бит в целом тихий» — поэтому заводской пресет FL «Max loudness» (gain выше умолчания), а не умолчание.
LIMIT = ("fruitylimiter", "Max loudness")
# «в тактах 23, 31–32 и 59.4» в конце звена fx: такт, такты подряд, доля такта (59.4 — четвёртая)
BARS = re.compile(r"\bв тактах\s+((?:\d+(?:\.[1-4])?(?:\s*[–—-]\s*\d+(?:\.[1-4])?)?(?:\s*,\s*|\s+и\s+)?)+)$")
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


def _body(ev: list[tuple[int, bytes]]) -> bytes:
    return b"".join(bytes([e]) + (_size(len(v)) + v if e >= 192 else v) for e, v in ev)


def pack(ev: list[tuple[int, bytes]], channels: int, kind: int = 0) -> bytes:
    """События обратно в файл; kind — вид файла в заголовке: 0 — проект, 0x30 — пресет плагина."""
    body = _body(ev)
    return b"FLhd" + struct.pack("<IHHH", 6, kind, channels, 96) + b"FLdt" + struct.pack("<I", len(body)) + body


def repath(data: bytes, old: str, new: str) -> bytes | None:
    """Пути звуков проекта (событие 196) — из папки old в папку new, остальное байт в байт: заголовок файла прежний,
    кроме длины. None — файл не разбирается туда-обратно байт в байт (другая версия FL, битый файл): такой не трогаем."""
    try:
        ev = events(data)
        if _body(ev) != data[22:]:
            return None
        swap = lambda s: s.replace(f"/{unicodedata.normalize('NFD', old)}/", f"/{new}/").replace(f"/{unicodedata.normalize('NFC', old)}/", f"/{new}/")
        body = _body([(e, swap(v.decode("utf-16-le")).encode("utf-16-le") if e == 196 else v) for e, v in ev])
    except (AssertionError, IndexError, UnicodeError):
        return None
    return data[:18] + struct.pack("<I", len(body)) + body


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
        elif e == 132 and ch.get("cut"):        # группа отсечки «сам себя»: новая нота глушит хвост прошлой — в 4 проектах из 6
            v = struct.pack("<HH", i + 1, i + 1)
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


def _curve(proto: bytes, spans: list[tuple[float, float]], total: float) -> bytes:
    """Точки клипа автоматизации (событие 234): 0 весь бит и 1 в отрезках spans, ступенями. Место точки — сдвиг от прошлой
    в долях-четвертях, скачок — две точки с нулевым сдвигом: так mix слота Gross Beat ведёт демо из поставки FL
    («ANNA MIA», клип «Gross Beat - Mix level»). Шапка до числа точек и хвост после них — из шаблона, как есть."""
    pts, at = [(0.0, 0.0)], 0.0
    for a, b in spans:
        a, b = min(a, total), min(b, total)
        if b > a >= at:
            pts += [(a - at, 0.0), (0.0, 1.0), (b - a, 1.0), (0.0, 0.0)]
            at = b
    pts.append((total - at, 0.0))
    old = int.from_bytes(proto[17:21], "little")
    return proto[:17] + _int(len(pts), 4) + b"".join(
        struct.pack("<ddf4s", dx, y, 0, b"\0\0\0\2" if k else bytes(4)) for k, (dx, y) in enumerate(pts)) + proto[21 + 24 * old:]


def project(base: bytes, bpm: float, channels: list[dict], inserts: dict[int, dict], markers=(), auto=None) -> bytes:
    """Проект из шаблона FL. channels — каналы стойки по порядку: name, insert (дорожка микшера), у партии — part
    и notes, у сэмплера — sound (путь), root и cut (отсечка «сам себя»), у Serum — plugin (события обёртки), у аудиоклипа —
    sound и clip (длина в тиках). Партия — паттерн на весь бит на своей дорожке плейлиста; каналы одной партии — слой.
    inserts — дорожки микшера: name, plugins (файлы .fst по слотам), to (куда вместо мастера), level (фейдер, %),
    auto — {слот: (имя клипа, отрезки в долях от начала бита)}: клип автоматизации на mix слота, своя дорожка плейлиста.
    auto — события канала-клипа из шаблона FL; без него клипов нет. markers — (такт, имя)."""
    ev = events(base)
    first, arr = (next(i for i, (e, _) in enumerate(ev) if e == x) for x in (64, 99))
    head, proto, tail = ev[:first], ev[first:arr], ev[arr:]
    assert sum(e == 64 for e, _ in proto) == 1 and channels, "шаблон — с одним каналом, проект — хотя бы с одним"
    notes, names, items, tracks, ends = [], [], [], [], [0]
    for p, part in enumerate(dict.fromkeys(c["part"] for c in channels if c.get("notes")), 1):
        mine = [(i, c["notes"]) for i, c in enumerate(channels) if c.get("notes") and c["part"] == part]
        body = b"".join(_rows(n, i) for i, n in mine)
        notes += [(65, _int(p, 2)), (224, b"".join(sorted((body[k:k + 24] for k in range(0, len(body), 24)), key=lambda r: r[3::-1])))]
        names += [(65, _int(p, 2)), (193, _text(part)), (150, _int(5656904, 4)), (157, FF), (158, FF), (164, bytes(4))]
        ends.append(math.ceil(max(n.pos + n.ln for _, ns in mine for n in ns) / 16) * BAR)
        items.append(_item(0x5000 + p, ends[-1], len(tracks), FF * 2))
        tracks.append(part)
    for i, c in enumerate(channels):
        if c.get("clip"):
            ends.append(c["clip"])
            items.append(_item(i, c["clip"], len(tracks), struct.pack("<ff", -1, -1)))
            tracks.append(c["name"])
    head = [(e, _int(round(bpm * 1000), 4) if e == 156 else b"\1" if e == 9 else v) for e, v in head]   # 9 — режим песни: Play играет плейлист
    at = next((i for i, (e, _) in enumerate(head) if e == 226), len(head))
    head[at:at] = notes
    rack = []
    for i, c in enumerate(channels):
        rack += _channel(proto, i, c) + (names if not i else [])
    # Клипы автоматизации: канал вида 5 после каналов стойки, запись привязки (227) — после нот и записей 226, как пишет
    # сам FL; цель — 0x2000 + дорожка × 64 + слот, параметр 0x1F01 — mix слота (номер 1 из события 225 под признаком 0x1F)
    clips = [(ins, slot, *x) for ins, row in sorted(inserts.items()) for slot, x in sorted((row.get("auto") or {}).items())] if auto else []
    for iid, (ins, slot, name, spans) in enumerate(clips, len(channels)):
        rack += [(e, _int(iid, 2) if e == 64 else _text(name) if e == 203 else _curve(v, spans, max(ends) / 96) if e == 234 else v)
                 for e, v in auto]
        head.append((227, struct.pack("<HHIHHII", 0, iid, 0, 0x1F01, 0x2000 + ins * 64 + slot, 8, 0x1D5)))
        items.append(_item(iid, max(ends), len(tracks), struct.pack("<ff", -1, -1)))
        tracks.append(name)
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
        elif e == 225:                          # записи по 12 байт: параметр, 0x1F, дорожка × 64 + слот, значение; 192 — фейдер
            v = bytearray(v)
            for k in range(0, len(v) - 11, 12):
                level = inserts.get(int.from_bytes(v[k + 6:k + 8], "little") >> 6 & 127, {}).get("level")
                if v[k + 4] == 192 and level:
                    v[k + 8:k + 12] = _int(round(128 * level), 4)       # 12800 — 100%
            v = bytes(v)
        out.append((e, v))
        if e == 233:
            out += [x for bar, name in markers for x in ((148, _int((bar - 1) * BAR, 4)), (205, _text(name)))]
        elif e == 238 and int.from_bytes(v[:4], "little") <= len(tracks):
            out.append((239, _text(tracks[int.from_bytes(v[:4], "little") - 1])))
    return pack(head + rack + out, len(channels) + len(clips))


def read(data: bytes) -> dict:
    """Проект обратно — своим разбором: то, что сверяет селфтест и печатает --read."""
    out = {"bpm": 0.0, "channels": [], "patterns": {}, "clips": [], "markers": [], "inserts": {}, "links": []}
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
            ch = {"name": "", "kind": "сэмплер", "sound": None, "insert": 0, "root": None, "state": b"", "cut": 0, "on": []}
            out["channels"].append(ch)
        elif e == 99:
            ch = None
        elif ch is not None:
            if e == 21:
                ch["kind"] = {0: "сэмплер", 2: "плагин", 4: "аудиоклип", 5: "автоматизация"}.get(n, str(n))
            elif e in (203, 196):
                ch["name" if e == 203 else "sound"] = text(v)
            elif e in (22, 135):
                ch["insert" if e == 22 else "root"] = n
            elif e == 213:
                ch["state"] = v
            elif e == 132:
                ch["cut"] = int.from_bytes(v[:2], "little")
            elif e == 234:                      # отрезки, где клип держит 1, — в долях от начала
                at, was = 0.0, (0.0, 0.0)
                for k in range(int.from_bytes(v[17:21], "little")):
                    dx, y = struct.unpack_from("<dd", v, 21 + 24 * k)
                    at += dx
                    ch["on"] += [(was[0], at)] if was[1] == y == 1 and dx else []
                    was = (at, y)
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
            out["inserts"][ins], name = {"name": name, "slots": {}, "to": [], "level": 100}, None
        elif ins >= 0 and e in (201, 203):
            plug = text(v) or plug
        elif ins >= 0 and e == 98 and plug:
            out["inserts"][ins]["slots"][n], plug = plug, None
        elif ins >= 0 and e == 235:
            out["inserts"][ins]["to"] = [i for i, b in enumerate(v) if b]
        elif e == 225:
            for k in range(0, len(v) - 11, 12):
                i = int.from_bytes(v[k + 6:k + 8], "little") >> 6 & 127
                if v[k + 4] == 192 and i in out["inserts"]:
                    out["inserts"][i]["level"] = round(int.from_bytes(v[k + 8:k + 12], "little", signed=True) / 128)
        elif e == 227 and len(v) == 20:         # привязка клипа автоматизации: канал клипа, параметр, цель
            _, clip, _, what, to, _, _ = struct.unpack("<HHIHHII", v)
            out["links"].append({"clip": clip, "mix": what == 0x1F01, "insert": to >> 6 & 127, "slot": to & 63} if to & 0x2000
                                else {"clip": clip, "mix": False, "insert": None, "slot": None})
    out["inserts"] = {i: x for i, x in out["inserts"].items()
                      if x["name"] or x["slots"] or x["to"] not in ([], [0]) or x["level"] != 100}
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


def _spans(text: str) -> list[tuple[float, float]]:
    """«… в тактах 23, 31–32 и 59.4» на конце звена → отрезки в долях-четвертях от начала бита, по порядку и слитые.
    Только на конце и только этими словами: «(такты 1–12)» и «первая доля тактов 4, 6, 8» в старых паспортах —
    слова для владельца, такты там считались от начала восьмёрки."""
    m, out = BARS.search(text.strip()), []
    for a, b in re.findall(r"(\d+(?:\.\d)?)(?:\s*[–—-]\s*(\d+(?:\.\d)?))?", m[1]) if m else []:
        (x, _), (y, w) = (((int(bar) - 1) * 4 + int(beat or 1) - 1, 1 if beat else 4)
                          for bar, _, beat in (a.partition("."), (b or a).partition(".")))
        if 0 <= x < y + w:
            out.append((float(x), float(y + w)))
    merged = []
    for a, b in sorted(out):
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
        else:
            merged.append((a, b))
    return merged


def _chain(text: str, effects: dict[str, Path], buses: list[str]) -> tuple[list[dict], str | None]:
    """Цепочка из fx: звено, которое начинается с имени плагина из базы FL, — слот; «в шину …» — маршрут дорожки.
    Сразу за именем «Пресет» или «Пресет: ячейка» — пресет FL (`_preset`, `_cell`); «в тактах …» на конце звена —
    где эффект включён (`_spans`). Остальное («без обработки», числа настроек) остаётся записке."""
    steps, bus = [], None
    for step in str(text).split("→"):
        raw = unicodedata.normalize("NFC", step).strip()
        if raw.lower().startswith("в шину"):
            bus = next((b for b in buses if raw.lower().startswith("в шину" + b[4:])), bus)
        elif key := next((n for n in sorted(effects, key=len, reverse=True) if _norm(raw).startswith(n)), None):
            m = re.match(r"([^«»]*)«([^«»]+)»", raw)
            preset, _, cell = m[2].partition(":") if m and _norm(m[1]) == key else ("", "", "")
            steps.append({"key": key, "file": effects[key], "preset": preset.strip(), "cell": cell.strip(), "spans": _spans(raw)})
    return steps[:10], bus              # слотов на дорожке микшера FL 20 — десять


def _preset(key: str, name: str, roots=PRESETS) -> bytes | None:
    """Состояние плагина из пресета FL: «Plugin presets/Effects/<плагин>/…/<имя>.fst». key — имя плагина без пробелов
    и знаков, как в `_effects`. Старые заводские пресеты (FL 3–8) пишут имена не в UTF-16 — из файла берётся одно состояние."""
    for root in roots:
        for d in sorted(d for d in root.iterdir() if d.is_dir() and _norm(d.name) == key) if root.is_dir() else ():
            for f in sorted(d.rglob("*.fst")):
                if _norm(f.stem) == _norm(name) and (data := _bytes(f)):
                    return next((v for e, v in reversed(events(data)) if e == 213), None)
    return None


def _cell(state: bytes, name: str) -> bytes | None:
    """Gross Beat: ячейка банка по имени — выбранной. После шапки в состоянии 72 ячейки, 36 времени и 36 громкости:
    имя с байтом длины, 23 байта, число точек, точки по 24 байта, хвост 20 — проход кончается ровно в конце состояния
    (сверено на банках Momentary, Patterns, Repeater, Stutter, Turntablist). Выбранные ячейки — числа по смещениям 4
    (время) и 8 (громкость). None — банк не разобрался или имени в нём нет: состояние остаётся как в пресете.
    ponytail: начало ищется по первой ячейке «Empty»; банки без неё (Default, Flanging, Pitch shifter) не разбираются."""
    at, names = state.find(b"\x05Empty"), []
    while 0 <= at < len(state) - 28 and len(names) < 72:
        ln = state[at]
        n = int.from_bytes(state[at + 24 + ln:at + 28 + ln], "little")
        if ln > 30 or not 1 <= n <= 4000:
            break
        names.append(_norm(state[at + 1:at + 1 + ln].decode("latin1")))
        at += ln + 48 + 24 * n
    if len(names) != 72 or at != len(state) or not _norm(name) or _norm(name) not in names:
        return None
    k = names.index(_norm(name))
    return state[:4 + 4 * (k // 36)] + _int(k % 36, 4) + state[8 + 4 * (k // 36):]


def _clip(auto: Path) -> list[tuple[int, bytes]] | None:
    """События канала-клипа автоматизации из шаблона FL: канал вида 5 с точками, от своего номера до следующего канала.
    Из нескольких — с пустыми флажками в шапке точек: смысл флажков не разобран."""
    try:
        ev = events(auto.read_bytes())
    except (OSError, AssertionError, IndexError):
        return None
    cuts = [i for i, (e, _) in enumerate(ev) if e in (64, 99)]
    found = [ev[a:b] for a, b in zip(cuts, cuts[1:]) if (21, b"\5") in ev[a:b] and any(e == 234 and len(v) >= 21 for e, v in ev[a:b])]
    return next((c for c in found if dict(c)[234][4:9] == bytes(5)), found[0] if found else None)


def _bytes(f: Path) -> bytes | None:
    """Файл базы плагинов. База лежит в «Документах», а они в iCloud: выгруженный файл фоновому процессу macOS
    не отдаёт, зато `brctl download` оттуда работает и файл на месте через секунды (`noty.lay`) — просим и пробуем ещё раз."""
    for last in (False, True):
        try:
            return f.read_bytes()
        except OSError:
            if last or not f.exists():
                return None
            try:
                subprocess.run(["brctl", "download", str(f)], capture_output=True, timeout=30)
            except (OSError, subprocess.SubprocessError):
                return None
            time.sleep(3)


def _where(f: Path) -> str:
    """Путь звука, как его пишет сам FL: от папки данных пользователя."""
    home = LIBRARY["KITS"].parent
    return f"%FLStudioUserData%/{f.relative_to(home).as_posix()}" if f.is_relative_to(home) else str(f)


def today(kits: Path, serum: Path, plan: dict, base: Path = BASE, db: Path = DB, home: Path | None = None,
          banks=PRESETS, auto: Path = AUTO) -> str:
    """Проект бита — в папку «Сегодня», из того, что в ней уже лежит: партитуры, звуки с именем партии впереди,
    дорожки петли и пресеты. plan — поля паспорта (`noty.build`): title, bpm, parts, tricks, fx, preset.
    home — где папка будет лежать, если не здесь (пробная сборка в сторону): пути звуков ведут туда.
    Возвращает строку для записки: что в проекте есть и что осталось рукам."""
    if not base.exists():
        return "Проект FL не собран: на этой машине нет FL Studio 20."
    nfc = lambda s: unicodedata.normalize("NFC", str(s))
    where = lambda f: _where((home or kits) / f.name)
    role = lambda p: "808" if any(w in p.lower() for w in SAMPLED) else "барабаны" if any(w in p.lower() for w in GM_DRUM) else "музыка"
    scores = [(nfc(f.stem).split(" ", 1)[1], read_fsc(f)) for f in sorted(kits.glob("*.fsc"))]
    wavs = sorted((f for f in kits.iterdir() if f.suffix.lower() == ".wav"), key=lambda f: nfc(f.name))
    presets = sorted(serum.glob("*.fxp"), key=lambda f: nfc(f.name)) if serum.is_dir() else []
    fx = {nfc(k).strip().lower(): str(v) for k, v in plan["fx"].items()} if isinstance(plan.get("fx"), dict) else {}
    own = plan.get("preset") if isinstance(plan.get("preset"), dict) else {}
    wrap = [x for x in events(_bytes(db / SERUM) or pack([], 0)) if x[0] in PLUGIN]
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
            channels += [ch | {"name": f"{part} {k + 1}" if k else part, "sound": where(f), "root": root, "cut": role(part) == "808"}
                         for k, f in enumerate(mine)]
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
            channels.append({"name": Path(file).stem, "insert": number[key], "sound": where(kits / file), "clip": ticks})
    effects, drums = _effects(db / "Effects"), next((b for b in buses if "барабан" in b), None)
    proto, inserts, lost, own, timed, miss = _clip(auto), {}, 0, [], [], []
    for i, row in enumerate([MASTER] + rows):
        steps, bus = _chain(fx.get(row.lower(), ""), effects, buses)
        kind = role(row) if 0 < i <= len(rows) - len(buses) else None       # роль — у партий и дорожек петли, не у шин
        if row.lower() not in fx and any(row == p for p, _ in scores):      # у барабанов строки в fx нет: их шина — барабанная
            bus = drums
        # Готовые настройки по умолчанию — звену автора без своего пресета либо новым слотом в конец цепочки: перегруз
        # на дорожке 808 (автор не назвал там ничего) и ограничитель на мастере (ограничителя в цепочке нет)
        blank = lambda key: {"key": key, "file": effects[key], "preset": "", "cell": "", "spans": []}
        bare = lambda key: next((s for s in steps if s["key"] == key and not s["preset"]), None)
        if kind == "808" and DRIVE[0] in effects:
            steps += [] if steps else [blank(DRIVE[0])]
            if st := bare(DRIVE[0]):
                st["state"] = DRIVE[1]
                own.append(f"{row}: Fruity Soft Clipper перегрузом (порог 23 из 127, post 111 из 160)")
        if not i and LIMIT[0] in effects:
            steps += [] if len(steps) > 9 or any("limit" in s["key"] or "maximus" in s["key"] for s in steps) else [blank(LIMIT[0])]
            if st := bare(LIMIT[0]):
                st["preset"] = LIMIT[1]
        loaded, clips = [], {}
        for st in steps:
            data, label = _bytes(st["file"]), st["file"].stem
            if not data:
                lost += 1
                continue
            state = st.get("state") or (_preset(st["key"], st["preset"], banks) if st.get("preset") else None)
            picked = _cell(state, st["cell"]) if state and st.get("cell") else None
            if st.get("preset") and not state:
                miss.append(f"пресета «{st['preset']}» у {label} нет — плагин с настройками по умолчанию")
            elif st.get("cell") and not picked:
                miss.append(f"ячейки «{st['cell']}» в пресете «{st['preset']}» у {label} нет — выбери её сам")
            if state:
                data = pack([(e, (picked or state) if e == 213 else v) for e, v in events(data)], 0, 0x30)
                own += [f"{row}: {label} «{st['preset']}{': ' + st['cell'] if picked else ''}»"] if st.get("preset") else []
            if st["spans"] and proto:
                clips[len(loaded)] = (f"{row}: {label}", st["spans"])
                timed.append(f"{row}: {label} — " + ", ".join(_bars(a, b) for a, b in st["spans"]))
            elif st["spans"]:
                miss.append(f"клип автоматизации для {label} не поставлен: в этой поставке FL нет шаблона с таким клипом")
            loaded.append(data)
        inserts[i] = {"name": row if i else None, "plugins": loaded, "to": number.get(bus) if i and bus != row.lower() else None,
                      "level": LEVEL.get(kind), "auto": clips}
    flat = str(plan.get("parts") or "")
    for _ in range(3):                      # пояснения в скобках — не части: «(петля молчит в тактах 24–25)»
        flat = re.sub(r"\([^()]*\)", "", flat)
    markers = [(int(m[2]), m[1].strip()) for m in re.finditer(r"([^,;]+?)\s+(\d+)\s*[–—-]\s*\d+", flat)]
    name = re.sub(r"[/\\:\0]", " ", str(plan.get("title") or "бит")).strip()[:80] + ".flp"
    data = project(base.read_bytes(), plan["bpm"], channels, inserts, markers, proto)
    back = read(data)
    assert back["bpm"] == plan["bpm"] and len(back["channels"]) == len(channels) + len(timed), "проект записался не так"
    end = max(ln for _, _, ln, _ in back["clips"]) / 96                 # отрезок за концом бита клип обрезает
    want = [[(a, min(b, end)) for a, b in x[1] if a < end] for r in inserts.values() for _, x in sorted(r["auto"].items())]
    assert [c["on"] for c in back["channels"][len(channels):]] == want and len(back["links"]) == len(want), "клип автоматизации записался не так"
    (kits / name).write_bytes(data)
    slots = sum(len(x["plugins"]) for x in inserts.values())
    levels = ", ".join(f"{k} — {v}%" for k, v in LEVEL.items())
    return (f"Проект FL — «{name}» в этой же папке: каналов {len(channels)}, со звуками и нотами; партии — паттернами на весь бит "
            f"в плейлисте, части — маркерами; дорожки микшера подписаны и разведены по шинам. Фейдеры: {levels}, остальное 100% — "
            f"по чужим проектам под твои рефы; у канала 808 отсечка «сам себя». Эффектов в слотах — {slots}: числа из «Обработки» "
            "выстави сам, настроены только названные здесь."
            + (f" Готовыми настройками: {'; '.join(own)}." if own else "")
            + (f" Включаются сами, клипом автоматизации на mix слота (своя дорожка плейлиста, 100% в тактах, 0% в остальных): "
               f"{'; '.join(timed)}." if timed else " Эффектов «местами» в проекте нет: автор нот не назвал их с тактами.")
            + (f" Не вышло: {'; '.join(miss)}." if miss else "")
            + (f" Корневая нота канала выставлена: {', '.join(roots)}." if roots else "")
            + (f" Без звука, поставь сам: {', '.join(silent)}." if silent else "")
            + (f" Эффектов не встало (файл базы плагинов не прочитался): {lost}." if lost else "")
            + " На слух проект не проверял никто. "
            + ("Папка пробная: утренняя сборка её не трогает." if home else
               "Сохранишь проект в этой папке — завтра она не сотрётся, а переедет рядом, в «00 - <дата> <бит>», со звуками; "
               "не сохранишь — перепишется."))


def _bars(a: float, b: float) -> str:
    """Отрезок в долях от начала бита — словами записки: «такт 23», «такты 31–32», «такт 59 (доли 3–4)»."""
    x, y = divmod(a, 4), divmod(b - 1, 4)
    if x[1] == 0 and y[1] == 3:
        return f"такт {x[0] + 1:g}" if x[0] == y[0] else f"такты {x[0] + 1:g}–{y[0] + 1:g}"
    if x[0] == y[0]:
        return f"такт {x[0] + 1:g} (" + (f"доля {x[1] + 1:g})" if x[1] == y[1] else f"доли {x[1] + 1:g}–{y[1] + 1:g})")
    return f"с такта {x[0] + 1:g}.{x[1] + 1:g} по {y[0] + 1:g}.{y[1] + 1:g}"


def keep(kits: Path) -> str:
    """Проект, который владелец сохранил в «Сегодня» (файл .flp новее метки `.бит`), утром не стирается: папка целиком
    переезжает рядом, в «00 - <дата> <бит>», пути звуков в её проектах переписаны на новое имя (`repath`), прежний
    файл — рядом, .bak. Владелец 06.10.2026 сохранил первый же проект прямо в «Сегодня», а `noty.lay` стирает её
    каждое утро. Нетронутую папку стирает `lay`, как раньше. Проект не разобрался байт в байт — папка переезжает,
    а файл не тронут: FL спросит звуки сам. Возвращает строку для записки; пустая — переезда не было."""
    mark = kits / ".бит"
    since = mark.stat().st_mtime if mark.exists() else 0
    mine = sorted((f for f in kits.glob("*.flp") if f.stat().st_mtime > since), key=lambda f: f.stat().st_mtime) if kits.is_dir() else []
    if not mine:
        return ""
    day = mark.read_text("utf-8")[:8] if mark.exists() else ""
    day = day if day.isdigit() else time.strftime("%Y%m%d", time.localtime(mine[-1].stat().st_mtime))
    title = unicodedata.normalize("NFC", mine[-1].stem).split(" — ")[-1]
    new = next(d for k in range(1, 1000) if not (d := kits.with_name(f"00 - {day} {title}" + f" {k}" * (k > 1))).exists())
    kits.rename(new)
    stuck = []
    for f in sorted(new.glob("*.flp")):
        moved = repath(f.read_bytes(), kits.name, new.name)
        if moved is None:
            stuck.append(f.name)
            continue
        shutil.copy2(f, f.with_name(f.name + ".bak"))
        f.write_bytes(moved)
    return (f"Прошлый проект ты сохранил в «{kits.name}» — папка не стёрта, а переехала рядом со всеми звуками: «{new.name}». "
            + (f"Пути звуков не переписаны, файл не тронут — {', '.join(stuck)}: при открытии FL спросит, где звуки, — покажи эту папку."
               if stuck else "Пути звуков в проекте переписаны на неё, прежний файл лежит рядом с окончанием .bak."))


# --- проверка ----------------------------------------------------------------

def _fake() -> bytes:
    """Шаблон в миниатюре — для машин без FL (Actions): события Empty.flp в том же порядке, но дорожек восемь."""
    ev = [(199, b"20.7.0.1702\0"), (156, _int(140000, 4)), (9, b"\0"), (146, FF), (226, bytes(20)),
          (64, bytes(2)), (21, b"\0"), (201, _text("")), (212, bytes(52)), (203, _text("Sampler")), (155, bytes(4)),
          (128, bytes(4)), (0, b"\1"), (22, b"\1"), (215, bytes(158)), (132, bytes(4)), (143, _int(3, 4)), (20, b"\0"),
          (99, bytes(2)), (241, _text("Arrangement")), (233, b"")] + [(238, _int(i, 4) + bytes(62)) for i in range(1, 9)]
    for i in range(8):
        ev += [(236, bytes(12)), *((98, _int(s, 2)) for s in range(10)), (235, bytes([i > 0]) + bytes(126)), (154, FF), (147, FF)]
    return pack(ev + [(225, b"".join(struct.pack("<IBBHi", 0, 192, 31, 0x2000 + i * 64, 12800) for i in range(8))), (133, bytes(4))], 1)


def selftest() -> None:
    import tempfile
    notes = [N(0, 4, 31, 112), N(4, 2.5, 34, 90, pan=-50, fine=30), N(6, 1, 38, 100, slide=True), N(100 * 16, 8, 31)]
    plan = {"title": "А x Б — Проба", "bpm": 120, "parts": "вступление 1–8 (тихо, петля молчит в тактах 3–4), игра 9–104",
            "tricks": ["808 — «Тон D#1»: корневая нота канала — 27 по имени файла", "хэт: корневая нота канала — на слух"],
            "preset": {"мелодия": {"имя": "Свой"}},
            "fx": {"мелодия": "Pro-Q 4: срез низа до 150 Гц → без обработки → в шину музыки", "808": "Fruity Soft Clipper → в шину барабанов и 808",
                   "петля": "Fruity Soft Clipper «Нет такого», слегка → Нет такого плагина → Pro-Q 4 → "
                            "Gross Beat «Momentary: 1/2 Speed», замедление, в тактах 2, 3.3–3.4 и 90–200",
                   "шина музыки": "Pro-Q 4, фильтр низких частот от 6 кГц", "шина барабанов и 808": "Fruity Soft Clipper — клиппер",
                   "весь бит": "Pro-Q 4 → Fruity Soft Clipper на мастере; местами: Pro-Q 4, такты 1 и 7"}}
    with tempfile.TemporaryDirectory(prefix="flp-") as tmp:
        kits, serum, db, pre = (Path(tmp) / d for d in ("kits", "serum", "db", "presets"))
        for d in (kits, serum, db / "Effects" / "Dynamics", db / SERUM.rpartition("/")[0], pre / "Gross Beat", pre / "Fruity Limiter"):
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
        native = lambda name, state: pack([(199, b"11.5.5\0"), (201, _text(name)), (212, bytes(52)), (213, state)], 2, 0x30)
        (db / "Effects" / "Gross Beat.fst").write_bytes(native("Gross Beat", b"gross-default"))
        (db / "Effects" / "Dynamics" / "Fruity Limiter.fst").write_bytes(native("Fruity Limiter", b"limiter-default"))
        # банк Gross Beat в миниатюре: шапка и 72 ячейки — имя с байтом длины, 23 байта, число точек, точка, хвост
        cell = lambda name: bytes([len(name)]) + name.encode() + bytes(23) + _int(1, 4) + bytes(44)
        bank = _int(4, 4) + bytes(44) + b"".join(cell({0: "Empty", 30: "1/2 Speed", 36: "Empty", 41: "1/4 Bt Gate"}.get(k, "")) for k in range(72))
        half = _cell(bank, "1/2 speed")
        assert half[4:12] == _int(30, 4) + bytes(4) and _cell(bank, "1/4 Bt Gate")[4:12] == bytes(4) + _int(5, 4), "ячейка времени и громкости"
        assert _cell(bank, "Нет такой") is None and _cell(bank[:-1], "1/2 Speed") is None, "банк не разобрался — состояние не трогаем"
        (pre / "Gross Beat" / "Momentary.fst").write_bytes(pack([(201, b"Gross beat\0"), (213, bank)], 2, 0x30))   # имя не в UTF-16, как в старых
        (pre / "Fruity Limiter" / "Max loudness.fst").write_bytes(native("Fruity Limiter", b"limiter-loud"))
        assert _spans("Gross Beat в тактах 1 и 1.3") == [(0, 4)] and _spans("прикрыт (такты 1–12) и открыт с такта 13") == [], "такты"
        clip = pack([(64, bytes(2)), (21, b"\5"), (203, _text("Volume")), (234, bytes(17) + _int(2, 4) + bytes(48) + b"tail"), (99, bytes(2))], 1)
        for base, auto in [(_fake(), clip)] + [(BASE.read_bytes(), AUTO.read_bytes())] * (BASE.exists() and AUTO.exists()):   # на Маке — и шаблоны FL
            (Path(tmp) / "Empty.flp").write_bytes(base)
            (Path(tmp) / "Auto.flp").write_bytes(auto)
            line = today(kits, serum, plan, Path(tmp) / "Empty.flp", db, None, (pre,), Path(tmp) / "Auto.flp")
            data = (kits / "А x Б — Проба.flp").read_bytes()
            got = read(data)
            ch = got["channels"]
            assert got["bpm"] == 120 and [c["name"] for c in ch] == ["808", "хэт", "хэт 2", "мелодия", "Петля — на весь бит", "петля: Gross Beat"], ch
            assert [c["kind"] for c in ch] == ["сэмплер"] * 3 + ["плагин", "аудиоклип", "автоматизация"] and [c["insert"] for c in ch][:5] == [1, 2, 2, 3, 4]
            assert ch[0]["sound"].endswith("/808 — Тон D#1.wav") and ch[0]["root"] == 27 and ch[1]["root"] is None, ch[:2]
            assert [c["cut"] for c in ch[:3]] == [1, 0, 0], "отсечка «сам себя» — только у 808"
            assert b"CcnK-svoy" in ch[3]["state"] and b"osnova" not in ch[3]["state"], "в Serum — свой пресет бита, а не основа"
            same = sorted(notes)                                    # ноты партии — те же: место, длина, высота, сила, панорама, слайд
            assert got["patterns"][1] == {"name": "808", "notes": {0: same}} and got["patterns"][2]["notes"] == {1: same, 2: same}
            assert got["clips"] == [("паттерн", 1, 101 * BAR, 0), ("паттерн", 2, 101 * BAR, 1), ("паттерн", 3, 101 * BAR, 2),
                                    ("канал", 4, BAR, 3), ("канал", 5, 101 * BAR, 4)], got["clips"]
            assert got["markers"] == [[1, "вступление"], [9, "игра"]], got["markers"]
            mix = got["inserts"]
            # мастер: цепочка автора и ограничитель с заводским пресетом последним; «местами: …, такты 1 и 7» — слова, клипа нет
            assert mix[0] == {"name": None, "slots": {0: "Pro-Q 4", 1: "Fruity Soft Clipper", 2: "Fruity Limiter"}, "to": [], "level": 100}, mix[0]
            assert b"limiter-loud" in data and b"limiter-default" not in data, "ограничитель — с пресетом, а не по умолчанию"
            # 808: поднят, клиппер автор назвал без чисел — он с числами чужого проекта; мелодия и петля опущены, барабаны — 100
            assert mix[1] == {"name": "808", "slots": {0: "Fruity Soft Clipper"}, "to": [6], "level": 125} and DRIVE[1] in data, mix[1]
            assert mix[2] == {"name": "хэт", "slots": {}, "to": [6], "level": 100}, "808 и барабаны — в свою шину"
            assert mix[3] == {"name": "мелодия", "slots": {0: "Pro-Q 4"}, "to": [5], "level": 57}, mix[3]
            assert mix[4] == {"name": "петля", "slots": {0: "Fruity Soft Clipper", 1: "Pro-Q 4", 2: "Gross Beat"}, "to": [0], "level": 57}, mix[4]
            assert mix[5]["slots"] == {0: "Pro-Q 4"} and mix[6] == {"name": "шина барабанов и 808", "slots": {0: "Fruity Soft Clipper"},
                                                                    "to": [0], "level": 100}
            # Gross Beat — банк пресета с выбранной ячейкой; клип ведёт mix его слота: 1 в названных тактах, конец — по концу бита
            assert half in data and b"gross-default" not in data, "в слоте — пресет с ячейкой «1/2 Speed»"
            assert got["links"] == [{"clip": 5, "mix": True, "insert": 4, "slot": 2}], got["links"]
            assert ch[5]["on"] == [(4, 8), (10, 12), (356, 404)], ch[5]["on"]
            assert "каналов 5" in line and "808 — 27" in line and "Эффектов в слотах — 10" in line, line
            assert "петля: Gross Beat — такт 2, такт 3 (доли 3–4), такты 90–200" in line and "пресета «Нет такого»" in line, line
        assert "нет FL Studio" in today(kits, serum, plan, Path(tmp) / "нет.flp", db)
        if PRESETS[1].is_dir():                                 # на Маке — настоящий банк FL: ячейка «1/2 Speed» в нём тридцатая
            assert _cell(_preset("grossbeat", "Momentary"), "1/2 Speed")[4:12] == _int(30, 4) + bytes(4), "заводской банк Momentary"
        from .noty import _project
        _project(Path(tmp) / "нет.json", kits, serum)           # сбой проекта — строка в записке, а не падение сбора папки
        assert "Проект FL не собрался" in (kits / "о бите.txt").read_text("utf-8")
        # Сохранённое владельцем не стирается: проект новее метки — папка переезжает, пути звуков ведут в неё, остальное байт в байт
        import os
        (kits / ".бит").write_text("20261006-proba abc", "utf-8")
        assert keep(kits) == "" and kits.is_dir(), "нетронутая папка остаётся чистке"
        os.utime(kits / "А x Б — Проба.flp", (time.time() + 60,) * 2)
        (kits / "битый.flp").write_bytes(b"not FL")
        said, new = keep(kits), kits.with_name("00 - 20261006 Проба")
        moved = (new / "А x Б — Проба.flp").read_bytes()
        assert not kits.exists() and (new / "А x Б — Проба.flp.bak").read_bytes() == data and "битый.flp" in said, said
        assert all(c["sound"].startswith(f"{new}/") and (new / Path(c["sound"]).name).exists() for c in read(moved)["channels"] if c["sound"])
        assert repath(moved, new.name, kits.name) == data and (new / "битый.flp").read_bytes() == b"not FL", "кроме путей не тронуто ничего"
    print("проект FL: шаблон, каналы со звуком и пресетом, ноты, клипы, маркеры, слоты, уровни и шины читаются обратно; отсечка 808, "
          "перегруз и ограничитель по умолчанию; пресет FL и ячейка Gross Beat; клип автоматизации на mix слота; сбой — строка в записке; "
          "сохранённая папка переезжает, пути звуков — за ней")


def main() -> None:
    ap = argparse.ArgumentParser(description="Проект FL Studio из нот, звуков и обработки бита")
    ap.add_argument("--selftest", action="store_true", help="проект читается обратно: темп, каналы, ноты, микшер, автоматизация")
    ap.add_argument("--read", metavar="ФАЙЛ", help="что лежит в проекте .flp")
    args = ap.parse_args()
    if args.selftest:
        selftest()
    elif args.read:
        got = read(Path(args.read).read_bytes())
        print(f"{got['bpm']:g} BPM")
        for i, c in enumerate(got["channels"]):
            print(f"канал {i}: {c['name']} — {c['kind']}" + (f", дорожка микшера {c['insert']}" if c["kind"] != "автоматизация" else "")
                  + (f", звук {c['sound']}" if c["sound"] else "") + (f", корневая нота {c['root']}" if c["root"] is not None else "")
                  + (f", группа отсечки {c['cut']}" if c["cut"] else "") + (f", состояние плагина {len(c['state'])} байт" if c["state"] else "")
                  + (", держит 1: " + (", ".join(_bars(a, b) for a, b in c["on"]) or "нигде") if c["kind"] == "автоматизация" else ""))
        for x in got["links"]:
            print(f"привязка: канал {x['clip']} → " + (f"микшер {x['insert']}, слот {x['slot'] + 1}, {'mix' if x['mix'] else 'другой параметр'}"
                                                         if x["insert"] is not None else "не микшер"))
        for p, pat in got["patterns"].items():
            print(f"паттерн {p}: {pat['name']} — " + ", ".join(f"канал {c}: нот {len(n)}" for c, n in pat["notes"].items()))
        for kind, idx, ln, track in got["clips"]:
            print(f"клип: {kind} {idx}, тактов {ln / BAR:g}, дорожка плейлиста {track + 1}")
        print("маркеры: " + ", ".join(f"{bar} {name}" for bar, name in got["markers"]))
        for i, x in got["inserts"].items():
            print(f"микшер {i}: {x['name'] or ('мастер' if not i else '—')} — фейдер {x['level']}%, слоты: "
                  + (", ".join(f"{s + 1} {p}" for s, p in x["slots"].items()) or "пусто") + f"; идёт в {x['to']}")
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
