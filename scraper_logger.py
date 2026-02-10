"""
Модуль логирования для скрапера mektep.edu.kz.
Обеспечивает подробное логирование каждого этапа работы.

ВАЖНО: Этот логгер НЕ обновляет progress.json - прогресс управляется 
через _update_progress() в scrape_mektep.py для совместимости с scraper_runner.py.
"""
from pathlib import Path
from datetime import datetime
from typing import Optional


class ScraperLogger:
    """Логгер для отслеживания всех этапов работы скрапера."""
    
    # Этапы работы
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
    
    def __init__(self, out_dir: Path, progress_file: Optional[str] = None):
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.out_dir / "scraper.log"
        # НЕ используем progress_file - прогресс управляется через _update_progress() в scrape_mektep.py
        # чтобы scraper_runner.py мог корректно читать прогресс
        self.start_time = datetime.now()
        self.current_stage = self.STAGE_INIT
        self.stages_completed = []
        self.errors = []
        self.reports_created = 0
        self.total_reports = 0
        
        # Инициализация лог-файла
        self._write_log("=" * 70)
        self._write_log(f"SCRAPER LOG - Начало: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        self._write_log("=" * 70)
    
    def _write_log(self, message: str, level: str = "INFO") -> None:
        """Запись в лог-файл и консоль."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_line = f"[{timestamp}] [{level}] {message}"
        
        # Консоль
        print(log_line)
        
        # Файл
        try:
            with self.log_file.open("a", encoding="utf-8") as f:
                f.write(log_line + "\n")
        except Exception:
            pass
    
    def stage(self, stage_name: str, message: str, percent: int = None) -> None:
        """Фиксация перехода на новый этап.
        
        Примечание: percent игнорируется - прогресс управляется через 
        _update_progress() в scrape_mektep.py для совместимости с scraper_runner.py
        """
        self.current_stage = stage_name
        if stage_name not in self.stages_completed:
            self.stages_completed.append(stage_name)
        
        elapsed = (datetime.now() - self.start_time).total_seconds()
        self._write_log(f"[ЭТАП: {stage_name}] {message} (прошло: {elapsed:.1f}с)")
    
    def info(self, message: str) -> None:
        """Информационное сообщение."""
        self._write_log(message, "INFO")
    
    def success(self, message: str) -> None:
        """Успешное завершение операции."""
        self._write_log(f"✓ {message}", "SUCCESS")
    
    def warning(self, message: str) -> None:
        """Предупреждение."""
        self._write_log(f"⚠ {message}", "WARNING")
    
    def error(self, message: str, exception: Exception = None) -> None:
        """Ошибка."""
        error_msg = message
        if exception:
            error_msg = f"{message}: {type(exception).__name__}: {exception}"
        self.errors.append(error_msg)
        self._write_log(f"✗ {error_msg}", "ERROR")
    
    def report_created(self, class_name: str, subject: str, report_type: str) -> None:
        """Фиксация создания отчета."""
        self.reports_created += 1
        elapsed = (datetime.now() - self.start_time).total_seconds()
        self._write_log(
            f"[{self.reports_created}/{self.total_reports}] "
            f"{report_type} отчет создан: {class_name} - {subject} "
            f"(прошло: {elapsed:.1f}с)",
            "SUCCESS"
        )
        # Примечание: прогресс обновляется через _update_progress() в scrape_mektep.py
    
    def set_total_reports(self, total: int) -> None:
        """Установка общего количества отчетов."""
        self.total_reports = total
        self._write_log(f"Всего отчетов для обработки: {total}")
    
    def finish(self, success: bool = True) -> None:
        """Завершение работы скрапера."""
        elapsed = (datetime.now() - self.start_time).total_seconds()
        
        self._write_log("=" * 70)
        if success:
            self._write_log(f"ЗАВЕРШЕНО УСПЕШНО")
            self._write_log(f"  Создано отчетов: {self.reports_created}")
            self._write_log(f"  Время выполнения: {elapsed:.1f} секунд ({elapsed/60:.1f} мин)")
        else:
            self._write_log(f"ЗАВЕРШЕНО С ОШИБКАМИ")
            self._write_log(f"  Ошибок: {len(self.errors)}")
            for err in self.errors[-10:]:
                self._write_log(f"  - {err}")
        self._write_log("=" * 70)
        # Примечание: progress.json обновляется в scraper_runner.py после завершения процесса
    
    def log_browser_action(self, action: str, details: str = "") -> None:
        """Логирование действий браузера."""
        msg = f"[Browser] {action}"
        if details:
            msg += f" - {details}"
        self._write_log(msg, "DEBUG")


# Глобальный логгер (инициализируется в run())
_logger: Optional[ScraperLogger] = None


def get_logger() -> Optional[ScraperLogger]:
    """Получение текущего логгера."""
    return _logger


def init_logger(out_dir: Path, progress_file: str = None) -> ScraperLogger:
    """Инициализация логгера."""
    global _logger
    _logger = ScraperLogger(out_dir, progress_file)
    return _logger


def log_stage(stage: str, message: str, percent: int = None):
    """Декоратор/функция для логирования этапов."""
    if _logger:
        _logger.stage(stage, message, percent)


def log_info(message: str):
    """Логирование информации."""
    if _logger:
        _logger.info(message)


def log_success(message: str):
    """Логирование успеха."""
    if _logger:
        _logger.success(message)


def log_warning(message: str):
    """Логирование предупреждения."""
    if _logger:
        _logger.warning(message)


def log_error(message: str, exception: Exception = None):
    """Логирование ошибки."""
    if _logger:
        _logger.error(message, exception)
