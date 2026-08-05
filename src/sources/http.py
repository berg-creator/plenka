"""Общий HTTP-клиент для всех источников: вежливые паузы, ретраи, единый User-Agent."""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

log = logging.getLogger(__name__)

# Часть изданий (Афиша, Lenta и др.) отдаёт 403/404 на нестандартный User-Agent,
# поэтому по умолчанию представляемся браузером — проверено вживую.
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)

# MusicBrainz, наоборот, требует осмысленный User-Agent с контактом, иначе банит.
BOT_UA = "PlenkaBot/1.0 (music news aggregator)"

_session = requests.Session()
_session.headers.update({"User-Agent": BROWSER_UA})

# Момент последнего запроса к каждому хосту — чтобы соблюдать лимиты.
_last_call: dict[str, float] = {}


def get(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    min_interval: float = 0.0,
    timeout: int = 20,
    retries: int = 3,
    identify_as_bot: bool = False,
) -> requests.Response | None:
    """GET с паузой между запросами к одному хосту и ретраями с backoff.

    Возвращает None, если все попытки провалились — вызывающий код должен это
    пережить: падение одного источника не должно ронять весь сбор.
    """
    host = requests.utils.urlparse(url).netloc

    if min_interval:
        waited = time.monotonic() - _last_call.get(host, 0.0)
        if waited < min_interval:
            time.sleep(min_interval - waited)

    headers = {"User-Agent": BOT_UA} if identify_as_bot else None

    for attempt in range(retries):
        try:
            response = _session.get(url, params=params, timeout=timeout, headers=headers)
            _last_call[host] = time.monotonic()

            if response.status_code == 200:
                return response
            if response.status_code == 404:
                return None  # ретраить бессмысленно
            if response.status_code == 429:
                # Слишком часто — ждём дольше обычного backoff.
                time.sleep(5 * (attempt + 1))
                continue
            log.warning("%s вернул %s", host, response.status_code)
        except requests.RequestException as exc:
            log.warning("%s: ошибка запроса (%s)", host, exc)

        time.sleep(2**attempt)

    log.error("%s: не удалось получить %s после %d попыток", host, url, retries)
    return None


def get_json(url: str, **kwargs: Any) -> Any | None:
    response = get(url, **kwargs)
    if response is None:
        return None
    try:
        return response.json()
    except ValueError:
        log.warning("%s: ответ не является JSON", url)
        return None
