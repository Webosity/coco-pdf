"""Main window: menus, toolbar, file handling, search and printing."""
from __future__ import annotations

from pathlib import Path

import pymupdf
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QActionGroup, QImage, QKeySequence, QPainter
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QStyle,
    QToolBar,
    QToolButton,
    QWidget,
)

from . import __version__, asset
from .document import PdfDocument
from .editing import PDF_FILTER, EditingMixin
from .icons import icon
from .signatures import SignatureStore
from .thumbnails import ThumbnailList
from .viewer import PageView

MAX_RECENT = 10


class MainWindow(EditingMixin, QMainWindow):
    def __init__(self):
        super().__init__()
        self.pdf: PdfDocument | None = None
        self.settings = QSettings("Digital Rhapsody", "Coco PDF")
        self.signatures = SignatureStore()
        self.search_hits: list[tuple[int, pymupdf.Rect]] = []
        self.search_pos = -1

        self.view = PageView()
        self.thumbs = ThumbnailList()
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.thumbs)
        layout.addWidget(self.view, 1)
        self.setCentralWidget(central)
        self.page_label = QLabel()
        self.statusBar().addPermanentWidget(self.page_label)

        self.view.page_clicked.connect(self.on_page_clicked)
        self.view.text_edited.connect(self.on_text_edited)
        self.view.image_edited.connect(self.on_image_edited)
        self.view.current_page_changed.connect(self.on_current_page)
        self.thumbs.page_selected.connect(self.view.go_to_page)
        self.thumbs.order_changed.connect(self.reorder)

        self._build_actions()
        self.setAcceptDrops(True)
        self.resize(1200, 850)
        if geometry := self.settings.value("geometry"):
            self.restoreGeometry(geometry)
        self.update_state()

    # --- UI construction ---------------------------------------------------

    def _action(self, menu, text, slot, shortcut=None, icon=None, needs_doc=True) -> QAction:
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        if icon is not None:
            action.setIcon(self.style().standardIcon(icon))
        action.triggered.connect(slot)
        action.setProperty("needs_doc", needs_doc)
        menu.addAction(action)
        return action

    def _build_actions(self) -> None:
        sp = QStyle.StandardPixmap
        bar = self.menuBar()
        file_menu = bar.addMenu("&Fichier")
        self.act_open = self._action(file_menu, "&Ouvrir…", self.open_dialog, QKeySequence.StandardKey.Open,
                                     sp.SP_DialogOpenButton, needs_doc=False)
        self.recent_menu = file_menu.addMenu("Fichiers &récents")
        self.recent_menu.aboutToShow.connect(self._fill_recent)
        self.act_save = self._action(file_menu, "&Enregistrer", self.save, QKeySequence.StandardKey.Save,
                                     sp.SP_DialogSaveButton)
        self._action(file_menu, "Enregistrer &sous…", self.save_as, "Ctrl+Shift+S")
        self._action(file_menu, "Enregistrer une copie &compressée…", self.save_compressed)
        file_menu.addSeparator()
        self.act_print = self._action(file_menu, "&Imprimer…", self.print_document, QKeySequence.StandardKey.Print)
        file_menu.addSeparator()
        self._action(file_menu, "&Quitter", self.close, "Ctrl+Q", needs_doc=False)

        edit_menu = bar.addMenu("É&dition")
        self.act_undo = self._action(edit_menu, "&Annuler", self.undo, QKeySequence.StandardKey.Undo, sp.SP_ArrowBack)
        self.act_redo = self._action(edit_menu, "&Rétablir", self.redo, "Ctrl+Y", sp.SP_ArrowForward)
        edit_menu.addSeparator()
        self._action(edit_menu, "Rec&hercher…", self.focus_search, QKeySequence.StandardKey.Find)
        self._action(edit_menu, "Résultat suivant", lambda: self.next_hit(1), "F3")
        self._action(edit_menu, "Résultat précédent", lambda: self.next_hit(-1), "Shift+F3")

        view_menu = bar.addMenu("&Affichage")
        self._action(view_menu, "Zoom &avant", lambda: self.view.set_zoom(self.view.zoom * 1.2), "Ctrl++")
        self._action(view_menu, "Zoom a&rrière", lambda: self.view.set_zoom(self.view.zoom / 1.2), "Ctrl+-")
        self._action(view_menu, "Taille &réelle", lambda: self.view.set_zoom(1.0), "Ctrl+0")
        self._action(view_menu, "&Largeur de page", self.view.fit_width, "Ctrl+2")
        self._action(view_menu, "Aller à la &page…", self.goto_dialog, "Ctrl+G")

        page_menu = bar.addMenu("&Pages")
        self._action(page_menu, "Pivoter à &gauche", lambda: self.rotate(-90), "Ctrl+Shift+-")
        self._action(page_menu, "Pivoter à &droite", lambda: self.rotate(90), "Ctrl+Shift++")
        self._action(page_menu, "&Supprimer", self.delete_pages, "Del")
        page_menu.addSeparator()
        self._action(page_menu, "Insérer une page &blanche", self.insert_blank)
        self._action(page_menu, "Insérer un &PDF (fusionner)…", self.insert_pdf)
        page_menu.addSeparator()
        self._action(page_menu, "&Extraire les pages sélectionnées…", self.extract_pages)
        self._action(page_menu, "Dé&couper le document…", self.split)

        tools_menu = bar.addMenu("&Outils")
        self.mode_group = QActionGroup(self)
        # Optional: while a signature is being placed, no mode button is lit.
        self.mode_group.setExclusionPolicy(QActionGroup.ExclusionPolicy.ExclusiveOptional)
        self.mode_actions = []
        for mode, text, key in (("view", "&Lecture", "Ctrl+L"), ("edit", "&Modifier", "Ctrl+E"),
                                ("add_text", "&Ajouter du texte", "Ctrl+T"),
                                ("add_image", "Ajouter une &image", "Ctrl+Shift+I")):
            action = self._action(tools_menu, text, lambda _=False, m=mode: self.set_mode(m), key)
            action.setIcon(icon(mode))
            action.setCheckable(True)
            action.setChecked(mode == "view")
            self.mode_group.addAction(action)
            self.mode_actions.append(action)
        self.signature_menu = QMenu("&Signature", self)
        self.signature_menu.setIcon(icon("signature"))
        self.signature_menu.aboutToShow.connect(self.fill_signature_menu)
        tools_menu.addMenu(self.signature_menu)
        tools_menu.addSeparator()
        self._action(tools_menu, "Remplir le &formulaire…", self.fill_form)
        self._action(tools_menu, "Reconnaissance de texte (&OCR)…", self.run_ocr)

        help_menu = bar.addMenu("&?")
        self._action(help_menu, "À &propos", self.about, needs_doc=False)

        toolbar = QToolBar("Outils", movable=False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(toolbar)
        for action in (self.act_open, self.act_save, self.act_undo, self.act_redo):
            toolbar.addAction(action)
        toolbar.addSeparator()
        for action in self.mode_actions:
            toolbar.addAction(action)
        self.signature_button = QToolButton(text="Signature", icon=icon("signature"), toolTip="Insérer une signature")
        self.signature_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.signature_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.signature_button.setMenu(self.signature_menu)
        toolbar.addWidget(self.signature_button)
        toolbar.addSeparator()
        self.search_box = QLineEdit(placeholderText="Rechercher (Entrée)", clearButtonEnabled=True)
        self.search_box.setMaximumWidth(260)
        self.search_box.returnPressed.connect(self.search)
        toolbar.addWidget(self.search_box)

    # --- state -------------------------------------------------------------

    def update_state(self) -> None:
        has_doc = self.pdf is not None
        for action in self.findChildren(QAction):
            if action.property("needs_doc"):
                action.setEnabled(has_doc)
        self.search_box.setEnabled(has_doc)
        if has_doc:
            self.act_undo.setEnabled(self.pdf.can_undo())
            self.act_redo.setEnabled(self.pdf.can_redo())
        name = self.pdf.path.name if has_doc and self.pdf.path else "Sans titre" if has_doc else ""
        dirty = " *" if has_doc and self.pdf.modified else ""
        self.setWindowTitle(f"{name}{dirty} — Coco PDF" if has_doc else "Coco PDF")
        self.on_current_page(self.view.current_page())

    def on_current_page(self, index: int) -> None:
        self.page_label.setText(f"Page {index + 1} / {self.pdf.page_count}" if self.pdf else "")
        self.thumbs.select_page(index)

    def after_change(self, page_index: int) -> None:
        """Content of one page changed."""
        self.view.refresh_page(page_index)
        self.thumbs.refresh_page(page_index)
        self.update_state()

    def after_structure_change(self, go_to: int | None = None) -> None:
        """Pages added, removed, moved or rotated: rebuild everything."""
        current = self.view.current_page() if go_to is None else go_to
        self.view.rebuild()
        self.thumbs.rebuild()
        self.view.set_mode(self.view.mode)
        self.search_hits = []
        self.update_state()
        self.view.go_to_page(min(current, self.pdf.page_count - 1))

    def set_mode(self, mode: str) -> None:
        self.view.set_mode(mode)
        hints = {"edit": "Clique sur un paragraphe pour le modifier, ou sur une image pour la déplacer, "
                         "la redimensionner ou la faire pivoter (Maj : rotation par 15°, coin sans garder les "
                         "proportions)",
                 "add_text": "Clique où placer le texte",
                 "add_image": "Clique où placer le coin haut-gauche de l'image"}
        self.statusBar().showMessage(hints.get(mode, ""))

    def undo(self) -> None:
        self.pdf.undo()
        self.after_structure_change()

    def redo(self) -> None:
        self.pdf.redo()
        self.after_structure_change()

    # --- files -------------------------------------------------------------

    def open_dialog(self) -> None:
        start = self.settings.value("last_dir", str(Path.home() / "Documents"))
        path, _ = QFileDialog.getOpenFileName(self, "Ouvrir un PDF", start, PDF_FILTER)
        if path:
            self.open_file(path)

    def open_file(self, path: str) -> None:
        if not self.confirm_discard():
            return
        try:
            pdf = PdfDocument(path)
        except PermissionError:
            password, ok = QInputDialog.getText(self, "PDF protégé", "Mot de passe :", QLineEdit.EchoMode.Password)
            if not ok:
                return
            try:
                pdf = PdfDocument(path, password)
            except PermissionError as error:
                QMessageBox.warning(self, "Ouvrir", str(error))
                return
        except (RuntimeError, OSError, ValueError) as error:
            QMessageBox.warning(self, "Ouvrir", f"Impossible d'ouvrir ce fichier :\n{error}")
            return
        self.pdf = pdf
        self.view.set_document(pdf)
        self.thumbs.set_document(pdf)
        self.search_hits = []
        self.settings.setValue("last_dir", str(Path(path).parent))
        self._add_recent(str(Path(path).resolve()))
        self.update_state()

    def save(self) -> bool:
        if self.pdf.path is None:
            return self.save_as()
        return self._save_to(None)

    def save_as(self) -> bool:
        path, _ = QFileDialog.getSaveFileName(self, "Enregistrer sous", str(self.default_dir() / f"{self.stem()}.pdf"),
                                              PDF_FILTER)
        return self._save_to(path) if path else False

    def save_compressed(self) -> None:
        default = str(self.default_dir() / f"{self.stem()}_compressé.pdf")
        path, _ = QFileDialog.getSaveFileName(self, "Copie compressée", default, PDF_FILTER)
        if not path:
            return
        before = len(self.pdf.doc.tobytes())
        copy = PdfDocument()
        copy.doc.insert_pdf(self.pdf.doc)
        copy.save(path, compress=True)
        after = Path(path).stat().st_size
        self.statusBar().showMessage(f"Copie compressée : {before // 1024} Ko → {after // 1024} Ko", 8000)

    def _save_to(self, path: str | None) -> bool:
        try:
            self.pdf.save(path)
        except (RuntimeError, OSError, ValueError) as error:
            QMessageBox.warning(self, "Enregistrer", f"Échec de l'enregistrement :\n{error}")
            return False
        self._add_recent(str(self.pdf.path.resolve()))
        self.update_state()
        self.statusBar().showMessage(f"Enregistré : {self.pdf.path}", 5000)
        return True

    def confirm_discard(self) -> bool:
        if not self.pdf or not self.pdf.modified:
            return True
        answer = QMessageBox.question(
            self, "Modifications non enregistrées", "Enregistrer les modifications avant de continuer ?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Save:
            return self.save()
        return answer == QMessageBox.StandardButton.Discard

    def _recent(self) -> list[str]:
        value = self.settings.value("recent", [])
        return [value] if isinstance(value, str) else list(value or [])

    def _add_recent(self, path: str) -> None:
        recent = [path] + [p for p in self._recent() if p != path]
        self.settings.setValue("recent", recent[:MAX_RECENT])

    def _fill_recent(self) -> None:
        self.recent_menu.clear()
        for path in self._recent():
            if Path(path).exists():
                self.recent_menu.addAction(path, lambda p=path: self.open_file(p))
        if self.recent_menu.isEmpty():
            self.recent_menu.addAction("(aucun)").setEnabled(False)

    # --- search, navigation, print -----------------------------------------

    def focus_search(self) -> None:
        self.search_box.setFocus()
        self.search_box.selectAll()

    def search(self) -> None:
        needle = self.search_box.text().strip()
        hits = {i: self.pdf.search(i, needle) for i in range(self.pdf.page_count)}
        self.view.set_highlights(hits)
        self.search_hits = [(i, rect) for i, rects in hits.items() for rect in rects]
        self.search_pos = -1
        if needle:
            self.statusBar().showMessage(f"{len(self.search_hits)} résultat(s) pour « {needle} »", 5000)
            self.next_hit(1)

    def next_hit(self, step: int) -> None:
        if not self.search_hits:
            return
        self.search_pos = (self.search_pos + step) % len(self.search_hits)
        page, rect = self.search_hits[self.search_pos]
        self.view.go_to_page(page, rect)

    def goto_dialog(self) -> None:
        page, ok = QInputDialog.getInt(self, "Aller à la page", "Page :", self.view.current_page() + 1, 1,
                                       self.pdf.page_count)
        if ok:
            self.view.go_to_page(page - 1)

    def print_document(self) -> None:
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setFromTo(1, self.pdf.page_count)
        dialog = QPrintDialog(printer, self)
        if dialog.exec() != QPrintDialog.DialogCode.Accepted:
            return
        first, last = (printer.fromPage(), printer.toPage()) if printer.fromPage() else (1, self.pdf.page_count)
        painter = QPainter(printer)
        for number in range(first, last + 1):
            if number > first:
                printer.newPage()
            pix = self.pdf.page(number - 1).get_pixmap(dpi=300, alpha=False)
            image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
            target = painter.viewport()
            size = image.size().scaled(target.size(), Qt.AspectRatioMode.KeepAspectRatio)
            painter.drawImage(target.x(), target.y(), image.scaled(size, transformMode=Qt.TransformationMode.SmoothTransformation))
        painter.end()

    def about(self) -> None:
        logo = asset("logo.png").as_uri()
        QMessageBox.about(self, "Coco PDF", f'<p align="center"><img src="{logo}" width="160"></p>'
                                            f"<b>Coco PDF</b> {__version__}<br>Lecteur et éditeur PDF.<br>"
                                            f"Moteur PyMuPDF {pymupdf.VersionBind}.")

    # --- Qt events ---------------------------------------------------------

    def dragEnterEvent(self, event) -> None:
        if any(url.toLocalFile().lower().endswith(".pdf") for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.toLocalFile().lower().endswith(".pdf")]
        if paths:
            self.open_file(paths[0])

    def closeEvent(self, event) -> None:
        if self.confirm_discard():
            self.settings.setValue("geometry", self.saveGeometry())
            event.accept()
        else:
            event.ignore()
