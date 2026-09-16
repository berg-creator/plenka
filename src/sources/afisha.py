"""Концерты артиста — со страницы артиста в Яндекс Афише.

Человек подписан на артистов и указал город — бот пишет, когда кто-то из них
объявил там концерт (src/service.py, notify_concerts). Здесь только источник:
страница `afisha.yandex.ru/artist/<адрес>` отдаёт расписание артиста по всем
городам сразу, в обычной разметке, без ключа. robots.txt её не закрывает
(закрыты /api и поиск), в условиях Афиши запрета на чтение нет, а общие
условия Яндекса оставляют за ним право запретить автоматические обращения —
поэтому запрос один в день на артиста, с паузой, и больше ничего.

Источник выбран сверкой 16.09.2026: десять артистов разного веса (Баста,
Скриптонит, Три дня дождя, Хаски, Буерак, Пасош, SODA LUV, УННВ, Kunteynir,
Ssshhhiiittt!), пять городов (Москва, Петербург, Екатеринбург, Новосибирск,
Краснодар), концерты с 16.09 до конца года. Руками по всем источникам нашлось
14; из них

- Яндекс Афиша — 12. Не хватило Басты на Газпром Арене 19.12 (страница
  показывает ближайшие десять дат, остальные подгружает через закрытый /api —
  дальний концерт придёт позже, когда ближние пройдут) и сольника участника
  Kunteynir под другим именем;
- Кассир — 6 по карте сайта (sitemap.xml по каждому городу, даты в адресе
  есть не у всех). Мог бы добрать Басту 19.12, но это пять тяжёлых файлов
  в день ради одного концерта из четырнадцати;
- Ticketland — 3 по карте сайта, но страницы закрыты антиботом, даты не прочесть;
- KudaGo — 0: пять городов без Новосибирска и Краснодара, в выдаче в основном
  органные вечера и стендап, из всех 156 артистов сбора нашёлся один концерт;
- МТС Live — карта сайта отвечает 500, поиска для роботов нет;
- Bandsintown — только с app_id, который дают самим артистам, без него 403;
- каналы артистов в Telegram — даты там в картинках афиш и в ссылках
  «билеты тут», текстом их нет, а адреса каналов пришлось бы собирать руками.

Адрес артиста в Афише — его имя транслитом («Три дня дождя» → tri-dnia-dozhdia).
Поиск закрыт в robots.txt, поэтому адрес угадывается и сверяется с именем
на странице: по molchat-doma Афиша отдаёт чужого человека, и без сверки
подписчик получал бы его концерты. Не угадался — артиста в Афише для бота нет.

    python -m src.sources.afisha --check "Баста"   концерты артиста, без записи
"""

from __future__ import annotations

import html
import re
import sys
from datetime import date

from .http import get

BASE = "https://afisha.yandex.ru"
ARTIST = BASE + "/artist/{slug}"
# Пауза между запросами к Афише: проход раз в день, спешить некуда.
MIN_INTERVAL = 2.0

_LETTERS = dict(zip(
    "абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
    ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "i", "k", "l", "m", "n", "o", "p",
     "r", "s", "t", "u", "f", "kh", "ts", "ch", "sh", "shch", "", "y", "", "e", "iu", "ia"],
))
_MONTHS = ("январ", "феврал", "март", "апрел", "ма", "июн", "июл", "август",
           "сентябр", "октябр", "ноябр", "декабр")

ITEM_SPLIT = 'data-test-id="personSchedule.item"'
TITLE_RE = re.compile(r"<title>(.*?)\s+[–—-]\s+афиша", re.DOTALL)
EVENT_RE = re.compile(r'href="(/[^"?/]+/[^"?/]+/[^"?]+)')
DAY_RE = re.compile(r'data-test-id="scheduleDate\.date">(\d+)<')
MONTH_RE = re.compile(r'data-test-id="scheduleDate\.month">([^<]*)<')
CITY_RE = re.compile(r'class="person-schedule-place__city">([^<]*)<')
PLACE_RE = re.compile(r'data-test-id="personSchedule\.placeName">([^<]*)<')
PASSED = "person-schedule-item__passed"


def slug(name: str) -> str:
    """Адрес артиста так, как его строит Афиша: транслит, пробелы и знаки — дефис."""
    latin = "".join(_LETTERS.get(ch, ch) for ch in name.casefold())
    return re.sub(r"[^a-z0-9]+", "-", latin).strip("-")


def same_name(a: str, b: str) -> bool:
    fold = lambda s: re.sub(r"\W+", "", s.casefold().replace("ё", "е"))  # noqa: E731
    return fold(a) == fold(b)


def find_artist(name: str) -> str | None:
    """Адрес страницы артиста в Афише или None, если там его нет (или там тёзка)."""
    candidate = slug(name)
    if not candidate:
        return None
    response = get(ARTIST.format(slug=candidate), min_interval=MIN_INTERVAL)
    if response is None:
        return None
    title = TITLE_RE.search(response.text)
    # Афиша перенаправляет на свой адрес («skriptonit» → «gruppa-skryptonite»),
    # и имя на странице бывает другим — тогда это не наш артист.
    if not title or not same_name(html.unescape(title.group(1)), name):
        return None
    return response.url.split("/artist/", 1)[1].split("?", 1)[0]


def parse_day(text: str, today: date) -> date | None:
    """«17 и 18 сентября», «30 сентября», «28 и 29 августа 2027» → первый день.

    Год Афиша пишет только у дальних и прошедших дат. Без года дата относится
    к ближайшему будущему: «29 января», увиденное в сентябре, — следующий год.
    Но то, что было меньше двух месяцев назад, — прошедшее, а не через год:
    страница иногда держит вчерашний концерт без пометки «Событие прошло».
    """
    day = re.search(r"\d{1,2}", text)
    month = next((i + 1 for i, stem in enumerate(_MONTHS)
                  if re.search(rf"\b{stem}[а-я]*\b", text[day.end():] if day else "")), None)
    if not day or not month:
        return None
    year = re.search(r"\b(20\d\d)\b", text)
    try:
        when = date(int(year.group(1)) if year else today.year, month, int(day.group()))
    except ValueError:
        return None
    if not year and when < today and (today - when).days > 60:
        when = when.replace(year=today.year + 1)
    return when


def concerts(artist_slug: str, today: date | None = None) -> list[dict]:
    """Предстоящие концерты: день, дата словами, город, площадка, ссылка.

    Дату словами берём как есть — в вести только то, что сказал источник.
    """
    response = get(ARTIST.format(slug=artist_slug), min_interval=MIN_INTERVAL)
    return parse(response.text, today or date.today()) if response is not None else []


def parse(page: str, today: date) -> list[dict]:
    found = []
    for chunk in page.split(ITEM_SPLIT)[1:]:
        event, month, city = EVENT_RE.search(chunk), MONTH_RE.search(chunk), CITY_RE.search(chunk)
        if PASSED in chunk or not (event and month and city):
            continue
        number = DAY_RE.search(chunk)
        when_text = html.unescape(f"{int(number.group(1))} {month.group(1)}" if number else month.group(1)).strip()
        when = parse_day(when_text, today)
        if when is None or when < today:
            continue
        place = PLACE_RE.search(chunk)
        found.append({
            "day": when.isoformat(),
            "when": when_text,
            "city": html.unescape(city.group(1)).strip(),
            "place": html.unescape(place.group(1)).strip() if place else "",
            "url": BASE + event.group(1),
        })
    return found


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] != "--check":
        print(__doc__.rsplit("\n\n", 1)[-1])
        return 1
    name = sys.argv[2]
    found = find_artist(name)
    if not found:
        print(f"«{name}» в Афише не нашёлся (или по адресу {slug(name)} другой артист).")
        return 0
    print(f"{name}: {ARTIST.format(slug=found)}")
    for item in concerts(found):
        print(f"  {item['day']}  {item['when']:<22} {item['city']:<18} {item['place']}  {item['url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
