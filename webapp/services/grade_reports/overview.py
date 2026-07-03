"""Сводка классов для раздела «Обзор оценок»."""

from __future__ import annotations

from typing import Any

from ...constants import kazakh_sort_key, normalize_subject_name
from .periods import class_accordion_group
from .context import SchoolPeriodContext


def build_grades_overview(ctx: SchoolPeriodContext) -> dict[str, dict[str, Any]]:
    """Группирует отчёты по классам (только активные классы школы)."""
    classes_data: dict[str, dict[str, Any]] = {}
    school_id = ctx.school_id

    for report in ctx.reports:
        class_name = report.class_name
        if class_name not in ctx.active_class_names:
            continue
        if class_name not in classes_data:
            classes_data[class_name] = {
                "class_name": class_name,
                "subjects": [],
                "students_count": 0,
                "quality_percent": 0,
                "success_percent": 0,
            }

        subj_norm = normalize_subject_name(report.subject_name, school_id)
        if subj_norm not in classes_data[class_name]["subjects"]:
            classes_data[class_name]["subjects"].append(subj_norm)

        # Предрассчитанная колонка вместо парсинга grades_json; fallback —
        # старые строки до бэкфилла.
        total_students = getattr(report, "total_students", None)
        if total_students is None:
            grades_data = ctx.payload(report)
            total_students = (grades_data or {}).get("total_students", 0)
        classes_data[class_name]["students_count"] = max(
            classes_data[class_name]["students_count"],
            int(total_students or 0),
        )

    return classes_data


def sort_grades_overview_classes(
    classes_data: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, list]]:
    """Сортировка и разбиение по аккордеонам 1-4 / 5-9 / 10-11."""
    sorted_classes = sorted(
        classes_data.values(), key=lambda x: kazakh_sort_key(x["class_name"])
    )
    classes_by_accordion: dict[str, list] = {"1-4": [], "5-9": [], "10-11": []}
    for cls in sorted_classes:
        group = class_accordion_group(cls["class_name"])
        classes_by_accordion[group].append(cls)
    return sorted_classes, classes_by_accordion
