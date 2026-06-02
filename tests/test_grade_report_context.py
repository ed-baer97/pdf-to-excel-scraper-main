"""Tests for SchoolPeriodContext payload/analytics caching."""

from __future__ import annotations

import json

import pytest

from webapp import create_app
from webapp.config import TestingConfig
from webapp.extensions import db
from webapp.models import Class, GradeReport, Role, School, User
from webapp.services.grade_reports.context import load_school_period_context


@pytest.fixture
def app():
    application = create_app(TestingConfig)
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture
def ctx_setup(app):
    with app.app_context():
        school = School(name="Ctx School")
        db.session.add(school)
        db.session.flush()
        teacher = User(
            username="ctx_teacher",
            full_name="Ctx Teacher",
            role=Role.TEACHER.value,
            school_id=school.id,
        )
        teacher.set_password("pass")
        db.session.add(teacher)
        db.session.flush()
        db.session.add(Class(school_id=school.id, name="5А"))
        report = GradeReport(
            teacher_id=teacher.id,
            school_id=school.id,
            class_name="5А",
            subject_name="Математика",
            period_type="quarter",
            period_number=2,
            grades_json=json.dumps(
                {"students": [{"name": "A", "grade": 5}]}, ensure_ascii=False
            ),
            analytics_json=json.dumps(
                {"sor": [], "soch": {}}, ensure_ascii=False
            ),
        )
        db.session.add(report)
        db.session.commit()
        yield {"school_id": school.id, "report": report}


def test_payload_cache_single_parse(app, ctx_setup):
    with app.app_context():
        ctx = load_school_period_context(ctx_setup["school_id"], 2)
        report = ctx_setup["report"]
        p1 = ctx.payload(report)
        p2 = ctx.payload(report)
        assert p1 is p2
        assert p1["students"][0]["name"] == "A"


def test_analytics_payload_cache(app, ctx_setup):
    with app.app_context():
        ctx = load_school_period_context(ctx_setup["school_id"], 2)
        report = ctx_setup["report"]
        a1 = ctx.analytics_payload(report)
        a2 = ctx.analytics_payload(report)
        assert a1 is a2


def test_filter_active_includes_registered_class(app, ctx_setup):
    with app.app_context():
        ctx = load_school_period_context(ctx_setup["school_id"], 2)
        active = ctx.filter_active()
        assert len(active) == 1
        assert active[0].class_name == "5А"
