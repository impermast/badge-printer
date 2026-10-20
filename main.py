#!/usr/bin/env python3
"""Configure and orchestrate the data-cleaning and PDF-generation pipelines."""
from __future__ import annotations

import argparse
from pathlib import Path

from settings import Badge, Paths, Processing, Settings, Sheet, TextField, Typography
from scripts.ai_patches import export_ai, import_ai
from scripts.generate import generate_pdf
from scripts.prepare import prepare, apply_approved, update_review_page

# 1. CONFIGURATION. Change the paths and layout here, not inside scripts/.
ROOT = Path(__file__).resolve().parent
CONFIG = Settings(
    paths=Paths(
        root=ROOT,
        registrations=ROOT / "data/input/registrations.csv",
        participants=ROOT / "data/work/participants.csv",
        dictionary=ROOT / "data/dictionaries/affiliations.csv",
        affiliation_review=ROOT / "data/work/affiliations_review.csv",
        review_html=ROOT / "data/work/review.html",
        patches=ROOT / "data/patches",
        participant_design=ROOT / "design/participant.png",
        organizer_design=ROOT / "design/organizer.png",
        pdf_output=ROOT / "output/badges_a4.pdf",
    ),
    processing=Processing(batch_size=100),
    sheet=Sheet(columns=2, rows=2),
    badge=Badge(width_mm=105, height_mm=148, font_path=None),
    typography=Typography(
        first_name=TextField(53.3, 32, 18),
        last_name=TextField(68.1, 32, 18),
        institution=TextField(86.4, 17.5, 10),
        country=TextField(96.7, 17.5, 12),
    ),
    strict_review=False,  # Set True before final printing.
)


# 2. PIPELINE. Invoke only the requested step; no import-time side effects.
def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare Indico registrations and print 4-up A4 badges")
    parser.add_argument("command", choices=["prepare", "export-ai", "import-ai", "apply", "review", "badges"])
    parser.add_argument("--input", type=Path, help="Override the CSV input for 'prepare'")
    parser.add_argument("--force", action="store_true", help="Replace an existing prepared CSV (prepare only)")
    args = parser.parse_args()

    if args.command == "prepare":
        prepare(CONFIG, input_path=args.input, force=args.force)
    elif args.command == "export-ai":
        export_ai(CONFIG)
    elif args.command == "import-ai":
        import_ai(CONFIG)
    elif args.command == "apply":
        apply_approved(CONFIG)
    elif args.command == "review":
        update_review_page(CONFIG)
    elif args.command == "badges":
        generate_pdf(CONFIG)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError) as error:
        raise SystemExit(f"ERROR: {error}") from error
