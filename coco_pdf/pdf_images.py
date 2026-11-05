"""Movable images: an image placement is the k-th "/Name Do" of the page content stream.

Moving, resizing or rotating rewrites only that placement, so the same image shown elsewhere
(another page, a repeated logo) is left untouched.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

import pymupdf


@dataclass(frozen=True)
class ImageItem:
    page: int
    xref: int
    name: str
    occurrence: int  # index among the placements of this image on the page
    center: pymupdf.Point  # unrotated page space
    width: float
    height: float
    angle: float  # degrees, clockwise on screen
    flipped: bool

    def matrix(self) -> pymupdf.Matrix:
        """Unit square -> unrotated page space (same convention as get_image_info's transform)."""
        sign = -1 if self.flipped else 1
        return (pymupdf.Matrix(self.width * sign, 0, 0, self.height, -self.width * sign / 2, -self.height / 2)
                * pymupdf.Matrix(self.angle) * pymupdf.Matrix(1, 0, 0, 1, self.center.x, self.center.y))

    def contains(self, point: pymupdf.Point) -> bool:
        local = point * ~self.matrix()
        return 0 <= local.x <= 1 and 0 <= local.y <= 1

    def moved(self, center: pymupdf.Point, width: float, height: float, angle: float) -> ImageItem:
        return ImageItem(self.page, self.xref, self.name, self.occurrence, center, width, height, angle % 360,
                         self.flipped)


def _do_pattern(*names: str) -> re.Pattern:
    alternatives = b"|".join(re.escape(n.encode()) for n in names)
    return re.compile(rb"/(" + alternatives + rb")\s+Do\b")


def _content(page: pymupdf.Page) -> bytes:
    return b"\n".join(page.parent.xref_stream(x) or b"" for x in page.get_contents())


def _from_transform(page_index: int, xref: int, name: str, k: int, t: pymupdf.Matrix) -> ImageItem:
    center = pymupdf.Point(0.5, 0.5) * t
    width, height = math.hypot(t.a, t.b), math.hypot(t.c, t.d)
    flipped = t.a * t.d - t.b * t.c < 0
    angle = math.degrees(math.atan2(t.b, t.a)) + (180 if flipped else 0)
    return ImageItem(page_index, xref, name, k, center, width, height, angle % 360, flipped)


def list_images(page: pymupdf.Page) -> list[ImageItem]:
    """Images drawn directly by the page content (not inside a form XObject), topmost last."""
    # Resource name -> xref. One image can be registered under several names (e.g. inserted twice).
    xref_of = {img[7]: img[0] for img in page.get_images(full=True) if img[-1] == 0}
    if not xref_of:
        return []
    used = [m.group(1).decode() for m in _do_pattern(*xref_of).finditer(_content(page))]
    # get_image_info lists placements in drawing order, but its xrefs are guessed from the image digest
    # (identical images all get the same one), so placements are matched to the "Do" operators by order.
    # Images nested in form XObjects break that order: such pages get no movable images.
    infos = page.get_image_info()
    if len(used) != len(infos):
        return []
    items, seen = [], {}
    for name, info in zip(used, infos):
        xref = xref_of[name]
        k = seen.get(xref, 0)
        seen[xref] = k + 1
        items.append(_from_transform(page.number, xref, name, k, pymupdf.Matrix(info["transform"])))
    return items


def _rewrite(page: pymupdf.Page, item: ImageItem, new: ImageItem | None) -> None:
    doc = page.parent
    page.clean_contents()  # single, normalized content stream
    xref = page.get_contents()[0]
    content = doc.xref_stream(xref)
    names = [img[7] for img in page.get_images(full=True) if img[0] == item.xref and img[-1] == 0]
    matches = list(_do_pattern(*names).finditer(content))
    if item.occurrence >= len(matches):
        raise ValueError("Image introuvable dans le contenu de la page")
    match = matches[item.occurrence]
    content = content[:match.start()] + content[match.end():]
    if new is not None:
        # PDF images are drawn bottom-up: flip the unit square vertically before the page transform.
        m = pymupdf.Matrix(1, 0, 0, -1, 0, 1) * new.matrix() * ~page.transformation_matrix
        content += b"\nq %.4f %.4f %.4f %.4f %.4f %.4f cm /%s Do Q\n" % (m.a, m.b, m.c, m.d, m.e, m.f,
                                                                         new.name.encode())
    doc.update_stream(xref, content)


def place(page: pymupdf.Page, item: ImageItem, new: ImageItem) -> None:
    """Redraw the image with its new geometry. It moves to the top of the page's drawing order."""
    _rewrite(page, item, new)


def remove(page: pymupdf.Page, item: ImageItem) -> None:
    _rewrite(page, item, None)


def insert(page: pymupdf.Page, screen_rect: pymupdf.Rect, image: str | bytes) -> None:
    """Insert an image (file path or encoded bytes) in a rect given in screen (rotated) space, upright on screen."""
    source = {"stream": image} if isinstance(image, bytes) else {"filename": image}
    page.insert_image(screen_rect * page.derotation_matrix, keep_proportion=True, rotate=page.rotation, **source)


def png_bytes(doc: pymupdf.Document, xref: int) -> bytes:
    """The image as PNG, with its transparency (soft mask) if it has one."""
    pix = pymupdf.Pixmap(doc, xref)
    smask = doc.xref_get_key(xref, "SMask")
    if smask[0] == "xref":
        pix = pymupdf.Pixmap(pix, pymupdf.Pixmap(doc, int(smask[1].split()[0])))
    if pix.colorspace and pix.colorspace.n not in (1, 3):
        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
    return pix.tobytes("png")
