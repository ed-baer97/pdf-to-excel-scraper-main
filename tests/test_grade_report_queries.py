"""Tests for webapp.services.grade_reports.queries."""

from __future__ import annotations

import json

import pytest

from webapp import create_app
from webapp.config import TestingConfig
from webapp.extensions import db
from webapp.models import GradeReport, Role, School, User
from webapp.services.grade_reports.queries import get_period_reports, get_quarter_reports
from webapp.services.year_grades import YEAR_UI_PERIOD


@pytest.fixture
def app():
    application = create_app(TestingConfig)
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


def _add_report(
    *,
    school_id: int,
    teacher_id: int,
    class_name: str,
    subject_name: str,
    period_type: str,
    period_number: int,
) -> GradeReport:
    report = GradeReport(
        teacher_id=teacher_id,
        school_id=school_id,
        class_name=class_name,
        subject_name=subject_name,
        period_type=period_type,
        period_number=period_number,
        grades_json=json.dumps(
            {"students": [{"name": "A", "grade": 5}], "total_students": 1},
            ensure_ascii=False,
        ),
    )
    db.session.add(report)
    db.session.commit()
    return report


@pytest.fixture
def school_ctx(app):
    with app.app_context():
        school = School(name="Query Test School")
        db.session.add(school)
        db.session.flush()
        teacher = User(
            username="query_teacher",
            full_name="Query Teacher",
            role=Role.TEACHER.value,
            school_id=school.id,
        )
        teacher.set_password("pass")
        db.session.add(teacher)
        db.session.commit()
        yield {"school_id": school.id, "teacher_id": teacher.id}


def test_quarter_2_includes_semester_one(app, school_ctx):
    sid = school_ctx["school_id"]
    tid = school_ctx["teacher_id"]
    with app.app_context():
        _add_report(
            school_id=sid,
            teacher_id=tid,
            class_name="7А",
            subject_name="Математика",
            period_type="quarter",
            period_number=2,
        )
        _add_report(
            school_id=sid,
            teacher_id=tid,
            class_name="7А",
            subject_name="Физика",
            period_type="semester",
            period_number=1,
        )

        reports = get_quarter_reports(sid, 2)
        keys = {(r.period_type, r.period_number, r.subject_name) for r in reports}

        assert ("quarter", 2, "Математика") in keys
        assert ("semester", 1, "Физика") in keys


def test_quarter_1_excludes_semester_subject_duplicate(app, school_ctx):
    sid = school_ctx["school_id"]
    tid = school_ctx["teacher_id"]
    with app.app_context():
        _add_report(
            school_id=sid,
            teacher_id=tid,
            class_name="8Б",
            subject_name="История",
            period_type="semester",
            period_number=1,
        )
        _add_report(
            school_id=sid,
            teacher_id=tid,
            class_name="8Б",
            subject_name="История",
            period_type="quarter",
            period_number=1,
        )
        _add_report(
            school_id=sid,
            teacher_id=tid,
            class_name="8Б",
            subject_name="География",
            period_type="quarter",
            period_number=1,
        )

        reports = get_quarter_reports(sid, 1)
        subjects = {r.subject_name for r in reports}

        assert "География" in subjects
        assert "История" not in subjects


def test_get_period_reports_year_smoke(app, school_ctx):
    sid = school_ctx["school_id"]
    tid = school_ctx["teacher_id"]
    with app.app_context():
        _add_report(
            school_id=sid,
            teacher_id=tid,
            class_name="5А",
            subject_name="Математика",
            period_type="quarter",
            period_number=1,
        )

        result = get_period_reports(sid, YEAR_UI_PERIOD)

        assert isinstance(result, list)


def test_api_aliases_match_central_queries(app, school_ctx):
    from webapp.services.api_helpers import (
        get_period_reports_api,
        get_quarter_reports_api,
    )

    sid = school_ctx["school_id"]
    tid = school_ctx["teacher_id"]
    with app.app_context():
        _add_report(
            school_id=sid,
            teacher_id=tid,
            class_name="6В",
            subject_name="Биология",
            period_type="quarter",
            period_number=3,
        )

        central = get_quarter_reports(sid, 3)
        via_api = get_quarter_reports_api(sid, 3)

        assert {r.id for r in central} == {r.id for r in via_api}
        assert get_period_reports is get_period_reports_api
        assert get_quarter_reports is get_quarter_reports_api
