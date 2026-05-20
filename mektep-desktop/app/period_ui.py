"""Общие значения селектора периода в десктопе (5 = учебный год)."""

YEAR_UI_PERIOD = 5


def period_combo_items(translator) -> list[tuple[str, int]]:
    """Подписи периода для QComboBox: (label, period_number для API)."""
    return [
        (translator.tr("quarter_1"), 1),
        (translator.tr("quarter_2"), 2),
        (translator.tr("quarter_3"), 3),
        (translator.tr("quarter_4"), 4),
        (translator.tr("period_year"), YEAR_UI_PERIOD),
    ]
