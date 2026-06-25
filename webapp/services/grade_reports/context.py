"""Контекст школы за период: один запрос отчётов и кэш распарсенного JSON."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ...models import Class
from ..academic_year import resolve_academic_year
from .payload import report_analytics_payload, report_grades_payload
from .queries import fetch_semester_subject_pairs, get_period_reports


@dataclass
class SchoolPeriodContext:
    school_id: int
    period_number: int
    active_class_names: set[str]
    reports: list
    academic_year: int

    _payload_cache: dict[int, dict[str, Any] | None] = field(
        default_factory=dict, repr=False
    )
    _analytics_cache: dict[int, dict[str, Any] | None] = field(
        default_factory=dict, repr=False
    )
    semester_pairs: set[tuple[str, str]] | None = field(default=None, repr=False)

    def _cache_key(self, report: Any) -> int:
        rid = getattr(report, "id", None)
        return rid if rid is not None else id(report)

    def payload(self, report: Any) -> dict[str, Any] | None:
        cache_key = self._cache_key(report)
        if cache_key not in self._payload_cache:
            self._payload_cache[cache_key] = report_grades_payload(report)
        return self._payload_cache[cache_key]

    def analytics_payload(self, report: Any) -> dict[str, Any] | None:
        cache_key = self._cache_key(report)
        if cache_key not in self._analytics_cache:
            self._analytics_cache[cache_key] = report_analytics_payload(report)
        return self._analytics_cache[cache_key]

    def filter_active(self) -> list:
        """Отчёты только по активным классам школы."""
        return [r for r in self.reports if r.class_name in self.active_class_names]

    def get_semester_pairs(self) -> set[tuple[str, str]]:
        if self.semester_pairs is None:
            from .queries import fetch_semester_subject_pairs

            self.semester_pairs = fetch_semester_subject_pairs(
                self.school_id,
                academic_year=self.academic_year,
            )
        return self.semester_pairs


def load_school_period_context(
    school_id: int,
    period_number: int,
    *,
    class_name: str | None = None,
    academic_year: int | None = None,
) -> SchoolPeriodContext:
    """Загружает отчёты за период и список активных классов школы."""
    year = resolve_academic_year(academic_year)
    active_class_names = {
        row.name
        for row in Class.query.filter_by(school_id=school_id).with_entities(Class.name).all()
    }
    extra_filters: dict[str, Any] = {}
    if class_name is not None:
        extra_filters["class_name"] = class_name
    semester_pairs = fetch_semester_subject_pairs(school_id, academic_year=year)
    reports = get_period_reports(
        school_id,
        period_number,
        semester_pairs=semester_pairs,
        academic_year=year,
        **extra_filters,
    )
    return SchoolPeriodContext(
        school_id=school_id,
        period_number=period_number,
        active_class_names=active_class_names,
        reports=reports,
        semester_pairs=semester_pairs,
        academic_year=year,
    )
