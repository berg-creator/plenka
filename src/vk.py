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
import re

import requests

from . import config

API = "https://api.vk.com/method"
VERSION = "5.199"

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


def post(text: str, *, photo_url: str = "", link: str = "") -> int:
    """Публикует запись от имени сообщества. Возвращает id записи.

    Картинку загрузить нельзя: методы photos.* закрыты для ключа сообщества.
    Вместо этого прикладываем ссылку — ВКонтакте сам вытягивает из неё
    обложку и делает карточку с картинкой.
    """
    owner = -group_id()  # у сообществ идентификатор отрицательный
    message = to_plain_text(text)

    # Ссылку оставляем прямо в тексте: ВКонтакте сам разворачивает первую
    # ссылку в карточку с обложкой. Передавать её через attachments нельзя —
    # там требуется уже загруженное фото, а photos.* ключу сообщества закрыты.
    target = link or _first_link(text)
    if target and target not in message:
        message = f"{message}\n\n{target}"

    result = _call(
        "wall.post",
        owner_id=owner,
        from_group=1,  # запись от имени сообщества, а не от лица админа
        message=message[:16000],
    )
    return int(result.get("post_id", 0))


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
    """Переносит картинку по ссылке на серверы ВКонтакте.

    Внешние адреса ВКонтакте не принимает: файл нужно скачать и загрузить.
    Если что-то пойдёт не так — вернём пустую строку, пост уйдёт без картинки.
    """
    try:
        image = requests.get(url, timeout=30)
        if image.status_code != 200:
            return ""

        server = _call("photos.getWallUploadServer", group_id=group_id())
        upload = requests.post(
            server["upload_url"],
            files={"photo": ("cover.jpg", image.content, "image/jpeg")},
            timeout=60,
        ).json()

        saved = _call(
            "photos.saveWallPhoto",
            group_id=group_id(),
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
