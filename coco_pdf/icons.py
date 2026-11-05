"""Toolbar icons: 24 px line drawings, tinted with the current palette so they work in light and dark themes."""
from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

ACCENT = "#e5484d"  # red of the Coco PDF logo

SHAPES = {
    "view": '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    "edit": '<path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16v4z"/><path d="M13.5 6.5l4 4"/>',
    "add_text": '<path d="M4 7V5h12v2"/><path d="M10 5v14"/><path d="M7.5 19h5"/>'
                '<path d="M19 13v8M15 17h8" stroke="{accent}"/>',
    "add_image": '<rect x="3" y="4" width="15" height="14" rx="2"/><circle cx="8.5" cy="9" r="1.6"/>'
                 '<path d="M3 16l4.5-4.5 3.5 3.5 2-2 5 5"/><path d="M20 13v8M16 17h8" stroke="{accent}"/>',
    "signature": '<path d="M3 17c2.5-3 4-9 6.5-9 2 0-.5 8 1.5 8 1.5 0 2.5-3.5 4-3.5 1.2 0 1 2.5 2.5 2.5 1 0 2-1 '
                 '3-1.5"/><path d="M3 21h18" stroke="{accent}"/>',
}


def icon(name: str) -> QIcon:
    color = QApplication.palette().color(QPalette.ColorRole.WindowText).name()
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
           f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
           f'{SHAPES[name].format(accent=ACCENT)}</svg>')
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    result = QIcon()
    for size in (16, 24, 32, 48):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter, QRectF(0, 0, size, size))
        painter.end()
        result.addPixmap(pixmap)
    return result
