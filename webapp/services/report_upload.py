"""Приём отчётов от десктоп-клиента: валидация и UPSERT GradeReport, лог метаданных."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from flask import current_app

from ..extensions import db
from ..models import GradeReport, ReportFile, Role
from .academic_year import resolve_academic_year
from .api_helpers import auto_create_class_and_subject, find_school_by_org_name
from .grade_reports.aggregates import apply_grade_aggregates
from .grade_reports.cache import bump_grade_reports_version
from .teacher_schools import get_allowed_school_names, teacher_can_report_for_school_id


class ReportUploadError(Exception):
    """Ошибка валидации/авторизации загрузки отчёта: message + HTTP-статус + доп. поля ответа."""

    def __init__(self, message: str, status: int = 400, **extra: Any) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.extra = extra

    def to_payload(self) -> dict[str, Any]:
        return {"error": self.message, **self.extra}


def _validate_period(data: dict) -> tuple[str, int]:
    period_type = data["period_type"]
    period_number = int(data["period_number"])

    if period_type == "year":
        raise ReportUploadError(
            "Годовые оценки вычисляются автоматически из четвертей 1–4. "
            "Загрузите отчёты за четверть или полугодие."
        )
    if period_type not in ("quarter", "semester", "final"):
        raise ReportUploadError("period_type должен быть 'quarter', 'semester' или 'final'")

    if period_type == "quarter":
        max_period = 4
    elif period_type == "semester":
        max_period = 2
    else:
        max_period = 1
    if not (1 <= period_number <= max_period):
        raise ReportUploadError(f"period_number должен быть от 1 до {max_period}")
    return period_type, period_number


def _resolve_school_id(user, data: dict) -> int:
    """school_id по org_name (с проверкой членства учителя) или из профиля пользователя."""
    org_name = (data.get("org_name") or "").strip()
    if org_name:
        # Python-side сравнение (SQLite lower() не поддерживает кириллицу)
        school = find_school_by_org_name(org_name)
        if not school:
            raise ReportUploadError(
                f"Организация '{org_name}' не найдена в базе данных. "
                "Данные не были загружены на сервер.",
                status=404,
                org_not_found=True,
            )
        if user.role == Role.TEACHER.value and not teacher_can_report_for_school_id(
            user.id, school.id
        ):
            allowed = ", ".join(get_allowed_school_names(user.id)) or "—"
            raise ReportUploadError(
                f"Организация «{org_name}» не входит в ваши школы ({allowed}). "
                "Попросите администратора добавить вас в эту школу по ИИН "
                "или включите «Отчёты для других школ».",
                status=403,
                org_mismatch=True,
            )
        return school.id

    if not user.school_id:
        raise ReportUploadError(
            "Не удалось определить организацию. Укажите org_name или привяжите пользователя к школе."
        )
    return user.school_id


def _validate_grades_payload(
    data: dict,
    period_type: str,
    grades_payload: Any,
    analytics_payload: Any,
) -> None:
    if period_type == "final":
        final_block = (
            grades_payload.get("final") if isinstance(grades_payload, dict) else None
        )
        students_final = (
            final_block.get("students") if isinstance(final_block, dict) else None
        )
        if not students_final:
            raise ReportUploadError(
                "Отчёт итога без таблицы четвертных/годовых оценок.",
                status=422,
                missing_final_data=True,
            )
        return

    # Четверть/полугодие: upload допустим при заголовке «Расчет оценки за …» / «Бағаны есептеу: …».
    has_grades = False
    if isinstance(grades_payload, dict):
        for student in grades_payload.get("students", []) or []:
            grade = student.get("grade")
            if grade not in (None, "", "0", 0):
                has_grades = True
                break
    has_quarter_grade_header = bool(data.get("has_quarter_grade_header"))
    has_soch = isinstance(analytics_payload, dict) and isinstance(analytics_payload.get("soch"), dict)
    has_grade_summary_columns = bool(data.get("has_grade_summary_columns"))
    visible_soch_column = bool(data.get("visible_soch_column"))
    upload_allowed = (
        has_quarter_grade_header
        or has_soch
        or has_grade_summary_columns
        or visible_soch_column
    )
    if has_grades and not upload_allowed:
        raise ReportUploadError(
            "Отчёт без заголовка расчёта оценки за период. "
            "Загрузка оценок по предмету запрещена.",
            status=422,
            missing_grade_header=True,
        )


def upsert_grade_report(user, data: dict) -> dict[str, Any]:
    """Валидирует данные и создаёт/обновляет GradeReport. Возвращает report_id и action."""
    required_fields = ["class_name", "subject_name", "period_type", "period_number"]
    for field in required_fields:
        if field not in data:
            raise ReportUploadError(f"Отсутствует поле: {field}")

    class_name = data["class_name"]
    subject_name = data["subject_name"]
    period_type, period_number = _validate_period(data)
    academic_year = resolve_academic_year(data.get("academic_year"))
    grades_payload = data.get("grades_json")
    analytics_payload = data.get("analytics_json")

    school_id = _resolve_school_id(user, data)
    _validate_grades_payload(data, period_type, grades_payload, analytics_payload)

    grades_json = json.dumps(grades_payload, ensure_ascii=False) if grades_payload else None
    analytics_json = json.dumps(analytics_payload, ensure_ascii=False) if analytics_payload else None

    auto_create_class_and_subject(
        school_id=school_id,
        class_name=class_name,
        subject_name=subject_name,
        teacher_id=user.id,
    )

    existing_report = GradeReport.query.filter_by(
        teacher_id=user.id,
        school_id=school_id,
        class_name=class_name,
        subject_name=subject_name,
        period_type=period_type,
        period_number=period_number,
        academic_year=academic_year,
    ).first()

    if existing_report:
        existing_report.grades_json = grades_json
        existing_report.analytics_json = analytics_json
        existing_report.updated_at = datetime.utcnow()
        apply_grade_aggregates(
            existing_report,
            grades_payload if isinstance(grades_payload, dict) else None,
        )
        report_id = existing_report.id
        action = "updated"
    else:
        new_report = GradeReport(
            teacher_id=user.id,
            school_id=school_id,
            class_name=class_name,
            subject_name=subject_name,
            period_type=period_type,
            period_number=period_number,
            academic_year=academic_year,
            grades_json=grades_json,
            analytics_json=analytics_json,
        )
        apply_grade_aggregates(
            new_report,
            grades_payload if isinstance(grades_payload, dict) else None,
        )
        db.session.add(new_report)
        db.session.flush()  # Чтобы получить ID
        report_id = new_report.id
        action = "created"

    db.session.commit()
    bump_grade_reports_version(school_id)
    return {"report_id": report_id, "action": action}


def log_report_metadata(user, reports: list) -> int:
    """Сохраняет метаданные созданных отчётов (без файлов). Возвращает число записей."""
    created_count = 0
    for report_data in reports:
        try:
            academic_year = resolve_academic_year(report_data.get("academic_year"))
            report = ReportFile(
                school_id=user.school_id,
                teacher_id=user.id,
                period_code=report_data.get("period", "2"),
                academic_year=academic_year,
                class_name=report_data.get("class", ""),
                subject=report_data.get("subject", ""),
                excel_path=None,  # Файлы не хранятся на сервере
                word_path=None,   # Только метаданные
                created_at=datetime.fromisoformat(
                    report_data.get("timestamp", datetime.utcnow().isoformat())
                    .replace("Z", "+00:00")
                ),
            )
            db.session.add(report)
            created_count += 1
        except Exception as e:
            current_app.logger.error(f"Error logging report: {e}")
            continue
    db.session.commit()
    return created_count
