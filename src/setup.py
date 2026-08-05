"""Настройка витрины канала: проверка, пост-визитка, правила чата.

Канал состоит из трёх разных сущностей, и они постоянно путаются:

    Канал @plenka_fm        сюда пишет бот, читатели только читают
    Чат обсуждений          отдельная группа, куда Telegram пересылает каждый
                            пост; ответы на пересылку и есть «комментарии»
    Бот @plenka_fm_bot      публикует посты, принимает кнопки модерации
                            и выдаёт разборы ПРОЯВКИ в личке

Что где включено, по интерфейсу не видно — половина настроек живёт в правах
бота, половина в свойствах чата. Поэтому есть одна команда, которая показывает
всё сразу и говорит, чего не хватает.

    python -m src.setup --check              что настроено, а что нет
    python -m src.setup --card               показать пост-визитку
    python -m src.setup --card --publish     опубликовать её и закрепить
    python -m src.setup --rules              показать правила чата
    python -m src.setup --rules --publish    отправить их в чат и закрепить
    python -m src.setup --bot                команды и описания бота
    python -m src.setup --about              описание канала
    python -m src.setup --vk                 пост во ВКонтакте про разборы

Всё, что публикует, по умолчанию только показывает: `--publish` добавляется
осознанно. Особенно это важно для ВКонтакте — ключом сообщества пост можно
опубликовать, но нельзя удалить.
"""

from __future__ import annotations

import argparse
import logging

from . import config, telegram

log = logging.getLogger("setup")

# ─────────────────────────── тексты ───────────────────────────

# Абзацы держим одной строкой: Telegram переносит текст сам, а жёсткие переносы
# на узком экране рвут фразы в неожиданных местах.
CARD = """<b>ПЛЁНКА</b> — откуда взялся весь этот тёмный звук.

Фонк собрали в Мемфисе на двух кассетниках, потому что на студию не было денег. Эмо-рэп вырос из гитар нулевых. Половина того, что играет в рилсах, записана до твоего рождения.

Тут разбираем, кто у кого что взял, и говорим, что из нового стоит времени, а что нет.

<b>ОТКУДА НОГИ</b> — ниточка от сегодняшнего трека к его предку
<b>ВЕРДИКТ</b> — разнос или респект новому релизу, без вежливой середины
<b>ИНФОПОВОД</b> — что происходит на сцене, нашей и не нашей
<b>МЕЖДУ СТРОК</b> — что на самом деле сказано в тексте песни
<b>МЕМ</b> — юмор про музыку и индустрию

<b>Комментарии открыты.</b> Спорить можно и нужно — про музыку, а не про людей.

<b>Разборы по запросу</b> — в личке бота {bot}: пришли своих артистов, и он покажет, откуда растёт твой вкус. С картинкой, которую не стыдно кинуть друзьям.

Зеркало во ВКонтакте: {vk}"""

RULES = """Это чат <b>ПЛЁНКИ</b>. Ветки под постами — тоже он.

Спорить о музыке можно и нужно, для этого всё и затевалось.

Переходить на личности, здоровье и семьи артистов — нет. За это банят канал, а не тебя.

Реклама, крипта и «залетай в лс» — сразу и молча в бан.

А если пришёл сказать, что раньше было лучше, — раньше было ровно то же самое, только на кассетах."""


# ─────────────────────────── витрина бота ───────────────────────────

# Список под кнопкой «/» в боте. Telegram принимает в командах только строчную
# латиницу и цифры, поэтому названия транслитом — по-русски они всё равно
# читаются. Кириллицу бот понимает при наборе, но в меню её не показать.
BOT_COMMANDS = [
    ("start", "Что тут есть"),
    ("vkus", "Разбор вкуса по списку артистов + карточка"),
    ("nogi", "Откуда взялся артист, трек или жанр"),
    ("tekst", "Разбор строк из песни"),
]

# Экран до нажатия «Начать»: единственный шанс объяснить, зачем сюда пришли.
BOT_DESCRIPTION = (
    "Разборы от канала ПЛЁНКА.\n\n"
    "Пришли список артистов — покажу, откуда растёт твой вкус, и дам карточку.\n"
    "Пришли одно имя — расскажу, откуда оно выросло.\n"
    "Пришли строки из песни — разберу, что в них происходит.\n\n"
    "Работает для подписчиков канала."
)

BOT_SHORT = "Разборы вкуса и родословной тёмного звука. Канал @plenka_fm"

# Описание канала: 255 знаков, видно до подписки — там должно быть и про что
# канал, и что у него есть бот.
CHANNEL_DESCRIPTION = (
    "Откуда взялся весь тёмный звук: фонк из Мемфиса, эмо-рэп из гитар нулевых. "
    "Разбираем, кто у кого что взял.\n\n"
    "Бот {bot} разберёт твой вкус по списку артистов и пришлёт карточку."
)

VK_ANNOUNCE = """У канала появился бот, который разбирает вкус.

Кидаешь ему список артистов, которых слушаешь, — он показывает, откуда этот вкус растёт: какой трек чей потомок, что откуда взято и в каком году это уже было. В ответ приходит карточка, которую не стыдно кинуть в сторис.

Ещё умеет две вещи. Пришлёшь одно имя или жанр — расскажет, откуда оно выросло. Пришлёшь строки из песни — разберёт, что в них на самом деле происходит.

Врать не умеет принципиально: если связь не подтверждена, так и скажет, вместо того чтобы выдумать красивую историю.

Бот живёт в телеграме: {link}"""


def bot_link(payload: str = "") -> str:
    """Ссылка на бота. С нагрузкой — открывает сразу нужный разбор."""
    name = telegram.check().lstrip("@")
    return f"https://t.me/{name}?start={payload}" if payload else f"https://t.me/{name}"


def card_text() -> str:
    bot = telegram.check()
    group = config.secret("VK_GROUP_ID", required=False)
    vk_link = f"vk.com/{group}" if group else "скоро"
    return CARD.format(bot=bot, vk=vk_link)


# ─────────────────────────── проверка ───────────────────────────


def _mark(ok: bool) -> str:
    return "✓" if ok else "✗"


def check() -> int:
    """Показывает состояние канала, чата и прав бота — с подсказками."""
    channel = config.secret("TELEGRAM_CHANNEL_ID")
    todo: list[str] = []

    bot_name = telegram.check()
    info = telegram.get_chat(channel)
    bot_id = None

    print(f"\nБОТ {bot_name}")
    print(f"\nКАНАЛ {info.get('title', '')} ({channel})")
    print(f"  подписчиков: {telegram.member_count(channel)}")
    print(f"  {_mark(bool(info.get('description')))} описание")
    print(f"  {_mark(bool(info.get('photo')))} аватар")

    # Пустой список реакций — это не «по умолчанию», а выключенные реакции.
    # Самое дешёвое действие читателя: ставится в один тап и поднимает пост.
    reactions = info.get("available_reactions")
    if reactions == []:
        print("  ✗ реакции выключены")
        todo.append(
            "Включи реакции: канал → Управление → Реакции → Все.\n"
            "     Через API это не делается, только руками. Реакция — самое дешёвое\n"
            "     действие читателя, а по ней видно, какие посты заходят."
        )
    else:
        print(f"  ✓ реакции включены ({len(reactions or []) or 'все'})")

    community = info.get("community")
    if community:
        print(f"  · канал входит в сообщество «{community.get('name', '')}»")

    for admin in telegram.administrators(channel):
        user = admin.get("user", {})
        if not user.get("is_bot"):
            continue
        bot_id = user.get("id")
        print(f"  {_mark(bool(admin.get('can_post_messages')))} бот может публиковать")
        print(f"  {_mark(bool(admin.get('can_delete_messages')))} бот может удалять")
        pin = bool(admin.get("can_pin_messages"))
        print(f"  {_mark(pin)} бот может закреплять")
        if not pin:
            todo.append(
                "Выдай боту право «Закрепление сообщений» в правах администратора\n"
                "     канала — иначе пост-визитку придётся закреплять руками."
            )

    linked = info.get("linked_chat_id")
    print("\nЧАТ ОБСУЖДЕНИЙ (он же комментарии под постами)")
    if not linked:
        print("  ✗ не привязан — комментариев под постами нет")
        todo.append(
            "Привяжи чат: канал → Управление → Обсуждение → выбрать группу.\n"
            "     Telegram будет пересылать туда каждый пост, а ответы на пересылку\n"
            "     показываются под постом как комментарии."
        )
        return _report(todo)

    print(f"  ✓ привязан, id {linked}")

    try:
        chat = telegram.get_chat(str(linked))
    except telegram.TelegramError:
        print("  ✗ бота в чате нет — он не увидит комментарии и не сможет модерировать")
        todo.append(
            "Добавь бота в чат обсуждений и сделай администратором с правами\n"
            "     «Удаление сообщений» и «Блокировка пользователей». Без этого он не может\n"
            "     ни открыть ветку первым комментарием, ни убрать спам."
        )
        return _report(todo)

    print(f"  название: {chat.get('title', '')}")
    print(f"  участников: {telegram.member_count(str(linked))}")

    rights = {}
    for admin in telegram.administrators(str(linked)):
        if admin.get("user", {}).get("id") == bot_id:
            rights = admin
    if rights:
        print(f"  {_mark(bool(rights.get('can_delete_messages')))} бот может удалять спам")
        print(f"  {_mark(bool(rights.get('can_restrict_members')))} бот может банить")
    else:
        print("  ✗ бот в чате не администратор")
        todo.append(
            "Сделай бота администратором чата. Обычный участник не получает\n"
            "     пересылки постов, а значит, не может открыть ветку первым комментарием."
        )

    if chat.get("slow_mode_delay"):
        print(f"  ✓ медленный режим: {chat['slow_mode_delay']} сек")
    else:
        print("  · медленный режим выключен")

    print(f"\nПервый комментарий под постами: {'включён' if config.COMMENT_SEED else 'выключен'}"
          f" (config.COMMENT_SEED)")

    return _report(todo)


def _report(todo: list[str]) -> int:
    if not todo:
        print("\nВсё на месте.\n")
        return 0
    print("\nЧТО СДЕЛАТЬ РУКАМИ\n")
    for number, item in enumerate(todo, 1):
        print(f"  {number}. {item}\n")
    return 0


# ─────────────────────────── публикация ───────────────────────────


def setup_bot(publish: bool) -> int:
    """Ставит боту команды и описания — то, что человек видит до первого слова."""
    commands = "\n".join(f"  /{name} — {text}" for name, text in BOT_COMMANDS)
    if not publish:
        print("\n— — — КОМАНДЫ В МЕНЮ — — —\n")
        print(commands)
        print("\n— — — ЭКРАН ДО «НАЧАТЬ» — — —\n")
        print(BOT_DESCRIPTION)
        print("\n— — — СТРОКА В ПОИСКЕ — — —\n")
        print(f"  {BOT_SHORT}")
        print("\nПрименить: python -m src.setup --bot --publish")
        return 0

    telegram.set_my_commands(BOT_COMMANDS)
    telegram.set_my_description(BOT_DESCRIPTION)
    telegram.set_my_short_description(BOT_SHORT)
    print("Витрина бота обновлена: команды, описание, строка в поиске.")
    return 0


def setup_channel_description(publish: bool) -> int:
    """Описание канала — его видно до подписки, вместе с кнопкой «Подписаться»."""
    text = CHANNEL_DESCRIPTION.format(bot=telegram.check())
    if not publish:
        print("\n— — — ОПИСАНИЕ КАНАЛА — — —\n")
        print(text)
        print(f"\n({len(text)} из 255 знаков)")
        print("\nПрименить: python -m src.setup --about --publish")
        return 0

    channel = config.secret("TELEGRAM_CHANNEL_ID")
    try:
        telegram.set_chat_description(channel, text)
    except telegram.TelegramError as exc:
        print(f"Не вышло ({exc}).")
        print("Боту нужно право «Изменение профиля канала» в правах администратора.")
        return 1
    print("Описание канала обновлено.")
    return 0


def publish_card(publish: bool) -> int:
    text = card_text()
    # Кнопка под визиткой — единственный способ увести человека в бота одним
    # касанием. Ссылка с нагрузкой открывает разбор вкуса сразу с инструкцией.
    buttons = telegram.url_button("🎧 Разобрать свой вкус", bot_link("taste"))

    if not publish:
        print("\n— — — ПОСТ-ВИЗИТКА — — —\n")
        print(telegram.sanitize(text))
        print(f"\n  [ {buttons[0][0]['text']} ] → {buttons[0][0]['url']}")
        print("\nОтправить и закрепить: python -m src.setup --card --publish")
        return 0

    channel = config.secret("TELEGRAM_CHANNEL_ID")
    message = telegram.send_message(channel, text, preview=False, buttons=buttons)
    print(f"Визитка опубликована, сообщение {message.get('message_id')}.")

    try:
        telegram.pin_message(channel, message["message_id"])
        print("Закреплена.")
    except telegram.TelegramError as exc:
        print(f"Закрепить не вышло ({exc}) — закрепи руками, это одно касание.")
    return 0


def publish_rules(publish: bool) -> int:
    if not publish:
        print("\n— — — ПРАВИЛА ЧАТА — — —\n")
        print(telegram.sanitize(RULES))
        print("\nОтправить и закрепить: python -m src.setup --rules --publish")
        return 0

    channel = config.secret("TELEGRAM_CHANNEL_ID")
    linked = telegram.get_chat(channel).get("linked_chat_id")
    if not linked:
        print("Чат обсуждений не привязан — сначала привяжи его в настройках канала.")
        return 1

    message = telegram.send_message(str(linked), RULES)
    print(f"Правила отправлены в чат, сообщение {message.get('message_id')}.")

    try:
        telegram.pin_message(str(linked), message["message_id"])
        print("Закреплены.")
    except telegram.TelegramError as exc:
        print(f"Закрепить не вышло ({exc}) — нужны права администратора в чате.")
    return 0


def announce_vk(publish: bool) -> int:
    """Пост во ВКонтакте про разборы.

    Отдельной командой и с предпросмотром по умолчанию: ключом сообщества
    ВКонтакте публиковать можно, а удалять — нельзя, так что «отправил и
    передумал» тут не работает.
    """
    from . import vk

    text = VK_ANNOUNCE.format(link=bot_link("taste"))
    if not publish:
        print("\n— — — ПОСТ ВО ВКОНТАКТЕ — — —\n")
        print(text)
        print("\nОпубликовать: python -m src.setup --vk --publish")
        print("Учти: ключом сообщества пост потом не удалить, только руками из ВК.")
        return 0

    post_id = vk.post(text)
    group = config.secret("VK_GROUP_ID", required=False)
    print(f"Опубликовано: vk.com/{group}?w=wall-{vk.group_id()}_{post_id}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Настройка канала, чата и комментариев")
    parser.add_argument("--check", action="store_true", help="что настроено, а что нет")
    parser.add_argument("--card", action="store_true", help="пост-визитка канала")
    parser.add_argument("--rules", action="store_true", help="правила чата обсуждений")
    parser.add_argument("--bot", action="store_true", help="команды и описания бота")
    parser.add_argument("--about", action="store_true", help="описание канала")
    parser.add_argument("--vk", action="store_true", help="пост во ВКонтакте про разборы")
    parser.add_argument(
        "--publish",
        action="store_true",
        help="не показать, а отправить (к любой из команд выше)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    config.load_dotenv()

    if args.check:
        return check()
    if args.card:
        return publish_card(args.publish)
    if args.rules:
        return publish_rules(args.publish)
    if args.bot:
        return setup_bot(args.publish)
    if args.about:
        return setup_channel_description(args.publish)
    if args.vk:
        return announce_vk(args.publish)

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
