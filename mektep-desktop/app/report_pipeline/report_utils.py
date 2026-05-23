"""Вспомогательные функции для путей отчётов, имён файлов и определения периода."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any, Optional, Tuple


def move_file(src: Path, dst: Path) -> Optional[Path]:
    """Переместить файл; при ошибке — копировать."""
    try:
        shutil.move(str(src), str(dst))
        return dst
    except Exception:
        try:
            shutil.copy2(str(src), str(dst))
            return dst
        except Exception:
            return None


def sanitize_filename(s: str) -> str:
    """Очистка строки для использования в имени файла."""
    s = " ".join((s or "").split()).strip()
    s = re.sub(r'[<>:"/\\|?*]+', "_", s)
    s = s.strip(" .")
    return s or "report"


def parse_class_liter(class_text: str) -> str:
    """Нормализация названия класса: '5 «В»' -> '5В'"""
    s = (class_text or "").replace("«", " ").replace("»", " ").strip()
    m = re.search(r"(\d+)\s*([A-Za-zА-ЯЁӘҒҚҢӨҰҮҺа-яёәғқңөұүһ])?", s)
    if not m:
        return (class_text or "").strip()
    num = m.group(1)
    lit = (m.group(2) or "").upper()
    return f"{num}{lit}".strip()


def parse_number(val: Any) -> Optional[float]:
    """Преобразовать значение в float."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace("%", "").replace(",", ".")
    try:
        return float(s) if s else None
    except (ValueError, TypeError):
        return None


def is_semester_subject(batch_subdir: Path) -> bool:
    """
    Проверяет, является ли предмет полугодовым (оценка не за четверть).

    Приоритет: criteria_context.json.has_quarter_grade_header —
    если в панели есть заголовок «Расчет оценки за N четверть» / «Бағаны есептеу: N тоқсан»,
    то has_quarter_grade_header=True → предмет четвертной (не полугодовой).
    Если заголовка нет → полугодовой/по разделам.

    Fallback (старые batch): criteria_tabs.json с метками «полугод» / «жартыжылдық».
    """
    ctx_file = batch_subdir / "criteria_context.json"
    if ctx_file.exists():
        try:
            with open(ctx_file, "r", encoding="utf-8") as f:
                ctx = json.load(f)
            if "has_quarter_grade_header" in ctx:
                return not ctx["has_quarter_grade_header"]
        except Exception:
            pass
    tabs_file = batch_subdir / "criteria_tabs.json"
    if not tabs_file.exists():
        return False
    try:
        with open(tabs_file, "r", encoding="utf-8") as f:
            tabs = json.load(f)
        for tab in tabs:
            text = (tab.get("text") or "").lower()
            if "полугод" in text or "жартыжылдық" in text:
                return True
    except Exception:
        pass
    return False


def resolve_period(period_code: str, batch_subdir: Path) -> Tuple[str, int, bool]:
    """
    Определяет тип периода (четверть/полугодие/учебный год), номер и флаг пропуска.

    Возвращает кортеж (period_type, period_number, skip).

    Коды 1..4 — четверти (с автоматическим переключением на полугодия для
    соответствующих предметов). Учебный год на сервере считается из четвертей.
    """
    normalized_period = normalize_period_code(period_code)
    if normalized_period is None:
        return "quarter", 1, True

    is_sem = is_semester_subject(batch_subdir)

    if is_sem:
        if normalized_period in ("1", "2"):
            return "semester", 1, False
        if normalized_period in ("3", "4"):
            return "semester", 2, False

    return "quarter", int(normalized_period), False


def has_grade_summary_columns(batch_subdir: Path) -> bool:
    """Колонки «Сумма%» и «Оценка» в критериях (предмет без СОЧ, но с итоговой оценкой)."""
    ctx_file = batch_subdir / "criteria_context.json"
    if not ctx_file.exists():
        return False
    try:
        with open(ctx_file, "r", encoding="utf-8") as f:
            ctx = json.load(f)
        if isinstance(ctx, dict) and "has_grade_summary_columns" in ctx:
            return bool(ctx["has_grade_summary_columns"])
    except Exception:
        pass
    return False


def can_upload_period_grades(has_soch_section: bool, batch_subdir: Path) -> bool:
    """Можно загружать оценки на сервер: есть СОЧ или колонки итога без СОЧ."""
    return has_soch_section or has_grade_summary_columns(batch_subdir)


def normalize_period_code(period_code: Any) -> Optional[str]:
    """Normalize period code to one of '1'..'4'."""
    if period_code is None:
        return None
    value = str(period_code).strip()
    return value if value in {"1", "2", "3", "4"} else None
