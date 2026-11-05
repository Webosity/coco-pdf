"""Paragraph-level text editing: extract text blocks with their style, rewrite them in place."""
from __future__ import annotations

import functools
import hashlib
import itertools
import statistics
from dataclasses import dataclass, replace

import pymupdf

from . import fonts

ALIGN_LEFT, ALIGN_CENTER, ALIGN_RIGHT, ALIGN_JUSTIFY = range(4)


@dataclass(frozen=True)
class TextStyle:
    family: str = "Helvetica"
    size: float = 12.0
    bold: bool = False
    italic: bool = False
    color: tuple[float, float, float] = (0.0, 0.0, 0.0)
    lineheight: float = 1.2  # line pitch / font size
    align: int = ALIGN_LEFT

    def with_(self, **changes) -> TextStyle:
        return replace(self, **changes)


@dataclass(frozen=True)
class TextBlock:
    page: int
    bbox: pymupdf.Rect  # unrotated page space
    text: str
    style: TextStyle
    pdf_font: str  # font name as found in the PDF


def _color(srgb: int) -> tuple[float, float, float]:
    return ((srgb >> 16 & 255) / 255, (srgb >> 8 & 255) / 255, (srgb & 255) / 255)


def _join_lines(lines: list[dict], block_width: float) -> str:
    """Lines that run up to the right edge are soft wraps (joined by a space); shorter ones end a paragraph."""
    text = ""
    for i, line in enumerate(lines):
        content = "".join(s["text"] for s in line["spans"]).replace("\xa0", " ").strip()
        if i:
            previous = pymupdf.Rect(lines[i - 1]["bbox"])
            text += " " if previous.width > block_width * 0.8 else "\n"
        text += content
    return text


def _block_from_dict(page_index: int, block: dict) -> TextBlock | None:
    lines = [ln for ln in block.get("lines", []) if ln["dir"] == (1.0, 0.0) and "".join(
        s["text"] for s in ln["spans"]).strip()]
    if not lines:
        return None
    spans = [s for ln in lines for s in ln["spans"] if s["text"].strip()]
    main = max(spans, key=lambda s: len(s["text"]))  # dominant style of the paragraph
    family, bold, italic = fonts.identify(main["font"], main["flags"])
    pitches = [b["spans"][0]["origin"][1] - a["spans"][0]["origin"][1] for a, b in itertools.pairwise(lines)]
    lineheight = statistics.median(pitches) / main["size"] if pitches else 1.2
    bbox = pymupdf.Rect()
    for line in lines:
        bbox |= pymupdf.Rect(line["bbox"])
    style = TextStyle(family, round(main["size"], 1), bold, italic, _color(main["color"]),
                      round(min(max(lineheight, 0.8), 3.0), 2))
    return TextBlock(page_index, bbox, _join_lines(lines, bbox.width), style, main["font"])


def extract_blocks(page: pymupdf.Page) -> list[TextBlock]:
    data = page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)
    blocks = (_block_from_dict(page.number, b) for b in data["blocks"] if b["type"] == 0)
    return [b for b in blocks if b is not None]


def erase(page: pymupdf.Page, rect: pymupdf.Rect) -> None:
    """Remove the text under rect, leaving images and drawings (backgrounds, lines) untouched."""
    # Slightly shrunk so the characters of neighbouring blocks are not caught.
    area = pymupdf.Rect(rect.x0 + 0.3, rect.y0 + 0.3, rect.x1 - 0.3, rect.y1 - 0.3)
    page.add_redact_annot(area, fill=False)
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE, graphics=pymupdf.PDF_REDACT_LINE_ART_NONE)


def _font_name(page: pymupdf.Page, choice: fonts.FontChoice) -> str:
    if choice.path is None:
        return choice.base14
    name = "CP" + hashlib.md5(choice.path.encode()).hexdigest()[:8]
    page.insert_font(fontname=name, fontfile=choice.path)
    return name


def unrotated_rect(page: pymupdf.Page) -> pymupdf.Rect:
    return page.rect * page.derotation_matrix


@functools.cache
def _pitch_factor(choice: fonts.FontChoice) -> float:
    """insert_textbox spaces lines by lineheight * size * a font-dependent factor (0.75 for Calibri): measure it."""
    with pymupdf.open() as scratch:
        page = scratch.new_page()
        fontname = _font_name(page, choice)
        # Two words that cannot share a 300 pt line at size 100: forces one wrap ("A\nA" extracts as one line).
        page.insert_textbox(pymupdf.Rect(0, 0, 300, 800), "MMMM MMMM", fontname=fontname, fontsize=100, lineheight=1)
        origins = [ln["spans"][0]["origin"][1] for b in page.get_text("dict")["blocks"] for ln in b["lines"]]
    return (origins[1] - origins[0]) / 100 if len(origins) >= 2 else 1.0


def write(page: pymupdf.Page, box: pymupdf.Rect, text: str, style: TextStyle, rotate: int = 0) -> None:
    """Write text wrapped in the box (unrotated page space); rotate turns the text with the page."""
    choice = fonts.resolve(style.family, style.bold, style.italic)
    fontname = _font_name(page, choice)
    lineheight = style.lineheight / _pitch_factor(choice)
    left = page.insert_textbox(box, text, fontname=fontname, fontsize=style.size, color=style.color,
                               lineheight=lineheight, align=style.align, rotate=rotate)
    if left < 0:
        raise ValueError("Le texte ne tient pas dans la page")


def replace_block(page: pymupdf.Page, block: TextBlock, text: str, style: TextStyle) -> None:
    erase(page, block.bbox)
    if text.strip():
        # Down to the bottom of the page so a longer paragraph can grow instead of being cut.
        bottom = unrotated_rect(page).y1
        write(page, pymupdf.Rect(block.bbox.x0, block.bbox.y0, block.bbox.x1, bottom), text, style)


def add_box(page: pymupdf.Page, screen_rect: pymupdf.Rect, text: str, style: TextStyle) -> None:
    """New text in a box given in screen (rotated) space, extended to the bottom of the page."""
    tall = pymupdf.Rect(screen_rect.x0, screen_rect.y0, screen_rect.x1, page.rect.y1)
    write(page, tall * page.derotation_matrix, text, style, rotate=page.rotation)
