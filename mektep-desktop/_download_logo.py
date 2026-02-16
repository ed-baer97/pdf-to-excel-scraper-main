"""
Скачивание логотипа и конвертация в ICO для сборки приложения.
"""
import os
import sys
import requests
from PIL import Image
from io import BytesIO

URLS = [
    "https://mektep-analyzer.kz/assets/img/logo_edus_logo_white.png",
    "https://mektep.edu.kz/assets/img/logo_edus_logo_white.png",
    "https://mektep-analyzer.kz/static/img/logo_edus_logo_white.png",
]

def download_logo():
    for url in URLS:
        print(f"Trying: {url}")
        try:
            r = requests.get(url, timeout=10, verify=False)
            if r.status_code == 200 and len(r.content) > 100:
                print(f"  -> OK, {len(r.content)} bytes")
                return r.content
            else:
                print(f"  -> Status {r.status_code}, size {len(r.content)}")
        except Exception as e:
            print(f"  -> Error: {e}")
    return None

def main():
    # Пути
    script_dir = os.path.dirname(os.path.abspath(__file__))
    resources_img = os.path.join(script_dir, "resources", "img")
    resources_icons = os.path.join(script_dir, "resources", "icons")
    
    os.makedirs(resources_img, exist_ok=True)
    os.makedirs(resources_icons, exist_ok=True)
    
    png_path = os.path.join(resources_img, "logo_edus_logo_white.png")
    ico_path = os.path.join(resources_icons, "app_icon.ico")
    
    # Скачиваем
    data = download_logo()
    if data is None:
        print("\nНе удалось скачать логотип. Создаю из локального файла...")
        if os.path.exists(png_path):
            with open(png_path, "rb") as f:
                data = f.read()
        else:
            print("Локальный файл тоже не найден.")
            print("Поместите logo_edus_logo_white.png в resources/img/ и запустите заново.")
            sys.exit(1)
    
    # Сохраняем PNG
    with open(png_path, "wb") as f:
        f.write(data)
    print(f"\nPNG saved: {png_path}")
    
    # Конвертируем в ICO с синим фоном
    img = Image.open(BytesIO(data))
    
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    
    # Создаём квадратное изображение с синим фоном (#0d6efd)
    max_side = max(img.size)
    icon_size = max(max_side, 256)
    
    bg = Image.new("RGBA", (icon_size, icon_size), (13, 110, 253, 255))  # #0d6efd
    
    # Центрируем логотип на синем фоне с небольшим отступом
    logo_resized = img.copy()
    # Масштабируем логотип чтобы он занимал ~80% площади иконки
    target_size = int(icon_size * 0.75)
    logo_resized.thumbnail((target_size, target_size), Image.Resampling.LANCZOS)
    
    offset_x = (icon_size - logo_resized.width) // 2
    offset_y = (icon_size - logo_resized.height) // 2
    bg.paste(logo_resized, (offset_x, offset_y), logo_resized)
    
    # Скругляем углы для красивого вида (опционально)
    # Сохраняем как ICO с несколькими размерами
    sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    bg.save(ico_path, format="ICO", sizes=sizes)
    print(f"ICO saved: {ico_path}")
    print("\nГотово!")

if __name__ == "__main__":
    main()
