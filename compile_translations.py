"""
Скрипт для компиляции переводов .po в .mo файлы
"""
import os
import subprocess
from pathlib import Path

# Путь к директории с переводами
translations_dir = Path(__file__).parent / "webapp" / "translations"

# Компилируем все .po файлы
for locale_dir in translations_dir.glob("*/LC_MESSAGES"):
    po_file = locale_dir / "messages.po"
    mo_file = locale_dir / "messages.mo"
    
    if po_file.exists():
        print(f"Компиляция {po_file}...")
        try:
            # Используем msgfmt если доступен
            result = subprocess.run(
                ["msgfmt", "-o", str(mo_file), str(po_file)],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                print(f"  ✓ Создан {mo_file}")
            else:
                # Если msgfmt недоступен, используем polib
                try:
                    import polib
                    po = polib.pofile(str(po_file))
                    po.save_as_mofile(str(mo_file))
                    print(f"  ✓ Создан {mo_file} (через polib)")
                except ImportError:
                    print(f"  ✗ Ошибка: установите msgfmt или polib")
                    print(f"     pip install polib")
        except FileNotFoundError:
            # msgfmt не найден, пробуем polib
            try:
                import polib
                po = polib.pofile(str(po_file))
                po.save_as_mofile(str(mo_file))
                print(f"  ✓ Создан {mo_file} (через polib)")
            except ImportError:
                print(f"  ✗ Ошибка: установите polib")
                print(f"     pip install polib")

print("\nГотово!")
