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

1. Рутина смотрит git log. Новых и вышедших постов бота с прошлого прохода
   нет — выходит, ничего не читая: лимиты подписки не бесконечны. Есть —
   сверяет и пишет content/review/<ГГГГММДД-ЧЧММ>.json: пост, rewrite (новый
   полный текст) или drop (снять из очереди), дословная цитата выдумки и чего
   нет в данных. Выдумок нет — не пушит ничего.
2. --check на снимке, по которому рутина писала правки: цитата есть в посте
   и ушла из нового текста, новый текст проходит quality.problems (там же
   заголовок <b> у рубрик с заголовком), строка кнопки «▸ <a …>» осталась
   как была. Мем и опрос только снимаются: подпись мема держится на картинке,
   а опрос — это JSON. Проверке не нужны ни сеть, ни пакеты сверх стандартной
   библиотеки — её же рутина зовёт перед пушем.
3. --apply на свежем main. Между проходом и применением пост мог поменяться:
   такой пропускается, а не затирается устаревшей правкой. Битый файл
   не применяется целиком и красит запуск.

Вышедший пост правится прямо в канале. publish.to_channel кладёт в архивный
JSON сообщение с текстом поста — поле message, вместе с кнопками: правка
без reply_markup их снимает. --apply зовёт publish.edit, а тот
editMessageCaption или editMessageText. Снять вышедший нельзя, только
rewrite; старый пост без message пропускается — править не с чем. Отказ
канала красит запуск, но годные правки рядом применяются: в канале они уже
вышли, и архив должен помнить их текст. ВКонтакте не правится вовсе.

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

PUBLISHED = "пост вышел, а сообщение в канале не записано — править не с чем"


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
        return "file: путь поста вида content/queue/<имя>.json или content/archive/<имя>.json"
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


def _current(file: str) -> Path:
    """Где пост лежит сейчас: в очереди, а вышедший — в архиве."""
    path = config.ROOT / file
    return path if file.startswith("content/queue/") and path.is_file() else config.ARCHIVE / path.name


def _post(edit: dict) -> tuple[dict | None, str]:
    """Пост из правки, как он лежит сейчас. None — править нечего, и почему."""
    path = _current(edit["file"])
    if not path.is_file():
        return None, "поста уже нет"
    try:
        post = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None, "пост — битый JSON"
    if path.parent == config.ARCHIVE:
        if edit["action"] == "drop":
            return None, "пост уже вышел — снять нельзя, только rewrite"
        if not post.get("message"):
            return None, PUBLISHED
    return post, ""


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
        post, reason = _post(edit)
        if post is not None and plain(edit["fragment"]) not in plain(post.get("text", "")):
            post, reason = None, "цитаты fragment нет в тексте поста — не дословно или пост поменялся"
        if post is None:
            skipped[index] = reason
            continue
        errors += [f"{where}: {problem}" for problem in _text_problems(post, edit)]
    return errors, skipped


def _write(edit: dict, path: Path) -> str:
    """Пишет одну правку. Непустая строка — канал её не принял, и почему."""
    if edit["action"] == "drop":
        path.unlink()
        return ""
    post = {**json.loads(path.read_text(encoding="utf-8")), "text": edit["text"]}
    if path.parent == config.ARCHIVE:
        # Не наверху: --check зовёт облачный автор, а publish тянет requests и Pillow.
        from . import publish, telegram

        try:
            publish.edit(post)
        except telegram.TelegramError as exc:
            # «not modified» — этот текст уже в канале: прошлый запуск поправил,
            # а коммит не дошёл. «not found» — пост удалили руками. Остальное — поломка.
            if "message is not modified" not in str(exc) and "message to edit not found" not in str(exc):
                return f"в канале не поправлен — {exc}"
    state.write_json(path, post)
    return ""


def apply(review, name: str, dry_run: bool) -> int:
    """Применяет правки: очередь переписывает и снимает, вышедшее правит в канале.
    1 — файл битый и не тронуто ничего, или канал не принял правку.

    Сначала проверяется весь файл, потом пишется: применённый наполовину файл
    хуже неприменённого — следующий проход рутины не узнает, какая половина
    осталась. Отказ канала — не порок файла: годные правки рядом применяются.
    """
    errors, skipped = check(review, name)
    for error in errors:
        print(f"  ✗ {error}")
    if errors:
        print(f"Правки {name} не применены: ошибок {len(errors)}.")
        return 1

    done = failed = 0
    for index, edit in enumerate(review["edits"]):
        path = _current(edit["file"])
        if index in skipped:
            print(f"  — {path.name}: {skipped[index]}")
            continue
        problem = "" if dry_run else _write(edit, path)
        if problem:
            print(f"  ✗ {path.name}: {problem}")
            failed += 1
            continue
        what = "снят" if edit["action"] == "drop" else "поправлен в канале" if path.parent == config.ARCHIVE else "переписан"
        print(f"  {what} {path.name}: {edit['why']}")
        done += 1
    print(f"{'Применилось бы' if dry_run else 'Применено'} правок: {done}, пропущено: {len(skipped)}, "
          f"не принял канал: {failed}.")
    return 1 if failed else 0


def _selftest() -> None:
    """Без сети, во временной папке: правка, снятие, отказ на битом тексте,
    вышедший пост — правка в канале, отказ канала и пропуск без сообщения.

    Запуск: python -m src.review --selftest
    """
    import contextlib
    import io
    import tempfile
    from unittest import mock

    from . import publish, telegram

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
            # Вышедший пост без записанного сообщения править не с чем: пропуск с причиной.
            refused("не записано", file="content/archive/c-release.json")

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

            # Вышедший пост с записанным сообщением правится в канале: строка «▸ Слушать…»
            # в подписи развёрнута в площадки, кнопки старого поста на месте (правка без
            # reply_markup их сняла бы), в архиве — новый текст.
            message = {"chat": -100, "message_id": 5, "kind": "caption", "buttons": [[{"text": "Apple", "url": "a"}]]}
            released = {"rubric": "verdict", "artist": "nkeeei & Yanix", "text": old, "message": message}
            state.write_json(config.ARCHIVE / "e-verdict.json", released)
            out = {**fix, "file": "content/archive/e-verdict.json"}
            assert check({"edits": [out]}, name) == ([], {})
            refused("снять нельзя", {"edits": [{**drop, "file": "content/queue/e-verdict.json"}]})
            edited = []
            with (mock.patch.object(publish, "release_title", lambda post: ""),
                  mock.patch.object(telegram, "edit_caption", lambda *args, **kw: edited.append((*args, kw)))):
                assert apply({"edits": [out]}, name, dry_run=False) == 0
            assert len(edited) == 1 and edited[0][0::3] == (-100, {"buttons": message["buttons"]}), edited
            caption = edited[0][2]
            assert caption.startswith(new.replace("\n\n" + button, "")) and button not in caption, caption
            assert "\n\n▸ Слушать — <a href=" in caption, caption
            assert post_of(config.ARCHIVE / "e-verdict.json") == {**released, "text": new}

            # Канал не принял — запуск красный, архив прежний. Тот же текст уже в канале
            # (прошлый запуск поправил, коммит не дошёл) — это успех.
            for error, code, text in (("Forbidden: not enough rights", 1, old), ("message is not modified", 0, new)):
                state.write_json(config.ARCHIVE / "e-verdict.json", released)

                def refuse(*_, error=error, **__):
                    raise telegram.TelegramError(f"editMessageCaption: Bad Request: {error}")

                with (mock.patch.object(publish, "release_title", lambda post: ""),
                      mock.patch.object(telegram, "edit_caption", refuse)):
                    assert apply({"edits": [out]}, name, dry_run=False) == code, error
                assert post_of(config.ARCHIVE / "e-verdict.json")["text"] == text, error
        finally:
            config.ROOT, config.ARCHIVE = saved


def main() -> int:
    parser = argparse.ArgumentParser(description="Автопилот точности: правки выдумок в постах")
    parser.add_argument("--check", metavar="ФАЙЛ", help="проверить файл правок по постам, без сети")
    parser.add_argument("--apply", metavar="ФАЙЛ",
                        help="применить правки: переписать или снять посты очереди, поправить вышедшие в канале")
    parser.add_argument("--dry-run", action="store_true", help="с --apply: показать, что изменится, ничего не меняя")
    parser.add_argument("--selftest", action="store_true",
                        help="правка, снятие, отказ на битом тексте и правка вышедшего поста — без сети")
    args = parser.parse_args()

    if args.selftest:
        _selftest()
        print("Правка, снятие, отказ на битом тексте, правка вышедшего поста в канале: все проверки прошли.")
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
        config.load_dotenv()  # токен бота для правки в канале; в Actions он в окружении
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
