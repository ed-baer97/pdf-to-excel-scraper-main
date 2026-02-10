"""
Translator - модуль для мультиязычности приложения

Поддерживает русский (ru) и казахский (kk) языки.
"""
from PyQt6.QtCore import QObject, pyqtSignal


class Translator(QObject):
    """Класс для управления переводами"""
    
    # Сигнал при смене языка
    language_changed = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self.current_lang = 'ru'
        
        # Словарь переводов
        self.translations = {
            'ru': {
                # Общие
                'app_name': 'Mektep Desktop',
                'yes': 'Да',
                'no': 'Нет',
                'ok': 'ОК',
                'cancel': 'Отмена',
                'close': 'Закрыть',
                'save': 'Сохранить',
                'delete': 'Удалить',
                'edit': 'Редактировать',
                'add': 'Добавить',
                'browse': 'Обзор...',
                'select': 'Выбрать',
                'error': 'Ошибка',
                'warning': 'Предупреждение',
                'info': 'Информация',
                'success': 'Успех',
                
                # Login Dialog
                'login_title': 'Mektep Desktop - Вход',
                'login_subtitle': 'Платформа для создания отчетов',
                'login_description': 'Войдите в систему, используя учетные данные веб-платформы',
                'username': 'Логин',
                'password': 'Пароль',
                'remember_me': 'Запомнить меня',
                'login_button': 'Войти',
                'logging_in': 'Вход в систему...',
                'login_error': 'Ошибка входа',
                'invalid_credentials': 'Неверный логин или пароль',
                'connection_error': 'Ошибка подключения',
                'check_connection': 'Проверьте подключение к интернету и URL сервера',
                'server_url': 'URL сервера',
                'default_server': 'По умолчанию: http://localhost:5000',
                
                # Main Window
                'main_window_title': 'Mektep Desktop - {}',
                'user': 'Пользователь',
                'settings': 'Настройки',
                'history': 'История',
                'logout': 'Выход',
                'logout_confirm': 'Подтверждение выхода',
                'logout_question': 'Вы уверены, что хотите выйти?',
                
                # Scraper Form
                'scraper_section': 'Параметры скрапинга',
                'mektep_login': 'Логин (mektep.edu.kz)',
                'mektep_password': 'Пароль (mektep.edu.kz)',
                'language': 'Язык интерфейса',
                'lang_russian': 'Русский',
                'lang_kazakh': 'Қазақша',
                'quarter': 'Четверть',
                'quarter_1': '1 четверть',
                'quarter_2': '2 четверть (1 полугодие)',
                'quarter_3': '3 четверть',
                'quarter_4': '4 четверть (2 полугодие)',
                'school': 'Школа',
                'select_school': 'Выберите школу',
                'class': 'Класс',
                'select_class': 'Выберите класс',
                'parallel': 'Параллель',
                'select_parallel': 'Выберите параллель',
                'start_scraping': 'Запустить скрапинг',
                'stop_scraping': 'Остановить',
                
                # Progress
                'progress': 'Прогресс',
                'status': 'Статус',
                'ready': 'Готово к работе',
                'running': 'Выполняется...',
                'completed': 'Завершено',
                'error_occurred': 'Произошла ошибка',
                'cancelled': 'Отменено',
                
                # Log
                'log_section': 'Журнал событий',
                'clear_log': 'Очистить журнал',
                
                # Goals Dialog
                'goals_title': 'Цели и задачи преподавания',
                'goals_description': 'Укажите цели преподавания для каждого класса и предмета',
                'subject': 'Предмет',
                'goals_placeholder': 'Введите цели и задачи преподавания...',
                'goals_saved': 'Цели сохранены',
                'goals_saved_message': 'Цели и задачи успешно сохранены',
                
                # History Widget
                'history_title': 'История отчетов',
                'history_empty': 'История отчетов пуста',
                'date': 'Дата',
                'classes': 'Классы',
                'status_col': 'Статус',
                'actions': 'Действия',
                'open_folder': 'Открыть папку',
                'view_report': 'Просмотр',
                'delete_report': 'Удалить',
                'confirm_delete': 'Подтверждение удаления',
                'confirm_delete_message': 'Вы уверены, что хотите удалить этот отчет?',
                'report_deleted': 'Отчет удален',
                
                # Settings Dialog
                'settings_title': 'Настройки',
                'reports_folder': 'Папка для сохранения отчетов',
                'interface_language': 'Язык интерфейса',
                'language_change_note': 'Изменение языка вступит в силу после перезапуска приложения',
                
                # Validation Messages
                'fill_all_fields': 'Заполните все обязательные поля',
                'select_school_first': 'Сначала выберите школу',
                'select_class_first': 'Сначала выберите класс',
                'invalid_credentials_mektep': 'Проверьте логин и пароль для mektep.edu.kz',
                
                # Report Generation
                'generating_report': 'Генерация отчета...',
                'report_generated': 'Отчет сгенерирован',
                'report_saved_at': 'Отчет сохранен в: {}',
                'open_report_folder': 'Открыть папку с отчетом',
                
                # Errors
                'network_error': 'Ошибка сети',
                'server_error': 'Ошибка сервера',
                'unknown_error': 'Неизвестная ошибка',

                # Tabs
                'tab_my_reports': 'Мои отчёты',
                'tab_grades': 'Оценки по классам',
                'tab_subject_report': 'Предметник',
                'tab_class_teacher_report': 'Кл. руководитель',

                # Excel export
                'export_excel': 'Скачать Excel',
                'save_excel': 'Сохранить Excel',
                'excel_saved': 'Файл Excel успешно сохранён',
                'excel_save_error': 'Ошибка сохранения Excel',

                # Grades Widget
                'period': 'Период:',
                'class_label': 'Класс:',
                'refresh': 'Обновить',
                'select_class_for_grades': 'Выберите класс для просмотра сводной таблицы оценок',
                'loading_classes': 'Загрузка классов...',
                'loading_grades': 'Загрузка оценок {}...',
                'loading_data': 'Загрузка данных...',
                'class_col': 'Класс',
                'students_count': 'Учеников',
                'quality_pct': 'Качество',
                'success_pct': 'Успеваемость',
                'fio': 'ФИО',
                'count_5': 'Кол-во «5»',
                'count_4': 'Кол-во «4»',
                'count_3': 'Кол-во «3»',
                'quality_percent': 'Качество %',
                'success_percent': 'Успеваемость %',
                'total': 'Всего',

                # Subject Report Widget
                'loading_subject_report': 'Загрузка отчёта предметника...',
                'press_refresh_subject': 'Нажмите «Обновить» для загрузки отчёта предметника',
                'no_data_for_period': 'Нет данных за выбранный период',

                # Class Report Widget
                'loading_class_teacher_report': 'Загрузка отчёта кл. руководителя...',
                'press_refresh_class_teacher': 'Нажмите «Обновить» для загрузки отчёта классного руководителя.\n\nДанные доступны только если вы назначены классным руководителем.',
                'no_data_class_teacher': 'Нет данных. Вы не назначены классным руководителем или нет отчётов за этот период.',
            },
            'kk': {
                # Общие
                'app_name': 'Mektep Desktop',
                'yes': 'Иә',
                'no': 'Жоқ',
                'ok': 'Жарайды',
                'cancel': 'Болдырмау',
                'close': 'Жабу',
                'save': 'Сақтау',
                'delete': 'Жою',
                'edit': 'Өңдеу',
                'add': 'Қосу',
                'browse': 'Шолу...',
                'select': 'Таңдау',
                'error': 'Қате',
                'warning': 'Ескерту',
                'info': 'Ақпарат',
                'success': 'Сәтті',
                
                # Login Dialog
                'login_title': 'Mektep Desktop - Кіру',
                'login_subtitle': 'Есептер жасау платформасы',
                'login_description': 'Веб-платформа тіркелгі деректерін пайдаланып жүйеге кіріңіз',
                'username': 'Логин',
                'password': 'Құпия сөз',
                'remember_me': 'Мені есте сақта',
                'login_button': 'Кіру',
                'logging_in': 'Жүйеге кіру...',
                'login_error': 'Кіру қатесі',
                'invalid_credentials': 'Логин немесе құпия сөз қате',
                'connection_error': 'Қосылу қатесі',
                'check_connection': 'Интернет қосылымы мен сервер URL мекенжайын тексеріңіз',
                'server_url': 'Сервер URL мекенжайы',
                'default_server': 'Әдепкі: http://localhost:5000',
                
                # Main Window
                'main_window_title': 'Mektep Desktop - {}',
                'user': 'Пайдаланушы',
                'settings': 'Баптаулар',
                'history': 'Тарих',
                'logout': 'Шығу',
                'logout_confirm': 'Шығуды растау',
                'logout_question': 'Шығуға сенімдісіз бе?',
                
                # Scraper Form
                'scraper_section': 'Скрапинг параметрлері',
                'mektep_login': 'Логин (mektep.edu.kz)',
                'mektep_password': 'Құпия сөз (mektep.edu.kz)',
                'language': 'Интерфейс тілі',
                'lang_russian': 'Русский',
                'lang_kazakh': 'Қазақша',
                'quarter': 'Тоқсан',
                'quarter_1': '1 тоқсан',
                'quarter_2': '2 тоқсан (1 жартыжылдық)',
                'quarter_3': '3 тоқсан',
                'quarter_4': '4 тоқсан (2 жартыжылдық)',
                'school': 'Мектеп',
                'select_school': 'Мектепті таңдаңыз',
                'class': 'Сынып',
                'select_class': 'Сыныпты таңдаңыз',
                'parallel': 'Параллель',
                'select_parallel': 'Параллельді таңдаңыз',
                'start_scraping': 'Скрапингті бастау',
                'stop_scraping': 'Тоқтату',
                
                # Progress
                'progress': 'Прогресс',
                'status': 'Күй',
                'ready': 'Жұмысқа дайын',
                'running': 'Орындалуда...',
                'completed': 'Аяқталды',
                'error_occurred': 'Қате орын алды',
                'cancelled': 'Болдырылмады',
                
                # Log
                'log_section': 'Оқиғалар журналы',
                'clear_log': 'Журналды тазалау',
                
                # Goals Dialog
                'goals_title': 'Оқыту мақсаттары мен міндеттері',
                'goals_description': 'Әр сынып пен пән үшін оқыту мақсаттарын көрсетіңіз',
                'subject': 'Пән',
                'goals_placeholder': 'Оқыту мақсаттары мен міндеттерін енгізіңіз...',
                'goals_saved': 'Мақсаттар сақталды',
                'goals_saved_message': 'Мақсаттар мен міндеттер сәтті сақталды',
                
                # History Widget
                'history_title': 'Есептер тарихы',
                'history_empty': 'Есептер тарихы бос',
                'date': 'Күні',
                'classes': 'Сыныптар',
                'status_col': 'Күй',
                'actions': 'Әрекеттер',
                'open_folder': 'Қалтаны ашу',
                'view_report': 'Көру',
                'delete_report': 'Жою',
                'confirm_delete': 'Жоюды растау',
                'confirm_delete_message': 'Бұл есепті жоюға сенімдісіз бе?',
                'report_deleted': 'Есеп жойылды',
                
                # Settings Dialog
                'settings_title': 'Баптаулар',
                'reports_folder': 'Есептерді сақтау қалтасы',
                'interface_language': 'Интерфейс тілі',
                'language_change_note': 'Тіл өзгерісі қолданбаны қайта іске қосқаннан кейін күшіне енеді',
                
                # Validation Messages
                'fill_all_fields': 'Барлық міндетті өрістерді толтырыңыз',
                'select_school_first': 'Алдымен мектепті таңдаңыз',
                'select_class_first': 'Алдымен сыныпты таңдаңыз',
                'invalid_credentials_mektep': 'mektep.edu.kz үшін логин мен құпия сөзді тексеріңіз',
                
                # Report Generation
                'generating_report': 'Есеп жасалуда...',
                'report_generated': 'Есеп жасалды',
                'report_saved_at': 'Есеп сақталды: {}',
                'open_report_folder': 'Есеп қалтасын ашу',
                
                # Errors
                'network_error': 'Желі қатесі',
                'server_error': 'Сервер қатесі',
                'unknown_error': 'Белгісіз қате',

                # Tabs
                'tab_my_reports': 'Менің есептерім',
                'tab_grades': 'Сыныптар бойынша бағалар',
                'tab_subject_report': 'Пән мұғалімі',
                'tab_class_teacher_report': 'Сынып жетекшісі',

                # Excel export
                'export_excel': 'Excel жүктеу',
                'save_excel': 'Excel сақтау',
                'excel_saved': 'Excel файлы сәтті сақталды',
                'excel_save_error': 'Excel сақтау қатесі',

                # Grades Widget
                'period': 'Кезең:',
                'class_label': 'Сынып:',
                'refresh': 'Жаңарту',
                'select_class_for_grades': 'Бағалар кестесін көру үшін сыныпты таңдаңыз',
                'loading_classes': 'Сыныптар жүктелуде...',
                'loading_grades': '{} бағалары жүктелуде...',
                'loading_data': 'Деректер жүктелуде...',
                'class_col': 'Сынып',
                'students_count': 'Оқушылар',
                'quality_pct': 'Сапа',
                'success_pct': 'Үлгерім',
                'fio': 'Аты-жөні',
                'count_5': '«5» саны',
                'count_4': '«4» саны',
                'count_3': '«3» саны',
                'quality_percent': 'Сапа %',
                'success_percent': 'Үлгерім %',
                'total': 'Барлығы',

                # Subject Report Widget
                'loading_subject_report': 'Пән мұғалімі есебі жүктелуде...',
                'press_refresh_subject': 'Пән мұғалімі есебін жүктеу үшін «Жаңарту» батырмасын басыңыз',
                'no_data_for_period': 'Таңдалған кезеңде деректер жоқ',

                # Class Report Widget
                'loading_class_teacher_report': 'Сынып жетекшісі есебі жүктелуде...',
                'press_refresh_class_teacher': 'Сынып жетекшісі есебін жүктеу үшін «Жаңарту» батырмасын басыңыз.\n\nДеректер сынып жетекшісі ретінде тағайындалған жағдайда ғана қолжетімді.',
                'no_data_class_teacher': 'Деректер жоқ. Сіз сынып жетекшісі ретінде тағайындалмағансыз немесе осы кезеңде есептер жоқ.',
            }
        }
    
    def tr(self, key: str, *args) -> str:
        """
        Получить перевод по ключу
        
        Args:
            key: Ключ перевода
            *args: Аргументы для форматирования строки
            
        Returns:
            Переведенная строка
        """
        translation = self.translations.get(self.current_lang, {}).get(key, key)
        
        # Форматирование строки, если переданы аргументы
        if args:
            try:
                translation = translation.format(*args)
            except (IndexError, KeyError):
                pass
        
        return translation
    
    def set_language(self, lang: str):
        """
        Установить язык интерфейса
        
        Args:
            lang: Код языка ('ru' или 'kk')
        """
        if lang in self.translations:
            self.current_lang = lang
            self.language_changed.emit(lang)
    
    def get_language(self) -> str:
        """Получить текущий язык"""
        return self.current_lang
    
    def get_available_languages(self) -> dict:
        """Получить список доступных языков"""
        return {
            'ru': 'Русский',
            'kk': 'Қазақша'
        }


# Глобальный экземпляр переводчика
_translator = Translator()


def get_translator() -> Translator:
    """Получить глобальный экземпляр переводчика"""
    return _translator


def tr(key: str, *args) -> str:
    """
    Сокращенная функция для получения перевода
    
    Args:
        key: Ключ перевода
        *args: Аргументы для форматирования
        
    Returns:
        Переведенная строка
    """
    return _translator.tr(key, *args)
