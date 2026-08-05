"""Единая точка конфигурации: пути, рубрики, секреты, расписание."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DATA = ROOT / "data"
PROMPTS = ROOT / "prompts"
QUEUE = ROOT / "content" / "queue"
ARCHIVE = ROOT / "content" / "archive"
TEMPLATES = ROOT / "assets" / "templates"

ARTISTS_FILE = DATA / "artists.json"
CANDIDATES_FILE = DATA / "artists_candidates.json"
LINEAGE_FILE = DATA / "lineage.json"
SUBTEXT_FILE = DATA / "subtext.json"
CALENDAR_FILE = DATA / "calendar.json"
INBOX_FILE = DATA / "inbox.jsonl"
SEEN_FILE = DATA / "seen.json"
POSTED_FILE = DATA / "posted.json"
STORIES_FILE = DATA / "stories.json"

# Какой генератор текстов используется, задаётся в .env переменной LLM_PROVIDER
# (gemini — бесплатный тариф Google, anthropic — платный Claude).
# Сама модель выбирается внутри соответствующего провайдера в src/providers/.

# Сколько постов держим в очереди. Если меньше MIN — health.yml поднимает тревогу.
QUEUE_TARGET = 24
QUEUE_MIN = 6

# Минимальный интервал между публикациями. Публикатор смотрит не на часы,
# а на «сколько прошло с прошлого поста» — так пропуск cron не ломает ленту.
PUBLISH_INTERVAL_HOURS = 4

# Сколько дней храним отпечатки в seen.json, чтобы файл не рос бесконечно.
SEEN_TTL_DAYS = 120

# Лимиты бота-сервиса (src/service.py). Разбор стоит примерно столько же токенов,
# сколько пост канала, а бесплатный миллион уже наполовину расписан очередью,
# поэтому потолок нужен с самого начала — накрутить его всегда успеется.
SERVICE_DAILY_USER = 1  # разборов на человека в сутки
SERVICE_DAILY_TOTAL = 40  # разборов на всех в сутки
SERVICE_PER_RUN = 6  # сколько разборов делаем за один запуск поллера


@dataclass(frozen=True)
class Rubric:
    """Описание рубрики: как часто выходит и с каким весом попадает в очередь."""

    key: str
    title: str
    # Доля рубрики в очереди. Сумма весов нормируется, точных чисел не требуется.
    weight: int
    # Из какого сырья строится: release | news | lineage | calendar | verdict | meme | poll | digest
    feeds_on: str
    description: str


RUBRICS: tuple[Rubric, ...] = (
    Rubric(
        key="lineage",
        title="ОТКУДА НОГИ",
        weight=20,
        feeds_on="lineage",
        description=(
            "Ниточка от современного трека к его предку: фонк → Three 6 Mafia, "
            "эмо-рэп → грандж, дрейн → витч-хаус. Главная рубрика канала."
        ),
    ),
    Rubric(
        key="verdict",
        title="ВЕРДИКТ",
        weight=18,
        feeds_on="verdict",
        description=(
            "Реакция на свежий трек или тренд: либо разнос, либо честный респект. "
            "Без вежливой середины — середина не репостится."
        ),
    ),
    Rubric(
        key="news",
        title="ИНФОПОВОД",
        weight=18,
        feeds_on="news",
        description=(
            "Что происходит на сцене: бифы, скандалы, уходы с лейблов, воссоединения, "
            "суды, цифры стримов. Мировая и русская сцена наравне."
        ),
    ),
    Rubric(
        key="meme",
        title="МЕМ",
        weight=18,
        feeds_on="meme",
        description=(
            "Юмор про музыку и индустрию: ру-рэп, продюсеры, лейблы, слушатели, "
            "жанровые стереотипы. Картинка на шаблоне или чистый текст."
        ),
    ),
    Rubric(
        key="subtext",
        title="МЕЖДУ СТРОК",
        weight=14,
        feeds_on="subtext",
        description=(
            "Разбор текста: отсылки, двойные смыслы, контекст. Работает на курируемой "
            "базе data/subtext.json — цитаты берутся только оттуда, чтобы канал "
            "никогда не приписал артисту выдуманную строчку."
        ),
    ),
    Rubric(
        key="release",
        title="РЕЛИЗ",
        weight=12,
        feeds_on="release",
        description="Вышло что-то у трекаемого артиста — короткий пост со ссылками.",
    ),
    Rubric(
        key="legend",
        title="ЛЕГЕНДА",
        weight=6,
        feeds_on="calendar",
        description="Годовщина: смерть, рождение, выход культового альбома.",
    ),
    Rubric(
        key="poll",
        title="ОПРОС",
        weight=6,
        feeds_on="poll",
        description="Нативный опрос Telegram: кто круче, какой альбом лучше.",
    ),
)

RUBRIC_BY_KEY = {r.key: r for r in RUBRICS}


def secret(name: str, *, required: bool = True) -> str:
    """Достаёт секрет из окружения. В GitHub Actions они приходят из Secrets."""
    value = os.environ.get(name, "").strip()
    if not value and required:
        raise RuntimeError(
            f"Не задана переменная окружения {name}. "
            f"Локально — положи её в .env, на GitHub — в Settings → Secrets → Actions."
        )
    return value


def load_dotenv(path: Path | None = None) -> None:
    """Простейший загрузчик .env для локального запуска (в Actions не нужен)."""
    env_path = path or (ROOT / ".env")
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())
