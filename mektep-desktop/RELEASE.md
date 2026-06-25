# Релиз Mektep Desktop

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
[ ] APP_VERSION в mektep-desktop/version.py
[ ] DESKTOP_VERSION в webapp/constants.py (ссылка на сайте)
[ ] MIN_DESKTOP_VERSION — только если нужно заблокировать старых клиентов
[ ] python build.py на Windows (нужен Inno Setup 6)
[ ] scp setup.exe + latest.json на сервер → ~/pdf-to-excel-scraper-main/updates/
[ ] curl: latest.json и setup.exe отдают 200
[ ] docker compose up -d --build web — только если меняли constants.py
[ ] Проверка: скачивание с сайта + автообновление с предыдущей версии
```

---

## Шаг 1. Версия в коде

**Обязательно** — `mektep-desktop/version.py`:

```python
APP_VERSION = "1.2.2"
```

**Рекомендуется** — `webapp/constants.py` (кнопка на главной):

```python
DESKTOP_VERSION = "1.2.2"
```

**Опционально** — принудительное обновление при логине:

```python
MIN_DESKTOP_VERSION = (1, 2, 2)
```

---

## Шаг 2. Сборка (только Windows)

```powershell
cd mektep-desktop
python build.py
```

Не используйте `python build.py onefile` — для автообновления нужен folder + Inno Setup.

Результат в `dist/`:

- `MektepDesktopSetup-<version>.exe`
- `latest.json` (version, url, sha256 — sha256 считается автоматически)

Перед публикацией можно дописать `notes` в `latest.json`.

---

## Шаг 3. Публикация на сервер

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

## Шаг 4. Webapp (если меняли constants.py)

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
