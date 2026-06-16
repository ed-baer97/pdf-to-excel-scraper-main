"""Подготовка os.environ, sys.path, шаблонов и Playwright для запуска scrape_mektep в десктопе."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Tuple

if TYPE_CHECKING:
    from ..api_client import MektepAPIClient


def ensure_std_streams() -> None:
    """Защита от None stdout/stderr в frozen PyInstaller builds (console=False)."""
    if getattr(sys, "frozen", False):
        if sys.stdout is None:
            sys.stdout = open(os.devnull, "w", encoding="utf-8")
        if sys.stderr is None:
            sys.stderr = open(os.devnull, "w", encoding="utf-8")


def compute_import_and_templates_paths() -> Tuple[Path, Path]:
    """
    parent_dir — в sys.path для импорта scrape_mektep;
    templates_src_dir — откуда копировать Шаблон.xlsx/docx (dev или _MEIPASS/templates).
    """
    if getattr(sys, "frozen", False):
        base_dir = Path(sys._MEIPASS)
        templates_src_dir = base_dir / "templates"
        parent_dir = base_dir
    else:
        desktop_dir = Path(__file__).resolve().parent.parent.parent
        parent_dir = desktop_dir.parent
        templates_src_dir = desktop_dir
    return parent_dir, templates_src_dir


def ensure_parent_on_syspath(parent_dir: Path) -> None:
    """Добавляет каталог корня репозитория в начало sys.path для импорта scrape_mektep."""
    if str(parent_dir) not in sys.path:
        sys.path.insert(0, str(parent_dir))


def copy_report_templates_to_temp(
    temp_dir: Path, templates_src_dir: Path, parent_dir: Path, frozen: bool
) -> Path:
    """Копирует шаблоны во временную папку; возвращает путь к каталогу templates."""
    templates_dir = temp_dir / "templates"
    templates_dir.mkdir(parents=True, exist_ok=True)
    for name in ["Шаблон.xlsx", "Шаблон.docx", "Шаблон_каз.docx"]:
        src = templates_src_dir / name
        if not src.exists() and not frozen:
            src = parent_dir / name
        dst = templates_dir / name
        if src.exists() and not dst.exists():
            try:
                shutil.copy2(src, dst)
            except Exception:
                pass
    return templates_dir


def setup_playwright_browsers_path_if_frozen() -> None:
    """В собранном EXE задаёт PLAYWRIGHT_BROWSERS_PATH на %LOCALAPPDATA%\\ms-playwright при наличии папки."""
    if getattr(sys, "frozen", False):
        _local = os.environ.get("LOCALAPPDATA", "")
        _pw_browsers = os.path.join(_local, "ms-playwright")
        if os.path.isdir(_pw_browsers):
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = _pw_browsers


def apply_scraper_env(
    login: str,
    password: str,
    period_code: str,
    lang: str,
    progress_file: Path,
    school_index: str,
    templates_dir: Path,
) -> None:
    """Записывает в окружение параметры скрапера (логин, период, язык, PROGRESS_FILE, шаблоны, школа)."""
    os.environ["MEKTEP_LOGIN"] = login
    os.environ["MEKTEP_PASSWORD"] = password
    os.environ["MEKTEP_PERIOD"] = period_code
    os.environ["MEKTEP_LANG"] = lang
    os.environ["MEKTEP_ALL"] = "1"
    os.environ["PROGRESS_FILE"] = str(progress_file)
    if school_index:
        os.environ["MEKTEP_SCHOOL_INDEX"] = school_index
    elif "MEKTEP_SCHOOL_INDEX" in os.environ:
        del os.environ["MEKTEP_SCHOOL_INDEX"]
    os.environ["MEKTEP_TEMPLATES_DIR"] = str(templates_dir)


def apply_expected_iin_policy(api_client: Optional["MektepAPIClient"], login: str) -> str | None:
    """
    Задаёт MEKTEP_EXPECTED_IIN из API. Возвращает текст ошибки, если логин не совпадает с ИИН.
    """
    if "MEKTEP_EXPECTED_IIN" in os.environ:
        del os.environ["MEKTEP_EXPECTED_IIN"]

    if not api_client or not api_client.is_authenticated():
        return None

    try:
        school_info = api_client.get_my_school()
        if not school_info.get("success"):
            return None
        if school_info.get("iin_missing"):
            return (
                "Администратор школы должен указать ваш ИИН (ЖСН) в карточке учителя — "
                "тот же номер, что для входа на mektep.edu.kz."
            )
        expected = school_info.get("expected_iin")
        if not expected or not str(expected).strip():
            return None
        digits = "".join(c for c in str(login) if c.isdigit())
        exp = str(expected).strip()
        if len(digits) != 12 or digits != exp:
            return (
                "Логин для mektep.edu.kz должен совпадать с вашим ИИН (12 цифр), "
                "указанным администратором в системе."
            )
        os.environ["MEKTEP_EXPECTED_IIN"] = exp
        print(f"[DEBUG] Защита: ожидаемый ИИН задан (проверка логина пройдена)")
        return None
    except Exception as e:
        print(f"[DEBUG] Ошибка при проверке ИИН: {e}")
        return None


def apply_expected_school_policy(api_client: Optional["MektepAPIClient"]) -> None:
    """Защита от передачи аккаунта: список школ учителя из API."""
    for key in ("MEKTEP_EXPECTED_SCHOOL", "MEKTEP_ALLOWED_SCHOOLS"):
        if key in os.environ:
            del os.environ[key]

    if api_client and api_client.is_authenticated():
        try:
            import json

            school_info = api_client.get_my_school()
            if school_info.get("success"):
                _ac = school_info.get("allow_cross_school_reports", True)
                allow_cross = (
                    _ac is True
                    if isinstance(_ac, bool)
                    else str(_ac).lower() not in ("false", "0", "no", "")
                )
                allowed_names = school_info.get("allowed_school_names") or []
                if not allowed_names and school_info.get("school_name"):
                    allowed_names = [school_info.get("school_name")]
                if allowed_names and not allow_cross:
                    os.environ["MEKTEP_ALLOWED_SCHOOLS"] = json.dumps(
                        allowed_names, ensure_ascii=False
                    )
                    print(f"[DEBUG] Защита: разрешённые школы = {allowed_names}")
                else:
                    print("[DEBUG] Защита: cross-school разрешено или школы не назначены")
            else:
                print(
                    f"[DEBUG] Не удалось получить информацию о школе: "
                    f"{school_info.get('error', '?')}"
                )
        except Exception as e:
            print(f"[DEBUG] Ошибка при получении информации о школе: {e}")


def cleanup_stale_output_artifacts(output_dir: Path) -> None:
    """Очистка старых промежуточных папок/файлов из главной директории вывода."""
    if not output_dir.exists():
        return

    temp_items = [
        "batch",
        "reports",
        "templates",
        "before_click.html",
        "before_click.png",
        "before_click.url.txt",
        "after_login.html",
        "after_login.png",
        "after_login.url.txt",
        "grades.html",
        "grades.png",
        "grades.url.txt",
        "grades_table.json",
        "grades_table.csv",
        "criteria.html",
        "criteria.png",
        "criteria.url.txt",
        "criteria_tabs.json",
        "criteria_selected_tab.txt",
        "criteria_students.xlsx",
        "criteria_students.json",
        "criteria_students.csv",
        "criteria_context.json",
        "criteria_max_points.json",
        "org_name.txt",
        "profile_name.txt",
        "period.txt",
        "progress.json",
        "selected_row.json",
        "meta.json",
    ]

    for item_name in temp_items:
        item_path = output_dir / item_name
        try:
            if item_path.is_dir():
                shutil.rmtree(item_path)
            elif item_path.is_file():
                item_path.unlink()
        except Exception:
            pass
