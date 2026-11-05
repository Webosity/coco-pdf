"""Editing actions of the main window (pages, text, images, forms, OCR)."""
from __future__ import annotations

from pathlib import Path

import pymupdf
from PySide6.QtCore import Qt
from PySide6.QtGui import QImageReader
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox

from .dialogs import FormDialog
from .document import tesseract_available
from .pdf_images import ImageItem
from .pdf_text import TextStyle

PDF_FILTER = "Documents PDF (*.pdf)"
IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp)"


class EditingMixin:
    """Expects self.pdf, self.view, self.thumbs, self.mode_actions, self.after_change()
    and self.after_structure_change()."""

    # --- pages -------------------------------------------------------------

    def target_pages(self) -> list[int]:
        return self.thumbs.selected_pages() or [self.view.current_page()]

    def rotate(self, angle: int) -> None:
        self.pdf.rotate_pages(self.target_pages(), angle)
        self.after_structure_change()

    def delete_pages(self) -> None:
        pages = self.target_pages()
        answer = QMessageBox.question(self, "Supprimer", f"Supprimer {len(pages)} page(s) ?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.pdf.delete_pages(pages)
        except ValueError as error:
            QMessageBox.warning(self, "Supprimer", str(error))
            return
        self.after_structure_change()

    def reorder(self, order: list[int]) -> None:
        self.pdf.reorder(order)
        self.after_structure_change()

    def insert_blank(self) -> None:
        self.pdf.insert_blank_page(self.view.current_page() + 1)
        self.after_structure_change(self.view.current_page() + 1)

    def insert_pdf(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Insérer des PDF après la page courante", "", PDF_FILTER)
        at = self.view.current_page() + 1
        for path in paths:
            at += self.pdf.insert_pdf(path, at)
        if paths:
            self.after_structure_change()

    def extract_pages(self) -> None:
        pages = self.target_pages()
        default = str(self.default_dir() / f"{self.stem()}_extrait.pdf")
        path, _ = QFileDialog.getSaveFileName(self, f"Extraire {len(pages)} page(s)", default, PDF_FILTER)
        if path:
            self.pdf.extract_pages(pages, path)
            self.statusBar().showMessage(f"{len(pages)} page(s) extraite(s) vers {path}", 6000)

    def split(self) -> None:
        every, ok = QInputDialog.getInt(self, "Découper", "Nombre de pages par fichier :", 1, 1, self.pdf.page_count)
        if not ok:
            return
        folder = QFileDialog.getExistingDirectory(self, "Dossier de destination", str(self.default_dir()))
        if folder:
            files = self.pdf.split(folder, every)
            self.statusBar().showMessage(f"{len(files)} fichier(s) créé(s) dans {folder}", 6000)

    # --- in-place text and image edits (signals from the page view) ------

    def on_text_edited(self, index: int, block, screen_rect: pymupdf.Rect, text: str, style: TextStyle) -> None:
        try:
            if block is None:
                if not text.strip():
                    return
                self.view.new_text_style = style
                self.pdf.add_text_box(index, screen_rect, text, style)
            else:
                self.pdf.replace_block(block, text, style)
        except (RuntimeError, ValueError) as error:
            QMessageBox.warning(self, "Texte", f"Modification impossible : {error}")
            return
        self.after_change(index)

    def on_image_edited(self, item: ImageItem, new: ImageItem | None) -> None:
        try:
            if new is None:
                self.pdf.delete_image(item)
                current = None
            else:
                current = self.pdf.move_image(item, new)
        except (RuntimeError, ValueError) as error:
            QMessageBox.warning(self, "Image", f"Modification impossible : {error}")
            return
        self.after_change(item.page)
        if current is not None:
            self.view.select_image(current)  # keep it selected for the next adjustment

    def on_page_clicked(self, index: int, point: pymupdf.Point) -> None:
        if self.view.mode == "add_image":
            self.add_image_at(index, point)

    def add_image_at(self, index: int, point: pymupdf.Point) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Insérer une image", "", IMAGE_FILTER)
        if not path:
            return
        size = QImageReader(path).size()
        if not size.isValid():
            QMessageBox.warning(self, "Image", "Image illisible.")
            return
        page = self.pdf.page(index)
        width = min(size.width() * 0.75, page.rect.width / 3)  # 96 dpi pixels -> points, capped
        height = width * size.height() / size.width()
        top_left = point * page.rotation_matrix  # screen (rotated) space
        item = self.pdf.add_image(index, pymupdf.Rect(top_left, top_left + (width, height)), path)
        self.after_change(index)
        # Switch to edit mode with the new image selected, ready to be moved or resized.
        self.mode_actions[1].trigger()
        if item is not None:
            self.view.select_image(item)

    # --- forms and OCR -----------------------------------------------------

    def fill_form(self) -> None:
        fields = self.pdf.form_fields()
        if not fields:
            QMessageBox.information(self, "Formulaire", "Ce document ne contient aucun champ de formulaire.")
            return
        dialog = FormDialog(self, fields)
        if dialog.exec():
            self.pdf.set_field_values(dialog.values())
            self.after_structure_change()

    def run_ocr(self) -> None:
        if not tesseract_available():
            QMessageBox.information(
                self, "OCR",
                "La reconnaissance de texte nécessite Tesseract OCR.\n\n"
                "Installe-le (par exemple « winget install UB-Mannheim.TesseractOCR » avec la langue "
                "française), puis relance Coco PDF.")
            return
        pages = self.target_pages()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            words = self.pdf.ocr_pages(pages)
        except (RuntimeError, OSError, ValueError) as error:
            QMessageBox.warning(self, "OCR", f"Échec de l'OCR : {error}")
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.after_structure_change()
        self.statusBar().showMessage(f"OCR : {words} mots reconnus sur {len(pages)} page(s)", 6000)

    # --- helpers -----------------------------------------------------------

    def default_dir(self) -> Path:
        return self.pdf.path.parent if self.pdf and self.pdf.path else Path.home() / "Documents"

    def stem(self) -> str:
        return self.pdf.path.stem if self.pdf and self.pdf.path else "document"
