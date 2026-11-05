"""Form filling dialog."""
from __future__ import annotations

import pymupdf
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .document import FormField


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
