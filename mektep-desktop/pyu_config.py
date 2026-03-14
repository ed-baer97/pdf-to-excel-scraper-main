"""
Конфигурация клиента PyUpdater для Mektep Desktop.

Важно:
- Замените UPDATE_URLS на ваш реальный URL, где лежит versions.json и пакеты обновлений.
- Замените PUBLIC_KEY на публичный ключ, сгенерированный PyUpdater (pyupdater keys).
"""

from __future__ import annotations

from typing import List

from . import version as app_version


class PyuConfig:
    """Минимальная конфигурация PyUpdater-клиента."""

    APP_NAME: str = app_version.APP_NAME
    COMPANY_NAME: str = "Mektep"

    # URL(ы), где лежат versions.json и пакеты обновлений,
    # подготовленные PyUpdater-ом. Пример:
    #   https://your-domain.com/updates/
    UPDATE_URLS: List[str] = [
        "https://example.com/updates/",  # TODO: замените на свой URL
    ]

    # Публичный ключ PyUpdater (строка), сгенерированный командой `pyupdater keys`.
    # Его нужно скопировать сюда из файла конфигурации/ключей PyUpdater.
    PUBLIC_KEY: str = "REPLACE_WITH_REAL_PUBLIC_KEY"

    MAX_DOWNLOAD_RETRIES: int = 3

