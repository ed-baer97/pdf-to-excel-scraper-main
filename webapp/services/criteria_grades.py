"""Критериальное оценивание: разбор grades_json.criteria и построение таблиц."""

from __future__ import annotations

import json
from typing import Any

from .year_grades import YEAR_UI_PERIOD

FINAL_UI_PERIOD = 6


def parse_points_by_section(points: dict[str, str], quarter_num: int) -> dict[int, str]:
    """Группирует значения points по номеру секции razdel (как в scrape_mektep)."""
    out: dict[int, str] = {}
    prefix = f"chetvert_{quarter_num}_razdel_"
    for k, v in (points or {}).items():
        if not isinstance(k, str) or not k.startswith(prefix):
            continue
        parts = k.split("_")
        if len(parts) >= 5 and parts[2] == "razdel":
            try:
                section = int(parts[3])
            except (TypeError, ValueError):
                continue
            out[section] = v
    return out


def criteria_from_grades_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Извлекает блок criteria из распарсенного grades_json."""
    if not isinstance(payload, dict):
        return None
    criteria = payload.get("criteria")
    return criteria if isinstance(criteria, dict) else None


def final_from_grades_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Извлекает блок final (четвертные/годовые оценки) из grades_json."""
    if not isinstance(payload, dict):
        return None
    final = payload.get("final")
    return final if isinstance(final, dict) else None


def has_final_data(payload: dict[str, Any] | None) -> bool:
    """Есть ли таблица итога (quarter_final scrape)."""
    final = final_from_grades_payload(payload)
    if not final:
        return False
    students = final.get("students")
    return isinstance(students, list) and len(students) > 0


def has_criteria_data(payload: dict[str, Any] | None) -> bool:
    """Есть ли детализированные критериальные строки учеников."""
    criteria = criteria_from_grades_payload(payload)
    if not criteria:
        return False
    students = criteria.get("students")
    return isinstance(students, list) and len(students) > 0


def parse_grades_json(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def ordered_criteria_sections(
    criteria: dict[str, Any],
) -> list[tuple[int, str]]:
    """
    Секции для заголовков: СОр 1..N, затем СОЧ (0).
    Возвращает [(section_id, label), ...].
    """
    quarter_num = int(criteria.get("quarter_num") or 0)
    max_points = criteria.get("max_points") or {}
    if not isinstance(max_points, dict):
        max_points = {}

    sections: set[int] = set()
    for sid in criteria.get("sections") or []:
        try:
            sections.add(int(sid))
        except (TypeError, ValueError):
            pass

    for s in criteria.get("students") or []:
        if not isinstance(s, dict):
            continue
        pts = s.get("points") or {}
        if isinstance(pts, dict):
            sections.update(parse_points_by_section(pts, quarter_num).keys())

    for k in max_points:
        try:
            sections.add(int(k))
        except (TypeError, ValueError):
            pass

    sor_secs = sorted(s for s in sections if s > 0)
    result: list[tuple[int, str]] = [(sec, f"СОр {sec}") for sec in sor_secs]
    if 0 in sections:
        result.append((0, "СОЧ"))
    return result


def section_label(section_id: int) -> str:
    if section_id == 0:
        return "СОЧ"
    return f"СОр {section_id}"


def _section_max_points(max_points: dict, section_id: int) -> int | None:
    """Максимальный балл секции из criteria.max_points."""
    if not isinstance(max_points, dict):
        return None
    raw = max_points.get(str(section_id), max_points.get(section_id))
    if raw is None or raw == "":
        return None
    try:
        val = int(raw)
        return val if val > 0 else None
    except (TypeError, ValueError):
        return None


def format_score_with_max(raw: str | int | float | None, section_id: int, max_points: dict) -> str:
    """Балл в формате «17/20», если известен максимум; иначе как есть."""
    if raw is None or raw == "":
        return ""
    text = str(raw).strip()
    if not text or "%" in text:
        return text
    mp = _section_max_points(max_points, section_id)
    if mp is None:
        return text
    return f"{text}/{mp}"


def build_criteria_table(criteria: dict[str, Any]) -> dict[str, Any]:
    """
    Строит заголовки и строки для шаблона.
    Колонки: №, ФИО, ФО, [СОр N...], СОЧ (если sec 0), Сумма, Оценка.
    """
    quarter_num = int(criteria.get("quarter_num") or 0)
    sections = ordered_criteria_sections(criteria)
    max_points = criteria.get("max_points") or {}

    headers = ["№", "ФИО", "ФО"]
    for sec_id, label in sections:
        if sec_id > 0:
            mp = _section_max_points(max_points, sec_id)
            headers.append(f"{label} (макс. {mp})" if mp else label)
    has_soch_col = any(sid == 0 for sid, _ in sections)
    if has_soch_col:
        mp_soch = _section_max_points(max_points, 0)
        headers.append(f"СОЧ (макс. {mp_soch})" if mp_soch else "СОЧ")
    headers.extend(["Сумма", "Оценка"])

    rows: list[dict[str, Any]] = []
    students = criteria.get("students") or []
    sorted_students = sorted(
        [s for s in students if isinstance(s, dict)],
        key=lambda s: int(s.get("num") or 0),
    )

    for s in sorted_students:
        fio = (s.get("fio") or s.get("name") or "").strip()
        if not fio:
            continue
        pts = s.get("points") or {}
        sec_points = (
            parse_points_by_section(pts, quarter_num) if isinstance(pts, dict) else {}
        )

        cells: list[str] = [
            str(s.get("num") or ""),
            fio,
            str(s.get("average") or ""),
        ]
        for sec_id, _label in sections:
            if sec_id > 0:
                cells.append(
                    format_score_with_max(sec_points.get(sec_id, ""), sec_id, max_points)
                )
        if has_soch_col:
            soch_val = sec_points.get(0, "")
            if soch_val:
                cells.append(format_score_with_max(soch_val, 0, max_points))
            else:
                cells.append(str(s.get("soch_pct") or ""))
        cells.append(str(s.get("total_pct") or ""))
        cells.append(str(s.get("grade") or ""))

        rows.append({"cells": cells})

    return {"headers": headers, "rows": rows}


def grade_distribution(payload: dict[str, Any] | None) -> dict[str, int]:
    """Распределение итоговых оценок 5/4/3/2 по payload.students."""
    counts = {"5": 0, "4": 0, "3": 0, "2": 0}
    if not isinstance(payload, dict):
        return counts
    for s in payload.get("students") or []:
        if not isinstance(s, dict):
            continue
        raw = s.get("grade")
        if raw in (None, "", "0", 0):
            continue
        try:
            g = int(float(str(raw).strip()))
        except (TypeError, ValueError):
            continue
        if g >= 5:
            counts["5"] += 1
        elif g >= 4:
            counts["4"] += 1
        elif g >= 3:
            counts["3"] += 1
        else:
            counts["2"] += 1
    return counts


def build_criteria_subject_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Сводка для шапки страницы предмета: распределение, качество, успеваемость."""
    grades_count = grade_distribution(payload)
    total = 0
    if isinstance(payload, dict):
        total = int(payload.get("total_students") or 0)
        if not total:
            total = len(payload.get("students") or [])
    with_grade = sum(grades_count.values())
    quality = payload.get("quality_percent") if isinstance(payload, dict) else 0
    success = payload.get("success_percent") if isinstance(payload, dict) else 0
    if isinstance(payload, dict) and with_grade and (quality in (None, 0) and success in (None, 0)):
        quality = round((grades_count["5"] + grades_count["4"]) / with_grade * 100, 1)
        success = round(
            (grades_count["5"] + grades_count["4"] + grades_count["3"]) / with_grade * 100, 1
        )
    return {
        "grades_count": grades_count,
        "total_students": total,
        "with_grade": with_grade,
        "quality_percent": quality or 0,
        "success_percent": success or 0,
    }


def build_final_table(final: dict[str, Any]) -> dict[str, Any]:
    """Таблица итога: №, ФИО + динамические колонки (четверти, экзамен, итог)."""
    columns = final.get("columns") or []
    headers = ["№", "ФИО"] + [
        str(c.get("label") or c.get("key") or "") for c in columns if isinstance(c, dict)
    ]
    rows: list[dict[str, Any]] = []
    students = final.get("students") or []
    sorted_students = sorted(
        [s for s in students if isinstance(s, dict)],
        key=lambda s: int(s.get("num") or 0),
    )
    for s in sorted_students:
        fio = (s.get("fio") or "").strip()
        if not fio:
            continue
        cells = [str(s.get("num") or ""), fio]
        for col in columns:
            if not isinstance(col, dict):
                continue
            key = col.get("key", "")
            cells.append(str(s.get(key, "")))
        rows.append({"cells": cells})
    return {"headers": headers, "rows": rows}


def build_simple_grades_table(payload: dict[str, Any]) -> dict[str, Any]:
    """Упрощённая таблица для учебного года: №, ФИО, итоговая оценка (без %)."""
    headers = ["№", "ФИО", "Оценка"]
    rows: list[dict[str, Any]] = []
    for i, s in enumerate(payload.get("students") or [], start=1):
        if not isinstance(s, dict):
            continue
        name = (s.get("name") or "").strip()
        if not name:
            continue
        rows.append(
            {
                "cells": [
                    str(i),
                    name,
                    str(s.get("grade") if s.get("grade") is not None else ""),
                ]
            }
        )
    return {"headers": headers, "rows": rows}


def report_has_criteria_block(report: Any) -> bool:
    """Проверяет GradeReport на наличие criteria в grades_json."""
    payload = parse_grades_json(getattr(report, "grades_json", None))
    return has_criteria_data(payload)


def report_has_final_block(report: Any) -> bool:
    """Проверяет GradeReport на наличие final в grades_json."""
    payload = parse_grades_json(getattr(report, "grades_json", None))
    return has_final_data(payload)


def collect_classes_with_criteria(
    reports: list,
    active_class_names: set[str],
    school_id: int,
    *,
    require_criteria: bool = True,
    require_final: bool = False,
) -> dict[str, dict[str, Any]]:
    """
    Группирует отчёты по классам.
    require_criteria: только отчёты с блоком criteria.
    require_final: только отчёты с блоком final (итог).
    """
    from ..constants import normalize_subject_name

    classes_data: dict[str, dict[str, Any]] = {}
    for report in reports:
        class_name = report.class_name
        if class_name not in active_class_names:
            continue
        payload = parse_grades_json(report.grades_json)
        if require_final and not has_final_data(payload):
            continue
        if require_criteria and not has_criteria_data(payload):
            continue
        if not require_criteria and not require_final and not payload:
            continue

        if class_name not in classes_data:
            classes_data[class_name] = {
                "class_name": class_name,
                "subjects": [],
                "students_count": 0,
            }

        subj_norm = normalize_subject_name(report.subject_name, school_id)
        if subj_norm not in classes_data[class_name]["subjects"]:
            classes_data[class_name]["subjects"].append(subj_norm)

        if payload:
            total = payload.get("total_students")
            if not total and payload.get("students"):
                total = len(payload.get("students") or [])
            if total:
                classes_data[class_name]["students_count"] = max(
                    classes_data[class_name]["students_count"],
                    int(total),
                )
    return classes_data


def is_final_period(period_number: int) -> bool:
    return period_number == FINAL_UI_PERIOD


def is_final_period_placeholder(period_number: int) -> bool:
    """Устарело: итог больше не заглушка; оставлено для совместимости."""
    return False


def is_year_period(period_number: int) -> bool:
    return period_number == YEAR_UI_PERIOD
