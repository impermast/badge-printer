"""Review unknown affiliations through portable JSON batches, with no personal data."""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path

from settings import Settings
from .records import AFFILIATION_COLUMNS, read_csv, save_csv


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def export_ai(settings: Settings) -> None:
    paths = settings.paths
    reviews = read_csv(paths.affiliation_review)
    selected = [r for r in reviews if r.get("Approved", "").upper() != "YES"]
    if not selected:
        print("Nothing to research")
        return
    if (paths.patches / "manifest.json").exists():
        raise ValueError("Batches already exist. Complete this round before exporting again")
    batch_size = settings.processing.batch_size
    if batch_size < 1:
        raise ValueError("batch_size must be greater than zero")
    originals = paths.patches / "original"
    returned = paths.patches / "returned"
    originals.mkdir(parents=True, exist_ok=True)
    returned.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(paths.dictionary, paths.patches / "affiliations_reference.csv")
    manifest = {"version": 1, "review_sha256": digest(paths.affiliation_review.read_bytes()), "batches": {}}
    for index, start in enumerate(range(0, len(selected), batch_size), 1):
        chunk = selected[start:start + batch_size]
        name = f"batch_{index:03d}.json"
        manifest["batches"][name] = [item["Affiliation"] for item in chunk]
        data = {"batch": name, "items": [
            {
                "affiliation": item["Affiliation"],
                "suggested": item.get("Suggested", ""),
                "sources": item.get("Sources", "").split() if item.get("Sources") else [],
                "notes": item.get("Notes", ""),
            }
            for item in chunk
        ]}
        (originals / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (paths.patches / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (paths.patches / "INSTRUCTIONS.md").write_text(INSTRUCTIONS, encoding="utf-8")
    print(f"Exported {len(selected)} unique affiliations in {len(manifest['batches'])} JSON batch(es)")
    print("Send INSTRUCTIONS.md, affiliations_reference.csv, and one original/batch_NNN.json to ChatGPT")
    print(f"Save returned files in {returned}")
    print("Then run: python main.py import-ai; approve in data/work/affiliations_review.csv; python main.py apply")


def import_ai(settings: Settings) -> None:
    paths = settings.paths
    manifest_path = paths.patches / "manifest.json"
    if not manifest_path.exists():
        raise ValueError("Export batches first: python main.py export-ai")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("version") != 1 or not isinstance(manifest.get("batches"), dict):
        raise ValueError("Unsupported manifest")
    if digest(paths.affiliation_review.read_bytes()) != manifest["review_sha256"]:
        raise ValueError("Affiliation review table changed after export. Do not overwrite your manual edits")
    expected_files = set(manifest["batches"])
    actual_files = {p.name for p in (paths.patches / "returned").glob("*.json")}
    if expected_files != actual_files:
        raise ValueError(f"Incomplete AI response. Missing: {sorted(expected_files - actual_files)}; extra: {sorted(actual_files - expected_files)}")

    suggestions = {}
    for filename, expected in manifest["batches"].items():
        batch = json.loads((paths.patches / "returned" / filename).read_text(encoding="utf-8"))
        if set(batch) != {"batch", "items"} or batch["batch"] != filename or not isinstance(batch["items"], list):
            raise ValueError(f"Bad batch structure in {filename}")
        got = [item.get("affiliation") for item in batch["items"]]
        if got != expected or len(got) != len(set(got)):
            raise ValueError(f"Affiliations changed, reordered, added or removed in {filename}")
        for item in batch["items"]:
            if set(item) != {"affiliation", "suggested", "sources", "notes"}:
                raise ValueError(f"Unexpected item fields in {filename}")
            if not isinstance(item["suggested"], str) or not isinstance(item["notes"], str):
                raise ValueError(f"Non-string suggestion in {filename}")
            sources = item["sources"]
            if not isinstance(sources, list) or any(not isinstance(s, str) or not s.startswith(("http://", "https://")) for s in sources):
                raise ValueError(f"Invalid sources in {filename}")
            if not item["suggested"].strip():
                # A blank suggestion means research was inconclusive. Human review still required.
                pass
            suggestions[item["affiliation"]] = item

    rows = read_csv(paths.affiliation_review)
    for row in rows:
        if row["Affiliation"] in suggestions:
            candidate = suggestions[row["Affiliation"]]
            row["Suggested"] = candidate["suggested"].strip()
            row["Sources"] = " ".join(candidate["sources"])
            row["Notes"] = candidate["notes"].strip()
            # Approved deliberately remains blank: AI suggestions are never silently applied.
    backups = paths.review_html.parent / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    backup = backups / f"affiliations_before_ai_{datetime.now():%Y%m%d_%H%M%S%f}.csv"
    shutil.copy2(paths.affiliation_review, backup)
    save_csv(paths.affiliation_review, rows, AFFILIATION_COLUMNS)
    with_suggestion = sum(bool(item["suggested"].strip()) for item in suggestions.values())
    print(f"Imported {len(suggestions)} records: {with_suggestion} suggestions, "
          f"{len(suggestions) - with_suggestion} unresolved")
    print(f"Proposals stored ONLY in: {paths.affiliation_review}")
    print("No participant Institution fields have changed yet.")
    print("Edit Suggested if necessary, set Approved=YES for accepted rows, "
          "then run: python main.py apply")


INSTRUCTIONS = """# Проверка сокращений аффилиаций

Ты проверяешь **только названия научных организаций**, без персональных данных участников конференции. Тебе переданы три файла: эта инструкция, `affiliations_reference.csv` с действующим словарём и один `batch_NNN.json`.

Для каждого `affiliation` найди короткое официальное или широко принятое английское написание для бейджа. Обрабатывай организации так:

- Сначала ищи название и известные альтернативные написания в `affiliations_reference.csv`. Используй уже утверждённое значение из столбца `Institution`.
- Не заменяй найденное стандартное сокращение своим вариантом.
- Для неизвестной организации проверь официальное сокращение на сайте самого учреждения. Укажи использованные URL в `sources`.
- Для двойных и тройных аффилиаций проверь каждую организацию отдельно. Сохрани исходный порядок и разделяй сокращения через ` / `.
- Если соответствие неоднозначно или подтвердить его не удалось, оставь `suggested` пустым и объясни причину в `notes`. Не выдумывай сокращения.

Меняй только `suggested` (строка), `sources` (список URL) и `notes` (краткое объяснение). Не меняй `affiliation`, `batch`, количество и порядок записей или имена ключей JSON.

Верни только исправленный JSON-патч в прежнем формате, без Markdown и пояснений вокруг. Сохрани имя файла `batch_NNN.json`.

После импорта предложения останутся неодобренными. Пользователь проверяет их и указывает `Approved=YES`; только затем локальная команда `apply` обновит словарь и рабочую таблицу.
"""
