"""Тесты членства учителя в нескольких школах."""

import pytest

from webapp import create_app
from webapp.config import TestingConfig
from webapp.extensions import db
from webapp.models import Role, School, User
from webapp.services.teacher_schools import (
    ensure_membership,
    find_teacher_by_iin,
    iin_taken_in_school,
    org_names_match,
    teacher_can_report_for_org,
    teacher_in_school,
    teachers_for_school,
)


@pytest.fixture
def app():
    application = create_app(TestingConfig)
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


def _make_school(name: str) -> School:
    s = School(name=name, is_active=True)
    db.session.add(s)
    db.session.flush()
    return s


def _make_teacher(username: str, iin: str, school: School) -> User:
    u = User(
        username=username,
        full_name=username,
        iin=iin,
        role=Role.TEACHER.value,
        school_id=school.id,
        is_active=True,
    )
    u.set_password("secret")
    db.session.add(u)
    db.session.flush()
    ensure_membership(u, school.id)
    db.session.commit()
    return u


def test_add_existing_teacher_to_second_school(app):
    with app.app_context():
        school_a = _make_school("Школа А")
        school_b = _make_school("Школа Б")
        teacher = _make_teacher("ivanov", "850101300123", school_a)

        assert teacher_in_school(teacher.id, school_a.id)
        assert not teacher_in_school(teacher.id, school_b.id)

        ensure_membership(teacher, school_b.id)
        db.session.commit()

        assert teacher_in_school(teacher.id, school_b.id)
        assert find_teacher_by_iin("850101300123").id == teacher.id
        assert len(teachers_for_school(school_b.id)) == 1
        assert iin_taken_in_school(school_b.id, "850101300123")


def test_teacher_can_report_for_member_schools(app):
    with app.app_context():
        school_a = _make_school("IT лицей №1")
        school_b = _make_school("СШ №2")
        teacher = _make_teacher("petrov", "850101300124", school_a)
        ensure_membership(teacher, school_b.id)
        db.session.commit()

        assert teacher_can_report_for_org(teacher.id, "IT лицей №1")
        assert teacher_can_report_for_org(teacher.id, "СШ №2")
        assert not teacher_can_report_for_org(teacher.id, "Чужая школа")


def test_org_names_match_partial():
    assert org_names_match("IT лицей", "Специализированный IT лицей")
    assert not org_names_match("Школа 1", "Школа 2")
