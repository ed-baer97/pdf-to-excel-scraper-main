"""Админ: ручной ввод данных итогового отчёта (ГИА, ЕНТ, аттестаты)."""

from __future__ import annotations

import json

from flask import flash, redirect, render_template, request, session, url_for
from flask_login import current_user

from ...services.academic_year import available_academic_years, format_academic_year, resolve_academic_year
from ...services.auth_guards import admin_or_superadmin_required as admin_required
from ...services.grade_reports.final_report_data import (
    VALID_SECTIONS,
    load_all_sections,
    save_section_data,
)
from . import bp


@bp.route("/final-report/input", methods=["GET", "POST"])
@admin_required
def final_report_input():
    """Форма ввода ручных данных итогового отчёта."""
    school_id = current_user.school_id
    academic_year = resolve_academic_year(request.values.get("academic_year"))
    years = available_academic_years(school_id)

    if request.method == "POST":
        section = (request.form.get("section") or "").strip()
        if section not in VALID_SECTIONS:
            flash("Неверный раздел", "danger")
            return redirect(
                url_for("admin.final_report_input", academic_year=academic_year)
            )
        raw = request.form.get("data_json") or "{}"
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("data must be object")
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            flash(f"Ошибка JSON: {exc}", "danger")
            return redirect(
                url_for(
                    "admin.final_report_input",
                    academic_year=academic_year,
                    section=section,
                )
            )
        save_section_data(school_id, academic_year, section, data)
        flash("Данные сохранены", "success")
        return redirect(
            url_for(
                "admin.final_report_input",
                academic_year=academic_year,
                section=section,
            )
        )

    active_section = request.args.get("section") or "gia9"
    if active_section not in VALID_SECTIONS:
        active_section = "gia9"

    sections_data = load_all_sections(school_id, academic_year)
    return render_template(
        "admin/final_report_input.html",
        academic_year=academic_year,
        years=years,
        format_academic_year=format_academic_year,
        active_section=active_section,
        sections_data=sections_data,
        sections_json=json.dumps(sections_data, ensure_ascii=False, indent=2),
    )
