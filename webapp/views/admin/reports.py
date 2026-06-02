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
from ...services.grade_reports.class_teacher import build_class_teacher_categories_data
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

from . import bp

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

@bp.get("/grades")
@admin_required
def grades_overview():
    """Обзор оценок: список классов со сводкой"""
    
    # Параметры фильтрации (только четверти)
    period_number = parse_ui_period_number(request.args.get("period_number", 2))

    ctx = load_school_period_context(current_user.school_id, period_number)
    classes_data = build_grades_overview(ctx)
    sorted_classes, classes_by_accordion = sort_grades_overview_classes(classes_data)

    return render_template(
        "admin/grades_overview.html",
        classes=sorted_classes,
        classes_by_accordion=classes_by_accordion,
        period_number=period_number
    )


@bp.get("/grades/class/<class_name>")
@admin_required
def grades_class(class_name: str):
    """Сводная таблица оценок класса: ученик × предмет"""
    
    # Параметры (только четверти)
    period_number = parse_ui_period_number(request.args.get("period_number", 2))

    if not Class.query.filter_by(school_id=current_user.school_id, name=class_name).first():
        flash(
            "Этого класса нет в списке школы (возможно, он удалён). Данные в отчётах остаются в базе, но страница недоступна.",
            "warning",
        )
        return redirect(url_for("admin.grades_overview", period_number=period_number))

    school_id = current_user.school_id

    if period_number == YEAR_UI_PERIOD:
        year_map = build_year_student_subjects(
            school_id, class_name, get_quarter_reports
        )
        students_data = students_data_from_year_map(year_map)
        subjects = {subj for subjs in students_data.values() for subj in subjs}
    else:
        reports = get_period_reports(school_id, period_number, class_name=class_name)
        subjects = set()
        students_data = {}

        for report in reports:
            subj = normalize_subject_name(report.subject_name, school_id)
            subjects.add(subj)

            if report.grades_json:
                try:
                    grades_data = report_grades_payload(report)
                    for student in grades_data.get("students", []):
                        name = student.get("name")
                        if not name:
                            continue
                        if name not in students_data:
                            students_data[name] = {}
                        existing = students_data[name].get(subj)
                        new_grade = {
                            "percent": student.get("percent"),
                            "grade": student.get("grade"),
                        }
                        if existing is None or existing.get("grade") is None:
                            students_data[name][subj] = new_grade
                        elif (
                            new_grade.get("grade") is not None
                            and new_grade["grade"] > existing.get("grade", 0)
                        ):
                            students_data[name][subj] = new_grade
                except json.JSONDecodeError:
                    pass

    # Формируем списки для шаблона
    subjects_list = sorted(subjects, key=kazakh_sort_key)
    students_list = []
    
    for name in sorted(students_data.keys(), key=kazakh_sort_key):
        grades = students_data[name]
        
        # Подсчёт 5, 4, 3 по строке (ученику)
        row_count_5 = sum(1 for g in grades.values() if g.get("grade") == 5)
        row_count_4 = sum(1 for g in grades.values() if g.get("grade") == 4)
        row_count_3 = sum(1 for g in grades.values() if g.get("grade") == 3)
        row_count_2 = sum(1 for g in grades.values() if g.get("grade") == 2)
        
        students_list.append({
            "name": name,
            "grades": grades,
            "count_5": row_count_5,
            "count_4": row_count_4,
            "count_3": row_count_3,
            "count_2": row_count_2,
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
        if period_number == YEAR_UI_PERIOD:
            quality = math_round_percent(s5 + s4, total_in_subj) if total_in_subj else 0
            success = math_round_percent(s5 + s4 + s3, total_in_subj) if total_in_subj else 0
        else:
            quality = round((s5 + s4) / total_in_subj * 100, 1) if total_in_subj else 0
            success = round((s5 + s4 + s3) / total_in_subj * 100, 1) if total_in_subj else 0
        subject_stats[subj] = {
            "count_5": s5, "count_4": s4, "count_3": s3, "count_2": s2,
            "total": total_in_subj,
            "quality_percent": quality,
            "success_percent": success
        }
    
    # Карточки сверху: по ученикам (отличники / хорошисты / троишники с двойками), не по ячейкам таблицы
    total_students = len(students_data)
    grades_count = {"5": 0, "4": 0, "3": 0, "2": 0}
    for student in students_list:
        cat = student_class_summary_category(student["grades"])
        if cat == "excellent":
            grades_count["5"] += 1
        elif cat == "good":
            grades_count["4"] += 1
        elif cat == "troishnik":
            grades_count["3"] += 1
        elif cat == "failing":
            grades_count["2"] += 1

    # Метрики карточек считаем строго из распределения 5/4/3/2,
    # чтобы "Качество" всегда совпадало с карточкой "Распределение".
    quality_percent = 0
    success_percent = 0
    distribution_total = sum(grades_count.values())
    if distribution_total > 0:
        quality_percent = round(
            (grades_count["5"] + grades_count["4"]) / distribution_total * 100, 1
        )
        success_percent = round(
            (grades_count["5"] + grades_count["4"] + grades_count["3"])
            / distribution_total
            * 100,
            1,
        )

    return render_template(
        "admin/grades_class.html",
        class_name=class_name,
        subjects=subjects_list,
        students=students_list,
        subject_stats=subject_stats,
        period_number=period_number,
        summary={
            "total_students": total_students,
            "quality_percent": quality_percent,
            "success_percent": success_percent,
            "grades_count": grades_count
        }
    )


# ==============================================================================
# Criteria assessment routes
# ==============================================================================


@bp.get("/criteria")
@admin_required
def criteria_overview():
    """Критериальное оценивание: период → список классов."""
    period_number = parse_ui_period_number(request.args.get("period_number", 2))

    ctx = load_school_period_context(current_user.school_id, period_number)
    classes_data = collect_classes_with_criteria(
        ctx.reports,
        ctx.active_class_names,
        current_user.school_id,
        period_number,
    )

    sorted_classes = sorted(
        classes_data.values(), key=lambda x: kazakh_sort_key(x["class_name"])
    )
    classes_by_accordion = {"1-4": [], "5-9": [], "10-11": []}
    for cls in sorted_classes:
        group = class_accordion_group(cls["class_name"])
        classes_by_accordion[group].append(cls)

    return render_template(
        "admin/criteria_overview.html",
        classes=sorted_classes,
        classes_by_accordion=classes_by_accordion,
        period_number=period_number,
    )


@bp.get("/criteria/download-excel")
@admin_required
def download_criteria_period_excel():
    """ZIP: все классы за период — {орг}/{период}/{класс}/предметы.xlsx."""
    period_number = parse_ui_period_number(request.args.get("period_number", 2))

    school = School.query.get(current_user.school_id)
    if not school:
        flash("Школа не найдена.", "danger")
        return redirect(url_for("admin.criteria_overview", period_number=period_number))

    ctx = load_school_period_context(current_user.school_id, period_number)

    zip_buf = build_criteria_period_zip(
        school.name,
        period_number,
        ctx.reports,
        ctx.active_class_names,
        current_user.school_id,
    )
    if not zip_buf:
        flash("Нет данных для выгрузки за выбранный период.", "warning")
        return redirect(url_for("admin.criteria_overview", period_number=period_number))

    org_slug = safe_path_segment(school.name)
    period_slug = criteria_period_path_slug(period_number)
    zip_local = f"{org_slug}/{period_slug}/критериальное_оценивание.zip"
    zip_ascii = f"criteria_{period_number}.zip"

    resp = send_file(
        zip_buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name=zip_ascii,
    )
    resp.headers["Content-Disposition"] = (
        f'attachment; filename="{zip_ascii}"; filename*=UTF-8\'\'{quote(zip_local)}'
    )
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp


@bp.get("/criteria/class/<class_name>")
@admin_required
def criteria_class(class_name: str):
    """Критериальное оценивание: предметы класса."""
    period_number = parse_ui_period_number(request.args.get("period_number", 2))

    if not Class.query.filter_by(school_id=current_user.school_id, name=class_name).first():
        flash(
            "Этого класса нет в списке школы (возможно, он удалён).",
            "warning",
        )
        return redirect(url_for("admin.criteria_overview", period_number=period_number))

    school_id = current_user.school_id
    reports = get_period_reports(school_id, period_number, class_name=class_name)

    subjects = list_criteria_subject_entries(
        reports, school_id, period_number, class_name=class_name
    )
    subjects = [
        {
            "name": e["display_name"],
            "teacher": e.get("teacher") or "",
            "report_id": e.get("report_id"),
            "has_criteria": e.get("has_criteria"),
            "has_final": e.get("has_final"),
        }
        for e in subjects
    ]

    return render_template(
        "admin/criteria_class.html",
        class_name=class_name,
        subjects=subjects,
        period_number=period_number,
        year_period=is_year_period(period_number),
        final_period=is_final_period(period_number),
    )


@bp.get("/criteria/class/<class_name>/subject/<path:subject_name>")
@admin_required
def criteria_subject(class_name: str, subject_name: str):
    """Критериальное оценивание: таблица учеников по предмету."""
    period_number = parse_ui_period_number(request.args.get("period_number", 2))

    if not Class.query.filter_by(school_id=current_user.school_id, name=class_name).first():
        flash("Этого класса нет в списке школы.", "warning")
        return redirect(url_for("admin.criteria_overview", period_number=period_number))

    school_id = current_user.school_id
    reports = get_period_reports(school_id, period_number, class_name=class_name)

    report_id_arg = request.args.get("report_id", type=int)
    entry = find_criteria_subject_entry(
        reports,
        school_id,
        period_number,
        class_name,
        display_name=subject_name,
        report_id=report_id_arg,
    )

    if not entry or not entry.get("report_id"):
        flash("Нет данных по этому предмету за выбранный период.", "warning")
        return redirect(
            url_for(
                "admin.criteria_class",
                class_name=class_name,
                period_number=period_number,
            )
        )

    report = GradeReport.query.filter_by(
        id=entry["report_id"], school_id=school_id, class_name=class_name
    ).first()
    if not report:
        flash("Отчёт не найден.", "warning")
        return redirect(
            url_for(
                "admin.criteria_class",
                class_name=class_name,
                period_number=period_number,
            )
        )

    display_name = entry["display_name"]
    teacher_name = entry.get("teacher") or get_report_teacher_name(report)
    payload = entry.get("payload") or report_grades_payload(report)
    criteria = criteria_from_grades_payload(payload) if payload else None
    final_block = final_from_grades_payload(payload) if payload else None

    table = None
    show_reupload_hint = False
    if is_final_period(period_number) and final_block and has_final_data(payload):
        table = build_final_table(final_block)
    elif criteria and has_criteria_data(payload):
        table = build_criteria_table(criteria)
    elif is_year_period(period_number) and payload:
        table = build_simple_grades_table(payload)
        show_reupload_hint = False
    else:
        show_reupload_hint = True

    summary = build_criteria_subject_summary(payload) if payload else build_criteria_subject_summary(None)

    return render_template(
        "admin/criteria_subject.html",
        class_name=class_name,
        subject_name=display_name,
        period_number=period_number,
        report_id=entry["report_id"],
        teacher_name=teacher_name,
        table=table,
        show_reupload_hint=show_reupload_hint,
        year_period=is_year_period(period_number),
        final_period=is_final_period(period_number),
        summary=summary,
    )


@bp.post("/grades/class/<class_name>/subjects/delete")
@admin_required
def delete_subject_from_class(class_name: str):
    """Удаление предмета из отчетов указанного класса за выбранную четверть."""

    subject_name = (request.form.get("subject_name") or "").strip()
    period_raw = request.form.get("period_number", "2")
    period_number = parse_ui_period_number(period_raw)

    if not subject_name:
        flash("Не указан предмет для удаления.", "danger")
        return _redirect_back(url_for("admin.grades_class", class_name=class_name, period_number=period_number))

    target_subject = normalize_subject_name(subject_name, current_user.school_id)

    # Удаляем GradeReport по текущему классу и предмету ТОЛЬКО за выбранную четверть.
    # Для 2 и 4 четвертей дополнительно удаляем соответствующее полугодие.
    reports = GradeReport.query.filter_by(
        school_id=current_user.school_id,
        class_name=class_name,
    ).all()

    if period_number == YEAR_UI_PERIOD:
        allowed_periods = {
            ("quarter", 1),
            ("quarter", 2),
            ("quarter", 3),
            ("quarter", 4),
            ("semester", 1),
            ("semester", 2),
        }
    else:
        allowed_periods = {("quarter", period_number)}
        if period_number == 2:
            allowed_periods.add(("semester", 1))
        elif period_number == 4:
            allowed_periods.add(("semester", 2))

    reports_to_delete = [
        r for r in reports
        if normalize_subject_name(r.subject_name, current_user.school_id) == target_subject
        and (r.period_type, r.period_number) in allowed_periods
    ]

    # ReportFile: код четверти 1..4; при удалении «учебного года» — все четверти.
    report_files = ReportFile.query.filter_by(
        school_id=current_user.school_id,
        class_name=class_name,
    ).all()
    if period_number == YEAR_UI_PERIOD:
        period_codes = {"1", "2", "3", "4"}
    else:
        period_codes = {str(period_number)}
    files_to_delete = [
        rf for rf in report_files
        if normalize_subject_name(rf.subject, current_user.school_id) == target_subject
        and str(rf.period_code) in period_codes
    ]

    if not reports_to_delete and not files_to_delete:
        flash(f'Связанные отчёты для предмета "{target_subject}" не найдены.', "warning")
        return _redirect_back(url_for("admin.grades_class", class_name=class_name, period_number=period_number))

    for r in reports_to_delete:
        db.session.delete(r)
    for rf in files_to_delete:
        db.session.delete(rf)
    db.session.commit()

    flash(
        f'Предмет "{target_subject}" удалён: отчётов оценок — {len(reports_to_delete)}, файлов отчётов — {len(files_to_delete)}.',
        "success",
    )
    return _redirect_back(url_for("admin.grades_class", class_name=class_name, period_number=period_number))


@bp.get("/analytics")
@admin_required
def analytics_home():
    """
    Аналитика: 3 вкладки — СОР / СОЧ / Оценки.
    По каждому предмету — карточка с таблицей по классам.
    Структура копирует reference проект.
    """
    
    # Параметры (только четверти)
    period_number = parse_ui_period_number(request.args.get("period_number", 2))
    segment = request.args.get("segment")  # '1-4' или '5-11' или None

    ctx = load_school_period_context(current_user.school_id, period_number)
    subjects_data_sor, subjects_data_soch, subjects_data_grades = build_analytics_maps(
        ctx, segment=segment
    )
    subjects_data_sor, subjects_data_soch, subjects_data_grades = sort_analytics_subject_keys(
        subjects_data_sor, subjects_data_soch, subjects_data_grades
    )

    return render_template(
        "admin/analytics_home.html",
        subjects_data_sor=subjects_data_sor,
        subjects_data_soch=subjects_data_soch,
        subjects_data_grades=subjects_data_grades,
        period_number=period_number,
        segment=segment
    )


def _apply_analytics_filters(subjects_data_sor, subjects_data_soch, subjects_data_grades,
                             filter_subject, filter_class, filter_teacher):
    """Backward-compatible wrapper around shared analytics filters."""
    return apply_analytics_filters(
        subjects_data_sor,
        subjects_data_soch,
        subjects_data_grades,
        filter_subject,
        filter_class,
        filter_teacher,
    )


@bp.get("/analytics/download-excel")
@admin_required
def download_analytics_excel():
    """Скачать аналитику СОР/СОЧ/Оценки в Excel (с учётом фильтров subject/class/teacher)"""
    
    period_number = parse_ui_period_number(request.args.get("period_number", 2))
    filter_subject = request.args.get("subject", "").strip() or None
    filter_class = request.args.get("class", "").strip() or None
    filter_teacher = request.args.get("teacher", "").strip() or None
    lang = session.get("language", "ru")
    period_name = ui_period_display_name(period_number, lambda k: translate_gettext(k, lang))
    
    ctx = load_school_period_context(current_user.school_id, period_number)
    subjects_data_sor, subjects_data_soch, subjects_data_grades = build_analytics_maps(ctx)

    # Применяем фильтры (subject, class, teacher)
    if filter_subject or filter_class or filter_teacher:
        subjects_data_sor, subjects_data_soch, subjects_data_grades = _apply_analytics_filters(
            subjects_data_sor, subjects_data_soch, subjects_data_grades,
            filter_subject, filter_class, filter_teacher
        )
    
    output = build_analytics_workbook(
        period_name,
        subjects_data_sor,
        subjects_data_soch,
        subjects_data_grades,
    )
    filename = f"Аналитика_СОР_СОЧ_{period_name.replace(' ', '_')}.xlsx"
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename,
    )


@bp.get("/class-teacher-report")
@admin_required
def class_teacher_report():
    """Отчёт классного руководителя по всем классам школы."""
    period_number = parse_ui_period_number(request.args.get("period_number", 2))
    segment = request.args.get("segment")
    categories_data = build_class_teacher_categories_data(
        current_user.school_id,
        period_number,
        segment=segment,
    )
    return render_template(
        "admin/class_teacher_report.html",
        categories_data=categories_data,
        period_number=period_number,
        segment=segment,
    )


# ==============================================================================
# Excel Export Routes
# ==============================================================================

@bp.get("/grades/class/<class_name>/download-excel")
@admin_required
def download_grades_class_excel(class_name: str):
    """Скачать сводную таблицу оценок класса в Excel"""
    
    # Параметры (только четверти)
    period_number = parse_ui_period_number(request.args.get("period_number", 2))
    
    # Получаем все отчёты для этого класса (включая полугодовые для 2/4)
    reports = get_period_reports(current_user.school_id, period_number, class_name=class_name)
    
    # Собираем данные
    subjects = set()
    students_data = {}  # name -> {subject -> {percent, grade}}
    
    for report in reports:
        subj = normalize_subject_name(report.subject_name, current_user.school_id)
        subjects.add(subj)
        
        if report.grades_json:
            try:
                grades_data = report_grades_payload(report)
                students_list = grades_data.get("students", [])
                
                for student in students_list:
                    name = student.get("name")
                    if not name:
                        continue
                    
                    if name not in students_data:
                        students_data[name] = {}
                    
                    existing = students_data[name].get(subj)
                    new_grade = {"percent": student.get("percent"), "grade": student.get("grade")}
                    if existing is None or existing.get("grade") is None:
                        students_data[name][subj] = new_grade
                    elif new_grade.get("grade") is not None and new_grade["grade"] > existing.get("grade", 0):
                        students_data[name][subj] = new_grade
            except json.JSONDecodeError:
                pass
    
    # Формируем списки
    subjects_list = sorted(subjects, key=kazakh_sort_key)
    students_list = []
    
    for name in sorted(students_data.keys(), key=kazakh_sort_key):
        grades = students_data[name]
        row_count_5 = sum(1 for g in grades.values() if g.get("grade") == 5)
        row_count_4 = sum(1 for g in grades.values() if g.get("grade") == 4)
        row_count_3 = sum(1 for g in grades.values() if g.get("grade") == 3)
        row_count_2 = sum(1 for g in grades.values() if g.get("grade") == 2)
        
        students_list.append({
            "name": name,
            "grades": grades,
            "count_5": row_count_5,
            "count_4": row_count_4,
            "count_3": row_count_3,
            "count_2": row_count_2,
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
    
    lang = session.get("language", "ru")
    period_name = ui_period_display_name(period_number, lambda k: translate_gettext(k, lang))
    output, filename = build_grades_class_workbook(
        class_name,
        period_name,
        period_number,
        subjects_list,
        students_list,
        subject_stats,
    )
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename,
    )


@bp.get("/class-teacher-report/download-excel")
@admin_required
def download_class_teacher_report_excel():
    """Скачать отчёт классного руководителя в Excel (синхронно; async — POST /admin/exports)."""
    period_number = parse_ui_period_number(request.args.get("period_number", 2))
    segment = request.args.get("segment")
    class_filter = (request.args.get("class") or "").strip().lower() or None
    class_teacher_filter = (request.args.get("class_teacher") or "").strip().lower() or None
    student_filter = (request.args.get("student") or "").strip().lower() or None
    lang = session.get("language", "ru")
    period_name = ui_period_display_name(period_number, lambda k: translate_gettext(k, lang))

    categories_data = build_class_teacher_categories_data(
        current_user.school_id,
        period_number,
        segment=segment,
        class_filter=class_filter,
        class_teacher_filter=class_teacher_filter,
        student_filter=student_filter,
    )
    output, filename = build_class_teacher_workbook(categories_data, period_name)
    return send_file(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename,
    )


