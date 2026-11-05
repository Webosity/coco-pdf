"""Manage the signature bank: add, rename, reorder, delete, insert."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from .signatures import Signature, SignatureStore

IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp)"
THUMB = QSize(200, 80)
MENU_THUMB = QSize(120, 40)


def thumbnail(store: SignatureStore, signature: Signature, size: QSize = THUMB) -> QIcon:
    """The signature centred in a fixed-size frame, so every row of a list has the same height."""
    image = QPixmap(str(store.path(signature))).scaled(size, Qt.AspectRatioMode.KeepAspectRatio,
                                                       Qt.TransformationMode.SmoothTransformation)
    frame = QPixmap(size)
    frame.fill(Qt.GlobalColor.white)  # dark ink must stay readable in a dark-themed menu
    painter = QPainter(frame)
    painter.drawPixmap((size.width() - image.width()) // 2, (size.height() - image.height()) // 2, image)
    painter.end()
    return QIcon(frame)


class MenuEntry(QWidget):
    """Menu row with a readable signature preview (QMenu draws action icons at 16 px)."""

    clicked = Signal()

    def __init__(self, icon: QIcon, name: str):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setObjectName("entry")
        self.setStyleSheet("#entry { padding: 2px; border-radius: 4px; } #entry:hover { background: palette(highlight); }")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 12, 4)
        preview = QLabel()
        preview.setPixmap(icon.pixmap(MENU_THUMB))
        layout.addWidget(preview)
        layout.addWidget(QLabel(name), 1)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()


def add_menu_entry(menu: QMenu, store: SignatureStore, signature: Signature, on_click) -> None:
    entry = MenuEntry(thumbnail(store, signature, MENU_THUMB), signature.name)
    action = QWidgetAction(menu)
    action.setDefaultWidget(entry)
    entry.clicked.connect(menu.close)
    entry.clicked.connect(on_click)
    action.triggered.connect(on_click)  # keyboard: arrows + Enter
    menu.addAction(action)


class SignatureDialog(QDialog):
    insert_requested = Signal(object)  # Signature

    def __init__(self, parent, store: SignatureStore):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("Mes signatures")
        self.resize(560, 460)

        self.list = QListWidget()
        self.list.setIconSize(THUMB)
        self.list.setUniformItemSizes(True)
        # Signatures are dark ink on a transparent background: keep a white backdrop, even in dark mode.
        self.list.setStyleSheet("QListWidget { background: white; color: black; }"
                                "QListWidget::item { padding: 6px; border-bottom: 1px solid #e3e3e3; }"
                                "QListWidget::item:selected { background: #d6e6ff; color: black; }")
        self.list.itemDoubleClicked.connect(lambda _: self._insert())
        self.list.currentRowChanged.connect(lambda _: self._update_buttons())

        self.transparent = QCheckBox("Rendre le fond blanc transparent (signature scannée ou photographiée)",
                                     checked=True)
        hint = QLabel("Les signatures sont conservées sur ce PC d'une session à l'autre.")
        hint.setStyleSheet("color: gray;")

        buttons = QVBoxLayout()
        self.actions = {}
        for key, text, slot in (("add", "Ajouter…", self._add), ("insert", "Insérer", self._insert),
                                ("rename", "Renommer…", self._rename), ("up", "Monter", lambda: self._move(-1)),
                                ("down", "Descendre", lambda: self._move(1)), ("remove", "Supprimer", self._remove)):
            button = QPushButton(text)
            button.clicked.connect(slot)
            buttons.addWidget(button)
            self.actions[key] = button
        buttons.addStretch()
        close = QPushButton("Fermer")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)

        row = QHBoxLayout()
        row.addWidget(self.list, 1)
        row.addLayout(buttons)
        layout = QVBoxLayout(self)
        layout.addLayout(row)
        layout.addWidget(self.transparent)
        layout.addWidget(hint)
        self._reload()

    def _reload(self, select_id: str | None = None) -> None:
        self.list.clear()
        for signature in self.store.list():
            item = QListWidgetItem(thumbnail(self.store, signature), signature.name)
            item.setData(Qt.ItemDataRole.UserRole, signature)
            self.list.addItem(item)
            if signature.id == select_id:
                self.list.setCurrentItem(item)
        if self.list.currentRow() < 0 and self.list.count():
            self.list.setCurrentRow(0)
        self._update_buttons()

    def _current(self) -> Signature | None:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _update_buttons(self) -> None:
        has = self._current() is not None
        for key in ("insert", "rename", "up", "down", "remove"):
            self.actions[key].setEnabled(has)

    def _add(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Image de la signature", "", IMAGE_FILTER)
        if not path:
            return
        name, ok = QInputDialog.getText(self, "Nom de la signature", "Nom (ex. « Bon pour accord ») :")
        if not ok:
            return
        try:
            signature = self.store.add(path, name.strip() or "Signature", self.transparent.isChecked())
        except (RuntimeError, OSError, ValueError) as error:
            QMessageBox.warning(self, "Signature", f"Image illisible : {error}")
            return
        self._reload(signature.id)

    def _insert(self) -> None:
        signature = self._current()
        if signature:
            self.insert_requested.emit(signature)
            self.accept()

    def _rename(self) -> None:
        signature = self._current()
        if not signature:
            return
        name, ok = QInputDialog.getText(self, "Renommer", "Nouveau nom :", text=signature.name)
        if ok and name.strip():
            self.store.rename(signature.id, name.strip())
            self._reload(signature.id)

    def _move(self, delta: int) -> None:
        signature = self._current()
        if signature:
            self.store.move(signature.id, delta)
            self._reload(signature.id)

    def _remove(self) -> None:
        signature = self._current()
        if signature and QMessageBox.question(self, "Supprimer", f"Supprimer « {signature.name} » ?") == \
                QMessageBox.StandardButton.Yes:
            self.store.remove(signature.id)
            self._reload()
