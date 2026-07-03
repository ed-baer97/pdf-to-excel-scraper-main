"""Тесты Desktop API: авторизация и защищённые эндпоинты."""

import pytest

from webapp import create_app
from webapp.config import TestingConfig
from webapp.constants import DESKTOP_VERSION
from webapp.extensions import db
from webapp.models import Role, School, User


@pytest.fixture
def app():
    application = create_app(TestingConfig)
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def _make_teacher(username: str = "teacher1") -> User:
    school = School(name="Тестовая школа", is_active=True)
    db.session.add(school)
    db.session.flush()
    user = User(
        username=username,
        full_name="Учитель Т.",
        role=Role.TEACHER.value,
        school_id=school.id,
        is_active=True,
    )
    user.set_password("secret123")
    db.session.add(user)
    db.session.commit()
    return user


class TestApiAuth:
    def test_login_success(self, app, client):
        with app.app_context():
            _make_teacher()
        resp = client.post(
            "/api/auth/login",
            json={"username": "teacher1", "password": "secret123"},
            headers={"X-Desktop-Version": DESKTOP_VERSION},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["token"]
        assert data["user"]["username"] == "teacher1"

    def test_login_wrong_password(self, app, client):
        with app.app_context():
            _make_teacher()
        resp = client.post(
            "/api/auth/login",
            json={"username": "teacher1", "password": "wrong"},
            headers={"X-Desktop-Version": DESKTOP_VERSION},
        )
        assert resp.status_code == 401

    def test_login_outdated_desktop_version(self, app, client):
        with app.app_context():
            _make_teacher()
        resp = client.post(
            "/api/auth/login",
            json={"username": "teacher1", "password": "secret123"},
            headers={"X-Desktop-Version": "0.1.0"},
        )
        assert resp.status_code == 426
        assert resp.get_json().get("update_required") is True

    def test_protected_endpoint_requires_token(self, client):
        resp = client.post("/api/reports/log", json={"reports": []})
        assert resp.status_code == 401


class TestApiReportUpload:
    def test_upload_validation_error_without_grades(self, app, client):
        with app.app_context():
            user = _make_teacher("uploader")
            login = client.post(
                "/api/auth/login",
                json={"username": "uploader", "password": "secret123"},
                headers={"X-Desktop-Version": DESKTOP_VERSION},
            )
            token = login.get_json()["token"]

        resp = client.post(
            "/api/reports/upload",
            json={"class_name": "7А", "subject_name": "Математика"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400

    def test_upload_year_period_rejected(self, app, client):
        with app.app_context():
            _make_teacher("year_user")
            login = client.post(
                "/api/auth/login",
                json={"username": "year_user", "password": "secret123"},
                headers={"X-Desktop-Version": DESKTOP_VERSION},
            )
            token = login.get_json()["token"]

        resp = client.post(
            "/api/reports/upload",
            json={
                "class_name": "7А",
                "subject_name": "Математика",
                "period_type": "year",
                "period_number": 5,
                "grades_json": {"students": [{"name": "Алиев А.", "grade": 5}]},
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400
        assert "автоматически" in resp.get_json().get("error", "").lower()
