"""Centralized access control decorators and resource permission helpers."""

from __future__ import annotations

from functools import wraps

from flask import abort, redirect, url_for
from flask_login import current_user, login_required

from ..models import GradeReport, ReportFile, Role


# ---------------------------------------------------------------------------
# Decorator factory
# ---------------------------------------------------------------------------

def role_required(*allowed_roles: str):
    """Return a decorator that restricts a view to users with the given roles.

    Unauthorised users are redirected to the main index page with HTTP 302.
    Uses abort(403) for JSON/API callers would be a separate helper; this one
    is intentionally redirect-based to match the existing web UX.

    Usage::

        @bp.get("/some-route")
        @role_required(Role.SCHOOL_ADMIN.value, Role.SUPERADMIN.value)
        def some_view():
            ...
    """
    def decorator(f):
        @wraps(f)
        @login_required
        def wrapper(*args, **kwargs):
            if current_user.role not in allowed_roles:
                return redirect(url_for("main.index"))
            return f(*args, **kwargs)
        return wrapper
    return decorator


def superadmin_required(f):
    """Restrict view to SUPERADMIN role only."""
    return role_required(Role.SUPERADMIN.value)(f)


def admin_required(f):
    """Restrict view to SCHOOL_ADMIN role.

    SUPERADMIN is intentionally excluded here: superadmin operates through
    their own blueprint. If a view must allow both, use role_required() directly.
    """
    return role_required(Role.SCHOOL_ADMIN.value)(f)


def admin_or_superadmin_required(f):
    """Restrict view to SCHOOL_ADMIN or SUPERADMIN roles."""
    return role_required(Role.SCHOOL_ADMIN.value, Role.SUPERADMIN.value)(f)


def teacher_required(f):
    """Restrict view to TEACHER role only."""
    return role_required(Role.TEACHER.value)(f)


# ---------------------------------------------------------------------------
# Resource-level permission helpers
# ---------------------------------------------------------------------------

def can_access_report_file(rf: ReportFile) -> bool:
    """Return True if current_user may read/download the given ReportFile."""
    if current_user.role == Role.SUPERADMIN.value:
        return True
    if current_user.role == Role.SCHOOL_ADMIN.value:
        return rf.school_id == current_user.school_id
    return rf.teacher_id == current_user.id


def can_access_grade_report(gr: GradeReport) -> bool:
    """Return True if current_user may read the given GradeReport."""
    if current_user.role == Role.SUPERADMIN.value:
        return True
    if current_user.role == Role.SCHOOL_ADMIN.value:
        return gr.school_id == current_user.school_id
    return gr.teacher_id == current_user.id
