"""
API endpoints for Mektep Desktop integration

Минимальный REST API для десктопного приложения:
- Authentication (JWT tokens)
- Reports logging
"""
from datetime import datetime

from flask import Blueprint, current_app, jsonify, request
from werkzeug.security import check_password_hash

from ..extensions import db
from ..models import (
    User, Role, ReportFile, GradeReport,
    Class, School,
    Subject, TeacherClass, TeacherSubject,
)
import json
from ..services.api_helpers import (
    auto_create_class_and_subject,
    find_school_by_org_name,
    generate_jwt_token,
    get_period_reports_api,
    require_jwt,
)
from ..services.teacher_schools import (
    get_allowed_school_names,
    get_teacher_schools,
    teacher_can_report_for_school_id,
    teacher_has_cross_school_allowed,
)
from ..services.class_grades_matrix import (
    build_class_grades_matrix,
    build_teacher_analytics_map,
    class_grades_summary,
    get_teacher_subject_class_pairs,
    students_with_grades_count,
    subject_column_stats,
)
from ..services.grade_reports.class_teacher import categorize_students
from ..services.year_grades import YEAR_UI_PERIOD
from ..constants import MIN_DESKTOP_VERSION, normalize_subject_name, kazakh_sort_key

bp = Blueprint("api", __name__, url_prefix="/api")


def _parse_desktop_version(v: str) -> tuple:
    """Разбирает строку версии в кортеж целых чисел. При ошибке возвращает (0, 0, 0)."""
    try:
        return tuple(int(x) for x in v.strip().split(".")[:3])
    except Exception:
        return (0, 0, 0)


# ==============================================================================
# Authentication Endpoints
# ==============================================================================

@bp.post("/auth/login")
def api_login():
    """
    Авторизация пользователя
    
    Request:
        {
            "username": "teacher1",
            "password": "password123"
        }
    
    Response:
        {
            "success": true,
            "token": "eyJ...",
            "expires_in": 2592000,
            "user": {
                "id": 1,
                "username": "teacher1",
                "role": "teacher",
                "school_id": 1
            }
        }
    """
    data = request.get_json()
    
    if not data:
        return jsonify({"error": "Отсутствуют данные запроса"}), 400
    
    username = data.get("username")
    password = data.get("password")
    
    if not username or not password:
        return jsonify({"error": "Отсутствует логин или пароль"}), 400
    
    # Ищем пользователя
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
                f"требуется: {min_ver_str}). Пожалуйста, обновите Mektep Desktop."
            ),
            "update_required": True,
            "min_version": min_ver_str,
        }), 426

    # Генерируем токен
    expires_in = 2592000  # 30 дней
    token = generate_jwt_token(user, expires_in)
    
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
        "expires_in": expires_in,
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
        {
            "success": true,
            "token": "eyJ...",
            "expires_in": 2592000
        }
    """
    user = request.current_user
    
    expires_in = 2592000  # 30 дней
    token = generate_jwt_token(user, expires_in)
    
    return jsonify({
        "success": True,
        "token": token,
        "expires_in": expires_in
    }), 200


# ==============================================================================
# Reports Logging Endpoints
# ==============================================================================

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
        {
            "success": true,
            "count": 5
        }
    """
    user = request.current_user
    data = request.get_json()
    
    if not data or "reports" not in data:
        return jsonify({"error": "Отсутствуют данные отчетов"}), 400
    
    reports = data["reports"]
    if not isinstance(reports, list):
        return jsonify({"error": "reports должен быть массивом"}), 400
    
    # Сохраняем метаданные отчетов (БЕЗ файлов!)
    created_count = 0
    
    for report_data in reports:
        try:
            # Создаем запись в БД (только метаданные)
            report = ReportFile(
                school_id=user.school_id,
                teacher_id=user.id,
                period_code=report_data.get("period", "2"),
                class_name=report_data.get("class", ""),
                subject=report_data.get("subject", ""),
                excel_path=None,  # Файлы не хранятся на сервере
                word_path=None,   # Только метаданные
                created_at=datetime.fromisoformat(
                    report_data.get("timestamp", datetime.utcnow().isoformat())
                    .replace("Z", "+00:00")
                )
            )
            
            db.session.add(report)
            created_count += 1
        
        except Exception as e:
            current_app.logger.error(f"Error logging report: {e}")
            continue
    
    db.session.commit()
    
    return jsonify({
        "success": True,
        "count": created_count
    }), 200


# ==============================================================================
# School Info API (школа текущего пользователя)
# ==============================================================================

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
    user = request.current_user
    
    if not user.school_id:
        out = {
            "success": True,
            "school_id": None,
            "school_name": None,
            "allow_cross_school_reports": True,
        }
        if user.role == Role.TEACHER.value:
            tiin = (getattr(user, "iin", None) or "").strip()
            out["expected_iin"] = tiin if tiin else None
            out["iin_missing"] = not bool(tiin)
        else:
            out["expected_iin"] = None
            out["iin_missing"] = False
        return jsonify(out), 200

    school = db.session.get(School, user.school_id)
    if not school:
        out = {
            "success": True,
            "school_id": None,
            "school_name": None,
            "allow_cross_school_reports": True,
        }
        if user.role == Role.TEACHER.value:
            tiin = (getattr(user, "iin", None) or "").strip()
            out["expected_iin"] = tiin if tiin else None
            out["iin_missing"] = not bool(tiin)
        else:
            out["expected_iin"] = None
            out["iin_missing"] = False
        return jsonify(out), 200
    
    teacher_schools = get_teacher_schools(user.id) if user.role == Role.TEACHER.value else []
    payload = {
        "success": True,
        "school_id": school.id,
        "school_name": school.name,
        "allow_cross_school_reports": (
            teacher_has_cross_school_allowed(user.id)
            if user.role == Role.TEACHER.value
            else school.allow_cross_school_reports
        ),
    }
    if user.role == Role.TEACHER.value:
        payload["schools"] = [{"id": s.id, "name": s.name} for s in teacher_schools]
        payload["allowed_school_names"] = get_allowed_school_names(user.id)
        tiin = (getattr(user, "iin", None) or "").strip()
        if tiin:
            payload["expected_iin"] = tiin
            payload["iin_missing"] = False
        else:
            payload["expected_iin"] = None
            payload["iin_missing"] = True
    else:
        payload["expected_iin"] = None
        payload["iin_missing"] = False

    return jsonify(payload), 200


# ==============================================================================
# School Lookup API (поиск организации по имени)
# ==============================================================================

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
        {
            "success": true,
            "school_id": 1,
            "school_name": "Школа №15 г. Астана"
        }
    
    Response (не найдена):
        {
            "success": false,
            "error": "Организация не найдена в базе данных"
        }
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


# ==============================================================================
# Grade Reports API (для веб-панели админа и десктопа)
# ==============================================================================

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
        {
            "success": true,
            "report_id": 123,
            "action": "created" | "updated"
        }
    """
    user = request.current_user
    data = request.get_json()
    
    if not data:
        return jsonify({"error": "Отсутствуют данные запроса"}), 400
    
    # Валидация обязательных полей
    required_fields = ["class_name", "subject_name", "period_type", "period_number"]
    for field in required_fields:
        if field not in data:
            return jsonify({"error": f"Отсутствует поле: {field}"}), 400
    
    class_name = data["class_name"]
    subject_name = data["subject_name"]
    period_type = data["period_type"]
    period_number = int(data["period_number"])
    grades_payload = data.get("grades_json")
    analytics_payload = data.get("analytics_json")
    
    if period_type == "year":
        return jsonify({
            "error": "Годовые оценки вычисляются автоматически из четвертей 1–4. "
                     "Загрузите отчёты за четверть или полугодие.",
        }), 400

    if period_type not in ("quarter", "semester", "final"):
        return jsonify({"error": "period_type должен быть 'quarter', 'semester' или 'final'"}), 400

    if period_type == "quarter":
        max_period = 4
    elif period_type == "semester":
        max_period = 2
    else:
        max_period = 1
    if not (1 <= period_number <= max_period):
        return jsonify({"error": f"period_number должен быть от 1 до {max_period}"}), 400
    
    # ===== Определяем school_id по org_name (если передан) =====
    org_name = (data.get("org_name") or "").strip()
    
    if org_name:
        # Python-side сравнение (SQLite lower() не поддерживает кириллицу)
        school = find_school_by_org_name(org_name)
        
        if not school:
            return jsonify({
                "error": f"Организация '{org_name}' не найдена в базе данных. "
                         "Данные не были загружены на сервер.",
                "org_not_found": True
            }), 404
        
        school_id = school.id
        
        # ===== Проверка: org_name в списке школ учителя? =====
        if user.role == Role.TEACHER.value and not teacher_can_report_for_school_id(
            user.id, school_id
        ):
            allowed = ", ".join(get_allowed_school_names(user.id)) or "—"
            return jsonify({
                "error": (
                    f"Организация «{org_name}» не входит в ваши школы ({allowed}). "
                    "Попросите администратора добавить вас в эту школу по ИИН "
                    "или включите «Отчёты для других школ»."
                ),
                "org_mismatch": True
            }), 403
    else:
        # Fallback: используем school_id пользователя (обратная совместимость)
        school_id = user.school_id
    
    if not school_id:
        return jsonify({
            "error": "Не удалось определить организацию. Укажите org_name или привяжите пользователя к школе."
        }), 400
    
    if period_type == "final":
        final_block = (
            grades_payload.get("final")
            if isinstance(grades_payload, dict)
            else None
        )
        students_final = (
            final_block.get("students")
            if isinstance(final_block, dict)
            else None
        )
        if not students_final:
            return jsonify({
                "error": "Отчёт итога без таблицы четвертных/годовых оценок.",
                "missing_final_data": True,
            }), 422

    # Четверть/полугодие: upload допустим при заголовке «Расчет оценки за …» / «Бағаны есептеу: …».
    if period_type in ("quarter", "semester"):
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
            return jsonify({
                "error": "Отчёт без заголовка расчёта оценки за период. "
                         "Загрузка оценок по предмету запрещена.",
                "missing_grade_header": True
            }), 422

    # Преобразуем JSON данные в строки
    grades_json = json.dumps(grades_payload, ensure_ascii=False) if grades_payload else None
    analytics_json = json.dumps(analytics_payload, ensure_ascii=False) if analytics_payload else None
    
    # ===== Auto-create Class, Subject, TeacherSubject, TeacherClass =====
    auto_create_class_and_subject(
        school_id=school_id,
        class_name=class_name,
        subject_name=subject_name,
        teacher_id=user.id
    )
    
    # Ищем существующий отчёт
    existing_report = GradeReport.query.filter_by(
        teacher_id=user.id,
        school_id=school_id,
        class_name=class_name,
        subject_name=subject_name,
        period_type=period_type,
        period_number=period_number
    ).first()
    
    if existing_report:
        # Обновляем существующий
        existing_report.grades_json = grades_json
        existing_report.analytics_json = analytics_json
        existing_report.updated_at = datetime.utcnow()
        report_id = existing_report.id
        action = "updated"
    else:
        # Создаём новый
        new_report = GradeReport(
            teacher_id=user.id,
            school_id=school_id,
            class_name=class_name,
            subject_name=subject_name,
            period_type=period_type,
            period_number=period_number,
            grades_json=grades_json,
            analytics_json=analytics_json
        )
        db.session.add(new_report)
        db.session.flush()  # Чтобы получить ID
        report_id = new_report.id
        action = "created"
    
    db.session.commit()
    
    return jsonify({
        "success": True,
        "report_id": report_id,
        "action": action
    }), 200


@bp.delete("/reports/all")
@require_jwt
def api_delete_all_reports():
    """
    Удаление ВСЕХ отчётов текущего учителя на сервере.
    
    Удаляет:
    - Все GradeReport записи учителя
    - Все ReportFile записи учителя
    
    Response:
        {
            "success": true,
            "deleted_grade_reports": 10,
            "deleted_report_files": 5
        }
    """
    user = request.current_user
    
    # Удаляем все GradeReport
    grade_reports_count = GradeReport.query.filter_by(teacher_id=user.id).delete()
    
    # Удаляем все ReportFile
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
        {
            "success": true
        }
    """
    user = request.current_user
    
    report = db.session.get(GradeReport, report_id)
    
    if not report:
        return jsonify({"error": "Отчёт не найден"}), 404
    
    # Проверка: можно удалить только свой отчёт
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
    
    # Фильтры
    query = GradeReport.query.filter_by(teacher_id=user.id)
    
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
                "created_at": r.created_at.isoformat(),
                "updated_at": r.updated_at.isoformat()
            }
            for r in reports
        ]
    }), 200


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
    school_id = user.school_id

    matrix = build_class_grades_matrix(school_id, class_name, period_number)
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


# ==============================================================================
# Teacher Cabinet API (кабинет учителя для десктопа)
# ==============================================================================

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
    user = request.current_user
    
    # Предметы и классы через TeacherSubject → TeacherClass
    teacher_subjects = TeacherSubject.query.filter_by(teacher_id=user.id).all()
    
    subjects_data = []
    for ts in teacher_subjects:
        subject = db.session.get(Subject, ts.subject_id)
        if not subject:
            continue
        
        teacher_classes = TeacherClass.query.filter_by(teacher_subject_id=ts.id).all()
        classes_list = []
        for tc in teacher_classes:
            cls = db.session.get(Class, tc.class_id)
            if cls:
                classes_list.append({
                    "class_name": cls.name,
                    "class_id": cls.id,
                    "subgroup": tc.subgroup
                })
        
        if classes_list:
            subjects_data.append({
                "subject_name": subject.name,
                "subject_id": subject.id,
                "classes": classes_list
            })
    
    # Классы, где учитель — классный руководитель
    managed = Class.query.filter_by(
        class_teacher_id=user.id,
        school_id=user.school_id
    ).all()
    managed_classes = [c.name for c in managed]
    
    return jsonify({
        "success": True,
        "subjects": subjects_data,
        "managed_classes": managed_classes
    }), 200


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
                            "analytics": {
                                "sor": [...],
                                "soch": {...}
                            }
                        }
                    ]
                }
            ]
        }
    """
    user = request.current_user
    period_number = int(request.args.get("period_number", 2))
    school_id = user.school_id

    pairs = get_teacher_subject_class_pairs(user.id, school_id)
    if not pairs:
        reports = get_period_reports_api(
            school_id, period_number, teacher_id=user.id
        )
        seen_pairs: set[tuple[str, str]] = set()
        for report in reports:
            subj = normalize_subject_name(report.subject_name, school_id)
            key = (subj, report.class_name)
            if key not in seen_pairs:
                seen_pairs.add(key)
                pairs.append(key)

    analytics_map = build_teacher_analytics_map(
        school_id, user.id, period_number
    )

    subjects_map: dict[str, dict[str, dict]] = {}
    matrix_cache: dict[str, dict] = {}

    for subj, cls in pairs:
        if cls not in matrix_cache:
            matrix_cache[cls] = build_class_grades_matrix(
                school_id, cls, period_number
            )
        matrix = matrix_cache[cls]
        if matrix["empty"]:
            continue

        stats = subject_column_stats(matrix["students"], subj)
        class_data = {
            "class_name": cls,
            **stats,
            "analytics": analytics_map.get((cls, subj)),
        }
        subjects_map.setdefault(subj, {})[cls] = class_data

    subjects_list = []
    for subj_name in sorted(subjects_map.keys(), key=kazakh_sort_key):
        classes = sorted(
            subjects_map[subj_name].values(),
            key=lambda x: x["class_name"],
        )
        subjects_list.append({
            "subject_name": subj_name,
            "classes": classes,
        })

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
    user = request.current_user
    period_number = int(request.args.get("period_number", 2))
    
    # Находим классы, где учитель — классный руководитель
    managed_classes = Class.query.filter_by(
        class_teacher_id=user.id,
        school_id=user.school_id
    ).all()
    
    if not managed_classes:
        return jsonify({
            "success": True,
            "classes": [],
            "message": "Вы не назначены классным руководителем"
        }), 200
    
    result_classes = []
    
    for cls_obj in managed_classes:
        cls_name = cls_obj.name
        matrix = build_class_grades_matrix(
            user.school_id, cls_name, period_number
        )
        if matrix["empty"]:
            continue

        categories = categorize_students(
            matrix["students"], matrix["subject_teachers"]
        )
        total = students_with_grades_count(matrix["students"])
        result_classes.append({
            "class_name": cls_name,
            "categories": categories,
            "summary": {
                "total_students": total,
                "excellent": len(categories["excellent"]),
                "good": len(categories["good"]),
                "one_4": len(categories["one_4"]),
                "satisfactory": len(categories["satisfactory"]),
                "one_3": len(categories["one_3"]),
                "poor": len(categories["poor"]),
            },
        })
    
    return jsonify({
        "success": True,
        "classes": result_classes,
        "period_number": period_number
    }), 200
