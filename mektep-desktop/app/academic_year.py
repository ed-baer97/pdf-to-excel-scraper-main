"""Учебный год в десктопе: подпись, папка и список лет."""

from __future__ import annotations

from datetime import date
from pathlib import Path

ACADEMIC_YEAR_START_MONTH = 9


def current_academic_year(today: date | None = None) -> int:
    """Год начала учебного года (с сентября — текущий календарный год)."""
    day = today or date.today()
    return day.year if day.month >= ACADEMIC_YEAR_START_MONTH else day.year - 1


def format_academic_year(year: int) -> str:
    """2025 → «2025–2026»."""
    year = int(year)
    return f"{year}–{year + 1}"


def academic_year_folder(year: int) -> str:
    """Имя папки: 2025-2026."""
    year = int(year)
    return f"{year}-{year + 1}"


def academic_year_choices(extra_years: list[int] | None = None, today: date | None = None) -> list[int]:
    """Текущий год, два предыдущих и годы, которые уже есть в данных."""
    current = current_academic_year(today)
    years = {current, current - 1, current - 2}
    for year in extra_years or []:
        if year:
            years.add(int(year))
    return sorted(years, reverse=True)


def reports_period_dir(
    output_dir: Path,
    teacher_folder: str,
    period_name: str,
    academic_year: int,
) -> Path:
    """Mektep Reports / учитель / 2025-2026 / четверть или учебный год."""
    return (
        Path(output_dir)
        / teacher_folder
        / academic_year_folder(academic_year)
        / period_name
    )
