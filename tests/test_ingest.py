from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from app.config import Settings
from app.ingest import IngestError, load_document

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture()
def settings(tmp_path) -> Settings:
    return Settings(db_path=tmp_path / "db.sqlite", max_pages=5, max_image_px=2000)


def test_pdf_fixture_ingests_to_page_images(settings):
    data = (FIXTURES / "layout_a_classic_invoice.pdf").read_bytes()
    pages = load_document(data, "layout_a_classic_invoice.pdf", settings)
    assert len(pages) == 1
    assert pages[0].index == 0
    assert pages[0].width > 500
    assert pages[0].png_bytes.startswith(b"\x89PNG")


def test_receipt_pdf_ingests(settings):
    data = (FIXTURES / "layout_b_receipt_style.pdf").read_bytes()
    pages = load_document(data, "layout_b_receipt_style.pdf", settings)
    assert len(pages) == 1


def test_jpeg_image_ingests(settings):
    img = Image.new("RGB", (900, 1200), color=(240, 240, 240))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    pages = load_document(buf.getvalue(), "photo.jpg", settings)
    assert len(pages) == 1
    assert pages[0].height <= 2000


def test_oversized_image_is_downscaled(settings):
    s = Settings(db_path=settings.db_path, max_image_px=400)
    img = Image.new("RGB", (3000, 1000))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    page = load_document(buf.getvalue(), "big.png", s)[0]
    assert max(page.width, page.height) == 400


def test_text_file_rejected(settings):
    with pytest.raises(IngestError) as excinfo:
        load_document(b"vendor: acme\ntotal: 10", "invoice.txt", settings)
    assert "unsupported file type" in str(excinfo.value)


def test_corrupt_pdf_rejected(settings):
    with pytest.raises(IngestError):
        load_document(b"%PDF-1.4 garbage not a real pdf", "broken.pdf", settings)


def test_degraded_photo_fixture_ingests(settings):
    data = (FIXTURES / "layout_b_receipt_degraded.jpg").read_bytes()
    pages = load_document(data, "layout_b_receipt_degraded.jpg", settings)
    assert len(pages) == 1


def test_docx_fixture_renders_to_page_images(settings):
    data = (FIXTURES / "layout_c_word_invoice.docx").read_bytes()
    pages = load_document(data, "layout_c_word_invoice.docx", settings)
    assert len(pages) >= 1
    assert pages[0].png_bytes.startswith(b"\x89PNG")


def test_corrupt_docx_rejected(settings):
    with pytest.raises(IngestError) as excinfo:
        load_document(b"PK\x03\x04 not a real docx payload", "fake.docx", settings)
    assert "unreadable .docx" in str(excinfo.value)
