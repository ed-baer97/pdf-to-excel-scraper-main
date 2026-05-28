"""Имя учителя из GradeReport или SyntheticGradeReport."""

from __future__ import annotations

from typing import Any

from ..constants import normalize_subject_name
from ..extensions import db
from ..models import User


def get_report_teacher_name(report: Any) -> str:
    """ФИО/логин учителя отчёта; без AttributeError для SyntheticGradeReport."""
    teacher = getattr(report, "teacher", None)
    if teacher is None:
        tid = getattr(report, "teacher_id", None) or 0
        if tid:
            teacher = db.session.get(User, int(tid))
    if not teacher:
        return ""
    return (getattr(teacher, "full_name", None) or getattr(teacher, "username", None) or "").strip()


def lookup_teacher_id_for_class_subject(
    school_id: int,
    class_name: str,
    subject_name: str,
    get_quarter_reports,
) -> int:
    """teacher_id из последнего четвертного отчёта по классу и предмету."""
    subj_norm = normalize_subject_name(subject_name, school_id)
    for period_number in (4, 3, 2, 1):
        for report in get_quarter_reports(school_id, period_number, class_name=class_name):
            if normalize_subject_name(report.subject_name, school_id) != subj_norm:
                continue
            tid = getattr(report, "teacher_id", None) or 0
            if tid:
                return int(tid)
    return 0
