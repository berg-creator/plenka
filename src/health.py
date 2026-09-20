"""Сторож: следит, чтобы канал не встал молча.

Проверяет шесть вещей — не опустела ли очередь, не зависла ли публикация,
не перестал ли поступать материал, не иссякли ли входящие новости,
не пишет ли за основной генератор запасной и не падали ли запуски воркфлоу
за сутки.
Если что-то не так, пишет тебе в личку. Без этого поломка обнаруживается
только когда канал уже неделю молчит.
"""

from __future__ import annotations

import argparse
import os
from datetime import timedelta

from . import config, llm, state, telegram
from .sources import yandex_music


def problems() -> list[str]:
    issues: list[str] = []

    queue = len(list(config.QUEUE.glob("*.json")))
    if queue == 0:
        issues.append("❗ Очередь пуста — публиковать нечего.")
    elif queue < config.QUEUE_MIN:
        issues.append(f"⚠️ В очереди осталось {queue} постов — скоро кончатся.")

    posted = state.read_json(config.POSTED_FILE, {"items": []}).get("items", [])
    if posted:
        last = state._parse(posted[-1].get("published_at", ""))
        if last and state.now() - last > timedelta(hours=config.PUBLISH_INTERVAL_HOURS * 3):
            hours = int((state.now() - last).total_seconds() // 3600)
            issues.append(f"⚠️ Последняя публикация была {hours} ч назад — похоже, публикация встала.")

    if config.INBOX_FILE.exists():
        inbox = list(state.read_jsonl(config.INBOX_FILE))
        fresh = [
            i
            for i in inbox
            if (parsed := state._parse(i.get("collected_at", ""))) is not None
            and state.now() - parsed < timedelta(days=2)
        ]
        if not fresh:
            issues.append("⚠️ За двое суток не нашлось ни одной новинки — проверь источники.")

        # Срочные новости живут только на inbox: встанет сбор — рубрика замолчит,
        # а очередь ещё неделю будет делать вид, что канал в порядке. Сбор ходит
        # раз в 6 часов, поэтому два пустых прогона подряд — уже не совпадение.
        news = [
            i
            for i in inbox
            if i.get("kind") == "news"
            and (parsed := state._parse(i.get("collected_at", ""))) is not None
            and state.now() - parsed < timedelta(hours=12)
        ]
        if not news:
            issues.append("⚠️ Новостей не приходило 12 часов — сбор встал или ленты умерли.")
    else:
        issues.append("❗ Сбор ни разу не отработал: inbox отсутствует.")

    # СВЕДЕНИЕ держится на том, что Яндекс Музыка отвечает без входа. Закроет —
    # бот замолчит молча, а проверить это больше нечем. Спрашиваем, только когда
    # настроена функция Облака: без неё с адресов GitHub Яндекс отвечает 451 всегда.
    if config.secret("YANDEX_FUNCTION_URL", required=False) and not yandex_music.artist("Баста"):
        issues.append("⚠️ Яндекс Музыка не отвечает без входа — СВЕДЕНИЕ не считает.")

    if alarm := spare_alarm(list(state.read_jsonl(config.LLM_LOG))):
        issues.append(alarm)

    if failed := failed_runs():
        issues.append("⚠️ Упали запуски за сутки: " + ", ".join(failed))

    return issues


# Меньше этого числа обращений за сутки — молчим: один отказ основного генератора
# бывает у кого угодно, а в тихие сутки он сам по себе даст «больше половины».
SPARE_MIN = 4


def spare_alarm(rows: list[dict]) -> str:
    """Строка владельцу, если за сутки больше половины текстов написал запасной.

    Переход на запасной молчалив по устройству (llm._generate), а ради ухода
    с ГигаЧата на Gemini всё и затевалось: начни Google отвечать «high demand»,
    канал вернётся к генератору, который выдумывает прошлое артистов, и никто
    об этом не узнает. Порог — половина, а не первый же отказ: одиночный сбой
    сети лечится сам, а сторож пишет только о сломанном.
    """
    spare = llm.fallback()
    if not spare:
        return ""
    day = state.now() - timedelta(days=1)
    fresh = [
        r for r in rows
        if (parsed := state._parse(r.get("at", ""))) is not None and parsed > day
    ]
    if len(fresh) < SPARE_MIN:
        return ""
    if sum(1 for r in fresh if r.get("llm") == spare) * 2 <= len(fresh):
        return ""
    return f"❗ {llm.short_name(llm.provider())} не отвечает, пишет {llm.short_name(spare)}."


def failed_runs() -> list[str]:
    """Красные запуски воркфлоу за сутки: «Бот ×2 (ссылка)».

    Файлы состояния упавший запуск не трогает, поэтому проверки выше его не видят:
    12.09.2026 смена бота падала на каждом посте о релизе, а очередь и публикация
    выглядели здоровыми. Разбор выдумок пропускаем — о своей поломке он пишет сам.
    Без GITHUB_REPOSITORY (локальный запуск) проверка молча пропускается.
    """
    import requests

    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        return []
    token = os.environ.get("GITHUB_TOKEN")
    since = (state.now() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        response = requests.get(
            f"https://api.github.com/repos/{repo}/actions/runs",
            params={"status": "failure", "created": f">={since}", "per_page": 100},
            headers={"Authorization": f"Bearer {token}"} if token else {},
            timeout=30,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        return [f"не узнать у GitHub ({exc})"]
    runs: dict[str, list[str]] = {}
    for run in response.json().get("workflow_runs", []):
        if not run.get("path", "").endswith("review.yml"):
            runs.setdefault(run["name"], []).append(run["html_url"])
    return [f"{name} ×{len(urls)} ({urls[0]})" for name, urls in runs.items()]


def selftest() -> int:
    """Сторож замечает подмену генератора и не паникует от одного отказа."""
    spare = llm.fallback() or "gigachat"
    stamp, old = state.iso(), state.iso(state.now() - timedelta(days=2))

    def rows(fresh_spare: int, fresh_main: int, stale: int = 0) -> list[dict]:
        return (
            [{"at": stamp, "llm": spare}] * fresh_spare
            + [{"at": stamp, "llm": llm.provider()}] * fresh_main
            + [{"at": old, "llm": spare}] * stale
        )

    assert not spare_alarm([]), "пустой журнал — молчим"
    assert not spare_alarm(rows(2, 1)), "трёх обращений мало для вывода"
    assert not spare_alarm(rows(3, 3)), "ровно половина — ещё не поломка"
    assert not spare_alarm(rows(0, 6)), "основной пишет сам — молчим"
    assert not spare_alarm(rows(0, 5, stale=20)), "вчерашние отказы не считаются"
    assert spare_alarm(rows(4, 2)), "запасной написал больше половины — говорим"
    print("✅ Сторож: подмену генератора видит, одиночный отказ терпит.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка состояния канала")
    parser.add_argument("--quiet", action="store_true", help="молчать, если всё в порядке")
    parser.add_argument("--selftest", action="store_true", help="проверить правила сторожа без сети")
    args = parser.parse_args()

    if args.selftest:
        return selftest()

    config.load_dotenv()
    issues = problems()

    queue = len(list(config.QUEUE.glob("*.json")))
    posted = state.read_json(config.POSTED_FILE, {"items": []}).get("items", [])

    if not issues:
        summary = f"✅ Всё работает. В очереди: {queue}. Опубликовано всего: {len(posted)}."
        print(summary)
        if not args.quiet:
            telegram.send_message(config.secret("TELEGRAM_ADMIN_ID"), summary)
        return 0

    report = "<b>ПЛЁНКА — состояние</b>\n\n" + "\n".join(issues)
    report += f"\n\nВ очереди: {queue}. Опубликовано всего: {len(posted)}."
    print(report)
    telegram.send_message(config.secret("TELEGRAM_ADMIN_ID"), report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
