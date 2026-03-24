# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.building.build_main import Analysis, PYZ, EXE, COLLECT

block_cipher = None

# Required libraries
libs = [
    'yt_dlp',
    'customtkinter',
    'PIL',
    'requests',
    'tkinterdnd2'
]

hidden_imports = []
for lib in libs:
    hidden_imports += collect_submodules(lib)

# yt-dlp extractor fix (VERY important)
hidden_imports += collect_submodules('yt_dlp.extractor')

a = Analysis(
    ['main.py'],
    pathex=['.'],  # IMPORTANT: project root ekledik
    binaries=[],
    datas=[
        ('app', 'app'),  # tüm modüler yapı dahil edildi
    ],
    hiddenimports=hidden_imports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='YTDownloader',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon='YouTube.ico'  # varsa
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    name='YTDownloader'
)