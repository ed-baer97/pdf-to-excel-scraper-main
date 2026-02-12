import argparse
import os
import sys
import getpass
import json
import csv
import re
import time
from pathlib import Path
from urllib.parse import urljoin
from datetime import datetime

from dotenv import load_dotenv
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
from playwright.sync_api import Page

# Импорт логгера
try:
    from scraper_logger import (
        init_logger, get_logger, log_stage, log_info, log_success, 
        log_warning, log_error, ScraperLogger
    )
except ImportError:
    # Fallback если логгер недоступен
    def init_logger(*args, **kwargs): return None
    def get_logger(): return None
    def log_stage(*args, **kwargs): pass
    def log_info(msg): print(f"[INFO] {msg}")
    def log_success(msg): print(f"[SUCCESS] {msg}")
    def log_warning(msg): print(f"[WARNING] {msg}")
    def log_error(msg, exc=None): print(f"[ERROR] {msg}")
    class ScraperLogger:
        STAGE_INIT = "INIT"
        STAGE_BROWSER = "BROWSER"
        STAGE_PAGE_LOAD = "PAGE_LOAD"
        STAGE_LOGIN_FORM = "LOGIN_FORM"
        STAGE_AUTH = "AUTH"
        STAGE_LANGUAGE = "LANGUAGE"
        STAGE_NAVIGATION = "NAVIGATION"
        STAGE_GRADES_TABLE = "GRADES_TABLE"
        STAGE_CRITERIA = "CRITERIA"
        STAGE_STUDENTS = "STUDENTS"
        STAGE_EXCEL_REPORT = "EXCEL_REPORT"
        STAGE_WORD_REPORT = "WORD_REPORT"
        STAGE_COMPLETE = "COMPLETE"
        STAGE_ERROR = "ERROR"

# Fix encoding issues on Windows when printing Unicode characters
if sys.platform == "win32":
    try:
        # Set UTF-8 encoding for stdout and stderr
        if sys.stdout.encoding != "utf-8":
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if sys.stderr.encoding != "utf-8":
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        # Fallback for older Python versions
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

try:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font
    from openpyxl.utils import get_column_letter
except Exception:  # pragma: no cover
    Workbook = None  # type: ignore
    Alignment = None  # type: ignore
    Font = None  # type: ignore
    get_column_letter = None  # type: ignore


URL = "https://mektep.edu.kz/?school=logout&language=rus"
LOGIN_PANEL_SELECTOR = "#collapseThree"

LANG_MAP = {
    "ru": {"label": "Русский", "query": "language=rus"},
    "kk": {"label": "Қазақша", "query": "language=kaz"},
    "en": {"label": "English", "query": "language=eng"},
}

# Import PERIOD_MAP from webapp.constants if available, otherwise define locally
try:
    from webapp.constants import PERIOD_MAP
except ImportError:
    PERIOD_MAP = {
        "1": "1 четверть",
        "2": "2 четверть (1 полугодие)",
        "3": "3 четверть",
        "4": "4 четверть (2 полугодие)",
    }

def _safe_slug(s: str) -> str:
    s = " ".join((s or "").split()).strip()
    s = re.sub(r"[<>:\"/\\\\|?*]+", "_", s)
    s = s.strip(" .")
    return s or "item"


def _update_progress(percent: int, message: str, total_reports: int | None = None, processed_reports: int = 0):
    """Update progress file if PROGRESS_FILE environment variable is set."""
    progress_file = os.getenv("PROGRESS_FILE")
    if progress_file:
        try:
            progress_path = Path(progress_file)
            data = {
                "percent": percent,
                "message": message,
                "total_reports": total_reports,
                "processed_reports": processed_reports,
                "finished": False
            }
            progress_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass  # Silently fail if progress file can't be written


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def _resolve_template_path(name: str) -> Path:
    candidates: list[Path] = []
    env_dir = os.getenv("MEKTEP_TEMPLATES_DIR")
    if env_dir:
        candidates.append(Path(env_dir) / name)
    # PyInstaller one-file/one-dir temp bundle
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "templates" / name)
    # Current working directory
    candidates.append(Path(name))
    # Project root (where this file lives)
    base_dir = Path(__file__).resolve().parent
    candidates.append(base_dir / name)
    # Desktop app folders
    desktop_dir = base_dir / "mektep-desktop"
    candidates.append(desktop_dir / "templates" / name)
    candidates.append(desktop_dir / name)
    # Optional templates folder in root
    candidates.append(base_dir / "templates" / name)

    for c in candidates:
        if c.exists():
            return c
    return candidates[0] if candidates else Path(name)

def _try_click(locator, timeout_ms: int = 1500) -> None:
    try:
        locator.first.click(timeout=timeout_ms)
    except Exception:
        pass


def _click_login_button(page) -> None:
    # Prefer stable attributes from the provided HTML:
    # <button ... data-toggle="collapse" href="#collapseThree" aria-controls="collapseThree">Вход в систему</button>
    candidates = [
        page.locator('button[aria-controls="collapseThree"]'),
        page.locator('button[href="#collapseThree"]'),
        page.locator('button[data-toggle="collapse"][href="#collapseThree"]'),
        page.locator('header button.btn.btn-primary:has-text("Вход в систему")'),
        page.locator('button.btn.btn-primary:has-text("Вход в систему")'),
        page.locator('button:has-text("Вход в систему")'),
    ]

    last_err: Exception | None = None
    for loc in candidates:
        try:
            loc.first.wait_for(state="visible", timeout=10000)
            loc.first.scroll_into_view_if_needed(timeout=5000)
            loc.first.click(timeout=10000)
            return
        except Exception as e:
            last_err = e

    raise RuntimeError("Could not find/click the 'Вход в систему' button") from last_err


def _get_current_language(page) -> str | None:
    btn = page.locator("div.topline .btn-group button.btn.btn-default.dropdown-toggle").first
    try:
        btn.wait_for(state="visible", timeout=7000)
        txt = btn.inner_text().strip()
        # Example: "Қазақша" or "Русский" (may include caret/icon/newlines)
        for v in LANG_MAP.values():
            if v["label"] in txt:
                return v["label"]
        return txt.splitlines()[-1].strip() if txt else None
    except Exception:
        return None


def _ensure_language(page, lang_code: str) -> None:
    desired = LANG_MAP[lang_code]["label"]
    current = _get_current_language(page)
    if current and desired in current:
        print(f"Language already set: {desired}")
        return

    print(f"Switching language to: {desired}")

    # Desktop dropdown
    dropdown_btn = page.locator("div.topline .btn-group button.btn.btn-default.dropdown-toggle").first
    try:
        dropdown_btn.wait_for(state="visible", timeout=7000)
        dropdown_btn.click(timeout=7000)
        page.locator(f'div.topline .dropdown-menu a.dropdown-item[href*="{LANG_MAP[lang_code]["query"]}"]').first.click(
            timeout=7000
        )
        page.wait_for_load_state("domcontentloaded")
        return
    except Exception:
        pass

    # Mobile fallback (direct link)
    page.locator(f'div.mobile_lang a[href*="{LANG_MAP[lang_code]["query"]}"]').first.click(timeout=7000)
    page.wait_for_load_state("domcontentloaded")


def _get_profile_name(page) -> str | None:
    # Example HTML:
    # <div class="profile"> ... <p>Баер<br>Эдуард</p>
    loc = page.locator("nav .profile p").first
    try:
        loc.wait_for(state="visible", timeout=7000)
        txt = loc.inner_text()
        # Normalize whitespace/newlines.
        name = " ".join(txt.split()).strip()
        return name or None
    except Exception:
        return None


def _get_org_name(page) -> str | None:
    # Example HTML:
    # <div class="orgname">...<strong>Специализированный IT лицей</strong>
    loc = page.locator(".topline .orgname strong").first
    try:
        loc.wait_for(state="visible", timeout=7000)
        txt = loc.inner_text()
        name = " ".join((txt or "").split()).strip()
        return name or None
    except Exception:
        return None


def _choose_period() -> tuple[str, str]:
    """
    Returns (period_code, period_label).
    Business rule from user: "2 четверть = 1 полугодие (если нет 2 четверти)".
    We store the choice now; later steps may map it to the site's actual UI.
    """
    chosen = os.getenv("MEKTEP_PERIOD", "").strip()
    if chosen in PERIOD_MAP:
        return chosen, PERIOD_MAP[chosen]

    print("Какую четверть будем извлекать?")
    print("  1 - 1 четверть")
    print("  2 - 2 четверть (1 полугодие, если нет 2 четверти)")
    print("  3 - 3 четверть")
    print("  4 - 4 четверть (2 полугодие)")
    chosen = input("Выбор (1/2/3/4) [2]: ").strip() or "2"
    if chosen not in PERIOD_MAP:
        raise ValueError("Unknown period. Use: 1,2,3,4")
    return chosen, PERIOD_MAP[chosen]


def _go_to_grades(page) -> None:
    # Nav item:
    # <a class="nav-link" href="/office/?action=semester">Оценки</a>
    link = page.locator('a.nav-link[href="/office/?action=semester"]:visible').first
    try:
        link.wait_for(state="visible", timeout=7000)
        link.click(timeout=7000)
    except Exception:
        page.goto("https://mektep.edu.kz/office/?action=semester", wait_until="domcontentloaded")

    page.wait_for_load_state("domcontentloaded")

def _extract_grades_table(page) -> list[dict]:
    """
    Extract rows from the "Успеваемость" table on /office/?action=semester
    We care about: class, subject, criteria_link.
    """
    table = page.locator("table.table.table-hover").first
    table.wait_for(state="visible", timeout=15000)

    rows: list[dict] = []
    trs = table.locator("tbody tr")
    count = trs.count()
    for i in range(count):
        tr = trs.nth(i)
        tds = tr.locator("td")
        
        # Check for very small cells (2x2px) - these indicate problematic rows
        # If such a cell exists and there's no button, skip this row (case 1)
        has_small_cell = False
        td_count = tds.count()
        for j in range(td_count):
            try:
                td = tds.nth(j)
                box = td.bounding_box()
                if box:
                    width = box.get("width", 0)
                    height = box.get("height", 0)
                    # Check if cell is very small (2x2px or similar tiny size)
                    if width <= 3 and height <= 3:
                        has_small_cell = True
                        break
            except Exception:
                pass
        
        # Check if row has criteria button
        criteria_a = tr.locator('a[href*="action=semester2"]').first
        has_button = False
        href = ""
        try:
            if criteria_a.count() > 0:
                has_button = True
                href = criteria_a.get_attribute("href", timeout=1000) or ""
        except Exception:
            pass
        
        # Skip rows with small cells but no button (case 1)
        if has_small_cell and not has_button:
            continue
        
        class_name = " ".join((tds.nth(0).inner_text() or "").split())
        # Subject cell can contain extra muted text like "Обновленное содержание".
        # We only want the <strong>...</strong> text (e.g., "Алгебра").
        subject_strong = tds.nth(1).locator("strong").first
        try:
            subject = " ".join(((subject_strong.inner_text() or "").split()))
        except Exception:
            subject = ""
        if not subject:
            # Fallback: use full cell text but drop muted part if present.
            full = " ".join((tds.nth(1).inner_text() or "").split())
            muted = ""
            try:
                muted = " ".join((tds.nth(1).locator("div.text-muted").first.inner_text() or "").split())
            except Exception:
                muted = ""
            if muted and muted in full:
                full = full.replace(muted, "").strip()
            subject = full

        if not href:
            # Skip rows without criteria link (they can't be opened).
            continue
        rows.append(
            {
                "index": i + 1,
                "class": class_name,
                "subject": subject,
                "criteria_href": href,
                "criteria_url": urljoin(page.url, href) if href else "",
            }
        )

    return rows


def _save_grades_table(rows: list[dict], out_dir: Path) -> None:
    (out_dir / "grades_table.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    csv_path = out_dir / "grades_table.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["index", "class", "subject", "criteria_url"])
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in ["index", "class", "subject", "criteria_url"]})


def _choose_row(rows: list[dict]) -> dict:
    pick = os.getenv("MEKTEP_PICK", "").strip()
    if pick.isdigit():
        idx = int(pick)
        if 1 <= idx <= len(rows):
            return rows[idx - 1]

    print("Доступные строки (класс / предмет):")
    for r in rows:
        print(f'  {r["index"]:>2}. {r["class"]} — {r["subject"]}')
    raw = input(f"Выберите строку (1..{len(rows)}): ").strip()
    if not raw.isdigit():
        raise ValueError("Pick must be a number.")
    idx = int(raw)
    if not (1 <= idx <= len(rows)):
        raise ValueError("Pick out of range.")
    return rows[idx - 1]


def _open_criteria(page, href: str) -> None:
    if not href:
        raise ValueError("Empty criteria link.")
    # Use navigation by click if possible; fallback to goto.
    try:
        page.locator(f'a[href="{href}"]').first.click(timeout=7000)
    except Exception:
        page.goto(urljoin(page.url, href), wait_until="domcontentloaded")
    page.wait_for_load_state("domcontentloaded")


def _check_criteria_warning(page) -> bool:
    """
    Check if criteria page shows warning about missing evaluation data.
    Returns True if warning is found (page should be skipped), False otherwise.
    """
    try:
        # Look for alert warning with text about missing evaluation data
        # Try multiple selectors for robustness
        warning_selectors = [
            'div.alert.alert-warning:has-text("Для начала работы необходимо установить данные оценивания!")',
            'div.alert.alert-warning',
        ]
        
        for selector in warning_selectors:
            warning = page.locator(selector)
            if warning.count() > 0:
                # Check if it's visible and contains the warning text
                for i in range(warning.count()):
                    try:
                        warning_elem = warning.nth(i)
                        if warning_elem.is_visible():
                            text = warning_elem.inner_text()
                            if "Для начала работы необходимо установить данные оценивания!" in text:
                                return True
                    except Exception:
                        continue
    except Exception:
        pass
    return False


def _list_criteria_tabs(page) -> list[dict]:
    tabs = page.locator("ul#pills-tab a[data-toggle='pill']")
    out: list[dict] = []
    n = tabs.count()
    for i in range(n):
        a = tabs.nth(i)
        href = (a.get_attribute("href") or "").strip()
        text = " ".join((a.inner_text() or "").split())
        out.append({"text": text, "href": href})
    return [t for t in out if t["href"].startswith("#")]


def _click_criteria_tab(page, href: str) -> None:
    # href like "#chetvert_2"
    page.locator(f'ul#pills-tab a[data-toggle="pill"][href="{href}"]').first.click(timeout=7000)
    # Wait until the corresponding pane is shown (Bootstrap adds 'show' + 'active').
    pane_id = href.lstrip("#")
    pane = page.locator(f"div.tab-content div.tab-pane#{pane_id}").first
    pane.wait_for(state="visible", timeout=15000)
    try:
        page.wait_for_selector(f"div.tab-content div.tab-pane#{pane_id}.show", timeout=15000)
    except Exception:
        # Some pages render panes visible without 'show' toggling consistently.
        pass


def _count_tab_rows(page, href: str) -> int:
    pane_id = href.lstrip("#")
    pane = page.locator(f"div.tab-content div.tab-pane#{pane_id}").first
    # Count data rows in the first table inside the pane.
    table = pane.locator("table").first
    try:
        table.wait_for(state="visible", timeout=3000)
    except Exception:
        return 0
    return table.locator("tbody tr").count()


def _pick_tab_href_for_period(period_code: str, tabs: list[dict]) -> str | None:
    """
    Map our period selection to an existing tab.
    Special rule: if period_code == '2' and '#chetvert_2' doesn't exist, fall back to '1 полугодие' tab (if present).
    """
    hrefs = {t["href"] for t in tabs}
    texts = {t["href"]: t["text"] for t in tabs}

    if period_code in {"1", "2", "3"}:
        direct = f"#chetvert_{period_code}"
        if direct in hrefs:
            return direct

    # Period 4 could be either 4th quarter or "2 полугодие" depending on school settings.
    if period_code == "4":
        if "#chetvert_4" in hrefs:
            return "#chetvert_4"
        # Fallback by label:
        for href, txt in texts.items():
            if "2 полугод" in txt.lower():
                return href

    if period_code == "2":
        # Fallback to "1 полугодие" if 2nd quarter is absent.
        for href, txt in texts.items():
            if "1 полугод" in txt.lower():
                return href

    # Fallback by matching quarter number in text.
    desired_label = PERIOD_MAP.get(period_code, "")
    desired_num = desired_label.split()[0] if desired_label else ""
    if desired_num:
        for href, txt in texts.items():
            if desired_num in txt:
                return href

    return tabs[0]["href"] if tabs else None


def _analyze_and_select_criteria_tabs(page, out_dir: Path, period_code: str) -> str | None:
    tabs = _list_criteria_tabs(page)
    if not tabs:
        (out_dir / "criteria_tabs.json").write_text(json.dumps([], ensure_ascii=False, indent=2), encoding="utf-8")
        return None

    # Check each tab for content (row counts).
    report: list[dict] = []
    for t in tabs:
        href = t["href"]
        try:
            _click_criteria_tab(page, href)
        except Exception:
            report.append({**t, "rows": 0, "click_error": True})
            continue
        report.append({**t, "rows": _count_tab_rows(page, href)})

    (out_dir / "criteria_tabs.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # Select the desired period tab (with fallback rules).
    desired_href = _pick_tab_href_for_period(period_code, tabs)
    if desired_href:
        print(f"Selecting period tab: {desired_href}")
        _click_criteria_tab(page, desired_href)
        (out_dir / "criteria_selected_tab.txt").write_text(desired_href, encoding="utf-8")
        return desired_href

    return None


def _get_active_criteria_tab_href(page) -> str | None:
    a = page.locator('ul#pills-tab a[data-toggle="pill"].active').first
    try:
        if a.count() == 0:
            return None
        href = (a.get_attribute("href") or "").strip()
        return href if href.startswith("#") else None
    except Exception:
        return None


def _text_or_none(locator) -> str | None:
    try:
        if locator.count() == 0:
            return None
        txt = locator.first.inner_text()
        txt = " ".join((txt or "").split()).strip()
        return txt or None
    except Exception:
        return None


def _extract_students_from_criteria_tab(page, tab_href: str) -> list[dict]:
    pane_id = tab_href.lstrip("#")
    pane = page.locator(f"div#pills-tabContent div.tab-pane#{pane_id}").first
    pane.wait_for(state="visible", timeout=15000)

    # Determine quarter_num from tab id (#chetvert_N)
    quarter_num = 0
    try:
        quarter_num = int(pane_id.split("_")[1])
    except Exception:
        quarter_num = 0

    # Try to find table by grade cell first (preferred method)
    first_grade = pane.locator('p[id^="ocenka_"]').first
    table = None
    
    try:
        first_grade.wait_for(state="visible", timeout=7000)
        grade_id = (first_grade.get_attribute("id") or "").strip()
        # Example grade id: ocenka_0_chetvert_2  -> row_idx=0, quarter_num=2
        try:
            # ocenka_{row}_chetvert_{q}
            parts = grade_id.split("_")
            if len(parts) >= 4 and parts[0] == "ocenka" and parts[2] == "chetvert":
                quarter_num = int(parts[3])  # Override with actual quarter from grade id
        except Exception:
            pass
        
        table = first_grade.locator("xpath=ancestor::table[1]")
        table.wait_for(state="visible", timeout=15000)
    except Exception:
        # Fallback: try to find table directly by structure
        # Table is usually inside form within the tab pane
        try:
            # Try to find table with student data (has tbody with rows)
            tables = pane.locator("table.table tbody tr")
            if tables.count() > 0:
                # Get the first table that has rows
                table = tables.first.locator("xpath=ancestor::table[1]")
                table.wait_for(state="visible", timeout=5000)
            else:
                # Try alternative: find table inside form
                form_table = pane.locator("form table, table.table")
                if form_table.count() > 0:
                    table = form_table.first
                    table.wait_for(state="visible", timeout=5000)
        except Exception:
            print(f"Warning: Could not find students table in tab {tab_href}")
            return []
    
    if table is None:
        return []

    trs = table.locator("tbody tr, tr")
    out: list[dict] = []
    n = trs.count()
    
    if n == 0:
        print(f"Warning: No table rows found in tab {tab_href}")
        return []
    
    for i in range(n):
        tr = trs.nth(i)

        tds = tr.locator("td")
        if tds.count() < 2:
            continue

        num_txt = " ".join((tds.nth(0).inner_text() or "").split()).strip()
        fio_txt = " ".join((tds.nth(1).inner_text() or "").split()).strip()
        
        # Skip header rows or rows without valid student number
        if not num_txt.isdigit():
            continue

        # Try to find grade cell - may not exist for all subjects
        grade_loc = tr.locator(f'p[id^="ocenka_"][id$="_chetvert_{quarter_num}"]')
        row_index = None
        
        if grade_loc.count() > 0:
            # Row index comes from the grade id: ocenka_{row}_chetvert_{q}
            gid = (grade_loc.first.get_attribute("id") or "").strip()
            try:
                gid_parts = gid.split("_")
                row_index = int(gid_parts[1]) if len(gid_parts) >= 4 else None
            except Exception:
                row_index = None
        else:
            # Fallback: use row index from table position
            # This works when grade cells don't have the expected ID pattern
            row_index = i

        # Try to extract data using IDs first, then fallback to cell positions
        average_val = None
        formative_pct_val = None
        sor_pct_val = None
        soch_pct_val = None
        total_pct_val = None
        grade_val = None
        
        if row_index is not None:
            # Try ID-based extraction
            average_val = _text_or_none(tr.locator(f"p#average_{quarter_num}_chetvert_{row_index}"))
            formative_pct_val = _text_or_none(tr.locator(f"p#average_itog_{quarter_num}_chetvert_{row_index}"))
            sor_pct_val = _text_or_none(tr.locator(f"p#sor_{row_index}_chetvert_{quarter_num}"))
            soch_pct_val = _text_or_none(tr.locator(f"p#soch_{row_index}_chetvert_{quarter_num}"))
            total_pct_val = _text_or_none(tr.locator(f"p#summa_{row_index}_chetvert_{quarter_num}"))
            if grade_loc.count() > 0:
                grade_val = _text_or_none(grade_loc)
        
        # Fallback: extract from cell positions if IDs didn't work
        # Typically: №, ФИО, average, sections..., formative%, sor%, soch%, total%, grade
        td_count = tds.count()
        
        # Collect all cell texts for analysis
        all_cells = []
        for j in range(td_count):
            cell_text = " ".join((tds.nth(j).inner_text() or "").split()).strip()
            all_cells.append(cell_text)
        
        # Try to extract data from cell positions
        # Structure varies, but typically: №, ФИО, [sections with scores], average, percentages, grade
        if average_val is None or not any([formative_pct_val, sor_pct_val, soch_pct_val, total_pct_val]):
            # Look for numeric values and percentages in cells
            for j in range(2, td_count):
                cell_text = all_cells[j]
                if not cell_text:
                    continue
                
                # Check if it's a decimal number (likely average)
                try:
                    float_val = float(cell_text.replace(",", "."))
                    if average_val is None and 0 <= float_val <= 20:  # Average is usually 0-20
                        average_val = cell_text
                        continue
                except (ValueError, AttributeError):
                    pass
                
                # Check for percentages
                if "%" in cell_text:
                    # Try to determine which percentage it is based on position
                    # Usually: formative%, sor%, soch%, total% (in that order)
                    if not formative_pct_val:
                        formative_pct_val = cell_text
                    elif not sor_pct_val:
                        sor_pct_val = cell_text
                    elif not soch_pct_val:
                        soch_pct_val = cell_text
                    elif not total_pct_val:
                        total_pct_val = cell_text
        
        # Try to find grade in last cells
        if grade_val is None and td_count > 0:
            # Grade is usually in one of the last 1-3 cells
            for j in range(max(0, td_count - 3), td_count):
                cell_text = all_cells[j]
                if cell_text.isdigit() and 1 <= int(cell_text) <= 5:
                    grade_val = cell_text
                    break
                # Also check for grade in text format
                if cell_text in ["1", "2", "3", "4", "5"]:
                    grade_val = cell_text
                    break
        
        data = {
            "num": int(num_txt),
            "fio": fio_txt,
            "quarter_num": quarter_num,
            "average": average_val or "",
            "formative_pct": formative_pct_val or "",
            "sor_pct": sor_pct_val or "",
            "soch_pct": soch_pct_val or "",
            "total_pct": total_pct_val or "",
            "grade": grade_val or "",
        }

        # Raw cell texts (useful because number of sections (СОР/СОч) can vary).
        raw_cells: list[str] = []
        td_count = tds.count()
        for j in range(td_count):
            raw_cells.append(" ".join((tds.nth(j).inner_text() or "").split()).strip())
        data["raw_cells"] = raw_cells

        # Per-section points are often stored in inputs with ids like chetvert_{q}_razdel_{k}_{rowIndex}
        inputs = tr.locator(f'input[id^="chetvert_{quarter_num}_razdel_"]')
        inp_n = inputs.count()
        points: dict[str, str] = {}
        for k in range(inp_n):
            inp = inputs.nth(k)
            inp_id = inp.get_attribute("id") or ""
            inp_val = inp.input_value() if inp_id else ""
            if inp_id:
                points[inp_id] = inp_val
        data["points"] = points

        out.append(data)

    return out


def _extract_quarter_max_points(page: Page, tab_href: str) -> dict[int, int]:
    """
    Extract max points for each section (razdel) from the header inputs:
    input id="chetvert_{q}_razdel_{k}_max" value="..."
    """
    pane_id = tab_href.lstrip("#")
    pane = page.locator(f"div#pills-tabContent div.tab-pane#{pane_id}").first

    # Prefer quarter number from actual input IDs (more reliable than pane id naming).
    inputs_any = pane.locator('input[id^="chetvert_"][id*="_razdel_"][id$="_max"]')
    if inputs_any.count() == 0:
        return {}

    # Infer quarter_num from first input id: chetvert_{q}_razdel_{k}_max
    first_id = (inputs_any.first.get_attribute("id") or "").strip()
    quarter_num = None
    try:
        parts = first_id.split("_")
        if len(parts) >= 5 and parts[0] == "chetvert":
            quarter_num = int(parts[1])
    except Exception:
        quarter_num = None
    if quarter_num is None:
        return {}

    inputs = pane.locator(f'input[id^="chetvert_{quarter_num}_razdel_"][id$="_max"]')
    n = inputs.count()
    out: dict[int, int] = {}
    for i in range(n):
        inp = inputs.nth(i)
        inp_id = (inp.get_attribute("id") or "").strip()
        val = (inp.input_value() or "").strip()
        # chetvert_2_razdel_1_max -> section=1
        parts = inp_id.split("_")
        if len(parts) >= 5 and parts[0] == "chetvert" and parts[2] == "razdel":
            try:
                section = int(parts[3])
                out[section] = int(float(val)) if val else out.get(section, 0)
            except Exception:
                continue
    return out


def _parse_points_by_section(points: dict[str, str], quarter_num: int) -> dict[int, str]:
    """
    From ids like chetvert_{q}_razdel_{k}_{rowIndex} -> {k: value}
    """
    out: dict[int, str] = {}
    prefix = f"chetvert_{quarter_num}_razdel_"
    for k, v in points.items():
        if not k.startswith(prefix):
            continue
        parts = k.split("_")
        # ["chetvert", q, "razdel", k, rowIndex]
        if len(parts) >= 5 and parts[2] == "razdel":
            try:
                section = int(parts[3])
            except Exception:
                continue
            out[section] = v
    return out


def _export_students_xlsx(
    out_dir: Path,
    students: list[dict],
    ctx: dict,
    max_points: dict[int, int],
) -> None:
    if Workbook is None:
        print("openpyxl not installed; skipping XLSX export.")
        return

    wb = Workbook()
    ws = wb.active
    ws.title = "students"
    meta = wb.create_sheet("context")

    # Determine quarter number from first row.
    quarter_num = int(students[0].get("quarter_num", 0) or 0) if students else 0

    # Determine which sections exist in points across all students.
    sections: set[int] = set()
    for s in students:
        pts = s.get("points") or {}
        if isinstance(pts, dict):
            for sid in _parse_points_by_section(pts, quarter_num).keys():
                sections.add(sid)
    section_list = sorted(sections)

    def section_label(sec: int) -> str:
        if sec == 0:
            return "СОч"
        return f"СОр {sec}"

    headers = [
        "№",
        "ФИО",
        "Формативная (среднее)",
        *[section_label(sec) for sec in section_list],
        "% ФО",
        "% СОр",
        "% СОч",
        "Итог %",
        "Оценка",
    ]

    ws.append(headers)
    # Row 2: max points for section columns (instead of embedding it into header text)
    max_row = [""] * len(headers)
    max_row[1] = "Макс."
    sec_start_idx = 3  # 0-based; after №, ФИО, average
    for i, sec in enumerate(section_list):
        mp = max_points.get(sec)
        if mp is not None:
            max_row[sec_start_idx + i] = mp
    ws.append(max_row)

    ws.freeze_panes = "A3"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}1"

    # Style header
    for c in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=c)
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for c in range(1, len(headers) + 1):
        cell = ws.cell(row=2, column=c)
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for s in students:
        pts = s.get("points") or {}
        sec_points = _parse_points_by_section(pts, quarter_num) if isinstance(pts, dict) else {}
        row = [
            s.get("num", ""),
            s.get("fio", ""),
            s.get("average", ""),
            *[sec_points.get(sec, "") for sec in section_list],
            s.get("formative_pct", ""),
            s.get("sor_pct", ""),
            s.get("soch_pct", ""),
            s.get("total_pct", ""),
            s.get("grade", ""),
        ]
        ws.append(row)

    # Basic column widths
    widths = {
        1: 5,
        2: 28,
        3: 18,
    }
    for i in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(i)].width = widths.get(i, 14)

    # Context sheet
    meta.append(["generated_at", datetime.now().isoformat(timespec="seconds")])
    for k in [
        "org_name",
        "profile_name",
        "class",
        "subject",
        "period_code",
        "period_label",
        "selected_tab",
        "criteria_url",
    ]:
        meta.append([k, ctx.get(k, "")])

    xlsx_path = out_dir / "criteria_students.xlsx"
    wb.save(xlsx_path)
    print(f"Saved: {xlsx_path}")


def run(headless: bool, out_dir: Path, slow_mo_ms: int) -> int:
    _ensure_dir(out_dir)
    
    # Инициализация логгера
    logger = init_logger(out_dir, os.getenv("PROGRESS_FILE"))
    log_stage(ScraperLogger.STAGE_INIT, "Инициализация скрапера", 1)
    log_info(f"Директория вывода: {out_dir}")
    log_info(f"Режим: {'headless' if headless else 'с отображением браузера'}")

    login = os.getenv("MEKTEP_LOGIN") or ""
    password = os.getenv("MEKTEP_PASSWORD") or ""
    
    if login:
        log_info(f"Логин: {login[:3]}***")
    else:
        log_warning("Логин не указан в переменных окружения")

    with sync_playwright() as p:
        log_stage(ScraperLogger.STAGE_BROWSER, "Запуск браузера Chromium", 2)
        browser = p.chromium.launch(headless=headless, slow_mo=slow_mo_ms)
        context = browser.new_context(locale="ru-RU")
        page = context.new_page()
        log_success("Браузер запущен успешно")

        log_stage(ScraperLogger.STAGE_PAGE_LOAD, f"Загрузка страницы: {URL}", 3)
        try:
            page.goto(URL, wait_until="load", timeout=60000)
            log_success("Страница загружена")
        except Exception as e:
            log_error("Ошибка загрузки страницы", e)
            log_info("Возможные причины:")
            log_info("  - Проблемы с интернет-соединением")
            log_info("  - Сайт mektep.edu.kz недоступен или перегружен")
            log_info("  - Превышено время ожидания ответа сервера")
            if logger:
                logger.finish(success=False)
            raise
        page.wait_for_load_state("domcontentloaded")

        # Best-effort dismiss of any popups/modals that can block clicks.
        _try_click(page.locator("button:has-text('×')"))
        _try_click(page.locator("[aria-label='Close']"))

        log_stage(ScraperLogger.STAGE_LOGIN_FORM, "Открытие формы входа", 4)
        # Debug artifacts before clicking (useful if selector fails due to unexpected content).
        (out_dir / "before_click.url.txt").write_text(page.url, encoding="utf-8")
        (out_dir / "before_click.html").write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(out_dir / "before_click.png"), full_page=True)
        log_info("Сохранён скриншот: before_click.png")

        log_info("Нажатие кнопки 'Вход в систему'...")
        _click_login_button(page)
        log_success("Кнопка нажата")

        # Wait for the collapsed section to expand and reveal the login form.
        log_info("Ожидание раскрытия формы входа...")
        try:
            page.wait_for_selector(f"{LOGIN_PANEL_SELECTOR}.show", timeout=15000)
            log_success("Форма входа открыта")
        except Exception as e:
            log_error("Не удалось открыть форму входа", e)
            if logger:
                logger.finish(success=False)
            return 2
        panel = page.locator(LOGIN_PANEL_SELECTOR)

        log_info("Поиск полей ввода логина и пароля...")
        login_input = panel.locator(
            'input[name="usr_login"]:visible, input[name*="usr_login" i]:visible, input[name*="login" i]:visible, input[name*="iin" i]:visible, input[type="text"]:visible'
        ).first
        password_input = panel.locator(
            'input[name="usr_password"]:visible, input#password:visible, input[name*="pass" i]:visible, input[type="password"]:visible'
        ).first

        try:
            login_input.wait_for(state="visible", timeout=15000)
            password_input.wait_for(state="visible", timeout=15000)
            log_success("Поля ввода найдены")
        except Exception as e:
            log_error("Не найдены поля логина/пароля", e)
            if logger:
                logger.finish(success=False)
            return 2

        # Check credentials before attempting login
        all_mode = os.getenv("MEKTEP_ALL", "") == "1"
        headless_mode = headless
        
        # In headless/batch mode, don't ask for credentials interactively
        if not login or not password:
            if headless_mode or all_mode:
                log_error("Логин или пароль не указаны")
                if logger:
                    logger.finish(success=False)
                return 2
            # Only ask interactively if not in headless mode
            if not login:
                login = input("Логин или ИИН: ").strip()
            if not password:
                password = getpass.getpass("Пароль: ")
            if not login or not password:
                log_error("Логин или пароль пустые")
                if logger:
                    logger.finish(success=False)
                return 2
        
        # Single login attempt - if it fails, exit immediately
        log_stage(ScraperLogger.STAGE_AUTH, "Авторизация на сайте", 5)
        log_info(f"Ввод логина: {login[:3]}***")
        try:
            login_input.click()
            login_input.press("Control+A")
            login_input.type(login, delay=20)
            log_info("Логин введён")

            password_input.click()
            password_input.press("Control+A")
            password_input.type(password, delay=20)
            log_info("Пароль введён")

            log_info("Отправка формы авторизации...")
            panel.locator("form button[type='submit'], form input[type='submit']").first.click(timeout=10000)
            page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception as e:
            log_error("Ошибка при вводе данных или отправке формы", e)
            if logger:
                logger.finish(success=False)
            return 4

        # Wait for login to process
        log_info("Ожидание обработки авторизации (3 сек)...")
        time.sleep(3)
        
        # Scenario 2 & 3 Combined: Check for role/school selection dialog
        # If there are multiple "Войти как учитель" buttons, it means multiple schools
        log_info("Проверка наличия окна выбора роли/школы...")
        try:
            # Wait longer and explicitly check for buttons
            time.sleep(2)
            
            # Look for all role/school selection buttons by attributes (works for any language)
            # This selector finds buttons with name="account_choice" and value="true"
            # These buttons can have text "Войти как учитель" (RU) or "Мұғалім ретінде кіру" (KZ)
            # We filter by text containing "учитель" or "Мұғалім" to exclude other buttons like "Exit"
            all_buttons = page.locator('button[name="account_choice"][value="true"]')
            
            # Filter buttons that contain teacher-related text
            school_buttons_list = []
            for i in range(all_buttons.count()):
                btn = all_buttons.nth(i)
                btn_text = btn.inner_text().strip().lower()
                if 'учитель' in btn_text or 'мұғалім' in btn_text:
                    school_buttons_list.append(btn)
            
            button_count = len(school_buttons_list)
            log_info(f"Найдено кнопок выбора роли/школы (учитель): {button_count}")
            
            # Debug: show button texts if found
            if button_count > 0:
                try:
                    first_button_text = school_buttons_list[0].inner_text().strip()
                    log_info(f"Текст первой кнопки: '{first_button_text}'")
                except:
                    pass
            elif button_count == 0:
                # Дополнительная отладка: если не нашли, сохраняем файлы
                log_warning("Кнопки выбора не найдены, сохраняем отладочные файлы...")
                try:
                    page.screenshot(path=str(out_dir / "school_selection_not_found.png"))
                    (out_dir / "school_selection_not_found.html").write_text(page.content(), encoding="utf-8")
                    log_info("Сохранены файлы отладки: school_selection_not_found.png/html")
                except:
                    pass
            
            if button_count == 1:
                # Only one "Войти как учитель" button - simple role selection
                log_info("Обнаружено окно выбора роли (учитель/родитель)")
                school_buttons_list[0].click()
                log_success("Выбрана роль: Учитель")
                time.sleep(2)
            elif button_count > 1:
                # Multiple "Войти как учитель" buttons - teacher works at multiple schools
                log_info(f"Обнаружено окно выбора школы. Доступно школ: {button_count}")
                
                # Get school names
                school_list = []
                for i in range(button_count):
                    try:
                        btn = school_buttons_list[i]
                        # Try multiple ways to find school name
                        school_name = None
                        
                        # Method 1: Look for <small> in parent form
                        try:
                            parent_form = btn.locator('xpath=ancestor::form')
                            school_name_elem = parent_form.locator('p small, small').first
                            school_name = school_name_elem.inner_text().strip()
                        except:
                            pass
                        
                        # Method 2: Look for <small> as next sibling
                        if not school_name:
                            try:
                                school_name_elem = btn.locator('xpath=following-sibling::*[1]//small, xpath=following-sibling::small')
                                if school_name_elem.count() > 0:
                                    school_name = school_name_elem.first.inner_text().strip()
                            except:
                                pass
                        
                        # Method 3: Default naming
                        if not school_name:
                            school_name = f"Школа {i+1}"
                    except Exception as e:
                        log_warning(f"Ошибка получения названия школы {i}: {e}")
                        school_name = f"Школа {i+1}"
                    
                    school_list.append(school_name)
                    log_info(f"  {i}: {school_name}")
                
                # Check if we have environment variable first (for backwards compatibility)
                chosen_school_idx_str = os.getenv("MEKTEP_SCHOOL_INDEX", "").strip()
                chosen_school_idx = None
                
                if chosen_school_idx_str and chosen_school_idx_str.isdigit():
                    # Use environment variable
                    chosen_school_idx = int(chosen_school_idx_str)
                    if 0 <= chosen_school_idx < button_count:
                        log_success(f"Используется предустановленный выбор школы #{chosen_school_idx}")
                    else:
                        log_warning(f"Неверный индекс школы {chosen_school_idx}, требуется выбор пользователя")
                        chosen_school_idx = None
                
                if chosen_school_idx is None:
                    # No environment variable - request user selection via progress file
                    log_info("Ожидание выбора школы пользователем...")
                    _update_progress(5, f"schools_selection_needed|{json.dumps(school_list, ensure_ascii=False)}")
                    time.sleep(2)  # Даём время UI получить сообщение
                    _update_progress(5, "Ожидание выбора школы...")  # Очищаем специальное сообщение
                    
                    # Wait for user selection (with timeout)
                    school_choice_file = out_dir / "school_choice.txt"
                    if school_choice_file.exists():
                        school_choice_file.unlink()  # Remove old choice if exists
                    
                    timeout = 60  # 60 seconds timeout
                    start_time = time.time()
                    
                    while time.time() - start_time < timeout:
                        if school_choice_file.exists():
                            try:
                                file_content = school_choice_file.read_text(encoding="utf-8").strip()
                                chosen_school_idx = int(file_content)
                                log_info(f"Прочитан файл выбора: индекс {chosen_school_idx}")
                                if 0 <= chosen_school_idx < button_count:
                                    log_success(f"Получен выбор пользователя: школа #{chosen_school_idx}")
                                    school_choice_file.unlink()  # Удаляем файл после использования
                                    break
                                else:
                                    log_warning(f"Неверный индекс в файле выбора: {chosen_school_idx}")
                                    chosen_school_idx = None
                                    school_choice_file.unlink()  # Удаляем некорректный файл
                            except Exception as e:
                                log_warning(f"Ошибка чтения файла выбора: {e}")
                                chosen_school_idx = None
                            
                            if chosen_school_idx is not None:
                                break
                        
                        time.sleep(0.5)  # Проверяем каждые 0.5 секунды
                        
                        time.sleep(0.5)
                    
                    # If timeout or no valid selection, use first school
                    if chosen_school_idx is None:
                        chosen_school_idx = 0
                        log_warning(f"Выбор не получен за {timeout} секунд, используется первая школа автоматически")
                
                # Click selected school button
                school_buttons_list[chosen_school_idx].click()
                log_success(f"Выбрана школа: {school_list[chosen_school_idx]}")
                
                time.sleep(2)  # Wait for school selection to process
            else:
                # button_count == 0, no role/school selection needed
                log_info("Окно выбора роли/школы не обнаружено (стандартный вход)")
                
        except Exception as e:
            # No role/school selection dialog - that's fine, continue normally
            log_info(f"Окно выбора роли/школы не обнаружено: {e}")
        
        # Check if login was successful
        log_info("Проверка результата авторизации...")
        try:
            page.locator("nav .profile p, .topline .profile, .user-profile").first.wait_for(state="visible", timeout=10000)
            log_success("Авторизация успешна!")
        except Exception:
            # Login failed - check if we're still on login page
            page_content = page.content().lower()
            if "неверн" in page_content or "ошибк" in page_content or LOGIN_PANEL_SELECTOR in page.content():
                log_error("Неверный логин или пароль")
                if logger:
                    logger.finish(success=False)
                return 4
            else:
                # Unexpected state, but might be success - try one more check
                log_warning("Неопределённое состояние, повторная проверка...")
                time.sleep(2)
                try:
                    page.locator("nav .profile p, .topline .profile").first.wait_for(state="visible", timeout=5000)
                    log_success("Авторизация успешна (повторная проверка)")
                except Exception:
                    log_error("Неверный логин или пароль (повторная проверка)")
                    if logger:
                        logger.finish(success=False)
                    return 4

        # ============================================================
        # Определяем целевой язык отчётов
        # ============================================================
        chosen = os.getenv("MEKTEP_LANG", "").strip().lower()
        if chosen not in LANG_MAP:
            if headless or all_mode:
                chosen = "ru"
            else:
                chosen = input("Язык данных (ru/kk/en) [ru]: ").strip().lower() or "ru"
        if chosen not in LANG_MAP:
            log_error(f"Неизвестный язык: {chosen}")
            if logger:
                logger.finish(success=False)
            return 2

        # ============================================================
        # Читаем org_name СТРОГО НА РУССКОЙ СТРАНИЦЕ.
        # После выбора школы язык может быть любым (казахский/русский).
        # Принудительно переключаем на русский, читаем название,
        # затем переключаем на целевой язык для скрапинга.
        # ============================================================
        log_stage(ScraperLogger.STAGE_LANGUAGE, "Настройка языка интерфейса", 6)
        current_lang = _get_current_language(page)
        log_info(f"Текущий язык после авторизации: {current_lang or 'не определён'}")

        # Принудительно переключаем на русский для чтения org_name
        log_info("Переключение на русский для чтения названия организации...")
        _ensure_language(page, "ru")

        org_name_ru = _get_org_name(page)
        if org_name_ru:
            (out_dir / "org_name_ru.txt").write_text(org_name_ru, encoding="utf-8")
            log_info(f"Организация (рус): {org_name_ru}")
        else:
            log_warning("Название организации (рус) не найдено")

        # ===== Проверка организации (защита от передачи аккаунта) =====
        # MEKTEP_EXPECTED_SCHOOL передаётся из scraper_runner.py / десктоп-приложения
        # и содержит название школы, к которой привязан аккаунт в БД.
        expected_school = os.getenv("MEKTEP_EXPECTED_SCHOOL", "").strip()
        if expected_school and org_name_ru:
            a = " ".join(org_name_ru.lower().split())
            b = " ".join(expected_school.lower().split())
            if a != b and a not in b and b not in a:
                log_error(
                    f"Организация «{org_name_ru}» не совпадает с вашей школой «{expected_school}». "
                    f"Создание отчётов для других школ запрещено."
                )
                _update_progress(0, f"Организация «{org_name_ru}» не совпадает с «{expected_school}».")
                context.close()
                browser.close()
                if logger:
                    logger.finish(success=False)
                return 5  # Код ошибки: несовпадение организации
        elif expected_school and not org_name_ru:
            log_warning("Не удалось прочитать название организации — проверка пропущена")

        # Save profile (teacher) name
        profile_name = _get_profile_name(page)
        if profile_name:
            (out_dir / "profile_name.txt").write_text(profile_name, encoding="utf-8")
            log_info(f"Профиль: {profile_name}")
        else:
            log_warning("Имя профиля не найдено")

        # Переключаем на целевой язык отчётов
        log_info(f"Установка языка отчётов: {LANG_MAP[chosen]['label']}")
        _ensure_language(page, chosen)
        log_success(f"Язык установлен: {LANG_MAP[chosen]['label']}")

        # Save org name on target language (for report filenames/content)
        org_name = _get_org_name(page)
        if org_name:
            (out_dir / "org_name.txt").write_text(org_name, encoding="utf-8")
            log_info(f"Организация: {org_name}")
        else:
            org_name = org_name_ru
            if org_name:
                (out_dir / "org_name.txt").write_text(org_name, encoding="utf-8")
            log_warning("Название организации на текущем языке не найдено, использовано русское")

        # Choose quarter/period for future extraction steps.
        try:
            period_code, period_label = _choose_period()
        except ValueError as e:
            log_error(str(e))
            if logger:
                logger.finish(success=False)
            return 2
        (out_dir / "period.txt").write_text(period_label, encoding="utf-8")
        log_info(f"Выбранный период: {period_label}")

        # Go to "Оценки" section.
        log_stage(ScraperLogger.STAGE_NAVIGATION, "Переход в раздел 'Оценки'", 7)
        _update_progress(10, "Авторизация завершена, переход к оценкам...")
        _go_to_grades(page)
        log_success("Раздел 'Оценки' открыт")

        # Artifacts after navigation to grades.
        (out_dir / "grades.url.txt").write_text(page.url, encoding="utf-8")
        (out_dir / "grades.html").write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(out_dir / "grades.png"), full_page=True)
        log_info("Сохранён скриншот: grades.png")

        def process_one(selected: dict, batch_subdir: Path) -> None:
            _ensure_dir(batch_subdir)
            legacy = os.getenv("MEKTEP_LEGACY_FILES", "") == "1"
            (batch_subdir / "selected_row.json").write_text(json.dumps(selected, ensure_ascii=False, indent=2), encoding="utf-8")
            # Single metadata file instead of multiple txt files
            meta = {
                "org_name": org_name,
                "profile_name": profile_name,
                "period_code": period_code,
                "period_label": period_label,
                "class": selected.get("class"),
                "subject": selected.get("subject"),
                "criteria_href": selected.get("criteria_href"),
            }
            (batch_subdir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            if legacy:
                (batch_subdir / "period.txt").write_text(period_label, encoding="utf-8")
                if org_name:
                    (batch_subdir / "org_name.txt").write_text(org_name, encoding="utf-8")
                if profile_name:
                    (batch_subdir / "profile_name.txt").write_text(profile_name, encoding="utf-8")
                (batch_subdir / "subject.txt").write_text(str(selected.get("subject", "")).strip(), encoding="utf-8")

            class_name = selected.get("class", "Unknown")
            subject_name = selected.get("subject", "Unknown")
            log_stage(ScraperLogger.STAGE_CRITERIA, f"Открытие критериев: {class_name} - {subject_name}", None)
            log_info(f'[{class_name} - {subject_name}] Открытие критериев...')
            _open_criteria(page, selected["criteria_href"])
            
            # Wait a bit for page to fully render (especially for dynamic warnings)
            time.sleep(1)
            
            # Check for warning about missing evaluation data (case 2)
            if _check_criteria_warning(page):
                log_warning(f'[{class_name} - {subject_name}] Обнаружено предупреждение: "Для начала работы необходимо установить данные оценивания!" - пропуск страницы.')
                return
            
            log_success(f'[{class_name} - {subject_name}] Критерии открыты')

            log_info(f'[{class_name} - {subject_name}] Выбор вкладки периода...')
            selected_tab = _analyze_and_select_criteria_tabs(page, batch_subdir, period_code) or _get_active_criteria_tab_href(page)
            if not selected_tab:
                log_error(f'[{class_name} - {subject_name}] Не удалось определить вкладку критериев, пропуск.')
                return
            log_info(f'[{class_name} - {subject_name}] Вкладка выбрана: {selected_tab}')

            log_stage(ScraperLogger.STAGE_STUDENTS, f"Извлечение учащихся: {class_name}", None)
            log_info(f'[{class_name} - {subject_name}] Извлечение данных учащихся...')
            students = _extract_students_from_criteria_tab(page, selected_tab)
            students_count = len(students)
            log_success(f'[{class_name} - {subject_name}] Найдено учащихся: {students_count}')
            (batch_subdir / "criteria_students.json").write_text(json.dumps(students, ensure_ascii=False, indent=2), encoding="utf-8")
            with (batch_subdir / "criteria_students.csv").open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(
                    f,
                    fieldnames=["num", "fio", "quarter_num", "average", "formative_pct", "sor_pct", "soch_pct", "total_pct", "grade"],
                )
                w.writeheader()
                for s in students:
                    w.writerow({k: s.get(k, "") for k in w.fieldnames})

            ctx = {
                "org_name": org_name,
                "profile_name": profile_name,
                "class": selected.get("class"),
                "subject": selected.get("subject"),
                "period_code": period_code,
                "period_label": period_label,
                "selected_tab": selected_tab,
                "criteria_url": page.url,
            }
            (batch_subdir / "criteria_context.json").write_text(json.dumps(ctx, ensure_ascii=False, indent=2), encoding="utf-8")

            max_points = _extract_quarter_max_points(page, selected_tab)
            (batch_subdir / "criteria_max_points.json").write_text(json.dumps(max_points, ensure_ascii=False, indent=2), encoding="utf-8")

            # Build Excel report
            try:
                from build_report import build_report
                template_path = _resolve_template_path("Шаблон.xlsx")
                if template_path.exists():
                    log_stage(ScraperLogger.STAGE_EXCEL_REPORT, f"Создание Excel: {class_name} - {subject_name}", None)
                    log_info(f'[{class_name} - {subject_name}] Создание Excel отчета...')
                    report_path = build_report(
                        template_path=template_path,
                        students_path=batch_subdir / "criteria_students.json",
                        context_path=batch_subdir / "criteria_context.json",
                        out_dir=out_dir / "reports",
                        max_points_path=batch_subdir / "criteria_max_points.json",
                        criteria_html_path=batch_subdir / "criteria.html",
                        org_name_path=batch_subdir / "org_name.txt",
                    )
                    log_success(f'[{class_name} - {subject_name}] Excel отчет создан: {report_path.name}')
                    if logger:
                        logger.report_created(class_name, subject_name, "Excel")

                    # Build Word report
                    try:
                        from build_word_report import build_word_report
                        # Select template based on language (ru/kk)
                        if chosen == "kk":
                            tpl = _resolve_template_path("Шаблон_каз.docx")
                            if not tpl.exists():
                                tpl = _resolve_template_path("Шаблон.docx")  # Fallback to Russian
                                log_warning(f'Казахский шаблон не найден, используется русский')
                        else:
                            tpl = _resolve_template_path("Шаблон.docx")
                        
                        if tpl.exists():
                            log_stage(ScraperLogger.STAGE_WORD_REPORT, f"Создание Word: {class_name} - {subject_name}", None)
                            log_info(f'[{class_name} - {subject_name}] Создание Word отчета ({tpl.name})...')
                            word_path = build_word_report(
                                template_docx=tpl,
                                report_xlsx=report_path,
                                out_dir=out_dir / "reports",
                                context_json=batch_subdir / "criteria_context.json",
                                lang=chosen,
                            )
                            log_success(f'[{class_name} - {subject_name}] Word отчет создан: {word_path.name}')
                        else:
                            log_warning(f'[{class_name} - {subject_name}] Шаблон Word не найден: {tpl}')
                    except Exception as e:
                        import traceback
                        log_error(f'[{class_name} - {subject_name}] ОШИБКА создания Word отчета', e)
                        if os.getenv("DEBUG", "").lower() == "1":
                            print(traceback.format_exc())
                        # Continue even if Word report fails - Excel is still saved
                else:
                    log_error(f'[{class_name} - {subject_name}] Шаблон Excel не найден: {template_path}')
            except Exception as e:
                import traceback
                log_error(f'[{class_name} - {subject_name}] ОШИБКА создания отчетов', e)
                if os.getenv("DEBUG", "").lower() == "1":
                    print(traceback.format_exc())

        # Extract table rows and either process one (interactive) or all (batch).
        log_stage(ScraperLogger.STAGE_GRADES_TABLE, "Извлечение таблицы оценок", 8)
        log_info("Извлечение данных таблицы оценок...")
        rows = _extract_grades_table(page)
        if not rows:
            log_error("Таблица оценок пуста или не найдена")
            if logger:
                logger.finish(success=False)
            return 3
        log_success(f"Найдено классов/предметов: {len(rows)}")
        _save_grades_table(rows, out_dir)

        all_mode = os.getenv("MEKTEP_ALL", "") == "1"
        if all_mode:
            batch_root = out_dir / "batch"
            limit = int(os.getenv("MEKTEP_LIMIT", "0") or "0")
            rows_to_process = rows
            if limit > 0:
                rows_to_process = rows[:limit]
                log_info(f"Применён лимит: {limit} отчетов")
            total_reports = len(rows_to_process)
            
            # Установка общего количества отчетов в логгер
            if logger:
                logger.set_total_reports(total_reports)
            
            log_info("=" * 60)
            log_info(f"ПАКЕТНЫЙ РЕЖИМ: Создание отчетов для {total_reports} классов/предметов")
            log_info("=" * 60)
            _update_progress(10, f"Начало обработки {total_reports} отчетов...", total_reports, 0)
            
            for idx, r in enumerate(rows_to_process, 1):
                class_name = r.get("class", "Unknown")
                subject_name = r.get("subject", "Unknown")
                log_info("")
                log_info(f"[{idx}/{total_reports}] === Обработка: {class_name} - {subject_name} ===")
                log_info("-" * 60)
                sub = batch_root / _safe_slug(f'{class_name} {subject_name}')
                process_one(r, sub)
                # Calculate progress: 10% (auth) to 90% (reports processing)
                progress_percent = min(90, 10 + int((idx / total_reports) * 80))
                _update_progress(progress_percent, f"Обработано отчетов: {idx} из {total_reports}", total_reports, idx)
                # Return to grades list for next item
                log_info(f"[{idx}/{total_reports}] Возврат к списку оценок...")
                _go_to_grades(page)
            log_info("")
            log_info("=" * 60)
            log_success(f"ПАКЕТНЫЙ РЕЖИМ ЗАВЕРШЕН: Создано отчетов")
            log_info("=" * 60)
            _update_progress(90, f"Обработка завершена: {total_reports} отчетов", total_reports, total_reports)
        else:
            try:
                selected = _choose_row(rows)
            except ValueError as e:
                print(str(e))
                return 2
            process_one(selected, out_dir)

        (out_dir / "criteria.url.txt").write_text(page.url, encoding="utf-8")
        (out_dir / "criteria.html").write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(out_dir / "criteria.png"), full_page=True)

        html_path = out_dir / "after_login.html"
        png_path = out_dir / "after_login.png"
        url_path = out_dir / "after_login.url.txt"

        html_path.write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(png_path), full_page=True)
        url_path.write_text(page.url, encoding="utf-8")

        log_info(f"Сохранён: {html_path}")
        log_info(f"Сохранён: {png_path}")
        log_info(f"Сохранён: {url_path}")

        log_stage(ScraperLogger.STAGE_COMPLETE, "Закрытие браузера", 95)
        context.close()
        browser.close()
        log_success("Браузер закрыт")

    # Финализация логгера
    if logger:
        logger.finish(success=True)
    
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Login automation for mektep.edu.kz")
    parser.add_argument("--headless", type=int, default=1, help="1=headless, 0=show browser")
    parser.add_argument("--out", type=str, default="out/mektep", help="Output directory")
    parser.add_argument("--slowmo", type=int, default=0, help="Slow motion (ms) for debugging")
    parser.add_argument("--lang", type=str, default="", help="Language: ru / kk / en (if empty, asks after login)")
    parser.add_argument("--period", type=str, default="", help="Quarter: 1/2/3/4 (if empty, asks after login)")
    parser.add_argument("--pick", type=str, default="", help="Row index in grades table (if empty, asks on run)")
    parser.add_argument("--all", type=int, default=0, help="1 = generate reports for ALL rows in grades table")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit how many rows to process in --all mode (0 = no limit). Useful for quotas.",
    )
    parser.add_argument("--legacy-files", type=int, default=0, help="1 = also write separate *.txt helper files (subject/period/org/teacher)")
    parser.add_argument(
        "--dotenv",
        type=str,
        default="",
        help="Optional path to env file (not .env in this workspace). Example: env.local",
    )
    args = parser.parse_args()

    if args.dotenv:
        load_dotenv(args.dotenv)
    else:
        # Safe default: try env.example name if user copied it to env.local etc.
        load_dotenv()

    if args.lang:
        os.environ["MEKTEP_LANG"] = args.lang
    if args.period:
        os.environ["MEKTEP_PERIOD"] = args.period
    if args.pick:
        os.environ["MEKTEP_PICK"] = args.pick
    if args.all:
        os.environ["MEKTEP_ALL"] = "1"
    if args.limit:
        os.environ["MEKTEP_LIMIT"] = str(args.limit)
    if args.legacy_files:
        os.environ["MEKTEP_LEGACY_FILES"] = "1"

    return run(headless=bool(args.headless), out_dir=Path(args.out), slow_mo_ms=args.slowmo)


if __name__ == "__main__":
    raise SystemExit(main())

