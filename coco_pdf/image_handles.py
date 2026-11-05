"""Selected image overlay: move (drag), resize (corner and side handles), rotate (top handle), toolbar."""
from __future__ import annotations

import math

import pymupdf
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QTransform
from PySide6.QtWidgets import QFrame, QHBoxLayout, QToolButton, QWidget

from .pdf_images import ImageItem

HANDLE = 5  # half size of a handle, px
GRAB = 9  # hit radius around a handle, px
ROTATE_OFFSET = 28  # distance of the rotation handle above the top edge, px
BLUE = QColor(30, 120, 255)
# (sx, sy) of each handle in the image's local frame: corners then side midpoints.
HANDLES = [(-1, -1), (1, -1), (1, 1), (-1, 1), (0, -1), (1, 0), (0, 1), (-1, 0)]


def image_to_qimage(doc: pymupdf.Document, xref: int) -> QImage:
    pix = pymupdf.Pixmap(doc, xref)
    smask = doc.xref_get_key(xref, "SMask")
    if smask[0] == "xref":
        pix = pymupdf.Pixmap(pix, pymupdf.Pixmap(doc, int(smask[1].split()[0])))
    if pix.colorspace and pix.colorspace.n not in (1, 3):
        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
    fmt = QImage.Format.Format_RGBA8888 if pix.alpha else (
        QImage.Format.Format_Grayscale8 if pix.n == 1 else QImage.Format.Format_RGB888)
    return QImage(pix.samples, pix.width, pix.height, pix.stride, fmt).copy()


class ImageSelection(QWidget):
    """Covers the whole page widget while an image is selected. Geometry is kept in screen pixels."""

    changed = Signal(object)  # new ImageItem in unrotated page space
    deleted = Signal()
    clicked_outside = Signal(QPointF)

    def __init__(self, page_widget, item: ImageItem, page: pymupdf.Page, zoom: float):
        super().__init__(page_widget)
        self.item, self.zoom = item, zoom
        self.rotation, self.rotation_matrix, self.derotation_matrix = page.rotation, page.rotation_matrix, \
            page.derotation_matrix
        self.preview = image_to_qimage(page.parent, item.xref)
        c = item.center * page.rotation_matrix
        self.center = QPointF(c.x * zoom, c.y * zoom)
        self.w, self.h = item.width * zoom, item.height * zoom
        self.angle = (item.angle + page.rotation) % 360
        self.drag = None
        self.setGeometry(page_widget.rect())
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.toolbar = self._build_toolbar()
        self.show()
        self.setFocus()
        self._place_toolbar()

    # --- geometry helpers --------------------------------------------------

    def _transform(self) -> QTransform:
        t = QTransform()
        t.translate(self.center.x(), self.center.y())
        t.rotate(self.angle)
        return t

    def _local(self, pos: QPointF) -> QPointF:
        return self._transform().inverted()[0].map(pos)

    def _handle_points(self) -> list[QPointF]:
        t = self._transform()
        return [t.map(QPointF(sx * self.w / 2, sy * self.h / 2)) for sx, sy in HANDLES]

    def _rotate_handle(self) -> QPointF:
        return self._transform().map(QPointF(0, -self.h / 2 - ROTATE_OFFSET))

    def _hit(self, pos: QPointF):
        if (pos - self._rotate_handle()).manhattanLength() <= GRAB * 1.4:
            return ("rotate", None)
        for index, point in enumerate(self._handle_points()):
            if (pos - point).manhattanLength() <= GRAB * 1.4:
                return ("resize", index)
        local = self._local(pos)
        if abs(local.x()) <= self.w / 2 and abs(local.y()) <= self.h / 2:
            return ("move", None)
        return None

    def to_item(self) -> ImageItem:
        center = pymupdf.Point(self.center.x() / self.zoom, self.center.y() / self.zoom) * self.derotation_matrix
        return self.item.moved(center, self.w / self.zoom, self.h / self.zoom, self.angle - self.rotation)

    # --- painting ----------------------------------------------------------

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setTransform(self._transform())
        box = QRectF(-self.w / 2, -self.h / 2, self.w, self.h)
        if self.drag:
            # The page still shows the image at its old place until the change is applied: draw a ghost.
            p.setOpacity(0.75)
            if self.item.flipped:
                p.scale(-1, 1)
            p.drawImage(box, self.preview)
            if self.item.flipped:
                p.scale(-1, 1)
            p.setOpacity(1)
        p.setPen(QPen(BLUE, 1.5, Qt.PenStyle.DashLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(box)
        p.setPen(QPen(BLUE, 1.5))
        p.drawLine(QPointF(0, -self.h / 2), QPointF(0, -self.h / 2 - ROTATE_OFFSET))
        p.resetTransform()
        p.setBrush(Qt.GlobalColor.white)
        for point in self._handle_points():
            p.drawRect(QRectF(point.x() - HANDLE, point.y() - HANDLE, 2 * HANDLE, 2 * HANDLE))
        p.setBrush(BLUE)
        p.drawEllipse(self._rotate_handle(), HANDLE + 1, HANDLE + 1)

    # --- mouse -------------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        pos = event.position()
        hit = self._hit(pos)
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if hit is None:
            self.clicked_outside.emit(pos)
            return
        self.drag = (hit, pos, QPointF(self.center), self.w, self.h, self.angle)

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        if not self.drag:
            hit = self._hit(pos)
            cursors = {"move": Qt.CursorShape.SizeAllCursor, "resize": Qt.CursorShape.CrossCursor,
                       "rotate": Qt.CursorShape.PointingHandCursor}
            self.setCursor(cursors.get(hit[0], Qt.CursorShape.ArrowCursor) if hit else Qt.CursorShape.ArrowCursor)
            return
        (kind, index), start, center0, w0, h0, _ = self.drag
        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if kind == "move":
            self.center = center0 + (pos - start)
        elif kind == "rotate":
            d = pos - self.center
            angle = math.degrees(math.atan2(d.y(), d.x())) + 90
            self.angle = (round(angle / 15) * 15 if shift else angle) % 360
        else:
            self._resize(index, pos, center0, w0, h0, keep_ratio=index < 4 and not shift)
        self.update()
        self._place_toolbar()

    def _resize(self, index: int, pos: QPointF, center0: QPointF, w0: float, h0: float, keep_ratio: bool) -> None:
        sx, sy = HANDLES[index]
        t = QTransform()
        t.translate(center0.x(), center0.y())
        t.rotate(self.angle)
        local = t.inverted()[0].map(pos)
        # The opposite corner (or side) stays where it is.
        ox, oy = -sx * w0 / 2, -sy * h0 / 2
        w = max(8.0, sx * (local.x() - ox)) if sx else w0
        h = max(8.0, sy * (local.y() - oy)) if sy else h0
        if keep_ratio:
            scale = max(w / w0, h / h0)
            w, h = w0 * scale, h0 * scale
        cx = ox + sx * w / 2 if sx else 0
        cy = oy + sy * h / 2 if sy else 0
        self.center = t.map(QPointF(cx, cy))
        self.w, self.h = w, h

    def mouseReleaseEvent(self, event) -> None:
        if self.drag:
            moved = (self.center, self.w, self.h, self.angle) != self.drag[2:]
            self.drag = None
            self.update()
            if moved:
                self.changed.emit(self.to_item())

    def event(self, event) -> bool:
        # Delete / Esc act on the selected image, not through the window's shortcuts (Del deletes pages).
        if event.type() == QEvent.Type.ShortcutOverride and event.key() in (
                Qt.Key.Key_Delete, Qt.Key.Key_Backspace, Qt.Key.Key_Escape):
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.deleted.emit()
        elif event.key() == Qt.Key.Key_Escape:
            self.clicked_outside.emit(QPointF(-1, -1))
        else:
            super().keyPressEvent(event)

    # --- toolbar -----------------------------------------------------------

    def _build_toolbar(self) -> QFrame:
        bar = QFrame(self)
        bar.setStyleSheet("QFrame { background: palette(window); border: 1px solid palette(mid); "
                          "border-radius: 6px; } QToolButton { border: none; padding: 3px 6px; }")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(2)
        for text, tip, slot in (("⟲ 90°", "Pivoter à gauche", lambda: self._rotate_by(-90)),
                                ("⟳ 90°", "Pivoter à droite", lambda: self._rotate_by(90)),
                                ("0°", "Remettre droit", lambda: self._rotate_by(-self.angle)),
                                ("🗑", "Supprimer l'image (Suppr)", self.deleted.emit)):
            button = QToolButton(text=text, toolTip=tip)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.clicked.connect(slot)
            layout.addWidget(button)
        bar.adjustSize()
        bar.show()
        return bar

    def _rotate_by(self, delta: float) -> None:
        self.angle = (self.angle + delta) % 360
        self.changed.emit(self.to_item())

    def _place_toolbar(self) -> None:
        points = self._handle_points() + [self._rotate_handle()]
        top = min(p.y() for p in points)
        left = min(p.x() for p in points)
        bottom = max(p.y() for p in points)
        y = top - self.toolbar.height() - 8
        if y < 0:
            y = bottom + 8
        x = min(max(left, 0), max(self.width() - self.toolbar.width(), 0))
        self.toolbar.move(int(x), int(y))
