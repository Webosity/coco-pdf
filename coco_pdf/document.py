"""PDF model: a PyMuPDF document kept in memory, with undo/redo and editing operations.

All coordinates are in unrotated PDF page space (the space used by get_text and insert_text).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pymupdf

MAX_UNDO = 30

# Base-14 font short names indexed by family, then (bold, italic).
BASE14 = {
    "helv": {(False, False): "helv", (True, False): "hebo", (False, True): "heit", (True, True): "hebi"},
    "tiro": {(False, False): "tiro", (True, False): "tibo", (False, True): "tiit", (True, True): "tibi"},
    "cour": {(False, False): "cour", (True, False): "cobo", (False, True): "coit", (True, True): "cobi"},
}


@dataclass
class TextStyle:
    family: str = "helv"
    size: float = 12.0
    bold: bool = False
    italic: bool = False
    color: tuple[float, float, float] = (0.0, 0.0, 0.0)

    @property
    def fontname(self) -> str:
        return BASE14[self.family][(self.bold, self.italic)]


@dataclass
class Span:
    page: int
    bbox: pymupdf.Rect
    origin: pymupdf.Point
    text: str
    style: TextStyle


@dataclass
class FormField:
    page: int
    xref: int
    label: str
    kind: int
    value: object
    choices: list[str]
    on_state: str


def style_from_span(span: dict) -> TextStyle:
    """Approximate the span's embedded font with a Base-14 font."""
    name = span["font"].lower()
    flags = span["flags"]
    if flags & pymupdf.TEXT_FONT_MONOSPACED or "courier" in name or "mono" in name:
        family = "cour"
    elif flags & pymupdf.TEXT_FONT_SERIFED or "times" in name:
        family = "tiro"
    else:
        family = "helv"
    rgb = span["color"]
    return TextStyle(
        family=family,
        size=round(span["size"], 1),
        bold=bool(flags & pymupdf.TEXT_FONT_BOLD) or "bold" in name,
        italic=bool(flags & pymupdf.TEXT_FONT_ITALIC) or "italic" in name or "oblique" in name,
        color=((rgb >> 16 & 255) / 255, (rgb >> 8 & 255) / 255, (rgb & 255) / 255),
    )


class PdfDocument:
    def __init__(self, path: str | Path | None = None, password: str | None = None):
        self.path = Path(path) if path else None
        # Loaded from bytes so Windows never locks the file and we can overwrite it on save.
        self.doc = pymupdf.open("pdf", self.path.read_bytes()) if self.path else pymupdf.open()
        if self.doc.needs_pass and not self.doc.authenticate(password or ""):
            raise PermissionError("Mot de passe incorrect")
        self._undo: list[bytes] = []
        self._redo: list[bytes] = []
        self._spans: dict[int, list[Span]] = {}
        self.modified = False

    @property
    def needs_password(self) -> bool:
        return self.doc.needs_pass and self.doc.is_encrypted

    @property
    def page_count(self) -> int:
        return self.doc.page_count

    def page(self, index: int) -> pymupdf.Page:
        return self.doc[index]

    # --- undo / redo -------------------------------------------------------

    def checkpoint(self) -> None:
        """Snapshot the document before a modification."""
        self._undo.append(self.doc.tobytes())
        del self._undo[:-MAX_UNDO]
        self._redo.clear()
        self._spans.clear()
        self.modified = True

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> None:
        self._redo.append(self.doc.tobytes())
        self._restore(self._undo.pop())

    def redo(self) -> None:
        self._undo.append(self.doc.tobytes())
        self._restore(self._redo.pop())

    def _restore(self, data: bytes) -> None:
        self.doc.close()
        self.doc = pymupdf.open("pdf", data)
        self._spans.clear()
        self.modified = True

    # --- saving ------------------------------------------------------------

    def save(self, path: str | Path | None = None, compress: bool = False) -> None:
        target = Path(path) if path else self.path
        if target is None:
            raise ValueError("Aucun chemin de sauvegarde")
        if compress:
            self.doc.rewrite_images(dpi_threshold=200, dpi_target=150, quality=75)
        data = self.doc.tobytes(garbage=4 if compress else 3, deflate=True, clean=compress,
                                deflate_images=compress, deflate_fonts=compress)
        target.write_bytes(data)
        self.path = target
        self.modified = False

    # --- pages -------------------------------------------------------------

    def rotate_pages(self, indices: list[int], angle: int) -> None:
        self.checkpoint()
        for i in indices:
            page = self.doc[i]
            page.set_rotation((page.rotation + angle) % 360)

    def delete_pages(self, indices: list[int]) -> None:
        if len(indices) >= self.page_count:
            raise ValueError("Impossible de supprimer toutes les pages")
        self.checkpoint()
        self.doc.delete_pages(sorted(indices))

    def reorder(self, order: list[int]) -> None:
        self.checkpoint()
        self.doc.select(order)

    def insert_blank_page(self, at: int) -> None:
        ref = self.doc[min(at, self.page_count - 1)].rect if self.page_count else pymupdf.paper_rect("a4")
        self.checkpoint()
        self.doc.new_page(at, width=ref.width, height=ref.height)

    def insert_pdf(self, path: str | Path, at: int) -> int:
        with pymupdf.open(path) as src:
            self.checkpoint()
            self.doc.insert_pdf(src, start_at=at)
            return src.page_count

    def extract_pages(self, indices: list[int], out_path: str | Path) -> None:
        with pymupdf.open() as out:
            for i in indices:
                out.insert_pdf(self.doc, from_page=i, to_page=i)
            out.save(out_path, garbage=3, deflate=True)

    def split(self, out_dir: str | Path, every: int = 1) -> list[Path]:
        out_dir = Path(out_dir)
        stem = self.path.stem if self.path else "document"
        files = []
        for start in range(0, self.page_count, every):
            end = min(start + every, self.page_count)
            target = out_dir / f"{stem}_p{start + 1}-{end}.pdf"
            self.extract_pages(list(range(start, end)), target)
            files.append(target)
        return files

    # --- text --------------------------------------------------------------

    def spans(self, page_index: int) -> list[Span]:
        if page_index not in self._spans:
            page = self.doc[page_index]
            self._spans[page_index] = [
                Span(page_index, pymupdf.Rect(s["bbox"]), pymupdf.Point(s["origin"]), s["text"], style_from_span(s))
                for block in page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)["blocks"]
                for line in block.get("lines", [])
                for s in line["spans"]
                if s["text"].strip()
            ]
        return self._spans[page_index]

    def span_at(self, page_index: int, point: pymupdf.Point) -> Span | None:
        return next((s for s in self.spans(page_index) if s.bbox.contains(point)), None)

    def replace_span(self, span: Span, new_text: str, style: TextStyle) -> None:
        self.checkpoint()
        page = self.doc[span.page]
        # Shrink the area so the characters of neighbouring spans and lines are not erased.
        h = span.bbox.height
        area = pymupdf.Rect(span.bbox.x0 + 0.5, span.bbox.y0 + h * 0.2, span.bbox.x1 - 0.5, span.bbox.y1 - h * 0.2)
        page.add_redact_annot(area, fill=False)
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE, graphics=pymupdf.PDF_REDACT_LINE_ART_NONE)
        if new_text:
            page.insert_text(span.origin, new_text, fontname=style.fontname, fontsize=style.size, color=style.color)

    def add_text(self, page_index: int, point: pymupdf.Point, text: str, style: TextStyle) -> None:
        self.checkpoint()
        page = self.doc[page_index]
        # point is the on-screen top-left of the first line; insert_text expects the baseline.
        top_left = point * page.rotation_matrix
        baseline = pymupdf.Point(top_left.x, top_left.y + style.size) * page.derotation_matrix
        page.insert_text(baseline, text, fontname=style.fontname, fontsize=style.size,
                         color=style.color, rotate=page.rotation)

    def add_image(self, page_index: int, rect: pymupdf.Rect, image_path: str | Path) -> None:
        self.checkpoint()
        page = self.doc[page_index]
        page.insert_image(rect, filename=str(image_path), keep_proportion=True, rotate=page.rotation)

    def search(self, page_index: int, needle: str) -> list[pymupdf.Rect]:
        return self.doc[page_index].search_for(needle) if needle else []

    # --- forms -------------------------------------------------------------

    def form_fields(self) -> list[FormField]:
        # Read everything while the page is alive: Widget.parent is only a weak reference.
        fields = []
        for page in self.doc:
            for w in page.widgets():
                is_button = w.field_type in (pymupdf.PDF_WIDGET_TYPE_CHECKBOX, pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON)
                choices = [c[1] if isinstance(c, (list, tuple)) else c for c in w.choice_values or []]
                fields.append(FormField(page.number, w.xref, w.field_label or w.field_name or "", w.field_type,
                                        w.field_value, choices, str(w.on_state()) if is_button else ""))
        return fields

    def set_field_values(self, values: dict[tuple[int, int], object]) -> None:
        """values maps (page number, widget xref) to the new value."""
        self.checkpoint()
        for page in self.doc:
            for widget in page.widgets():
                key = (page.number, widget.xref)
                if key not in values:
                    continue
                value = values[key]
                if widget.field_type in (pymupdf.PDF_WIDGET_TYPE_CHECKBOX, pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON):
                    value = widget.on_state() if value else "Off"
                widget.field_value = value
                widget.update()

    # --- OCR ---------------------------------------------------------------

    def ocr_pages(self, indices: list[int], language: str = "fra+eng") -> int:
        """Add an invisible, searchable text layer from Tesseract. Returns the number of words added."""
        self.checkpoint()
        added = 0
        for i in indices:
            page = self.doc[i]
            textpage = page.get_textpage_ocr(language=language, dpi=300, full=True)
            for x0, y0, x1, y1, word, *_ in page.get_text("words", textpage=textpage):
                width = pymupdf.get_text_length(word, "helv", 1)
                size = min(y1 - y0, (x1 - x0) / width) if width else y1 - y0
                page.insert_text((x0, y1 - (y1 - y0) * 0.2), word, fontname="helv", fontsize=size, render_mode=3)
                added += 1
        return added


def tesseract_available() -> bool:
    try:
        pymupdf.get_tessdata()
        return True
    except RuntimeError:
        return False
