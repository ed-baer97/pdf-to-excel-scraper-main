"""Агрегация метрик качества/успеваемости по классам и школе."""

from __future__ import annotations

from ...models import GradeReport
from ..academic_year import resolve_academic_year
from ..year_grades import (
    YEAR_UI_PERIOD,
    aggregate_year_metrics as _aggregate_year_metrics,
)
from .cache import cached_computation
from .payload import report_grades_payload
from .periods import class_accordion_group, class_name_sort_key
from .queries import get_quarter_reports


def _accumulate_report_into_class_totals(
    report: GradeReport,
    active_class_names: set[str],
    class_totals: dict,
) -> None:
    """Add one GradeReport row into per-class arithmetic accumulators."""
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
    # Быстрый путь: предрассчитанные агрегатные колонки (заполняются при записи
    # отчёта, см. grade_reports.aggregates) — без парсинга grades_json.
    total = getattr(report, "total_students", None)
    quality = getattr(report, "quality_percent", None)
    success = getattr(report, "success_percent", None)

    if total is None or quality is None or success is None:
        # Fallback: старые строки до бэкфилла и синтетические отчёты —
        # считаем из JSON, как раньше.
        grades_data = report_grades_payload(report)
        if not grades_data:
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

    total = int(total or 0)
    if total <= 0:
        return
    if quality is None or success is None:
        return
    class_totals[class_name]["quality_sum"] += float(quality)
    class_totals[class_name]["success_sum"] += float(success)
    class_totals[class_name]["report_count"] += 1
    class_totals[class_name]["weight_total"] += total


def _build_metrics_from_reports(reports: list, active_class_names: set[str]) -> dict:
    """Из списка отчётов строит class_totals и сводку по школе/параллелям."""
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
        if school_quality_values
        else None
    )
    school_success = (
        round(sum(school_success_values) / len(school_success_values), 1)
        if school_success_values
        else None
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


def aggregate_class_metrics(
    school_id: int,
    period_number: int,
    active_class_names: set[str],
    *,
    academic_year: int | None = None,
) -> dict:
    """KPI по классам/школе за выбранный период.

    Результат кэшируется в Redis (версионная инвалидация при записи
    GradeReport, см. grade_reports.cache); без Redis считается напрямую.
    """
    year = resolve_academic_year(academic_year)

    def _build() -> dict:
        if period_number == YEAR_UI_PERIOD:
            return _aggregate_year_metrics(
                school_id,
                active_class_names,
                get_quarter_reports,
                academic_year=year,
            )
        reports = get_quarter_reports(
            school_id, period_number, academic_year=year
        )
        return _build_metrics_from_reports(reports, active_class_names)

    return cached_computation(
        school_id,
        "class_metrics",
        {
            "period": period_number,
            "year": year,
            "classes": sorted(active_class_names),
        },
        _build,
    )


def aggregate_year_metrics(
    school_id: int,
    active_class_names: set[str],
    *,
    academic_year: int | None = None,
) -> dict:
    """KPI за учебный год (расчёт из четвертей)."""
    year = resolve_academic_year(academic_year)
    return _aggregate_year_metrics(
        school_id,
        active_class_names,
        get_quarter_reports,
        academic_year=year,
    )


def chart_series_from_class_totals(
    class_totals: dict,
) -> tuple[list[str], list[float], list[float]]:
    """Build sorted label/value lists for bar charts."""
    labels = []
    quality_values = []
    success_values = []
    for class_name in sorted(class_totals.keys(), key=class_name_sort_key):
        report_count = class_totals[class_name].get("report_count", 0)
        if report_count <= 0:
            continue
        labels.append(class_name)
        q_val = class_totals[class_name]["quality_sum"] / report_count
        s_val = class_totals[class_name]["success_sum"] / report_count
        quality_values.append(round(q_val, 1) if report_count > 1 else q_val)
        success_values.append(round(s_val, 1) if report_count > 1 else s_val)
    return labels, quality_values, success_values
