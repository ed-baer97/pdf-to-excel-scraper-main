"""
Login Dialog - окно авторизации при запуске

Авторизация на сервере перед использованием приложения.
Поддерживает:
- Автоматический вход по сохранённому токену
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QMessageBox, QFrame, QCheckBox, QWidget
)
from PyQt6.QtCore import Qt, QSettings, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QFont

from .api_client import MektepAPIClient, DEFAULT_SERVER_URL
from .translator import get_translator


class TokenRestoreThread(QThread):
    """Поток для восстановления токена (не блокирует UI)"""
    finished = pyqtSignal(bool)
    
    def __init__(self, api_client: MektepAPIClient, token: str, expires: str, user_data: dict):
        super().__init__()
        self.api_client = api_client
        self.token = token
        self.expires = expires
        self.user_data = user_data
    
    def run(self):
        ok = self.api_client.restore_token(self.token, self.expires, self.user_data)
        self.finished.emit(ok)


class LoginDialog(QDialog):
    """Диалог авторизации"""
    
    def __init__(self, api_client: MektepAPIClient, parent=None):
        super().__init__(parent)
        self.api_client = api_client
        self.settings = QSettings("Mektep", "MektepDesktop")
        self.translator = get_translator()
        self.authenticated = False
        self.user_data = None
        self._restore_thread = None
        
        # Загрузить язык из настроек
        saved_lang = self.settings.value("language", "ru")
        self.translator.set_language(saved_lang)
        
        self.init_ui()
        self.load_saved_credentials()
    
    def init_ui(self):
        """Инициализация интерфейса"""
        self.setWindowTitle(self.translator.tr('login_title'))
        self.setFixedSize(480, 550)
        self.setModal(True)
        
        # Устанавливаем иконку окна
        from PyQt6.QtGui import QIcon
        icon_path = self._get_icon_path()
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        
        # Основной layout
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # Контейнер для кнопок языка
        lang_container = QWidget()
        lang_container.setFixedHeight(50)
        lang_container_layout = QHBoxLayout(lang_container)
        lang_container_layout.setContentsMargins(0, 10, 15, 10)
        lang_container_layout.addStretch()
        
        self.ru_btn = QPushButton("РУ")
        self.ru_btn.setFixedSize(50, 32)
        self.ru_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ru_btn.clicked.connect(lambda: self.switch_language('ru'))
        lang_container_layout.addWidget(self.ru_btn)
        
        lang_container_layout.addSpacing(8)
        
        self.kk_btn = QPushButton("ҚЗ")
        self.kk_btn.setFixedSize(50, 32)
        self.kk_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.kk_btn.clicked.connect(lambda: self.switch_language('kk'))
        lang_container_layout.addWidget(self.kk_btn)
        
        main_layout.addWidget(lang_container)
        
        # Основной контент
        layout = QVBoxLayout()
        layout.setSpacing(20)
        layout.setContentsMargins(40, 10, 40, 40)
        main_layout.addLayout(layout)
        
        # Обновить стили кнопок языка
        self.update_language_buttons()
        
        # Логотип / Заголовок
        title_label = QLabel(self.translator.tr('app_name'))
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_font = QFont("Segoe UI", 24, QFont.Weight.Bold)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: #0d6efd; margin-bottom: 10px;")
        layout.addWidget(title_label)
        
        subtitle_label = QLabel(self.translator.tr('login_subtitle'))
        subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle_label.setStyleSheet("color: #6c757d; font-size: 13px;")
        layout.addWidget(subtitle_label)
        
        layout.addSpacing(20)
        
        # Карточка с формой
        card = QFrame()
        card.setObjectName("loginCard")
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(0)
        card_layout.setContentsMargins(35, 35, 35, 35)
        
        # Поле логина
        username_label = QLabel(f"{self.translator.tr('username')}:")
        username_label.setStyleSheet("font-weight: 600; color: #212529; font-size: 14px;")
        card_layout.addWidget(username_label)
        
        card_layout.addSpacing(8)
        
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText(self.translator.tr('username'))
        self.username_input.setMinimumHeight(44)
        self.username_input.returnPressed.connect(self.handle_login)
        card_layout.addWidget(self.username_input)
        
        card_layout.addSpacing(15)
        
        # Поле пароля
        password_label = QLabel(f"{self.translator.tr('password')}:")
        password_label.setStyleSheet("font-weight: 600; color: #212529; font-size: 14px;")
        card_layout.addWidget(password_label)
        
        card_layout.addSpacing(8)
        
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText(self.translator.tr('password'))
        self.password_input.setMinimumHeight(44)
        self.password_input.returnPressed.connect(self.handle_login)
        card_layout.addWidget(self.password_input)
        
        card_layout.addSpacing(15)
        
        # Чекбокс "Запомнить меня"
        self.remember_checkbox = QCheckBox(self.translator.tr('remember_me'))
        self.remember_checkbox.setStyleSheet("color: #495057;")
        card_layout.addWidget(self.remember_checkbox)
        
        card_layout.addSpacing(10)
        
        # Кнопка входа
        self.login_btn = QPushButton(self.translator.tr('login_button'))
        self.login_btn.setMinimumHeight(45)
        self.login_btn.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self.login_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.login_btn.clicked.connect(self.handle_login)
        card_layout.addWidget(self.login_btn)
        
        card_layout.addSpacing(20)
        
        # Статус (с фиксированной высотой чтобы не прыгал интерфейс)
        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)
        self.status_label.setMinimumHeight(40)
        self.status_label.setStyleSheet("color: #6c757d; font-size: 12px;")
        card_layout.addWidget(self.status_label)
        
        layout.addWidget(card)
        layout.addStretch()
        
        # Применение стилей
        self.apply_styles()
    
    def apply_styles(self):
        """Применение стилей к диалогу"""
        self.setStyleSheet("""
            QDialog {
                background-color: #f8f9fa;
            }
            
            QFrame#loginCard {
                background-color: white;
                border-radius: 10px;
                border: 1px solid #dee2e6;
            }
            
            QLineEdit {
                padding: 10px 12px;
                border: 2px solid #ced4da;
                border-radius: 6px;
                background-color: white;
                font-size: 14px;
                color: #000000;
            }
            
            QLineEdit:focus {
                border: 2px solid #0d6efd;
                background-color: white;
                outline: none;
            }
            
            QLineEdit::placeholder {
                color: #6c757d;
            }
            
            QPushButton#loginBtn, QPushButton {
                background-color: #0d6efd;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 12px;
                font-size: 14px;
            }
            
            QPushButton:hover {
                background-color: #0b5ed7;
            }
            
            QPushButton:pressed {
                background-color: #0a58ca;
            }
            
            QPushButton:disabled {
                background-color: #6c757d;
            }
            
            QCheckBox {
                font-size: 14px;
                spacing: 8px;
                padding: 8px 0;
            }
            
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border: 2px solid #ced4da;
                border-radius: 4px;
                background-color: white;
            }
            
            QCheckBox::indicator:hover {
                border-color: #0d6efd;
            }
            
            QCheckBox::indicator:checked {
                background-color: #0d6efd;
                border-color: #0d6efd;
            }
            
            QCheckBox::indicator:checked:hover {
                background-color: #0b5ed7;
                border-color: #0b5ed7;
            }
        """)
    
    def load_saved_credentials(self):
        """Загрузка сохраненных учетных данных"""
        saved_username = self.settings.value("auth/username", "")
        saved_remember = self.settings.value("auth/remember", False, type=bool)
        
        if saved_username and saved_remember:
            self.username_input.setText(saved_username)
            self.remember_checkbox.setChecked(True)
            self.password_input.setFocus()
        else:
            self.username_input.setFocus()
    
    # ==========================================================================
    # Автоматический вход по сохранённому токену
    # ==========================================================================
    
    def try_auto_login(self):
        """Попытка автоматического входа по сохранённому токену"""
        saved_token = self.settings.value("auth/token", "")
        saved_expires = self.settings.value("auth/token_expires", "")
        saved_user_data_str = self.settings.value("auth/user_data", "")
        
        if not saved_token or not saved_expires:
            return
        
        # Парсим user_data из JSON
        import json
        try:
            user_data = json.loads(saved_user_data_str) if saved_user_data_str else {}
        except (json.JSONDecodeError, TypeError):
            user_data = {}
        
        # Показываем статус
        auto_msg = "Автоматический вход..." if self.translator.get_language() == 'ru' else "Автоматты кіру..."
        self.status_label.setText(f"🔄 {auto_msg}")
        self.status_label.setStyleSheet("color: #0d6efd; font-size: 12px;")
        self.login_btn.setEnabled(False)
        
        # Запускаем восстановление токена в потоке
        self._restore_thread = TokenRestoreThread(
            self.api_client, saved_token, saved_expires, user_data
        )
        self._restore_thread.finished.connect(self._on_token_restored)
        self._restore_thread.start()
    
    def _on_token_restored(self, success: bool):
        """Обработка результата восстановления токена"""
        if success:
            self.user_data = self.api_client.user_data
            self.authenticated = True
            
            if self.translator.get_language() == 'ru':
                msg = "Автоматический вход выполнен"
            else:
                msg = "Автоматты кіру орындалды"
            self.status_label.setText(f"✅ {msg}")
            self.status_label.setStyleSheet("color: #198754; font-size: 12px;")
            
            # Обновляем сохранённый токен
            self._save_token()
            
            QTimer.singleShot(500, self.accept)
        else:
            # Токен невалиден — очищаем и показываем форму
            self.settings.remove("auth/token")
            self.settings.remove("auth/token_expires")
            self.settings.remove("auth/user_data")
            
            self.login_btn.setEnabled(True)
            self.status_label.setText("")
    
    # ==========================================================================
    # Авторизация
    # ==========================================================================
    
    def handle_login(self):
        """Обработка входа"""
        username = self.username_input.text().strip()
        password = self.password_input.text().strip()
        
        if not username or not password:
            self.status_label.setText(f"⚠️ {self.translator.tr('fill_all_fields')}")
            self.status_label.setStyleSheet("color: #ffc107; font-size: 12px;")
            return
        
        # Блокируем UI
        self.login_btn.setEnabled(False)
        self.login_btn.setText(self.translator.tr('logging_in'))
        self.status_label.setText(f"🔄 {self.translator.tr('logging_in')}")
        self.status_label.setStyleSheet("color: #0d6efd; font-size: 12px;")
        
        # Небольшая задержка для UI
        QTimer.singleShot(100, lambda: self.perform_login(username, password))
    
    def perform_login(self, username: str, password: str):
        """Выполнение авторизации"""
        # Авторизация на сервере
        result = self.api_client.login(username, password)
        
        if result.get("success"):
            # Успешная авторизация
            self.user_data = result.get("user", {})
            self.authenticated = True
            
            # Сохраняем учетные данные если "Запомнить меня"
            if self.remember_checkbox.isChecked():
                self.settings.setValue("auth/username", self.username_input.text())
                self.settings.setValue("auth/remember", True)
            else:
                self.settings.remove("auth/username")
                self.settings.setValue("auth/remember", False)
            
            # Сохраняем токен для автоматического входа
            self._save_token()
            
            self.status_label.setText("✅ " + self.translator.tr('login_button'))
            self.status_label.setStyleSheet("color: #198754; font-size: 12px;")
            
            QTimer.singleShot(500, self.accept)
            
        elif result.get("offline"):
            # Сервер недоступен
            self.login_btn.setEnabled(True)
            self.login_btn.setText(self.translator.tr('login_button'))
            self.status_label.setText(f"❌ {self.translator.tr('connection_error')}")
            self.status_label.setStyleSheet("color: #dc3545; font-size: 12px;")
            
            QMessageBox.critical(
                self,
                self.translator.tr('connection_error'),
                self.translator.tr('check_connection')
            )
        else:
            # Ошибка авторизации
            self.login_btn.setEnabled(True)
            self.login_btn.setText(self.translator.tr('login_button'))
            error_msg = result.get("error", self.translator.tr('invalid_credentials'))
            self.status_label.setText(f"❌ {error_msg}")
            self.status_label.setStyleSheet("color: #dc3545; font-size: 12px;")
            
            # Фокус на пароль для повторного ввода
            self.password_input.clear()
            self.password_input.setFocus()
    
    def _save_token(self):
        """Сохранить токен в QSettings для автоматического входа"""
        import json
        token_info = self.api_client.get_token_info()
        if token_info:
            self.settings.setValue("auth/token", token_info["token"])
            self.settings.setValue("auth/token_expires", token_info["expires"])
            self.settings.setValue("auth/user_data", json.dumps(
                token_info["user_data"], ensure_ascii=False
            ))
    
    @staticmethod
    def _get_icon_path() -> 'Path':
        """Путь к иконке приложения"""
        import sys
        from pathlib import Path
        if getattr(sys, 'frozen', False):
            base = Path(sys._MEIPASS)
        else:
            base = Path(__file__).resolve().parent.parent
        return base / "resources" / "icons" / "app_icon.ico"
    
    def is_authenticated(self) -> bool:
        """Проверка успешной авторизации"""
        return self.authenticated
    
    def get_user_data(self) -> dict:
        """Получение данных пользователя"""
        return self.user_data or {}
    
    def switch_language(self, lang: str):
        """Переключение языка"""
        self.settings.setValue("language", lang)
        self.translator.set_language(lang)
        
        # Обновляем интерфейс
        self.setWindowTitle(self.translator.tr('login_title'))
        
        # Обновляем метки
        for label in self.findChildren(QLabel):
            text = label.text()
            if text.endswith(":"):
                key_text = text[:-1].strip()
                if "Логин" in key_text or "Login" in key_text:
                    label.setText(f"{self.translator.tr('username')}:")
                elif "Пароль" in key_text or "Құпия сөз" in key_text or "Password" in key_text:
                    label.setText(f"{self.translator.tr('password')}:")
        
        # Обновляем placeholder'ы
        self.username_input.setPlaceholderText(self.translator.tr('username'))
        self.password_input.setPlaceholderText(self.translator.tr('password'))
        
        # Обновляем чекбокс
        self.remember_checkbox.setText(self.translator.tr('remember_me'))
        
        # Обновляем кнопку входа
        self.login_btn.setText(self.translator.tr('login_button'))
        
        # Обновляем стили кнопок языка
        self.update_language_buttons()
    
    def update_language_buttons(self):
        """Обновить стили кнопок выбора языка"""
        current_lang = self.translator.get_language()
        
        # Стиль для активной кнопки
        active_style = """
            QPushButton {
                background-color: #0d6efd;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
                font-size: 12px;
                padding: 0px;
                text-align: center;
            }
            QPushButton:hover {
                background-color: #0b5ed7;
            }
        """
        
        # Стиль для неактивной кнопки
        inactive_style = """
            QPushButton {
                background-color: white;
                color: #0d6efd;
                border: 2px solid #0d6efd;
                border-radius: 4px;
                font-weight: bold;
                font-size: 12px;
                padding: 0px;
                text-align: center;
            }
            QPushButton:hover {
                background-color: #e7f1ff;
            }
        """
        
        if current_lang == 'ru':
            self.ru_btn.setStyleSheet(active_style)
            self.kk_btn.setStyleSheet(inactive_style)
        else:
            self.ru_btn.setStyleSheet(inactive_style)
            self.kk_btn.setStyleSheet(active_style)
