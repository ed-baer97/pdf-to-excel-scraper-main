"""Tests for grade_reports.payload helpers."""

from __future__ import annotations

from webapp.services.grade_reports.payload import (
    parse_analytics_json,
    parse_grades_json,
    report_analytics_payload,
    report_grades_payload,
)


class _Report:
    def __init__(self, grades_json=None, analytics_json=None):
        self.grades_json = grades_json
        self.analytics_json = analytics_json


def test_parse_grades_json_empty():
    assert parse_grades_json(None) is None
    assert parse_grades_json("") is None


def test_parse_grades_json_invalid():
    assert parse_grades_json("{not json") is None


def test_parse_grades_json_valid():
    data = parse_grades_json('{"students": [{"name": "X", "grade": 4}]}')
    assert data["students"][0]["name"] == "X"


def test_report_grades_payload_wrapper():
    r = _Report(grades_json='{"students": []}')
    assert report_grades_payload(r)["students"] == []


def test_parse_analytics_json_non_dict():
    assert parse_analytics_json("[1,2]") is None
