"""Учебный год (academic_year): вычисление, форматирование, контекст запроса."""

from __future__ import annotations

from datetime import date

ACADEMIC_YEAR_START_MONTH = 9
DEFAULT_BACKFILL_ACADEMIC_YEAR = 2025


def current_academic_year(today: date | None = None) -> int:
    """Год начала учебного года (сентябрь+ → текущий календарный год)."""
    d = today or date.today()
    return d.year if d.month >= ACADEMIC_YEAR_START_MONTH else d.year - 1


def format_academic_year(year: int) -> str:
    """2025 → «2025–2026»."""
    return f"{year}–{year + 1}"


def resolve_academic_year(explicit: int | str | None = None) -> int:
    """
    Активный учебный год: explicit > flask.g.active_academic_year > session > текущий.
    Без request-контекста — current_academic_year().
    """
    if explicit is not None and str(explicit).strip() != "":
        try:
            return int(explicit)
        except (TypeError, ValueError):
            pass

    try:
        from flask import g, has_request_context, session

        if has_request_context():
            g_year = getattr(g, "active_academic_year", None)
            if g_year is not None:
                return int(g_year)
            sess_year = session.get("academic_year")
            if sess_year is not None:
                return int(sess_year)
    except Exception:
        pass

    return current_academic_year()


def available_academic_years(school_id: int | None = None) -> list[int]:
    """Список лет с данными в школе + текущий учебный год (по убыванию)."""
    years: set[int] = {current_academic_year()}
    if school_id is not None:
        try:
            from ..extensions import db
            from ..models import GradeReport

            rows = (
                db.session.query(GradeReport.academic_year)
                .filter(GradeReport.school_id == school_id)
                .distinct()
                .all()
            )
            for (y,) in rows:
                if y is not None:
                    years.add(int(y))
        except Exception:
            pass
    return sorted(years, reverse=True)
