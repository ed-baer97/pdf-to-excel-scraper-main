"""Общие значения селектора периода в десктопе."""

from PyQt6.QtCore import QSettings

from .academic_year import (
    academic_year_choices,
    current_academic_year,
    format_academic_year,
)

# Совпадает с webapp.services.year_grades.YEAR_UI_PERIOD
YEAR_UI_PERIOD = 5
SETTINGS_YEAR_KEY = "academic_year"


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


def saved_academic_year() -> int:
    """Последний выбранный учебный год или текущий."""
    raw = QSettings("Mektep", "MektepDesktop").value(SETTINGS_YEAR_KEY)
    try:
        if raw not in (None, ""):
            return int(raw)
    except (TypeError, ValueError):
        pass
    return current_academic_year()


def remember_academic_year(year: int) -> None:
    QSettings("Mektep", "MektepDesktop").setValue(SETTINGS_YEAR_KEY, int(year))


def populate_academic_year_combo(combo, selected_year: int | None = None) -> None:
    """Заполняет комбобокс подписями «2025–2026», в data — год начала."""
    combo.blockSignals(True)
    combo.clear()
    chosen = saved_academic_year() if selected_year is None else int(selected_year)
    for year in academic_year_choices([chosen]):
        combo.addItem(format_academic_year(year), year)
    index = combo.findData(chosen)
    combo.setCurrentIndex(index if index >= 0 else 0)
    combo.blockSignals(False)


def combo_academic_year(combo) -> int:
    data = combo.currentData()
    if data is None:
        return current_academic_year()
    return int(data)
