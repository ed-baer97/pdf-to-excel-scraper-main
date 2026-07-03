"""Страж против возврата дублей: единственная копия кода скрапера — в mektep_core.

Раньше scrape_mektep.py и соседние модули существовали в двух копиях
(корень и mektep-desktop/) и синхронизировались вручную. Эти тесты
не дают ситуации повториться: шимы в корне должны оставаться тонкими
реэкспортами, а копий в mektep-desktop быть не должно.
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

SHARED_MODULES = [
    "scrape_mektep.py",
    "grade_table_signals.py",
    "iin_utils.py",
    "build_report.py",
    "build_word_report.py",
    "scraper_logger.py",
]


@pytest.mark.parametrize("module_name", SHARED_MODULES)
def test_canonical_copy_lives_in_mektep_core(module_name):
    assert (REPO_ROOT / "mektep_core" / module_name).exists()


@pytest.mark.parametrize("module_name", SHARED_MODULES)
def test_root_file_is_thin_shim(module_name):
    """Шим в корне — только реэкспорт из mektep_core, без собственной логики."""
    shim = REPO_ROOT / module_name
    text = shim.read_text(encoding="utf-8")
    assert "sys.modules[__name__] = _impl" in text, (
        f"{module_name} в корне должен быть шимом-реэкспортом из mektep_core; "
        "правки кода вносите в mektep_core/"
    )
    assert len(text.splitlines()) < 20, (
        f"{module_name} в корне разросся — похоже, в шим добавили логику. "
        "Код должен жить в mektep_core/"
    )


@pytest.mark.parametrize("module_name", SHARED_MODULES)
def test_no_copy_in_desktop_dir(module_name):
    """build.py больше не копирует модули в mektep-desktop — копий быть не должно."""
    assert not (REPO_ROOT / "mektep-desktop" / module_name).exists(), (
        f"mektep-desktop/{module_name} — дубль; десктоп должен импортировать "
        "mektep_core через pathex/шимы"
    )
