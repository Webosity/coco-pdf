import pymupdf
import pytest

from coco_pdf import ocr
from coco_pdf.pdf_text import extract_blocks

LETTER = ("Madame, nous vous informons que votre contrat de travail cessera à compter du 31 décembre. "
          "Vos garanties de prévoyance et de frais de santé seront maintenues pendant douze mois.")


@pytest.fixture
def scan_bytes():
    """A typed letter turned into a picture, like a scanned page: no text, one image over the page."""
    typed = pymupdf.open()
    page = typed.new_page()
    page.insert_textbox(pymupdf.Rect(72, 100, 520, 300), LETTER, fontname="tiro", fontsize=12)
    page.insert_textbox(pymupdf.Rect(72, 320, 520, 360), "Nom : ...............................", fontsize=12)
    image = page.get_pixmap(dpi=200).tobytes("png")
    scan = pymupdf.open()
    scan.new_page().insert_image(pymupdf.Rect(0, 0, 595, 842), stream=image)
    return scan.tobytes()


def test_is_scan_with_image_only_page_returns_true(scan_bytes):
    assert ocr.scanned_pages(pymupdf.open("pdf", scan_bytes)) == [0]


def test_is_scan_with_invisible_ocr_layer_returns_true(scan_bytes):
    doc = pymupdf.open("pdf", scan_bytes)
    doc[0].insert_text((72, 120), "hidden searchable layer", render_mode=3)
    assert ocr.is_scan(doc[0])


def test_rebuild_scan_makes_text_editable(scan_bytes):
    data, words = ocr.rebuild(scan_bytes, [0])
    text = " ".join(pymupdf.open("pdf", data)[0].get_text().split())
    assert (words > 20, "contrat de travail cessera" in text, "frais de santé" in text) == (True, True, True)


def test_rebuild_scan_detects_serif_family(scan_bytes):
    data, _ = ocr.rebuild(scan_bytes, [0])
    blocks = extract_blocks(pymupdf.open("pdf", data)[0])
    assert blocks[0].style.family == "Times"


def test_rebuild_scan_drops_dotted_leaders(scan_bytes):
    data, _ = ocr.rebuild(scan_bytes, [0])
    words = [w[4] for w in pymupdf.open("pdf", data)[0].get_text("words")]
    assert not any(ocr.is_junk(w) for w in words)


@pytest.mark.parametrize(("text", "junk"), [
    ("crrorreerrrcrrersecssersrensersrensernrerssen", True),
    ("·..·.:", True),
    ("reconnaissance", False),
    ("complémentaires", False),
    ("intention", False),
])
def test_is_junk_tells_leader_noise_from_words(text, junk):
    assert ocr.is_junk(text) is junk


@pytest.fixture
def invoice_scan():
    """A small invoice scanned at 200 dpi: a coloured logo, a table with ruled cells and a grey header."""
    typed = pymupdf.open()
    page = typed.new_page()
    page.draw_rect(pymupdf.Rect(40, 30, 130, 100), color=None, fill=(0.1, 0.4, 0.9))
    page.draw_circle((85, 65), 25, color=None, fill=(0.95, 0.6, 0.1))
    page.insert_text((150, 60), "Entreprise Martin plomberie", fontname="helv", fontsize=16)
    page.draw_rect(pymupdf.Rect(40, 200, 550, 225), color=None, fill=(0.75, 0.75, 0.75))
    for x in (40, 300, 420, 550):
        page.draw_line((x, 200), (x, 400), width=1)
    for y in (200, 225, 400):
        page.draw_line((40, y), (550, y), width=1)
    page.insert_text((50, 217), "Designation", fontname="hebo", fontsize=11)
    page.insert_text((310, 217), "Quantite", fontname="hebo", fontsize=11)
    page.insert_text((50, 250), "Receveur de douche extra plat", fontname="helv", fontsize=11)
    page.insert_text((310, 250), "1,00", fontname="helv", fontsize=11)
    page.insert_text((430, 250), "603,75", fontname="helv", fontsize=11)
    scan = pymupdf.open()
    scan.new_page().insert_image(pymupdf.Rect(0, 0, 595, 842), stream=page.get_pixmap(dpi=200).tobytes("png"))
    return scan.tobytes()


def test_rebuild_invoice_has_no_background_image(invoice_scan):
    page = pymupdf.open("pdf", ocr.rebuild(invoice_scan, [0])[0])[0]
    assert all(abs(pymupdf.Rect(i["bbox"])) < 0.15 * abs(page.rect) for i in page.get_image_info())


def test_rebuild_invoice_keeps_logo_as_separate_image(invoice_scan):
    page = pymupdf.open("pdf", ocr.rebuild(invoice_scan, [0])[0])[0]
    assert len(page.get_image_info()) == 1


def test_rebuild_invoice_draws_table_rules_and_grey_header(invoice_scan):
    drawings = pymupdf.open("pdf", ocr.rebuild(invoice_scan, [0])[0])[0].get_drawings()
    grey = [d for d in drawings if d.get("fill") and 0.6 < d["fill"][0] < 0.9]
    lines = [d for d in drawings if d["items"] and d["items"][0][0] == "l"]
    assert (len(grey) >= 1, len(lines) >= 6) == (True, True)


def test_rebuild_invoice_text_is_editable(invoice_scan):
    text = " ".join(pymupdf.open("pdf", ocr.rebuild(invoice_scan, [0])[0])[0].get_text().split())
    assert ("Receveur de douche extra plat" in text, "603,75" in text) == (True, True)
