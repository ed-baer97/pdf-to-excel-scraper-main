# Mektep Scraper

Приложение для автоматического сбора данных с [mektep.edu.kz](https://mektep.edu.kz) и формирования отчётов (Excel/Word), с веб-платформой для школ и десктоп-клиентом для учителей.

English summary: multi-user web app plus optional PyQt6 desktop client; Playwright-based scraper; templates for Excel/Word reports.

## Возможности

- Многопользовательская система (суперадмин → школы → учителя), учитель может работать в нескольких школах
- Сбор данных с mektep.edu.kz (Playwright), в т.ч. критериальное оценивание (СОР/СОЧ)
- Генерация Excel и Word из шаблонов; сводная аналитика, отчёты предметника и классного руководителя, годовые оценки
- **Итоговый отчёт школы** — многолистовой Excel со сводкой по школе (успеваемость, качество, динамика за 3 года, ГИА, ЕНТ, аттестаты); авто-разделы из `GradeReport`, ручной ввод ГИА/ЕНТ/аттестатов через админ-панель. Подробнее: [Итоговый отчёт школы](#итоговый-отчёт-школы).
- Асинхронный экспорт Excel из админ-панели (Celery или фоновый поток)
- Прогресс задач в реальном времени
- Десктоп-клиент с автообновлением через установщик (Inno Setup + `latest.json`)
- Опционально: аналитика через AI API (Qwen и др.)

## Требования

- Python 3.11+
- PostgreSQL (production) или SQLite (development)
- Redis (опционально: лимиты и Celery)
- Chromium (ставится через `playwright install chromium`)

---

## Структура проекта

Ниже приведена полная структура репозитория: дерево каталогов верхнего уровня, таблица корневых файлов, а также детальные подразделы по каждому пакету и служебной папке. Разделы идут в порядке:

1. [Дерево каталогов](#дерево-каталогов)
2. [Корневые файлы](#корневые-файлы)
3. [`webapp/` — Flask-платформа](#webapp--flask-платформа)
4. [`mektep-desktop/` — PyQt6-клиент](#mektep-desktop--pyqt6-клиент)
5. [`scripts/` — обслуживающие скрипты](#scripts--обслуживающие-скрипты)
6. [`entrypoints/` — точки входа веба](#entrypoints--точки-входа-веба)
7. [`deploy/` и `nginx/` — инфраструктура](#deploy-и-nginx--инфраструктура)
8. [`tests/` и `docs/`](#tests-и-docs)
9. [Runtime и артефакты сборки](#runtime-и-артефакты-сборки)

Подробные сценарии запуска: [ИНСТРУКЦИЯ_ЗАПУСКА.md](ИНСТРУКЦИЯ_ЗАПУСКА.md). Содержание методического пособия: [МЕТОДИЧЕСКОЕ_ПОСОБИЕ_СОДЕРЖАНИЕ.md](МЕТОДИЧЕСКОЕ_ПОСОБИЕ_СОДЕРЖАНИЕ.md). Авторская программа педагога-мастера на базе проекта: [АВТОРСКАЯ_ПРОГРАММА.md](АВТОРСКАЯ_ПРОГРАММА.md) + [приложения](АВТОРСКАЯ_ПРОГРАММА_ПРИЛОЖЕНИЯ.md) + [программа апробации](ПРОГРАММА_АПРОБАЦИИ.md).

### Дерево каталогов

```text
pdf-to-excel-scraper-main/
├── .cursor/                         # Настройки Cursor IDE (не коммитить в прод)
├── .pytest_cache/                   # Кэш pytest (артефакт, в .gitignore)
├── .venv/                           # Локальное виртуальное окружение (артефакт)
├── .venv-3.11/                      # Дополнительное venv под Python 3.11 (артефакт)
├── .gitignore                       # Правила исключения для git
├── app.py                           # Корневой прокси → entrypoints/app.py (dev-сервер)
├── wsgi.py                          # Корневой прокси → entrypoints/wsgi.py
├── run_production.py                # Корневой прокси → entrypoints/run_production.py
├── gunicorn_config.py               # Корневой прокси → entrypoints/gunicorn_config.py
├── scrape_mektep.py                 # CLI-скрапер mektep.edu.kz (Playwright)
├── scraper_logger.py                # Логгер этапов скрапинга (INIT/AUTH/... /COMPLETE)
├── grade_table_signals.py           # Эвристики структуры видимой таблицы критериального оценивания
├── build_report.py                  # Генератор Excel-отчёта из JSON по шаблону
├── build_word_report.py             # Генератор Word-отчёта из Excel + шаблон .docx
├── iin_utils.py                     # Нормализация казахстанского ИИН (12 цифр)
├── seed_test_data.py                # Наполнение БД тестовыми учителями/классами/оценками
├── requirements.txt                 # Prod-зависимости веба и скрапера
├── requirements-dev.txt             # Инструменты разработки (pytest и т.п.)
├── pytest.ini                       # Конфиг pytest (pythonpath = mektep-desktop)
├── env.example                      # Шаблон .env (SECRET_KEY, DATABASE_URL, REDIS_URL, ...)
├── Dockerfile                       # Сборка prod-образа (дубликат deploy/Dockerfile)
├── docker-compose.yml               # Docker-оркестрация (дубликат deploy/docker-compose.yml)
├── prometheus.yml                   # Конфиг Prometheus (дубликат deploy/prometheus.yml)
├── README.md                        # Этот файл
├── ИНСТРУКЦИЯ_ЗАПУСКА.md            # Подробная инструкция запуска (рус.)
├── МЕТОДИЧЕСКОЕ_ПОСОБИЕ_СОДЕРЖАНИЕ.md # Содержание методического пособия
├── Шаблон.xlsx                      # Excel-шаблон отчёта (рус.)
├── Шаблон.docx                      # Word-шаблон отчёта (рус.)
├── Шаблон_каз.docx                  # Word-шаблон отчёта (каз.)
├── debug-*.log                      # Отладочные логи скрапера/веба (артефакты)
│
├── webapp/                          # Flask-приложение (auth, API, admin, teacher, superadmin)
│   ├── __init__.py                  # Фабрика create_app(), регистрация blueprint'ов
│   ├── config.py                    # Конфигурация Flask/SQLAlchemy/Celery
│   ├── constants.py                 # Общие константы домена
│   ├── extensions.py                # Инстансы db/login_manager/babel и т.п.
│   ├── models.py                    # SQLAlchemy-модели (School/Teacher/Class/...)
│   ├── security.py                  # Хеширование паролей, проверка прав
│   ├── tasks.py                     # Фоновые задачи (Celery / потоки)
│   ├── celery_app.py                # Инициализация Celery
│   ├── cli.py                       # Flask CLI-команды
│   ├── redis_utils.py               # Обёртки над Redis (лимиты, кэш)
│   ├── translator.py                # i18n-утилиты (ru/kk) + словари
│   ├── scraper_runner.py            # Оркестрация прогонов скрапера из веба
│   ├── views/                       # Blueprint-модули (auth, admin/ (пакет), teacher, api, ...)
│   ├── services/                    # Прикладные сервисы (grade_reports/, criteria, экспорт, guards)
│   ├── templates/                   # Jinja2-шаблоны (layout + подпапки ролей)
│   ├── static/                      # JS для асинхронного экспорта Excel (admin_async_export.js, ...)
│   └── translations/                # gettext-каталоги (ru/, kk/)
│
├── mektep-desktop/                  # PyQt6-клиент для учителя
│   ├── main.py                      # Точка входа десктоп-приложения
│   ├── build.py                     # Сборка EXE + установщик Inno Setup + latest.json
│   ├── mektep_desktop.spec          # PyInstaller spec (onedir)
│   ├── mektep_desktop_onefile.spec  # PyInstaller spec (onefile)
│   ├── installer.iss                # Inno Setup: сборка MektepDesktopSetup-<ver>.exe
│   ├── version.py                   # Версия клиента (APP_VERSION)
│   ├── UPDATES.md                   # Публикация обновлений (Nginx /updates/, latest.json)
│   ├── RELEASE.md                   # Чек-лист релиза десктопа
│   ├── requirements.txt             # Зависимости десктопа (PyQt6, requests, packaging, ...)
│   ├── scrape_mektep.py             # Копия скрапера (используется внутри EXE)
│   ├── scraper_logger.py            # Копия логгера скрапера
│   ├── grade_table_signals.py       # Копия эвристик таблицы критериев
│   ├── build_report.py              # Копия генератора Excel
│   ├── build_word_report.py         # Копия генератора Word
│   ├── iin_utils.py                 # Копия ИИН-утилит
│   ├── _download_logo.py            # Служебный скрипт загрузки логотипа
│   ├── Шаблон.xlsx / .docx / _каз.docx # Копии шаблонов для сборки EXE
│   ├── app/                         # UI-слой (widgets, dialogs, updater) + report_pipeline
│   ├── ai/                          # AI-генерация текста (Qwen/DashScope)
│   ├── resources/                   # Иконки и изображения (icons/, img/)
│   ├── .pyupdater/, pyu-data/       # Наследие PyUpdater (артефакт, в .gitignore)
│   ├── build/                       # PyInstaller build (артефакт)
│   └── dist/                        # PyInstaller dist + Inno Setup установщик (артефакт)
│
├── scripts/                         # Обслуживающие скрипты
│   ├── __init__.py
│   ├── db/                          # Миграции и операции над БД
│   └── dev/                         # Локальные dev-утилиты
│
├── entrypoints/                     # Точки входа веб-приложения (реальная логика)
│   ├── __init__.py
│   ├── app.py                       # Flask dev-сервер (create_app)
│   ├── wsgi.py                      # WSGI-точка для Gunicorn/Waitress
│   ├── run_production.py            # Авто-выбор Gunicorn (Unix) / Waitress (Windows)
│   └── gunicorn_config.py           # Параметры Gunicorn (workers, timeout, ...)
│
├── deploy/                          # Инфраструктурные файлы (Docker, Prometheus)
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── prometheus.yml
│
├── nginx/
│   └── nginx.conf                   # Reverse-proxy, rate-limit, статика
│
├── tests/                           # Pytest-тесты (report_pipeline, grade_reports, criteria, ...)
│
├── docs/                            # Зарезервировано (пока пусто)
│
├── updates/                         # Раздача установщика десктопа (latest.json + setup.exe)
│   └── .gitkeep
│
├── instance/                        # Flask instance folder
│   └── mektep_platform.db           # SQLite (dev-база)
│
├── out/                             # Выходные данные скрапера (артефакт)
│   ├── platform_runs/               # Рабочие директории прогонов
│   └── platform_uploads/            # Артефакты загрузки (Excel/Word)
│
├── build/                           # PyInstaller build в корне (артефакт)
└── dist/                            # PyInstaller dist в корне (артефакт)
```

### Корневые файлы

| Файл | Назначение |
|------|------------|
| [app.py](app.py) | Тонкий прокси: `from entrypoints.app import app`; dev-запуск на `127.0.0.1:5000` без авто-перезагрузки. |
| [wsgi.py](wsgi.py) | Тонкий прокси: `from entrypoints.wsgi import app`; совместимость с WSGI-серверами, которые ищут `wsgi:app` в корне. |
| [run_production.py](run_production.py) | Тонкий прокси: вызывает `entrypoints.run_production.main()` (авто-выбор Gunicorn/Waitress). |
| [gunicorn_config.py](gunicorn_config.py) | Тонкий прокси: `from entrypoints.gunicorn_config import *` (для команд вида `gunicorn -c gunicorn_config.py`). |
| [scrape_mektep.py](scrape_mektep.py) | Основной CLI-скрапер mektep.edu.kz на Playwright: авторизация, выбор языка/периода, сбор оценок, вызов построителей отчётов. |
| [scraper_logger.py](scraper_logger.py) | Класс `ScraperLogger` с этапами (`INIT`, `BROWSER`, `AUTH`, `STUDENTS`, `EXCEL_REPORT`, ...) и хелперы `log_info/log_stage/...`. |
| [grade_table_signals.py](grade_table_signals.py) | Эвристики распознавания структуры видимой таблицы критериального оценивания на `mektep.edu.kz` (заголовки СОР/СОЧ/ТЖБ/БЖБ, колонки четвертей). Копируется в десктоп при сборке. |
| [build_report.py](build_report.py) | Сборка Excel-отчёта из `progress.json`-подобного JSON и [Шаблон.xlsx](Шаблон.xlsx): СОР, СОЧ, формативные, лист «Оценки». |
| [build_word_report.py](build_word_report.py) | Сборка Word-отчёта из готового Excel и [Шаблон.docx](Шаблон.docx) / [Шаблон_каз.docx](Шаблон_каз.docx): таблицы анализа, уровни, цели. |
| [iin_utils.py](iin_utils.py) | `normalize_kz_iin` и `format_iin_for_display` — нормализация и маскирование ИИН (12 цифр, показ `****1234`). |
| [seed_test_data.py](seed_test_data.py) | Наполняет БД тестовыми учителями/классами/предметами/`GradeReport` для школы «Test». Запуск из корня: `python seed_test_data.py`. |
| [requirements.txt](requirements.txt) | Production-зависимости: Flask, SQLAlchemy, Playwright, openpyxl, python-docx, gunicorn/waitress и т.п. |
| [requirements-dev.txt](requirements-dev.txt) | Инструменты разработки (pytest и сопутствующее). |
| [pytest.ini](pytest.ini) | `pythonpath = mektep-desktop`, `testpaths = tests`, `python_files = test_*.py`. |
| [env.example](env.example) | Пример `.env`: `SECRET_KEY`, `DATABASE_URL`, `REDIS_URL`, `USE_CELERY`, `DASHSCOPE_API_KEY`, Gunicorn/Waitress-переменные и др. |
| [Dockerfile](Dockerfile) | Двухстадийная сборка `python:3.13-slim`; CMD `python run_production.py`. Дубликат [deploy/Dockerfile](deploy/Dockerfile). |
| [docker-compose.yml](docker-compose.yml) | Сервисы `nginx`/`web`/`db`/`node-exporter`/`prometheus`/`grafana` + сеть `mektep-network`. Дубликат [deploy/docker-compose.yml](deploy/docker-compose.yml). |
| [prometheus.yml](prometheus.yml) | Scrape-конфиг для `web:5000/metrics` и `node-exporter`. Дубликат [deploy/prometheus.yml](deploy/prometheus.yml). |
| [.gitignore](.gitignore) | Правила исключения: `.venv*`, `build/`, `dist/`, `instance/`, `out/`, `__pycache__/`, `*.log`, кэши, артефакты сборки. |
| [README.md](README.md) | Этот файл. |
| [ИНСТРУКЦИЯ_ЗАПУСКА.md](ИНСТРУКЦИЯ_ЗАПУСКА.md) | Подробный runbook на русском для локального и production-запуска. |
| [МЕТОДИЧЕСКОЕ_ПОСОБИЕ_СОДЕРЖАНИЕ.md](МЕТОДИЧЕСКОЕ_ПОСОБИЕ_СОДЕРЖАНИЕ.md) | Оглавление методического пособия по проекту. |
| `Шаблон.xlsx` / `Шаблон.docx` / `Шаблон_каз.docx` | Шаблоны отчётов, на которые опираются `build_report.py` и `build_word_report.py`. |
| `debug-*.log` | Отладочные логи (`debug-4e9670.log`, `debug-91cc02.log`, …) — артефакты, не коммитить. |

> Примечание. Корневые `app.py`, `wsgi.py`, `run_production.py`, `gunicorn_config.py` намеренно оставлены как тонкие прокси, чтобы сохранить привычные команды запуска (`python app.py`, `gunicorn wsgi:app`, `python run_production.py`) после переезда логики в пакет [entrypoints/](entrypoints/). Аналогично [Dockerfile](Dockerfile), [docker-compose.yml](docker-compose.yml), [prometheus.yml](prometheus.yml) продублированы из [deploy/](deploy/) — выбирайте одну копию для своего пайплайна.

### `webapp/` — Flask-платформа

Основной пакет веб-приложения. Фабрика [create_app](webapp/__init__.py) собирает Flask-экземпляр, регистрирует blueprint'ы, поднимает SQLAlchemy, Flask-Login, Flask-Migrate, Prometheus-метрики, Celery (опционально), выполняет «лёгкие» runtime-миграции схемы (добавление колонок/индексов через `ALTER TABLE`) и восстанавливает прерванные задачи скрапинга.

#### Модули верхнего уровня

| Файл | Назначение |
|------|------------|
| [webapp/\_\_init\_\_.py](webapp/__init__.py) | `create_app()`, регистрация blueprint'ов, bootstrap суперадмина, `_recover_interrupted_jobs()` после рестарта. |
| [webapp/config.py](webapp/config.py) | Классы `Config` / `DevelopmentConfig` / `ProductionConfig` / `TestingConfig` + `get_config()` по `FLASK_ENV`. |
| [webapp/constants.py](webapp/constants.py) | `DESKTOP_VERSION`, `MIN_DESKTOP_VERSION`, `DESKTOP_UPDATES_BASE_URL` + хелперы `desktop_installer_filename()`/`desktop_download_url()`; `PERIOD_MAP`, `DEFAULT_SUBJECT_ALIASES`, `normalize_subject_name()`, `kazakh_sort_key()` (казахская кириллическая сортировка). |
| [webapp/extensions.py](webapp/extensions.py) | Singleton-экземпляры `db` (SQLAlchemy), `migrate` (Flask-Migrate), `login_manager` (Flask-Login, `login_view="main.index"`). |
| [webapp/models.py](webapp/models.py) | Enum `Role`, `ScrapeJobStatus`, `ExportJobStatus`, `FinalReportSection`; модели `School`, `User`, `TeacherSchool` (учитель ↔ несколько школ), `Class`, `Subject`, `SubjectNameAlias` (алиасы названий предметов по школе), `TeacherClass`, `TeacherSubject`, `GradeReport`, `FinalReportData` (ручные данные итогового отчёта: ГИА, ЕНТ, аттестаты), `ReportFile`, `ScrapeJob`, `ExportJob` (фоновый экспорт Excel). |
| [webapp/security.py](webapp/security.py) | `encrypt_password()` / `decrypt_password()` через `Fernet` с ключом `PASSWORD_ENC_KEY`. |
| [webapp/tasks.py](webapp/tasks.py) | Celery-задачи (`run_scrape_task`, `generate_ai_text`, `run_export_task`) — альтернатива потокам в `scraper_runner`/`export_runner`. |
| [webapp/celery_app.py](webapp/celery_app.py) | `make_celery()` + `init_celery(flask_app)` (очереди `scraping`/`ai`, лимиты времени). |
| [webapp/cli.py](webapp/cli.py) | Flask-команды `flask create-superadmin <user> <pass>` и `flask clear-cache` (Redis FLUSHDB). |
| [webapp/redis_utils.py](webapp/redis_utils.py) | Лимитер AI-запросов, кэш, FLUSHDB. Автоматический fallback на in-memory при недоступности Redis. |
| [webapp/translator.py](webapp/translator.py) | Словари переводов `TRANSLATIONS["ru" \| "kk"]` + функция `gettext(key, lang)` (используется в шаблонах как `_()`). |
| [webapp/scraper_runner.py](webapp/scraper_runner.py) | Запуск `scrape_mektep.py` как subprocess из веба: семафор `MAX_CONCURRENT_JOBS`, отмена, мониторинг `progress.json`, восстановление отчётов. |

#### `webapp/views/` — blueprint-слой

| Файл | URL-префикс | Роли | Что делает |
|------|-------------|------|------------|
| [views/main.py](webapp/views/main.py) | `/` | anonymous/все | Главная: редиректит авторизованного на панель его роли; `/set_language/<ru\|kk>`; `/download/desktop` (exe/zip по `DESKTOP_DOWNLOAD_PATH`/`DESKTOP_DOWNLOAD_URL`). |
| [views/auth.py](webapp/views/auth.py) | `/auth` | anonymous | Обрабатывает `POST /auth/login` (учителя блокируются — вход только через десктоп) и `POST /auth/logout`. |
| [views/setup.py](webapp/views/setup.py) | `/setup` | (только если нет суперадмина) | One-time мастер создания первого суперадмина. |
| [views/superadmin.py](webapp/views/superadmin.py) | `/superadmin` | `SUPERADMIN` | Школы (создание/активация), школьные админы, смена пароля, AI-модели, квоты отчётов. |
| [views/admin/](webapp/views/admin/__init__.py) | `/admin` | `SCHOOL_ADMIN` | Пакет дашборда школы (разбит из бывшего монолитного `admin.py`): `management.py` (учителя/классы/предметы/алиасы), `reports.py` (оценки, аналитика, графики, критериальное оценивание, отчёты предметника/классрука), `final_report.py` (ввод ГИА/ЕНТ/аттестатов), `exports.py` (асинхронный экспорт Excel). |
| [views/teacher.py](webapp/views/teacher.py) | (без префикса) | `TEACHER` (+ API для десктопа) | Запуск скрапинга, просмотр своих отчётов, скачивание zip, AI-генерация текста с Redis rate-limit. |
| [views/api.py](webapp/views/api.py) | `/api` | JWT (десктоп) | REST-API для Mektep Desktop: логин/рефреш токена, загрузка отчётов, проверка версии (`MIN_DESKTOP_VERSION`). |
| [views/health.py](webapp/views/health.py) | `/health` | любые | `GET /health[/live]` (жив), `GET /health/ready` (БД), `GET /health/stats` (счётчики задач, школ, пользователей). |

##### `webapp/views/admin/` — пакет дашборда школы

Бывший монолитный `admin.py` разбит на пакет с общим blueprint `bp` (префикс `/admin`).

| Файл | Что делает |
|------|------------|
| [views/admin/__init__.py](webapp/views/admin/__init__.py) | Создаёт `Blueprint("admin")`, общие хелперы (`_management_list_context()` и пр.), импортирует подмодули `exports`, `final_report`, `management`, `reports`. |
| [views/admin/management.py](webapp/views/admin/management.py) | CRUD учителей/классов/предметов, связи «учитель↔класс/предмет», словарь алиасов названий предметов. |
| [views/admin/reports.py](webapp/views/admin/reports.py) | Просмотр оценок, аналитика, графики, критериальное оценивание (СОР/СОЧ), отчёты предметника и классного руководителя, годовые оценки. |
| [views/admin/final_report.py](webapp/views/admin/final_report.py) | Ручной ввод данных итогового отчёта: ГИА 9/11 классов, ЕНТ, аттестаты (`GET/POST /admin/final-report/input`). |
| [views/admin/exports.py](webapp/views/admin/exports.py) | Асинхронный экспорт Excel: `POST /admin/exports` (`export_kind`: `analytics`, `criteria_zip`, `grades_class`, `class_teacher`, `metrics_charts`, `final_report`), опрос статуса и скачивание. |

#### `webapp/services/` — прикладные сервисы

Выделенный из `views/` слой бизнес-логики и хелперов.

| Файл | Содержание |
|------|------------|
| [services/__init__.py](webapp/services/__init__.py) | Пустой «пакетный» модуль (docstring). |
| [services/auth_guards.py](webapp/services/auth_guards.py) | Декораторы `role_required`, `superadmin_required`, `admin_required`, `admin_or_superadmin_required`, `teacher_required`; проверки `can_access_report_file()`, `can_access_grade_report()`. |
| [services/admin_common.py](webapp/services/admin_common.py) | `is_safe_redirect_url()`, `redirect_back()` и `apply_analytics_filters()` для админских страниц. |
| [services/admin_dashboard.py](webapp/services/admin_dashboard.py) | Хелперы дашборда: `parse_class_grade()`, `class_accordion_group()`/`teacher_accordion_group()` (аккордеоны 1–4 / 5–9 / 10–11), агрегации метрик класса/года, серии для графиков. |
| [services/api_helpers.py](webapp/services/api_helpers.py) | JWT: `generate_jwt_token()`, декоратор `require_jwt`; `auto_create_class_and_subject()`, `find_school_by_org_name()`, `get_quarter_reports_api()` (слияние полугодий для четвертей 2/4). |
| [services/class_grades_matrix.py](webapp/services/class_grades_matrix.py) | Построение матрицы оценок класса (ученик × предмет) для сводных таблиц и отчётов классного руководителя. |
| [services/criteria_grades.py](webapp/services/criteria_grades.py) | Критериальное оценивание: разбор `grades_json.criteria`, построение таблиц СОР/СОЧ/итог, ZIP-выгрузка по периоду, сводка по предмету. |
| [services/export_runner.py](webapp/services/export_runner.py) | Исполнитель фонового экспорта Excel: формирует файл по `ExportJob.export_kind` (в т.ч. `final_report` — итоговый отчёт школы). |
| [services/report_teacher.py](webapp/services/report_teacher.py) | Имя учителя по `GradeReport`/синтетическому отчёту. |
| [services/subject_aliases.py](webapp/services/subject_aliases.py) | Per-school нормализация названий предметов через `SubjectNameAlias`: `ensure_default_aliases()`, `restore_default_aliases()`. |
| [services/teacher_schools.py](webapp/services/teacher_schools.py) | Учитель в нескольких школах: членство, `fs_teacher_seq`, активная школа сессии. |
| [services/year_grades.py](webapp/services/year_grades.py) | Расчёт годовых оценок из четвертных/полугодовых отчётов (`YEAR_UI_PERIOD`, округление процентов). |

##### `webapp/services/grade_reports/` — централизованная логика отчётов об оценках

Пакет, в который вынесена бизнес-логика парсинга, агрегации, аналитики и генерации Excel из `GradeReport`.

| Файл | Содержание |
|------|------------|
| [grade_reports/__init__.py](webapp/services/grade_reports/__init__.py) | Реэкспорт ключевых функций (`get_period_reports`, `parse_grades_json`, `report_*_payload`, ...). |
| [grade_reports/payload.py](webapp/services/grade_reports/payload.py) | Разбор JSON-полей `GradeReport` (`grades_json`, `analytics_json`). |
| [grade_reports/queries.py](webapp/services/grade_reports/queries.py) | Выборки `GradeReport` по периоду (учитель, полугодия, год, итог). |
| [grade_reports/context.py](webapp/services/grade_reports/context.py) | `SchoolPeriodContext`: загрузка и кэширование отчётов и их распарсенного JSON. |
| [grade_reports/aggregation.py](webapp/services/grade_reports/aggregation.py) | Агрегации метрик учеников/успеваемости по классам и школе. |
| [grade_reports/analytics.py](webapp/services/grade_reports/analytics.py) | Сводная аналитика СОР/СОЧ/оценок по предметам и классам. |
| [grade_reports/overview.py](webapp/services/grade_reports/overview.py) | Сводка оценок для страницы обзора (`grades_overview`). |
| [grade_reports/class_teacher.py](webapp/services/grade_reports/class_teacher.py) | Отчёт классного руководителя: категории учеников и блоки. |
| [grade_reports/student_edits.py](webapp/services/grade_reports/student_edits.py) | Редактирование списка учеников в `grade_reports/excel`-сводных таблицах. |
| [grade_reports/periods.py](webapp/services/grade_reports/periods.py) | Периоды UI и соответствие кодам четвертей/полугодий. |
| [grade_reports/final_report_data.py](webapp/services/grade_reports/final_report_data.py) | Загрузка/сохранение ручных JSON-разделов итогового отчёта (`gia9`, `gia11`, `ent`, `awards`) в `FinalReportData`. |
| [grade_reports/final_report.py](webapp/services/grade_reports/final_report.py) | Сборка многолистового Excel итогового отчёта школы: агрегации из `GradeReport`, диаграммы, ручные секции. |
| [grade_reports/excel/](webapp/services/grade_reports/excel/__init__.py) | Генерация Excel-отчётов: `analytics.py`, `charts.py`, `class_teacher.py`, `grades_class.py`, `criteria.py` (ZIP по критериям), общие `styles.py`. |

#### `webapp/templates/` — Jinja2-шаблоны

Базовый лейаут и шесть подпапок по ролям/разделам.

| Путь | Назначение |
|------|------------|
| [templates/layout.html](webapp/templates/layout.html) | Базовый лейаут (head, навигация, переключатель языка, flash-сообщения). |
| [templates/main/home.html](webapp/templates/main/home.html) | Лендинг для неавторизованных (описание, ссылка на скачивание десктопа). |
| [templates/auth/login.html](webapp/templates/auth/login.html) | Форма логина. |
| [templates/setup/setup.html](webapp/templates/setup/setup.html) | Форма создания первого суперадмина. |
| [templates/superadmin/dashboard.html](webapp/templates/superadmin/dashboard.html) | Панель суперадмина: школы, школьные админы, AI-модели. |
| [templates/superadmin/password.html](webapp/templates/superadmin/password.html) | Смена пароля суперадмина. |
| [templates/admin/dashboard.html](webapp/templates/admin/dashboard.html) | Стартовая страница школы для `SCHOOL_ADMIN`. |
| [templates/admin/management.html](webapp/templates/admin/management.html) | Управление учителями/классами/предметами (CRUD, связи). |
| [templates/admin/analytics_home.html](webapp/templates/admin/analytics_home.html) | Аналитика школы: карточки и сводные графики. |
| [templates/admin/grades_overview.html](webapp/templates/admin/grades_overview.html) | Сводная таблица оценок по предметам/классам. |
| [templates/admin/grades_class.html](webapp/templates/admin/grades_class.html) | Детальная таблица оценок по классу с фильтрами. |
| [templates/admin/criteria_overview.html](webapp/templates/admin/criteria_overview.html) | Обзор критериального оценивания (СОР/СОЧ) по классам/предметам. |
| [templates/admin/criteria_class.html](webapp/templates/admin/criteria_class.html) | Критериальные оценки по классу. |
| [templates/admin/criteria_subject.html](webapp/templates/admin/criteria_subject.html) | Критериальные оценки по предмету. |
| [templates/admin/class_metrics_charts.html](webapp/templates/admin/class_metrics_charts.html) | Графики метрик по классу. |
| [templates/admin/final_report_input.html](webapp/templates/admin/final_report_input.html) | Форма ввода ручных данных итогового отчёта (ГИА, ЕНТ, аттестаты) по учебным годам. |
| [templates/admin/class_teacher_report.html](webapp/templates/admin/class_teacher_report.html) | Сводный отчёт «класс × классный руководитель». |
| [templates/admin/subject_detail.html](webapp/templates/admin/subject_detail.html) | Карточка предмета (учителя, классы, оценки). |
| [templates/admin/school_detail.html](webapp/templates/admin/school_detail.html) | Детальная карточка школы. |
| [templates/admin/password.html](webapp/templates/admin/password.html) | Смена пароля школьного админа. |
| [templates/teacher/dashboard.html](webapp/templates/teacher/dashboard.html) | Кабинет учителя: запуск скрапера, список отчётов, цели, скачивание, AI-текст. |

#### `webapp/static/` — статика

CSS подключается из `layout.html` (CDN/инлайн); собственный JS — для асинхронного экспорта Excel из админ-панели:

| Путь | Назначение |
|------|------------|
| [static/js/admin_async_export.js](webapp/static/js/admin_async_export.js) | Запуск фонового экспорта (`POST /admin/exports`) и UI-индикация. |
| [static/js/admin_export_poll.js](webapp/static/js/admin_export_poll.js) | Опрос статуса `ExportJob` и автоскачивание готового файла. |

#### `webapp/translations/` — i18n (Babel)

Gettext-каталоги для двух локалей:

| Путь | Роль |
|------|------|
| `webapp/translations/ru/LC_MESSAGES/messages.po` | Исходник русского перевода. |
| `webapp/translations/ru/LC_MESSAGES/messages.mo` | Скомпилированный бинарник (обновляется через [scripts/dev/compile_translations.py](scripts/dev/compile_translations.py)). |
| `webapp/translations/kk/LC_MESSAGES/messages.po` | Исходник казахского перевода. |
| `webapp/translations/kk/LC_MESSAGES/messages.mo` | Скомпилированный бинарник. |

Помимо Babel-каталогов используется ручной словарь `TRANSLATIONS` в [webapp/translator.py](webapp/translator.py), доступный в шаблонах как `_("key")` (инъектируется через `context_processor` в `create_app`).

### `mektep-desktop/` — PyQt6-клиент

Десктоп-приложение для учителя: логин в платформу по JWT, запуск Playwright-скрапера `scrape_mektep.py`, финализация отчётов (перемещение, переименование, загрузка на сервер), локальный SQLite-архив отчётов, просмотр сводных таблиц оценок, редактирование «целей обучения» и AI-генерация текста. Собирается в EXE через PyInstaller и упаковывается в установщик Inno Setup; автообновление — через манифест `latest.json` на `/updates/` (см. [UPDATES.md](mektep-desktop/UPDATES.md) и [RELEASE.md](mektep-desktop/RELEASE.md)).

#### Файлы корня пакета

| Файл | Назначение |
|------|------------|
| [mektep-desktop/main.py](mektep-desktop/main.py) | Точка входа: `QApplication`, настройка палитры/шрифта, диалог логина, `MektepMainWindow`. Защищает `sys.stdout/stderr` от `None` в frozen-режиме. |
| [mektep-desktop/version.py](mektep-desktop/version.py) | `APP_NAME = "mektep-desktop"`, `APP_VERSION` — обновляется при релизе, читается `build.py`, передаётся в PyInstaller и Inno Setup. |
| [mektep-desktop/build.py](mektep-desktop/build.py) | Сборка: копирует модули скрапера/шаблоны из корня, проверяет иконку, ставит PyInstaller, запускает `.spec`; в режиме folder затем собирает установщик через Inno Setup (`ISCC`) и генерирует `dist/latest.json` (с sha256). Режимы `folder` (default) и `onefile`. |
| [mektep-desktop/mektep_desktop.spec](mektep-desktop/mektep_desktop.spec) | PyInstaller spec: onedir-сборка (`dist/Mektep Desktop/`). |
| [mektep-desktop/mektep_desktop_onefile.spec](mektep-desktop/mektep_desktop_onefile.spec) | PyInstaller spec: одиночный EXE (`dist/Mektep Desktop.exe`). |
| [mektep-desktop/installer.iss](mektep-desktop/installer.iss) | Inno Setup script: упаковывает onedir-папку в `dist/MektepDesktopSetup-<ver>.exe` (тихая установка, `AppId` фиксирован для in-place upgrade). |
| [mektep-desktop/UPDATES.md](mektep-desktop/UPDATES.md) | Публикация обновлений: структура `/updates/`, Nginx, формат `latest.json`, откат. |
| [mektep-desktop/RELEASE.md](mektep-desktop/RELEASE.md) | Чек-лист релиза десктопа (версии, сборка, публикация). |
| [mektep-desktop/_download_logo.py](mektep-desktop/_download_logo.py) | Скачивает логотип EDUS и конвертирует его в `.ico`; вызывается из `build.py` при отсутствии иконки. |
| [mektep-desktop/requirements.txt](mektep-desktop/requirements.txt) | Зависимости клиента: `PyQt6`, `playwright`, `openpyxl`, `python-docx`, `openai`, `PyJWT`, `requests`, `python-dotenv`, `packaging`. |
| `scrape_mektep.py`, `scraper_logger.py`, `grade_table_signals.py`, `build_report.py`, `build_word_report.py`, `iin_utils.py` | Копии корневых модулей, автоматически синхронизируемые `build.py` перед сборкой EXE (в `.gitignore` десктопа). |
| `Шаблон.xlsx` / `Шаблон.docx` / `Шаблон_каз.docx` | Копии шаблонов отчётов (копируются `build.py` из корня). |

#### `mektep-desktop/app/` — UI-слой

| Файл | Роль |
|------|------|
| [app/__init__.py](mektep-desktop/app/__init__.py) | Пакетный маркер (`__version__ = "1.2.1"`). |
| [app/main_window.py](mektep-desktop/app/main_window.py) | `MektepMainWindow` — главное окно: табы «Создание отчётов», «История», «Оценки», «Отчёт предметника», «Отчёт классного руководителя», меню «Настройки», «Цели», «Обновление». |
| [app/login_dialog.py](mektep-desktop/app/login_dialog.py) | `LoginDialog` — авторизация на сервере Mektep Scraper, авто-вход по сохранённому токену (`QSettings`). |
| [app/settings_dialog.py](mektep-desktop/app/settings_dialog.py) | `SettingsDialog` — вкладки «Сервер», «Папка отчётов», «Язык»; хранение в `QSettings`. |
| [app/goals_dialog.py](mektep-desktop/app/goals_dialog.py) | `GoalsDialog` — редактор целей обучения; применение изменений к Word-отчётам. |
| [app/history_widget.py](mektep-desktop/app/history_widget.py) | `HistoryWidget` — таблица ранее сгенерированных отчётов с фильтрами (период/класс/предмет). |
| [app/grades_widget.py](mektep-desktop/app/grades_widget.py) | `GradesWidget` — сводная таблица оценок по классам и предметам, которые ведёт учитель. |
| [app/subject_report_widget.py](mektep-desktop/app/subject_report_widget.py) | `SubjectReportWidget` — отчёт предметника: по классам «5»/«4»/«3»/«2», качество %, успеваемость %, СОР/СОЧ. |
| [app/class_report_widget.py](mektep-desktop/app/class_report_widget.py) | `ClassReportWidget` — отчёт классного руководителя: отличники/хорошисты/«с одной 4»/троечники/«с одной 3»/неуспевающие. |
| [app/loading_overlay.py](mektep-desktop/app/loading_overlay.py) | `LoadingOverlay` + `SpinnerWidget` — полупрозрачный оверлей с анимированным спиннером (12 точек). |
| [app/api_client.py](mektep-desktop/app/api_client.py) | `MektepAPIClient` — HTTP-клиент к серверу: логин, рефреш JWT, загрузка отчётов, аналитика, проверка версии. |
| [app/scraper_thread.py](mektep-desktop/app/scraper_thread.py) | `ScraperThread(QThread)` — запускает `scrape_mektep.run()` в отдельном потоке, эмитит сигналы прогресса, взаимодействует с `ReportFinalizer`. |
| [app/reports_manager.py](mektep-desktop/app/reports_manager.py) | `ReportsManager` — локальная SQLite-база метаданных отчётов (путь к файлам, период, класс/предмет). |
| [app/translator.py](mektep-desktop/app/translator.py) | `Translator(QObject)` с сигналом `language_changed` — переводы UI на `ru`/`kk`. |
| [app/updater.py](mektep-desktop/app/updater.py) | Автообновление через Inno Setup: `check_for_update()` (манифест `latest.json`), `download_installer()` (скачивание + проверка sha256), `launch_installer_and_exit()` (тихая установка `/SILENT`); фоновые `UpdateCheckWorker`/`UpdateDownloadWorker` (QThread). |
| [app/period_ui.py](mektep-desktop/app/period_ui.py) | Общие значения селектора периода (четверти 1–4, `YEAR_UI_PERIOD`). |
| [app/sort_utils.py](mektep-desktop/app/sort_utils.py) | `kazakh_sort_key()` — казахская кириллическая сортировка (аналог `webapp/constants.py`). |
| [app/debug_log.py](mektep-desktop/app/debug_log.py) | JSON-логгер в `mektep-debug.log` (корень репо): `debug_log()` (развёрнутый) и `dbg_log()` (краткий). |

> Папка `mektep-desktop/app/scraper/` существует, но на данный момент пустая (зарезервирована для будущего вынесения Playwright-логики из корневого `scrape_mektep.py`).

#### `mektep-desktop/app/report_pipeline/` — постобработка отчётов

Отдельный пакет, который превращает сырой вывод скрапера в готовые файлы и загружает их на сервер.

| Файл | Роль |
|------|------|
| [report_pipeline/__init__.py](mektep-desktop/app/report_pipeline/__init__.py) | Docstring-пакет. |
| [report_pipeline/period_map.py](mektep-desktop/app/report_pipeline/period_map.py) | `PERIOD_MAP` для подписей четвертей; при наличии `webapp` импортирует из `webapp.constants`, иначе использует локальную копию. |
| [report_pipeline/progress_monitor.py](mektep-desktop/app/report_pipeline/progress_monitor.py) | `read_progress_data()`, `parse_schools_from_progress_message()` (префикс `schools_selection_needed\|`), `format_progress_line()`. |
| [report_pipeline/report_utils.py](mektep-desktop/app/report_pipeline/report_utils.py) | `move_file()` (с fallback на copy), хелперы имён файлов и определения периода. |
| [report_pipeline/report_finalization.py](mektep-desktop/app/report_pipeline/report_finalization.py) | `ReportFinalizer` — перемещение `.xlsx`/`.docx` в папку пользователя, конвертация JSON → grades/analytics, загрузка на сервер через `MektepAPIClient`. |
| [report_pipeline/run_environment.py](mektep-desktop/app/report_pipeline/run_environment.py) | `ensure_std_streams()`, подготовка `os.environ`, `sys.path`, шаблонов и Playwright для запуска `scrape_mektep.run()` из frozen-EXE. |

#### `mektep-desktop/ai/` — AI-генерация

| Файл | Роль |
|------|------|
| [ai/__init__.py](mektep-desktop/ai/__init__.py) | Docstring-пакет. |
| [ai/text_generator.py](mektep-desktop/ai/text_generator.py) | `AITextGenerator` — клиент к Qwen/DashScope через `openai` SDK: генерирует `difficulties_list`/`reasons`/`recommendations` по целям обучения и оценкам; retry-логика. Язык ответа автоматически определяется по языку входных целей (ru/kk). |

#### `mektep-desktop/resources/` — ресурсы

| Путь | Назначение |
|------|------------|
| [resources/icons/app_icon.ico](mektep-desktop/resources/icons/app_icon.ico) | Иконка приложения (окно, панель задач, меню Пуск, EXE). |
| [resources/img/logo_edus_logo_white.png](mektep-desktop/resources/img/logo_edus_logo_white.png) | Логотип EDUS для главного окна. |
| `resources/img/.gitkeep`, `resources/img/README.txt` | Служебные файлы папки. |

#### Инфраструктура обновлений (Inno Setup + `latest.json`)

Обновления выпускаются как установщик Inno Setup; клиент сравнивает свою `APP_VERSION` с манифестом `latest.json` на сервере и при наличии новой версии скачивает и тихо устанавливает `setup.exe`.

| Путь | Что это |
|------|---------|
| `mektep-desktop/dist/MektepDesktopSetup-<ver>.exe` | Готовый установщик Inno Setup (артефакт сборки `python build.py`). |
| `mektep-desktop/dist/latest.json` | Манифест автообновления (`version`, `url`, `sha256`, `min_version`, `mandatory`, `notes`). Публикуется на сервер в `updates/`. |
| `mektep-desktop/build/` | PyInstaller build (spec-temp). Артефакт. |
| `mektep-desktop/dist/` | Готовые EXE, onedir-папки и установщик. Артефакт. |
| `mektep-desktop/.pyupdater/`, `mektep-desktop/pyu-data/` | Наследие PyUpdater; больше не используется, оставлено в `.gitignore`. Артефакт. |
| `mektep-desktop/debug-*.log` | Отладочные логи клиента. Артефакт. |

### `scripts/` — обслуживающие скрипты

Разделены на `db/` (операции с базой) и `dev/` (локальные dev-утилиты). Запускаются из корня репозитория командой вида `python -m scripts.db.<name>` или `python -m scripts.dev.<name>`.

#### `scripts/db/`

| Файл | Что делает |
|------|------------|
| [scripts/db/add_ai_api_key_column.py](scripts/db/add_ai_api_key_column.py) | Миграция: добавляет колонку `ai_api_key VARCHAR(512)` в таблицу `schools`. |
| [scripts/db/add_progress_columns.py](scripts/db/add_progress_columns.py) | Миграция: добавляет в `scrape_jobs` колонки `progress_percent`, `progress_message`, `total_reports`, `processed_reports`. |
| [scripts/db/add_final_report_data.py](scripts/db/add_final_report_data.py) | Миграция: создаёт таблицу `final_report_data` для ручных данных итогового отчёта (ГИА, ЕНТ, аттестаты). |
| [scripts/db/fix_semester_grades.py](scripts/db/fix_semester_grades.py) | Чистка: удаляет некорректные `GradeReport` c `period_type="quarter"` для полугодовых предметов (dry-run по умолчанию, `--apply` применяет). |
| [scripts/db/recover_reports.py](scripts/db/recover_reports.py) | Восстанавливает записи `ReportFile` из файлов на диске (каталоги задач скрапинга) — полезно после потери БД. |
| [scripts/db/reset_platform_db.py](scripts/db/reset_platform_db.py) | Удаляет SQLite-файл `instance/mektep_platform.db` и чистит `migrations/versions/`. Используется в dev. |

#### `scripts/dev/`

| Файл | Что делает |
|------|------------|
| [scripts/dev/clean_out.py](scripts/dev/clean_out.py) | Пересоздаёт каталог `out/mektep/{reports,batch}` (по умолчанию; `--path` переопределяет цель). |
| [scripts/dev/clear_test_data.py](scripts/dev/clear_test_data.py) | Показывает тестовые `GradeReport`/`ReportFile`/`Class`; с флагом `--delete` удаляет и сбрасывает привязки. |
| [scripts/dev/compile_translations.py](scripts/dev/compile_translations.py) | Компилирует `webapp/translations/*/LC_MESSAGES/messages.po` → `messages.mo` через `msgfmt` или `polib`. |
| [scripts/dev/seed_test_data.py](scripts/dev/seed_test_data.py) | Тонкая обёртка: `from seed_test_data import *` — запуск корневого `seed_test_data.py` как модуля пакета. |
| [scripts/dev/split_admin_views.py](scripts/dev/split_admin_views.py) | Разовая dev-утилита: помогала разнести монолитный `views/admin.py` на пакет `views/admin/` (management/reports/exports). |

### `entrypoints/` — точки входа веба

Все реальные точки входа веб-приложения вынесены сюда; корневые файлы ([app.py](app.py), [wsgi.py](wsgi.py), [run_production.py](run_production.py), [gunicorn_config.py](gunicorn_config.py)) — тонкие прокси, сохранённые для обратной совместимости.

| Файл | Назначение |
|------|------------|
| [entrypoints/\_\_init\_\_.py](entrypoints/__init__.py) | Маркер пакета (docstring). |
| [entrypoints/app.py](entrypoints/app.py) | Dev-сервер: `app = create_app()`; запуск на `127.0.0.1:5000` без reloader (чтобы фоновые потоки скрапера не убивались). |
| [entrypoints/wsgi.py](entrypoints/wsgi.py) | WSGI-объект для Gunicorn/uWSGI/Waitress; `load_dotenv()` до `create_app()`. |
| [entrypoints/run_production.py](entrypoints/run_production.py) | Production-лаунчер: на Windows запускает Waitress, на Unix — Gunicorn (`gunicorn -c entrypoints/gunicorn_config.py entrypoints.wsgi:app`). |
| [entrypoints/gunicorn_config.py](entrypoints/gunicorn_config.py) | Параметры Gunicorn: `workers=min(4, cpu*2)`, `threads=2`, `timeout=120`, `max_requests=1000`, `preload_app=true`, security-лимиты заголовков, hooks `on_starting`/`worker_abort`/`worker_exit`. |

### `deploy/` и `nginx/` — инфраструктура

#### `deploy/`

Инфраструктурные файлы для production-развёртывания. Продублированы в корне для привычного `docker compose up` без `-f`.

| Файл | Назначение |
|------|------------|
| [deploy/Dockerfile](deploy/Dockerfile) | Двухстадийная сборка на `python:3.13-slim`: builder ставит зависимости из [requirements.txt](requirements.txt), final-образ — минимальный runtime с `libpq5`; CMD `python run_production.py`. |
| [deploy/docker-compose.yml](deploy/docker-compose.yml) | Сервисы: `nginx` (80/443), `web` (expose 5000, `USE_CELERY=0`, маунтит `data/` и `instance/`), `db` (postgres:16-alpine, healthcheck `pg_isready`), `node-exporter`, `prometheus` (9090), `grafana` (3000). Общая сеть `mektep-network`, тома `postgres-data` и `grafana-data`. |
| [deploy/prometheus.yml](deploy/prometheus.yml) | Scrape-конфиг: job `mektep-webapp` → `web:5000/metrics` и job `node-exporter` → `node-exporter:9100`. |

#### `nginx/`

| Файл | Назначение |
|------|------------|
| [nginx/nginx.conf](nginx/nginx.conf) | Reverse-proxy для `web:5000`: gzip, security-заголовки (`X-Frame-Options`, `X-Content-Type-Options`, `X-XSS-Protection`), `limit_req_zone api_limit=10r/s` (burst 20) на `/api/`, `client_max_body_size 50M`, статика `/static/` → `/app/webapp/static/`, раздача обновлений десктопа `/updates/` → `/var/www/mektep/updates/` (`latest.json` с `no-cache`), закомментированный HTTPS-server с HSTS. |

### `tests/` и `docs/`

#### `tests/`

| Файл | Что тестирует |
|------|---------------|
| [tests/test_report_utils.py](tests/test_report_utils.py) | Юнит-тесты `app.report_pipeline.*` (десктоп): `parse_class_liter`, `parse_number`, `sanitize_filename`, `resolve_period`, `normalize_period_code`, `is_semester_subject`, `parse_schools_from_progress_message`, `format_progress_line`. |
| [tests/test_grade_table_signals.py](tests/test_grade_table_signals.py) | Эвристики распознавания видимой таблицы критериального оценивания (`grade_table_signals`). |
| [tests/test_grade_report_payload.py](tests/test_grade_report_payload.py) | Хелперы `grade_reports.payload` (разбор `grades_json`/`analytics_json`). |
| [tests/test_grade_report_queries.py](tests/test_grade_report_queries.py) | Выборки `grade_reports.queries` по периодам. |
| [tests/test_grade_report_context.py](tests/test_grade_report_context.py) | Кэширование payload/analytics в `SchoolPeriodContext`. |
| [tests/test_class_grades_matrix.py](tests/test_class_grades_matrix.py) | Матрица оценок класса (`class_grades_matrix`). |
| [tests/test_class_teacher_categories.py](tests/test_class_teacher_categories.py) | Категоризация учеников и блоки отчёта классного руководителя. |
| [tests/test_criteria_subject_entries.py](tests/test_criteria_subject_entries.py) | Сопоставление предметов в нескольких школах (критериальное оценивание). |
| [tests/test_student_edits.py](tests/test_student_edits.py) | Удаление ученика из `grades_json` (`student_edits`). |
| [tests/test_subject_aliases.py](tests/test_subject_aliases.py) | Нормализация названий предметов по словарю алиасов. |
| [tests/test_teacher_schools.py](tests/test_teacher_schools.py) | Учитель в нескольких школах: членство и активная школа. |
| [tests/test_year_grades.py](tests/test_year_grades.py) | Расчёт годовых оценок (`year_grades`). |
| [tests/test_final_report.py](tests/test_final_report.py) | Сборка итогового отчёта школы в Excel и round-trip `FinalReportData`. |

Конфиг [pytest.ini](pytest.ini) добавляет `mektep-desktop/` в `pythonpath`, чтобы `app.*` (десктоп) импортировался из корня репо. Запуск: `python -m pytest` (из корня).

#### `docs/`

Папка зарезервирована под будущую документацию (архитектурные схемы, ADR, описание API). На данный момент пустая; актуальные документы живут в корне: [README.md](README.md), [ИНСТРУКЦИЯ_ЗАПУСКА.md](ИНСТРУКЦИЯ_ЗАПУСКА.md), [МЕТОДИЧЕСКОЕ_ПОСОБИЕ_СОДЕРЖАНИЕ.md](МЕТОДИЧЕСКОЕ_ПОСОБИЕ_СОДЕРЖАНИЕ.md).

### Runtime и артефакты сборки

Каталоги и файлы, которые появляются во время работы/сборки и исключены из git правилами [.gitignore](.gitignore). В свежем клоне их может не быть — они создаются автоматически при первом запуске/сборке.

| Путь | Источник | Назначение |
|------|----------|------------|
| `.venv/`, `.venv-3.11/` | `python -m venv` | Локальные виртуальные окружения. Исключены через `.venv/` в [.gitignore](.gitignore). |
| `.cursor/` | Cursor IDE | Настройки/кэш Cursor (rules, planы, транскрипты). Исключён через `.cursor/`. |
| `.pytest_cache/` | pytest | Кэш pytest между прогонами. |
| `__pycache__/` | Python | Скомпилированные `.pyc`. Игнорируется правилом `__pycache__/`. |
| [instance/mektep_platform.db](instance/) | Flask + SQLite | Дев-база платформы (создаётся `db.create_all()` при первом запуске). `instance/` целиком исключена. |
| `out/platform_runs/<job_id>_<timestamp>/` | [webapp/scraper_runner.py](webapp/scraper_runner.py) | Рабочие директории прогонов скрапера: `progress.json`, извлечённые JSON, сырые Excel/Word. |
| `out/platform_uploads/school_<id>/` | [webapp/views/teacher.py](webapp/views/teacher.py), [webapp/views/api.py](webapp/views/api.py) | Загруженные финальные отчёты, сгруппированные по школе. |
| `data/` (в Docker) | [deploy/docker-compose.yml](deploy/docker-compose.yml) | Монтируется в `/app/data` контейнера `web` (upload root). |
| `build/`, `dist/` (корень) | PyInstaller | Артефакты сборки EXE, если собирать из корня. Обычно пусты, реальная сборка идёт в `mektep-desktop/`. |
| `mektep-desktop/build/`, `mektep-desktop/dist/` | PyInstaller / Inno Setup | Промежуточные и итоговые файлы сборки (EXE, `MektepDesktopSetup-*.exe`, `latest.json`). |
| `updates/` | релиз десктопа | Опубликованные `latest.json` + установщик; раздаётся Nginx по `/updates/`. В git хранится только `.gitkeep`. |
| `mektep-desktop/.pyupdater/`, `mektep-desktop/pyu-data/` | PyUpdater (наследие) | Старые рабочие каталоги PyUpdater; больше не используются. |
| `migrations/` | Flask-Migrate | Alembic-миграции (создаются командой `flask db init`). Сейчас схема поднимается через `db.create_all()` + runtime-ALTER в [webapp/__init__.py](webapp/__init__.py). |
| `postgres-data/` | Docker volume | Тома PostgreSQL (в `docker compose`). Исключён через `postgres-data/`. |
| `nginx/ssl/` | оператор | TLS-сертификаты (не коммитить). Исключены через `nginx/ssl/`. |
| `mektep-debug.log` | [mektep-desktop/app/debug_log.py](mektep-desktop/app/debug_log.py) | Единый JSON-лог отладки десктопа (в корне репо). |
| `debug-<hash>.log` | скрапер/веб | Отладочные логи прогонов ([debug-4e9670.log](debug-4e9670.log), [debug-91cc02.log](debug-91cc02.log), …). Все `*.log` игнорируются. |
| `api_key.txt` | пользователь | Локальный файл с AI-ключом (не коммитить). Игнорируется явно. |
| `.env` | пользователь | Локальные секреты и настройки окружения — копия [env.example](env.example). Игнорируется через `.env`. |

> Все перечисленные пути находятся под действием правил [.gitignore](.gitignore) (`.venv/`, `build/`, `dist/`, `instance/`, `data/`, `out/`, `*.db`, `*.log`, `postgres-data/`, `nginx/ssl/`, `__pycache__/`, `.cursor/` и др.).

---

## Быстрый старт (веб)

Минимальный набор шагов для поднятия веб-платформы локально на SQLite.

### Предусловия

- Python 3.11+ (проверить: `python --version`).
- Доступ в интернет для установки зависимостей и скачивания Chromium (~170 МБ).
- Redis — **опционально**; без него работает in-memory fallback для rate-limit, а `USE_CELERY=0` гарантирует, что фоновые задачи идут в потоках (см. [webapp/scraper_runner.py](webapp/scraper_runner.py)).

### Шаг 1. Клонирование и окружение

```bash
git clone <repo-url>
cd pdf-to-excel-scraper-main

python -m venv .venv
```

Активация виртуального окружения:

- Windows (PowerShell): `.venv\Scripts\Activate.ps1`
- Windows (cmd): `.venv\Scripts\activate.bat`
- Linux/macOS: `source .venv/bin/activate`

### Шаг 2. Зависимости

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

Для запуска тестов и линтеров дополнительно:

```bash
pip install -r requirements-dev.txt
```

### Шаг 3. Конфигурация

```bash
# Windows
copy env.example .env
# Linux/macOS
cp env.example .env
```

Отредактируйте [.env](env.example) — минимально достаточно оставить `FLASK_ENV=development`. Для первого входа можно задать:

```
BOOTSTRAP_SUPERADMIN_USER=admin
BOOTSTRAP_SUPERADMIN_PASS=admin123
```

Если оставить пустыми — используются те же значения по умолчанию (`admin`/`admin123`), см. `create_app()` в [webapp/__init__.py](webapp/__init__.py).

### Шаг 4. Инициализация БД

При первом запуске Flask создаст SQLite-базу [instance/mektep_platform.db](instance/) через `db.create_all()` и выполнит «лёгкие» ALTER-ы недостающих колонок. Дополнительных команд не требуется.

Опционально можно наполнить тестовые данные (школа «Test», учителя, классы, предметы, оценки):

```bash
python seed_test_data.py
```

### Шаг 5. Запуск dev-сервера

```bash
python app.py
```

Dev-сервер слушает `http://127.0.0.1:5000` без авто-перезагрузки (иначе убивались бы фоновые потоки скрапера). При изменениях кода перезапускайте вручную (Ctrl+C → повторный запуск).

Зайдите на `http://localhost:5000`, авторизуйтесь как суперадмин (по умолчанию `admin`/`admin123`) и смените пароль. Затем:

1. Создайте школу (раздел «Суперадмин»).
2. Создайте для неё школьного админа.
3. Войдите под школьным админом и добавьте учителей, классы и предметы.
4. Учителя входят **только** через десктоп-клиент; их логин/пароль используются для входа в `mektep.edu.kz` через десктоп.

### Production-запуск (без Docker)

```bash
# универсально: Gunicorn на Unix, Waitress на Windows
python run_production.py
```

Либо вручную:

```bash
# Unix
gunicorn -c entrypoints/gunicorn_config.py entrypoints.wsgi:app

# Windows
python -c "from waitress import serve; from entrypoints.wsgi import app; serve(app, host='0.0.0.0', port=5000, threads=4)"
```

Подробные параметры в [entrypoints/gunicorn_config.py](entrypoints/gunicorn_config.py) и [entrypoints/run_production.py](entrypoints/run_production.py) (все переопределяются через env `GUNICORN_*` / `WAITRESS_*`).

### Docker Compose

Полный стек (Nginx + Flask + PostgreSQL + Prometheus + Grafana + node-exporter) поднимается одной командой.

1. Подготовьте `.env`:

   ```bash
   cp env.example .env
   # обязательные для Docker:
   # SECRET_KEY=<python -c "import secrets; print(secrets.token_hex(32))">
   # POSTGRES_PASSWORD=<python -c "import secrets; print(secrets.token_hex(16))">
   # GRAFANA_ADMIN_PASSWORD=<your-password>
   ```

2. Поднимите сервисы:

   ```bash
   docker compose -f deploy/docker-compose.yml up -d --build
   ```

3. Проверьте статус:

   ```bash
   docker compose -f deploy/docker-compose.yml ps
   docker compose -f deploy/docker-compose.yml logs -f web
   ```

| Сервис | Порт (host) | Назначение |
|--------|-------------|------------|
| `nginx` | 80, 443 | Reverse-proxy на `web:5000`, rate-limit `/api/`, кэш `/static/`. |
| `web` | — (только внутри сети) | Flask + Waitress/Gunicorn, `USE_CELERY=0` в простой архитектуре. |
| `db` | — (по умолчанию без проброса) | PostgreSQL 16-alpine, healthcheck `pg_isready`. Для локальной отладки раскомментируйте `ports: 5432:5432`. |
| `node-exporter` | — | Системные метрики (CPU/RAM/диск) для Prometheus. |
| `prometheus` | 9090 | Сбор метрик с `web:5000/metrics` и `node-exporter:9100`. |
| `grafana` | 3000 | Дашборды. Логин `admin`, пароль из `GRAFANA_ADMIN_PASSWORD`. |

Данные PostgreSQL сохраняются в volume `postgres-data`, данные Grafana — в `grafana-data`. Данные приложения маунтятся из хост-папок `./data` и `./instance` — см. [deploy/docker-compose.yml](deploy/docker-compose.yml).

Остановка и чистка:

```bash
docker compose -f deploy/docker-compose.yml down           # остановить контейнеры
docker compose -f deploy/docker-compose.yml down -v        # + удалить volumes (ВНИМАНИЕ: сотрёт БД)
```

---

## Десктоп (Mektep Desktop)

PyQt6-клиент для учителя. Работает в двух режимах: **dev** (из исходников) и **prod** (собранный EXE).

### Dev-запуск из исходников

Запускайте из каталога `mektep-desktop/` — так импортируются и пакет `app.*`, и корневой `scrape_mektep` (через `sys.path`):

```bash
cd mektep-desktop
python -m venv .venv
.venv\Scripts\activate             # Windows
# source .venv/bin/activate        # Linux/macOS

pip install -r requirements.txt
python -m playwright install chromium
python main.py
```

При первом запуске откроется диалог логина. Настройки подключения:

- **URL сервера** — по умолчанию берётся из `QSettings("Mektep","MektepDesktop")` (production: `https://mektep-analyzer.kz/`). Для локальной разработки укажите `http://127.0.0.1:5000` в диалоге «Настройки» → «Сервер».
- **Логин/пароль** — те, что создал школьный админ для учителя. На десктопе учитель дополнительно вводит учётные данные `mektep.edu.kz` (логин/ИИН + пароль), которые используются Playwright-скрапером.

Папка для сохранения отчётов задаётся в «Настройки» → «Папка отчётов» (по умолчанию — `Documents/Mektep Reports/`).

### Сборка установщика

[mektep-desktop/build.py](mektep-desktop/build.py) автоматизирует всю цепочку: копирует модули скрапера и шаблоны из корня, проверяет иконку (при отсутствии — скачивает через [`_download_logo.py`](mektep-desktop/_download_logo.py)), ставит PyInstaller, запускает нужный `.spec`, а в режиме `folder` дополнительно собирает установщик Inno Setup и генерирует `latest.json`.

```bash
cd mektep-desktop

# folder + установщик Inno Setup + latest.json (для релиза и автообновления)
python build.py

# onefile — один EXE-файл, без установщика (для быстрой раздачи)
python build.py onefile
```

Результаты:

- `mektep-desktop/dist/Mektep Desktop/Mektep Desktop.exe` (onedir)
- `mektep-desktop/dist/MektepDesktopSetup-<version>.exe` + `dist/latest.json` (folder + Inno Setup)
- `mektep-desktop/dist/Mektep Desktop.exe` (onefile)

Для сборки установщика нужен установленный **Inno Setup 6** (`ISCC.exe` ищется в `C:\Program Files (x86)\Inno Setup 6\`). Если он не найден, `build.py` соберёт только папку и подскажет, что установщик не создан. Иконка лежит в [mektep-desktop/resources/icons/app_icon.ico](mektep-desktop/resources/icons/app_icon.ico), логотип — в [mektep-desktop/resources/img/logo_edus_logo_white.png](mektep-desktop/resources/img/logo_edus_logo_white.png).

### Автообновление (Inno Setup + `latest.json`)

Перед релизом обновите [mektep-desktop/version.py](mektep-desktop/version.py) (`APP_VERSION`) и при необходимости [webapp/constants.py](webapp/constants.py) (`DESKTOP_VERSION` для кнопки на сайте, `MIN_DESKTOP_VERSION` для блокировки старых клиентов). Типичный цикл (только Windows):

```bash
cd mektep-desktop
python build.py                # собрать setup.exe + latest.json
# залить оба файла на сервер в updates/ (Nginx /updates/)
scp dist/MektepDesktopSetup-<ver>.exe dist/latest.json deploy@server:~/pdf-to-excel-scraper-main/updates/
```

Клиент через ~2 с после старта фоном запрашивает `https://mektep-analyzer.kz/updates/latest.json` ([app/updater.py](mektep-desktop/app/updater.py)); если версия новее — предлагает скачать `setup.exe`, проверяет sha256 и запускает тихую установку. Также есть ручная кнопка «Проверить обновление». Полный регламент — [UPDATES.md](mektep-desktop/UPDATES.md) и [RELEASE.md](mektep-desktop/RELEASE.md).

### Раздача установщика через веб

Кнопка «Скачать приложение» на лендинге по умолчанию ведёт на установщик в `/updates/` (имя формируется из `DESKTOP_VERSION` через `desktop_download_url()` в [webapp/constants.py](webapp/constants.py)). Переопределить можно через env:

- Локальный файл: `DESKTOP_DOWNLOAD_PATH=dist/Mektep Desktop/Mektep Desktop.exe` → маршрут `/download/desktop` отдаст файл.
- Внешний URL: `DESKTOP_DOWNLOAD_URL=https://mektep-analyzer.kz/updates/MektepDesktopSetup-1.2.1.exe` (имеет приоритет; GitHub Releases-ссылки нормализуются в прямую ссылку на ассет).

См. [webapp/views/main.py](webapp/views/main.py) (`_get_desktop_download_info`).

---

## Итоговый отчёт школы

Школьный **итоговый отчёт** — многолистовой Excel-файл со сводной аналитикой за учебный год (и динамикой до 3 лет). Автоматические разделы строятся из загруженных в платформу `GradeReport`; данные ГИА, ЕНТ и аттестатов вводятся вручную (их нет в оценках mektep).

### Что входит в Excel

| Лист | Источник |
|------|----------|
| **Динамика численности** (первая вкладка) | Таблица за 3 учебных года: учащиеся на начало/конец года, классы-комплекты, наполняемость по ступеням; годы без данных — «-» |
| Сводка | KPI школы и ступеней (1–4 / 5–9 / 10–11) за учебный год |
| Успеваемость по классам | Распределение на «5»/«4»/«3»/«2», % успеваемости и качества |
| По ступеням / По четвертям | Агрегации + диаграмма динамики качества |
| Качество по предметам | Матрица предмет × класс |
| Проблемные зоны | Предметы/классы с наименьшим качеством |
| Отличники | Ученики со всеми оценками «5» |
| ГИА-9, ГИА-11, ЕНТ, Аттестаты | Ручной ввод (`FinalReportData`) |

### Как сформировать (школьный админ)

1. Убедитесь, что учителя загрузили оценки за нужные четверти/год (через десктоп-клиент).
2. На дашборде `/admin` откройте **«Итоговый отчёт — ввод данных»** (`/admin/final-report/input`) и заполните вкладки **ГИА 9**, **ГИА 11**, **ЕНТ**, **Аттестаты** для выбранного учебного года.
3. На дашборде нажмите **«Сформировать итоговый отчёт»** — файл соберётся асинхронно (`export_kind=final_report`) и скачается как `Итоговый_отчёт_<годы>.xlsx`.

Параметры экспорта (JSON в `POST /admin/exports`):

```json
{
  "export_kind": "final_report",
  "academic_year": 2025,
  "years_back": 3
}
```

### Миграция БД (существующие инсталляции)

Таблица `final_report_data` создаётся при `db.create_all()` при старте приложения. На production можно выполнить явно:

```bash
python -m scripts.db.add_final_report_data
```

### Код

- Модель: `FinalReportData` в [webapp/models.py](webapp/models.py) (`section`: `gia9` | `gia11` | `ent` | `awards`).
- Сборщик: [webapp/services/grade_reports/final_report.py](webapp/services/grade_reports/final_report.py).
- Тесты: [tests/test_final_report.py](tests/test_final_report.py).

---

## Разработка и тесты

### Инструменты разработки

```bash
pip install -r requirements-dev.txt
```

### Запуск тестов

Все команды запускаются **из корня** репозитория (конфиг [pytest.ini](pytest.ini) добавляет `mektep-desktop/` в `pythonpath`, чтобы импортировался пакет `app.*`):

```bash
python -m pytest                                  # все тесты
python -m pytest -v                               # подробный вывод
python -m pytest tests/test_report_utils.py       # один файл
python -m pytest -k "parse_class_liter"           # по имени
python -m pytest -x                               # остановить на первой ошибке
python -m pytest --lf                             # перезапустить только упавшие
```

Coverage-прогон (если установлен `pytest-cov`):

```bash
python -m pytest --cov=webapp --cov=mektep-desktop/app --cov-report=term-missing
```

### Что покрыто

Юнит-тесты двух слоёв:

- **Десктоп** (`app.report_pipeline.*`, `grade_table_signals`) — нормализация входных данных, определение периода отчёта, парсинг `progress.json`, распознавание таблицы критериев.
- **Веб** (`webapp.services.grade_reports.*`, `class_grades_matrix`, `subject_aliases`, `teacher_schools`, `year_grades`, критериальное оценивание, итоговый отчёт школы) — разбор payload, выборки по периодам, агрегации, категории классного руководителя, алиасы предметов, годовые оценки, сборка `final_report` Excel.

### Типовые dev-операции

| Задача | Команда |
|--------|---------|
| Сбросить SQLite-базу (для dev) | `python -m scripts.db.reset_platform_db --yes` |
| Создать суперадмина вручную | `flask --app entrypoints.app create-superadmin <user> <pass>` |
| Очистить Redis-кэш (FLUSHDB) | `flask --app entrypoints.app clear-cache -y` |
| Скомпилировать переводы | `python -m scripts.dev.compile_translations` |
| Почистить выход скрапера | `python -m scripts.dev.clean_out --yes` |
| Наполнить тестовыми данными | `python seed_test_data.py` |
| Проверить/удалить тестовые данные | `python -m scripts.dev.clear_test_data [--delete]` |
| Миграция `final_report_data` | `python -m scripts.db.add_final_report_data` |

### Диагностика

- Логи скрапера — в `mektep-debug.log` (корень репо) и `debug-<hash>.log`.
- Прогресс текущей задачи — `out/platform_runs/<job_id>_<ts>/progress.json`.
- `GET /health/stats` — общие счётчики (сколько задач в очереди/running/succeeded/failed).

---

## Конфигурация (веб)

Полный набор переменных окружения — в [env.example](env.example). Ниже — структурированная таблица по блокам.

### Flask / безопасность

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `FLASK_ENV` | `development` | `development` / `production` / `testing`. Выбирает класс конфига в [webapp/config.py](webapp/config.py). |
| `SECRET_KEY` | `dev-secret-key-change-me-in-production` | Секрет Flask для подписи сессий. **Обязателен в production**. Сгенерировать: `python -c "import secrets; print(secrets.token_hex(32))"`. |
| `PASSWORD_ENC_KEY` | `""` | Ключ Fernet для шифрования отображаемых паролей учителей ([webapp/security.py](webapp/security.py)). При отсутствии — детерминированно выводится из `SECRET_KEY` (только для dev). |

### База данных

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `DATABASE_URL` | `sqlite:///../instance/mektep_platform.db` | SQLAlchemy URI. Для production укажите `postgresql://user:pass@host:5432/db`. Поддерживается и Heroku-формат `postgres://` — автоматически нормализуется. |
| `POSTGRES_PASSWORD` | — | Используется [deploy/docker-compose.yml](deploy/docker-compose.yml) для пользователя `mektep`. |

### Bootstrap суперадмина

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `BOOTSTRAP_SUPERADMIN_USER` | `""` (fallback: `admin`) | Логин суперадмина при первом запуске. Если в БД ещё нет суперадмина — он будет создан автоматически. |
| `BOOTSTRAP_SUPERADMIN_PASS` | `""` (fallback: `admin123`) | Пароль суперадмина. После первого входа обязательно смените. |

### Скрапер и задачи

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `MAX_CONCURRENT_JOBS` | `3` (dev) / `5` (prod) | Лимит параллельных прогонов скрапера ([webapp/scraper_runner.py](webapp/scraper_runner.py)). Каждый прогон съедает ~1–2 ГБ RAM под Playwright. |
| `JOB_TIMEOUT_SECONDS` | `1800` (prod), `600` (dev) | Макс. время одного прогона. |
| `SCRAPER_HEADLESS` | `1` | `1` — без UI, `0` — показывать браузер (для отладки). |
| `SCRAPER_SLOWMO_MS` | `0` | Задержка между действиями Playwright, мс. |
| `MEKTEP_TIMING` | `1` | Логировать `[TIMING]`-строки для ожиданий и ключевых шагов скрапера. |
| `MEKTEP_DEBUG_ARTIFACTS` | `1` | Сохранять HTML/скриншоты-артефакты даже при успешном прогоне. |
| `UPLOAD_ROOT` | `out/platform_uploads` | Корень для загруженных/сгенерированных отчётов. В Docker — `/app/data/uploads`. |

### CLI-скрапер (`scrape_mektep.py`)

| Переменная | Описание |
|------------|----------|
| `MEKTEP_LOGIN` | Логин/ИИН для `mektep.edu.kz`. Если пусто — спросит интерактивно. |
| `MEKTEP_PASSWORD` | Пароль для `mektep.edu.kz`. Если пусто — `getpass` в терминале. |

### Redis / Celery

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `REDIS_URL` | `redis://localhost:6379/0` | URL Redis для rate-limit и Celery. При недоступности — автоматический fallback на in-memory ([webapp/redis_utils.py](webapp/redis_utils.py)). |
| `USE_CELERY` | `0` | `1` — включить Celery-задачи ([webapp/tasks.py](webapp/tasks.py)); `0` — использовать потоки в `scraper_runner`. |
| `CELERY_BROKER_URL` | `=REDIS_URL` | Переопределение брокера. |
| `CELERY_RESULT_BACKEND` | `=REDIS_URL` | Бэкенд результатов. |
| `CELERY_CONCURRENCY` | `2` | Число параллельных worker'ов Celery. |

### AI (Qwen / DashScope)

| Переменная | Описание |
|------------|----------|
| `DASHSCOPE_API_KEY` | API-ключ Qwen для AI-генерации текстов анализа. Получить: <https://dashscope.console.aliyun.com/>. Используется как default, индивидуальный ключ школы хранится в `School.ai_api_key` ([webapp/models.py](webapp/models.py)). |

### Production-сервер

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `GUNICORN_BIND` | `0.0.0.0:5000` | Адрес Gunicorn. |
| `GUNICORN_WORKERS` | `min(4, cpu*2)` | Число воркеров. |
| `GUNICORN_THREADS` | `2` | Потоков на воркер. |
| `GUNICORN_TIMEOUT` | `120` | Таймаут запроса, сек. |
| `GUNICORN_LOG_LEVEL` | `info` | Уровень логов. |
| `WAITRESS_HOST` | `0.0.0.0` | Адрес Waitress (Windows). |
| `WAITRESS_PORT` | `5000` | Порт Waitress. |
| `WAITRESS_THREADS` | `4` | Потоки Waitress. |

Остальные `GUNICORN_*` переменные — в [entrypoints/gunicorn_config.py](entrypoints/gunicorn_config.py).

### Скачивание десктопа

| Переменная | Описание |
|------------|----------|
| `DESKTOP_DOWNLOAD_PATH` | Путь к локальному EXE/ZIP, который отдаётся через `GET /download/desktop`. |
| `DESKTOP_DOWNLOAD_URL` | Внешний URL установщика. Имеет приоритет; если не задан — кнопка ведёт на `MektepDesktopSetup-<DESKTOP_VERSION>.exe` в `/updates/` (см. `desktop_download_url()` в [webapp/constants.py](webapp/constants.py)). GitHub Releases-ссылки нормализуются в прямую ссылку на ассет. |

---

## CLI-скрапер (отладка)

Инструмент командной строки [scrape_mektep.py](scrape_mektep.py) используется для локальной отладки без веб-интерфейса. Тот же самый модуль вызывается из `webapp/scraper_runner.py` (как subprocess) и из `ScraperThread` десктопа (напрямую `run()`).

### Аргументы

| Флаг | Значения | По умолчанию | Описание |
|------|----------|--------------|----------|
| `--headless` | `0` / `1` | `1` | `1` — без UI, `0` — показать Chromium (удобно смотреть, что делает скрапер). |
| `--slowmo` | ms | `0` | Задержка Playwright между действиями, для отладки (`--slowmo 200`). |
| `--out` | путь | `out/mektep` | Выходной каталог для сырых данных и отчётов. |
| `--lang` | `ru` / `kk` / `en` / `""` | `""` | Язык интерфейса `mektep.edu.kz`. Пусто — спросит после логина. |
| `--period` | `1`/`2`/`3`/`4` / `""` | `""` | Четверть (2 = первое полугодие, 4 = второе). Пусто — спросит. |
| `--pick` | индекс / `""` | `""` | Индекс строки в таблице оценок. Пусто — спросит. |
| `--all` | `0` / `1` | `0` | `1` — пройти по всем строкам таблицы оценок (массовый режим). |
| `--limit` | число | `0` | В режиме `--all 1` ограничить N строк (0 — без лимита). Полезно для квот. |
| `--legacy-files` | `0` / `1` | `0` | `1` — дополнительно создать `.txt`-помощники (subject/period/org/teacher). |
| `--dotenv` | путь | `""` | Путь к env-файлу (например, `env.local`). По умолчанию загружается стандартный `.env`. |

### Примеры

```bash
# Отладка с видимым браузером и замедлением
python scrape_mektep.py --headless 0 --slowmo 200

# Массовый прогон: 1-е полугодие (четверть 2), все классы, не более 10 отчётов
python scrape_mektep.py --lang ru --period 2 --all 1 --limit 10

# Один конкретный ряд в таблице (интерактивный выбор пропускается)
python scrape_mektep.py --lang kk --period 1 --pick 3 --headless 1
```

Учётные данные задаются через `MEKTEP_LOGIN` / `MEKTEP_PASSWORD` в окружении; иначе скрапер спросит их интерактивно (`getpass`).

### Артефакты прогона

В папке `out/mektep/` (или заданной через `--out`) появляются:

- `progress.json` — текущий этап и проценты (читается `progress_monitor.py` в десктопе и `scraper_runner.py` в вебе).
- `criteria_students.json`, `criteria_context.json`, `criteria_max_points.json`, `criteria.html`, `org_name.txt`, `period.txt`, `subject.txt` — промежуточные данные для построителей.
- `reports/*.xlsx`, `reports/*.docx` — готовые отчёты (через [build_report.py](build_report.py) и [build_word_report.py](build_word_report.py)).

### Построители отчётов по отдельности

```bash
# Excel
python build_report.py \
  --template "Шаблон.xlsx" \
  --students out/mektep/criteria_students.json \
  --context  out/mektep/criteria_context.json \
  --maxpoints out/mektep/criteria_max_points.json \
  --criteriahtml out/mektep/criteria.html \
  --orgfile  out/mektep/org_name.txt \
  --outdir   out/mektep/reports

# Word (по готовому Excel)
python build_word_report.py \
  --xlsx "out/mektep/reports/5 В Математика.xlsx" \
  --lang ru \
  --outdir out/mektep/reports
```

Для казахских отчётов используйте `--lang kk` (шаблон подбирается автоматически — [Шаблон_каз.docx](Шаблон_каз.docx)).

---

## Архитектура (кратко)

### Компоненты и среды

| Компонент | Dev | Production |
|-----------|-----|------------|
| Веб-сервер | `python app.py` (Flask dev) | Gunicorn (Unix) / Waitress (Windows) за Nginx |
| БД | SQLite (`instance/mektep_platform.db`) | PostgreSQL 16 |
| Фоновые задачи | Потоки (`threading.Semaphore`) / опционально Celery | Celery + Redis (при `USE_CELERY=1`) |
| Скрапер | Playwright (Chromium) — из `scrape_mektep.py` | То же; запуск через subprocess из `scraper_runner.py` |
| AI | Локальный ключ в `.env` | Ключ на уровне школы (`School.ai_api_key`) |
| Мониторинг | `/health/*`, `/metrics` | + Prometheus + Grafana + UptimeRobot |

### Поток данных (web → скрапер → отчёты)

```mermaid
flowchart LR
    U[Teacher UI] -->|POST /teacher/scrape| V[webapp/views/teacher.py]
    V -->|insert ScrapeJob| DB[(DB)]
    V --> SR[webapp/scraper_runner.py]
    SR -->|subprocess| SM[scrape_mektep.py]
    SM -->|Playwright| MK[mektep.edu.kz]
    SM -->|progress.json| FS[(out/platform_runs)]
    SR -.polling.-> FS
    SM --> BR[build_report.py]
    SM --> BW[build_word_report.py]
    BR --> RP[out/platform_uploads/<br>*.xlsx]
    BW --> RP2[out/platform_uploads/<br>*.docx]
    SR -->|ReportFile rows| DB
    U -->|GET /teacher/reports| V
    V --> DB
```

### Роли пользователей и UI

```mermaid
flowchart TD
    SA[SUPERADMIN] -->|/superadmin| SAP[Школы, AI-модели, квоты]
    SC[SCHOOL_ADMIN] -->|/admin| SCP[Учителя, классы, предметы,<br>аналитика, графики]
    TC[TEACHER] -->|desktop only| DT[Mektep Desktop]
    DT -->|JWT /api/*| API[webapp/views/api.py]
    API --> DB[(DB)]
    DT -->|Playwright| SMM[scrape_mektep.py]
    SMM --> RPIPE[report_pipeline]
    RPIPE -->|POST /api/reports| API
```

### Жизненный цикл `ScrapeJob` (десктоп-режим)

```mermaid
sequenceDiagram
    participant UI as Desktop UI
    participant ST as ScraperThread
    participant SM as scrape_mektep.run
    participant RF as ReportFinalizer
    participant API as webapp API

    UI->>ST: start(login, pass, period, lang)
    ST->>SM: run(args)
    SM-->>ST: progress.json updates
    ST-->>UI: emit progress signal
    SM-->>ST: reports/*.xlsx,*.docx
    ST->>RF: finalize(reports_dir)
    RF->>RF: move/rename files
    RF->>API: POST /api/reports (JWT)
    API-->>RF: 200 OK
    RF-->>ST: done
    ST-->>UI: emit finished
```

Десктоп-клиент и веб-платформа намеренно разделены: тяжёлый Playwright-скрапинг вынесен на учителя (его компьютер и его учётные данные `mektep.edu.kz`), сервер выступает как API + хранилище + аналитическая панель для школьных админов и суперадмина.

---

## Мониторинг

### Health endpoints

Все предоставлены blueprint'ом [webapp/views/health.py](webapp/views/health.py).

| Endpoint | Назначение | Коды ответа |
|----------|------------|-------------|
| `GET /health` или `GET /health/live` | Liveness — просто «процесс жив». Подходит для балансировщиков и Kubernetes. | 200 |
| `GET /health/ready` | Readiness — проверка БД (`SELECT 1`). | 200 / 503 |
| `GET /health/stats` | Сводка: задачи по статусам, активные процессы, школы, пользователи, лимиты. | 200 / 500 |
| `GET /metrics` | Prometheus-метрики (автоматически, если установлен `prometheus-flask-exporter`; см. [webapp/__init__.py](webapp/__init__.py)). | 200 |

Пример ответа `/health/stats`:

```json
{
  "status": "ok",
  "jobs": { "total": 42, "running": 1, "queued": 0, "succeeded": 35, "failed": 6, "active_processes": 1, "max_concurrent": 5 },
  "schools": { "total": 3, "active": 3 },
  "users": { "total": 17 },
  "config": { "debug": false, "max_concurrent_jobs": 5, "job_timeout_seconds": 1800 }
}
```

### UptimeRobot (внешний чек)

- Health URL: `https://mektep-analyzer.kz/health/live`
- Интервал проверки: 5 минут.
- В Cloudflare для путей `/health/*` поставьте `Cache Level: Bypass`, иначе агрегаторы будут видеть одно и то же закэшированное состояние.

### Prometheus

- URL: `http://localhost:9090`
- Поднимается вместе со стеком: `docker compose -f deploy/docker-compose.yml up -d`.
- Конфиг: [deploy/prometheus.yml](deploy/prometheus.yml). Scrape-jobs: `mektep-webapp` (`web:5000/metrics`) и `node-exporter` (`node-exporter:9100`).
- Проверка targets: `http://localhost:9090/targets` — все должны быть `UP`.

Полезные PromQL-запросы:

```promql
# RPS веб-приложения
sum(rate(flask_http_request_total[5m]))

# p95 latency
histogram_quantile(0.95, sum by (le) (rate(flask_http_request_duration_seconds_bucket[5m])))

# 5xx за последний час
sum(increase(flask_http_request_total{status=~"5.."}[1h]))

# Загрузка CPU хоста
100 - (avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)
```

### Grafana

- URL: `http://localhost:3000`
- Логин: `admin`
- Пароль: `GRAFANA_ADMIN_PASSWORD` (по умолчанию `admin`).
- Данные сохраняются в Docker volume `grafana-data`.
- Источники данных **Prometheus** и **Loki** подключаются автоматически через [deploy/grafana/provisioning/datasources/datasources.yml](deploy/grafana/provisioning/datasources/datasources.yml).

Готовые дашборды не поставляются — импортируйте из [Grafana Dashboards](https://grafana.com/grafana/dashboards/), например:

- `1860` — Node Exporter Full (хост-метрики).
- `9628`/`9964` — PostgreSQL.
- Кастомный — на базе `flask_http_request_*` метрик `prometheus-flask-exporter`.

### Loki (централизованные логи)

- Сервисы `loki` и `promtail` поднимаются вместе со стеком.
- Конфиги: [deploy/loki-config.yml](deploy/loki-config.yml), [deploy/promtail-config.yml](deploy/promtail-config.yml).
- Retention: 31 день (`loki-data` volume).
- Приложение пишет **структурированные JSON-логи** в stdout с полями `request_id`, `duration_ms`, `user_id`, `school_id` (см. [webapp/logging_config.py](webapp/logging_config.py), [webapp/request_logging.py](webapp/request_logging.py)).

Просмотр в Grafana → **Explore** → источник **Loki**. Примеры LogQL:

```logql
# Все HTTP-запросы контейнера web
{container=~".*web.*"} |= "http_request"

# Ошибки (5xx)
{container=~".*web.*"} | json | status >= 500

# Медленные запросы (> 1 сек)
{container=~".*web.*"} | json | duration_ms > 1000

# Медленные SQL
{container=~".*web.*"} |= "slow_sql"

# Поиск по request_id (из заголовка X-Request-ID)
{container=~".*web.*"} | json | request_id = "abc-123"
```

Переменные окружения: `LOG_LEVEL`, `LOG_JSON`, `SLOW_SQL_MS`, `SLOW_REQUEST_MS` — см. [env.example](env.example).

### GlitchTip (трекинг ошибок)

Self-hosted Sentry-совместимый сервис — данные об ошибках остаются на вашем сервере.

```bash
docker compose -f deploy/glitchtip-compose.yml up -d
```

1. Откройте `http://localhost:8000` (или `GLITCHTIP_DOMAIN`).
2. Создайте организацию и проект, скопируйте **DSN**.
3. Пропишите в `.env`: `SENTRY_DSN=https://...@.../1`
4. Перезапустите `web`: `docker compose -f deploy/docker-compose.yml up -d web`

Интеграция: [webapp/logging_config.py](webapp/logging_config.py) (`init_sentry`). Необработанные исключения также логируются через [webapp/request_logging.py](webapp/request_logging.py).

### Логи

- **Приложение (JSON)**: stdout контейнера `web` — собирается Promtail → Loki → Grafana. Быстрый просмотр: `docker compose logs -f web`.
- **Nginx**: внутри контейнера `nginx` — `/var/log/nginx/access.log` и `/var/log/nginx/error.log`.
- **Скрапер**: `out/platform_runs/<job_id>_<ts>/progress.json` и `debug-*.log` в корне репо.
- **Десктоп**: `mektep-debug.log` (корень репо), `mektep-desktop/debug-*.log`.

---

## Лицензия

MIT
