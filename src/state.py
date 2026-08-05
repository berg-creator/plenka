"""Чтение и запись состояния. Состояние живёт в JSON-файлах репозитория,
а git выступает бесплатной базой с историей и откатом."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from . import config


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(moment: datetime | None = None) -> str:
    return (moment or now()).isoformat(timespec="seconds")


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        # Битый файл не должен ронять весь запуск: откатываемся к пустому состоянию,
        # а испорченный вариант оставляем рядом для разбора.
        path.rename(path.with_suffix(path.suffix + ".broken"))
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    path.write_text(text + "\n", encoding="utf-8")


def append_jsonl(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> Iterator[dict]:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def fingerprint(*parts: str) -> str:
    """Стабильный отпечаток находки — основа защиты от дублей."""
    joined = "|".join(p.strip().lower() for p in parts if p)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:16]


class Seen:
    """Отпечатки уже обработанных находок с автоочисткой по возрасту."""

    def __init__(self) -> None:
        self._data: dict[str, str] = read_json(config.SEEN_FILE, {})

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def add(self, key: str) -> None:
        self._data[key] = iso()

    def prune(self) -> int:
        cutoff = now() - timedelta(days=config.SEEN_TTL_DAYS)
        stale = [
            key
            for key, stamp in self._data.items()
            if _parse(stamp) is not None and _parse(stamp) < cutoff  # type: ignore[operator]
        ]
        for key in stale:
            del self._data[key]
        return len(stale)

    def save(self) -> None:
        write_json(config.SEEN_FILE, self._data)


def _parse(stamp: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def git_commit(message: str, paths: list[Path]) -> bool:
    """Коммитит изменения состояния. Возвращает False, если менять было нечего.

    Внутри GitHub Actions коммит делает встроенный GITHUB_TOKEN — отдельный
    ключ для этого не нужен.
    """
    existing = [str(p.relative_to(config.ROOT)) for p in paths if p.exists()]
    if not existing:
        return False

    subprocess.run(["git", "add", "--", *existing], cwd=config.ROOT, check=True)
    staged = subprocess.run(
        ["git", "diff", "--cached", "--quiet"], cwd=config.ROOT
    ).returncode
    if staged == 0:
        return False  # изменений нет

    subprocess.run(["git", "commit", "-m", message], cwd=config.ROOT, check=True)
    return True
