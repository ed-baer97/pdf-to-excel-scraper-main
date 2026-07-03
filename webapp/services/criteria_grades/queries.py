"""Запросы и группировка отчётов для критериального оценивания."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from ...constants import kazakh_sort_key, normalize_subject_name
from ..grade_reports.payload import parse_grades_json
from ..report_teacher import get_report_teacher_name
from .periods import table_for_period_payload
from .tables import has_criteria_data, has_final_data


def report_has_criteria_block(report: Any) -> bool:
    """Проверяет GradeReport на наличие criteria в grades_json."""
    payload = parse_grades_json(getattr(report, "grades_json", None))
    return has_criteria_data(payload)


def report_has_final_block(report: Any) -> bool:
    """Проверяет GradeReport на наличие final в grades_json."""
    payload = parse_grades_json(getattr(report, "grades_json", None))
    return has_final_data(payload)


def report_eligible_for_criteria_period(
    report: Any,
    period_number: int,
) -> tuple[bool, dict[str, Any] | None]:
    """Подходит ли отчёт для раздела критериального оценивания за период."""
    from .periods import is_final_period, is_year_period

    payload = parse_grades_json(getattr(report, "grades_json", None))
    if is_final_period(period_number):
        return (has_final_data(payload), payload)
    if is_year_period(period_number):
        return (bool(payload), payload)
    return (has_criteria_data(payload), payload)


def list_criteria_subject_entries(
    reports: list,
    school_id: int,
    period_number: int,
    *,
    class_name: str | None = None,
) -> list[dict[str, Any]]:
    """
    Записи предметов для критериального оценивания без слияния отчётов разных учителей.

    Если несколько отчётов с одним normalize_subject_name в классе — display_name:
    «Математика 1», «Математика 2», …
    """
    eligible: list[tuple[Any, dict[str, Any]]] = []
    for report in reports:
        if class_name is not None and report.class_name != class_name:
            continue
        ok, payload = report_eligible_for_criteria_period(report, period_number)
        if not ok or payload is None:
            continue
        eligible.append((report, payload))

    groups: dict[tuple[str, str], list[tuple[Any, dict[str, Any]]]] = defaultdict(list)
    for report, payload in eligible:
        base = normalize_subject_name(report.subject_name, school_id)
        groups[(report.class_name, base)].append((report, payload))

    entries: list[dict[str, Any]] = []
    for (cls, base) in sorted(groups.keys(), key=lambda k: (kazakh_sort_key(k[0]), kazakh_sort_key(k[1]))):
        group = groups[(cls, base)]
        group.sort(
            key=lambda item: (
                kazakh_sort_key(get_report_teacher_name(item[0])),
                getattr(item[0], "id", 0) or 0,
            )
        )
        for idx, (report, payload) in enumerate(group, start=1):
            display_name = base if len(group) == 1 else f"{base} {idx}"
            entries.append(
                {
                    "report_id": getattr(report, "id", None),
                    "class_name": cls,
                    "base_name": base,
                    "display_name": display_name,
                    "teacher": get_report_teacher_name(report),
                    "payload": payload,
                    "raw_subject_name": report.subject_name,
                    "has_criteria": has_criteria_data(payload),
                    "has_final": has_final_data(payload),
                }
            )
    return entries


def find_criteria_subject_entry(
    reports: list,
    school_id: int,
    period_number: int,
    class_name: str,
    *,
    display_name: str | None = None,
    report_id: int | None = None,
) -> dict[str, Any] | None:
    """Находит запись предмета по report_id или отображаемому имени."""
    entries = list_criteria_subject_entries(
        reports, school_id, period_number, class_name=class_name
    )
    if report_id is not None:
        for entry in entries:
            if entry.get("report_id") == report_id:
                return entry
        return None
    if display_name:
        for entry in entries:
            if entry.get("display_name") == display_name:
                return entry
        base = normalize_subject_name(display_name, school_id)
        base_matches = [e for e in entries if e.get("base_name") == base]
        if len(base_matches) == 1:
            return base_matches[0]
    return None


def collect_classes_with_criteria(
    reports: list,
    active_class_names: set[str],
    school_id: int,
    period_number: int,
) -> dict[str, dict[str, Any]]:
    """Группирует отчёты по классам; предметы — с нумерацией при нескольких учителях."""
    classes_data: dict[str, dict[str, Any]] = {}
    entries = list_criteria_subject_entries(reports, school_id, period_number)
    for entry in entries:
        class_name = entry["class_name"]
        if class_name not in active_class_names:
            continue
        if class_name not in classes_data:
            classes_data[class_name] = {
                "class_name": class_name,
                "subjects": [],
                "students_count": 0,
            }
        name = entry["display_name"]
        if name not in classes_data[class_name]["subjects"]:
            classes_data[class_name]["subjects"].append(name)
        payload = entry.get("payload") or {}
        total = payload.get("total_students")
        if not total and payload.get("students"):
            total = len(payload.get("students") or [])
        if total:
            classes_data[class_name]["students_count"] = max(
                classes_data[class_name]["students_count"],
                int(total),
            )
    return classes_data


def collect_subject_tables_for_class(
    reports: list,
    class_name: str,
    period_number: int,
    school_id: int,
) -> list[dict[str, Any]]:
    """Данные по предметам класса за период (отдельный лист на каждый отчёт)."""
    sheets: list[dict[str, Any]] = []
    for entry in list_criteria_subject_entries(
        reports, school_id, period_number, class_name=class_name
    ):
        table = table_for_period_payload(period_number, entry.get("payload"))
        if not table:
            continue
        sheets.append(
            {
                "subject": entry["display_name"],
                "table": table,
                "payload": entry.get("payload"),
                "teacher": entry.get("teacher") or "",
            }
        )
    return sheets
