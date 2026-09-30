"""Дорожки ссылкой на облако для СВЕДЕНИЯ: Яндекс Диск, Dropbox, файл Google Диска.

Музыканты отдают стемы папкой на Яндекс Диске, а у кого старый телефон, другого пути
и нет: гигабайт на телефон не скачать и боту не загрузить (владелец 30.09.2026).
До этого бот при открытой заявке принимал ссылку за просьбу словами и отвечал
«Записал — учту при сведении», хотя ни одной дорожки не получил.

Дежурство только смотрит (look): у Яндекса есть открытый API, и один запрос
метаданных с коротким таймаутом сразу говорит человеку, что бот увидел — «папка,
19 WAV». У Dropbox и Google метаданных без ключа нет, там — «скачаю при сведении».
Качает и распаковывает только процесс сведения (fetch), как и генератор: гигабайт
в цикле опроса держал бы кнопки всех.

Что по ссылке — чужое, поэтому проверки обязательные. Размер — до скачивания,
из API или Content-Length, и ещё раз по факту: файл не больше SKLEYKA_MAX_MB, всё
по ссылкам трека — не больше SKLEYKA_LINK_MB. У архива оглавление читается раньше
распаковки: пути с «..» и абсолютные — отказ всему архиву, распакованный размер
сверяется с потолком, а 7z идёт под пределом размера файла и под присмотром
за папкой. Берутся только аудиофайлы, не больше SKLEYKA_LINK_FILES, и на диск они
ложатся под номерами: имя из архива путём не становится.

Отвергнуто: папка Google Диска — без ключа API её не открыть; облако Mail.ru и прочие —
без ключа ни списка, ни скачивания. Им честный отказ: «пришли архивом или ссылкой
на Яндекс Диск». rar — только если 7z на машине его умеет, иначе тоже отказ.

Журналы Actions видят все, поэтому здесь печатаются только числа, размеры и коды
ответов — ни имён файлов, ни ссылок.

    python -m src.oblako --probe      отвечают ли облака с этой машины и есть ли 7z — без чужих ссылок
    python -m src.oblako --selftest   ссылки, отказы, «..» в архиве, размеры — без сети
"""

from __future__ import annotations

import argparse
import contextlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath

import requests

from . import config

YANDEX_API = "https://cloud-api.yandex.net/v1/disk/public/resources"
GOOGLE_DOWNLOAD = "https://drive.usercontent.google.com/download"
URL = re.compile(r"https?://[^\s<>«»\"']+")
YANDEX = re.compile(r"^https?://(?:disk\.yandex\.[a-z.]+/(?:d|i)/|yadi\.sk/(?:d|i)/)", re.I)
DROPBOX = re.compile(r"^https?://(?:www\.)?dropbox\.com/(?:s|sh|scl/fi|scl/fo)/", re.I)
GOOGLE_FILE = re.compile(r"^https?://(?:drive|docs)\.google\.com/(?:file/d/([\w-]+)|(?:open|uc)\?(?:\S*&)?id=([\w-]+))", re.I)
# Облака, откуда без ключа не скачать, — им отказ, а не «записал просьбу».
CLOUDS = re.compile(r"^https?://(?:[\w-]+\.)*(?:google\.com|cloud\.mail\.ru|mega\.nz|mega\.io|wetransfer\.com|we\.tl"
                    r"|icloud\.com|1drv\.ms|onedrive\.live\.com|mediafire\.com)/", re.I)
AUDIO = (".wav", ".wave", ".flac", ".mp3", ".m4a", ".aac", ".aif", ".aiff", ".ogg", ".opus")
ARCHIVES = (".zip", ".7z", ".rar")
MB = 2**20
MAX_FILE = config.SKLEYKA_MAX_MB * MB
MAX_TOTAL = config.SKLEYKA_LINK_MB * MB
MAX_ENTRIES = 1000  # строк в оглавлении архива или в папке: больше — это не проект трека
LOOK_TIMEOUT = 5  # дежурство ждёт метаданные не дольше — дальше «посмотрю при сведении»

REFUSE = "Отсюда скачать не могу — пришли архивом или ссылкой на Яндекс Диск."
GONE = "Ссылка не открылась — проверь, что доступ по ссылке открыт."
NOT_AUDIO = "По ссылке не звук и не архив — пришли WAV, FLAC, MP3 или архив."
TOO_BIG = f"По ссылке файл больше {config.SKLEYKA_MAX_MB} МБ — пришли FLAC или MP3 320."
TOO_MUCH = f"По ссылкам больше {config.SKLEYKA_LINK_MB // 1024} ГБ — пришли только нужные дорожки."
TOO_MANY = f"По ссылкам больше {config.SKLEYKA_LINK_FILES} звуковых файлов — пришли только нужные дорожки."
BAD_ARCHIVE = "Архив не открылся — пришли zip, 7z или папкой на Яндекс Диске."
UNSAFE = "В архиве странные пути к файлам — открывать его не буду. Пришли папкой или другим архивом."


class Refused(Exception):
    """Отказ человеку: текст исключения уходит ему как есть."""


def links(text: str) -> list[str]:
    """Ссылки на облака в тексте — и те, откуда качаем, и те, откуда не можем."""
    return [url.rstrip(".,;)") for url in URL.findall(text)
            if any(kind.match(url) for kind in (YANDEX, DROPBOX, GOOGLE_FILE, CLOUDS))]


def _get(url: str, **kwargs) -> requests.Response:
    """Единственная дорога в сеть — самопроверка подменяет её ответами. Ошибка сети — без адреса:
    в тексте исключения requests стоит ссылка человека, а журнал сведения открыт всем."""
    try:
        return requests.get(url, **kwargs)
    except requests.RequestException as exc:
        raise RuntimeError(f"облако: {type(exc).__name__}") from None


@contextlib.contextmanager
def _quiet():
    """Обрыв посреди скачивания — тоже без адреса в тексте ошибки."""
    try:
        yield
    except requests.RequestException as exc:
        raise RuntimeError(f"облако: {type(exc).__name__}") from None


def _check(response: requests.Response) -> None:
    """Код ответа: закрыто или нет — отказ человеку, прочий сбой — без адреса в тексте."""
    if response.status_code in (403, 404, 410):
        raise Refused(GONE)
    if response.status_code >= 400:
        raise RuntimeError(f"облако отвечает {response.status_code}")


def _suffix(name: str) -> str:
    return PurePosixPath(name).suffix.lower()


def _mb(size: int) -> str:
    return f"{size / MB:.0f} МБ" if size >= MB else "меньше 1 МБ"


def _yandex(url: str, path: str = "", offset: int = 0, timeout: float = 30) -> dict:
    params = {"public_key": url, "limit": 200, "offset": offset, **({"path": path} if path else {})}
    response = _get(YANDEX_API, params=params, timeout=timeout)
    print(f"  облако: Яндекс отвечает {response.status_code}")
    _check(response)
    return response.json()


def look(url: str) -> str:
    """Что по ссылке — строкой человеку, без скачивания. Нельзя — Refused. У Яндекса
    один запрос с коротким таймаутом; не ответил — «посмотрю при сведении»."""
    if YANDEX.match(url):
        try:
            meta = _yandex(url, timeout=LOOK_TIMEOUT)
        except (RuntimeError, ValueError):
            return "ссылка на Яндекс Диск — загляну при сведении"
        if meta.get("type") != "dir":
            return _one(meta.get("name", ""), meta.get("size") or 0)
        items = (meta.get("_embedded") or {}).get("items", [])
        files = [item for item in items if item.get("type") == "file"]
        size = sum(item.get("size") or 0 for item in files)
        if size > MAX_TOTAL:
            raise Refused(TOO_MUCH)
        kinds = Counter(_suffix(item["name"]).lstrip(".").upper() for item in files
                        if _suffix(item["name"]) in AUDIO + ARCHIVES)
        dirs = sum(item.get("type") == "dir" for item in items)
        more = (meta.get("_embedded") or {}).get("total", len(items)) > len(items)
        said = " и ".join(f"{n} {kind}" for kind, n in kinds.most_common()) or "звука сверху нет"
        return f"папка, {said}" + (f", вложенных папок: {dirs} — загляну при сведении" if dirs else "") \
            + (" — остальное увижу при сведении" if more else "")
    if DROPBOX.match(url):
        return "ссылка Dropbox — скачаю при сведении"
    if GOOGLE_FILE.match(url):
        return "файл Google Диска — скачаю при сведении"
    raise Refused(REFUSE)


def _one(name: str, size: int) -> str:
    """Строка человеку про один файл по ссылке."""
    suffix = _suffix(name)
    if suffix in ARCHIVES:
        if size > MAX_TOTAL:
            raise Refused(TOO_MUCH)
        return f"архив, {_mb(size)} — распакую при сведении"
    if suffix not in AUDIO:
        raise Refused(NOT_AUDIO)
    if size > MAX_FILE:
        raise Refused(TOO_BIG)
    return f"файл {suffix.lstrip('.').upper()}, {_mb(size)}"


def listing(url: str) -> list[dict]:
    """Все файлы по ссылке Яндекса без скачивания, с вложенными папками: [{name, size, href}],
    name — путь внутри папки. У Dropbox и Google списка без скачивания нет — пусто."""
    if not YANDEX.match(url):
        return []
    found: list[dict] = []

    def walk(path: str, depth: int) -> None:
        offset = 0
        while True:
            meta = _yandex(url, path, offset)
            if meta.get("type") != "dir":
                found.append({"name": meta.get("name", ""), "size": meta.get("size") or 0, "href": meta.get("file")})
                return
            items = (meta.get("_embedded") or {}).get("items", [])
            for item in items:
                inner = f"{path.rstrip('/')}/{item['name']}"
                if item.get("type") == "dir" and depth < 5:
                    walk(inner, depth + 1)
                elif item.get("type") == "file":
                    found.append({"name": inner.lstrip("/"), "size": item.get("size") or 0, "href": item.get("file")})
                if len(found) > MAX_ENTRIES:
                    raise Refused(TOO_MANY)
            offset += len(items)
            if not items or offset >= (meta.get("_embedded") or {}).get("total", 0):
                return

    walk("", 0)
    return found


class Budget:
    """Сколько байт ещё можно записать по ссылкам трека и сколько взять звуковых файлов."""

    def __init__(self) -> None:
        self.left, self.files = MAX_TOTAL, config.SKLEYKA_LINK_FILES

    def take(self, size: int) -> None:
        if size > self.left:
            raise Refused(TOO_MUCH)
        self.left -= size

    def count(self, files: int) -> None:
        if files > self.files:
            raise Refused(TOO_MANY)
        self.files -= files


def _download(url: str, dest: Path, cap: int, budget: Budget, params: dict | None = None) -> str:
    """Файл по ссылке — в dest, не больше cap байт: Content-Length до скачивания, счёт — по ходу.
    Возвращает имя из Content-Disposition, если оно есть."""
    limit = min(cap, budget.left)
    why = TOO_BIG if limit == MAX_FILE else TOO_MUCH
    with _get(url, params=params, stream=True, timeout=60, allow_redirects=True) as response:
        print(f"  облако: скачивание отвечает {response.status_code}")
        _check(response)
        if int(response.headers.get("Content-Length") or 0) > limit:
            raise Refused(why)
        if "text/html" in response.headers.get("Content-Type", ""):
            raise Refused(GONE)  # страница вместо файла: доступ закрыт или Google просит вход
        written = 0
        with dest.open("wb") as out, _quiet():
            for chunk in response.iter_content(MB):
                written += len(chunk)
                if written > limit:
                    raise Refused(why)
                out.write(chunk)
        budget.take(written)
        disposition = response.headers.get("Content-Disposition", "")
    named = re.search(r"filename\*=UTF-8''([^;]+)", disposition) or re.search(r'filename="?([^";]+)', disposition)
    return urllib.parse.unquote(named.group(1)) if named else ""


def _safe(name: str) -> bool:
    """Путь из оглавления архива — внутри архива: без «..», без корня и диска."""
    parts = PurePosixPath(name.replace("\\", "/")).parts
    return bool(parts) and not name.startswith(("/", "\\")) and ".." not in parts and ":" not in parts[0]


def _sevenzip() -> str:
    return shutil.which("7zz") or shutil.which("7z") or ""


def _entries(archive: Path) -> list[tuple[str, int]]:
    """Оглавление архива: [(путь, размер)] — только файлы, до распаковки."""
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as packed:
            return [(info.filename, info.file_size) for info in packed.infolist() if not info.is_dir()]
    tool = _sevenzip()
    if not tool:
        raise Refused(BAD_ARCHIVE)
    shown = subprocess.run([tool, "l", "-slt", "-ba", "-sccUTF-8", str(archive)], capture_output=True, timeout=120)
    if shown.returncode:
        print(f"  облако: 7z не открыл архив, код {shown.returncode}")
        raise Refused(BAD_ARCHIVE)
    entries, name, size, folder = [], None, 0, False
    for line in shown.stdout.decode("utf-8", "replace").splitlines() + [""]:
        key, _, value = line.partition(" = ")
        if key == "Path":
            name, size, folder = value, 0, False
        elif key == "Size" and value.isdigit():
            size = int(value)
        elif key == "Folder":
            folder = value == "+"
        elif key == "Attributes":
            folder = folder or value.startswith("D")
        elif not line.strip() and name is not None:
            if not folder:
                entries.append((name, size))
            name = None
    return entries


def _unpack(archive: Path, dest: Path, budget: Budget) -> list[tuple[str, Path]]:
    """Звук из архива — в dest под номерами: [(путь в архиве, файл)]. Оглавление проверяется
    целиком до распаковки: один странный путь — отказ всему архиву."""
    entries = _entries(archive)
    if len(entries) > MAX_ENTRIES:
        raise Refused(TOO_MANY)
    if not all(_safe(name) for name, _ in entries):
        raise Refused(UNSAFE)
    sounds = [(name, size) for name, size in entries
              if _suffix(name) in AUDIO and not PurePosixPath(name).name.startswith("._")]  # ._ — след macOS
    if any(size > MAX_FILE for _, size in sounds):
        raise Refused(TOO_BIG)
    budget.count(len(sounds))
    budget.take(sum(size for _, size in sounds))
    dest.mkdir(parents=True, exist_ok=True)
    print(f"  облако: архив — {len(entries)} файлов, звуковых {len(sounds)}, "
          f"{sum(size for _, size in sounds) / MB:.0f} МБ после распаковки")
    if zipfile.is_zipfile(archive):
        found = []
        with zipfile.ZipFile(archive) as packed:
            for n, (name, size) in enumerate(sounds):
                target, written = dest / f"{n}{_suffix(name)}", 0
                with packed.open(name) as source, target.open("wb") as out:
                    while chunk := source.read(MB):
                        written += len(chunk)
                        if written > size:  # оглавление соврало о размере
                            raise Refused(UNSAFE)
                        out.write(chunk)
                found.append((name, target))
        return found
    return _unpack_7z(archive, dest, sounds)


def _unpack_7z(archive: Path, dest: Path, sounds: list[tuple[str, int]]) -> list[tuple[str, Path]]:
    """7z и rar — бинарником 7z: только звуковые файлы по списку, каждый не больше MAX_FILE
    (предел процесса), вся папка — не больше заявленного в оглавлении, иначе процесс снимается."""
    import resource

    raw, allowed = dest / "raw", sum(size for _, size in sounds)
    raw.mkdir()
    listfile = dest / "list.txt"
    listfile.write_text("\n".join(name for name, _ in sounds), encoding="utf-8")

    def limit() -> None:
        resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_FILE, MAX_FILE))

    process = subprocess.Popen([_sevenzip(), "x", "-y", "-bd", "-scsUTF-8", f"-o{raw}", str(archive), f"@{listfile}"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=limit)
    started = time.monotonic()
    while process.poll() is None:
        time.sleep(0.5)
        written = sum(path.stat().st_size for path in raw.rglob("*") if path.is_file())
        if written > allowed or time.monotonic() - started > 600:
            process.kill()
            process.wait()
            raise Refused(UNSAFE)
    if process.returncode:
        print(f"  облако: 7z не распаковал архив, код {process.returncode}")
        raise Refused(BAD_ARCHIVE)
    found, root = [], raw.resolve()
    for n, (name, _) in enumerate(sounds):
        source = (raw / name.replace("\\", "/")).resolve()
        if not source.is_relative_to(root) or not source.is_file():
            raise Refused(UNSAFE)
        target = dest / f"{n}{_suffix(name)}"
        source.replace(target)
        found.append((name, target))
    shutil.rmtree(raw, ignore_errors=True)
    return found


def _place(name: str, path: Path, folder: Path, n: int, budget: Budget) -> list[tuple[str, Path]]:
    """Скачанный файл: звук — как есть, архив — распаковать, прочее — отказ."""
    suffix = _suffix(name)
    if suffix in ARCHIVES:
        return [(f"{name}/{inner}", file) for inner, file in _unpack(path, folder / f"x{n}", budget)]
    if suffix not in AUDIO:
        raise Refused(NOT_AUDIO)
    budget.count(1)
    return [(name, path)]


def fetch(url: str, folder: Path, budget: Budget) -> list[tuple[str, Path]]:
    """Звук по ссылке — в folder: [(путь внутри ссылки, файл)]. Только в процессе сведения."""
    folder.mkdir(parents=True, exist_ok=True)
    found: list[tuple[str, Path]] = []
    if YANDEX.match(url):
        entries = [entry for entry in listing(url) if _suffix(entry["name"]) in AUDIO + ARCHIVES]
        if any(entry["size"] > (MAX_TOTAL if _suffix(entry["name"]) in ARCHIVES else MAX_FILE) for entry in entries):
            raise Refused(TOO_BIG)
        if sum(entry["size"] for entry in entries) > budget.left:
            raise Refused(TOO_MUCH)
        print(f"  облако: по ссылке {len(entries)} файлов, {sum(e['size'] for e in entries) / MB:.0f} МБ")
        for n, entry in enumerate(entries):
            suffix = _suffix(entry["name"])
            path = folder / f"{n}{suffix}"
            _download(entry["href"], path, MAX_TOTAL if suffix in ARCHIVES else MAX_FILE, budget)
            found += _place(entry["name"], path, folder, n, budget)
        return found
    if DROPBOX.match(url):
        # dl=1 — сам файл, а папка — zip-архивом: у Dropbox это одна и та же ссылка.
        parts = urllib.parse.urlsplit(url)
        query = urllib.parse.urlencode([*[(k, v) for k, v in urllib.parse.parse_qsl(parts.query) if k != "dl"], ("dl", "1")])
        path = folder / "dropbox"
        name = _download(urllib.parse.urlunsplit(parts._replace(query=query)), path, MAX_TOTAL, budget) \
            or PurePosixPath(parts.path).name
        if "/fo/" in parts.path or "/sh/" in parts.path:
            name = name if _suffix(name) == ".zip" else f"{name}.zip"
        return _place(name, path, folder, 0, budget)
    if google := GOOGLE_FILE.match(url):
        # confirm=t — без него большой файл отдаётся страницей «проверить на вирусы не можем».
        path = folder / "google"
        name = _download(GOOGLE_DOWNLOAD, path, MAX_TOTAL, budget,
                         {"id": google.group(1) or google.group(2), "export": "download", "confirm": "t"})
        return _place(name or "файл", path, folder, 0, budget)
    raise Refused(REFUSE)


def probe() -> int:
    """Отвечают ли облака этой машине — на заведомо пустых адресах, без чужих ссылок: ответ
    «такого нет» — облако доступно, 451 или обрыв — нет. И есть ли 7z и умеет ли он rar."""
    tries = (("Яндекс Диск", YANDEX_API, {"public_key": "https://disk.yandex.ru/d/plenka-probe-0000"}),
             ("Dropbox", "https://www.dropbox.com/scl/fi/plenkaprobe0000/probe.wav", {"dl": "1"}),
             ("Google Диск", GOOGLE_DOWNLOAD, {"id": "plenka-probe-0000", "export": "download"}))
    broken = False
    for name, url, params in tries:
        try:
            code = _get(url, params=params, timeout=20, allow_redirects=False).status_code
        except RuntimeError as exc:
            code, broken = str(exc), True
        broken = broken or code in (403, 451) and name == "Яндекс Диск"
        print(f"  {name}: {code}")
    tool = _sevenzip()
    rar = tool and b"Rar" in subprocess.run([tool, "i"], capture_output=True).stdout
    print(f"  7z: {'есть' if tool else 'нет'}, rar: {'умеет' if rar else 'не умеет'}")
    return 1 if broken else 0


class Answer:
    """Подменный ответ сети для самопроверок — здесь и в skleyka."""

    def __init__(self, code: int = 200, data: dict | None = None, body: bytes = b"", headers: dict | None = None):
        self.status_code, self._data, self._body, self.headers = code, data, body, headers or {}

    def json(self) -> dict:
        return self._data

    def iter_content(self, size: int):
        yield from (self._body[i:i + size] for i in range(0, len(self._body), size))

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None


def _selftest() -> None:
    """Без сети: какие ссылки облачные, отказы, «..» в архиве, размеры до и после скачивания."""
    assert links("вот https://disk.yandex.ru/d/abc123 и https://youtu.be/x") == ["https://disk.yandex.ru/d/abc123"]
    assert links("https://yadi.sk/d/q1, https://www.dropbox.com/scl/fo/a/b?rlkey=c&dl=0") == \
        ["https://yadi.sk/d/q1", "https://www.dropbox.com/scl/fo/a/b?rlkey=c&dl=0"]
    for url in ("https://drive.google.com/drive/folders/abc", "https://cloud.mail.ru/public/a/b"):
        assert links(url) == [url]
        with contextlib.suppress(Refused):
            look(url)
            raise AssertionError(f"папка Google и Mail.ru — отказ: {url}")
    assert look("https://drive.google.com/file/d/abc_1/view?usp=sharing").startswith("файл Google")
    assert _safe("Audio/vocal.wav") and not _safe("../evil.wav") and not _safe("/etc/x.wav") \
        and not _safe("a/../../b.wav") and not _safe("C:\\x.wav") and not _safe("a\\..\\b.wav")

    global _get
    real = _get
    tmp = Path(tempfile.mkdtemp(prefix="oblako-test-"))
    try:
        # Папка: строка человеку по метаданным; огромная — отказ до скачивания.
        folder = {"type": "dir", "_embedded": {"total": 3, "items": [
            {"type": "file", "name": "a.wav", "size": 5 * MB, "file": "u1"},
            {"type": "file", "name": "b.wav", "size": 5 * MB, "file": "u2"},
            {"type": "dir", "name": "sub"}]}}
        _get = lambda url, **kw: Answer(data=folder)
        assert look("https://disk.yandex.ru/d/x") == "папка, 2 WAV, вложенных папок: 1 — загляну при сведении"
        folder["_embedded"]["items"][0]["size"] = MAX_TOTAL
        with contextlib.suppress(Refused):
            look("https://disk.yandex.ru/d/x")
            raise AssertionError("больше потолка — отказ по метаданным")
        _get = lambda url, **kw: Answer(data={"type": "file", "name": "big.wav", "size": MAX_FILE + 1})
        with contextlib.suppress(Refused):
            look("https://disk.yandex.ru/d/x")
            raise AssertionError("файл больше лимита — отказ")
        _get = lambda url, **kw: Answer(404)
        with contextlib.suppress(Refused):
            look("https://disk.yandex.ru/d/x")
            raise AssertionError("закрытая ссылка — отказ")
        # Content-Length больше лимита — отказ, не скачивая; соврал — счёт по ходу.
        _get = lambda url, **kw: Answer(headers={"Content-Length": str(MAX_FILE + 1)})
        with contextlib.suppress(Refused):
            _download("u", tmp / "x.wav", MAX_FILE, Budget())
            raise AssertionError("Content-Length больше лимита")
        _get = lambda url, **kw: Answer(body=b"0" * 3000)
        with contextlib.suppress(Refused):
            _download("u", tmp / "x.wav", 2000, Budget())
            raise AssertionError("скачалось больше, чем можно")
        # Архив с «..» — отказ всему архиву, раньше распаковки.
        evil = tmp / "evil.zip"
        with zipfile.ZipFile(evil, "w") as packed:
            packed.writestr("vocal.wav", b"RIFF")
            packed.writestr("../../escape.wav", b"RIFF")
        with contextlib.suppress(Refused):
            _unpack(evil, tmp / "evil", Budget())
            raise AssertionError("«..» в архиве")
        assert not (tmp / "escape.wav").exists() and not (tmp / "evil").exists()
        # Обычный zip: только звук, под номерами.
        good = tmp / "good.zip"
        with zipfile.ZipFile(good, "w") as packed:
            packed.writestr("Audio/vocal.wav", b"RIFF1")
            packed.writestr("Audio/readme.txt", b"x")
            packed.writestr("__MACOSX/Audio/._vocal.wav", b"x")
        got = _unpack(good, tmp / "good", Budget())
        assert [(name, path.name, path.read_bytes()) for name, path in got] == [("Audio/vocal.wav", "0.wav", b"RIFF1")], got
        budget = Budget()
        budget.left = 3
        with contextlib.suppress(Refused):
            _unpack(good, tmp / "small", budget)
            raise AssertionError("распакованное больше потолка")
    finally:
        _get = real
        shutil.rmtree(tmp, ignore_errors=True)
    print("oblako: облачные ссылки, отказ папке Google и Mail.ru, размеры до и после скачивания, «..» в архиве — ок")


def main() -> int:
    parser = argparse.ArgumentParser(description="Дорожки ссылкой на облако")
    parser.add_argument("--probe", action="store_true", help="отвечают ли облака и есть ли 7z — без чужих ссылок")
    parser.add_argument("--selftest", action="store_true", help="ссылки, отказы, архивы, размеры — без сети")
    args = parser.parse_args()
    if args.probe:
        return probe()
    if args.selftest:
        _selftest()
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
