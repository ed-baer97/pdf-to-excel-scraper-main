"""Данные кабинета учителя для Desktop API: классы, отчёт предметника, отчёт классрука."""

from __future__ import annotations

from ..constants import kazakh_sort_key, normalize_subject_name
from ..extensions import db
from ..models import Class, Subject, TeacherClass, TeacherSubject
from .academic_year import resolve_academic_year
from .api_helpers import get_period_reports_api
from .class_grades_matrix import (
    build_class_grades_matrix,
    build_teacher_analytics_map,
    get_teacher_subject_class_pairs,
    students_with_grades_count,
    subject_column_stats,
)
from .grade_reports.class_teacher import categorize_students


def teacher_subjects_overview(user) -> dict:
    """Предметы с классами (через TeacherSubject → TeacherClass) и классы классрука."""
    teacher_subjects = TeacherSubject.query.filter_by(teacher_id=user.id).all()

    subjects_data = []
    for ts in teacher_subjects:
        subject = db.session.get(Subject, ts.subject_id)
        if not subject:
            continue

        teacher_classes = TeacherClass.query.filter_by(teacher_subject_id=ts.id).all()
        classes_list = []
        for tc in teacher_classes:
            cls = db.session.get(Class, tc.class_id)
            if cls:
                classes_list.append({
                    "class_name": cls.name,
                    "class_id": cls.id,
                    "subgroup": tc.subgroup,
                })

        if classes_list:
            subjects_data.append({
                "subject_name": subject.name,
                "subject_id": subject.id,
                "classes": classes_list,
            })

    managed = Class.query.filter_by(
        class_teacher_id=user.id,
        school_id=user.school_id,
    ).all()
    return {
        "subjects": subjects_data,
        "managed_classes": [c.name for c in managed],
    }


def subject_report_payload(user, period_number: int, academic_year: int | None) -> list[dict]:
    """Отчёт предметника: статистика оценок по предметам и классам учителя."""
    academic_year = resolve_academic_year(academic_year)
    school_id = user.school_id

    pairs = get_teacher_subject_class_pairs(user.id, school_id)
    if not pairs:
        reports = get_period_reports_api(
            school_id,
            period_number,
            teacher_id=user.id,
            academic_year=academic_year,
        )
        seen_pairs: set[tuple[str, str]] = set()
        for report in reports:
            subj = normalize_subject_name(report.subject_name, school_id)
            key = (subj, report.class_name)
            if key not in seen_pairs:
                seen_pairs.add(key)
                pairs.append(key)

    analytics_map = build_teacher_analytics_map(
        school_id, user.id, period_number, academic_year=academic_year
    )

    subjects_map: dict[str, dict[str, dict]] = {}
    matrix_cache: dict[str, dict] = {}

    for subj, cls in pairs:
        if cls not in matrix_cache:
            matrix_cache[cls] = build_class_grades_matrix(
                school_id, cls, period_number, academic_year=academic_year
            )
        matrix = matrix_cache[cls]
        if matrix["empty"]:
            continue

        stats = subject_column_stats(matrix["students"], subj)
        class_data = {
            "class_name": cls,
            **stats,
            "analytics": analytics_map.get((cls, subj)),
        }
        subjects_map.setdefault(subj, {})[cls] = class_data

    subjects_list = []
    for subj_name in sorted(subjects_map.keys(), key=kazakh_sort_key):
        classes = sorted(
            subjects_map[subj_name].values(),
            key=lambda x: x["class_name"],
        )
        subjects_list.append({
            "subject_name": subj_name,
            "classes": classes,
        })
    return subjects_list


def class_teacher_report_payload(user, period_number: int, academic_year: int | None) -> list[dict] | None:
    """Отчёт классрука: категоризация учеников. None — учитель не классрук."""
    academic_year = resolve_academic_year(academic_year)

    managed_classes = Class.query.filter_by(
        class_teacher_id=user.id,
        school_id=user.school_id,
    ).all()
    if not managed_classes:
        return None

    result_classes = []
    for cls_obj in managed_classes:
        cls_name = cls_obj.name
        matrix = build_class_grades_matrix(
            user.school_id, cls_name, period_number, academic_year=academic_year
        )
        if matrix["empty"]:
            continue

        categories = categorize_students(
            matrix["students"], matrix["subject_teachers"]
        )
        total = students_with_grades_count(matrix["students"])
        result_classes.append({
            "class_name": cls_name,
            "categories": categories,
            "summary": {
                "total_students": total,
                "excellent": len(categories["excellent"]),
                "good": len(categories["good"]),
                "one_4": len(categories["one_4"]),
                "satisfactory": len(categories["satisfactory"]),
                "one_3": len(categories["one_3"]),
                "poor": len(categories["poor"]),
            },
        })
    return result_classes
