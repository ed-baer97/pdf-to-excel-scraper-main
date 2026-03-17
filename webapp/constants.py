"""Common constants used across the application."""

import re

PERIOD_MAP = {
    "1": "1 четверть",
    "2": "2 четверть (1 полугодие)",
    "3": "3 четверть",
    "4": "4 четверть (2 полугодие)",
}

_SUBGROUP_RE = re.compile(r"\s*\(\d+\)\s*$")

# Kazakh Cyrillic collation order (with common Cyrillic letters).
_KAZAKH_ALPHABET = (
    "аәбвгғдеёжзийкқлмнңоөпрстуұүфхһцчшщъыіьэюя"
)
_KAZAKH_ORDER = {char: idx for idx, char in enumerate(_KAZAKH_ALPHABET)}


def normalize_subject_name(raw: str) -> str:
    """Normalize subject name: strip subgroup suffix and deduplicate repeated base name.

    Examples:
        "Иностранный язык Иностранный язык (1)" -> "Иностранный язык"
        "Иностранный язык Иностранный язык (2)" -> "Иностранный язык"
        "Математика"                             -> "Математика"
        "Казахский язык (1)"                     -> "Казахский язык"
        "Физика Физика"                          -> "Физика"
    """
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
    Locale-like sort key for Kazakh Cyrillic text.

    Unknown symbols are placed after alphabet characters and then ordered by
    Unicode code point.
    """
    text = str(raw or "").strip().lower()
    order = tuple(_KAZAKH_ORDER.get(char, 1000 + ord(char)) for char in text)
    return (order, text)
