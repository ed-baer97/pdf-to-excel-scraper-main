"""Школьный итоговый отчёт в Excel.

Пакет разбит по ответственности:
- data.py — выборка и агрегация данных из БД (без openpyxl);
- styles.py — стили ячеек, хелперы записи строк и оформления диаграмм;
- dynamics_sheet.py, quality_sheet.py, summary_sheets.py, manual_sheets.py —
  рендеринг листов (по модулю на группу листов);
- workbook.py — оркестратор build_final_report_workbook().
"""

from .workbook import build_final_report_workbook

__all__ = ["build_final_report_workbook"]
