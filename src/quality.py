"""Отбраковка постов перед попаданием в очередь.

Модель работает нестабильно: иногда возвращает служебный JSON вместо текста,
иногда скатывается в школьное сочинение с выводом в конце. Такое лучше поймать
автоматически и перегенерировать, чем показывать читателям.

Проверки намеренно грубые: цель — отсечь явный брак, а не оценивать стиль.

    python -m src.quality --selftest   опись и её пересказ ловятся, законные цифры проходят
"""

from __future__ import annotations

import re

# Обороты, которые прямо запрещены голосом канала. Их наличие означает,
# что модель сползла в интонацию школьного реферата.
BANNED_PHRASES = (
    "резюме:",
    "в итоге получилось",
    "формула успеха",
    "вот так рождается",
    "история циклична",
    "давайте разберёмся",
    "давайте разберемся",
    "стоит отметить",
    "как известно",
    "теперь смотри внимательно",
    "подводя итог",
    "таким образом",
    "так что когда ты",
    "вспомни, что",
    "вот это поворот",
    "тут твоё место",
    "тут твое место",
    "не пропустите",
    "приятного прослушивания",
    "уважаемые подписчики",
)

# Слова-пустышки: одно-два простительно, но если их много — это вода.
# Вторая половина списка — то, чем обычно подменяют разговор о звуке:
# эти слова выглядят как описание музыки, но не сообщают о ней ничего.
FILLER_WORDS = (
    "культовый",
    "легендарный",
    "знаковый",
    "поистине",
    "атмосфера мрака",
    "атмосферн",
    "энергетик",
    "энергичн",
    "мураш",
    "уникальное звучание",
    "ни на кого не похож",
    "глубокий смысл",
    "вайб",
    # Из того же списка в voice.md. Их тут не хватало, и посты вроде
    # «круто качают и цепляют до мурашек» проходили фильтр насквозь.
    # Корни, а не словарные формы: «мурашк» не совпадает с «мурашек»,
    # и на этом ловля срывалась.
    "качает",
    "качают",
    "залета",
)

# У этих рубрик во входных данных нет никакого адреса: разбор связи и цитаты
# берутся из курируемых файлов, шутка — ниоткуда. Ссылка в таком посте всегда
# выдумана моделью и ведёт в никуда — проверено, 404.
RUBRICS_WITHOUT_LINK = frozenset({"lineage", "subtext", "meme", "poll"})

MIN_LENGTH = 60
MAX_LENGTH = 1500

# Рубрики, где пост открывается заголовком. У мема и опроса его нет,
# у разборов бота (service.py) — своя форма.
HEADLINED = ("release", "verdict", "news", "lineage", "subtext", "legend")

# Ссылка вырезается перед сверкой с данными релиза: в адресе бывают цифры.
_LINK = re.compile(r"<a\b.*?</a>", re.IGNORECASE | re.DOTALL)

# Брак описи — длинно, но не враньё: исчерпав попытки, compose.generate_checked
# выпускает такой пост, а не теряет его.
INVENTORY_ISSUES = ("опись <code>", "пересказ описи")


def problems(text: str, rubric: str, payload: dict | None = None) -> list[str]:
    """Список причин, по которым пост нельзя публиковать. Пусто — годится.

    payload — данные, по которым писался пост: с ними пересказ описи
    сверяется с фактами релиза. Без них эта проверка молчит.
    """
    issues: list[str] = []
    stripped = text.strip()

    if not stripped:
        return ["пустой текст"]

    # Опрос — это JSON по замыслу, к нему текстовые правила не применяются.
    if rubric == "poll":
        return []

    # Мем держится на картинке: две короткие надписи и строка подписи —
    # законный мем, а не брак, поэтому порог у него ниже.
    if len(stripped) < (20 if rubric == "meme" else MIN_LENGTH):
        issues.append(f"слишком короткий ({len(stripped)} знаков)")
    if len(stripped) > MAX_LENGTH:
        issues.append(f"слишком длинный ({len(stripped)} знаков)")

    # Служебный JSON, просочившийся в текст поста.
    if stripped.startswith("{") or '"skip"' in stripped or '"text":' in stripped:
        issues.append("в текст попал служебный JSON")

    # Литеральные «\n» вместо настоящих переводов строки.
    if "\\n" in stripped:
        issues.append("экранированные переводы строк вместо настоящих")

    lowered = stripped.lower()
    for phrase in BANNED_PHRASES:
        if phrase in lowered:
            issues.append(f"запрещённый оборот: «{phrase}»")

    filler_hits = [w for w in FILLER_WORDS if w in lowered]
    if len(filler_hits) >= 2:
        issues.append(f"слова-пустышки: {', '.join(filler_hits)}")

    # Название рубрики, вынесенное в шапку поста. Рубрика и так стоит
    # на карточке, а модель регулярно выносит её отдельной строкой —
    # иногда транслитом («Rubrik Otkuda Nogi»), что читается как брак.
    if re.match(r"\s*(<b>)?\s*(рубрика|rubrik[ao])\b", stripped, re.IGNORECASE):
        issues.append("название рубрики вынесено в шапку поста")

    # Первую строку показывают уведомление и список чатов, поэтому пост
    # начинается с заголовка. Пометку над ним («new tape / 10 треков») убрали:
    # она съедала крючок, а модель по старой памяти ещё может её поставить.
    if rubric in HEADLINED and not stripped.startswith("<b>"):
        issues.append("пост открывается не заголовком <b>")

    # Описи в РЕЛИЗЕ и ВЕРДИКТЕ нет (решение владельца от 11.09.2026): длину
    # показывает плеер под постом, а лишняя строка растягивает пост. GigaChat
    # по старой памяти ставит её обратно или пересказывает прозой: «Один трек,
    # 2:19, никого не позвал». С данными релиза сверяются точное число треков
    # и гостей и хронометраж до секунды. «Ни один трек не дотянул до 3 минут»,
    # «7-минутная вещь», округлённые «2 минуты» и повтор словами проходят:
    # ложная тревога стоит поста — после трёх попыток
    # compose.generate_checked его не выпускает.
    if rubric in ("release", "verdict"):
        if "<code>" in lowered:
            issues.append("опись <code> в посте — её убрали")
        facts = payload or {}
        count = len(facts.get("tracks") or []) or facts.get("track_count")
        guests = len(facts.get("features") or [])
        total = facts.get("total_length")
        checks = [
            (f"{count} трек", rf"(?<!\d){count}[\s-]*трек") if count else None,
            (f"{guests} гост", rf"(?<!\d){guests}[\s-]*гост") if guests else None,
            (total, rf"(?<![\d:]){re.escape(total)}(?![\d:])") if total else None,
        ]
        text_only = _LINK.sub(" ", lowered)
        retold = [name for name, pattern in filter(None, checks) if re.search(pattern, text_only)]
        if retold:
            issues.append("пересказ описи: " + ", ".join(retold))

    # Неподдерживаемая разметка, которую Telegram не разберёт.
    if re.search(r"<\s*(br|p|ul|ol|li|h[1-6])\b", stripped, re.IGNORECASE):
        issues.append("неподдерживаемые HTML-теги")

    # Дежурные отмашки вместо отношения. Ловим с любыми пробелами внутри:
    # «ну ок» модель любит ставить в разрядку, и тогда простое вхождение
    # строки его не находит.
    if re.search(r"(?i)\bн\s*у\s+о\s*к\b|\bну\s+такое\b|\bвот\s+такие\s+дела\b", stripped):
        issues.append("дежурная отмашка вместо отношения («ну ок» и подобное)")

    if rubric in RUBRICS_WITHOUT_LINK and re.search(r"<a\s+href", stripped, re.IGNORECASE):
        issues.append("ссылка в рубрике, у которой нет источника — она выдумана")

    # Мем длиной в абзац — это уже не мем.
    if rubric == "meme" and len(stripped) > 400:
        issues.append("мем слишком длинный")

    return issues


def is_ok(text: str, rubric: str) -> bool:
    return not problems(text, rubric)


def _selftest() -> None:
    """Опись и её пересказ в РЕЛИЗЕ и ВЕРДИКТЕ ловятся, законные цифры проходят."""
    link = '\n\n▸ <a href="https://music.apple.com/us/album/sorry-mama-single/6807382817">Слушать в Apple Music</a>'
    single = {"tracks": [{"title": "Sorry Mama", "length": "2:19"}], "total_length": "2:19", "features": []}
    album = {"tracks": [{"title": "", "length": "3:11"}] * 22, "total_length": "70:12", "features": list("ABCDEFGHI")}

    def retold(text: str, facts: dict, rubric: str = "release") -> bool:
        return any(p.startswith("пересказ описи") for p in problems(text, rubric, facts))

    # Живой пример от 11.09.2026: опись пересказана в первом абзаце.
    smoky = (
        "<b>SMOKY MO ИЗВИНИЛСЯ ПЕРЕД МАМОЙ</b>\n\n"
        "У Смоки Мо вышел сингл <i>Sorry Mama</i>. Один трек, 2:19, никого не позвал." + link
    )
    assert retold(smoky, single), problems(smoky, "release", single)
    assert retold(smoky, single, "verdict")
    # Разборы бота (service.py) данных не передают — сверять не с чем.
    assert not retold(smoky, {})

    # Заголовок капсом — тоже текст.
    kizaru = "<b>KIZARU ВЫПУСТИЛ 22 ТРЕКА</b>\n\nУ kizaru вышел альбом <i>CA$HEY</i>, короткий и ровный." + link
    assert retold(kizaru, album), problems(kizaru, "release", album)

    # Опись, поставленная по старой памяти.
    assert "опись <code> в посте — её убрали" in problems(smoky + "\n\n<code>1 трек · 2:19</code>", "release")

    # Пост, который владелец сократил в канале сам (Ghost Mountain, 11.09.2026):
    # округлённые «2 минуты» в цитате — довод, а не опись.
    ghost = (
        "<b>GHOST MOUNTAIN ВЫПУСТИЛ СИНГЛ OUTLAST</b>\n\n"
        "Парень из орбиты Haunted Mound, где сингл давно главная форма высказывания: "
        "альбом надо собирать, а трек можно выкинуть в пятницу и уйти.\n\n"
        "<blockquote>2 минуты — это уже не сингл, это проверка, вспомнят ли тебя через неделю.</blockquote>"
    )
    ghost_facts = {**single, "total_length": "2:14"}
    assert problems(ghost, "release", ghost_facts) == [], problems(ghost, "release", ghost_facts)

    # Цифры, которых нет в данных, — вывод из треклиста.
    example = (
        "<b>ARTIST ВЫПУСТИЛ ALBUM И СПРЯТАЛ ГЛАВНОЕ В СЕРЕДИНУ</b>\n\n"
        "Первые 8 треков идут по 1,5 минуты, потом внезапно 7-минутная вещь. "
        "После неё ни один трек не дотянул до 3 минут.\n\n"
        "<blockquote>Столько треков — не щедрость, а отсутствие редактора.</blockquote>" + link
    )
    assert not retold(example, album), problems(example, "release", album)
    print("quality: самопроверка пройдена")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Отбраковка постов перед очередью.")
    parser.add_argument("--selftest", action="store_true", help="опись и её пересказ ловятся, законные цифры проходят")
    if parser.parse_args().selftest:
        _selftest()
