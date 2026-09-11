"""Автопилот точности: облачный Claude сверяет новые посты с данными и сам правит выдумки.

Посты пишет GigaChat, и он выдумывает: звучание, которого нет в данных
(«жёсткий ритм, отрывистый вокал»), прошлое артиста («после серии больших
альбомов» у Смоки Мо, у которого за лето четыре сингла), устройство релиза
(«все треки короткие, кроме последнего» — неправда). Решение владельца
от 11.09.2026 — автопилот: сам он посты не проверяет. Раз в два часа облачный
Claude по его подписке (запланированный агент claude.ai/code, бриф —
prompts/review.md) сверяет новые посты очереди с данными, из которых они
написаны, и вырезает выдумку или заменяет её фактом.

Отвергнуто:

- Список выдумок владельцу. Читать его владелец не будет, а непрочитанный
  список ничем не лучше никакого.
- Claude через API прямо в конвейере. Около $0,7 в день — дороже, чем стоит
  проверка, а подписка владельца уже оплачена.
- Правка из рутины прямо в main. Облачный автор в main пушить не может, поэтому,
  как у роликов (src/reels.py), ветка служит почтовым ящиком: рутина пушит файл
  правок в claude/review-*, воркфлоу review.yml проверяет его, применяет к main
  и удаляет ветку.

Путь одной правки:

1. Рутина смотрит git log. Новых постов бота с прошлого прохода нет — выходит,
   ничего не читая: лимиты подписки не бесконечны. Есть — сверяет и пишет
   content/review/<ГГГГММДД-ЧЧММ>.json: пост, rewrite (новый полный текст)
   или drop (снять из очереди), дословная цитата выдумки и чего нет в данных.
   Выдумок нет — не пушит ничего.
2. --check на снимке, по которому рутина писала правки: цитата есть в посте
   и ушла из нового текста, новый текст проходит quality.problems (там же
   заголовок <b> у рубрик с заголовком), строка кнопки «▸ <a …>» осталась
   как была. Мем и опрос только снимаются: подпись мема держится на картинке,
   а опрос — это JSON. Проверке не нужны ни сеть, ни пакеты сверх стандартной
   библиотеки — её же рутина зовёт перед пушем.
3. --apply на свежем main. Между проходом и применением пост мог выйти или
   поменяться: такой пропускается, а не затирается устаревшей правкой.
   Битый файл не применяется целиком и красит запуск.

Вышедшие посты не правятся: publish.py не хранит id сообщения в канале,
а без него editMessageCaption и editMessageText звать не с чем. ВКонтакте
не правится вовсе.

    python -m src.review --check content/review/20260912-0835.json    проверка без сети
    python -m src.review --apply content/review/20260912-0835.json --dry-run
    python -m src.review --selftest
"""

from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path

# Только лёгкое: --check зовёт облачный автор, и requests с Pillow ему ставить незачем.
from . import config, quality, state

ACTIONS = ("rewrite", "drop")
# Мем держится на картинке, опрос — JSON: подпись мема без выдумки остаётся
# шуткой ни о чём, а JSON опроса, переписанный руками, ломает опрос.
DROP_ONLY = ("meme", "poll")

ID_FORMAT = re.compile(r"\d{8}-\d{4}")
# Путь приходит из ветки, то есть снаружи: только файл очереди или архива, без «../».
POST_PATH = re.compile(r"content/(queue|archive)/[\w-]+\.json")
BUTTON = re.compile(r"(?m)^▸\s*<a\s+href=.*$")
TAG = re.compile(r"<[^>]+>")

PUBLISHED = "пост уже вышел — в канале не правлю: publish.py не хранит id сообщения"


def _filled(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def plain(text: str) -> str:
    """Текст для поиска цитаты: без разметки, сущностей, регистра, «ё» и лишних пробелов.

    Цитату рутина переписывает из поста: теги и переносы строк в ней не угадать,
    а «ё» модели меняют на «е» и обратно. Дословность — по словам, не по разметке.
    """
    text = html.unescape(TAG.sub("", text)).casefold().replace("ё", "е")
    return " ".join(text.split())


def _shape(edit) -> str:
    """Что не так с правкой по форме, без чтения поста. Пустая строка — годна."""
    if not isinstance(edit, dict):
        return "правка — это объект"
    file, action = edit.get("file"), edit.get("action")
    if not isinstance(file, str) or not POST_PATH.fullmatch(file):
        return "file: путь поста вида content/queue/<имя>.json"
    if action not in ACTIONS:
        return f"action «{action}»: rewrite или drop"
    missing = [field for field in ("fragment", "why") if not _filled(edit.get(field))]
    if action == "rewrite" and not _filled(edit.get("text")):
        missing.append("text")
    if missing:
        return "нет " + ", ".join(missing)
    if action == "drop" and not file.startswith("content/queue/"):
        return "drop — только для поста в очереди"
    return ""


def _post(file: str) -> tuple[dict | None, str]:
    """Пост из правки, как он лежит сейчас. None — править нечего, и почему."""
    path = config.ROOT / file
    if file.startswith("content/queue/") and path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8")), ""
        except ValueError:
            return None, "пост — битый JSON"
    if (config.ARCHIVE / path.name).is_file():
        return None, PUBLISHED
    return None, "поста уже нет"


def _text_problems(post: dict, edit: dict) -> list[str]:
    """Годен ли новый текст на место старого."""
    rubric = post.get("rubric", "")
    if edit["action"] == "drop":
        return []
    if rubric in DROP_ONLY:
        return [f"{rubric} не переписывается — только drop"]
    old, new = post.get("text", ""), edit["text"]
    errors = [f"новый текст: {issue}" for issue in quality.problems(new, rubric)]
    if plain(edit["fragment"]) in plain(new):
        errors.append("цитата выдумки осталась в новом тексте")
    kept = {line.strip() for line in new.splitlines()}
    errors += [
        f"строки кнопки нет в новом тексте: {line.strip()}"
        for line in BUTTON.findall(old)
        if line.strip() not in kept
    ]
    return errors


def check(review, name: str = "") -> tuple[list[str], dict[int, str]]:
    """Ошибки файла правок и пропуски — {номер правки с нуля: почему}.

    Ошибка — файл сделан неверно, применять его нельзя. Пропуск — правка годна
    по форме, но пост вышел, снят или поменялся. На снимке рутины пропуск —
    тоже ошибка (пост там лежит ровно как она его читала, значит, неверны путь
    или цитата), а на свежем main — обычная гонка, и правка просто не нужна.
    """
    if not isinstance(review, dict) or not isinstance(review.get("edits"), list):
        return ['файл правок — объект {"edits": [...]}'], {}
    edits = review["edits"]
    errors: list[str] = []
    skipped: dict[int, str] = {}
    if name and not ID_FORMAT.fullmatch(name):
        errors.append(f"имя файла «{name}»: ГГГГММДД-ЧЧММ, например 20260912-0835")
    if not edits:
        errors.append("edits пуст — без выдумок файл не пушится")
    files = [edit.get("file") for edit in edits if isinstance(edit, dict)]
    for index, edit in enumerate(edits):
        where = f"правка {index + 1}"
        wrong = _shape(edit)
        # Две правки одного поста: вторая молча затёрла бы первую.
        if not wrong and files.count(edit["file"]) > 1:
            wrong = f"{edit['file']} второй раз — одна правка на пост, все его выдумки в одном text"
        if wrong:
            errors.append(f"{where}: {wrong}")
            continue
        post, reason = _post(edit["file"])
        if post is not None and plain(edit["fragment"]) not in plain(post.get("text", "")):
            post, reason = None, "цитаты fragment нет в тексте поста — не дословно или пост поменялся"
        if post is None:
            skipped[index] = reason
            continue
        errors += [f"{where}: {problem}" for problem in _text_problems(post, edit)]
    return errors, skipped


def apply(review, name: str, dry_run: bool) -> int:
    """Применяет правки к очереди. 1 — файл битый, и не тронуто ничего.

    Сначала проверяется весь файл, потом пишется: применённый наполовину файл
    хуже неприменённого — следующий проход рутины не узнает, какая половина
    осталась.
    """
    errors, skipped = check(review, name)
    for error in errors:
        print(f"  ✗ {error}")
    if errors:
        print(f"Правки {name} не применены: ошибок {len(errors)}.")
        return 1

    done = 0
    for index, edit in enumerate(review["edits"]):
        path = config.ROOT / edit["file"]
        if index in skipped:
            print(f"  — {path.name}: {skipped[index]}")
            continue
        print(f"  {'снят' if edit['action'] == 'drop' else 'переписан'} {path.name}: {edit['why']}")
        done += 1
        if dry_run:
            continue
        if edit["action"] == "drop":
            path.unlink()
        else:
            post = json.loads(path.read_text(encoding="utf-8"))
            state.write_json(path, {**post, "text": edit["text"]})
    print(f"{'Применилось бы' if dry_run else 'Применено'} правок: {done}, пропущено: {len(skipped)}.")
    return 0


def _selftest() -> None:
    """Без сети, во временной папке: правка, снятие, отказ на битом тексте, вышедший пост.

    Запуск: python -m src.review --selftest
    """
    import contextlib
    import io
    import tempfile

    button = '▸ <a href="https://music.apple.com/us/album/x/6809882935">Слушать в Apple Music</a>'
    # Живой пример из очереди 11.09.2026: содержание трека, который никто не слушал.
    old = (
        "<b>NKEEEI & YANIX СДЕЛАЛИ ТРЕК-ПРИЗНАНИЕ</b>\n\n"
        "У nkeeei и Yanix вышел сингл <i>Поцелуи</i>: короткий и лишённый драмы.\n\n"
        "<blockquote>Получилось тепло и искренне. Без пафоса и драм.</blockquote>\n\n" + button
    )
    new = (
        "<b>NKEEEI И YANIX ВЫПУСТИЛИ СИНГЛ ПОЦЕЛУИ</b>\n\n"
        "У nkeeei и Yanix вышел сингл <i>Поцелуи</i>.\n\n"
        "<blockquote>Два имени на обложке, один трек — делили, видимо, по секундам.</blockquote>\n\n" + button
    )
    name = "20260912-0835"
    fix = {"file": "content/queue/a-verdict.json", "action": "rewrite", "text": new,
           "fragment": "Получилось тепло и искренне.", "why": "в inbox только название, 2:05 и жанр"}
    drop = {"file": "content/queue/b-meme.json", "action": "drop",
            "fragment": "Bones выпустил 90 альбомов", "why": "числа альбомов нет в данных"}

    def post_of(path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def refused(word: str, review: dict | None = None, file_name: str = name, **change) -> None:
        errors, skipped = check(review or {"edits": [{**fix, **change}]}, file_name)
        found = errors + list(skipped.values())
        assert any(word in problem for problem in found), (word, found)

    saved = config.ROOT, config.ARCHIVE
    with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
        config.ROOT, config.ARCHIVE = Path(tmp), Path(tmp) / "content" / "archive"
        queue = config.ROOT / "content" / "queue"
        try:
            state.write_json(queue / "a-verdict.json", {"rubric": "verdict", "artist": "nkeeei & Yanix", "text": old})
            state.write_json(queue / "b-meme.json",
                             {"rubric": "meme", "text": "Bones выпустил 90 альбомов за год. Я — ни одного плейлиста."})
            state.write_json(config.ARCHIVE / "c-release.json", {"rubric": "release", "text": old})

            good = {"edits": [fix, drop]}
            assert check(good, name) == ([], {}), check(good, name)
            # Цитату ищут без разметки, регистра и «ё»: переписанная глазами находится.
            assert plain("сингл ПОЦЕЛУИ: короткий и лишенный") in plain(old)

            refused("ГГГГММДД-ЧЧММ", file_name="20260912")
            refused("edits пуст", {"edits": []})
            refused("объект", {"edits": {}})
            refused("путь поста", file="content/queue/../../.env")
            refused("rewrite или drop", action="fix")
            refused("нет why", why=" ")
            refused("нет text", text="")
            refused("цитаты fragment нет", fragment="жёсткий ритм")
            refused("осталась", text=old)
            refused("одна правка на пост", {"edits": [fix, fix]})
            # Отказ на битом тексте: заголовок пропал, кнопка пропала, реферат.
            refused("заголовком <b>", text=new.replace("<b>", "").replace("</b>", ""))
            refused("строки кнопки нет", text=new.replace(button, "Слушать"))
            refused("запрещённый оборот", text=new.replace("<i>Поцелуи</i>.", "<i>Поцелуи</i>. Стоит отметить, что это сингл."))
            refused("только drop", {"edits": [{**drop, "action": "rewrite", "text": "Подпись без выдумки и без шутки."}]})
            refused("только для поста в очереди", {"edits": [{**drop, "file": "content/archive/c-release.json"}]})
            # Вышедший пост в канале не правится: пропуск с причиной, архив не трогается.
            refused("уже вышел", file="content/archive/c-release.json")

            # Сухой прогон не трогает ничего.
            assert apply(good, name, dry_run=True) == 0
            assert post_of(queue / "a-verdict.json")["text"] == old and (queue / "b-meme.json").is_file()

            # Битый текст — не пишется ничего, даже годное снятие рядом.
            assert apply({"edits": [{**fix, "text": new.replace(button, "")}, drop]}, name, dry_run=False) == 1
            assert post_of(queue / "a-verdict.json")["text"] == old and (queue / "b-meme.json").is_file()

            # Пост вышел между проходом рутины и применением — пропуск, остальное применяется.
            state.write_json(queue / "d-verdict.json", {"rubric": "verdict", "text": old})
            late = {**fix, "file": "content/queue/d-verdict.json"}
            assert check({"edits": [late]}, name) == ([], {})
            (queue / "d-verdict.json").rename(config.ARCHIVE / "d-verdict.json")
            assert apply({"edits": [fix, drop, late]}, name, dry_run=False) == 0
            rewritten = post_of(queue / "a-verdict.json")
            assert rewritten == {"rubric": "verdict", "artist": "nkeeei & Yanix", "text": new}, rewritten
            assert not (queue / "b-meme.json").exists()
            assert post_of(config.ARCHIVE / "d-verdict.json")["text"] == old

            # Перезапуск воркфлоу: пост уже переписан, мем снят — пропуски, а не красный запуск.
            assert apply(good, name, dry_run=False) == 0
            assert post_of(queue / "a-verdict.json")["text"] == new
        finally:
            config.ROOT, config.ARCHIVE = saved


def main() -> int:
    parser = argparse.ArgumentParser(description="Автопилот точности: правки выдумок в постах")
    parser.add_argument("--check", metavar="ФАЙЛ", help="проверить файл правок по постам, без сети")
    parser.add_argument("--apply", metavar="ФАЙЛ", help="применить правки: переписать или снять посты очереди")
    parser.add_argument("--dry-run", action="store_true", help="с --apply: показать, что изменится, ничего не меняя")
    parser.add_argument("--selftest", action="store_true",
                        help="правка, снятие, отказ на битом тексте и вышедший пост — без сети")
    args = parser.parse_args()

    if args.selftest:
        _selftest()
        print("Правка, снятие, отказ на битом тексте, вышедший пост: все проверки прошли.")
        return 0
    if not (args.check or args.apply):
        parser.print_help()
        return 0

    path = Path(args.check or args.apply)
    # Не state.read_json: тот прячет битый файл в .broken и молча отдаёт пустое,
    # а проверке нужно сказать, где JSON сломан.
    try:
        review = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        print(f"Не прочитать {path}: {exc.strerror}")
        return 1
    except json.JSONDecodeError as exc:
        print(f"{path.name}: не JSON — строка {exc.lineno}, {exc.msg}")
        return 1

    if args.apply:
        return apply(review, path.stem, args.dry_run)

    errors, skipped = check(review, path.stem)
    errors += [f"правка {index + 1}: {reason}" for index, reason in sorted(skipped.items())]
    for error in errors:
        print(f"  ✗ {error}")
    if errors:
        print(f"Правки {path.name} не годны: ошибок {len(errors)}.")
        return 1
    actions = [edit["action"] for edit in review["edits"]]
    print(f"Правки {path.name} годны: переписать {actions.count('rewrite')}, снять {actions.count('drop')}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
