"""
Main application window. Wires the page view to the toolbar and dispatches
the four operations (OCR, DOCX export, watermark, redaction) to the engine,
running the slow ones on a worker thread.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QMainWindow, QFileDialog, QMessageBox, QToolBar, QLabel, QSpinBox,
    QInputDialog, QStatusBar, QApplication,
)

import fitz
from . import engine
from .pageview import PageView
from .worker import run_async


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF Tool")
        self.resize(1000, 800)

        self.doc: fitz.Document | None = None
        self.path: str | None = None
        self._threads = []  # keep refs alive

        self.view = PageView(self)
        self.view.selectionsChanged.connect(self._on_selection_change)
        self.setCentralWidget(self.view)

        self.setStatusBar(QStatusBar())
        self._build_toolbar()
        self._update_actions()

    # ------------------------------------------------------------------
    def _build_toolbar(self):
        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)

        self.act_open = QAction("Open", self)
        self.act_open.setShortcut(QKeySequence.Open)
        self.act_open.triggered.connect(self.open_file)
        tb.addAction(self.act_open)
        tb.addSeparator()

        # page navigation
        self.prev = QAction("◀", self); self.prev.triggered.connect(self._prev)
        self.next = QAction("▶", self); self.next.triggered.connect(self._next)
        tb.addAction(self.prev)
        self.page_spin = QSpinBox(); self.page_spin.setMinimum(1)
        self.page_spin.valueChanged.connect(lambda v: self.view.set_page(v - 1))
        tb.addWidget(self.page_spin)
        self.page_total = QLabel(" / 0 "); tb.addWidget(self.page_total)
        tb.addAction(self.next)
        tb.addSeparator()

        # zoom
        zout = QAction("−", self); zout.triggered.connect(lambda: self._zoom(0.8))
        zin = QAction("+", self); zin.triggered.connect(lambda: self._zoom(1.25))
        tb.addAction(zout); tb.addAction(zin)
        tb.addSeparator()

        # features
        self.act_ocr = QAction("OCR", self)
        self.act_ocr.triggered.connect(self.do_ocr)
        tb.addAction(self.act_ocr)

        self.act_docx = QAction("Export DOCX", self)
        self.act_docx.triggered.connect(self.do_docx)
        tb.addAction(self.act_docx)

        self.act_wm = QAction("Watermark", self)
        self.act_wm.triggered.connect(self.do_watermark)
        tb.addAction(self.act_wm)

        self.act_redact = QAction("Redact mode", self)
        self.act_redact.setCheckable(True)
        self.act_redact.toggled.connect(self.view.set_redact_mode)
        tb.addAction(self.act_redact)

        self.act_apply = QAction("Apply redactions", self)
        self.act_apply.triggered.connect(self.do_redactions)
        tb.addAction(self.act_apply)

        self.act_clear = QAction("Clear", self)
        self.act_clear.triggered.connect(self.view.clear_selections)
        tb.addAction(self.act_clear)

    # ------------------------------------------------------------------
    def _busy(self, msg: str):
        self.statusBar().showMessage(msg)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        self.setEnabled(False)

    def _done(self, msg: str = "Ready"):
        QApplication.restoreOverrideCursor()
        self.setEnabled(True)
        self.statusBar().showMessage(msg, 5000)

    def _error(self, msg: str):
        self._done("Error")
        QMessageBox.critical(self, "Operation failed", msg)

    # ------------------------------------------------------------------
    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open PDF", "", "PDF files (*.pdf)")
        if not path:
            return
        try:
            doc = fitz.open(path)
        except Exception as exc:
            QMessageBox.critical(self, "Cannot open", str(exc))
            return
        self.doc = doc
        self.path = path
        self.view.load(doc)
        self.page_spin.setMaximum(len(doc))
        self.page_spin.setValue(1)
        self.page_total.setText(f" / {len(doc)} ")
        self.setWindowTitle(f"PDF Tool — {os.path.basename(path)}")
        self._update_actions()
        self._done(f"Opened {os.path.basename(path)}")

    def _reload(self, new_path: str):
        """Open the result of an operation in place."""
        self.doc = fitz.open(new_path)
        self.path = new_path
        self.view.load(self.doc)
        self.page_spin.setMaximum(len(self.doc))
        self.page_total.setText(f" / {len(self.doc)} ")

    # ----- navigation / zoom -----
    def _prev(self):
        if self.doc and self.view.page_no > 0:
            self.page_spin.setValue(self.view.page_no)  # 1-indexed

    def _next(self):
        if self.doc and self.view.page_no < len(self.doc) - 1:
            self.page_spin.setValue(self.view.page_no + 2)

    def _zoom(self, factor: float):
        self.view.set_zoom(self.view.zoom * factor)

    # ----- features -----
    def do_ocr(self):
        if not self._guard():
            return
        lang, ok = QInputDialog.getText(
            self, "OCR", "Language code(s) (e.g. eng, eng+fra):", text="eng")
        if not ok or not lang.strip():
            return
        out, _ = QFileDialog.getSaveFileName(
            self, "Save searchable PDF", self._suffix("ocr"), "PDF (*.pdf)")
        if not out:
            return
        self._busy("Running OCR…")
        t, w = run_async(
            self, engine.ocr_pdf, self.path, out,
            language=lang.strip(), force=False,
            on_done=lambda _r: (self._reload(out), self._done("OCR complete")),
            on_error=self._error,
        )
        self._threads.append((t, w))

    def do_docx(self):
        if not self._guard():
            return
        out, _ = QFileDialog.getSaveFileName(
            self, "Export to Word", self._suffix("docx", ext="docx"),
            "Word document (*.docx)")
        if not out:
            return
        self._busy("Converting to DOCX…")
        t, w = run_async(
            self, engine.pdf_to_docx, self.path, out,
            on_done=lambda _r: self._done(f"Saved {os.path.basename(out)}"),
            on_error=self._error,
        )
        self._threads.append((t, w))

    def do_watermark(self):
        if not self._guard():
            return
        text, ok = QInputDialog.getText(
            self, "Watermark", "Watermark text:", text="DRAFT")
        if not ok or not text:
            return
        out, _ = QFileDialog.getSaveFileName(
            self, "Save watermarked PDF", self._suffix("watermarked"),
            "PDF (*.pdf)")
        if not out:
            return
        self._busy("Applying watermark…")
        t, w = run_async(
            self, engine.add_text_watermark, self.path, out, text,
            on_done=lambda _r: (self._reload(out), self._done("Watermark applied")),
            on_error=self._error,
        )
        self._threads.append((t, w))

    def do_redactions(self):
        if not self._guard():
            return
        boxes = self.view.redact_boxes()
        if not boxes:
            QMessageBox.information(
                self, "No selections",
                "Enable Redact mode and drag over regions first.")
            return
        confirm = QMessageBox.warning(
            self, "Apply redactions",
            f"Permanently remove content under {len(boxes)} region(s)? "
            "This cannot be undone in the output file.",
            QMessageBox.Yes | QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        out, _ = QFileDialog.getSaveFileName(
            self, "Save redacted PDF", self._suffix("redacted"), "PDF (*.pdf)")
        if not out:
            return
        self._busy("Applying redactions…")
        t, w = run_async(
            self, engine.apply_redactions, self.path, out, boxes,
            on_done=lambda _r: (
                self.view.clear_selections(),
                self._reload(out),
                self.act_redact.setChecked(False),
                self._done("Redactions applied")),
            on_error=self._error,
        )
        self._threads.append((t, w))

    # ------------------------------------------------------------------
    def _guard(self) -> bool:
        if not self.doc:
            QMessageBox.information(self, "No document", "Open a PDF first.")
            return False
        return True

    def _suffix(self, tag: str, ext: str = "pdf") -> str:
        if not self.path:
            return f"output-{tag}.{ext}"
        base, _ = os.path.splitext(self.path)
        return f"{base}-{tag}.{ext}"

    def _on_selection_change(self, n: int):
        self.act_apply.setText(f"Apply redactions ({n})" if n else "Apply redactions")

    def _update_actions(self):
        has = self.doc is not None
        for a in (self.act_ocr, self.act_docx, self.act_wm,
                  self.act_redact, self.act_apply, self.act_clear,
                  self.prev, self.next):
            a.setEnabled(has)
