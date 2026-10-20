"""Shared font measurement for preparation and PDF rendering."""
from __future__ import annotations

import math
from pathlib import Path

import fitz

from settings import TextField, Typography


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


def name_lines(value: str, font: fitz.Font, style: TextField) -> list[str]:
    """Wrap a long multiword given name at a word boundary when needed."""
    max_width = pt(style.max_width_mm)
    if font.text_length(value, fontsize=style.font_size_pt) <= max_width:
        return [value]
    words = value.split()
    if len(words) < 2:
        return [value]
    split = min(range(1, len(words)), key=lambda i: max(
        font.text_length(" ".join(words[:i]), fontsize=style.font_size_pt),
        font.text_length(" ".join(words[i:]), fontsize=style.font_size_pt),
    ))
    return [" ".join(words[:split]), " ".join(words[split:])]


def institution_lines(value: str, font: fitz.Font, style: TextField) -> list[str]:
    """Prefer organization boundaries, otherwise wrap only between words."""
    max_width = pt(style.max_width_mm)
    if font.text_length(value, fontsize=style.font_size_pt) <= max_width:
        return [value]
    chunks = [part.strip() for part in value.split(" / ") if part.strip()] if " / " in value else value.split()
    if len(chunks) <= 1:
        return [value]
    sep = " / " if " / " in value else " "
    split = min(range(1, len(chunks)), key=lambda i: max(
        font.text_length(sep.join(chunks[:i]), fontsize=style.font_size_pt),
        font.text_length(sep.join(chunks[i:]), fontsize=style.font_size_pt),
    ))
    return [sep.join(chunks[:split]), sep.join(chunks[split:])]


def institution_too_long(value: str, font: fitz.Font, typography: Typography) -> bool:
    """True if the institution cannot fit in one or two permitted lines."""
    return any(
        font.text_length(line, fontsize=typography.institution.min_font_size_pt)
        > pt(typography.institution.max_width_mm) + 0.001
        for line in institution_lines(value, font, typography.institution)
    )
