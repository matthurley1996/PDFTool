"""
PDF page view: renders the current page, supports zoom, and lets the user
drag rubber-band rectangles to mark redaction regions.

Selections are stored in *PDF coordinate space* (not screen pixels) so they
remain correct regardless of zoom level.
"""
from __future__ import annotations

from typing import List

from PySide6.QtCore import Qt, QRectF, QPointF, Signal
from PySide6.QtGui import QImage, QPixmap, QPainter, QPen, QColor
from PySide6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QGraphicsRectItem,
)

import fitz
from .engine import RedactBox


class PageView(QGraphicsView):
    selectionsChanged = Signal(int)  # emits current selection count

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.NoDrag)

        self.doc: fitz.Document | None = None
        self.page_no = 0
        self.zoom = 1.0
        self._redact_mode = False

        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._rubber: QGraphicsRectItem | None = None
        self._origin = QPointF()
        # redaction rects in scene coords, per page index
        self._rects: dict[int, List[QRectF]] = {}

    # ----- document / navigation -----
    def load(self, doc: fitz.Document):
        self.doc = doc
        self._rects.clear()
        self.page_no = 0
        self.render()

    def set_page(self, n: int):
        if self.doc and 0 <= n < len(self.doc):
            self.page_no = n
            self.render()

    def set_zoom(self, z: float):
        self.zoom = max(0.1, min(z, 8.0))
        self.render()

    def set_redact_mode(self, on: bool):
        self._redact_mode = on
        self.setCursor(Qt.CrossCursor if on else Qt.ArrowCursor)

    # ----- rendering -----
    def render(self):
        if not self.doc:
            return
        page = self.doc[self.page_no]
        mat = fitz.Matrix(self.zoom, self.zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                     QImage.Format_RGB888)
        # copy() detaches from the underlying buffer which Qt does not own
        self._scene.clear()
        self._pixmap_item = self._scene.addPixmap(QPixmap.fromImage(img.copy()))
        self._scene.setSceneRect(QRectF(0, 0, pix.width, pix.height))
        self._redraw_saved_rects()

    def _redraw_saved_rects(self):
        for r in self._rects.get(self.page_no, []):
            item = QGraphicsRectItem(QRectF(r.topLeft() * self.zoom,
                                            r.bottomRight() * self.zoom))
            item.setBrush(QColor(0, 0, 0, 90))
            item.setPen(QPen(QColor(200, 30, 30), 1))
            self._scene.addItem(item)

    # ----- redaction selection -----
    def mousePressEvent(self, event):
        if self._redact_mode and event.button() == Qt.LeftButton:
            self._origin = self.mapToScene(event.position().toPoint())
            self._rubber = QGraphicsRectItem(QRectF(self._origin, self._origin))
            self._rubber.setBrush(QColor(200, 30, 30, 60))
            self._rubber.setPen(QPen(QColor(200, 30, 30), 1))
            self._scene.addItem(self._rubber)
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._rubber is not None:
            cur = self.mapToScene(event.position().toPoint())
            self._rubber.setRect(QRectF(self._origin, cur).normalized())
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._rubber is not None:
            rect_scene = self._rubber.rect()
            # store in PDF coords (divide out the zoom)
            pdf_rect = QRectF(rect_scene.topLeft() / self.zoom,
                              rect_scene.bottomRight() / self.zoom)
            if pdf_rect.width() > 2 and pdf_rect.height() > 2:
                self._rects.setdefault(self.page_no, []).append(pdf_rect)
                self.selectionsChanged.emit(self.selection_count())
            self._rubber = None
            self.render()
        else:
            super().mouseReleaseEvent(event)

    def clear_selections(self):
        self._rects.clear()
        self.selectionsChanged.emit(0)
        self.render()

    def selection_count(self) -> int:
        return sum(len(v) for v in self._rects.values())

    def redact_boxes(self) -> List[RedactBox]:
        boxes: List[RedactBox] = []
        for pno, rects in self._rects.items():
            for r in rects:
                boxes.append(RedactBox(pno, r.left(), r.top(),
                                       r.right(), r.bottom()))
        return boxes
