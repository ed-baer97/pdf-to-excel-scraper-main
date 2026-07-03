"""Предрассчитанные агрегаты GradeReport (denormalized из grades_json).

Считаются один раз при записи отчёта (upload с десктопа, редактирование
списка учеников) и сохраняются в колонки GradeReport, чтобы страницы
обзора/аналитики не парсили JSON на каждый запрос.
"""

from __future__ import annotations

from typing import Any

from .payload import parse_grades_json


def compute_grade_aggregates(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Агрегаты по grades_json-payload: распределение 5/4/3/2, качество, успеваемость.

    quality/success берутся из payload, если там уже посчитаны (скрапер пишет их),
    иначе выводятся из распределения оценок.
    """
    empty = {
        "quality_percent": None,
        "success_percent": None,
        "total_students": None,
        "count_5": None,
        "count_4": None,
        "count_3": None,
        "count_2": None,
    }
    if not isinstance(payload, dict):
        return empty

    # Ленивый импорт: criteria_grades сам импортирует grade_reports.payload,
    # импорт на уровне модуля создал бы цикл.
    from ..criteria_grades import grade_distribution

    counts = grade_distribution(payload)
    students = payload.get("students") or []
    total = payload.get("total_students")
    if total is None:
        total = len([s for s in students if isinstance(s, dict)])
    try:
        total = int(total)
    except (TypeError, ValueError):
        total = None

    quality = payload.get("quality_percent")
    success = payload.get("success_percent")
    denom = counts["5"] + counts["4"] + counts["3"] + counts["2"]
    if quality is None and denom:
        quality = round((counts["5"] + counts["4"]) / denom * 100, 1)
    if success is None and denom:
        success = round((counts["5"] + counts["4"] + counts["3"]) / denom * 100, 1)

    def _as_float(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    return {
        "quality_percent": _as_float(quality),
        "success_percent": _as_float(success),
        "total_students": total,
        "count_5": counts["5"],
        "count_4": counts["4"],
        "count_3": counts["3"],
        "count_2": counts["2"],
    }


def apply_grade_aggregates(report: Any, payload: dict[str, Any] | None = None) -> None:
    """Пересчитать и записать агрегатные колонки отчёта.

    Args:
        report: GradeReport (или совместимый объект с grades_json и колонками).
        payload: уже распарсенный grades_json — чтобы не парсить повторно.
    """
    if payload is None:
        payload = parse_grades_json(getattr(report, "grades_json", None))
    aggregates = compute_grade_aggregates(payload)
    for field, value in aggregates.items():
        setattr(report, field, value)
