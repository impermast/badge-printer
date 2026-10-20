"""Read, validate and safely write compact UTF-8 CSV tables."""
from __future__ import annotations

import csv
import io
import os
import tempfile
from pathlib import Path

COLUMNS = (
    "ID", "Full Name", "First Name", "Last Name", "Affiliation",
    "Institution", "Country", "Type", "Review", "Notes",
)
AFFILIATION_COLUMNS = ("Affiliation", "Count", "Suggested", "Approved", "Sources", "Notes")
AFFILIATION_TOO_LONG = "AFFILIATION_TOO_LONG"


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if rows and None in rows[0]:
        raise ValueError(f"Unexpected extra columns in {path}")
    return [{column: (value or "").strip() for column, value in row.items()} for row in rows]


def save_csv(path: Path, rows: list[dict[str, str]], columns: tuple[str, ...] = COLUMNS) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".badge_", suffix=".csv")
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as out:
            out.write(stream.getvalue())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def validate_people(rows: list[dict[str, str]]) -> None:
    if not rows:
        raise ValueError("Participants table is empty")
    if not set(COLUMNS).issubset(rows[0]):
        raise ValueError(f"Missing columns: {sorted(set(COLUMNS) - set(rows[0]))}")
    ids = [row["ID"] for row in rows]
    if any(not identifier for identifier in ids) or len(ids) != len(set(ids)):
        raise ValueError("Missing or duplicate participant IDs")
    for row in rows:
        if not row["Last Name"].strip() or not row["Institution"].strip():
            raise ValueError(f"ID {row['ID']}: missing Last Name or Institution")
        if row["Type"] not in {"PARTICIPANT", "ORGANIZER"}:
            raise ValueError(f"ID {row['ID']}: unknown badge type {row['Type']!r}")
        if row["Review"] not in {"OK", "NEED REVIEW"}:
            raise ValueError(f"ID {row['ID']}: Review must be OK or NEED REVIEW")


def sync_affiliation_length_flag(row: dict[str, str], too_long: bool) -> bool:
    """Synchronize the length flag without changing unrelated review reasons."""
    before = (row["Review"], row["Notes"])
    notes = [part.strip() for part in row["Notes"].split(" | ") if part.strip()]
    had_tag = AFFILIATION_TOO_LONG in notes
    notes = [part for part in notes if part != AFFILIATION_TOO_LONG]
    if too_long:
        notes.append(AFFILIATION_TOO_LONG)
        row["Review"] = "NEED REVIEW"
    elif had_tag and not notes:
        row["Review"] = "OK"
    row["Notes"] = " | ".join(notes)
    return (row["Review"], row["Notes"]) != before
