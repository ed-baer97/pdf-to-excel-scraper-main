"""Сборка данных итогового отчёта из БД оценок (без рендеринга Excel)."""

from __future__ import annotations

from typing import Any

from ....constants import normalize_subject_name
from ....models import Class, GradeReport
from ...academic_year import available_academic_years, resolve_academic_year
from ...year_grades import YEAR_UI_PERIOD
from ..payload import report_grades_payload
from ..periods import class_accordion_group, class_name_sort_key, parse_class_grade
from ..queries import get_period_reports

QUALITY_PERIODS = (1, 2, 3, 4, YEAR_UI_PERIOD)


def resolve_years(school_id: int, academic_year: int | None, years_back: int = 3) -> list[int]:
    """Годы с данными (для имени файла и прочих листов)."""
    all_years = available_academic_years(school_id)
    anchor = resolve_academic_year(academic_year)
    if anchor in all_years:
        idx = all_years.index(anchor)
        picked = all_years[idx : idx + years_back]
    else:
        picked = [anchor]
    return sorted(picked)


def dynamics_year_columns(anchor_year: int, years_back: int = 3) -> list[int]:
    """Ровно N колонок учебных лет подряд, заканчивая anchor_year (для таблицы динамики)."""
    n = max(1, int(years_back))
    start = anchor_year - n + 1
    return list(range(start, anchor_year + 1))


def year_has_grade_data(school_id: int, academic_year: int) -> bool:
    return (
        GradeReport.query.filter_by(school_id=school_id, academic_year=academic_year)
        .limit(1)
        .first()
        is not None
    )


def class_counts_by_period(
    school_id: int,
    academic_year: int,
    period_number: int,
) -> dict[str, int]:
    """Численность по классам за период (макс. total_students по предметам класса)."""
    reports = get_period_reports(
        school_id, period_number, academic_year=academic_year
    )
    by_class: dict[str, int] = {}
    for report in reports:
        payload = report_grades_payload(report)
        if not payload:
            continue
        students = payload.get("students") or []
        total = int(payload.get("total_students") or len(students) or 0)
        if total <= 0:
            continue
        by_class[report.class_name] = max(by_class.get(report.class_name, 0), total)
    return by_class


def stage_breakdown(class_counts: dict[str, int]) -> dict[str, dict[str, int | float] | None]:
    """Разбивка по ступеням: начальная (1–4), основная (5–9), средняя (10–11)."""
    buckets: dict[str, list[int]] = {"primary": [], "basic": [], "secondary": []}
    bucket_map = {"1-4": "primary", "5-9": "basic", "10-11": "secondary"}
    for class_name, count in class_counts.items():
        key = bucket_map.get(class_accordion_group(class_name))
        if key:
            buckets[key].append(count)

    def _stage(items: list[int]) -> dict[str, int | float] | None:
        if not items:
            return None
        return {
            "students": sum(items),
            "classes": len(items),
            "avg_fill": round(sum(items) / len(items), 1),
        }

    return {
        "primary": _stage(buckets["primary"]),
        "basic": _stage(buckets["basic"]),
        "secondary": _stage(buckets["secondary"]),
    }


def section_total(
    breakdown: dict[str, dict[str, int | float] | None],
    metric: str,
) -> int | float | None:
    stages = [s for s in breakdown.values() if s]
    if not stages:
        return None
    if metric == "students":
        return sum(int(s["students"]) for s in stages)
    if metric == "classes":
        return sum(int(s["classes"]) for s in stages)
    if metric == "avg_fill":
        total_students = sum(int(s["students"]) for s in stages)
        total_classes = sum(int(s["classes"]) for s in stages)
        return round(total_students / total_classes, 1) if total_classes else None
    return None


def active_class_names(school_id: int) -> set[str]:
    return {row.name for row in Class.query.filter_by(school_id=school_id).all()}


def class_students_map(
    school_id: int,
    class_name: str,
    academic_year: int,
    period_number: int = YEAR_UI_PERIOD,
) -> dict[str, dict[str, dict]]:
    """Ученики класса: предмет → оценка за выбранный период."""
    reports = get_period_reports(
        school_id,
        period_number,
        class_name=class_name,
        academic_year=academic_year,
    )
    students: dict[str, dict[str, dict]] = {}
    for report in reports:
        subj = normalize_subject_name(report.subject_name, school_id)
        grades_data = report_grades_payload(report)
        if not grades_data:
            continue
        for student in grades_data.get("students", []) or []:
            name = (student.get("name") or "").strip()
            if not name:
                continue
            if name not in students:
                students[name] = {}
            existing = students[name].get(subj)
            new_grade = {
                "percent": student.get("percent"),
                "grade": student.get("grade"),
            }
            if existing is None or existing.get("grade") is None:
                students[name][subj] = new_grade
            elif new_grade.get("grade") is not None and new_grade["grade"] > (
                existing.get("grade") or 0
            ):
                students[name][subj] = new_grade
    return students


def class_grade_summary(
    school_id: int,
    class_name: str,
    academic_year: int,
    period_number: int = YEAR_UI_PERIOD,
) -> dict[str, Any]:
    """Сводка по классу: кол-во на 5/4/3/2, успеваемость, качество."""
    students = class_students_map(school_id, class_name, academic_year, period_number)
    total = len(students)
    if total == 0:
        return {
            "class_name": class_name,
            "total": 0,
            "passing": 0,
            "count_5": 0,
            "count_4": 0,
            "one_3": 0,
            "two_plus_3": 0,
            "count_3": 0,
            "count_2": 0,
            "success_percent": None,
            "quality_percent": None,
        }

    count_5 = count_4 = one_3 = two_plus_3 = count_3 = count_2 = 0
    for grades in students.values():
        vals = [g.get("grade") for g in grades.values() if g.get("grade") is not None]
        if not vals:
            continue
        c3 = sum(1 for g in vals if g == 3)
        c2 = sum(1 for g in vals if g is not None and g <= 2)
        if c2 > 0:
            count_2 += 1
        elif all(g >= 5 for g in vals):
            count_5 += 1
        elif c3 == 0 and 4 in vals:
            count_4 += 1
        elif c3 == 1:
            one_3 += 1
        elif c3 >= 2:
            two_plus_3 += 1
            count_3 += 1
        else:
            count_4 += 1

    passing = total - count_2
    quality = round((count_5 + count_4) / total * 100, 1) if total else None
    success = round(passing / total * 100, 1) if total else None
    return {
        "class_name": class_name,
        "total": total,
        "passing": passing,
        "count_5": count_5,
        "count_4": count_4,
        "one_3": one_3,
        "two_plus_3": two_plus_3,
        "count_3": count_3,
        "count_2": count_2,
        "success_percent": success,
        "quality_percent": quality,
    }


def parallel_summary(class_summaries: list[dict], bucket: str) -> dict[str, Any]:
    subset = [
        s
        for s in class_summaries
        if class_accordion_group(s["class_name"]) == bucket and s["total"] > 0
    ]
    if not subset:
        return {"total": 0, "quality_percent": None, "success_percent": None}
    total = sum(s["total"] for s in subset)
    q_vals = [s["quality_percent"] for s in subset if s["quality_percent"] is not None]
    s_vals = [s["success_percent"] for s in subset if s["success_percent"] is not None]
    return {
        "total": total,
        "quality_percent": round(sum(q_vals) / len(q_vals), 1) if q_vals else None,
        "success_percent": round(sum(s_vals) / len(s_vals), 1) if s_vals else None,
    }


def school_grade_distribution_2_11(
    school_id: int,
    academic_year: int,
    period_number: int,
    active_names: set[str],
) -> dict[str, Any]:
    """Сводка по школе (классы 2–11): распределение на 5/4/3/2 и проценты."""
    count_5 = count_4 = one_3 = count_3 = count_2 = 0
    for class_name in active_names:
        grade_num = parse_class_grade(class_name)
        if grade_num is None or grade_num < 2 or grade_num > 11:
            continue
        summary = class_grade_summary(
            school_id, class_name, academic_year, period_number
        )
        if summary["total"] <= 0:
            continue
        count_5 += summary["count_5"]
        count_4 += summary["count_4"]
        one_3 += summary["one_3"]
        count_3 += summary["count_3"]
        count_2 += summary["count_2"]
    total = count_5 + count_4 + one_3 + count_3 + count_2
    on_3 = one_3 + count_3
    return {
        "count_5": count_5,
        "count_4": count_4,
        "count_3": on_3,
        "count_2": count_2,
        "total": total,
        "quality_percent": round((count_5 + count_4) / total * 100, 1) if total else None,
        "success_percent": round((total - count_2) / total * 100, 1) if total else None,
    }


def subject_quality_matrix(
    school_id: int,
    academic_year: int,
    active_names: set[str],
) -> list[dict[str, Any]]:
    """Качество по предметам и классам."""
    reports = get_period_reports(school_id, YEAR_UI_PERIOD, academic_year=academic_year)
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for report in reports:
        if report.class_name not in active_names:
            continue
        subj = normalize_subject_name(report.subject_name, school_id)
        key = (report.class_name, subj)
        if key in seen:
            continue
        seen.add(key)
        grades_data = report_grades_payload(report)
        if not grades_data:
            continue
        qp = grades_data.get("quality_percent")
        sp = grades_data.get("success_percent")
        if qp is None:
            students = grades_data.get("students", []) or []
            s5 = s4 = s3 = s2 = 0
            for st in students:
                g = st.get("grade")
                if g == 5:
                    s5 += 1
                elif g == 4:
                    s4 += 1
                elif g == 3:
                    s3 += 1
                elif g is not None and g <= 2:
                    s2 += 1
            denom = s5 + s4 + s3 + s2
            qp = round((s5 + s4) / denom * 100, 1) if denom else None
            sp = round((s5 + s4 + s3) / denom * 100, 1) if denom else None
        rows.append(
            {
                "class_name": report.class_name,
                "subject": subj,
                "grade": parse_class_grade(report.class_name),
                "quality_percent": qp,
                "success_percent": sp,
            }
        )
    rows.sort(key=lambda r: (r["subject"], class_name_sort_key(r["class_name"])))
    return rows


def lowest_quality(rows: list[dict], limit: int = 10) -> list[dict]:
    valid = [r for r in rows if r.get("quality_percent") is not None]
    valid.sort(key=lambda r: r["quality_percent"])
    return valid[:limit]
