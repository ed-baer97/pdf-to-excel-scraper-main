# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Mektep Desktop

Build command:
    pyinstaller mektep_desktop.spec

Перед сборкой поместите logo_edus_logo_white.png в resources/img/
"""
from pathlib import Path

block_cipher = None

# Логотип — включаем в сборку, если файл есть
_logo = Path('resources/img/logo_edus_logo_white.png')
_logo_datas = [('resources/img/logo_edus_logo_white.png', 'resources/img')] if _logo.exists() else []

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        # Копирование шаблонов из папки mektep-desktop
        ('Шаблон.xlsx', 'templates'),
        ('Шаблон.docx', 'templates'),
        ('Шаблон_каз.docx', 'templates'),
    ] + _logo_datas,
    hiddenimports=[
        # PyQt6
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        
        # Playwright
        'playwright',
        'playwright.sync_api',
        
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
        # Исключаем неиспользуемые модули
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
    [],
    exclude_binaries=True,
    name='Mektep Desktop',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # GUI приложение (без консоли)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon='resources/icons/app_icon.ico',  # Добавьте иконку если есть
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Mektep Desktop',
)
