"""Редактирование списка учеников в GradeReport (сводная таблица класса)."""

from __future__ import annotations

import json
from typing import Any

from ...extensions import db
from ...models import GradeReport
from ..criteria_grades import grade_distribution
from ..year_grades import YEAR_UI_PERIOD
from .payload import parse_grades_json


def allowed_periods_for_ui(period_number: int) -> set[tuple[str, int]]:
    """Периоды отчётов, соответствующие выбранному периоду на странице сводки."""
    if period_number == YEAR_UI_PERIOD:
        return {
            ("quarter", 1),
            ("quarter", 2),
            ("quarter", 3),
            ("quarter", 4),
            ("semester", 1),
            ("semester", 2),
        }
    allowed = {("quarter", period_number)}
    if period_number == 2:
        allowed.add(("semester", 1))
    elif period_number == 4:
        allowed.add(("semester", 2))
    return allowed


def _student_record_name(record: dict[str, Any]) -> str:
    return (record.get("name") or record.get("fio") or "").strip()


def _filter_student_list(
    students: list[Any] | None,
    target_name: str,
) -> tuple[list[Any], bool]:
    if not isinstance(students, list):
        return students or [], False
    removed = False
    kept: list[Any] = []
    for item in students:
        if not isinstance(item, dict):
            kept.append(item)
            continue
        if _student_record_name(item) == target_name:
            removed = True
        else:
            kept.append(item)
    return kept, removed


def recalculate_grades_summary(payload: dict[str, Any]) -> None:
    """Пересчёт total_students, quality_percent, success_percent по списку students."""
    grades_count = grade_distribution(payload)
    with_grade = sum(grades_count.values())
    students = payload.get("students") or []
    payload["total_students"] = len(
        [s for s in students if isinstance(s, dict) and _student_record_name(s)]
    )
    if with_grade:
        payload["quality_percent"] = round(
            (grades_count["5"] + grades_count["4"]) / with_grade * 100, 1
        )
        payload["success_percent"] = round(
            (grades_count["5"] + grades_count["4"] + grades_count["3"])
            / with_grade
            * 100,
            1,
        )
    else:
        payload["quality_percent"] = 0
        payload["success_percent"] = 0


def remove_student_from_payload(
    payload: dict[str, Any],
    student_name: str,
) -> bool:
    """Удаляет ученика из students / criteria.students / final.students. Возвращает True, если найден."""
    target = student_name.strip()
    if not target:
        return False

    removed = False

    if "students" in payload:
        new_list, changed = _filter_student_list(payload.get("students"), target)
        if changed:
            payload["students"] = new_list
            removed = True
            recalculate_grades_summary(payload)

    criteria = payload.get("criteria")
    if isinstance(criteria, dict) and "students" in criteria:
        new_list, changed = _filter_student_list(criteria.get("students"), target)
        if changed:
            criteria["students"] = new_list
            removed = True

    final = payload.get("final")
    if isinstance(final, dict) and "students" in final:
        new_list, changed = _filter_student_list(final.get("students"), target)
        if changed:
            final["students"] = new_list
            removed = True

    return removed


def delete_student_from_class_reports(
    school_id: int,
    class_name: str,
    student_name: str,
    period_number: int,
) -> int:
    """
    Удаляет ученика из grades_json всех отчётов класса за период UI.

    Returns:
        Число обновлённых GradeReport.
    """
    target = student_name.strip()
    if not target:
        return 0

    allowed = allowed_periods_for_ui(period_number)
    reports = GradeReport.query.filter_by(
        school_id=school_id,
        class_name=class_name,
    ).all()

    updated = 0
    for report in reports:
        if (report.period_type, report.period_number) not in allowed:
            continue
        payload = parse_grades_json(report.grades_json)
        if not payload:
            continue
        if not remove_student_from_payload(payload, target):
            continue
        report.grades_json = json.dumps(payload, ensure_ascii=False)
        updated += 1

    if updated:
        db.session.commit()
    return updated
