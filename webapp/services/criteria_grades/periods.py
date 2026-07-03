"""Периоды критериального оценивания и выбор таблицы по типу периода."""

from __future__ import annotations

import re
from typing import Any

from ..year_grades import YEAR_UI_PERIOD
from .tables import (
    build_criteria_table,
    build_final_table,
    build_simple_grades_table,
    criteria_from_grades_payload,
    final_from_grades_payload,
    has_criteria_data,
    has_final_data,
)

FINAL_UI_PERIOD = 6


def is_final_period(period_number: int) -> bool:
    return period_number == FINAL_UI_PERIOD


def is_final_period_placeholder(period_number: int) -> bool:
    """Устарело: итог больше не заглушка; оставлено для совместимости."""
    return False


def is_year_period(period_number: int) -> bool:
    return period_number == YEAR_UI_PERIOD


def safe_path_segment(name: str, *, max_len: int = 80) -> str:
    """Безопасный сегмент пути для ZIP / имени файла."""
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", (name or "").strip())
    s = re.sub(r"_+", "_", s).strip("._ ")
    if not s:
        return "unknown"
    return s[:max_len]


def criteria_period_path_slug(period_number: int) -> str:
    if is_year_period(period_number):
        return "учебный_год"
    if is_final_period(period_number):
        return "итог"
    return f"{period_number}_четверть"


def table_for_period_payload(
    period_number: int, payload: dict[str, Any] | None
) -> dict[str, Any] | None:
    """Таблица для Excel: критерии / год / итог — как на странице предмета."""
    if not payload:
        return None
    if is_final_period(period_number):
        final_block = final_from_grades_payload(payload)
        if final_block and has_final_data(payload):
            table = build_final_table(final_block)
            return table if table.get("rows") else None
    elif is_year_period(period_number):
        table = build_simple_grades_table(payload)
        return table if table.get("rows") else None
    criteria = criteria_from_grades_payload(payload)
    if criteria and has_criteria_data(payload):
        table = build_criteria_table(criteria)
        return table if table.get("rows") else None
    return None
