"""Pure configuration objects passed to pipeline scripts."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Paths:
    root: Path
    registrations: Path
    participants: Path
    dictionary: Path
    affiliation_review: Path
    review_html: Path
    patches: Path
    participant_design: Path
    organizer_design: Path
    pdf_output: Path


@dataclass(frozen=True)
class Processing:
    default_type: str = "PARTICIPANT"
    country_names: dict[str, str] = field(default_factory=lambda: {
        "Russian Federation": "Russia",
    })
    batch_size: int = 100


@dataclass(frozen=True)
class Sheet:
    width_mm: float = 210.0
    height_mm: float = 297.0
    columns: int = 2
    rows: int = 2
    margin_x_mm: float = 0.0
    margin_y_mm: float = 0.0
    gap_x_mm: float = 0.0
    gap_y_mm: float = 0.0


@dataclass(frozen=True)
class Badge:
    width_mm: float = 105.0
    height_mm: float = 148.0
    font_path: Path | None = None  # Uses locally installed DejaVuSans-Bold by default.


@dataclass(frozen=True)
class TextField:
    baseline_mm: float
    font_size_pt: float
    min_font_size_pt: float
    max_width_mm: float = 98.0


@dataclass(frozen=True)
class Typography:
    first_name: TextField = field(default_factory=lambda: TextField(53.3, 32, 18))
    last_name: TextField = field(default_factory=lambda: TextField(68.1, 32, 18))
    institution: TextField = field(default_factory=lambda: TextField(86.4, 17.5, 10))
    country: TextField = field(default_factory=lambda: TextField(96.7, 17.5, 12))
    # Institution may use two lines; baselines refer to the first and second lines.
    institution_two_lines_mm: tuple[float, float] = (84.0, 90.0)


@dataclass(frozen=True)
class Settings:
    paths: Paths
    processing: Processing = field(default_factory=Processing)
    sheet: Sheet = field(default_factory=Sheet)
    badge: Badge = field(default_factory=Badge)
    typography: Typography = field(default_factory=Typography)
    strict_review: bool = False
