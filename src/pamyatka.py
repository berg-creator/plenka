"""ПАМЯТКА — два раза в неделю короткий пост-совет артисту: чьи права на трек и как записать голос.

Канал — сцена для тех, кто пришёл в бот делать музыку (владелец 06.10.2026), и им нужнее пересказа
чужого релиза то, на чём начинающий теряет трек или деньги: «free» в названии бита, фит без уговора,
голосовое вместо записи. Поэтому ПАМЯТКА выходит вместо поста о релизе, а не вдобавок (владелец
09.10.2026): в её сутки ленты publish.release_due релиз не пускает, а слот обычного поста она
занимает так же, как занял бы он (publish.due), — постов в день больше не становится. Релиз этого
дня не выходит вовсе и на утро не переносится (took): пост о нём убирается из очереди, новый
не пишется. До 09.10.2026 релиз с выходом в 10:00 МСК (iTunes) жил ещё час следующего утра, выходил
вчерашним и забирал единственный выход дня у свежего — а релизы у канала выходят свежими.

В пост идёт только то, за чем стоит документ или правило самого бота: у каждой записи базы
(data/pamyatka.json) обязательное поле sources — статьи закона или место в коде. Цитаты закона стоят
в кавычках дословно: все сверены 09.10.2026 с официальным текстом на pravo.gov.ru (ГК — nd=102110716,
редакция 48, последняя правка — 214-ФЗ от 07.07.2025). «Что делать» —
практический вывод, а не цитата. Текст — шаблоном, без модели: норму, пересказанную своими словами,
уже не проверить по статье. Базу пополняют руками.
Три записи — slova, zamysel, shtraf — о запрете пропаганды наркотиков, который артисты зовут «запретом
слов» (владелец 09.10.2026: самая больная тема для тех, кто выпускает треки, а в боте про неё было
пусто). Они показывают текст закона и больше ничего: ни «что делать», ни совета, как переписать
строчку, ни «можно/нельзя» про чей-то трек — такой совет был бы подсказкой, как обойти запрет,
а ПЛЁНКА не юрист; о площадках и лейблах там тоже ни слова: это новости, а не закон. Источники —
закон № 3-ФЗ, ст. 46 (nd=102050997, редакция 47), КоАП, ст. 6.13 (nd=102074277, редакция 970),
УК, ст. 230.3 (nd=102041891, редакция 365) и приказ Минкультуры № 884 (nd=603649989). Сверять
по печатному виду страницы (?docview&page=1&print=1&nd=…&rdk=…): обычный вид длинный документ
обрывает молча, а печатный отдаёт его целиком и пишет дату, на которую текст действует; поправки,
ещё не внесённые в текст, ИПС показывает в списке редакций пометкой «не готова» — их читать отдельно.
Последняя строка поста зовёт в бота, слова «в боте» в ней — ссылка. Своя строка записи — поле bot,
метка ссылки — поле start: про бит «free» она ведёт в список битов, про запись голоса — в сведение
(отдельной проверки голоса в боте нет: замер записи, skleyka.gauge, идёт внутри сведения и человеку
не показывается). Записи про права (поле topic) без своей строки шаблон дописывает призыв CALL —
«Лучше пишите ПЛЁНКЕ» со ссылкой на раздел в боте (владелец 09.10.2026). Команд в тексте поста нет:
в канале Telegram подсвечивает /команду, а нажатие никуда не ведёт.

Та же база открывается в боте разделом «ПАМЯТКА» (screen, answer; кнопки и счёт — service._memo):
вход — две темы, «права и закон» и «запись голоса» (владелец 10.10.2026: «сначала 2 кнопки … а только
потом список памяток»), в теме — её вопросы кнопками (поле ask) по config.PAMYATKA_PAGE на экран,
ответ — та же запись без призыва.
Это справочник, а не консультант: модель не вызывается, текст человека раздел не разбирает —
«модель выдумывает, юриста у нас нет» (владелец 09.10.2026), и экран раздела говорит это первым.
Страницы внутри темы остались: права и закон — 17 вопросов из 23, одним экраном это простыня.
Отвергнута правка сообщения на месте (ответ пропадал бы при возврате к списку — прочитанное остаётся в чате).

Одно исключение из «модель не вызывается» — «🔎 Проверить текст» (владелец 09.10.2026): артист присылает
текст трека, бот показывает его же строки, где названы вещества, и запись slova. Модель здесь не отвечает
человеку, а только называет номера строк: её слов в ответе нет, выдумать ей нечем. Вердикта бот не выносит —
закон судит не слова, а то, о чём информация, и «чисто» перед снятым треком было бы виной канала; замен
не предлагает; текст не хранит. Границы, тексты и код — раздел «проверка текста» ниже.
Ищет модель, а не словарь в коде: словарь неполон и был бы списком сленга в открытом репозитории. Решила
проба 09.10.2026 из Actions (--probe, запуск 37985423309): десять своих коротких текстов, шесть из них
с названиями веществ, — Gemini прочёл все десять без отказа и назвал нужные строки, «траву у дома»
с «травой за гаражами» не спутал. Начнёт отказывать чаще раза из десяти — словарь. Пробы короткие
и без похвалы веществам: как модель читает тексты жёстче, не проверено. Текст уходит генератору (Gemini,
при его сбое — ГигаЧат): «не хранится» — это о боте, и экран вопроса так и говорит.

Выход — в дни config.PAMYATKA_DAYS с config.PAMYATKA_HOUR_MSK по Москве, не ночью, одна запись
в сутки ленты, по порядку базы. Отметка вышедшей — pamyatka-<id>.json в content/archive, как у совета
недели (src/sovet.py): запись дважды не выходит, поэтому id в базе не менять. База кончилась —
рубрика молчит и релизы в её дни выходят как раньше; с последней записью владельцу уходит строка.
Отвергнуто: счётчик «какая запись следующая» отдельным файлом (отметки в архиве уже это знают
и переживают вставку записи в середину базы), пост вдобавок к релизу (владелец 06.10.2026: постов
в ленте и так много) и посты по справке YouTube — её страницы автоматически не читаются, а писать
по памяти значит выдумывать.

    python -m src.pamyatka --selftest   без сети и Telegram; настоящая база — источники, длина подписи с призывом,
                                        раздел в боте: страницы, кнопки и ответы в лимитах Telegram
    python -m src.pamyatka --dry-run    что в запасе, когда выйдет следующая и её текст, без записи и отправки
    python -m src.pamyatka --probe      читает ли генератор тексты с названиями веществ: десять проб — только
                                        из Actions (с Мака Gemini не отвечает), с пустым LLM_FALLBACK
"""
from __future__ import annotations

import argparse
import html
import itertools
import re
import subprocess
import sys
import tempfile
from datetime import datetime, time
from pathlib import Path

from . import config, state

RUBRIC = "pamyatka"
LAW = "prava"  # поле topic записи про права; вторая тема — "golos", запись голоса
# Отсылка к названию сериала о юристе — без имени персонажа: его нигде не пишем.
CALL = "▸ Лучше пишите ПЛЁНКЕ: все памятки про права — в боте"
# Кнопки раздела в боте: s:pam:<id> — запись, s:pam:<тема>.<страница> — список темы; «s:pam» без хвоста — вход
# из меню (service.menu_buttons), он считается. Числа и точки в id не бывает — селфтест базы, — поэтому HOME,
# первый экран без счёта входа, — число: так до 10.10.2026 выглядели страницы общего списка и «← Все вопросы»,
# и кнопки в старых сообщениях ведут туда же.
PICK = "s:pam:"
HOME = f"{PICK}0"
ICONS = {LAW: "⚖️", "golos": "🎙"}
TOPICS = {LAW: "Права и закон", "golos": "Запись голоса"}
HEAD = "⚖️ <b>ПАМЯТКА</b>"
INTRO = ("Ответы на то, на чём начинающий теряет трек или деньги: чьи права на музыку, как записать голос "
         "и что в законе о «запрете слов».")
NOTE = "ПЛЁНКА не юрист: здесь цитаты закона и что с ними делать, свой случай — к юристу."
MORE = "Новые памятки выходят в канале {channel} по средам и субботам."  # дни — config.PAMYATKA_DAYS, сверяет селфтест
BACK = "← Все вопросы"
# Своя строка записи зовёт в биты или в сведение — под ответом кнопка туда же, тем же путём, что кнопка меню.
DOORS = {"bity": "🎚 БИТЫ — бесплатно, можно в релиз", "skleyka": "🎛 СВЕДЕНИЕ — вокал и бит в трек"}
# Счёт в data/bot_sources.json (service.count_source): вход в раздел и каждая открытая запись, по дню.
OPENED = "ПАМЯТКА: открыт раздел"
LAST = "📌 Запас ПАМЯТКИ кончился: «{title}» — последняя запись базы. Новые — в data/pamyatka.json."


def load() -> list[dict]:
    """Записи базы. Без id, заголовка или текста — не запись: базу правят руками, а спрашивает о ней
    и выход релизов (publish.release_due) — кривая правка не должна ронять дежурство."""
    data = state.read_json(config.PAMYATKA_FILE, [])
    return [item for item in data if isinstance(item, dict) and item.get("id") and item.get("title") and item.get("text")] \
        if isinstance(data, list) else []


def pending() -> list[dict]:
    """Невышедшие записи в порядке базы."""
    return [item for item in load() if not (config.ARCHIVE / f"{RUBRIC}-{item['id']}.json").exists()]


def _parts(item: dict) -> list[str]:
    return [f"<b>ПАМЯТКА: {html.escape(item['title'])}</b>", *map(html.escape, item["text"])]


def build(item: dict) -> dict:
    """Пост канала: запись и последней строкой — своя строка про бота или, у записи про права, призыв CALL."""
    parts = _parts(item)
    line, start = (item["bot"], item["start"]) if item.get("bot") else (CALL, RUBRIC) if item.get("topic") == LAW else ("", "")
    if line:
        url = f"https://t.me/{config.BOT_HANDLE.lstrip('@')}?start={start}"
        parts.append(re.sub("(?i)в боте", lambda found: f'<a href="{url}">{found[0]}</a>', html.escape(line), count=1))
    return {"rubric": RUBRIC, "id": item["id"], "title": item["title"], "text": "\n\n".join(parts)}


def label(item: dict) -> str:
    """Подпись счётчика открытой записи — её вопрос: владельцу видно, что открывают."""
    return f"ПАМЯТКА: «{item.get('ask') or item['title']}»"


def find(key: str) -> dict | None:
    return next((item for item in load() if item["id"] == key), None)


def screen(where: str = "") -> tuple[str, list[list[dict]]]:
    """Экран раздела в боте по хвосту кнопки. «<тема>.<страница>» — вопросы этой темы кнопками,
    config.PAMYATKA_PAGE на страницу, в порядке базы, и «← Назад» на вход; оговорка о юристе — только в теме
    закона. Всё остальное (пусто, число прежних страниц, тема, которой нет) — вход: вступление, оговорка,
    строка о канале (пока в базе есть невышедшее) и три кнопки — «🔎 Проверить текст» (ролик зовёт кинуть
    текст, а не листать вопросы; в темах её нет) и две темы. Вопросов на входе нет."""
    topic, _, page = where.partition(".")
    if topic not in TOPICS:
        parts = [HEAD, INTRO, NOTE, *([MORE.format(channel=config.CHANNEL_HANDLE)] if pending() else [])]
        return "\n\n".join(parts), [[{"text": TEXT_BUTTON, "callback_data": TEXT_KEY}]] + \
            [[{"text": f"{ICONS[key]} {name}", "callback_data": f"{PICK}{key}.0"}] for key, name in TOPICS.items()]
    base, size = [item for item in load() if item.get("topic") == topic], config.PAMYATKA_PAGE
    # isdecimal, а не isdigit: «²» — цифра, но int() на ней падает, а хвост кнопки приходит из чужих рук.
    at = min(int(page) if page.isdecimal() else 0, max(0, (len(base) - 1) // size)) * size
    rows = [[{"text": f"{ICONS[topic]} {item.get('ask') or item['title']}",
              "callback_data": f"{PICK}{item['id']}"}] for item in base[at:at + size]]
    turn = ([{"text": "‹ Предыдущие", "callback_data": f"{PICK}{topic}.{at // size - 1}"}] if at else []) + \
        ([{"text": "Ещё вопросы ›", "callback_data": f"{PICK}{topic}.{at // size + 1}"}] if at + size < len(base) else [])
    parts = [f"{ICONS[topic]} <b>ПАМЯТКА: {TOPICS[topic].lower()}</b>", *([NOTE] if topic == LAW else []),
             *([f"Вопросы {at + 1}–{min(at + size, len(base))} из {len(base)} ↓"] if len(base) > size else [])]
    return "\n\n".join(parts), rows + ([turn] if turn else []) + [[{"text": "← Назад", "callback_data": HOME}]]


def answer(item: dict) -> tuple[str, list[list[dict]]]:
    """Ответ на вопрос в боте: запись тем же шаблоном, что пост, без призыва и без ссылки — человек уже
    в боте. Своя строка про бота остаётся строкой, а ведёт туда кнопка под ответом. Под записью
    о «запрете слов» (SLOVA) — «🔎 Проверить текст». «← Все вопросы» — список темы записи, на её странице;
    запись без темы (кривая правка базы) возвращает на вход."""
    door, topic = item.get("start", "").partition("_")[0], item.get("topic")
    mine = [row["id"] for row in load() if row.get("topic") == topic]
    back = f"{PICK}{topic}.{mine.index(item['id']) // config.PAMYATKA_PAGE}" if topic in TOPICS else HOME
    rows = [[{"text": DOORS[door], "callback_data": f"s:{door}"}]] if item.get("bot") and door in DOORS else []
    rows += [[{"text": TEXT_BUTTON, "callback_data": TEXT_KEY}]] if item["id"] == SLOVA else []
    return ("\n\n".join(_parts(item) + ([html.escape(item["bot"])] if item.get("bot") else [])),
            rows + [[{"text": BACK, "callback_data": back}]])


# ─────────────────────────── проверка текста ───────────────────────────
# «🔎 Проверить текст» (владелец 09.10.2026: «было бы круто сделать фичу что можно отправить текст на проверку
# боту»): артист присылает текст трека, бот показывает его же строки, где названы вещества, и запись slova.
# Границы — они же селфтест:
# 1. Вердикта нет: ни «чисто», ни «можно», ни «нарушение». Закон судит не слова, а то, о чём информация
#    (ст. 46 закона № 3-ФЗ), и «чисто» перед снятым треком — вина канала.
# 2. Замен, синонимов и способов спрятать слово бот не предлагает.
# 3. Сверх строк самого артиста названия веществ не звучат: модель отвечает номерами строк (llm.TEKST_SCHEMA),
#    её слов в ответе нет вовсе, строки берёт код из присланного текста. Промпт веществ не называет, в коде
#    названия стоят только в пробах генератора (PROBES) — человеку они не уходят.
# 4. Текст не хранится: дежурство отдаёт его процессу проверки через stdin — ни файла, ни аргумента команды,
#    ни строки в логе; в счётчик идёт метка (service.count_source), в лимиты — число (service._tekst).
# 5. «ПЛЁНКА не юрист» — на экране вопроса и в каждом ответе.
SLOVA = "slova"  # запись базы о «запрете слов»: её текст закона идёт в ответ проверки, под ней — кнопка проверки
# Кнопка: на экране раздела и под записью slova; «s:tekst:ok» — «Подписался», вход уже посчитан (service).
TEXT_KEY = "s:tekst"
TEXT_BUTTON = "🔎 Проверить текст"
TEXT_HEAD = "🔎 <b>ПРОВЕРКА ТЕКСТА</b>"
# Текст трека — ответом на сообщение с этой меткой, как у ДВОЙНИКА (svedenie.INTRO_MARK): без ответа
# он ушёл бы в ПРОЯВКУ. Помнить, о чём спросил, боту не нужно — и хранить про человека нечего.
TEXT_MARK = "Пришли текст трека ответом на это сообщение"
TEXT_ASK = (f"{TEXT_HEAD}\n\n{TEXT_MARK} — покажу строки, где названы наркотические вещества, и что о них говорит закон.\n\n"
            "Что в тексте пропаганда, а что нет, бот не решает: закон описывает не слова, а то, о чём информация. "
            "ПЛЁНКА не юрист.\n\n"
            f"Текст читает нейросеть, бот его не сохраняет. До {config.TEKST_CHARS} знаков, проверок в сутки — {config.TEKST_PER_DAY}.")
TEXT_HINT = "Текст трека"
TEXT_WAIT = "🔎 Читаю. Ответ придёт отдельным сообщением — обычно меньше минуты."
TEXT_BUSY = "Прошлый текст ещё читаю — пришли этот, когда придёт ответ."
TEXT_LONG = f"Текст длиннее {config.TEKST_CHARS} знаков. {TEXT_MARK} частями — по куплету."
TEXT_LIMIT = f"Проверок в сутки — {config.TEKST_PER_DAY}. Завтра приходи ещё."
TEXT_FULL = "На сегодня проверки у бота кончились — приходи завтра."
TEXT_FOUND = "Строки, где нейросеть увидела названия веществ:"
TEXT_REST = "…и ещё {count} — не поместились."
TEXT_NONE = "Названий веществ не нашёл; сленг знаю не весь, а закон описывает не слова, а то, о чём информация."
TEXT_MAYBE = "Нейросеть могла пропустить строку или показать лишнюю."
TEXT_NOTE = "Это не оценка текста: что в нём пропаганда, а что нет, бот не решает. ПЛЁНКА не юрист — свой случай к юристу."
# Отказ модели — не вердикт: «не взялась читать» человек иначе прочёл бы как «текст плохой».
TEXT_FAIL = ("Нейросеть не прочитала текст — проверить не вышло. Это её сбой или отказ, а не оценка текста: "
             "что в нём названо, бот так и не узнал. Попробуй ещё раз позже.")
TEXT_AGAIN = "🔎 Проверить ещё текст"
# Счёт в data/bot_sources.json: сколько раз открыли и сколько текстов прислали — по дню, без человека и без текста.
TEXT_OPENED = "ПРОВЕРКА ТЕКСТА: открыта"
TEXT_SENT = "ПРОВЕРКА ТЕКСТА: текст прислан"
# Строки в ответе — в пределах TEXT_ROOM знаков разметки, длинная строка — началом в TEXT_LINE знаков: с записью
# о законе в сообщение Telegram (4096) влезает не всё, а обрезка отправки (telegram.MAX_TEXT) рвала бы тег.
TEXT_ROOM, TEXT_LINE = 2400, 300
# Проверки, что идут сейчас, по чатам: память смены, как skleyka._BEATS.
_READING: dict[str, subprocess.Popen] = {}


def lines_of(text: str) -> list[str]:
    """Непустые строки текста, как их прислал человек: по их номерам отвечает модель."""
    return [line.strip() for line in text.splitlines() if line.strip()]


def flagged(lines: list[str], numbers: list) -> list[str]:
    """Строки по номерам модели, в порядке текста и по разу (припев повторяется). Номер мимо текста
    и всё, что не номер, — прочь: показать можно только строку, которая стоит в тексте."""
    wanted = sorted({int(n) for n in numbers if isinstance(n, (int, str)) and str(n).isdigit()})
    return list(dict.fromkeys(lines[n - 1] for n in wanted if 1 <= n <= len(lines)))


def found(text: str) -> list[str] | None:
    """Строки текста, где модель увидела название вещества; None — она не ответила: отказ, сбой
    или ответ не по схеме (запасной генератор строгих схем не держит)."""
    from . import llm

    lines = lines_of(text)
    answer = llm.generate_tekst(lines)
    if answer.get("skip") or not isinstance(answer.get("lines"), list):
        # Причину пишет только Gemini: это код его фильтра. У запасного она — слова модели, а в них мог попасть текст.
        why = answer.get("reason", "")
        print(f"ПРОВЕРКА ТЕКСТА: модель не ответила — {why if why.startswith('Gemini') else 'отказ или ответ не по схеме'}")
        return None
    return flagged(lines, answer["lines"])


def report(shown: list[str] | None) -> tuple[str, list[list[dict]]]:
    """Ответ проверки: None — модель не ответила, пусто — названий не нашлось, иначе строки человека,
    запись slova целиком и оговорка. Своих слов о тексте, кроме этих трёх шаблонов, у бота нет."""
    rows = [[{"text": TEXT_AGAIN, "callback_data": TEXT_KEY}], [{"text": BACK, "callback_data": f"{PICK}0"}]]
    law = find(SLOVA)
    if shown is None:
        return f"{TEXT_HEAD}\n\n{TEXT_FAIL}", rows
    if not shown:
        ask = [[{"text": f"{ICONS[LAW]} {law['ask']}", "callback_data": f"{PICK}{SLOVA}"}]] if law and law.get("ask") else []
        return f"{TEXT_HEAD}\n\n{TEXT_NONE}\n\n{TEXT_NOTE}", ask + rows
    cut = [html.escape(line[:TEXT_LINE] + "…" * (len(line) > TEXT_LINE)) for line in shown]
    fit = [line for line, size in zip(cut, itertools.accumulate(len(line) + 1 for line in cut)) if size <= TEXT_ROOM]
    rest = f"\n{TEXT_REST.format(count=len(cut) - len(fit))}" if len(cut) > len(fit) else ""
    parts = [TEXT_HEAD, f"{TEXT_FOUND}\n<blockquote>" + "\n".join(fit) + f"</blockquote>{rest}",
             *(_parts(law) if law else []), f"{TEXT_MAYBE} {TEXT_NOTE}"]
    return "\n\n".join(parts), rows


def take(chat_id: str | int, text: str) -> bool:
    """Текст человека — процессу проверки (--read). Модель отвечает секунды, а при занятых моделях минуты,
    и дежурство — единственный поллер: ждать её в цикле опроса значит держать кнопки всех (так было
    с просьбами к сведению, skleyka.heed). Текст идёт через stdin процесса — на диск и в строку запуска
    он не попадает. False — прошлый текст этого человека ещё читается.
    ponytail: проверки разных людей идут разом и без общей паузы между запросами (gemini.MIN_INTERVAL —
    на процесс); упрётся в минутный лимит Gemini — очередь по одному, как у сведения."""
    chat_id = str(chat_id)
    for chat, process in list(_READING.items()):
        if process.poll() is not None:
            del _READING[chat]
    if chat_id in _READING:
        return False
    process = subprocess.Popen([sys.executable, "-m", "src.pamyatka", "--read", chat_id], cwd=config.ROOT, stdin=subprocess.PIPE)
    process.stdin.write(text.encode())
    process.stdin.close()
    _READING[chat_id] = process
    return True


def finish(seconds: float = 120) -> None:
    """Конец смены: идущие проверки дочитываются — машина Actions с концом задания гасит процессы,
    и человек, приславший текст последним, остался бы без ответа с потраченной проверкой."""
    for process in _READING.values():
        try:
            process.wait(seconds)
        except subprocess.TimeoutExpired:
            pass


def _read(chat_id: str) -> None:
    """Процесс проверки: текст из stdin — модели, ответ — человеку. В лог идёт только род сбоя: в тексте
    ошибки Telegram и в словах модели могли бы оказаться строки человека."""
    from . import telegram

    try:
        shown = found(sys.stdin.buffer.read().decode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001 — оба генератора недоступны: человеку — честная строка
        print(f"ПРОВЕРКА ТЕКСТА: модель не ответила — {type(exc).__name__}")
        shown = None
    try:
        text, rows = report(shown)
        telegram.send_message(chat_id, text, buttons=rows)
    except Exception as exc:  # noqa: BLE001
        print(f"ПРОВЕРКА ТЕКСТА: ответ не ушёл — {type(exc).__name__}")


# Пробы генератора: строки свои, не из чужих треков; названия — те, что стоят в самом законе и в новостях,
# сленга здесь нет. Вторым полем — номера строк с названием вещества; None — намёк, годится любой ответ.
PROBES: tuple[tuple[str, set[int] | None], ...] = (
    ("Ночь, район, фонари не горят\nВ кармане кокаин, друзья говорят\nА я молчу и смотрю в окно", {2}),
    ("Он начинал с травы за гаражами\nПотом героин — и мы его не узнали\nМама плачет, а двор молчит", {1, 2}),
    ("Мефедрон забрал у меня брата\nЯ помню его смех, он был когда-то", {1}),
    ("На столе амфетамин и чей-то паспорт\nВ этой квартире давно никто не спасся", {1}),
    ("Курим гашиш, за окном минус двадцать\nМне двадцать один, и некуда деваться", {1}),
    ("Экстази в клубе, ЛСД на афише\nЯ вышел на воздух, я этого выше", {1}),
    ("Я встаю в шесть утра и бегу на завод\nМама звонит, говорит: всё пройдёт\nДеньги придут, а пока только пот", set()),
    ("Мы пили вино и курили на крыше\nСигареты кончались, а город всё тише", set()),
    ("Трава у дома зелёная, как в детстве\nЯ вернулся сюда — и некуда деться", set()),
    ("Меня накрыло, я не сплю третьи сутки\nБелый порошок на зеркале — не шутки", None),
)


def probe() -> int:
    """Читает ли генератор тексты с названиями веществ — живой запрос на каждую пробу (prompts/service/tekst.md).
    Из России Gemini не отвечает, поэтому только из Actions; чтобы отказ основного не спрятал запасной,
    запускать с пустым LLM_FALLBACK. Отказ — skip или ответ не по схеме, сбой — генератор недоступен.
    Итог — отказы и сбои вместе: больше одного из десяти — проверку текста на этом генераторе не держать."""
    from . import llm

    bad = misses = 0
    for n, (text, want) in enumerate(PROBES, 1):
        try:
            answer = llm.generate_tekst(lines_of(text))
        except Exception as exc:  # noqa: BLE001
            bad += 1
            print(f"  {n}. СБОЙ: {exc}")
            continue
        if answer.get("skip") or not isinstance(answer.get("lines"), list):
            bad += 1
            print(f"  {n}. ОТКАЗ: {answer.get('reason') or answer.get('text') or 'ответ не по схеме'}")
            continue
        got = {lines_of(text).index(line) + 1 for line in flagged(lines_of(text), answer["lines"])}
        ok = want is None or got == want
        misses += not ok
        print(f"  {n}. {'ок' if ok else 'МИМО'}: строки {sorted(got)}" + ("" if want is None else f", ждали {sorted(want)}"))
    print(f"Отказов и сбоев: {bad} из {len(PROBES)}; ответил, но мимо: {misses}.")
    return bad


def aired(moment: datetime) -> bool:
    """Вышла ли памятка в эти сутки ленты — по журналу публикаций, как счёт релизов (publish.releases_today)."""
    from . import publish

    today = publish.feed_day(moment)
    return any(item.get("rubric") == RUBRIC and (at := state._parse(item.get("published_at", "")))
               and publish.feed_day(at) == today
               for item in state.read_json(config.POSTED_FILE, {"items": []}).get("items", []))


def due(moment: datetime | None = None) -> bool:
    """День рубрики с PAMYATKA_HOUR_MSK по Москве, не ночью, и в эти сутки ленты памятка ещё не выходила."""
    from . import publish
    from .compose import MSK

    moment = moment or state.now()
    local = moment.astimezone(MSK)
    return (local.weekday() in config.PAMYATKA_DAYS and local.hour >= config.PAMYATKA_HOUR_MSK
            and not publish.night(moment) and not aired(moment))


def day(moment: datetime | None = None) -> bool:
    """Отданы ли сутки ленты ПАМЯТКЕ: она сегодня уже вышла либо сегодня её день и в базе есть невышедшая.
    В такие сутки пост о релизе не выходит (publish.release_due) — с их начала, а не с 12:00:
    иначе утренний релиз и памятка днём давали бы тот самый лишний пост."""
    from . import publish

    moment = moment or state.now()
    return aired(moment) or publish.feed_day(moment).weekday() in config.PAMYATKA_DAYS and bool(pending())


def took(released: datetime, moment: datetime | None = None) -> bool:
    """Забрала ли ПАМЯТКА выход релиза насовсем: его день (дата выхода по Москве) отдан ей — в те сутки
    ленты она вышла либо это день рубрики с невышедшей записью — и эти сутки уже начались. Такой пост
    не выходит и не пишется (publish.next_post, compose.do_fresh). Ночью до 9:00 МСК своего дня релиз
    выходить вправе: это хвост вчерашних суток ленты, памятке они не отданы."""
    from . import publish
    from .compose import MSK

    born = released.astimezone(MSK).date()
    if publish.feed_day(moment or state.now()) < born:
        return False
    return aired(datetime.combine(born, time(12), MSK)) or born.weekday() in config.PAMYATKA_DAYS and bool(pending())


def air() -> str:
    """Выход из дежурства (moderate.publish_shift): id вышедшей записи или пустая строка.
    Не вышло — отметка снимается, и следующий заход пробует снова."""
    from . import publish, telegram

    left = pending()
    if not left or not due():
        return ""
    post = build(left[0])
    path = config.ARCHIVE / f"{RUBRIC}-{post['id']}.json"
    config.ARCHIVE.mkdir(parents=True, exist_ok=True)
    state.write_json(path, post)
    try:
        publish.to_channel(post, path, config.secret("TELEGRAM_CHANNEL_ID"))
    except Exception:
        path.unlink(missing_ok=True)
        raise
    if len(left) == 1:
        try:
            telegram.send_message(config.secret("TELEGRAM_ADMIN_ID"), LAST.format(title=html.escape(post["title"])))
        except telegram.TelegramError as exc:  # памятка уже вышла — строка владельцу её не отменяет
            print(f"  памятка: строка о запасе не ушла: {str(exc)[:120]}")
    return post["id"]


def shot(post: dict) -> Path:
    """Карточка поста: заголовок крупно, «ПАМЯТКА» — рубрикой (publish.send)."""
    from . import card

    return card.save(post["title"][:1].upper() + post["title"][1:], [], label="ПАМЯТКА", name=RUBRIC)


def _selftest_text() -> None:
    """Проверка текста: границы раздела «проверка текста» выше — модель и Telegram подменены."""
    import contextlib
    import io

    from . import llm, telegram

    law = "\n\n".join(_parts(find(SLOVA)))
    assert law and TEXT_MARK in TEXT_ASK and TEXT_MARK in TEXT_LONG and "не юрист" in TEXT_ASK and len(TEXT_KEY.encode()) <= 64
    song = "первая строка\n\n  вторая <строка> про вещество  \nтретья строка\nвторая <строка> про вещество\n"
    lines = lines_of(song)
    assert lines == ["первая строка", "вторая <строка> про вещество", "третья строка", "вторая <строка> про вещество"]
    assert flagged(lines, [4, "2", 9, 0, -3, True, 2.5, None, "вещество"]) == [lines[1]], "номер мимо текста и не номер — прочь, припев — раз"
    real = llm.generate_tekst, telegram.send_message, subprocess.Popen, sys.stdin
    said, sent, spawned, log = [], [], [], io.StringIO()
    try:
        # Найдено: в ответе шаблон, строка человека, запись о законе и оговорка — и ничего больше: ни слов модели,
        # ни строки, которой в тексте нет, ни строки, которую модель не назвала.
        llm.generate_tekst = lambda asked: said.append(asked) or {"skip": False, "lines": [2, 4, 7, "слово модели"], "text": "слово модели"}
        text, rows = report(found(song))
        assert said == [lines] and text == "\n\n".join([
            TEXT_HEAD, f"{TEXT_FOUND}\n<blockquote>вторая &lt;строка&gt; про вещество</blockquote>", law, f"{TEXT_MAYBE} {TEXT_NOTE}"]), text
        assert [key["callback_data"] for row in rows for key in row] == [TEXT_KEY, f"{PICK}0"]
        replies = [text]
        # Не найдено: названная в задаче строка, без «чисто»; запись о законе — кнопкой.
        llm.generate_tekst = lambda asked: {"skip": False, "lines": []}
        text, rows = report(found(song))
        assert text == f"{TEXT_HEAD}\n\n{TEXT_NONE}\n\n{TEXT_NOTE}" and rows[0][0]["callback_data"] == f"{PICK}{SLOVA}"
        replies.append(text)
        # Отказ модели, проза запасного генератора и ответ не по схеме — честная строка, а не «названий нет».
        with contextlib.redirect_stdout(log):
            for answer in ({"skip": True, "text": "", "reason": "Gemini: PROHIBITED_CONTENT"},
                           {"skip": False, "text": f"В строке «{lines[1]}» названо вещество", "reason": ""},
                           {"skip": True, "text": "", "reason": f"не буду читать: {lines[1]}"}, {"skip": False, "lines": "2"}):
                llm.generate_tekst = lambda asked, answer=answer: answer
                assert found(song) is None, answer
        assert report(None)[0] == f"{TEXT_HEAD}\n\n{TEXT_FAIL}" and "PROHIBITED_CONTENT" in log.getvalue() and "строка" not in log.getvalue()
        replies.append(report(None)[0])
        # Все строки названы в тексте предельной длины, и строка без переносов: ответ влезает в сообщение целиком.
        llm.generate_tekst = lambda asked: {"skip": False, "lines": list(range(1, len(asked) + 1))}
        for long in ("\n".join(f"строка {n} " + "&<>" * 9 for n in range(400))[:config.TEKST_CHARS], "слово " * (config.TEKST_CHARS // 6)):
            text, _ = report(found(long))
            assert len(telegram.sanitize(text)) <= telegram.MAX_TEXT and text.count("<blockquote>") == text.count("</blockquote>") == 1
            assert law in text and TEXT_NOTE in text and ("…и ещё " in text) == ("\n" in long) and ("…</blockquote>" in text) != ("\n" in long)
        # Процесс проверки: текст — из stdin, ответ — человеку; ни сбой модели, ни сбой отправки текст в лог не несут.
        telegram.send_message = lambda chat, text, buttons=None, **_: sent.append((chat, text, buttons))
        sys.stdin = type("In", (), {"buffer": io.BytesIO(song.encode())})()
        llm.generate_tekst = lambda asked: {"skip": False, "lines": [2]}
        _read("7")
        assert sent == [("7", *report([lines[1]]))], sent
        with contextlib.redirect_stdout(log):
            for breaks in (lambda asked: 1 / 0, lambda asked: (_ for _ in ()).throw(RuntimeError(song))):
                sys.stdin = type("In", (), {"buffer": io.BytesIO(song.encode())})()
                llm.generate_tekst = breaks
                _read("7")
                assert sent[-1] == ("7", *report(None))
            telegram.send_message = lambda chat, text, **_: (_ for _ in ()).throw(telegram.TelegramError(text))
            sys.stdin = type("In", (), {"buffer": io.BytesIO(song.encode())})()
            _read("7")
        assert "строка" not in log.getvalue() and log.getvalue().count("ПРОВЕРКА ТЕКСТА:") == 8, log.getvalue()
        # Дежурство: текст уходит процессу через stdin — в строке запуска его нет; второй текст того же человека
        # ждёт конца первого, чужой — нет; кончившийся процесс место освобождает.
        popen = real[2]
        subprocess.Popen = lambda args, **kw: spawned.append((args, kw)) or popen(["sleep", "30"], stdin=subprocess.PIPE)
        assert take(7, song) and not take("7", song) and take("8", song) and len(spawned) == 2
        assert spawned[0] == ([sys.executable, "-m", "src.pamyatka", "--read", "7"], {"cwd": config.ROOT, "stdin": subprocess.PIPE})
        for process in _READING.values():
            process.kill()
        finish()
        assert take("7", song) and len(spawned) == 3 and set(_READING) == {"7"}
    finally:
        llm.generate_tekst, telegram.send_message, subprocess.Popen, sys.stdin = real
        for process in _READING.values():
            process.kill()
            process.wait()
        _READING.clear()
    # Ни в одном ответе нет вердикта и нет совета, как переписать: слова закона не в счёт — это цитата.
    verdict = ("чист", "можно", "нельзя", "нарушен", "нарушает", "законн", "разреш", "запрещ", "безопасн", "легальн", "пройд",
               "замен", "синоним", "перепи", "вместо")
    for text in (TEXT_ASK, TEXT_WAIT, TEXT_BUSY, TEXT_LONG, TEXT_LIMIT, TEXT_FULL, TEXT_BUTTON, TEXT_AGAIN, *replies):
        assert not [word for word in verdict if word in text.replace(law, "").casefold()], text
    assert all("не юрист" in text for text in (TEXT_ASK, *replies[:2])), "оговорка — на экране вопроса и в ответах"
    # Пробы генератора — свои строки; в ответ человеку они не попадают, промпт веществ не называет.
    prompt = (config.PROMPTS / "service" / "tekst.md").read_text(encoding="utf-8").casefold()
    named = {word.casefold() for text, want in PROBES if want for n in want for word in re.findall(r"\w{5,}", lines_of(text)[n - 1])}
    assert len(PROBES) == 10 and sum(bool(want) for _, want in PROBES) >= 5 and not [word for word in named if word in prompt]


def _selftest() -> None:
    import os

    from . import compose, publish, quality, skleyka, telegram

    # Настоящая база: у каждой записи источник, подпись влезает в подпись к фото, сказанное о боте стоит на коде.
    base = load()
    assert len(base) >= 16 and len({item["id"] for item in base}) == len(base), "id записей не повторяются"
    link = f'<a href="https://t.me/{config.BOT_HANDLE.lstrip("@")}?start={RUBRIC}">в боте</a>'
    for item in base:
        text, cited = build(item)["text"], " ".join(item.get("sources") or [])
        assert re.fullmatch(r"[a-z0-9-]+", item["id"]) and not item["id"].isdigit() and cited, f"{item['id']}: нет источника"
        # Последняя строка зовёт в бота: своя — в биты или сведение, у записи про права без своей — призыв в раздел.
        assert item.get("topic") in ICONS and text.count("<a href") == 1, f"{item['id']}: тема и одна ссылка в бота"
        assert item.get("bot") or text.endswith(CALL.replace("в боте", link)), f"{item['id']}: призыв — последней строкой"
        assert not item.get("bot") or item["start"].partition("_")[0] in DOORS and CALL not in text, f"{item['id']}: своя строка — с кнопкой"
        assert not re.search(r"(?<![:/\w<])/[a-z]", text), f"{item['id']}: команда в посте канала не нажимается"
        # Раздел в боте: вопрос влезает в кнопку, её данные — в 64 байта, ответ — без призыва и ссылки.
        reply, keys = answer(item)
        assert 0 < len(item.get("ask") or "") <= 36 and len(f"{PICK}{item['id']}".encode()) <= 64, f"{item['id']}: кнопка"
        assert reply == text.split("\n\n▸")[0] + (f"\n\n{html.escape(item['bot'])}" if item.get("bot") else ""), item["id"]
        assert telegram.visible_len(reply) <= telegram.MAX_TEXT and keys[-1][0]["text"] == BACK
        assert [key["callback_data"] for row in keys for key in row] == \
            [f"s:{item.get('start', '').partition('_')[0]}"] * bool(item.get("bot")) + [TEXT_KEY] * (item["id"] == SLOVA) + \
            [f"{PICK}{item['topic']}.{[row for row in base if row['topic'] == item['topic']].index(item) // config.PAMYATKA_PAGE}"]
        assert telegram.visible_len(text) <= quality.CAPTION_LIMIT, f"{item['id']}: подпись {telegram.visible_len(text)} знаков"
        assert set(re.findall(r"ст\. (\d+)", text)) == set(re.findall(r"ст\. (\d+)", cited)), f"{item['id']}: статьи текста и источника"
        assert all(key in skleyka.TAKE_FLAWS for key in re.findall(r'TAKE_FLAWS\["(\w+)"\]', cited)), item["id"]
        assert not item.get("bot") or f'?start={item["start"]}">' in text, f"{item['id']}: «в боте» не стало ссылкой"
        assert "prod." not in text or config.BEAT_CREDIT in text, f"{item['id']}: условие бита — config.BEAT_CREDIT"
        assert " ГБ" not in text or f"до {config.SKLEYKA_LINK_MB // 1024} ГБ и {config.SKLEYKA_LINK_FILES} файлов" in text, f"{item['id']}: лимиты облака — из config"
        assert "Проверить свой голос" not in text, f"{item['id']}: отдельной проверки голоса в боте нет"
        # Совет — только у записи о голосе и о правах по ГК: запись о запрете показывает текст закона, и всё.
        assert "Что делать" not in text or "ГК РФ" in cited or item["topic"] != LAW, f"{item['id']}: совет в записи о запрете"
    # Вход в раздел (владелец 10.10.2026): вступление, оговорка, строка о канале и три кнопки — проверка текста
    # и две темы; ни одного вопроса. Кнопки прежнего общего списка (число — страница и «← Все вопросы»)
    # и тема, которой нет, ведут сюда же.
    first, keys = screen()
    assert first.startswith(f"{HEAD}\n\n{INTRO}\n\n{NOTE}") and (config.CHANNEL_HANDLE in first) == bool(pending())
    assert config.PAMYATKA_DAYS == (2, 5), "MORE называет среду и субботу"
    assert keys == [[{"text": TEXT_BUTTON, "callback_data": TEXT_KEY}],
                    [{"text": "⚖️ Права и закон", "callback_data": f"{PICK}{LAW}.0"}],
                    [{"text": "🎙 Запись голоса", "callback_data": f"{PICK}golos.0"}]], "вход: проверка текста и две темы"
    assert all(screen(old) == (first, keys) for old in ("0", "1", "2", "99", "нет-такой", "нет.1", ".", HOME.removeprefix(PICK)))
    assert set(TOPICS) == set(ICONS) and telegram.visible_len(first) <= telegram.MAX_TEXT
    # Экран темы: только её записи, каждая ровно одной кнопкой, страницы листаются в обе стороны, «← Назад» —
    # на вход без счёта; оговорка о юристе — в теме закона, проверки текста в темах нет; всё в лимитах Telegram.
    reach = []
    for topic in TOPICS:
        mine = [f"{PICK}{item['id']}" for item in base if item["topic"] == topic]
        pages = [screen(f"{topic}.{n}") for n in range(-(-len(mine) // config.PAMYATKA_PAGE))]
        assert pages and screen(topic) == screen(f"{topic}.²") == pages[0] and screen(f"{topic}.99") == pages[-1], "лишний номер — последняя"
        asked = []
        for n, (text, rows) in enumerate(pages):
            marks = [key["callback_data"] for row in rows for key in row]
            assert rows[-1] == [{"text": "← Назад", "callback_data": HOME}] and TEXT_KEY not in marks and marks.pop() == HOME
            assert [mark for mark in marks if "." in mark] == [f"{PICK}{topic}.{m}" for m in (n - 1, n + 1) if 0 <= m < len(pages)], (topic, n)
            asked += [mark for mark in marks if "." not in mark]
            assert (NOTE in text) == (topic == LAW) and HEAD not in text and INTRO not in text and TOPICS[topic].lower() in text
            assert telegram.visible_len(text) <= telegram.MAX_TEXT and len(rows) <= config.PAMYATKA_PAGE + 2
            assert all(len(key["callback_data"].encode()) <= 64 and len(key["text"]) <= 40 for row in rows for key in row)
        assert asked == mine, f"{topic}: все записи темы, по разу, в порядке базы"
        reach += asked
    # Любая запись базы — за два нажатия от входа (тема, вопрос) плюс листание; хвост кнопки записи не спутать с экраном.
    assert sorted(reach) == sorted(f"{PICK}{item['id']}" for item in base) and all(find(mark.removeprefix(PICK)) for mark in reach)
    assert find("") is None and find("1") is None and find(f"{LAW}.0") is None and find(LAW), "запись prava — не тема prava"
    _selftest_text()

    at = lambda stamp: datetime.fromisoformat(f"2026-10-{stamp}:00+03:00")  # noqa: E731 — 07.10 среда, 10.10 суббота
    real = (state.now, config.ARCHIVE, config.POSTED_FILE, config.PAMYATKA_FILE, publish.to_channel, telegram.send_message,
            config.QUEUE, config.INBOX_FILE, compose.USED_FILE, compose.release_jobs, compose.do_now)
    with tempfile.TemporaryDirectory() as tmp:
        config.ARCHIVE, config.POSTED_FILE, config.PAMYATKA_FILE = Path(tmp) / "archive", Path(tmp) / "posted.json", Path(tmp) / "base.json"
        config.QUEUE, config.INBOX_FILE, compose.USED_FILE = Path(tmp) / "queue", Path(tmp) / "inbox.jsonl", Path(tmp) / "used.json"
        # Релиз суток памятки на утро не переносится (took). Выход в 07:00 UTC — это 10:00 МСК, так ставит iTunes:
        # пост годен ещё час следующих суток ленты, и без условия пост среды, более весомый, в четверг обошёл бы свежий.
        out = "2026-10-{:02d}T07:00:00+00:00".format

        def queued(date: int, score: int) -> Path:  # готовый к выходу пост о релизе этого числа
            state.write_json(path := config.QUEUE / f"{date}.json",
                             {"rubric": "release", "score": score, "full_track_file_id": "x", "released_at": out(date)})
            return path

        def found() -> list[str]:  # о каких находках сбор написал бы пост (compose.do_fresh), без модели
            written.clear()
            compose.do_fresh(False)
            return written

        written: list[str] = []
        compose.release_jobs = lambda items, *_: [("", "release", {}, item) for item in items]
        compose.do_now = lambda count, jobs: written.extend(source["fingerprint"] for *_, source in jobs) or 0
        state.append_jsonl(config.INBOX_FILE, [
            {"kind": "release", "fingerprint": f"день {date}", "score": 90, "artist": "Артист", "tracked": "Артист",
             "title": f"Релиз {date}", "released_at": out(date)} for date in (7, 8, 14)])
        os.environ.setdefault("TELEGRAM_CHANNEL_ID", "-1")
        os.environ.setdefault("TELEGRAM_ADMIN_ID", "1")
        sent, lines = [], []
        channel = lambda post, path, chat: (sent.append(post), publish.record(post, path, "channel"))  # noqa: E731
        publish.to_channel = channel
        telegram.send_message = lambda chat, text, **_: lines.append(text)
        items = [{"id": key, "title": f"запись {key}", "text": ["Текст."], "sources": ["ГК РФ"]} for key in "abc"]
        state.write_json(config.PAMYATKA_FILE, items[:2])
        try:
            state.now = lambda: at("06T13:00")
            assert not due() and air() == "" and not day() and publish.release_due(), "вторник — молчит, релиз выходит"
            state.write_json(config.POSTED_FILE, {"items": [{"rubric": "release", "published_at": state.iso(at("06T10:00"))}]})
            assert not publish.release_due(), "в обычный день лимит релизов прежний"
            state.write_json(config.POSTED_FILE, {"items": []})
            state.now = lambda: at("07T04:00")
            wed = queued(7, 99)
            assert publish.release_due() and publish.next_post(releases=True) == wed, "среда, 4:00 — хвост суток вторника, пост среды выходит"
            assert found() == ["день 7"], "и находка среды ночью пишется"
            state.now = lambda: at("07T08:00")
            assert not day() and publish.release_due(), "среда до 9:00 — ещё сутки вторника, релиз выходит"
            state.now = lambda: at("07T09:30")
            assert day() and not publish.release_due() and air() == "", "сутки среды отданы памятке с начала, сама она — с 12:00"
            assert publish.next_post(releases=True, dry_run=True) is None and wed.exists(), "сухой прогон очередь не трогает"
            assert publish.next_post(releases=True) is None and not wed.exists(), "сутки среды начались — пост среды убран из очереди"
            assert found() == [], "находка среды в её сутки не пишется — памятка ещё не вышла, но запись в базе есть"
            assert not took(at("06T10:00")), "релиз вторника — обычного дня — памятка не забирает"
            state.now = lambda: at("07T12:30")
            assert air() == "a" and sent[0]["text"] == "<b>ПАМЯТКА: запись a</b>\n\nТекст." and not lines
            assert air() == "" and len(sent) == 1, "одна запись в сутки"
            assert day() and not publish.release_due(), "памятка вышла — релиз в эти сутки не выходит"
            state.now = lambda: at("08T02:00")
            assert not publish.release_due() and air() == "", "ночь четверга — хвост суток среды"
            state.now = lambda: at("08T03:20")
            assert found() == ["день 8"], "в сутки памятки находка среды не пишется, находка четверга — пишется"
            state.now = lambda: at("08T09:20")
            wed, thu = queued(7, 99), queued(8, 1)
            assert publish.next_post(releases=True) == thu and not wed.exists(), "четверг, 9:20 — пост среды не выходит, пост четверга выходит"
            assert found() == ["день 8"], "и сбор в 9:17 пост среды заново не пишет"
            thu.unlink()
            state.now = lambda: at("08T09:30")
            assert not day() and publish.release_due(), "четверг — релиз выходит как раньше"
            state.now = lambda: at("10T23:30")
            assert not due(), "ночью — молчит"
            state.now = lambda: at("10T12:30")
            assert air() == "b" and len(lines) == 1 and "Запас ПАМЯТКИ кончился" in lines[0], "порядок базы, с последней — строка владельцу"
            state.now = lambda: at("14T12:30")
            assert air() == "" and len(sent) == 2 and len(lines) == 1, "база кончилась — молчит, строка одна"
            assert not day() and publish.release_due(), "база кончилась — релизы в дни рубрики как раньше"
            late = queued(14, 1)
            assert publish.next_post(releases=True) == late and found() == ["день 14"], "и пост среды остаётся в очереди и пишется"
            state.write_json(config.PAMYATKA_FILE, items)
            publish.to_channel = lambda *a: 1 / 0
            try:
                air()
            except ZeroDivisionError:
                pass
            assert not (config.ARCHIVE / "pamyatka-c.json").exists() and day(), "сбой отправки снимает отметку"
            publish.to_channel = channel
            assert air() == "c" and [post["id"] for post in sent] == ["a", "b", "c"], "после сбоя — та же запись"
        finally:
            (state.now, config.ARCHIVE, config.POSTED_FILE, config.PAMYATKA_FILE, publish.to_channel, telegram.send_message,
             config.QUEUE, config.INBOX_FILE, compose.USED_FILE, compose.release_jobs, compose.do_now) = real
    print("pamyatka: самопроверка пройдена")


def main() -> None:
    parser = argparse.ArgumentParser(description="ПАМЯТКА: пост-совет артисту по средам и субботам")
    parser.add_argument("--selftest", action="store_true", help="проверка без сети и Telegram")
    parser.add_argument("--dry-run", action="store_true", help="что в запасе и какой пост вышел бы следующим, без записи")
    parser.add_argument("--probe", action="store_true",
                        help="читает ли генератор тексты с названиями веществ: десять проб — только из Actions")
    parser.add_argument("--read", metavar="ЧАТ", help=argparse.SUPPRESS)  # процесс проверки текста: его запускает дежурство
    args = parser.parse_args()
    if args.selftest:
        return _selftest()
    if args.probe:
        return 1 if probe() > 1 else 0
    if args.read:
        return _read(args.read)
    from . import telegram

    left = pending()
    print(f"В базе: {len(load())}, не вышло: {len(left)}; сутки отданы памятке: {day()}; сейчас можно выйти: {bool(left) and due()}")
    for item in left:
        print(f"  {item['id']}: подпись {telegram.visible_len(build(item)['text'])} знаков — {item['title']}")
    print("В боте: " + ", ".join(f"«{name}» — {sum(item.get('topic') == key for item in load())}" for key, name in TOPICS.items())
          + f" вопросов, по {config.PAMYATKA_PAGE} на экран; счёт — python -m src.service --sources | grep ПАМЯТКА")
    print("\n" + build(left[0])["text"] if left else "Запас кончился: рубрика молчит, релизы в её дни выходят как раньше.")


if __name__ == "__main__":
    sys.exit(main())
