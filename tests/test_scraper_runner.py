"""Тесты вспомогательных функций scraper_runner (без Playwright)."""

from webapp.scraper_runner import (
    _org_names_match,
    _parse_class_subject,
    get_max_concurrent_jobs,
)


class TestParseClassSubject:
    def test_kazakh_class_quotes(self):
        assert _parse_class_subject('5 «В» Математика') == ('5 «В»', 'Математика')

    def test_fallback_first_token(self):
        assert _parse_class_subject("7А Алгебра") == ("7А", "Алгебра")

    def test_single_token(self):
        assert _parse_class_subject("7А") == ("7А", "")

    def test_empty(self):
        assert _parse_class_subject("") == ("", "")


class TestOrgNamesMatch:
    def test_exact_case_insensitive(self):
        assert _org_names_match("  Школа №1 ", "школа №1")

    def test_partial_inclusion(self):
        assert _org_names_match("IT лицей", "Специализированный IT лицей")

    def test_empty_names(self):
        assert not _org_names_match("", "Школа")
        assert not _org_names_match("Школа", "")

    def test_no_match(self):
        assert not _org_names_match("Лицей А", "Гимназия Б")


def test_get_max_concurrent_jobs_default():
    assert get_max_concurrent_jobs() >= 1
