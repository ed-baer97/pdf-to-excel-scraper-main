"""
Settings Dialog - диалог настроек приложения

Сохранение настроек через QSettings.
"""
from pathlib import Path
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QLabel, QLineEdit, QPushButton, QCheckBox, QSpinBox,
    QComboBox, QGroupBox, QFileDialog, QDialogButtonBox, QMessageBox
)
from PyQt6.QtCore import QSettings

from .translator import get_translator


class SettingsDialog(QDialog):
    """Диалог настроек"""
    
    def __init__(self, settings: QSettings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.translator = get_translator()
        self.init_ui()
        self.load_settings()
    
    def init_ui(self):
        """Инициализация интерфейса"""
        self.setWindowTitle(self.translator.tr('settings_title'))
        self.setMinimumSize(550, 400)
        
        layout = QVBoxLayout(self)
        
        # Вкладки настроек
        tabs = QTabWidget()
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
    
    # Удалены методы: create_server_tab, create_scraping_tab, create_ai_tab
    
    def _old_create_server_tab(self) -> QWidget:
        """Вкладка настроек сервера"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # URL сервера
        server_group = QGroupBox("API Сервер")
        server_layout = QVBoxLayout()
        
        url_layout = QHBoxLayout()
        url_layout.addWidget(QLabel("URL:"))
        self.server_url_input = QLineEdit()
        self.server_url_input.setPlaceholderText("http://localhost:5000")
        url_layout.addWidget(self.server_url_input)
        server_layout.addLayout(url_layout)
        
        server_group.setLayout(server_layout)
        layout.addWidget(server_group)
        
        # Учетные данные веб-приложения
        webapp_group = QGroupBox("Веб-приложение (опционально)")
        webapp_layout = QVBoxLayout()
        
        webapp_login_layout = QHBoxLayout()
        webapp_login_layout.addWidget(QLabel("Логин:"))
        self.webapp_login_input = QLineEdit()
        self.webapp_login_input.setPlaceholderText("Ваш логин для веб-приложения")
        webapp_login_layout.addWidget(self.webapp_login_input)
        webapp_layout.addLayout(webapp_login_layout)
        
        webapp_password_layout = QHBoxLayout()
        webapp_password_layout.addWidget(QLabel("Пароль:"))
        self.webapp_password_input = QLineEdit()
        self.webapp_password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.webapp_password_input.setPlaceholderText("Пароль для веб-приложения")
        webapp_password_layout.addWidget(self.webapp_password_input)
        webapp_layout.addLayout(webapp_password_layout)
        
        webapp_info = QLabel(
            "Эти данные используются для входа в веб-версию платформы\n"
            "и проверки квоты на успешные скрапы."
        )
        webapp_info.setWordWrap(True)
        webapp_info.setStyleSheet("color: gray; font-size: 10px;")
        webapp_layout.addWidget(webapp_info)
        
        webapp_group.setLayout(webapp_layout)
        layout.addWidget(webapp_group)
        
        layout.addStretch()
        return tab
    
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
        # Путь к отчетам
        self.settings.setValue("storage/path", self.reports_path_input.text())
        
        # Язык интерфейса
        old_lang = self.settings.value("language", "ru")
        new_lang = self.language_combo.currentData()
        self.settings.setValue("language", new_lang)
        
        # Если язык изменился, показываем сообщение
        if old_lang != new_lang:
            QMessageBox.information(
                self,
                self.translator.tr('info'),
                self.translator.tr('language_change_note')
            )
        
        self.accept()
