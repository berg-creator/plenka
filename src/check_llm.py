"""Проверка генератора текстов: доступен ли, какие модели видит, что пишет.

    python -m src.check_llm            проверить связь и показать модели
    python -m src.check_llm --sample   ещё и сгенерировать пробный пост
"""

from __future__ import annotations

import argparse

from . import config, llm
from .providers import gigachat


def check_gigachat(required: bool) -> int:
    """Связь со Сбером и список моделей по ключу.

    required=False — GigaChat здесь только запасной: его поломка означает,
    что канал остался без подстраховки, но не что проверка провалена.
    """
    try:
        models = gigachat.available_models()
    except Exception as exc:
        print(f"✗ GigaChat недоступен: {exc}")
        print("  Проверь GIGACHAT_CREDENTIALS в .env — это «Ключ авторизации» "
              "из проекта GigaChat API на developers.sber.ru")
        if required:
            return 1
        print("  Это запасной генератор: канал работает, но подстраховки нет.")
        return 0

    if not models:
        print("GigaChat: соединение установлено, список моделей пуст.")
        return 0

    print("GigaChat, доступные модели:")
    for name in models:
        mark = "→" if name == gigachat.model_name() else " "
        print(f"  {mark} {name}")
    if gigachat.model_name() not in models:
        print(f"\n⚠️ Модель {gigachat.model_name()} недоступна по твоему ключу.")
        print("   Впиши в .env одну из списка: GIGACHAT_MODEL=...")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка генератора текстов")
    parser.add_argument("--sample", action="store_true", help="сгенерировать пробный пост")
    args = parser.parse_args()

    config.load_dotenv()
    print(f"Генератор: {llm.describe()}\n")

    if "gigachat" in (llm.provider(), llm.fallback()):
        if check_gigachat(required=llm.provider() == "gigachat"):
            return 1

    if not args.sample:
        print("\nЧтобы проверить качество текста: python -m src.check_llm --sample")
        return 0

    print("\nГенерирую пробный пост рубрики ОТКУДА НОГИ...\n")
    sample = {
        "modern": "Дрифт-фонк, который играет в каждом втором ролике с машинами",
        "ancestor": "Мемфисский рэп начала девяностых",
        "connection": "замедленный темп, перегруженный бас, шипение кассеты",
        "facts": [
            "Мемфисские артисты записывали музыку на кассетные деки",
            "Грязный звук был следствием дешёвой техники, а не приёмом",
        ],
    }
    result = llm.generate_now("lineage", sample)

    if result["skip"] or not result["text"]:
        print(f"Модель отказалась писать: {result.get('reason', '')}")
        return 1

    print("─" * 60)
    print(result["text"])
    print("─" * 60)
    print(f"\nДлина: {len(result['text'])} знаков")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
