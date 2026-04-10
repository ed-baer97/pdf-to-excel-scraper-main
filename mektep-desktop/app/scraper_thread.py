"""
Scraper Thread - фоновый поток для скрапинга

Интеграция с существующим scrape_mektep.py без блокировки UI.
"""
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from PyQt6.QtCore import QThread, pyqtSignal

from .report_pipeline.progress_monitor import (
    format_progress_line,
    parse_schools_from_progress_message,
    read_progress_data,
)
from .report_pipeline.report_finalization import ReportFinalizer
from .report_pipeline.run_environment import (
    apply_expected_iin_policy,
    apply_expected_school_policy,
    apply_scraper_env,
    cleanup_stale_output_artifacts,
    compute_import_and_templates_paths,
    copy_report_templates_to_temp,
    ensure_parent_on_syspath,
    ensure_std_streams,
    setup_playwright_browsers_path_if_frozen,
)

ensure_std_streams()

if TYPE_CHECKING:
    from .api_client import MektepAPIClient


class ScraperThread(QThread):
    """Фоновый поток для выполнения скрапинга"""

    progress = pyqtSignal(int, str)
    report_created = pyqtSignal(str, str)
    finished = pyqtSignal(bool, list)
    error = pyqtSignal(str)
    schools_detected = pyqtSignal(list)

    def __init__(
        self,
        login: str,
        password: str,
        period_code: str,
        lang: str,
        output_dir: Path,
        school_index: str = "",
        headless: bool = True,
        api_client: Optional["MektepAPIClient"] = None,
    ):
        """Настраивает поток: логин Mektep, период, язык, каталог вывода, headless и клиент сервера."""
        super().__init__()
        self.login = login
        self.password = password
        self.period_code = period_code
        self.lang = lang
        self.output_dir = Path(output_dir)
        self.school_index = school_index
        self.headless = headless
        self.api_client = api_client

        print(f"[DEBUG] ScraperThread создан с output_dir: {self.output_dir}")
        print(f"[DEBUG] output_dir существует: {self.output_dir.exists()}")

        self.temp_dir = None
        self.progress_file = None
        self._stop_requested = False

    def stop(self):
        """Просит остановить скрапинг; основной цикл проверяет флаг и выходит."""
        self._stop_requested = True

    def select_school(self, school_index: int):
        """Записывает индекс выбранной школы в temp_dir/school_choice.txt для скрипта скрапера."""
        if self.temp_dir:
            choice_file = self.temp_dir / "school_choice.txt"
            print(f"[DEBUG] Запись выбора школы в файл: {choice_file}")
            print(f"[DEBUG] Индекс школы: {school_index}")
            choice_file.write_text(str(school_index), encoding="utf-8")
            print(f"[DEBUG] Файл записан. Существует: {choice_file.exists()}")
        else:
            print("[DEBUG] ОШИБКА: temp_dir не установлен!")

    def run(self):
        """Выполняет сценарий скрапинга: env, scrape_mektep.run, чтение progress.json, финализация отчётов."""
        try:
            self.temp_dir = Path(tempfile.mkdtemp(prefix="mektep_"))
            self.progress_file = self.temp_dir / "progress.json"

            self.output_dir.mkdir(parents=True, exist_ok=True)
            cleanup_stale_output_artifacts(self.output_dir)

            parent_dir, templates_src_dir = compute_import_and_templates_paths()
            ensure_parent_on_syspath(parent_dir)
            frozen = getattr(sys, "frozen", False)
            templates_dir = copy_report_templates_to_temp(
                self.temp_dir, templates_src_dir, parent_dir, frozen
            )

            apply_scraper_env(
                self.login,
                self.password,
                self.period_code,
                self.lang,
                self.progress_file,
                self.school_index,
                templates_dir,
            )
            apply_expected_school_policy(self.api_client)
            iin_err = apply_expected_iin_policy(self.api_client, self.login)
            if iin_err:
                self.error.emit(iin_err)
                self.finished.emit(False, [])
                return

            self.progress.emit(5, "Инициализация...")
            setup_playwright_browsers_path_if_frozen()

            from scrape_mektep import run as scrape_run

            scraper_thread = threading.Thread(
                target=self._run_scraper,
                args=(scrape_run, self.temp_dir),
            )
            scraper_thread.daemon = True
            scraper_thread.start()

            last_progress = 0
            no_progress_count = 0

            while scraper_thread.is_alive():
                if self._stop_requested:
                    self.error.emit("Скрапинг остановлен пользователем")
                    return

                progress_data = read_progress_data(self.progress_file)
                if progress_data:
                    try:
                        percent = progress_data.get("percent", 0)
                        message = progress_data.get("message", "Выполняется...")
                        total_reports = progress_data.get("total_reports")
                        processed_reports = progress_data.get("processed_reports", 0)

                        schools_list = parse_schools_from_progress_message(message)
                        if schools_list is not None:
                            print(
                                f"[DEBUG] Обнаружен запрос выбора школы: {len(schools_list)} школ"
                            )
                            print(f"[DEBUG] Школы: {schools_list}")
                            if not hasattr(self, "_schools_signal_sent"):
                                self._schools_signal_sent = True
                                print(
                                    f"[DEBUG] Отправка сигнала schools_detected с {len(schools_list)} школами"
                                )
                                self.schools_detected.emit(schools_list)
                                print("[DEBUG] Сигнал schools_detected отправлен")
                            else:
                                print("[DEBUG] Сигнал уже был отправлен ранее, пропускаем")
                            continue

                        message = format_progress_line(
                            message, total_reports, processed_reports
                        )

                        if percent != last_progress:
                            self.progress.emit(percent, message)
                            last_progress = percent
                            no_progress_count = 0
                        else:
                            no_progress_count += 1

                        if no_progress_count > 120:
                            self.error.emit("Скрапер завис. Попробуйте еще раз.")
                            return

                    except Exception:
                        pass

                time.sleep(1)

            scraper_thread.join(timeout=5)

            if self._scraper_result == 0:
                self.progress.emit(95, "Финализация отчетов...")
                finalizer = ReportFinalizer(
                    self.period_code,
                    self.lang,
                    self.output_dir,
                    self.temp_dir,
                    self.api_client,
                )
                reports = finalizer.finalize_reports()
                reports_dir = self.output_dir / "reports"
                if reports_dir.exists():
                    try:
                        shutil.rmtree(reports_dir)
                    except Exception:
                        pass
                self.progress.emit(100, f"Готово! Создано отчетов: {len(reports)}")
                self.finished.emit(True, reports)
            elif self._scraper_result == 5:
                self.error.emit(
                    "Организация на mektep.edu.kz не совпадает с вашей школой. "
                    "Создание отчётов для других школ запрещено администратором."
                )
                self.finished.emit(False, [])
            elif self._scraper_result == 6:
                self.error.emit(
                    "Логин для mektep.edu.kz должен совпадать с вашим ИИН (12 цифр), "
                    "указанным администратором в системе."
                )
                self.finished.emit(False, [])
            else:
                detail = getattr(self, "_scraper_error_detail", "")
                if detail:
                    self.error.emit(f"Скрапинг завершился с ошибкой:\n{detail}")
                else:
                    self.error.emit(
                        f"Скрапинг завершился с ошибкой (код: {self._scraper_result})"
                    )
                self.finished.emit(False, [])

        except Exception as e:
            self.error.emit(f"Ошибка выполнения: {str(e)}")
            self.finished.emit(False, [])

        finally:
            if self.temp_dir and self.temp_dir.exists():
                try:
                    time.sleep(0.5)
                    shutil.rmtree(self.temp_dir, ignore_errors=True)
                except Exception as e:
                    print(f"Warning: Could not remove temp directory {self.temp_dir}: {e}")
                    try:
                        for item in self.temp_dir.rglob("*"):
                            try:
                                if item.is_file():
                                    item.unlink()
                            except Exception:
                                pass
                    except Exception:
                        pass

    def _run_scraper(self, scrape_function, temp_dir):
        """Вызывает переданную функцию скрапера (обычно scrape_mektep.run) с out_dir=temp_dir."""
        try:
            result = scrape_function(
                headless=self.headless,
                out_dir=temp_dir,
                slow_mo_ms=0,
            )
            self._scraper_result = result
        except Exception as e:
            self._scraper_error_detail = f"{type(e).__name__}: {e}"
            self._scraper_result = 1
