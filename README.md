# Mektep Scraper

Приложение для автоматического сбора данных с [mektep.edu.kz](https://mektep.edu.kz) и формирования отчётов (Excel/Word), с веб-платформой для школ и десктоп-клиентом для учителей.

English summary: multi-user web app plus optional PyQt6 desktop client; Playwright-based scraper; templates for Excel/Word reports.

## Возможности

- Многопользовательская система (суперадмин → школы → учителя)
- Сбор данных с mektep.edu.kz (Playwright)
- Генерация Excel и Word из шаблонов
- Прогресс задач в реальном времени
- Опционально: аналитика через AI API (Qwen и др.)

## Требования

- Python 3.11+
- PostgreSQL (production) или SQLite (development)
- Redis (опционально: лимиты и Celery)
- Chromium (ставится через `playwright install chromium`)

---

## Структура проекта

### Карта каталогов

| Путь | Роль |
|------|------|
| `webapp/` | Flask веб-платформа: роуты, модели, сервисы, шаблоны, фоновые задачи |
| `entrypoints/` | Точки входа для запуска веба (`app`, `wsgi`, production launcher) |
| `scripts/db/` | DB-миграции и обслуживающие скрипты |
| `scripts/dev/` | Локальные dev-утилиты (очистка данных/выходов, компиляция переводов) |
| `scrape_mektep.py` | Основной CLI-скрапер для mektep.edu.kz |
| `build_report.py`, `build_word_report.py` | Генерация Excel/Word отчётов по шаблонам |
| `deploy/` | Docker/Prometheus файлы для инфраструктуры |
| `nginx/` | Конфиг reverse-proxy для production |
| `mektep-desktop/` | PyQt6 десктоп-клиент для учителя |
| `tests/` | Pytest-тесты |

### Внутренняя структура модулей

- **`webapp/`**: `views/`, `services/`, `templates/`, `translations/`, `tasks.py`, `models.py`, `security.py`
- **`mektep-desktop/`**: UI-слой в `app/`, отчётный pipeline в `app/report_pipeline/`, AI-модуль в `ai/`
- **`tests/`**: базовые unit-тесты утилит report pipeline
- **`nginx/`**: `nginx.conf` для роутинга и ограничений

### Текущие зоны для рефакторинга

- Крупные скрипты в корне (`scrape_mektep.py`, `build_word_report.py`, `build_report.py`) — кандидаты на декомпозицию.
- `webapp/models.py` и `webapp/tasks.py` потенциально стоит дробить по доменам.
- В `webapp/views/*` часть логики уже вынесена в `webapp/services/*`; направление верное, можно продолжать.

Подробные сценарии запуска: [ИНСТРУКЦИЯ_ЗАПУСКА.md](ИНСТРУКЦИЯ_ЗАПУСКА.md). Содержание методического пособия: [МЕТОДИЧЕСКОЕ_ПОСОБИЕ_СОДЕРЖАНИЕ.md](МЕТОДИЧЕСКОЕ_ПОСОБИЕ_СОДЕРЖАНИЕ.md).

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
docker compose -f deploy/docker-compose.yml up -d
```

Сервисы: веб (порт 5000), PostgreSQL, мониторинг. См. `deploy/docker-compose.yml`.

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
| `REDIS_URL` | Redis для Celery |
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

## Мониторинг

### UptimeRobot

- Health URL: `https://mektep-analyzer.kz/health/live`
- Интервал проверки: 5 минут
- В Cloudflare для `/health/*` используйте `Cache Level: Bypass`

### Prometheus

- URL: `http://localhost:9090`
- Поднимается через `docker compose -f deploy/docker-compose.yml up -d`
- Конфиг: `deploy/prometheus.yml`

### Grafana

- URL: `http://localhost:3000`
- Логин: `admin`
- Пароль: `GRAFANA_ADMIN_PASSWORD` (по умолчанию `admin`)

Первичная настройка источника данных:
1. Откройте `http://localhost:3000`
2. Войдите в Grafana
3. Перейдите в `Connections` → `Data sources` → `Add data source`
4. Выберите `Prometheus`
5. Укажите URL `http://prometheus:9090` и нажмите `Save & test`

---

## Лицензия

MIT
