"""Автоперевод классного руководителя на следующую параллель в новом учебном году."""

from __future__ import annotations

import pytest

from webapp import create_app
from webapp.config import TestingConfig
from webapp.extensions import db
from webapp.models import Class, GradeReport, Role, School, User
from webapp.services.academic_year import current_academic_year
from webapp.services.class_homeroom import (
    assign_class_teacher,
    class_teacher_user,
    managed_classes,
    prepare_class_teachers,
    shift_class_name,
)


def test_shift_class_name_keeps_letter_and_stops_after_11():
    assert shift_class_name("5Е", 1) == "6Е"
    assert shift_class_name("5е", 1) == "6е"
    assert shift_class_name("10Б", 1) == "11Б"
    assert shift_class_name("11А", 1) is None
    assert shift_class_name("1А", -1) is None
    assert shift_class_name("класс", 1) is None


@pytest.fixture
def app():
    application = create_app(TestingConfig)
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


def _school_with_teacher(name: str):
    school = School(name=name, is_active=True)
    db.session.add(school)
    db.session.flush()
    teacher = User(
        username=f"ct-{school.id}",
        full_name="Классный Пятого",
        role=Role.TEACHER.value,
        school_id=school.id,
        is_active=True,
    )
    teacher.set_password("secret123")
    db.session.add(teacher)
    db.session.flush()
    return school, teacher


def test_previous_year_teacher_moves_to_next_grade(app):
    with app.app_context():
        current = current_academic_year()
        previous = current - 1
        school, teacher = _school_with_teacher("Лицей перевода")
        db.session.add(Class(school_id=school.id, name="5Е", class_teacher_id=teacher.id))
        db.session.add(
            GradeReport(
                teacher_id=teacher.id,
                school_id=school.id,
                class_name="5Е",
                subject_name="Математика",
                period_type="quarter",
                period_number=1,
                academic_year=previous,
                grades_json="{}",
            )
        )
        db.session.commit()

        index = prepare_class_teachers(school.id, current)

        assert class_teacher_user(school.id, "5Е", previous).id == teacher.id
        assert class_teacher_user(school.id, "6Е", current).id == teacher.id
        assert class_teacher_user(school.id, "5Е", current) is None
        assert class_teacher_user(school.id, "6е", current).id == teacher.id
        assert index.teacher_id("7Е", current + 1) == teacher.id
        assert Class.query.filter_by(school_id=school.id, name="6Е").first() is not None
        assert [c.name for c in managed_classes(school.id, teacher.id, current)] == ["6Е"]
        assert [c.name for c in managed_classes(school.id, teacher.id, previous)] == ["5Е"]


def test_graduating_class_is_not_promoted(app):
    with app.app_context():
        current = current_academic_year()
        school, teacher = _school_with_teacher("Лицей выпуска")
        db.session.add(Class(school_id=school.id, name="11А", class_teacher_id=teacher.id))
        db.session.add(
            GradeReport(
                teacher_id=teacher.id,
                school_id=school.id,
                class_name="11А",
                subject_name="Математика",
                period_type="quarter",
                period_number=1,
                academic_year=current - 1,
                grades_json="{}",
            )
        )
        db.session.commit()

        prepare_class_teachers(school.id, current)

        assert Class.query.filter_by(school_id=school.id, name="12А").first() is None
        assert class_teacher_user(school.id, "11А", current - 1).id == teacher.id
        assert managed_classes(school.id, teacher.id, current) == []


def test_explicit_assignment_overrides_promotion(app):
    with app.app_context():
        current = current_academic_year()
        school, teacher = _school_with_teacher("Лицей замены")
        other = User(
            username=f"ct-other-{school.id}",
            full_name="Новый Классный",
            role=Role.TEACHER.value,
            school_id=school.id,
            is_active=True,
        )
        other.set_password("secret123")
        db.session.add(other)
        db.session.flush()
        db.session.add(Class(school_id=school.id, name="5Е", class_teacher_id=teacher.id))
        db.session.add(
            GradeReport(
                teacher_id=teacher.id,
                school_id=school.id,
                class_name="5Е",
                subject_name="Математика",
                period_type="quarter",
                period_number=1,
                academic_year=current - 1,
                grades_json="{}",
            )
        )
        db.session.commit()

        prepare_class_teachers(school.id, current)
        promoted = Class.query.filter_by(school_id=school.id, name="6Е").one()
        assign_class_teacher(promoted, other.id, current)
        db.session.commit()

        assert class_teacher_user(school.id, "6Е", current).id == other.id
        assert class_teacher_user(school.id, "5Е", current - 1).id == teacher.id


def test_same_year_assignment_is_not_shifted_without_archive(app):
    with app.app_context():
        current = current_academic_year()
        school, teacher = _school_with_teacher("Лицей без архива")
        db.session.add(Class(school_id=school.id, name="5Е", class_teacher_id=teacher.id))
        db.session.commit()

        prepare_class_teachers(school.id, current)

        assert class_teacher_user(school.id, "5Е", current).id == teacher.id
        assert Class.query.filter_by(school_id=school.id, name="6Е").first() is None
