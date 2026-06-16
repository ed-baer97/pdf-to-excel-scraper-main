"""Общие константы и утилиты для названий предметов и сортировки (веб и API)."""

import re

# Актуальный релиз Mektep Desktop (синхронизировать с mektep-desktop/version.py).
DESKTOP_VERSION = "1.2.1"

# Минимальная версия десктопа для API (логин, загрузка отчётов).
MIN_DESKTOP_VERSION = (1, 2, 1)

# Раздача установщика и манифеста автообновления (Nginx /updates/).
DESKTOP_UPDATES_BASE_URL = "https://mektep-analyzer.kz/updates/"


def desktop_installer_filename(version: str | None = None) -> str:
    """Имя Inno Setup установщика для указанной версии."""
    v = (version or DESKTOP_VERSION).strip()
    return f"MektepDesktopSetup-{v}.exe"


def desktop_download_url(version: str | None = None) -> str:
    """Прямая ссылка на установщик на сервере обновлений."""
    base = DESKTOP_UPDATES_BASE_URL.rstrip("/")
    return f"{base}/{desktop_installer_filename(version)}"

PERIOD_MAP = {
    "1": "1 четверть",
    "2": "2 четверть (1 полугодие)",
    "3": "3 четверть",
    "4": "4 четверть (2 полугодие)",
    "6": "Итог",
}

_SUBGROUP_RE = re.compile(r"\s*\(\d+\)\s*$")

# Kazakh Cyrillic collation order (with common Cyrillic letters).
_KAZAKH_ALPHABET = (
    "аәбвгғдеёжзийкқлмнңоөпрстуұүфхһцчшщъыіьэюя"
)
_KAZAKH_ORDER = {char: idx for idx, char in enumerate(_KAZAKH_ALPHABET)}

# Казахское / альтернативное название → каноническое (русское) для сводных таблиц.
DEFAULT_SUBJECT_ALIASES: dict[str, str] = {
    "Орыс тілі": "Русский язык",
    "Орыс әдебиеті": "Русская литература",
    "Қазақ тілі мен әдебиеті": "Казахский язык и литература",
    "Шетел тілі": "Иностранный язык",
    "Математика": "Математика",
    "Информатика": "Информатика",
    "Жаратылыстану": "Естествознание",
    "Қазақстан тарихы": "История Казахстана",
    "Дүниежүзі тарихы": "Всемирная история",
}


def _base_normalize_subject_name(raw: str) -> str:
    """Убирает суффикс подгруппы (N) и точное дублирование строки в названии."""
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


def _apply_subject_aliases(name: str, aliases: dict[str, str]) -> str:
    """Сопоставляет название со словарём: билингвальные и казахские варианты → канон."""
    name_stripped = name.strip()
    if not name_stripped or not aliases:
        return name_stripped

    canonicals = set(aliases.values())
    for canonical in sorted(canonicals, key=len, reverse=True):
        if name_stripped == canonical:
            return canonical
        suffix = " " + canonical
        if name_stripped.endswith(suffix):
            return canonical

    for alias, canonical in sorted(aliases.items(), key=lambda x: len(x[0]), reverse=True):
        if alias and alias.lower() in name_stripped.lower():
            return canonical

    return name_stripped


def normalize_subject_name(raw: str, school_id: int | None = None) -> str:
    """
    Приводит название предмета к каноническому виду.
    При переданном school_id учитывает словарь школы из БД.
    """
    if school_id is not None:
        from .services.subject_aliases import normalize_subject_name as _norm_school

        return _norm_school(raw, school_id)

    name = _base_normalize_subject_name(raw)
    return _apply_subject_aliases(name, DEFAULT_SUBJECT_ALIASES)


def kazakh_sort_key(raw: str | None) -> tuple:
    """
    Ключ сортировки для казахского кириллического текста (порядок алфавита, неизвестные символы в конец).
    """
    text = str(raw or "").strip().lower()
    order = tuple(_KAZAKH_ORDER.get(char, 1000 + ord(char)) for char in text)
    return (order, text)
