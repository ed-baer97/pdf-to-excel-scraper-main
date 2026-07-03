"""Кабинет учителя: классы/предметы, отчёт предметника, отчёт классного руководителя."""

from flask import jsonify, request

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

    Response:
        {
            "success": true,
            "subjects": [
                {
                    "subject_name": "Математика",
                    "classes": [
                        {"class_name": "7А", "subgroup": null},
                        {"class_name": "7Б", "subgroup": 1}
                    ]
                }
            ],
            "managed_classes": ["7А"]
        }
    """
    overview = teacher_subjects_overview(request.current_user)
    return jsonify({"success": True, **overview}), 200


@bp.get("/teacher/subject-report")
@require_jwt
def api_teacher_subject_report():
    """
    Отчёт предметника: статистика оценок по предметам и классам

    Query params:
        - period_type: "quarter" | "semester" (default: "quarter")
        - period_number: 1-4 (default: 2)

    Response:
        {
            "success": true,
            "subjects": [
                {
                    "subject_name": "Математика",
                    "classes": [
                        {
                            "class_name": "7А",
                            "count_5": 5, "count_4": 8, "count_3": 3, "count_2": 1,
                            "total": 17,
                            "quality_percent": 76.5,
                            "success_percent": 94.1,
                            "analytics": {"sor": [...], "soch": {...}}
                        }
                    ]
                }
            ]
        }
    """
    period_number = int(request.args.get("period_number", 2))
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

    Query params:
        - period_type: "quarter" | "semester" (default: "quarter")
        - period_number: 1-4 (default: 2)

    Response:
        {
            "success": true,
            "classes": [
                {
                    "class_name": "7А",
                    "categories": {
                        "excellent": [...],
                        "good": [...],
                        "one_4": [...],
                        "satisfactory": [...],
                        "one_3": [...],
                        "poor": [...]
                    },
                    "summary": {...}
                }
            ]
        }
    """
    period_number = int(request.args.get("period_number", 2))
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
