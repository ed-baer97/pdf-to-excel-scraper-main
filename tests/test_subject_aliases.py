"""Тесты нормализации названий предметов по словарю."""

from webapp.constants import (
    DEFAULT_SUBJECT_ALIASES,
    _apply_subject_aliases,
    _base_normalize_subject_name,
    normalize_subject_name,
)


def test_apply_bilingual_kazakh_literature():
    raw = "Қазақ тілі мен әдебиеті Казахский язык и литература"
    assert (
        _apply_subject_aliases(_base_normalize_subject_name(raw), DEFAULT_SUBJECT_ALIASES)
        == "Казахский язык и литература"
    )


def test_apply_russian_only_canonical():
    assert (
        _apply_subject_aliases("Казахский язык и литература", DEFAULT_SUBJECT_ALIASES)
        == "Казахский язык и литература"
    )


def test_apply_kazakh_alias():
    assert (
        _apply_subject_aliases("Орыс тілі", DEFAULT_SUBJECT_ALIASES) == "Русский язык"
    )


def test_normalize_without_school_uses_defaults():
    assert normalize_subject_name("Шетел тілі") == "Иностранный язык"


def test_subgroup_suffix_stripped():
    assert normalize_subject_name("Математика (2)") == "Математика"
