"""Отчёты: загрузка (UPSERT), лог метаданных, список и удаление."""

from flask import jsonify, request

from ...extensions import db
from ...models import GradeReport, ReportFile
from ...services.academic_year import resolve_academic_year
from ...services.api_helpers import require_jwt
from ...services.report_upload import (
    ReportUploadError,
    log_report_metadata,
    upsert_grade_report,
)
from . import bp


@bp.post("/reports/log")
@require_jwt
def api_log_reports():
    """
    Логирование созданных отчетов (только метаданные)

    Request:
        {
            "reports": [
                {
                    "class": "9А",
                    "subject": "Математика",
                    "period": "2",
                    "timestamp": "2024-01-15T10:30:00",
                    "has_excel": true,
                    "has_word": true
                },
                ...
            ]
        }

    Response:
        {"success": true, "count": 5}
    """
    user = request.current_user
    data = request.get_json()

    if not data or "reports" not in data:
        return jsonify({"error": "Отсутствуют данные отчетов"}), 400

    reports = data["reports"]
    if not isinstance(reports, list):
        return jsonify({"error": "reports должен быть массивом"}), 400

    created_count = log_report_metadata(user, reports)

    return jsonify({
        "success": True,
        "count": created_count
    }), 200


@bp.post("/reports/upload")
@require_jwt
def api_upload_report():
    """
    Загрузка/обновление отчёта с оценками (UPSERT)

    Если отчёт с таким class_name/subject_name/period уже существует
    у этого учителя — обновляет, иначе создаёт новый.

    Request:
        {
            "class_name": "7А",
            "subject_name": "Математика",
            "period_type": "quarter",
            "period_number": 2,
            "grades_json": {
                "students": [
                    {"name": "Иванов Иван", "percent": 85.5, "grade": 4},
                    ...
                ],
                "quality_percent": 66.7,
                "success_percent": 100.0,
                "total_students": 25
            },
            "analytics_json": {
                "sor": [{"name": "СОр 1", "count_5": 5, "count_4": 8, ...}, ...],
                "soch": {"count_5": 6, "count_4": 9, ...}
            }
        }

    Response:
        {"success": true, "report_id": 123, "action": "created" | "updated"}
    """
    user = request.current_user
    data = request.get_json()

    if not data:
        return jsonify({"error": "Отсутствуют данные запроса"}), 400

    try:
        result = upsert_grade_report(user, data)
    except ReportUploadError as exc:
        return jsonify(exc.to_payload()), exc.status

    return jsonify({"success": True, **result}), 200


@bp.delete("/reports/all")
@require_jwt
def api_delete_all_reports():
    """
    Удаление ВСЕХ отчётов текущего учителя на сервере.

    Удаляет:
    - Все GradeReport записи учителя
    - Все ReportFile записи учителя

    Response:
        {"success": true, "deleted_grade_reports": 10, "deleted_report_files": 5}
    """
    user = request.current_user

    grade_reports_count = GradeReport.query.filter_by(teacher_id=user.id).delete()
    report_files_count = ReportFile.query.filter_by(teacher_id=user.id).delete()
    db.session.commit()

    return jsonify({
        "success": True,
        "deleted_grade_reports": grade_reports_count,
        "deleted_report_files": report_files_count,
    }), 200


@bp.delete("/reports/<int:report_id>")
@require_jwt
def api_delete_report(report_id: int):
    """
    Удаление отчёта

    Учитель может удалить только свои отчёты.

    Response:
        {"success": true}
    """
    user = request.current_user

    report = db.session.get(GradeReport, report_id)

    if not report:
        return jsonify({"error": "Отчёт не найден"}), 404

    if report.teacher_id != user.id:
        return jsonify({"error": "Нет прав для удаления этого отчёта"}), 403

    db.session.delete(report)
    db.session.commit()

    return jsonify({
        "success": True
    }), 200


@bp.get("/reports/my")
@require_jwt
def api_get_my_reports():
    """
    Получение списка своих отчётов

    Query params:
        - period_type: "quarter" | "semester" (optional)
        - period_number: 1-4 (optional)

    Response:
        {
            "success": true,
            "reports": [
                {
                    "id": 123,
                    "class_name": "7А",
                    "subject_name": "Математика",
                    "period_type": "quarter",
                    "period_number": 2,
                    "created_at": "2024-01-15T10:30:00",
                    "updated_at": "2024-01-16T12:00:00"
                },
                ...
            ]
        }
    """
    user = request.current_user
    academic_year = resolve_academic_year(request.args.get("academic_year"))

    query = GradeReport.query.filter_by(
        teacher_id=user.id,
        academic_year=academic_year,
    )

    period_type = request.args.get("period_type")
    if period_type:
        query = query.filter_by(period_type=period_type)

    period_number = request.args.get("period_number")
    if period_number:
        query = query.filter_by(period_number=int(period_number))

    reports = query.order_by(GradeReport.updated_at.desc()).all()

    return jsonify({
        "success": True,
        "reports": [
            {
                "id": r.id,
                "class_name": r.class_name,
                "subject_name": r.subject_name,
                "period_type": r.period_type,
                "period_number": r.period_number,
                "academic_year": r.academic_year,
                "created_at": r.created_at.isoformat(),
                "updated_at": r.updated_at.isoformat()
            }
            for r in reports
        ]
    }), 200
