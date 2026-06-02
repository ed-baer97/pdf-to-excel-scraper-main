"""Контекст школы за период: один запрос отчётов и кэш распарсенного JSON."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ...models import Class
from .payload import report_grades_payload
from .queries import get_period_reports


@dataclass
class SchoolPeriodContext:
    school_id: int
    period_number: int
    active_class_names: set[str]
    reports: list

    _payload_cache: dict[int, dict[str, Any] | None] = field(
        default_factory=dict, repr=False
    )

    def payload(self, report: Any) -> dict[str, Any] | None:
        rid = getattr(report, "id", None)
        cache_key = rid if rid is not None else id(report)
        if cache_key not in self._payload_cache:
            self._payload_cache[cache_key] = report_grades_payload(report)
        return self._payload_cache[cache_key]


def load_school_period_context(
    school_id: int,
    period_number: int,
    *,
    class_name: str | None = None,
) -> SchoolPeriodContext:
    """Загружает отчёты за период и список активных классов школы."""
    active_class_names = {
        row.name
        for row in Class.query.filter_by(school_id=school_id).with_entities(Class.name).all()
    }
    extra_filters: dict[str, Any] = {}
    if class_name is not None:
        extra_filters["class_name"] = class_name
    reports = get_period_reports(school_id, period_number, **extra_filters)
    return SchoolPeriodContext(
        school_id=school_id,
        period_number=period_number,
        active_class_names=active_class_names,
        reports=reports,
    )
