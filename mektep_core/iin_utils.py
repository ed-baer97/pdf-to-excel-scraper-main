"""Нормализация ИИН (ЖСН) Казахстана для сравнения с логином mektep.edu.kz."""

from __future__ import annotations

import re


def normalize_kz_iin(value: str | None) -> str | None:
    """
    Из строки оставляет только цифры. Возвращает ровно 12 цифр или None.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    digits = re.sub(r"\D", "", s)
    if len(digits) != 12:
        return None
    return digits


def format_iin_for_display(stored: str | None) -> str:
    """Краткое отображение в таблицах (не полный ИИН)."""
    d = normalize_kz_iin(stored) if stored else None
    if not d:
        return "—"
    return f"****{d[-4:]}"
