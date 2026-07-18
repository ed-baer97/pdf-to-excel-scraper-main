"""Generate web/desktop brand assets from the source logo PNG."""
from pathlib import Path

from PIL import Image

root = Path(__file__).resolve().parent
src = root / "ChatGPT Image 1 июл. 2026 г., 00_41_38.png"
if not src.exists():
    raise SystemExit(f"Source logo not found: {src}")

web_img = root / "webapp" / "static" / "img"
web_img.mkdir(parents=True, exist_ok=True)
desk_img = root / "mektep-desktop" / "resources" / "img"
desk_icons = root / "mektep-desktop" / "resources" / "icons"
desk_img.mkdir(parents=True, exist_ok=True)
desk_icons.mkdir(parents=True, exist_ok=True)

img = Image.open(src).convert("RGBA")
bbox = img.getbbox()
if bbox:
    img = img.crop(bbox)

side = max(img.size)
square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
square.paste(img, ((side - img.width) // 2, (side - img.height) // 2), img)

web_logo = square.copy()
web_logo.thumbnail((512, 512), Image.Resampling.LANCZOS)
web_logo.save(web_img / "logo.png", optimize=True)
square.resize((256, 256), Image.Resampling.LANCZOS).save(web_img / "logo-256.png", optimize=True)
square.resize((64, 64), Image.Resampling.LANCZOS).save(web_img / "favicon-64.png", optimize=True)
fav = square.resize((32, 32), Image.Resampling.LANCZOS)
fav.save(web_img / "favicon.ico", format="ICO", sizes=[(16, 16), (32, 32)])

desk_logo = square.copy()
desk_logo.thumbnail((512, 512), Image.Resampling.LANCZOS)
desk_logo.save(desk_img / "logo_edus_logo_white.png", optimize=True)
desk_logo.save(desk_img / "logo_mektep_analyzer.png", optimize=True)

icon_size = 256
bg = Image.new("RGBA", (icon_size, icon_size), (8, 115, 206, 255))  # #0873CE
logo = square.copy()
logo.thumbnail((int(icon_size * 0.82), int(icon_size * 0.82)), Image.Resampling.LANCZOS)
ox = (icon_size - logo.width) // 2
oy = (icon_size - logo.height) // 2
bg.paste(logo, (ox, oy), logo)
sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
bg.save(desk_icons / "app_icon.ico", format="ICO", sizes=sizes)

for p in [
    web_img / "logo.png",
    web_img / "logo-256.png",
    web_img / "favicon.ico",
    desk_img / "logo_edus_logo_white.png",
    desk_icons / "app_icon.ico",
]:
    print(f"{p} ({p.stat().st_size} bytes)")
print("Done.")
