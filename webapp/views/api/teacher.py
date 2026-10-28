"""Кабинет учителя: классы/предметы, отчёт предметника, отчёт классного руководителя, ИИ-анализ целей."""

from flask import jsonify, request

from ...redis_utils import ai_rate_limiter
from ...services.admin_dashboard import parse_ui_period_number
from ...services.ai_analysis import generate_goals_analysis_for_user
from ...services.api_helpers import require_jwt
from ...services.teacher_cabinet import (
    class_teacher_report_payload,
    subject_report_payload,
    teacher_subjects_overview,
)
from . import bp


@bp.get("/teacher/my-classes")
@require_jwt
def api_teacher_my_classes():
    """
    Получение классов и предметов учителя
    """
    overview = teacher_subjects_overview(
        request.current_user, request.args.get("academic_year")
    )
    return jsonify({"success": True, **overview}), 200


@bp.get("/teacher/subject-report")
@require_jwt
def api_teacher_subject_report():
    """
    Отчёт предметника: статистика оценок по предметам и классам
    """
    period_number = parse_ui_period_number(request.args.get("period_number", 2))
    subjects_list = subject_report_payload(
        request.current_user, period_number, request.args.get("academic_year")
    )
    return jsonify({
        "success": True,
        "subjects": subjects_list,
        "period_number": period_number,
    }), 200


@bp.get("/teacher/class-teacher-report")
@require_jwt
def api_teacher_class_teacher_report():
    """
    Отчёт классного руководителя: категоризация учеников
    """
    period_number = parse_ui_period_number(request.args.get("period_number", 2))
    result_classes = class_teacher_report_payload(
        request.current_user, period_number, request.args.get("academic_year")
    )
    if result_classes is None:
        return jsonify({
            "success": True,
            "classes": [],
            "message": "Вы не назначены классным руководителем"
        }), 200

    return jsonify({
        "success": True,
        "classes": result_classes,
        "period_number": period_number
    }), 200


@bp.post("/teacher/goals/generate")
@require_jwt
def api_teacher_generate_goals():
    """
    Серверная генерация ИИ-анализа суммативного оценивания (СОР/СОЧ) для десктоп-клиента.
    Позволяет генерировать анализ без передачи AI API ключа школы на клиент.
    """
    user = request.current_user
    allowed, reset_in = ai_rate_limiter.is_allowed(str(user.id))
    if not allowed:
        return jsonify({
            "success": False,
            "error": f"Превышен лимит запросов. Попробуйте через {reset_in} сек.",
            "rate_limited": True,
            "reset_in": reset_in,
        }), 429

    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "Нет данных"}), 400

    achieved = (data.get("achieved") or "").strip()
    difficulties = (data.get("difficulties") or "").strip()
    if not difficulties:
        return jsonify({
            "success": False,
            "error": "Заполните поле 'Цели, вызвавшие затруднения'",
        }), 400

    payload = generate_goals_analysis_for_user(user, achieved, difficulties)
    if not payload.get("fallback"):
        payload["remaining_requests"] = ai_rate_limiter.get_remaining(str(user.id))
    return jsonify(payload), 200
