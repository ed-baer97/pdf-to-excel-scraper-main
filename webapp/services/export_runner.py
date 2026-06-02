"""Фоновый экспорт Excel: сборка файлов по ExportJob.export_kind."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any

from flask import current_app

from ..constants import kazakh_sort_key, normalize_subject_name
from ..extensions import db
from ..models import Class, ExportJob, ExportJobStatus, School
from ..scraper_runner import _resolve_upload_root
from ..services.admin_common import apply_analytics_filters
from ..services.criteria_grades import (
    build_criteria_period_zip,
    criteria_period_path_slug,
    safe_path_segment,
)
from ..services.grade_reports.analytics import build_analytics_maps
from ..services.grade_reports.class_teacher import build_class_teacher_categories_data
from ..services.grade_reports.context import load_school_period_context
from ..services.grade_reports.excel import (
    build_analytics_workbook,
    build_class_metrics_charts_workbook,
    build_class_teacher_workbook,
    build_grades_class_workbook,
)
from ..services.grade_reports.payload import report_grades_payload
from ..services.grade_reports.periods import parse_ui_period_number, ui_period_display_name
from ..services.admin_dashboard import aggregate_class_metrics
from ..translator import gettext as translate_gettext


def _export_dir(job_id: int) -> Path:
    root = _resolve_upload_root(current_app)
    path = root / "exports" / str(job_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _save_bytesio(buf: BytesIO, dest: Path) -> None:
    dest.write_bytes(buf.getvalue())


def _period_name(period_number: int, lang: str) -> str:
    return ui_period_display_name(
        period_number, lambda k: translate_gettext(k, lang)
    )


def execute_export_job(job_id: int) -> None:
    """Собрать файл экспорта и обновить ExportJob."""
    job: ExportJob | None = db.session.get(ExportJob, job_id)
    if not job:
        return

    job.status = ExportJobStatus.RUNNING.value
    db.session.commit()

    try:
        params = json.loads(job.params_json or "{}")
        lang = params.get("lang", "ru")
        school_id = job.school_id
        out_dir = _export_dir(job_id)
        filename: str
        output: BytesIO

        kind = job.export_kind

        if kind == "analytics":
            period_number = parse_ui_period_number(params.get("period_number", 2))
            ctx = load_school_period_context(school_id, period_number)
            sor, soch, grades = build_analytics_maps(ctx)
            if any(
                params.get(k)
                for k in ("filter_subject", "filter_class", "filter_teacher")
            ):
                sor, soch, grades = apply_analytics_filters(
                    sor,
                    soch,
                    grades,
                    params.get("filter_subject") or None,
                    params.get("filter_class") or None,
                    params.get("filter_teacher") or None,
                )
            period_name = _period_name(period_number, lang)
            output = build_analytics_workbook(period_name, sor, soch, grades)
            filename = f"Аналитика_СОР_СОЧ_{period_name.replace(' ', '_')}.xlsx"

        elif kind == "criteria_zip":
            period_number = parse_ui_period_number(params.get("period_number", 2))
            school = db.session.get(School, school_id)
            if not school:
                raise ValueError("School not found")
            ctx = load_school_period_context(school_id, period_number)
            zip_buf = build_criteria_period_zip(
                school.name,
                period_number,
                ctx.reports,
                ctx.active_class_names,
                school_id,
            )
            if not zip_buf:
                raise ValueError("No criteria data for period")
            org_slug = safe_path_segment(school.name)
            period_slug = criteria_period_path_slug(period_number)
            filename = f"criteria_{period_number}.zip"
            dest = out_dir / filename
            dest.write_bytes(zip_buf.getvalue())
            job.file_path = str(dest)
            job.status = ExportJobStatus.DONE.value
            job.expires_at = datetime.utcnow() + timedelta(hours=24)
            db.session.commit()
            return

        elif kind == "grades_class":
            period_number = parse_ui_period_number(params.get("period_number", 2))
            class_name = params.get("class_name") or ""
            from ..services.grade_reports.queries import get_period_reports

            reports = get_period_reports(
                school_id, period_number, class_name=class_name
            )
            subjects: set[str] = set()
            students_data: dict[str, dict[str, dict]] = {}
            for report in reports:
                subj = normalize_subject_name(report.subject_name, school_id)
                subjects.add(subj)
                grades_data = report_grades_payload(report)
                if not grades_data:
                    continue
                for student in grades_data.get("students", []) or []:
                    name = (student.get("name") or "").strip()
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
                    elif new_grade.get("grade") is not None and new_grade[
                        "grade"
                    ] > (existing.get("grade") or 0):
                        students_data[name][subj] = new_grade

            subjects_list = sorted(subjects, key=kazakh_sort_key)
            students_list = []
            for name in sorted(students_data.keys(), key=kazakh_sort_key):
                grades = students_data[name]
                students_list.append(
                    {
                        "name": name,
                        "grades": grades,
                        "count_5": sum(
                            1 for g in grades.values() if g.get("grade") == 5
                        ),
                        "count_4": sum(
                            1 for g in grades.values() if g.get("grade") == 4
                        ),
                        "count_3": sum(
                            1 for g in grades.values() if g.get("grade") == 3
                        ),
                        "count_2": sum(
                            1 for g in grades.values() if g.get("grade") == 2
                        ),
                    }
                )
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
                subject_stats[subj] = {
                    "count_5": s5,
                    "count_4": s4,
                    "count_3": s3,
                    "count_2": s2,
                    "total": total_in_subj,
                    "quality_percent": round(
                        (s5 + s4) / total_in_subj * 100, 1
                    )
                    if total_in_subj
                    else 0,
                    "success_percent": round(
                        (s5 + s4 + s3) / total_in_subj * 100, 1
                    )
                    if total_in_subj
                    else 0,
                }
            period_name = _period_name(period_number, lang)
            output, filename = build_grades_class_workbook(
                class_name,
                period_name,
                period_number,
                subjects_list,
                students_list,
                subject_stats,
            )

        elif kind == "class_teacher":
            period_number = parse_ui_period_number(params.get("period_number", 2))
            categories_data = build_class_teacher_categories_data(
                school_id,
                period_number,
                segment=params.get("segment"),
                class_filter=params.get("class_filter", ""),
                class_teacher_filter=params.get("class_teacher_filter", ""),
                student_filter=params.get("student_filter", ""),
            )
            period_name = _period_name(period_number, lang)
            output, filename = build_class_teacher_workbook(
                categories_data, period_name
            )

        elif kind == "metrics_charts":
            period_number = parse_ui_period_number(params.get("period_number", 2))
            scope = (params.get("chart_scope") or "overall").strip().lower()
            if scope not in ("overall", "parallel"):
                scope = "overall"
            active_class_names = {
                row.name
                for row in Class.query.filter_by(school_id=school_id)
                .with_entities(Class.name)
                .all()
            }
            agg = aggregate_class_metrics(
                school_id, period_number, active_class_names
            )

            def tr(key: str) -> str:
                return translate_gettext(key, lang)

            output, filename, _local = build_class_metrics_charts_workbook(
                scope=scope,
                period_number=period_number,
                agg=agg,
                tr=tr,
            )

        else:
            raise ValueError(f"Unknown export_kind: {kind}")

        dest = out_dir / filename
        _save_bytesio(output, dest)
        job.file_path = str(dest)
        job.status = ExportJobStatus.DONE.value
        job.expires_at = datetime.utcnow() + timedelta(hours=24)
        db.session.commit()

    except Exception as exc:
        current_app.logger.exception("Export job %s failed", job_id)
        job.status = ExportJobStatus.FAILED.value
        job.error = str(exc)[:2000]
        db.session.commit()


run_export_job = execute_export_job
