"""Tests for grade_reports.class_teacher categorization and blocks."""

from __future__ import annotations

from webapp.services.grade_reports.class_teacher import (
    build_class_teacher_categories_data,
    categories_per_class_to_blocks,
    categorize_students,
)


def test_categorize_excellent_and_good():
    students = {
        "Отличник": {
            "А": {"grade": 5},
            "Б": {"grade": 5},
        },
        "Хорошист": {
            "А": {"grade": 5},
            "Б": {"grade": 4},
            "В": {"grade": 4},
        },
    }
    cats = categorize_students(students, {"А": "T1", "Б": "T2", "В": "T3"})
    assert len(cats["excellent"]) == 1
    assert cats["excellent"][0]["name"] == "Отличник"
    assert len(cats["good"]) == 1
    assert cats["good"][0]["name"] == "Хорошист"


def test_categorize_one_4_and_poor():
    students = {
        "Почти": {"А": {"grade": 5}, "Б": {"grade": 4}},
        "Двоечник": {"А": {"grade": 2}, "Б": {"grade": 5}},
    }
    cats = categorize_students(students, {"А": "Ta", "Б": "Tb"})
    assert len(cats["one_4"]) == 1
    assert cats["one_4"][0]["subject"] == "Б"
    assert len(cats["poor"]) == 1
    assert cats["poor"][0]["subjects"][0]["subject"] == "А"


def test_categorize_satisfactory_with_troechniki():
    students = {
        "Троечник": {
            "А": {"grade": 3},
            "Б": {"grade": 3},
            "В": {"grade": 5},
        },
    }
    cats = categorize_students(students, {})
    assert len(cats["satisfactory"]) == 1
    assert set(cats["satisfactory"][0]["subjects_with_3"]) == {"А", "Б"}

    blocks = categories_per_class_to_blocks(cats, "7А", "Учитель")
    assert len(blocks["satisfactory"]) == 1
    block = blocks["satisfactory"][0]
    assert block["class_name"] == "7А"
    assert "Троечник" in block["students"]
    assert len(block["troechniki_detailed"]) == 1
    assert block["troechniki_detailed"][0]["student"] == "Троечник"


def test_categories_per_class_to_blocks_one_3():
    cats = categorize_students(
        {"Ученик": {"М": {"grade": 5}, "Ф": {"grade": 3}}},
        {"М": "T1", "Ф": "T2"},
    )
    blocks = categories_per_class_to_blocks(cats, "8Б", "Кл. рук.")
    assert len(blocks["one_3"]) == 1
    row = blocks["one_3"][0]["students"][0]
    assert row["student"] == "Ученик"
    assert row["subject"] == "Ф"


def test_student_filter_on_blocks():
    from webapp.services.grade_reports.class_teacher import _apply_student_filter

    cats = categorize_students(
        {
            "Аа": {"А": {"grade": 5}},
            "Бб": {"А": {"grade": 5}},
        },
        {"А": "T1"},
    )
    blocks = categories_per_class_to_blocks(cats, "1А", "Уч")
    _apply_student_filter(blocks, "аа")
    assert blocks["excellent"][0]["students"] == ["Аа"]


def test_segment_filter_1_4():
    from webapp.services.grade_reports.analytics import _segment_matches

    assert _segment_matches("3А", "1-4") is True
    assert _segment_matches("10А", "1-4") is False
    assert _segment_matches("10А", "5-11") is True
