"""Общие значения селектора периода в десктопе."""

# Совпадает с webapp.services.year_grades.YEAR_UI_PERIOD
YEAR_UI_PERIOD = 5


def period_combo_items(translator) -> list[tuple[str, int]]:
    """Четверти 1–4 (скрап на главном экране)."""
    return [
        (translator.tr("quarter_1"), 1),
        (translator.tr("quarter_2"), 2),
        (translator.tr("quarter_3"), 3),
        (translator.tr("quarter_4"), 4),
    ]


def period_combo_items_grades_view(translator) -> list[tuple[str, int]]:
    """Четверти 1–4 и учебный год (просмотр оценок, отчёты кл. рук. и предметника)."""
    return [
        *period_combo_items(translator),
        (translator.tr("period_year"), YEAR_UI_PERIOD),
    ]
