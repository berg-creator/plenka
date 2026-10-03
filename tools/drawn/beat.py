"""Бит под рисованный ролик: ACE-Step 1.5 по строке настроения, без слов и без языковой модели.

Чужой бит в ролик нельзя: аренда beatmaker.tv запрещает синхронизацию с видео, чужой трек ловит
Content ID. Свой — можно. Путь чистый DiT (llm_handler=None, thinking=False): инструменталу без
текста языковая модель не нужна — меньше качать и держать в памяти; темп, тональность и длину
задаём сами, раз угадывать их некому.

Строка настроения — по-английски и про звук: что играет главную тему, какой ритм, какое настроение
и чего нет («not dark, no triplet hi-hat rolls»). Хвост про «с первой секунды, без вступления,
без слов» дописывается сам: ролику нужен бит, который можно резать с любого места.

Запуск (окружением ACE-Step; `drawn.py beat …` зовёт его сам):
    ~/.cache/acestep/repo/.venv/bin/python tools/drawn/beat.py keef-organ \
        "Bouncy hip-hop instrumental, a big warm church organ plays bold chords, punchy kick, claps on the backbeat" \
        --bpm 128 --variants 3
Варианты — data/private/audio/ИМЯ-1.mp3…, слова, по которым они сделаны, — ИМЯ.txt в ~/.cache/acestep/out/.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ACE = Path.home() / ".cache/acestep"
REPO = Path(__file__).resolve().parents[2]
TAIL = ("The main hook plays from the very first second, no build-up, no intro. "
        "Steady energy with no drop, no breakdown, no fade out. "
        "Pure instrumental beat, no vocals, no rapping, no singing, no spoken word.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Свой бит под ролик по строке настроения")
    parser.add_argument("name", help="имя файла без расширения: keef-organ")
    parser.add_argument("mood", help="настроение и звук, по-английски")
    parser.add_argument("--bpm", type=int, default=128, help="темп")
    parser.add_argument("--key", default="C minor", help="тональность")
    parser.add_argument("--seconds", type=float, default=82.0, help="длина")
    parser.add_argument("--variants", type=int, default=3, help="сколько вариантов")
    parser.add_argument("--seed", type=int, default=525011, help="сид первого варианта")
    parser.add_argument("--out", type=Path, default=REPO / "data/private/audio", help="куда положить mp3")
    args = parser.parse_args()

    for proxy in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        os.environ.pop(proxy, None)
    sys.path.insert(0, str(ACE / "repo"))
    from acestep.handler import AceStepHandler
    from acestep.inference import GenerationConfig, GenerationParams, generate_music

    handler = AceStepHandler()
    status, ok = handler.initialize_service(project_root=str(ACE / "repo"), config_path="acestep-v15-turbo",
                                            device="auto", offload_to_cpu=False)
    if not ok:
        print(f"ACE-Step не загрузился: {status}")
        return 1
    caption = f"{args.mood.rstrip('. ')}. Tempo {args.bpm} BPM. {TAIL}"
    work = ACE / "out"
    work.mkdir(exist_ok=True)
    args.out.mkdir(parents=True, exist_ok=True)
    (work / f"{args.name}.txt").write_text(f"bpm={args.bpm} key={args.key} seed={args.seed}\n{caption}\n", encoding="utf-8")
    for n in range(args.variants):
        seed = args.seed + n
        params = GenerationParams(
            task_type="text2music", thinking=False, use_cot_caption=False, use_cot_language=False, use_cot_metas=False,
            caption=caption, lyrics="[Instrumental]", instrumental=True, bpm=args.bpm, keyscale=args.key,
            timesignature="4", vocal_language="unknown", duration=args.seconds, inference_steps=8,
            guidance_scale=1.0, seed=seed)
        config = GenerationConfig(batch_size=1, audio_format="wav", use_random_seed=False, seeds=[seed])
        result = generate_music(handler, None, params=params, config=config, save_dir=str(work))
        if not result.success or not result.audios:
            print(f"{args.name}-{n + 1}: не вышло — {result.status_message}")
            continue
        out = args.out / f"{args.name}-{n + 1}.mp3"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", result.audios[0]["path"], "-b:a", "320k", out], check=True)
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
