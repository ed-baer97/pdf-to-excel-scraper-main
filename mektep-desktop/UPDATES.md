# Публикация обновлений Mektep Analyzer

Полный чек-лист релиза: [RELEASE.md](RELEASE.md).

## Структура на сервере

Файлы размещаются в `updates/` в корне проекта (Docker: монтируется в Nginx как `/var/www/mektep/updates/`) и доступны по URL `https://mektep-analyzer.kz/updates/`:

```
updates/
├── latest.json
├── MektepDesktopSetup-1.2.1.exe
└── MektepDesktopSetup-1.2.2.exe   # предыдущие версии — для отката
```

## Nginx

```nginx
location /updates/ {
    alias /var/www/mektep/updates/;
    autoindex off;

    # Кэш манифеста не нужен — клиент должен видеть свежую версию
    location = /updates/latest.json {
        alias /var/www/mektep/updates/latest.json;
        add_header Cache-Control "no-cache, no-store, must-revalidate";
    }
}
```

## Сборка и публикация

1. Обновите версию в `version.py`.
2. Соберите установщик:
   ```bash
   cd mektep-desktop
   python build.py
   ```
3. В `dist/` появятся:
   - `MektepDesktopSetup-<version>.exe`
   - `latest.json` (с sha256 и URL)
4. Загрузите оба файла на сервер (или в `./updates/` при Docker-деплое):
   ```bash
   scp dist/MektepDesktopSetup-1.2.2.exe dist/latest.json user@mektep-analyzer.kz:/var/www/mektep/updates/
   # или локально:
   cp dist/MektepDesktopSetup-1.2.2.exe dist/latest.json ../updates/
   ```

## Формат latest.json

```json
{
  "version": "1.2.2",
  "url": "https://mektep-analyzer.kz/updates/MektepDesktopSetup-1.2.2.exe",
  "sha256": "abc123...",
  "min_version": "1.0.0",
  "mandatory": false,
  "notes": "Исправлены ошибки выгрузки отчётов."
}
```

## SmartScreen (без code signing)

При первой установке Windows может показать «Неизвестный издатель». Пользователю нужно:
1. Нажать «Подробнее»
2. Выбрать «Выполнить в любом случае»

Автообновление (тихая установка) обычно не показывает это окно повторно.

## Откат

Сохраняйте 1–2 предыдущих `MektepDesktopSetup-*.exe`. Для отката обновите `latest.json`, указав старую версию и соответствующий sha256.
