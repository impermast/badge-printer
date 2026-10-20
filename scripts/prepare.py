"""Prepare registration data without changing the source export."""
from __future__ import annotations

from collections import Counter
import html
import re
from pathlib import Path

from settings import Settings
from .records import (
    COLUMNS, AFFILIATION_COLUMNS, read_csv, save_csv,
    validate_people, sync_affiliation_length_flag, AFFILIATION_TOO_LONG, NO_AFFILIATION,
)
from .layout import find_font, institution_too_long
import fitz

RU = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def transliterate(text: str) -> str:
    return "".join(
        (RU[ch.lower()].capitalize() if ch.isupper() else RU[ch]) if ch.lower() in RU else ch
        for ch in text
    )


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().replace("«", '"').replace("»", '"').replace("“", '"').replace("”", '"')).casefold()


def load_dictionary(path: Path) -> dict[str, str]:
    rows = read_csv(path)
    if rows and not {"Affiliation", "Institution"}.issubset(rows[0]):
        raise ValueError("Dictionary needs Affiliation and Institution columns")
    mapping: dict[str, str] = {}
    for row in rows:
        k = normalize(row.get("Affiliation", ""))
        v = row.get("Institution", "").strip()
        if not k or not v:
            raise ValueError("Dictionary contains empty affiliation or abbreviation")
        if k in mapping and mapping[k] != v:
            raise ValueError(f"Conflicting abbreviation for {row['Affiliation']}")
        mapping[k] = v
    return mapping


def shorten(affiliation: str, mapping: dict[str, str]) -> tuple[str, bool]:
    """Split on known affiliation boundaries only, never on arbitrary commas."""
    if normalize(affiliation) in mapping:
        return mapping[normalize(affiliation)], True
    for delimiter in (";", ","):
        if delimiter in affiliation:
            parts = [part.strip() for part in affiliation.split(delimiter)]
            if len(parts) > 1 and all(normalize(part) in mapping for part in parts):
                return " / ".join(mapping[normalize(part)] for part in parts), True
    return affiliation.strip(), False


def prepare(settings: Settings, input_path: Path | None = None, force: bool = False) -> None:
    paths = settings.paths
    if paths.participants.exists() and not force:
        raise ValueError("Prepared table already exists; use --force only if you intend to discard manual edits")
    source = read_csv(input_path or paths.registrations)
    if not source or not {"ID", "First Name", "Last Name", "Affiliation", "Country"}.issubset(source[0]):
        raise ValueError("CSV needs ID, First Name, Last Name, Affiliation, Country")
    mapping = load_dictionary(paths.dictionary)
    font = fitz.Font(fontfile=str(find_font(settings.badge.font_path)))
    result = []
    unknown: Counter[str] = Counter()
    for original in source:
        first, last = original["First Name"], original["Last Name"]
        aff = original["Affiliation"]
        if not last.strip() or not aff.strip():
            raise ValueError(f"ID {original['ID']}: missing source surname or affiliation")
        institution, known = shorten(aff, mapping)
        if not known:
            unknown[aff] += 1
        notes = []
        if not known:
            notes.append("Unknown affiliation")
        if not first.strip():
            notes.append("Missing first name")
        row = {
            "ID": original["ID"],
            "Full Name": original.get("Name") or " ".join(x for x in (first, last) if x),
            "First Name": transliterate(first),
            "Last Name": transliterate(last),
            "Affiliation": aff,
            "Institution": institution,
            "Country": settings.processing.country_names.get(original["Country"], original["Country"]),
            "Type": settings.processing.default_type,
            "Review": "NEED REVIEW" if notes else "OK",
            "Notes": " | ".join(notes),
        }
        sync_affiliation_length_flag(
            row, institution_too_long(institution, font, settings.typography)
        )
        result.append(row)
    validate_people(result)
    save_csv(paths.participants, result)
    to_review = [
        {"Affiliation": text, "Count": str(count), "Suggested": "", "Approved": "", "Sources": "", "Notes": ""}
        for text, count in unknown.most_common()
    ]
    save_csv(paths.affiliation_review, to_review, AFFILIATION_COLUMNS)
    update_review_page(settings)
    long_count = sum(AFFILIATION_TOO_LONG in r["Notes"] for r in result)
    print(f"Prepared: {len(result)} registrations; unknown affiliation variants: {len(to_review)}; "
          f"too-long institutions: {long_count}")
    print(f"Edit: {paths.participants}\nAffiliations: {paths.affiliation_review}")


def apply_approved(settings: Settings) -> None:
    paths = settings.paths
    review = read_csv(paths.affiliation_review)
    dictionary_rows = read_csv(paths.dictionary)
    mapping = load_dictionary(paths.dictionary)
    added = 0
    approved_mappings: dict[str, str] = {}
    intentionally_blank: set[str] = set()
    for item in review:
        decision = item.get("Approved", "").strip().upper()
        if decision not in {"", "YES", "NO"}:
            raise ValueError(f"Invalid Approved for {item['Affiliation']}: {decision}. Use YES/NO/blank")
        if decision != "YES":
            continue
        original, short = item["Affiliation"], item["Suggested"].strip()
        normalized = normalize(original)
        if not short:
            if normalized in approved_mappings:
                raise ValueError(f"Conflicting approved decisions for {original}")
            intentionally_blank.add(normalized)
            continue
        if normalized in intentionally_blank:
            raise ValueError(f"Conflicting approved decisions for {original}")
        if normalized in mapping and mapping[normalized] != short:
            raise ValueError(f"Conflicting mapping for {original}: {mapping[normalized]} vs {short}")
        approved_mappings[normalized] = short
        if normalized not in mapping:
            dictionary_rows.append({"Affiliation": original, "Institution": short})
            mapping[normalized] = short
            added += 1

    people = read_csv(paths.participants)
    validate_people(people)
    fixed = 0
    for row in people:
        normalized = normalize(row["Affiliation"])
        if normalized in intentionally_blank and row["Institution"] == row["Affiliation"]:
            row["Institution"] = ""
            notes = [
                part.strip() for part in row["Notes"].split(" | ")
                if part.strip() and part.strip() != "Unknown affiliation"
            ]
            if NO_AFFILIATION not in notes:
                notes.append(NO_AFFILIATION)
            row["Notes"] = " | ".join(notes)
            row["Review"] = "NEED REVIEW"
            fixed += 1
            continue
        if normalized not in approved_mappings or row["Institution"] != row["Affiliation"]:
            continue

        row["Institution"] = approved_mappings[normalized]
        notes = [part.strip() for part in row["Notes"].split(" | ") if part.strip()]
        affiliation_only_review = notes == ["Unknown affiliation"]
        notes = [part for part in notes if part != "Unknown affiliation"]
        if not row["First Name"].strip() and "Missing first name" not in notes:
            notes.append("Missing first name")
        row["Notes"] = " | ".join(notes)
        if affiliation_only_review and not notes:
            row["Review"] = "OK"
        fixed += 1

    # Check the full result before writing to disk.
    validate_people(people)
    if added:
        save_csv(paths.dictionary, dictionary_rows, ("Affiliation", "Institution"))
    if fixed:
        save_csv(paths.participants, people)
    update_review_page(settings)
    print(f"Approved: {added} new dictionary entries; updated participants: {fixed}")
    pending = sum(item.get("Approved", "").strip().upper() != "YES" for item in review)
    print(f"Pending affiliation variants: {pending}")
    print("Other manual Institution edits remain untouched")


def update_review_page(settings: Settings) -> None:
    people = read_csv(settings.paths.participants)
    validate_people(people)
    font = fitz.Font(fontfile=str(find_font(settings.badge.font_path)))
    changed = False
    for person in people:
        changed |= sync_affiliation_length_flag(
            person, institution_too_long(person["Institution"], font, settings.typography)
        )
    if changed:
        save_csv(settings.paths.participants, people)
    parts = [
        '<!doctype html><html lang="ru"><meta charset="utf-8"><title>Badge review</title>',
        '<style>body{font:14px system-ui,sans-serif;margin:20px}table{border-collapse:collapse;width:100%}',
        'td,th{padding:6px;border:1px solid #ccc;text-align:left;vertical-align:top}',
        'th{background:#e7ecf2;position:sticky;top:0}tr.flag{background:#fff2c4}',
        'td{overflow-wrap:anywhere}</style>',
        f'<h2>Participants: {len(people)}. NEED REVIEW: {sum(x["Review"] == "NEED REVIEW" for x in people)}</h2>',
        '<p>Read-only preview. Edit <code>data/work/participants.csv</code> in LibreOffice or Excel.</p>',
        '<table><thead><tr>' + ''.join(f'<th>{html.escape(x)}</th>' for x in COLUMNS) + '</tr></thead><tbody>',
    ]
    for p in people:
        css = ' class="flag"' if p["Review"] == "NEED REVIEW" else ""
        parts.append(f'<tr{css}>' + ''.join(f'<td>{html.escape(p.get(col, ""))}</td>' for col in COLUMNS) + '</tr>')
    parts.append('</tbody></table></html>')
    settings.paths.review_html.parent.mkdir(parents=True, exist_ok=True)
    settings.paths.review_html.write_text('\n'.join(parts), encoding="utf-8")
