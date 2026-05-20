"""Признаки структуры таблицы критериального оценивания на mektep.edu.kz."""

from __future__ import annotations

from typing import Iterable


def detect_grade_summary_columns(td_texts: Iterable[str]) -> bool:
    """
    Предмет без СОЧ, но с итоговой оценкой: в шапке таблицы есть
    колонки «Сумма%» и «Оценка» (или казахские эквиваленты).
    """
    has_summa = False
    has_grade = False
    for raw in td_texts:
        txt = " ".join((raw or "").split()).strip()
        if not txt:
            continue
        low = txt.lower().replace(" ", "")
        if ("сумма" in low or "жиынты" in low or "жиынтық" in low) and "%" in txt:
            has_summa = True
        if txt in ("Оценка", "Баға", "Бағалау") or low in ("оценка", "баға", "бағалау"):
            has_grade = True
    return has_summa and has_grade
