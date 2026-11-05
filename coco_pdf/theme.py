"""One fixed look on every PC.

Left alone, Qt follows Windows: light or dark mode, the user's accent colour, and a native style that
differs between Windows 10 and 11, so the same window looked different from one PC to another (white
text on white inputs in some setups). Fusion plus a complete palette removes all of that.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QFrame, QWidget

ACCENT = "#2563eb"
ROLES = {
    QPalette.ColorRole.Window: "#f3f3f3",
    QPalette.ColorRole.WindowText: "#1f1f1f",
    QPalette.ColorRole.Base: "#ffffff",
    QPalette.ColorRole.AlternateBase: "#f5f5f5",
    QPalette.ColorRole.Text: "#1f1f1f",
    QPalette.ColorRole.PlaceholderText: "#7a7a7a",
    QPalette.ColorRole.Button: "#e9e9e9",
    QPalette.ColorRole.ButtonText: "#1f1f1f",
    QPalette.ColorRole.BrightText: "#ffffff",
    QPalette.ColorRole.Highlight: ACCENT,
    QPalette.ColorRole.HighlightedText: "#ffffff",
    QPalette.ColorRole.ToolTipBase: "#fffbe6",
    QPalette.ColorRole.ToolTipText: "#1f1f1f",
    QPalette.ColorRole.Link: ACCENT,
    QPalette.ColorRole.LinkVisited: "#7c3aed",
    QPalette.ColorRole.Light: "#ffffff",
    QPalette.ColorRole.Midlight: "#e3e3e3",
    QPalette.ColorRole.Mid: "#b8b8b8",
    QPalette.ColorRole.Dark: "#8c8c8c",
    QPalette.ColorRole.Shadow: "#5c5c5c",
}
DISABLED = {
    QPalette.ColorRole.WindowText: "#9a9a9a",
    QPalette.ColorRole.Text: "#9a9a9a",
    QPalette.ColorRole.ButtonText: "#9a9a9a",
    QPalette.ColorRole.Highlight: "#a8a8a8",
}


def floating_panel(frame: QFrame) -> None:
    """Toolbars laid over the page. Deliberately no style sheet: a style sheet on a container makes Qt
    draw its combo and spin boxes with its own fallback colours (dark grey here), which is what made
    them look different from one PC to another."""
    palette = frame.palette()  # its own: the page backdrop's grey would be inherited otherwise
    palette.setColor(QPalette.ColorRole.Window, QColor(ROLES[QPalette.ColorRole.Window]))
    frame.setPalette(palette)
    frame.setAutoFillBackground(True)
    frame.setFrameShape(QFrame.Shape.StyledPanel)


def set_text_color(widget: QWidget, color: str) -> None:
    palette = widget.palette()
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        palette.setColor(role, QColor(color))
    widget.setPalette(palette)


def apply(app: QApplication) -> None:
    app.styleHints().setColorScheme(Qt.ColorScheme.Light)  # ignore Windows dark mode
    app.setStyle("Fusion")  # same widgets on Windows 10 and 11
    palette = QPalette()
    for role, color in ROLES.items():
        palette.setColor(role, QColor(color))  # every colour group: active, inactive, disabled
    for role, color in DISABLED.items():
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(color))
    app.setPalette(palette)
