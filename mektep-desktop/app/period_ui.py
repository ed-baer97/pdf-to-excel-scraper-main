"""Общие значения селектора периода в десктопе (только четверти 1–4 для скрапа)."""


def period_combo_items(translator) -> list[tuple[str, int]]:
    """Подписи периода для QComboBox: (label, period_number 1–4)."""
    return [
        (translator.tr("quarter_1"), 1),
        (translator.tr("quarter_2"), 2),
        (translator.tr("quarter_3"), 3),
        (translator.tr("quarter_4"), 4),
    ]
