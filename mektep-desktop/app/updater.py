"""
Автообновление Mektep Analyzer через Inno Setup установщик.

Приложение проверяет манифест latest.json на сервере, скачивает setup.exe,
проверяет sha256 и запускает тихую установку.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, Optional

import requests
from packaging.version import parse as parse_version
from PyQt6.QtCore import QThread, pyqtSignal

UPDATE_MANIFEST_URL = "https://mektep-analyzer.kz/updates/latest.json"
UPDATE_BASE_URL = "https://mektep-analyzer.kz/updates/"


def _is_newer(remote_version: str, current_version: str) -> bool:
    """True если remote_version строго новее current_version."""
    try:
        return parse_version(remote_version) > parse_version(current_version)
    except Exception:
        return remote_version != current_version


def check_for_update(
    current_version: str,
    manifest_url: str = UPDATE_MANIFEST_URL,
    timeout: int = 15,
) -> Optional[dict]:
    """
    Проверить наличие обновления.

    Returns:
        dict с полями version, url, sha256, notes, mandatory или None.
    """
    response = requests.get(manifest_url, timeout=timeout)
    response.raise_for_status()
    info = response.json()

    remote_version = str(info.get("version", "")).strip()
    if not remote_version or not _is_newer(remote_version, current_version):
        return None

    url = info.get("url", "").strip()
    if not url:
        filename = info.get("filename") or f"MektepDesktopSetup-{remote_version}.exe"
        url = f"{UPDATE_BASE_URL.rstrip('/')}/{filename.lstrip('/')}"

    return {
        "version": remote_version,
        "url": url,
        "sha256": str(info.get("sha256", "")).strip().lower(),
        "min_version": str(info.get("min_version", "")).strip(),
        "mandatory": bool(info.get("mandatory", False)),
        "notes": str(info.get("notes", "")).strip(),
    }


def download_installer(
    info: dict,
    progress_cb: Optional[Callable[[int], None]] = None,
    timeout: int = 120,
) -> Path:
    """
    Скачать установщик и проверить sha256.

    Raises:
        ValueError: если sha256 не совпадает или отсутствует в манифесте.
    """
    expected_sha = info.get("sha256", "").lower()
    if not expected_sha:
        raise ValueError("В манифесте отсутствует sha256")

    version = info.get("version", "unknown")
    dst = Path(tempfile.gettempdir()) / f"MektepSetup-{version}.exe"

    sha = hashlib.sha256()
    with requests.get(info["url"], stream=True, timeout=timeout) as response:
        response.raise_for_status()
        total = int(response.headers.get("content-length", 0) or 0)
        downloaded = 0

        with open(dst, "wb") as file_handle:
            for chunk in response.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                file_handle.write(chunk)
                sha.update(chunk)
                downloaded += len(chunk)
                if progress_cb and total > 0:
                    progress_cb(int(downloaded * 100 / total))

    actual_sha = sha.hexdigest().lower()
    if actual_sha != expected_sha:
        dst.unlink(missing_ok=True)
        raise ValueError(
            "Контрольная сумма не совпадает — файл повреждён или подменён"
        )

    return dst


def launch_installer_and_exit(installer_path: Path) -> None:
    """Запустить тихую установку и завершить текущий процесс."""
    subprocess.Popen(
        [
            str(installer_path),
            "/SILENT",
            "/CLOSEAPPLICATIONS",
            "/RESTARTAPPLICATIONS",
        ],
        close_fds=True,
    )
    sys.exit(0)


class UpdateCheckWorker(QThread):
    """Фоновая проверка наличия обновления."""

    finished = pyqtSignal(object)  # dict | None
    failed = pyqtSignal(str)

    def __init__(self, current_version: str, manifest_url: str = UPDATE_MANIFEST_URL):
        super().__init__()
        self._current_version = current_version
        self._manifest_url = manifest_url

    def run(self):
        try:
            result = check_for_update(self._current_version, self._manifest_url)
            self.finished.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class UpdateDownloadWorker(QThread):
    """Фоновое скачивание установщика."""

    progress = pyqtSignal(int)
    finished = pyqtSignal(object)  # Path
    failed = pyqtSignal(str)

    def __init__(self, update_info: dict):
        super().__init__()
        self._update_info = update_info

    def run(self):
        try:
            path = download_installer(
                self._update_info,
                progress_cb=lambda percent: self.progress.emit(percent),
            )
            self.finished.emit(path)
        except Exception as exc:
            self.failed.emit(str(exc))
