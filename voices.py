"""Голоса героев ролика через ElevenLabs: пробы голосов по описанию (design) или реплики (speak).

Стандартная библиотека, ключ — ELEVENLABS_API_KEY. Режим берётся из поля mode в voices.json.
    python3 voices.py voices.json out
"""
from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error
import urllib.request

API = "https://api.elevenlabs.io"
KEY = os.environ["ELEVENLABS_API_KEY"]


def call(path: str, body: dict | None = None) -> bytes:
    req = urllib.request.Request(
        API + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"xi-api-key": KEY, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{path}: HTTP {e.code} {e.read()[:500]!r}") from None


def design(hero: str, h: dict, out: str) -> list:
    body = {"voice_description": h["describe"], "text": h["sample"], "model_id": "eleven_ttv_v3"}
    try:
        d = json.loads(call("/v1/text-to-voice/design?output_format=mp3_44100_128", body))
    except RuntimeError as e:
        print("design:", e, "— пробую create-previews")
        body.pop("model_id")
        d = json.loads(call("/v1/text-to-voice/create-previews?output_format=mp3_44100_128", body))
    ids = []
    for i, p in enumerate(d["previews"], 1):
        with open(f"{out}/{hero}-{i}.mp3", "wb") as f:
            f.write(base64.b64decode(p["audio_base_64"]))
        ids.append(p["generated_voice_id"])
    return ids


def main() -> None:
    spec, out = json.load(open(sys.argv[1])), sys.argv[2]
    os.makedirs(out, exist_ok=True)
    try:  # у ключа может не быть права user_read — тариф тогда не узнать, но озвучке это не мешает
        sub = json.loads(call("/v1/user/subscription"))
        print("тариф:", sub.get("tier"), "знаков:", sub.get("character_count"), "из", sub.get("character_limit"))
    except RuntimeError as e:
        print("тариф не узнать:", str(e)[:120])
    result, failed = {}, []
    for hero, h in spec["heroes"].items():
        assert 100 <= len(h["sample"]) <= 1000, f"{hero}: образец {len(h['sample'])} знаков, нужно 100–1000"
        try:
            result[hero] = design(hero, h, out)
            print(hero, "ok", len(result[hero]))
        except Exception as e:  # один герой не должен ронять остальных
            failed.append(hero)
            print(hero, "СБОЙ", e)
    json.dump(result, open(f"{out}/ids.json", "w"), ensure_ascii=False, indent=1)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
