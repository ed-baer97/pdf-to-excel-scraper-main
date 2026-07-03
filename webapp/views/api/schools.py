"""Информация о школе пользователя и поиск организации по имени."""

from flask import jsonify, request

from ...services.api_helpers import (
    build_my_school_payload,
    find_school_by_org_name,
    require_jwt,
)
from . import bp


@bp.get("/schools/my")
@require_jwt
def api_my_school():
    """
    Информация о школе текущего пользователя.

    Возвращает название школы и флаг allow_cross_school_reports.
    Используется десктопным приложением для проверки организации
    перед запуском скрапинга.

    Response:
        {
            "success": true,
            "school_id": 1,
            "school_name": "Специализированный IT лицей",
            "allow_cross_school_reports": false
        }
    """
    return jsonify(build_my_school_payload(request.current_user)), 200


@bp.get("/schools/lookup")
@require_jwt
def api_lookup_school():
    """
    Поиск школы по имени организации (из mektep.edu.kz).

    Используется десктоп-приложением для определения, есть ли организация
    учителя в нашей базе данных, перед отправкой отчётов.

    Query params:
        - org_name: Название организации (строка из mektep.edu.kz)

    Response (найдена):
        {"success": true, "school_id": 1, "school_name": "Школа №15 г. Астана"}

    Response (не найдена):
        {"success": false, "error": "Организация не найдена в базе данных"}
    """
    org_name = (request.args.get("org_name") or "").strip()

    if not org_name:
        return jsonify({"error": "Не указано название организации"}), 400

    # Python-side сравнение (SQLite lower() не поддерживает кириллицу)
    school = find_school_by_org_name(org_name)

    if school:
        return jsonify({
            "success": True,
            "school_id": school.id,
            "school_name": school.name
        }), 200

    return jsonify({
        "success": False,
        "error": f"Организация '{org_name}' не найдена в базе данных"
    }), 404
