"""Сборка школьного итогового отчёта в Excel из БД оценок и ручных данных."""

from __future__ import annotations

import json
from io import BytesIO
from typing import Any, Callable

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference, Series
from openpyxl.chart.axis import ChartLines, Scaling
from openpyxl.chart.label import DataLabelList
from openpyxl.chart.shapes import GraphicalProperties
from openpyxl.drawing.colors import ColorChoice
from openpyxl.drawing.line import LineProperties
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from ...constants import kazakh_sort_key, normalize_subject_name
from ...extensions import db
from ...models import Class, School
from ..academic_year import available_academic_years, format_academic_year, resolve_academic_year
from ..admin_dashboard import aggregate_class_metrics
from ..year_grades import YEAR_UI_PERIOD
from .excel.charts import chart_title_large, excel_chart_sheet_name
from .final_report_data import load_all_sections, load_sections_for_years
from .payload import report_grades_payload
from .periods import class_accordion_group, class_name_sort_key, parse_class_grade
from .queries import get_period_reports

_HEADER_FILL = PatternFill(start_color="0D6EFD", end_color="0D6EFD", fill_type="solid")
_HEADER_FONT = Font(bold=True, color="FFFFFF", size=11)
_THIN = Side(style="thin", color="CED4DA")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)


def _resolve_years(school_id: int, academic_year: int | None, years_back: int = 3) -> list[int]:
    all_years = available_academic_years(school_id)
    anchor = resolve_academic_year(academic_year)
    if anchor in all_years:
        idx = all_years.index(anchor)
        picked = all_years[idx : idx + years_back]
    else:
        picked = [anchor]
    return sorted(picked)


def _active_class_names(school_id: int) -> set[str]:
    return {row.name for row in Class.query.filter_by(school_id=school_id).all()}


def _write_header_row(ws, row: int, headers: list[str]) -> None:
    for col, title in enumerate(headers, start=1):
        cell = ws.cell(row=row, column=col, value=title)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.border = _BORDER
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _write_data_row(ws, row: int, values: list, *, number_cols: set[int] | None = None) -> None:
    number_cols = number_cols or set()
    for col, val in enumerate(values, start=1):
        cell = ws.cell(row=row, column=col, value=val)
        cell.border = _BORDER
        cell.alignment = Alignment(horizontal="center", vertical="center")
        if col in number_cols and isinstance(val, (int, float)):
            cell.number_format = "0.0"


def _class_students_map(
    school_id: int,
    class_name: str,
    academic_year: int,
) -> dict[str, dict[str, dict]]:
    """Ученики класса: предмет → оценка (за учебный год)."""
    reports = get_period_reports(
        school_id, YEAR_UI_PERIOD, class_name=class_name, academic_year=academic_year
    )
    students: dict[str, dict[str, dict]] = {}
    for report in reports:
        subj = normalize_subject_name(report.subject_name, school_id)
        grades_data = report_grades_payload(report)
        if not grades_data:
            continue
        for student in grades_data.get("students", []) or []:
            name = (student.get("name") or "").strip()
            if not name:
                continue
            if name not in students:
                students[name] = {}
            existing = students[name].get(subj)
            new_grade = {
                "percent": student.get("percent"),
                "grade": student.get("grade"),
            }
            if existing is None or existing.get("grade") is None:
                students[name][subj] = new_grade
            elif new_grade.get("grade") is not None and new_grade["grade"] > (
                existing.get("grade") or 0
            ):
                students[name][subj] = new_grade
    return students


def _class_grade_summary(
    school_id: int,
    class_name: str,
    academic_year: int,
) -> dict[str, Any]:
    """Сводка по классу: кол-во на 5/4/3/2, успеваемость, качество."""
    students = _class_students_map(school_id, class_name, academic_year)
    total = len(students)
    if total == 0:
        return {
            "class_name": class_name,
            "total": 0,
            "passing": 0,
            "count_5": 0,
            "count_4": 0,
            "one_3": 0,
            "two_plus_3": 0,
            "count_3": 0,
            "count_2": 0,
            "success_percent": None,
            "quality_percent": None,
        }

    count_5 = count_4 = one_3 = two_plus_3 = count_3 = count_2 = 0
    for grades in students.values():
        vals = [g.get("grade") for g in grades.values() if g.get("grade") is not None]
        if not vals:
            continue
        c3 = sum(1 for g in vals if g == 3)
        c2 = sum(1 for g in vals if g is not None and g <= 2)
        if c2 > 0:
            count_2 += 1
        elif all(g >= 5 for g in vals):
            count_5 += 1
        elif c3 == 0 and 4 in vals:
            count_4 += 1
        elif c3 == 1:
            one_3 += 1
        elif c3 >= 2:
            two_plus_3 += 1
            count_3 += 1
        else:
            count_4 += 1

    passing = total - count_2
    quality = round((count_5 + count_4) / total * 100, 1) if total else None
    success = round(passing / total * 100, 1) if total else None
    return {
        "class_name": class_name,
        "total": total,
        "passing": passing,
        "count_5": count_5,
        "count_4": count_4,
        "one_3": one_3,
        "two_plus_3": two_plus_3,
        "count_3": count_3,
        "count_2": count_2,
        "success_percent": success,
        "quality_percent": quality,
    }


def _parallel_summary(class_summaries: list[dict], bucket: str) -> dict[str, Any]:
    subset = [
        s
        for s in class_summaries
        if class_accordion_group(s["class_name"]) == bucket and s["total"] > 0
    ]
    if not subset:
        return {"total": 0, "quality_percent": None, "success_percent": None}
    total = sum(s["total"] for s in subset)
    q_vals = [s["quality_percent"] for s in subset if s["quality_percent"] is not None]
    s_vals = [s["success_percent"] for s in subset if s["success_percent"] is not None]
    return {
        "total": total,
        "quality_percent": round(sum(q_vals) / len(q_vals), 1) if q_vals else None,
        "success_percent": round(sum(s_vals) / len(s_vals), 1) if s_vals else None,
    }


def _enrollment_for_year(
    school_id: int,
    academic_year: int,
    active_names: set[str],
) -> dict[str, Any]:
    """Численность и наполняемость по ступеням."""
    buckets = {"1-4": [], "5-9": [], "10-11": []}
    for name in sorted(active_names, key=class_name_sort_key):
        summary = _class_grade_summary(school_id, name, academic_year)
        bucket = class_accordion_group(name)
        if bucket in buckets and summary["total"] > 0:
            buckets[bucket].append(summary["total"])

    def bucket_stats(counts: list[int]) -> dict:
        if not counts:
            return {"classes": 0, "students": 0, "avg_fill": None}
        return {
            "classes": len(counts),
            "students": sum(counts),
            "avg_fill": round(sum(counts) / len(counts), 1),
        }

    return {
        "year": academic_year,
        "primary": bucket_stats(buckets["1-4"]),
        "basic": bucket_stats(buckets["5-9"]),
        "secondary": bucket_stats(buckets["10-11"]),
        "total_students": sum(
            bucket_stats(buckets[k])["students"] for k in buckets
        ),
        "total_classes": sum(bucket_stats(buckets[k])["classes"] for k in buckets),
    }


def _subject_quality_matrix(
    school_id: int,
    academic_year: int,
    active_names: set[str],
) -> list[dict[str, Any]]:
    """Качество по предметам и классам."""
    reports = get_period_reports(school_id, YEAR_UI_PERIOD, academic_year=academic_year)
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for report in reports:
        if report.class_name not in active_names:
            continue
        subj = normalize_subject_name(report.subject_name, school_id)
        key = (report.class_name, subj)
        if key in seen:
            continue
        seen.add(key)
        grades_data = report_grades_payload(report)
        if not grades_data:
            continue
        qp = grades_data.get("quality_percent")
        sp = grades_data.get("success_percent")
        if qp is None:
            students = grades_data.get("students", []) or []
            s5 = s4 = s3 = s2 = 0
            for st in students:
                g = st.get("grade")
                if g == 5:
                    s5 += 1
                elif g == 4:
                    s4 += 1
                elif g == 3:
                    s3 += 1
                elif g is not None and g <= 2:
                    s2 += 1
            denom = s5 + s4 + s3 + s2
            qp = round((s5 + s4) / denom * 100, 1) if denom else None
            sp = round((s5 + s4 + s3) / denom * 100, 1) if denom else None
        rows.append(
            {
                "class_name": report.class_name,
                "subject": subj,
                "grade": parse_class_grade(report.class_name),
                "quality_percent": qp,
                "success_percent": sp,
            }
        )
    rows.sort(key=lambda r: (r["subject"], class_name_sort_key(r["class_name"])))
    return rows


def _lowest_quality(rows: list[dict], limit: int = 10) -> list[dict]:
    valid = [r for r in rows if r.get("quality_percent") is not None]
    valid.sort(key=lambda r: r["quality_percent"])
    return valid[:limit]


def _add_bar_chart(
    wb: Workbook,
    ws_data,
    *,
    title: str,
    hdr_row: int,
    data_row: int,
    last_col: int,
    chart_idx: int,
    y_max: float = 100,
) -> None:
    sheet_name = excel_chart_sheet_name(wb, title, chart_idx)
    wch = wb.create_sheet(title=sheet_name)
    chart = BarChart()
    chart.type = "col"
    chart.grouping = "clustered"
    chart.title = chart_title_large(title)
    chart.y_axis.scaling = Scaling(min=0, max=y_max)
    chart.y_axis.majorUnit = 10 if y_max >= 50 else None
    chart.dLbls = DataLabelList(showVal=True, showSerName=False, showCatName=False)
    cats = Reference(ws_data, min_col=2, min_row=hdr_row, max_col=last_col)
    ser = Series(
        Reference(ws_data, min_col=2, min_row=data_row, max_col=last_col),
        title_from_data=True,
    )
    chart.append(ser)
    chart.set_categories(cats)
    chart.series[0].graphicalProperties.solidFill = ColorChoice(srgbClr="0D6EFD")
    wch.add_chart(chart, "A1")


def build_final_report_workbook(
    school_id: int,
    *,
    academic_year: int | None = None,
    years_back: int = 3,
    tr: Callable[[str], str],
) -> tuple[BytesIO, str]:
    """Собрать многолистовой Excel итогового отчёта."""
    school = db.session.get(School, school_id)
    school_name = school.name if school else f"School {school_id}"
    anchor_year = resolve_academic_year(academic_year)
    years = _resolve_years(school_id, anchor_year, years_back)
    active_names = _active_class_names(school_id)
    manual_by_year = load_sections_for_years(school_id, years)

    wb = Workbook()
    # --- Сводка ---
    ws_sum = wb.active
    ws_sum.title = tr("final_report_sheet_summary")[:31]
    ws_sum.cell(row=1, column=1, value=tr("final_report_title")).font = Font(bold=True, size=16)
    ws_sum.cell(row=2, column=1, value=school_name)
    ws_sum.cell(row=3, column=1, value=format_academic_year(anchor_year))
    row = 5
    year_agg = aggregate_class_metrics(
        school_id, YEAR_UI_PERIOD, active_names, academic_year=anchor_year
    )
    _write_header_row(ws_sum, row, [tr("metrics_col_indicator"), tr("metrics_row_quality"), tr("metrics_row_success")])
    row += 1
    _write_data_row(
        ws_sum,
        row,
        [
            tr("metrics_excel_school_weighted"),
            year_agg.get("school_quality"),
            year_agg.get("school_success"),
        ],
        number_cols={2, 3},
    )
    row += 2
    for key, label_key in (
        ("1-4", "metrics_excel_parallel_1_4"),
        ("5-9", "metrics_excel_parallel_5_9"),
        ("10-11", "metrics_excel_parallel_10_11"),
    ):
        pr = (year_agg.get("parallel") or {}).get(key) or {}
        _write_data_row(
            ws_sum,
            row,
            [tr(label_key), pr.get("quality"), pr.get("success")],
            number_cols={2, 3},
        )
        row += 1

    # --- Численность ---
    ws_enr = wb.create_sheet(title=tr("final_report_sheet_enrollment")[:31])
    _write_header_row(
        ws_enr,
        1,
        [
            tr("academic_year_label"),
            tr("final_report_col_total_students"),
            tr("final_report_col_total_classes"),
            tr("classes_1_4"),
            tr("classes_5_9"),
            tr("classes_10_11"),
            tr("final_report_col_avg_fill"),
        ],
    )
    er = 2
    for yr in years:
        enr = _enrollment_for_year(school_id, yr, active_names)
        avg_vals = [
            enr["primary"]["avg_fill"],
            enr["basic"]["avg_fill"],
            enr["secondary"]["avg_fill"],
        ]
        avg_vals = [v for v in avg_vals if v is not None]
        avg_all = round(sum(avg_vals) / len(avg_vals), 1) if avg_vals else None
        _write_data_row(
            ws_enr,
            er,
            [
                format_academic_year(yr),
                enr["total_students"],
                enr["total_classes"],
                enr["primary"]["students"],
                enr["basic"]["students"],
                enr["secondary"]["students"],
                avg_all,
            ],
            number_cols={7},
        )
        er += 1

    # --- Успеваемость по классам ---
    class_summaries = [
        _class_grade_summary(school_id, cn, anchor_year)
        for cn in sorted(active_names, key=class_name_sort_key)
    ]
    ws_cls = wb.create_sheet(title=tr("final_report_sheet_classes")[:31])
    cls_headers = [
        tr("class"),
        tr("final_report_col_students"),
        tr("final_report_col_on_5"),
        tr("final_report_col_on_4"),
        tr("final_report_col_one_3"),
        tr("final_report_col_two_3"),
        tr("final_report_col_on_3"),
        tr("final_report_col_on_2"),
        tr("metrics_row_success"),
        tr("metrics_row_quality"),
    ]
    _write_header_row(ws_cls, 1, cls_headers)
    cr = 2
    for s in class_summaries:
        if s["total"] <= 0:
            continue
        _write_data_row(
            ws_cls,
            cr,
            [
                s["class_name"],
                s["total"],
                s["count_5"],
                s["count_4"],
                s["one_3"],
                s["two_plus_3"],
                s["count_3"],
                s["count_2"],
                s["success_percent"],
                s["quality_percent"],
            ],
            number_cols={9, 10},
        )
        cr += 1

    # --- По ступеням ---
    ws_par = wb.create_sheet(title=tr("final_report_sheet_parallels")[:31])
    _write_header_row(
        ws_par,
        1,
        [
            tr("final_report_col_stage"),
            tr("final_report_col_students"),
            tr("metrics_row_quality"),
            tr("metrics_row_success"),
        ],
    )
    pr = 2
    for bucket, label_key in (
        ("1-4", "metrics_excel_sec_1_4"),
        ("5-9", "metrics_excel_sec_5_9"),
        ("10-11", "metrics_excel_parallel_10_11"),
    ):
        ps = _parallel_summary(class_summaries, bucket)
        _write_data_row(
            ws_par,
            pr,
            [tr(label_key), ps["total"], ps["quality_percent"], ps["success_percent"]],
            number_cols={3, 4},
        )
        pr += 1

    # --- По четвертям ---
    ws_q = wb.create_sheet(title=tr("final_report_sheet_quarters")[:31])
    _write_header_row(
        ws_q,
        1,
        [
            tr("quarter_label"),
            tr("metrics_row_quality"),
            tr("metrics_row_success"),
            tr("final_report_col_classes_with_data"),
        ],
    )
    qr = 2
    quarter_chart_hdr = 20
    ws_q.cell(row=quarter_chart_hdr, column=1, value=tr("quarter_label"))
    for qi, qn in enumerate([1, 2, 3, 4, YEAR_UI_PERIOD], start=2):
        label = (
            tr(f"metrics_excel_period_q{qn}")
            if qn <= 4
            else tr("metrics_excel_period_year")
        )
        ws_q.cell(row=quarter_chart_hdr, column=qi, value=label)
    ws_q.cell(row=quarter_chart_hdr + 1, column=1, value=tr("metrics_row_quality"))
    ws_q.cell(row=quarter_chart_hdr + 2, column=1, value=tr("metrics_row_success"))
    for qi, qn in enumerate([1, 2, 3, 4, YEAR_UI_PERIOD], start=2):
        agg = aggregate_class_metrics(
            school_id, qn, active_names, academic_year=anchor_year
        )
        label = (
            tr(f"metrics_excel_period_q{qn}")
            if qn <= 4
            else tr("metrics_excel_period_year")
        )
        _write_data_row(
            ws_q,
            qr,
            [label, agg.get("school_quality"), agg.get("school_success"), agg.get("classes_with_data")],
            number_cols={2, 3},
        )
        ws_q.cell(row=quarter_chart_hdr + 1, column=qi, value=agg.get("school_quality"))
        ws_q.cell(row=quarter_chart_hdr + 2, column=qi, value=agg.get("school_success"))
        qr += 1
    _add_bar_chart(
        wb,
        ws_q,
        title=tr("final_report_chart_quarters"),
        hdr_row=quarter_chart_hdr,
        data_row=quarter_chart_hdr + 1,
        last_col=6,
        chart_idx=0,
    )

    # --- Качество по предметам ---
    subj_rows = _subject_quality_matrix(school_id, anchor_year, active_names)
    ws_subj = wb.create_sheet(title=tr("final_report_sheet_subjects")[:31])
    _write_header_row(
        ws_subj,
        1,
        [tr("subject"), tr("class"), tr("metrics_row_quality"), tr("metrics_row_success")],
    )
    sr = 2
    for r in subj_rows:
        _write_data_row(
            ws_subj,
            sr,
            [r["subject"], r["class_name"], r["quality_percent"], r["success_percent"]],
            number_cols={3, 4},
        )
        sr += 1

    # --- Проблемные зоны ---
    ws_prob = wb.create_sheet(title=tr("final_report_sheet_problems")[:31])
    _write_header_row(
        ws_prob,
        1,
        [tr("class"), tr("subject"), tr("metrics_row_quality")],
    )
    prb = 2
    for r in _lowest_quality(subj_rows):
        _write_data_row(
            ws_prob,
            prb,
            [r["class_name"], r["subject"], r["quality_percent"]],
            number_cols={3},
        )
        prb += 1
    ws_prob.cell(row=prb + 1, column=1, value=tr("final_report_recommendations"))
    ws_prob.cell(row=prb + 2, column=1, value=tr("final_report_rec_weak"))
    ws_prob.cell(row=prb + 3, column=1, value=tr("final_report_rec_math"))

    # --- Отличники ---
    ws_exc = wb.create_sheet(title=tr("final_report_sheet_excellent")[:31])
    _write_header_row(ws_exc, 1, [tr("class"), tr("final_report_col_student_name")])
    exr = 2
    for cn in sorted(active_names, key=class_name_sort_key):
        students = _class_students_map(school_id, cn, anchor_year)
        for name, grades in sorted(students.items(), key=lambda x: kazakh_sort_key(x[0])):
            vals = [g.get("grade") for g in grades.values() if g.get("grade") is not None]
            if vals and all(g >= 5 for g in vals):
                _write_data_row(ws_exc, exr, [cn, name])
                exr += 1

    # --- ГИА / ЕНТ / Аттестаты (ручной ввод) ---
    manual = manual_by_year.get(anchor_year, load_all_sections(school_id, anchor_year))

    def _write_json_sheet(title_key: str, data: Any) -> None:
        ws = wb.create_sheet(title=tr(title_key)[:31])
        ws.cell(row=1, column=1, value=tr(title_key)).font = Font(bold=True, size=14)
        if isinstance(data, dict):
            row_i = 3
            for k, v in data.items():
                if isinstance(v, (list, dict)):
                    ws.cell(row=row_i, column=1, value=str(k))
                    ws.cell(row=row_i, column=2, value=json.dumps(v, ensure_ascii=False, indent=2))
                    row_i += 2
                else:
                    ws.cell(row=row_i, column=1, value=str(k))
                    ws.cell(row=row_i, column=2, value=v)
                    row_i += 1
        else:
            ws.cell(row=3, column=1, value=json.dumps(data, ensure_ascii=False, indent=2))

    _write_json_sheet("final_report_sheet_gia9", manual.get("gia9", {}))
    _write_json_sheet("final_report_sheet_gia11", manual.get("gia11", {}))

    # ЕНТ с диаграммой
    ent = manual.get("ent", {})
    ws_ent = wb.create_sheet(title=tr("final_report_sheet_ent")[:31])
    ws_ent.cell(row=1, column=1, value=tr("final_report_sheet_ent")).font = Font(bold=True, size=14)
    _write_header_row(
        ws_ent,
        3,
        [
            tr("final_report_ent_col_period"),
            tr("final_report_ent_col_count"),
            tr("final_report_ent_col_avg"),
            tr("final_report_ent_col_max"),
        ],
    )
    ent_row = 4
    periods = ent.get("periods") or []
    chart_hdr = 3
    for i, p in enumerate(periods):
        _write_data_row(
            ws_ent,
            ent_row,
            [
                p.get("month") or p.get("period") or "",
                p.get("count"),
                p.get("avg_score"),
                p.get("max_score"),
            ],
            number_cols={3},
        )
        ent_row += 1
    if len(periods) >= 2:
        for i, p in enumerate(periods, start=2):
            ws_ent.cell(row=chart_hdr, column=i, value=p.get("month") or p.get("period") or "")
        ws_ent.cell(row=chart_hdr + 1, column=1, value=tr("final_report_ent_col_avg"))
        for i, p in enumerate(periods, start=2):
            ws_ent.cell(row=chart_hdr + 1, column=i, value=p.get("avg_score"))
        _add_bar_chart(
            wb,
            ws_ent,
            title=tr("final_report_chart_ent"),
            hdr_row=chart_hdr,
            data_row=chart_hdr + 1,
            last_col=1 + len(periods),
            chart_idx=1,
            y_max=140,
        )
    if ent.get("forecast_avg") is not None:
        ws_ent.cell(row=ent_row + 1, column=1, value=tr("final_report_ent_forecast"))
        ws_ent.cell(row=ent_row + 1, column=2, value=ent.get("forecast_avg"))
    if ent.get("recommendations"):
        ws_ent.cell(row=ent_row + 3, column=1, value=tr("final_report_recommendations"))
        ws_ent.cell(row=ent_row + 4, column=1, value=ent.get("recommendations"))

    # Аттестаты
    awards = manual.get("awards", {})
    ws_aw = wb.create_sheet(title=tr("final_report_sheet_awards")[:31])
    ws_aw.cell(row=1, column=1, value=tr("final_report_sheet_awards")).font = Font(bold=True, size=14)
    _write_header_row(
        ws_aw,
        3,
        [
            tr("final_report_awards_altyn"),
            tr("final_report_awards_excellent_11"),
            tr("final_report_awards_excellent_9"),
        ],
    )
    _write_data_row(
        ws_aw,
        4,
        [
            awards.get("altyn_belgi", 0),
            awards.get("excellent_11", 0),
            awards.get("excellent_9", 0),
        ],
    )
    students_aw = awards.get("students") or []
    if students_aw:
        _write_header_row(ws_aw, 6, [tr("final_report_col_student_name"), tr("final_report_col_award_type")])
        ar = 7
        for st in students_aw:
            if isinstance(st, dict):
                _write_data_row(ws_aw, ar, [st.get("name", ""), st.get("award", "")])
            else:
                _write_data_row(ws_aw, ar, [str(st), ""])
            ar += 1

    # Auto column widths
    for ws in wb.worksheets:
        for col in range(1, min(ws.max_column + 1, 12)):
            letter = get_column_letter(col)
            ws.column_dimensions[letter].width = 18

    years_label = "_".join(str(y) for y in years)
    filename = f"Итоговый_отчёт_{years_label}.xlsx"
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return output, filename
