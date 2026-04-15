# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the rtplot browser server Windows executable.
#
# Build from the repo root with:
#     pyinstaller packaging/rtplot-server.spec --noconfirm
#
# The output lands in `dist/rtplot-server/` as a onedir bundle whose
# top-level exe is `rtplot-server.exe`. onefile is intentionally NOT used
# — onefile binaries extract to a temp dir on every launch (slow) and
# Windows Defender tends to flag them as packed malware. onedir avoids
# both problems at the cost of shipping a folder of DLLs alongside the
# exe.

import os

HERE = os.path.abspath(os.path.dirname(SPEC))
ROOT = os.path.abspath(os.path.join(HERE, ".."))

block_cipher = None

a = Analysis(
    # Entry point is the Tk GUI wrapper — it imports rtplot.server_browser
    # under the hood and launches the aiohttp app in a background thread.
    [os.path.join(ROOT, "rtplot", "server_browser_gui.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[
        # uPlot assets served by the aiohttp static route.
        (os.path.join(ROOT, "rtplot", "static"), "rtplot/static"),
    ],
    # These are picked up via runtime imports that PyInstaller's static
    # analysis can miss.
    hiddenimports=[
        "aiohttp",
        "aiohttp.web",
        "zmq",
        "zmq.asyncio",
        "numpy",
        "pandas",
        "pyarrow",
        "rtplot.server_browser",
        "tkinter",
        "tkinter.ttk",
        "tkinter.messagebox",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Keep the bundle lean — these are not used by the browser server.
    excludes=[
        "matplotlib",
        "pyqtgraph",
        "PySide6",
        "PyQt5",
        "PyQt6",
        "IPython",
        "jupyter",
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
    name="rtplot-server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX compression is optional; disable for now because it slows
    # builds and some antivirus products dislike UPX-packed binaries.
    upx=False,
    console=True,
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
    upx=False,
    upx_exclude=[],
    name="rtplot-server",
)
