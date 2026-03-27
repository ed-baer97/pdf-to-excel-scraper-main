# Project Structure

Этот файл фиксирует текущую структуру целевых директорий для итерационного рефакторинга.

## Scope

- `webapp`
- `mektep-desktop`
- `tests`
- `nginx`

## webapp

Role: Flask web-слой (views, templates, модели, security, фоновые задачи и интеграция со scraper).

### Directory Tree

```text
webapp/
  services/
  templates/
    admin/
    auth/
    main/
    setup/
    superadmin/
    teacher/
  translations/
    kk/LC_MESSAGES/
    ru/LC_MESSAGES/
  views/
```

### Files

- `webapp/__init__.py`
- `webapp/celery_app.py`
- `webapp/cli.py`
- `webapp/config.py`
- `webapp/constants.py`
- `webapp/extensions.py`
- `webapp/models.py`
- `webapp/redis_utils.py`
- `webapp/scraper_runner.py`
- `webapp/security.py`
- `webapp/services/__init__.py`
- `webapp/services/admin_common.py`
- `webapp/services/admin_dashboard.py`
- `webapp/services/api_helpers.py`
- `webapp/services/auth_guards.py`
- `webapp/tasks.py`
- `webapp/translator.py`
- `webapp/views/admin.py`
- `webapp/views/api.py`
- `webapp/views/auth.py`
- `webapp/views/health.py`
- `webapp/views/main.py`
- `webapp/views/setup.py`
- `webapp/views/superadmin.py`
- `webapp/views/teacher.py`
- `webapp/templates/layout.html`
- `webapp/templates/admin/analytics_home.html`
- `webapp/templates/admin/class_teacher_report.html`
- `webapp/templates/admin/dashboard.html`
- `webapp/templates/admin/grades_class.html`
- `webapp/templates/admin/grades_overview.html`
- `webapp/templates/admin/password.html`
- `webapp/templates/admin/school_detail.html`
- `webapp/templates/admin/subject_detail.html`
- `webapp/templates/auth/login.html`
- `webapp/templates/main/home.html`
- `webapp/templates/setup/setup.html`
- `webapp/templates/superadmin/dashboard.html`
- `webapp/templates/superadmin/password.html`
- `webapp/templates/teacher/dashboard.html`
- `webapp/translations/kk/LC_MESSAGES/messages.po`
- `webapp/translations/ru/LC_MESSAGES/messages.po`

## mektep-desktop

Role: Desktop-клиент (UI, worker/thread orchestration, API client, report pipeline, packaging/update configs).

### Directory Tree

```text
mektep-desktop/
  .pyupdater/
  ai/
  app/
    report_pipeline/
  resources/
    img/
```

### Files

- `mektep-desktop/.gitignore`
- `mektep-desktop/build.py`
- `mektep-desktop/client_config.py`
- `mektep-desktop/main.py`
- `mektep-desktop/mektep_desktop.spec`
- `mektep-desktop/mektep_desktop_onefile.spec`
- `mektep-desktop/pyu_config.py`
- `mektep-desktop/requirements.txt`
- `mektep-desktop/version.py`
- `mektep-desktop/_download_logo.py`
- `mektep-desktop/.pyupdater/config.pyu`
- `mektep-desktop/ai/__init__.py`
- `mektep-desktop/ai/text_generator.py`
- `mektep-desktop/resources/img/README.txt`
- `mektep-desktop/app/__init__.py`
- `mektep-desktop/app/api_client.py`
- `mektep-desktop/app/class_report_widget.py`
- `mektep-desktop/app/debug_log.py`
- `mektep-desktop/app/goals_dialog.py`
- `mektep-desktop/app/grades_widget.py`
- `mektep-desktop/app/history_widget.py`
- `mektep-desktop/app/loading_overlay.py`
- `mektep-desktop/app/login_dialog.py`
- `mektep-desktop/app/main_window.py`
- `mektep-desktop/app/reports_manager.py`
- `mektep-desktop/app/scraper_thread.py`
- `mektep-desktop/app/settings_dialog.py`
- `mektep-desktop/app/subject_report_widget.py`
- `mektep-desktop/app/translator.py`
- `mektep-desktop/app/report_pipeline/__init__.py`
- `mektep-desktop/app/report_pipeline/period_map.py`
- `mektep-desktop/app/report_pipeline/progress_monitor.py`
- `mektep-desktop/app/report_pipeline/report_finalization.py`
- `mektep-desktop/app/report_pipeline/report_utils.py`
- `mektep-desktop/app/report_pipeline/run_environment.py`

## tests

Role: Unit/integration tests для ключевых утилит и бизнес-правил.

### Directory Tree

```text
tests/
```

### Files

- `tests/test_report_utils.py`

### Coverage Matrix (current baseline)

- `app.report_pipeline.report_utils.parse_class_liter`
- `app.report_pipeline.report_utils.parse_number`
- `app.report_pipeline.report_utils.sanitize_filename`
- `app.report_pipeline.report_utils.resolve_period`
- `app.report_pipeline.report_utils.normalize_period_code`
- `app.report_pipeline.report_utils.is_semester_subject`
- `app.report_pipeline.progress_monitor.parse_schools_from_progress_message`
- `app.report_pipeline.progress_monitor.format_progress_line`

## nginx

Role: Reverse proxy / routing слой для прод-окружения.

### Directory Tree

```text
nginx/
```

### Files

- `nginx/nginx.conf`

## Refactoring Candidates

- Крупные файлы в корне (`scrape_mektep.py`, `build_word_report.py`, `build_report.py`) выглядят как кандидаты на модульную декомпозицию.
- `webapp/models.py` и `webapp/tasks.py` вероятно содержат смешанную ответственность (стоит дробить на пакеты по доменам).
- В `webapp/views/*` и `webapp/templates/*` возможны пересечения ролей и дубли view/template-логики.
- В `mektep-desktop/app/*` есть признаки смешения UI и orchestration-логики (widgets/dialogs рядом с pipeline- и thread-кодом).
- `tests/` пока содержит минимальный набор тестов, покрытие критических сценариев нужно расширять по мере рефакторинга.

## Iteration Progress Notes

- `webapp`: часть логики группировки/периодов вынесена из `views/admin.py` в `services/admin_dashboard.py`; в `views/teacher.py` добавлена явная проверка rate-limit перед стартом job.
- `webapp` stage 2: из `views/api.py` вынесены JWT/auth и infra-helper функции в `services/api_helpers.py`; в `views/admin.py` вынесены redirect/filter helpers в `services/admin_common.py`.
- `webapp` stage 3 (auth): создан `services/auth_guards.py` с `role_required`, `superadmin_required`, `admin_required`, `admin_or_superadmin_required`, `teacher_required`, `can_access_report_file`, `can_access_grade_report`. Все `@login_required + if not _require_*()` паттерны заменены на декораторы. В `teacher` blueprint добавлен `before_request` guard. JWT `require_jwt` теперь верифицирует роль из БД, а не только из payload.
- `mektep-desktop`: `report_utils.resolve_period` теперь устойчив к невалидному `period_code` через `normalize_period_code`.
- `tests`: добавлены проверки нормализации `period_code` и поведения `resolve_period` для невалидного ввода.
- `nginx`: устранено дублирование proxy-настроек на уровне `server`, для `/api/` задан явный `limit_req_status 429`.
