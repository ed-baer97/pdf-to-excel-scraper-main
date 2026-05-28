"""Единая матрица оценок класса (ученик × предмет) для сводки, предметника и кл. руководителя."""

from __future__ import annotations

import json
from typing import Any

from flask import current_app

from ..constants import kazakh_sort_key, normalize_subject_name
from .api_helpers import get_period_reports_api, get_quarter_reports_api
from .report_teacher import get_report_teacher_name
from .year_grades import (
    YEAR_UI_PERIOD,
    build_year_student_subjects,
    students_data_from_year_map,
)


def _parse_grade(raw: Any) -> int | None:
    if raw is None:
        return None
    try:
        return int(float(str(raw).strip()))
    except (ValueError, TypeError):
        return None


def _merge_grade_cell(
    students_data: dict[str, dict[str, dict]],
    name: str,
    subj: str,
    percent: Any,
    grade_raw: Any,
) -> None:
    new_grade = _parse_grade(grade_raw)
    if name not in students_data:
        students_data[name] = {}
    existing = students_data[name].get(subj)
    new_cell = {"percent": percent, "grade": new_grade}
    if existing is None or existing.get("grade") is None:
        students_data[name][subj] = new_cell
    elif new_grade is not None and new_grade > (existing.get("grade") or 0):
        students_data[name][subj] = new_cell


def build_subject_teachers_map(reports: list) -> dict[str, str]:
    """Предмет → ФИО учителя (из последнего отчёта в списке)."""
    subject_teachers: dict[str, str] = {}
    for report in reports:
        teacher_name = get_report_teacher_name(report)
        subj = normalize_subject_name(report.subject_name, report.school_id)
        subject_teachers[subj] = teacher_name
    return subject_teachers


def build_class_grades_matrix(
    school_id: int,
    class_name: str,
    period_number: int,
) -> dict[str, Any]:
    """
    Матрица оценок класса за период (та же логика, что «Оценки по классу»).

    Returns:
        subjects: list[str]
        students: dict[name, dict[subject, {"grade": int|None, "percent": ...}]]
        subject_teachers: dict[subject, teacher_name]
        empty: bool — нет данных
    """
    students_data: dict[str, dict[str, dict]] = {}
    subjects: set[str] = set()
    subject_teachers: dict[str, str] = {}

    if period_number == YEAR_UI_PERIOD:
        year_map = build_year_student_subjects(
            school_id, class_name, get_quarter_reports_api
        )
        students_data = students_data_from_year_map(year_map)
        subjects = {subj for subjs in students_data.values() for subj in subjs}
        reports = get_quarter_reports_api(school_id, 1, class_name=class_name)
        if not reports:
            for pn in (2, 3, 4):
                reports = get_period_reports_api(
                    school_id, pn, class_name=class_name
                )
                if reports:
                    break
        subject_teachers = build_subject_teachers_map(reports)
    else:
        reports = get_period_reports_api(
            school_id, period_number, class_name=class_name
        )
        if not reports:
            return {
                "subjects": [],
                "students": {},
                "subject_teachers": {},
                "empty": True,
            }

        subject_teachers = build_subject_teachers_map(reports)

        for report in reports:
            subj = normalize_subject_name(report.subject_name, school_id)
            subjects.add(subj)
            if not report.grades_json:
                continue
            try:
                grades_data = json.loads(report.grades_json)
            except json.JSONDecodeError:
                current_app.logger.error(
                    "Invalid JSON in report %s", report.id
                )
                continue
            for student in grades_data.get("students", []) or []:
                name = (student.get("name") or "").strip()
                if not name:
                    continue
                _merge_grade_cell(
                    students_data,
                    name,
                    subj,
                    student.get("percent"),
                    student.get("grade"),
                )

    subjects_list = sorted(subjects, key=kazakh_sort_key)
    return {
        "subjects": subjects_list,
        "students": students_data,
        "subject_teachers": subject_teachers,
        "empty": not students_data,
    }


def subject_column_stats(
    students_data: dict[str, dict[str, dict]],
    subject_name: str,
) -> dict[str, Any]:
    """Счётчики 5/4/3/2 и качество/успеваемость по столбцу предмета (как футер сводки)."""
    class_data: dict[str, Any] = {
        "count_5": 0,
        "count_4": 0,
        "count_3": 0,
        "count_2": 0,
        "total": 0,
        "quality_percent": 0,
        "success_percent": 0,
    }
    for _name, grades in students_data.items():
        gi = grades.get(subject_name, {})
        g = _parse_grade(gi.get("grade"))
        if g is None:
            continue
        class_data["total"] += 1
        if g >= 5:
            class_data["count_5"] += 1
        elif g >= 4:
            class_data["count_4"] += 1
        elif g >= 3:
            class_data["count_3"] += 1
        else:
            class_data["count_2"] += 1

    total = class_data["total"]
    if total > 0:
        class_data["quality_percent"] = round(
            (class_data["count_5"] + class_data["count_4"]) / total * 100, 1
        )
        class_data["success_percent"] = round(
            (total - class_data["count_2"]) / total * 100, 1
        )
    return class_data


def students_with_grades_count(students_data: dict[str, dict[str, dict]]) -> int:
    """Число учеников с хотя бы одной оценкой в матрице."""
    return sum(
        1
        for grades in students_data.values()
        if any(_parse_grade(g.get("grade")) is not None for g in grades.values())
    )


def categorize_students(
    students_data: dict[str, dict[str, dict]],
    subject_teachers: dict[str, str],
) -> dict[str, list]:
    """Категории учеников для отчёта классного руководителя."""
    categories: dict[str, list] = {
        "excellent": [],
        "good": [],
        "one_4": [],
        "satisfactory": [],
        "one_3": [],
        "poor": [],
    }

    students_grades: dict[str, dict[str, int]] = {}
    for name, grades in students_data.items():
        row: dict[str, int] = {}
        for subj, gi in grades.items():
            g = _parse_grade(gi.get("grade"))
            if g is not None:
                row[subj] = g
        if row:
            students_grades[name] = row

    for name, subj_grades in sorted(
        students_grades.items(), key=lambda item: kazakh_sort_key(item[0])
    ):
        grades_list = list(subj_grades.values())
        if not grades_list:
            continue

        count_4 = grades_list.count(4)
        count_3 = grades_list.count(3)
        count_2 = sum(1 for g in grades_list if g <= 2)

        if count_2 > 0:
            failing_subjects = [
                {"subject": s, "teacher": subject_teachers.get(s, "")}
                for s, g in subj_grades.items()
                if g <= 2
            ]
            categories["poor"].append(
                {"name": name, "subjects": failing_subjects}
            )
        elif all(g >= 5 for g in grades_list):
            categories["excellent"].append({"name": name})
        elif count_4 == 1 and count_3 == 0:
            subj_with_4 = next((s for s, g in subj_grades.items() if g == 4), "")
            categories["one_4"].append(
                {
                    "name": name,
                    "subject": subj_with_4,
                    "teacher": subject_teachers.get(subj_with_4, ""),
                }
            )
        elif count_3 == 0:
            categories["good"].append({"name": name})
        elif count_3 == 1:
            subj_with_3 = next((s for s, g in subj_grades.items() if g == 3), "")
            categories["one_3"].append(
                {
                    "name": name,
                    "subject": subj_with_3,
                    "teacher": subject_teachers.get(subj_with_3, ""),
                }
            )
        else:
            subjects_with_3 = [s for s, g in subj_grades.items() if g == 3]
            categories["satisfactory"].append(
                {"name": name, "subjects_with_3": subjects_with_3}
            )

    return categories


def class_grades_summary(
    students_data: dict[str, dict[str, dict]],
    period_number: int,
) -> dict[str, Any]:
    """Сводка для api_get_class_grades (карточки качества/успеваемости)."""
    from .year_grades import quality_success_from_grades

    total_students = len(students_data)
    grades_count = {"5": 0, "4": 0, "3": 0, "2": 0}

    for _name, grades in students_data.items():
        grades_values = [
            _parse_grade(g.get("grade"))
            for g in grades.values()
            if _parse_grade(g.get("grade")) is not None
        ]
        if grades_values:
            avg_grade = sum(grades_values) / len(grades_values)
            if avg_grade >= 4.5:
                grades_count["5"] += 1
            elif avg_grade >= 3.5:
                grades_count["4"] += 1
            elif avg_grade >= 2.5:
                grades_count["3"] += 1
            else:
                grades_count["2"] += 1

    quality_percent = 0
    success_percent = 0
    if period_number == YEAR_UI_PERIOD:
        all_cells = [
            _parse_grade(g.get("grade"))
            for grades in students_data.values()
            for g in grades.values()
            if _parse_grade(g.get("grade")) is not None
        ]
        if all_cells:
            quality_percent, success_percent = quality_success_from_grades(
                all_cells
            )
    elif total_students > 0:
        quality_percent = round(
            (grades_count["5"] + grades_count["4"]) / total_students * 100, 1
        )
        success_percent = round(
            (grades_count["5"] + grades_count["4"] + grades_count["3"])
            / total_students
            * 100,
            1,
        )

    return {
        "total_students": total_students,
        "quality_percent": quality_percent,
        "success_percent": success_percent,
    }


def get_teacher_subject_class_pairs(
    teacher_id: int,
    school_id: int,
) -> list[tuple[str, str]]:
    """Пары (канонический предмет, класс) из закрепления учителя."""
    from ..extensions import db
    from ..models import Class, Subject, TeacherClass, TeacherSubject

    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for ts in TeacherSubject.query.filter_by(teacher_id=teacher_id).all():
        subject = db.session.get(Subject, ts.subject_id)
        if not subject:
            continue
        subj = normalize_subject_name(subject.name, school_id)
        for tc in TeacherClass.query.filter_by(teacher_subject_id=ts.id).all():
            cls = db.session.get(Class, tc.class_id)
            if not cls or cls.school_id != school_id:
                continue
            key = (subj, cls.name)
            if key not in seen:
                seen.add(key)
                pairs.append(key)

    return pairs


def build_teacher_analytics_map(
    school_id: int,
    teacher_id: int,
    period_number: int,
) -> dict[tuple[str, str], dict]:
    """(class_name, subject) → analytics_json для отчёта предметника."""
    reports = get_period_reports_api(
        school_id, period_number, teacher_id=teacher_id
    )
    out: dict[tuple[str, str], dict] = {}
    for report in reports:
        subj = normalize_subject_name(report.subject_name, school_id)
        key = (report.class_name, subj)
        if not report.analytics_json:
            continue
        try:
            out[key] = json.loads(report.analytics_json)
        except json.JSONDecodeError:
            pass
    return out
