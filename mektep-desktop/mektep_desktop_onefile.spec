# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Mektep Desktop — ONEFILE (один EXE)

Build command:
    pyinstaller mektep_desktop_onefile.spec

Результат: dist/Mektep Desktop.exe (один файл)
"""
import os
from pathlib import Path

block_cipher = None

# Логотип PNG — включаем в сборку, если файл есть
_logo = Path('resources/img/logo_edus_logo_white.png')
_logo_datas = [('resources/img/logo_edus_logo_white.png', 'resources/img')] if _logo.exists() else []

# Иконка ICO — включаем в сборку
_icon = Path('resources/icons/app_icon.ico')
_icon_datas = [('resources/icons/app_icon.ico', 'resources/icons')] if _icon.exists() else []

# Playwright driver (Node.js сервер) — обязателен для работы браузера
_playwright_datas = []
try:
    import playwright
    _pw_dir = os.path.dirname(playwright.__file__)
    _pw_driver = os.path.join(_pw_dir, 'driver')
    if os.path.isdir(_pw_driver):
        _playwright_datas = [(os.path.join(_pw_driver, '*'), 'playwright/driver')]
        for _root, _dirs, _files in os.walk(_pw_driver):
            _rel = os.path.relpath(_root, _pw_dir)
            if _files:
                _playwright_datas.append(
                    (os.path.join(_root, '*'), os.path.join('playwright', _rel))
                )
        print(f"[OK] Playwright driver найден: {_pw_driver}")
    else:
        print(f"[!] Playwright driver НЕ найден: {_pw_driver}")
except ImportError:
    print("[!] Playwright не установлен — driver не будет включён в сборку")

# Шаблоны — включаем только если существуют
_template_datas = []
for _tmpl_name in ['Шаблон.xlsx', 'Шаблон.docx', 'Шаблон_каз.docx']:
    if Path(_tmpl_name).exists():
        _template_datas.append((_tmpl_name, 'templates'))
    else:
        print(f"[!] Шаблон не найден: {_tmpl_name}")

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=_template_datas + _logo_datas + _icon_datas + _playwright_datas,
    hiddenimports=[
        # PyQt6
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        
        # Playwright
        'playwright',
        'playwright.sync_api',
        'playwright._impl',
        'playwright._impl._driver',
        
        # Office
        'openpyxl',
        'openpyxl.styles',
        'openpyxl.utils',
        'docx',
        
        # AI
        'openai',
        
        # HTTP
        'requests',
        'jwt',
        
        # dotenv
        'dotenv',
        
        # App modules
        'app.reports_manager',
        'app.history_widget',
        'app.grades_widget',
        'app.loading_overlay',
        'app.subject_report_widget',
        'app.class_report_widget',
        
        # Scraper modules
        'scrape_mektep',
        'build_report',
        'build_word_report',
        'scraper_logger',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'PIL',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='Mektep Desktop',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='resources/icons/app_icon.ico' if _icon.exists() else None,
)
