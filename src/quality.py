"""Отбраковка постов перед попаданием в очередь.

Модель работает нестабильно: иногда возвращает служебный JSON вместо текста,
иногда скатывается в школьное сочинение с выводом в конце. Такое лучше поймать
автоматически и перегенерировать, чем показывать читателям.

Проверки намеренно грубые: цель — отсечь явный брак, а не оценивать стиль.
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
FILLER_WORDS = ("культовый", "легендарный", "знаковый", "поистине", "атмосфера мрака")

MIN_LENGTH = 60
MAX_LENGTH = 1500


def problems(text: str, rubric: str) -> list[str]:
    """Список причин, по которым пост нельзя публиковать. Пусто — годится."""
    issues: list[str] = []
    stripped = text.strip()

    if not stripped:
        return ["пустой текст"]

    # Опрос — это JSON по замыслу, к нему текстовые правила не применяются.
    if rubric == "poll":
        return []

    if len(stripped) < MIN_LENGTH:
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

    # Неподдерживаемая разметка, которую Telegram не разберёт.
    if re.search(r"<\s*(br|p|ul|ol|li|h[1-6])\b", stripped, re.IGNORECASE):
        issues.append("неподдерживаемые HTML-теги")

    # Мем длиной в абзац — это уже не мем.
    if rubric == "meme" and len(stripped) > 400:
        issues.append("мем слишком длинный")

    return issues


def is_ok(text: str, rubric: str) -> bool:
    return not problems(text, rubric)
