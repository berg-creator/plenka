"""Публикация во ВКонтакте.

Про токен — важное. ВКонтакте убрал из интерфейса тип «Standalone-приложение»,
и классический способ с OAuth больше не доступен. Зато для публикации в
собственное сообщество достаточно **ключа доступа сообщества**: он выдаётся
прямо в настройках группы (Управление → Работа с API), приложение создавать
не нужно.

Ключу нужны права «Стена» и «Фотографии». Токены нового VK ID (начинаются
с vk2.) на стену сообщества не публикуют — нужен именно ключ сообщества.

    python -m src.vk --check           проверить токен и доступ к сообществу
    python -m src.vk --test            отправить тестовый пост
"""

from __future__ import annotations

import argparse
import logging
import os
import re
from pathlib import Path

import requests

from . import config

log = logging.getLogger("vk")

API = "https://api.vk.com/method"
VERSION = "5.199"

# Плейлист сообщества в адресе выглядит так:
#   vk.ru/audios-240682204?z=audio_playlist-240682204_1_e3cfff80617c147439
# Хвост после второго подчёркивания — ключ доступа, без него плейлист
# посторонним не открывается, поэтому переносим адрес целиком.
PLAYLIST_RE = re.compile(r"audio_playlist(-?\d+)_(\d+)(?:_([0-9a-f]+))?")

# HTML-разметка Telegram во ВКонтакте не поддерживается — там обычный текст.
TAG_RE = re.compile(r"<[^>]+>")
LINK_RE = re.compile(r'<a\s+href="([^"]+)"[^>]*>(.*?)</a>', re.DOTALL | re.IGNORECASE)


class VKError(RuntimeError):
    pass


def _call(method: str, **params) -> dict:
    params.update({"access_token": config.secret("VK_TOKEN"), "v": VERSION})
    response = requests.post(f"{API}/{method}", data=params, timeout=30)

    try:
        data = response.json()
    except ValueError:
        raise VKError(f"{method}: ответ не JSON (код {response.status_code})")

    if "error" in data:
        error = data["error"]
        raise VKError(
            f"{method}: {error.get('error_msg', 'ошибка')} "
            f"(код {error.get('error_code')})"
        )
    return data.get("response", {})


def to_plain_text(html: str) -> str:
    """Переводит разметку Telegram в текст, понятный ВКонтакте.

    Ссылки разворачиваются в «текст — адрес»: во ВКонтакте нет встроенных
    гиперссылок в тексте поста, и голый адрес читается лучше, чем потерянная
    ссылка.
    """
    text = LINK_RE.sub(lambda m: f"{m.group(2).strip()}: {m.group(1)}", html)
    text = TAG_RE.sub("", text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def resolve_group_id(screen_name: str) -> int:
    """Числовой id сообщества по короткому имени."""
    clean = screen_name.strip().lstrip("@").replace("https://vk.com/", "").strip("/")
    result = _call("groups.getById", group_ids=clean)
    # В новых версиях API ответ приходит объектом со списком groups.
    groups = result.get("groups") if isinstance(result, dict) else result
    if not groups:
        raise VKError(f"Сообщество «{clean}» не найдено")
    return int(groups[0]["id"])


def group_id() -> int:
    raw = config.secret("VK_GROUP_ID").strip()
    if raw.lstrip("-").isdigit():
        return abs(int(raw))
    return resolve_group_id(raw)


def playlist() -> tuple[str, str]:
    """Плейлист сообщества: (вложение, ссылка). Пусто, если не задан.

    Задаётся переменной VK_PLAYLIST — туда кладётся адрес плейлиста из строки
    браузера целиком. Плейлист ведётся руками: раздел audio.* сообществам
    закрыт наглухо, бот не может ни искать треки, ни добавлять их, ни даже
    посмотреть, что внутри. Всё, что ему доступно, — сослаться на подборку.
    """
    match = PLAYLIST_RE.search(os.environ.get("VK_PLAYLIST", "").strip())
    if not match:
        return "", ""
    owner, number, key = match.groups()
    tail = f"{owner}_{number}" + (f"_{key}" if key else "")
    return f"audio_playlist{tail}", f"https://vk.com/music/playlist/{tail}"


def post(
    text: str,
    *,
    photo_url: str = "",
    link: str = "",
    artist: str = "",
    track: str = "",
) -> int:
    """Публикует запись от имени сообщества. Возвращает id записи.

    Обложка идёт вложением. Метод из документации (`photos.getWallUploadServer`)
    ключу сообщества закрыт — «method is unavailable with group auth», код 27,
    и правом `photos` не лечится. Зато открыт сервер сообщений, а сохранённое
    им фото стена принимает: это единственный путь без второго ключа от личного
    аккаунта. Не вышло — пост уходит без картинки, текст важнее.

    Музыку вложить нельзя никак: `wall.post` отвечает «Required a combination
    of photo attachments for audio attachment» и на трек, и на плейлист, и с фото,
    и без него (проверено вживую 12.09.2026 на отложенной записи). Поэтому
    подборка сообщества уходит ссылкой в тексте — жать одно нажатие, как и плеер.

    artist и track остаются в подписи ради вызывающей стороны (src/publish.py):
    пост знает, о ком он, а чем это пригодится во ВКонтакте, решать здесь.
    """
    owner = -group_id()  # у сообществ идентификатор отрицательный
    message = to_plain_text(text)

    photo = _upload_photo(photo_url) if photo_url else ""

    target = link or _first_link(text)
    if target and target not in message:
        message = f"{message}\n\n{target}"

    _, playlist_link = playlist()
    if playlist_link:
        message = f"{message}\n\nПодборка канала: {playlist_link}"

    params = {
        "owner_id": owner,
        "from_group": 1,  # запись от имени сообщества, а не от лица админа
        "message": message[:16000],
    }
    if photo:
        params["attachments"] = photo
    return int(_call("wall.post", **params).get("post_id", 0))


def _first_link(html: str) -> str:
    """Первая ссылка из поста — она и станет карточкой с обложкой."""
    match = re.search(r'<a\s+href="([^"]+)"', html, re.IGNORECASE)
    if match:
        return match.group(1)
    match = re.search(r"https?://\S+", html)
    return match.group(0).rstrip(".,;)") if match else ""


def _drop_link(text: str, url: str) -> str:
    """Убирает из текста строку с адресом, который ушёл вложением."""
    lines = [line for line in text.split("\n") if url not in line]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _upload_photo(url: str) -> str:
    """Переносит картинку по ссылке на серверы ВКонтакте. Возвращает вложение
    вида `photo-123_456` или пустую строку, если не вышло.

    Загрузка идёт через сервер сообщений, а не через `photos.getWallUploadServer`,
    как просит документация: стеновой метод для групповой авторизации закрыт
    наглухо — «method is unavailable with group auth», код 27, и правом `photos`
    у токена это не лечится. Серверу сообщений групповой ключ доступен, при этом
    `photos.saveMessagesPhoto` сохраняет файл владельцем-сообществом, и стена
    такое вложение принимает. Обходной путь, но единственный без второго ключа
    от личного аккаунта.

    Внешние адреса ВКонтакте не принимает: файл нужно скачать и залить.
    """
    try:
        image = requests.get(url, timeout=30)
        if image.status_code != 200:
            return ""

        server = _call("photos.getMessagesUploadServer")
        upload = requests.post(
            server["upload_url"],
            files={"photo": ("cover.jpg", image.content, "image/jpeg")},
            timeout=60,
        ).json()

        saved = _call(
            "photos.saveMessagesPhoto",
            photo=upload["photo"],
            server=upload["server"],
            hash=upload["hash"],
        )
        item = saved[0] if isinstance(saved, list) else saved.get("items", [{}])[0]
        return f"photo{item['owner_id']}_{item['id']}"
    except (VKError, requests.RequestException, KeyError, IndexError):
        return ""


def pin(post_id: int) -> None:
    """Закрепляет пост в сообществе — он показывается первым на стене."""
    _call("wall.pin", owner_id=-group_id(), post_id=post_id)


def upload_video(path: Path, *, name: str, description: str = "") -> str:
    """Заливает готовый ролик в сообщество. Возвращает `видео-owner_id_video_id`.

    **Групповым ключом не работает — проверено.** `video.save` отвечает
    «User authorization failed» (код 5) при любом наборе параметров:
    с `group_id`, без него, с `owner_id`, с `wallpost`. Право «Видео»
    в настройках ключа на это не влияет — метод требует пользовательский
    токен. То же семейство ограничений, что у `wall.get` и `photos.getAll`.

    Функция оставлена рабочей на случай, если появится пользовательский
    ключ: с ним всё описанное ниже верно. Клипы пока доставляются в Telegram
    и перекладываются во ВКонтакте руками — см. `src/clips.py`, `deliver`.

    Порядок двухшаговый, как и у фотографий: `video.save` выдаёт одноразовый
    адрес для загрузки и сразу заводит запись, файл уходит вторым запросом.
    Из этого следует важное: запись появляется в сообществе **до** того, как
    файл долетел. Оборвётся загрузка — останется пустой ролик, а удалить его
    групповым ключом нельзя, как и стеновые записи. Поэтому вызывать метод
    стоит только на собранном и проверенном файле.

    Попадёт ролик в Клипы или в обычные видео, решает сама платформа по
    формату и длине — отдельного параметра для этого в открытом API нет.
    Вертикальные короткие ролики обычно уходят в Клипы.
    """
    gid = group_id()
    slot = _call(
        "video.save",
        group_id=gid,
        name=name[:128],
        description=description[:1000],
        wallpost=0,
    )

    with path.open("rb") as handle:
        response = requests.post(
            slot["upload_url"],
            files={"video_file": (path.name, handle, "video/mp4")},
            timeout=300,
        )

    if response.status_code != 200:
        raise VKError(f"загрузка видео не удалась: код {response.status_code}")

    owner = slot.get("owner_id", -gid)
    return f"video{owner}_{slot.get('video_id', '')}"


def check() -> str:
    """Проверяет токен и доступ к сообществу.

    Работает и с ключом сообщества, и с пользовательским: у первого нет
    владельца-человека, поэтому users.get может не отвечать — это не ошибка.
    """
    lines: list[str] = []

    try:
        me = _call("users.get")
        items = me if isinstance(me, list) else me.get("items", [])
        user = items[0] if items else {}
        name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
        # Ключ сообщества отвечает на users.get пустым списком — это не ошибка.
        lines.append(
            f"Тип токена: пользовательский ({name})" if name else "Тип токена: ключ сообщества"
        )
    except (VKError, IndexError, KeyError, AttributeError):
        lines.append("Тип токена: ключ сообщества")

    gid = group_id()
    info = _call("groups.getById", group_ids=str(gid))
    groups = info.get("groups") if isinstance(info, dict) else info
    title = groups[0].get("name", "?") if groups else "?"
    lines.append(f"Сообщество: «{title}» (id {gid})")

    return "\n".join(lines)


def _selftest() -> None:
    """Из чего собирается запись: без сети, с подменённым API."""
    import os
    import sys
    from unittest import mock

    text = ('<b>SODA LUV ВЫПУСТИЛ АЛЬБОМ</b>\n\nДевять вещей, 23 минуты.\n\n'
            '▸ <a href="https://www.deezer.com/album/1075976302">Слушать в Deezer</a>')
    sent: dict = {}

    def fake_call(method: str, **params):
        if method == "groups.getById":
            return {"groups": [{"id": 240682204}]}
        sent.update(params)
        return {"post_id": 7}

    playlist_url = "https://vk.ru/audios-240682204?z=audio_playlist-240682204_1_e3cfff80617c147439"
    with (mock.patch.dict(os.environ, {"VK_PLAYLIST": playlist_url, "VK_GROUP": "240682204"}),
          mock.patch.object(sys.modules[__name__], "_call", fake_call),
          mock.patch.object(sys.modules[__name__], "_upload_photo", lambda url: "photo-240682204_1")):
        assert post(text, photo_url="https://x/cover.jpg") == 7

    message = sent["message"]
    assert "<b>" not in message, message
    # Ссылка на релиз и подборка сообщества — обе в тексте: музыку вложением
    # стена от ключа сообщества не берёт вовсе.
    assert "deezer.com/album/1075976302" in message, message
    assert "vk.com/music/playlist/-240682204_1_" in message, message
    # Обложка — единственное вложение, которое доходит.
    assert sent["attachments"] == "photo-240682204_1", sent
    assert sent["from_group"] == 1 and sent["owner_id"] == -240682204, sent
    print("ВКонтакте: обложка вложением, релиз и подборка ссылками в тексте")


def main() -> int:
    parser = argparse.ArgumentParser(description="Публикация во ВКонтакте")
    parser.add_argument("--selftest", action="store_true",
                        help="проверить сборку записи без сети")
    parser.add_argument("--check", action="store_true", help="проверить токен и сообщество")
    parser.add_argument("--test", action="store_true", help="отправить тестовый пост")
    parser.add_argument("--resolve", metavar="ИМЯ", help="узнать id сообщества по адресу")
    args = parser.parse_args()

    config.load_dotenv()

    if args.resolve:
        print(f"id сообщества: {resolve_group_id(args.resolve)}")
        return 0

    if args.selftest:
        _selftest()
        return 0

    if args.check:
        print(check())
        return 0

    if args.test:
        post_id = post("Проверка связи. Это тестовая запись, её можно удалить.")
        print(f"Опубликовано, id записи: {post_id}")
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
