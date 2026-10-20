"""Render 2x2 sheets using existing blank badge backgrounds."""
from __future__ import annotations

import math
import fitz

from settings import Settings, TextField
from .layout import pt, find_font, fitted_size, institution_lines, institution_too_long, name_lines
from .records import read_csv, save_csv, sync_affiliation_length_flag, validate_people
from .prepare import update_review_page

def write_center(page: fitz.Page, font: fitz.Font, text: str,
                 badge_left_pt: float, badge_top_pt: float, badge_w_pt: float,
                 baseline_mm: float, field: TextField) -> None:
    if not text:
        return
    size = fitted_size(font, text, field)
    width = font.text_length(text, fontsize=size)
    page.insert_text((badge_left_pt + (badge_w_pt - width) / 2, badge_top_pt + pt(baseline_mm)),
                     text, fontname="badge_bold", fontsize=size, color=(0, 0, 0))

def generate_pdf(settings: Settings, badge_type: str | None = None) -> None:
    people = read_csv(settings.paths.participants)
    validate_people(people)
    if badge_type is not None:
        if badge_type not in {"PARTICIPANT", "ORGANIZER"}:
            raise ValueError(f"Unknown badge type: {badge_type}")
        people = [person for person in people if person["Type"] == badge_type]
        if not people:
            raise ValueError(f"No registrations for badge type {badge_type}")
    sheet, badge, typography = settings.sheet, settings.badge, settings.typography
    if (sheet.columns * badge.width_mm + (sheet.columns - 1) * sheet.gap_x_mm + 2 * sheet.margin_x_mm
            > sheet.width_mm + 0.001 or
            sheet.rows * badge.height_mm + (sheet.rows - 1) * sheet.gap_y_mm + 2 * sheet.margin_y_mm
            > sheet.height_mm + 0.001):
        raise ValueError("Badges do not fit onto the configured sheet without resizing")
    font_path = find_font(badge.font_path)
    font = fitz.Font(fontfile=str(font_path))

    # Mark oversized institutions in the review table before rendering.
    # The PDF remains a draft: leave these institution fields blank instead
    # of breaking a line or stopping the entire batch.
    too_long = set()
    modified = False
    for person in people:
        oversized = institution_too_long(person["Institution"], font, typography)
        if oversized:
            too_long.add(person["ID"])
        modified |= sync_affiliation_length_flag(person, oversized)
    if modified:
        save_csv(settings.paths.participants, people)
        update_review_page(settings)
    flagged = [p["ID"] for p in people if p["Review"] == "NEED REVIEW"]
    if settings.strict_review and flagged:
        raise ValueError(f"Refusing print: {len(flagged)} NEED REVIEW participants, e.g. {', '.join(flagged[:8])}")

    design_paths = {
        "PARTICIPANT": settings.paths.participant_design,
        "ORGANIZER": settings.paths.organizer_design,
    }
    # Keep PDF source documents open until the destination has been saved.
    designs = {}
    for kind, path in design_paths.items():
        if path.suffix.lower() == ".pdf":
            source = fitz.open(path)
            if source.page_count != 1:
                source.close()
                raise ValueError(f"Design must contain one page: {path}")
            designs[kind] = source
        else:
            if path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
                raise ValueError(f"Use PDF, PNG or JPG design: {path}")
            designs[kind] = path.read_bytes()
    pages = fitz.open()
    per_sheet = sheet.columns * sheet.rows
    try:
        for i, person in enumerate(people):
            if i % per_sheet == 0:
                page = pages.new_page(width=pt(sheet.width_mm), height=pt(sheet.height_mm))
                page.insert_font(fontname="badge_bold", fontfile=str(font_path))
            else:
                page = pages[-1]
            pos = i % per_sheet
            left = pt(sheet.margin_x_mm + (pos % sheet.columns) * (badge.width_mm + sheet.gap_x_mm))
            top = pt(sheet.margin_y_mm + (pos // sheet.columns) * (badge.height_mm + sheet.gap_y_mm))
            width, height = pt(badge.width_mm), pt(badge.height_mm)
            frame = fitz.Rect(left, top, left + width, top + height)
            design = designs[person["Type"]]
            if isinstance(design, fitz.Document):
                page.show_pdf_page(frame, design, 0, keep_proportion=False)
            else:
                page.insert_image(frame, stream=design, keep_proportion=False)
            try:
                given_name_lines = name_lines(person["First Name"], font, typography.first_name)
                for line_index, line in enumerate(given_name_lines):
                    baseline = typography.first_name.baseline_mm - 11.0 * (len(given_name_lines) - 1 - line_index)
                    write_center(page, font, line, left, top, width, baseline, typography.first_name)
                write_center(page, font, person["Last Name"], left, top, width,
                             typography.last_name.baseline_mm, typography.last_name)
                if person["ID"] not in too_long:
                    lines = institution_lines(person["Institution"], font, typography.institution)
                    if len(lines) == 1:
                        baselines = [typography.institution.baseline_mm]
                    else:
                        baselines = typography.institution_two_lines_mm
                    for line, baseline in zip(lines, baselines):
                        write_center(page, font, line, left, top, width, baseline, typography.institution)
                write_center(page, font, person["Country"], left, top, width,
                             typography.country.baseline_mm, typography.country)
            except ValueError as error:
                raise ValueError(f"ID {person['ID']} ({person['Full Name']}): {error}") from error
        settings.paths.pdf_output.parent.mkdir(parents=True, exist_ok=True)
        pages.save(settings.paths.pdf_output, deflate=True, garbage=3)
    finally:
        pages.close()
        for design in designs.values():
            if isinstance(design, fitz.Document):
                design.close()
    print(f"PDF: {settings.paths.pdf_output}; badges: {len(people)}; pages: {math.ceil(len(people) / per_sheet)}")
    if too_long:
        print(f"WARNING: {len(too_long)} oversized Institution field(s) omitted from draft PDF: "
              f"{', '.join(sorted(too_long))}")
        print("Tagged AFFILIATION_TOO_LONG in data/work/participants.csv. Fix Institution and run badges again.")
    if flagged:
        print(f"WARNING: {len(flagged)} registrations still marked NEED REVIEW: {', '.join(flagged[:10])}")
