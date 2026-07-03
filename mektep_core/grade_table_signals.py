"""Признаки структуры видимой таблицы критериального оценивания на mektep.edu.kz."""

from __future__ import annotations

import re
from typing import Iterable

_SOCH_HEADER_RE = re.compile(
    r"^(?:соч|тжб|soch)$",
    re.IGNORECASE,
)
_QUARTER_SOCH_PHRASE_RE = re.compile(
    r"суммативн\w*\s+оценив\w*\s+за\s+четверть",
    re.IGNORECASE,
)


def _normalize_cell(raw: str) -> str:
    return " ".join((raw or "").split()).strip()


def _is_summa_percent_column(txt: str) -> bool:
    """
    Колонка «Сумма%» / «Жиынтық%» — только явные заголовки, не «Суммативное …».
    """
    low = txt.lower().replace(" ", "")
    if "сумматив" in low:
        return False
    if low in ("сумма%", "жиынты%", "жиынтық%", "жиынтық%"):
        return True
    if txt.strip() in ("Сумма%", "Жиынтық%", "Жиынты%", "Жиынтық%"):
        return True
    if low.startswith("сумма") and "%" in txt:
        return True
    if ("жиынты" in low or "жиынтық" in low or "жиынтық" in low) and "%" in txt:
        return True
    return False


def _is_grade_column(txt: str) -> bool:
    low = txt.lower().replace(" ", "")
    return txt in ("Оценка", "Баға", "Бағалау") or low in ("оценка", "баға", "бағалау")


def detect_visible_soch_column(td_texts: Iterable[str]) -> bool:
    """
    В видимой шапке таблицы есть колонка СОЧ / ТЖБ (не «Суммативное за раздел»).
    """
    for raw in td_texts:
        txt = _normalize_cell(raw)
        if not txt:
            continue
        compact = txt.lower().replace(" ", "")
        if _SOCH_HEADER_RE.match(compact):
            return True
        if _QUARTER_SOCH_PHRASE_RE.search(txt):
            return True
    return False


def detect_grade_summary_columns(td_texts: Iterable[str]) -> bool:
    """
    В видимой шапке есть колонки «Сумма%» и «Оценка» (или казахские эквиваленты).
    """
    has_summa = False
    has_grade = False
    for raw in td_texts:
        txt = _normalize_cell(raw)
        if not txt:
            continue
        if _is_summa_percent_column(txt):
            has_summa = True
        if _is_grade_column(txt):
            has_grade = True
    return has_summa and has_grade


def analyze_visible_table_headers(td_texts: Iterable[str]) -> dict[str, bool]:
    """Сводка по видимым колонкам итога за период."""
    texts = list(td_texts)
    return {
        "visible_soch_column": detect_visible_soch_column(texts),
        "visible_grade_summary_columns": detect_grade_summary_columns(texts),
    }


def can_upload_from_visible_headers(td_texts: Iterable[str]) -> bool:
    """Можно загружать оценки на сервер по видимой таблице."""
    analysis = analyze_visible_table_headers(td_texts)
    return analysis["visible_soch_column"] or analysis["visible_grade_summary_columns"]
