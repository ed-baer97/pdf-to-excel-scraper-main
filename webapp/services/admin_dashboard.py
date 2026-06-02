"""Helper functions for admin dashboard/report views (backward-compatible re-exports)."""

from __future__ import annotations

from .grade_reports.aggregation import (
    aggregate_class_metrics,
    aggregate_year_metrics,
    chart_series_from_class_totals,
)
from .grade_reports.periods import (
    class_accordion_group,
    class_name_sort_key,
    parse_class_grade,
    parse_ui_period_number,
    student_class_summary_category,
    teacher_accordion_group,
    ui_period_display_name,
)
from .grade_reports.queries import get_period_reports, get_quarter_reports
from .year_grades import YEAR_UI_PERIOD

__all__ = [
    "YEAR_UI_PERIOD",
    "aggregate_class_metrics",
    "aggregate_year_metrics",
    "chart_series_from_class_totals",
    "class_accordion_group",
    "class_name_sort_key",
    "get_period_reports",
    "get_quarter_reports",
    "parse_class_grade",
    "parse_ui_period_number",
    "student_class_summary_category",
    "teacher_accordion_group",
    "ui_period_display_name",
]
