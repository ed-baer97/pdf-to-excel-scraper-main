"""
Скрипт сборки Mektep Desktop в EXE и установщик Inno Setup.

Использование:
    python build.py            — сборка в папку + установщик + latest.json
    python build.py onefile    — сборка в один EXE (без установщика)

Что делает:
1. Копирует модули скрапера из корня проекта
2. Проверяет наличие иконки (скачивает при необходимости)
3. Устанавливает PyInstaller (если не установлен)
4. Запускает сборку через PyInstaller
5. (folder) Собирает установщик через Inno Setup и генерирует latest.json
"""
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent  # pdf-to-excel-scraper-main/
ICON_PATH = SCRIPT_DIR / "resources" / "icons" / "app_icon.ico"
LOGO_PATH = SCRIPT_DIR / "resources" / "img" / "logo_edus_logo_white.png"

SPEC_FOLDER = SCRIPT_DIR / "mektep_desktop.spec"
SPEC_ONEFILE = SCRIPT_DIR / "mektep_desktop_onefile.spec"
INSTALLER_ISS = SCRIPT_DIR / "installer.iss"
UPDATE_BASE_URL = "https://mektep-analyzer.kz/updates/"

# Модули скрапера, которые живут в корне проекта и нужны десктопу
SCRAPER_MODULES = [
    "scrape_mektep.py",
    "grade_table_signals.py",
    "iin_utils.py",
    "build_report.py",
    "build_word_report.py",
    "scraper_logger.py",
]

# Шаблоны отчетов из корня проекта
TEMPLATE_FILES = [
    "Шаблон.xlsx",
    "Шаблон.docx",
    "Шаблон_каз.docx",
]


def get_app_version() -> str:
    """Прочитать APP_VERSION из version.py."""
    version_file = SCRIPT_DIR / "version.py"
    namespace: dict = {}
    exec(version_file.read_text(encoding="utf-8"), namespace)  # noqa: S102
    return str(namespace["APP_VERSION"])


def copy_scraper_modules():
    """Копирование модулей скрапера из корня проекта в mektep-desktop"""
    all_ok = True
    for module in SCRAPER_MODULES:
        src = PROJECT_ROOT / module
        dst = SCRIPT_DIR / module
        if src.exists():
            shutil.copy2(str(src), str(dst))
            print(f"[OK] Скопирован: {module}")
        else:
            print(f"[!] Не найден в корне: {src}")
            if dst.exists():
                print(f"     (локальная копия уже есть)")
            else:
                print(f"     [ОШИБКА] Модуль отсутствует!")
                all_ok = False
    return all_ok


def copy_templates():
    """Копирование шаблонов отчетов из корня проекта в mektep-desktop"""
    all_ok = True
    for tmpl in TEMPLATE_FILES:
        src = PROJECT_ROOT / tmpl
        dst = SCRIPT_DIR / tmpl
        if src.exists():
            shutil.copy2(str(src), str(dst))
            print(f"[OK] Шаблон скопирован: {tmpl}")
        else:
            print(f"[!] Шаблон не найден в корне: {src}")
            if dst.exists():
                print(f"     (локальная копия уже есть)")
            else:
                print(f"     [ОШИБКА] Шаблон отсутствует!")
                all_ok = False
    return all_ok


def check_icon():
    """Проверка наличия иконки и логотипа"""
    if ICON_PATH.exists() and LOGO_PATH.exists():
        print(f"[OK] Иконка найдена: {ICON_PATH}")
        print(f"[OK] Логотип найден: {LOGO_PATH}")
        return True

    print("[!] Иконка или логотип не найдены. Запускаю скачивание...")
    download_script = SCRIPT_DIR / "_download_logo.py"
    if download_script.exists():
        result = subprocess.run([sys.executable, str(download_script)], cwd=str(SCRIPT_DIR))
        if result.returncode != 0:
            print("[ОШИБКА] Не удалось скачать логотип.")
            return False
        return ICON_PATH.exists()
    else:
        print("[ОШИБКА] Скрипт _download_logo.py не найден.")
        print(f"  Поместите иконку вручную: {ICON_PATH}")
        return False


def install_pyinstaller():
    """Установка PyInstaller если не установлен"""
    try:
        import PyInstaller
        print(f"[OK] PyInstaller {PyInstaller.__version__} установлен")
    except ImportError:
        print("[!] PyInstaller не установлен. Устанавливаю...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        print("[OK] PyInstaller установлен")


def find_iscc() -> Path | None:
    """Найти компилятор Inno Setup (ISCC.exe)."""
    candidates = [
        Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
        Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def sha256_file(path: Path) -> str:
    """Вычислить sha256 файла."""
    digest = hashlib.sha256()
    with open(path, "rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_installer(app_version: str) -> Path | None:
    """Собрать setup.exe через Inno Setup."""
    iscc = find_iscc()
    if iscc is None:
        print("\n[!] Inno Setup не найден. Установите Inno Setup 6:")
        print("    https://jrsoftware.org/isdl.php")
        print("    Установщик не будет создан.")
        return None

    if not INSTALLER_ISS.exists():
        print(f"\n[ОШИБКА] Не найден installer.iss: {INSTALLER_ISS}")
        return None

    print(f"\n[*] Запуск Inno Setup: {INSTALLER_ISS.name}")
    print("-" * 60)

    result = subprocess.run(
        [str(iscc), f"/DAppVersion={app_version}", str(INSTALLER_ISS)],
        cwd=str(SCRIPT_DIR),
    )
    if result.returncode != 0:
        print("\n[ОШИБКА] Сборка установщика завершилась с ошибкой.")
        return None

    installer_path = SCRIPT_DIR / "dist" / f"MektepDesktopSetup-{app_version}.exe"
    if not installer_path.exists():
        print(f"\n[ОШИБКА] Установщик не найден: {installer_path}")
        return None

    print(f"\n[OK] Установщик: {installer_path}")
    return installer_path


def write_latest_json(app_version: str, installer_path: Path) -> Path:
    """Сгенерировать latest.json с sha256 для публикации на сервере."""
    filename = installer_path.name
    manifest = {
        "version": app_version,
        "url": f"{UPDATE_BASE_URL.rstrip('/')}/{filename}",
        "sha256": sha256_file(installer_path),
        "min_version": "1.0.0",
        "mandatory": False,
        "notes": "",
    }
    manifest_path = SCRIPT_DIR / "dist" / "latest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"[OK] Манифест: {manifest_path}")
    return manifest_path


def build(onefile: bool = False):
    """Запуск сборки"""
    mode = "ONEFILE (один EXE)" if onefile else "FOLDER (папка + установщик)"
    spec_file = SPEC_ONEFILE if onefile else SPEC_FOLDER
    app_version = get_app_version()

    print("\n" + "=" * 60)
    print(f"  СБОРКА MEKTEP DESKTOP v{app_version} — {mode}")
    print("=" * 60 + "\n")

    # 1. Копирование модулей скрапера из корня проекта
    print("[*] Копирование модулей скрапера...")
    if not copy_scraper_modules():
        print("\n[ОШИБКА] Не все модули найдены. Сборка может завершиться с ошибкой.")
    print()

    # 1.5. Копирование шаблонов из корня проекта
    print("[*] Копирование шаблонов отчетов...")
    if not copy_templates():
        print("\n[!] Не все шаблоны найдены. Отчеты могут не создаваться.")
    print()

    # 2. Проверка иконки
    if not check_icon():
        print("\n[!] Сборка без иконки. Иконка EXE будет стандартной.")

    # 3. Установка PyInstaller
    install_pyinstaller()

    # 4. Проверка spec-файла
    if not spec_file.exists():
        print(f"\n[ОШИБКА] Spec-файл не найден: {spec_file}")
        sys.exit(1)

    # 5. Сборка
    print(f"\n[*] Запуск PyInstaller: {spec_file.name}")
    print("-" * 60)

    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--clean", str(spec_file)],
        cwd=str(SCRIPT_DIR)
    )

    if result.returncode == 0:
        print("\n" + "=" * 60)
        print("  СБОРКА ЗАВЕРШЕНА УСПЕШНО!")
        print("=" * 60)

        if onefile:
            exe_path = SCRIPT_DIR / "dist" / "Mektep Desktop.exe"
            print(f"\n  EXE: {exe_path}")
            print(f"\n  Один файл — готов к распространению!")
        else:
            dist_dir = SCRIPT_DIR / "dist" / "Mektep Desktop"
            exe_path = dist_dir / "Mektep Desktop.exe"
            print(f"\n  Путь к EXE: {exe_path}")
            print(f"  Папка:      {dist_dir}")

            installer_path = build_installer(app_version)
            if installer_path:
                write_latest_json(app_version, installer_path)
                print("\n  Для публикации загрузите на сервер:")
                print(f"    - {installer_path.name}")
                print("    - latest.json")
                print(f"  См. также: {SCRIPT_DIR / 'UPDATES.md'}")
            else:
                print(f"\n  Для распространения скопируйте всю папку 'Mektep Desktop'.")
    else:
        print("\n[ОШИБКА] Сборка завершилась с ошибкой.")
        sys.exit(1)


if __name__ == "__main__":
    onefile = "onefile" in sys.argv
    build(onefile=onefile)
