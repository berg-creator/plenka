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
    python -m src.setup --announce           пост про бота в канал и ВК

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
CARD = """<b>ПЛЁНКА</b> — откуда взялся звук.

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
# Команд две — по разделу, и названы они как на кнопках меню (service.MENU).
# «Что тут есть» ничего не называло, а разбор текста — лишь один из видов
# ПРОЯВКИ, которую бот и так угадывает по сообщению. Старые названия бот
# по-прежнему понимает при наборе, просто не показывает.
BOT_COMMANDS = [
    ("otbor", "🎙 ОТБОР — прислать свой трек в канал"),
    ("skleyka", "🎛 СКЛЕЙКА — свести вокал с битом в трек"),
    ("proyavka", "🎞 ПРОЯВКА — откуда взялась музыка"),
    ("slezhu", "🔔 СЛЕЖУ — релизы и концерты артистов"),
    ("sved", "🪞 ДВОЙНИК — на сколько ты совпал с артистом"),
    ("vkladysh", "📼 ВКЛАДЫШ — трек для друга со всеми площадками"),
]

# Экран до нажатия «Начать»: единственный шанс объяснить, зачем сюда пришли.
# Первая строка — корейский пустой символ (U+3164): отступ от заголовка Telegram
# «Что может делать этот бот?». Перевод строки и пустой символ Брайля в начале
# API срезает, этот оставляет.
BOT_DESCRIPTION = (
    "\u3164\n"
    "Бот музыкального канала ПЛЁНКА.\n\n"
    "🎙 ОТБОР. Пишешь сам? Пришли свой трек — он выйдет в канале с твоим именем.\n\n"
    "🎛 СКЛЕЙКА. Пришли вокал и бит — сведу их в готовый трек.\n\n"
    "🎞 ПРОЯВКА. Пришли артиста, песню или строки из текста — расскажу, откуда это взялось.\n\n"
    "🔔 СЛЕЖУ. Назови артистов и свой город — напишу, когда выйдет релиз или объявят концерт.\n\n"
    "🪞 ДВОЙНИК. Узнай, на сколько процентов твоя музыка совпадает с артистами.\n\n"
    # Ссылку словом описание не умеет — только текстом, @адрес в нём нажимается.
    # Без адреса владелец пробовал 16.09.2026 и вернул: подписаться отсюда не на что нажать.
    f"Всё бесплатно — достаточно подписаться на канал {config.CHANNEL_HANDLE}."
)

BOT_SHORT = "Пришли свой трек — выйдет в канале @plenka_fm. И расскажу, откуда взялась музыка."

# Описание канала: 255 знаков, видно до подписки — там должно быть и про что
# канал, и что у него есть бот. Первая строка — как её поставил владелец;
# жанрами канал не описываем (владелец, 16.09.2026).
CHANNEL_DESCRIPTION = (
    "Откуда взялся звук?\n\n"
    "Бот {bot}: пришли свой трек — выйдет в канале. И разберёт любого артиста или песню."
)

# Пост про бота, закреплён в канале. Ссылок в тексте нет — под ним кнопки:
# две дороги в одно место в коротком посте выглядят суетой. Отбор первым,
# как в меню бота: ради него из канала идут в бота (GROWTH.md, «Третий актив»).
# Первая строка — то, что видно в плашке закрепа, поэтому в ней само дело.
# Прежний пост звал разбирать плейлист; про отбор в нём не было ни слова
# (владелец, 16.09.2026).
ANNOUNCE_TG = """<b>Пишешь музыку? Пришли свой трек в бота — он выйдет в канале с твоим именем.</b>

🎙 <b>ОТБОР</b>
Трек — ссылкой, «Артист — Трек» или файлом. Он должен быть уже выложен хоть на одной площадке, а тебя самого пока не должны знать тысячи. Выходит по одному в день, по очереди, и тебе приходит ссылка на пост — кидай своим.

🎞 <b>ПРОЯВКА</b>
Пришли артиста, песню или строки из текста — бот расскажет, откуда это взялось. Если связь не подтверждена, так и скажет: выдумывать про музыку не станет.

🔔 <b>СЛЕЖУ</b>
Назови артистов и свой город — бот напишет, когда у них выйдет релиз или они объявят у тебя концерт.

Всё <b>бесплатно</b> — достаточно подписаться на канал."""

VK_ANNOUNCE = """Пишешь музыку? Пришли свой трек в бота ПЛЁНКИ — он выйдет в канале с твоим именем.

ОТБОР. Трек — ссылкой, «Артист — Трек» или файлом. Он должен быть уже выложен хоть на одной площадке, а тебя самого пока не должны знать тысячи. Выходит по одному в день, по очереди, и тебе приходит ссылка на пост.

ПРОЯВКА. Пришли артиста, песню или строки из текста — бот расскажет, откуда это взялось. Если связь не подтверждена, так и скажет: выдумывать про музыку не станет.

СЛЕЖУ. Назови артистов и свой город — бот напишет, когда у них выйдет релиз или они объявят у тебя концерт.

Всё бесплатно — достаточно подписаться на канал. Бот живёт в телеграме: {link}"""


def announce_buttons() -> list[list[dict]]:
    # ?start=pin открывает заявку сразу и считается в bot_sources.json.
    return (telegram.url_button("🎙 Прислать свой трек", bot_link("pin"))
            + telegram.url_button("🎞 Проявка", bot_link("proyavka"))
            + telegram.url_button("🔔 Следить за артистами", bot_link("slezhu")))


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

    # Реакция — самое дешёвое действие читателя: один тап, и пост поднимается.
    # Но боту этот список виден не всегда: у канала внутри сообщества getChat
    # отдаёт одну платную реакцию, даже когда в настройках стоят все
    # (проверено 12.09.2026 на @plenka_fm). Поэтому строка показывает, что
    # ответил API, и не выносит вердикт: пугать «реакции выключены» там,
    # где они включены, хуже, чем промолчать.
    reactions = info.get("available_reactions")
    emoji = [r for r in (reactions or []) if r.get("type") == "emoji"]
    if reactions is None:
        print("  ✓ реакции включены (все)")
    elif emoji:
        print(f"  ✓ реакции включены ({len(emoji)})")
    elif reactions:
        print("  · реакций API не показывает — у канала в сообществе их не видно,")
        print("    проверь глазами: канал → Управление → Реакции")
    else:
        print("  ✗ реакции выключены")
        todo.append(
            "Включи реакции: канал → Управление → Реакции → Все.\n"
            "     Метода в Bot API нет, только руками. Без них не работает\n"
            "     голосование реакциями в конце поста."
        )

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
        tags = bool(rights.get("can_manage_tags"))
        print(f"  {_mark(tags)} бот может ставить метки участникам")
        if not tags:
            todo.append(
                "Выдай боту в чате обсуждений право менять метки участников — оно\n"
                "     в правах администратора чата. Без него СЛЕПАЯ ПРОСЛУШКА не повесит\n"
                "     угадавшим титул «знаток: …» рядом с именем."
            )
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
        for row in buttons:
            print(f"  [ {row[0]['text']} ] → {row[0]['url']}")
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


def announce(publish: bool) -> int:
    """Пост про запуск бота: в канал и во ВКонтакте, с закреплением.

    С предпросмотром по умолчанию: ключом сообщества ВКонтакте публиковать
    можно, а удалять — нельзя, так что «отправил и передумал» тут не работает.
    """
    from . import vk

    buttons = announce_buttons()
    vk_text = VK_ANNOUNCE.format(link=bot_link("pin"))

    if not publish:
        print("\n— — — В КАНАЛ — — —\n")
        print(telegram.sanitize(ANNOUNCE_TG))
        for row in buttons:
            print(f"  [ {row[0]['text']} ] → {row[0]['url']}")
        print("\n— — — ВО ВКОНТАКТЕ — — —\n")
        print(vk_text)
        print("\nОпубликовать и закрепить: python -m src.setup --announce --publish")
        print("Учти: во ВКонтакте пост ключом сообщества потом не удалить.")
        return 0

    channel = config.secret("TELEGRAM_CHANNEL_ID")
    message = telegram.send_message(channel, ANNOUNCE_TG, preview=False, buttons=buttons)
    print(f"Канал: опубликовано, сообщение {message.get('message_id')}.")
    try:
        telegram.pin_message(channel, message["message_id"], notify=True)
        print("Канал: закреплено.")
    except telegram.TelegramError as exc:
        print(f"Канал: закрепить не вышло ({exc}) — нужно право «Закрепление сообщений».")

    # ВКонтакте идёт вторым и на исход не влияет: пост в канале к этому
    # моменту уже вышел, и ошибка на второй площадке его не отменяет.
    try:
        post_id = vk.post(vk_text)
        group = config.secret("VK_GROUP_ID", required=False)
        print(f"ВК: опубликовано, vk.com/{group}?w=wall-{vk.group_id()}_{post_id}")
    except Exception as exc:  # noqa: BLE001 — вторая площадка не роняет первую
        print(f"ВК: не вышло ({exc}).")
        return 0

    # Закрепление ключом сообщества запрещено — как и удаление. Это ограничение
    # ВКонтакте, а не недостаток прав: из приложения то же самое делается в тап.
    try:
        vk.pin(post_id)
        print("ВК: закреплено.")
    except Exception as exc:  # noqa: BLE001
        log.debug("wall.pin недоступен: %s", exc)
        print("ВК: закрепи руками — групповым ключом это запрещено, как и удаление.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Настройка канала, чата и комментариев")
    parser.add_argument("--check", action="store_true", help="что настроено, а что нет")
    parser.add_argument("--card", action="store_true", help="пост-визитка канала")
    parser.add_argument("--rules", action="store_true", help="правила чата обсуждений")
    parser.add_argument("--bot", action="store_true", help="команды и описания бота")
    parser.add_argument("--about", action="store_true", help="описание канала")
    parser.add_argument(
        "--announce", action="store_true", help="пост про бота в канал и ВК, с закреплением"
    )
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
    if args.announce:
        return announce(args.publish)

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
