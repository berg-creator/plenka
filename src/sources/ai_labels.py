"""Метки ИИ на площадках: чем доказано, что трек сделала нейросеть.

Прослушка «где ИИ» (src/quiz_ai.py) называет в канале один трек нейросетью.
Ошибка здесь — обвинение живого артиста, поэтому доказательство — две метки
сразу, от двух независимых сторон:

- Яндекс Музыка, раздел «О треке»: `GET tracks/<id>/credits`, строка
  «Использование ИИ». Значений три, годится одно — «Трек полностью создан
  с использованием ИИ»: его заявляет правообладатель. «Частично» — живой голос
  на сгенерированном бите, «Возможно» — догадка площадки. Ни то ни другое
  нейросетью трек не делает.
- Deezer: `Album.hasIdentifiedAIContent` — детектор самой площадки. В открытом
  API поля нет, только в GraphQL `pipe.deezer.com/api` с анонимным ключом
  от `auth.deezer.com/login/anonymous`, до 25 альбомов в одном запросе.

С адресов GitHub Яндекс отвечает 451, поэтому, как src/sources/yandex_music.py,
ходим через функцию Яндекс Облака (YANDEX_FUNCTION_URL и KEY), а без неё
(Mac владельца) — напрямую. Запрос свой, а не yandex_music._get и не http.get:
те пишут в лог путь запроса, а в пути — номер трека, и лог открытого
репозитория выдал бы ответ загадки.

Площадка не ответила — исключение `Unknown`, а не «метки нет»: упавшая сеть
не повод выбрасывать раунд из запаса.

    python -m src.sources.ai_labels ЯНДЕКС_ТРЕК DEEZER_АЛЬБОМ   обе метки одного трека
"""

from __future__ import annotations

import sys
import time

import requests

from .. import config

YANDEX = "https://api.music.yandex.net/"
# Подпись python-requests Яндекс встречает 403 — как в yandex_music.
UA = "plenka-bot"
FULL = "Трек полностью создан"
BATCH = 25


class Unknown(RuntimeError):
    """Площадка не ответила: про метку ничего не известно."""


def _yandex(path: str, **params) -> dict:
    url, headers = YANDEX + path, {"User-Agent": UA}
    function = config.secret("YANDEX_FUNCTION_URL", required=False)
    if function:
        url, params = function, {"_path": path, **params}
        headers["X-Plenka-Key"] = config.secret("YANDEX_FUNCTION_KEY", required=False)
    for attempt in range(3):
        try:
            response = requests.get(url, params=params, headers=headers, timeout=20)
            if response.status_code == 200:
                return response.json().get("result") or {}
            # Трек сняли с площадки: ответ окончательный, метки у него больше нет.
            if response.status_code in (400, 404):
                return {}
        except (requests.RequestException, ValueError):
            pass
        time.sleep(2**attempt)
    raise Unknown("Яндекс Музыка не ответила")


def yandex(track_id: str | int) -> str:
    """Значение строки «Использование ИИ» у трека; пустая строка — строки нет."""
    for row in _yandex(f"tracks/{track_id}/credits").get("credits") or []:
        if "ИИ" in row.get("title", ""):
            return row.get("value") or ""
    return ""


def yandex_search(text: str) -> list[dict]:
    """Треки Яндекса по строке поиска. Без `page=0` поиск отвечает 400."""
    return (_yandex("search", text=text, type="track", page=0).get("tracks") or {}).get("results") or []


_jwt = ""


def _graphql(query: str) -> dict:
    global _jwt
    for attempt in range(3):
        try:
            if not _jwt:
                _jwt = requests.get("https://auth.deezer.com/login/anonymous",
                                    params={"jo": "p", "rto": "c", "i": "c"}, timeout=20).json()["jwt"]
            response = requests.post("https://pipe.deezer.com/api", json={"query": query},
                                     headers={"Authorization": f"Bearer {_jwt}"}, timeout=20)
            answer = response.json()
            # Ошибки GraphQL приходят с кодом 200 и пустым альбомом. «Альбома нет» — ответ
            # (снятый альбом без метки), а всё прочее — сбой: анонимный ключ живёт
            # минут шесть, и 27.09.2026 истёкший ключ выдал 45 живых меток за снятые.
            failed = [e for e in answer.get("errors") or [] if e.get("type") != "AlbumNotFoundError"]
            if response.status_code == 200 and answer.get("data") is not None and not failed:
                return answer["data"]
        except (requests.RequestException, ValueError, KeyError):
            pass
        _jwt = ""  # ключ мог истечь — следующая попытка возьмёт новый
        time.sleep(2**attempt)
    raise Unknown("Deezer не ответил")


def deezer(album_ids: list) -> dict[str, dict]:
    """{альбом: {"ai": True/False/None, "date": "ГГГГ-ММ-ДД", "explicit": bool}}.

    Снятый альбом GraphQL отдаёт пустым с ошибкой AlbumNotFoundError — это «метки нет»,
    а не сбой.
    """
    ids, out = [str(a) for a in dict.fromkeys(album_ids) if a], {}
    for start in range(0, len(ids), BATCH):
        chunk = ids[start:start + BATCH]
        query = "{" + " ".join(f'a{i}:album(albumId:"{a}"){{hasIdentifiedAIContent releaseDate isExplicit}}'
                               for i, a in enumerate(chunk)) + "}"
        data = _graphql(query)
        for i, album in enumerate(chunk):
            got = data.get(f"a{i}") or {}
            out[album] = {"ai": got.get("hasIdentifiedAIContent"), "date": (got.get("releaseDate") or "")[:10],
                          "explicit": bool(got.get("isExplicit"))}
    return out


def confirmed(ya_track: str | int, dz_album: str | int) -> bool:
    """Обе метки на месте: Яндекс — «полностью», Deezer — True. Сбой — Unknown."""
    if not yandex(ya_track).startswith(FULL):
        return False
    return deezer([dz_album]).get(str(dz_album), {}).get("ai") is True


if __name__ == "__main__":
    config.load_dotenv()
    ya, dz = sys.argv[1:3]
    print(f"Яндекс: {yandex(ya) or 'метки нет'}")
    print(f"Deezer: {deezer([dz]).get(dz)}")
