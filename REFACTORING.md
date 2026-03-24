# Состояние рефакторинга (handoff для новых чатов)

Скопируйте блок ниже в начало нового чата, чтобы продолжить без перегрузки контекста.

```
Проект: pdf-to-excel-scraper-main.
Десктоп: логика после скрапинга вынесена из app/scraper_thread.py в app/report_pipeline/.
Файлы: report_utils.py, report_finalization.py (ReportFinalizer), run_environment.py, progress_monitor.py; отладка — app/debug_log.py (единый mektep-debug.log в корне репо).
Публичный API ScraperThread не менялся: сигналы progress, report_created, finished, error, schools_detected; методы stop(), select_school().
PyInstaller: hiddenimports обновлены в mektep_desktop.spec и mektep_desktop_onefile.spec.
Тесты: pytest из корня, tests/test_report_utils.py, requirements-dev.txt.
```

## Выполнено (итерация 1)

- Разделение `mektep-desktop/app/scraper_thread.py` на модули `report_pipeline/`.
- Регрессия: поведение `run()`, финализации и кодов `_scraper_result` сохранено по логике исходного файла.
- Документация: `README.md`, этот файл.

## Возможные следующие шаги

- Дополнительные unit-тесты для `ReportFinalizer` с моками `MektepAPIClient`.
- Рефакторинг `webapp/` и корневых одноразовых скриптов в `scripts/`.
- CI (GitHub Actions): `pip install -r requirements.txt -r requirements-dev.txt && pytest`.
