"""
History Widget - виджет истории отчетов

Таблица с фильтрами для просмотра созданных отчетов.
"""
import os
import json
import subprocess
from pathlib import Path
from typing import Optional, TYPE_CHECKING
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QComboBox, QLabel, QMessageBox, QHeaderView
)
from PyQt6.QtCore import Qt, pyqtSignal, QSettings

from .reports_manager import ReportsManager
from .translator import get_translator

if TYPE_CHECKING:
    from .api_client import MektepAPIClient


class HistoryWidget(QWidget):
    """Виджет истории отчетов"""
    
    # Сигнал для открытия диалога целей
    goals_requested = pyqtSignal()
    
    PERIOD_MAP_RU = {
        "1": "1 четверть",
        "2": "2 четверть",
        "3": "3 четверть",
        "4": "4 четверть"
    }
    
    PERIOD_MAP_KK = {
        "1": "1 тоқсан",
        "2": "2 тоқсан",
        "3": "3 тоқсан",
        "4": "4 тоқсан"
    }
    
    def __init__(self, reports_manager: ReportsManager, api_client: Optional["MektepAPIClient"] = None):
        super().__init__()
        self.reports_manager = reports_manager
        self.api_client = api_client
        self.translator = get_translator()
        self.settings = QSettings("Mektep", "MektepDesktop")
        saved_lang = self.settings.value("language", "ru")
        self.translator.set_language(saved_lang)
        self.init_ui()
        self.refresh()
    
    def set_api_client(self, api_client: Optional["MektepAPIClient"]):
        """Установить API клиент для синхронизации с сервером"""
        self.api_client = api_client
    
    def init_ui(self):
        """Инициализация интерфейса"""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        
        # Фильтры
        filter_layout = QHBoxLayout()
        
        # Фильтр по периоду
        quarter_label = "Четверть:" if self.translator.get_language() == 'ru' else "Тоқсан:"
        filter_layout.addWidget(QLabel(quarter_label))
        self.period_filter = QComboBox()
        all_text = "Все" if self.translator.get_language() == 'ru' else "Барлығы"
        self.period_filter.addItem(all_text, None)
        period_map = self.PERIOD_MAP_RU if self.translator.get_language() == 'ru' else self.PERIOD_MAP_KK
        for code, label in period_map.items():
            self.period_filter.addItem(label, code)
        self.period_filter.currentIndexChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.period_filter)
        
        filter_layout.addSpacing(20)
        
        # Кнопка обновления
        refresh_text = "Обновить" if self.translator.get_language() == 'ru' else "Жаңарту"
        refresh_btn = QPushButton(refresh_text)
        refresh_btn.setObjectName("refreshButton")
        refresh_btn.clicked.connect(self.refresh)
        filter_layout.addWidget(refresh_btn)
        
        # Кнопка целей обучения
        goals_text = "Цели обучения" if self.translator.get_language() == 'ru' else "Оқыту мақсаттары"
        goals_btn = QPushButton(goals_text)
        goals_btn.setObjectName("goalsButton")
        goals_btn.clicked.connect(self.goals_requested.emit)
        filter_layout.addWidget(goals_btn)
        
        filter_layout.addStretch()
        
        # Кнопка удаления всех отчетов (справа)
        delete_all_text = "Удалить все отчеты" if self.translator.get_language() == 'ru' else "Барлық есептерді жою"
        delete_all_btn = QPushButton(delete_all_text)
        delete_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #dc2626;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #b91c1c;
            }
        """)
        delete_all_btn.clicked.connect(self.delete_all_reports)
        filter_layout.addWidget(delete_all_btn)
        
        layout.addLayout(filter_layout)
        
        # Таблица отчетов
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "Дата", "Класс", "Предмет", "Четверть", "Excel", "Word", "Действия"
        ])
        
        # Растягивание колонок
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(4, 90)
        self.table.setColumnWidth(5, 90)
        self.table.setColumnWidth(6, 200)
        
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(48)  # Высота строк
        self.table.setShowGrid(False)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: white;
                alternate-background-color: #f9fafb;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
                gridline-color: transparent;
                font-size: 13px;
                color: #374151;
            }
            QHeaderView::section {
                background-color: #f3f4f6;
                color: #111827;
                border: none;
                border-bottom: 1px solid #e5e7eb;
                padding: 10px 12px;
                font-weight: 600;
                font-size: 13px;
            }
            QTableWidget::item {
                padding: 8px 12px;
                border-bottom: 1px solid #f3f4f6;
            }
            QTableWidget::item:selected {
                background-color: #eff6ff;
                color: #111827;
            }
            QPushButton#excelButton {
                background-color: #22c55e;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 2px 12px;
                font-weight: 600;
                font-size: 11px;
                min-height: 20px;
                max-height: 20px;
            }
            QPushButton#excelButton:hover {
                background-color: #16a34a;
            }
            QPushButton#excelButton:disabled {
                background-color: #e5e7eb;
                color: #9ca3af;
            }
            QPushButton#wordButton {
                background-color: #3b82f6;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 2px 12px;
                font-weight: 600;
                font-size: 11px;
                min-height: 20px;
                max-height: 20px;
            }
            QPushButton#wordButton:hover {
                background-color: #2563eb;
            }
            QPushButton#wordButton:disabled {
                background-color: #e5e7eb;
                color: #9ca3af;
            }
            QPushButton#actionButton {
                background-color: #f3f4f6;
                color: #374151;
                border: 1px solid #d1d5db;
                border-radius: 4px;
                padding: 2px 10px;
                font-size: 11px;
                min-height: 20px;
                max-height: 20px;
            }
            QPushButton#actionButton:hover {
                background-color: #e5e7eb;
            }
            QPushButton#deleteButton {
                background-color: #fef2f2;
                color: #dc2626;
                border: 1px solid #fecaca;
                border-radius: 4px;
                padding: 2px 10px;
                font-size: 11px;
                min-height: 20px;
                max-height: 20px;
            }
            QPushButton#deleteButton:hover {
                background-color: #fee2e2;
                border-color: #f87171;
            }
            QPushButton#deleteAllButton {
                background-color: #dc2626;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 12px;
            }
            QPushButton#deleteAllButton:hover {
                background-color: #b91c1c;
            }
        """)
        
        layout.addWidget(self.table)
        
        # Статистика
        self.stats_label = QLabel()
        layout.addWidget(self.stats_label)
    
    def refresh(self):
        """Обновить список отчетов"""
        self.apply_filters()
        self.update_statistics()
    
    def apply_filters(self):
        """Применить фильтры к списку"""
        filters = {}
        
        # Фильтр по периоду
        period_code = self.period_filter.currentData()
        if period_code:
            filters["period_code"] = period_code
        
        # Получаем отчеты
        reports = self.reports_manager.get_reports(filters)
        
        # Заполняем таблицу
        self.table.setRowCount(len(reports))
        
        for row, report in enumerate(reports):
            self.table.setRowHeight(row, 48)
            # Дата
            created_at = report.get("created_at", "")
            if created_at:
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    date_str = dt.strftime("%d.%m.%Y %H:%M")
                except:
                    date_str = created_at
            else:
                date_str = "—"
            
            self.table.setItem(row, 0, QTableWidgetItem(date_str))
            
            # Класс
            self.table.setItem(row, 1, QTableWidgetItem(report.get("class_name", "—")))
            
            # Предмет
            self.table.setItem(row, 2, QTableWidgetItem(report.get("subject", "—")))
            
            # Четверть
            period_map = self.PERIOD_MAP_RU if self.translator.get_language() == 'ru' else self.PERIOD_MAP_KK
            period_label = period_map.get(report.get("period_code", ""), "—")
            self.table.setItem(row, 3, QTableWidgetItem(period_label))
            
            # Excel
            excel_container = QWidget()
            excel_layout = QHBoxLayout(excel_container)
            excel_layout.setContentsMargins(4, 0, 4, 0)
            excel_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            excel_btn = QPushButton("Excel")
            excel_btn.setObjectName("excelButton")
            if report.get("excel_path") and Path(report["excel_path"]).exists():
                excel_btn.clicked.connect(lambda _, p=report["excel_path"]: self.open_file(p))
            else:
                excel_btn.setEnabled(False)
            excel_layout.addWidget(excel_btn)
            self.table.setCellWidget(row, 4, excel_container)
            
            # Word
            word_container = QWidget()
            word_layout = QHBoxLayout(word_container)
            word_layout.setContentsMargins(4, 0, 4, 0)
            word_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            word_btn = QPushButton("Word")
            word_btn.setObjectName("wordButton")
            if report.get("word_path") and Path(report["word_path"]).exists():
                word_btn.clicked.connect(lambda _, p=report["word_path"]: self.open_file(p))
            else:
                word_btn.setEnabled(False)
            word_layout.addWidget(word_btn)
            self.table.setCellWidget(row, 5, word_container)
            
            # Действия
            actions_widget = self.create_actions_widget(report)
            self.table.setCellWidget(row, 6, actions_widget)
    
    def create_actions_widget(self, report: dict) -> QWidget:
        """Создать виджет с кнопками действий"""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(4, 0, 8, 0)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        
        report_id = report["id"]
        
        # Кнопка открытия папки
        folder_btn = QPushButton("Папка")
        folder_btn.setObjectName("actionButton")
        folder_btn.setToolTip("Открыть папку")
        folder_btn.clicked.connect(lambda: self.open_folder(report))
        layout.addWidget(folder_btn)
        
        # Кнопка удаления
        delete_btn = QPushButton("Удалить")
        delete_btn.setObjectName("deleteButton")
        delete_btn.setToolTip("Удалить")
        delete_btn.clicked.connect(lambda: self.delete_report(report_id))
        layout.addWidget(delete_btn)
        
        return widget
    
    def open_file(self, file_path: str):
        """Открыть файл в системном приложении"""
        try:
            path = Path(file_path)
            if not path.exists():
                QMessageBox.warning(self, "Ошибка", f"Файл не найден:\n{file_path}")
                return
            
            # Открываем файл в системном приложении
            if os.name == 'nt':  # Windows
                os.startfile(str(path))
            elif os.name == 'posix':  # Mac/Linux
                subprocess.run(['open' if sys.platform == 'darwin' else 'xdg-open', str(path)])
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось открыть файл:\n{str(e)}")
    
    def open_folder(self, report: dict):
        """Открыть папку с отчетом"""
        try:
            # Определяем путь к папке
            excel_path = report.get("excel_path")
            word_path = report.get("word_path")
            
            folder_path = None
            if excel_path and Path(excel_path).exists():
                folder_path = Path(excel_path).parent
            elif word_path and Path(word_path).exists():
                folder_path = Path(word_path).parent
            
            if not folder_path or not folder_path.exists():
                QMessageBox.warning(self, "Ошибка", "Папка не найдена")
                return
            
            # Открываем папку
            if os.name == 'nt':  # Windows
                subprocess.run(['explorer', str(folder_path)])
            elif os.name == 'posix':  # Mac/Linux
                subprocess.run(['open' if sys.platform == 'darwin' else 'xdg-open', str(folder_path)])
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось открыть папку:\n{str(e)}")
    
    def delete_report(self, report_id: int):
        """Удалить отчет"""
        reply = QMessageBox.question(
            self,
            "Подтверждение",
            "Вы уверены, что хотите удалить этот отчет?\nФайлы Excel и Word также будут удалены.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            # Получаем информацию об отчёте для удаления с сервера
            report = self.reports_manager.get_report(report_id)
            server_report_id = None
            
            if report:
                # Пытаемся найти server_report_id в метафайле
                excel_path = report.get("excel_path")
                if excel_path:
                    server_report_id = self._get_server_report_id(excel_path)
            
            # Удаляем локально
            if self.reports_manager.delete_report(report_id, delete_files=True):
                # Удаляем с сервера если есть ID
                if server_report_id and self.api_client and self.api_client.is_authenticated():
                    result = self.api_client.delete_report(server_report_id)
                    if result.get("success"):
                        print(f"[DEBUG] Отчёт удалён с сервера: ID {server_report_id}")
                    else:
                        print(f"[DEBUG] Ошибка удаления с сервера: {result.get('error')}")
                
                QMessageBox.information(self, "Успех", "Отчет удален")
                self.refresh()
            else:
                QMessageBox.warning(self, "Ошибка", "Не удалось удалить отчет")
    
    def _get_server_report_id(self, excel_path: str) -> Optional[int]:
        """Получить ID отчёта на сервере из метафайла"""
        try:
            meta_file = Path(excel_path).with_suffix(".meta.json")
            if meta_file.exists():
                with open(meta_file, "r", encoding="utf-8") as f:
                    meta_data = json.load(f)
                return meta_data.get("server_report_id")
        except Exception as e:
            print(f"[DEBUG] Ошибка чтения метафайла: {e}")
        return None
    
    def delete_all_reports(self):
        """Удалить все отчеты"""
        reports = self.reports_manager.get_reports()
        
        if not reports:
            QMessageBox.information(self, "Информация", "Нет отчетов для удаления")
            return
        
        reply = QMessageBox.question(
            self,
            "Подтверждение",
            f"Вы уверены, что хотите удалить ВСЕ отчеты ({len(reports)} шт.)?\n\n"
            "Все файлы Excel и Word также будут удалены.\n"
            "Данные на сервере также будут очищены.\n"
            "Это действие необратимо!",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            deleted_count = 0
            
            # Удаляем локальные отчеты
            for report in reports:
                if self.reports_manager.delete_report(report["id"], delete_files=True):
                    deleted_count += 1
            
            # Удаляем ВСЕ отчёты с сервера одним запросом
            server_message = ""
            if self.api_client and self.api_client.is_authenticated():
                result = self.api_client.delete_all_reports()
                if result.get("success"):
                    gr = result.get("deleted_grade_reports", 0)
                    rf = result.get("deleted_report_files", 0)
                    server_message = f"\nУдалено с сервера: {gr + rf} записей"
                    print(f"[DEBUG] Серверные данные очищены: GradeReport={gr}, ReportFile={rf}")
                else:
                    error = result.get("error", "Неизвестная ошибка")
                    server_message = f"\nОшибка очистки сервера: {error}"
                    print(f"[DEBUG] Ошибка очистки сервера: {error}")
            
            message = f"Удалено локальных отчетов: {deleted_count} из {len(reports)}"
            message += server_message
            
            QMessageBox.information(self, "Готово", message)
            self.refresh()
    
    def update_statistics(self):
        """Обновить статистику"""
        stats = self.reports_manager.get_statistics()
        
        total = stats.get("total", 0)
        synced = stats.get("synced", 0)
        not_synced = stats.get("not_synced", 0)
        
        period_map = self.PERIOD_MAP_RU if self.translator.get_language() == 'ru' else self.PERIOD_MAP_KK
        by_period_text = ", ".join([
            f"{period_map.get(k, k)}: {v}"
            for k, v in stats.get("by_period", {}).items()
        ])
        
        text = f"Всего отчетов: {total}"
        if by_period_text:
            text += f" | По периодам: {by_period_text}"
        if synced > 0:
            text += f" | Синхронизировано: {synced}"
        
        self.stats_label.setText(text)
