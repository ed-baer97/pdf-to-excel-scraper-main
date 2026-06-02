"""Агрегация аналитики СОР/СОЧ/оценок по предметам и классам."""

from __future__ import annotations

from typing import Any

from ...constants import kazakh_sort_key, normalize_subject_name
from ..report_teacher import get_report_teacher_name
from .context import SchoolPeriodContext
from .payload import report_analytics_payload


def _class_sort_key(item: dict[str, Any]) -> tuple:
    name = str(item.get("class_name") or "")
    grade_str = ""
    for ch in name:
        if ch.isdigit():
            grade_str += ch
        else:
            break
    grade_num = int(grade_str) if grade_str else 999
    return (grade_num, name)


def _segment_matches(cls: str, segment: str | None) -> bool:
    if not segment:
        return True
    grade_str = ""
    for ch in str(cls):
        if ch.isdigit():
            grade_str += ch
        else:
            break
    grade_num = int(grade_str) if grade_str else None
    if segment == "1-4":
        return bool(grade_num and 1 <= grade_num <= 4)
    if segment == "5-11":
        return bool(grade_num and 5 <= grade_num <= 11)
    return True


def build_analytics_maps(
    ctx: SchoolPeriodContext,
    *,
    segment: str | None = None,
) -> tuple[dict, dict, dict]:
    """
    Возвращает (subjects_data_sor, subjects_data_soch, subjects_data_grades).
    """
    school_id = ctx.school_id
    subjects_data_sor: dict = {}
    subjects_data_soch: dict = {}
    subjects_data_grades: dict = {}

    for report in ctx.reports:
        subj = normalize_subject_name(report.subject_name, school_id)
        cls = report.class_name
        if cls not in ctx.active_class_names:
            continue
        if not _segment_matches(cls, segment):
            continue

        teacher_name = get_report_teacher_name(report)

        if report.analytics_json:
            analytics = report_analytics_payload(report)
        else:
            analytics = None

        if analytics:
            sor_list = analytics.get("sor", [])
            for sor in sor_list:
                total = (
                    sor.get("count_5", 0)
                    + sor.get("count_4", 0)
                    + sor.get("count_3", 0)
                    + sor.get("count_2", 0)
                )
                sor["total"] = total
                if total > 0:
                    sor["quality"] = round(
                        (sor.get("count_5", 0) + sor.get("count_4", 0)) / total * 100, 1
                    )
                    sor["success_rate"] = round((total - sor.get("count_2", 0)) / total * 100, 1)
                else:
                    sor["quality"] = None
                    sor["success_rate"] = None

            subjects_data_sor.setdefault(subj, []).append(
                {
                    "class_name": cls,
                    "sor_list": sor_list,
                    "teacher": teacher_name,
                    "has_data": len(sor_list) > 0,
                }
            )

            soch = analytics.get("soch", {})
            if soch:
                s5 = soch.get("count_5", 0)
                s4 = soch.get("count_4", 0)
                s3 = soch.get("count_3", 0)
                s2 = soch.get("count_2", 0)
                total = s5 + s4 + s3 + s2
                subjects_data_soch.setdefault(subj, []).append(
                    {
                        "class_name": cls,
                        "count_5": s5,
                        "count_4": s4,
                        "count_3": s3,
                        "count_2": s2,
                        "total": total,
                        "quality": round((s5 + s4) / total * 100, 1) if total else None,
                        "success_rate": round((total - s2) / total * 100, 1) if total else None,
                        "teacher": teacher_name,
                        "has_data": total > 0,
                    }
                )

        grades_data = ctx.payload(report) if report.grades_json else None
        if grades_data:
            s5 = s4 = s3 = s2 = 0
            for student in grades_data.get("students", []):
                g = student.get("grade")
                if g == 5:
                    s5 += 1
                elif g == 4:
                    s4 += 1
                elif g == 3:
                    s3 += 1
                elif g is not None and g <= 2:
                    s2 += 1
            total = s5 + s4 + s3 + s2
            quality = grades_data.get("quality_percent") or (
                round((s5 + s4) / total * 100, 1) if total else None
            )
            success = grades_data.get("success_percent") or (
                round((total - s2) / total * 100, 1) if total else None
            )
            subjects_data_grades.setdefault(subj, []).append(
                {
                    "class_name": cls,
                    "count_5": s5,
                    "count_4": s4,
                    "count_3": s3,
                    "count_2": s2,
                    "total": total,
                    "quality": quality,
                    "success_rate": success,
                    "teacher": teacher_name,
                    "has_data": total > 0,
                }
            )

    for subj_data in (subjects_data_sor, subjects_data_soch, subjects_data_grades):
        for subj in subj_data:
            subj_data[subj].sort(key=_class_sort_key)

    return subjects_data_sor, subjects_data_soch, subjects_data_grades


def sort_analytics_subject_keys(
    subjects_data_sor: dict,
    subjects_data_soch: dict,
    subjects_data_grades: dict,
) -> tuple[dict, dict, dict]:
    """Сортирует ключи предметов для шаблона."""
    return (
        dict(sorted(subjects_data_sor.items(), key=lambda item: kazakh_sort_key(item[0]))),
        dict(sorted(subjects_data_soch.items(), key=lambda item: kazakh_sort_key(item[0]))),
        dict(
            sorted(
                subjects_data_grades.items(), key=lambda item: kazakh_sort_key(item[0])
            )
        ),
    )
