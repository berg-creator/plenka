"""Единая точка конфигурации: пути, рубрики, секреты, расписание."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DATA = ROOT / "data"
PROMPTS = ROOT / "prompts"
QUEUE = ROOT / "content" / "queue"
# Срочные новости живут отдельно от очереди: их пишут и показывают в тот же
# день, и в общую ленту по расписанию они попадать не должны — пока пост
# дождётся своей очереди, новость успеет протухнуть.
URGENT = ROOT / "content" / "urgent"
ARCHIVE = ROOT / "content" / "archive"
TEMPLATES = ROOT / "assets" / "templates"

ARTISTS_FILE = DATA / "artists.json"
CANDIDATES_FILE = DATA / "artists_candidates.json"
LINEAGE_FILE = DATA / "lineage.json"
SUBTEXT_FILE = DATA / "subtext.json"
FACTS_FILE = DATA / "facts.json"
CALENDAR_FILE = DATA / "calendar.json"
INBOX_FILE = DATA / "inbox.jsonl"
SEEN_FILE = DATA / "seen.json"
POSTED_FILE = DATA / "posted.json"
STORIES_FILE = DATA / "stories.json"
# Выгрузка плейлиста ВКонтакте: «артист|трек» → вложение audio-…_…
# Собирается разово руками, потому что audio.search сообществам закрыт.
VK_AUDIO_FILE = DATA / "vk_audio.json"
CLIPS_FILE = DATA / "clips.json"
# Мемные картинки рубрики МЕМ: каталог с подсказкой, когда какая уместна,
# и сами шаблоны. Шаблоны лежат в репозитории, а не качаются при публикации:
# иначе выход поста зависел бы от чужого сайта.
MEMES_FILE = DATA / "memes.json"
MEME_TEMPLATES = ROOT / "assets" / "meme" / "templates"

# Всё, что относится к конкретным людям, лежит отдельно от кода.
# Репозиторий проекта открытый, и списки тех, кто писал боту и за кем следит,
# в нём быть не должны — ни в каком виде. Путь задаётся переменной STATE_DIR:
# в GitHub Actions туда клонируется приватный репозиторий, локально —
# просто папка рядом, которую не берёт git (см. .gitignore).
PRIVATE = Path(os.environ.get("STATE_DIR", "")) if os.environ.get("STATE_DIR") else DATA / "private"
WATCH_FILE = PRIVATE / "watches.json"

# Какой генератор текстов используется, задаётся в .env переменной LLM_PROVIDER
# (anthropic — платный Claude, по умолчанию; gigachat — Сбер; gemini — Google).
# Переменная LLM_FALLBACK задаёт запасной генератор на случай, когда основной
# недоступен: см. src/llm.py. Сама модель выбирается внутри провайдера
# в src/providers/.

# Сколько постов держим в очереди. Если меньше MIN — health.yml поднимает тревогу.
QUEUE_TARGET = 24
QUEUE_MIN = 6

# Срочные новости: сколько пишем за один заход и через сколько часов
# непринятый пост считается протухшим и удаляется сам.
# Один инфоповод за заход: заходов три в день, и при трёх новостях за раз
# лента получала бы девять срочных сообщений в сутки поверх очереди
# и викторины. Срочное перестаёт читаться срочным, когда его много.
URGENT_PER_RUN = 1
URGENT_TTL_HOURS = 48
# Новость старше этого срока срочной уже не считается.
URGENT_MAX_AGE_HOURS = 36
# Окно сбора RSS — от него же, но с запасом: сбор ходит раз в 6 часов, и новость,
# вышедшая сразу после прогона, должна дожить до следующего. Пока окно сбора было
# уже (30 часов), верхняя половина срока срочности пустовала: новость возрастом
# 30-36 часов не попадала в inbox вообще.
NEWS_MAX_AGE_HOURS = URGENT_MAX_AGE_HOURS + 12

# Минимальный интервал между публикациями. Публикатор смотрит не на часы,
# а на «сколько прошло с прошлого поста» — так пропуск cron не ломает ленту.
PUBLISH_INTERVAL_HOURS = 3

# Сколько дней храним отпечатки в seen.json, чтобы файл не рос бесконечно.
SEEN_TTL_DAYS = 120

# Открывать ли ветку комментариев первым сообщением — см. src/comments.py.
# Пустая ветка под каждым постом читается как «здесь никого нет», поэтому
# канал задаёт вопрос сам. Токенов это не стоит: вопросы готовые.
COMMENT_SEED = True

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
    # Перекос в сторону МЕМА сделан намеренно: канал растёт пересылками, а
    # пересылают шутку, а не разбор. Разборы остаются, но перестают быть половиной ленты.
    # Ноль — рубрика в очередь наперёд не пишется: её посты делает отдельный
    # запуск ко дню публикации (ЛЕГЕНДА — календарь, ИНФОПОВОД — src/urgent.py).
    weight: int
    # Из какого сырья строится: release | news | lineage | calendar | verdict | meme | poll | digest
    feeds_on: str
    description: str


RUBRICS: tuple[Rubric, ...] = (
    Rubric(
        key="lineage",
        title="ОТКУДА НОГИ",
        weight=22,
        feeds_on="lineage",
        description=(
            "Ниточка от современного трека к его предку: фонк → Three 6 Mafia, "
            "эмо-рэп → грандж, дрейн → витч-хаус. Главная рубрика канала."
        ),
    ),
    Rubric(
        key="verdict",
        title="ВЕРДИКТ",
        weight=16,
        feeds_on="verdict",
        description=(
            "Реакция на свежий трек или тренд: либо разнос, либо честный респект. "
            "Без вежливой середины — середина не репостится."
        ),
    ),
    Rubric(
        key="news",
        title="ИНФОПОВОД",
        weight=0,
        feeds_on="news",
        description=(
            "Что происходит на сцене: бифы, скандалы, уходы с лейблов, воссоединения, "
            "суды, цифры стримов. Мировая и русская сцена наравне. В очередь не идёт: "
            "новость к своей очереди протухает, поэтому её пишет src/urgent.py "
            "в день события и сразу показывает владельцу."
        ),
    ),
    Rubric(
        key="meme",
        title="МЕМ",
        weight=30,
        feeds_on="meme",
        description=(
            "Юмор про музыку и слушателя: ру-рэп, продюсеры, лейблы, стриминг, "
            "плейлисты, тикток, жанровые стереотипы. Самая пересылаемая рубрика — "
            "поэтому и самая весомая: разборы держат лицо канала, а растит его тот, "
            "кого пересылают друзьям."
        ),
    ),
    Rubric(
        key="subtext",
        title="МЕЖДУ СТРОК",
        weight=12,
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
        weight=14,
        feeds_on="release",
        description="Вышло что-то у трекаемого артиста — короткий пост со ссылками.",
    ),
    Rubric(
        key="legend",
        title="ЛЕГЕНДА",
        weight=0,
        feeds_on="calendar",
        description=(
            "Годовщина: смерть, рождение, выход культового альбома. "
            "Пишется в день даты — см. src/calendar_check.py."
        ),
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
