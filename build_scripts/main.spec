# -*- mode: python -*-
import os

import CTkColorPicker
import ctkmessagebox2

block_cipher = None

root = os.getcwd()
main_script = os.path.join(root, 'src', 'main.py')
assets = os.path.join(root, 'src', 'assets')
app_icon = os.path.join(assets, 'dxf2plasmac.icns')

datas = [(assets, 'assets')]
# these don't have hooks for pyinstaller so add them to datas
col_path = os.path.dirname(CTkColorPicker.__file__)
datas += [(col_path, 'CTkColorPicker')]
msg_path = os.path.dirname(ctkmessagebox2.__file__)
datas += [(msg_path, 'ctkmessagebox2')]

a = Analysis(
    [main_script],  # Replace with your entry script
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[],
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
    name='dxf2PlasmaC',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False, # Set to True if you want a command prompt to show
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='dxf2PlasmaC',
)

icon = app_icon if os.path.exists(app_icon) else None

app = BUNDLE(
    coll,
    name='dxf2PlasmaC.app',
    icon=icon,
    bundle_identifier='com.local.dxf2plasmac',
    info_plist={
        'NSPrincipalClass': 'NSApplication',
        'NSAppleScriptEnabled': False,
        'CFBundleShortVersionString': '0.1.0',
    },
)
