"""Функция Яндекс Облака: мини-приложение «🎚 Двигать голос» для СВЕДЕНИЯ.

Место голоса в бите бот задаёт ручкой `at` — секундой бита, где встаёт первое
слово. Кнопки «🎯 на дроп» и просьба словами попадают не всегда: голос, выгруженный
не с начала проекта, человек хочет поставить сам, как в CapCut или DAW, — пальцем
по сетке бита, слушая. Для этого нужна страница, а сервера у проекта нет: страницу
и звук отдаёт эта функция, выбор приходит боту сам — `Telegram.WebApp.sendData`
с кнопки обычной клавиатуры шлёт его сообщением в тот же getUpdates дежурства.

Страница и звук — с одного адреса, поэтому без CORS:

- GET без `audio` — страница skleyka_app.html, лежит рядом;
- POST с `put&f&e&s` — бот кладёт превью сведения: mp3, левый канал — голос без
  сдвига, правый — бит (его собирает `skleyka.run_job`);
- GET с `audio&f&e&s` — страница забирает это превью.

`f` — случайное имя файла от бота, `e` — срок ссылки (24 ч), `s` — HMAC-SHA256
ключом SKLEYKA_APP_KEY от «f|e», а для записи — от «put:f|e»: подпись на чтение
лежит в адресе страницы, и записывать ею нельзя. Без верной подписи функция
не пишет и не отдаёт ничего.

Хранилище — бакет plenka-skleyka-previews, смонтированный в версию: закрытый,
файлы удаляет правило через двое суток. Раньше функция брала превью у Telegram
по file_id, но 28.09.2026 оказалось, что из Облака Яндекса api.telegram.org
не отвечает — соединение висит до тайм-аута. Бот же живёт на GitHub, откуда
Telegram открыт, поэтому превью приносит он сам. Ответ Функций — до 3,5 МБ,
а тело в base64 толще на треть: файл больше MAX_BYTES не принимается, превью
бот и так ужимает до ~2 МБ.

Выкладка (ключ — в переменной окружения функции, в репозиторий не попадает):

    python3 -c "import secrets; print(secrets.token_hex(32))"      # ключ подписи
    yc storage bucket create --name plenka-skleyka-previews
    yc storage bucket update --name plenka-skleyka-previews --lifecycle-rules \\
      '{"lifecycleRules":[{"id":"old","enabled":true,"filter":{},"expiration":{"days":"2"}}]}'
    yc iam service-account create --name plenka-skleyka-app   # storage.editor на каталог
    yc serverless function create --name plenka-skleyka-app
    yc serverless function version create --function-name plenka-skleyka-app \\
      --runtime python312 --entrypoint skleyka_app.handler \\
      --memory 128m --execution-timeout 15s --source-path cloud/ \\
      --service-account-id <id plenka-skleyka-app> \\
      --mount type=object-storage,mount-point=previews,bucket=plenka-skleyka-previews,mode=rw \\
      --environment SKLEYKA_APP_KEY=<ключ>
    yc serverless function allow-unauthenticated-invoke plenka-skleyka-app
    gh secret set SKLEYKA_APP_KEY            # тот же ключ — боту в Actions
    yc serverless function get plenka-skleyka-app   # http_invoke_url → config.SKLEYKA_APP_URL

Проверка в браузере без Telegram: адрес функции с `?src=<адрес mp3>&b=0.6&p=0.1&w=2&a=2&l=180`.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import time
from pathlib import Path

STORE = Path("/function/storage/previews")  # бакет plenka-skleyka-previews
NAME = re.compile(r"[A-Za-z0-9_-]{16,64}")  # имя от бота; иначе «../» ушёл бы из бакета
MAX_BYTES = 2_500_000  # в base64 это 3,33 МБ — под лимитом Функций 3,5 МБ
PAGE = Path(__file__).with_name("skleyka_app.html")


def sign(key: str, name: str, expires: int | str) -> str:
    """Подпись ссылки на звук. Та же строка — в src/skleyka.py (боту этот файл не виден)."""
    return hmac.new(key.encode(), f"{name}|{expires}".encode(), hashlib.sha256).hexdigest()


def reply(status: int, body: str, content_type: str = "text/plain; charset=utf-8") -> dict:
    return {"statusCode": status, "headers": {"Content-Type": content_type}, "body": body}


def handler(event, context):
    method = event.get("httpMethod")
    query = event.get("queryStringParameters") or {}
    if method == "GET" and "audio" not in query:
        return reply(200, PAGE.read_text(encoding="utf-8"), "text/html; charset=utf-8")
    if method not in ("GET", "POST"):
        return reply(405, "only GET and POST")

    name, expires, signature = query.get("f", ""), query.get("e", ""), query.get("s", "")
    key = os.environ.get("SKLEYKA_APP_KEY", "")
    signed = name if method == "GET" else "put:" + name
    # Пустой ключ в окружении — закрыто для всех, а не открыто.
    if not key or not NAME.fullmatch(name) or not expires.isdigit() or int(expires) < time.time() \
            or not hmac.compare_digest(signature.encode(), sign(key, signed, expires).encode()):
        return reply(403, "forbidden")
    path = STORE / f"{name}.mp3"
    if method == "POST":
        body = event.get("body") or ""
        data = base64.b64decode(body) if event.get("isBase64Encoded") else body.encode()
        if len(data) > MAX_BYTES:
            return reply(413, "too big")
        path.write_bytes(data)
        return reply(200, "ok")
    if not path.exists():
        return reply(404, "gone")
    return {"statusCode": 200, "isBase64Encoded": True, "body": base64.b64encode(path.read_bytes()).decode(),
            "headers": {"Content-Type": "audio/mpeg", "Cache-Control": "private, max-age=86400"}}
