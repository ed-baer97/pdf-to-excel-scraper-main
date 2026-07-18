# Релиз Mektep Analyzer

Краткая памятка: как выпустить новую версию десктоп-приложения.

См. также: [UPDATES.md](UPDATES.md) — Nginx, структура `/updates/`, откат.

## Три уровня версии

| Уровень | Файл | Назначение |
|---------|------|------------|
| Версия в приложении | `version.py` → `APP_VERSION` | Отображение в UI, сравнение при автообновлении |
| Манифест на сервере | `updates/latest.json` | Что считается последним релизом для автообновления |
| Минимум для API | `webapp/constants.py` → `MIN_DESKTOP_VERSION` | Блокировка логина старых клиентов (HTTP 426) |

Кнопка «Скачать приложение» на сайте берёт URL из `webapp/constants.py` → `DESKTOP_VERSION`.

---

## Чек-лист релиза

```
[ ] Чистая рабочая копия Git
[ ] .\release.ps1 <version> (тесты, версии, сборка, публикация и проверка)
[ ] Зафиксировать обновлённые version.py и webapp/constants.py
[ ] MIN_DESKTOP_VERSION — только если нужно заблокировать старых клиентов
[ ] docker compose up -d --build web — только если меняли constants.py
[ ] Проверка: скачивание с сайта + автообновление с предыдущей версии
```

---

## Автоматический релиз одной командой

Требования на Windows:

- Python и зависимости проекта;
- Inno Setup 6;
- OpenSSH Client (`ssh` и `scp`);
- доступ по SSH к серверу.

Один раз задайте адрес сервера в текущем окне PowerShell:

```powershell
$env:MEKTEP_DEPLOY_TARGET = "deploy@SERVER"
```

Для постоянной настройки добавьте пользовательскую переменную среды Windows
`MEKTEP_DEPLOY_TARGET`. При нестандартном размещении также доступны:

```powershell
$env:MEKTEP_REMOTE_UPDATES_PATH = "~/pdf-to-excel-scraper-main/updates"
$env:MEKTEP_PUBLIC_UPDATES_URL = "https://mektep-analyzer.kz/updates"
$env:MEKTEP_SSH_IDENTITY_FILE = "$HOME\.ssh\id_ed25519"
```

Обычный релиз:

```powershell
cd mektep-desktop
.\release.ps1 1.2.2 -Notes "Исправлены ошибки выгрузки отчётов."
```

Скрипт последовательно:

1. синхронизирует `APP_VERSION` и `DESKTOP_VERSION`;
2. запускает pytest;
3. запускает PyInstaller и Inno Setup через `build.py`;
4. проверяет SHA-256;
5. загружает установщик под временным именем и атомарно переименовывает;
6. публикует `latest.json` последним;
7. проверяет манифест и установщик через публичный HTTPS-адрес.

При ошибке до публикации манифеста изменения версий в исходниках будут отменены.
После атомарной публикации версии сохраняются, даже если публичная проверка не
прошла: в этом случае скрипт потребует немедленно проверить сервер вручную.

Полезные варианты:

```powershell
# Только локальная сборка
.\release.ps1 1.2.2 -BuildOnly

# Принудительное обновление в манифесте
.\release.ps1 1.2.2 -Mandatory

# Одновременно поднять минимальную версию API
.\release.ps1 1.2.2 -MinimumApiVersion 1.2.2

# Нестандартный SSH-порт и ключ
.\release.ps1 1.2.2 -SshPort 2222 -IdentityFile "$HOME\.ssh\mektep"
```

По умолчанию скрипт требует чистую рабочую копию Git. `-AllowDirty` разрешает
релиз с локальными изменениями, а `-SkipTests` пропускает тесты; используйте эти
параметры только осознанно.

После успешного релиза зафиксируйте изменения версий в Git. Если изменился
`MIN_DESKTOP_VERSION`, разверните webapp, чтобы новое ограничение начало действовать.

---

## Ручной резервный процесс

Если автоматический скрипт недоступен, обновите версии вручную:

- `mektep-desktop/version.py` → `APP_VERSION`;
- `webapp/constants.py` → `DESKTOP_VERSION`;
- при необходимости `webapp/constants.py` → `MIN_DESKTOP_VERSION`.

Затем выполните сборку:

```powershell
cd mektep-desktop
python build.py
```

Не используйте `python build.py onefile` — для автообновления нужен folder + Inno Setup.

В `dist/` появятся установщик и `latest.json`. Загрузите установщик первым,
убедитесь, что он доступен, и только после этого заменяйте `latest.json`.

С Windows (подставьте свой хост и версию):

```powershell
cd <корень-репозитория>
scp mektep-desktop\dist\MektepDesktopSetup-1.2.2.exe mektep-desktop\dist\latest.json deploy@SERVER:~/pdf-to-excel-scraper-main/updates/
```

На сервере:

```bash
ls -lh ~/pdf-to-excel-scraper-main/updates/
curl -s http://127.0.0.1/updates/latest.json
```

Перезапуск Docker **не нужен** — Nginx отдаёт файлы с диска.

---

## Webapp (если меняли constants.py)

```bash
cd ~/pdf-to-excel-scraper-main
git pull
docker compose up -d --build web
```

Если меняли только файлы в `updates/` — webapp не трогать.

---

## Что видит пользователь

### Уже установленное приложение

1. При старте (через ~2 с) — фоновая проверка `latest.json`
2. Если версия на сервере новее — диалог «Установить обновление?»
3. Скачивание setup.exe → проверка sha256 → тихая установка Inno Setup
4. Ручная проверка — кнопка «Проверить обновление» в главном окне

### Новый пользователь

Главная страница сайта → «Скачать приложение» → тот же `MektepDesktopSetup-*.exe` с `/updates/`.

---

## Типы релизов

| Тип | Действия |
|-----|----------|
| **Обычный** | Залить setup + latest.json, `mandatory: false` |
| **С напоминанием** | + заполнить `notes` в latest.json |
| **Принудительный** | `mandatory: true` в latest.json **или** поднять `MIN_DESKTOP_VERSION` и задеплоить web |

---

## Откат

1. Оставить на сервере предыдущий `MektepDesktopSetup-*.exe`
2. В `latest.json` вернуть старую `version`, `url` и `sha256`
3. Залить обновлённый `latest.json`

Пересборка не требуется.

---

## Чего не делать

- Не собирать установщик на Linux — только Windows + Inno Setup
- Не публиковать latest.json без корректного sha256
- Не забывать синхронизировать `APP_VERSION`, `DESKTOP_VERSION` и `version` в latest.json
- Не перезапускать весь сервер ради десктоп-релиза (достаточно заменить файлы в `updates/`)
