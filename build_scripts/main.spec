# -*- mode: python -*-
import os

import CTkColorPicker
import ctkmessagebox2
import customtkinter

# Find where customtkinter is installed on the current OS runner
col_path = os.path.dirname(CTkColorPicker.__file__)
msg_path = os.path.dirname(ctkmessagebox2.__file__)
ctk_path = os.path.dirname(customtkinter.__file__)
print(f'{col_path}\n{msg_path}\n{ctk_path}')

block_cipher = None

# Dynamically bundle the internal json/otf theme files
datas = [(ctk_path, 'customtkinter/')]

# Add any custom asset folders you have (e.g., images)
# datas += [('assets/', 'assets/')]

a = Analysis(
    ['main.py'],  # Replace with your entry script
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
    name='MyCustomTkinterApp',
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
    name='MyCustomTkinterApp',
)

app = BUNDLE(
    coll,
    name='MyCustomTkinterApp.app',
    icon='assets/app_icon.icns',
    bundle_identifier='com.yourcompany.mycustomtkinterapp',
    target_arch=os.environ.get('MACOS_ARCH', 'x86_64') # Dynamically sets arch via workflow env
)
