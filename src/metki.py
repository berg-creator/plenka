"""МЕТКИ — страница на Маке, где владелец слушает звуки по одному и раскладывает их по артистам и настроению.

Утренняя сборка бита (src/noty.py) берёт музыку из одобренного (data/beat_music.json), а барабаны — из любых
источников владельца, и подбирает хэт и клэп по тембру образца. Владелец об «Отбое» (17.10.2026): «драмка будто вообще
не подходит к этому биту», «нужно, чтобы ты под нужный стиль нужный звук брал». Под какого артиста звук годится, знает
только его ухо, поэтому страница даёт ему карточку на звук: звук играет сам, под ним артисты и настроение, исходы —
«мимо», «годится всем», «сохранить» с метками, «пропустить» и «назад». Метки сборка читает из data/beat_tags.json:
«мимо» выпадает отовсюду, барабаны «берём» — одобренные (`noty.approved`, `noty.owned`), а артист и настроение —
порядок выбора автора нот (`noty --tags`, раздел «Один бит — один образец» брифа).

Барабан звучит не ударом, а рисунком своей роли в такт: одна бочка ничего не говорит о том, сядет ли она в бит.
Бочка и 808 — по долям (808 тремя высотами), клэп и снейр — на 2 и 4, хэт — восьмыми, открытый хэт — на слабую
долю, перк — раз в долю; галочка «под петлю» кладёт тот же рисунок поверх одной из одобренных петель в её темпе.

Почему своя страница, а не кнопки бота: каждый звук пришлось бы заливать в Telegram, под каждым висел бы свой плеер,
и звук там звучит без контекста — один удар, без такта и без петли. Почему не мини-приложение Telegram: ему нужен
адрес в сети, а звук отдавался бы из облака, то есть чужие наборы пришлось бы туда выложить. Страница же отдаёт файл
прямо с диска Мака, в том числе на телефон в домашнем Wi-Fi.

Отдаёт она файл только по номеру карточки из своего списка: путь в запросе не принимается, иначе любой в той же сети
читал бы диск. Без случайного ключа в адресе — 403. Звуки на две трети — заглушки iCloud, чтение файла его скачивает,
поэтому при старте файлы не читаются: только список имён, файл — по запросу, следующие три страница просит заранее.
Черновик меток — вне git (`config.BEAT_TAGS_DRAFT`, почему — там же), в main его несёт `--push` из временной копии
на свежем origin/main: рабочую копию, из которой запущена страница, отправка не трогает.

    python -m src.metki              страница: адрес с ключом для Мака и для телефона
    python -m src.metki --push       метки — коммитом в main
    python -m src.metki --selftest   без сети и без записи в настоящие файлы
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import config, noty, state

# Под кого делаем type beat'ы — верх спроса 17.10.2026 (`bity --demand`: рядовой ролик за месяц 1557, 1276, 958 и 625
# просмотров, у следующих — 400 и меньше). Владелец их послушал: «все делаем с ними… теперь врубаюсь».
# Свои рефы он на странице не держит — сборке нужна метка артиста образца; образцы под этих — NEXT.md, раздел 84.
# Западные корни русских артистов (bity.ROOTS): звук образцов утреннего бита — с запада (владелец 17.10.2026),
# в like образца есть и корень, и русские имена, поэтому прежние метки под русских тоже работают.
ARTISTS = ("Playboi Carti", "Don Toliver", "2hollis", "Kanye West")
# Настроения — звуки западных корней (владелец 17.10.2026, вместо «злой, кино, обычный»: «обычный» о звуке не говорил).
MOODS = ("злой", "грустный", "дымка", "клуб")
ROLES = tuple(noty.ROLE_WORDS)      # порядок карточек барабанов: бочки, 808, клэп и снейр, хэт, открытый хэт, перки
PORT = 8765
MESSAGE = "звуки: метки владельца"
LOCK = threading.Lock()             # одна запись черновика за раз: телефон и Мак могут нажать разом


def deck(music: dict, library: set[str]) -> list[dict]:
    """Карточки по порядку: одобренные петли и звуки музыки (data/beat_music.json), затем барабаны и 808, которые сборка
    вправе взять (`noty.kind` — список библиотеки, кроме петель ударов), по ролям и внутри — по наборам. Бочку и 808
    набора 11 бриф запрещает («бас слабый как и бочка», 06.10.2026) — их нет и здесь."""
    rows = [{"path": n, "kind": "петля", "bpm": (r or {}).get("bpm") or noty.loop_bpm(n)} for n, r in (music.get("loops") or {}).items()]
    rows += [{"path": n, "kind": (r or {}).get("kind") or "звук"} for n, r in (music.get("sounds") or {}).items()]
    drums = [n for n in library if noty.kind(n) in ROLES and not (n.startswith(noty.NET + "/") and noty.kind(n) in ("Kicks", "808s"))]
    rows += [{"path": n, "kind": noty.ROLE_WORDS[noty.kind(n)], "role": noty.kind(n)}
             for n in sorted(drums, key=lambda n: (ROLES.index(noty.kind(n)), n.split("/")[1], n))]
    for i, row in enumerate(rows):
        path = row["path"] = noty._nfc(row["path"])
        row |= {"id": i, "kit": path.split("/")[1] if path.count("/") > 1 else path.split("/")[0],
                "name": path.rsplit("/", 1)[-1], "audio": path.startswith("KITS/") and path.lower().endswith(".wav")}
    return rows


def read_tags() -> dict[str, dict]:
    """Черновик меток; его ещё нет — копия того, что уже в main (страница на другой копии или после чистки)."""
    for path in (config.BEAT_TAGS_DRAFT, config.BEAT_TAGS):
        data = state.read_json(path, None)
        if isinstance(data, dict):
            return data
    return {}


def write_tags(data: dict) -> None:
    """Запись через временный файл: оборванная на середине запись не должна стереть сотни меток."""
    path = config.BEAT_TAGS_DRAFT
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def tag(cards: list[dict], body: dict) -> dict:
    """Решение по карточке: {"id", "v": "yes"|"no", "like", "mood"} или {"id", "undo": true} — снять. Ошибка — ValueError."""
    i = body.get("id")
    if not isinstance(i, int) or isinstance(i, bool) or not 0 <= i < len(cards):
        raise ValueError("нет такой карточки")
    path = cards[i]["path"]
    with LOCK:
        data = read_tags()
        if body.get("undo"):
            data.pop(path, None)
        else:
            like, mood = body.get("like") or [], body.get("mood") or []
            if body.get("v") not in ("yes", "no") or not isinstance(like, list) or not isinstance(mood, list) \
                    or set(like) - set(ARTISTS) or set(mood) - set(MOODS):
                raise ValueError("решение не из списка")
            data[path] = {"v": body["v"], "like": [a for a in ARTISTS if a in like], "mood": [m for m in MOODS if m in mood]}
        write_tags(data)
    return {"ok": True, "left": sum(1 for c in cards if c["path"] not in data)}


def push(draft: Path, root: Path, send: bool = True) -> str:
    """Черновик меток — коммитом «звуки: метки владельца» в main: временная копия на свежем origin/main, в неё файл, коммит,
    push с повтором через pull --rebase. send=False — до коммита, без отправки (селфтест). Итог — одной строкой."""
    if not draft.exists():
        return "меток ещё нет: отправлять нечего"

    def git(*args: str, cwd: Path = root) -> str:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()

    tmp = Path(tempfile.mkdtemp(prefix="metki-"))
    try:
        git("fetch", "-q", "origin", "main")
        git("worktree", "add", "-q", "--detach", str(tmp), "origin/main")
        target = tmp / config.BEAT_TAGS.relative_to(config.ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(draft, target)
        git("add", str(target.relative_to(tmp)), cwd=tmp)
        if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=tmp).returncode == 0:
            return "метки уже в main: отправлять нечего"
        git("commit", "-q", "-m", MESSAGE, cwd=tmp)
        count = len(json.loads(draft.read_text("utf-8")))
        if not send:
            return f"коммит {git('rev-parse', 'HEAD', cwd=tmp)} — проба, не отправлен"
        for _ in range(3):
            if subprocess.run(["git", "push", "-q", "origin", "HEAD:main"], cwd=tmp, capture_output=True).returncode == 0:
                return f"отправлено: {count} меток в main, коммит {git('rev-parse', '--short', 'HEAD', cwd=tmp)}"
            git("pull", "-q", "--rebase", "origin", "main", cwd=tmp)
        return "не отправилось: main трижды ушёл вперёд — нажми ещё раз"
    except subprocess.CalledProcessError as e:
        tail = (e.stderr or "").strip().splitlines()
        return f"не отправилось: git {e.cmd[1]} — {tail[-1] if tail else 'без ответа'}"[:300]
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(tmp)], cwd=root, capture_output=True)
        shutil.rmtree(tmp, ignore_errors=True)


class Page(BaseHTTPRequestHandler):
    """Пять адресов: / — страница, /cards — список, /f/<номер> — звук карточки, POST /tag и /push. Всё — только с ключом."""

    def log_message(self, *args) -> None:     # каждый звук — строка в Терминал: шум, а не сведения
        pass

    def _send(self, code: int, body: bytes | str | dict, kind: str | None = None) -> None:
        if isinstance(body, dict):
            body, kind = json.dumps(body, ensure_ascii=False), "application/json; charset=utf-8"
        if isinstance(body, str):
            body, kind = body.encode("utf-8"), kind or "text/plain; charset=utf-8"
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _gate(self) -> str | None:
        url = urlsplit(self.path)
        args = parse_qs(url.query, keep_blank_values=True)
        if len(args.get("k", ())) != 1 or not secrets.compare_digest(args["k"][0].encode(), self.server.key.encode()):
            self._send(403, "нет ключа: открой адрес, который страница напечатала при старте")
            return None
        if set(args) - {"k"}:
            self._send(400, "лишнее в запросе: звук отдаётся только по номеру карточки")
            return None
        return url.path

    def do_GET(self) -> None:
        path = self._gate()
        if path is None:
            return
        cards = self.server.cards
        if path == "/":
            return self._send(200, HTML, "text/html; charset=utf-8")
        if path == "/cards":
            done = read_tags()
            return self._send(200, {"cards": cards, "pending": [c["id"] for c in cards if c["path"] not in done],
                                    "artists": ARTISTS, "moods": MOODS,
                                    "loops": [c["id"] for c in cards if c["kind"] == "петля" and c["audio"] and c.get("bpm")
                                              and (done.get(c["path"]) or {}).get("v") != "no"]})
        hit = re.fullmatch(r"/f/(\d{1,6})", path)
        if not hit or int(hit[1]) >= len(cards) or not cards[int(hit[1])]["audio"]:
            return self._send(404, "нет такой карточки или у неё нет звука")
        file = self.server.library / cards[int(hit[1])]["path"].partition("/")[2]
        try:
            data = file.read_bytes()        # заглушку iCloud это чтение и скачивает
        except OSError:
            return self._send(404, "файл не открылся")
        self._send(200, data, "audio/wav")

    def do_POST(self) -> None:
        path = self._gate()
        if path is None:
            return
        try:
            body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 10_000)) or b"{}")
        except ValueError:
            return self._send(400, "тело запроса — не JSON")
        if path == "/tag":
            try:
                return self._send(200, tag(self.server.cards, body if isinstance(body, dict) else {}))
            except ValueError as e:
                return self._send(400, {"error": str(e)})
        if path == "/push":
            return self._send(200, {"line": self.server.push()})
        self._send(404, "нет такого адреса")


def serve(cards: list[dict], host: str, port: int, library: Path, key: str | None = None) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), Page)
    server.cards, server.library, server.key = cards, library, key or secrets.token_urlsafe(12)
    server.push = lambda: push(config.BEAT_TAGS_DRAFT, config.ROOT)
    return server


def lan() -> str | None:
    """Адрес Мака в домашней сети: UDP-«соединение» ничего не шлёт, но называет, через какой адрес пошёл бы пакет."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
        except OSError:
            return None
    return None if ip.startswith("127.") else ip


def run(port: int) -> None:
    cards = deck(state.read_json(config.BEAT_MUSIC, {}), noty.known())
    server = serve(cards, "0.0.0.0", port, noty.LIBRARY["KITS"])
    left = sum(1 for c in cards if c["path"] not in read_tags())
    print(f"карточек {len(cards)}, осталось {left}; метки — {config.BEAT_TAGS_DRAFT}")
    print(f"на Маке:   http://localhost:{port}/?k={server.key}")
    ip = lan()
    print(f"с телефона: http://{ip}:{port}/?k={server.key}" if ip else "адреса в домашней сети не нашлось: только на Маке")
    print("остановить — Ctrl+C", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def selftest() -> None:
    from unittest import mock
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        kits = tmp / "KITS"
        (kits / "13 - X Kit" / "Hats").mkdir(parents=True)
        (kits / "13 - X Kit" / "Hats" / "Hat 1.wav").write_bytes(b"RIFF-hat")
        music = {"loops": {"KITS/01 - A Kit/Loops/Trap - L(140BPM).wav": {"bpm": 140}},
                 "sounds": {"KITS/13 - X Kit/Oneshots/Lead (C4).wav": {"kind": "лид"}, "Serum/x.fxp": {"kind": "лид"}}}
        library = {"KITS/13 - X Kit/Hats/Hat 1.wav", "KITS/13 - X Kit/Kicks/Kick 1.wav", "KITS/11 - Сеть Kit/Kicks/Сеть - k.wav",
                   "KITS/11 - Сеть Kit/Percs/Сеть - p.wav", "KITS/13 - X Kit/Oneshots/Lead (C4).wav"}
        cards = deck(music, library)
        assert [c["kind"] for c in cards] == ["петля", "лид", "лид", "бочка", "хэт", "перк"], [c["kind"] for c in cards]
        assert not cards[2]["audio"] and cards[0]["bpm"] == 140, "пресет не звучит, у петли темп"
        hat = next(c["id"] for c in cards if c["kind"] == "хэт")
        with mock.patch.object(config, "BEAT_TAGS_DRAFT", tmp / "draft.json"), mock.patch.object(config, "BEAT_TAGS", tmp / "tags.json"), \
                mock.patch.object(config, "BEAT_MUSIC", tmp / "music.json"):
            server = serve(cards, "127.0.0.1", 0, kits, key="kluch")
            server.push = lambda: "проба"
            threading.Thread(target=server.serve_forever, daemon=True).start()
            base = f"http://127.0.0.1:{server.server_address[1]}"

            def ask(path: str, body: dict | None = None) -> tuple[int, bytes]:
                req = Request(base + path, json.dumps(body).encode() if body is not None else None,
                              {"Content-Type": "application/json"})
                try:
                    with urlopen(req, timeout=5) as r:
                        return r.status, r.read()
                except HTTPError as e:
                    return e.code, e.read()

            k = "?k=kluch"
            assert ask("/")[0] == ask("/cards?k=klu")[0] == ask("/cards?k=%D0%BA")[0] == ask(f"/f/{hat}")[0] == 403, "без ключа — 403"
            code, page = ask("/" + k)
            assert code == 200 and b"<title>" in page
            assert ask(f"/f/{hat}{k}") == (200, b"RIFF-hat"), "звук — по номеру карточки"
            for bad in (f"/f/999{k}", f"/f/2{k}", f"/f/..%2FKITS{k}", f"/f/-1{k}"):
                assert ask(bad)[0] == 404, bad
            assert ask(f"/f/{hat}{k}&path=KITS/13%20-%20X%20Kit/Hats/Hat%201.wav")[0] == 400 \
                and ask(f"/f{k}&path=x")[0] == 400, "путь в запросе — отказ"
            # Решение пишется, «назад» его снимает; чужая карточка и чужой артист — отказ
            assert ask("/tag" + k, {"id": hat, "v": "yes", "like": ["Kanye West", "Playboi Carti"], "mood": ["злой"]})[0] == 200
            saved = json.loads(config.BEAT_TAGS_DRAFT.read_text("utf-8"))
            assert saved == {cards[hat]["path"]: {"v": "yes", "like": ["Playboi Carti", "Kanye West"], "mood": ["злой"]}}, saved
            assert hat not in json.loads(ask("/cards" + k)[1])["pending"], "решённое не показывается"
            assert ask("/tag" + k, {"id": hat, "undo": True})[0] == 200 and json.loads(config.BEAT_TAGS_DRAFT.read_text("utf-8")) == {}
            assert hat in json.loads(ask("/cards" + k)[1])["pending"], "снятое — снова в очереди"
            for body in ({"id": 999, "v": "no"}, {"id": "0", "v": "no"}, {"id": hat, "v": "yes", "like": ["Чужой"]}, {"id": hat, "v": "да"}):
                assert ask("/tag" + k, body)[0] == 400, body
            assert json.loads(ask("/push" + k, {})[1]) == {"line": "проба"}
            server.shutdown()
            server.server_close()
            # Сборка: «мимо» выпадает из музыки, «берём» — в одобренных: барабан, петля и звук музыки
            lead, bad = "KITS/13 - X Kit/Oneshots/Lead (C4).wav", "KITS/13 - X Kit/Oneshots/Pad (C4).wav"
            config.BEAT_MUSIC.write_text(json.dumps({"sounds": {lead: {}, bad: {}}}), encoding="utf-8")
            ring, keys = "KITS/11 - Сеть Kit/Loops/Keys 90BPM.wav", "KITS/13 - X Kit/Oneshots/Keys (C4).wav"
            config.BEAT_TAGS.write_text(json.dumps({bad: {"v": "no"}, cards[hat]["path"]: {"v": "yes", "like": [], "mood": []},
                                                    ring: {"v": "yes"}, keys: {"v": "yes"}}), encoding="utf-8")
            with mock.patch.object(noty, "loops", lambda: {ring: {}}):
                sounds, rings, drums = noty.approved()
            assert lead in sounds and bad not in sounds and cards[hat]["path"] in drums, (sounds, drums)
            assert ring in rings and ring not in sounds and keys in sounds, "петля и звук «берём» — в одобренных"
            said = "\n".join(noty._palette({"tonal": ["мелодия"], "sounds": {"мелодия": bad}}, {"мелодия": []}))
            assert f"звук «{bad}» — не из одобренных" in said, said
            assert noty._palette({"tonal": ["мелодия"], "sounds": {"мелодия": lead}}, {"мелодия": []}) == []
        assert noty.artist_key("Shh!") == noty.artist_key("Shh...") == noty.artist_key("shh") \
            and noty.artist_key("Тёмный  принц") == noty.artist_key("темный принц"), "имена — без регистра и знаков"
        # Отправка во временной копии доходит до коммита и не пушит; рабочая копия и origin не тронуты
        env = os.environ | {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
                            "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
        sh = lambda *a, cwd=tmp: subprocess.run(["git", *a], cwd=cwd, env=env, capture_output=True, text=True, check=True).stdout.strip()
        sh("init", "-q", "--bare", "-b", "main", "origin.git")
        sh("clone", "-q", "origin.git", "work")
        work = tmp / "work"
        (work / "data").mkdir()
        (work / "data" / "x.json").write_text("{}", encoding="utf-8")
        sh("add", ".", cwd=work)
        sh("commit", "-q", "-m", "1", cwd=work)
        sh("push", "-q", "origin", "HEAD:main", cwd=work)
        draft = tmp / "draft.json"
        write = {"KITS/a.wav": {"v": "no", "like": [], "mood": []}}
        draft.write_text(json.dumps(write), encoding="utf-8")
        with mock.patch.dict(os.environ, env):
            line = push(draft, work, send=False)
            assert line.endswith("проба, не отправлен"), line
            head = line.split()[1]
            assert sh("log", "-1", "--format=%s", head, cwd=work) == MESSAGE
            assert json.loads(sh("show", f"{head}:data/beat_tags.json", cwd=work)) == write
            assert sh("rev-parse", "main", cwd=tmp / "origin.git") == sh("rev-parse", "HEAD", cwd=work), "origin не тронут"
            assert not (work / "data" / "beat_tags.json").exists() and len(sh("worktree", "list", cwd=work).splitlines()) == 1, \
                "рабочая копия не тронута, временная убрана"
            assert push(tmp / "нет.json", work, send=False) == "меток ещё нет: отправлять нечего"
    print("метки: решение пишется и «назад» его снимает, решённое не показывается, без ключа — 403, путь в запросе и чужой номер — "
          "отказ, «мимо» сборка не берёт, «берём» — в одобренных (барабан, петля, звук), «Shh!» = «Shh», отправка доходит до коммита и не пушит")


HTML = r"""<!doctype html><meta charset="utf-8"><title>Метки звуков</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root { --bg:#111; --card:#1c1c1c; --line:#333; --text:#eee; --dim:#999; --on:#e8c547; --no:#c0392b; --yes:#2e8b57 }
* { box-sizing:border-box } [hidden] { display:none !important }
body { margin:0; background:var(--bg); color:var(--text); font:16px/1.35 -apple-system, system-ui, sans-serif }
main { max-width:440px; margin:0 auto; padding:16px }
#top { color:var(--dim); font-size:13px; display:flex; justify-content:space-between; gap:8px }
#kind { font-size:22px; font-weight:600; margin:6px 0 2px }
#name { word-break:break-word; font-size:14px; color:var(--dim) }
#note { min-height:20px; color:var(--on); font-size:13px; margin:6px 0 }
.row { display:grid; grid-template-columns:repeat(3, 1fr); gap:6px; margin:10px 0 }
button { font:inherit; color:var(--text); background:var(--card); border:1px solid var(--line); border-radius:10px;
         padding:12px 6px; min-height:48px; cursor:pointer; position:relative; touch-action:manipulation }
button.on { background:var(--on); color:#111; border-color:var(--on) }
button:disabled { opacity:.35 }
button kbd { position:absolute; top:3px; right:6px; font-size:10px; color:var(--dim) }
button.on kbd { color:#333 }
h3 { font-size:12px; text-transform:uppercase; letter-spacing:.06em; color:var(--dim); margin:14px 0 0 }
#play { display:flex; gap:6px; align-items:center }
#play button { flex:1 }
label { display:flex; align-items:center; gap:6px; color:var(--dim); font-size:14px }
#who { display:flex; flex-wrap:wrap; gap:4px 14px; font-size:14px; margin:6px 0 }
#who span { flex-basis:100%; color:var(--dim); font-size:13px }
a { color:var(--on) } h3 a { text-transform:none; letter-spacing:0; margin-left:8px }
#out .no { background:#3a1612; border-color:var(--no) } #out .yes { background:#14301f; border-color:var(--yes) }
#bot { margin-top:20px; border-top:1px solid var(--line); padding-top:12px; display:flex; gap:8px; align-items:center }
#line { font-size:13px; color:var(--dim) }
#start { position:fixed; inset:0; background:var(--bg); display:flex; align-items:center; justify-content:center; padding:16px }
#start button { font-size:22px; padding:24px 40px }
</style>
<main>
  <div id="top"><span id="where"></span><span id="count"></span></div>
  <div id="kind"></div><div id="name"></div><div id="note"></div>
  <div id="play"><button id="again">▶ повтор<kbd>пробел</kbd></button><button id="halt">■ стоп<kbd>esc</kbd></button>
    <label hidden id="underbox"><input type="checkbox" id="under"> под петлю</label><button hidden id="next" style="flex:0 0 48px">↻</button></div>
  <h3>Артисты <a href="#" id="whois">кто это?</a></h3>
  <div id="who" hidden><span>Имя — песни артиста на YouTube, в новой вкладке. Не знаешь артиста — не жми его:
    хватит настроения или «годится всем».</span></div>
  <div class="row" id="artists"></div>
  <h3>Настроение</h3><div class="row" id="moods"></div>
  <h3>Решение</h3>
  <div class="row" id="out">
    <button class="no" data-do="no">мимо<kbd>←</kbd></button>
    <button class="yes" data-do="all">годится всем<kbd>↓</kbd></button>
    <button class="yes" data-do="yes" id="save">→ сохранить<kbd>→</kbd></button>
    <button data-do="skip">пропустить<kbd>↑</kbd></button>
    <button data-do="back">← назад<kbd>⌫</kbd></button>
  </div>
  <div id="bot"><button id="push">Отправить в бота</button><span id="line"></span></div>
</main>
<div id="start"><button id="go">▶ Начать</button></div>
<script>
const K = new URLSearchParams(location.search).get('k') || '';
const q = p => p + '?k=' + encodeURIComponent(K);
const post = (p, b) => fetch(q(p), {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(b)});
const $ = id => document.getElementById(id);
const ART_KEYS = ['Digit1','Digit2','Digit3','Digit4','Digit5','Digit6','Digit7','Digit8','Digit9','Digit0','KeyQ','KeyW','KeyE','KeyR','KeyT'];
const ART_HINT = '1234567890QWERT', MOOD_KEYS = ['KeyA','KeyS','KeyD','KeyF'], MOOD_HINT = 'ASDF';
const SEMI = [0, 0, 0, 3, 0, 0, -2, -2];        // 808: три высоты по долям двух тактов
let C = [], queue = [], hist = [], LOOPS = [], ARTISTS = [], MOODS = [], loopAt = 0;
let cur = null, like = new Set(), mood = new Set(), ctx = null, live = [], timer = null, busy = false;
const cache = new Map();

function buf(id) {
  if (!cache.has(id)) cache.set(id, fetch(q('/f/' + id)).then(r => { if (!r.ok) throw r.status; return r.arrayBuffer(); })
    .then(b => ctx.decodeAudioData(b)));
  const p = cache.get(id); p.catch(() => cache.delete(id)); return p;
}
function stop() { clearInterval(timer); timer = null; live.forEach(s => { try { s.stop(); } catch (e) {} }); live = []; }
function src(b, t, rate = 1, loop = false) {
  const s = ctx.createBufferSource(); s.buffer = b; s.playbackRate.value = rate; s.loop = loop;
  s.connect(ctx.destination); s.start(t); live.push(s); s.onended = () => { live = live.filter(x => x !== s); }; return s;
}
function pattern(b, role, bpm, back) {
  const dt = 60 / bpm / 4; let t = ctx.currentTime + .05, s = 0, last = null;
  if (back) src(back, t, 1, true);
  const hit = (s, t) => {
    const beat = s % 4 === 0;
    if (role === 'Kicks' && beat) src(b, t);
    else if (role === '808s' && beat) { if (last) try { last.stop(t); } catch (e) {} last = src(b, t, 2 ** (SEMI[s >> 2] / 12)); }
    else if (role === 'Claps' && s % 8 === 4) src(b, t);
    else if (role === 'Hats' && s % 2 === 0) src(b, t);
    else if (role === 'Open Hats' && s % 4 === 2) src(b, t);
    else if (role === 'Percs' && beat) src(b, t);
  };
  const tick = () => { while (t < ctx.currentTime + .15) { hit(s, t); t += dt; s = (s + 1) % 32; } };
  tick(); timer = setInterval(tick, 25);
}
async function play() {
  stop(); const c = cur; if (!c || !ctx) return;
  if (!c.audio) { $('note').textContent = 'здесь не звучит: пресет — слушай в FL'; return; }
  let b; try { b = await buf(c.id); } catch (e) { if (cur === c) $('note').textContent = 'файл не открылся (' + e + ')'; return; }
  if (cur !== c) return;
  if (!c.role) { stop(); src(b, ctx.currentTime + .02, 1, c.kind === 'петля'); return; }
  let bpm = 140, back = null;
  if ($('under').checked && LOOPS.length) {
    const L = C[LOOPS[loopAt % LOOPS.length]];
    try { back = await buf(L.id); bpm = L.bpm; $('note').textContent = 'под петлю: ' + L.name; } catch (e) {}
    if (cur !== c) return;
  }
  stop(); pattern(b, c.role, bpm, back);
}
function render() {
  const c = cur;
  $('where').textContent = c ? c.kit : ''; $('count').textContent = c ? `карточка ${c.id + 1} из ${C.length} · осталось ${queue.length}` : '';
  $('kind').textContent = c ? c.kind + (c.bpm ? ` · ${c.bpm} BPM` : '') : 'Всё размечено';
  $('name').textContent = c ? c.name : 'Осталось отправить в бота.'; $('note').textContent = '';
  $('underbox').hidden = $('next').hidden = !(c && c.role && LOOPS.length);
  document.querySelectorAll('#artists button').forEach(x => x.classList.toggle('on', like.has(x.dataset.v)));
  document.querySelectorAll('#moods button').forEach(x => x.classList.toggle('on', mood.has(x.dataset.v)));
  document.querySelectorAll('#out button').forEach(x => { x.disabled = x.dataset.do === 'back' ? !hist.length
    : !c || (x.dataset.do === 'yes' && !(like.size || mood.size)); });
}
function show() {
  cur = queue.length ? C[queue[0]] : null; render(); play();
  if (!ctx) return;
  const keep = new Set([...queue.slice(0, 4), LOOPS[loopAt % LOOPS.length]]);
  queue.slice(1, 4).forEach(id => { if (C[id].audio) buf(id).catch(() => {}); });
  for (const id of cache.keys()) if (!keep.has(id)) cache.delete(id);
}
async function decide(v) {
  if (!cur || busy || (v === 'yes' && !(like.size || mood.size))) return;
  const t = v === 'no' ? {v: 'no', like: [], mood: []} : {v: 'yes', like: v === 'all' ? [] : [...like], mood: [...mood]};
  busy = true;
  try {
    const r = await post('/tag', {id: cur.id, ...t});
    if (!r.ok) { $('note').textContent = 'не записалось: ' + await r.text(); return; }
    hist.push({id: cur.id, t}); queue.shift(); like = new Set(); mood = new Set(); show();
  } catch (e) { $('note').textContent = 'страница не отвечает: запущена ли она на Маке?'; } finally { busy = false; }
}
function skip() { if (!cur) return; hist.push({id: cur.id, t: null}); queue.push(queue.shift()); like = new Set(); mood = new Set(); show(); }
async function back() {
  const h = hist[hist.length - 1]; if (!h || busy) return;
  if (h.t) { busy = true; try { const r = await post('/tag', {id: h.id, undo: true}); if (!r.ok) return; } catch (e) { return; } finally { busy = false; } }
  hist.pop(); queue = [h.id, ...queue.filter(x => x !== h.id)];
  like = new Set(h.t ? h.t.like : []); mood = new Set(h.t ? h.t.mood : []); show();
}
function toggle(set, v) { set.has(v) ? set.delete(v) : set.add(v); render(); }
function buttons(box, list, hint, set) {
  list.forEach((v, i) => { const b = document.createElement('button'); b.dataset.v = v; b.textContent = v;
    if (hint[i]) { const k = document.createElement('kbd'); k.textContent = hint[i]; b.append(k); }
    b.onclick = () => toggle(set(), v); $(box).append(b); });
}
document.addEventListener('click', e => { const b = e.target.closest('button'); if (b) b.blur();
  const d = b && b.dataset.do; if (d === 'skip') skip(); else if (d === 'back') back(); else if (d) decide(d); });
document.addEventListener('keydown', e => {
  if (e.metaKey || e.ctrlKey || e.altKey || !ctx) return;
  const a = ART_KEYS.indexOf(e.code), m = MOOD_KEYS.indexOf(e.code);
  if (a >= 0 && a < ARTISTS.length) toggle(like, ARTISTS[a]);
  else if (m >= 0) toggle(mood, MOODS[m]);
  else if (e.code === 'ArrowLeft') decide('no'); else if (e.code === 'ArrowDown') decide('all');
  else if (e.code === 'ArrowRight') decide('yes'); else if (e.code === 'ArrowUp') skip();
  else if (e.code === 'Backspace') back(); else if (e.code === 'Space') play(); else if (e.code === 'Escape') stop();
  else return;
  e.preventDefault();
});
$('again').onclick = play; $('halt').onclick = stop;
$('whois').onclick = e => { e.preventDefault(); $('who').hidden = !$('who').hidden; };
 $('under').onchange = play; $('next').onclick = () => { loopAt++; play(); };
$('push').onclick = async () => {
  $('line').textContent = 'отправляю…'; $('push').disabled = true;
  try { $('line').textContent = (await (await post('/push', {})).json()).line; } catch (e) { $('line').textContent = 'страница не ответила'; }
  $('push').disabled = false;
};
$('go').onclick = () => { ctx = new (window.AudioContext || window.webkitAudioContext)(); ctx.resume(); $('start').hidden = true; show(); };
fetch(q('/cards')).then(r => { if (!r.ok) throw r.status; return r.json(); }).then(d => {
  C = d.cards; queue = d.pending; LOOPS = d.loops; ARTISTS = d.artists; MOODS = d.moods;
  buttons('artists', ARTISTS, ART_HINT, () => like);
  ARTISTS.forEach(v => { const a = document.createElement('a'); a.textContent = v; a.target = '_blank'; a.rel = 'noopener';
    a.href = 'https://www.youtube.com/results?search_query=' + encodeURIComponent(v); $('who').append(a); });
  buttons('moods', MOODS, MOOD_HINT, () => mood); render();
}).catch(e => { $('go').textContent = e === 403 ? 'нет ключа в адресе' : 'страница не отвечает'; $('go').disabled = true; });
</script>
"""


def main() -> None:
    p = argparse.ArgumentParser(description="Метки звуков: страница на Маке — звук за звуком по артистам и настроению")
    p.add_argument("--selftest", action="store_true", help="проверить без сети и без записи в настоящие файлы")
    p.add_argument("--push", action="store_true", help="метки — коммитом «звуки: метки владельца» в main из временной копии")
    p.add_argument("--port", type=int, default=PORT, help=f"порт страницы (по умолчанию {PORT})")
    a = p.parse_args()
    if a.selftest:
        selftest()
    elif a.push:
        print(push(config.BEAT_TAGS_DRAFT, config.ROOT))
    else:
        run(a.port)


if __name__ == "__main__":
    main()
