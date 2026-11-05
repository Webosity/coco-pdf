"""Grips around the text box being edited: move it (top-left grip) or resize it (sides and corner)."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

SIZE = 10  # px
MIN_WIDTH = 40
BLUE = QColor(30, 120, 255)
# kind -> cursor. "move" sits outside the top-left corner so it never covers the text.
KINDS = {"move": Qt.CursorShape.SizeAllCursor, "left": Qt.CursorShape.SizeHorCursor,
         "right": Qt.CursorShape.SizeHorCursor, "corner": Qt.CursorShape.SizeFDiagCursor}


class Grip(QWidget):
    def __init__(self, handles: BoxHandles, kind: str):
        super().__init__(handles.target.parentWidget())
        self.handles, self.kind = handles, kind
        self.setFixedSize(SIZE + 6 if kind == "move" else SIZE, SIZE + 6 if kind == "move" else SIZE)
        self.setCursor(KINDS[kind])
        self.setToolTip("Déplacer la zone de texte" if kind == "move" else "Redimensionner la zone de texte")
        self.start: tuple[QPoint, QRect] | None = None

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(BLUE, 1.2))
        p.setBrush(BLUE if self.kind == "move" else QColor("white"))
        r = self.rect().adjusted(1, 1, -1, -1)
        if self.kind == "move":
            p.drawRoundedRect(r, 3, 3)
            p.setPen(QPen(QColor("white"), 1.4))
            c = r.center()
            for dx, dy in ((-4, 0), (4, 0), (0, -4), (0, 4)):
                p.drawLine(c, c + QPoint(dx, dy))
        else:
            p.drawRect(r)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.start = (event.globalPosition().toPoint(), self.handles.target.geometry())

    def mouseMoveEvent(self, event) -> None:
        if self.start:
            origin, geometry = self.start
            self.handles.drag(self.kind, geometry, event.globalPosition().toPoint() - origin)

    def mouseReleaseEvent(self, event) -> None:
        self.start = None


class BoxHandles:
    """on_change(new_geometry, user_height) is called while dragging; user_height is None unless the corner moved."""

    def __init__(self, target: QWidget, on_change: Callable[[QRect, int | None], None]):
        self.target, self.on_change = target, on_change
        self.grips = {kind: Grip(self, kind) for kind in KINDS}
        self.place()
        for grip in self.grips.values():
            grip.show()

    def drag(self, kind: str, start: QRect, delta: QPoint) -> None:
        g = QRect(start)
        bounds = self.target.parentWidget().rect()
        user_height = None
        if kind == "move":
            g.moveTopLeft(start.topLeft() + delta)
            g.moveLeft(min(max(g.left(), 0), bounds.width() - g.width()))
            g.moveTop(min(max(g.top(), 0), bounds.height() - g.height()))
        elif kind == "left":
            g.setLeft(min(max(start.left() + delta.x(), 0), start.right() - MIN_WIDTH))
        elif kind == "right":
            g.setRight(min(max(start.right() + delta.x(), start.left() + MIN_WIDTH), bounds.width() - 1))
        else:
            g.setRight(min(max(start.right() + delta.x(), start.left() + MIN_WIDTH), bounds.width() - 1))
            user_height = max(start.height() + delta.y(), SIZE)
        self.on_change(g, user_height)

    def place(self) -> None:
        g = self.target.geometry()
        half = SIZE // 2
        move = self.grips["move"]
        move.move(g.left() - move.width() - 2, g.top() - move.height() - 2)
        self.grips["left"].move(g.left() - half, g.center().y() - half)
        self.grips["right"].move(g.right() - half + 1, g.center().y() - half)
        self.grips["corner"].move(g.right() - half + 1, g.bottom() - half + 1)
        for grip in self.grips.values():
            grip.raise_()

    def close(self) -> None:
        for grip in self.grips.values():
            grip.hide()
            grip.deleteLater()
