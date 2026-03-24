"""
Скрипт для компиляции переводов .po в .mo файлы.
"""
import subprocess
from pathlib import Path


def main() -> None:
    """Компилирует все messages.po в webapp/translations в messages.mo через msgfmt или polib."""
    translations_dir = Path(__file__).parent / "webapp" / "translations"

    for locale_dir in translations_dir.glob("*/LC_MESSAGES"):
        po_file = locale_dir / "messages.po"
        mo_file = locale_dir / "messages.mo"

        if po_file.exists():
            print(f"Компиляция {po_file}...")
            try:
                result = subprocess.run(
                    ["msgfmt", "-o", str(mo_file), str(po_file)],
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0:
                    print(f"  ✓ Создан {mo_file}")
                else:
                    try:
                        import polib

                        po = polib.pofile(str(po_file))
                        po.save_as_mofile(str(mo_file))
                        print(f"  ✓ Создан {mo_file} (через polib)")
                    except ImportError:
                        print("  ✗ Ошибка: установите msgfmt или polib")
                        print("     pip install polib")
            except FileNotFoundError:
                try:
                    import polib

                    po = polib.pofile(str(po_file))
                    po.save_as_mofile(str(mo_file))
                    print(f"  ✓ Создан {mo_file} (через polib)")
                except ImportError:
                    print("  ✗ Ошибка: установите polib")
                    print("     pip install polib")

    print("\nГотово!")


if __name__ == "__main__":
    main()
