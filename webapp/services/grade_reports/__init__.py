"""Централизованная логика отчётов об оценках."""

from .payload import (
    parse_analytics_json,
    parse_grades_json,
    report_analytics_payload,
    report_grades_payload,
)
from .queries import get_period_reports, get_quarter_reports

__all__ = [
    "get_period_reports",
    "get_quarter_reports",
    "parse_analytics_json",
    "parse_grades_json",
    "report_analytics_payload",
    "report_grades_payload",
]
