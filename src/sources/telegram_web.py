"""Публичные Telegram-каналы изданий — источник инфоповодов русской сцены.

RSS по русскому рэпу вымер: The Flow, Rap.ru, SRSLY и Hip-Hop.ru ленту
не отдают ни по одному адресу (причины проставлены в data/feeds.json),
а новости публикуют в своих Telegram-каналах. Читаем веб-превью
`t.me/s/<канал>` — обычную страницу, которую Telegram отдаёт всем без
авторизации ради поисковиков, — и разбираем регулярками: разметка превью
проще, чем повод тащить шестую зависимость в requirements.txt.

Отвергнуто: Bot API чужие каналы не читает вовсе, а ВКонтакте требует
личный токен — ключ сообщества отвечает на чужую стену ошибкой 27,
а личный ВК выдаёт руками, и он протухает.

Записи возвращаются в том же виде, что и у `feeds.fetch_recent`, поэтому
`collect.collect_news` разбирает их теми же фильтрами.

Отсюда же берутся сниппеты: паблик сужается полем `only` в data/feeds.json до
постов со своим словом, а `snippet_video` достаёт приложенный ролик, который
ложится под пост канала первым комментарием. Тяжёлого ролика превью не отдаёт,
и его качает `account_video` — входом в аккаунт владельца (решение от 17.09.2026):
аккаунт, в отличие от бота, видит публичный канал целиком. Пакет для входа
(Telethon) добавлен ради этого; без ключей аккаунта всё работает как раньше.

    python -m src.sources.telegram_web --check   какие каналы живы
    python -m src.sources.telegram_web --login   войти в аккаунт, ключ — в .env
    python -m src.sources.telegram_web --login-mac   свой ключ Mac для src/tracks.py
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .. import config
from .feeds import FEEDS_FILE
from .http import get

PREVIEW = "https://t.me/s/{channel}"
# Одиночный пост: ссылку на приложенный файл страница канала отдаёт не всегда,
# а embed-версия отдельного поста — да, и со свежим ключом.
EMBED = "{url}?embed=1&mode=tme"

# Превью отдаёт последние ~20 постов одной страницей: сообщение открывается
# data-post="канал/номер", а дальше внутри лежат текст, время и фото.
MESSAGE_SPLIT = 'class="tgme_widget_message_wrap'
POST_RE = re.compile(r'data-post="([^"]+)"')
# Вложенных div в тексте поста Telegram не делает — закрывающий тег первый же.
TEXT_RE = re.compile(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', re.DOTALL)
TIME_RE = re.compile(r'<time datetime="([^"]+)"')
PHOTO_RE = re.compile(r"background-image:url\('([^']+)'\)")
# Издания выносят суть поста в первый жирный абзац — он и работает заголовком.
BOLD_RE = re.compile(r"<b>(.*?)</b>", re.DOTALL)
BREAK_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")
VIDEO_RE = re.compile(r'<video[^>]*src="([^"]+)"')
# Плеер стоит и у тяжёлого ролика, только вместо файла в нём «Media is too big».
PLAYER = "tgme_widget_message_video_player"
POST_URL_RE = re.compile(r"https://t\.me/(\w+)/(\d+)")
# Больше боту не залить: sendVideo принимает файл до 50 МБ.
BOT_UPLOAD_LIMIT = 50 * 1024 * 1024
ACCOUNT_KEYS = ("TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_SESSION")
# Свой ключ входа у Mac владельца (src/tracks.py): ключ дежурства, открытый
# одновременно с двух машин, Telegram гасит насовсем.
MAC_SESSION = "TELEGRAM_SESSION_MAC"

log = logging.getLogger("telegram_web")


def load_channels() -> list[dict]:
    if not FEEDS_FILE.exists():
        return []
    payload = json.loads(FEEDS_FILE.read_text(encoding="utf-8"))
    return [c for c in payload.get("telegram", []) if c.get("enabled", True)]


def fetch_recent(max_age_hours: int = 30) -> list[dict]:
    """Свежие посты всех включённых каналов."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    items: list[dict] = []

    for channel in load_channels():
        response = get(PREVIEW.format(channel=channel["channel"]), min_interval=1.0)
        if response is None:
            continue
        # `only` сужает канал до одной темы. «РЭП СМИ» иначе принесёт с собой
        # бульварщину про вес и внешность артистов — каналу она запрещена тоном,
        # и отсеивать её потом пришлось бы генерацией, то есть за деньги.
        only = tuple(word.casefold() for word in channel.get("only", ()))
        for post in parse(response.text, channel.get("name", "")):
            if post["_published"] < cutoff:
                continue
            if only and not any(word in post["summary"].casefold() for word in only):
                continue
            items.append({k: v for k, v in post.items() if k != "_published"})
    return items


def parse(page: str, outlet: str) -> list[dict]:
    """Разбирает страницу превью в записи того же вида, что отдаёт RSS."""
    posts: list[dict] = []

    for block in page.split(MESSAGE_SPLIT)[1:]:
        post_id = POST_RE.search(block)
        text = TEXT_RE.search(block)
        stamp = TIME_RE.search(block)
        if not (post_id and text and stamp):
            continue  # служебный блок: без текста, даты или номера поста

        body = _clean(text.group(1))
        if len(body) < 40:
            continue  # подписи вроде «Реклама» и голые ссылки инфоповодом не считаем

        bold = BOLD_RE.search(text.group(1))
        title = _clean(bold.group(1)) if bold else ""
        # Издания начинают пост жирной плашкой-эмодзи («💿», «🚀») — это не заголовок.
        if len(title) < 15:
            title = body.split(". ")[0]
        photo = PHOTO_RE.search(block)

        posts.append(
            {
                "source": "telegram",
                "outlet": outlet,
                "lang": "ru",
                "title": title[:200],
                "url": f"https://t.me/{post_id.group(1)}",
                "summary": body[:600],
                "cover": photo.group(1) if photo else "",
                "published_at": stamp.group(1),
                "external_id": f"tg:{post_id.group(1)}",
                "_published": datetime.fromisoformat(stamp.group(1)),
            }
        )
    return posts


def snippet_video(post_url: str) -> str:
    """Ссылка на видеофайл поста паблика — или пустая строка.

    Так под пост канала попадает сам сниппет: звук лежит не у нас, а в посте,
    откуда пришёл инфоповод. Ключ в ссылке временный, поэтому она берётся
    в момент отправки, а не при сборе — между ними проходят часы.

    Больших файлов превью не отдаёт вовсе, вместо ролика ставит «Media is too
    big» (поймано 12.09.2026 на сниппете ICEGERGERT: 1:42 не дали) — такой
    ролик качает `account_video`.
    """
    found = VIDEO_RE.search(_embed(post_url))
    return found.group(1) if found else ""


def _embed(post_url: str) -> str:
    if not post_url.startswith("https://t.me/"):
        return ""
    response = get(EMBED.format(url=post_url), min_interval=0.5)
    return response.text if response is not None else ""


def account_ready() -> bool:
    return all(os.environ.get(key) for key in ACCOUNT_KEYS)


def snippet_reachable(post_url: str) -> bool:
    """Достанется ли ролик к выходу поста: превью отдаёт его ссылкой, или ролик
    тяжёлый, но есть аккаунт. Не достанется — пост не пишется (urgent.run):
    «показал сниппет» без сниппета пуст, 17.09.2026 так вышел Avenuepluggg.

    Сам аккаунт здесь не трогаем: ключ входа, открытый одновременно с двух
    адресов, Telegram гасит насовсем (AuthKeyDuplicated), а срочное и дежурство
    идут на разных машинах. Качает ролик только дежурство.
    """
    page = _embed(post_url)
    return bool(VIDEO_RE.search(page)) or (PLAYER in page and account_ready())


def _client(session: str = ""):
    from telethon.sessions import StringSession
    from telethon.sync import TelegramClient

    return TelegramClient(StringSession(session), int(os.environ["TELEGRAM_API_ID"]),
                          os.environ["TELEGRAM_API_HASH"])


def account_video(post_url: str, folder: Path) -> dict:
    """Ролик поста через аккаунт владельца: {path, seconds, width, height} или {}.

    Bot API чужой канал не читает («message to copy not found»), а аккаунт видит
    его целиком. Файл скачивается и заливается ботом заново: переслать
    от имени бота нельзя, а пересылка от аккаунта подписала бы комментарий
    не ботом и привела бы в ветку издание.
    """
    found = POST_URL_RE.match(post_url)
    if not (found and account_ready()):
        return {}
    client = None
    try:
        client = _client(os.environ["TELEGRAM_SESSION"])
        client.connect()
        # start() на погасшем ключе спросил бы телефон и повесил дежурство.
        if not client.is_user_authorized():
            log.error("Ключ входа в аккаунт Telegram не действует — войти заново: --login")
            return {}
        message = client.get_messages(found.group(1), ids=int(found.group(2)))
        if not (message and message.video) or message.file.size > BOT_UPLOAD_LIMIT:
            return {}
        path = client.download_media(message, file=str(folder / "snippet.mp4"))
        return {"path": Path(path), "seconds": int(message.file.duration or 0),
                "width": message.file.width or 0, "height": message.file.height or 0}
    except Exception as exc:  # noqa: BLE001 — без ролика под постом останется вопрос
        log.warning("Сниппет через аккаунт не скачался: %s", exc)
        return {}
    finally:
        if client is not None:
            client.disconnect()


def login(key: str = "TELEGRAM_SESSION") -> None:
    """Один раз на компьютере владельца: коды приложения с my.telegram.org,
    телефон, код из Telegram. Ключ входа ложится в .env под именем key
    и на экран не выводится."""
    # Не `key`: переменная цикла затёрла бы имя ключа, и 17.09.2026 ключ Mac лёг
    # в .env второй строкой TELEGRAM_API_HASH, где его никто не читает.
    for name, prompt in (("TELEGRAM_API_ID", "api_id"), ("TELEGRAM_API_HASH", "api_hash")):
        os.environ[name] = os.environ.get(name) or input(f"{prompt} с my.telegram.org: ").strip()
    from getpass import getpass

    # Свои вопросы вместо английских по умолчанию: команду запускает владелец.
    client = _client().start(
        phone=lambda: input("Номер телефона, в виде +79991234567: ").strip(),
        code_callback=lambda: input("Код, который пришёл в Telegram: ").strip(),
        password=lambda: getpass("Облачный пароль Telegram (при вводе не видно): "))
    try:
        name = client.get_me().first_name
        session = client.session.save()
    finally:
        client.disconnect()
    env = config.ROOT / ".env"
    lines = env.read_text(encoding="utf-8").splitlines() if env.exists() else []
    replaced = ("TELEGRAM_API_ID", "TELEGRAM_API_HASH", key)
    lines = [line for line in lines if line.partition("=")[0].strip() not in replaced]
    lines += [f"TELEGRAM_API_ID={os.environ['TELEGRAM_API_ID']}",
              f"TELEGRAM_API_HASH={os.environ['TELEGRAM_API_HASH']}", f"{key}={session}"]
    env.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nВошёл как {name}. Ключ входа сохранён в .env — скажите Claude «готово».")


def _clean(fragment: str) -> str:
    """Разметка превью — в простой текст: переносы строк моделью не читаются."""
    return " ".join(html.unescape(TAG_RE.sub("", BREAK_RE.sub(" ", fragment))).split())


def check() -> int:
    """Проверяет, что каналы живы и отдают посты. Возвращает число мёртвых."""
    dead = 0
    for channel in json.loads(FEEDS_FILE.read_text(encoding="utf-8")).get("telegram", []):
        mark = " " if channel.get("enabled", True) else "×"
        response = get(PREVIEW.format(channel=channel["channel"]), min_interval=0.5)
        posts = parse(response.text, channel.get("name", "")) if response else []
        if not posts:
            print(f" {mark}✗ {channel['name']:<22} постов не отдаёт — @{channel['channel']}")
            dead += 1
        else:
            last = max(p["published_at"] for p in posts)
            print(f" {mark}✓ {channel['name']:<22} {len(posts):>2} постов, последний {last[:16]}")
    return dead


def _selftest() -> None:
    page = (
        'class="tgme_widget_message_wrap"><div data-post="rapruchannel/1">'
        '<a class="tgme_widget_message_photo_wrap" style="background-image:url('
        "'https://cdn.telesco.pe/x.jpg')\"></a>"
        '<div class="tgme_widget_message_text js-message_text" dir="auto">'
        "<b>Артист выпустил альбом</b><br/><br/>Пластинка вышла ночью &laquo;без анонса&raquo;,"
        " и это первый его релиз за три года.</div>"
        '<time datetime="2026-09-12T07:46:23+00:00" class="time">07:46</time>'
        'class="tgme_widget_message_wrap"><div data-post="rapruchannel/2">'
        '<div class="tgme_widget_message_text">Реклама</div>'
        '<time datetime="2026-09-12T08:00:00+00:00" class="time">08:00</time>'
        'class="tgme_widget_message_wrap"><div data-post="rapruchannel/3">'
        '<div class="tgme_widget_message_text"><b>💿</b><br/>Артист объявил дату выхода'
        " пластинки. Первый альбом за три года.</div>"
        '<time datetime="2026-09-12T09:00:00+00:00" class="time">09:00</time>'
    )
    only = (
        'class="tgme_widget_message_wrap"><div data-post="rapsmi/9">'
        '<div class="tgme_widget_message_text">Артист показал сниппет нового трека,'
        " целиком он выйдет осенью. Норм звучит?</div>"
        '<video src="https://cdn4.telesco.pe/file/snip.mp4?token=k"></video>'
        '<time datetime="2026-09-12T10:00:00+00:00" class="time">10:00</time>'
        'class="tgme_widget_message_wrap"><div data-post="rapsmi/10">'
        '<div class="tgme_widget_message_text">Рэпер похудел и показал новое фото'
        " подписчикам своего канала. Норм выглядит?</div>"
        '<time datetime="2026-09-12T11:00:00+00:00" class="time">11:00</time>'
    )
    # only сужает паблик до своей темы: бульварщина про вес каналу запрещена тоном.
    kept = [p for p in parse(only, "РЭП СМИ") if "сниппет" in p["summary"].casefold()]
    assert len(kept) == 1 and "похудел" not in kept[0]["summary"], kept
    assert VIDEO_RE.search(only).group(1).endswith("snip.mp4?token=k")
    assert snippet_video("") == "" and snippet_video("http://example.com/x") == ""
    assert POST_URL_RE.match("https://t.me/rapruchannel/5516").groups() == ("rapruchannel", "5516")

    posts = parse(page, "RAP.RU")
    assert len(posts) == 2, f"разобрались не все посты: {posts}"
    assert posts[1]["title"].startswith("💿 Артист"), posts[1]["title"]
    post = posts[0]
    assert post["title"] == "Артист выпустил альбом", post["title"]
    assert post["url"] == "https://t.me/rapruchannel/1", post["url"]
    assert post["cover"] == "https://cdn.telesco.pe/x.jpg", post["cover"]
    assert "«без анонса»" in post["summary"], post["summary"]
    assert "<" not in post["summary"], post["summary"]
    assert post["external_id"] == "tg:rapruchannel/1", post["external_id"]
    print("✓ разбор превью: заголовок, ссылка, фото, чистый текст и отбор по only")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    elif "--login-mac" in sys.argv:
        config.load_dotenv()
        login(MAC_SESSION)
    elif "--login" in sys.argv:
        config.load_dotenv()
        login()
    elif "--check" in sys.argv:
        print("Проверяю Telegram-каналы:\n")
        print(f"\nМолчащих каналов: {check()}")
    else:
        for item in fetch_recent():
            print(f"[{item['outlet']}] {item['title']}")
