"""Tests for grade_table_signals.detect_grade_summary_columns."""

import pytest

from grade_table_signals import detect_grade_summary_columns


@pytest.mark.parametrize(
    "texts,expected",
    [
        (["Сумма%", "Оценка"], True),
        (["№", "Ф.И.О.", "Сумма%", "Оценка"], True),
        (["Жиынтық%", "Баға"], True),
        (["Сумма%", "СОр 1"], False),
        (["Оценка"], False),
        ([], False),
    ],
)
def test_detect_grade_summary_columns(texts, expected):
    assert detect_grade_summary_columns(texts) is expected
