"""Tests for grade_table_signals visible-table detection."""

import pytest

from grade_table_signals import (
    analyze_visible_table_headers,
    can_upload_from_visible_headers,
    detect_grade_summary_columns,
    detect_visible_soch_column,
)


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


@pytest.mark.parametrize(
    "texts,expected",
    [
        (["СОЧ"], True),
        (["ТЖБ"], True),
        (["Суммативное оценивание за четверть"], True),
        (["Суммативное оценивание за раздел 25%"], False),
        (["СОр 1", "Суммативное оценивание за раздел 25%"], False),
        (["СОр 1"], False),
    ],
)
def test_detect_visible_soch_column(texts, expected):
    assert detect_visible_soch_column(texts) is expected


def test_world_history_sor_only_headers_no_upload():
    """Как «Всемирная история» 5Б, 1 четверть: только СОР, без итоговых колонок."""
    texts = [
        "№",
        "Ф.И.О. ученика",
        "Суммативное оценивание за раздел 25%",
        "Раздел 1. СОр 1",
    ]
    analysis = analyze_visible_table_headers(texts)
    assert analysis["visible_grade_summary_columns"] is False
    assert analysis["visible_soch_column"] is False
    assert can_upload_from_visible_headers(texts) is False


def test_hidden_grade_headers_must_not_be_passed():
    """В analyze передаём только видимые ячейки — скрытые «Оценка»/«Сумма%» не должны попадать."""
    visible_only = ["№", "Ф.И.О.", "Суммативное оценивание за раздел 25%", "СОр 1"]
    assert can_upload_from_visible_headers(visible_only) is False
    # Если бы скрытые колонки ошибочно попали в список:
    with_hidden = visible_only + ["Сумма%", "Оценка"]
    assert can_upload_from_visible_headers(with_hidden) is True
