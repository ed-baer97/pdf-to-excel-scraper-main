"""Tests for app.report_pipeline.report_utils (desktop)."""

import json
from pathlib import Path

import pytest

from app.report_pipeline.progress_monitor import (
    format_progress_line,
    parse_schools_from_progress_message,
)
from app.report_pipeline.report_utils import (
    can_upload_period_grades,
    has_grade_summary_columns,
    has_quarter_grade_header,
    is_semester_subject,
    normalize_period_code,
    parse_class_liter,
    parse_number,
    resolve_period,
    sanitize_filename,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ('5 «В»', "5В"),
        ("  10 А ", "10А"),
        ("no match here", "no match here"),
    ],
)
def test_parse_class_liter(raw, expected):
    """Проверяет нормализацию строки класса (литера, пробелы)."""
    assert parse_class_liter(raw) == expected


@pytest.mark.parametrize(
    "val,expected",
    [
        (None, None),
        (42, 42.0),
        ("12,5%", 12.5),
        ("", None),
        ("bad", None),
    ],
)
def test_parse_number(val, expected):
    """Проверяет разбор чисел из строк, процентов и невалидного ввода."""
    got = parse_number(val)
    if expected is None:
        assert got is None
    else:
        assert got == pytest.approx(expected)


def test_sanitize_filename():
    """Проверяет замену недопустимых символов в имени файла."""
    assert sanitize_filename("a<b>c") == "a_b_c"


def test_resolve_period_quarter(tmp_path):
    """Четвертной предмет: ожидается тип quarter и номер четверти."""
    (tmp_path / "criteria_tabs.json").write_text("[]", encoding="utf-8")
    ptype, pnum, skip = resolve_period("3", tmp_path)
    assert ptype == "quarter"
    assert pnum == 3
    assert skip is False


def test_resolve_period_semester_from_tabs(tmp_path):
    """Полугодие по вкладкам: первое полугодие при периоде 2."""
    tabs = [{"text": "полугодие итог"}]
    (tmp_path / "criteria_tabs.json").write_text(json.dumps(tabs), encoding="utf-8")
    ptype, pnum, skip = resolve_period("2", tmp_path)
    assert ptype == "semester"
    assert pnum == 1
    assert skip is False


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1", "1"),
        (" 4 ", "4"),
        (2, "2"),
        ("0", None),
        ("5", None),
        ("6", "6"),
        ("q1", None),
        (None, None),
    ],
)
def test_normalize_period_code(raw, expected):
    """Нормализация period_code: 1..4 и 6 (итог)."""
    assert normalize_period_code(raw) == expected


def test_resolve_period_final(tmp_path):
  """Код 6 — period_type final."""
  ptype, pnum, skip = resolve_period("6", tmp_path)
  assert ptype == "final"
  assert pnum == 1
  assert skip is False


def test_resolve_period_invalid_code(tmp_path):
    """Невалидный period_code должен приводить к skip=True."""
    ptype, pnum, skip = resolve_period("q1", tmp_path)
    assert ptype == "quarter"
    assert pnum == 1
    assert skip is True


def test_is_semester_from_context(tmp_path):
    """При заголовке четвертной оценки предмет не считается полугодовым."""
    ctx = {"has_quarter_grade_header": True}
    (tmp_path / "criteria_context.json").write_text(json.dumps(ctx), encoding="utf-8")
    assert is_semester_subject(tmp_path) is False


def test_can_upload_with_quarter_grade_header(tmp_path):
    ctx = {"has_quarter_grade_header": True}
    (tmp_path / "criteria_context.json").write_text(json.dumps(ctx), encoding="utf-8")
    assert has_quarter_grade_header(tmp_path) is True
    assert can_upload_period_grades(tmp_path) is True


def test_can_upload_denied_without_quarter_grade_header(tmp_path):
    assert has_quarter_grade_header(tmp_path) is False
    assert can_upload_period_grades(tmp_path) is False


def test_has_grade_summary_columns_from_context(tmp_path):
    ctx = {"visible_grade_summary_columns": True}
    (tmp_path / "criteria_context.json").write_text(json.dumps(ctx), encoding="utf-8")
    assert has_grade_summary_columns(tmp_path) is True
    assert can_upload_period_grades(tmp_path) is False


def test_has_grade_summary_columns_legacy_key(tmp_path):
    ctx = {"has_grade_summary_columns": True}
    (tmp_path / "criteria_context.json").write_text(json.dumps(ctx), encoding="utf-8")
    assert has_grade_summary_columns(tmp_path) is True
    assert can_upload_period_grades(tmp_path) is False


def test_parse_schools_message():
    """Разбор сообщения schools_selection_needed|... в список школ."""
    payload = [{"name": "School A"}]
    msg = "schools_selection_needed|" + json.dumps(payload)
    assert parse_schools_from_progress_message(msg) == payload
    assert parse_schools_from_progress_message("other") is None


def test_format_progress_line():
    """Формат строки прогресса с и без total_reports."""
    assert format_progress_line("Working", 10, 3) == "Working (3/10)"
    assert format_progress_line("Working", None, 0) == "Working"
