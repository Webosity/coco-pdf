"""Continuous-scroll page view. Pages are rendered lazily when painted; editing overlays sit on top of them."""
from __future__ import annotations

import pymupdf
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPalette, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

from .document import PdfDocument
from .image_handles import ImageSelection
from .pdf_images import ImageItem
from .pdf_text import TextStyle
from .text_editor import InlineTextEditor

PAGE_GAP = 12
NEW_TEXT_WIDTH = 250  # pt
UNIT_SQUARE = [pymupdf.Point(0, 0), pymupdf.Point(1, 0), pymupdf.Point(1, 1), pymupdf.Point(0, 1)]


BACKDROP = "#525659"  # grey around the pages


def _backdrop(palette: QPalette) -> QPalette:
    palette.setColor(QPalette.ColorRole.Window, QColor(BACKDROP))
    return palette


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
        self.hover: list[pymupdf.Point] | None = None  # outline of the text block or image under the mouse
        self.mask: pymupdf.Rect | None = None  # paragraph being edited: hidden, as the editor may be moved away
        self.setMouseTracking(True)
        self.resize_to_page()

    def page(self) -> pymupdf.Page:
        return self.view.pdf.page(self.index)

    def resize_to_page(self) -> None:
        rect = self.page().rect
        self.setFixedSize(int(rect.width * self.view.zoom), int(rect.height * self.view.zoom))
        self.pixmap = None

    def to_page_point(self, pos: QPoint | QPointF) -> pymupdf.Point:
        zoom = self.view.zoom
        return pymupdf.Point(pos.x() / zoom, pos.y() / zoom) * self.page().derotation_matrix

    def to_screen(self, point: pymupdf.Point) -> QPointF:
        p = point * self.page().rotation_matrix * self.view.zoom
        return QPointF(p.x, p.y)

    def to_screen_rect(self, rect: pymupdf.Rect) -> QRectF:
        r = rect * self.page().rotation_matrix * self.view.zoom
        return QRectF(r.x0, r.y0, r.width, r.height)

    def paintEvent(self, event) -> None:
        if self.pixmap is None:
            self.pixmap = render(self.page(), self.view.zoom)
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self.pixmap)
        if self.mask is not None:
            painter.fillRect(self.to_screen_rect(self.mask), QColor("white"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 200, 0, 90))
        for rect in self.highlights:
            painter.drawRect(self.to_screen_rect(rect))
        if self.hover:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(30, 120, 255), 1, Qt.PenStyle.DashLine))
            painter.drawPolygon(QPolygonF([self.to_screen(p) for p in self.hover]))

    def _shape_under(self, point: pymupdf.Point) -> list[pymupdf.Point] | None:
        item = self.view.pdf.item_at(self.index, point)
        if isinstance(item, ImageItem):
            m = item.matrix()
            return [p * m for p in UNIT_SQUARE]
        if item:
            r = item.bbox + (-2, -2, 2, 2)
            return [r.tl, r.tr, r.br, r.bl]
        return None

    def mouseMoveEvent(self, event) -> None:
        shape = None
        if self.view.mode == "edit" and not self.view.busy():
            shape = self._shape_under(self.to_page_point(event.position()))
        if shape != self.hover:
            self.hover = shape
            self.update()

    def leaveEvent(self, event) -> None:
        if self.hover:
            self.hover = None
            self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.index, self.to_page_point(event.position()))

    def contextMenuEvent(self, event) -> None:
        self.view.close_overlays()
        self.view.context_requested.emit(self.index, self.to_page_point(event.pos()), event.globalPos())


class PageView(QScrollArea):
    page_clicked = Signal(int, object)  # click not handled by the view itself (e.g. "add image" mode)
    current_page_changed = Signal(int)
    # page, TextBlock | None, screen rect (pt), text, style, box moved or resized
    text_edited = Signal(int, object, object, str, object, bool)
    context_requested = Signal(int, object, QPoint)  # page, pymupdf.Point, global position
    image_edited = Signal(object, object)  # old ImageItem, new ImageItem or None to delete

    def __init__(self):
        super().__init__()
        self.pdf: PdfDocument | None = None
        self.zoom = 1.25
        self.mode = "view"
        self.new_text_style = TextStyle()
        self.pages: list[PageWidget] = []
        self.text_session: InlineTextEditor | None = None
        self.image_session: ImageSelection | None = None
        self.setWidgetResizable(True)
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.setPalette(_backdrop(self.palette()))
        self.verticalScrollBar().valueChanged.connect(self._emit_current_page)

    def set_document(self, pdf: PdfDocument | None) -> None:
        self.pdf = pdf
        self.rebuild()

    def rebuild(self) -> None:
        """Recreate page widgets (after page count, order or rotation changes)."""
        self.close_overlays(commit=False)
        container = QWidget()
        # A palette, not a style sheet: a style sheet here would cascade to every widget laid over the
        # pages (editing toolbars, their combo boxes...) and paint them all dark grey.
        container.setAutoFillBackground(True)
        container.setPalette(_backdrop(container.palette()))
        layout = QVBoxLayout(container)
        layout.setSpacing(PAGE_GAP)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.pages = []
        if self.pdf:
            for i in range(self.pdf.page_count):
                widget = PageWidget(self, i)
                widget.clicked.connect(self.on_page_clicked)
                layout.addWidget(widget, alignment=Qt.AlignmentFlag.AlignHCenter)
                self.pages.append(widget)
        self.setWidget(container)

    def refresh_page(self, index: int) -> None:
        if 0 <= index < len(self.pages):
            self.pages[index].resize_to_page()
            self.pages[index].update()

    # --- editing overlays --------------------------------------------------

    def busy(self) -> bool:
        return self.text_session is not None or self.image_session is not None

    def close_overlays(self, commit: bool = True) -> None:
        if self.text_session:
            session, self.text_session = self.text_session, None
            session.commit() if commit else session.cancel()
        if self.image_session:
            session, self.image_session = self.image_session, None
            session.hide()  # now: deleteLater only runs once control is back in the event loop
            session.deleteLater()

    def on_page_clicked(self, index: int, point: pymupdf.Point) -> None:
        if self.busy():
            self.close_overlays()  # a click outside the editor validates it
            return
        widget = self.pages[index]
        widget.hover = None
        if self.mode == "edit":
            item = self.pdf.item_at(index, point)
            if isinstance(item, ImageItem):
                self.select_image(item)
            elif item:
                self.edit_block(item)
        elif self.mode == "add_text":
            self.new_text_at(index, point)
        else:
            self.page_clicked.emit(index, point)

    def edit_block(self, block) -> None:
        widget = self.pages[block.page]
        self._start_text(widget, widget.to_screen_rect(block.bbox), block, block.text, block.style)

    def new_text_at(self, index: int, point: pymupdf.Point, text: str = "", style: TextStyle | None = None) -> None:
        self.close_overlays()
        widget = self.pages[index]
        top_left = point * widget.page().rotation_matrix
        width = max(40.0, min(NEW_TEXT_WIDTH, widget.page().rect.width - top_left.x - 10))
        rect = QRectF(top_left.x * self.zoom, top_left.y * self.zoom, width * self.zoom, 0)
        self._start_text(widget, rect, None, text, style or self.new_text_style)
        if text:
            self.text_session.box_changed = True  # pasted text: validating must write it even if unchanged

    def _start_text(self, widget: PageWidget, rect: QRectF, block, text: str, style: TextStyle) -> None:
        session = InlineTextEditor(widget, rect.adjusted(-1, -1, 1, 1), text, style, self.zoom)
        widget.mask = block.bbox if block else None
        widget.update()

        def unmask() -> None:
            widget.mask = None
            widget.update()

        def done(new_text: str, new_style: TextStyle, moved: bool) -> None:
            self.text_session = None
            unmask()
            g = session.editor.geometry()
            screen = pymupdf.Rect(g.x(), g.y(), g.x() + g.width(), g.y() + g.height()) / self.zoom
            self.text_edited.emit(widget.index, block, screen, new_text, new_style, moved)

        session.committed.connect(done)
        session.cancelled.connect(lambda: setattr(self, "text_session", None))
        session.cancelled.connect(unmask)
        self.text_session = session

    def select_image(self, item) -> None:
        self.close_overlays()
        widget = self.pages[item.page]
        session = ImageSelection(widget, item, widget.page(), self.zoom)
        session.changed.connect(lambda new: self.image_edited.emit(item, new))
        session.deleted.connect(lambda: self._delete_image(item))
        session.clicked_outside.connect(lambda pos: self._leave_image(widget, pos))
        self.image_session = session

    def _delete_image(self, item) -> None:
        self.close_overlays()
        self.image_edited.emit(item, None)

    def _leave_image(self, widget: PageWidget, pos: QPointF) -> None:
        self.close_overlays()
        if pos.x() >= 0:  # forward the click, so another block or image can be picked at once
            self.on_page_clicked(widget.index, widget.to_page_point(pos))

    # --- view --------------------------------------------------------------

    def set_zoom(self, zoom: float) -> None:
        self.close_overlays()
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
        self.close_overlays()
        self.mode = mode
        cursors = {"view": Qt.CursorShape.ArrowCursor, "edit": Qt.CursorShape.IBeamCursor}
        for widget in self.pages:
            widget.setCursor(cursors.get(mode, Qt.CursorShape.CrossCursor))
            widget.hover = None

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
