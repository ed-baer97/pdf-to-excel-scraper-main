"""Общие константы и утилиты для названий предметов и сортировки (веб и API)."""

import re

# Минимальная версия десктоп-приложения, которая допускается к авторизации.
# Обновляйте при каждом обязательном (breaking) обновлении десктопа.
MIN_DESKTOP_VERSION = (1, 1, 0)

PERIOD_MAP = {
    "1": "1 четверть",
    "2": "2 четверть (1 полугодие)",
    "3": "3 четверть",
    "4": "4 четверть (2 полугодие)",
    "5": "Учебный год",
}

_SUBGROUP_RE = re.compile(r"\s*\(\d+\)\s*$")

# Kazakh Cyrillic collation order (with common Cyrillic letters).
_KAZAKH_ALPHABET = (
    "аәбвгғдеёжзийкқлмнңоөпрстуұүфхһцчшщъыіьэюя"
)
_KAZAKH_ORDER = {char: idx for idx, char in enumerate(_KAZAKH_ALPHABET)}


def normalize_subject_name(raw: str) -> str:
    """Приводит название предмета к каноническому виду: убирает суффикс (N) и дублирование строки."""
    name = _SUBGROUP_RE.sub("", raw).strip()

    half = len(name) // 2
    if half > 0 and len(name) % 2 != 0:
        left = name[:half]
        right = name[half + 1:]
        if left == right and name[half] == " ":
            name = left

    if half > 0 and len(name) % 2 == 0:
        left = name[:half]
        right = name[half:]
        if right.startswith(" ") and left == right.lstrip():
            name = left

    return name


def kazakh_sort_key(raw: str | None) -> tuple:
    """
    Ключ сортировки для казахского кириллического текста (порядок алфавита, неизвестные символы в конец).
    """
    text = str(raw or "").strip().lower()
    order = tuple(_KAZAKH_ORDER.get(char, 1000 + ord(char)) for char in text)
    return (order, text)
