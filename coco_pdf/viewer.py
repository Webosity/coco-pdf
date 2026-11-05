"""Continuous-scroll page view. Pages are rendered lazily when they get painted."""
from __future__ import annotations

import pymupdf
from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

from .document import PdfDocument

PAGE_GAP = 12


def render(page: pymupdf.Page, zoom: float) -> QPixmap:
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
    image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(image.copy())


class PageWidget(QWidget):
    clicked = Signal(int, object)  # page index, pymupdf.Point in unrotated page space

    def __init__(self, view: PageView, index: int):
        super().__init__()
        self.view = view
        self.index = index
        self.pixmap: QPixmap | None = None
        self.highlights: list[pymupdf.Rect] = []
        self.hover_rect: pymupdf.Rect | None = None
        self.setMouseTracking(True)
        self.resize_to_page()

    def page(self) -> pymupdf.Page:
        return self.view.pdf.page(self.index)

    def resize_to_page(self) -> None:
        rect = self.page().rect
        self.setFixedSize(int(rect.width * self.view.zoom), int(rect.height * self.view.zoom))
        self.pixmap = None

    def to_page_point(self, pos: QPoint) -> pymupdf.Point:
        zoom = self.view.zoom
        return pymupdf.Point(pos.x() / zoom, pos.y() / zoom) * self.page().derotation_matrix

    def to_screen_rect(self, rect: pymupdf.Rect) -> QRectF:
        r = rect * self.page().rotation_matrix * self.view.zoom
        return QRectF(r.x0, r.y0, r.width, r.height)

    def paintEvent(self, event) -> None:
        if self.pixmap is None:
            self.pixmap = render(self.page(), self.view.zoom)
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self.pixmap)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 200, 0, 90))
        for rect in self.highlights:
            painter.drawRect(self.to_screen_rect(rect))
        if self.hover_rect is not None:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QColor(30, 120, 255))
            painter.drawRect(self.to_screen_rect(self.hover_rect))

    def mouseMoveEvent(self, event) -> None:
        rect = None
        if self.view.mode == "edit_text":
            span = self.view.pdf.span_at(self.index, self.to_page_point(event.position().toPoint()))
            rect = span.bbox if span else None
        if rect != self.hover_rect:
            self.hover_rect = rect
            self.update()

    def leaveEvent(self, event) -> None:
        self.hover_rect = None
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.index, self.to_page_point(event.position().toPoint()))


class PageView(QScrollArea):
    page_clicked = Signal(int, object)
    current_page_changed = Signal(int)

    def __init__(self):
        super().__init__()
        self.pdf: PdfDocument | None = None
        self.zoom = 1.25
        self.mode = "view"
        self.pages: list[PageWidget] = []
        self.setWidgetResizable(True)
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.setStyleSheet("QScrollArea { background: #525659; }")
        self.verticalScrollBar().valueChanged.connect(self._emit_current_page)

    def set_document(self, pdf: PdfDocument | None) -> None:
        self.pdf = pdf
        self.rebuild()

    def rebuild(self) -> None:
        """Recreate page widgets (after page count, order or rotation changes)."""
        container = QWidget()
        container.setStyleSheet("background: #525659;")
        layout = QVBoxLayout(container)
        layout.setSpacing(PAGE_GAP)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.pages = []
        if self.pdf:
            for i in range(self.pdf.page_count):
                widget = PageWidget(self, i)
                widget.clicked.connect(self.page_clicked)
                layout.addWidget(widget, alignment=Qt.AlignmentFlag.AlignHCenter)
                self.pages.append(widget)
        self.setWidget(container)

    def refresh_page(self, index: int) -> None:
        if 0 <= index < len(self.pages):
            self.pages[index].resize_to_page()
            self.pages[index].update()

    def set_zoom(self, zoom: float) -> None:
        current = self.current_page()
        self.zoom = max(0.25, min(zoom, 6.0))
        for widget in self.pages:
            widget.resize_to_page()
        self.widget().adjustSize()
        self.go_to_page(current)

    def fit_width(self) -> None:
        if self.pages:
            available = self.viewport().width() - 40
            self.set_zoom(available / self.pages[self.current_page()].page().rect.width)

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        cursor = Qt.CursorShape.ArrowCursor if mode == "view" else Qt.CursorShape.CrossCursor
        if mode == "edit_text":
            cursor = Qt.CursorShape.IBeamCursor
        for widget in self.pages:
            widget.setCursor(cursor)
            widget.hover_rect = None

    def set_highlights(self, hits: dict[int, list[pymupdf.Rect]]) -> None:
        for widget in self.pages:
            widget.highlights = hits.get(widget.index, [])
            widget.update()

    def go_to_page(self, index: int, rect: pymupdf.Rect | None = None) -> None:
        if not 0 <= index < len(self.pages):
            return
        widget = self.pages[index]
        y = widget.y()
        if rect is not None:
            y += int(widget.to_screen_rect(rect).top()) - 80
        self.verticalScrollBar().setValue(y)

    def current_page(self) -> int:
        middle = self.verticalScrollBar().value() + self.viewport().height() // 3
        for widget in self.pages:
            if widget.y() + widget.height() + PAGE_GAP > middle:
                return widget.index
        return max(len(self.pages) - 1, 0)

    def _emit_current_page(self) -> None:
        self.current_page_changed.emit(self.current_page())

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.set_zoom(self.zoom * (1.1 if event.angleDelta().y() > 0 else 1 / 1.1))
        else:
            super().wheelEvent(event)
