# PyInstaller spec — builds a single-file executable.
#
# Before building, place external binaries and language data where this spec
# expects them (or edit the paths below):
#
#   bin/        -> tesseract(.exe), gs(.exe)  and their required shared libs
#   tessdata/   -> eng.traineddata  (plus any other languages you ship)
#
# These get extracted next to the app at runtime; engine.resolve_binary()
# and engine.tessdata_dir() locate them via sys._MEIPASS.
#
# Build:   pyinstaller pdftool.spec
# Output:  dist/pdftool   (or dist/pdftool.exe on Windows)

import os
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

binaries = []
datas = []

# --- bundle external binaries if present ---
BIN_DIR = "bin"
if os.path.isdir(BIN_DIR):
    for fn in os.listdir(BIN_DIR):
        binaries.append((os.path.join(BIN_DIR, fn), "bin"))

# --- bundle tesseract language data ---
TESSDATA = "tessdata"
if os.path.isdir(TESSDATA):
    for fn in os.listdir(TESSDATA):
        datas.append((os.path.join(TESSDATA, fn), "tessdata"))

# ocrmypdf and pdf2docx pull in data files / plugins
hiddenimports = []
hiddenimports += collect_submodules("ocrmypdf")
hiddenimports += collect_submodules("pdf2docx")
datas += collect_data_files("ocrmypdf")
datas += collect_data_files("pdf2docx")

a = Analysis(
    ["pdftool/__main__.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "PyQt5", "PyQt6"],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="pdftool",
    debug=False,
    strip=False,
    upx=True,            # set False if UPX is unavailable
    console=False,       # GUI app — no console window
    disable_windowed_traceback=False,
)
