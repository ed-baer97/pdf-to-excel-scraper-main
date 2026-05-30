"""Тесты нумерации предметов при нескольких учителях (критериальное оценивание)."""

from types import SimpleNamespace

from webapp.services.criteria_grades import list_criteria_subject_entries


def _report(rid, cls, subj, teacher_name, criteria_students):
    import json

    return SimpleNamespace(
        id=rid,
        class_name=cls,
        subject_name=subj,
        teacher=SimpleNamespace(full_name=teacher_name, username=""),
        teacher_id=rid,
        grades_json=json.dumps(
            {
                "students": [{"name": "A", "grade": 5}],
                "criteria": {
                    "quarter_num": 1,
                    "sections": [1],
                    "max_points": {"1": 10},
                    "students": criteria_students,
                },
            },
            ensure_ascii=False,
        ),
    )


def test_list_criteria_subject_entries_single_teacher():
    r = _report(1, "7А", "Математика", "Иванов", [{"num": 1, "fio": "A", "grade": "4", "points": {}}])
    entries = list_criteria_subject_entries([r], school_id=None, period_number=1)
    assert len(entries) == 1
    assert entries[0]["display_name"] == "Математика"


def test_list_criteria_subject_entries_two_teachers_same_subject():
    s = [{"num": 1, "fio": "A", "grade": "4", "points": {}}]
    r1 = _report(1, "7А", "Математика (1)", "Алиев", s)
    r2 = _report(2, "7А", "Математика (2)", "Беков", s)
    entries = list_criteria_subject_entries([r1, r2], school_id=None, period_number=1)
    assert len(entries) == 2
    names = {e["display_name"] for e in entries}
    assert names == {"Математика 1", "Математика 2"}
    assert entries[0]["report_id"] != entries[1]["report_id"]
