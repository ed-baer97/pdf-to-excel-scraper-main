"""
Mektep Desktop - главная точка входа

Десктопное приложение для автоматизации создания отчетов из mektep.edu.kz
"""
import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QFont, QPalette, QColor

from app.main_window import MektepMainWindow
from app.login_dialog import LoginDialog
from app.api_client import MektepAPIClient


def main():
    """Запуск приложения"""
    app = QApplication(sys.argv)
    
    # Установка стиля приложения
    app.setStyle("Fusion")
    
    # Шрифт по умолчанию
    app.setFont(QFont("Segoe UI", 9))
    
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
    
    # API клиент (подключение по умолчанию к localhost)
    api_client = MektepAPIClient("http://localhost:5000")
    
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
