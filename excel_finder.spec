# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=['src'],
    binaries=[],
    datas=[
        ('config', 'config'),
        ('icon', 'icon'),
    ],
    hiddenimports=[
        'pandas',
        'numpy',
        'PyQt5',
        'xlrd',
        'openpyxl',
        'psutil',
        'concurrent.futures',
        'multiprocessing',
        'threading',
        'queue',
        # Explicitly include all src modules
        'config',
        'main_app',
        'loading_dialog',
        'search_worker',
        'search_utils',
        'streaming_search',
        'file_processor',
        'excel_utils',
        'app_settings',
        'file_cache',
        'ui_components',
        'sheet_viewer',
        'search_exception_dialog_improved',
        'constants',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='ExcelFinder',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon\\icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ExcelFinder'
)