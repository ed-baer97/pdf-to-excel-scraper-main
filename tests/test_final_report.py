"""Smoke tests for final school report Excel builder."""

from __future__ import annotations

import json

import pytest
from openpyxl import load_workbook

from webapp import create_app
from webapp.config import TestingConfig
from webapp.extensions import db
from webapp.models import Class, FinalReportData, GradeReport, Role, School, User
from webapp.services.grade_reports.final_report import build_final_report_workbook
from webapp.services.grade_reports.final_report_data import save_section_data
from webapp.translator import gettext


@pytest.fixture
def app():
    application = create_app(TestingConfig)
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


def _seed_school(app) -> dict:
    with app.app_context():
        school = School(name="Final Report School")
        db.session.add(school)
        db.session.flush()
        teacher = User(
            username="final_teacher",
            full_name="Final Teacher",
            role=Role.TEACHER.value,
            school_id=school.id,
        )
        teacher.set_password("pass")
        db.session.add(teacher)
        db.session.flush()
        db.session.add(Class(school_id=school.id, name="5А"))
        grades = {
            "students": [
                {"name": "Алиев А.", "grade": 5, "percent": 100},
                {"name": "Беков Б.", "grade": 4, "percent": 85},
            ],
            "total_students": 2,
            "quality_percent": 100.0,
            "success_percent": 100.0,
        }
        db.session.add(
            GradeReport(
                teacher_id=teacher.id,
                school_id=school.id,
                class_name="5А",
                subject_name="Математика",
                period_type="quarter",
                period_number=1,
                academic_year=2025,
                grades_json=json.dumps(grades, ensure_ascii=False),
            )
        )
        db.session.add(
            GradeReport(
                teacher_id=teacher.id,
                school_id=school.id,
                class_name="5А",
                subject_name="Математика",
                period_type="quarter",
                period_number=2,
                academic_year=2025,
                grades_json=json.dumps(grades, ensure_ascii=False),
            )
        )
        db.session.commit()
        save_section_data(
            school.id,
            2025,
            "ent",
            {
                "periods": [
                    {"month": "Январь", "count": 10, "avg_score": 80.0, "max_score": 120},
                    {"month": "Май", "count": 10, "avg_score": 93.0, "max_score": 130},
                ],
                "quality_levels": [],
                "class_slices": [],
                "forecast_avg": 96.7,
                "recommendations": "Test",
            },
        )
        return {"school_id": school.id}


def test_build_final_report_workbook_smoke(app):
    ctx = _seed_school(app)
    with app.app_context():
        buf, filename = build_final_report_workbook(
            ctx["school_id"],
            academic_year=2025,
            years_back=1,
            tr=lambda k: gettext(k, "ru"),
        )
        assert filename.endswith(".xlsx")
        wb = load_workbook(buf)
        sheet_names = wb.sheetnames
        assert any("Сводка" in n for n in sheet_names)
        assert any("Численность" in n for n in sheet_names)
        assert any("ЕНТ" in n for n in sheet_names)
        wb.close()


def test_final_report_data_roundtrip(app):
    ctx = _seed_school(app)
    with app.app_context():
        row = FinalReportData.query.filter_by(
            school_id=ctx["school_id"], section="ent"
        ).first()
        assert row is not None
        data = json.loads(row.data_json)
        assert data.get("forecast_avg") == 96.7
