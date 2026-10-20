"""Render 2x2 sheets using existing blank badge backgrounds."""
from __future__ import annotations

import math
from pathlib import Path

import fitz

from settings import Settings, TextField
from .records import read_csv, validate_people


def pt(mm: float) -> float:
    return mm * 72 / 25.4


def find_font(override: Path | None) -> Path:
    candidates = ([override] if override else []) + [
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf"),
    ]
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate
    raise FileNotFoundError("Bold sans-serif TTF not found; specify Badge(font_path=Path(...))")


def fitted_size(font: fitz.Font, text: str, field: TextField) -> float:
    max_size = field.font_size_pt
    width = font.text_length(text, fontsize=max_size)
    if not width:
        return max_size
    size = min(max_size, math.floor(max_size * pt(field.max_width_mm) / width * 10) / 10)
    if size + 0.001 < field.min_font_size_pt:
        raise ValueError(f"Text does not fit at minimum font size: {text!r}")
    return max(field.min_font_size_pt, size)


def write_center(page: fitz.Page, font: fitz.Font, text: str,
                 badge_left_pt: float, badge_top_pt: float, badge_w_pt: float,
                 baseline_mm: float, field: TextField) -> None:
    if not text:
        return
    size = fitted_size(font, text, field)
    width = font.text_length(text, fontsize=size)
    page.insert_text((badge_left_pt + (badge_w_pt - width) / 2, badge_top_pt + pt(baseline_mm)),
                     text, fontname="badge_bold", fontsize=size, color=(0, 0, 0))


def institution_lines(value: str, font: fitz.Font, style: TextField) -> list[str]:
    """Prefer organization boundaries, otherwise wrap only between words."""
    max_width = pt(style.max_width_mm)
    if font.text_length(value, fontsize=style.font_size_pt) <= max_width:
        return [value]
    chunks = [part.strip() for part in value.split(" / ") if part.strip()] if " / " in value else value.split()
    if len(chunks) <= 1:
        return [value]
    sep = " / " if " / " in value else " "
    # Split near the midpoint measured in actual font widths.
    split = min(range(1, len(chunks)), key=lambda i: max(
        font.text_length(sep.join(chunks[:i]), fontsize=style.font_size_pt),
        font.text_length(sep.join(chunks[i:]), fontsize=style.font_size_pt),
    ))
    return [sep.join(chunks[:split]), sep.join(chunks[split:])]


def generate_pdf(settings: Settings) -> None:
    people = read_csv(settings.paths.participants)
    validate_people(people)
    flagged = [p["ID"] for p in people if p["Review"] == "NEED REVIEW"]
    if settings.strict_review and flagged:
        raise ValueError(f"Refusing print: {len(flagged)} NEED REVIEW participants, e.g. {', '.join(flagged[:8])}")

    sheet, badge, typography = settings.sheet, settings.badge, settings.typography
    if (sheet.columns * badge.width_mm + (sheet.columns - 1) * sheet.gap_x_mm + 2 * sheet.margin_x_mm
            > sheet.width_mm + 0.001 or
            sheet.rows * badge.height_mm + (sheet.rows - 1) * sheet.gap_y_mm + 2 * sheet.margin_y_mm
            > sheet.height_mm + 0.001):
        raise ValueError("Badges do not fit onto the configured sheet without resizing")
    font_path = find_font(badge.font_path)
    font = fitz.Font(fontfile=str(font_path))
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
                write_center(page, font, person["First Name"], left, top, width,
                             typography.first_name.baseline_mm, typography.first_name)
                write_center(page, font, person["Last Name"], left, top, width,
                             typography.last_name.baseline_mm, typography.last_name)
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
    if flagged:
        print(f"WARNING: {len(flagged)} registrations still marked NEED REVIEW: {', '.join(flagged[:10])}")
