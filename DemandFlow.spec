# -*- mode: python ; coding: utf-8 -*-
"""
Spec do PyInstaller para o DemandFlow (build --onedir).
Gerar o executável:
    .venv\\Scripts\\pyinstaller.exe DemandFlow.spec --noconfirm
Resultado em dist\\DemandFlow\\DemandFlow.exe
"""
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = [
    ('resources/dictionaries', 'resources/dictionaries'),
    ('resources/icon.ico', 'resources'),
    ('resources/arrow_down_light.svg', 'resources'),
    ('resources/arrow_down_dark.svg', 'resources'),
    ('version.py', '.'),
    ('updater.bat', '.'),
]
datas += collect_data_files('qtawesome')

# cyhunspell e sua dependência cacheman são importados de dentro da extensão
# .pyd compilada (Cython) — o modulegraph não detecta isso sozinho.
hiddenimports = collect_submodules('hunspell') + collect_submodules('cacheman')

a = Analysis(
    ['main.py'],
    pathex=[SPECPATH],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='DemandFlow',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='resources/icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='DemandFlow',
)
