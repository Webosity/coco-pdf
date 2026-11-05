"""Signature bank: images kept between sessions in %LOCALAPPDATA%\\Coco PDF\\signatures.

Imported images are copied into the bank, so the original file can be moved or deleted afterwards.
"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

import pymupdf

DEFAULT_ROOT = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Coco PDF" / "signatures"
MAX_WIDTH = 1600  # px: more is useless for a signature and bloats the PDF
WHITE, INK = 235, 160  # luminance: above WHITE fully transparent, below INK fully opaque


@dataclass
class Signature:
    id: str
    name: str
    file: str  # file name inside the bank folder


def _white_to_alpha(pix: pymupdf.Pixmap) -> pymupdf.Pixmap:
    """Paper becomes transparent, ink stays opaque, with a soft edge in between (anti-aliasing)."""
    rgb = pix if pix.colorspace and pix.colorspace.n == 3 else pymupdf.Pixmap(pymupdf.csRGB, pix)
    gray = pymupdf.Pixmap(pymupdf.csGRAY, rgb)
    table = bytes(0 if v >= WHITE else 255 if v <= INK else round(255 * (WHITE - v) / (WHITE - INK))
                  for v in range(256))
    out = pymupdf.Pixmap(rgb, 1)
    out.set_alpha(gray.samples.translate(table))
    return out


def _crop_to_ink(pix: pymupdf.Pixmap) -> pymupdf.Pixmap:
    alpha = pix.samples[pix.n - 1::pix.n]
    w, h = pix.width, pix.height
    rows = [alpha[y * w:(y + 1) * w] for y in range(h)]
    inked = [y for y, row in enumerate(rows) if row.strip(b"\0")]
    if not inked:
        return pix
    left = min(len(row) - len(row.lstrip(b"\0")) for row in rows if row.strip(b"\0"))
    right = max(len(row.rstrip(b"\0")) for row in rows if row.strip(b"\0"))
    margin = 4
    box = pymupdf.IRect(max(left - margin, 0), max(inked[0] - margin, 0), min(right + margin, w),
                        min(inked[-1] + 1 + margin, h))
    cropped = pymupdf.Pixmap(pix.colorspace, box, True)
    cropped.copy(pix, box)
    cropped.set_origin(0, 0)
    return cropped


def prepare(source: str | Path, transparent: bool) -> pymupdf.Pixmap:
    pix = pymupdf.Pixmap(str(source))
    if pix.width > MAX_WIDTH:
        pix = pymupdf.Pixmap(pix, MAX_WIDTH, round(pix.height * MAX_WIDTH / pix.width), None)
    if pix.alpha:
        return _crop_to_ink(pix)
    if transparent:
        return _crop_to_ink(_white_to_alpha(pix))
    return pix if pix.colorspace.n in (1, 3) else pymupdf.Pixmap(pymupdf.csRGB, pix)


class SignatureStore:
    def __init__(self, root: str | Path = DEFAULT_ROOT):
        self.root = Path(root)
        self.index = self.root / "signatures.json"

    def list(self) -> list[Signature]:
        try:
            items = [Signature(**item) for item in json.loads(self.index.read_text(encoding="utf-8"))]
        except (OSError, ValueError, TypeError):
            return []
        return [s for s in items if self.path(s).exists()]

    def path(self, signature: Signature) -> Path:
        return self.root / signature.file

    def _save(self, items: list[Signature]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.index.write_text(json.dumps([asdict(s) for s in items], ensure_ascii=False, indent=1),
                              encoding="utf-8")

    def add(self, source: str | Path, name: str, transparent: bool = True) -> Signature:
        self.root.mkdir(parents=True, exist_ok=True)
        signature = Signature(uuid.uuid4().hex[:12], name, "")
        signature.file = f"{signature.id}.png"
        prepare(source, transparent).save(str(self.path(signature)))
        self._save([*self.list(), signature])
        return signature

    def rename(self, signature_id: str, name: str) -> None:
        items = self.list()
        for s in items:
            if s.id == signature_id:
                s.name = name
        self._save(items)

    def remove(self, signature_id: str) -> None:
        items = self.list()
        for s in items:
            if s.id == signature_id:
                self.path(s).unlink(missing_ok=True)
        self._save([s for s in items if s.id != signature_id])

    def move(self, signature_id: str, delta: int) -> None:
        items = self.list()
        index = next((i for i, s in enumerate(items) if s.id == signature_id), None)
        if index is None:
            return
        target = min(max(index + delta, 0), len(items) - 1)
        items.insert(target, items.pop(index))
        self._save(items)
