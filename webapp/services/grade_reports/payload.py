"""Разбор JSON полей GradeReport (grades_json, analytics_json)."""

from __future__ import annotations

import json
from typing import Any


def parse_grades_json(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def parse_analytics_json(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def report_grades_payload(report: Any) -> dict[str, Any] | None:
    """Распарсенный grades_json для ORM-отчёта или объекта с полем grades_json."""
    return parse_grades_json(getattr(report, "grades_json", None))


def report_analytics_payload(report: Any) -> dict[str, Any] | None:
    """Распарсенный analytics_json для ORM-отчёта."""
    return parse_analytics_json(getattr(report, "analytics_json", None))
