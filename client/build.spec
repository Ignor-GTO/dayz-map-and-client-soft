# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all, collect_submodules

hiddenimports = [
    'PIL._tkinter_finder',
    'uuid',
    '_uuid',
    'enum',
    'typing',
    'asyncio',
] + collect_submodules('winrt')

datas = []
binaries = []

for pkg in (
    'winrt.runtime',
    'winrt.windows.media.ocr',
    'winrt.windows.graphics.imaging',
    'winrt.windows.storage.streams',
    'winrt.windows.globalization',
    'winrt.windows.foundation',
    'winrt.windows.foundation.collections',
):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['pyi_rth_winrt.py'],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='DayZMapClient',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)
