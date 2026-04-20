"""Словарь подписей четвертей; при наличии webapp импортируется из webapp.constants."""

try:
    from webapp.constants import PERIOD_MAP
except ImportError:
    PERIOD_MAP = {
        "1": "1 четверть",
        "2": "2 четверть (1 полугодие)",
        "3": "3 четверть",
        "4": "4 четверть (2 полугодие)",
        "5": "Учебный год",
    }
