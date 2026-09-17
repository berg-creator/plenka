"""Полный трек к посту о релизе — с YouTube, без рук владельца.

Владелец и так брал трек с YouTube: находил видео и качал его через сайт.
Бот делает то же в два шага, и шаги живут на разных машинах намеренно.
Искать YouTube пускает кого угодно, а качать сервер GitHub — нет: 17.09.2026
поиск оттуда нашёл 10 последних релизов из 10, скачивание — 0 из 3
(«Sign in to confirm you're not a bot»), а с домашнего интернета скачалось всё.

1. На GitHub `compose --ask-tracks` находит видео (`find`) и кладёт ссылку
   в запрос трека: кнопка YouTube ведёт ровно на него, а не на поиск.
2. На Mac владельца этот модуль раз в десять минут (launchd) смотрит очередь
   на GitHub, качает найденное и отправляет боту из аккаунта владельца
   ответом на запрос. Дальше путь тот же, что у присланного руками файла:
   дежурство принимает его в `moderate.attach_track`. Mac выключен или спит —
   запрос ждёт, и владелец может ответить сам.

Видео годится, только если длина сошлась с магазином: так отсекаются
тёзки, ремиксы и ускоренные версии. Официальному каналу (свой канал артиста
или «Artist - Topic») прощаем три секунды, чужой заливке — две.

Отвергнуто: отдельный бот-качалка — бот не может писать другому боту,
а свой поллер на токене канала воровал бы события у дежурства; обход защиты
YouTube на сервере — это атака на чужой сервис, и его закрывают в любой момент.
Ключ входа у Mac свой (TELEGRAM_SESSION_MAC): ключ дежурства, открытый
одновременно с двух машин, Telegram гасит насовсем.

    python -m src.sources.telegram_web --login-mac   один раз: свой ключ входа для Mac
    python -m src.tracks --install    поставить на Mac запуск раз в 10 минут
    python -m src.tracks --dry-run    какие треки скачались бы, без скачивания
    python -m src.tracks --selftest   выбор видео по длине и каналу, без сети
    python -m src.tracks              один проход руками
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import config, state
from .sources import telegram_web

log = logging.getLogger("tracks")

OFFICIAL_TOLERANCE = 3
UPLOAD_TOLERANCE = 2
SEARCH_RESULTS = 5
# Запрос трека уходит сразу за постом, а пост ждёт трек два часа:
# среди последних сообщений бота запрос найдётся с запасом.
REQUEST_SCAN = 300
SENT_FILE = config.PRIVATE / "tracks_sent.json"
LABEL = "fm.plenka.tracks"
INTERVAL = 600
LOG_FILE = Path.home() / "Library" / "Logs" / "plenka-tracks.log"


def pick(entries: list[dict], artist: str, seconds: int) -> dict:
    """Видео из выдачи поиска, у которого длина как в магазине, или {}."""
    names = [n.strip().casefold() for n in re.split(r",|&| feat\.? | x ", artist, flags=re.I) if n.strip()]

    def channel(entry: dict) -> str:
        return (entry.get("channel") or entry.get("uploader") or "").casefold()

    def off(entry: dict) -> float:
        return abs((entry.get("duration") or -100) - seconds)

    # «Topic» — звук ровно из магазина; в клипе на своём канале бывают сценки и шумы.
    ranked = sorted(entries, key=lambda e: (not channel(e).endswith(" - topic"), off(e)))
    return next((e for e in ranked if (channel(e).endswith(" - topic") or any(n in channel(e) for n in names))
                 and off(e) <= OFFICIAL_TOLERANCE), None) or next(
        (e for e in ranked if off(e) <= UPLOAD_TOLERANCE), {})


def find(artist: str, title: str, seconds: int) -> dict:
    """Видео трека на YouTube: {url, title, channel, duration} или {}.

    Без длины из магазина не ищем: сверять не с чем, а тёзка хуже пустоты.
    """
    if not (artist and title and seconds):
        return {}
    from yt_dlp import YoutubeDL

    try:
        with YoutubeDL({"quiet": True, "no_warnings": True, "extract_flat": True}) as ydl:
            found = ydl.extract_info(f"ytsearch{SEARCH_RESULTS}:{artist} {title}", download=False)
    except Exception as exc:  # noqa: BLE001 — без ссылки запрос уйдёт с поиском, как раньше
        log.warning("Поиск на YouTube не ответил: %s", exc)
        return {}
    return pick(found.get("entries") or [], artist, seconds)


def download(url: str, folder: Path) -> Path:
    """Звук видео в mp3 192 kbps: восьмиминутный трек — 11 МБ, боту отдаётся до 20."""
    from yt_dlp import YoutubeDL

    options = {
        "quiet": True, "no_warnings": True, "noprogress": True, "noplaylist": True, "format": "bestaudio/best",
        "outtmpl": str(folder / "track.%(ext)s"),
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}],
    }
    with YoutubeDL(options) as ydl:
        ydl.download([url])
    return folder / "track.mp3"


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(config.ROOT), *args], capture_output=True,
                          text=True, check=True, timeout=120).stdout


def pending() -> list[tuple[str, dict]]:
    """Посты очереди на GitHub, к которым найдено видео, а трека ещё нет.

    Очередь читается из свежего origin/main, а не с диска: рабочую папку
    владельца трогать нельзя, и она отстаёт от автоматики на часы.
    """
    _git("fetch", "-q", "origin", "main")
    folder = config.QUEUE.relative_to(config.ROOT).as_posix()
    found = []
    for path in _git("ls-tree", "--name-only", "origin/main", f"{folder}/").split():
        if not path.endswith(".json"):
            continue
        post = json.loads(_git("show", f"origin/main:{path}"))
        if (post.get("track_request") or {}).get("youtube") and not post.get("full_track_file_id"):
            found.append((Path(path).name, post))
    return found


def run(dry_run: bool) -> int:
    sent = state.read_json(SENT_FILE, {"sent": []})
    waiting = [(name, post) for name, post in pending() if name not in sent["sent"]]
    if not waiting:
        print("Трек сейчас не нужен ни одному посту.")
        return 0
    for name, post in waiting:
        print(f"  ↓ {post['artist']} — {post['track']}  {post['track_request']['youtube']}  ({name})")
    if dry_run:
        return 0
    if not os.environ.get(telegram_web.MAC_SESSION):
        log.error("Нет своего ключа входа у Mac — войти: python -m src.sources.telegram_web --login-mac")
        return 1

    from telethon.tl.types import DocumentAttributeAudio

    client = telegram_web._client(os.environ[telegram_web.MAC_SESSION])
    client.connect()
    try:
        # start() на погасшем ключе спросил бы телефон, а спрашивать некого — это launchd.
        if not client.is_user_authorized():
            log.error("Ключ входа Mac не действует — войти заново: --login-mac")
            return 1
        bot = client.get_entity(config.BOT_HANDLE)
        # Номер сообщения в личке у каждой стороны свой: message_id запроса из поста —
        # номер у бота, отвечать надо на номер у владельца. Запрос узнаём по имени файла.
        requests = {}
        for message in client.iter_messages(bot, limit=REQUEST_SCAN):
            for name, _ in waiting:
                if not message.out and name in (message.message or ""):
                    requests.setdefault(name, message.id)
        for name, post in waiting:
            if name not in requests:
                log.warning("Запрос трека к %s в личке не нашёлся", name)
                continue
            try:
                with tempfile.TemporaryDirectory() as work:
                    path = download(post["track_request"]["youtube"], Path(work))
                    client.send_file(bot, str(path), reply_to=requests[name], attributes=[
                        DocumentAttributeAudio(duration=int(post.get("seconds") or 0),
                                               title=post["track"], performer=post["artist"])])
            except Exception as exc:  # noqa: BLE001 — не скачался один, пробуем остальные; повтор через 10 минут
                log.error("Трек %s — %s не ушёл: %s", post["artist"], post["track"], exc)
                continue
            # Отправленное второй раз не шлём, даже если дежурство отказало:
            # причину оно уже написало владельцу, а повтор завалил бы личку.
            sent["sent"] = (sent["sent"] + [name])[-200:]
            state.write_json(SENT_FILE, sent)
            print(f"  ✓ {post['artist']} — {post['track']}")
    finally:
        client.disconnect()
    return 0


def install() -> int:
    """Запуск раз в десять минут через launchd. Спал Mac — пройдёт при пробуждении."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        print("Нужен ffmpeg: brew install ffmpeg")
        return 1
    plist = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    plist.write_bytes(plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": [sys.executable, "-m", "src.tracks"],
        "WorkingDirectory": str(config.ROOT),
        "StartInterval": INTERVAL,
        "RunAtLoad": True,
        # У launchd PATH голый: без него не найдутся ни git, ни ffmpeg из Homebrew.
        "EnvironmentVariables": {"PATH": f"{Path(ffmpeg).parent}:/usr/bin:/bin"},
        "StandardOutPath": str(LOG_FILE),
        "StandardErrorPath": str(LOG_FILE),
    }))
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", domain, str(plist)], capture_output=True)
    subprocess.run(["launchctl", "bootstrap", domain, str(plist)], check=True)
    print(f"Готово: помощник проверяет очередь раз в 10 минут. Журнал — {LOG_FILE}")
    return 0


def _selftest() -> int:
    # Официальный канал вперёд чужой заливки той же длины.
    entries = [{"url": "reupload", "channel": "Zach Wiglusz", "duration": 146},
               {"url": "own", "channel": "Ghostface Playa", "duration": 146}]
    assert pick(entries, "Ghostface Playa & Jupiluxe", 146)["url"] == "own"
    # «Topic» — официальный, даже когда имя канала по-русски, а в магазине латиницей.
    entries = [{"url": "album", "channel": "Смоки Мо - Topic", "duration": 200},
               {"url": "single", "channel": "Смоки Мо - Topic", "duration": 133}]
    assert pick(entries, "Smoky Mo", 131)["url"] == "single"
    # Трек с «Topic» вперёд клипа на канале артиста.
    entries = [{"url": "clip", "channel": "GHOST MOUNTAIN", "duration": 134},
               {"url": "audio", "channel": "Ghost Mountain - Topic", "duration": 133}]
    assert pick(entries, "Ghost Mountain", 134)["url"] == "audio"
    # Чужой заливке трёх секунд не прощаем, выдаче без длины не верим.
    assert pick([{"url": "x", "channel": "random", "duration": 149}], "Nemzzz", 146) == {}
    assert pick([{"url": "x", "channel": "Nemzzz"}], "Nemzzz", 146) == {}
    assert pick([{"url": "x", "channel": "random", "duration": 148}], "Nemzzz", 146)["url"] == "x"
    # Без длины из магазина в сеть не ходим.
    assert find("Nemzzz", "GASS", 0) == {}
    print("✓ видео: длина как в магазине, официальный канал первым, тёзки и заливки мимо")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Полные треки к постам о релизах с YouTube (на Mac владельца)")
    parser.add_argument("--dry-run", action="store_true", help="что скачалось бы, без скачивания и отправки")
    parser.add_argument("--install", action="store_true", help="запускать на Mac раз в 10 минут")
    parser.add_argument("--selftest", action="store_true", help="выбор видео, без сети")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.selftest:
        return _selftest()
    if args.install:
        return install()
    config.load_dotenv()
    return run(args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
