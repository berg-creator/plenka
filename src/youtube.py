"""Заливка роликов битов на YouTube с отложенным выходом — официальным YouTube Data API.

Владелец 26.10.2026: «раз в неделю открываешь страницу в Chrome, я выбираю аккаунт, ты загружаешь
на отложку». Путь тот же, что в его проекте Dwell Time (youtube.py там): ключ Google «Desktop app»
и разовое согласие в браузере, а пропуск (refresh token) лежит у ПЛЁНКИ свой. Пока проект Google
в режиме проверки, пропуск живёт неделю — поэтому раз в неделю Chrome и открывается заново, и это
не поломка. Ролики канала Count One, залитые этим ключом, вышли открытыми (сверено 26.10.2026),
так что запрета «приватно до аудита» у ключа нет.

Браузерную автоматизацию YouTube Studio не делаем: условия YouTube запрещают заходить
на сервис автоматическими средствами, а Google не пускает вход в управляемый Chrome.
SDK Google не ставим: три запроса — стандартной библиотекой, как в Dwell Time.

Название, описание и теги ролика бита — из каталога бота теми же функциями, что тексты владельцу
(`bity.youtube_title`, `about`, `tags`), поэтому описание обещает ровно то, что есть в боте:
бит без записи в каталоге (`--beat`) не заливается.

Ключ и пропуск — в data/private/youtube/ (не в git): client.json — ключ Google, token.json — пропуск.
Квота ключа общая с Dwell Time: 10 000 единиц в сутки, заливка — 1600, около шести роликов в день
на оба канала.

  python -m src.youtube auth                                  согласие в Chrome: выбрать аккаунт канала
  python -m src.youtube mine                                  последние ролики канала: статус и время выхода
  python -m src.youtube upload ФАЙЛ --beat 8 --at 2026-10-28T18:00 [--thumb ПРЕВЬЮ.jpg]
                                                              залить с выходом в это время по Москве
  python -m src.youtube --selftest                            тело запроса — без сети
"""
from __future__ import annotations

import argparse
import http.server
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config

API = "https://www.googleapis.com/youtube/v3"
UPLOAD = "https://www.googleapis.com/upload/youtube/v3/videos"
SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"
HOME = config.DATA / "private" / "youtube"  # только Мак: согласие владелец даёт в Chrome, Actions не заливает
CLIENT = HOME / "client.json"
TOKEN = HOME / "token.json"
MUSIC = "10"  # категория YouTube «Музыка»
MSK = timezone(timedelta(hours=3))


def fetch(url: str, data=None, headers: dict | None = None, method: str | None = None) -> tuple[dict, dict]:
    request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(request) as response:
            body = response.read()
            return (json.loads(body) if body else {}), dict(response.headers)
    except urllib.error.HTTPError as error:
        sys.exit(f"YouTube: {error.code} {error.reason}\n{error.read().decode(errors='replace')[:800]}")


def form(url: str, fields: dict) -> dict:
    return fetch(url, urllib.parse.urlencode(fields).encode(), {"content-type": "application/x-www-form-urlencoded"})[0]


def client() -> dict:
    if not CLIENT.exists():
        sys.exit(f"Нет {CLIENT}: ключ Google «Desktop app» — тот же, что client_secrets.json в Dwell Time.")
    data = json.loads(CLIENT.read_text())
    return data.get("installed") or data["web"]


def store(token: dict) -> dict:
    old = json.loads(TOKEN.read_text()) if TOKEN.exists() else {}
    token = {**old, **token, "expires_at": time.time() + token.get("expires_in", 3600) - 60}
    TOKEN.write_text(json.dumps(token))
    TOKEN.chmod(0o600)
    return token


def consent(keys: dict) -> dict:
    """Согласие в браузере: Google возвращает код на разовый локальный сервер."""
    got = {}

    class Catch(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            got.update(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
            self.send_response(200)
            self.send_header("content-type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("ПЛЁНКА подключена к YouTube. Вкладку можно закрыть.".encode())

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Catch)
    redirect = f"http://localhost:{server.server_port}"
    # prompt=select_account: владелец выбирает канал ПЛЁНКИ, а не тот, под которым Chrome вошёл
    url = keys["auth_uri"] + "?" + urllib.parse.urlencode(
        {"client_id": keys["client_id"], "redirect_uri": redirect, "response_type": "code", "scope": SCOPES,
         "access_type": "offline", "prompt": "select_account consent"})
    print("Выбери аккаунт канала в Chrome (не открылся — вставь адрес сам):\n" + url)
    try:
        webbrowser.get("chrome").open(url)
    except webbrowser.Error:
        webbrowser.open(url)
    server.handle_request()
    if "code" not in got:
        sys.exit(f"Google не вернул код: {got or 'ничего'}")
    return store(form(keys["token_uri"], {"code": got["code"], "client_id": keys["client_id"],
                                          "client_secret": keys["client_secret"], "redirect_uri": redirect,
                                          "grant_type": "authorization_code"}))


def auth(fresh: bool = False) -> dict:
    keys = client()
    token = None if fresh or not TOKEN.exists() else json.loads(TOKEN.read_text())
    if not token:
        token = consent(keys)
    elif time.time() >= token.get("expires_at", 0):
        try:
            token = store(form(keys["token_uri"], {"refresh_token": token["refresh_token"], "client_id": keys["client_id"],
                                                   "client_secret": keys["client_secret"], "grant_type": "refresh_token"}))
        except SystemExit:  # пропуск истёк (неделя в режиме проверки) — снова согласие, а не отказ
            token = consent(keys)
    return {"authorization": "Bearer " + token["access_token"]}


def api(path: str, params: dict) -> dict:
    return fetch(f"{API}/{path}?" + urllib.parse.urlencode(params), headers=auth())[0]


def moment(at: str) -> str:
    """«2026-10-28T18:00» по Москве → время выхода для YouTube в UTC; прошлое — отказ."""
    when = datetime.fromisoformat(at)
    when = when.replace(tzinfo=MSK) if when.tzinfo is None else when
    if when <= datetime.now(timezone.utc) + timedelta(minutes=15):
        sys.exit(f"Время выхода {at} уже прошло или слишком близко.")
    return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def body(beat_id: str, beat: dict, at: str) -> dict:
    from . import bity  # тяжёлый импорт (PIL, requests) — только для заливки, селфтесту хватает и его

    title, about = bity.youtube_title(beat), bity.about(beat_id, beat)
    if len(title) > 100 or len(about) > 5000:
        sys.exit(f"Название {len(title)} знаков (предел 100) или описание {len(about)} (предел 5000).")
    return {"snippet": {"title": title, "description": about, "tags": bity.tags(beat).split(", "), "categoryId": MUSIC,
                        "defaultLanguage": "ru", "defaultAudioLanguage": "ru"},
            # отложенный выход требует приватного ролика до своего часа
            "status": {"privacyStatus": "private", "publishAt": moment(at), "selfDeclaredMadeForKids": False}}


def upload(path: Path, meta: dict) -> dict:
    size = path.stat().st_size
    _, headers = fetch(UPLOAD + "?" + urllib.parse.urlencode({"uploadType": "resumable", "part": "snippet,status"}),
                       json.dumps(meta).encode(), {**auth(), "content-type": "application/json",
                                                   "x-upload-content-length": str(size), "x-upload-content-type": "video/*"})
    # ponytail: весь файл одним PUT в сессию; начнут рваться — слать кусками с Content-Range в тот же адрес
    print(f"заливаю {path.name}, {size / 1e6:.0f} МБ…")
    with path.open("rb") as file:
        return fetch(headers["Location"], file, {**auth(), "content-length": str(size), "content-type": "video/*"}, "PUT")[0]


def thumbnail(video: str, path: Path) -> None:
    fetch("https://www.googleapis.com/upload/youtube/v3/thumbnails/set?" + urllib.parse.urlencode({"videoId": video}),
          path.read_bytes(), {**auth(), "content-type": "image/png" if path.suffix == ".png" else "image/jpeg"})


def mine(count: int = 15) -> None:
    channel = api("channels", {"part": "contentDetails,snippet", "mine": "true"})["items"][0]
    print("канал:", channel["snippet"]["title"])
    ids = [item["snippet"]["resourceId"]["videoId"] for item in api(
        "playlistItems", {"part": "snippet", "playlistId": channel["contentDetails"]["relatedPlaylists"]["uploads"],
                          "maxResults": count}).get("items", [])]
    for video in api("videos", {"part": "status,snippet", "id": ",".join(ids)}).get("items", []) if ids else []:
        status = video["status"]
        print(video["id"], status["privacyStatus"], status.get("publishAt", ""), video["snippet"]["title"])


def selftest() -> None:
    from . import bity

    beat = {"artists": ["Saluki", "A$AP Rocky"], "title": "Престол", "bpm": "134", "key": "Em", "name": "x.wav"}
    meta = body("8", beat, (datetime.now(MSK) + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M"))
    assert meta["status"]["privacyStatus"] == "private" and meta["status"]["publishAt"].endswith("Z")
    assert meta["snippet"]["title"] == bity.youtube_title(beat) and "saluki type beat" in meta["snippet"]["tags"]
    assert moment("2030-01-01T18:00") == "2030-01-01T15:00:00Z"  # Москва → UTC
    try:
        moment("2020-01-01T18:00")
        raise AssertionError("прошлое время прошло")
    except SystemExit:
        pass
    print("youtube: селфтест прошёл")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ролики битов на YouTube с отложенным выходом")
    parser.add_argument("command", nargs="?", choices=("auth", "mine", "upload"), help="что сделать")
    parser.add_argument("file", nargs="?", type=Path, help="ролик для upload")
    parser.add_argument("--beat", help="номер бита в data/beats.json: название, описание и теги")
    parser.add_argument("--at", help="время выхода по Москве, 2026-10-28T18:00")
    parser.add_argument("--thumb", type=Path, help="превью 1280×720")
    parser.add_argument("--selftest", action="store_true", help="тело запроса без сети")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    if args.command == "auth":
        auth(fresh=True)
        return mine(5)
    if args.command == "mine":
        return mine()
    if args.command != "upload" or not (args.file and args.beat and args.at):
        parser.error("upload ФАЙЛ --beat N --at ВРЕМЯ")
    from . import state

    beat = state.read_json(config.BEATS_FILE, {}).get(args.beat) or sys.exit(f"Бита {args.beat} нет в каталоге")
    video = upload(args.file, body(args.beat, beat, args.at))
    if args.thumb:
        thumbnail(video["id"], args.thumb)
    print(f"готово: https://youtu.be/{video['id']} — выйдет {video['status'].get('publishAt')}")


if __name__ == "__main__":
    main()
