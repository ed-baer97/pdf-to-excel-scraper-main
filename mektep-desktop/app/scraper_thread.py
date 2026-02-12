"""
Scraper Thread - фоновый поток для скрапинга

Интеграция с существующим scrape_mektep.py без блокировки UI.
"""
import os
import sys
import json
import time
import shutil
import tempfile
from pathlib import Path
from typing import Optional, List, Dict, TYPE_CHECKING
from PyQt6.QtCore import QThread, pyqtSignal

if TYPE_CHECKING:
    from .api_client import MektepAPIClient


# Импорт PERIOD_MAP
try:
    from webapp.constants import PERIOD_MAP
except ImportError:
    PERIOD_MAP = {
        "1": "1 четверть",
        "2": "2 четверть (1 полугодие)",
        "3": "3 четверть",
        "4": "4 четверть (2 полугодие)",
    }


class ScraperThread(QThread):
    """Фоновый поток для выполнения скрапинга"""
    
    # Сигналы для обновления UI
    progress = pyqtSignal(int, str)  # (процент, сообщение)
    report_created = pyqtSignal(str, str)  # (класс, предмет)
    finished = pyqtSignal(bool, list)  # (успех, список отчетов)
    error = pyqtSignal(str)  # сообщение об ошибке
    schools_detected = pyqtSignal(list)  # (список названий школ)
    
    def __init__(
        self,
        login: str,
        password: str,
        period_code: str,
        lang: str,
        output_dir: Path,
        school_index: str = "",
        headless: bool = True,
        api_client: Optional["MektepAPIClient"] = None
    ):
        """
        Инициализация потока скрапинга
        
        Args:
            login: Логин mektep.edu.kz
            password: Пароль
            period_code: Код периода (1-4)
            lang: Язык (ru/kk/en)
            output_dir: Папка для сохранения отчетов
            school_index: Индекс школы (пустая строка = авто, "0", "1", и т.д.)
            headless: Запускать браузер в headless режиме
            api_client: API клиент для загрузки отчётов на сервер
        """
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
        
        # Создаем временную папку для промежуточных файлов
        self.temp_dir = None
        self.progress_file = None
        self._stop_requested = False
    
    def stop(self):
        """Запрос на остановку скрапинга"""
        self._stop_requested = True
    
    def select_school(self, school_index: int):
        """Записать выбор школы пользователя в файл для скрипта"""
        # ИСПРАВЛЕНИЕ: Пишем в temp_dir (где скрипт ищет), а не в output_dir
        if self.temp_dir:
            choice_file = self.temp_dir / "school_choice.txt"
            print(f"[DEBUG] Запись выбора школы в файл: {choice_file}")
            print(f"[DEBUG] Индекс школы: {school_index}")
            choice_file.write_text(str(school_index), encoding="utf-8")
            print(f"[DEBUG] Файл записан. Существует: {choice_file.exists()}")
        else:
            print(f"[DEBUG] ОШИБКА: temp_dir не установлен!")
    
    def _cleanup_old_temp_files(self):
        """Очистка старых промежуточных файлов и папок из главной директории"""
        if not self.output_dir.exists():
            return
        
        # Список промежуточных папок и файлов, которые нужно удалить
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
            "meta.json"
        ]
        
        for item_name in temp_items:
            item_path = self.output_dir / item_name
            try:
                if item_path.is_dir():
                    shutil.rmtree(item_path)
                elif item_path.is_file():
                    item_path.unlink()
            except Exception:
                pass  # Игнорируем ошибки - файл может не существовать
    
    def run(self):
        """Выполнение скрапинга в фоновом потоке"""
        try:
            # Создаем временную директорию для всех промежуточных файлов
            self.temp_dir = Path(tempfile.mkdtemp(prefix="mektep_"))
            self.progress_file = self.temp_dir / "progress.json"
            
            # Создаем выходную директорию (на случай если она не существует)
            self.output_dir.mkdir(parents=True, exist_ok=True)
            
            # Очистка старых промежуточных папок/файлов из предыдущих запусков
            self._cleanup_old_temp_files()
            
            # Настройка переменных окружения для скрапера
            os.environ["MEKTEP_LOGIN"] = self.login
            os.environ["MEKTEP_PASSWORD"] = self.password
            os.environ["MEKTEP_PERIOD"] = self.period_code
            os.environ["MEKTEP_LANG"] = self.lang
            os.environ["MEKTEP_ALL"] = "1"  # Создать все отчеты
            os.environ["PROGRESS_FILE"] = str(self.progress_file)
            # Set school index if specified
            if self.school_index:
                os.environ["MEKTEP_SCHOOL_INDEX"] = self.school_index
            elif "MEKTEP_SCHOOL_INDEX" in os.environ:
                del os.environ["MEKTEP_SCHOOL_INDEX"]
            
            # ===== Защита от передачи аккаунта: получаем школу пользователя =====
            if "MEKTEP_EXPECTED_SCHOOL" in os.environ:
                del os.environ["MEKTEP_EXPECTED_SCHOOL"]
            
            if self.api_client and self.api_client.is_authenticated():
                try:
                    school_info = self.api_client.get_my_school()
                    if school_info.get("success"):
                        school_name = school_info.get("school_name")
                        allow_cross = school_info.get("allow_cross_school_reports", True)
                        if school_name and not allow_cross:
                            os.environ["MEKTEP_EXPECTED_SCHOOL"] = school_name
                            print(f"[DEBUG] Защита: ожидаемая школа = '{school_name}'")
                        else:
                            print(f"[DEBUG] Защита: cross-school разрешено или школа не назначена")
                    else:
                        print(f"[DEBUG] Не удалось получить информацию о школе: "
                              f"{school_info.get('error', '?')}")
                except Exception as e:
                    print(f"[DEBUG] Ошибка при получении информации о школе: {e}")
            
            # Определяем базовые директории (поддержка PyInstaller)
            if getattr(sys, 'frozen', False):
                # Скомпилированное приложение (PyInstaller)
                base_dir = Path(sys._MEIPASS)
                templates_src_dir = base_dir / "templates"
                # Для импорта scrape_mektep в frozen режиме
                parent_dir = base_dir
            else:
                # Режим разработки
                desktop_dir = Path(__file__).parent.parent
                parent_dir = desktop_dir.parent
                templates_src_dir = desktop_dir  # Шаблоны в mektep-desktop
            
            # Добавляем родительскую папку в path для импорта
            if str(parent_dir) not in sys.path:
                sys.path.insert(0, str(parent_dir))

            # Подготовка шаблонов в временной папке
            templates_dir = self.temp_dir / "templates"
            templates_dir.mkdir(parents=True, exist_ok=True)
            
            for name in ["Шаблон.xlsx", "Шаблон.docx", "Шаблон_каз.docx"]:
                # В frozen режиме шаблоны уже в templates_src_dir
                src = templates_src_dir / name
                if not src.exists() and not getattr(sys, 'frozen', False):
                    # В режиме разработки пробуем родительскую папку
                    src = parent_dir / name
                dst = templates_dir / name
                if src.exists() and not dst.exists():
                    try:
                        shutil.copy2(src, dst)
                    except Exception:
                        pass
            os.environ["MEKTEP_TEMPLATES_DIR"] = str(templates_dir)
            
            # Запускаем мониторинг прогресса
            self.progress.emit(5, "Инициализация...")
            
            # Импортируем и запускаем скрапер (во временной папке)
            from scrape_mektep import run as scrape_run
            
            # Запускаем скрапер в отдельном процессе для мониторинга
            import threading
            scraper_thread = threading.Thread(
                target=self._run_scraper,
                args=(scrape_run, self.temp_dir)
            )
            scraper_thread.daemon = True
            scraper_thread.start()
            
            # Мониторинг прогресса
            last_progress = 0
            no_progress_count = 0
            
            while scraper_thread.is_alive():
                if self._stop_requested:
                    self.error.emit("Скрапинг остановлен пользователем")
                    return
                
                # Читаем файл прогресса
                if self.progress_file.exists():
                    try:
                        with open(self.progress_file, 'r', encoding='utf-8') as f:
                            progress_data = json.load(f)
                        
                        percent = progress_data.get('percent', 0)
                        message = progress_data.get('message', 'Выполняется...')
                        total_reports = progress_data.get('total_reports')
                        processed_reports = progress_data.get('processed_reports', 0)
                        
                        # Проверка на запрос выбора школы
                        if message.startswith('schools_selection_needed|'):
                            try:
                                # Извлекаем список школ из сообщения
                                schools_json = message.split('|', 1)[1]
                                schools_list = json.loads(schools_json)
                                print(f"[DEBUG] Обнаружен запрос выбора школы: {len(schools_list)} школ")
                                print(f"[DEBUG] Школы: {schools_list}")
                                # Эмитируем сигнал один раз
                                if not hasattr(self, '_schools_signal_sent'):
                                    self._schools_signal_sent = True
                                    print(f"[DEBUG] Отправка сигнала schools_detected с {len(schools_list)} школами")
                                    self.schools_detected.emit(schools_list)
                                    print(f"[DEBUG] Сигнал schools_detected отправлен")
                                else:
                                    print(f"[DEBUG] Сигнал уже был отправлен ранее, пропускаем")
                                # Не отправляем это сообщение как обычный прогресс
                                continue
                            except Exception as e:
                                # Если не удалось распарсить, продолжаем как обычно
                                print(f"[DEBUG] Ошибка парсинга schools_selection_needed: {e}")
                                pass
                        
                        # Формируем сообщение
                        if total_reports:
                            message = f"{message} ({processed_reports}/{total_reports})"
                        
                        # Отправляем обновление только если изменилось
                        if percent != last_progress:
                            self.progress.emit(percent, message)
                            last_progress = percent
                            no_progress_count = 0
                        else:
                            no_progress_count += 1
                        
                        # Проверка на зависание (2 минуты без прогресса)
                        if no_progress_count > 120:
                            self.error.emit("Скрапер завис. Попробуйте еще раз.")
                            return
                    
                    except Exception:
                        pass
                
                time.sleep(1)
            
            # Скрапер завершился, проверяем результат
            scraper_thread.join(timeout=5)
            
            if self._scraper_result == 0:
                # Успех! Перемещаем отчеты в финальную папку
                self.progress.emit(95, "Финализация отчетов...")
                reports = self._finalize_reports()
                # Дополнительная очистка папки reports в главной директории (если осталась)
                reports_dir = self.output_dir / "reports"
                if reports_dir.exists():
                    try:
                        shutil.rmtree(reports_dir)
                    except Exception:
                        pass
                self.progress.emit(100, f"Готово! Создано отчетов: {len(reports)}")
                self.finished.emit(True, reports)
            elif self._scraper_result == 5:
                # Организация не совпадает — защита от передачи аккаунта
                self.error.emit(
                    "Организация на mektep.edu.kz не совпадает с вашей школой. "
                    "Создание отчётов для других школ запрещено администратором."
                )
                self.finished.emit(False, [])
            else:
                self.error.emit(f"Скрапинг завершился с ошибкой (код: {self._scraper_result})")
                self.finished.emit(False, [])
        
        except Exception as e:
            self.error.emit(f"Ошибка выполнения: {str(e)}")
            self.finished.emit(False, [])
        
        finally:
            # Очистка временной папки
            if self.temp_dir and self.temp_dir.exists():
                try:
                    # Даем время для освобождения файлов
                    time.sleep(0.5)
                    shutil.rmtree(self.temp_dir, ignore_errors=True)
                except Exception as e:
                    print(f"Warning: Could not remove temp directory {self.temp_dir}: {e}")
                    # Попытка удалить отдельные файлы, если папку не удалось
                    try:
                        for item in self.temp_dir.rglob('*'):
                            try:
                                if item.is_file():
                                    item.unlink()
                            except Exception:
                                pass
                    except Exception:
                        pass  # Не критично, если не удалось удалить
    
    def _run_scraper(self, scrape_function, temp_dir):
        """Запуск функции скрапинга во временной папке"""
        try:
            result = scrape_function(
                headless=self.headless,
                out_dir=temp_dir,
                slow_mo_ms=0
            )
            self._scraper_result = result
        except Exception as e:
            print(f"Scraper error: {e}")
            self._scraper_result = 1
    
    def _finalize_reports(self) -> List[Dict]:
        """
        Финализация отчетов: перемещение из временной папки в финальную структуру.
        
        Формирует grades_json + analytics_json напрямую из JSON скрапера
        (без обхода через Excel) и загружает на сервер.
        """
        reports = []
        
        # Получаем название четверти
        period_name = PERIOD_MAP.get(self.period_code, f"Четверть {self.period_code}")
        
        # Ищем отчеты во временной папке
        if not self.temp_dir or not self.temp_dir.exists():
            return reports
        
        # ===== Читаем ФИО учителя из profile_name.txt =====
        teacher_name = None
        profile_file = self.temp_dir / "profile_name.txt"
        if profile_file.exists():
            try:
                teacher_name = profile_file.read_text(encoding="utf-8").strip()
                print(f"[DEBUG] ФИО учителя из скрапера: '{teacher_name}'")
            except Exception as e:
                print(f"[DEBUG] Ошибка чтения profile_name.txt: {e}")
        
        # Санитизация имени для файловой системы
        if teacher_name:
            import re
            safe_teacher_name = re.sub(r'[\\/*?:"<>|]', '_', teacher_name).strip()
        else:
            safe_teacher_name = "Неизвестный учитель"
        
        # Создаем финальную папку: output_dir / ФИО учителя / четверть
        final_reports_dir = self.output_dir / safe_teacher_name / period_name
        final_reports_dir.mkdir(parents=True, exist_ok=True)
        
        # ===== Читаем имя организации из org_name.txt =====
        self._scraped_org_name = None
        org_name_file = self.temp_dir / "org_name.txt"
        if org_name_file.exists():
            try:
                self._scraped_org_name = org_name_file.read_text(encoding="utf-8").strip()
                print(f"[DEBUG] Организация из скрапера: '{self._scraped_org_name}'")
            except Exception as e:
                print(f"[DEBUG] Ошибка чтения org_name.txt: {e}")
        
        # ===== Предварительная проверка: есть ли организация в БД сервера =====
        self._org_upload_allowed = True  # По умолчанию разрешаем загрузку
        self._server_school_name = None
        
        if self._scraped_org_name and self.api_client and self.api_client.is_authenticated():
            lookup_result = self.api_client.lookup_school(self._scraped_org_name)
            if lookup_result.get("success"):
                self._server_school_name = lookup_result.get("school_name")
                print(f"[DEBUG] Организация найдена на сервере: '{self._server_school_name}' "
                      f"(ID: {lookup_result.get('school_id')})")
            else:
                self._org_upload_allowed = False
                print(f"[DEBUG] Организация '{self._scraped_org_name}' НЕ найдена на сервере. "
                      f"Отчёты будут сохранены только локально (Excel/Word).")
        
        batch_dir = self.temp_dir / "batch"
        reports_dir = self.temp_dir / "reports"
        
        # Собираем batch-подпапки с JSON данными скрапера
        batch_subdirs = []
        if batch_dir.exists():
            batch_subdirs = sorted(
                [d for d in batch_dir.iterdir() if d.is_dir()],
                key=lambda d: d.name
            )
        
        if batch_subdirs:
            # Основной подход: данные из JSON скрапера напрямую
            for subdir in batch_subdirs:
                try:
                    report_data = self._process_batch_subdir(
                        subdir, reports_dir, final_reports_dir, period_name
                    )
                    if report_data:
                        reports.append(report_data)
                except Exception as e:
                    print(f"[DEBUG] Ошибка обработки {subdir.name}: {e}")
                    continue
        else:
            # Fallback: ищем Excel файлы напрямую (старый формат без batch)
            reports = self._finalize_from_excel_files(final_reports_dir, period_name)
        
        return reports
    
    def _process_batch_subdir(
        self,
        subdir: Path,
        reports_dir: Path,
        final_reports_dir: Path,
        period_name: str
    ) -> Optional[Dict]:
        """Обработка одного batch-подкаталога с JSON данными скрапера."""
        students_file = subdir / "criteria_students.json"
        context_file = subdir / "criteria_context.json"
        
        if not students_file.exists():
            return None
        
        # Читаем контекст
        ctx = {}
        if context_file.exists():
            with open(context_file, "r", encoding="utf-8") as f:
                ctx = json.load(f)
        
        class_name_raw = str(ctx.get("class", "")).strip()
        subject_name = str(ctx.get("subject", "")).strip()
        class_name = self._parse_class_liter(class_name_raw)
        
        if not class_name or not subject_name:
            return None
        
        # Ищем Excel/Word файл в reports_dir
        final_excel = None
        final_word = None
        
        if reports_dir.exists():
            # Имя файла как в build_report.py: sanitize(class_name_raw + subject)
            expected_name = self._sanitize_filename(
                f"{class_name_raw} {subject_name}".strip()
            )
            excel_candidate = reports_dir / f"{expected_name}.xlsx"
            
            if not excel_candidate.exists():
                # Пробуем с нормализованным именем класса
                alt_name = self._sanitize_filename(
                    f"{class_name} {subject_name}".strip()
                )
                excel_candidate = reports_dir / f"{alt_name}.xlsx"
            
            if excel_candidate.exists():
                final_excel = self._move_file(
                    excel_candidate, final_reports_dir / excel_candidate.name
                )
                
                # Word файл с таким же именем
                word_candidate = excel_candidate.with_suffix(".docx")
                if word_candidate.exists():
                    final_word = self._move_file(
                        word_candidate, final_reports_dir / word_candidate.name
                    )
        
        report_data = {
            "class_name": class_name,
            "subject": subject_name,
            "period_code": self.period_code,
            "lang": self.lang,
            "org_name": getattr(self, '_scraped_org_name', None),
            "excel_path": str(final_excel.absolute()) if final_excel else None,
            "word_path": str(final_word.absolute()) if final_word else None,
            "metadata": {
                "created_by": "desktop",
                "output_dir": str(final_reports_dir),
                "period_name": period_name,
                "org_name": getattr(self, '_scraped_org_name', None),
                "server_school_name": getattr(self, '_server_school_name', None)
            }
        }
        
        # Формируем данные из JSON и загружаем на сервер
        # Проверяем: организация должна быть в БД сервера для загрузки
        org_upload_allowed = getattr(self, '_org_upload_allowed', True)
        
        if not org_upload_allowed:
            print(f"[DEBUG] Пропуск загрузки на сервер: организация "
                  f"'{getattr(self, '_scraped_org_name', '?')}' не найдена в БД. "
                  f"Отчёт сохранён только локально: {class_name} {subject_name}")
            report_data["upload_skipped"] = True
            report_data["upload_skip_reason"] = "org_not_found"
            return report_data
        
        if self.api_client and self.api_client.is_authenticated():
            try:
                grades_data, analytics_data = self._build_grades_and_analytics(subdir)
                if grades_data:
                    period_type = "quarter"
                    period_number = int(self.period_code)
                    
                    upload_result = self.api_client.upload_report(
                        class_name=class_name,
                        subject_name=subject_name,
                        period_type=period_type,
                        period_number=period_number,
                        grades_data=grades_data,
                        analytics_data=analytics_data,
                        org_name=getattr(self, '_scraped_org_name', None)
                    )
                    
                    if upload_result.get("success"):
                        report_data["server_report_id"] = upload_result.get("report_id")
                        if final_excel:
                            self._save_report_metadata(
                                final_excel,
                                upload_result.get("report_id"),
                                class_name,
                                subject_name,
                                period_type,
                                period_number
                            )
                        print(f"[DEBUG] Отчёт загружен: {class_name} {subject_name} "
                              f"-> ID {upload_result.get('report_id')} ({upload_result.get('action')})")
                    elif upload_result.get("org_not_found"):
                        print(f"[DEBUG] Сервер: организация не найдена. "
                              f"Отчёт сохранён только локально: {class_name} {subject_name}")
                        report_data["upload_skipped"] = True
                        report_data["upload_skip_reason"] = "org_not_found_server"
                    else:
                        print(f"[DEBUG] Ошибка загрузки: {upload_result.get('error')}")
            except Exception as e:
                print(f"[DEBUG] Ошибка при загрузке на сервер: {e}")
        
        return report_data
    
    def _finalize_from_excel_files(
        self, final_reports_dir: Path, period_name: str
    ) -> List[Dict]:
        """Fallback: финализация из Excel файлов (когда batch-подпапок нет)."""
        reports = []
        
        possible_dirs = [
            self.temp_dir / "reports",
            self.temp_dir / "batch",
            self.temp_dir,
        ]
        
        reports_dir = None
        for dir_path in possible_dirs:
            if dir_path.exists() and list(dir_path.glob("*.xlsx")):
                reports_dir = dir_path
                break
        
        if reports_dir is None:
            reports_dir = self.temp_dir
        
        excel_files = [
            f for f in reports_dir.glob("**/*.xlsx")
            if not f.stem.startswith("Шаблон") and "templates" not in str(f)
        ]
        
        for excel_file in excel_files:
            stem = excel_file.stem
            if "_" in stem or " " in stem:
                parts = stem.replace("_", " ").split(" ", 1)
                class_name = parts[0] if parts else "Unknown"
                subject = parts[1] if len(parts) > 1 else "Unknown"
            else:
                class_name = "Unknown"
                subject = stem
            
            final_excel = self._move_file(
                excel_file, final_reports_dir / excel_file.name
            )
            
            final_word = None
            word_file = excel_file.with_suffix('.docx')
            if word_file.exists():
                final_word = self._move_file(
                    word_file, final_reports_dir / word_file.name
                )
            
            reports.append({
                "class_name": class_name,
                "subject": subject,
                "period_code": self.period_code,
                "lang": self.lang,
                "excel_path": str(final_excel.absolute()) if final_excel else None,
                "word_path": str(final_word.absolute()) if final_word else None,
                "metadata": {
                    "created_by": "desktop",
                    "output_dir": str(final_reports_dir),
                    "period_name": period_name
                }
            })
        
        return reports
    
    # ==================================================================
    # Вспомогательные методы
    # ==================================================================
    
    @staticmethod
    def _move_file(src: Path, dst: Path) -> Optional[Path]:
        """Переместить файл; при ошибке — копировать."""
        try:
            shutil.move(str(src), str(dst))
            return dst
        except Exception:
            try:
                shutil.copy2(str(src), str(dst))
                return dst
            except Exception:
                return None
    
    @staticmethod
    def _sanitize_filename(s: str) -> str:
        """Очистка строки для использования в имени файла."""
        import re
        s = " ".join((s or "").split()).strip()
        s = re.sub(r'[<>:"/\\|?*]+', '_', s)
        s = s.strip(" .")
        return s or "report"
    
    @staticmethod
    def _parse_class_liter(class_text: str) -> str:
        """Нормализация названия класса: '5 «В»' -> '5В'"""
        import re
        s = (class_text or "").replace("«", " ").replace("»", " ").strip()
        m = re.search(r"(\d+)\s*([A-Za-zА-ЯЁӘҒҚҢӨҰҮҺа-яёәғқңөұүһ])?", s)
        if not m:
            return (class_text or "").strip()
        num = m.group(1)
        lit = (m.group(2) or "").upper()
        return f"{num}{lit}".strip()
    
    @staticmethod
    def _parse_number(val):
        """Преобразовать значение в float."""
        if val is None:
            return None
        if isinstance(val, (int, float)):
            return float(val)
        s = str(val).strip().replace("%", "").replace(",", ".")
        try:
            return float(s) if s else None
        except (ValueError, TypeError):
            return None
    
    # ==================================================================
    # Формирование JSON данных из сырых данных скрапера
    # ==================================================================
    
    def _build_grades_and_analytics(self, batch_subdir: Path):
        """
        Формирование grades_json и analytics_json из сырых JSON скрапера.
        
        Читает criteria_students.json + criteria_max_points.json напрямую,
        без обхода через Excel.
        
        Пороги оценок (как в build_report.py):
          ≥85% → 5,  65–84% → 4,  40–64% → 3,  <40% → 2
        
        Returns:
            tuple: (grades_data: dict | None, analytics_data: dict | None)
        """
        try:
            students_file = batch_subdir / "criteria_students.json"
            max_points_file = batch_subdir / "criteria_max_points.json"
            
            if not students_file.exists():
                return None, None
            
            with open(students_file, "r", encoding="utf-8") as f:
                students = json.load(f)
            
            if not students:
                return None, None
            
            # Max points по секциям (0 = СОЧ, 1/2/3 = СОР 1/2/3)
            max_points = {}
            if max_points_file.exists():
                try:
                    with open(max_points_file, "r", encoding="utf-8") as f:
                        mp = json.load(f)
                    if isinstance(mp, dict):
                        max_points = {int(k): int(v) for k, v in mp.items()}
                except Exception:
                    pass
            
            quarter_num = int(students[0].get("quarter_num", 0)) if students else 0
            students_sorted = sorted(students, key=lambda s: int(s.get("num") or 0))
            
            # ==============================================================
            # grades_json — итоговые оценки учеников
            # ==============================================================
            grades_students = []
            g5 = g4 = g3 = g2 = 0
            
            for s in students_sorted:
                name = (s.get("fio") or "").strip()
                if not name:
                    continue
                
                percent = self._parse_number(s.get("total_pct"))
                
                grade_int = None
                grade_raw = s.get("grade")
                if grade_raw is not None:
                    try:
                        grade_int = int(float(str(grade_raw).strip()))
                    except (ValueError, TypeError):
                        pass
                
                if grade_int:
                    if grade_int >= 5:
                        g5 += 1
                    elif grade_int >= 4:
                        g4 += 1
                    elif grade_int >= 3:
                        g3 += 1
                    else:
                        g2 += 1
                
                grades_students.append({
                    "name": name,
                    "percent": percent,
                    "grade": grade_int
                })
            
            total = len(grades_students)
            grades_data = {
                "students": grades_students,
                "quality_percent": round((g5 + g4) / total * 100, 1) if total > 0 else 0,
                "success_percent": round((g5 + g4 + g3) / total * 100, 1) if total > 0 else 0,
                "total_students": total
            }
            
            # ==============================================================
            # analytics_json — распределение оценок по СОР / СОЧ
            # ==============================================================
            # Определяем, какие секции присутствуют в данных
            sections_present = set()
            prefix_base = f"chetvert_{quarter_num}_razdel_"
            
            for s in students_sorted:
                for pid in (s.get("points") or {}):
                    if isinstance(pid, str) and pid.startswith(prefix_base):
                        parts = pid.split("_")
                        if len(parts) >= 5:
                            try:
                                sections_present.add(int(parts[3]))
                            except ValueError:
                                pass
            
            sor_list = []
            soch_data = None
            
            for sec in sorted(sections_present):
                max_val = max_points.get(sec)
                if not max_val or max_val <= 0:
                    continue
                
                c5 = c4 = c3 = c2 = 0
                sec_prefix = f"chetvert_{quarter_num}_razdel_{sec}_"
                
                for s in students_sorted:
                    if not (s.get("fio") or "").strip():
                        continue
                    
                    # Берём балл ученика по данной секции
                    # (логика как в build_report._points_by_section)
                    point_val = None
                    for pid, val in (s.get("points") or {}).items():
                        if isinstance(pid, str) and pid.startswith(sec_prefix):
                            try:
                                point_val = float(str(val).strip())
                            except (ValueError, TypeError):
                                pass
                    
                    if point_val is not None:
                        pct = point_val / max_val * 100
                        if pct >= 85:
                            c5 += 1
                        elif pct >= 65:
                            c4 += 1
                        elif pct >= 40:
                            c3 += 1
                        else:
                            c2 += 1
                
                entry = {"count_5": c5, "count_4": c4, "count_3": c3, "count_2": c2}
                
                if sec == 0:
                    soch_data = entry
                else:
                    entry["name"] = f"СОр {sec}"
                    sor_list.append(entry)
            
            analytics_data = None
            if sor_list or soch_data:
                analytics_data = {}
                if sor_list:
                    analytics_data["sor"] = sor_list
                if soch_data:
                    analytics_data["soch"] = soch_data
            
            return grades_data, analytics_data
        
        except Exception as e:
            print(f"[DEBUG] Ошибка формирования данных из JSON: {e}")
            return None, None
    
    def _save_report_metadata(
        self,
        excel_path: Path,
        server_report_id: int,
        class_name: str,
        subject_name: str,
        period_type: str,
        period_number: int
    ):
        """
        Сохранение метаданных отчёта для синхронизации с сервером
        
        Создаёт .meta.json файл рядом с Excel файлом.
        """
        try:
            meta_file = excel_path.with_suffix(".meta.json")
            meta_data = {
                "server_report_id": server_report_id,
                "class_name": class_name,
                "subject_name": subject_name,
                "period_type": period_type,
                "period_number": period_number,
                "org_name": getattr(self, '_scraped_org_name', None),
                "server_school_name": getattr(self, '_server_school_name', None),
                "uploaded_at": time.strftime("%Y-%m-%dT%H:%M:%S")
            }
            with open(meta_file, "w", encoding="utf-8") as f:
                json.dump(meta_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[DEBUG] Ошибка сохранения метаданных: {e}")
