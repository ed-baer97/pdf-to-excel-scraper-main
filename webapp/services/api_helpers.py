"""Reusable helpers for API views."""

from __future__ import annotations

from datetime import datetime, timedelta
from functools import wraps

import jwt
from flask import current_app, jsonify, request

from ..constants import normalize_subject_name
from ..extensions import db
from ..models import (
    Class,
    GradeReport,
    School,
    Subject,
    TeacherClass,
    TeacherSubject,
    User,
)


from .grade_reports.queries import get_period_reports, get_quarter_reports

get_period_reports_api = get_period_reports
get_quarter_reports_api = get_quarter_reports


def _normalize_org_name(value: str) -> str:
    """Приводит название организации к каноничному виду для сравнения.

    - схлопывает любые whitespace (включая NBSP \xa0) в одиночные пробелы;
    - убирает обрамляющие пробелы;
    - приводит к нижнему регистру.
    """
    if not value:
        return ""
    return " ".join(value.replace("\xa0", " ").lower().split())


def find_school_by_org_name(org_name: str):
    """Поиск школы по имени организации.

    Стратегия (от строгого к мягкому, чтобы избежать ложных коллизий):
    1) точное совпадение нормализованных имён;
    2) `org_name` целиком содержится в имени школы — только если совпадение
       единственное (иначе возвращаем None, чтобы не выбрать произвольную);
    3) обратное вхождение (имя школы — подстрока org_name) намеренно НЕ
       используется: оно слишком часто давало бы false-positive (например,
       короткое «Лицей» как подстрока «Специализированный IT лицей»).
    """
    org_lower = _normalize_org_name(org_name)
    if not org_lower:
        return None

    all_active = School.query.filter(School.is_active == True).all()

    for school in all_active:
        if _normalize_org_name(school.name) == org_lower:
            return school

    candidates = [
        school
        for school in all_active
        if org_lower in _normalize_org_name(school.name)
    ]
    if len(candidates) == 1:
        return candidates[0]

    return None


def auto_create_class_and_subject(school_id: int, class_name: str, subject_name: str, teacher_id: int):
    """Create and bind class/subject relations for teacher if missing."""
    cls = Class.query.filter_by(school_id=school_id, name=class_name).first()
    if not cls:
        cls = Class(school_id=school_id, name=class_name)
        db.session.add(cls)
        db.session.flush()

    subj = Subject.query.filter_by(school_id=school_id, name=subject_name).first()
    if not subj:
        subj = Subject(school_id=school_id, name=subject_name)
        db.session.add(subj)
        db.session.flush()

    ts = TeacherSubject.query.filter_by(teacher_id=teacher_id, subject_id=subj.id).first()
    if not ts:
        ts = TeacherSubject(teacher_id=teacher_id, subject_id=subj.id)
        db.session.add(ts)
        db.session.flush()

    tc = TeacherClass.query.filter_by(teacher_subject_id=ts.id, class_id=cls.id).first()
    if not tc:
        tc = TeacherClass(teacher_subject_id=ts.id, class_id=cls.id, subgroup=None)
        db.session.add(tc)
        db.session.flush()


def generate_jwt_token(user: User, expires_in: int = 2592000) -> str:
    """Generate JWT token for API client."""
    payload = {
        "user_id": user.id,
        "username": user.username,
        "role": user.role,
        "exp": datetime.utcnow() + timedelta(seconds=expires_in),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, current_app.config["SECRET_KEY"], algorithm="HS256")


def verify_jwt_token(token: str) -> dict | None:
    """Decode JWT token and return payload if valid."""
    try:
        return jwt.decode(
            token,
            current_app.config["SECRET_KEY"],
            algorithms=["HS256"],
        )
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def require_jwt(f):
    """Decorator that validates bearer token and injects request.current_user.

    Security notes:
    - User is loaded fresh from DB on every request, so deactivated accounts
      are blocked even if their token has not yet expired.
    - Role is compared against the live DB value; if the role was changed after
      token issuance the request is rejected immediately.
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            return jsonify({"error": "Отсутствует токен авторизации"}), 401

        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return jsonify({"error": "Неверный формат токена"}), 401

        payload = verify_jwt_token(parts[1])
        if not payload:
            return jsonify({"error": "Токен недействителен или истек"}), 401

        user = db.session.get(User, payload["user_id"])
        if not user or not user.is_active:
            return jsonify({"error": "Пользователь не найден или неактивен"}), 401

        # Verify the role from the live DB matches what was encoded in the token.
        # Prevents old tokens from granting stale elevated access after role change.
        if user.role != payload.get("role"):
            return jsonify({"error": "Роль пользователя изменилась. Войдите снова."}), 401

        request.current_user = user
        return f(*args, **kwargs)

    return decorated_function
