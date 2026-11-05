"""Make text editable again: scanned pages, or pages whose text is corrupted (wrong character codes).

The page is read by Tesseract (built into PyMuPDF, only the language file is shipped). Each word is
then written back as real text at its exact place, in a Base-14 font of the detected family, with the
paragraph's size and ink colour:
- scan: the page becomes the scanned image with its text lines painted over in the paper colour;
- corrupted text: the original text objects are removed, images and drawings are kept, and only the
  words lying where text was are written (handwriting drawn over the form is not transcribed).
"""
from __future__ import annotations

import re
import statistics
from collections.abc import Callable
from dataclasses import dataclass

import pymupdf

from . import asset, fonts, layout

LANGUAGE = "fra"
OCR_DPI = 150  # best accuracy on the tests, and fast
SAMPLE_DPI = 200  # colour measurement and background image
INK = 90  # darker than the paper by this much (0-255) = ink
SCAN_COVERAGE = 0.5  # images over half the page and no visible text = scanned page
FONTS = {"tiro": "Times", "helv": "Helvetica"}
BOLD = {"tiro": "tibo", "helv": "hebo"}
BOLD_MIN_DPI = 200  # below, strokes are 1-2 px wide: bold cannot be told from regular
BOLD_RATIO = 1.22  # stroke this much thicker than the page's usual text = bold
JUSTIFY_GAP = 40  # pt: wider gaps between pieces of a line separate columns, not justified words
BIG_PICTURE = 0.15  # share of the page above which a picture is a damaged scan's backdrop, not a logo


@dataclass
class Word:
    rect: pymupdf.Rect
    text: str
    block: int
    line: int = 0
    baseline: float | None = None
    bold: bool = False
    color: tuple[float, float, float] | None = None


def tessdata() -> str:
    return str(asset("tessdata"))


def visible_text_length(page: pymupdf.Page) -> int:
    # Invisible text (render mode 3, alpha 0) is the OCR layer some scanners add: not editable on screen.
    return sum(len(s["text"].strip()) for b in page.get_text("dict")["blocks"] if b["type"] == 0
               for ln in b["lines"] for s in ln["spans"] if s.get("alpha", 255))


def is_scan(page: pymupdf.Page) -> bool:
    if visible_text_length(page) > 20:
        return False
    covered = sum(abs(pymupdf.Rect(i["bbox"]) & page.rect) for i in page.get_image_info())
    return covered >= SCAN_COVERAGE * abs(page.rect)


def scanned_pages(doc: pymupdf.Document) -> list[int]:
    return [page.number for page in doc if is_scan(page)]


# --- reading ---------------------------------------------------------------

LEADER = re.compile(r"[.…_·]{5,}")
SHORT_LETTERS = set("acemnorsuvwxz")  # x-height letters without ascender, descender or dot


def is_junk(text: str) -> bool:
    """What Tesseract makes of dotted leader lines ("....." -> "·..·.:", "crrorreerrrcrrersecs…"):
    mostly punctuation, or a long run of x-height letters only, which no real 16+ letter word is."""
    if len(text) >= 3 and sum(not c.isalnum() for c in text) > len(text) / 2:
        return True
    letters = "".join(c for c in text.lower() if c.isalpha())
    return len(letters) >= 16 and set(letters) <= SHORT_LETTERS


def read_words(page: pymupdf.Page, dpi: int = OCR_DPI) -> list[Word]:
    textpage = page.get_textpage_ocr(language=LANGUAGE, dpi=dpi, full=True, tessdata=tessdata())
    words = [Word(pymupdf.Rect(w[:4]), w[4], w[5], w[6]) for w in page.get_text("words", textpage=textpage)]
    return [w for w in words if not is_junk(w.text)]


def rows(words: list[Word]) -> list[tuple[pymupdf.Rect, list[Word]]]:
    """Words grouped into visual lines (Tesseract splits justified lines at wide gaps)."""
    # Tesseract's own lines, then the pieces of one visual line put back together. Pieces are compared
    # with the first piece's box, not with the growing union: tight lines must not swallow each other.
    groups: dict[tuple[int, int], list[Word]] = {}
    for w in words:
        groups.setdefault((w.block, w.line), []).append(w)
    out: list[list] = []
    for ws in sorted(groups.values(), key=lambda ws: min(w.rect.y0 for w in ws)):
        rect = pymupdf.Rect(ws[0].rect)
        for w in ws[1:]:
            rect |= w.rect
        # Same height, and close enough to be one justified line rather than two columns side by side.
        row = next((r for r in out if min(r[2].y1, rect.y1) - max(r[2].y0, rect.y0) > 0.5 * min(r[2].height, rect.height)
                    and max(rect.x0 - r[0].x1, r[0].x0 - rect.x1) < JUSTIFY_GAP), None)
        if row:
            row[0] |= rect
            row[1] += ws
        else:
            out.append([pymupdf.Rect(rect), list(ws), rect])
    return [(r, sorted(ws, key=lambda w: w.rect.x0)) for r, ws, _ in out]


def fit(text: str, width: float, fontname: str) -> float | None:
    """Font size at which text has this width."""
    w1 = pymupdf.get_text_length(text, fontname, 1)
    return width / w1 if w1 else None


# --- measuring -------------------------------------------------------------

class Sampler:
    def __init__(self, page: pymupdf.Page):
        self.scale = SAMPLE_DPI / 72
        self.rgb = page.get_pixmap(dpi=SAMPLE_DPI, alpha=False, colorspace=pymupdf.csRGB)
        self.gray = pymupdf.Pixmap(pymupdf.csGRAY, self.rgb)
        self.gray_data = self.gray.samples  # Pixmap.samples copies the whole image on every access

    def box(self, rect: pymupdf.Rect, pad: float = 0) -> pymupdf.IRect:
        s = self.scale
        return pymupdf.IRect((rect.x0 - pad) * s, (rect.y0 - pad) * s, (rect.x1 + pad) * s,
                             (rect.y1 + pad) * s) & pymupdf.IRect(self.rgb.irect)

    def paper(self, rect: pymupdf.Rect) -> tuple[int, int, int]:
        """Median colour just above and below the line."""
        ring = self.box(rect, pad=rect.height * 0.3)
        samples = [self.rgb.pixel(x, y) for y in (ring.y0, ring.y1 - 1) for x in range(ring.x0, ring.x1, 3)]
        return tuple(int(statistics.median(c[i] for c in samples)) for i in range(3)) if samples else (255,) * 3

    def ink(self, rect: pymupdf.Rect, paper_level: float, limit: int = 60) -> list[tuple[int, int, int]]:
        """Colours of the darkest pixels of a word: the core of the strokes, not the anti-aliased (or
        ClearType-coloured) edges."""
        box, stride, data = self.box(rect), self.gray.stride, self.gray_data
        dark = []
        for y in range(box.y0, box.y1, 2):
            row = data[y * stride + box.x0:y * stride + box.x1]
            dark += [(v, box.x0 + i, y) for i, v in enumerate(row) if v < paper_level - INK]
        dark.sort()
        core = dark[:max(len(dark) // 3, 1)][:limit] if dark else []
        return [self.rgb.pixel(x, y) for _, x, y in core]


PROFILE_BINS = 48


def _profile(gray: pymupdf.Pixmap, box: pymupdf.IRect) -> list[float]:
    """Ink per column, resampled to PROFILE_BINS and normalised: the 'rhythm' of the letters."""
    columns = [0] * max(box.width, 1)
    data = gray.samples
    for y in range(box.y0, box.y1):
        row = data[y * gray.stride + box.x0:y * gray.stride + box.x1]
        for i, v in enumerate(row):
            columns[i] += 255 - v
    bins = [sum(columns[i * len(columns) // PROFILE_BINS:(i + 1) * len(columns) // PROFILE_BINS] or [0])
            for i in range(PROFILE_BINS)]
    mean = sum(bins) / PROFILE_BINS
    centred = [b - mean for b in bins]
    norm = sum(c * c for c in centred) ** 0.5 or 1
    return [c / norm for c in centred]


def _rendered_profile(text: str, fontname: str, scale: float) -> list[float]:
    size = 40
    with pymupdf.open() as doc:
        page = doc.new_page(width=pymupdf.get_text_length(text, fontname, size), height=size * 1.4)
        page.insert_text((0, size), text, fontname=fontname, fontsize=size)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(scale / 4, scale / 4), colorspace=pymupdf.csGRAY)
    return _profile(pix, pymupdf.IRect(pix.irect))


def guess_family(sampler: Sampler, words: list[Word]) -> str:
    """Serif or sans-serif: compare the ink rhythm of the longest words with both renderings."""
    longest = sorted((w for w in words if len(w.text) >= 6 and w.text.isalpha()), key=lambda w: -len(w.text))[:15]
    scores = dict.fromkeys(FONTS, 0.0)
    for w in longest:
        mine = _profile(sampler.gray, sampler.box(w.rect))
        for family in FONTS:
            scores[family] += sum(a * b for a, b in zip(mine, _rendered_profile(w.text, family, sampler.scale)))
    return max(scores, key=scores.get) if longest else "tiro"


def ink_color(samples: list[tuple[int, int, int]]) -> tuple[float, float, float]:
    if not samples:
        return (0.0, 0.0, 0.0)
    color = tuple(statistics.median(c[i] for c in samples) / 255 for i in range(3))
    # Black ink scans as dark grey: dark, nearly neutral colours are black.
    if max(color) - min(color) < 0.18 and max(color) < 0.5:
        return (0.0, 0.0, 0.0)
    return color


# --- rebuilding ------------------------------------------------------------

def _original_spans(page: pymupdf.Page) -> tuple[list[pymupdf.Rect], list[pymupdf.Rect], str]:
    """(text to replace, spans to keep as they are, family of the replaced text). Kept: lone symbols such as check boxes, and anything
    holding a dotted leader (a label and its dots are often one span): they display fine, and OCR would
    misread them ("☐" -> "CO", dots -> letters). The dotted lines are where people write anyway."""
    replace, keep, serif = [], [], 0
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            for s in ln["spans"]:
                text = s["text"].strip()
                if not text:
                    continue
                symbolic = len(text) == 1 or not any(c.isalnum() for c in text) or LEADER.search(text)
                (keep if symbolic else replace).append(pymupdf.Rect(s["bbox"]))
                if not symbolic:
                    serif += len(text) if fonts.identify(s["font"], s["flags"])[0] != "Helvetica" else -len(text)
    # The original font is known: better than guessing from the shapes. Courier is rare enough to be Times.
    return replace, keep, "tiro" if serif >= 0 else "helv"


def _overlap(word: Word, areas: list[pymupdf.Rect], share: float) -> bool:
    return any(abs(word.rect & a) > share * abs(word.rect) for a in areas)


def _font(family: str, word: Word) -> str:
    return BOLD[family] if word.bold else family


def _ink_bands(counts: list[int]) -> list[tuple[int, int, int]]:
    """(first row, end row, ink) of the runs of rows holding ink; one-row gaps do not split a band."""
    bands, start, gap = [], None, 0
    for i, c in enumerate(counts + [0, 0]):
        if c:
            if start is None:
                start = i
            gap = 0
        elif start is not None:
            gap += 1
            if gap > 1:
                end = i - gap + 1
                bands.append((start, end, sum(counts[start:end])))
                start = None
    return bands


def _refine_boxes(words: list[Word], text_pix: pymupdf.Pixmap, scale: float) -> None:
    """The OCR gives every word its line's box, and that box may be far too tall (a footer line got a
    box two lines high, spanning the next one) or overlap the next line: words then merge into the
    wrong line and baselines fall too low. Re-measured in the word's own pixels: the ink band holding
    most ink (accents are small separate bands), or in an oversized box the first substantial band.
    The baseline is the last well-filled row down from the band's fullest row (descenders are sparse)."""
    data = text_pix.samples
    heights = sorted(w.rect.height for w in words)
    usual = heights[len(heights) // 2] if heights else 0
    for w in words:
        box = pymupdf.IRect(w.rect.x0 * scale, w.rect.y0 * scale, w.rect.x1 * scale, w.rect.y1 * scale) & \
            pymupdf.IRect(text_pix.irect)
        counts = [data[y * text_pix.stride + box.x0:y * text_pix.stride + box.x1].count(0) for y in range(box.y0, box.y1)]
        bands = _ink_bands(counts)
        if not bands:
            continue
        most = max(b[2] for b in bands)
        substantial = [b for b in bands if b[2] >= 0.2 * most]  # not a stray accent
        if w.rect.height > 1.6 * usual:
            first, last_row, _ = substantial[0]
        else:
            # The band at the box's centre: a box overlapping the next line holds part of it too.
            middle = len(counts) / 2
            first, last_row, _ = min(substantial, key=lambda b: 0 if b[0] <= middle < b[1] else
                                     min(abs(b[0] - middle), abs(b[1] - middle)))
        band = counts[first:last_row]
        full = max(band) * 0.35
        base = band.index(max(band))
        while base + 1 < len(band) and band[base + 1] >= full:
            base += 1
        w.rect = pymupdf.Rect(w.rect.x0, (box.y0 + first) / scale, w.rect.x1, (box.y0 + last_row) / scale)
        if len(w.text) >= 2:
            w.baseline = (box.y0 + first + base + 1) / scale


def _mark_bold(words: list[Word], text_pix: pymupdf.Pixmap, scale: float) -> None:
    """Bold strokes are thicker. Measure: median length of the horizontal black runs of the word on the
    black-and-white text-only image (300 dpi receipt: 6-7 px bold, 4-5 px regular), divided by the font
    size of its line, the median of the sizes its words' widths give. Per line, not per word: a bold
    word is wider, so its own size estimate is inflated and hides its weight; heights (word or line)
    vary too much with accents, capitals and descenders. Words of 1-3 characters are too short to
    measure: they follow the majority of their line."""
    strokes, data = {}, text_pix.samples
    lines = [line for block in {w.block for w in words} for _, line in rows([w for w in words if w.block == block])]
    for line in lines:
        sizes = [z for w in line if len(w.text) >= 3 and (z := fit(w.text, w.rect.width, "helv"))]
        height = statistics.median(sizes) if sizes else 0
        for w in line:
            box = pymupdf.IRect(w.rect.x0 * scale, w.rect.y0 * scale, w.rect.x1 * scale, w.rect.y1 * scale) & \
                pymupdf.IRect(text_pix.irect)
            runs = []
            for y in range(box.y0, box.y1):
                row = data[y * text_pix.stride + box.x0:y * text_pix.stride + box.x1]
                runs += [len(m) for m in re.findall(rb"\x00+", row)]
            if runs and height:
                runs.sort()
                middle = runs[len(runs) // 4:max(3 * len(runs) // 4, 1)]  # trimmed: runs are a few whole pixels
                strokes[id(w)] = statistics.mean(middle) / height
    usual = [strokes[id(w)] for w in words if len(w.text) >= 4 and id(w) in strokes]
    if len(usual) < 10:
        return
    normal = statistics.median(usual)
    for line in lines:
        measured = [w for w in line if len(w.text) >= 4 and id(w) in strokes]
        for w in measured:
            w.bold = strokes[id(w)] > normal * BOLD_RATIO
        majority = sum(w.bold for w in measured) * 2 >= len(measured) if measured else False
        for w in line:
            if w not in measured:
                w.bold = majority


def _write(page: pymupdf.Page, words: list[Word], family: str, colors: dict[int, tuple]) -> None:
    for block in sorted({w.block for w in words}):
        block_words = [w for w in words if w.block == block]
        sizes = [s for w in block_words if len(w.text) >= 3 and (s := fit(w.text, w.rect.width, _font(family, w)))]
        block_size = statistics.median(sizes) if sizes else block_words[0].rect.height * 0.8
        descender = pymupdf.Font(family).descender
        for rect, line in rows(block_words):
            # Each line its own size: a title and the text under it are often one OCR block.
            # Short words are noisy, but a line with one long word must not take that word's size alone.
            shortest = 3 if sum(len(w.text) >= 3 for w in line) >= 3 else 2
            line_sizes = [s for w in line if len(w.text) >= shortest and (s := fit(w.text, w.rect.width, _font(family, w)))]
            size = statistics.median(line_sizes) if line_sizes else block_size
            # The median of the baselines measured word by word: one word's measure can be off (short
            # words, boxes overlapping the next line), the line's is robust and keeps the line straight.
            measured = [w.baseline for w in line if w.baseline is not None]
            baseline = statistics.median(measured) if measured else rect.y1 + descender * size
            for i, w in enumerate(line):
                # Never wider than the word was, or it runs into the next one; short words keep the
                # line size (their OCR box is too tight to measure).
                fontname = _font(family, w)
                word_size = min(size, fit(w.text, w.rect.width * 1.02, fontname) or size) if len(w.text) >= 4 else size
                # A real space after each word: words are placed one by one, and text extraction (hence
                # editing) does not see a gap of a few points as a space ("Déposeéléments").
                text = w.text + (" " if i < len(line) - 1 else "")
                page.insert_text((w.rect.x0, baseline), text, fontname=fontname, fontsize=word_size,
                                 color=w.color or colors[block])


def _drop_border_specks(words: list[Word], parts: layout.Layout) -> list[Word]:
    """Bits of frames and their shadows read as characters: '|' stuck to a word ("|Facture"), and lone
    1-2 character "words" that are no letters or digits (";") or sit on the edge of a filled area ("TS"
    from a box's shadow). Short words inside narrow table cells are real ("M2", "4"): rules are no clue."""
    edges = [(rect + (-3, -3, 3, 3), rect + (3, 3, -3, -3)) for rect, _ in parts.fills]
    for w in words:
        w.text = w.text.strip("|")
    words = [w for w in words if w.text and not is_junk(w.text)]
    per_line: dict[tuple[int, int], int] = {}
    for w in words:
        per_line[(w.block, w.line)] = per_line.get((w.block, w.line), 0) + 1

    def speck(w: Word) -> bool:
        if len(w.text) > 2 or per_line[(w.block, w.line)] > 1:
            return False
        on_edge = any(w.rect.intersects(outer) and not inner.contains(w.rect) for outer, inner in edges)
        return not any(c.isalnum() for c in w.text) or on_edge

    return [w for w in words if not speck(w)]


def source_dpi(page: pymupdf.Page) -> int:
    """Resolution of the scanned image covering the page (96 for a screenshot, 300 for a scanner)."""
    infos = [i for i in page.get_image_info() if i["bbox"][2] > i["bbox"][0]]
    if not infos:
        return 150
    big = max(infos, key=lambda i: abs(pymupdf.Rect(i["bbox"])))
    return round(big["width"] / (pymupdf.Rect(big["bbox"]).width / 72))


def _block_colors(sampler: Sampler, words: list[Word]) -> dict[int, tuple]:
    colors = {}
    for block in {w.block for w in words}:
        block_words = [w for w in words if w.block == block]
        level = statistics.mean(sum(sampler.paper(r)) / 3 for r, _ in rows(block_words))
        colors[block] = ink_color([c for w in block_words for c in sampler.ink(w.rect, level)])
    return colors


def _rebuild_scan(doc: pymupdf.Document, index: int) -> int:
    """No background image: the page is rebuilt from its parts. Filled areas become coloured rectangles,
    rules vector lines, logos and photos separate (movable) images, and the text real text, read on a
    copy of the page that holds nothing else, so rules and logos cannot be misread as letters."""
    page = doc[index]
    dpi = source_dpi(page)
    parts = layout.analyze(page, colour_pictures=dpi >= OCR_DPI)
    ocr_dpi = min(max(dpi, OCR_DPI), 300)
    text_doc, text_pix = layout.text_only_page(page, parts, ocr_dpi)
    words = _drop_border_specks(read_words(text_doc[0], ocr_dpi), parts)
    # Measures below look for black pixels: give them a pure black-and-white copy (halfway grey).
    black_white = pymupdf.Pixmap(pymupdf.csGRAY, text_pix.width, text_pix.height,
                                 text_pix.samples.translate(bytes(0 if v < 128 else 255 for v in range(256))), False)
    if ocr_dpi >= BOLD_MIN_DPI:
        # Only on real scans: on a low-resolution screenshot strokes are grey, the black-and-white copy
        # loses part of them, and the OCR's own boxes are the better guess.
        _refine_boxes(words, black_white, ocr_dpi / 72)
        _mark_bold(words, black_white, ocr_dpi / 72)
    sampler = Sampler(page)
    family = guess_family(sampler, words)
    colors = _block_colors(sampler, words)
    if dpi >= OCR_DPI:
        # Per word when clearly coloured: a blue heading and the black text beside it are often one OCR
        # block. Not on low-resolution screenshots, whose ClearType fringes tint every word.
        for rect, line in rows(words):
            level = sum(sampler.paper(rect)) / 3
            for w in line:
                color = ink_color(sampler.ink(w.rect, level))
                if len(w.text) >= 3 and max(color) - min(color) > 0.25:
                    w.color = color

    new_doc = pymupdf.open()
    new = new_doc.new_page(width=page.rect.width, height=page.rect.height)
    for rect, color in parts.fills:
        new.draw_rect(rect, color=None, fill=color, width=0)
    page_area = abs(page.rect)
    for rect in parts.pictures:
        pix = page.get_pixmap(dpi=min(max(dpi, 150), 300), clip=rect)
        if abs(rect) > BIG_PICTURE * page_area:
            # A damaged scan's backdrop (crumpled sheet, scanner lid): its text is written as real text
            # over it, so blank it out of the picture.
            k = pix.width / rect.width
            for w in words:
                if w.rect.intersects(rect):
                    box = pymupdf.IRect((w.rect.x0 - rect.x0) * k - 2, (w.rect.y0 - rect.y0) * k - 2,
                                        (w.rect.x1 - rect.x0) * k + 2, (w.rect.y1 - rect.y0) * k + 2)
                    pix.set_rect(box & pymupdf.IRect(pix.irect), (255, 255, 255))
        new.insert_image(rect, stream=pix.tobytes("jpeg", jpg_quality=85))
    for rule in parts.rules:
        new.draw_line(rule.p1, rule.p2, color=rule.color, width=rule.width)
    _write(new, words, family, colors)
    doc.insert_pdf(new_doc, start_at=index)
    doc.delete_page(index + 1)
    return len(words)


def _repair_text(page: pymupdf.Page) -> int:
    """Text that displays fine but reads as gibberish: replace only the text, keep everything else."""
    words = read_words(page)
    replace, keep, family = _original_spans(page)
    words = [w for w in words if _overlap(w, replace, 0.5) and not _overlap(w, keep, 0.3)]
    if not words:
        return 0
    colors = _block_colors(Sampler(page), words)
    for rect in replace:
        # Shrunk a little so the kept leaders and check boxes right next to the text survive.
        page.add_redact_annot(rect + (0.4, 0.4, -0.4, -0.4), fill=False)
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE, graphics=pymupdf.PDF_REDACT_LINE_ART_NONE)
    _write(page, words, family, colors)
    return len(words)


def rebuild_page(doc: pymupdf.Document, index: int) -> int:
    """Rewrite one page with editable text. Returns the number of words written."""
    rotation = doc[index].rotation
    if rotation:
        # Work upright: OCR word boxes and the rendered image must share one coordinate space.
        doc[index].set_rotation(0)
    words = _rebuild_scan(doc, index) if is_scan(doc[index]) else _repair_text(doc[index])
    doc[index].set_rotation(rotation)
    return words


def rebuild(data: bytes, pages: list[int], progress: Callable[[int, int], bool] | None = None) -> tuple[bytes, int]:
    """Work on a copy of the document (data); progress(done, total) returns False to cancel."""
    doc = pymupdf.open("pdf", data)
    words = 0
    for done, index in enumerate(pages):
        if progress and not progress(done, len(pages)):
            break
        words += rebuild_page(doc, index)
    if progress:
        progress(len(pages), len(pages))
    return doc.tobytes(garbage=3, deflate=True), words
