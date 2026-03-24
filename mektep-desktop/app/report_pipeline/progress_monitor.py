"""Чтение progress.json и разбор сообщения выбора школы."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHOOLS_PREFIX = "schools_selection_needed|"


def read_progress_data(progress_file: Path) -> Optional[Dict[str, Any]]:
    """Читает JSON прогресса скрапера из файла; при ошибке или отсутствии файла возвращает None."""
    if not progress_file.exists():
        return None
    try:
        with open(progress_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def parse_schools_from_progress_message(message: str) -> Optional[List[Any]]:
    """Если сообщение — запрос выбора школы, вернуть список школ; иначе None."""
    if not message.startswith(SCHOOLS_PREFIX):
        return None
    try:
        schools_json = message.split("|", 1)[1]
        return json.loads(schools_json)
    except Exception:
        return None


def format_progress_line(
    message: str, total_reports: Optional[int], processed_reports: int
) -> str:
    """Формирует строку прогресса с счётчиком (обработано/всего), если total_reports задан."""
    if total_reports:
        return f"{message} ({processed_reports}/{total_reports})"
    return message
