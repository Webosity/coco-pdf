"""Page thumbnails sidebar: navigation, multi-selection and drag-and-drop reordering."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QListWidget, QListWidgetItem

from .document import PdfDocument
from .viewer import render

THUMB_WIDTH = 130
BATCH = 8


class ThumbnailList(QListWidget):
    page_selected = Signal(int)
    order_changed = Signal(list)

    def __init__(self):
        super().__init__()
        self.pdf: PdfDocument | None = None
        # List mode, not icon mode: only list mode turns a drag-and-drop into a real row move.
        self.setIconSize(QSize(THUMB_WIDTH, int(THUMB_WIDTH * 1.42)))
        self.setSpacing(4)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setFixedWidth(THUMB_WIDTH + 70)
        self._placeholder = QPixmap(self.iconSize())
        self._placeholder.fill(Qt.GlobalColor.white)
        self.itemClicked.connect(lambda item: self.page_selected.emit(self.row(item)))
        self.model().rowsMoved.connect(self._on_rows_moved)
        self._pending: list[int] = []
        self._timer = QTimer(self, interval=0)
        self._timer.timeout.connect(self._render_batch)

    def set_document(self, pdf: PdfDocument | None) -> None:
        self.pdf = pdf
        self.rebuild()

    def rebuild(self) -> None:
        self.clear()
        if not self.pdf:
            return
        for i in range(self.pdf.page_count):
            item = QListWidgetItem(QIcon(self._placeholder), str(i + 1))
            item.setData(Qt.ItemDataRole.UserRole, i)
            self.addItem(item)
        self._pending = list(range(self.pdf.page_count))
        self._timer.start()

    def refresh_page(self, index: int) -> None:
        if index not in self._pending:
            self._pending.insert(0, index)
            self._timer.start()

    def _render_batch(self) -> None:
        for _ in range(BATCH):
            if not self._pending:
                self._timer.stop()
                return
            i = self._pending.pop(0)
            if i < self.count():
                page = self.pdf.page(i)
                zoom = THUMB_WIDTH / max(page.rect.width, page.rect.height / 1.42)
                self.item(i).setIcon(QIcon(render(page, zoom)))

    def selected_pages(self) -> list[int]:
        return sorted(self.row(item) for item in self.selectedItems())

    def select_page(self, index: int) -> None:
        if 0 <= index < self.count() and index not in self.selected_pages():
            self.blockSignals(True)
            self.setCurrentRow(index)
            self.blockSignals(False)

    def _on_rows_moved(self, *args) -> None:
        order = [self.item(row).data(Qt.ItemDataRole.UserRole) for row in range(self.count())]
        if order != sorted(order):
            # Deferred: rebuilding the list from inside its own drop handler crashes Qt.
            QTimer.singleShot(0, lambda: self.order_changed.emit(order))
