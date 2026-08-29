"""Крис — ведущая канала: лицо в кадре и голос за кадром.

Ролик без человека в кадре — это карточка с текстом, и в ленте коротких
роликов она проигрывает всему, где есть лицо. Своё лицо нужно ещё и потому,
что фотографии артистов чужие: канал, собранный только из них, читается как
чужая нарезка. Крис — то единственное, что в каждом ролике одно и то же.

Почему фотографии лежат файлами, а не генерируются на лету. Модель, рисующая
человека по описанию, каждый раз рисует нового: чуть другое лицо, чуть другой
возраст. Для персонажа это смерть — узнавание держится на том, что она
одинаковая. Поэтому кадры делаются руками, по одному описанию из
[prompts/host.md](../prompts/host.md), и складываются сюда навсегда.

Почему синтез, а не запись живым голосом. Ролики выходят три раза в неделю
без участия человека; голос, который нужно записывать руками, остановит
конвейер на первой же занятой неделе. Камкордерная обработка поверх
скрадывает то, чем машинная речь выдаёт себя.

Почему локальный Kokoro, а не облачный синтез. У Крис должен быть один
голос навсегда — такая же примета, как чёлка и капюшон. Облако этого
не обещает: у Fish Audio обращения по ключу списываются с баланса
и на нуле голос замолкает посреди недели, а тариф и набор движков там
меняются без спроса. Kokoro-ru лежит файлом на диске: те же 82 миллиона
параметров скажут то же самое и через год, бесплатно и без сети.
Ключ FISH_AUDIO_KEY остаётся запасным путём и ничего не ломает.

Ни того, ни другого нет — ролик собирается молча. Голос это украшение,
а не условие выпуска.

    python -m src.host --check         кадры на месте, синтез отвечает
    python -m src.host --voices        какие голоса доступны по ключу
    python -m src.host --say "текст"   синтезировать фразу в файл
"""

from __future__ import annotations

import argparse
import os
import subprocess
import shutil
from pathlib import Path

import requests

from . import config

FRAMES_DIR = config.ROOT / "assets" / "host"

SYNTH_URL = "https://api.fish.audio/v1/tts"
MODELS_URL = "https://api.fish.audio/model"

# Голос Крис: модель «Девушка» из библиотеки Fish Audio — молодой женский,
# русский, разговорный. Выбран один раз и меняться не должен: голос у неё
# такая же примета, как чёлка и капюшон. Пусто — синтез ответит голосом
# по умолчанию, и это будет уже не она.
VOICE_ID = "a7b8d6d0a7b84fe093822d5d2877b002"

# Движок синтеза. s1 читает по-русски заметно живее прежних speech-*,
# и на шестнадцати секундах разница слышна сразу.
ENGINE = "s1"


# --- лицо ----------------------------------------------------------------


def frames() -> list[Path]:
    """Все кадры с ведущей. Порядок постоянный — от него зависит выбор.

    Рядом с фотографиями лежат короткие петли `.mp4`: та же Крис, но моргает
    и поворачивает голову. Петля снимается один раз с готовой фотографии
    и после этого ничего не стоит — конвейеру она такой же файл, как jpg,
    и попадает в тот же общий порядок.
    """
    if not FRAMES_DIR.exists():
        return []
    return sorted(
        p for p in FRAMES_DIR.iterdir() if p.suffix.lower() in {".jpg", ".png", ".mp4"}
    )


def frame(index: int) -> Path | None:
    """Кадр по номеру шага раскадровки, по кругу.

    Кадров может быть один — тогда он же и в крючке, и в финале. Это
    не поломка: между ними три другие сцены и разный текст, повтор
    в глаза не бросается. Появится второй файл — сцены разъедутся сами.
    """
    available = frames()
    if not available:
        return None
    return available[index % len(available)]


# --- голос ---------------------------------------------------------------


def _clean(text: str) -> str:
    """Готовит поле связи к произнесению.

    Точка в конце снимается — знаки дописывают фразы ниже. Первая буква
    поднимается в заглавную: поля в базе писались как продолжение
    заголовка и начинаются со строчной, а синтез читает начало строки
    с прописной иначе, чем с середины предложения.
    """
    text = text.strip().rstrip(".").strip()
    return text[:1].upper() + text[1:] if text else text


def lines(link: dict, *, facts: bool = False) -> list[str]:
    """Что Крис говорит в каждом кадре раскадровки.

    Факты берутся из связи целиком, а не в обрезанном виде: на экране
    ярлык в два слова, в наушниках — вся мысль. Это и есть выигрыш голоса,
    ради него он и заводится.

    Обрамление вокруг фактов жёстко зашито и ничего не утверждает —
    модель к этим фразам не подпускается, выдумывать тут нечему.
    """
    if facts:
        return fact_lines(link)

    modern = _clean(link.get("modern", ""))
    ancestor = _clean(link.get("ancestor", ""))
    connection = _clean(link.get("connection", ""))
    return [
        f"{modern}. Откуда это вообще взялось?",
        f"Началось здесь. {ancestor}.",
        f"{connection}.",
        "Плёнка. Откуда взялся весь тёмный звук.",
    ]


def fact_lines(item: dict) -> list[str]:
    """Закадровый текст формата «А ВЫ ЗНАЛИ»: вопрос, факты, финал.

    Фактов в записи три-четыре, поэтому длина списка плавает — раскадровка
    считает её по той же базе (см. `clips.storyboard_facts`), а не по
    константе, иначе кадр остался бы без фразы или фраза без кадра.

    Обрамление вокруг фактов зашито и ничего не утверждает: сами факты
    берутся из data/facts.json как есть, модель к ним не подпускается.
    """
    artist = _clean(item.get("artist", item.get("modern", "")))
    said = [f"{artist}. Что ты о нём не знал."]
    said += [f"{_clean(fact)}." for fact in item.get("facts", []) if fact]
    return said + ["Плёнка. Откуда взялся весь тёмный звук."]


def _credentials() -> str:
    return config.secret("FISH_AUDIO_KEY", required=False)


def voices() -> list[tuple[str, str]]:
    """Голосовые модели, доступные по ключу: id и название.

    Нужна ровно затем, чтобы было чем заполнить VOICE_ID: id голоса
    в кабинете глазами не найти, а без него синтез говорит не Крис.
    """
    response = requests.get(
        MODELS_URL,
        headers={"Authorization": f"Bearer {_credentials()}"},
        params={"self": "true", "page_size": 50},
        timeout=30,
    )
    response.raise_for_status()
    items = response.json().get("items", response.json().get("data", []))
    return [(item.get("_id", item.get("id", "")), item.get("title", "")) for item in items]


def _fish(text: str, dest: Path) -> Path | None:
    if not _credentials():
        return None

    payload = {"text": text, "format": "wav", "normalize": True}
    if VOICE_ID:
        payload["reference_id"] = VOICE_ID

    response = requests.post(
        SYNTH_URL,
        headers={
            "Authorization": f"Bearer {_credentials()}",
            "Content-Type": "application/json",
            # Движок выбирается заголовком, а не полем тела — так у них
            # устроено, и на это легко потратить полчаса.
            "model": ENGINE,
        },
        json=payload,
        timeout=120,
    )
    response.raise_for_status()
    dest.write_bytes(response.content)
    return dest


def kokoro_dir() -> Path:
    """Где лежит своя сборка kokoro-ru — локальный синтез голоса Крис.

    Функцией, а не константой: `.env` читается уже после импорта модуля,
    и путь, посчитанный на импорте, про него бы не узнал. Модель весит
    триста мегабайт, живёт вне репозитория и на другой машине окажется
    в другом месте — отсюда и настройка.
    """
    return Path(os.environ.get("KOKORO_RU_DIR") or Path.home() / "claude-voice-ru")


def _kokoro(text: str, dest: Path) -> Path | None:
    """Синтез локальной моделью. Отдельным процессом — намеренно.

    У kokoro-ru свой venv с торчем на полтора гигабайта, и тянуть его
    в зависимости канала ради четырёх фраз в ролике незачем: пять пакетов
    в requirements.txt держатся не случайно. Модель поднимается за секунды,
    поэтому запуск на фразу ничего не стоит.
    """
    here = kokoro_dir()
    python = here / ".venv" / "bin" / "python"
    script = here / "speak.py"
    if not python.exists() or not script.exists():
        return None

    result = subprocess.run(
        [str(python), str(script), "--wav", str(dest.parent)],
        input=text,
        capture_output=True,
        text=True,
        timeout=300,
    )
    made = result.stdout.strip().splitlines()
    if result.returncode != 0 or not made:
        return None
    # Скрипт нумерует файлы сам, а зовущему нужен путь, который он просил.
    Path(made[0]).replace(dest)
    return dest


def _macos(text: str, dest: Path) -> Path | None:
    """Запасной синтез для локальной сборки: встроенный голос macOS.

    Он заметно машиннее, зато не требует ни ключа, ни сети, ни денег —
    на нём удобно смотреть, как ролик звучит целиком, не тратя лимит.
    В Actions его нет, там всегда работает основной путь.
    """
    say = shutil.which("say")
    if not say:
        return None
    out = dest.with_suffix(".aiff")
    result = subprocess.run(
        [say, "-v", "Milena", "-o", str(out), text], capture_output=True, text=True
    )
    return out if result.returncode == 0 and out.exists() else None


def speak(text: str, dest: Path) -> Path | None:
    """Озвучивает фразу. None — если синтез недоступен, и это не ошибка.

    Формат намеренно не приводится к общему виду: файл всё равно проходит
    через ffmpeg при выравнивании по кадру (см. src/clips.py), там он
    и станет тем, чем нужно.
    """
    # Свой синтез первым: он бесплатный, не ходит в сеть и звучит лучше
    # запасного голоса системы. Fish остаётся вторым — на случай, если
    # модель на этой машине не разложена.
    for synth in (_kokoro, _fish, _macos):
        try:
            path = synth(text, dest)
        except Exception:
            continue
        if path is not None:
            return path
    return None


# --- проверка ------------------------------------------------------------


def _selftest() -> None:
    """Проверка без сети: фразы строятся, кадры выбираются по кругу."""
    spoken = lines({"modern": "Дрифт-фонк.", "ancestor": "Мемфис", "connection": "Связь"})
    assert len(spoken) == 4, spoken
    assert spoken[0] == "Дрифт-фонк. Откуда это вообще взялось?", spoken[0]
    assert ".." not in " ".join(spoken), spoken
    assert spoken[2].startswith("Связь"), spoken[2]

    told = fact_lines({"artist": "Bones", "facts": ["Кассетные деки", "Дешёвая техника"]})
    assert len(told) == 4, told
    assert told[1] == "Кассетные деки.", told[1]

    if frames():
        assert frame(0) == frame(len(frames())), "выбор кадра должен идти по кругу"


def main() -> int:
    parser = argparse.ArgumentParser(description="Ведущая канала: кадры и голос")
    parser.add_argument("--check", action="store_true", help="кадры на месте, синтез отвечает")
    parser.add_argument("--voices", action="store_true", help="какие голоса доступны по ключу")
    parser.add_argument("--say", metavar="ТЕКСТ", help="синтезировать фразу в файл")
    args = parser.parse_args()

    config.load_dotenv()
    _selftest()

    if args.voices:
        if not _credentials():
            print("Не задан FISH_AUDIO_KEY — списка голосов не будет.")
            return 1
        found = voices()
        for voice_id, title in found:
            print(f"  {voice_id}  {title}")
        if not found:
            print("  ни одного: голос Крис пока не создан в кабинете fish.audio")
        else:
            print("\nНужный id — в VOICE_ID (src/host.py).")
        return 0

    if args.say:
        # Не в папку кадров: там лежит лицо канала, черновики ей не место.
        out = config.ROOT / "assets" / "clips" / "проба.wav"
        out.parent.mkdir(parents=True, exist_ok=True)
        path = speak(args.say, out)
        print(f"Готово: {path}" if path else "Синтез недоступен — ролик соберётся молча.")
        return 0 if path else 1

    found = frames()
    print(f"Кадров с ведущей: {len(found)}")
    for path in found:
        print(f"  {path.relative_to(config.ROOT)}")
    if not found:
        print(f"  нет ни одного — как их сделать, написано в prompts/host.md")

    # Проверяем синтезом, а не наличием файлов: сломаться может именно он —
    # переехала модель, разъехался venv, кончился баланс у запасного.
    probe = config.ROOT / "assets" / "clips" / "проба.wav"
    probe.parent.mkdir(parents=True, exist_ok=True)
    try:
        if _kokoro("Проверка связи.", probe) is not None:
            print(f"Голос: kokoro-ru отвечает, {kokoro_dir()}")
            probe.unlink(missing_ok=True)
            return 0
    except Exception as exc:
        print(f"  kokoro-ru не ответил: {str(exc)[:120]}")
    print(f"Голос: своей модели нет в {kokoro_dir()}")

    if not _credentials():
        print("  запасной ключ FISH_AUDIO_KEY тоже не задан", end="")
        print(", локально сработает голос macOS." if shutil.which("say") else ", ролики будут молчать.")
        return 1
    try:
        _fish("Проверка связи.", probe)
    except Exception as exc:
        # 402 — самый частый ответ: у Fish бесплатен только кабинет,
        # обращения по ключу списываются с баланса.
        hint = " — нужно пополнить баланс на fish.audio" if "402" in str(exc) else ""
        print(f"  запасной Fish не отвечает{hint}")
        print(f"  {str(exc)[:120]}")
        print("  пока сработает голос macOS, а в Actions ролики выйдут молча.")
        return 1
    probe.unlink(missing_ok=True)
    print(f"  запасной Fish отвечает, движок {ENGINE}, голос {VOICE_ID or 'по умолчанию'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
