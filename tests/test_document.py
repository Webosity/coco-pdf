import pymupdf
import pytest

from coco_pdf.document import PdfDocument
from coco_pdf.pdf_text import TextStyle


@pytest.fixture
def sample(tmp_path):
    path = tmp_path / "sample.pdf"
    doc = pymupdf.open()
    for n in range(3):
        page = doc.new_page()
        page.insert_text((72, 100), f"Page {n + 1} Bonjour", fontname="tibo", fontsize=14)
    widget = pymupdf.Widget()
    widget.field_name = "nom"
    widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
    widget.rect = pymupdf.Rect(72, 200, 300, 220)
    doc[0].add_widget(widget)
    doc.save(path)
    return path


def page_texts(pdf):
    return [pdf.page(i).get_text().strip() for i in range(pdf.page_count)]


def test_undo_after_delete_restores_page(sample):
    pdf = PdfDocument(sample)
    pdf.delete_pages([1])
    pdf.undo()
    assert pdf.page_count == 3


def test_redo_after_undo_reapplies_change(sample):
    pdf = PdfDocument(sample)
    pdf.delete_pages([1])
    pdf.undo()
    pdf.redo()
    assert pdf.page_count == 2


def test_reorder_with_reversed_order_reverses_pages(sample):
    pdf = PdfDocument(sample)
    pdf.reorder([2, 1, 0])
    assert page_texts(pdf)[0].startswith("Page 3")


def test_rotate_pages_accumulates_angle(sample):
    pdf = PdfDocument(sample)
    pdf.rotate_pages([0], 90)
    pdf.rotate_pages([0], 270)
    assert pdf.page(0).rotation == 0


def test_delete_all_pages_is_refused(sample):
    with pytest.raises(ValueError):
        PdfDocument(sample).delete_pages([0, 1, 2])


def test_insert_pdf_appends_pages(sample):
    pdf = PdfDocument(sample)
    pdf.insert_pdf(sample, at=pdf.page_count)
    assert pdf.page_count == 6


def test_split_every_two_pages_creates_two_files(sample, tmp_path):
    files = PdfDocument(sample).split(tmp_path, every=2)
    assert [pymupdf.open(f).page_count for f in files] == [2, 1]


def test_save_overwrites_opened_file(sample):
    pdf = PdfDocument(sample)
    pdf.add_text_box(0, pymupdf.Rect(72, 300, 300, 320), "Ajout", TextStyle())
    pdf.save()
    assert "Ajout" in pymupdf.open(sample)[0].get_text()


def test_compressed_save_produces_valid_pdf(sample, tmp_path):
    out = tmp_path / "small.pdf"
    PdfDocument(sample).save(out, compress=True)
    assert pymupdf.open(out).page_count == 3


def test_set_field_values_fills_text_field(sample):
    pdf = PdfDocument(sample)
    field = pdf.form_fields()[0]
    pdf.set_field_values({(0, field.xref): "Dupont"})
    assert pdf.form_fields()[0].value == "Dupont"
