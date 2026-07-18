"""Загрузка и сохранение ручных данных итогового отчёта."""

from __future__ import annotations

import json
from typing import Any

from ...extensions import db
from ...models import FinalReportData, FinalReportSection
from ..academic_year import resolve_academic_year

VALID_SECTIONS = {s.value for s in FinalReportSection}


def default_section_data(section: str) -> dict[str, Any]:
    """Пустой шаблон JSON для раздела."""
    if section == FinalReportSection.AWARDS.value:
        return {
            "altyn_belgi": 0,
            "excellent_11": 0,
            "excellent_9": 0,
            "students": [],
        }
    return {}


def load_section_data(
    school_id: int,
    academic_year: int | None,
    section: str,
) -> dict[str, Any]:
    """Прочитать JSON раздела или вернуть шаблон по умолчанию."""
    if section not in VALID_SECTIONS:
        return {}
    year = resolve_academic_year(academic_year)
    row = FinalReportData.query.filter_by(
        school_id=school_id,
        academic_year=year,
        section=section,
    ).first()
    if not row or not row.data_json:
        return default_section_data(section)
    try:
        data = json.loads(row.data_json)
        if isinstance(data, dict):
            return data
    except (TypeError, json.JSONDecodeError):
        pass
    return default_section_data(section)


def load_all_sections(
    school_id: int,
    academic_year: int | None,
) -> dict[str, dict[str, Any]]:
    """Все разделы за учебный год."""
    return {
        section: load_section_data(school_id, academic_year, section)
        for section in VALID_SECTIONS
    }


def save_section_data(
    school_id: int,
    academic_year: int | None,
    section: str,
    data: dict[str, Any],
) -> FinalReportData:
    """Сохранить или обновить JSON раздела."""
    if section not in VALID_SECTIONS:
        raise ValueError(f"invalid section: {section}")
    year = resolve_academic_year(academic_year)
    row = FinalReportData.query.filter_by(
        school_id=school_id,
        academic_year=year,
        section=section,
    ).first()
    payload = json.dumps(data, ensure_ascii=False)
    if row:
        row.data_json = payload
    else:
        row = FinalReportData(
            school_id=school_id,
            academic_year=year,
            section=section,
            data_json=payload,
        )
        db.session.add(row)
    db.session.commit()
    return row


def load_sections_for_years(
    school_id: int,
    years: list[int],
) -> dict[int, dict[str, dict[str, Any]]]:
    """Разделы по нескольким учебным годам (для экспорта)."""
    return {year: load_all_sections(school_id, year) for year in years}
