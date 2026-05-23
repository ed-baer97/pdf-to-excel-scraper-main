"""Расчёт учебного года из четвертных/полугодовых отчётов (без скрапа вкладки «Учебный год»)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from ..constants import normalize_subject_name
from ..extensions import db
from ..models import GradeReport

YEAR_UI_PERIOD = 5

GetQuarterReportsFn = Callable[..., list]


def math_round(x: float) -> int:
    """Математическое округление к целому."""
    return int(x + 0.5)


def math_round_percent(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        return 0
    return math_round(numerator / denominator * 100)


def quality_success_from_grades(grades: list[int]) -> tuple[int, int]:
    """Качество и успеваемость, %, из списка годовых оценок (int(x+0.5))."""
    if not grades:
        return 0, 0
    total = len(grades)
    quality = math_round_percent(sum(1 for g in grades if g >= 4), total)
    success = math_round_percent(sum(1 for g in grades if g >= 3), total)
    return quality, success


def get_semester_subject_pairs(school_id: int) -> set[tuple[str, str]]:
    rows = (
        db.session.query(GradeReport.class_name, GradeReport.subject_name)
        .filter_by(school_id=school_id, period_type="semester")
        .distinct()
        .all()
    )
    return {(r.class_name, normalize_subject_name(r.subject_name, school_id)) for r in rows}


def _parse_grade(raw: Any) -> int | None:
    if raw is None:
        return None
    try:
        return int(float(str(raw).strip()))
    except (ValueError, TypeError):
        return None


def grades_map_from_reports(reports: list, school_id: int) -> dict[str, dict[str, int]]:
    """После слияния подгрупп: ученик → предмет → оценка (максимум при конфликте)."""
    out: dict[str, dict[str, int]] = {}
    for report in reports:
        subj = normalize_subject_name(report.subject_name, school_id)
        if not report.grades_json:
            continue
        try:
            data = json.loads(report.grades_json)
        except json.JSONDecodeError:
            continue
        for student in data.get("students", []) or []:
            name = (student.get("name") or "").strip()
            if not name:
                continue
            gi = _parse_grade(student.get("grade"))
            if gi is None:
                continue
            bucket = out.setdefault(name, {})
            prev = bucket.get(subj)
            if prev is None or gi > prev:
                bucket[subj] = gi
    return out


def compute_year_grade_from_periods(
    period_grades: dict[int, int | None],
    *,
    is_semester: bool,
) -> int | None:
    """
    Четвертной предмет: строго все четверти 1–4.
    Полугодовой: строго «2» и «4» (semester 1 и 2 в отчётах за 2/4 четверть).
    """
    if is_semester:
        g2, g4 = period_grades.get(2), period_grades.get(4)
        if g2 is None or g4 is None:
            return None
        return math_round((g2 + g4) / 2)
    vals = [period_grades.get(pn) for pn in (1, 2, 3, 4)]
    if any(v is None for v in vals):
        return None
    return math_round(sum(vals) / 4)


def build_period_grade_maps(
    school_id: int,
    class_name: str,
    get_quarter_reports: GetQuarterReportsFn,
) -> dict[int, dict[str, dict[str, int]]]:
    maps: dict[int, dict[str, dict[str, int]]] = {}
    for period_number in (1, 2, 3, 4):
        reports = get_quarter_reports(
            school_id, period_number, class_name=class_name
        )
        maps[period_number] = grades_map_from_reports(reports, school_id)
    return maps


def build_year_student_subjects(
    school_id: int,
    class_name: str,
    get_quarter_reports: GetQuarterReportsFn,
) -> dict[str, dict[str, int]]:
    """Ученик → предмет → годовая оценка."""
    semester_pairs = get_semester_subject_pairs(school_id)
    period_maps = build_period_grade_maps(school_id, class_name, get_quarter_reports)

    all_students: set[str] = set()
    all_subjects: set[str] = set()
    for period_map in period_maps.values():
        for student, subjs in period_map.items():
            all_students.add(student)
            all_subjects.update(subjs.keys())

    result: dict[str, dict[str, int]] = {}
    for student in all_students:
        student_grades: dict[str, int] = {}
        for subj in all_subjects:
            is_semester = (class_name, subj) in semester_pairs
            period_grades = {
                pn: period_maps[pn].get(student, {}).get(subj)
                for pn in (1, 2, 3, 4)
            }
            year_grade = compute_year_grade_from_periods(
                period_grades, is_semester=is_semester
            )
            if year_grade is not None:
                student_grades[subj] = year_grade
        if student_grades:
            result[student] = student_grades
    return result


@dataclass
class SyntheticGradeReport:
    """Виртуальный отчёт за учебный год (не хранится в БД)."""

    school_id: int
    class_name: str
    subject_name: str
    grades_json: str
    period_type: str = "year"
    period_number: int = 1
    analytics_json: str | None = None
    teacher_id: int = 0
    id: int | None = None

    @property
    def subject_name_normalized(self) -> str:
        return self.subject_name


def _synthetic_report_for_subject(
    school_id: int,
    class_name: str,
    subject_name: str,
    student_grades: list[tuple[str, int]],
) -> SyntheticGradeReport:
    students_payload = [
        {"name": name, "percent": None, "grade": grade}
        for name, grade in sorted(student_grades, key=lambda x: x[0])
    ]
    grades_only = [g for _, g in student_grades]
    total = len(grades_only)
    quality, success = quality_success_from_grades(grades_only)
    payload = {
        "students": students_payload,
        "quality_percent": quality,
        "success_percent": success,
        "total_students": total,
    }
    return SyntheticGradeReport(
        school_id=school_id,
        class_name=class_name,
        subject_name=subject_name,
        grades_json=json.dumps(payload, ensure_ascii=False),
    )


def build_synthetic_year_reports(
    school_id: int,
    get_quarter_reports: GetQuarterReportsFn,
    *,
    class_name: str | None = None,
    teacher_id: int | None = None,
) -> list[SyntheticGradeReport]:
    """Синтетические отчёты по предметам для UI/API (period_number=5)."""
    if class_name:
        class_names = [class_name]
    else:
        q = (
            db.session.query(GradeReport.class_name)
            .filter_by(school_id=school_id)
            .distinct()
        )
        if teacher_id is not None:
            q = q.filter(GradeReport.teacher_id == teacher_id)
        class_names = sorted({row.class_name for row in q.all()})

    reports: list[SyntheticGradeReport] = []
    for cn in class_names:
        year_map = build_year_student_subjects(school_id, cn, get_quarter_reports)
        by_subject: dict[str, list[tuple[str, int]]] = {}
        for student, subjs in year_map.items():
            for subj, grade in subjs.items():
                by_subject.setdefault(subj, []).append((student, grade))
        for subj, pairs in by_subject.items():
            if not pairs:
                continue
            syn = _synthetic_report_for_subject(school_id, cn, subj, pairs)
            if teacher_id is not None:
                syn.teacher_id = teacher_id
            reports.append(syn)
    return reports


def aggregate_year_metrics(
    school_id: int,
    active_class_names: set[str],
    get_quarter_reports: GetQuarterReportsFn,
) -> dict:
    """
    KPI за учебный год: качество/успеваемость по классу — из пула годовых оценок
  (ученик×предмет); по школе и параллелям — int(mean по классам + 0.5).
    """
    from .admin_dashboard import class_accordion_group  # noqa: PLC0415 — avoid circular import

    class_totals: dict = {}
    school_quality_values: list[float] = []
    school_success_values: list[float] = []
    parallel_values: dict[str, dict[str, list[float]]] = {
        "1-4": {"quality": [], "success": []},
        "5-9": {"quality": [], "success": []},
        "10-11": {"quality": [], "success": []},
    }
    students_total = 0

    for class_name in sorted(active_class_names):
        year_map = build_year_student_subjects(
            school_id, class_name, get_quarter_reports
        )
        all_grades: list[int] = []
        for subjs in year_map.values():
            all_grades.extend(subjs.values())
        if not all_grades:
            continue

        class_quality, class_success = quality_success_from_grades(all_grades)
        class_totals[class_name] = {
            "quality_sum": float(class_quality),
            "success_sum": float(class_success),
            "report_count": 1,
            "weight_total": len(all_grades),
        }
        school_quality_values.append(float(class_quality))
        school_success_values.append(float(class_success))
        students_total += len(all_grades)
        bucket = class_accordion_group(class_name)
        if bucket in parallel_values:
            parallel_values[bucket]["quality"].append(float(class_quality))
            parallel_values[bucket]["success"].append(float(class_success))

    school_quality = (
        math_round(sum(school_quality_values) / len(school_quality_values))
        if school_quality_values
        else None
    )
    school_success = (
        math_round(sum(school_success_values) / len(school_success_values))
        if school_success_values
        else None
    )

    parallel: dict = {}
    for key, vals in parallel_values.items():
        if vals["quality"]:
            parallel[key] = {
                "quality": math_round(sum(vals["quality"]) / len(vals["quality"])),
                "success": math_round(sum(vals["success"]) / len(vals["success"])),
            }
        else:
            parallel[key] = {"quality": None, "success": None}

    return {
        "class_totals": class_totals,
        "school_quality": school_quality,
        "school_success": school_success,
        "parallel": parallel,
        "classes_with_data": len(school_quality_values),
        "total_weight": students_total,
        "has_data": bool(school_quality_values),
    }


def students_data_from_year_map(
    year_map: dict[str, dict[str, int]],
) -> dict[str, dict[str, dict[str, Any]]]:
    """Формат как в grades_class: name → subject → {percent, grade}."""
    return {
        name: {subj: {"percent": None, "grade": grade} for subj, grade in subjs.items()}
        for name, subjs in year_map.items()
    }


def purge_legacy_year_reports() -> int:
    """Удаляет устаревшие строки period_type='year' из БД."""
    deleted = GradeReport.query.filter_by(period_type="year").delete()
    if deleted:
        db.session.commit()
    try:
        from ..models import ReportFile

        rf_deleted = ReportFile.query.filter(ReportFile.period_code == "5").delete()
        if rf_deleted:
            db.session.commit()
        deleted += rf_deleted
    except Exception:
        db.session.rollback()
    return deleted
