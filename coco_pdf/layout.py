"""Split a scanned page into rules, filled areas, pictures and text, from its pixels.

Everything is measured on a 100 dpi grey rendering with byte-level operations (bytes.translate,
regular expressions on rows and columns): fast enough without numpy.
- rules: long thin runs of ink, horizontal or vertical (table borders, frames);
- fills: long runs of non-paper rows stacked over a few millimetres (grey cells, shaded boxes); uniform
  ones become coloured rectangles, textured ones (gradients, photos) pictures;
- pictures: tall or colourful ink blobs (logos, stamps, signatures), with the small text stuck to them;
- text: the remaining ink blobs, rendered black on white, without rules or pictures, for the OCR.
"""
from __future__ import annotations

import re
import statistics
from collections import deque
from dataclasses import dataclass, field

import pymupdf

DPI = 100
SCALE = DPI / 72
RULE_MIN_H = 60  # px at 100 dpi (~15 mm): shortest horizontal rule
RULE_MIN_V = 40  # px (~10 mm): shortest vertical rule
RULE_MAX_THICK = 5  # px (~1.3 mm)
FILL_MIN_RUN = 80  # px (~20 mm)
FILL_MIN_H = 8  # px (~2 mm)
FILL_BLOCK = 8  # px: fills are judged on 8x8 block means, which smooth out a printed grey's halftone dots...
FILL_SPREAD = 13  # ...but not a gradient: measured 5.5 and 10.5 on grey boxes, 18.2 on a gradient banner
CELL = 3  # px: grid used to find blobs
TEXT_MAX_H = 31  # px (~8 mm): taller blobs are pictures
COLOURFUL = 60  # mean RGB spread of a blob's ink above which it is a picture (logos)...
COLOURFUL_MIN_H = 16  # ...unless it is short (coloured headings stay text)
BIG_PICTURE = 0.15  # share of the page
EDGE = 0.012  # share of the width: ink this close to the page edge is the scanner's shadow
TEXT_GAP = 0.02  # a row with less ink than this share of the width separates two lines of text


@dataclass
class Rule:
    p1: pymupdf.Point
    p2: pymupdf.Point
    width: float  # pt
    color: tuple[float, float, float]


@dataclass
class Layout:
    rules: list[Rule] = field(default_factory=list)
    fills: list[tuple[pymupdf.Rect, tuple[float, float, float]]] = field(default_factory=list)
    pictures: list[pymupdf.Rect] = field(default_factory=list)
    text_boxes: list[tuple[pymupdf.IRect, int]] = field(default_factory=list)  # px box, ink threshold
    rule_boxes: list[pymupdf.IRect] = field(default_factory=list)  # px, to blank out before OCR


def _table(threshold: int) -> bytes:
    return bytes(1 if v < threshold else 0 for v in range(256))


def _strokes(lines: list[bytes], min_run: int) -> list[list[int]]:
    """Runs of 1 at least min_run long, stacked over consecutive lines: [first, last, start, end]."""
    pattern = re.compile(rb"\x01{%d,}" % min_run)
    done, open_ = [], []
    for i, line in enumerate(lines):
        still = []
        for m in pattern.finditer(line):
            a, b = m.span()
            match = next((s for s in open_ if s[1] == i - 1 and min(b, s[3]) - max(a, s[2]) > 0.8 * (b - a)), None)
            if match:
                open_.remove(match)
                match[1], match[2], match[3] = i, min(match[2], a), max(match[3], b)
                still.append(match)
            else:
                still.append([i, i, a, b])
        done += open_
        open_ = still
    return done + open_


def _area(r: pymupdf.IRect) -> int:
    return 0 if r.is_empty else r.width * r.height


def _or3(lines: list[bytes]) -> list[bytes]:
    """Each line OR-ed with its two neighbours (0/1 bytes): a slightly skewed rule stays one run."""
    ints = [int.from_bytes(line, "big") for line in lines]
    n = len(lines[0]) if lines else 0
    return [(ints[max(i - 1, 0)] | ints[i] | ints[min(i + 1, len(ints) - 1)]).to_bytes(n, "big")
            for i in range(len(ints))]


def _px(rect: pymupdf.IRect | tuple) -> pymupdf.Rect:
    r = pymupdf.IRect(rect)
    return pymupdf.Rect(r.x0 / SCALE, r.y0 / SCALE, r.x1 / SCALE, r.y1 / SCALE)


class Analyzer:
    def __init__(self, page: pymupdf.Page):
        self.rgb = page.get_pixmap(dpi=DPI, colorspace=pymupdf.csRGB, alpha=False)
        self.gray = pymupdf.Pixmap(pymupdf.csGRAY, self.rgb)
        self.w, self.h = self.gray.width, self.gray.height
        data = self.gray.samples
        self.data = data
        self.paper = statistics.median(data[::97])  # most of a page is paper
        self.ink_level = self.paper - 65
        self.ink = bytearray(data.translate(_table(self.ink_level)))
        self.nonpaper = data.translate(_table(self.paper - 18))

    def rows(self, mask) -> list[bytes]:
        return [bytes(mask[y * self.w:(y + 1) * self.w]) for y in range(self.h)]

    def columns(self, mask) -> list[bytes]:
        mask = bytes(mask)
        return [mask[x::self.w] for x in range(self.w)]

    def color(self, box: pymupdf.IRect, dark: bool) -> tuple[float, float, float]:
        """Median colour of the ink (dark=True) or of the background (dark=False) inside box."""
        samples = []
        for y in range(box.y0, box.y1, 2):
            for x in range(box.x0, box.x1, 2):
                if (self.data[y * self.w + x] < self.ink_level) == dark:
                    samples.append(self.rgb.pixel(x, y))
        if not samples:
            return (0.0, 0.0, 0.0)
        c = tuple(statistics.median(s[i] for s in samples) / 255 for i in range(3))
        return (0.0, 0.0, 0.0) if dark and max(c) - min(c) < 0.18 and max(c) < 0.5 else c

    def clear_edges(self) -> None:
        e = max(int(self.w * EDGE), 2)
        for box in ((0, 0, self.w, e), (0, self.h - e, self.w, self.h), (0, 0, e, self.h), (self.w - e, 0, self.w, self.h)):
            self.clear(pymupdf.IRect(box))

    def clear(self, box: pymupdf.IRect) -> None:
        box = box & pymupdf.IRect(0, 0, self.w, self.h)
        for y in range(box.y0, box.y1):
            self.ink[y * self.w + box.x0:y * self.w + box.x1] = bytes(box.width)

    # --- rules -------------------------------------------------------------

    def find_rules(self) -> list[tuple[Rule, pymupdf.IRect]]:
        # On masks OR-ed over 3 lines (or columns), so a scan's slight skew does not break the rules;
        # that widens them by 2 px, taken back from the thickness.
        found = []
        for first, last, a, b in _strokes(_or3(self.rows(self.ink)), RULE_MIN_H):
            thick = last - first + 1 - 2
            if thick <= RULE_MAX_THICK:
                box = pymupdf.IRect(a, first, b, last + 1)
                y = (first + last + 1) / 2 / SCALE
                found.append((Rule(pymupdf.Point(a / SCALE, y), pymupdf.Point(b / SCALE, y),
                                   max(thick / SCALE, 0.5), self.color(box, True)), box))
        for first, last, a, b in _strokes(_or3(self.columns(self.ink)), RULE_MIN_V):
            thick = last - first + 1 - 2
            if thick <= RULE_MAX_THICK:
                box = pymupdf.IRect(first, a, last + 1, b)
                x = (first + last + 1) / 2 / SCALE
                found.append((Rule(pymupdf.Point(x, a / SCALE), pymupdf.Point(x, b / SCALE),
                                   max(thick / SCALE, 0.5), self.color(box, True)), box))
        return found

    # --- fills -------------------------------------------------------------

    def find_fills(self) -> tuple[list[tuple[pymupdf.IRect, tuple, int]], list[pymupdf.IRect]]:
        """(uniform fills with their colour and grey level, tall textured areas that are pictures).
        A fill's own grey may be darker than the ink threshold (table headers): its background is what
        stays close to its median grey, the darker text and rules inside are left out."""
        uniform, textured = [], []
        for first, last, a, b in _strokes(self.rows(self.nonpaper), FILL_MIN_RUN):
            if last - first + 1 < FILL_MIN_H:
                continue
            box = pymupdf.IRect(a, first, b, last + 1)
            levels = [self.data[y * self.w + x] for y in range(box.y0, box.y1, 2) for x in range(box.x0, box.x1, 3)]
            level = statistics.median(levels)
            background = [v for v in levels if v > level - 40]
            if len(background) > 0.6 * len(levels) and self.block_spread(box, level) < FILL_SPREAD:
                samples = [self.rgb.pixel(x, y) for y in range(box.y0, box.y1, 3) for x in range(box.x0, box.x1, 4)
                           if self.data[y * self.w + x] > level - 40]
                color = tuple(statistics.median(c[i] for c in samples) / 255 for i in range(3))
                uniform.append((box, color, int(level)))
            elif box.height > TEXT_MAX_H:  # a banner or photo, not a line of bold text
                textured.append(box)
        return uniform, textured

    def block_spread(self, box: pymupdf.IRect, level: float) -> float:
        """Spread of the 8x8 block means of the background (blocks mostly made of text are skipped)."""
        n, means = FILL_BLOCK, []
        for by in range(box.y0, box.y1 - n + 1, n):
            for bx in range(box.x0, box.x1 - n + 1, n):
                values = [v for y in range(by, by + n) for v in self.data[y * self.w + bx:y * self.w + bx + n]]
                background = [v for v in values if v > level - 40]
                if len(background) > 0.8 * len(values):
                    means.append(sum(background) / len(background))
        return statistics.pstdev(means) if len(means) > 3 else 99.0

    def ink_inside_fill(self, box: pymupdf.IRect, level: int) -> int:
        """Inside a grey fill the fill itself (halftone dots at full resolution) may pass for ink: only
        what is clearly darker is."""
        threshold = min(level - 60, 110)
        table = _table(threshold)
        for y in range(box.y0, box.y1):
            row = self.data[y * self.w + box.x0:y * self.w + box.x1]
            self.ink[y * self.w + box.x0:y * self.w + box.x1] = row.translate(table)
        return threshold

    # --- blobs -------------------------------------------------------------

    def blobs(self) -> list[pymupdf.IRect]:
        """Ink blobs on a coarse grid; letters are joined horizontally into words and lines only."""
        cw, ch = (self.w + CELL - 1) // CELL, (self.h + CELL - 1) // CELL
        grid = bytearray(cw * ch)
        for y in range(self.h):
            row = self.ink[y * self.w:(y + 1) * self.w]
            for m in re.finditer(rb"\x01+", bytes(row)):
                for cx in range(m.start() // CELL, (m.end() - 1) // CELL + 1):
                    grid[(y // CELL) * cw + cx] = 1
        seen = bytearray(cw * ch)
        out = []
        for start in range(cw * ch):
            if not grid[start] or seen[start]:
                continue
            seen[start] = 1
            queue, x0, y0, x1, y1 = deque([start]), cw, ch, 0, 0
            while queue:
                i = queue.popleft()
                cx, cy = i % cw, i // cw
                x0, y0, x1, y1 = min(x0, cx), min(y0, cy), max(x1, cx), max(y1, cy)
                # Two cells sideways (letter and word gaps), one up and down (never the next line).
                for dx, dy in ((1, 0), (-1, 0), (2, 0), (-2, 0), (0, 1), (0, -1), (1, 1), (-1, 1), (1, -1), (-1, -1)):
                    nx, ny = cx + dx, cy + dy
                    j = ny * cw + nx
                    if 0 <= nx < cw and 0 <= ny < ch and grid[j] and not seen[j]:
                        seen[j] = 1
                        queue.append(j)
            out.append(pymupdf.IRect(x0 * CELL, y0 * CELL, min((x1 + 1) * CELL, self.w), min((y1 + 1) * CELL, self.h)))
        return out

    def text_bands(self, box: pymupdf.IRect) -> list[pymupdf.IRect]:
        """A tall blob made of lines of text (tight leading joins them): split it at the nearly empty rows.
        Empty list when it does not split into text-high bands: then it is a picture."""
        limit = max(1, int(box.width * TEXT_GAP))
        bands, start = [], None
        for y in range(box.y0, box.y1):
            busy = sum(self.ink[y * self.w + box.x0:y * self.w + box.x1]) > limit
            if busy and start is None:
                start = y
            elif not busy and start is not None:
                bands.append(pymupdf.IRect(box.x0, start, box.x1, y))
                start = None
        if start is not None:
            bands.append(pymupdf.IRect(box.x0, start, box.x1, box.y1))
        if len(bands) < 2 or any(b.height > TEXT_MAX_H for b in bands):
            return []
        return bands

    def colourfulness(self, box: pymupdf.IRect) -> float:
        spreads = []
        for y in range(box.y0, box.y1, 2):
            for x in range(box.x0, box.x1, 2):
                if self.ink[y * self.w + x]:
                    r, g, b = self.rgb.pixel(x, y)
                    spreads.append(max(r, g, b) - min(r, g, b))
        return statistics.mean(spreads) if spreads else 0


def _grow(boxes: list[pymupdf.IRect], margin: int) -> list[pymupdf.IRect]:
    """Merge boxes that touch (within margin) until stable."""
    boxes = [pymupdf.IRect(b) for b in boxes]
    merged = True
    while merged:
        merged = False
        for i, a in enumerate(boxes):
            for j in range(i + 1, len(boxes)):
                b = boxes[j]
                if not (pymupdf.IRect(a.x0 - margin, a.y0 - margin, a.x1 + margin, a.y1 + margin) & b).is_empty:
                    boxes[i] = a | b
                    del boxes[j]
                    merged = True
                    break
            if merged:
                break
    return boxes


def analyze(page: pymupdf.Page, colour_pictures: bool = True) -> Layout:
    """colour_pictures=False for low-resolution screenshots: ClearType tints the edges of every letter,
    so colourful text would be taken for logos (logos there are still found by their height)."""
    an = Analyzer(page)
    layout = Layout()
    uniform, textured = an.find_fills()
    pictures = list(textured)
    thresholds = []
    for box, color, level in uniform:
        thresholds.append((box, an.ink_inside_fill(box, level)))
    # A rule hugging the page edge is the scanner's shadow, not part of the document.
    an.clear_edges()
    rules = [(r, b) for r, b in an.find_rules() if b.x0 > 3 and b.y0 > 3 and b.x1 < an.w - 3 and b.y1 < an.h - 3]
    for _, box in rules:
        an.clear(pymupdf.IRect(box.x0 - 1, box.y0 - 1, box.x1 + 1, box.y1 + 1))

    texts = []
    for blob in an.blobs():
        if blob.width * blob.height < 6:  # specks of dust
            continue
        if colour_pictures and blob.height > COLOURFUL_MIN_H and an.colourfulness(blob) > COLOURFUL:
            pictures.append(blob)
        elif blob.height > TEXT_MAX_H:
            bands = an.text_bands(blob)
            if bands:
                texts.extend(bands)
            else:
                pictures.append(blob)
        else:
            texts.append(blob)
    pictures = _grow(pictures, 0)
    # Text overlapping a picture is part of it (words printed in a logo or a banner), unless the picture
    # is a big part of the page: the backdrop of a damaged scan, whose text must stay text.
    page_area = an.w * an.h
    for t in list(texts):
        for k, p in enumerate(pictures):
            if not (p & t).is_empty and _area(p) < BIG_PICTURE * page_area:
                pictures[k] = p | t
                texts.remove(t)
                break
    pictures = _grow(pictures, 0)

    def inside_picture(box: pymupdf.IRect) -> bool:
        return any(_area(box & p) > 0.5 * _area(box) for p in pictures)

    layout.pictures = [_px(p) for p in pictures]
    layout.fills = [(_px(box), color) for box, color, _ in uniform if not inside_picture(box)]
    layout.rules = [rule for rule, box in rules if not inside_picture(box)]
    # For the OCR, text keeps its greys down to just below the paper: on a low-resolution screenshot the
    # anti-aliasing carries half of each stroke (a black-and-white cut lost 5 phrases out of 12).
    text_level = int(an.paper - 30)
    for t in texts:
        threshold = next((thr for box, thr in thresholds if _area(t & box) > 0.5 * _area(t)), text_level)
        layout.text_boxes.append((t, threshold))
    layout.rule_boxes = [box for _, box in rules]
    return layout


def text_only_page(page: pymupdf.Page, layout: Layout, dpi: int) -> tuple[pymupdf.Document, pymupdf.Pixmap]:
    """A copy of the page holding only its text, dark on white: no rules, fills nor pictures to confuse OCR."""
    gray = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY, alpha=False)
    w, h, k = gray.width, gray.height, dpi / DPI
    out = bytearray(b"\xff" * (w * h))
    data = gray.samples
    for box, threshold in layout.text_boxes:
        # Ink keeps its grey (anti-aliasing carries the thin strokes of low-resolution text), everything
        # lighter than the threshold (paper, a cell's grey fill) turns white.
        table = bytes(v if v < threshold else 255 for v in range(256))
        x0, x1 = max(int(box.x0 * k) - 1, 0), min(int(box.x1 * k) + 1, w)
        for y in range(max(int(box.y0 * k) - 1, 0), min(int(box.y1 * k) + 1, h)):
            out[y * w + x0:y * w + x1] = data[y * w + x0:y * w + x1].translate(table)
    for box in layout.rule_boxes:
        x0, x1 = max(int((box.x0 - 1) * k), 0), min(int((box.x1 + 1) * k), w)
        for y in range(max(int((box.y0 - 1) * k), 0), min(int((box.y1 + 1) * k), h)):
            out[y * w + x0:y * w + x1] = b"\xff" * (x1 - x0)
    pix = pymupdf.Pixmap(pymupdf.csGRAY, w, h, bytes(out), False)
    doc = pymupdf.open()
    doc.new_page(width=page.rect.width, height=page.rect.height).insert_image(page.rect, stream=pix.tobytes("png"))
    return doc, pix
