import re
import secrets
import json
from functools import wraps
from io import BytesIO

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, url_for, flash, send_file
from flask_login import login_required, current_user
from sqlalchemy import func
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from openpyxl.utils import get_column_letter

from ..extensions import db
from ..models import Role, User, GradeReport, Class, ReportFile, TeacherSubject, TeacherClass
from ..security import decrypt_password, encrypt_password

bp = Blueprint("admin", __name__, url_prefix="/admin")


def _require_admin():
    return current_user.role == Role.SCHOOL_ADMIN.value


def admin_required(f):
    """Декоратор для проверки прав админа школы"""
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if current_user.role not in (Role.SUPERADMIN.value, Role.SCHOOL_ADMIN.value):
            flash("У вас нет прав для доступа к этой странице.", "danger")
            return redirect(url_for("main.index"))
        return f(*args, **kwargs)
    return decorated_function


def _parse_class_grade(class_name: str) -> int | None:
    """Извлекает номер класса из названия (1А -> 1, 10Б -> 10)."""
    m = re.match(r"^(\d+)", str(class_name or ""))
    return int(m.group(1)) if m else None


def _class_accordion_group(class_name: str) -> str:
    """Определяет группу аккордеона для класса по номеру (1А -> 1-4, 7Б -> 5-9, 10А -> 10-11)."""
    grade = _parse_class_grade(class_name)
    if grade is None:
        return "1-4"  # fallback
    if grade <= 4:
        return "1-4"
    if grade <= 9:
        return "5-9"
    return "10-11"


def _teacher_accordion_group(teacher: User, classes: list) -> str:
    """
    Определяет группу аккордеона для учителя-классного руководителя.
    Возвращает: "1-4", "5-9", "10-11" или "no_leadership".
    """
    teacher_classes = [c for c in classes if c.class_teacher_id == teacher.id]
    if not teacher_classes:
        return "no_leadership"
    grades = [_parse_class_grade(c.name) for c in teacher_classes if _parse_class_grade(c.name) is not None]
    if not grades:
        return "1-4"  # fallback
    min_grade = min(grades)
    if min_grade <= 4:
        return "1-4"
    if min_grade <= 9:
        return "5-9"
    return "10-11"


@bp.get("/")
@login_required
def dashboard():
    if not _require_admin():
        return redirect(url_for("teacher.dashboard"))
    teachers = User.query.filter_by(
        role=Role.TEACHER.value, school_id=current_user.school_id
    ).order_by(User.full_name).all()
    classes = Class.query.filter_by(
        school_id=current_user.school_id
    ).order_by(Class.name).all()
    # Группировка учителей по аккордеонам (1-4, 5-9, 10-11, без руководства)
    teachers_by_accordion = {
        "1-4": [],
        "5-9": [],
        "10-11": [],
        "no_leadership": [],
    }
    for t in teachers:
        group = _teacher_accordion_group(t, classes)
        teachers_by_accordion[group].append(t)
    # Группировка классов по аккордеонам (1-4, 5-9, 10-11)
    classes_by_accordion = {
        "1-4": [],
        "5-9": [],
        "10-11": [],
    }
    for cls in classes:
        group = _class_accordion_group(cls.name)
        classes_by_accordion[group].append(cls)
    return render_template(
        "admin/dashboard.html",
        teachers=teachers,
        teachers_by_accordion=teachers_by_accordion,
        classes=classes,
        classes_by_accordion=classes_by_accordion,
    )


@bp.post("/teachers/create")
@login_required
def create_teacher():
    if not _require_admin():
        return redirect(url_for("teacher.dashboard"))
    username = request.form.get("username", "").strip()
    full_name = request.form.get("full_name", "").strip()
    if not username:
        flash("Логин учителя обязателен.", "danger")
        return redirect(url_for("admin.dashboard"))
    if User.query.filter_by(username=username).first():
        flash("Такой логин уже существует.", "danger")
        return redirect(url_for("admin.dashboard"))

    pw = secrets.token_urlsafe(8)
    u = User(username=username, full_name=full_name or username, role=Role.TEACHER.value, school_id=current_user.school_id, is_active=True)
    # Assign per-school sequential number for filesystem paths (teacher_1, teacher_2, ...)
    max_seq = (
        db.session.query(func.max(User.fs_teacher_seq))
        .filter(User.school_id == current_user.school_id, User.role == Role.TEACHER.value)
        .scalar()
    )
    u.fs_teacher_seq = int(max_seq or 0) + 1
    u.set_password(pw)
    u.password_enc = encrypt_password(pw, current_app.config.get("PASSWORD_ENC_KEY", ""))
    db.session.add(u)
    db.session.commit()
    flash(f"Учитель создан. Пароль: {pw}", "success")
    return redirect(url_for("admin.dashboard"))


@bp.get("/teachers/import-template")
@login_required
def download_import_template():
    """Download an Excel template for bulk teacher import."""
    if not _require_admin():
        return redirect(url_for("teacher.dashboard"))

    wb = Workbook()
    ws = wb.active
    ws.title = "Учителя"

    headers = ["ФИО учителя", "Логин"]
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="4F81BD", end_color="4F81BD", fill_type="solid")
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")

    ws.cell(row=2, column=1, value="Иванов Иван Иванович")
    ws.cell(row=2, column=2, value="ivanov")
    ws.cell(row=3, column=1, value="Петрова Мария Сергеевна")
    ws.cell(row=3, column=2, value="petrova")

    ws.column_dimensions["A"].width = 35
    ws.column_dimensions["B"].width = 20

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="шаблон_импорта_учителей.xlsx",
    )


@bp.post("/teachers/import")
@login_required
def import_teachers():
    """Bulk import teachers from an uploaded Excel file."""
    if not _require_admin():
        return redirect(url_for("teacher.dashboard"))

    file = request.files.get("file")
    if not file or not file.filename:
        flash("Файл не выбран.", "danger")
        return redirect(url_for("admin.dashboard"))

    if not file.filename.lower().endswith((".xlsx", ".xls")):
        flash("Поддерживается только формат Excel (.xlsx).", "danger")
        return redirect(url_for("admin.dashboard"))

    try:
        wb = load_workbook(file, read_only=True, data_only=True)
    except Exception:
        flash("Не удалось прочитать файл. Убедитесь, что это корректный файл Excel (.xlsx).", "danger")
        return redirect(url_for("admin.dashboard"))

    ws = wb.active
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    wb.close()

    if not rows:
        flash("Файл пуст или содержит только заголовок.", "warning")
        return redirect(url_for("admin.dashboard"))

    created = 0
    skipped = 0
    errors = []
    passwords_info = []

    max_seq = (
        db.session.query(func.max(User.fs_teacher_seq))
        .filter(User.school_id == current_user.school_id, User.role == Role.TEACHER.value)
        .scalar()
    )
    next_seq = int(max_seq or 0) + 1

    for i, row in enumerate(rows, start=2):
        if not row or len(row) < 1:
            continue

        full_name = str(row[0] or "").strip()
        username = str(row[1] or "").strip() if len(row) > 1 else ""

        if not full_name:
            continue

        if not username:
            username = re.sub(r"[^a-zA-Zа-яА-ЯёЁ0-9]", "", full_name.split()[0].lower()) if full_name.split() else ""
            if not username:
                errors.append(f"Строка {i}: невозможно создать логин для \"{full_name}\"")
                skipped += 1
                continue

        if User.query.filter_by(username=username).first():
            errors.append(f"Строка {i}: логин \"{username}\" уже существует")
            skipped += 1
            continue

        pw = secrets.token_urlsafe(8)
        u = User(
            username=username,
            full_name=full_name,
            role=Role.TEACHER.value,
            school_id=current_user.school_id,
            is_active=True,
        )
        u.fs_teacher_seq = next_seq
        next_seq += 1
        u.set_password(pw)
        u.password_enc = encrypt_password(pw, current_app.config.get("PASSWORD_ENC_KEY", ""))
        db.session.add(u)
        passwords_info.append(f"{full_name} ({username}): {pw}")
        created += 1

    if created:
        db.session.commit()

    msg_parts = [f"Импорт завершён: создано {created}"]
    if skipped:
        msg_parts.append(f"пропущено {skipped}")
    flash(". ".join(msg_parts) + ".", "success" if created else "warning")

    if errors:
        flash("Ошибки: " + "; ".join(errors[:10]) + ("..." if len(errors) > 10 else ""), "warning")

    if passwords_info:
        flash("Пароли: " + " | ".join(passwords_info), "info")

    return redirect(url_for("admin.dashboard"))


@bp.get("/teachers/<int:user_id>/password")
@login_required
def get_teacher_password(user_id: int):
    """AJAX endpoint: return password as JSON."""
    if not _require_admin():
        return jsonify({"error": "Unauthorized"}), 403
    u = db.session.get(User, user_id)
    if not u or u.role != Role.TEACHER.value or u.school_id != current_user.school_id:
        return jsonify({"error": "Not found"}), 404
    pw = decrypt_password(u.password_enc, current_app.config.get("PASSWORD_ENC_KEY", ""))
    return jsonify({"username": u.username, "password": pw or "Недоступен"})


@bp.post("/teachers/<int:user_id>/password")
@login_required
def update_teacher_password(user_id: int):
    """Update teacher password."""
    if not _require_admin():
        flash("Доступ запрещен.", "danger")
        return redirect(url_for("admin.dashboard"))
    u = db.session.get(User, user_id)
    if not u or u.role != Role.TEACHER.value or u.school_id != current_user.school_id:
        flash("Пользователь не найден.", "danger")
        return redirect(url_for("admin.dashboard"))
    new_password = request.form.get("new_password", "").strip()
    if not new_password or len(new_password) < 4:
        flash("Пароль должен быть не менее 4 символов.", "danger")
        return redirect(url_for("admin.dashboard"))
    u.set_password(new_password)
    u.password_enc = encrypt_password(new_password, current_app.config.get("PASSWORD_ENC_KEY", ""))
    db.session.commit()
    flash(f"Пароль для {u.username} обновлен.", "success")
    return redirect(url_for("admin.dashboard"))


@bp.post("/teachers/<int:user_id>/edit")
@login_required
def edit_teacher(user_id: int):
    """Редактирование ФИО учителя."""
    if not _require_admin():
        return redirect(url_for("teacher.dashboard"))
    u = db.session.get(User, user_id)
    if not u or u.role != Role.TEACHER.value or u.school_id != current_user.school_id:
        flash("Учитель не найден.", "danger")
        return redirect(url_for("admin.dashboard"))
    full_name = request.form.get("full_name", "").strip()
    if not full_name:
        flash("ФИО не может быть пустым.", "danger")
        return redirect(url_for("admin.dashboard"))
    u.full_name = full_name
    db.session.commit()
    flash(f'ФИО обновлено: "{full_name}".', "success")
    return redirect(url_for("admin.dashboard"))


@bp.post("/teachers/<int:user_id>/delete")
@login_required
def delete_teacher(user_id: int):
    """Удаление учителя и всех его данных."""
    if not _require_admin():
        return redirect(url_for("teacher.dashboard"))
    u = db.session.get(User, user_id)
    if not u or u.role != Role.TEACHER.value or u.school_id != current_user.school_id:
        flash("Учитель не найден.", "danger")
        return redirect(url_for("admin.dashboard"))
    
    teacher_name = u.full_name or u.username
    
    # Удаляем связанные данные
    GradeReport.query.filter_by(teacher_id=u.id).delete()
    ReportFile.query.filter_by(teacher_id=u.id).delete()
    
    # Удаляем связи учитель-класс и учитель-предмет
    teacher_subjects = TeacherSubject.query.filter_by(teacher_id=u.id).all()
    for ts in teacher_subjects:
        TeacherClass.query.filter_by(teacher_subject_id=ts.id).delete()
    TeacherSubject.query.filter_by(teacher_id=u.id).delete()
    
    # Снимаем классное руководство
    Class.query.filter_by(class_teacher_id=u.id).update({"class_teacher_id": None})
    
    db.session.delete(u)
    db.session.commit()
    flash(f'Учитель "{teacher_name}" удалён.', "success")
    return redirect(url_for("admin.dashboard"))


# ==============================================================================
# Class CRUD Routes
# ==============================================================================

@bp.post("/classes/create")
@login_required
def create_class():
    """Создание класса"""
    if not _require_admin():
        return redirect(url_for("teacher.dashboard"))
    name = request.form.get("name", "").strip()
    class_teacher_id = request.form.get("class_teacher_id")
    if not name:
        flash("Название класса обязательно.", "danger")
        return redirect(url_for("admin.dashboard") + "#classes-tab")
    # Проверяем дубликат
    existing = Class.query.filter_by(school_id=current_user.school_id, name=name).first()
    if existing:
        flash(f'Класс "{name}" уже существует.', "danger")
        return redirect(url_for("admin.dashboard") + "#classes-tab")
    cls = Class(name=name, school_id=current_user.school_id)
    if class_teacher_id:
        cls.class_teacher_id = int(class_teacher_id)
    db.session.add(cls)
    db.session.commit()
    flash(f'Класс "{name}" создан.', "success")
    return redirect(url_for("admin.dashboard") + "#classes-tab")


@bp.post("/classes/<int:class_id>/edit")
@login_required
def edit_class(class_id: int):
    """Редактирование класса"""
    if not _require_admin():
        return redirect(url_for("teacher.dashboard"))
    cls = db.session.get(Class, class_id)
    if not cls or cls.school_id != current_user.school_id:
        flash("Класс не найден.", "danger")
        return redirect(url_for("admin.dashboard") + "#classes-tab")
    name = request.form.get("name", "").strip()
    if name:
        # Проверяем, нет ли другого класса с таким именем
        dup = Class.query.filter_by(school_id=current_user.school_id, name=name).first()
        if dup and dup.id != class_id:
            flash(f'Класс "{name}" уже существует.', "danger")
            return redirect(url_for("admin.dashboard") + "#classes-tab")
        cls.name = name
    class_teacher_id = request.form.get("class_teacher_id")
    cls.class_teacher_id = int(class_teacher_id) if class_teacher_id else None
    db.session.commit()
    flash(f'Класс "{cls.name}" обновлён.', "success")
    return redirect(url_for("admin.dashboard") + "#classes-tab")


@bp.post("/classes/<int:class_id>/delete")
@login_required
def delete_class(class_id: int):
    """Удаление класса"""
    if not _require_admin():
        return redirect(url_for("teacher.dashboard"))
    cls = db.session.get(Class, class_id)
    if not cls or cls.school_id != current_user.school_id:
        flash("Класс не найден.", "danger")
        return redirect(url_for("admin.dashboard") + "#classes-tab")
    db.session.delete(cls)
    db.session.commit()
    flash(f'Класс "{cls.name}" удалён.', "success")
    return redirect(url_for("admin.dashboard") + "#classes-tab")


# ==============================================================================
# Grades Overview Routes
# ==============================================================================

@bp.get("/grades")
@login_required
def grades_overview():
    """Обзор оценок: список классов со сводкой"""
    if not _require_admin():
        return redirect(url_for("teacher.dashboard"))
    
    # Параметры фильтрации
    period_type = request.args.get("period_type", "quarter")
    period_number = int(request.args.get("period_number", 2))
    
    # Получаем все отчёты школы
    reports = GradeReport.query.filter_by(
        school_id=current_user.school_id,
        period_type=period_type,
        period_number=period_number
    ).all()
    
    # Группируем по классам
    classes_data = {}
    for report in reports:
        class_name = report.class_name
        if class_name not in classes_data:
            classes_data[class_name] = {
                "class_name": class_name,
                "subjects": [],
                "students_count": 0,
                "quality_percent": 0,
                "success_percent": 0
            }
        
        classes_data[class_name]["subjects"].append(report.subject_name)
        
        # Собираем статистику
        if report.grades_json:
            try:
                grades_data = json.loads(report.grades_json)
                classes_data[class_name]["students_count"] = max(
                    classes_data[class_name]["students_count"],
                    grades_data.get("total_students", 0)
                )
            except json.JSONDecodeError:
                pass
    
    # Сортируем классы
    sorted_classes = sorted(classes_data.values(), key=lambda x: x["class_name"])
    
    # Группировка по аккордеонам (1-4, 5-9, 10-11)
    classes_by_accordion = {"1-4": [], "5-9": [], "10-11": []}
    for cls in sorted_classes:
        group = _class_accordion_group(cls["class_name"])
        classes_by_accordion[group].append(cls)
    
    return render_template(
        "admin/grades_overview.html",
        classes=sorted_classes,
        classes_by_accordion=classes_by_accordion,
        period_type=period_type,
        period_number=period_number
    )


@bp.get("/grades/class/<class_name>")
@login_required
def grades_class(class_name: str):
    """Сводная таблица оценок класса: ученик × предмет"""
    if not _require_admin():
        return redirect(url_for("teacher.dashboard"))
    
    # Параметры
    period_type = request.args.get("period_type", "quarter")
    period_number = int(request.args.get("period_number", 2))
    
    # Получаем все отчёты для этого класса
    reports = GradeReport.query.filter_by(
        school_id=current_user.school_id,
        class_name=class_name,
        period_type=period_type,
        period_number=period_number
    ).all()
    
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
                pass
    
    # Формируем списки для шаблона
    subjects_list = sorted(subjects)
    students_list = []
    
    for name in sorted(students_data.keys()):
        grades = students_data[name]
        
        # Подсчёт 5, 4, 3 по строке (ученику)
        row_count_5 = sum(1 for g in grades.values() if g.get("grade") == 5)
        row_count_4 = sum(1 for g in grades.values() if g.get("grade") == 4)
        row_count_3 = sum(1 for g in grades.values() if g.get("grade") == 3)
        
        students_list.append({
            "name": name,
            "grades": grades,
            "count_5": row_count_5,
            "count_4": row_count_4,
            "count_3": row_count_3,
        })
    
    # Подсчёт по столбцам (предметам): кол-во 5,4,3 + качество + успеваемость
    subject_stats = {}
    for subj in subjects_list:
        s5 = s4 = s3 = s2 = 0
        total_in_subj = 0
        for student in students_list:
            gi = student["grades"].get(subj, {})
            g = gi.get("grade")
            if g is not None:
                total_in_subj += 1
                if g == 5:
                    s5 += 1
                elif g == 4:
                    s4 += 1
                elif g == 3:
                    s3 += 1
                else:
                    s2 += 1
        quality = round((s5 + s4) / total_in_subj * 100, 1) if total_in_subj else 0
        success = round((s5 + s4 + s3) / total_in_subj * 100, 1) if total_in_subj else 0
        subject_stats[subj] = {
            "count_5": s5, "count_4": s4, "count_3": s3, "count_2": s2,
            "total": total_in_subj,
            "quality_percent": quality,
            "success_percent": success
        }
    
    # Считаем общую статистику класса
    total_students = len(students_data)
    grades_count = {"5": 0, "4": 0, "3": 0, "2": 0}
    
    # Считаем по среднему баллу (для карточек сверху)
    for student in students_list:
        all_grades = [g.get("grade") for g in student["grades"].values() if g.get("grade")]
        if all_grades:
            avg = sum(all_grades) / len(all_grades)
            if avg >= 4.5:
                grades_count["5"] += 1
            elif avg >= 3.5:
                grades_count["4"] += 1
            elif avg >= 2.5:
                grades_count["3"] += 1
            else:
                grades_count["2"] += 1
    
    quality_percent = 0
    success_percent = 0
    if total_students > 0:
        quality_percent = round((grades_count["5"] + grades_count["4"]) / total_students * 100, 1)
        success_percent = round((grades_count["5"] + grades_count["4"] + grades_count["3"]) / total_students * 100, 1)
    
    return render_template(
        "admin/grades_class.html",
        class_name=class_name,
        subjects=subjects_list,
        students=students_list,
        subject_stats=subject_stats,
        period_type=period_type,
        period_number=period_number,
        summary={
            "total_students": total_students,
            "quality_percent": quality_percent,
            "success_percent": success_percent,
            "grades_count": grades_count
        }
    )


@bp.get("/analytics")
@login_required
def analytics_home():
    """
    Аналитика: 3 вкладки — СОР / СОЧ / Оценки.
    По каждому предмету — карточка с таблицей по классам.
    Структура копирует reference проект.
    """
    if not _require_admin():
        return redirect(url_for("teacher.dashboard"))
    
    # Параметры
    period_type = request.args.get("period_type", "quarter")
    period_number = int(request.args.get("period_number", 2))
    
    # Получаем все отчёты школы за период
    reports = GradeReport.query.filter_by(
        school_id=current_user.school_id,
        period_type=period_type,
        period_number=period_number
    ).all()
    
    # Группируем по предмету
    # subjects_data_sor:    { subject_name -> [{ class_name, sor_list, teacher, has_data }] }
    # subjects_data_soch:   { subject_name -> [{ class_name, count_5..2, total, quality, success_rate, teacher, has_data }] }
    # subjects_data_grades: { subject_name -> [{ class_name, count_5..2, total, quality, success_rate, teacher, has_data }] }
    
    subjects_data_sor = {}
    subjects_data_soch = {}
    subjects_data_grades = {}
    
    for report in reports:
        subj = report.subject_name
        cls = report.class_name
        teacher_name = ""
        # Получаем имя учителя
        if report.teacher:
            teacher_name = report.teacher.full_name or report.teacher.username
        
        # --- СОР / СОЧ из analytics_json ---
        if report.analytics_json:
            try:
                analytics = json.loads(report.analytics_json)
                
                # СОР
                sor_list = analytics.get("sor", [])
                # Добавляем total, quality, success_rate к каждому СОР если нет
                for sor in sor_list:
                    total = (sor.get("count_5", 0) + sor.get("count_4", 0) +
                             sor.get("count_3", 0) + sor.get("count_2", 0))
                    sor["total"] = total
                    if total > 0:
                        sor["quality"] = round((sor.get("count_5", 0) + sor.get("count_4", 0)) / total * 100, 1)
                        sor["success_rate"] = round((total - sor.get("count_2", 0)) / total * 100, 1)
                    else:
                        sor["quality"] = None
                        sor["success_rate"] = None
                
                if subj not in subjects_data_sor:
                    subjects_data_sor[subj] = []
                subjects_data_sor[subj].append({
                    "class_name": cls,
                    "sor_list": sor_list,
                    "teacher": teacher_name,
                    "has_data": len(sor_list) > 0
                })
                
                # СОЧ
                soch = analytics.get("soch", {})
                if soch:
                    s5 = soch.get("count_5", 0)
                    s4 = soch.get("count_4", 0)
                    s3 = soch.get("count_3", 0)
                    s2 = soch.get("count_2", 0)
                    total = s5 + s4 + s3 + s2
                    if subj not in subjects_data_soch:
                        subjects_data_soch[subj] = []
                    subjects_data_soch[subj].append({
                        "class_name": cls,
                        "count_5": s5, "count_4": s4, "count_3": s3, "count_2": s2,
                        "total": total,
                        "quality": round((s5 + s4) / total * 100, 1) if total else None,
                        "success_rate": round((total - s2) / total * 100, 1) if total else None,
                        "teacher": teacher_name,
                        "has_data": total > 0
                    })
            except json.JSONDecodeError:
                pass
        
        # --- Оценки из grades_json ---
        if report.grades_json:
            try:
                grades_data = json.loads(report.grades_json)
                s5 = s4 = s3 = s2 = 0
                for student in grades_data.get("students", []):
                    g = student.get("grade")
                    if g == 5: s5 += 1
                    elif g == 4: s4 += 1
                    elif g == 3: s3 += 1
                    elif g is not None and g <= 2: s2 += 1
                total = s5 + s4 + s3 + s2
                quality = grades_data.get("quality_percent") or (round((s5 + s4) / total * 100, 1) if total else None)
                success = grades_data.get("success_percent") or (round((total - s2) / total * 100, 1) if total else None)
                
                if subj not in subjects_data_grades:
                    subjects_data_grades[subj] = []
                subjects_data_grades[subj].append({
                    "class_name": cls,
                    "count_5": s5, "count_4": s4, "count_3": s3, "count_2": s2,
                    "total": total,
                    "quality": quality,
                    "success_rate": success,
                    "teacher": teacher_name,
                    "has_data": total > 0
                })
            except json.JSONDecodeError:
                pass
    
    # Сортируем классы внутри каждого предмета
    for subj_data in [subjects_data_sor, subjects_data_soch, subjects_data_grades]:
        for subj in subj_data:
            subj_data[subj].sort(key=lambda x: x["class_name"])
    
    # Периоды для фильтра
    periods = [
        {"type": "quarter", "number": i, "name": f"{i} четверть"} for i in range(1, 5)
    ] + [
        {"type": "semester", "number": i, "name": f"{i} полугодие"} for i in range(1, 3)
    ]

    return render_template(
        "admin/analytics_home.html",
        subjects_data_sor=dict(sorted(subjects_data_sor.items())),
        subjects_data_soch=dict(sorted(subjects_data_soch.items())),
        subjects_data_grades=dict(sorted(subjects_data_grades.items())),
        period_type=period_type,
        period_number=period_number,
        periods=periods
    )


def _apply_analytics_filters(subjects_data_sor, subjects_data_soch, subjects_data_grades,
                             filter_subject, filter_class, filter_teacher):
    """Применяет фильтры к данным аналитики (subject, class, teacher)."""
    def _filter_item(item):
        if filter_class and item.get("class_name") != filter_class:
            return False
        if filter_teacher and (item.get("teacher") or "").strip() != filter_teacher:
            return False
        return True

    def _filter_dict(data_dict):
        result = {}
        for subj, items in data_dict.items():
            if filter_subject and subj != filter_subject:
                continue
            filtered = [i for i in items if _filter_item(i)]
            if filtered:
                result[subj] = filtered
        return result

    return (
        _filter_dict(subjects_data_sor),
        _filter_dict(subjects_data_soch),
        _filter_dict(subjects_data_grades),
    )


@bp.get("/analytics/download-excel")
@login_required
def download_analytics_excel():
    """Скачать аналитику СОР/СОЧ/Оценки в Excel (с учётом фильтров subject/class/teacher)"""
    if not _require_admin():
        return redirect(url_for("teacher.dashboard"))
    
    period_type = request.args.get("period_type", "quarter")
    period_number = int(request.args.get("period_number", 2))
    filter_subject = request.args.get("subject", "").strip() or None
    filter_class = request.args.get("class", "").strip() or None
    filter_teacher = request.args.get("teacher", "").strip() or None
    period_name = f"{period_number} {'четверть' if period_type == 'quarter' else 'полугодие'}"
    
    reports = GradeReport.query.filter_by(
        school_id=current_user.school_id,
        period_type=period_type,
        period_number=period_number
    ).all()
    
    subjects_data_sor = {}
    subjects_data_soch = {}
    subjects_data_grades = {}
    
    for report in reports:
        subj = report.subject_name
        cls = report.class_name
        teacher_name = ""
        if report.teacher:
            teacher_name = report.teacher.full_name or report.teacher.username
        
        if report.analytics_json:
            try:
                analytics = json.loads(report.analytics_json)
                sor_list = analytics.get("sor", [])
                for sor in sor_list:
                    total = (sor.get("count_5", 0) + sor.get("count_4", 0) +
                             sor.get("count_3", 0) + sor.get("count_2", 0))
                    sor["total"] = total
                    if total > 0:
                        sor["quality"] = round((sor.get("count_5", 0) + sor.get("count_4", 0)) / total * 100, 1)
                        sor["success_rate"] = round((total - sor.get("count_2", 0)) / total * 100, 1)
                    else:
                        sor["quality"] = None
                        sor["success_rate"] = None
                
                if subj not in subjects_data_sor:
                    subjects_data_sor[subj] = []
                subjects_data_sor[subj].append({
                    "class_name": cls, "sor_list": sor_list, "teacher": teacher_name, "has_data": len(sor_list) > 0
                })
                
                soch = analytics.get("soch", {})
                if soch:
                    s5 = soch.get("count_5", 0)
                    s4 = soch.get("count_4", 0)
                    s3 = soch.get("count_3", 0)
                    s2 = soch.get("count_2", 0)
                    total = s5 + s4 + s3 + s2
                    if subj not in subjects_data_soch:
                        subjects_data_soch[subj] = []
                    subjects_data_soch[subj].append({
                        "class_name": cls,
                        "count_5": s5, "count_4": s4, "count_3": s3, "count_2": s2,
                        "total": total,
                        "quality": round((s5 + s4) / total * 100, 1) if total else None,
                        "success_rate": round((total - s2) / total * 100, 1) if total else None,
                        "teacher": teacher_name, "has_data": total > 0
                    })
            except json.JSONDecodeError:
                pass
        
        if report.grades_json:
            try:
                grades_data = json.loads(report.grades_json)
                s5 = s4 = s3 = s2 = 0
                for student in grades_data.get("students", []):
                    g = student.get("grade")
                    if g == 5: s5 += 1
                    elif g == 4: s4 += 1
                    elif g == 3: s3 += 1
                    elif g is not None and g <= 2: s2 += 1
                total = s5 + s4 + s3 + s2
                quality = grades_data.get("quality_percent") or (round((s5 + s4) / total * 100, 1) if total else None)
                success = grades_data.get("success_percent") or (round((total - s2) / total * 100, 1) if total else None)
                
                if subj not in subjects_data_grades:
                    subjects_data_grades[subj] = []
                subjects_data_grades[subj].append({
                    "class_name": cls,
                    "count_5": s5, "count_4": s4, "count_3": s3, "count_2": s2,
                    "total": total, "quality": quality, "success_rate": success,
                    "teacher": teacher_name, "has_data": total > 0
                })
            except json.JSONDecodeError:
                pass
    
    for subj_data in [subjects_data_sor, subjects_data_soch, subjects_data_grades]:
        for subj in subj_data:
            subj_data[subj].sort(key=lambda x: x["class_name"])
    
    # Применяем фильтры (subject, class, teacher)
    if filter_subject or filter_class or filter_teacher:
        subjects_data_sor, subjects_data_soch, subjects_data_grades = _apply_analytics_filters(
            subjects_data_sor, subjects_data_soch, subjects_data_grades,
            filter_subject, filter_class, filter_teacher
        )
    
    styles = _create_excel_styles()
    wb = Workbook()
    
    def _write_sor_sheet():
        ws = wb.active
        ws.title = "СОР"[:31]
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=10)
        ws["A1"] = f"Аналитика СОР ({period_name})"
        ws["A1"].font = Font(bold=True, size=14)
        ws["A1"].alignment = Alignment(horizontal="center")
        row = 3
        for subj, data_list in sorted(subjects_data_sor.items()):
            ws.cell(row=row, column=1, value=subj).font = Font(bold=True, size=12)
            row += 1
            headers = ["Класс", "СОР", "5", "4", "3", "2", "Всего", "Качество %", "Успеваемость %", "Учитель"]
            for col, h in enumerate(headers, 1):
                c = ws.cell(row=row, column=col, value=h)
                c.font = styles["header_font"]
                c.fill = styles["header_fill"]
                c.border = styles["border"]
            row += 1
            for item in data_list:
                if item["sor_list"]:
                    for sor in item["sor_list"]:
                        ws.cell(row=row, column=1, value=item["class_name"]).border = styles["border"]
                        ws.cell(row=row, column=2, value=sor.get("name", "-")).border = styles["border"]
                        ws.cell(row=row, column=3, value=sor.get("count_5", 0)).border = styles["border"]
                        ws.cell(row=row, column=4, value=sor.get("count_4", 0)).border = styles["border"]
                        ws.cell(row=row, column=5, value=sor.get("count_3", 0)).border = styles["border"]
                        ws.cell(row=row, column=6, value=sor.get("count_2", 0)).border = styles["border"]
                        ws.cell(row=row, column=7, value=sor.get("total", 0)).border = styles["border"]
                        ws.cell(row=row, column=8, value=sor.get("quality") or "-").border = styles["border"]
                        ws.cell(row=row, column=9, value=sor.get("success_rate") or "-").border = styles["border"]
                        ws.cell(row=row, column=10, value=item["teacher"] or "-").border = styles["border"]
                        row += 1
                else:
                    ws.cell(row=row, column=1, value=item["class_name"]).border = styles["border"]
                    for col in range(2, 10):
                        ws.cell(row=row, column=col, value="-").border = styles["border"]
                    ws.cell(row=row, column=10, value=item["teacher"] or "-").border = styles["border"]
                    row += 1
            row += 2
    
    def _write_soch_sheet():
        ws = wb.create_sheet(title="СОЧ"[:31])
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=9)
        ws["A1"] = f"Аналитика СОЧ ({period_name})"
        ws["A1"].font = Font(bold=True, size=14)
        ws["A1"].alignment = Alignment(horizontal="center")
        row = 3
        for subj, data_list in sorted(subjects_data_soch.items()):
            ws.cell(row=row, column=1, value=subj).font = Font(bold=True, size=12)
            row += 1
            headers = ["Класс", "5", "4", "3", "2", "Всего", "Качество %", "Успеваемость %", "Учитель"]
            for col, h in enumerate(headers, 1):
                c = ws.cell(row=row, column=col, value=h)
                c.font = styles["header_font"]
                c.fill = styles["header_fill"]
                c.border = styles["border"]
            row += 1
            for item in data_list:
                ws.cell(row=row, column=1, value=item["class_name"]).border = styles["border"]
                ws.cell(row=row, column=2, value=item["count_5"]).border = styles["border"]
                ws.cell(row=row, column=3, value=item["count_4"]).border = styles["border"]
                ws.cell(row=row, column=4, value=item["count_3"]).border = styles["border"]
                ws.cell(row=row, column=5, value=item["count_2"]).border = styles["border"]
                ws.cell(row=row, column=6, value=item["total"]).border = styles["border"]
                ws.cell(row=row, column=7, value=item["quality"] or "-").border = styles["border"]
                ws.cell(row=row, column=8, value=item["success_rate"] or "-").border = styles["border"]
                ws.cell(row=row, column=9, value=item["teacher"] or "-").border = styles["border"]
                row += 1
            row += 2
    
    def _write_grades_sheet():
        ws = wb.create_sheet(title="Оценки"[:31])
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=9)
        ws["A1"] = f"Аналитика оценок ({period_name})"
        ws["A1"].font = Font(bold=True, size=14)
        ws["A1"].alignment = Alignment(horizontal="center")
        row = 3
        for subj, data_list in sorted(subjects_data_grades.items()):
            ws.cell(row=row, column=1, value=subj).font = Font(bold=True, size=12)
            row += 1
            headers = ["Класс", "5", "4", "3", "2", "Всего", "Качество %", "Успеваемость %", "Учитель"]
            for col, h in enumerate(headers, 1):
                c = ws.cell(row=row, column=col, value=h)
                c.font = styles["header_font"]
                c.fill = styles["header_fill"]
                c.border = styles["border"]
            row += 1
            for item in data_list:
                ws.cell(row=row, column=1, value=item["class_name"]).border = styles["border"]
                ws.cell(row=row, column=2, value=item["count_5"]).border = styles["border"]
                ws.cell(row=row, column=3, value=item["count_4"]).border = styles["border"]
                ws.cell(row=row, column=4, value=item["count_3"]).border = styles["border"]
                ws.cell(row=row, column=5, value=item["count_2"]).border = styles["border"]
                ws.cell(row=row, column=6, value=item["total"]).border = styles["border"]
                ws.cell(row=row, column=7, value=item["quality"] or "-").border = styles["border"]
                ws.cell(row=row, column=8, value=item["success_rate"] or "-").border = styles["border"]
                ws.cell(row=row, column=9, value=item["teacher"] or "-").border = styles["border"]
                row += 1
            row += 2
    
    _write_sor_sheet()
    _write_soch_sheet()
    _write_grades_sheet()
    
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    filename = f"Аналитика_СОР_СОЧ_{period_name.replace(' ', '_')}.xlsx"
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )


@bp.get("/class-teacher-report")
@login_required
def class_teacher_report():
    """
    Отчёт классного руководителя (структура из reference проекта).
    
    6 вкладок:
    - на 5 (отличники): Класс | № | ФИО | Классный руководитель
    - на 4 (хорошисты): Класс | № | ФИО | Классный руководитель
    - С одной 4: Класс | № | ФИО | Предмет | Учитель | Классный руководитель
    - на 3 (троечники): Класс | ФИО | Предмет 1..5 | Классный руководитель
    - С одной 3: Класс | № | ФИО | Предмет | Учитель | Классный руководитель
    - Неуспевающие: Класс | № | ФИО | Классный руководитель
    
    Данные сгруппированы по классам.
    """
    if not _require_admin():
        return redirect(url_for("teacher.dashboard"))
    
    # Параметры
    period_type = request.args.get("period_type", "quarter")
    period_number = int(request.args.get("period_number", 2))
    
    # Периоды для фильтра
    periods = [
        {"type": "quarter", "number": i, "name": f"{i} четверть"} for i in range(1, 5)
    ] + [
        {"type": "semester", "number": i, "name": f"{i} полугодие"} for i in range(1, 3)
    ]
    
    # Получаем все классы с данными
    class_names_query = db.session.query(GradeReport.class_name).filter_by(
        school_id=current_user.school_id,
        period_type=period_type,
        period_number=period_number
    ).distinct()
    class_names = sorted([c[0] for c in class_names_query.all()])
    
    # Собираем данные по каждому классу
    categories_data = {
        "excellent": [],     # на 5
        "good": [],          # на 4
        "one_4": [],         # С одной 4
        "satisfactory": [],  # на 3
        "one_3": [],         # С одной 3
        "poor": []           # Неуспевающие
    }
    
    for cls_name in class_names:
        # Получаем классного руководителя
        cls_obj = Class.query.filter_by(school_id=current_user.school_id, name=cls_name).first()
        class_teacher_name = ""
        if cls_obj and cls_obj.class_teacher:
            class_teacher_name = cls_obj.class_teacher.full_name or cls_obj.class_teacher.username
        
        # Получаем все отчёты для класса
        reports = GradeReport.query.filter_by(
            school_id=current_user.school_id,
            class_name=cls_name,
            period_type=period_type,
            period_number=period_number
        ).all()
        
        # Собираем оценки: name -> {subject_name: grade}
        # И учителей: subject_name -> teacher_name
        students_grades = {}   # name -> {subject_name: grade}
        subject_teachers = {}  # subject_name -> teacher_name
        
        for report in reports:
            teacher_name = ""
            if report.teacher:
                teacher_name = report.teacher.full_name or report.teacher.username
            subject_teachers[report.subject_name] = teacher_name
            
            if report.grades_json:
                try:
                    grades_data = json.loads(report.grades_json)
                    for student in grades_data.get("students", []):
                        name = student.get("name")
                        grade = student.get("grade")
                        if name and grade is not None:
                            if name not in students_grades:
                                students_grades[name] = {}
                            students_grades[name][report.subject_name] = grade
                except json.JSONDecodeError:
                    pass
        
        # Категоризируем
        excellent_students = []
        good_students = []
        one_4_students = []
        satisfactory_students = []
        troechniki_detailed = []
        one_3_students = []
        poor_students = []
        
        for name, subj_grades in sorted(students_grades.items()):
            grades_list = list(subj_grades.values())
            if not grades_list:
                continue
            
            count_5 = grades_list.count(5)
            count_4 = grades_list.count(4)
            count_3 = grades_list.count(3)
            count_2 = sum(1 for g in grades_list if g <= 2)
            
            if count_2 > 0:
                # Для неуспевающих: предметы с двойками
                failing_subjects = [
                    {"subject": s, "teacher": subject_teachers.get(s, "")}
                    for s, g in subj_grades.items() if g <= 2
                ]
                for fs in failing_subjects:
                    poor_students.append({
                        "student": name,
                        "subject": fs["subject"],
                        "teacher": fs["teacher"]
                    })
            elif all(g >= 5 for g in grades_list):
                excellent_students.append(name)
            elif count_4 == 1 and count_3 == 0:
                # С одной 4: найдём предмет
                subj_with_4 = next((s for s, g in subj_grades.items() if g == 4), "")
                one_4_students.append({
                    "student": name,
                    "subject": subj_with_4,
                    "teacher": subject_teachers.get(subj_with_4, "")
                })
            elif count_3 == 0:
                good_students.append(name)
            elif count_3 == 1:
                # С одной 3: найдём предмет
                subj_with_3 = next((s for s, g in subj_grades.items() if g == 3), "")
                one_3_students.append({
                    "student": name,
                    "subject": subj_with_3,
                    "teacher": subject_teachers.get(subj_with_3, "")
                })
            else:
                satisfactory_students.append(name)
                # Подробности: предметы с тройками
                subjects_with_3 = [
                    {"subject_name": s, "grade": g}
                    for s, g in subj_grades.items() if g == 3
                ]
                # Разделяем на первые 4 и остальные (для колонок)
                troechniki_detailed.append({
                    "student": name,
                    "subjects_1_4": subjects_with_3[:4],
                    "subjects_5": subjects_with_3[4:]
                })
        
        # Добавляем блок класса в каждую непустую категорию
        class_block = lambda students: {
            "class_name": cls_name,
            "class_teacher": class_teacher_name,
            "students": students
        }
        
        if excellent_students:
            categories_data["excellent"].append(class_block(excellent_students))
        if good_students:
            categories_data["good"].append(class_block(good_students))
        if one_4_students:
            categories_data["one_4"].append(class_block(one_4_students))
        if satisfactory_students:
            block = class_block(satisfactory_students)
            block["troechniki_detailed"] = troechniki_detailed
            categories_data["satisfactory"].append(block)
        if one_3_students:
            categories_data["one_3"].append(class_block(one_3_students))
        if poor_students:
            categories_data["poor"].append(class_block(poor_students))
    
    return render_template(
        "admin/class_teacher_report.html",
        categories_data=categories_data,
        period_type=period_type,
        period_number=period_number,
        periods=periods
    )


# ==============================================================================
# Excel Export Routes
# ==============================================================================

def _create_excel_styles():
    """Создание стилей для Excel"""
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="4F81BD", end_color="4F81BD", fill_type="solid")
    header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    
    border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )
    
    # Заливки для оценок
    grade_fills = {
        5: PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid"),  # Зеленый
        4: PatternFill(start_color="BDD7EE", end_color="BDD7EE", fill_type="solid"),  # Голубой
        3: PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid"),  # Желтый
        2: PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid"),  # Красный
    }
    
    # Заливка для пограничных оценок
    border_highlight_fill = PatternFill(start_color="FFF3CD", end_color="FFF3CD", fill_type="solid")
    
    # Заливки для строк/столбцов подсчёта
    count_5_fill = PatternFill(start_color="D1FAE5", end_color="D1FAE5", fill_type="solid")
    count_4_fill = PatternFill(start_color="DBEAFE", end_color="DBEAFE", fill_type="solid")
    count_3_fill = PatternFill(start_color="FEF3C7", end_color="FEF3C7", fill_type="solid")
    
    # Заливки для качества/успеваемости
    quality_fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
    success_fill = PatternFill(start_color="BDD7EE", end_color="BDD7EE", fill_type="solid")
    
    return {
        "header_font": header_font,
        "header_fill": header_fill,
        "header_alignment": header_alignment,
        "border": border,
        "grade_fills": grade_fills,
        "border_highlight_fill": border_highlight_fill,
        "count_5_fill": count_5_fill,
        "count_4_fill": count_4_fill,
        "count_3_fill": count_3_fill,
        "quality_fill": quality_fill,
        "success_fill": success_fill,
    }


def _is_border_percent(pct):
    """Проверка: пограничный процент (37-39%, 61-64%, 82-84%)"""
    if pct is None:
        return False
    return (37 <= pct <= 39) or (61 <= pct <= 64) or (82 <= pct <= 84)


@bp.get("/grades/class/<class_name>/download-excel")
@login_required
def download_grades_class_excel(class_name: str):
    """Скачать сводную таблицу оценок класса в Excel"""
    if not _require_admin():
        return redirect(url_for("teacher.dashboard"))
    
    # Параметры
    period_type = request.args.get("period_type", "quarter")
    period_number = int(request.args.get("period_number", 2))
    
    # Получаем все отчёты для этого класса
    reports = GradeReport.query.filter_by(
        school_id=current_user.school_id,
        class_name=class_name,
        period_type=period_type,
        period_number=period_number
    ).all()
    
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
                pass
    
    # Формируем списки
    subjects_list = sorted(subjects)
    students_list = []
    
    for name in sorted(students_data.keys()):
        grades = students_data[name]
        row_count_5 = sum(1 for g in grades.values() if g.get("grade") == 5)
        row_count_4 = sum(1 for g in grades.values() if g.get("grade") == 4)
        row_count_3 = sum(1 for g in grades.values() if g.get("grade") == 3)
        
        students_list.append({
            "name": name,
            "grades": grades,
            "count_5": row_count_5,
            "count_4": row_count_4,
            "count_3": row_count_3,
        })
    
    # Статистика по предметам (столбцам)
    subject_stats = {}
    for subj in subjects_list:
        s5 = s4 = s3 = s2 = 0
        total_in_subj = 0
        for student in students_list:
            gi = student["grades"].get(subj, {})
            g = gi.get("grade")
            if g is not None:
                total_in_subj += 1
                if g == 5: s5 += 1
                elif g == 4: s4 += 1
                elif g == 3: s3 += 1
                else: s2 += 1
        quality = round((s5 + s4) / total_in_subj * 100, 1) if total_in_subj else 0
        success = round((s5 + s4 + s3) / total_in_subj * 100, 1) if total_in_subj else 0
        subject_stats[subj] = {"count_5": s5, "count_4": s4, "count_3": s3, "count_2": s2,
                                "total": total_in_subj, "quality_percent": quality, "success_percent": success}
    
    # Создаём Excel
    wb = Workbook()
    ws = wb.active
    ws.title = f"Оценки {class_name}"
    
    styles = _create_excel_styles()
    bold_font = Font(bold=True)
    center_align = Alignment(horizontal="center")
    
    # Заголовок
    period_name = f"{period_number} {'четверть' if period_type == 'quarter' else 'полугодие'}"
    total_cols = len(subjects_list) + 5  # №, ФИО, предметы..., Кол5, Кол4, Кол3
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=total_cols)
    ws["A1"] = f"Сводная таблица оценок: {class_name} ({period_name})"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A1"].alignment = Alignment(horizontal="center")
    
    # Шапка таблицы
    header_row = 3
    headers = ["№", "ФИО ученика"] + subjects_list + ["Кол-во 5", "Кол-во 4", "Кол-во 3"]
    
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=header_row, column=col, value=header)
        cell.font = styles["header_font"]
        cell.fill = styles["header_fill"]
        cell.alignment = styles["header_alignment"]
        cell.border = styles["border"]
    
    # Столбцы подсчёта — цветные заголовки
    col_5_idx = len(subjects_list) + 3
    col_4_idx = len(subjects_list) + 4
    col_3_idx = len(subjects_list) + 5
    ws.cell(row=header_row, column=col_5_idx).fill = styles["count_5_fill"]
    ws.cell(row=header_row, column=col_5_idx).font = Font(bold=True)
    ws.cell(row=header_row, column=col_4_idx).fill = styles["count_4_fill"]
    ws.cell(row=header_row, column=col_4_idx).font = Font(bold=True)
    ws.cell(row=header_row, column=col_3_idx).fill = styles["count_3_fill"]
    ws.cell(row=header_row, column=col_3_idx).font = Font(bold=True)
    
    # Данные учеников
    for row_idx, student in enumerate(students_list, header_row + 1):
        # Номер
        cell = ws.cell(row=row_idx, column=1, value=row_idx - header_row)
        cell.border = styles["border"]
        cell.alignment = center_align
        
        # ФИО
        cell = ws.cell(row=row_idx, column=2, value=student["name"])
        cell.border = styles["border"]
        
        # Оценки по предметам
        for col_idx, subject in enumerate(subjects_list, 3):
            grade_info = student["grades"].get(subject, {})
            grade = grade_info.get("grade")
            percent = grade_info.get("percent")
            
            if grade:
                # Показываем оценку и процент
                cell_value = f"{grade} ({percent}%)" if percent else str(grade)
                cell = ws.cell(row=row_idx, column=col_idx, value=cell_value)
                
                # Подсветка пограничных процентов
                if _is_border_percent(percent):
                    cell.fill = styles["border_highlight_fill"]
                    cell.font = Font(bold=True, color="B45309")
            else:
                cell = ws.cell(row=row_idx, column=col_idx, value="—")
            
            cell.border = styles["border"]
            cell.alignment = center_align
        
        # Кол-во 5, 4, 3 по строке
        cell = ws.cell(row=row_idx, column=col_5_idx, value=student["count_5"])
        cell.border = styles["border"]
        cell.alignment = center_align
        cell.fill = styles["count_5_fill"]
        cell.font = bold_font
        
        cell = ws.cell(row=row_idx, column=col_4_idx, value=student["count_4"])
        cell.border = styles["border"]
        cell.alignment = center_align
        cell.fill = styles["count_4_fill"]
        cell.font = bold_font
        
        cell = ws.cell(row=row_idx, column=col_3_idx, value=student["count_3"])
        cell.border = styles["border"]
        cell.alignment = center_align
        cell.fill = styles["count_3_fill"]
        cell.font = bold_font
    
    # --- Итоговые строки ---
    footer_start = header_row + len(students_list) + 1
    
    # Строка: Кол-во «5» по столбцам
    row = footer_start
    ws.cell(row=row, column=2, value='Кол-во «5»').font = bold_font
    for col_idx, subj in enumerate(subjects_list, 3):
        cell = ws.cell(row=row, column=col_idx, value=subject_stats[subj]["count_5"])
        cell.border = styles["border"]
        cell.alignment = center_align
        cell.fill = styles["count_5_fill"]
        cell.font = bold_font
    cell = ws.cell(row=row, column=col_5_idx, value=sum(s["count_5"] for s in students_list))
    cell.border = styles["border"]
    cell.alignment = center_align
    cell.fill = styles["count_5_fill"]
    cell.font = bold_font
    
    # Строка: Кол-во «4» по столбцам
    row = footer_start + 1
    ws.cell(row=row, column=2, value='Кол-во «4»').font = bold_font
    for col_idx, subj in enumerate(subjects_list, 3):
        cell = ws.cell(row=row, column=col_idx, value=subject_stats[subj]["count_4"])
        cell.border = styles["border"]
        cell.alignment = center_align
        cell.fill = styles["count_4_fill"]
        cell.font = bold_font
    cell = ws.cell(row=row, column=col_4_idx, value=sum(s["count_4"] for s in students_list))
    cell.border = styles["border"]
    cell.alignment = center_align
    cell.fill = styles["count_4_fill"]
    cell.font = bold_font
    
    # Строка: Кол-во «3» по столбцам
    row = footer_start + 2
    ws.cell(row=row, column=2, value='Кол-во «3»').font = bold_font
    for col_idx, subj in enumerate(subjects_list, 3):
        cell = ws.cell(row=row, column=col_idx, value=subject_stats[subj]["count_3"])
        cell.border = styles["border"]
        cell.alignment = center_align
        cell.fill = styles["count_3_fill"]
        cell.font = bold_font
    cell = ws.cell(row=row, column=col_3_idx, value=sum(s["count_3"] for s in students_list))
    cell.border = styles["border"]
    cell.alignment = center_align
    cell.fill = styles["count_3_fill"]
    cell.font = bold_font
    
    # Строка: Качество % по предмету
    row = footer_start + 3
    ws.cell(row=row, column=2, value='Качество %').font = bold_font
    for col_idx, subj in enumerate(subjects_list, 3):
        cell = ws.cell(row=row, column=col_idx, value=f"{subject_stats[subj]['quality_percent']}%")
        cell.border = styles["border"]
        cell.alignment = center_align
        cell.fill = styles["quality_fill"]
        cell.font = bold_font
    
    # Строка: Успеваемость % по предмету
    row = footer_start + 4
    ws.cell(row=row, column=2, value='Успеваемость %').font = bold_font
    for col_idx, subj in enumerate(subjects_list, 3):
        cell = ws.cell(row=row, column=col_idx, value=f"{subject_stats[subj]['success_percent']}%")
        cell.border = styles["border"]
        cell.alignment = center_align
        cell.fill = styles["success_fill"]
        cell.font = bold_font
    
    # Авто-ширина колонок
    ws.column_dimensions["A"].width = 5
    ws.column_dimensions["B"].width = 30
    for col in range(3, len(subjects_list) + 3):
        ws.column_dimensions[get_column_letter(col)].width = 16
    ws.column_dimensions[get_column_letter(col_5_idx)].width = 10
    ws.column_dimensions[get_column_letter(col_4_idx)].width = 10
    ws.column_dimensions[get_column_letter(col_3_idx)].width = 10
    
    # Сохраняем в память
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    
    filename = f"Оценки_{class_name}_{period_number}_{'четверть' if period_type == 'quarter' else 'полугодие'}.xlsx"
    
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )


@bp.get("/class-teacher-report/download-excel")
@login_required
def download_class_teacher_report_excel():
    """Скачать отчёт классного руководителя в Excel — все классы, по категориям"""
    if not _require_admin():
        return redirect(url_for("teacher.dashboard"))
    
    period_type = request.args.get("period_type", "quarter")
    period_number = int(request.args.get("period_number", 2))
    period_name = f"{period_number} {'четверть' if period_type == 'quarter' else 'полугодие'}"
    
    # --- Собираем данные (повторяем логику class_teacher_report) ---
    class_names_query = db.session.query(GradeReport.class_name).filter_by(
        school_id=current_user.school_id,
        period_type=period_type,
        period_number=period_number
    ).distinct()
    class_names = sorted([c[0] for c in class_names_query.all()])
    
    categories_data = {
        "excellent": [], "good": [], "one_4": [],
        "satisfactory": [], "one_3": [], "poor": []
    }
    
    for cls_name in class_names:
        cls_obj = Class.query.filter_by(school_id=current_user.school_id, name=cls_name).first()
        class_teacher_name = ""
        if cls_obj and cls_obj.class_teacher:
            class_teacher_name = cls_obj.class_teacher.full_name or cls_obj.class_teacher.username
        
        reports = GradeReport.query.filter_by(
            school_id=current_user.school_id,
            class_name=cls_name,
            period_type=period_type,
            period_number=period_number
        ).all()
        
        students_grades = {}
        subject_teachers = {}
        for report in reports:
            t_name = ""
            if report.teacher:
                t_name = report.teacher.full_name or report.teacher.username
            subject_teachers[report.subject_name] = t_name
            if report.grades_json:
                try:
                    gd = json.loads(report.grades_json)
                    for st in gd.get("students", []):
                        nm = st.get("name")
                        gr = st.get("grade")
                        if nm and gr is not None:
                            students_grades.setdefault(nm, {})[report.subject_name] = gr
                except json.JSONDecodeError:
                    pass
        
        excellent_s, good_s, one4_s, satisf_s, troech_d, one3_s, poor_s = [], [], [], [], [], [], []
        for name, sg in sorted(students_grades.items()):
            gl = list(sg.values())
            if not gl:
                continue
            c5, c4, c3, c2 = gl.count(5), gl.count(4), gl.count(3), sum(1 for g in gl if g<=2)
            if c2 > 0:
                for s_name, g_val in sg.items():
                    if g_val <= 2:
                        poor_s.append({"student": name, "subject": s_name, "teacher": subject_teachers.get(s_name, "")})
            elif all(g>=5 for g in gl):
                excellent_s.append(name)
            elif c4==1 and c3==0:
                subj4 = next((s for s,g in sg.items() if g==4), "")
                one4_s.append({"student": name, "subject": subj4, "teacher": subject_teachers.get(subj4,"")})
            elif c3==0:
                good_s.append(name)
            elif c3==1:
                subj3 = next((s for s,g in sg.items() if g==3), "")
                one3_s.append({"student": name, "subject": subj3, "teacher": subject_teachers.get(subj3,"")})
            else:
                satisf_s.append(name)
                subjs3 = [{"subject_name": s, "grade": g} for s,g in sg.items() if g==3]
                troech_d.append({"student": name, "subjects_1_4": subjs3[:4], "subjects_5": subjs3[4:]})
        
        def _block(students):
            return {"class_name": cls_name, "class_teacher": class_teacher_name, "students": students}
        if excellent_s: categories_data["excellent"].append(_block(excellent_s))
        if good_s: categories_data["good"].append(_block(good_s))
        if one4_s: categories_data["one_4"].append(_block(one4_s))
        if satisf_s:
            b = _block(satisf_s); b["troechniki_detailed"] = troech_d; categories_data["satisfactory"].append(b)
        if one3_s: categories_data["one_3"].append(_block(one3_s))
        if poor_s: categories_data["poor"].append(_block(poor_s))
    
    # --- Создаём Excel ---
    wb = Workbook()
    styles = _create_excel_styles()
    
    cat_meta = [
        ("excellent",     "на 5",        "C6EFCE", ["Класс", "№", "ФИО", "Классный руководитель"]),
        ("good",          "на 4",        "BDD7EE", ["Класс", "№", "ФИО", "Классный руководитель"]),
        ("one_4",         "С одной 4",   "D9EAD3", ["Класс", "№", "ФИО", "Предмет", "Учитель", "Классный руководитель"]),
        ("satisfactory",  "на 3",        "FFEB9C", ["Класс", "ФИО", "Предмет 1", "Предмет 2", "Предмет 3", "Предмет 4", "Предмет 5+", "Классный руководитель"]),
        ("one_3",         "С одной 3",   "FBE5D6", ["Класс", "№", "ФИО", "Предмет", "Учитель", "Классный руководитель"]),
        ("poor",          "Неуспевающие", "FFC7CE", ["Класс", "№", "ФИО", "Предмет", "Учитель", "Классный руководитель"]),
    ]
    
    first_sheet = True
    for cat_key, cat_label, cat_color, headers in cat_meta:
        blocks = categories_data[cat_key]
        total_count = sum(len(b["students"]) for b in blocks)
        sheet_name = f"{cat_label} ({total_count})"[:31]
        
        if first_sheet:
            ws = wb.active
            ws.title = sheet_name
            first_sheet = False
        else:
            ws = wb.create_sheet(title=sheet_name)
        
        # Заголовок
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
        c = ws.cell(row=1, column=1, value=f"Отчёт классных руководителей — {cat_label} ({period_name})")
        c.font = Font(bold=True, size=13)
        c.alignment = Alignment(horizontal="center")
        
        # Шапка таблицы
        for col, h in enumerate(headers, 1):
            cell = ws.cell(row=3, column=col, value=h)
            cell.font = styles["header_font"]
            cell.fill = PatternFill(start_color=cat_color, end_color=cat_color, fill_type="solid")
            cell.alignment = styles["header_alignment"]
            cell.border = styles["border"]
        
        row = 4
        if not blocks:
            ws.cell(row=row, column=1, value="Нет данных")
            continue
        
        for block in blocks:
            cls = block["class_name"]
            ct = block["class_teacher"]
            
            if cat_key == "satisfactory":
                details = block.get("troechniki_detailed", [])
                n = len(details)
                if n == 0:
                    continue
                # Класс (rowspan)
                ws.merge_cells(start_row=row, start_column=1, end_row=row+n-1, end_column=1)
                ws.cell(row=row, column=1, value=cls).font = Font(bold=True)
                ws.cell(row=row, column=1).border = styles["border"]
                ws.cell(row=row, column=1).alignment = Alignment(vertical="center", horizontal="center")
                # Кл. руководитель (rowspan)
                ws.merge_cells(start_row=row, start_column=8, end_row=row+n-1, end_column=8)
                ws.cell(row=row, column=8, value=ct).border = styles["border"]
                ws.cell(row=row, column=8).alignment = Alignment(vertical="center")
                
                for item in details:
                    ws.cell(row=row, column=2, value=item["student"]).border = styles["border"]
                    for i in range(4):
                        val = ""
                        if i < len(item["subjects_1_4"]):
                            s = item["subjects_1_4"][i]
                            val = f"{s['subject_name']} ({s['grade']})"
                        ws.cell(row=row, column=3+i, value=val or "—").border = styles["border"]
                    # 5+
                    val5 = ", ".join(f"{s['subject_name']} ({s['grade']})" for s in item.get("subjects_5", []))
                    ws.cell(row=row, column=7, value=val5 or "—").border = styles["border"]
                    row += 1
            
            elif cat_key in ("one_4", "one_3", "poor"):
                students = block["students"]
                n = len(students)
                ws.merge_cells(start_row=row, start_column=1, end_row=row+n-1, end_column=1)
                ws.cell(row=row, column=1, value=cls).font = Font(bold=True)
                ws.cell(row=row, column=1).border = styles["border"]
                ws.cell(row=row, column=1).alignment = Alignment(vertical="center", horizontal="center")
                ws.merge_cells(start_row=row, start_column=6, end_row=row+n-1, end_column=6)
                ws.cell(row=row, column=6, value=ct).border = styles["border"]
                ws.cell(row=row, column=6).alignment = Alignment(vertical="center")
                
                for idx, item in enumerate(students, 1):
                    ws.cell(row=row, column=2, value=idx).border = styles["border"]
                    ws.cell(row=row, column=3, value=item["student"]).border = styles["border"]
                    ws.cell(row=row, column=4, value=item["subject"]).border = styles["border"]
                    ws.cell(row=row, column=5, value=item["teacher"]).border = styles["border"]
                    row += 1
            
            else:  # excellent, good, poor
                students = block["students"]
                n = len(students)
                ws.merge_cells(start_row=row, start_column=1, end_row=row+n-1, end_column=1)
                ws.cell(row=row, column=1, value=cls).font = Font(bold=True)
                ws.cell(row=row, column=1).border = styles["border"]
                ws.cell(row=row, column=1).alignment = Alignment(vertical="center", horizontal="center")
                ws.merge_cells(start_row=row, start_column=4, end_row=row+n-1, end_column=4)
                ws.cell(row=row, column=4, value=ct).border = styles["border"]
                ws.cell(row=row, column=4).alignment = Alignment(vertical="center")
                
                for idx, student in enumerate(students, 1):
                    ws.cell(row=row, column=2, value=idx).border = styles["border"]
                    ws.cell(row=row, column=3, value=student).border = styles["border"]
                    row += 1
        
        # Авто-ширина
        for col_idx in range(1, len(headers)+1):
            ws.column_dimensions[get_column_letter(col_idx)].width = max(12, len(headers[col_idx-1]) + 5)
        ws.column_dimensions["C"].width = 35  # ФИО
    
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    
    filename = f"Отчёт_классных_руководителей_{period_name.replace(' ', '_')}.xlsx"
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )

