"""'Make the text editable' in the window: banner on scanned documents, background work, result file."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMessageBox, QProgressDialog, QPushButton, QToolButton

from . import ocr


class OcrWorker(QThread):
    progressed = Signal(int, int)
    done = Signal(bytes, int)
    failed = Signal(str)

    def __init__(self, data: bytes, pages: list[int]):
        super().__init__()
        self.data, self.pages = data, pages

    def run(self) -> None:
        # A copy of the document, opened in this thread: PyMuPDF objects must not cross threads.
        try:
            def report(done: int, total: int) -> bool:
                self.progressed.emit(done, total)
                return not self.isInterruptionRequested()
            result, words = ocr.rebuild(self.data, self.pages, report)
        except (RuntimeError, ValueError, OSError) as error:
            self.failed.emit(str(error))
            return
        if not self.isInterruptionRequested():
            self.done.emit(result, words)


class ScanBanner(QFrame):
    def __init__(self, on_click):
        super().__init__()
        # Fixed colours (not the palette): the banner must read the same on every PC.
        self.setStyleSheet(
            "ScanBanner { background: #fff4d6; border-bottom: 1px solid #e3c770; }"
            "QLabel { color: #3d2e00; font-size: 10pt; }"
            "QPushButton { background: #b45309; color: white; font-weight: bold; font-size: 10pt;"
            " border: none; border-radius: 5px; padding: 6px 16px; }"
            "QPushButton:hover { background: #92400e; }"
            "QPushButton:pressed { background: #78350f; }"
            "QToolButton { color: #3d2e00; border: none; padding: 4px; }")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 8, 8)
        self.label = QLabel()
        self.label.setWordWrap(True)
        button = QPushButton("Rendre le texte modifiable")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(on_click)
        close = QToolButton(text="✕", toolTip="Masquer")
        close.clicked.connect(self.hide)
        layout.addWidget(self.label, 1)
        layout.addWidget(button)
        layout.addWidget(close)
        self.hide()


def result_path(source: Path | None) -> Path:
    folder = source.parent if source else Path.home() / "Documents"
    stem = source.stem if source else "document"
    target = folder / f"{stem} (modifiable).pdf"
    n = 2
    while target.exists():
        target = folder / f"{stem} (modifiable {n}).pdf"
        n += 1
    return target


class OcrMixin:
    """Expects self.pdf, self.view, self.banner, self.open_file() and EditingMixin.target_pages()."""

    worker: OcrWorker | None = None

    def check_scanned(self) -> None:
        pages = ocr.scanned_pages(self.pdf.doc) if self.pdf else []
        if pages:
            count = "Ce document est une image scannée" if len(pages) == self.pdf.page_count else \
                f"{len(pages)} page(s) de ce document sont des images scannées"
            self.banner.label.setText(f"{count} : son texte ne peut pas encore être modifié.")
            self.banner.show()
        else:
            self.banner.hide()

    def make_editable(self) -> None:
        if self.pdf is None or self.worker is not None:
            return
        pages = ocr.scanned_pages(self.pdf.doc)
        if not pages:
            # No scan: repair the current (or selected) pages, e.g. text that shows fine but reads as gibberish.
            pages = self.target_pages()
            answer = QMessageBox.question(
                self, "Rendre le texte modifiable",
                f"Relire {len(pages)} page(s) et remplacer leur texte par le texte reconnu ?\n\n"
                "Utile quand le texte s'affiche bien mais devient incompréhensible une fois modifié ou copié. "
                "Une copie est créée, l'original n'est pas modifié.")
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.view.close_overlays()
        progress = QProgressDialog("Lecture du texte de la page…", "Annuler", 0, len(pages), self)
        progress.setWindowTitle("Rendre le texte modifiable")
        progress.setMinimumDuration(0)
        progress.setValue(0)
        worker = OcrWorker(self.pdf.doc.tobytes(), pages)
        worker.progressed.connect(lambda done, total: (progress.setValue(done),
                                                       progress.setLabelText(f"Lecture du texte : page {min(done + 1, total)} sur {total}…")))
        worker.done.connect(lambda data, words: self._ocr_done(data, words, progress))
        worker.failed.connect(lambda message: self._ocr_failed(message, progress))
        progress.canceled.connect(worker.requestInterruption)
        worker.finished.connect(self._ocr_finished)
        self.worker = worker
        worker.start()

    def _ocr_finished(self) -> None:
        self.worker.deleteLater()
        self.worker = None

    def _ocr_failed(self, message: str, progress: QProgressDialog) -> None:
        progress.close()
        QMessageBox.warning(self, "Rendre le texte modifiable", f"La lecture du texte a échoué :\n{message}")

    def _ocr_done(self, data: bytes, words: int, progress: QProgressDialog) -> None:
        progress.close()
        if not words:
            QMessageBox.information(self, "Rendre le texte modifiable", "Aucun texte n'a été reconnu.")
            return
        target = result_path(self.pdf.path)
        try:
            target.write_bytes(data)
        except OSError as error:
            QMessageBox.warning(self, "Rendre le texte modifiable", f"Enregistrement impossible :\n{error}")
            return
        self.open_file(str(target))
        self.banner.hide()
        QMessageBox.information(
            self, "Texte modifiable",
            f"C'est fait : {words} mots reconnus.\n\nLe nouveau document est enregistré ici :\n{target}\n\n"
            "Relisez-le : la lecture automatique peut se tromper, surtout sur les noms et les chiffres. "
            "Pour corriger un mot, cliquez sur « Modifier » puis sur le paragraphe.")
