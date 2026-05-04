"""
Утилиты сортировки для десктопа (аналогично webapp/constants.py).
"""

# Kazakh Cyrillic collation order (with common Cyrillic letters).
_KAZAKH_ALPHABET = (
    "аәбвгғдеёжзийкқлмнңоөпрстуұүфхһцчшщъыіьэюя"
)
_KAZAKH_ORDER = {char: idx for idx, char in enumerate(_KAZAKH_ALPHABET)}


def kazakh_sort_key(raw: str | None) -> tuple:
    """
    Ключ сортировки для казахского кириллического текста
    (неизвестные символы отправляются в конец).
    """
    text = str(raw or "").strip().lower()
    order = tuple(_KAZAKH_ORDER.get(char, 1000 + ord(char)) for char in text)
    return (order, text)
