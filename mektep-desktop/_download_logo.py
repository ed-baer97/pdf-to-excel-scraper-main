"""
Подготовка логотипа и конвертация в ICO для сборки приложения.

Приоритет источников:
1) локальный brand-логотип репозитория
2) уже существующий PNG в resources/img
3) удалённые URL (fallback)
"""
import os
import sys
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
LOCAL_SOURCES = [
    REPO_ROOT / "webapp" / "static" / "img" / "logo.png",
    REPO_ROOT / "ChatGPT Image 1 июл. 2026 г., 00_41_38.png",
    SCRIPT_DIR / "resources" / "img" / "logo_mektep_analyzer.png",
    SCRIPT_DIR / "resources" / "img" / "logo_edus_logo_white.png",
]
URLS = [
    "https://mektep-analyzer.kz/static/img/logo.png",
    "https://mektep-analyzer.kz/assets/img/logo_edus_logo_white.png",
]


def load_local_logo() -> bytes | None:
    for path in LOCAL_SOURCES:
        if path.exists() and path.stat().st_size > 100:
            print(f"Using local: {path}")
            return path.read_bytes()
    return None


def download_logo() -> bytes | None:
    for url in URLS:
        print(f"Trying: {url}")
        try:
            response = requests.get(url, timeout=10, verify=False)
            if response.status_code == 200 and len(response.content) > 100:
                print(f"  -> OK, {len(response.content)} bytes")
                return response.content
            print(f"  -> Status {response.status_code}, size {len(response.content)}")
        except Exception as exc:
            print(f"  -> Error: {exc}")
    return None


def main():
    resources_img = SCRIPT_DIR / "resources" / "img"
    resources_icons = SCRIPT_DIR / "resources" / "icons"
    resources_img.mkdir(parents=True, exist_ok=True)
    resources_icons.mkdir(parents=True, exist_ok=True)

    png_path = resources_img / "logo_edus_logo_white.png"
    ico_path = resources_icons / "app_icon.ico"

    data = load_local_logo() or download_logo()
    if data is None:
        print("Не удалось найти логотип.")
        print("Поместите logo_edus_logo_white.png в resources/img/ и запустите заново.")
        sys.exit(1)

    png_path.write_bytes(data)
    print(f"\nPNG saved: {png_path}")

    img = Image.open(BytesIO(data))
    if img.mode != "RGBA":
        img = img.convert("RGBA")

    max_side = max(img.size)
    icon_size = max(max_side, 256)
    bg = Image.new("RGBA", (icon_size, icon_size), (8, 115, 206, 255))  # #0873CE

    logo_resized = img.copy()
    target_size = int(icon_size * 0.75)
    logo_resized.thumbnail((target_size, target_size), Image.Resampling.LANCZOS)
    offset_x = (icon_size - logo_resized.width) // 2
    offset_y = (icon_size - logo_resized.height) // 2
    bg.paste(logo_resized, (offset_x, offset_y), logo_resized)

    sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    bg.save(ico_path, format="ICO", sizes=sizes)
    print(f"ICO saved: {ico_path}")
    print("\nГотово!")


if __name__ == "__main__":
    main()
