"""
Main Window - главное окно приложения Mektep Desktop
"""
import sys
from pathlib import Path
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QProgressBar,
    QTextEdit, QGroupBox, QMessageBox, QFileDialog, QFrame,
    QFormLayout, QScrollArea, QTabWidget
)
from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QFont, QIcon

from .api_client import MektepAPIClient, DEFAULT_SERVER_URL
from .scraper_thread import ScraperThread
from .reports_manager import ReportsManager
from .history_widget import HistoryWidget
from .goals_dialog import GoalsDialog
from .settings_dialog import SettingsDialog
from .translator import get_translator
from .grades_widget import GradesWidget
from .subject_report_widget import SubjectReportWidget
from .class_report_widget import ClassReportWidget


class MektepMainWindow(QMainWindow):
    """Главное окно приложения"""
    
    def __init__(self, api_client: MektepAPIClient = None, user_data: dict = None):
        super().__init__()
        
        # Настройки приложения
        self.settings = QSettings("Mektep", "MektepDesktop")
        
        # Переводчик
        self.translator = get_translator()
        saved_lang = self.settings.value("language", "ru")
        self.translator.set_language(saved_lang)
        
        # API клиент
        self.api_client = api_client or MektepAPIClient(DEFAULT_SERVER_URL)
        
        # Данные пользователя
        self.user_data = user_data or {}
        
        # Менеджер отчетов (с привязкой к текущему пользователю)
        storage_path = Path(self.settings.value(
            "storage/path",
            str(Path.home() / "Documents" / "Mektep Reports")
        ))
        current_username = self.user_data.get("username", "")
        self.reports_manager = ReportsManager(storage_path, username=current_username)
        
        # Поток скрапинга
        self.scraper_thread = None
        
        # Инициализация UI
        self.init_ui()
        
        # Загрузка сохраненных настроек
        self.load_settings()
    
    @staticmethod
    def _get_icon_path() -> Path:
        """Путь к иконке приложения"""
        if getattr(sys, 'frozen', False):
            base = Path(sys._MEIPASS)
        else:
            base = Path(__file__).resolve().parent.parent
        return base / "resources" / "icons" / "app_icon.ico"
    
    def init_ui(self):
        """Инициализация интерфейса"""
        username = self.user_data.get("username", self.translator.tr('user'))
        title = self.translator.tr('main_window_title', username)
        
        self.setWindowTitle(title)
        self.setMinimumSize(1100, 700)
        
        # Устанавливаем иконку окна
        icon_path = self._get_icon_path()
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        
        # Центральный виджет
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # Информационная панель пользователя
        self.create_user_info_panel(main_layout)
        
        # Две колонки: слева создание отчетов, справа история
        columns_layout = QHBoxLayout()
        columns_layout.setSpacing(15)
        
        # Левая колонка - Создание отчетов
        self.left_panel = self.create_reports_panel()
        columns_layout.addWidget(self.left_panel, 4)  # 40% ширины
        
        # Правая колонка - Мои отчеты
        right_panel = self.create_history_panel()
        columns_layout.addWidget(right_panel, 6)  # 60% ширины
        
        main_layout.addLayout(columns_layout)
        
        # Применение стилей
        self.apply_styles()
    
    def create_user_info_panel(self, parent_layout):
        """Создание информационной панели пользователя"""
        info_frame = QFrame()
        info_frame.setObjectName("userInfoPanel")
        info_frame.setMaximumHeight(60)
        
        info_layout = QHBoxLayout(info_frame)
        info_layout.setContentsMargins(15, 10, 15, 10)
        
        # Информация о пользователе
        username = self.user_data.get("username", self.translator.tr('user'))
        
        user_label = QLabel(f"{username}")
        user_label.setStyleSheet("font-weight: bold; color: #212529;")
        info_layout.addWidget(user_label)
        
        # Индикатор подключения к серверу
        server_url = self.settings.value("server/url", DEFAULT_SERVER_URL)
        # Показываем только домен для компактности
        try:
            from urllib.parse import urlparse
            parsed = urlparse(server_url)
            server_display = parsed.netloc or server_url
        except Exception:
            server_display = server_url
        
        self.connection_indicator = QLabel(f"🟢 {server_display}")
        self.connection_indicator.setStyleSheet("color: #198754; font-size: 11px;")
        info_layout.addWidget(self.connection_indicator)
        
        info_layout.addStretch()
        
        # Кнопка скрытия/показа панели создания отчетов
        toggle_text = "◀ Скрыть панель" if self.translator.get_language() == 'ru' else "◀ Панельді жасыру"
        self.toggle_btn = QPushButton(toggle_text)
        self.toggle_btn.setFixedWidth(140)
        self.toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_btn.setObjectName("togglePanelBtn")
        self.toggle_btn.clicked.connect(self.toggle_reports_panel)
        info_layout.addWidget(self.toggle_btn)
        
        # Кнопка настроек
        settings_btn = QPushButton(self.translator.tr('settings'))
        settings_btn.setFixedWidth(100)
        settings_btn.clicked.connect(self.open_settings)
        info_layout.addWidget(settings_btn)
        
        # Кнопка выхода
        logout_btn = QPushButton(self.translator.tr('logout'))
        logout_btn.setFixedWidth(100)
        logout_btn.clicked.connect(self.logout)
        info_layout.addWidget(logout_btn)
        
        parent_layout.addWidget(info_frame)
    
    def create_reports_panel(self) -> QWidget:
        """Панель создания отчетов (левая колонка)"""
        panel = QFrame()
        panel.setObjectName("card")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(15, 15, 15, 15)
        panel_layout.setSpacing(12)
        
        # Заголовок панели
        create_reports = "Создание отчетов" if self.translator.get_language() == 'ru' else "Есептер жасау"
        title = QLabel(create_reports)
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #212529;")
        panel_layout.addWidget(title)
        
        # Скролл для содержимого
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(12)
        content_layout.setContentsMargins(0, 0, 0, 0)

        # === Блок авторизации ===
        login_text = "Вход в mektep.edu.kz" if self.translator.get_language() == 'ru' else "mektep.edu.kz-ге кіру"
        auth_group = QGroupBox(login_text)
        auth_layout = QVBoxLayout(auth_group)
        auth_layout.setSpacing(8)

        portal_info = "Введите данные от образовательного портала" if self.translator.get_language() == 'ru' else "Білім порталының деректерін енгізіңіз"
        info_label = QLabel(portal_info)
        info_label.setStyleSheet("color: #666; font-size: 11px;")
        auth_layout.addWidget(info_label)

        auth_form = QFormLayout()
        auth_form.setHorizontalSpacing(10)
        auth_form.setVerticalSpacing(8)

        self.login_input = QLineEdit()
        login_placeholder = "ИИН или Логин" if self.translator.get_language() == 'ru' else "ЖСН немесе Логин"
        self.login_input.setPlaceholderText(login_placeholder)
        self.login_input.setMinimumHeight(30)
        auth_form.addRow(f"{self.translator.tr('mektep_login')}:", self.login_input)

        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText(self.translator.tr('mektep_password'))
        self.password_input.setMinimumHeight(30)
        auth_form.addRow(f"{self.translator.tr('password')}:", self.password_input)

        auth_layout.addLayout(auth_form)
        content_layout.addWidget(auth_group)

        # === Блок параметров ===
        report_settings = "Настройки отчета" if self.translator.get_language() == 'ru' else "Есеп баптаулары"
        params_group = QGroupBox(report_settings)
        params_layout = QFormLayout(params_group)
        params_layout.setHorizontalSpacing(10)
        params_layout.setVerticalSpacing(8)

        self.lang_combo = QComboBox()
        self.lang_combo.addItems(["Русский", "Қазақша", "English"])
        self.lang_combo.setMinimumHeight(30)
        # Явно устанавливаем стиль для view
        self.lang_combo.view().setStyleSheet("background-color: white; color: #212529;")
        lang_label = "Язык" if self.translator.get_language() == 'ru' else "Тіл"
        params_layout.addRow(f"{lang_label}:", self.lang_combo)

        self.period_combo = QComboBox()
        if self.translator.get_language() == 'kk':
            self.period_combo.addItems([
                "1 тоқсан",
                "2 тоқсан (1 жартыжылдық)",
                "3 тоқсан",
                "4 тоқсан (2 жартыжылдық)"
            ])
        else:
            self.period_combo.addItems([
                "1 четверть",
                "2 четверть (1 полугодие)",
                "3 четверть",
                "4 четверть (2 полугодие)"
            ])
        self.period_combo.setCurrentIndex(1)
        self.period_combo.setMinimumHeight(30)
        # Явно устанавливаем стиль для view
        self.period_combo.view().setStyleSheet("background-color: white; color: #212529;")
        period_label = "Период" if self.translator.get_language() == 'ru' else "Кезең"
        params_layout.addRow(f"{period_label}:", self.period_combo)

        folder_container = QWidget()
        folder_layout = QHBoxLayout(folder_container)
        folder_layout.setContentsMargins(0, 0, 0, 0)
        folder_layout.setSpacing(5)

        self.output_input = QLineEdit()
        self.output_input.setMinimumHeight(30)
        default_path = str(Path.home() / "Documents" / "Mektep Reports")
        self.output_input.setText(default_path)
        folder_layout.addWidget(self.output_input, 3)

        select_folder = "Выбрать папку" if self.translator.get_language() == 'ru' else "Қалтаны таңдау"
        self.browse_btn = QPushButton(select_folder)
        self.browse_btn.setMinimumHeight(30)
        self.browse_btn.setMinimumWidth(110)
        self.browse_btn.clicked.connect(self.browse_folder)
        folder_layout.addWidget(self.browse_btn, 2)

        folder_label = "Папка" if self.translator.get_language() == 'ru' else "Қалта"
        params_layout.addRow(f"{folder_label}:", folder_container)
        content_layout.addWidget(params_group)

        # === Кнопка запуска ===
        start_text = "Начать создание отчетов" if self.translator.get_language() == 'ru' else "Есептер жасауды бастау"
        self.start_btn = QPushButton(start_text)
        self.start_btn.setObjectName("primaryAction")
        self.start_btn.setMinimumHeight(40)
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.clicked.connect(self.start_scraping)
        content_layout.addWidget(self.start_btn)

        # === Статус выполнения ===
        status_exec = "Статус выполнения" if self.translator.get_language() == 'ru' else "Орындалу күйі"
        status_group = QGroupBox(status_exec)
        status_layout = QVBoxLayout(status_group)
        status_layout.setSpacing(8)

        self.progress_label = QLabel(self.translator.tr('ready'))
        self.progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_layout.addWidget(self.progress_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimumHeight(20)
        self.progress_bar.setTextVisible(True)
        status_layout.addWidget(self.progress_bar)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(80)
        log_placeholder = "Здесь будет журнал событий..." if self.translator.get_language() == 'ru' else "Мұнда оқиғалар журналы болады..."
        self.log_text.setPlaceholderText(log_placeholder)
        status_layout.addWidget(self.log_text)

        # Контейнер для динамических кнопок выбора школы
        self.school_buttons_container = QWidget()
        self.school_buttons_layout = QVBoxLayout(self.school_buttons_container)
        self.school_buttons_layout.setSpacing(8)
        self.school_buttons_layout.setContentsMargins(0, 0, 0, 0)
        self.school_buttons_container.setVisible(False)
        status_layout.addWidget(self.school_buttons_container)

        self.stop_btn = QPushButton("Остановить процесс")
        self.stop_btn.setVisible(False)
        self.stop_btn.clicked.connect(self.stop_scraping)
        status_layout.addWidget(self.stop_btn)

        content_layout.addWidget(status_group)
        content_layout.addStretch()
        
        scroll.setWidget(content)
        panel_layout.addWidget(scroll)
        
        return panel
    
    def create_history_panel(self) -> QWidget:
        """Правая колонка — вкладки: История | Оценки | Предметник | Кл. руководитель"""
        panel = QFrame()
        panel.setObjectName("card")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(10, 10, 10, 10)
        panel_layout.setSpacing(0)

        # --- QTabWidget ---
        self.right_tabs = QTabWidget()
        self.right_tabs.setDocumentMode(True)

        # 1) Мои отчеты (История)
        self.history_widget = HistoryWidget(self.reports_manager)
        self.history_widget.goals_requested.connect(self.open_goals_dialog)
        self.right_tabs.addTab(self.history_widget, self.translator.tr('tab_my_reports'))

        # 2) Сводная таблица оценок
        self.grades_widget = GradesWidget(api_client=self.api_client)
        self.right_tabs.addTab(self.grades_widget, self.translator.tr('tab_grades'))

        # 3) Отчёт предметника
        self.subject_report_widget = SubjectReportWidget(api_client=self.api_client)
        self.right_tabs.addTab(self.subject_report_widget, self.translator.tr('tab_subject_report'))

        # 4) Отчёт классного руководителя
        self.class_report_widget = ClassReportWidget(api_client=self.api_client)
        self.right_tabs.addTab(self.class_report_widget, self.translator.tr('tab_class_teacher_report'))

        # Загружаем данные при переключении на вкладку
        self.right_tabs.currentChanged.connect(self._on_tab_changed)

        panel_layout.addWidget(self.right_tabs)
        return panel

    def _on_tab_changed(self, index: int):
        """Загрузка данных при переключении на вкладку кабинета учителя"""
        widget = self.right_tabs.widget(index)
        if isinstance(widget, GradesWidget):
            widget.load_data()
        elif isinstance(widget, SubjectReportWidget):
            widget.load_data()
        elif isinstance(widget, ClassReportWidget):
            widget.load_data()
        
    def browse_folder(self):
        """Выбор папки для отчетов"""
        select_folder_text = "Выберите папку для отчетов" if self.translator.get_language() == 'ru' else "Есептер үшін қалтаны таңдаңыз"
        folder = QFileDialog.getExistingDirectory(
            self,
            select_folder_text,
            self.output_input.text()
        )
        if folder:
            self.output_input.setText(folder)
            
    def open_goals_dialog(self):
        """Открыть диалог целей"""
        dialog = GoalsDialog(self.reports_manager, self.user_data, self)
        dialog.exec()
    
    def load_settings(self):
        """Загрузка сохраненных настроек"""
        # Язык
        saved_lang = self.settings.value("scraper/lang", "Русский")
        index = self.lang_combo.findText(saved_lang)
        if index >= 0:
            self.lang_combo.setCurrentIndex(index)
        
        # Период
        saved_period = int(self.settings.value("scraper/period", 1))
        if 0 <= saved_period < self.period_combo.count():
            self.period_combo.setCurrentIndex(saved_period)
        
        # Папка вывода
        saved_output = self.settings.value("storage/path")
        if saved_output:
            self.output_input.setText(saved_output)
            
    def start_scraping(self):
        """Запуск скрапинга"""
        login = self.login_input.text().strip()
        password = self.password_input.text().strip()
        
        if not login or not password:
            msg = "Пожалуйста, введите логин и пароль" if self.translator.get_language() == 'ru' else "Логин мен құпия сөзді енгізіңіз"
            QMessageBox.warning(self, self.translator.tr('error'), msg)
            return
            
        output_dir = self.output_input.text()
        if not output_dir:
             msg = "Выберите папку для отчетов" if self.translator.get_language() == 'ru' else "Есептер үшін қалтаны таңдаңыз"
             QMessageBox.warning(self, self.translator.tr('error'), msg)
             return
             
        # Lang
        lang_map = {"Русский": "ru", "Қазақша": "kk", "English": "en"}
        lang = lang_map.get(self.lang_combo.currentText(), "ru")
        
        # Period
        period = str(self.period_combo.currentIndex() + 1)
        
        # Сохраняем настройки
        self.settings.setValue("scraper/lang", self.lang_combo.currentText())
        self.settings.setValue("scraper/period", self.period_combo.currentIndex())
        self.settings.setValue("storage/path", output_dir)
        
        self.start_btn.setEnabled(False)
        self.stop_btn.setVisible(True)
        self.log_text.append("Запуск скрапера...")
        
        # Запускаем без предустановленной школы - будет динамический выбор если нужно
        self.scraper_thread = ScraperThread(login, password, period, lang, Path(output_dir), "", api_client=self.api_client)
        self.scraper_thread.progress.connect(self.on_progress)
        self.scraper_thread.report_created.connect(self.on_report_created)
        self.scraper_thread.finished.connect(self.on_finished)
        self.scraper_thread.error.connect(self.on_error)
        self.scraper_thread.schools_detected.connect(self.on_schools_detected)
        self.scraper_thread.start()
        
    def stop_scraping(self):
        """Остановка скрапинга"""
        if self.scraper_thread and self.scraper_thread.isRunning():
            self.scraper_thread.stop()
            self.log_text.append("Остановка скрапинга...")
            self.stop_btn.setEnabled(False)

    def on_progress(self, percent: int, message: str):
        """Обновление прогресса"""
        self.progress_bar.setValue(percent)
        self.progress_label.setText(message)
        self.log_text.append(f"{percent}% — {message}")
        
    def on_report_created(self, class_name: str, subject: str):
        """Отчет создан"""
        self.log_text.append(f"Создан отчет: {class_name} - {subject}")
        
    def on_finished(self, success: bool, reports: list):
        """Завершение скрапинга"""
        self.start_btn.setEnabled(True)
        self.stop_btn.setVisible(False)
        self.stop_btn.setEnabled(True)
        
        if success:
            self.progress_bar.setValue(100)
            self.progress_label.setText("Готово!")
            self.log_text.append(f"Создано отчетов: {len(reports)}")
            
            # Определяем организацию и статус загрузки
            org_name = None
            skipped_count = 0
            uploaded_count = 0
            for report in reports:
                if not org_name and report.get("org_name"):
                    org_name = report["org_name"]
                if report.get("upload_skipped"):
                    skipped_count += 1
                elif report.get("server_report_id"):
                    uploaded_count += 1
            
            # Логируем организацию
            if org_name:
                self.log_text.append(f"<b>Организация:</b> {org_name}")
            
            # Логируем статус загрузки на сервер
            if uploaded_count > 0:
                self.log_text.append(
                    f"<span style='color: #198754;'>Загружено на сервер: {uploaded_count}</span>"
                )
            if skipped_count > 0:
                if self.translator.get_language() == 'ru':
                    skip_msg = (f"<span style='color: #ff9800;'>Не загружено на сервер: "
                                f"{skipped_count} (организация не найдена в базе данных)</span>")
                else:
                    skip_msg = (f"<span style='color: #ff9800;'>Серверге жүктелмеді: "
                                f"{skipped_count} (ұйым деректер базасында табылмады)</span>")
                self.log_text.append(skip_msg)
            
            # Сохраняем в историю
            for report in reports:
                self.reports_manager.save_report(report)
                
            self.history_widget.refresh()
            
            # Формируем итоговое сообщение
            if self.translator.get_language() == 'ru':
                msg = f"Отчеты успешно созданы!\nВсего: {len(reports)}"
                if org_name:
                    msg += f"\nОрганизация: {org_name}"
                if skipped_count > 0:
                    msg += (f"\n\n{skipped_count} отчёт(ов) не загружено на сервер: "
                            f"организация не найдена в базе данных.\n"
                            f"Файлы Excel/Word сохранены локально.")
                if uploaded_count > 0:
                    msg += f"\nЗагружено на сервер: {uploaded_count}"
            else:
                msg = f"Есептер сәтті жасалды!\nБарлығы: {len(reports)}"
                if org_name:
                    msg += f"\nҰйым: {org_name}"
                if skipped_count > 0:
                    msg += (f"\n\n{skipped_count} есеп серверге жүктелмеді: "
                            f"ұйым деректер базасында табылмады.\n"
                            f"Excel/Word файлдары жергілікті сақталды.")
                if uploaded_count > 0:
                    msg += f"\nСерверге жүктелді: {uploaded_count}"
            
            if skipped_count > 0:
                QMessageBox.warning(self, self.translator.tr('success'), msg)
            else:
                QMessageBox.information(self, self.translator.tr('success'), msg)
        else:
            self.progress_bar.setValue(0)
            error_label = "Ошибка" if self.translator.get_language() == 'ru' else "Қате"
            self.progress_label.setText(error_label)
            
    def on_error(self, message: str):
        """Обработка ошибки"""
        self.log_text.append(f"Ошибка: {message}")
        QMessageBox.critical(self, self.translator.tr('error'), message)
        self.start_btn.setEnabled(True)
        self.stop_btn.setVisible(False)
    
    def on_schools_detected(self, schools: list):
        """Обработка обнаружения нескольких школ"""
        print(f"[DEBUG] on_schools_detected вызван с {len(schools)} школами: {schools}")
        self.log_text.append("<br><b style='color: #ff9800;'>Обнаружено несколько школ. Выберите нужную:</b><br>")
        
        # Очистить предыдущие кнопки (если были)
        for i in reversed(range(self.school_buttons_layout.count())): 
            widget = self.school_buttons_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)
        
        # Создать кнопку для каждой школы
        for i, school_name in enumerate(schools):
            btn = QPushButton(school_name)
            btn.setMinimumHeight(40)
            btn.setObjectName("schoolButton")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked, idx=i, name=school_name: self.select_school(idx, name))
            
            # Стиль кнопки
            btn.setStyleSheet("""
                QPushButton#schoolButton {
                    background-color: #0d6efd;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    padding: 10px;
                    font-size: 13px;
                    text-align: left;
                }
                QPushButton#schoolButton:hover {
                    background-color: #0b5ed7;
                }
                QPushButton#schoolButton:pressed {
                    background-color: #0a58ca;
                }
            """)
            
            self.school_buttons_layout.addWidget(btn)
        
        # Показать контейнер
        self.school_buttons_container.setVisible(True)
        self.log_text.append("<i style='color: #6c757d;'>Ожидание выбора...</i><br>")
    
    def select_school(self, index: int, school_name: str):
        """Обработка выбора школы пользователем"""
        print(f"[DEBUG] select_school вызван: индекс={index}, название={school_name}")
        
        # Скрыть кнопки
        self.school_buttons_container.setVisible(False)
        
        # Записать выбор в файл для скрипта
        if self.scraper_thread:
            print(f"[DEBUG] Вызов scraper_thread.select_school({index})")
            self.scraper_thread.select_school(index)
        else:
            print(f"[DEBUG] ОШИБКА: scraper_thread не существует!")
        
        # Логировать выбор
        self.log_text.append(f"<b style='color: #198754;'>Выбрана школа:</b> {school_name}<br>")
        self.log_text.append("<i>Продолжаем работу...</i><br>")
    
    def toggle_reports_panel(self):
        """Скрыть/показать панель создания отчетов"""
        is_visible = self.left_panel.isVisible()
        self.left_panel.setVisible(not is_visible)
        
        if is_visible:
            # Панель скрыта
            if self.translator.get_language() == 'ru':
                self.toggle_btn.setText("▶ Показать панель")
            else:
                self.toggle_btn.setText("▶ Панельді көрсету")
        else:
            # Панель показана
            if self.translator.get_language() == 'ru':
                self.toggle_btn.setText("◀ Скрыть панель")
            else:
                self.toggle_btn.setText("◀ Панельді жасыру")
    
    def open_settings(self):
        """Открыть диалог настроек"""
        old_server_url = self.settings.value("server/url", DEFAULT_SERVER_URL)
        
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec():
            # Обновить менеджер отчетов с новым путем
            new_path = Path(self.settings.value(
                "storage/path",
                str(Path.home() / "Documents" / "Mektep Reports")
            ))
            current_username = self.user_data.get("username", "")
            self.reports_manager = ReportsManager(new_path, username=current_username)
            
            # Обновить историю
            if hasattr(self, 'history_widget'):
                self.history_widget.reports_manager = self.reports_manager
                self.history_widget.refresh()
            
            # Обновить URL сервера в API клиенте
            new_server_url = self.settings.value("server/url", DEFAULT_SERVER_URL)
            if old_server_url != new_server_url:
                self.api_client.set_base_url(new_server_url)
                
                # Обновляем индикатор
                try:
                    from urllib.parse import urlparse
                    parsed = urlparse(new_server_url)
                    server_display = parsed.netloc or new_server_url
                except Exception:
                    server_display = new_server_url
                self.connection_indicator.setText(f"🔄 {server_display}")
                self.connection_indicator.setStyleSheet("color: #ffc107; font-size: 11px;")
            
            # Проверить изменение языка
            new_lang = self.settings.value("language", "ru")
            if self.translator.get_language() != new_lang:
                msg = "Перезапустите приложение для применения нового языка" if new_lang == 'ru' else "Жаңа тілді қолдану үшін қолданбаны қайта іске қосыңыз"
                QMessageBox.information(
                    self,
                    self.translator.tr('info'),
                    msg
                )
        
    def logout(self):
        """Выход из приложения"""
        reply = QMessageBox.question(
            self, self.translator.tr('logout_confirm'), self.translator.tr('logout_question'),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.api_client.logout()
            
            # Очищаем сохранённый токен
            self.settings.remove("auth/token")
            self.settings.remove("auth/token_expires")
            self.settings.remove("auth/user_data")
            
            self.close()
            # Перезапуск
            import sys
            from PyQt6.QtCore import QProcess
            QProcess.startDetached(sys.executable, sys.argv)
            
    def apply_styles(self):
        """Применение стилей"""
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #f8f9fa;
                color: #212529;
            }
            QFrame#userInfoPanel {
                background-color: white;
                border-bottom: 1px solid #dee2e6;
            }
            QFrame#card {
                background-color: white;
                border: 1px solid #dee2e6;
                border-radius: 8px;
            }
            QFrame#card QLabel {
                background-color: transparent;
            }
            QLabel#cardTitle {
                font-weight: 600;
                font-size: 14px;
                color: #212529;
            }
            QGroupBox {
                background-color: white;
                border: 1px solid #dee2e6;
                border-radius: 8px;
                margin-top: 1.5em; /* Место для заголовка */
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 15px;
                padding: 0 5px;
                background-color: white;
                color: #212529;
            }
            QLineEdit, QComboBox {
                padding: 8px 12px;
                border: 1px solid #ced4da;
                border-radius: 4px;
                background-color: white;
                color: #212529;
                min-height: 20px;
            }
            QLineEdit:focus, QComboBox:focus {
                border: 2px solid #86b7fe;
            }
            QComboBox::drop-down {
                border: none;
                width: 30px;
                background-color: transparent;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 6px solid #6c757d;
                width: 0;
                height: 0;
            }
            QComboBox QAbstractItemView {
                background: white;
                color: #212529;
                border: 1px solid #ced4da;
                selection-background-color: #0d6efd;
                selection-color: white;
                outline: 0;
            }
            QComboBox QAbstractItemView::item {
                padding: 8px 12px;
                min-height: 25px;
                background: white;
                color: #212529;
            }
            QComboBox QAbstractItemView::item:hover {
                background: #e9ecef;
                color: #212529;
            }
            QComboBox QAbstractItemView::item:selected {
                background: #0d6efd;
                color: white;
            }
            QPushButton {
                background-color: #0d6efd;
                color: white;
                border: 1px solid #0d6efd;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: 500;
            }
            QPushButton#togglePanelBtn {
                background-color: #6c757d;
                border: 1px solid #6c757d;
                font-size: 12px;
                padding: 6px 12px;
            }
            QPushButton#togglePanelBtn:hover {
                background-color: #5c636a;
                border-color: #5c636a;
            }
            QPushButton#primaryAction {
                padding: 6px 14px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #0b5ed7;
            }
            QTabWidget::pane {
                border: 1px solid #dee2e6;
                background-color: white;
                border-radius: 4px;
            }
            QTabBar::tab {
                background-color: white;
                padding: 10px 20px;
                margin-right: 2px;
                border: 1px solid #dee2e6;
                border-bottom: none;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected {
                border-bottom: 2px solid #0d6efd;
                font-weight: bold;
                color: #0d6efd;
            }
        """)
