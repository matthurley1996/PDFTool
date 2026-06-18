# PDF Tool

A lightweight, cross-platform PDF viewer/editor with OCR, PDF→DOCX export,
watermarking, and true redaction. Built with PySide6 + PyMuPDF; packages to a
single executable with PyInstaller.

## Features

- **View** — page rendering with navigation and zoom.
- **OCR** — adds a searchable text layer via `ocrmypdf` (Tesseract). Supports
  multiple languages (`eng`, `eng+fra`, …).
- **PDF → DOCX** — layout-preserving conversion via `pdf2docx`.
- **Watermark** — diagonal text stamp across all pages.
- **Redaction** — drag rectangles in *Redact mode*; applying them permanently
  removes the underlying text/image content (not just a visual cover).

## Project layout

```
pdftool/
  __main__.py     entry point  (python -m pdftool)
  engine.py       all PDF operations, no GUI deps — unit-testable
  pageview.py     Qt page view + rubber-band redaction selection
  mainwindow.py   window, toolbar, operation dispatch
  worker.py       QThread helper so slow ops don't freeze the UI
pdftool.spec      PyInstaller build
requirements.txt
```

The engine is deliberately GUI-free so you can script it or test it headless.

## Running from source

```bash
pip install -r requirements.txt
python -m pdftool
```

You also need **Tesseract** and **Ghostscript** installed for OCR when running
from source:

- macOS:   `brew install tesseract ghostscript`
- Ubuntu:  `sudo apt install tesseract-ocr ghostscript`
- Windows: install the official Tesseract and Ghostscript builds, ensure
  they're on `PATH`.

## Building a single executable

1. Install build deps:
   ```bash
   pip install pyinstaller
   ```
2. Bundle the external binaries so the executable is self-contained. Create:
   - `bin/` — the `tesseract` and `gs` executables (plus any shared libraries
     they need on your target OS).
   - `tessdata/` — `eng.traineddata` and any other language files you want to
     ship. Each language adds roughly 5–15 MB.
3. Build:
   ```bash
   pyinstaller pdftool.spec
   ```
   Output lands in `dist/`. At runtime the app finds the bundled binaries via
   PyInstaller's extraction dir (`sys._MEIPASS`); see
   `engine.resolve_binary()` and `engine.tessdata_dir()`.

### Size note

Expect roughly 80–150 MB onefile, dominated by Qt and the Tesseract language
data. If you only ship `eng`, you stay near the low end. Set `upx=False` in the
spec if UPX isn't installed.

## Leaner alternative

If you later want to drop the Tesseract/Ghostscript external-binary dependency,
swap the OCR backend in `engine.ocr_pdf()` for a pure-ONNX engine like RapidOCR.
You lose `ocrmypdf`'s automatic deskew/cleanup but gain a much simpler,
fully-Python package.
