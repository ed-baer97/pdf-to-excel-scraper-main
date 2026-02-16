"""
Скрипт сборки Mektep Desktop в EXE.

Использование:
    python build.py            — сборка в папку (быстрый запуск)
    python build.py onefile    — сборка в один EXE (удобно для распространения)

Что делает:
1. Копирует модули скрапера из корня проекта
2. Проверяет наличие иконки (скачивает при необходимости)
3. Устанавливает PyInstaller (если не установлен)
4. Запускает сборку через PyInstaller
"""
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

# Модули скрапера, которые живут в корне проекта и нужны десктопу
SCRAPER_MODULES = [
    "scrape_mektep.py",
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


def build(onefile: bool = False):
    """Запуск сборки"""
    mode = "ONEFILE (один EXE)" if onefile else "FOLDER (папка)"
    spec_file = SPEC_ONEFILE if onefile else SPEC_FOLDER
    
    print("\n" + "=" * 60)
    print(f"  СБОРКА MEKTEP DESKTOP — {mode}")
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
            print(f"\n  Для распространения скопируйте всю папку 'Mektep Desktop'.")
            print(f"  Или заархивируйте: dist/Mektep Desktop -> Mektep_Desktop.zip")
    else:
        print("\n[ОШИБКА] Сборка завершилась с ошибкой.")
        sys.exit(1)


if __name__ == "__main__":
    onefile = "onefile" in sys.argv
    build(onefile=onefile)
