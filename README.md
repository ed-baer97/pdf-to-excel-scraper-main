# Mektep Scraper

Приложение для автоматического сбора данных с [mektep.edu.kz](https://mektep.edu.kz) и формирования отчётов (Excel/Word), с веб-платформой для школ и десктоп-клиентом для учителей.

English summary: multi-user web app plus optional PyQt6 desktop client; Playwright-based scraper; templates for Excel/Word reports.

## Возможности

- Многопользовательская система (суперадмин → школы → учителя)
- Сбор данных с mektep.edu.kz (Playwright)
- Генерация Excel и Word из шаблонов
- Квоты отчётов по четвертям
- Прогресс задач в реальном времени
- Опционально: аналитика через AI API (Qwen и др.)

## Требования

- Python 3.11+
- PostgreSQL (production) или SQLite (development)
- Redis (опционально: лимиты и Celery)
- Chromium (ставится через `playwright install chromium`)

---

## Структура репозитория

| Путь | Назначение |
|------|------------|
| `webapp/` | Flask-приложение (модели, views, Celery) |
| `scrape_mektep.py` | Скрапер (CLI и общая логика для десктопа) |
| `build_report.py`, `build_word_report.py` | Сборка отчётов из шаблонов |
| `mektep-desktop/` | PyQt6 десктоп (`mektep-desktop/main.py`) |
| `mektep-desktop/app/report_pipeline/` | Логика финализации отчётов после скрапинга (вынесена из `scraper_thread`) |
| `tests/` | Pytest (утилиты `report_pipeline`) |

Подробные запуски и сценарии: [ИНСТРУКЦИЯ_ЗАПУСКА.md](ИНСТРУКЦИЯ_ЗАПУСКА.md). Мониторинг: [MONITORING.md](MONITORING.md). Методическое оформление проекта (структура пособия): [МЕТОДИЧЕСКИЕ_РЕКОМЕНДАЦИИ_MEKTEP.md](МЕТОДИЧЕСКИЕ_РЕКОМЕНДАЦИИ_MEKTEP.md).

---

## Быстрый старт (веб)

```bash
git clone <repo-url>
cd pdf-to-excel-scraper-main

python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium

copy env.example .env
python app.py
```

Откройте http://localhost:5000 (учётные данные по умолчанию см. в документации/миграциях).

### Docker Compose

```bash
copy env.example .env
docker-compose up -d
```

Сервисы: веб (порт 5000), Celery, PostgreSQL, Redis. См. `docker-compose.yml`.

---

## Десктоп (Mektep Desktop)

Запуск из каталога `mektep-desktop` (чтобы импортировались `app.*` и корневой `scrape_mektep`):

```bash
cd mektep-desktop
pip install -r requirements.txt
python -m playwright install chromium
python main.py
```

Сборка EXE: `python build.py` или `python build.py onefile` (см. [mektep-desktop/build.py](mektep-desktop/build.py)).

---

## Разработка и тесты

Установка инструментов разработки:

```bash
pip install -r requirements-dev.txt
```

Запуск тестов из **корня** репозитория:

```bash
python -m pytest
```

Конфигурация: [pytest.ini](pytest.ini) (`pythonpath` включает `mektep-desktop` для пакета `app`).

---

## Конфигурация (веб)

Основные переменные окружения (см. `env.example`):

| Variable | Описание |
|----------|----------|
| `SECRET_KEY` | Секрет Flask (обязателен в production) |
| `DATABASE_URL` | Строка подключения к БД |
| `REDIS_URL` | Redis для Celery/лимитов |
| `USE_CELERY` | Включить фоновые задачи |

---

## CLI-скрапер (отладка)

```bash
python scrape_mektep.py --headless 0 --slowmo 200
python scrape_mektep.py --lang ru --period 2 --all 1 --limit 10
```

---

## Архитектура (кратко)

| Компонент | Dev | Production |
|-----------|-----|------------|
| Веб | Flask dev server | Gunicorn / Waitress |
| БД | SQLite | PostgreSQL |
| Фон | Потоки / опционально Celery | Celery + Redis |

Десктоп: поток `ScraperThread` вызывает `scrape_mektep.run`, затем модуль `report_pipeline` переносит файлы и при необходимости загружает отчёты на сервер через API.

---

## Лицензия

MIT
