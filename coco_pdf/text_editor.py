"""In-place text editing: a text box laid over the paragraph, with a floating style toolbar above it."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QTextBlockFormat, QTextCursor
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QTextEdit,
    QToolButton,
    QWidget,
)

from . import fonts
from .pdf_text import TextStyle

ALIGNMENTS = [("Gauche", Qt.AlignmentFlag.AlignLeft), ("Centré", Qt.AlignmentFlag.AlignHCenter),
              ("Droite", Qt.AlignmentFlag.AlignRight), ("Justifié", Qt.AlignmentFlag.AlignJustify)]
TOOLBAR_STYLE = """
QFrame#textToolbar { background: palette(window); border: 1px solid palette(mid); border-radius: 6px; }
QToolButton { min-width: 26px; min-height: 24px; }
"""


def _tool_button(text: str, tip: str, checkable: bool = False) -> QToolButton:
    button = QToolButton(text=text, toolTip=tip, checkable=checkable)
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return button


class InlineTextEditor(QObject):
    """Lives on a page widget; emits committed(text, style) or cancelled()."""

    committed = Signal(str, object)
    cancelled = Signal()

    def __init__(self, page_widget: QWidget, rect: QRectF, text: str, style: TextStyle, zoom: float):
        super().__init__(page_widget)
        self.page_widget = page_widget
        self.zoom = zoom
        self.original = (text, style)
        self.style = style
        self.min_height = max(rect.height(), style.size * style.lineheight * zoom)
        self.closed = False

        self.editor = QTextEdit(page_widget)
        self.editor.setAcceptRichText(False)
        self.editor.setFrameShape(QFrame.Shape.NoFrame)
        self.editor.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.editor.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.editor.document().setDocumentMargin(0)
        self.editor.setGeometry(int(rect.x()), int(rect.y()), max(int(rect.width()), 60), int(self.min_height))
        self.editor.setPlainText(text)
        self.editor.installEventFilter(self)

        self.toolbar = self._build_toolbar()
        self._apply_style()
        self.editor.document().contentsChanged.connect(self._fit_height)
        self.editor.show()
        self.toolbar.show()
        self.editor.setFocus()
        self.editor.moveCursor(QTextCursor.MoveOperation.End)

    # --- toolbar -----------------------------------------------------------

    def _build_toolbar(self) -> QFrame:
        bar = QFrame(self.page_widget, objectName="textToolbar")
        bar.setStyleSheet(TOOLBAR_STYLE)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)

        self.family = QComboBox(toolTip="Police")
        self.family.setMaxVisibleItems(20)
        families = fonts.available_families(self.style.family)
        self.family.addItems(families)
        self.family.insertSeparator(len(families))
        self.family.addItems([f for f in fonts.all_families() if f not in families])
        self.family.setCurrentText(self.style.family)
        self.family.currentTextChanged.connect(lambda v: self._update(family=v))

        self.size = QDoubleSpinBox(minimum=4, maximum=300, value=self.style.size, singleStep=0.5, decimals=1,
                                   toolTip="Taille (pt)")
        self.size.valueChanged.connect(lambda v: self._update(size=v))
        self.bold = _tool_button("G", "Gras (Ctrl+B)", checkable=True)
        self.bold.setChecked(self.style.bold)
        self.bold.setStyleSheet("font-weight: bold;")
        self.bold.toggled.connect(lambda v: self._update(bold=v))
        self.italic = _tool_button("I", "Italique (Ctrl+I)", checkable=True)
        self.italic.setChecked(self.style.italic)
        self.italic.setStyleSheet("font-style: italic;")
        self.italic.toggled.connect(lambda v: self._update(italic=v))
        self.color = _tool_button("A", "Couleur du texte")
        self.color.clicked.connect(self._pick_color)
        self.align = QComboBox(toolTip="Alignement")
        self.align.addItems([label for label, _ in ALIGNMENTS])
        self.align.setCurrentIndex(self.style.align)
        self.align.currentIndexChanged.connect(lambda v: self._update(align=v))
        self.warning = QLabel(toolTip="Cette police n'est pas installée sur ce PC : une police standard proche "
                                      "sera utilisée. Installe-la pour conserver le rendu exact.")
        self.warning.setStyleSheet("color: #c77700;")
        ok = _tool_button("✓", "Valider (Ctrl+Entrée)")
        ok.setStyleSheet("color: #1a8f3c; font-weight: bold;")
        ok.clicked.connect(self.commit)
        cancel = _tool_button("✕", "Annuler (Échap)")
        cancel.clicked.connect(self.cancel)

        for widget in (self.family, self.size, self.bold, self.italic, self.color, self.align, self.warning,
                       ok, cancel):
            layout.addWidget(widget)
        for widget in (self.family, self.size, self.align):
            widget.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        return bar

    def _update(self, **changes) -> None:
        self.style = self.style.with_(**changes)
        self._apply_style()
        self.editor.setFocus()

    def _pick_color(self) -> None:
        color = QColorDialog.getColor(QColor.fromRgbF(*self.style.color), self.page_widget, "Couleur du texte")
        if color.isValid():
            self._update(color=(color.redF(), color.greenF(), color.blueF()))

    # --- preview -----------------------------------------------------------

    def _apply_style(self) -> None:
        style, zoom = self.style, self.zoom
        font = QFont(fonts.preview_family(style.family))
        font.setPixelSize(max(1, round(style.size * zoom)))
        font.setBold(style.bold)
        font.setItalic(style.italic)
        self.editor.setFont(font)
        self.editor.document().setDefaultFont(font)
        color = QColor.fromRgbF(*style.color).name()
        self.editor.setStyleSheet(f"QTextEdit {{ background: white; color: {color}; }}")
        self.color.setStyleSheet(f"color: {color}; font-weight: bold; border-bottom: 3px solid {color};")
        exact = fonts.resolve(style.family, style.bold, style.italic).exact
        self.warning.setText("" if exact else "⚠ non installée")
        self.warning.setVisible(not exact)

        block_format = QTextBlockFormat()
        block_format.setAlignment(ALIGNMENTS[style.align][1])
        block_format.setLineHeight(style.size * style.lineheight * zoom,
                                   QTextBlockFormat.LineHeightTypes.FixedHeight.value)
        cursor = QTextCursor(self.editor.document())
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.mergeBlockFormat(block_format)
        self.toolbar.adjustSize()
        self._fit_height()

    def _fit_height(self) -> None:
        height = max(self.min_height, self.editor.document().size().height() + 4)
        self.editor.resize(self.editor.width(), int(height))
        self._place_toolbar()

    def _place_toolbar(self) -> None:
        bar, box = self.toolbar, self.editor.geometry()
        y = box.top() - bar.height() - 6
        if y < 0:
            y = box.bottom() + 6
        x = min(max(box.left(), 0), max(self.page_widget.width() - bar.width(), 0))
        bar.move(x, y)
        bar.raise_()

    # --- closing -----------------------------------------------------------

    def text(self) -> str:
        return self.editor.toPlainText()

    def commit(self) -> None:
        if self.closed:
            return
        self._close()
        if (self.text(), self.style) == self.original:
            self.cancelled.emit()
        else:
            self.committed.emit(self.text(), self.style)

    def cancel(self) -> None:
        if not self.closed:
            self._close()
            self.cancelled.emit()

    def _close(self) -> None:
        self.closed = True
        self.editor.hide()
        self.toolbar.hide()
        self.editor.deleteLater()
        self.toolbar.deleteLater()

    def eventFilter(self, obj, event) -> bool:
        if obj is self.editor and event.type() == QEvent.Type.ShortcutOverride and (
                event.key() == Qt.Key.Key_Escape or event.matches(QKeySequence.StandardKey.Bold)
                or event.matches(QKeySequence.StandardKey.Italic)):
            # These keys belong to the editor, not to the window's menu shortcuts (Ctrl+I, Esc...).
            event.accept()
            return True
        if obj is self.editor and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self.cancel()
                return True
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self.commit()
                return True
            if event.matches(QKeySequence.StandardKey.Bold):
                self.bold.toggle()
                return True
            if event.matches(QKeySequence.StandardKey.Italic):
                self.italic.toggle()
                return True
        return False
