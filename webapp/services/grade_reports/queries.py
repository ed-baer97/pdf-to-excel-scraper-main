"""Единая выборка GradeReport за период (четверть, полугодие, год, итог)."""

from __future__ import annotations

from ...constants import normalize_subject_name
from ...extensions import db
from ...models import GradeReport
from ..academic_year import resolve_academic_year
from ..criteria_grades import FINAL_UI_PERIOD
from ..year_grades import YEAR_UI_PERIOD, build_synthetic_year_reports


def fetch_semester_subject_pairs(
    school_id: int,
    *,
    academic_year: int | None = None,
) -> set:
    year = resolve_academic_year(academic_year)
    rows = (
        db.session.query(GradeReport.class_name, GradeReport.subject_name)
        .filter_by(
            school_id=school_id,
            period_type="semester",
            academic_year=year,
        )
        .distinct()
        .all()
    )
    return {(r.class_name, normalize_subject_name(r.subject_name, school_id)) for r in rows}


def _exclude_semester_subjects(
    reports: list,
    period_type: str,
    period_number: int,
    school_id: int,
    *,
    semester_pairs: set | None = None,
    academic_year: int | None = None,
) -> list:
    if period_type != "quarter" or period_number not in (1, 3):
        return reports
    if semester_pairs is None:
        semester_pairs = fetch_semester_subject_pairs(
            school_id, academic_year=academic_year
        )
    if not semester_pairs:
        return reports
    return [
        r
        for r in reports
        if (r.class_name, normalize_subject_name(r.subject_name, school_id))
        not in semester_pairs
    ]


def get_quarter_reports(
    school_id: int,
    period_number: int,
    *,
    semester_pairs: set | None = None,
    academic_year: int | None = None,
    **extra_filters,
):
    """Fetch quarter reports and blend semester-subject reports when required."""
    year = resolve_academic_year(academic_year)
    base_filters = {"school_id": school_id, "academic_year": year, **extra_filters}

    reports = GradeReport.query.filter_by(
        period_type="quarter",
        period_number=period_number,
        **base_filters,
    ).all()

    if period_number == 2:
        reports += GradeReport.query.filter_by(
            period_type="semester",
            period_number=1,
            **base_filters,
        ).all()
    elif period_number == 4:
        reports += GradeReport.query.filter_by(
            period_type="semester",
            period_number=2,
            **base_filters,
        ).all()
    else:
        reports = _exclude_semester_subjects(
            reports,
            "quarter",
            period_number,
            school_id,
            semester_pairs=semester_pairs,
            academic_year=year,
        )

    return reports


def get_period_reports(
    school_id: int,
    period_number: int,
    *,
    semester_pairs: set | None = None,
    academic_year: int | None = None,
    **extra_filters,
):
    """Отчёты за четверть/полугодие (1–4), синтетические за год (5), итог (6)."""
    year = resolve_academic_year(academic_year)
    if period_number == FINAL_UI_PERIOD:
        return GradeReport.query.filter_by(
            school_id=school_id,
            period_type="final",
            period_number=1,
            academic_year=year,
            **extra_filters,
        ).all()
    if period_number == YEAR_UI_PERIOD:
        return build_synthetic_year_reports(
            school_id,
            get_quarter_reports,
            academic_year=year,
            **extra_filters,
        )
    return get_quarter_reports(
        school_id,
        period_number,
        semester_pairs=semester_pairs,
        academic_year=year,
        **extra_filters,
    )
