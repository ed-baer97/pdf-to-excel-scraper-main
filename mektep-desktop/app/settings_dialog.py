"""
Settings Dialog - диалог настроек приложения

Сохранение настроек через QSettings.
Вкладки: Сервер | Папка отчётов | Язык
"""
from pathlib import Path
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QLabel, QLineEdit, QPushButton, QCheckBox, QSpinBox,
    QComboBox, QGroupBox, QFileDialog, QDialogButtonBox, QMessageBox
)
from PyQt6.QtCore import QSettings, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QIcon

from .api_client import MektepAPIClient, DEFAULT_SERVER_URL
from .translator import get_translator


class _ConnectionCheckThread(QThread):
    """Поток для проверки подключения"""
    finished = pyqtSignal(dict)
    
    def __init__(self, url: str):
        super().__init__()
        self.url = url
    
    def run(self):
        client = MektepAPIClient(self.url)
        result = client.check_connection(timeout=8)
        self.finished.emit(result)


class SettingsDialog(QDialog):
    """Диалог настроек"""
    
    def __init__(self, settings: QSettings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.translator = get_translator()
        self._check_thread = None
        self.init_ui()
        self.load_settings()
    
    @staticmethod
    def _get_icon_path() -> Path:
        """Путь к иконке приложения"""
        import sys
        if getattr(sys, 'frozen', False):
            base = Path(sys._MEIPASS)
        else:
            base = Path(__file__).resolve().parent.parent
        return base / "resources" / "icons" / "app_icon.ico"
    
    def init_ui(self):
        """Инициализация интерфейса"""
        self.setWindowTitle(self.translator.tr('settings_title'))
        self.setMinimumSize(550, 450)
        
        # Устанавливаем иконку окна
        icon_path = self._get_icon_path()
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        
        layout = QVBoxLayout(self)
        
        # Вкладки настроек
        tabs = QTabWidget()
        tabs.addTab(self.create_server_tab(), self.translator.tr('server_url'))
        tabs.addTab(self.create_paths_tab(), self.translator.tr('reports_folder'))
        tabs.addTab(self.create_language_tab(), self.translator.tr('interface_language'))
        layout.addWidget(tabs)
        
        # Кнопки OK/Cancel
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.save_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    
    # ==========================================================================
    # Вкладка: Сервер
    # ==========================================================================
    
    def create_server_tab(self) -> QWidget:
        """Настройки подключения к серверу"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # URL сервера
        if self.translator.get_language() == 'ru':
            group_title = "Подключение к серверу"
        else:
            group_title = "Серверге қосылу"
        
        server_group = QGroupBox(group_title)
        server_layout = QVBoxLayout()
        server_layout.setSpacing(10)
        
        # URL
        url_label = QLabel(f"{self.translator.tr('server_url')}:")
        url_label.setStyleSheet("font-weight: 600; font-size: 13px;")
        server_layout.addWidget(url_label)
        
        url_row = QHBoxLayout()
        self.server_url_input = QLineEdit()
        self.server_url_input.setPlaceholderText(DEFAULT_SERVER_URL)
        self.server_url_input.setMinimumHeight(38)
        url_row.addWidget(self.server_url_input)
        
        check_text = "Проверить" if self.translator.get_language() == 'ru' else "Тексеру"
        self.check_btn = QPushButton(check_text)
        self.check_btn.setMinimumHeight(38)
        self.check_btn.setMinimumWidth(120)
        self.check_btn.clicked.connect(self.check_server_connection)
        url_row.addWidget(self.check_btn)
        
        server_layout.addLayout(url_row)
        
        # Статус подключения
        self.server_status = QLabel("")
        self.server_status.setWordWrap(True)
        self.server_status.setStyleSheet("color: #6c757d; font-size: 11px; padding: 5px 0;")
        server_layout.addWidget(self.server_status)
        
        # Подсказка
        if self.translator.get_language() == 'ru':
            hint = (
                "Укажите адрес сервера Mektep Platform.\n"
                f"По умолчанию: {DEFAULT_SERVER_URL}\n\n"
                "После изменения URL потребуется повторная авторизация."
            )
        else:
            hint = (
                "Mektep Platform серверінің мекенжайын көрсетіңіз.\n"
                f"Әдепкі: {DEFAULT_SERVER_URL}\n\n"
                "URL өзгертілгеннен кейін қайта авторизация қажет."
            )
        
        hint_label = QLabel(hint)
        hint_label.setWordWrap(True)
        hint_label.setStyleSheet("color: #6c757d; font-size: 11px; padding: 10px;")
        server_layout.addWidget(hint_label)
        
        server_group.setLayout(server_layout)
        layout.addWidget(server_group)
        
        layout.addStretch()
        return widget
    
    def check_server_connection(self):
        """Проверить подключение к серверу"""
        url = self.server_url_input.text().strip()
        if not url:
            url = DEFAULT_SERVER_URL
            self.server_url_input.setText(url)
        
        self.check_btn.setEnabled(False)
        check_text = "Проверка..." if self.translator.get_language() == 'ru' else "Тексеруде..."
        self.check_btn.setText(check_text)
        self.server_status.setText("🔄 " + check_text)
        self.server_status.setStyleSheet("color: #0d6efd; font-size: 11px; padding: 5px 0;")
        
        self._check_thread = _ConnectionCheckThread(url)
        self._check_thread.finished.connect(self._on_check_finished)
        self._check_thread.start()
    
    def _on_check_finished(self, result: dict):
        """Обработка результата проверки"""
        check_text = "Проверить" if self.translator.get_language() == 'ru' else "Тексеру"
        self.check_btn.setText(check_text)
        self.check_btn.setEnabled(True)
        
        if result.get("success"):
            latency = result.get("latency_ms", 0)
            if self.translator.get_language() == 'ru':
                msg = f"✅ Подключение установлено ({latency} мс)"
            else:
                msg = f"✅ Қосылым орнатылды ({latency} мс)"
            self.server_status.setText(msg)
            self.server_status.setStyleSheet("color: #198754; font-size: 11px; padding: 5px 0;")
        else:
            error = result.get("error", "")
            if self.translator.get_language() == 'ru':
                msg = f"❌ Нет подключения: {error}"
            else:
                msg = f"❌ Қосылу жоқ: {error}"
            self.server_status.setText(msg)
            self.server_status.setStyleSheet("color: #dc3545; font-size: 11px; padding: 5px 0;")
    
    # ==========================================================================
    # Вкладка: Папка отчётов
    # ==========================================================================
    
    def create_paths_tab(self) -> QWidget:
        """Настройки пути для отчетов"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Папка для отчетов
        reports_group = QGroupBox(self.translator.tr('reports_folder'))
        reports_layout = QVBoxLayout()
        reports_layout.setSpacing(10)
        
        reports_path_layout = QHBoxLayout()
        self.reports_path_input = QLineEdit()
        self.reports_path_input.setMinimumHeight(35)
        reports_path_layout.addWidget(self.reports_path_input)
        
        browse_reports_btn = QPushButton(f"📁 {self.translator.tr('browse')}")
        browse_reports_btn.setMinimumHeight(35)
        browse_reports_btn.setMinimumWidth(120)
        browse_reports_btn.clicked.connect(
            lambda: self.browse_directory(self.reports_path_input)
        )
        reports_path_layout.addWidget(browse_reports_btn)
        reports_layout.addLayout(reports_path_layout)
        
        reports_group.setLayout(reports_layout)
        layout.addWidget(reports_group)
        
        layout.addStretch()
        return widget
    
    # ==========================================================================
    # Вкладка: Язык
    # ==========================================================================
    
    def create_language_tab(self) -> QWidget:
        """Настройки языка интерфейса"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Выбор языка
        lang_group = QGroupBox(self.translator.tr('interface_language'))
        lang_layout = QVBoxLayout()
        lang_layout.setSpacing(10)
        
        self.language_combo = QComboBox()
        self.language_combo.setMinimumHeight(35)
        
        # Добавляем языки
        available_langs = self.translator.get_available_languages()
        for lang_code, lang_name in available_langs.items():
            self.language_combo.addItem(lang_name, lang_code)
        
        lang_layout.addWidget(self.language_combo)
        
        # Информационное сообщение
        info_label = QLabel(self.translator.tr('language_change_note'))
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #6c757d; font-size: 11px; padding: 10px;")
        lang_layout.addWidget(info_label)
        
        lang_group.setLayout(lang_layout)
        layout.addWidget(lang_group)
        
        layout.addStretch()
        return widget
    
    # ==========================================================================
    # Общие методы
    # ==========================================================================
    
    def browse_directory(self, line_edit: QLineEdit):
        """Выбор директории"""
        current_path = line_edit.text() or str(Path.home())
        folder = QFileDialog.getExistingDirectory(
            self,
            "Выберите папку",
            current_path
        )
        if folder:
            line_edit.setText(folder)
    
    def load_settings(self):
        """Загрузка текущих настроек"""
        # URL сервера
        self.server_url_input.setText(
            self.settings.value("server/url", DEFAULT_SERVER_URL)
        )
        
        # Путь к отчетам
        self.reports_path_input.setText(
            self.settings.value(
                "storage/path",
                str(Path.home() / "Documents" / "Mektep Reports")
            )
        )
        
        # Язык интерфейса
        current_lang = self.settings.value("language", "ru")
        index = self.language_combo.findData(current_lang)
        if index >= 0:
            self.language_combo.setCurrentIndex(index)
    
    def save_and_accept(self):
        """Сохранение настроек и закрытие"""
        # URL сервера
        old_url = self.settings.value("server/url", DEFAULT_SERVER_URL)
        new_url = self.server_url_input.text().strip() or DEFAULT_SERVER_URL
        self.settings.setValue("server/url", new_url)
        
        # Путь к отчетам
        self.settings.setValue("storage/path", self.reports_path_input.text())
        
        # Язык интерфейса
        old_lang = self.settings.value("language", "ru")
        new_lang = self.language_combo.currentData()
        self.settings.setValue("language", new_lang)
        
        # Если URL сервера изменился, очищаем токен (нужен повторный вход)
        if old_url != new_url:
            self.settings.remove("auth/token")
            self.settings.remove("auth/token_expires")
            self.settings.remove("auth/user_data")
            
            if self.translator.get_language() == 'ru':
                msg = "Адрес сервера изменён.\nТребуется повторная авторизация при следующем запуске."
            else:
                msg = "Сервер мекенжайы өзгертілді.\nКелесі іске қосуда қайта авторизация қажет."
            
            QMessageBox.information(self, self.translator.tr('info'), msg)
        
        # Если язык изменился, показываем сообщение
        if old_lang != new_lang:
            QMessageBox.information(
                self,
                self.translator.tr('info'),
                self.translator.tr('language_change_note')
            )
        
        self.accept()
