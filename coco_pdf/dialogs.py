"""Dialogs: text editing/insertion and form filling."""
from __future__ import annotations

import pymupdf
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .document import FormField, TextStyle

FAMILIES = {"helv": "Sans serif (Helvetica)", "tiro": "Serif (Times)", "cour": "Chasse fixe (Courier)"}


class TextDialog(QDialog):
    """Edit a text and its style. Used both to replace an existing span and to add new text."""

    def __init__(self, parent, title: str, text: str, style: TextStyle, multiline: bool):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(460)
        self.color = style.color

        self.text_edit = QPlainTextEdit(text) if multiline else QLineEdit(text)
        if multiline:
            self.text_edit.setMinimumHeight(110)
        self.family = QComboBox()
        for key, label in FAMILIES.items():
            self.family.addItem(label, key)
        self.family.setCurrentIndex(list(FAMILIES).index(style.family))
        self.size = QDoubleSpinBox(minimum=4, maximum=200, value=style.size, singleStep=0.5)
        self.bold = QCheckBox("Gras", checked=style.bold)
        self.italic = QCheckBox("Italique", checked=style.italic)
        self.color_button = QPushButton()
        self.color_button.clicked.connect(self._pick_color)
        self._paint_color_button()

        style_row = QHBoxLayout()
        for widget in (self.size, self.bold, self.italic, self.color_button):
            style_row.addWidget(widget)

        form = QFormLayout()
        form.addRow("Texte", self.text_edit)
        form.addRow("Police", self.family)
        form.addRow("Taille / style", style_row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        note = QLabel("La police d'origine est remplacée par la police standard la plus proche.")
        note.setStyleSheet("color: gray;")
        layout.addWidget(note)
        layout.addWidget(buttons)
        self.text_edit.setFocus()

    def _pick_color(self) -> None:
        color = QColorDialog.getColor(QColor.fromRgbF(*self.color), self, "Couleur du texte")
        if color.isValid():
            self.color = (color.redF(), color.greenF(), color.blueF())
            self._paint_color_button()

    def _paint_color_button(self) -> None:
        self.color_button.setText("Couleur")
        self.color_button.setStyleSheet(f"border-left: 14px solid {QColor.fromRgbF(*self.color).name()};")

    def text(self) -> str:
        widget = self.text_edit
        return widget.toPlainText() if isinstance(widget, QPlainTextEdit) else widget.text()

    def style(self) -> TextStyle:
        return TextStyle(self.family.currentData(), self.size.value(), self.bold.isChecked(),
                         self.italic.isChecked(), self.color)


class FormDialog(QDialog):
    """List every form field of the document with an editor matching its type."""

    def __init__(self, parent, fields: list[FormField]):
        super().__init__(parent)
        self.setWindowTitle("Remplir le formulaire")
        self.resize(560, 520)
        self.editors: dict[tuple[int, int], QWidget] = {}

        form = QFormLayout()
        for field in fields:
            editor = self._editor_for(field)
            if editor is None:
                continue
            self.editors[(field.page, field.xref)] = editor
            form.addRow(f"p.{field.page + 1} — {field.label or '(sans nom)'}", editor)

        inner = QWidget()
        inner.setLayout(form)
        scroll = QScrollArea(widgetResizable=True)
        scroll.setWidget(inner)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(scroll)
        layout.addWidget(buttons)

    @staticmethod
    def _editor_for(field: FormField) -> QWidget | None:
        kind = field.kind
        if kind in (pymupdf.PDF_WIDGET_TYPE_CHECKBOX, pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON):
            return QCheckBox(field.on_state, checked=field.value not in (None, "", "Off", False))
        if kind in (pymupdf.PDF_WIDGET_TYPE_COMBOBOX, pymupdf.PDF_WIDGET_TYPE_LISTBOX):
            combo = QComboBox(editable=kind == pymupdf.PDF_WIDGET_TYPE_COMBOBOX)
            combo.addItems(field.choices)
            combo.setCurrentText(str(field.value or ""))
            return combo
        if kind == pymupdf.PDF_WIDGET_TYPE_TEXT:
            return QLineEdit(str(field.value or ""))
        return None

    def values(self) -> dict[tuple[int, int], object]:
        result = {}
        for key, editor in self.editors.items():
            if isinstance(editor, QCheckBox):
                result[key] = editor.isChecked()
            elif isinstance(editor, QComboBox):
                result[key] = editor.currentText()
            else:
                result[key] = editor.text()
        return result
