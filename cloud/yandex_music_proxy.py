"""Функция Яндекс Облака: запросы бота к api.music.yandex.net с российского адреса.

С серверов GitHub Яндекс Музыка отвечает 451 (brief-info — 403): адреса США
она не обслуживает, а бот живёт в GitHub Actions. Функция в Облаке стоит
в России, берёт у бота путь и параметры запроса, сама идёт к Яндексу и отдаёт
ответ как есть — код, тип и тело. Первый миллион вызовов в месяц бесплатный.
Прокси за деньги и VPS отвергнуты: платить помесячно за то, что бесплатно,
а телефон и Mac владельца спят, когда человек кидает ссылку.

Функция публичная, но без заголовка X-Plenka-Key с верным ключом отвечает 403.
Приватную из Actions пришлось бы звать с IAM-токеном сервисного аккаунта: хранить
его ключ, подписывать JWT и менять токен раз в 12 часов. Публичная с ключом —
один секрет и один заголовок в запросе. Ходит она только GET и только
на api.music.yandex.net: чужой адрес подставить некуда, хост зашит.

Вызов: путь Яндекса — параметром _path, остальные параметры — как у Яндекса:

    curl -H "X-Plenka-Key: $KEY" \\
      "$URL?_path=search&type=artist&text=Баста"

Выкладка (ключ — в переменной окружения функции, в репозиторий не попадает):

    yc serverless function create --name plenka-yandex-music
    yc serverless function version create --function-name plenka-yandex-music \\
      --runtime python312 --entrypoint yandex_music_proxy.handler \\
      --memory 128m --execution-timeout 10s --source-path cloud/ \\
      --environment PLENKA_KEY=<ключ>
    yc serverless function allow-unauthenticated-invoke plenka-yandex-music
"""

from __future__ import annotations

import hmac
import os
import urllib.error
import urllib.parse
import urllib.request

UPSTREAM = "https://api.music.yandex.net/"
TIMEOUT = 8  # у функции 10 с, два оставляем на ответ боту


def reply(status: int, body: str, content_type: str = "text/plain; charset=utf-8") -> dict:
    return {"statusCode": status, "headers": {"Content-Type": content_type}, "body": body}


def handler(event, context):
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    key = os.environ.get("PLENKA_KEY", "")
    # Пустой ключ в окружении — закрыто для всех, а не открыто.
    if not key or not hmac.compare_digest(headers.get("x-plenka-key", "").encode(), key.encode()):
        return reply(403, "forbidden")
    if event.get("httpMethod") != "GET":
        return reply(405, "only GET")

    params = dict(event.get("multiValueQueryStringParameters") or {})
    path = (params.pop("_path", None) or [""])[0].lstrip("/")
    if not path:
        return reply(400, "_path is required")
    url = UPSTREAM + urllib.parse.quote(path, safe="/")
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)

    request = urllib.request.Request(url, headers={"User-Agent": "plenka-bot"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            status, body, ctype = response.status, response.read(), response.headers.get("Content-Type")
    except urllib.error.HTTPError as error:
        status, body, ctype = error.code, error.read(), error.headers.get("Content-Type")
    except (urllib.error.URLError, TimeoutError) as error:
        return reply(502, f"upstream: {error}")
    return reply(status, body.decode("utf-8", "replace"), ctype or "application/json")
