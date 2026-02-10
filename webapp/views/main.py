from pathlib import Path

from flask import Blueprint, current_app, redirect, render_template, send_file, url_for, session, request
from flask_login import current_user

from ..models import Role

bp = Blueprint("main", __name__)


def _get_desktop_download_info():
    """Возвращает (download_available, download_url) для шаблона."""
    ext_url = current_app.config.get("DESKTOP_DOWNLOAD_URL")
    if ext_url:
        return False, ext_url  # Внешняя ссылка
    path = current_app.config.get("DESKTOP_DOWNLOAD_PATH")
    if path:
        p = Path(path)
        if p.exists():
            return True, None  # Файл есть, будем отдавать через route
    return False, None


@bp.get("/")
def index():
    if not current_user.is_authenticated:
        download_available, download_url = _get_desktop_download_info()
        return render_template(
            "main/home.html",
            download_available=download_available,
            download_url=download_url,
        )
    if current_user.role == Role.SUPERADMIN.value:
        return redirect(url_for("superadmin.dashboard"))
    if current_user.role == Role.SCHOOL_ADMIN.value:
        return redirect(url_for("admin.dashboard"))
    return redirect(url_for("teacher.dashboard"))


@bp.get("/download/desktop")
def download_desktop():
    """Скачивание десктопного приложения (exe или zip)."""
    path = current_app.config.get("DESKTOP_DOWNLOAD_PATH")
    if not path:
        return redirect(url_for("main.index"))
    p = Path(path)
    if not p.exists():
        return redirect(url_for("main.index"))
    return send_file(
        str(p.resolve()),
        as_attachment=True,
        download_name=p.name,
    )


@bp.route("/set_language/<lang>")
def set_language(lang):
    """Установить язык интерфейса"""
    if lang in ['ru', 'kk']:
        session['language'] = lang
    # Перенаправляем на предыдущую страницу или на главную
    return redirect(request.referrer or url_for('main.index'))

