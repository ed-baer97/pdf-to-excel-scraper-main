"""Тесты удаления ученика из grades_json."""

from webapp.services.grade_reports.student_edits import remove_student_from_payload


def test_remove_student_from_payload_and_recalc():
    payload = {
        "students": [
            {"name": "Айлин", "grade": 3, "percent": 57.0},
            {"name": "Абильмансур", "grade": 5, "percent": 91.0},
        ],
        "total_students": 2,
        "quality_percent": 50.0,
        "success_percent": 100.0,
    }
    assert remove_student_from_payload(payload, "Айлин") is True
    assert len(payload["students"]) == 1
    assert payload["students"][0]["name"] == "Абильмансур"
    assert payload["total_students"] == 1
    assert payload["quality_percent"] == 100.0
    assert payload["success_percent"] == 100.0


def test_remove_student_from_criteria_block():
    payload = {
        "students": [{"name": "Иван", "grade": 4}],
        "criteria": {
            "students": [
                {"fio": "Иван", "points": {}},
                {"fio": "Пётр", "points": {}},
            ],
        },
    }
    assert remove_student_from_payload(payload, "Иван") is True
    assert len(payload["students"]) == 0
    assert len(payload["criteria"]["students"]) == 1
    assert payload["criteria"]["students"][0]["fio"] == "Пётр"


def test_remove_student_no_match():
    payload = {"students": [{"name": "Айлин", "grade": 3}]}
    assert remove_student_from_payload(payload, "Нет такого") is False
    assert len(payload["students"]) == 1
