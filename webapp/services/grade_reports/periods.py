"""Периоды UI и группировка классов/учителей."""

from __future__ import annotations

import re

from ..criteria_grades import FINAL_UI_PERIOD
from ..year_grades import YEAR_UI_PERIOD


def parse_ui_period_number(raw, default: int = 2) -> int:
    """Нормализует period_number: 1–4 четверти, 5 — учебный год, 6 — итог."""
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return default
    return n if 1 <= n <= FINAL_UI_PERIOD else default


def ui_period_display_name(period_number: int, gettext_func) -> str:
    """Подпись периода для заголовков и Excel."""
    if period_number == FINAL_UI_PERIOD:
        return gettext_func("period_final")
    if period_number == YEAR_UI_PERIOD:
        return gettext_func("period_year")
    if 1 <= period_number <= 4:
        return f"{period_number} {gettext_func('quarter_suffix')}"
    return str(period_number)


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
    grades = [
        parse_class_grade(c.name)
        for c in teacher_classes
        if parse_class_grade(c.name) is not None
    ]
    if not grades:
        return "1-4"
    min_grade = min(grades)
    if min_grade <= 4:
        return "1-4"
    if min_grade <= 9:
        return "5-9"
    return "10-11"


def class_name_sort_key(name: str) -> tuple:
    """Sort key for class labels (e.g. 7А before 10Б)."""
    grade_str = ""
    for ch in str(name):
        if ch.isdigit():
            grade_str += ch
        else:
            break
    grade_num = int(grade_str) if grade_str else 999
    return (grade_num, name)
