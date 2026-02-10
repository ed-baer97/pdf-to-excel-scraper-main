from flask import Blueprint, redirect, render_template, request, url_for, flash

from ..extensions import db
from ..models import Role, User

bp = Blueprint("setup", __name__, url_prefix="/setup")


@bp.get("/")
def setup():
    # Allow setup only if no superadmin exists.
    existing = User.query.filter_by(role=Role.SUPERADMIN.value).first()
    if existing:
        return redirect(url_for("auth.login"))
    return render_template("setup/setup.html")


@bp.post("/")
def setup_post():
    existing = User.query.filter_by(role=Role.SUPERADMIN.value).first()
    if existing:
        return redirect(url_for("auth.login"))

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    if not username or not password:
        flash("Нужны логин и пароль.", "danger")
        return redirect(url_for("setup.setup"))

    if User.query.filter_by(username=username).first():
        flash("Этот логин уже существует. Возьмите другой или войдите.", "danger")
        return redirect(url_for("setup.setup"))

    u = User(username=username, full_name=username, role=Role.SUPERADMIN.value, school_id=None, is_active=True)
    u.set_password(password)
    db.session.add(u)
    db.session.commit()
    flash("SuperAdmin создан. Теперь войдите.", "success")
    return redirect(url_for("auth.login"))

