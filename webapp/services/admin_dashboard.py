"""Helper functions for admin dashboard/report views."""

from __future__ import annotations

import json
import re

from ..extensions import db
from ..models import GradeReport
from ..constants import normalize_subject_name

# UI period_number=5 → GradeReport period_type="year", period_number=1 (вкладка Mektep #chetvert_5)
YEAR_UI_PERIOD = 5


def parse_ui_period_number(raw, default: int = 2) -> int:
    """Нормализует period_number из query/form: 1–4 четверти, 5 — учебный год."""
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return default
    return n if 1 <= n <= YEAR_UI_PERIOD else default


def get_period_reports(school_id: int, period_number: int, **extra_filters):
    """Отчёты за четверть/полугодие (1–4) или за учебный год (5)."""
    if period_number == YEAR_UI_PERIOD:
        return GradeReport.query.filter_by(
            school_id=school_id,
            period_type="year",
            period_number=1,
            **extra_filters,
        ).all()
    return get_quarter_reports(school_id, period_number, **extra_filters)


def ui_period_display_name(period_number: int, gettext_func) -> str:
    """Подпись периода для заголовков и Excel."""
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


def _accumulate_report_into_class_totals(
    report: GradeReport,
    active_class_names: set[str],
    class_totals: dict,
) -> None:
    """Add one GradeReport row into per-class arithmetic accumulators.

    Качество/успеваемость по классу считаются простым средним арифметическим
    процентов по всем учебным предметам (без взвешивания по числу учеников).
    Поле ``weight_total`` сохраняется для информационных целей и равно сумме
    учеников во всех учтённых отчётах класса.
    """
    class_name = report.class_name
    if class_name not in active_class_names:
        return
    if class_name not in class_totals:
        class_totals[class_name] = {
            "quality_sum": 0.0,
            "success_sum": 0.0,
            "report_count": 0,
            "weight_total": 0,
        }
    if not report.grades_json:
        return
    try:
        grades_data = json.loads(report.grades_json)
    except json.JSONDecodeError:
        return
    students = grades_data.get("students", []) or []
    total = int(grades_data.get("total_students") or len(students) or 0)
    if total <= 0:
        return
    quality = grades_data.get("quality_percent")
    success = grades_data.get("success_percent")
    if quality is None:
        s5 = s4 = s3 = s2 = 0
        for student in students:
            grade = student.get("grade")
            if grade == 5:
                s5 += 1
            elif grade == 4:
                s4 += 1
            elif grade == 3:
                s3 += 1
            elif grade is not None and grade <= 2:
                s2 += 1
        denom = s5 + s4 + s3 + s2
        quality = round((s5 + s4) / denom * 100, 1) if denom else None
        success = round((s5 + s4 + s3) / denom * 100, 1) if denom else None
    if quality is None or success is None:
        return
    class_totals[class_name]["quality_sum"] += float(quality)
    class_totals[class_name]["success_sum"] += float(success)
    class_totals[class_name]["report_count"] += 1
    class_totals[class_name]["weight_total"] += total


def _build_metrics_from_reports(reports: list, active_class_names: set[str]) -> dict:
    """Общее ядро агрегации: из списка отчётов строит класс‑тоталы и сводку.

    Качество/успеваемость считаются простым средним арифметическим: внутри
    класса — по всем его предметам; по школе/параллелям — по классам с данными.
    """
    roster = set(active_class_names)
    class_totals: dict = {}
    for report in reports:
        _accumulate_report_into_class_totals(report, roster, class_totals)

    school_quality_values: list[float] = []
    school_success_values: list[float] = []
    parallel_values: dict[str, dict[str, list[float]]] = {
        "1-4": {"quality": [], "success": []},
        "5-9": {"quality": [], "success": []},
        "10-11": {"quality": [], "success": []},
    }
    students_total = 0
    for class_name, agg in class_totals.items():
        rc = agg["report_count"]
        if rc <= 0:
            continue
        class_quality = agg["quality_sum"] / rc
        class_success = agg["success_sum"] / rc
        school_quality_values.append(class_quality)
        school_success_values.append(class_success)
        students_total += int(agg["weight_total"])
        bucket = class_accordion_group(class_name)
        if bucket in parallel_values:
            parallel_values[bucket]["quality"].append(class_quality)
            parallel_values[bucket]["success"].append(class_success)

    school_quality = (
        round(sum(school_quality_values) / len(school_quality_values), 1)
        if school_quality_values else None
    )
    school_success = (
        round(sum(school_success_values) / len(school_success_values), 1)
        if school_success_values else None
    )

    parallel = {}
    for key, vals in parallel_values.items():
        if vals["quality"]:
            parallel[key] = {
                "quality": round(sum(vals["quality"]) / len(vals["quality"]), 1),
                "success": round(sum(vals["success"]) / len(vals["success"]), 1),
            }
        else:
            parallel[key] = {"quality": None, "success": None}

    return {
        "class_totals": class_totals,
        "school_quality": school_quality,
        "school_success": school_success,
        "parallel": parallel,
        "classes_with_data": len(school_quality_values),
        "total_weight": students_total,
        "has_data": bool(school_quality_values),
    }


def aggregate_class_metrics(school_id: int, period_number: int, active_class_names: set[str]) -> dict:
    """
    Качество/успеваемость по классам и по школе за выбранную четверть —
    простое среднее арифметическое.

    Внутри класса: простое среднее процентов по всем учебным предметам.
    По школе и параллелям: простое среднее процентов по классам.

    Учитываются только отчёты, у которых class_name есть в списке классов школы
    (таблица Class). Так удалённый из списка класс не отображается на диаграммах,
    даже если строки GradeReport остались в базе (их можно удалить в «Обзоре оценок»).

    Returns dict with:
      class_totals, school_quality, school_success,
      parallel (1-4, 5-9, 10-11): optional floats,
      classes_with_data, total_weight, has_data.
    """
    if period_number == YEAR_UI_PERIOD:
        return aggregate_year_metrics(school_id, active_class_names)
    reports = get_quarter_reports(school_id, period_number)
    return _build_metrics_from_reports(reports, active_class_names)


def aggregate_year_metrics(school_id: int, active_class_names: set[str]) -> dict:
    """
    Качество/успеваемость по классам и по школе за учебный год.

    Берёт отчёты ``period_type="year"`` (заполняется скрапером со вкладки
    ``#chetvert_5`` на Mektep), агрегация — простое среднее арифметическое,
    структура результата совпадает с :func:`aggregate_class_metrics`.
    """
    reports = GradeReport.query.filter_by(
        school_id=school_id,
        period_type="year",
        period_number=1,
    ).all()
    return _build_metrics_from_reports(reports, active_class_names)


def chart_series_from_class_totals(class_totals: dict) -> tuple[list[str], list[float], list[float]]:
    """Build sorted label/value lists for bar charts.

    Значения по классу — простое среднее арифметическое процентов по предметам
    (без взвешивания по числу учеников).
    """
    labels = []
    quality_values = []
    success_values = []
    for class_name in sorted(class_totals.keys(), key=class_name_sort_key):
        report_count = class_totals[class_name].get("report_count", 0)
        if report_count <= 0:
            continue
        labels.append(class_name)
        quality_values.append(
            round(class_totals[class_name]["quality_sum"] / report_count, 1)
        )
        success_values.append(
            round(class_totals[class_name]["success_sum"] / report_count, 1)
        )
    return labels, quality_values, success_values
