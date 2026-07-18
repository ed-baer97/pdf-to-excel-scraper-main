"""Листы ручного ввода итогового отчёта."""

from __future__ import annotations

from typing import Callable

from openpyxl import Workbook
from openpyxl.styles import Font

from .styles import write_data_row, write_header_row


def write_awards_sheet(wb: Workbook, awards: dict, tr: Callable[[str], str]) -> None:
    """Аттестаты: счётчики «Алтын белгі»/с отличием и список учеников."""
    ws_aw = wb.create_sheet(title=tr("final_report_sheet_awards")[:31])
    ws_aw.cell(row=1, column=1, value=tr("final_report_sheet_awards")).font = Font(bold=True, size=14)
    write_header_row(
        ws_aw,
        3,
        [
            tr("final_report_awards_altyn"),
            tr("final_report_awards_excellent_11"),
            tr("final_report_awards_excellent_9"),
        ],
    )
    write_data_row(
        ws_aw,
        4,
        [
            awards.get("altyn_belgi", 0),
            awards.get("excellent_11", 0),
            awards.get("excellent_9", 0),
        ],
    )
    students_aw = awards.get("students") or []
    if students_aw:
        write_header_row(ws_aw, 6, [tr("final_report_col_student_name"), tr("final_report_col_award_type")])
        ar = 7
        for st in students_aw:
            if isinstance(st, dict):
                write_data_row(ws_aw, ar, [st.get("name", ""), st.get("award", "")])
            else:
                write_data_row(ws_aw, ar, [str(st), ""])
            ar += 1
