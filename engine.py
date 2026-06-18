"""
Core PDF operations. No GUI dependencies — everything here is testable
in isolation and reused by the Qt layer.

Operations: render (for viewing), OCR, PDF->DOCX, watermark, redaction.
"""
from __future__ import annotations

import os
import sys
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

import fitz  # PyMuPDF


# --------------------------------------------------------------------------
# Bundled-binary resolution
#
# When frozen by PyInstaller, external binaries (tesseract, ghostscript) are
# extracted to sys._MEIPASS. In a normal dev run we fall back to PATH.
# --------------------------------------------------------------------------
def _resource_base() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def resolve_binary(name: str) -> Optional[str]:
    """Return path to a bundled binary if present, else whatever is on PATH."""
    exe = name + (".exe" if os.name == "nt" else "")
    bundled = _resource_base() / "bin" / exe
    if bundled.exists():
        return str(bundled)
    return shutil.which(name)


def tessdata_dir() -> Optional[str]:
    bundled = _resource_base() / "tessdata"
    if bundled.exists():
        return str(bundled)
    return os.environ.get("TESSDATA_PREFIX")


# --------------------------------------------------------------------------
# Rendering for the viewer
# --------------------------------------------------------------------------
@dataclass
class RenderedPage:
    width: int
    height: int
    samples: bytes      # RGB/RGBA pixel buffer
    stride: int
    alpha: bool


def render_page(doc: "fitz.Document", page_number: int, zoom: float = 1.0) -> RenderedPage:
    """Render a single page to a raw pixmap for display in Qt."""
    page = doc[page_number]
    matrix = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    return RenderedPage(
        width=pix.width,
        height=pix.height,
        samples=pix.samples,
        stride=pix.stride,
        alpha=bool(pix.alpha),
    )


# --------------------------------------------------------------------------
# Watermark
# --------------------------------------------------------------------------
def add_text_watermark(
    in_path: str,
    out_path: str,
    text: str,
    *,
    opacity: float = 0.15,
    rotate: int = 45,
    fontsize: int = 48,
    color: tuple[float, float, float] = (0.5, 0.5, 0.5),
    pages: Optional[Sequence[int]] = None,
) -> None:
    """Stamp a diagonal text watermark across selected pages (all if None)."""
    doc = fitz.open(in_path)
    try:
        targets = range(len(doc)) if pages is None else pages
        for pno in targets:
            page = doc[pno]
            rect = page.rect
            # Center the stamp; PyMuPDF rotates around the morph pivot.
            point = fitz.Point(rect.width / 2, rect.height / 2)
            morph = (point, fitz.Matrix(rotate))
            # Approximate centering of the text box.
            tw = fitz.TextWriter(rect, color=color)
            tw.append(
                fitz.Point(rect.width * 0.18, rect.height / 2),
                text,
                fontsize=fontsize,
            )
            tw.write_text(page, opacity=opacity, morph=morph)
        doc.save(out_path, garbage=4, deflate=True)
    finally:
        doc.close()


# --------------------------------------------------------------------------
# Redaction — genuinely removes content, not a visual cover
# --------------------------------------------------------------------------
@dataclass
class RedactBox:
    page: int
    x0: float
    y0: float
    x1: float
    y1: float


def apply_redactions(
    in_path: str,
    out_path: str,
    boxes: Sequence[RedactBox],
    *,
    fill: tuple[float, float, float] = (0, 0, 0),
) -> None:
    """Apply redactions. apply_redactions() erases underlying text/images."""
    doc = fitz.open(in_path)
    try:
        for box in boxes:
            page = doc[box.page]
            rect = fitz.Rect(box.x0, box.y0, box.x1, box.y1)
            page.add_redact_annot(rect, fill=fill)
        for page in doc:
            page.apply_redactions()
        doc.save(out_path, garbage=4, deflate=True)
    finally:
        doc.close()


def redact_text_matches(
    in_path: str,
    out_path: str,
    needles: Sequence[str],
    *,
    fill: tuple[float, float, float] = (0, 0, 0),
) -> int:
    """Find and redact every occurrence of each search string. Returns count."""
    doc = fitz.open(in_path)
    hits = 0
    try:
        for page in doc:
            for needle in needles:
                for rect in page.search_for(needle):
                    page.add_redact_annot(rect, fill=fill)
                    hits += 1
            page.apply_redactions()
        doc.save(out_path, garbage=4, deflate=True)
    finally:
        doc.close()
    return hits


# --------------------------------------------------------------------------
# OCR via ocrmypdf (wraps Tesseract; adds a searchable text layer)
# --------------------------------------------------------------------------
def ocr_pdf(
    in_path: str,
    out_path: str,
    *,
    language: str = "eng",
    force: bool = False,
    deskew: bool = True,
) -> None:
    """
    Run ocrmypdf. Prefers the library API; falls back to the CLI. Points at
    bundled tesseract/ghostscript/tessdata when frozen.
    """
    env = os.environ.copy()
    td = tessdata_dir()
    if td:
        # ocrmypdf/tesseract reads TESSDATA_PREFIX (parent of tessdata on
        # older tesseract, the dir itself on newer — set both safely).
        env["TESSDATA_PREFIX"] = td

    tesseract = resolve_binary("tesseract")
    gs = resolve_binary("gs")
    # Prepend bundled bin dir to PATH so ocrmypdf discovers them.
    if tesseract:
        env["PATH"] = str(Path(tesseract).parent) + os.pathsep + env.get("PATH", "")

    args = [
        sys.executable, "-m", "ocrmypdf",
        "-l", language,
        "--output-type", "pdf",
    ]
    if force:
        args.append("--force-ocr")
    else:
        args.append("--skip-text")
    if deskew:
        args.append("--deskew")
    args += [in_path, out_path]

    proc = subprocess.run(args, env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"OCR failed (exit {proc.returncode}):\n{proc.stderr.strip()}"
        )


# --------------------------------------------------------------------------
# PDF -> DOCX
# --------------------------------------------------------------------------
def pdf_to_docx(in_path: str, out_path: str, *, start: int = 0, end: Optional[int] = None) -> None:
    """Convert a PDF to a Word document using pdf2docx."""
    from pdf2docx import Converter
    cv = Converter(in_path)
    try:
        cv.convert(out_path, start=start, end=end)
    finally:
        cv.close()
