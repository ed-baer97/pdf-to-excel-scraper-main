"""Tests for webapp.services.year_grades."""

import pytest

from webapp.services.year_grades import (
    compute_year_grade_from_periods,
    math_round,
    math_round_percent,
    quality_success_from_grades,
)


@pytest.mark.parametrize(
    "value,expected",
    [
        (2.4, 2),
        (2.5, 3),
        (3.5, 4),
        (4.5, 5),
    ],
)
def test_math_round(value, expected):
    assert math_round(value) == expected


def test_math_round_percent():
    assert math_round_percent(1, 2) == 50
    assert math_round_percent(2, 3) == 67


def test_quality_success_from_grades():
    quality, success = quality_success_from_grades([5, 4, 3, 2])
    assert quality == 50
    assert success == 75


def test_year_grade_quarter_all_four():
    grades = {1: 5, 2: 4, 3: 4, 4: 5}
    assert compute_year_grade_from_periods(grades, is_semester=False) == 5


def test_year_grade_quarter_missing_one():
    grades = {1: 5, 2: 4, 3: None, 4: 5}
    assert compute_year_grade_from_periods(grades, is_semester=False) is None


def test_year_grade_semester_both_halves():
    grades = {2: 4, 4: 5}
    assert compute_year_grade_from_periods(grades, is_semester=True) == 5


def test_year_grade_semester_missing_half():
    grades = {2: 4, 4: None}
    assert compute_year_grade_from_periods(grades, is_semester=True) is None


def test_year_grade_semester_ignores_q1_q3():
    grades = {1: 2, 2: 4, 3: 2, 4: 4}
    assert compute_year_grade_from_periods(grades, is_semester=True) == 4
