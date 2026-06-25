"""Отчёт классного руководителя: категоризация учеников и сборка блоков по классам."""

from __future__ import annotations

from typing import Any

from ...constants import kazakh_sort_key
from ...models import Class
from .analytics import _segment_matches
from .periods import parse_class_grade
from .queries import get_period_reports

_CATEGORY_KEYS = (
    "excellent",
    "good",
    "one_4",
    "satisfactory",
    "one_3",
    "poor",
)


def _parse_grade(raw: Any) -> int | None:
    if raw is None:
        return None
    try:
        return int(float(str(raw).strip()))
    except (ValueError, TypeError):
        return None


def categorize_students(
    students_data: dict[str, dict[str, dict]],
    subject_teachers: dict[str, str],
) -> dict[str, list]:
    """Категории учеников для отчёта классного руководителя."""
    categories: dict[str, list] = {
        "excellent": [],
        "good": [],
        "one_4": [],
        "satisfactory": [],
        "one_3": [],
        "poor": [],
    }

    students_grades: dict[str, dict[str, int]] = {}
    for name, grades in students_data.items():
        row: dict[str, int] = {}
        for subj, gi in grades.items():
            g = _parse_grade(gi.get("grade"))
            if g is not None:
                row[subj] = g
        if row:
            students_grades[name] = row

    for name, subj_grades in sorted(
        students_grades.items(), key=lambda item: kazakh_sort_key(item[0])
    ):
        grades_list = list(subj_grades.values())
        if not grades_list:
            continue

        count_4 = grades_list.count(4)
        count_3 = grades_list.count(3)
        count_2 = sum(1 for g in grades_list if g <= 2)

        if count_2 > 0:
            failing_subjects = [
                {"subject": s, "teacher": subject_teachers.get(s, "")}
                for s, g in subj_grades.items()
                if g <= 2
            ]
            categories["poor"].append(
                {"name": name, "subjects": failing_subjects}
            )
        elif all(g >= 5 for g in grades_list):
            categories["excellent"].append({"name": name})
        elif count_4 == 1 and count_3 == 0:
            subj_with_4 = next((s for s, g in subj_grades.items() if g == 4), "")
            categories["one_4"].append(
                {
                    "name": name,
                    "subject": subj_with_4,
                    "teacher": subject_teachers.get(subj_with_4, ""),
                }
            )
        elif count_3 == 0:
            categories["good"].append({"name": name})
        elif count_3 == 1:
            subj_with_3 = next((s for s, g in subj_grades.items() if g == 3), "")
            categories["one_3"].append(
                {
                    "name": name,
                    "subject": subj_with_3,
                    "teacher": subject_teachers.get(subj_with_3, ""),
                }
            )
        else:
            subjects_with_3 = [s for s, g in subj_grades.items() if g == 3]
            categories["satisfactory"].append(
                {"name": name, "subjects_with_3": subjects_with_3}
            )

    return categories


def categories_per_class_to_blocks(
    categories: dict[str, list],
    class_name: str,
    class_teacher_name: str,
) -> dict[str, list]:
    """Преобразование flat-категорий API в формат admin/HTML/Excel."""
    blocks: dict[str, list] = {k: [] for k in _CATEGORY_KEYS}

    excellent = [item["name"] for item in categories.get("excellent", [])]
    if excellent:
        blocks["excellent"].append(
            {
                "class_name": class_name,
                "class_teacher": class_teacher_name,
                "students": excellent,
            }
        )

    good = [item["name"] for item in categories.get("good", [])]
    if good:
        blocks["good"].append(
            {
                "class_name": class_name,
                "class_teacher": class_teacher_name,
                "students": good,
            }
        )

    one_4 = [
        {
            "student": item["name"],
            "subject": item.get("subject", ""),
            "teacher": item.get("teacher", ""),
        }
        for item in categories.get("one_4", [])
    ]
    if one_4:
        blocks["one_4"].append(
            {
                "class_name": class_name,
                "class_teacher": class_teacher_name,
                "students": one_4,
            }
        )

    satisf_names = [item["name"] for item in categories.get("satisfactory", [])]
    troechniki_detailed = []
    for item in categories.get("satisfactory", []):
        subjs3 = [
            {"subject_name": s, "grade": 3}
            for s in item.get("subjects_with_3", [])
        ]
        troechniki_detailed.append(
            {
                "student": item["name"],
                "subjects_1_4": subjs3[:4],
                "subjects_5": subjs3[4:],
            }
        )
    if satisf_names:
        block = {
            "class_name": class_name,
            "class_teacher": class_teacher_name,
            "students": satisf_names,
            "troechniki_detailed": troechniki_detailed,
        }
        blocks["satisfactory"].append(block)

    one_3 = [
        {
            "student": item["name"],
            "subject": item.get("subject", ""),
            "teacher": item.get("teacher", ""),
        }
        for item in categories.get("one_3", [])
    ]
    if one_3:
        blocks["one_3"].append(
            {
                "class_name": class_name,
                "class_teacher": class_teacher_name,
                "students": one_3,
            }
        )

    poor_rows = []
    for item in categories.get("poor", []):
        for subj in item.get("subjects", []):
            poor_rows.append(
                {
                    "student": item["name"],
                    "subject": subj.get("subject", ""),
                    "teacher": subj.get("teacher", ""),
                }
            )
    if poor_rows:
        blocks["poor"].append(
            {
                "class_name": class_name,
                "class_teacher": class_teacher_name,
                "students": poor_rows,
            }
        )

    return blocks


def _merge_category_blocks(
    target: dict[str, list], source: dict[str, list]
) -> None:
    for key in _CATEGORY_KEYS:
        target[key].extend(source.get(key, []))


def _apply_student_filter(blocks: dict[str, list], student_filter: str) -> None:
    if not student_filter:
        return
    for key in _CATEGORY_KEYS:
        filtered = []
        for block in blocks[key]:
            students = block.get("students", [])
            if key in ("excellent", "good", "satisfactory"):
                students = [
                    s
                    for s in students
                    if isinstance(s, str) and s.strip().lower() == student_filter
                ]
            else:
                students = [
                    s
                    for s in students
                    if (s.get("student") or "").strip().lower() == student_filter
                ]
            if key == "satisfactory":
                block = dict(block)
                block["troechniki_detailed"] = [
                    d
                    for d in block.get("troechniki_detailed", [])
                    if (d.get("student") or "").strip().lower() == student_filter
                ]
            if students:
                block = dict(block)
                block["students"] = students
                filtered.append(block)
        blocks[key] = filtered


def build_class_teacher_categories_data(
    school_id: int,
    period_number: int,
    *,
    segment: str | None = None,
    class_filter: str | None = None,
    class_teacher_filter: str | None = None,
    student_filter: str | None = None,
    class_names: list[str] | None = None,
    academic_year: int | None = None,
) -> dict[str, list]:
    """
    Собирает categories_data для HTML/Excel отчёта классного руководителя.

    class_names: если задан — только эти классы (для API managed classes).
    """
    from ..class_grades_matrix import build_class_grades_matrix

    class_filter = (class_filter or "").strip().lower()
    class_teacher_filter = (class_teacher_filter or "").strip().lower()
    student_filter = (student_filter or "").strip().lower()

    all_reports = get_period_reports(
        school_id, period_number, academic_year=academic_year
    )
    active_class_names = {
        row.name
        for row in Class.query.filter_by(school_id=school_id).with_entities(Class.name).all()
    }
    all_reports = [r for r in all_reports if r.class_name in active_class_names]

    if class_names is None:
        all_class_names = {r.class_name for r in all_reports}
        sorted_classes: list[tuple[int, str]] = []
        for cls_name in all_class_names:
            if not _segment_matches(cls_name, segment):
                continue
            grade_num = parse_class_grade(cls_name)
            sorted_classes.append(
                (grade_num if grade_num is not None else 999, cls_name)
            )
        class_names = [
            name
            for _, name in sorted(
                sorted_classes, key=lambda x: (x[0], kazakh_sort_key(x[1]))
            )
        ]

    categories_data: dict[str, list] = {k: [] for k in _CATEGORY_KEYS}

    for cls_name in class_names:
        if class_filter and cls_name.strip().lower() != class_filter:
            continue

        cls_obj = Class.query.filter_by(school_id=school_id, name=cls_name).first()
        class_teacher_name = ""
        if cls_obj and cls_obj.class_teacher:
            class_teacher_name = (
                cls_obj.class_teacher.full_name or cls_obj.class_teacher.username
            )

        if (
            class_teacher_filter
            and class_teacher_name.strip().lower() != class_teacher_filter
        ):
            continue

        matrix = build_class_grades_matrix(
            school_id,
            cls_name,
            period_number,
            academic_year=academic_year,
        )
        if matrix["empty"]:
            continue

        categories = categorize_students(
            matrix["students"], matrix["subject_teachers"]
        )
        blocks = categories_per_class_to_blocks(
            categories, cls_name, class_teacher_name
        )
        if student_filter:
            _apply_student_filter(blocks, student_filter)
        _merge_category_blocks(categories_data, blocks)

    return categories_data


__all__ = [
    "categorize_students",
    "categories_per_class_to_blocks",
    "build_class_teacher_categories_data",
]
