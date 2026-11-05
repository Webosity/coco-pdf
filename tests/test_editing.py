from pathlib import Path

import pymupdf
import pytest

from coco_pdf import fonts
from coco_pdf.document import PdfDocument

CALIBRI = Path(r"C:\Windows\Fonts\calibri.ttf")
needs_calibri = pytest.mark.skipif(not CALIBRI.exists(), reason="Calibri not installed")


@pytest.fixture
def calibri_pdf(tmp_path):
    """A paragraph in an embedded *subset* Calibri, like PDFs exported from Word."""
    path = tmp_path / "calibri.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_font(fontname="F0", fontfile=str(CALIBRI))
    page.insert_textbox(pymupdf.Rect(72, 72, 300, 300), "Bonjour Coco, ceci est un paragraphe assez long pour "
                        "occuper plusieurs lignes dans la page.", fontname="F0", fontsize=14)
    doc.subset_fonts()
    doc.save(path)
    return path


@pytest.fixture
def image_pdf(tmp_path):
    """The same image shown on two pages."""
    image = tmp_path / "img.png"
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 20), False)
    pix.set_rect(pix.irect, (255, 0, 0))
    pix.save(image)
    path = tmp_path / "images.pdf"
    doc = pymupdf.open()
    for _ in range(2):
        doc.new_page(width=400, height=400)
    for page in doc:
        page.insert_image(pymupdf.Rect(50, 50, 170, 110), filename=str(image))
    doc.save(path)
    return path


@pytest.mark.parametrize(("pdf_name", "expected"), [
    ("YGKZTE+Calibri Regular", ("Calibri", False, False)),
    ("Arial-BoldMT", ("Arial", True, False)),
    ("TimesNewRomanPS-BoldItalicMT", ("Times New Roman", True, True)),
])
def test_identify_with_pdf_font_name_finds_installed_family(pdf_name, expected):
    if not fonts.resolve(expected[0], False, False).exact:
        pytest.skip(f"{expected[0]} not installed")
    assert fonts.identify(pdf_name, 0) == expected


def test_identify_with_unknown_font_falls_back_to_base14():
    assert fonts.identify("NoSuchFont-Bold", 0) == ("Helvetica", True, False)


@needs_calibri
def test_block_at_returns_whole_paragraph_with_original_font(calibri_pdf):
    block = PdfDocument(calibri_pdf).block_at(0, pymupdf.Point(80, 80))
    assert (block.style.family, block.text.startswith("Bonjour Coco"), block.text.endswith("la page.")) == (
        "Calibri", True, True)


@needs_calibri
def test_replace_block_keeps_original_font(calibri_pdf):
    pdf = PdfDocument(calibri_pdf)
    block = pdf.block_at(0, pymupdf.Point(80, 80))
    pdf.replace_block(block, "Texte entièrement nouveau : àéèùç €", block.style)
    fonts_used = {s["font"] for b in pdf.page(0).get_text("dict")["blocks"] for ln in b["lines"] for s in ln["spans"]}
    assert fonts_used == {"Calibri"}


@needs_calibri
def test_save_after_font_insert_subsets_font(calibri_pdf, tmp_path):
    pdf = PdfDocument(calibri_pdf)
    block = pdf.block_at(0, pymupdf.Point(80, 80))
    pdf.replace_block(block, "Court", block.style)
    pdf.save(tmp_path / "out.pdf")
    assert (tmp_path / "out.pdf").stat().st_size < 200_000


def test_move_image_changes_only_that_placement(image_pdf):
    pdf = PdfDocument(image_pdf)
    item = pdf.image_at(0, pymupdf.Point(100, 80))
    pdf.move_image(item, item.moved(pymupdf.Point(250, 250), 60, 30, 0))
    moved = pdf.page(0).get_image_info()[0]["bbox"]
    other = pdf.page(1).get_image_info()[0]["bbox"]
    assert (pymupdf.Rect(moved), pymupdf.Rect(other)) == (pymupdf.Rect(220, 235, 280, 265),
                                                           pymupdf.Rect(50, 50, 170, 110))


def test_move_image_with_angle_is_reported_back(image_pdf):
    pdf = PdfDocument(image_pdf)
    item = pdf.image_at(0, pymupdf.Point(100, 80))
    new = pdf.move_image(item, item.moved(item.center, item.width, item.height, 30))
    assert (round(new.angle), round(new.width), round(new.height)) == (30, 120, 60)


def test_delete_image_removes_it_from_page(image_pdf):
    pdf = PdfDocument(image_pdf)
    pdf.delete_image(pdf.image_at(0, pymupdf.Point(100, 80)))
    assert (len(pdf.page(0).get_image_info()), len(pdf.page(1).get_image_info())) == (0, 1)


def test_add_image_on_rotated_page_returns_selectable_item(image_pdf, tmp_path):
    pdf = PdfDocument(image_pdf)
    pdf.rotate_pages([1], 90)
    item = pdf.add_image(1, pymupdf.Rect(200, 200, 280, 240), tmp_path / "img.png")
    assert item is not None


@needs_calibri
def test_replace_block_keeps_line_pitch(calibri_pdf):
    pdf = PdfDocument(calibri_pdf)
    block = pdf.block_at(0, pymupdf.Point(80, 80))
    pdf.replace_block(block, block.text, block.style.with_(bold=True))
    new = pdf.block_at(0, pymupdf.Point(80, 80))
    assert abs(new.style.lineheight - block.style.lineheight) < 0.05
