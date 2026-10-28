"""Тесты исправлений безопасности, каскадного удаления, мульти-школьности и единого AI-сервиса."""

from __future__ import annotations

import pytest

from webapp import create_app
from webapp.config import TestingConfig
from webapp.constants import DESKTOP_VERSION
from webapp.extensions import db
from webapp.models import (
    Class,
    ClassTeacherYear,
    ExportJob,
    FinalReportData,
    GradeReport,
    ReportFile,
    Role,
    School,
    ScrapeJob,
    Subject,
    SubjectNameAlias,
    TeacherClass,
    TeacherSchool,
    TeacherSubject,
    User,
)
from webapp.services.ai_analysis import (
    generate_fallback_analysis_dict,
    parse_ai_json_response,
)
from webapp.services.class_homeroom import assign_class_teacher
from webapp.services.teacher_schools import ensure_membership


@pytest.fixture
def app():
    application = create_app(TestingConfig)
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()
        db.engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


def test_login_does_not_expose_raw_ai_api_key(app, client):
    with app.app_context():
        school = School(
            name="Школа AI",
            is_active=True,
            ai_api_key="sk-secret-key-do-not-expose",
            ai_model="qwen-plus",
        )
        db.session.add(school)
        db.session.flush()
        user = User(
            username="teacher_ai",
            full_name="Учитель ИИ",
            role=Role.TEACHER.value,
            school_id=school.id,
            is_active=True,
        )
        user.set_password("secret123")
        db.session.add(user)
        db.session.commit()

    resp = client.post(
        "/api/auth/login",
        json={"username": "teacher_ai", "password": "secret123"},
        headers={"X-Desktop-Version": DESKTOP_VERSION},
    )
    assert resp.status_code == 200
    user_payload = resp.get_json()["user"]
    assert "ai_api_key" not in user_payload
    assert user_payload["ai_enabled"] is True
    assert user_payload["ai_model"] == "qwen-plus"


def test_api_teacher_goals_generate_bilingual_fallback(app, client):
    with app.app_context():
        school = School(name="Школа КЗ", is_active=True)
        db.session.add(school)
        db.session.flush()
        user = User(
            username="teacher_kz",
            full_name="Мұғалім",
            role=Role.TEACHER.value,
            school_id=school.id,
            is_active=True,
        )
        user.set_password("secret123")
        db.session.add(user)
        db.session.commit()

    login = client.post(
        "/api/auth/login",
        json={"username": "teacher_kz", "password": "secret123"},
        headers={"X-Desktop-Version": DESKTOP_VERSION},
    )
    token = login.get_json()["token"]

    resp = client.post(
        "/api/teacher/goals/generate",
        json={
            "achieved": "Теңдеулерді шешу",
            "difficulties": "Бөлшектермен есептер шығару",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "Оқушылар" in data["difficulties_list"]


def test_api_reports_my_invalid_period_number_returns_400(app, client):
    with app.app_context():
        school = School(name="Школа Тест", is_active=True)
        db.session.add(school)
        db.session.flush()
        user = User(
            username="teacher_p",
            full_name="Учитель П",
            role=Role.TEACHER.value,
            school_id=school.id,
            is_active=True,
        )
        user.set_password("secret123")
        db.session.add(user)
        db.session.commit()

    login = client.post(
        "/api/auth/login",
        json={"username": "teacher_p", "password": "secret123"},
        headers={"X-Desktop-Version": DESKTOP_VERSION},
    )
    token = login.get_json()["token"]

    resp = client.get(
        "/api/reports/my?period_number=invalid",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


def test_delete_class_removes_class_teacher_year_and_teacher_class(app, client):
    with app.app_context():
        school = School(name="Школа Классов", is_active=True)
        db.session.add(school)
        db.session.flush()

        admin = User(
            username="school_admin_1",
            full_name="Админ",
            role=Role.SCHOOL_ADMIN.value,
            school_id=school.id,
            is_active=True,
        )
        admin.set_password("adminpass")
        teacher = User(
            username="teacher_cls",
            full_name="Учитель Кл",
            role=Role.TEACHER.value,
            school_id=school.id,
            iin="850101300111",
            is_active=True,
        )
        teacher.set_password("tpass")
        db.session.add_all([admin, teacher])
        db.session.flush()
        ensure_membership(teacher, school.id)

        cls = Class(name="9А", school_id=school.id)
        db.session.add(cls)
        db.session.flush()
        assign_class_teacher(cls, teacher.id, 2025)

        subj = Subject(name="Алгебра", school_id=school.id)
        db.session.add(subj)
        db.session.flush()
        ts = TeacherSubject(teacher_id=teacher.id, subject_id=subj.id)
        db.session.add(ts)
        db.session.flush()
        tc = TeacherClass(teacher_subject_id=ts.id, class_id=cls.id)
        db.session.add(tc)
        db.session.commit()
        class_id = cls.id
        admin_id = admin.id

    with client.session_transaction() as sess:
        sess["_user_id"] = str(admin_id)
        sess["_fresh"] = True

    resp = client.post(f"/admin/classes/{class_id}/delete")
    assert resp.status_code == 302

    with app.app_context():
        assert db.session.get(Class, class_id) is None
        assert ClassTeacherYear.query.filter_by(class_id=class_id).count() == 0
        assert TeacherClass.query.filter_by(class_id=class_id).count() == 0


def test_delete_school_cleans_all_related_tables_and_preserves_multischool_teacher(app, client):
    with app.app_context():
        s1 = School(name="Удаляемая Школа", is_active=True)
        s2 = School(name="Вторая Школа", is_active=True)
        db.session.add_all([s1, s2])
        db.session.flush()

        superadmin = User.query.filter_by(role=Role.SUPERADMIN.value).first()
        single_teacher = User(
            username="single_t",
            full_name="Учитель Одной Школы",
            role=Role.TEACHER.value,
            school_id=s1.id,
            iin="850101300222",
            is_active=True,
        )
        single_teacher.set_password("pass")
        multi_teacher = User(
            username="multi_t",
            full_name="Учитель Двух Школ",
            role=Role.TEACHER.value,
            school_id=s1.id,
            iin="850101300333",
            is_active=True,
        )
        multi_teacher.set_password("pass")
        db.session.add_all([single_teacher, multi_teacher])
        db.session.flush()

        ensure_membership(single_teacher, s1.id)
        ensure_membership(multi_teacher, s1.id)
        ensure_membership(multi_teacher, s2.id)

        cls = Class(name="10А", school_id=s1.id)
        db.session.add(cls)
        db.session.flush()
        assign_class_teacher(cls, single_teacher.id, 2025)

        db.session.add(SubjectNameAlias(school_id=s1.id, alias_name="Матем", canonical_name="Математика"))
        db.session.add(FinalReportData(school_id=s1.id, academic_year=2025, section="ent", data_json="{}"))
        db.session.add(ExportJob(school_id=s1.id, user_id=single_teacher.id, export_kind="analytics"))
        db.session.add(ScrapeJob(school_id=s1.id, teacher_id=single_teacher.id, period_code="2"))
        db.session.add(
            GradeReport(
                school_id=s1.id,
                teacher_id=single_teacher.id,
                class_name="10А",
                subject_name="Математика",
                period_type="quarter",
                period_number=1,
                academic_year=2025,
            )
        )
        db.session.add(
            ReportFile(
                school_id=s1.id,
                teacher_id=single_teacher.id,
                period_code="1",
                academic_year=2025,
                class_name="10А",
                subject="Математика",
            )
        )
        db.session.commit()

        s1_id = s1.id
        s2_id = s2.id
        single_id = single_teacher.id
        multi_id = multi_teacher.id
        sa_id = superadmin.id

    with client.session_transaction() as sess:
        sess["_user_id"] = str(sa_id)
        sess["_fresh"] = True

    resp = client.post(f"/superadmin/schools/{s1_id}/delete")
    assert resp.status_code == 302

    with app.app_context():
        assert db.session.get(School, s1_id) is None
        assert db.session.get(User, single_id) is None
        preserved = db.session.get(User, multi_id)
        assert preserved is not None
        assert preserved.school_id == s2_id
        assert TeacherSchool.query.filter_by(school_id=s1_id).count() == 0


def test_parse_ai_json_and_fallback_helpers():
    parsed = parse_ai_json_response('Ответ: {"difficulties_list": "A", "reasons": "B", "correction": "C"}')
    assert parsed == {"difficulties_list": "A", "reasons": "B", "correction": "C"}

    ru_fb = generate_fallback_analysis_dict("Дроби", "Линейные уравнения")
    assert ru_fb["fallback"] is True
    assert "Обучающиеся" in ru_fb["difficulties_list"]


def test_upload_report_invalid_period_number_returns_400(app, client):
    with app.app_context():
        school = School(name="Школа Загрузки", is_active=True)
        db.session.add(school)
        db.session.flush()
        user = User(
            username="teacher_up",
            full_name="Учитель",
            role=Role.TEACHER.value,
            school_id=school.id,
            is_active=True,
        )
        user.set_password("secret123")
        db.session.add(user)
        db.session.commit()

    login = client.post(
        "/api/auth/login",
        json={"username": "teacher_up", "password": "secret123"},
        headers={"X-Desktop-Version": DESKTOP_VERSION},
    )
    token = login.get_json()["token"]

    resp = client.post(
        "/api/reports/upload",
        json={
            "class_name": "9А",
            "subject_name": "Математика",
            "period_type": "quarter",
            "period_number": "not_a_number",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400
    assert "period_number" in resp.get_json()["error"]


def test_log_report_metadata_upserts_without_duplicates(app, client):
    with app.app_context():
        school = School(name="Школа Лога", is_active=True)
        db.session.add(school)
        db.session.flush()
        user = User(
            username="teacher_log",
            full_name="Учитель",
            role=Role.TEACHER.value,
            school_id=school.id,
            is_active=True,
        )
        user.set_password("secret123")
        db.session.add(user)
        db.session.commit()
        school_id = school.id

    login = client.post(
        "/api/auth/login",
        json={"username": "teacher_log", "password": "secret123"},
        headers={"X-Desktop-Version": DESKTOP_VERSION},
    )
    token = login.get_json()["token"]

    payload = {
        "reports": [
            {
                "class": "9А",
                "subject": "Математика",
                "period": "2",
                "timestamp": "2026-01-15T10:30:00",
            }
        ]
    }
    resp1 = client.post(
        "/api/reports/log",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    resp2 = client.post(
        "/api/reports/log",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp1.status_code == 200
    assert resp2.status_code == 200

    with app.app_context():
        assert ReportFile.query.filter_by(school_id=school_id, class_name="9А").count() == 1


def test_delete_subject_and_student_preserve_archive_academic_years(app, client):
    import json
    from webapp.services.academic_year import current_academic_year
    from webapp.services.grade_reports.student_edits import delete_student_from_class_reports

    cur_year = current_academic_year()
    archive_year = cur_year - 1

    with app.app_context():
        school = School(name="Школа Архива", is_active=True)
        db.session.add(school)
        db.session.flush()

        admin = User(
            username="admin_arch",
            full_name="Админ",
            role=Role.SCHOOL_ADMIN.value,
            school_id=school.id,
            is_active=True,
        )
        admin.set_password("pass")
        teacher = User(
            username="teacher_arch",
            full_name="Учитель",
            role=Role.TEACHER.value,
            school_id=school.id,
            is_active=True,
        )
        teacher.set_password("pass")
        db.session.add_all([admin, teacher])
        db.session.flush()

        grades_json = json.dumps(
            {
                "students": [
                    {"name": "Иванов Иван", "grade": 5},
                    {"name": "Петров Пётр", "grade": 4},
                ],
                "total_students": 2,
                "quality_percent": 100.0,
                "success_percent": 100.0,
            },
            ensure_ascii=False,
        )

        for year in (cur_year, archive_year):
            for subj in ("Физика", "Химия"):
                db.session.add(
                    GradeReport(
                        school_id=school.id,
                        teacher_id=teacher.id,
                        class_name="8А",
                        subject_name=subj,
                        period_type="quarter",
                        period_number=2,
                        academic_year=year,
                        grades_json=grades_json,
                    )
                )
        db.session.commit()

        updated = delete_student_from_class_reports(
            school.id, "8А", "Иванов Иван", 2, academic_year=cur_year
        )
        assert updated == 2

        arch_chem = GradeReport.query.filter_by(
            school_id=school.id,
            class_name="8А",
            subject_name="Химия",
            academic_year=archive_year,
        ).first()
        assert len(json.loads(arch_chem.grades_json)["students"]) == 2

        admin_id = admin.id
        school_id = school.id

    with client.session_transaction() as sess:
        sess["_user_id"] = str(admin_id)
        sess["_fresh"] = True

    resp = client.post(
        "/admin/grades/class/8А/subjects/delete",
        data={"subject_name": "Физика", "period_number": "2"},
    )
    assert resp.status_code == 302

    with app.app_context():
        assert (
            GradeReport.query.filter_by(
                school_id=school_id,
                class_name="8А",
                subject_name="Физика",
                academic_year=cur_year,
            ).count()
            == 0
        )
        assert (
            GradeReport.query.filter_by(
                school_id=school_id,
                class_name="8А",
                subject_name="Физика",
                academic_year=archive_year,
            ).count()
            == 1
        )

