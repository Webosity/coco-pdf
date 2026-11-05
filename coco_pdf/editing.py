"""Editing actions of the main window (pages, text, images, forms, OCR)."""
from __future__ import annotations

from pathlib import Path

import pymupdf
from PySide6.QtCore import Qt
from PySide6.QtGui import QImageReader
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox

from .dialogs import FormDialog, TextDialog
from .document import TextStyle, tesseract_available

PDF_FILTER = "Documents PDF (*.pdf)"
IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp)"


class EditingMixin:
    """Expects self.pdf, self.view, self.thumbs, self.after_change() and self.after_structure_change()."""

    last_style = TextStyle()

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

    # --- clicks on a page --------------------------------------------------

    def on_page_clicked(self, index: int, point: pymupdf.Point) -> None:
        handlers = {"edit_text": self.edit_text_at, "add_text": self.add_text_at, "add_image": self.add_image_at}
        if self.view.mode in handlers:
            handlers[self.view.mode](index, point)

    def edit_text_at(self, index: int, point: pymupdf.Point) -> None:
        span = self.pdf.span_at(index, point)
        if span is None:
            self.statusBar().showMessage("Aucun texte modifiable à cet endroit", 4000)
            return
        dialog = TextDialog(self, "Modifier le texte", span.text, span.style, multiline=False)
        if dialog.exec():
            self.pdf.replace_span(span, dialog.text(), dialog.style())
            self.after_change(index)

    def add_text_at(self, index: int, point: pymupdf.Point) -> None:
        dialog = TextDialog(self, "Ajouter du texte", "", self.last_style, multiline=True)
        if dialog.exec() and dialog.text().strip():
            EditingMixin.last_style = dialog.style()
            self.pdf.add_text(index, point, dialog.text(), dialog.style())
            self.after_change(index)

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
        rect = pymupdf.Rect(top_left, top_left + (width, height)) * page.derotation_matrix
        self.pdf.add_image(index, rect, path)
        self.after_change(index)

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
