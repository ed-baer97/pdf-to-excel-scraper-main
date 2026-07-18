"""Авторизация Desktop API: выдача и обновление JWT-токенов."""

from flask import jsonify, request
from werkzeug.security import check_password_hash

from ...constants import MIN_DESKTOP_VERSION
from ...models import User
from ...services.api_helpers import generate_jwt_token, require_jwt
from . import bp

TOKEN_EXPIRES_IN = 2592000  # 30 дней


def _parse_desktop_version(v: str) -> tuple:
    """Разбирает строку версии в кортеж целых чисел. При ошибке возвращает (0, 0, 0)."""
    try:
        return tuple(int(x) for x in v.strip().split(".")[:3])
    except Exception:
        return (0, 0, 0)


@bp.post("/auth/login")
def api_login():
    """
    Авторизация пользователя

    Request:
        {"username": "teacher1", "password": "password123"}

    Response:
        {
            "success": true,
            "token": "eyJ...",
            "expires_in": 2592000,
            "user": {"id": 1, "username": "teacher1", "role": "teacher", "school_id": 1}
        }
    """
    data = request.get_json()

    if not data:
        return jsonify({"error": "Отсутствуют данные запроса"}), 400

    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        return jsonify({"error": "Отсутствует логин или пароль"}), 400

    user = User.query.filter_by(username=username).first()

    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({"error": "Неверный логин или пароль"}), 401

    if not user.is_active:
        return jsonify({"error": "Учетная запись отключена"}), 403

    # Проверка версии десктоп-приложения
    desktop_ver_str = request.headers.get("X-Desktop-Version", "").strip()
    parsed_ver = _parse_desktop_version(desktop_ver_str) if desktop_ver_str else (0, 0, 0)
    if parsed_ver < MIN_DESKTOP_VERSION:
        min_ver_str = ".".join(str(x) for x in MIN_DESKTOP_VERSION)
        return jsonify({
            "error": (
                f"Версия приложения устарела (у вас: {desktop_ver_str or 'не указана'}, "
                f"требуется: {min_ver_str}). Пожалуйста, обновите Mektep Analyzer."
            ),
            "update_required": True,
            "min_version": min_ver_str,
        }), 426

    token = generate_jwt_token(user, TOKEN_EXPIRES_IN)

    # AI настройки школы (ключ и модель — выбор супер-админа)
    ai_api_key = None
    ai_model = "qwen-flash-character"
    if user.school:
        if user.school.ai_api_key:
            ai_api_key = user.school.ai_api_key
        if user.school.ai_model:
            ai_model = user.school.ai_model

    return jsonify({
        "success": True,
        "token": token,
        "expires_in": TOKEN_EXPIRES_IN,
        "user": {
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "school_id": user.school_id,
            "ai_api_key": ai_api_key,
            "ai_model": ai_model,
        }
    }), 200


@bp.post("/auth/refresh")
@require_jwt
def api_refresh_token():
    """
    Обновление JWT токена

    Response:
        {"success": true, "token": "eyJ...", "expires_in": 2592000}
    """
    user = request.current_user
    token = generate_jwt_token(user, TOKEN_EXPIRES_IN)

    return jsonify({
        "success": True,
        "token": token,
        "expires_in": TOKEN_EXPIRES_IN
    }), 200
