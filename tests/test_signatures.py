import pymupdf
import pytest

from coco_pdf.signatures import SignatureStore


@pytest.fixture
def scan(tmp_path):
    """A 'scanned' signature: black ink stroke on a white sheet with a wide blank margin."""
    path = tmp_path / "scan.png"
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 400, 200), False)
    pix.set_rect(pix.irect, (255, 255, 255))
    pix.set_rect(pymupdf.IRect(100, 80, 300, 120), (20, 20, 20))
    pix.save(path)
    return path


@pytest.fixture
def store(tmp_path):
    return SignatureStore(tmp_path / "bank")


def test_add_with_transparent_background_crops_to_ink(store, scan):
    signature = store.add(scan, "Signature simple")
    pix = pymupdf.Pixmap(str(store.path(signature)))
    assert (pix.alpha, pix.width, pix.height) == (1, 208, 48)


def test_add_with_transparent_background_makes_paper_transparent(store, scan):
    pix = pymupdf.Pixmap(str(store.path(store.add(scan, "s"))))
    assert (pix.pixel(0, 0)[3], pix.pixel(104, 24)[3]) == (0, 255)


def test_add_without_transparency_keeps_image(store, scan):
    pix = pymupdf.Pixmap(str(store.path(store.add(scan, "s", transparent=False))))
    assert (pix.alpha, pix.width) == (0, 400)


def test_list_persists_between_store_instances(store, scan, tmp_path):
    store.add(scan, "Lu et approuvé")
    assert [s.name for s in SignatureStore(tmp_path / "bank").list()] == ["Lu et approuvé"]


def test_remove_deletes_entry_and_file(store, scan):
    signature = store.add(scan, "s")
    store.remove(signature.id)
    assert (store.list(), store.path(signature).exists()) == ([], False)


def test_move_up_reorders(store, scan):
    store.add(scan, "a")
    b = store.add(scan, "b")
    store.move(b.id, -1)
    assert [s.name for s in store.list()] == ["b", "a"]


def test_rename_changes_name(store, scan):
    signature = store.add(scan, "a")
    store.rename(signature.id, "Bon pour accord")
    assert store.list()[0].name == "Bon pour accord"
