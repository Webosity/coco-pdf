"""About window: Coco's animation, the publisher and the story of the software."""
from __future__ import annotations

import pymupdf
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QMovie, QPixmap
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QVBoxLayout

from . import __version__, asset

PUBLISHER = "SARL Digital Rhapsody, 31700 Blagnac, France"
STORY = ("Coco, c'est ma maman, et à force de la voir galérer avec ses différents pdfs, j'ai décidé qu'il était "
         "temps que je lui crée un logiciel pour elle, pour son utilisation, puis aussi pour mon utilisation des "
         "pdfs... et finalement Coco PDF a vu le jour. Merci Maman :)")
ANIMATION_SIZE = QSize(212, 205)  # half of the 425 x 411 pixel art: an exact ratio keeps the pixels crisp


class AboutDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("À propos de Coco PDF")
        self.setStyleSheet("QDialog { background: white; } QLabel { color: #1f1f1f; }")

        animation = QLabel()
        self.movie = QMovie(str(asset("coco-animation.gif")))
        self.movie.setScaledSize(ANIMATION_SIZE)
        animation.setMovie(self.movie)
        animation.setFixedSize(ANIMATION_SIZE)
        self.movie.start()

        logo = QLabel()
        logo.setPixmap(QPixmap(str(asset("logo.png"))).scaledToWidth(150, Qt.TransformationMode.SmoothTransformation))
        version = QLabel(f"<b>Version {__version__}</b><br>Lecteur et éditeur PDF")
        publisher = QLabel(f"<b>Éditeur :</b> {PUBLISHER}")
        story = QLabel(f"« {STORY} »")
        story.setWordWrap(True)
        story.setStyleSheet("font-style: italic; color: #5a4300; background: #fff8e6; border-left: 3px solid #e3c770;"
                            " padding: 10px;")
        engine = QLabel(f"Moteur PDF : PyMuPDF {pymupdf.VersionBind} (licence AGPL)")
        engine.setStyleSheet("color: #7a7a7a; font-size: 8pt;")

        text = QVBoxLayout()
        for widget in (logo, version, publisher, story, engine):
            text.addWidget(widget)
        text.addStretch()
        row = QHBoxLayout()
        row.addWidget(animation, alignment=Qt.AlignmentFlag.AlignTop)
        row.addSpacing(12)
        row.addLayout(text, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 14)
        layout.addLayout(row)
        layout.addWidget(buttons)
        self.setFixedWidth(620)
