import re
from pathlib import Path

from flask import Blueprint, current_app, redirect, render_template, send_file, url_for, session, request
from flask_login import current_user

from ..models import Role

bp = Blueprint("main", __name__)

# Частая ошибка: вместо прямой загрузки указывают страницу релиза:
#   .../releases/tag/<тег>/<файл.exe>  — так GitHub НЕ отдаёт файл.
# Правильно: .../releases/download/<тег>/<файл.exe>
_GITHUB_TAG_ASSET_RE = re.compile(
    r"(https?://github\.com/[^/]+/[^/]+)/releases/tag/([^/]+)/([^/]+\.(?:exe|zip|msi))(?:\?.*)?$",
    re.IGNORECASE,
)


def _normalize_github_desktop_download_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return url
    m = _GITHUB_TAG_ASSET_RE.match(url)
    if m:
        base, tag, filename = m.groups()
        return f"{base}/releases/download/{tag}/{filename}"
    return url


def _get_desktop_download_info():
    """Возвращает (download_available, download_url) для шаблона."""
    ext_url = current_app.config.get("DESKTOP_DOWNLOAD_URL")
    if ext_url:
        ext_url = _normalize_github_desktop_download_url(ext_url)
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

