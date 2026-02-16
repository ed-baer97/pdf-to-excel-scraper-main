"""
Mektep Desktop - главная точка входа

Десктопное приложение для автоматизации создания отчетов из mektep.edu.kz
"""
import os
import sys
from pathlib import Path

# Защита stdout/stderr для frozen PyInstaller builds (console=False → stdout is None)
if getattr(sys, 'frozen', False):
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QFont, QPalette, QColor, QIcon

from app.main_window import MektepMainWindow
from app.login_dialog import LoginDialog
from app.api_client import MektepAPIClient, DEFAULT_SERVER_URL


def _get_icon_path() -> Path:
    """Путь к иконке приложения (работает в dev и в скомпилированном виде)."""
    if getattr(sys, 'frozen', False):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).resolve().parent
    return base / "resources" / "icons" / "app_icon.ico"


def main():
    """Запуск приложения"""
    # Устанавливаем AppUserModelID для корректного отображения иконки в панели задач Windows
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('mektep.desktop.app.1')
    except (ImportError, AttributeError, OSError):
        pass  # Не Windows — пропускаем
    
    app = QApplication(sys.argv)
    
    # Установка стиля приложения
    app.setStyle("Fusion")
    
    # Шрифт по умолчанию
    app.setFont(QFont("Segoe UI", 9))
    
    # Установка иконки приложения (заголовок окна, панель задач, меню Пуск)
    icon_path = _get_icon_path()
    if icon_path.exists():
        app_icon = QIcon(str(icon_path))
        app.setWindowIcon(app_icon)
    else:
        app_icon = None
    
    # Палитра: тёмный текст на светлом фоне (чтобы всплывающие окна были читаемы при любой теме)
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(33, 37, 41))
    palette.setColor(QPalette.ColorRole.Base, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.Text, QColor(33, 37, 41))
    app.setPalette(palette)
    
    # Стили для диалогов: все дочерние виджеты — читаемый текст
    app.setStyleSheet("""
        QMessageBox, QMessageBox * { color: #212529; background-color: #ffffff; }
        QProgressDialog, QProgressDialog * { color: #212529; background-color: #ffffff; }
        QInputDialog, QInputDialog * { color: #212529; background-color: #ffffff; }
    """)
    
    # Настройки
    settings = QSettings("Mektep", "MektepDesktop")
    
    # Загружаем URL сервера из настроек
    server_url = settings.value("server/url", DEFAULT_SERVER_URL)
    
    # API клиент (подключение к настроенному серверу)
    api_client = MektepAPIClient(server_url)
    
    # Показываем окно логина
    login_dialog = LoginDialog(api_client)
    
    if login_dialog.exec():
        # Успешная авторизация
        if not login_dialog.is_authenticated():
            QMessageBox.critical(
                None,
                "Ошибка",
                "Не удалось авторизоваться.\nПриложение будет закрыто."
            )
            return 1
        
        # Получаем данные пользователя
        user_data = login_dialog.get_user_data()
        
        # Создание и отображение главного окна
        window = MektepMainWindow(api_client=api_client, user_data=user_data)
        window.show()
        
        return app.exec()
    else:
        # Пользователь закрыл окно логина
        return 0


if __name__ == "__main__":
    sys.exit(main())
