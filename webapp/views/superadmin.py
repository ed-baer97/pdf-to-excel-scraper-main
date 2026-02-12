import secrets

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy import func

from ..extensions import db
from ..models import Role, School, User, Class, GradeReport, ReportFile, TeacherSubject, TeacherClass, Subject
from ..security import decrypt_password, encrypt_password

bp = Blueprint("superadmin", __name__, url_prefix="/superadmin")


def _require_superadmin():
    if current_user.role != Role.SUPERADMIN.value:
        return False
    return True


@bp.get("/")
@login_required
def dashboard():
    if not _require_superadmin():
        return redirect(url_for("teacher.dashboard"))
    schools = School.query.order_by(School.created_at.desc()).all()
    admins = User.query.filter_by(role=Role.SCHOOL_ADMIN.value).order_by(User.created_at.desc()).all()
    return render_template(
        "superadmin/dashboard.html",
        schools=schools,
        admins=admins,
        ai_model_choices=AI_MODEL_CHOICES,
    )


@bp.post("/schools/create")
@login_required
def create_school():
    if not _require_superadmin():
        return redirect(url_for("teacher.dashboard"))
    name = request.form.get("name", "").strip()
    if not name:
        flash("Название школы обязательно.", "danger")
        return redirect(url_for("superadmin.dashboard"))
    s = School(name=name, is_active=True)
    db.session.add(s)
    db.session.commit()
    flash("Школа создана.", "success")
    return redirect(url_for("superadmin.dashboard"))


@bp.post("/schools/<int:school_id>/toggle")
@login_required
def toggle_school(school_id: int):
    if not _require_superadmin():
        return redirect(url_for("teacher.dashboard"))
    s = db.session.get(School, school_id)
    if not s:
        return redirect(url_for("superadmin.dashboard"))
    s.is_active = not s.is_active
    db.session.commit()
    flash("Статус школы обновлен.", "success")
    return redirect(url_for("superadmin.dashboard"))


@bp.post("/schools/<int:school_id>/delete")
@login_required
def delete_school(school_id: int):
    """Удаление школы и всех связанных данных."""
    if not _require_superadmin():
        return redirect(url_for("teacher.dashboard"))
    s = db.session.get(School, school_id)
    if not s:
        flash("Школа не найдена.", "danger")
        return redirect(url_for("superadmin.dashboard"))

    school_name = s.name

    # Удаляем всех пользователей школы и их данные
    users = User.query.filter_by(school_id=s.id).all()
    for u in users:
        GradeReport.query.filter_by(teacher_id=u.id).delete()
        ReportFile.query.filter_by(teacher_id=u.id).delete()
        teacher_subjects = TeacherSubject.query.filter_by(teacher_id=u.id).all()
        for ts in teacher_subjects:
            TeacherClass.query.filter_by(teacher_subject_id=ts.id).delete()
        TeacherSubject.query.filter_by(teacher_id=u.id).delete()

    # Удаляем отчёты, привязанные к школе напрямую
    GradeReport.query.filter_by(school_id=s.id).delete()

    # Удаляем предметы школы
    Subject.query.filter_by(school_id=s.id).delete()

    # Удаляем классы школы
    Class.query.filter_by(school_id=s.id).delete()

    # Удаляем пользователей школы
    User.query.filter_by(school_id=s.id).delete()

    # Удаляем саму школу
    db.session.delete(s)
    db.session.commit()
    flash(f'Школа "{school_name}" и все связанные данные удалены.', "success")
    return redirect(url_for("superadmin.dashboard"))


# Список моделей AI для выбора супер-админом (учителю не показывается)
AI_MODEL_CHOICES = [
    ("qwen-flash-character", "qwen-flash-character"),
    ("qwen-plus", "qwen-plus"),
    ("qwen-turbo", "qwen-turbo"),
]


@bp.post("/schools/<int:school_id>/ai_api_key")
@login_required
def update_ai_api_key(school_id: int):
    """Обновить AI API ключ школы"""
    if not _require_superadmin():
        return redirect(url_for("teacher.dashboard"))
    s = db.session.get(School, school_id)
    if not s:
        return redirect(url_for("superadmin.dashboard"))
    ai_api_key = request.form.get("ai_api_key", "").strip()
    s.ai_api_key = ai_api_key if ai_api_key else None
    db.session.commit()
    flash("AI API ключ обновлен.", "success")
    return redirect(url_for("superadmin.dashboard"))


@bp.post("/schools/<int:school_id>/ai_model")
@login_required
def update_ai_model(school_id: int):
    """Обновить модель AI для школы (выбор супер-админа)"""
    if not _require_superadmin():
        return redirect(url_for("teacher.dashboard"))
    s = db.session.get(School, school_id)
    if not s:
        return redirect(url_for("superadmin.dashboard"))
    ai_model = request.form.get("ai_model", "").strip()
    allowed = {v[0] for v in AI_MODEL_CHOICES}
    s.ai_model = ai_model if ai_model in allowed else (AI_MODEL_CHOICES[0][0])
    db.session.commit()
    flash("Модель AI обновлена.", "success")
    return redirect(url_for("superadmin.dashboard"))


@bp.post("/schools/<int:school_id>/toggle_cross_school")
@login_required
def toggle_cross_school(school_id: int):
    """Переключить разрешение на создание отчётов для других школ."""
    if not _require_superadmin():
        return redirect(url_for("teacher.dashboard"))
    s = db.session.get(School, school_id)
    if not s:
        return redirect(url_for("superadmin.dashboard"))
    s.allow_cross_school_reports = not s.allow_cross_school_reports
    db.session.commit()
    status = "включено" if s.allow_cross_school_reports else "выключено"
    flash(f"Разрешение на другие школы для «{s.name}»: {status}.", "success")
    return redirect(url_for("superadmin.dashboard"))


@bp.post("/admins/create")
@login_required
def create_admin():
    if not _require_superadmin():
        return redirect(url_for("teacher.dashboard"))
    school_id = int(request.form.get("school_id", "0") or "0")
    username = request.form.get("username", "").strip()
    full_name = request.form.get("full_name", "").strip()
    if not username or not school_id:
        flash("Нужны школа и логин админа.", "danger")
        return redirect(url_for("superadmin.dashboard"))
    if User.query.filter_by(username=username).first():
        flash("Такой логин уже существует.", "danger")
        return redirect(url_for("superadmin.dashboard"))
    school = db.session.get(School, school_id)
    if not school:
        flash("Школа не найдена.", "danger")
        return redirect(url_for("superadmin.dashboard"))

    pw = secrets.token_urlsafe(8)
    u = User(username=username, full_name=full_name or username, role=Role.SCHOOL_ADMIN.value, school_id=school_id, is_active=True)
    u.set_password(pw)
    u.password_enc = encrypt_password(pw, current_app.config.get("PASSWORD_ENC_KEY", ""))
    db.session.add(u)
    db.session.commit()
    flash(f"Админ создан. Пароль: {pw}", "success")
    return redirect(url_for("superadmin.dashboard"))


@bp.get("/admins/<int:user_id>/password")
@login_required
def get_admin_password(user_id: int):
    """AJAX endpoint: return password as JSON."""
    if not _require_superadmin():
        return jsonify({"error": "Unauthorized"}), 403
    u = db.session.get(User, user_id)
    if not u or u.role != Role.SCHOOL_ADMIN.value:
        return jsonify({"error": "Not found"}), 404
    pw = decrypt_password(u.password_enc, current_app.config.get("PASSWORD_ENC_KEY", ""))
    return jsonify({"username": u.username, "password": pw or "Недоступен"})


@bp.post("/admins/<int:user_id>/password")
@login_required
def update_admin_password(user_id: int):
    """Update admin password."""
    if not _require_superadmin():
        flash("Доступ запрещен.", "danger")
        return redirect(url_for("superadmin.dashboard"))
    u = db.session.get(User, user_id)
    if not u or u.role != Role.SCHOOL_ADMIN.value:
        flash("Пользователь не найден.", "danger")
        return redirect(url_for("superadmin.dashboard"))
    new_password = request.form.get("new_password", "").strip()
    if not new_password or len(new_password) < 4:
        flash("Пароль должен быть не менее 4 символов.", "danger")
        return redirect(url_for("superadmin.dashboard"))
    u.set_password(new_password)
    u.password_enc = encrypt_password(new_password, current_app.config.get("PASSWORD_ENC_KEY", ""))
    db.session.commit()
    flash(f"Пароль для {u.username} обновлен.", "success")
    return redirect(url_for("superadmin.dashboard"))


@bp.post("/admins/<int:user_id>/edit")
@login_required
def edit_admin(user_id: int):
    """Редактирование ФИО администратора."""
    if not _require_superadmin():
        return redirect(url_for("teacher.dashboard"))
    u = db.session.get(User, user_id)
    if not u or u.role != Role.SCHOOL_ADMIN.value:
        flash("Администратор не найден.", "danger")
        return redirect(url_for("superadmin.dashboard"))
    full_name = request.form.get("full_name", "").strip()
    if not full_name:
        flash("ФИО не может быть пустым.", "danger")
        return redirect(url_for("superadmin.dashboard"))
    u.full_name = full_name
    db.session.commit()
    flash(f'ФИО обновлено: "{full_name}".', "success")
    return redirect(url_for("superadmin.dashboard"))


@bp.post("/admins/<int:user_id>/delete")
@login_required
def delete_admin(user_id: int):
    """Удаление администратора школы."""
    if not _require_superadmin():
        return redirect(url_for("teacher.dashboard"))
    u = db.session.get(User, user_id)
    if not u or u.role != Role.SCHOOL_ADMIN.value:
        flash("Администратор не найден.", "danger")
        return redirect(url_for("superadmin.dashboard"))
    
    admin_name = u.full_name or u.username
    db.session.delete(u)
    db.session.commit()
    flash(f'Администратор "{admin_name}" удалён.', "success")
    return redirect(url_for("superadmin.dashboard"))


@bp.get("/schools/<int:school_id>")
@login_required
def school_detail(school_id: int):
    """Детальная страница школы: учителя, админы, классы, предметы"""
    if not _require_superadmin():
        return redirect(url_for("main.index"))
    school = db.session.get(School, school_id)
    if not school:
        flash("Школа не найдена.", "danger")
        return redirect(url_for("superadmin.dashboard"))

    admins = User.query.filter_by(
        role=Role.SCHOOL_ADMIN.value, school_id=school_id
    ).order_by(User.username).all()
    teachers = User.query.filter_by(
        role=Role.TEACHER.value, school_id=school_id
    ).order_by(User.username).all()
    classes = Class.query.filter_by(school_id=school_id).order_by(Class.name).all()

    # Предметы извлекаем из GradeReport (автоматически из скрапинга)
    subject_rows = db.session.query(
        GradeReport.subject_name,
        func.count(func.distinct(GradeReport.teacher_id)).label("teacher_count")
    ).filter_by(school_id=school_id).group_by(GradeReport.subject_name).order_by(GradeReport.subject_name).all()
    subjects = [{"name": row.subject_name, "teacher_count": row.teacher_count} for row in subject_rows]

    return render_template(
        "admin/school_detail.html",
        school=school,
        admins=admins,
        teachers=teachers,
        classes=classes,
        subjects=subjects,
    )

