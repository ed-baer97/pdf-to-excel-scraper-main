"""Папка учебного года в Mektep Reports."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mektep-desktop"))

from app.academic_year import academic_year_folder, format_academic_year, reports_period_dir
from app.reports_manager import ReportsManager


def test_year_folder_wraps_quarter_and_year_period():
    root = Path("C:/Users/teacher/Documents/Mektep Reports")
    quarter = reports_period_dir(root, "Иванов И.И.", "1 четверть", 2025)
    year_period = reports_period_dir(root, "Иванов И.И.", "Учебный год", 2025)

    assert academic_year_folder(2025) == "2025-2026"
    assert format_academic_year(2025) == "2025–2026"
    assert quarter == root / "Иванов И.И." / "2025-2026" / "1 четверть"
    assert year_period == root / "Иванов И.И." / "2025-2026" / "Учебный год"
    assert quarter.parent == year_period.parent


def test_local_reports_keep_same_quarter_in_two_years(tmp_path):
    db = tmp_path / "storage"
    db.mkdir()
    conn = sqlite3.connect(db / "reports.db")
    conn.execute(
        """
        CREATE TABLE reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL DEFAULT '',
            class_name TEXT NOT NULL,
            subject TEXT NOT NULL,
            period_code TEXT NOT NULL,
            lang TEXT DEFAULT 'ru',
            excel_path TEXT,
            word_path TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            synced_to_server BOOLEAN DEFAULT 0,
            metadata TEXT,
            UNIQUE(username, class_name, subject, period_code)
        )
        """
    )
    conn.execute(
        """
        INSERT INTO reports (username, class_name, subject, period_code, excel_path)
        VALUES ('teacher', '5Е', 'Математика', '1', 'old.xlsx')
        """
    )
    conn.commit()
    conn.close()

    manager = ReportsManager(db, username="teacher")
    new_id = manager.save_report(
        {
            "class_name": "5Е",
            "subject": "Математика",
            "period_code": "1",
            "academic_year": 2024,
            "excel_path": "new.xlsx",
        }
    )
    saved = manager.get_reports({"academic_year": 2024})
    previous = manager.get_reports()

    assert new_id
    assert len(saved) == 1
    assert saved[0]["excel_path"] == "new.xlsx"
    assert any(row["excel_path"] == "old.xlsx" for row in previous)
    assert saved[0]["id"] != next(row["id"] for row in previous if row["excel_path"] == "old.xlsx")
