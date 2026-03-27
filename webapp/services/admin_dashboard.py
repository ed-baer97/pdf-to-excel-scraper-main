"""Helper functions for admin dashboard/report views."""

from __future__ import annotations

import re

from ..extensions import db
from ..models import GradeReport
from ..constants import normalize_subject_name


def parse_class_grade(class_name: str) -> int | None:
    """Extract numeric grade from class name (e.g. 1A -> 1)."""
    m = re.match(r"^(\d+)", str(class_name or ""))
    return int(m.group(1)) if m else None


def class_accordion_group(class_name: str) -> str:
    """Map class name to accordion bucket."""
    grade = parse_class_grade(class_name)
    if grade is None:
        return "1-4"
    if grade <= 4:
        return "1-4"
    if grade <= 9:
        return "5-9"
    return "10-11"


def student_class_summary_category(grades: dict) -> str | None:
    """Return summary category for student cards."""
    vals = [g.get("grade") for g in grades.values() if g.get("grade") is not None]
    if not vals:
        return None
    if all(g == 5 for g in vals):
        return "excellent"
    if 2 in vals:
        return "failing"
    if 3 not in vals:
        return "good"
    return "troishnik"


def teacher_accordion_group(teacher, classes: list) -> str:
    """Return bucket for class teacher accordion grouping."""
    teacher_classes = [c for c in classes if c.class_teacher_id == teacher.id]
    if not teacher_classes:
        return "no_leadership"
    grades = [parse_class_grade(c.name) for c in teacher_classes if parse_class_grade(c.name) is not None]
    if not grades:
        return "1-4"
    min_grade = min(grades)
    if min_grade <= 4:
        return "1-4"
    if min_grade <= 9:
        return "5-9"
    return "10-11"


def _get_semester_subject_pairs(school_id: int) -> set:
    rows = (
        db.session.query(GradeReport.class_name, GradeReport.subject_name)
        .filter_by(school_id=school_id, period_type="semester")
        .distinct()
        .all()
    )
    return {(r.class_name, normalize_subject_name(r.subject_name)) for r in rows}


def _exclude_semester_subjects(reports: list, period_type: str, period_number: int, school_id: int) -> list:
    if period_type != "quarter" or period_number not in (1, 3):
        return reports
    semester_pairs = _get_semester_subject_pairs(school_id)
    if not semester_pairs:
        return reports
    return [r for r in reports if (r.class_name, normalize_subject_name(r.subject_name)) not in semester_pairs]


def get_quarter_reports(school_id: int, period_number: int, **extra_filters):
    """Fetch quarter reports and blend semester-subject reports when required."""
    reports = GradeReport.query.filter_by(
        school_id=school_id,
        period_type="quarter",
        period_number=period_number,
        **extra_filters,
    ).all()

    if period_number == 2:
        reports += GradeReport.query.filter_by(
            school_id=school_id,
            period_type="semester",
            period_number=1,
            **extra_filters,
        ).all()
    elif period_number == 4:
        reports += GradeReport.query.filter_by(
            school_id=school_id,
            period_type="semester",
            period_number=2,
            **extra_filters,
        ).all()
    else:
        reports = _exclude_semester_subjects(reports, "quarter", period_number, school_id)

    return reports
