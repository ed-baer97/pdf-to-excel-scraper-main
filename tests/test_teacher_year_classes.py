"""Список классов кабинета учителя ограничен отчётами выбранного года."""

from __future__ import annotations

import pytest

from webapp import create_app
from webapp.config import TestingConfig
from webapp.extensions import db
from webapp.models import Class, GradeReport, Role, School, User
from webapp.services.academic_year import current_academic_year
from webapp.services.class_homeroom import assign_class_teacher
from webapp.services.teacher_cabinet import teacher_subjects_overview


@pytest.fixture
def app():
    application = create_app(TestingConfig)
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


def _teacher(school: School, username: str) -> User:
    user = User(
        username=username,
        full_name=username,
        role=Role.TEACHER.value,
        school_id=school.id,
        is_active=True,
    )
    user.set_password("secret")
    db.session.add(user)
    db.session.flush()
    return user


def _report(teacher: User, class_name: str, year: int, subject: str = "История") -> None:
    db.session.add(
        GradeReport(
            teacher_id=teacher.id,
            school_id=teacher.school_id,
            class_name=class_name,
            subject_name=subject,
            period_type="quarter",
            period_number=1,
            academic_year=year,
            grades_json="{}",
        )
    )


def _class_names(overview: dict) -> set[str]:
    names = {name for name in overview["managed_classes"]}
    for subject in overview["subjects"]:
        for cls in subject["classes"]:
            names.add(cls["class_name"])
    return names


def test_new_year_is_empty_until_reports_exist(app):
    with app.app_context():
        year = current_academic_year()
        school = School(name="Лицей", is_active=True)
        db.session.add(school)
        db.session.flush()
        teacher = _teacher(school, "gani")
        _report(teacher, "5В", year - 1)
        _report(teacher, "6В", year)
        db.session.commit()

        assert _class_names(teacher_subjects_overview(teacher, year)) == {"6В"}
        assert _class_names(teacher_subjects_overview(teacher, year - 1)) == {"5В"}
        assert _class_names(teacher_subjects_overview(teacher, year + 1)) == set()


def test_homeroom_class_appears_only_after_a_report(app):
    with app.app_context():
        year = current_academic_year()
        school = School(name="Лицей 2", is_active=True)
        db.session.add(school)
        db.session.flush()
        homeroom = _teacher(school, "homeroom")
        colleague = _teacher(school, "colleague")
        cls = Class(school_id=school.id, name="6Д", class_teacher_id=homeroom.id)
        db.session.add(cls)
        db.session.flush()
        assign_class_teacher(cls, homeroom.id, year)
        db.session.commit()

        assert _class_names(teacher_subjects_overview(homeroom, year)) == set()

        _report(colleague, "6Д", year, subject="Математика")
        db.session.commit()

        overview = teacher_subjects_overview(homeroom, year)
        assert overview["subjects"] == []
        assert overview["managed_classes"] == ["6Д"]
