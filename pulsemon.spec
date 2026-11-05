# -*- mode: python ; coding: utf-8 -*-
import sys
import os

block_cipher = None

datas = [
    ('app/static', 'app/static'),
    ('config.yaml', '.'),
]

hiddenimports = [
    'uvicorn',
    'uvicorn.logging',
    'uvicorn.loops.auto',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan.on',
    'websockets',
    'psutil',
    'pymysql',
    'psycopg2',
    'yaml',
    'sqlite3',
    'webview',
    'webview.platforms.winforms',
    'webview.platforms.edgechromium',
    'webview.platforms.cocoa',
    'webview.platforms.gtk',
    'app.services.email_service',
    'app.paths',
    'app.desktop',
]

a = Analysis(
    ['run.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'scipy', 'numpy', 'IPython'],
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
    name='PulseMon',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Suppresses terminal/cmd prompt in native desktop application mode
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# macOS Application Bundle (.app)
if sys.platform == 'darwin':
    app = BUNDLE(
        exe,
        name='PulseMon.app',
        icon=None,
        bundle_identifier='com.pulsemon.desktop',
        info_plist={
            'CFBundleName': 'PulseMon',
            'CFBundleDisplayName': 'PulseMon',
            'CFBundleGetInfoString': 'PulseMon System & Database Monitor',
            'CFBundleIdentifier': 'com.pulsemon.desktop',
            'CFBundleVersion': '2.0.0',
            'CFBundleShortVersionString': '2.0.0',
            'NSHighResolutionCapable': True,
        },
    )

