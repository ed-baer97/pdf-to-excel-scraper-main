import json
import secrets
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

from flask import (
    Blueprint,
    abort,
    current_app,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
    flash,
    send_file,
)
from flask_login import current_user
from sqlalchemy import func
from openpyxl import Workbook, load_workbook

from ...extensions import db
from ...models import Role, User, GradeReport, Class, School, ReportFile, TeacherSubject, TeacherClass, SubjectNameAlias
from ...security import decrypt_password, encrypt_password
from ...constants import kazakh_sort_key, normalize_subject_name
from ...services.admin_common import apply_analytics_filters, redirect_back
from ...services.report_teacher import get_report_teacher_name
from ...services.admin_dashboard import (
    YEAR_UI_PERIOD,
    aggregate_class_metrics,
    aggregate_year_metrics,
    chart_series_from_class_totals,
    class_accordion_group,
    class_name_sort_key,
    get_period_reports,
    get_quarter_reports,
    parse_class_grade,
    parse_ui_period_number,
    student_class_summary_category,
    teacher_accordion_group,
    ui_period_display_name,
)
from ...services.grade_reports.analytics import (
    build_analytics_maps,
    sort_analytics_subject_keys,
)
from ...services.grade_reports.context import load_school_period_context
from ...services.grade_reports.overview import (
    build_grades_overview,
    sort_grades_overview_classes,
)
from ...services.grade_reports.payload import (
    report_analytics_payload,
    report_grades_payload,
)
from ...services.grade_reports.excel import (
    build_analytics_workbook,
    build_class_metrics_charts_workbook,
    build_class_teacher_workbook,
    build_grades_class_workbook,
)
from ...services.criteria_grades import (
    build_criteria_period_zip,
    build_criteria_subject_summary,
    build_criteria_table,
    build_final_table,
    build_simple_grades_table,
    collect_classes_with_criteria,
    find_criteria_subject_entry,
    list_criteria_subject_entries,
    criteria_from_grades_payload,
    criteria_period_path_slug,
    final_from_grades_payload,
    has_criteria_data,
    has_final_data,
    is_final_period,
    is_year_period,
    parse_grades_json,
    report_has_criteria_block,
    report_has_final_block,
    safe_path_segment,
)
from ...services.auth_guards import admin_or_superadmin_required as admin_required
from ...services.subject_aliases import ensure_default_aliases, restore_default_aliases
from ...services.year_grades import (
    build_year_student_subjects,
    math_round_percent,
    students_data_from_year_map,
)
from ...translator import gettext as translate_gettext

from iin_utils import normalize_kz_iin


bp = Blueprint("admin", __name__, url_prefix="/admin")

from . import exports, management, reports  # noqa: E402, F401

def _iin_taken_by_other_teacher(school_id: int, iin_norm: str, exclude_id: int | None = None) -> bool:
    q = User.query.filter_by(role=Role.TEACHER.value, school_id=school_id, iin=iin_norm)
    if exclude_id is not None:
        q = q.filter(User.id != exclude_id)
    return q.first() is not None


def _redirect_back(fallback_url: str):
    """Backward-compatible wrapper around shared redirect helper."""
    return redirect_back(fallback_url)


def _management_list_context(school_id: int) -> dict:
    """Teachers/classes lists and accordion buckets for the management page."""
    teachers = User.query.filter_by(
        role=Role.TEACHER.value, school_id=school_id
    ).all()
    classes = Class.query.filter_by(school_id=school_id).all()
    teachers.sort(key=lambda t: kazakh_sort_key(t.full_name or t.username))
    classes.sort(key=lambda c: kazakh_sort_key(c.name))
    teachers_by_accordion = {
        "1-4": [],
        "5-9": [],
        "10-11": [],
        "no_leadership": [],
    }
    for t in teachers:
        group = teacher_accordion_group(t, classes)
        teachers_by_accordion[group].append(t)
    classes_by_accordion = {
        "1-4": [],
        "5-9": [],
        "10-11": [],
    }
    for cls in classes:
        group = class_accordion_group(cls.name)
        classes_by_accordion[group].append(cls)
    ensure_default_aliases(school_id)
    subject_aliases = (
        SubjectNameAlias.query.filter_by(school_id=school_id)
        .order_by(SubjectNameAlias.alias_name)
        .all()
    )
    return {
        "teachers": teachers,
        "classes": classes,
        "teachers_by_accordion": teachers_by_accordion,
        "classes_by_accordion": classes_by_accordion,
        "subject_aliases": subject_aliases,
    }

