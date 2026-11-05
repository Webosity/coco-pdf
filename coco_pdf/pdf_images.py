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


REFERENCE = re.compile(r"/([^\s/<>\[\]()]+)\s+(\d+)\s+0\s+R")
MAX_DEPTH = 8


def _xobjects(doc: pymupdf.Document, owner: int) -> dict[str, int]:
    """Resource name -> xref of the XObjects (images and forms) a form XObject can draw."""
    kind, value = doc.xref_get_key(owner, "Resources/XObject")
    if kind == "xref":
        value = doc.xref_object(int(value.split()[0]))
    return {name: int(x) for name, x in REFERENCE.findall(value)} if kind in ("dict", "xref") else {}


def _images_in_form(doc: pymupdf.Document, form: int, depth: int = 0) -> int:
    """How many image placements a form XObject draws, nested forms included (in get_image_info's sense)."""
    if depth > MAX_DEPTH:
        return 0
    names = _xobjects(doc, form)
    if not names:
        return 0
    count = 0
    for match in _do_pattern(*names).finditer(doc.xref_stream(form) or b""):
        xref = names[match.group(1).decode()]
        if doc.xref_get_key(xref, "Subtype")[1] == "/Image":
            count += 1
        else:
            count += _images_in_form(doc, xref, depth + 1)
    return count


def list_images(page: pymupdf.Page) -> list[ImageItem]:
    """Images drawn directly by the page content, topmost last. Images inside form XObjects (often a
    logo in a header) are not movable, but no longer prevent the others from being found."""
    doc = page.parent
    # Resource name -> xref. One image can be registered under several names (e.g. inserted twice).
    image_xref = {img[7]: img[0] for img in page.get_images(full=True) if img[-1] == 0}
    form_xref = {f[1]: f[0] for f in page.get_xobjects() if f[2] == 0}
    if not image_xref:
        return []
    # get_image_info lists placements in drawing order, but its xrefs are guessed from the image digest
    # (identical images all get the same one): placements are matched to the "Do" operators by order,
    # a form standing for all the images it draws.
    infos = page.get_image_info()
    items, seen, position = [], {}, 0
    for match in _do_pattern(*image_xref, *form_xref).finditer(_content(page)):
        name = match.group(1).decode()
        if name not in image_xref:
            position += _images_in_form(doc, form_xref[name])
            continue
        if position >= len(infos):
            return []  # inconsistent count (e.g. inline images): better none than a wrong one
        xref = image_xref[name]
        k = seen.get(xref, 0)
        seen[xref] = k + 1
        items.append(_from_transform(page.number, xref, name, k, pymupdf.Matrix(infos[position]["transform"])))
        position += 1
    return items if position == len(infos) else []


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
