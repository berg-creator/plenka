"""Функция Яндекс Облака: мини-приложение «🎚 Двигать голос» для СВЕДЕНИЯ.

Место голоса в бите бот задаёт ручкой `at` — секундой бита, где встаёт первое
слово. Кнопки «🎯 на дроп» и просьба словами попадают не всегда: голос, выгруженный
не с начала проекта, человек хочет поставить сам, как в CapCut или DAW, — пальцем
по сетке бита, слушая. Для этого нужна страница, а сервера у проекта нет: страницу
и звук отдаёт эта функция, выбор приходит боту сам — `Telegram.WebApp.sendData`
с кнопки обычной клавиатуры шлёт его сообщением в тот же getUpdates дежурства.

Страница и звук — с одного адреса, поэтому без CORS:

- GET без `audio` — страница skleyka_app.html, лежит рядом;
- GET с `audio&f&e&s` — превью сведения: mp3, левый канал — голос без сдвига,
  правый — бит (его собирает `skleyka.run_job` и заливает ботом). Хранилище —
  сам Telegram: `f` — file_id, `e` — срок ссылки (24 ч), `s` — HMAC-SHA256
  ключом SKLEYKA_APP_KEY от «f|e». Без верной подписи функция не качает ничего:
  иначе она была бы открытым скачивателем любых файлов бота.

Токен бота — только в окружении функции, на страницу он не попадает. Ходит функция
только на api.telegram.org: getFile и сам файл, хост зашит. Ответ Функций — до 3,5 МБ,
а тело в base64 толще на треть, поэтому файл больше MAX_BYTES не отдаётся; превью
бот и так ужимает до ~2 МБ. Хранить превью в Object Storage отвергнуто: второй
сервис, второй ключ и уборка старых файлов, а file_id Telegram живёт и так.

Выкладка (ключ и токен — в переменных окружения функции, в репозиторий не попадают):

    python3 -c "import secrets; print(secrets.token_hex(32))"      # ключ подписи
    yc serverless function create --name plenka-skleyka-app
    yc serverless function version create --function-name plenka-skleyka-app \\
      --runtime python312 --entrypoint skleyka_app.handler \\
      --memory 128m --execution-timeout 15s --source-path cloud/ \\
      --environment SKLEYKA_APP_KEY=<ключ>,TELEGRAM_BOT_TOKEN=<токен>
    yc serverless function allow-unauthenticated-invoke plenka-skleyka-app
    gh secret set SKLEYKA_APP_KEY            # тот же ключ — боту в Actions
    yc serverless function get plenka-skleyka-app   # http_invoke_url → config.SKLEYKA_APP_URL

Проверка в браузере без Telegram: адрес функции с `?src=<адрес mp3>&b=0.6&p=0.1&w=2&a=2&l=180`.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.telegram.org/"
TIMEOUT = 6  # у функции 15 с: getFile и сам файл, остальное — на ответ
MAX_BYTES = 2_500_000  # в base64 это 3,33 МБ — под лимитом ответа Функций 3,5 МБ
PAGE = Path(__file__).with_name("skleyka_app.html")


def sign(key: str, file_id: str, expires: int | str) -> str:
    """Подпись ссылки на звук. Та же строка — в src/skleyka.py (боту этот файл не виден)."""
    return hmac.new(key.encode(), f"{file_id}|{expires}".encode(), hashlib.sha256).hexdigest()


def fetch(file_id: str, token: str) -> bytes:
    """Файл бота по file_id: путь — getFile, сам файл — вторым запросом."""
    query = urllib.parse.urlencode({"file_id": file_id})
    with urllib.request.urlopen(f"{API}bot{token}/getFile?{query}", timeout=TIMEOUT) as response:
        path = json.load(response)["result"]["file_path"]
    with urllib.request.urlopen(f"{API}file/bot{token}/{path}", timeout=TIMEOUT) as response:
        return response.read(MAX_BYTES + 1)


def reply(status: int, body: str, content_type: str = "text/plain; charset=utf-8") -> dict:
    return {"statusCode": status, "headers": {"Content-Type": content_type}, "body": body}


def handler(event, context):
    if event.get("httpMethod") != "GET":
        return reply(405, "only GET")
    query = event.get("queryStringParameters") or {}
    if "audio" not in query:
        return reply(200, PAGE.read_text(encoding="utf-8"), "text/html; charset=utf-8")

    file_id, expires, signature = query.get("f", ""), query.get("e", ""), query.get("s", "")
    key = os.environ.get("SKLEYKA_APP_KEY", "")
    # Пустой ключ в окружении — закрыто для всех, а не открыто.
    if not key or not expires.isdigit() or int(expires) < time.time() \
            or not hmac.compare_digest(signature.encode(), sign(key, file_id, expires).encode()):
        return reply(403, "forbidden")
    try:
        body = fetch(file_id, os.environ["TELEGRAM_BOT_TOKEN"])
    except (KeyError, urllib.error.URLError, TimeoutError, ValueError) as error:
        # Текст ошибки urllib несёт адрес вместе с токеном — наружу только тип.
        return reply(502, f"telegram: {type(error).__name__}")
    if len(body) > MAX_BYTES:
        return reply(413, "too big")
    return {"statusCode": 200, "isBase64Encoded": True, "body": base64.b64encode(body).decode(),
            "headers": {"Content-Type": "audio/mpeg", "Cache-Control": "private, max-age=86400"}}
