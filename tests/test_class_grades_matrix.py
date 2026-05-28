"""Tests for webapp.services.class_grades_matrix."""

import pytest

from webapp.services.class_grades_matrix import (
    categorize_students,
    subject_column_stats,
    students_with_grades_count,
)


def _matrix():
    return {
        "Иванов И.": {
            "Математика": {"grade": 5, "percent": 90},
            "Физика": {"grade": 5, "percent": 88},
        },
        "Петров П.": {
            "Математика": {"grade": 4, "percent": 75},
            "Физика": {"grade": 5, "percent": 92},
        },
        "Сидоров С.": {
            "Математика": {"grade": 3, "percent": 60},
            "Физика": {"grade": 4, "percent": 70},
        },
    }


def test_subject_column_stats_matches_column():
    students = _matrix()
    stats = subject_column_stats(students, "Математика")
    assert stats["count_5"] == 1
    assert stats["count_4"] == 1
    assert stats["count_3"] == 1
    assert stats["total"] == 3
    assert stats["quality_percent"] == round(2 / 3 * 100, 1)
    assert stats["success_percent"] == 100.0


def test_subject_column_stats_semester_merge_scenario():
    """Два «источника» уже сведены в матрицу — берём итоговые ячейки."""
    students = {
        "А": {"Предмет": {"grade": 5, "percent": None}},
        "Б": {"Предмет": {"grade": 4, "percent": None}},
    }
    stats = subject_column_stats(students, "Предмет")
    assert stats["count_5"] == 1
    assert stats["count_4"] == 1
    assert stats["total"] == 2


def test_categorize_excellent_and_one_4():
    students = {
        "Отличник": {
            "А": {"grade": 5, "percent": None},
            "Б": {"grade": 5, "percent": None},
        },
        "Почти": {
            "А": {"grade": 5, "percent": None},
            "Б": {"grade": 4, "percent": None},
        },
    }
    cats = categorize_students(students, {"А": "Учитель А", "Б": "Учитель Б"})
    assert len(cats["excellent"]) == 1
    assert cats["excellent"][0]["name"] == "Отличник"
    assert len(cats["one_4"]) == 1
    assert cats["one_4"][0]["name"] == "Почти"
    assert cats["one_4"][0]["subject"] == "Б"


def test_students_with_grades_count():
    assert students_with_grades_count(_matrix()) == 3
    assert students_with_grades_count({"X": {"А": {"grade": None, "percent": None}}}) == 0
