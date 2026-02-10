from flask import Blueprint, redirect, render_template, request, url_for, flash
from flask_login import login_user, logout_user

from ..extensions import db
from ..models import User

bp = Blueprint("auth", __name__, url_prefix="/auth")


@bp.get("/login")
def login():
    return redirect(url_for("main.index"))


@bp.post("/login")
def login_post():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    u: User | None = User.query.filter_by(username=username).first()
    if not u or not u.is_active or not u.check_password(password):
        flash("Неверный логин/пароль или доступ отключен.", "danger")
        return redirect(url_for("main.index"))

    # Учителя входят только через десктопное приложение
    if u.role == "teacher":
        flash("Учителя входят только через десктопное приложение. Скачайте Mektep Desktop и войдите там.", "warning")
        return redirect(url_for("main.index"))

    # School access toggle (superadmin can open/close school).
    if u.school_id and u.school and not u.school.is_active:
        flash("Доступ школы закрыт супер-админом.", "danger")
        return redirect(url_for("main.index"))

    login_user(u)
    if u.role == "superadmin":
        return redirect(url_for("superadmin.dashboard"))
    if u.role == "school_admin":
        return redirect(url_for("admin.dashboard"))
    return redirect(url_for("teacher.dashboard"))


@bp.post("/logout")
def logout():
    logout_user()
    return redirect(url_for("main.index"))

