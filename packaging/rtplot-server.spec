# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the rtplot browser server Windows executable.
#
# Build from the repo root with:
#     pyinstaller packaging/rtplot-server.spec --noconfirm
#
# The output is a single self-contained `dist/rtplot-server.exe`. This
# is onefile mode: on first launch the bootloader extracts the bundled
# payload to %TEMP%\_MEIxxxxxx\ (takes ~2-4s on a cold disk) and then
# runs from there. onefile makes distribution much easier — the whole
# server is a single file you can drop in an email or share link —
# at the cost of that one-time extraction delay and occasional extra
# scrutiny from heuristic antivirus scanners that dislike packed
# executables.

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
        "rtplot.server_browser",
        "rtplot.client",
        "tkinter",
        "tkinter.ttk",
        "tkinter.messagebox",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Everything here is excluded from the bundle to keep the download
    # small. pandas + pyarrow together add ~92 MB uncompressed, almost
    # all of which is pyarrow's arrow.dll / arrow_flight.dll. They are
    # only needed by save_current_plot (Parquet output), and
    # server_browser now handles the ImportError gracefully — so the
    # browser UI still works fully, the Save Plot button just reports
    # "pandas not installed" instead of crashing the receiver.
    excludes=[
        "matplotlib",
        "pyqtgraph",
        "PySide6",
        "PyQt5",
        "PyQt6",
        "IPython",
        "jupyter",
        "pandas",
        "pyarrow",
        "scipy",
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
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="rtplot-server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX compression is optional; disable for now because it slows
    # builds and some antivirus products dislike UPX-packed binaries.
    upx=False,
    runtime_tmpdir=None,
    # console=False: Windows "windowed subsystem" binary. No black
    # console window on double-click. stdout / stderr are captured by
    # the GUI's _TkLogRedirect and routed to the collapsable log panel,
    # so users never lose the output they'd have seen in a console.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
