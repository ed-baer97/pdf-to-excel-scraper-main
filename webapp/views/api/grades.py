"""Сводная таблица оценок класса."""

from flask import jsonify, request

from ...constants import kazakh_sort_key
from ...services.academic_year import resolve_academic_year
from ...services.api_helpers import require_jwt
from ...services.class_grades_matrix import build_class_grades_matrix, class_grades_summary
from . import bp


@bp.get("/grades/class/<class_name>")
@require_jwt
def api_get_class_grades(class_name: str):
    """
    Получение сводной таблицы оценок класса

    Объединяет данные от всех учителей (включая подгруппы).

    Query params:
        - period_type: "quarter" | "semester" (default: "quarter")
        - period_number: 1-4 (default: 2)

    Response:
        {
            "success": true,
            "class_name": "7А",
            "period_type": "quarter",
            "period_number": 2,
            "subjects": ["Математика", "Физика", ...],
            "students": [
                {
                    "name": "Иванов Иван",
                    "grades": {
                        "Математика": {"percent": 85.5, "grade": 4},
                        "Физика": {"percent": 72.0, "grade": 3},
                        ...
                    }
                },
                ...
            ],
            "summary": {
                "total_students": 25,
                "quality_percent": 66.7,
                "success_percent": 100.0
            }
        }
    """
    user = request.current_user
    period_number = int(request.args.get("period_number", 2))
    academic_year = resolve_academic_year(request.args.get("academic_year"))
    school_id = user.school_id

    matrix = build_class_grades_matrix(
        school_id, class_name, period_number, academic_year=academic_year
    )
    if matrix["empty"]:
        return jsonify({
            "success": True,
            "class_name": class_name,
            "period_number": period_number,
            "subjects": [],
            "students": [],
            "summary": {
                "total_students": 0,
                "quality_percent": 0,
                "success_percent": 0,
            },
        }), 200

    students_data = matrix["students"]
    students_list = [
        {"name": name, "grades": grades}
        for name, grades in sorted(
            students_data.items(), key=lambda item: kazakh_sort_key(item[0])
        )
    ]
    summary = class_grades_summary(students_data, period_number)

    return jsonify({
        "success": True,
        "class_name": class_name,
        "period_number": period_number,
        "subjects": matrix["subjects"],
        "students": students_list,
        "summary": summary,
    }), 200
