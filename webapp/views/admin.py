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
from openpyxl.chart import BarChart, Series, Reference
from openpyxl.chart.axis import ChartLines, Scaling
from openpyxl.chart.label import DataLabelList
from openpyxl.chart.plotarea import DataTable as ChartDataTable
from openpyxl.chart.shapes import GraphicalProperties
from openpyxl.drawing.colors import ColorChoice
from openpyxl.drawing.line import LineProperties
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from openpyxl.utils import get_column_letter

from ..extensions import db
from ..models import Role, User, GradeReport, Class, ReportFile, TeacherSubject, TeacherClass
from ..security import decrypt_password, encrypt_password
from ..constants import kazakh_sort_key, normalize_subject_name
from ..services.admin_common import apply_analytics_filters, redirect_back
from ..services.admin_dashboard import (
    aggregate_class_metrics,
    aggregate_year_metrics,
    chart_series_from_class_totals,
    class_accordion_group,
    class_name_sort_key,
    get_quarter_reports,
    parse_class_grade,
    student_class_summary_category,
    teacher_accordion_group,
)
from ..services.auth_guards import admin_or_superadmin_required as admin_required
from ..translator import gettext as translate_gettext

from iin_utils import normalize_kz_iin

bp = Blueprint("admin", __name__, url_prefix="/admin")


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
    return {
        "teachers": teachers,
        "classes": classes,
        "teachers_by_accordion": teachers_by_accordion,
        "classes_by_accordion": classes_by_accordion,
    }


@bp.get("/")
@admin_required
def dashboard():
    period_number = int(request.args.get("period_number", 2))
    if period_number < 1 or period_number > 4:
        period_number = 2
    classes = Class.query.filter_by(school_id=current_user.school_id).all()
    active_class_names = {c.name for c in classes}
    school_metrics = aggregate_class_metrics(current_user.school_id, period_number, active_class_names)
    year_metrics = aggregate_year_metrics(current_user.school_id, active_class_names)
    teachers_count = User.query.filter_by(
        role=Role.TEACHER.value, school_id=current_user.school_id
    ).count()
    classes_count = Class.query.filter_by(school_id=current_user.school_id).count()
    return render_template(
        "admin/dashboard.html",
        teachers_count=teachers_count,
        classes_count=classes_count,
        period_number=period_number,
        school_metrics=school_metrics,
        year_metrics=year_metrics,
    )


@bp.get("/management")
@admin_required
def management():
    """Учителя и классы: отдельная страница."""
    return render_template(
        "admin/management.html",
        **_management_list_context(current_user.school_id),
    )


@bp.get("/class-metrics-charts")
@admin_required
def class_metrics_charts():
    """Статистика качества и успеваемости по классам в виде диаграмм."""
    period_number = int(request.args.get("period_number", 2))
    active_class_names = {
        row.name
        for row in Class.query.filter_by(school_id=current_user.school_id).with_entities(Class.name).all()
    }
    agg = aggregate_class_metrics(current_user.school_id, period_number, active_class_names)
    labels, quality_values, success_values = chart_series_from_class_totals(agg["class_totals"])

    lang = session.get("language", "ru")

    def tr_key(key: str) -> str:
        return translate_gettext(key, lang)

    metrics_i18n = {
        "indicator": tr_key("metrics_col_indicator"),
        "total": tr_key("metrics_col_total"),
        "row_quality": tr_key("metrics_row_quality"),
        "row_success": tr_key("metrics_row_success"),
        "chart_quality": tr_key("metrics_chart_quality"),
        "chart_success": tr_key("metrics_chart_success"),
        "class_word": tr_key("metrics_class_word"),
        "parallel_empty": tr_key("metrics_parallel_empty"),
    }

    resp = make_response(
        render_template(
            "admin/class_metrics_charts.html",
            period_number=period_number,
            labels=labels,
            quality_values=quality_values,
            success_values=success_values,
            metrics_i18n=metrics_i18n,
        )
    )
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp


def _avg_pct_metrics(values: list) -> float | None:
    """Среднее по числам в строке метрик (как «Итого» на странице диаграмм)."""
    nums: list[float] = []
    for v in values:
        try:
            if v is not None:
                nums.append(float(v))
        except (TypeError, ValueError):
            pass
    if not nums:
        return None
    return round(sum(nums) / len(nums), 1)


def _excel_chart_sheet_name(wb: Workbook, title: str, index: int) -> str:
    """Имя листа для гистограммы: ≤31 символа, без \\/*?:[], уникально в книге."""
    bad = "\\/*?:[]"
    raw = "".join("_" if c in bad else c for c in (title or "").strip()) or f"График_{index + 1}"
    for n in range(50):
        suffix = "" if n == 0 else f" ({n})"
        base = raw if n == 0 else raw[: max(1, 31 - len(suffix))].rstrip() + suffix
        candidate = base[:31]
        if candidate and candidate not in wb.sheetnames:
            return candidate
    return f"Гр_{index + 1}"[:31]


def _apply_rect_table_borders(
    ws,
    top_row: int,
    bottom_row: int,
    left_col: int,
    right_col: int,
) -> None:
    """Рамка таблицы: снаружи жирнее, внутри «перегородки» между строками/столбцами."""
    v_in = Side(style="thin", color="9CA3AF")
    h_mid = Side(style="medium", color="6C757D")
    out = Side(style="medium", color="495057")
    for rr in range(top_row, bottom_row + 1):
        for cc in range(left_col, right_col + 1):
            left = out if cc == left_col else v_in
            right = out if cc == right_col else v_in
            top = out if rr == top_row else h_mid
            bottom = out if rr == bottom_row else h_mid
            ws.cell(row=rr, column=cc).border = Border(left=left, right=right, top=top, bottom=bottom)


def _chart_title_large(text: str, sz: int = 2200):
    """Заголовок диаграммы Excel с увеличенным шрифтом (sz — размер в 1/100 pt, OOXML)."""
    from openpyxl.chart.text import Text
    from openpyxl.chart.title import Title
    from openpyxl.drawing.text import CharacterProperties, Paragraph, ParagraphProperties, RegularTextRun

    rpr = CharacterProperties(sz=sz, b=True)
    paras = []
    for line in text.split("\n"):
        run = RegularTextRun(t=line)
        run.rPr = rpr
        pp = ParagraphProperties()
        pp.defRPr = CharacterProperties(sz=sz, b=True)
        paras.append(Paragraph(r=[run], pPr=pp))
    t = Title()
    t.tx = Text()
    t.tx.rich.paragraphs = paras
    return t


@bp.get("/class-metrics-charts/download-excel")
@admin_required
def download_class_metrics_charts_excel_legacy():
    """Раньше вид экспорта передавался как ?scope= — перенаправляем на URL с сегментом пути (надёжнее для кэша и url_for)."""
    sk = (request.args.get("scope") or "overall").strip().lower()
    if sk not in ("overall", "parallel"):
        sk = "overall"
    try:
        pn = int(request.args.get("period_number", 2))
    except (TypeError, ValueError):
        pn = 2
    if pn < 1 or pn > 4:
        pn = 2
    return redirect(
        url_for("admin.download_class_metrics_charts_excel", export_kind=sk, period_number=pn),
        code=302,
    )


@bp.get("/class-metrics-charts/download-excel/<export_kind>")
@admin_required
def download_class_metrics_charts_excel(export_kind: str):
    """Книга Excel: лист «Таблицы» — все числа; далее по одному листу на гистограмму. export_kind=overall — «Общее» + сводка; parallel — «По параллелям»."""
    period_number = int(request.args.get("period_number", 2))
    if period_number < 1 or period_number > 4:
        period_number = 2
    export_kind = (export_kind or "").strip().lower()
    if export_kind not in ("overall", "parallel"):
        abort(404)
    scope = export_kind
    lang = session.get("language", "ru")

    def tr(key: str) -> str:
        return translate_gettext(key, lang)

    active_class_names = {
        row.name
        for row in Class.query.filter_by(school_id=current_user.school_id).with_entities(Class.name).all()
    }
    agg = aggregate_class_metrics(current_user.school_id, period_number, active_class_names)
    labels, quality_values, success_values = chart_series_from_class_totals(agg["class_totals"])
    class_totals = agg["class_totals"]

    PAGE_WIDE_COL = 8
    thin_grid = Side(style="thin", color="CED4DA")
    grid_border = Border(left=thin_grid, right=thin_grid, top=thin_grid, bottom=thin_grid)
    table_header_fill = PatternFill(start_color="0D6EFD", end_color="0D6EFD", fill_type="solid")
    header_font_white = Font(bold=True, color="FFFFFF", size=11)
    card_header_fill = PatternFill(start_color="0D6EFD", end_color="0D6EFD", fill_type="solid")
    card_header_font = Font(bold=True, color="FFFFFF", size=13)
    section_label_fill = PatternFill(start_color="F8F9FA", end_color="F8F9FA", fill_type="solid")
    section_label_font = Font(bold=True, size=11, color="0D6EFD")
    sheet_band_fill = PatternFill(start_color="F8F9FA", end_color="F8F9FA", fill_type="solid")
    fill_q = PatternFill(start_color="ECF4FF", end_color="ECF4FF", fill_type="solid")
    fill_s = PatternFill(start_color="D1E7DD", end_color="D1E7DD", fill_type="solid")
    label_font = Font(bold=True, size=10, color="212529")

    rows_data: list[dict] = []
    for i, name in enumerate(labels):
        rows_data.append(
            {
                "name": name,
                "grade": parse_class_grade(name),
                "q": quality_values[i],
                "s": success_values[i],
                "w": int(class_totals.get(name, {}).get("weight_total") or 0),
            }
        )
    rows_data.sort(key=lambda r: class_name_sort_key(r["name"]))

    def filt(pred):
        return [r for r in rows_data if r["grade"] is not None and pred(r["grade"])]

    overall_sections = [
        (tr("metrics_excel_sec_1_4"), lambda g: 1 <= g <= 4, tr("metrics_excel_empty_1_4")),
        (tr("metrics_excel_sec_5_9"), lambda g: 5 <= g <= 9, tr("metrics_excel_empty_5_9")),
        (tr("metrics_excel_sec_9_11"), lambda g: 9 <= g <= 11, tr("metrics_excel_empty_9_11")),
        (tr("metrics_excel_sec_9"), lambda g: g == 9, tr("metrics_excel_empty_9")),
        (tr("metrics_excel_sec_11"), lambda g: g == 11, tr("metrics_excel_empty_11")),
    ]

    grades_parallel = sorted({r["grade"] for r in rows_data if r["grade"] is not None})

    if scope == "overall":
        note_scope = tr("metrics_excel_note_overall")
    else:
        note_scope = tr("metrics_excel_note_parallel")

    wb = Workbook()
    ws = wb.active
    ws.title = tr("metrics_excel_sheet_tables")
    ws.sheet_view.showGridLines = False
    chart_specs: list[dict] = []

    if 1 <= period_number <= 4:
        period_label = tr(f"metrics_excel_period_q{period_number}")
    else:
        period_label = tr("metrics_excel_period_fallback").format(n=period_number)
    r = 1
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=5)
    ws.merge_cells(start_row=r, start_column=6, end_row=r, end_column=PAGE_WIDE_COL)
    t1 = ws.cell(row=r, column=1, value=tr("metrics_excel_title"))
    t1.font = Font(bold=True, size=17, color="212529")
    t1.fill = sheet_band_fill
    t1.alignment = Alignment(horizontal="left", vertical="center", indent=2)
    tper = ws.cell(row=r, column=6, value=period_label)
    tper.font = Font(size=11, color="495057")
    tper.fill = sheet_band_fill
    tper.alignment = Alignment(horizontal="right", vertical="center", indent=2)
    ws.row_dimensions[r].height = 32
    r += 1
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=PAGE_WIDE_COL)
    st = ws.cell(row=r, column=1, value=tr("metrics_excel_subtitle"))
    st.font = Font(size=11, color="6C757D")
    st.fill = sheet_band_fill
    st.alignment = Alignment(horizontal="left", vertical="center", indent=2)
    ws.row_dimensions[r].height = 22
    r += 1
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=PAGE_WIDE_COL)
    tnote = ws.cell(row=r, column=1, value=note_scope)
    tnote.font = Font(size=9, color="6C757D")
    tnote.fill = sheet_band_fill
    tnote.alignment = Alignment(horizontal="left", vertical="center", indent=2, wrap_text=True)
    ws.row_dimensions[r].height = 34
    r += 1
    r += 1
    _apply_rect_table_borders(ws, 1, 3, 1, PAGE_WIDE_COL)

    def write_table_block(title: str, subset: list[dict], empty_msg: str) -> None:
        nonlocal r
        n = len(subset)
        if not subset:
            empty_w = 4
            r_head = r
            ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=empty_w)
            h_empty = ws.cell(row=r, column=1, value=title)
            h_empty.font = card_header_font
            h_empty.fill = card_header_fill
            h_empty.alignment = Alignment(horizontal="left", vertical="center", indent=2)
            ws.row_dimensions[r].height = 22
            r += 1
            r_msg = r
            ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=empty_w)
            em = ws.cell(row=r, column=1, value=empty_msg)
            em.font = Font(italic=True, size=10, color="6C757D")
            em.fill = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")
            em.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True, indent=2)
            ws.row_dimensions[r].height = 22
            r += 1
            _apply_rect_table_borders(ws, r_head, r_msg, 1, empty_w)
            r += 1
            r += 1
            return

        last_tot_col = 2 + n
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=last_tot_col)
        h = ws.cell(row=r, column=1, value=title)
        h.font = card_header_font
        h.fill = card_header_fill
        h.alignment = Alignment(horizontal="left", vertical="center", indent=2)
        ws.row_dimensions[r].height = 24
        r += 1

        qvals = [rec["q"] for rec in subset]
        svals = [rec["s"] for rec in subset]
        q_tot = _avg_pct_metrics(qvals)
        s_tot = _avg_pct_metrics(svals)

        hdr_row = r
        c0 = ws.cell(row=hdr_row, column=1, value=tr("metrics_col_indicator"))
        c0.font = header_font_white
        c0.fill = table_header_fill
        c0.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        for i, rec in enumerate(subset, start=2):
            chc = ws.cell(row=hdr_row, column=i, value=rec["name"])
            chc.font = header_font_white
            chc.fill = table_header_fill
            chc.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ct = ws.cell(row=hdr_row, column=last_tot_col, value=tr("metrics_col_total"))
        ct.font = header_font_white
        ct.fill = table_header_fill
        ct.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.row_dimensions[hdr_row].height = 20

        row_q = hdr_row + 1
        ws.cell(row=row_q, column=1, value=tr("metrics_row_quality")).font = label_font
        ws.cell(row=row_q, column=1).alignment = Alignment(horizontal="left", vertical="center", indent=2)
        ws.cell(row=row_q, column=1).fill = fill_q
        for ci, v in enumerate(qvals, start=2):
            cell = ws.cell(row=row_q, column=ci, value=v)
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.fill = fill_q
            if isinstance(v, (int, float)):
                cell.number_format = "0.0"
        cqt = ws.cell(
            row=row_q,
            column=last_tot_col,
            value=q_tot if q_tot is not None else "—",
        )
        cqt.alignment = Alignment(horizontal="center", vertical="center")
        cqt.font = Font(bold=True, size=10)
        cqt.fill = fill_q
        if q_tot is not None:
            cqt.number_format = "0.0"

        row_s = hdr_row + 2
        ws.cell(row=row_s, column=1, value=tr("metrics_row_success")).font = label_font
        ws.cell(row=row_s, column=1).alignment = Alignment(horizontal="left", vertical="center", indent=2)
        ws.cell(row=row_s, column=1).fill = fill_s
        for ci, v in enumerate(svals, start=2):
            cell = ws.cell(row=row_s, column=ci, value=v)
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.fill = fill_s
            if isinstance(v, (int, float)):
                cell.number_format = "0.0"
        cst = ws.cell(
            row=row_s,
            column=last_tot_col,
            value=s_tot if s_tot is not None else "—",
        )
        cst.alignment = Alignment(horizontal="center", vertical="center")
        cst.font = Font(bold=True, size=10)
        cst.fill = fill_s
        if s_tot is not None:
            cst.number_format = "0.0"
        ws.row_dimensions[row_q].height = 19
        ws.row_dimensions[row_s].height = 19

        _apply_rect_table_borders(ws, hdr_row, row_s, 1, last_tot_col)

        chart_specs.append(
            {
                "title": title,
                "hdr_row": hdr_row,
                "row_q": row_q,
                "row_s": row_s,
                "last_tot_col": last_tot_col,
                "n": n,
            }
        )
        r = row_s + 1
        r += 2

    def append_histogram_sheets() -> None:
        for idx, spec in enumerate(chart_specs):
            title = spec["title"]
            hdr_row = spec["hdr_row"]
            row_q = spec["row_q"]
            row_s = spec["row_s"]
            last_tot_col = spec["last_tot_col"]
            n = spec["n"]
            wsheet = _excel_chart_sheet_name(wb, title, idx)
            wch = wb.create_sheet(title=wsheet)
            chart = BarChart()
            chart.type = "col"
            chart.grouping = "clustered"
            chart.varyColors = False
            chart.style = 2
            chart.title = _chart_title_large(title)
            chart.title.overlay = False
            # У openpyxl по умолчанию у catAx и valAx axPos="l" — для столбчатой диаграммы нужно X снизу, Y слева.
            chart.x_axis.axPos = "b"
            chart.y_axis.axPos = "l"
            # Явно «не удалять» оси — в Excel галочка «Оси» в элементах диаграммы (delete val="0" в XML).
            chart.x_axis.delete = False
            chart.y_axis.delete = False
            chart.y_axis.title = "%"
            chart.y_axis.scaling = Scaling(min=0, max=100)
            chart.y_axis.majorUnit = 10
            chart.y_axis.tickLblPos = "nextTo"
            chart.y_axis.spPr = GraphicalProperties(
                ln=LineProperties(
                    w=19050,
                    solidFill=ColorChoice(srgbClr="495057"),
                )
            )
            chart.y_axis.majorGridlines = ChartLines(
                spPr=GraphicalProperties(
                    ln=LineProperties(
                        w=6350,
                        solidFill=ColorChoice(srgbClr="DEE2E6"),
                    )
                )
            )
            chart.plot_area.spPr = GraphicalProperties(
                noFill=True,
                ln=LineProperties(noFill=True),
            )
            chart.x_axis.lblAlgn = "ctr"
            chart.x_axis.tickLblPos = "low"
            chart.x_axis.spPr = GraphicalProperties(
                ln=LineProperties(
                    w=19050,
                    solidFill=ColorChoice(srgbClr="495057"),
                )
            )
            chart.gapWidth = 78
            # Явно только значение — иначе Excel показывает «ряд; категория; значение» и всё слипается.
            chart.dLbls = DataLabelList(
                showVal=True,
                showSerName=False,
                showCatName=False,
                showLegendKey=False,
                dLblPos="inEnd",
            )
            chart.width = min(36.0, max(15.0, 5.5 + (n + 1) * 1.28))
            if n <= 2:
                chart.height = 12.0
            elif n <= 6:
                chart.height = 13.0
            elif n <= 12:
                chart.height = 14.5
            else:
                chart.height = 16.0

            cats = Reference(ws, min_col=2, min_row=hdr_row, max_col=last_tot_col)
            ser_q = Series(
                Reference(ws, min_col=2, min_row=row_q, max_col=last_tot_col),
                title=tr("metrics_row_quality"),
            )
            ser_s = Series(
                Reference(ws, min_col=2, min_row=row_s, max_col=last_tot_col),
                title=tr("metrics_row_success"),
            )
            chart.append(ser_q)
            chart.append(ser_s)
            chart.set_categories(cats)
            chart.series[0].graphicalProperties.solidFill = ColorChoice(srgbClr="0D6EFD")
            chart.series[1].graphicalProperties.solidFill = ColorChoice(srgbClr="198754")
            chart.plot_area.dTable = ChartDataTable(
                showHorzBorder=True,
                showVertBorder=True,
                showOutline=True,
                showKeys=True,
            )
            chart.legend = None
            wch.add_chart(chart, "A1")

    if scope == "overall":
        row_ob = r
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=PAGE_WIDE_COL)
        tab_o = ws.cell(row=r, column=1, value=tr("metrics_excel_section_overall"))
        tab_o.font = section_label_font
        tab_o.fill = section_label_fill
        tab_o.alignment = Alignment(horizontal="left", vertical="center", indent=2)
        ws.row_dimensions[r].height = 24
        r += 1
        r += 1
        _apply_rect_table_borders(ws, row_ob, row_ob, 1, PAGE_WIDE_COL)

        first_block_row = r

        for title, pred, empty_msg in overall_sections:
            write_table_block(title, filt(pred), empty_msg)

        row_sv = r
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=PAGE_WIDE_COL)
        sv = ws.cell(row=r, column=1, value=tr("metrics_excel_section_summary"))
        sv.font = section_label_font
        sv.fill = section_label_fill
        sv.alignment = Alignment(horizontal="left", vertical="center", indent=2)
        ws.row_dimensions[r].height = 24
        r += 1
        _apply_rect_table_borders(ws, row_sv, row_sv, 1, PAGE_WIDE_COL)

        sum_top = r
        sq, ss = agg.get("school_quality"), agg.get("school_success")
        for col, val in enumerate(
            (tr("metrics_col_indicator"), tr("metrics_row_quality"), tr("metrics_row_success")),
            start=1,
        ):
            c = ws.cell(row=r, column=col, value=val)
            c.font = header_font_white
            c.fill = table_header_fill
            c.border = grid_border
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.row_dimensions[r].height = 19
        r += 1

        c_school = ws.cell(row=r, column=1, value=tr("metrics_excel_school_weighted"))
        c_school.border = grid_border
        c_school.alignment = Alignment(horizontal="left", vertical="center", indent=2)
        c_school.font = Font(size=10, color="212529")
        for col, val in ((2, sq), (3, ss)):
            cell = ws.cell(row=r, column=col, value=val if val is not None else "—")
            cell.border = grid_border
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.font = Font(size=10)
            if isinstance(val, (int, float)):
                cell.number_format = "0.0"
        ws.row_dimensions[r].height = 18
        r += 1

        parallel = agg.get("parallel") or {}
        for pkey, title in (
            ("1-4", tr("metrics_excel_parallel_1_4")),
            ("5-9", tr("metrics_excel_parallel_5_9")),
            ("10-11", tr("metrics_excel_parallel_10_11")),
        ):
            pr = parallel.get(pkey) or {}
            pq, ps = pr.get("quality"), pr.get("success")
            c1 = ws.cell(row=r, column=1, value=title)
            c1.border = grid_border
            c1.alignment = Alignment(horizontal="left", vertical="center", indent=2)
            c1.font = Font(size=10, color="212529")
            for col, val in ((2, pq), (3, ps)):
                cell = ws.cell(row=r, column=col, value=val if val is not None else "—")
                cell.border = grid_border
                cell.alignment = Alignment(horizontal="center", vertical="center")
                cell.font = Font(size=10)
                if isinstance(val, (int, float)):
                    cell.number_format = "0.0"
            ws.row_dimensions[r].height = 18
            r += 1
        _apply_rect_table_borders(ws, sum_top, r - 1, 1, 3)
    else:
        row_tp = r
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=PAGE_WIDE_COL)
        tab_p = ws.cell(row=r, column=1, value=tr("metrics_excel_section_parallel"))
        tab_p.font = section_label_font
        tab_p.fill = section_label_fill
        tab_p.alignment = Alignment(horizontal="left", vertical="center", indent=2)
        ws.row_dimensions[r].height = 24
        r += 1
        r += 1
        _apply_rect_table_borders(ws, row_tp, row_tp, 1, PAGE_WIDE_COL)

        first_block_row = r

        for g in grades_parallel:
            sub = [x for x in rows_data if x["grade"] == g]
            write_table_block(
                f"{g} {tr('metrics_class_word')}",
                sub,
                tr("metrics_parallel_empty").format(grade=g),
            )

    for spec in chart_specs:
        for col_i in range(2, spec["last_tot_col"] + 1):
            letter = get_column_letter(col_i)
            prev = ws.column_dimensions[letter].width
            ws.column_dimensions[letter].width = max(float(prev or 10), 11.0)

    append_histogram_sheets()

    ws.freeze_panes = f"A{first_block_row}"
    ws.column_dimensions["A"].width = 26
    for col_i in range(2, 15):
        letter = get_column_letter(col_i)
        prev = ws.column_dimensions[letter].width
        ws.column_dimensions[letter].width = max(float(prev or 10), 11.5)

    suffix_key = "metrics_excel_fn_suf_o" if scope == "overall" else "metrics_excel_fn_suf_p"
    filename_local = tr("metrics_excel_fn_pattern").format(period=period_number, suffix=tr(suffix_key))
    suffix_ascii = "overall" if scope == "overall" else "parallel"
    filename_ascii = f"stat_classes_{period_number}ch_{suffix_ascii}.xlsx"
    wb.properties.title = filename_local.replace(".xlsx", "")

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    resp = send_file(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename_ascii,
    )
    # Явное имя UTF-8 — иначе Edge/Excel иногда подставляют старое имя или заголовок из ячейки A1.
    resp.headers["Content-Disposition"] = (
        f'attachment; filename="{filename_ascii}"; filename*=UTF-8\'\'{quote(filename_local)}'
    )
    # GET-скачивание часто кэшируется браузером — без этого виден «старый» xlsx после правок сервера.
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp


@bp.post("/teachers/create")
@admin_required
def create_teacher():
    username = request.form.get("username", "").strip()
    full_name = request.form.get("full_name", "").strip()
    iin_raw = request.form.get("iin", "").strip()
    if not username:
        flash("Логин учителя обязателен.", "danger")
        return redirect_back(url_for("admin.management") + "#teachers-tab")
    if User.query.filter_by(username=username).first():
        flash("Такой логин уже существует.", "danger")
        return redirect_back(url_for("admin.management") + "#teachers-tab")

    iin_norm = normalize_kz_iin(iin_raw) if iin_raw else None
    if not iin_norm:
        flash("Укажите корректный ИИН (ЖСН): 12 цифр — тот же номер, что для входа на mektep.edu.kz.", "danger")
        return redirect_back(url_for("admin.management") + "#teachers-tab")
    if _iin_taken_by_other_teacher(current_user.school_id, iin_norm):
        flash("Этот ИИН уже привязан к другому учителю в школе.", "danger")
        return redirect_back(url_for("admin.management") + "#teachers-tab")

    pw = secrets.token_urlsafe(8)
    u = User(
        username=username,
        full_name=full_name or username,
        iin=iin_norm,
        role=Role.TEACHER.value,
        school_id=current_user.school_id,
        is_active=True,
    )
    # Assign per-school sequential number for filesystem paths (teacher_1, teacher_2, ...)
    max_seq = (
        db.session.query(func.max(User.fs_teacher_seq))
        .filter(User.school_id == current_user.school_id, User.role == Role.TEACHER.value)
        .scalar()
    )
    u.fs_teacher_seq = int(max_seq or 0) + 1
    u.set_password(pw)
    u.password_enc = encrypt_password(pw, current_app.config.get("PASSWORD_ENC_KEY", ""))
    db.session.add(u)
    db.session.commit()
    flash(f"Учитель создан. Пароль: {pw}", "success")
    return _redirect_back(url_for("admin.management") + "#teachers-tab")


@bp.post("/teachers/import")
@admin_required
def import_teachers():

    file = request.files.get("file")
    if not file or not file.filename:
        flash("Выберите Excel-файл для импорта.", "danger")
        return _redirect_back(url_for("admin.management") + "#teachers-tab")

    if not file.filename.lower().endswith(".xlsx"):
        flash("Поддерживается только формат .xlsx.", "danger")
        return _redirect_back(url_for("admin.management") + "#teachers-tab")

    try:
        wb = load_workbook(file, data_only=True)
        ws = wb.active
    except Exception:
        flash("Не удалось прочитать Excel-файл.", "danger")
        return _redirect_back(url_for("admin.management") + "#teachers-tab")

    header_cells = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), None)
    if not header_cells:
        flash("Файл пустой или не содержит заголовков.", "danger")
        return _redirect_back(url_for("admin.management") + "#teachers-tab")

    headers = [str(v).strip().lower() if v is not None else "" for v in header_cells]
    header_map = {name: idx for idx, name in enumerate(headers)}

    required_headers = ("фио", "логин", "пароль")
    missing = [h for h in required_headers if h not in header_map]
    if missing:
        flash(f"Не найдены обязательные столбцы: {', '.join(missing)}.", "danger")
        return _redirect_back(url_for("admin.management") + "#teachers-tab")

    fio_idx = header_map["фио"]
    login_idx = header_map["логин"]
    password_idx = header_map["пароль"]
    iin_idx = header_map.get("иин")
    if iin_idx is None:
        iin_idx = header_map.get("жсн")
    if iin_idx is None:
        flash("В Excel нужен столбец «ИИН» или «ЖСН» (12 цифр).", "danger")
        return _redirect_back(url_for("admin.management") + "#teachers-tab")

    max_seq = (
        db.session.query(func.max(User.fs_teacher_seq))
        .filter(User.school_id == current_user.school_id, User.role == Role.TEACHER.value)
        .scalar()
    )
    next_seq = int(max_seq or 0) + 1

    created = 0
    skipped = 0
    seen_usernames = set()

    for row in ws.iter_rows(min_row=2, values_only=True):
        full_name_raw = row[fio_idx] if fio_idx < len(row) else None
        username_raw = row[login_idx] if login_idx < len(row) else None
        password_raw = row[password_idx] if password_idx < len(row) else None
        iin_raw = None
        if iin_idx is not None and iin_idx < len(row):
            iin_raw = row[iin_idx]

        full_name = str(full_name_raw).strip() if full_name_raw is not None else ""
        username = str(username_raw).strip() if username_raw is not None else ""
        password = str(password_raw).strip() if password_raw is not None else ""
        iin_norm = normalize_kz_iin(str(iin_raw).strip() if iin_raw is not None else "") if iin_raw is not None else None

        # Пропускаем полностью пустые строки.
        if not full_name and not username and not password:
            continue

        if not username or not password:
            skipped += 1
            continue

        if not iin_norm:
            skipped += 1
            continue

        if _iin_taken_by_other_teacher(current_user.school_id, iin_norm):
            skipped += 1
            continue

        username_key = username.lower()
        if username_key in seen_usernames:
            skipped += 1
            continue
        if User.query.filter_by(username=username).first():
            skipped += 1
            continue

        seen_usernames.add(username_key)

        u = User(
            username=username,
            full_name=full_name or username,
            iin=iin_norm,
            role=Role.TEACHER.value,
            school_id=current_user.school_id,
            is_active=True,
            fs_teacher_seq=next_seq,
        )
        next_seq += 1
        u.set_password(password)
        u.password_enc = encrypt_password(password, current_app.config.get("PASSWORD_ENC_KEY", ""))
        db.session.add(u)
        created += 1

    db.session.commit()

    category = "success" if created else "warning"
    flash(f"Импорт завершён: добавлено {created}, пропущено {skipped}.", category)
    return _redirect_back(url_for("admin.management") + "#teachers-tab")


@bp.get("/teachers/import/template")
@admin_required
def download_teachers_import_template():

    wb = Workbook()
    ws = wb.active
    ws.title = "Шаблон"
    ws.append(["ФИО", "ИИН", "логин", "пароль"])
    ws.append(["Иванов Иван Иванович", "850101300123", "ivanov_i_i", "TempPass123"])

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    return send_file(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="Шаблон_импорта_учителей.xlsx",
    )


@bp.get("/teachers/<int:user_id>/password")
@admin_required
def get_teacher_password(user_id: int):
    """AJAX endpoint: return password as JSON."""
    u = db.session.get(User, user_id)
    if not u or u.role != Role.TEACHER.value or u.school_id != current_user.school_id:
        return jsonify({"error": "Not found"}), 404
    pw = decrypt_password(u.password_enc, current_app.config.get("PASSWORD_ENC_KEY", ""))
    return jsonify({"username": u.username, "password": pw or "Недоступен"})


@bp.post("/teachers/<int:user_id>/password")
@admin_required
def update_teacher_password(user_id: int):
    """Update teacher password."""
    u = db.session.get(User, user_id)
    if not u or u.role != Role.TEACHER.value or u.school_id != current_user.school_id:
        flash("Пользователь не найден.", "danger")
        return _redirect_back(url_for("admin.management") + "#teachers-tab")
    new_password = request.form.get("new_password", "").strip()
    if not new_password or len(new_password) < 4:
        flash("Пароль должен быть не менее 4 символов.", "danger")
        return _redirect_back(url_for("admin.management") + "#teachers-tab")
    u.set_password(new_password)
    u.password_enc = encrypt_password(new_password, current_app.config.get("PASSWORD_ENC_KEY", ""))
    db.session.commit()
    flash(f"Пароль для {u.username} обновлен.", "success")
    return _redirect_back(url_for("admin.management") + "#teachers-tab")


@bp.post("/teachers/<int:user_id>/edit")
@admin_required
def edit_teacher(user_id: int):
    """Редактирование ФИО и ИИН учителя."""
    u = db.session.get(User, user_id)
    if not u or u.role != Role.TEACHER.value or u.school_id != current_user.school_id:
        flash("Учитель не найден.", "danger")
        return _redirect_back(url_for("admin.management") + "#teachers-tab")
    full_name = request.form.get("full_name", "").strip()
    if not full_name:
        flash("ФИО не может быть пустым.", "danger")
        return _redirect_back(url_for("admin.management") + "#teachers-tab")
    iin_raw = request.form.get("iin", "").strip()
    iin_norm = normalize_kz_iin(iin_raw) if iin_raw else None
    if not iin_norm:
        flash("Укажите корректный ИИН (ЖСН): 12 цифр.", "danger")
        return _redirect_back(url_for("admin.management") + "#teachers-tab")
    if _iin_taken_by_other_teacher(current_user.school_id, iin_norm, exclude_id=u.id):
        flash("Этот ИИН уже привязан к другому учителю.", "danger")
        return _redirect_back(url_for("admin.management") + "#teachers-tab")
    u.full_name = full_name
    u.iin = iin_norm
    db.session.commit()
    flash(f'Данные учителя обновлены: «{full_name}».', "success")
    return _redirect_back(url_for("admin.management") + "#teachers-tab")


@bp.post("/teachers/<int:user_id>/delete")
@admin_required
def delete_teacher(user_id: int):
    """Удаление учителя и всех его данных."""
    u = db.session.get(User, user_id)
    if not u or u.role != Role.TEACHER.value or u.school_id != current_user.school_id:
        flash("Учитель не найден.", "danger")
        return _redirect_back(url_for("admin.management") + "#teachers-tab")
    
    teacher_name = u.full_name or u.username
    
    # Удаляем связанные данные
    GradeReport.query.filter_by(teacher_id=u.id).delete()
    ReportFile.query.filter_by(teacher_id=u.id).delete()
    
    # Удаляем связи учитель-класс и учитель-предмет
    teacher_subjects = TeacherSubject.query.filter_by(teacher_id=u.id).all()
    for ts in teacher_subjects:
        TeacherClass.query.filter_by(teacher_subject_id=ts.id).delete()
    TeacherSubject.query.filter_by(teacher_id=u.id).delete()
    
    # Снимаем классное руководство
    Class.query.filter_by(class_teacher_id=u.id).update({"class_teacher_id": None})
    
    db.session.delete(u)
    db.session.commit()
    flash(f'Учитель "{teacher_name}" удалён.', "success")
    return _redirect_back(url_for("admin.management") + "#teachers-tab")


# ==============================================================================
# Class CRUD Routes
# ==============================================================================

@bp.post("/classes/create")
@admin_required
def create_class():
    """Создание класса"""
    name = request.form.get("name", "").strip()
    class_teacher_id = request.form.get("class_teacher_id")
    if not name:
        flash("Название класса обязательно.", "danger")
        return _redirect_back(url_for("admin.management") + "#classes-tab")
    # Проверяем дубликат
    existing = Class.query.filter_by(school_id=current_user.school_id, name=name).first()
    if existing:
        flash(f'Класс "{name}" уже существует.', "danger")
        return _redirect_back(url_for("admin.management") + "#classes-tab")
    cls = Class(name=name, school_id=current_user.school_id)
    if class_teacher_id:
        cls.class_teacher_id = int(class_teacher_id)
    db.session.add(cls)
    db.session.commit()
    flash(f'Класс "{name}" создан.', "success")
    return _redirect_back(url_for("admin.management") + "#classes-tab")


@bp.post("/classes/<int:class_id>/edit")
@admin_required
def edit_class(class_id: int):
    """Редактирование класса"""
    cls = db.session.get(Class, class_id)
    if not cls or cls.school_id != current_user.school_id:
        flash("Класс не найден.", "danger")
        return _redirect_back(url_for("admin.management") + "#classes-tab")
    name = request.form.get("name", "").strip()
    if name:
        # Проверяем, нет ли другого класса с таким именем
        dup = Class.query.filter_by(school_id=current_user.school_id, name=name).first()
        if dup and dup.id != class_id:
            flash(f'Класс "{name}" уже существует.', "danger")
            return _redirect_back(url_for("admin.management") + "#classes-tab")
        cls.name = name
    class_teacher_id = request.form.get("class_teacher_id")
    cls.class_teacher_id = int(class_teacher_id) if class_teacher_id else None
    db.session.commit()
    flash(f'Класс "{cls.name}" обновлён.', "success")
    return _redirect_back(url_for("admin.management") + "#classes-tab")


@bp.post("/classes/<int:class_id>/delete")
@admin_required
def delete_class(class_id: int):
    """Удаление класса из списка школы вместе с оценками (GradeReport) и записями файлов отчётов по этому классу."""
    cls = db.session.get(Class, class_id)
    if not cls or cls.school_id != current_user.school_id:
        flash("Класс не найден.", "danger")
        return _redirect_back(url_for("admin.management") + "#classes-tab")
    name = cls.name
    school_id = cls.school_id

    report_files = ReportFile.query.filter_by(school_id=school_id, class_name=name).all()
    for rf in report_files:
        for path_str in (rf.excel_path, rf.word_path):
            if path_str:
                try:
                    Path(path_str).unlink(missing_ok=True)
                except OSError:
                    pass
        db.session.delete(rf)

    grades_n = GradeReport.query.filter_by(school_id=school_id, class_name=name).delete(
        synchronize_session=False
    )

    # Явно удаляем связи учитель-предмет-класс, чтобы ORM не пытался
    # проставлять class_id = NULL (поле NOT NULL в teacher_classes).
    TeacherClass.query.filter_by(class_id=class_id).delete(synchronize_session=False)
    db.session.delete(cls)
    db.session.commit()
    flash(
        f'Класс «{name}» удалён. Удалено записей оценок: {grades_n}, файлов отчётов: {len(report_files)}.',
        "success",
    )
    return _redirect_back(url_for("admin.management") + "#classes-tab")


# ==============================================================================
# Grades Overview Routes
# ==============================================================================

@bp.get("/grades")
@admin_required
def grades_overview():
    """Обзор оценок: список классов со сводкой"""
    
    # Параметры фильтрации (только четверти)
    period_number = int(request.args.get("period_number", 2))

    active_class_names = {
        row.name
        for row in Class.query.filter_by(school_id=current_user.school_id).with_entities(Class.name).all()
    }
    
    # Получаем отчёты (включая полугодовые для четвертей 2/4)
    reports = get_quarter_reports(current_user.school_id, period_number)
    
    # Группируем по классам (только классы из актуального списка школы — как на диаграммах)
    classes_data = {}
    for report in reports:
        class_name = report.class_name
        if class_name not in active_class_names:
            continue
        if class_name not in classes_data:
            classes_data[class_name] = {
                "class_name": class_name,
                "subjects": [],
                "students_count": 0,
                "quality_percent": 0,
                "success_percent": 0
            }
        
        subj_norm = normalize_subject_name(report.subject_name)
        if subj_norm not in classes_data[class_name]["subjects"]:
            classes_data[class_name]["subjects"].append(subj_norm)
        
        # Собираем статистику
        if report.grades_json:
            try:
                grades_data = json.loads(report.grades_json)
                classes_data[class_name]["students_count"] = max(
                    classes_data[class_name]["students_count"],
                    grades_data.get("total_students", 0)
                )
            except json.JSONDecodeError:
                pass
    
    # Сортируем классы
    sorted_classes = sorted(classes_data.values(), key=lambda x: kazakh_sort_key(x["class_name"]))
    
    # Группировка по аккордеонам (1-4, 5-9, 10-11)
    classes_by_accordion = {"1-4": [], "5-9": [], "10-11": []}
    for cls in sorted_classes:
        group = class_accordion_group(cls["class_name"])
        classes_by_accordion[group].append(cls)
    
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
    period_number = int(request.args.get("period_number", 2))

    if not Class.query.filter_by(school_id=current_user.school_id, name=class_name).first():
        flash(
            "Этого класса нет в списке школы (возможно, он удалён). Данные в отчётах остаются в базе, но страница недоступна.",
            "warning",
        )
        return redirect(url_for("admin.grades_overview", period_number=period_number))
    
    # Получаем все отчёты для этого класса (включая полугодовые для 2/4)
    reports = get_quarter_reports(current_user.school_id, period_number, class_name=class_name)
    
    # Собираем данные
    subjects = set()
    students_data = {}  # name -> {subject -> {percent, grade}}
    
    for report in reports:
        subj = normalize_subject_name(report.subject_name)
        subjects.add(subj)
        
        if report.grades_json:
            try:
                grades_data = json.loads(report.grades_json)
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

    quality_percent = 0
    success_percent = 0
    if total_students > 0:
        quality_percent = round(
            (grades_count["5"] + grades_count["4"]) / total_students * 100, 1
        )
        success_percent = round(
            (grades_count["5"] + grades_count["4"] + grades_count["3"])
            / total_students
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


@bp.post("/grades/class/<class_name>/subjects/delete")
@admin_required
def delete_subject_from_class(class_name: str):
    """Удаление предмета из отчетов указанного класса за выбранную четверть."""

    subject_name = (request.form.get("subject_name") or "").strip()
    period_raw = request.form.get("period_number", "2")
    try:
        period_number = int(period_raw)
    except (TypeError, ValueError):
        period_number = 2

    if not subject_name:
        flash("Не указан предмет для удаления.", "danger")
        return _redirect_back(url_for("admin.grades_class", class_name=class_name, period_number=period_number))

    target_subject = normalize_subject_name(subject_name)

    # Удаляем GradeReport по текущему классу и предмету ТОЛЬКО за выбранную четверть.
    # Для 2 и 4 четвертей дополнительно удаляем соответствующее полугодие.
    reports = GradeReport.query.filter_by(
        school_id=current_user.school_id,
        class_name=class_name,
    ).all()

    allowed_periods = {("quarter", period_number)}
    if period_number == 2:
        allowed_periods.add(("semester", 1))
    elif period_number == 4:
        allowed_periods.add(("semester", 2))

    reports_to_delete = [
        r for r in reports
        if normalize_subject_name(r.subject_name) == target_subject
        and (r.period_type, r.period_number) in allowed_periods
    ]

    # Удаляем связанные записи ReportFile только за выбранную четверть.
    # ReportFile хранит period_code как код четверти (1..4).
    report_files = ReportFile.query.filter_by(
        school_id=current_user.school_id,
        class_name=class_name,
    ).all()
    files_to_delete = [
        rf for rf in report_files
        if normalize_subject_name(rf.subject) == target_subject
        and str(rf.period_code) == str(period_number)
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
    period_number = int(request.args.get("period_number", 2))
    segment = request.args.get("segment")  # '1-4' или '5-11' или None
    
    # Получаем отчёты (включая полугодовые для четвертей 2/4)
    reports = get_quarter_reports(current_user.school_id, period_number)
    active_class_names = {
        row.name
        for row in Class.query.filter_by(school_id=current_user.school_id).with_entities(Class.name).all()
    }
    
    # Группируем по предмету
    # subjects_data_sor:    { subject_name -> [{ class_name, sor_list, teacher, has_data }] }
    # subjects_data_soch:   { subject_name -> [{ class_name, count_5..2, total, quality, success_rate, teacher, has_data }] }
    # subjects_data_grades: { subject_name -> [{ class_name, count_5..2, total, quality, success_rate, teacher, has_data }] }
    
    subjects_data_sor = {}
    subjects_data_soch = {}
    subjects_data_grades = {}
    
    for report in reports:
        subj = normalize_subject_name(report.subject_name)
        cls = report.class_name
        if cls not in active_class_names:
            continue
        # Фильтрация по сегменту классов 1-4 / 5-11, если указан
        grade_str = ""
        for ch in str(cls):
            if ch.isdigit():
                grade_str += ch
            else:
                break
        grade_num = int(grade_str) if grade_str else None
        if segment == "1-4" and not (grade_num and 1 <= grade_num <= 4):
            continue
        if segment == "5-11" and not (grade_num and 5 <= grade_num <= 11):
            continue
        teacher_name = ""
        # Получаем имя учителя
        if report.teacher:
            teacher_name = report.teacher.full_name or report.teacher.username
        
        # --- СОР / СОЧ из analytics_json ---
        if report.analytics_json:
            try:
                analytics = json.loads(report.analytics_json)
                
                # СОР
                sor_list = analytics.get("sor", [])
                # Добавляем total, quality, success_rate к каждому СОР если нет
                for sor in sor_list:
                    total = (sor.get("count_5", 0) + sor.get("count_4", 0) +
                             sor.get("count_3", 0) + sor.get("count_2", 0))
                    sor["total"] = total
                    if total > 0:
                        sor["quality"] = round((sor.get("count_5", 0) + sor.get("count_4", 0)) / total * 100, 1)
                        sor["success_rate"] = round((total - sor.get("count_2", 0)) / total * 100, 1)
                    else:
                        sor["quality"] = None
                        sor["success_rate"] = None
                
                if subj not in subjects_data_sor:
                    subjects_data_sor[subj] = []
                subjects_data_sor[subj].append({
                    "class_name": cls,
                    "sor_list": sor_list,
                    "teacher": teacher_name,
                    "has_data": len(sor_list) > 0
                })
                
                # СОЧ
                soch = analytics.get("soch", {})
                if soch:
                    s5 = soch.get("count_5", 0)
                    s4 = soch.get("count_4", 0)
                    s3 = soch.get("count_3", 0)
                    s2 = soch.get("count_2", 0)
                    total = s5 + s4 + s3 + s2
                    if subj not in subjects_data_soch:
                        subjects_data_soch[subj] = []
                    subjects_data_soch[subj].append({
                        "class_name": cls,
                        "count_5": s5, "count_4": s4, "count_3": s3, "count_2": s2,
                        "total": total,
                        "quality": round((s5 + s4) / total * 100, 1) if total else None,
                        "success_rate": round((total - s2) / total * 100, 1) if total else None,
                        "teacher": teacher_name,
                        "has_data": total > 0
                    })
            except json.JSONDecodeError:
                pass
        
        # --- Оценки из grades_json ---
        if report.grades_json:
            try:
                grades_data = json.loads(report.grades_json)
                s5 = s4 = s3 = s2 = 0
                for student in grades_data.get("students", []):
                    g = student.get("grade")
                    if g == 5: s5 += 1
                    elif g == 4: s4 += 1
                    elif g == 3: s3 += 1
                    elif g is not None and g <= 2: s2 += 1
                total = s5 + s4 + s3 + s2
                quality = grades_data.get("quality_percent") or (round((s5 + s4) / total * 100, 1) if total else None)
                success = grades_data.get("success_percent") or (round((total - s2) / total * 100, 1) if total else None)
                
                if subj not in subjects_data_grades:
                    subjects_data_grades[subj] = []
                subjects_data_grades[subj].append({
                    "class_name": cls,
                    "count_5": s5, "count_4": s4, "count_3": s3, "count_2": s2,
                    "total": total,
                    "quality": quality,
                    "success_rate": success,
                    "teacher": teacher_name,
                    "has_data": total > 0
                })
            except json.JSONDecodeError:
                pass
    
    # Сортируем классы внутри каждого предмета (по номеру класса 1..11, затем по имени)
    def _class_sort_key(item):
        name = str(item.get("class_name") or "")
        grade_str = ""
        for ch in name:
            if ch.isdigit():
                grade_str += ch
            else:
                break
        grade_num = int(grade_str) if grade_str else 999
        return (grade_num, name)

    for subj_data in [subjects_data_sor, subjects_data_soch, subjects_data_grades]:
        for subj in subj_data:
            subj_data[subj].sort(key=_class_sort_key)
    
    return render_template(
        "admin/analytics_home.html",
        subjects_data_sor=dict(sorted(subjects_data_sor.items(), key=lambda item: kazakh_sort_key(item[0]))),
        subjects_data_soch=dict(sorted(subjects_data_soch.items(), key=lambda item: kazakh_sort_key(item[0]))),
        subjects_data_grades=dict(sorted(subjects_data_grades.items(), key=lambda item: kazakh_sort_key(item[0]))),
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
    
    period_number = int(request.args.get("period_number", 2))
    filter_subject = request.args.get("subject", "").strip() or None
    filter_class = request.args.get("class", "").strip() or None
    filter_teacher = request.args.get("teacher", "").strip() or None
    period_name = f"{period_number} четверть"
    
    reports = get_quarter_reports(current_user.school_id, period_number)
    active_class_names = {
        row.name
        for row in Class.query.filter_by(school_id=current_user.school_id).with_entities(Class.name).all()
    }
    
    subjects_data_sor = {}
    subjects_data_soch = {}
    subjects_data_grades = {}
    
    for report in reports:
        subj = normalize_subject_name(report.subject_name)
        cls = report.class_name
        if cls not in active_class_names:
            continue
        teacher_name = ""
        if report.teacher:
            teacher_name = report.teacher.full_name or report.teacher.username
        
        if report.analytics_json:
            try:
                analytics = json.loads(report.analytics_json)
                sor_list = analytics.get("sor", [])
                for sor in sor_list:
                    total = (sor.get("count_5", 0) + sor.get("count_4", 0) +
                             sor.get("count_3", 0) + sor.get("count_2", 0))
                    sor["total"] = total
                    if total > 0:
                        sor["quality"] = round((sor.get("count_5", 0) + sor.get("count_4", 0)) / total * 100, 1)
                        sor["success_rate"] = round((total - sor.get("count_2", 0)) / total * 100, 1)
                    else:
                        sor["quality"] = None
                        sor["success_rate"] = None
                
                if subj not in subjects_data_sor:
                    subjects_data_sor[subj] = []
                subjects_data_sor[subj].append({
                    "class_name": cls, "sor_list": sor_list, "teacher": teacher_name, "has_data": len(sor_list) > 0
                })
                
                soch = analytics.get("soch", {})
                if soch:
                    s5 = soch.get("count_5", 0)
                    s4 = soch.get("count_4", 0)
                    s3 = soch.get("count_3", 0)
                    s2 = soch.get("count_2", 0)
                    total = s5 + s4 + s3 + s2
                    if subj not in subjects_data_soch:
                        subjects_data_soch[subj] = []
                    subjects_data_soch[subj].append({
                        "class_name": cls,
                        "count_5": s5, "count_4": s4, "count_3": s3, "count_2": s2,
                        "total": total,
                        "quality": round((s5 + s4) / total * 100, 1) if total else None,
                        "success_rate": round((total - s2) / total * 100, 1) if total else None,
                        "teacher": teacher_name, "has_data": total > 0
                    })
            except json.JSONDecodeError:
                pass
        
        if report.grades_json:
            try:
                grades_data = json.loads(report.grades_json)
                s5 = s4 = s3 = s2 = 0
                for student in grades_data.get("students", []):
                    g = student.get("grade")
                    if g == 5: s5 += 1
                    elif g == 4: s4 += 1
                    elif g == 3: s3 += 1
                    elif g is not None and g <= 2: s2 += 1
                total = s5 + s4 + s3 + s2
                quality = grades_data.get("quality_percent") or (round((s5 + s4) / total * 100, 1) if total else None)
                success = grades_data.get("success_percent") or (round((total - s2) / total * 100, 1) if total else None)
                
                if subj not in subjects_data_grades:
                    subjects_data_grades[subj] = []
                subjects_data_grades[subj].append({
                    "class_name": cls,
                    "count_5": s5, "count_4": s4, "count_3": s3, "count_2": s2,
                    "total": total, "quality": quality, "success_rate": success,
                    "teacher": teacher_name, "has_data": total > 0
                })
            except json.JSONDecodeError:
                pass
    
    for subj_data in [subjects_data_sor, subjects_data_soch, subjects_data_grades]:
        for subj in subj_data:
            subj_data[subj].sort(key=lambda x: x["class_name"])
    
    # Применяем фильтры (subject, class, teacher)
    if filter_subject or filter_class or filter_teacher:
        subjects_data_sor, subjects_data_soch, subjects_data_grades = _apply_analytics_filters(
            subjects_data_sor, subjects_data_soch, subjects_data_grades,
            filter_subject, filter_class, filter_teacher
        )
    
    styles = _create_excel_styles()
    wb = Workbook()
    
    def _write_sor_sheet():
        ws = wb.active
        ws.title = "СОР"[:31]
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=10)
        ws["A1"] = f"Аналитика СОР ({period_name})"
        ws["A1"].font = Font(bold=True, size=14)
        ws["A1"].alignment = Alignment(horizontal="center")
        row = 3
        for subj, data_list in sorted(subjects_data_sor.items(), key=lambda item: kazakh_sort_key(item[0])):
            ws.cell(row=row, column=1, value=subj).font = Font(bold=True, size=12)
            row += 1
            headers = ["Класс", "СОР", "5", "4", "3", "2", "Всего", "Качество %", "Успеваемость %", "Учитель"]
            for col, h in enumerate(headers, 1):
                c = ws.cell(row=row, column=col, value=h)
                c.font = styles["header_font"]
                c.fill = styles["header_fill"]
                c.border = styles["border"]
            row += 1
            for item in data_list:
                if item["sor_list"]:
                    for sor in item["sor_list"]:
                        ws.cell(row=row, column=1, value=item["class_name"]).border = styles["border"]
                        ws.cell(row=row, column=2, value=sor.get("name", "-")).border = styles["border"]
                        ws.cell(row=row, column=3, value=sor.get("count_5", 0)).border = styles["border"]
                        ws.cell(row=row, column=4, value=sor.get("count_4", 0)).border = styles["border"]
                        ws.cell(row=row, column=5, value=sor.get("count_3", 0)).border = styles["border"]
                        ws.cell(row=row, column=6, value=sor.get("count_2", 0)).border = styles["border"]
                        ws.cell(row=row, column=7, value=sor.get("total", 0)).border = styles["border"]
                        ws.cell(row=row, column=8, value=sor.get("quality") or "-").border = styles["border"]
                        ws.cell(row=row, column=9, value=sor.get("success_rate") or "-").border = styles["border"]
                        ws.cell(row=row, column=10, value=item["teacher"] or "-").border = styles["border"]
                        row += 1
                else:
                    ws.cell(row=row, column=1, value=item["class_name"]).border = styles["border"]
                    for col in range(2, 10):
                        ws.cell(row=row, column=col, value="-").border = styles["border"]
                    ws.cell(row=row, column=10, value=item["teacher"] or "-").border = styles["border"]
                    row += 1
            row += 2
    
    def _write_soch_sheet():
        ws = wb.create_sheet(title="СОЧ"[:31])
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=9)
        ws["A1"] = f"Аналитика СОЧ ({period_name})"
        ws["A1"].font = Font(bold=True, size=14)
        ws["A1"].alignment = Alignment(horizontal="center")
        row = 3
        for subj, data_list in sorted(subjects_data_soch.items(), key=lambda item: kazakh_sort_key(item[0])):
            ws.cell(row=row, column=1, value=subj).font = Font(bold=True, size=12)
            row += 1
            headers = ["Класс", "5", "4", "3", "2", "Всего", "Качество %", "Успеваемость %", "Учитель"]
            for col, h in enumerate(headers, 1):
                c = ws.cell(row=row, column=col, value=h)
                c.font = styles["header_font"]
                c.fill = styles["header_fill"]
                c.border = styles["border"]
            row += 1
            for item in data_list:
                ws.cell(row=row, column=1, value=item["class_name"]).border = styles["border"]
                ws.cell(row=row, column=2, value=item["count_5"]).border = styles["border"]
                ws.cell(row=row, column=3, value=item["count_4"]).border = styles["border"]
                ws.cell(row=row, column=4, value=item["count_3"]).border = styles["border"]
                ws.cell(row=row, column=5, value=item["count_2"]).border = styles["border"]
                ws.cell(row=row, column=6, value=item["total"]).border = styles["border"]
                ws.cell(row=row, column=7, value=item["quality"] or "-").border = styles["border"]
                ws.cell(row=row, column=8, value=item["success_rate"] or "-").border = styles["border"]
                ws.cell(row=row, column=9, value=item["teacher"] or "-").border = styles["border"]
                row += 1
            row += 2
    
    def _write_grades_sheet():
        ws = wb.create_sheet(title="Оценки"[:31])
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=9)
        ws["A1"] = f"Аналитика оценок ({period_name})"
        ws["A1"].font = Font(bold=True, size=14)
        ws["A1"].alignment = Alignment(horizontal="center")
        row = 3
        for subj, data_list in sorted(subjects_data_grades.items(), key=lambda item: kazakh_sort_key(item[0])):
            ws.cell(row=row, column=1, value=subj).font = Font(bold=True, size=12)
            row += 1
            headers = ["Класс", "5", "4", "3", "2", "Всего", "Качество %", "Успеваемость %", "Учитель"]
            for col, h in enumerate(headers, 1):
                c = ws.cell(row=row, column=col, value=h)
                c.font = styles["header_font"]
                c.fill = styles["header_fill"]
                c.border = styles["border"]
            row += 1
            for item in data_list:
                ws.cell(row=row, column=1, value=item["class_name"]).border = styles["border"]
                ws.cell(row=row, column=2, value=item["count_5"]).border = styles["border"]
                ws.cell(row=row, column=3, value=item["count_4"]).border = styles["border"]
                ws.cell(row=row, column=4, value=item["count_3"]).border = styles["border"]
                ws.cell(row=row, column=5, value=item["count_2"]).border = styles["border"]
                ws.cell(row=row, column=6, value=item["total"]).border = styles["border"]
                ws.cell(row=row, column=7, value=item["quality"] or "-").border = styles["border"]
                ws.cell(row=row, column=8, value=item["success_rate"] or "-").border = styles["border"]
                ws.cell(row=row, column=9, value=item["teacher"] or "-").border = styles["border"]
                row += 1
            row += 2
    
    _write_sor_sheet()
    _write_soch_sheet()
    _write_grades_sheet()
    
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    filename = f"Аналитика_СОР_СОЧ_{period_name.replace(' ', '_')}.xlsx"
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )


@bp.get("/class-teacher-report")
@admin_required
def class_teacher_report():
    """
    Отчёт классного руководителя (структура из reference проекта).
    
    6 вкладок:
    - на 5 (отличники): Класс | № | ФИО | Классный руководитель
    - на 4 (хорошисты): Класс | № | ФИО | Классный руководитель
    - С одной 4: Класс | № | ФИО | Предмет | Учитель | Классный руководитель
    - на 3 (троечники): Класс | ФИО | Предмет 1..5 | Классный руководитель
    - С одной 3: Класс | № | ФИО | Предмет | Учитель | Классный руководитель
    - Неуспевающие: Класс | № | ФИО | Классный руководитель
    
    Данные сгруппированы по классам.
    """
    
    # Параметры (только четверти)
    period_number = int(request.args.get("period_number", 2))
    segment = request.args.get("segment")  # '1-4' или '5-11' или None
    
    # Получаем все отчёты (включая полугодовые для 2/4)
    all_reports = get_quarter_reports(current_user.school_id, period_number)
    active_class_names = {
        row.name
        for row in Class.query.filter_by(school_id=current_user.school_id).with_entities(Class.name).all()
    }
    all_reports = [r for r in all_reports if r.class_name in active_class_names]
    all_class_names = {r.class_name for r in all_reports}
    def _parse_grade_from_name(name: str):
        grade_str = ""
        for ch in str(name):
            if ch.isdigit():
                grade_str += ch
            else:
                break
        return int(grade_str) if grade_str else None

    class_names = []
    for cls_name in all_class_names:
        grade_num = _parse_grade_from_name(cls_name)
        if segment == "1-4":
            if grade_num and 1 <= grade_num <= 4:
                class_names.append((grade_num, cls_name))
        elif segment == "5-11":
            if grade_num and 5 <= grade_num <= 11:
                class_names.append((grade_num, cls_name))
        else:
            class_names.append((grade_num if grade_num is not None else 999, cls_name))

    class_names = [name for _, name in sorted(class_names, key=lambda x: (x[0], kazakh_sort_key(x[1])))]
    
    # Собираем данные по каждому классу
    categories_data = {
        "excellent": [],     # на 5
        "good": [],          # на 4
        "one_4": [],         # С одной 4
        "satisfactory": [],  # на 3
        "one_3": [],         # С одной 3
        "poor": []           # Неуспевающие
    }
    
    for cls_name in class_names:
        # Получаем классного руководителя
        cls_obj = Class.query.filter_by(school_id=current_user.school_id, name=cls_name).first()
        class_teacher_name = ""
        if cls_obj and cls_obj.class_teacher:
            class_teacher_name = cls_obj.class_teacher.full_name or cls_obj.class_teacher.username
        
        # Отчёты для класса из уже загруженных
        reports = [r for r in all_reports if r.class_name == cls_name]
        
        # Собираем оценки: name -> {subject_name: grade}
        # И учителей: subject_name -> teacher_name
        students_grades = {}   # name -> {subject_name: grade}
        subject_teachers = {}  # subject_name -> teacher_name
        
        for report in reports:
            subj = normalize_subject_name(report.subject_name)
            teacher_name = ""
            if report.teacher:
                teacher_name = report.teacher.full_name or report.teacher.username
            subject_teachers[subj] = teacher_name
            
            if report.grades_json:
                try:
                    grades_data = json.loads(report.grades_json)
                    for student in grades_data.get("students", []):
                        name = student.get("name")
                        grade = student.get("grade")
                        if name and grade is not None:
                            if name not in students_grades:
                                students_grades[name] = {}
                            prev = students_grades[name].get(subj)
                            if prev is None or grade > prev:
                                students_grades[name][subj] = grade
                except json.JSONDecodeError:
                    pass
        
        # Категоризируем
        excellent_students = []
        good_students = []
        one_4_students = []
        satisfactory_students = []
        troechniki_detailed = []
        one_3_students = []
        poor_students = []
        
        for name, subj_grades in sorted(students_grades.items(), key=lambda item: kazakh_sort_key(item[0])):
            grades_list = list(subj_grades.values())
            if not grades_list:
                continue
            
            count_5 = grades_list.count(5)
            count_4 = grades_list.count(4)
            count_3 = grades_list.count(3)
            count_2 = sum(1 for g in grades_list if g <= 2)
            
            if count_2 > 0:
                # Для неуспевающих: предметы с двойками
                failing_subjects = [
                    {"subject": s, "teacher": subject_teachers.get(s, "")}
                    for s, g in subj_grades.items() if g <= 2
                ]
                for fs in failing_subjects:
                    poor_students.append({
                        "student": name,
                        "subject": fs["subject"],
                        "teacher": fs["teacher"]
                    })
            elif all(g >= 5 for g in grades_list):
                excellent_students.append(name)
            elif count_4 == 1 and count_3 == 0:
                # С одной 4: найдём предмет
                subj_with_4 = next((s for s, g in subj_grades.items() if g == 4), "")
                one_4_students.append({
                    "student": name,
                    "subject": subj_with_4,
                    "teacher": subject_teachers.get(subj_with_4, "")
                })
            elif count_3 == 0:
                good_students.append(name)
            elif count_3 == 1:
                # С одной 3: найдём предмет
                subj_with_3 = next((s for s, g in subj_grades.items() if g == 3), "")
                one_3_students.append({
                    "student": name,
                    "subject": subj_with_3,
                    "teacher": subject_teachers.get(subj_with_3, "")
                })
            else:
                satisfactory_students.append(name)
                # Подробности: предметы с тройками
                subjects_with_3 = [
                    {"subject_name": s, "grade": g}
                    for s, g in subj_grades.items() if g == 3
                ]
                # Разделяем на первые 4 и остальные (для колонок)
                troechniki_detailed.append({
                    "student": name,
                    "subjects_1_4": subjects_with_3[:4],
                    "subjects_5": subjects_with_3[4:]
                })
        
        # Добавляем блок класса в каждую непустую категорию
        class_block = lambda students: {
            "class_name": cls_name,
            "class_teacher": class_teacher_name,
            "students": students
        }
        
        if excellent_students:
            categories_data["excellent"].append(class_block(excellent_students))
        if good_students:
            categories_data["good"].append(class_block(good_students))
        if one_4_students:
            categories_data["one_4"].append(class_block(one_4_students))
        if satisfactory_students:
            block = class_block(satisfactory_students)
            block["troechniki_detailed"] = troechniki_detailed
            categories_data["satisfactory"].append(block)
        if one_3_students:
            categories_data["one_3"].append(class_block(one_3_students))
        if poor_students:
            categories_data["poor"].append(class_block(poor_students))
    
    return render_template(
        "admin/class_teacher_report.html",
        categories_data=categories_data,
        period_number=period_number,
        segment=segment
    )


# ==============================================================================
# Excel Export Routes
# ==============================================================================

def _create_excel_styles():
    """Создание стилей для Excel"""
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="4F81BD", end_color="4F81BD", fill_type="solid")
    header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    
    border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )
    
    # Заливки для оценок
    grade_fills = {
        5: PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid"),  # Зеленый
        4: PatternFill(start_color="BDD7EE", end_color="BDD7EE", fill_type="solid"),  # Голубой
        3: PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid"),  # Желтый
        2: PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid"),  # Красный
    }
    
    # Заливка для пограничных оценок
    border_highlight_fill = PatternFill(start_color="FFF3CD", end_color="FFF3CD", fill_type="solid")
    
    # Заливки для строк/столбцов подсчёта
    count_5_fill = PatternFill(start_color="D1FAE5", end_color="D1FAE5", fill_type="solid")
    count_4_fill = PatternFill(start_color="DBEAFE", end_color="DBEAFE", fill_type="solid")
    count_3_fill = PatternFill(start_color="FEF3C7", end_color="FEF3C7", fill_type="solid")
    count_2_fill = PatternFill(start_color="FFE4E6", end_color="FFE4E6", fill_type="solid")
    
    # Заливки для качества/успеваемости
    quality_fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
    success_fill = PatternFill(start_color="BDD7EE", end_color="BDD7EE", fill_type="solid")
    
    return {
        "header_font": header_font,
        "header_fill": header_fill,
        "header_alignment": header_alignment,
        "border": border,
        "grade_fills": grade_fills,
        "border_highlight_fill": border_highlight_fill,
        "count_5_fill": count_5_fill,
        "count_4_fill": count_4_fill,
        "count_3_fill": count_3_fill,
        "count_2_fill": count_2_fill,
        "quality_fill": quality_fill,
        "success_fill": success_fill,
    }


def _is_border_percent(pct):
    """Проверка: пограничный процент (37-39%, 61-64%, 82-84%)"""
    if pct is None:
        return False
    return (37 <= pct <= 39) or (61 <= pct <= 64) or (82 <= pct <= 84)


@bp.get("/grades/class/<class_name>/download-excel")
@admin_required
def download_grades_class_excel(class_name: str):
    """Скачать сводную таблицу оценок класса в Excel"""
    
    # Параметры (только четверти)
    period_number = int(request.args.get("period_number", 2))
    
    # Получаем все отчёты для этого класса (включая полугодовые для 2/4)
    reports = get_quarter_reports(current_user.school_id, period_number, class_name=class_name)
    
    # Собираем данные
    subjects = set()
    students_data = {}  # name -> {subject -> {percent, grade}}
    
    for report in reports:
        subj = normalize_subject_name(report.subject_name)
        subjects.add(subj)
        
        if report.grades_json:
            try:
                grades_data = json.loads(report.grades_json)
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
    
    # Создаём Excel
    wb = Workbook()
    ws = wb.active
    ws.title = f"Оценки {class_name}"
    
    styles = _create_excel_styles()
    bold_font = Font(bold=True)
    center_align = Alignment(horizontal="center")
    
    # Заголовок
    period_name = f"{period_number} четверть"
    total_cols = len(subjects_list) + 6  # №, ФИО, предметы..., Кол5, Кол4, Кол3, Кол2
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=total_cols)
    ws["A1"] = f"Сводная таблица оценок: {class_name} ({period_name})"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A1"].alignment = Alignment(horizontal="center")
    
    # Шапка таблицы
    header_row = 3
    headers = ["№", "ФИО ученика"] + subjects_list + ["Кол-во 5", "Кол-во 4", "Кол-во 3", "Кол-во 2"]
    
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=header_row, column=col, value=header)
        cell.font = styles["header_font"]
        cell.fill = styles["header_fill"]
        cell.alignment = styles["header_alignment"]
        cell.border = styles["border"]
    
    # Столбцы подсчёта — цветные заголовки
    col_5_idx = len(subjects_list) + 3
    col_4_idx = len(subjects_list) + 4
    col_3_idx = len(subjects_list) + 5
    col_2_idx = len(subjects_list) + 6
    ws.cell(row=header_row, column=col_5_idx).fill = styles["count_5_fill"]
    ws.cell(row=header_row, column=col_5_idx).font = Font(bold=True)
    ws.cell(row=header_row, column=col_4_idx).fill = styles["count_4_fill"]
    ws.cell(row=header_row, column=col_4_idx).font = Font(bold=True)
    ws.cell(row=header_row, column=col_3_idx).fill = styles["count_3_fill"]
    ws.cell(row=header_row, column=col_3_idx).font = Font(bold=True)
    ws.cell(row=header_row, column=col_2_idx).fill = styles["count_2_fill"]
    ws.cell(row=header_row, column=col_2_idx).font = Font(bold=True)
    
    # Данные учеников
    for row_idx, student in enumerate(students_list, header_row + 1):
        # Номер
        cell = ws.cell(row=row_idx, column=1, value=row_idx - header_row)
        cell.border = styles["border"]
        cell.alignment = center_align
        
        # ФИО
        cell = ws.cell(row=row_idx, column=2, value=student["name"])
        cell.border = styles["border"]
        
        # Оценки по предметам
        for col_idx, subject in enumerate(subjects_list, 3):
            grade_info = student["grades"].get(subject, {})
            grade = grade_info.get("grade")
            percent = grade_info.get("percent")
            
            if grade:
                # Показываем оценку и процент
                cell_value = f"{grade} ({percent}%)" if percent else str(grade)
                cell = ws.cell(row=row_idx, column=col_idx, value=cell_value)
                
                # Подсветка пограничных процентов
                if _is_border_percent(percent):
                    cell.fill = styles["border_highlight_fill"]
                    cell.font = Font(bold=True, color="B45309")
            else:
                cell = ws.cell(row=row_idx, column=col_idx, value="—")
            
            cell.border = styles["border"]
            cell.alignment = center_align
        
        # Кол-во 5, 4, 3, 2 по строке
        cell = ws.cell(row=row_idx, column=col_5_idx, value=student["count_5"])
        cell.border = styles["border"]
        cell.alignment = center_align
        cell.fill = styles["count_5_fill"]
        cell.font = bold_font
        
        cell = ws.cell(row=row_idx, column=col_4_idx, value=student["count_4"])
        cell.border = styles["border"]
        cell.alignment = center_align
        cell.fill = styles["count_4_fill"]
        cell.font = bold_font
        
        cell = ws.cell(row=row_idx, column=col_3_idx, value=student["count_3"])
        cell.border = styles["border"]
        cell.alignment = center_align
        cell.fill = styles["count_3_fill"]
        cell.font = bold_font
        
        cell = ws.cell(row=row_idx, column=col_2_idx, value=student["count_2"])
        cell.border = styles["border"]
        cell.alignment = center_align
        cell.fill = styles["count_2_fill"]
        cell.font = bold_font
    
    # --- Итоговые строки ---
    footer_start = header_row + len(students_list) + 1
    
    # Строка: Кол-во «5» по столбцам
    row = footer_start
    ws.cell(row=row, column=2, value='Кол-во «5»').font = bold_font
    for col_idx, subj in enumerate(subjects_list, 3):
        cell = ws.cell(row=row, column=col_idx, value=subject_stats[subj]["count_5"])
        cell.border = styles["border"]
        cell.alignment = center_align
        cell.fill = styles["count_5_fill"]
        cell.font = bold_font
    cell = ws.cell(
        row=row,
        column=col_5_idx,
        value=sum(1 for s in students_list if s["count_4"] == 0),
    )
    cell.border = styles["border"]
    cell.alignment = center_align
    cell.fill = styles["count_5_fill"]
    cell.font = bold_font
    
    # Строка: Кол-во «4» по столбцам
    row = footer_start + 1
    ws.cell(row=row, column=2, value='Кол-во «4»').font = bold_font
    for col_idx, subj in enumerate(subjects_list, 3):
        cell = ws.cell(row=row, column=col_idx, value=subject_stats[subj]["count_4"])
        cell.border = styles["border"]
        cell.alignment = center_align
        cell.fill = styles["count_4_fill"]
        cell.font = bold_font
    cell = ws.cell(
        row=row,
        column=col_4_idx,
        value=sum(1 for s in students_list if s["count_3"] == 0),
    )
    cell.border = styles["border"]
    cell.alignment = center_align
    cell.fill = styles["count_4_fill"]
    cell.font = bold_font
    
    # Строка: Кол-во «3» по столбцам
    row = footer_start + 2
    ws.cell(row=row, column=2, value='Кол-во «3»').font = bold_font
    for col_idx, subj in enumerate(subjects_list, 3):
        cell = ws.cell(row=row, column=col_idx, value=subject_stats[subj]["count_3"])
        cell.border = styles["border"]
        cell.alignment = center_align
        cell.fill = styles["count_3_fill"]
        cell.font = bold_font
    cell = ws.cell(
        row=row,
        column=col_3_idx,
        value=sum(1 for s in students_list if s["count_2"] == 0),
    )
    cell.border = styles["border"]
    cell.alignment = center_align
    cell.fill = styles["count_3_fill"]
    cell.font = bold_font
    
    # Строка: Кол-во «2» по столбцам
    row = footer_start + 3
    ws.cell(row=row, column=2, value='Кол-во «2»').font = bold_font
    for col_idx, subj in enumerate(subjects_list, 3):
        cell = ws.cell(row=row, column=col_idx, value=subject_stats[subj]["count_2"])
        cell.border = styles["border"]
        cell.alignment = center_align
        cell.fill = styles["count_2_fill"]
        cell.font = bold_font
    cell = ws.cell(
        row=row,
        column=col_2_idx,
        value=sum(1 for s in students_list if s["count_2"] > 0),
    )
    cell.border = styles["border"]
    cell.alignment = center_align
    cell.fill = styles["count_2_fill"]
    cell.font = bold_font
    
    # Строка: Качество % по предмету
    row = footer_start + 4
    ws.cell(row=row, column=2, value='Качество %').font = bold_font
    for col_idx, subj in enumerate(subjects_list, 3):
        cell = ws.cell(row=row, column=col_idx, value=f"{subject_stats[subj]['quality_percent']}%")
        cell.border = styles["border"]
        cell.alignment = center_align
        cell.fill = styles["quality_fill"]
        cell.font = bold_font
    
    # Строка: Успеваемость % по предмету
    row = footer_start + 5
    ws.cell(row=row, column=2, value='Успеваемость %').font = bold_font
    for col_idx, subj in enumerate(subjects_list, 3):
        cell = ws.cell(row=row, column=col_idx, value=f"{subject_stats[subj]['success_percent']}%")
        cell.border = styles["border"]
        cell.alignment = center_align
        cell.fill = styles["success_fill"]
        cell.font = bold_font
    
    # Авто-ширина колонок
    ws.column_dimensions["A"].width = 5
    ws.column_dimensions["B"].width = 30
    for col in range(3, len(subjects_list) + 3):
        ws.column_dimensions[get_column_letter(col)].width = 16
    ws.column_dimensions[get_column_letter(col_5_idx)].width = 10
    ws.column_dimensions[get_column_letter(col_4_idx)].width = 10
    ws.column_dimensions[get_column_letter(col_3_idx)].width = 10
    ws.column_dimensions[get_column_letter(col_2_idx)].width = 10
    
    # Сохраняем в память
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    
    filename = f"Оценки_{class_name}_{period_number}_четверть.xlsx"
    
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )


@bp.get("/class-teacher-report/download-excel")
@admin_required
def download_class_teacher_report_excel():
    """Скачать отчёт классного руководителя в Excel — все классы, по категориям"""
    
    period_number = int(request.args.get("period_number", 2))
    period_name = f"{period_number} четверть"
    
    # --- Собираем данные (повторяем логику class_teacher_report) ---
    all_reports = get_quarter_reports(current_user.school_id, period_number)
    class_names = sorted({r.class_name for r in all_reports}, key=kazakh_sort_key)
    
    categories_data = {
        "excellent": [], "good": [], "one_4": [],
        "satisfactory": [], "one_3": [], "poor": []
    }
    
    for cls_name in class_names:
        cls_obj = Class.query.filter_by(school_id=current_user.school_id, name=cls_name).first()
        class_teacher_name = ""
        if cls_obj and cls_obj.class_teacher:
            class_teacher_name = cls_obj.class_teacher.full_name or cls_obj.class_teacher.username
        
        reports = [r for r in all_reports if r.class_name == cls_name]
        
        students_grades = {}
        subject_teachers = {}
        for report in reports:
            subj = normalize_subject_name(report.subject_name)
            t_name = ""
            if report.teacher:
                t_name = report.teacher.full_name or report.teacher.username
            subject_teachers[subj] = t_name
            if report.grades_json:
                try:
                    gd = json.loads(report.grades_json)
                    for st in gd.get("students", []):
                        nm = st.get("name")
                        gr = st.get("grade")
                        if nm and gr is not None:
                            students_grades.setdefault(nm, {})
                            prev = students_grades[nm].get(subj)
                            if prev is None or gr > prev:
                                students_grades[nm][subj] = gr
                except json.JSONDecodeError:
                    pass
        
        excellent_s, good_s, one4_s, satisf_s, troech_d, one3_s, poor_s = [], [], [], [], [], [], []
        for name, sg in sorted(students_grades.items(), key=lambda item: kazakh_sort_key(item[0])):
            gl = list(sg.values())
            if not gl:
                continue
            c5, c4, c3, c2 = gl.count(5), gl.count(4), gl.count(3), sum(1 for g in gl if g<=2)
            if c2 > 0:
                for s_name, g_val in sg.items():
                    if g_val <= 2:
                        poor_s.append({"student": name, "subject": s_name, "teacher": subject_teachers.get(s_name, "")})
            elif all(g>=5 for g in gl):
                excellent_s.append(name)
            elif c4==1 and c3==0:
                subj4 = next((s for s,g in sg.items() if g==4), "")
                one4_s.append({"student": name, "subject": subj4, "teacher": subject_teachers.get(subj4,"")})
            elif c3==0:
                good_s.append(name)
            elif c3==1:
                subj3 = next((s for s,g in sg.items() if g==3), "")
                one3_s.append({"student": name, "subject": subj3, "teacher": subject_teachers.get(subj3,"")})
            else:
                satisf_s.append(name)
                subjs3 = [{"subject_name": s, "grade": g} for s,g in sg.items() if g==3]
                troech_d.append({"student": name, "subjects_1_4": subjs3[:4], "subjects_5": subjs3[4:]})
        
        def _block(students):
            return {"class_name": cls_name, "class_teacher": class_teacher_name, "students": students}
        if excellent_s: categories_data["excellent"].append(_block(excellent_s))
        if good_s: categories_data["good"].append(_block(good_s))
        if one4_s: categories_data["one_4"].append(_block(one4_s))
        if satisf_s:
            b = _block(satisf_s); b["troechniki_detailed"] = troech_d; categories_data["satisfactory"].append(b)
        if one3_s: categories_data["one_3"].append(_block(one3_s))
        if poor_s: categories_data["poor"].append(_block(poor_s))
    
    # --- Создаём Excel ---
    wb = Workbook()
    styles = _create_excel_styles()
    
    cat_meta = [
        ("excellent",     "на 5",        "C6EFCE", ["Класс", "№", "ФИО", "Классный руководитель"]),
        ("good",          "на 4",        "BDD7EE", ["Класс", "№", "ФИО", "Классный руководитель"]),
        ("one_4",         "С одной 4",   "D9EAD3", ["Класс", "№", "ФИО", "Предмет", "Учитель", "Классный руководитель"]),
        ("satisfactory",  "на 3",        "FFEB9C", ["Класс", "ФИО", "Предмет 1", "Предмет 2", "Предмет 3", "Предмет 4", "Предмет 5+", "Классный руководитель"]),
        ("one_3",         "С одной 3",   "FBE5D6", ["Класс", "№", "ФИО", "Предмет", "Учитель", "Классный руководитель"]),
        ("poor",          "Неуспевающие", "FFC7CE", ["Класс", "№", "ФИО", "Предмет", "Учитель", "Классный руководитель"]),
    ]
    
    first_sheet = True
    for cat_key, cat_label, cat_color, headers in cat_meta:
        blocks = categories_data[cat_key]
        total_count = sum(len(b["students"]) for b in blocks)
        sheet_name = f"{cat_label} ({total_count})"[:31]
        
        if first_sheet:
            ws = wb.active
            ws.title = sheet_name
            first_sheet = False
        else:
            ws = wb.create_sheet(title=sheet_name)
        
        # Заголовок
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
        c = ws.cell(row=1, column=1, value=f"Отчёт классных руководителей — {cat_label} ({period_name})")
        c.font = Font(bold=True, size=13)
        c.alignment = Alignment(horizontal="center")
        
        # Шапка таблицы
        for col, h in enumerate(headers, 1):
            cell = ws.cell(row=3, column=col, value=h)
            cell.font = styles["header_font"]
            cell.fill = PatternFill(start_color=cat_color, end_color=cat_color, fill_type="solid")
            cell.alignment = styles["header_alignment"]
            cell.border = styles["border"]
        
        row = 4
        if not blocks:
            ws.cell(row=row, column=1, value="Нет данных")
            continue
        
        for block in blocks:
            cls = block["class_name"]
            ct = block["class_teacher"]
            
            if cat_key == "satisfactory":
                details = block.get("troechniki_detailed", [])
                n = len(details)
                if n == 0:
                    continue
                # Класс (rowspan)
                ws.merge_cells(start_row=row, start_column=1, end_row=row+n-1, end_column=1)
                ws.cell(row=row, column=1, value=cls).font = Font(bold=True)
                ws.cell(row=row, column=1).border = styles["border"]
                ws.cell(row=row, column=1).alignment = Alignment(vertical="center", horizontal="center")
                # Кл. руководитель (rowspan)
                ws.merge_cells(start_row=row, start_column=8, end_row=row+n-1, end_column=8)
                ws.cell(row=row, column=8, value=ct).border = styles["border"]
                ws.cell(row=row, column=8).alignment = Alignment(vertical="center")
                
                for item in details:
                    ws.cell(row=row, column=2, value=item["student"]).border = styles["border"]
                    for i in range(4):
                        val = ""
                        if i < len(item["subjects_1_4"]):
                            s = item["subjects_1_4"][i]
                            val = f"{s['subject_name']} ({s['grade']})"
                        ws.cell(row=row, column=3+i, value=val or "—").border = styles["border"]
                    # 5+
                    val5 = ", ".join(f"{s['subject_name']} ({s['grade']})" for s in item.get("subjects_5", []))
                    ws.cell(row=row, column=7, value=val5 or "—").border = styles["border"]
                    row += 1
            
            elif cat_key in ("one_4", "one_3", "poor"):
                students = block["students"]
                n = len(students)
                ws.merge_cells(start_row=row, start_column=1, end_row=row+n-1, end_column=1)
                ws.cell(row=row, column=1, value=cls).font = Font(bold=True)
                ws.cell(row=row, column=1).border = styles["border"]
                ws.cell(row=row, column=1).alignment = Alignment(vertical="center", horizontal="center")
                ws.merge_cells(start_row=row, start_column=6, end_row=row+n-1, end_column=6)
                ws.cell(row=row, column=6, value=ct).border = styles["border"]
                ws.cell(row=row, column=6).alignment = Alignment(vertical="center")
                
                for idx, item in enumerate(students, 1):
                    ws.cell(row=row, column=2, value=idx).border = styles["border"]
                    ws.cell(row=row, column=3, value=item["student"]).border = styles["border"]
                    ws.cell(row=row, column=4, value=item["subject"]).border = styles["border"]
                    ws.cell(row=row, column=5, value=item["teacher"]).border = styles["border"]
                    row += 1
            
            else:  # excellent, good, poor
                students = block["students"]
                n = len(students)
                ws.merge_cells(start_row=row, start_column=1, end_row=row+n-1, end_column=1)
                ws.cell(row=row, column=1, value=cls).font = Font(bold=True)
                ws.cell(row=row, column=1).border = styles["border"]
                ws.cell(row=row, column=1).alignment = Alignment(vertical="center", horizontal="center")
                ws.merge_cells(start_row=row, start_column=4, end_row=row+n-1, end_column=4)
                ws.cell(row=row, column=4, value=ct).border = styles["border"]
                ws.cell(row=row, column=4).alignment = Alignment(vertical="center")
                
                for idx, student in enumerate(students, 1):
                    ws.cell(row=row, column=2, value=idx).border = styles["border"]
                    ws.cell(row=row, column=3, value=student).border = styles["border"]
                    row += 1
        
        # Авто-ширина
        for col_idx in range(1, len(headers)+1):
            ws.column_dimensions[get_column_letter(col_idx)].width = max(12, len(headers[col_idx-1]) + 5)
        ws.column_dimensions["C"].width = 35  # ФИО
    
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    
    filename = f"Отчёт_классных_руководителей_{period_name.replace(' ', '_')}.xlsx"
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )

