"""
API endpoints for Mektep Desktop integration

Минимальный REST API для десктопного приложения:
- Authentication (JWT tokens)
- Quota checking
- Reports logging
"""
from datetime import datetime, timedelta
from functools import wraps

import jwt
from flask import Blueprint, current_app, jsonify, request
from werkzeug.security import check_password_hash

from ..extensions import db
from ..models import (
    User, Role, TeacherQuotaUsage, ReportFile, GradeReport,
    Class, Subject, TeacherSubject, TeacherClass, School,
)
import json

bp = Blueprint("api", __name__, url_prefix="/api")


def _find_school_by_org_name(org_name: str):
    """
    Поиск школы по названию организации (Python-side сравнение).
    
    SQLite lower() не поддерживает Unicode/кириллицу, поэтому
    сравнение регистронезависимо выполняется в Python, а не в SQL.
    
    Returns:
        School или None
    """
    if not org_name:
        return None
    
    all_active = School.query.filter(School.is_active == True).all()
    org_lower = org_name.lower()
    
    # 1. Точное совпадение (case-insensitive)
    for s in all_active:
        if s.name.lower() == org_lower:
            return s
    
    # 2. Частичное: org_name содержится в school.name или наоборот
    for s in all_active:
        sn = s.name.lower()
        if org_lower in sn or sn in org_lower:
            return s
    
    return None


def _auto_create_class_and_subject(school_id: int, class_name: str, subject_name: str, teacher_id: int):
    """
    Автоматически создаёт Class, Subject, TeacherSubject, TeacherClass
    при загрузке оценок, если они ещё не существуют. Дублей не создаёт.
    """
    # --- Class ---
    cls = Class.query.filter_by(school_id=school_id, name=class_name).first()
    if not cls:
        cls = Class(school_id=school_id, name=class_name)
        db.session.add(cls)
        db.session.flush()

    # --- Subject ---
    subj = Subject.query.filter_by(school_id=school_id, name=subject_name).first()
    if not subj:
        subj = Subject(school_id=school_id, name=subject_name)
        db.session.add(subj)
        db.session.flush()

    # --- TeacherSubject ---
    ts = TeacherSubject.query.filter_by(teacher_id=teacher_id, subject_id=subj.id).first()
    if not ts:
        ts = TeacherSubject(teacher_id=teacher_id, subject_id=subj.id)
        db.session.add(ts)
        db.session.flush()

    # --- TeacherClass ---
    tc = TeacherClass.query.filter_by(teacher_subject_id=ts.id, class_id=cls.id).first()
    if not tc:
        tc = TeacherClass(teacher_subject_id=ts.id, class_id=cls.id, subgroup=None)
        db.session.add(tc)
        db.session.flush()


# ==============================================================================
# JWT Helper Functions
# ==============================================================================

def generate_jwt_token(user: User, expires_in: int = 2592000) -> str:
    """
    Генерация JWT токена
    
    Args:
        user: Пользователь
        expires_in: Срок действия в секундах (по умолчанию 30 дней)
    
    Returns:
        JWT токен
    """
    payload = {
        "user_id": user.id,
        "username": user.username,
        "role": user.role,
        "exp": datetime.utcnow() + timedelta(seconds=expires_in),
        "iat": datetime.utcnow()
    }
    
    return jwt.encode(
        payload,
        current_app.config["SECRET_KEY"],
        algorithm="HS256"
    )


def verify_jwt_token(token: str) -> dict:
    """
    Проверка и декодирование JWT токена
    
    Args:
        token: JWT токен
    
    Returns:
        Декодированный payload или None если невалиден
    """
    try:
        payload = jwt.decode(
            token,
            current_app.config["SECRET_KEY"],
            algorithms=["HS256"]
        )
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def require_jwt(f):
    """Декоратор для проверки JWT токена"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get("Authorization")
        
        if not auth_header:
            return jsonify({"error": "Отсутствует токен авторизации"}), 401
        
        # Формат: "Bearer <token>"
        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return jsonify({"error": "Неверный формат токена"}), 401
        
        token = parts[1]
        payload = verify_jwt_token(token)
        
        if not payload:
            return jsonify({"error": "Токен недействителен или истек"}), 401
        
        # Получаем пользователя
        user = db.session.get(User, payload["user_id"])
        if not user or not user.is_active:
            return jsonify({"error": "Пользователь не найден или неактивен"}), 401
        
        # Передаем пользователя в функцию
        request.current_user = user
        return f(*args, **kwargs)
    
    return decorated_function


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
# Quota Endpoints
# ==============================================================================

@bp.get("/quota/check")
@require_jwt
def api_check_quota():
    """
    Проверка квоты пользователя
    
    Response:
        {
            "success": true,
            "allowed": true,
            "remaining": 15,
            "used": 5,
            "total": 20
        }
    """
    user = request.current_user
    
    # Только учителя имеют квоту
    if user.role != Role.TEACHER.value:
        return jsonify({
            "success": True,
            "allowed": True,
            "remaining": 999,
            "used": 0,
            "total": 999,
            "unlimited": True
        }), 200
    
    # Получаем квоту школы
    school = user.school
    if not school or not school.is_active:
        return jsonify({"error": "Школа не найдена или неактивна"}), 403
    
    quota_per_period = int(school.reports_quota_per_period or 0)
    
    # Получаем текущий период (можно передать как параметр)
    period_code = request.args.get("period", "2")
    
    # Получаем использование квоты
    usage = TeacherQuotaUsage.query.filter_by(
        teacher_id=user.id,
        period_code=period_code
    ).first()
    
    used = int(usage.used_reports) if usage else 0
    remaining = max(0, quota_per_period - used)
    
    return jsonify({
        "success": True,
        "allowed": remaining > 0,
        "remaining": remaining,
        "used": used,
        "total": quota_per_period
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
    
    # Обновляем квоту: один успешный скрап = +1 (не зависит от числа отчётов)
    if created_count > 0 and user.role == Role.TEACHER.value:
        period_code = reports[0].get("period", "2")
        usage = TeacherQuotaUsage.query.filter_by(
            teacher_id=user.id,
            period_code=period_code
        ).first()
        
        if not usage:
            usage = TeacherQuotaUsage(
                teacher_id=user.id,
                period_code=period_code,
                used_reports=0
            )
            db.session.add(usage)
        
        usage.used_reports += 1
    
    db.session.commit()
    
    return jsonify({
        "success": True,
        "count": created_count
    }), 200


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
    school = _find_school_by_org_name(org_name)
    
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
    
    # Валидация period_type
    if period_type not in ("quarter", "semester"):
        return jsonify({"error": "period_type должен быть 'quarter' или 'semester'"}), 400
    
    # Валидация period_number
    max_period = 4 if period_type == "quarter" else 2
    if not (1 <= period_number <= max_period):
        return jsonify({"error": f"period_number должен быть от 1 до {max_period}"}), 400
    
    # ===== Определяем school_id по org_name (если передан) =====
    org_name = (data.get("org_name") or "").strip()
    
    if org_name:
        # Python-side сравнение (SQLite lower() не поддерживает кириллицу)
        school = _find_school_by_org_name(org_name)
        
        if not school:
            return jsonify({
                "error": f"Организация '{org_name}' не найдена в базе данных. "
                         "Данные не были загружены на сервер.",
                "org_not_found": True
            }), 404
        
        school_id = school.id
    else:
        # Fallback: используем school_id пользователя (обратная совместимость)
        school_id = user.school_id
    
    if not school_id:
        return jsonify({
            "error": "Не удалось определить организацию. Укажите org_name или привяжите пользователя к школе."
        }), 400
    
    # Преобразуем JSON данные в строки
    grades_json = json.dumps(data.get("grades_json"), ensure_ascii=False) if data.get("grades_json") else None
    analytics_json = json.dumps(data.get("analytics_json"), ensure_ascii=False) if data.get("analytics_json") else None
    
    # ===== Auto-create Class, Subject, TeacherSubject, TeacherClass =====
    _auto_create_class_and_subject(
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
    - Сбрасывает TeacherQuotaUsage учителя
    
    Response:
        {
            "success": true,
            "deleted_grade_reports": 10,
            "deleted_report_files": 5,
            "quota_reset": true
        }
    """
    user = request.current_user
    
    # Удаляем все GradeReport
    grade_reports_count = GradeReport.query.filter_by(teacher_id=user.id).delete()
    
    # Удаляем все ReportFile
    report_files_count = ReportFile.query.filter_by(teacher_id=user.id).delete()
    
    # Сбрасываем квоту
    TeacherQuotaUsage.query.filter_by(teacher_id=user.id).delete()
    
    db.session.commit()
    
    return jsonify({
        "success": True,
        "deleted_grade_reports": grade_reports_count,
        "deleted_report_files": report_files_count,
        "quota_reset": True
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
    
    # Параметры
    period_type = request.args.get("period_type", "quarter")
    period_number = int(request.args.get("period_number", 2))
    
    # Получаем все отчёты для этого класса из школы пользователя
    reports = GradeReport.query.filter_by(
        school_id=user.school_id,
        class_name=class_name,
        period_type=period_type,
        period_number=period_number
    ).all()
    
    if not reports:
        return jsonify({
            "success": True,
            "class_name": class_name,
            "period_type": period_type,
            "period_number": period_number,
            "subjects": [],
            "students": [],
            "summary": {
                "total_students": 0,
                "quality_percent": 0,
                "success_percent": 0
            }
        }), 200
    
    # Собираем данные
    subjects = set()
    students_data = {}  # name -> {subject -> {percent, grade}}
    
    for report in reports:
        subjects.add(report.subject_name)
        
        if report.grades_json:
            try:
                grades_data = json.loads(report.grades_json)
                students_list = grades_data.get("students", [])
                
                for student in students_list:
                    name = student.get("name")
                    if not name:
                        continue
                    
                    if name not in students_data:
                        students_data[name] = {}
                    
                    students_data[name][report.subject_name] = {
                        "percent": student.get("percent"),
                        "grade": student.get("grade")
                    }
            except json.JSONDecodeError:
                current_app.logger.error(f"Invalid JSON in report {report.id}")
    
    # Формируем ответ
    subjects_list = sorted(subjects)
    students_list = [
        {
            "name": name,
            "grades": grades
        }
        for name, grades in sorted(students_data.items())
    ]
    
    # Считаем общую статистику
    total_students = len(students_data)
    grades_count = {"5": 0, "4": 0, "3": 0, "2": 0}
    
    for name, grades in students_data.items():
        # Средний балл по всем предметам
        grades_values = [g.get("grade") for g in grades.values() if g.get("grade")]
        if grades_values:
            avg_grade = sum(grades_values) / len(grades_values)
            if avg_grade >= 4.5:
                grades_count["5"] += 1
            elif avg_grade >= 3.5:
                grades_count["4"] += 1
            elif avg_grade >= 2.5:
                grades_count["3"] += 1
            else:
                grades_count["2"] += 1
    
    quality_percent = 0
    success_percent = 0
    if total_students > 0:
        quality_percent = round((grades_count["5"] + grades_count["4"]) / total_students * 100, 1)
        success_percent = round((grades_count["5"] + grades_count["4"] + grades_count["3"]) / total_students * 100, 1)
    
    return jsonify({
        "success": True,
        "class_name": class_name,
        "period_type": period_type,
        "period_number": period_number,
        "subjects": subjects_list,
        "students": students_list,
        "summary": {
            "total_students": total_students,
            "quality_percent": quality_percent,
            "success_percent": success_percent
        }
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
    period_type = request.args.get("period_type", "quarter")
    period_number = int(request.args.get("period_number", 2))
    
    # Получаем отчёты текущего учителя за период
    reports = GradeReport.query.filter_by(
        teacher_id=user.id,
        school_id=user.school_id,
        period_type=period_type,
        period_number=period_number
    ).all()
    
    # Группируем по предмету → классу
    subjects_map = {}  # subject_name -> {class_name -> report}
    
    for report in reports:
        subj = report.subject_name
        cls = report.class_name
        
        if subj not in subjects_map:
            subjects_map[subj] = {}
        
        # Считаем статистику из grades_json
        class_data = {
            "class_name": cls,
            "count_5": 0, "count_4": 0, "count_3": 0, "count_2": 0,
            "total": 0,
            "quality_percent": 0,
            "success_percent": 0,
            "analytics": None
        }
        
        if report.grades_json:
            try:
                grades = json.loads(report.grades_json)
                students = grades.get("students", [])
                for student in students:
                    g = student.get("grade")
                    if g is not None:
                        class_data["total"] += 1
                        if g == 5:
                            class_data["count_5"] += 1
                        elif g == 4:
                            class_data["count_4"] += 1
                        elif g == 3:
                            class_data["count_3"] += 1
                        elif g <= 2:
                            class_data["count_2"] += 1
                
                total = class_data["total"]
                if total > 0:
                    class_data["quality_percent"] = round(
                        (class_data["count_5"] + class_data["count_4"]) / total * 100, 1
                    )
                    class_data["success_percent"] = round(
                        (total - class_data["count_2"]) / total * 100, 1
                    )
            except json.JSONDecodeError:
                pass
        
        # Аналитика СОР/СОЧ
        if report.analytics_json:
            try:
                class_data["analytics"] = json.loads(report.analytics_json)
            except json.JSONDecodeError:
                pass
        
        subjects_map[subj][cls] = class_data
    
    # Формируем ответ
    subjects_list = []
    for subj_name in sorted(subjects_map.keys()):
        classes = sorted(subjects_map[subj_name].values(), key=lambda x: x["class_name"])
        subjects_list.append({
            "subject_name": subj_name,
            "classes": classes
        })
    
    return jsonify({
        "success": True,
        "subjects": subjects_list,
        "period_type": period_type,
        "period_number": period_number
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
    period_type = request.args.get("period_type", "quarter")
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
        
        # Все отчёты по этому классу за период (от всех учителей)
        reports = GradeReport.query.filter_by(
            school_id=user.school_id,
            class_name=cls_name,
            period_type=period_type,
            period_number=period_number
        ).all()
        
        if not reports:
            continue
        
        # Собираем оценки: student_name -> {subject -> grade}
        students_grades = {}
        subject_teachers = {}
        
        for report in reports:
            # Учитель предмета
            teacher_name = ""
            if report.teacher:
                teacher_name = report.teacher.full_name or report.teacher.username
            subject_teachers[report.subject_name] = teacher_name
            
            if report.grades_json:
                try:
                    grades = json.loads(report.grades_json)
                    for student in grades.get("students", []):
                        name = student.get("name")
                        grade = student.get("grade")
                        if name and grade is not None:
                            if name not in students_grades:
                                students_grades[name] = {}
                            students_grades[name][report.subject_name] = grade
                except json.JSONDecodeError:
                    pass
        
        # Категоризация
        categories = {
            "excellent": [],
            "good": [],
            "one_4": [],
            "satisfactory": [],
            "one_3": [],
            "poor": []
        }
        
        for name, subj_grades in sorted(students_grades.items()):
            grades_list = list(subj_grades.values())
            if not grades_list:
                continue
            
            count_5 = grades_list.count(5)
            count_4 = grades_list.count(4)
            count_3 = grades_list.count(3)
            count_2 = sum(1 for g in grades_list if g <= 2)
            
            if count_2 > 0:
                # Неуспевающие
                failing_subjects = [
                    {"subject": s, "teacher": subject_teachers.get(s, "")}
                    for s, g in subj_grades.items() if g <= 2
                ]
                categories["poor"].append({
                    "name": name,
                    "subjects": failing_subjects
                })
            elif all(g >= 5 for g in grades_list):
                # Отличники
                categories["excellent"].append({"name": name})
            elif count_4 == 1 and count_3 == 0:
                # С одной 4
                subj_with_4 = next((s for s, g in subj_grades.items() if g == 4), "")
                categories["one_4"].append({
                    "name": name,
                    "subject": subj_with_4,
                    "teacher": subject_teachers.get(subj_with_4, "")
                })
            elif count_3 == 0:
                # Хорошисты
                categories["good"].append({"name": name})
            elif count_3 == 1:
                # С одной 3
                subj_with_3 = next((s for s, g in subj_grades.items() if g == 3), "")
                categories["one_3"].append({
                    "name": name,
                    "subject": subj_with_3,
                    "teacher": subject_teachers.get(subj_with_3, "")
                })
            else:
                # Троечники
                subjects_with_3 = [s for s, g in subj_grades.items() if g == 3]
                categories["satisfactory"].append({
                    "name": name,
                    "subjects_with_3": subjects_with_3
                })
        
        total = len(students_grades)
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
                "poor": len(categories["poor"])
            }
        })
    
    return jsonify({
        "success": True,
        "classes": result_classes,
        "period_type": period_type,
        "period_number": period_number
    }), 200
