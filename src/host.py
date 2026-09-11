"""Закадровый голос клипов.

Раньше здесь была ведущая Крис — нарисованный человек, который стоял
в кадре и читал связь. От лица отказались: одинаковое синтетическое лицо
из ролика в ролик площадки метят как машинный контент, а зритель читает
его как рекламу.
Узнавание, ради которого персонаж заводился, теперь держит плёнка:
кассета на аватаре и обложках (см. src/make_avatar_tape.py) и единая
камкордерная обработка кадра (src/clips.py). Вещь нельзя обвинить
в том, что она сгенерирована, — она и должна быть нарисованной.

Голос пережил персонажа и остался один на все ролики: на экране ярлык
в два слова, в наушниках вся мысль целиком, и это единственный способ
уложить связь в тридцать секунд, не завалив кадр текстом.

Почему синтез, а не запись живым голосом. Ролики выходят три раза в неделю
без участия человека; голос, который нужно записывать руками, остановит
конвейер на первой же занятой неделе. Камкордерная обработка поверх
скрадывает то, чем машинная речь выдаёт себя.

Почему локальный Kokoro, а не облачный синтез. Голос должен быть один
и тот же годами — это последняя примета канала после отказа от лица.
Облако этого не обещает: у Fish Audio обращения по ключу списываются
с баланса и на нуле голос замолкает посреди недели, а тариф и набор
движков там меняются без спроса. Kokoro-ru лежит файлом на диске: те же
82 миллиона параметров скажут то же самое и через год, бесплатно
и без сети. Ключ FISH_AUDIO_KEY остаётся запасным путём.

Ни того, ни другого нет — ролик собирается молча. Голос это украшение,
а не условие выпуска.

    python -m src.host --check         синтез отвечает
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

SYNTH_URL = "https://api.fish.audio/v1/tts"
MODELS_URL = "https://api.fish.audio/model"

# Запасной голос: модель «Девушка» из библиотеки Fish Audio — молодой
# женский, русский, разговорный. Выбран один раз и меняться не должен:
# после отказа от лица голос — единственная живая примета канала. Пусто —
# синтез ответит голосом по умолчанию, и канал зазвучит чужим.
VOICE_ID = "a7b8d6d0a7b84fe093822d5d2877b002"

# Движок синтеза. s1 читает по-русски заметно живее прежних speech-*,
# и на шестнадцати секундах разница слышна сразу.
ENGINE = "s1"


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


def lines(link: dict, *, kind: str = "lineage") -> list[str]:
    """Что голос читает в каждом кадре раскадровки.

    Факты берутся из связи целиком, а не в обрезанном виде: на экране
    ярлык в два слова, в наушниках — вся мысль. Это и есть выигрыш голоса,
    ради него он и заводится.

    Обрамление вокруг фактов жёстко зашито и ничего не утверждает —
    модель к этим фразам не подпускается, выдумывать тут нечему.
    """
    if kind == "facts":
        return fact_lines(link)
    if kind == "news":
        return news_lines(link)
    if kind == "reels":
        # Ролик с живым голосом (src/reels.py): фразы читает владелец, здесь
        # они нужны только для счёта по кадрам. Пауза — пустая фраза.
        return [line.get("say", "") for line in link.get("lines", [])]

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


def news_lines(item: dict) -> list[str]:
    """Закадровый текст новостного ролика: заголовок, три фразы, финал.

    Обрамление зашито, как у фактов, и ничего не утверждает: первую фразу
    голос читает с той же надписи, что стоит на экране, — новость должна
    прозвучать в первые секунды, а не после раскачки. Три средние фразы
    пишет модель строго по заголовку и краткому содержанию новости
    (см. prompts/rubrics/clip_news.md), выдумывать ей тут нечего.

    Фраз шесть — по кадру раскадровки, включая врезку между репликой
    и финалом: кадр без фразы висит молча, фраза без кадра пропадает.
    """
    labels = [label for label in item.get("labels", []) if label]
    said = [f"{_clean(labels[0])}."] if labels else []
    said += [f"{_clean(line)}." for line in item.get("lines", []) if line]
    # Реакция под кадром-врезкой (см. clips.CUT_IMAGE). Ничего не утверждает
    # и потому зашита: оценка новости — единственное, что каналу можно
    # сказать от себя, и говорится она в два слова.
    return said + ["Ну ок.", "Плёнка. Откуда взялся весь тёмный звук."]


def _credentials() -> str:
    return config.secret("FISH_AUDIO_KEY", required=False)


def voices() -> list[tuple[str, str]]:
    """Голосовые модели, доступные по ключу: id и название.

    Нужна ровно затем, чтобы было чем заполнить VOICE_ID: id голоса
    в кабинете глазами не найти, а без него синтез говорит чужим голосом.
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
    """Где лежит своя сборка kokoro-ru — локальный синтез голоса канала.

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

    news = news_lines({"labels": ["отменили тур"], "lines": ["Раз", "Два", "Три"]})
    assert len(news) == 6, news
    assert news[0] == "Отменили тур.", news[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="Закадровый голос клипов")
    parser.add_argument("--check", action="store_true", help="синтез отвечает")
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
            print("  ни одного: запасной голос в кабинете fish.audio не создан")
        else:
            print("\nНужный id — в VOICE_ID (src/host.py).")
        return 0

    if args.say:
        out = config.ROOT / "assets" / "clips" / "проба.wav"
        out.parent.mkdir(parents=True, exist_ok=True)
        path = speak(args.say, out)
        print(f"Готово: {path}" if path else "Синтез недоступен — ролик соберётся молча.")
        return 0 if path else 1

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
