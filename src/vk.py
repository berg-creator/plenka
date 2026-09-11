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

from . import config, state

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


# Русские артисты во ВКонтакте часто записаны латиницей: «Кунтейнир» лежит
# там как Kunteynir. Без обратной сборки такие треки не находятся никогда.
_TRANSLIT = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
})

# Скобки с уточнениями и всё, что идёт после «feat» — шум для сверки.
_BRACKETS = re.compile(r"\([^()]*\)|\[[^\]]*\]")
_TAIL = re.compile(r"\b(feat|ft|prod|vs|single|ep|remastered|deluxe|remix)\b.*")
# Перечисление исполнителей: «Slatt Savage, MAYOT», «Token x Pouya», «CORTIS/Juicy J».
_ENUM = re.compile(r"[,/&+×]|\sx\s|\sfeat\.?\s|\sft\.?\s|\svs\.?\s")


def _norm(text: str) -> str:
    text = _BRACKETS.sub(" ", text.casefold())
    text = _TAIL.sub(" ", text)
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text)).strip()


def title_key(track: str) -> str:
    """Название трека, приведённое к сверяемому виду."""
    return _norm(track)


def artist_keys(artist: str) -> set[str]:
    """Все имена из поля исполнителя — по отдельности и в транслите.

    Во ВКонтакте в это поле сваливают всех участников трека, а магазин отдаёт
    только основного. Поэтому сверяем не строку со строкой, а пересечение
    множеств: «MAYOT» должен найтись внутри «Slatt Savage, MAYOT».
    """
    keys: set[str] = set()
    for part in _ENUM.split(_BRACKETS.sub(" ", artist.casefold())):
        name = _norm(part)
        if name:
            keys.add(name)
            keys.add(name.translate(_TRANSLIT))
    return keys


def _audio_index() -> dict[str, list[tuple[set[str], str]]]:
    """Выгрузка плейлиста из data/vk_audio.json: название → кто и что приложить.

    Файл собирается разовой выгрузкой руками, потому что искать треки во
    ВКонтакте бот не может: audio.search сообществам закрыт. Нет файла —
    нет и точного трека, пост уйдёт с плейлистом целиком.
    """
    index: dict[str, list[tuple[set[str], str]]] = {}
    for key, attachment in state.read_json(config.VK_AUDIO_FILE, {}).items():
        if "|" not in key:
            continue
        artist, track = key.split("|", 1)
        index.setdefault(title_key(track), []).append((artist_keys(artist), attachment))
    return index


def track_attachment(artist: str, track: str) -> str:
    """Вложение с конкретным треком, если он есть в выгрузке плейлиста.

    Совпасть должны и название, и исполнитель: одно название встречается
    у разных артистов — «666» есть и у Tommy Wright III, и у Lord Infamous.
    Чужой трек под постом хуже, чем никакого.
    """
    if not (artist and track):
        return ""
    ours = artist_keys(artist)
    for theirs, attachment in _audio_index().get(title_key(track), []):
        if ours & theirs:
            return attachment
    return ""


def post(
    text: str,
    *,
    photo_url: str = "",
    link: str = "",
    artist: str = "",
    track: str = "",
) -> int:
    """Публикует запись от имени сообщества. Возвращает id записи.

    Обложка прикладывается вложением. Если загрузить её не вышло — пост уходит
    без картинки: текст важнее. Ссылка в любом случае остаётся в тексте, но
    карточку с превью ВКонтакте рисует только когда других вложений нет.

    Плейлист сообщества сначала пробуем приложить вложением — тогда под постом
    появляется плеер. Возьмёт ли стена такое вложение от ключа сообщества,
    заранее неизвестно: соседние методы раздела audio для групп закрыты.
    Откажет — тот же пост уходит повторно, со ссылкой на плейлист в тексте.
    Отказ приходит до создания записи, поэтому дубля не будет.
    """
    owner = -group_id()  # у сообществ идентификатор отрицательный
    message = to_plain_text(text)

    photo = _upload_photo(photo_url) if photo_url else ""

    # Трек, о котором пост, точнее подборки целиком. Нет его в выгрузке —
    # ссылаемся на плейлист: он про ту же музыку, просто шире.
    playlist_attachment, playlist_link = playlist()
    exact = track_attachment(artist, track)
    if exact:
        playlist_attachment = exact

    target = link or _first_link(text)
    if target and target not in message:
        message = f"{message}\n\n{target}"

    def send(attachments: list[str], extra_line: str = "") -> int:
        params = {
            "owner_id": owner,
            "from_group": 1,  # запись от имени сообщества, а не от лица админа
            "message": (message + extra_line)[:16000],
        }
        if attachments:
            params["attachments"] = ",".join(attachments)
        return int(_call("wall.post", **params).get("post_id", 0))

    if not playlist_attachment:
        return send([photo] if photo else [])

    try:
        return send([a for a in (photo, playlist_attachment) if a])
    except VKError as exc:
        log.warning("Плейлист вложением не принят (%s) — ставлю ссылкой", exc)
        return send([photo] if photo else [], f"\n\nПодборка канала: {playlist_link}")


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Публикация во ВКонтакте")
    parser.add_argument("--check", action="store_true", help="проверить токен и сообщество")
    parser.add_argument("--test", action="store_true", help="отправить тестовый пост")
    parser.add_argument("--resolve", metavar="ИМЯ", help="узнать id сообщества по адресу")
    args = parser.parse_args()

    config.load_dotenv()

    if args.resolve:
        print(f"id сообщества: {resolve_group_id(args.resolve)}")
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
