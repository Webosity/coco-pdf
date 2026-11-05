"""Find the installed Windows font matching a PDF font name, so edited text keeps its original font.

Fonts embedded in PDFs are usually subsets (only the glyphs already used), so they cannot be reused
for new text: the full font is looked up among the system fonts instead.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import pymupdf

FONT_DIRS = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts",
             Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts"]
CACHE_FILE = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Coco PDF" / "fonts.json"
STYLE_WORDS = ("bold", "italic", "oblique", "regular")  # not "roman": "Times New Roman" is a family

# Standard PDF fonts, always available, with the Windows font used to preview them.
BASE14 = {
    "Helvetica": ({(False, False): "helv", (True, False): "hebo", (False, True): "heit", (True, True): "hebi"}, "Arial"),
    "Times": ({(False, False): "tiro", (True, False): "tibo", (False, True): "tiit", (True, True): "tibi"},
              "Times New Roman"),
    "Courier": ({(False, False): "cour", (True, False): "cobo", (False, True): "coit", (True, True): "cobi"},
                "Courier New"),
}
COMMON_FAMILIES = ("Arial", "Calibri", "Cambria", "Georgia", "Segoe UI", "Tahoma", "Times New Roman", "Verdana")


@dataclass(frozen=True)
class FontChoice:
    path: str | None  # system font file, or None for a Base-14 font
    base14: str | None
    exact: bool  # False when the requested family or style is not installed


def normalize(name: str) -> str:
    name = re.sub(r"^[A-Z]{6}\+", "", name)  # subset prefix, e.g. "ABCDEF+Calibri"
    name = re.sub(r"(PS)?MT$", "", name)  # "Arial-BoldMT", "TimesNewRomanPSMT"
    name = re.sub(r"PS(?=[-,])", "", name)
    key = re.sub(r"[^a-z0-9]", "", name.lower())
    return key.replace("regular", "")


def split_style(full_name: str) -> tuple[str, bool, bool]:
    """'Calibri Bold Italic' -> ('Calibri', True, True)."""
    words = full_name.split()
    while len(words) > 1 and words[-1].lower() in STYLE_WORDS:
        words.pop()
    lower = full_name.lower()
    return " ".join(words), "bold" in lower, "italic" in lower or "oblique" in lower


def _signature() -> list:
    return [[str(d), len(os.listdir(d)), os.stat(d).st_mtime] for d in FONT_DIRS if d.is_dir()]


@cache
def system_fonts() -> dict[str, str]:
    """Full font name (e.g. 'Calibri Bold') -> file path. Cached on disk, rebuilt when a font folder changes."""
    signature = _signature()
    try:
        cached = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        if cached["signature"] == signature:
            return cached["fonts"]
    except (OSError, ValueError, KeyError):
        pass
    fonts = {}
    for folder in FONT_DIRS:
        if not folder.is_dir():
            continue
        for path in sorted(folder.iterdir()):
            if path.suffix.lower() not in (".ttf", ".otf", ".ttc"):
                continue
            try:
                fonts.setdefault(pymupdf.Font(fontfile=str(path)).name, str(path))
            except RuntimeError:
                continue
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps({"signature": signature, "fonts": fonts}), encoding="utf-8")
    except OSError:
        pass
    return fonts


@cache
def _families() -> dict[str, dict[tuple[bool, bool], str]]:
    families: dict[str, dict[tuple[bool, bool], str]] = {}
    for full_name, path in system_fonts().items():
        family, bold, italic = split_style(full_name)
        families.setdefault(family, {}).setdefault((bold, italic), path)
    return families


@cache
def _by_normalized_name() -> dict[str, tuple[str, bool, bool]]:
    return {normalize(name): split_style(name) for name in system_fonts()}


def identify(pdf_font_name: str, flags: int) -> tuple[str, bool, bool]:
    """Family and style of a PDF font: the installed family when found, else the closest Base-14 family."""
    found = _by_normalized_name().get(normalize(pdf_font_name))
    if found:
        return found
    name = pdf_font_name.lower()
    bold = bool(flags & pymupdf.TEXT_FONT_BOLD) or "bold" in name
    italic = bool(flags & pymupdf.TEXT_FONT_ITALIC) or "italic" in name or "oblique" in name
    if flags & pymupdf.TEXT_FONT_MONOSPACED or "courier" in name or "mono" in name:
        return "Courier", bold, italic
    if flags & pymupdf.TEXT_FONT_SERIFED or "times" in name:
        return "Times", bold, italic
    return "Helvetica", bold, italic


def resolve(family: str, bold: bool, italic: bool) -> FontChoice:
    if family in BASE14:
        return FontChoice(None, BASE14[family][0][(bold, italic)], True)
    variants = _families().get(family)
    if not variants:
        return FontChoice(None, BASE14["Helvetica"][0][(bold, italic)], False)
    path = variants.get((bold, italic))
    if path:
        return FontChoice(path, None, True)
    # Requested style not installed: fall back to the regular face of the same family.
    return FontChoice(variants.get((False, False)) or next(iter(variants.values())), None, False)


def available_families(extra: str | None = None) -> list[str]:
    installed = [f for f in COMMON_FAMILIES if f in _families()]
    families = ([extra] if extra else []) + installed + list(BASE14)
    return list(dict.fromkeys(families))


def all_families() -> list[str]:
    return sorted(_families())


def preview_family(family: str) -> str:
    """Windows font family Qt should use to preview a family (Base-14 fonts map to their Windows twins)."""
    return BASE14[family][1] if family in BASE14 else family
