"""Критериальное оценивание: разбор grades_json, запросы, Excel/ZIP.

Слои:
- tables.py — разбор payload и построение табличных структур;
- periods.py — идентификаторы периодов и выбор таблицы;
- queries.py — группировка отчётов по классам/предметам;
- excel.py — рендеринг xlsx и ZIP.
"""

from ..grade_reports.payload import parse_grades_json
from .excel import build_criteria_period_zip, build_subjects_workbook
from .periods import (
    FINAL_UI_PERIOD,
    criteria_period_path_slug,
    is_final_period,
    is_final_period_placeholder,
    is_year_period,
    safe_path_segment,
    table_for_period_payload,
)
from .queries import (
    collect_classes_with_criteria,
    collect_subject_tables_for_class,
    find_criteria_subject_entry,
    list_criteria_subject_entries,
    report_eligible_for_criteria_period,
    report_has_criteria_block,
    report_has_final_block,
)
from .tables import (
    build_criteria_subject_summary,
    build_criteria_table,
    build_final_table,
    build_simple_grades_table,
    criteria_from_grades_payload,
    final_from_grades_payload,
    format_score_with_max,
    grade_distribution,
    has_criteria_data,
    has_final_data,
    ordered_criteria_sections,
    parse_points_by_section,
    section_label,
)

__all__ = [
    "FINAL_UI_PERIOD",
    "build_criteria_period_zip",
    "build_criteria_subject_summary",
    "build_criteria_table",
    "build_final_table",
    "build_simple_grades_table",
    "build_subjects_workbook",
    "collect_classes_with_criteria",
    "collect_subject_tables_for_class",
    "criteria_from_grades_payload",
    "criteria_period_path_slug",
    "final_from_grades_payload",
    "find_criteria_subject_entry",
    "format_score_with_max",
    "grade_distribution",
    "has_criteria_data",
    "has_final_data",
    "is_final_period",
    "is_final_period_placeholder",
    "is_year_period",
    "list_criteria_subject_entries",
    "ordered_criteria_sections",
    "parse_grades_json",
    "parse_points_by_section",
    "report_eligible_for_criteria_period",
    "report_has_criteria_block",
    "report_has_final_block",
    "safe_path_segment",
    "section_label",
    "table_for_period_payload",
]
