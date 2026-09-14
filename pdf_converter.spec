# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec dosyası — PDF Web Dönüştürücü
Tek, bağımsız .exe oluşturur (onefile + noconsole).
"""

import sys
from pathlib import Path

# customtkinter kaynak dosyalarını bul
import customtkinter
CTK_PATH = Path(customtkinter.__file__).parent

# tkinterdnd2 kaynak dosyalarını bul
try:
    import tkinterdnd2
    DND_PATH = Path(tkinterdnd2.__file__).parent
    dnd_datas = [(str(DND_PATH), "tkinterdnd2")]
except ImportError:
    dnd_datas = []

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=[],
    datas=[
        (str(CTK_PATH), "customtkinter"),
        *dnd_datas,
        ("assets", "assets"),
    ],
    hiddenimports=[
        "customtkinter",
        "tkinterdnd2",
        "pymupdf",
        "pikepdf",
        "darkdetect",
        "PIL",
        "PIL._tkinter_finder",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "numpy", "scipy", "pandas"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PDF-Web-Donusturucu",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,       # Pencere modu, terminal gösterme
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/icon.ico",
)
