"""Right-click menu on the page, and cut / copy / paste of paragraphs and images."""
from __future__ import annotations

import pymupdf
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QMimeData, QPoint
from PySide6.QtGui import QAction, QImage, QKeySequence
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu

from .icons import icon
from .pdf_images import ImageItem
from .pdf_text import TextBlock

# Marks clipboard content copied by Coco PDF itself, so pasting it keeps the text style or image size.
MARKER = "application/x-coco-pdf"
PASTE_OFFSET = 15  # pt: a copy pasted with Ctrl+V lands next to the original, not on top of it


def _png(image: QImage) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data)


class ContextMenuMixin:
    """Expects EditingMixin's methods, self.pdf, self.view, self.signatures and the undo/redo actions."""

    clip: tuple | None = None  # ("image", png, width, height) or ("text", text, style)

    # --- right-click menu --------------------------------------------------

    def show_context_menu(self, index: int, point: pymupdf.Point, global_pos: QPoint) -> None:
        target = self.pdf.item_at(index, point)
        image = target if isinstance(target, ImageItem) else None
        block = None if image else target
        menu = QMenu(self)

        menu.addAction(icon("add_text"), "Ajouter une zone de texte ici", lambda: self.view.new_text_at(index, point))
        menu.addAction(icon("add_image"), "Ajouter une image ici…", lambda: self.add_image_here(index, point))
        signatures = menu.addMenu(icon("signature"), "Insérer une signature ici")
        self.fill_signatures(signatures, lambda s: self.place_signature(index, point, s))
        menu.addSeparator()

        if block:
            menu.addAction(icon("edit"), "Modifier ce texte", lambda: self.view.edit_block(block))
        elif image:
            menu.addAction(icon("edit"), "Ajuster cette image", lambda: self.view.select_image(image))
        self._entry(menu, "Couper", QKeySequence.StandardKey.Cut, lambda: self.cut(target), bool(target))
        self._entry(menu, "Copier", QKeySequence.StandardKey.Copy, lambda: self.copy(target), bool(target))
        self._entry(menu, "Coller ici", QKeySequence.StandardKey.Paste, lambda: self.paste_at(index, point),
                    self.can_paste())
        self._entry(menu, "Supprimer", QKeySequence.StandardKey.Delete, lambda: self.delete(target), bool(target))
        menu.addSeparator()
        self._entry(menu, "Annuler", QKeySequence.StandardKey.Undo, self.undo, self.pdf.can_undo())
        self._entry(menu, "Rétablir", QKeySequence("Ctrl+Y"), self.redo, self.pdf.can_redo())
        menu.exec(global_pos)
        menu.deleteLater()  # one menu per right-click: do not let them pile up under the window

    @staticmethod
    def _entry(menu: QMenu, text: str, shortcut, slot, enabled: bool) -> QAction:
        action = menu.addAction(text, slot)
        action.setShortcut(QKeySequence(shortcut))  # shown as a hint; the window's own actions handle the keys
        action.setShortcutVisibleInContextMenu(True)
        action.setEnabled(enabled)
        return action

    def add_image_here(self, index: int, point: pymupdf.Point) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Insérer une image", "", self.image_filter)
        if path:
            self.place_image(index, point, path, max_width=self.pdf.page(index).rect.width / 3)

    # --- clipboard ---------------------------------------------------------

    def selected_target(self) -> ImageItem | None:
        return self.view.image_session.item if self.view.image_session else None

    def copy(self, target: TextBlock | ImageItem | None = None) -> None:
        target = target or self.selected_target()
        if target is None:
            return
        mime = QMimeData()
        mime.setData(MARKER, b"1")
        if isinstance(target, ImageItem):
            png = self.pdf.image_png(target)
            self.clip = ("image", png, target.width, target.height)
            mime.setImageData(QImage.fromData(png))
        else:
            self.clip = ("text", target.text, target.style)
            mime.setText(target.text)
        QApplication.clipboard().setMimeData(mime)
        self.statusBar().showMessage("Copié", 2000)

    def cut(self, target: TextBlock | ImageItem | None = None) -> None:
        target = target or self.selected_target()
        if target is not None:
            self.copy(target)
            self.delete(target)

    def delete(self, target: TextBlock | ImageItem | None) -> None:
        if target is None:
            return
        self.view.close_overlays(commit=False)
        if isinstance(target, ImageItem):
            self.pdf.delete_image(target)
        else:
            self.pdf.delete_block(target)
        self.after_change(target.page)

    def can_paste(self) -> bool:
        mime = QApplication.clipboard().mimeData()
        return bool(mime and (mime.hasImage() or mime.hasText()))

    def paste(self) -> None:
        """Ctrl+V: next to the selected image, else near the top-left of the visible part of the current page."""
        if self.pdf is None:
            return
        selected = self.selected_target()
        if selected:
            corner = selected.center - (selected.width / 2 - PASTE_OFFSET, selected.height / 2 - PASTE_OFFSET)
            self.paste_at(selected.page, corner)
            return
        index = self.view.current_page()
        widget = self.view.pages[index]
        visible_top = max(self.view.verticalScrollBar().value() - widget.y(), 0) / self.view.zoom
        self.paste_at(index, pymupdf.Point(72, visible_top + 72) * widget.page().derotation_matrix)

    def paste_at(self, index: int, point: pymupdf.Point) -> None:
        mime = QApplication.clipboard().mimeData()
        ours = mime.hasFormat(MARKER) and self.clip is not None
        if ours and self.clip[0] == "image":
            _, png, width, height = self.clip
            self.place_image_bytes(index, point, png, width, height)
        elif ours:
            _, text, style = self.clip
            self.view.new_text_at(index, point, text, style)
        elif mime.hasImage():
            image = QImage(mime.imageData())
            width = min(image.width() * 0.75, self.pdf.page(index).rect.width / 2)
            self.place_image_bytes(index, point, _png(image), width, width * image.height() / image.width())
        elif mime.hasText():
            self.view.new_text_at(index, point, mime.text())
