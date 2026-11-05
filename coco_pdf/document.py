"""PDF model: a PyMuPDF document kept in memory, with undo/redo and editing operations.

Coordinates are in unrotated PDF page space (the space of get_text / insert_text) unless named "screen".
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pymupdf

from . import pdf_images, pdf_text
from .pdf_images import ImageItem
from .pdf_text import TextBlock, TextStyle

MAX_UNDO = 30


@dataclass
class FormField:
    page: int
    xref: int
    label: str
    kind: int
    value: object
    choices: list[str]
    on_state: str


class PdfDocument:
    def __init__(self, path: str | Path | None = None, password: str | None = None):
        self.path = Path(path) if path else None
        # Loaded from bytes so Windows never locks the file and we can overwrite it on save.
        self.doc = pymupdf.open("pdf", self.path.read_bytes()) if self.path else pymupdf.open()
        if self.doc.needs_pass and not self.doc.authenticate(password or ""):
            raise PermissionError("Mot de passe incorrect")
        self._undo: list[bytes] = []
        self._redo: list[bytes] = []
        self._blocks: dict[int, list[TextBlock]] = {}
        self._images: dict[int, list[ImageItem]] = {}
        self.fonts_added = False
        self.modified = False

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
        self._forget_layout()
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
        self._forget_layout()
        self.modified = True

    def _forget_layout(self) -> None:
        self._blocks.clear()
        self._images.clear()

    # --- saving ------------------------------------------------------------

    def save(self, path: str | Path | None = None, compress: bool = False) -> None:
        target = Path(path) if path else self.path
        if target is None:
            raise ValueError("Aucun chemin de sauvegarde")
        if self.fonts_added:
            # System fonts are embedded whole when inserted: keep only the glyphs used (1.8 MB -> ~50 KB).
            try:
                self.doc.subset_fonts()
            except RuntimeError:
                pass
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

    def blocks(self, page_index: int) -> list[TextBlock]:
        if page_index not in self._blocks:
            self._blocks[page_index] = pdf_text.extract_blocks(self.doc[page_index])
        return self._blocks[page_index]

    def block_at(self, page_index: int, point: pymupdf.Point) -> TextBlock | None:
        return next((b for b in self.blocks(page_index) if b.bbox.contains(point)), None)

    def replace_block(self, block: TextBlock, text: str, style: TextStyle,
                      screen_rect: pymupdf.Rect | None = None) -> None:
        self.checkpoint()
        pdf_text.replace_block(self.doc[block.page], block, text, style, screen_rect)
        self.fonts_added = True

    def delete_block(self, block: TextBlock) -> None:
        self.checkpoint()
        pdf_text.erase(self.doc[block.page], block.bbox)

    def image_png(self, item: ImageItem) -> bytes:
        return pdf_images.png_bytes(self.doc, item.xref)

    def add_text_box(self, page_index: int, screen_rect: pymupdf.Rect, text: str, style: TextStyle) -> None:
        self.checkpoint()
        pdf_text.add_box(self.doc[page_index], screen_rect, text, style)
        self.fonts_added = True

    def search(self, page_index: int, needle: str) -> list[pymupdf.Rect]:
        return self.doc[page_index].search_for(needle) if needle else []

    # --- images ------------------------------------------------------------

    def images(self, page_index: int) -> list[ImageItem]:
        if page_index not in self._images:
            self._images[page_index] = pdf_images.list_images(self.doc[page_index])
        return self._images[page_index]

    def image_at(self, page_index: int, point: pymupdf.Point) -> ImageItem | None:
        # Topmost first.
        return next((i for i in reversed(self.images(page_index)) if i.contains(point)), None)

    def item_at(self, page_index: int, point: pymupdf.Point) -> TextBlock | ImageItem | None:
        """Paragraph or image under the point. When both, the smaller one wins: a signature laid over a
        paragraph is picked, while text printed on a large background image stays editable."""
        block = self.block_at(page_index, point)
        image = self.image_at(page_index, point)
        if block and image:
            return image if image.width * image.height < block.bbox.width * block.bbox.height else block
        return block or image

    def add_image(self, page_index: int, screen_rect: pymupdf.Rect, image: str | Path | bytes) -> ImageItem | None:
        """Insert an image (file path or encoded bytes) and return it so it can be selected right away."""
        self.checkpoint()
        page = self.doc[page_index]
        pdf_images.insert(page, screen_rect, image if isinstance(image, bytes) else str(image))
        r = pymupdf.Rect(screen_rect)
        center = pymupdf.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2) * page.derotation_matrix
        hits = [i for i in self.images(page_index) if i.contains(center)]
        return hits[-1] if hits else None

    def move_image(self, item: ImageItem, new: ImageItem) -> ImageItem:
        """Apply new geometry; returns the item as it now stands (topmost placement)."""
        self.checkpoint()
        pdf_images.place(self.doc[item.page], item, new)
        same = [i for i in self.images(item.page) if i.xref == item.xref]
        return same[-1]

    def delete_image(self, item: ImageItem) -> None:
        self.checkpoint()
        pdf_images.remove(self.doc[item.page], item)

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
