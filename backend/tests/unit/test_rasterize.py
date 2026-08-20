"""Rendering PDF pages to images.

The path that matters is a scanned PDF: pages present, no text layer. Without
rendering, such a document ingests as empty and is invisible to retrieval —
which reads to the user as the upload simply not working.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.core.errors import ValidationError
from app.ingestion.parsers import parse_pdf
from app.ingestion.rasterize import page_count, render_pdf_pages


def build_scanned_pdf(pages: int = 3) -> bytes:
    """A PDF whose pages are images — exactly what a scanner produces.

    Built by placing rendered images into PDF pages with no text layer, so
    `extract_text` finds nothing.
    """
    images = []
    for index in range(pages):
        image = Image.new("RGB", (600, 800), "white")
        # Some non-white content, so the page is not blank.
        for x in range(50, 550):
            for y in range(100 + index * 20, 120 + index * 20):
                image.putpixel((x, y), (0, 0, 0))
        images.append(image)

    buffer = io.BytesIO()
    images[0].save(buffer, format="PDF", save_all=True, append_images=images[1:])
    return buffer.getvalue()


def test_a_scanned_pdf_has_pages_but_no_text():
    """The precondition the fallback keys off."""
    parsed = parse_pdf(build_scanned_pdf(2), "scan.pdf")

    assert parsed.page_count == 2
    assert parsed.text_blocks == []
    assert parsed.metadata["likely_scanned"] is True


def test_a_text_pdf_is_not_flagged_as_scanned(tmp_path):
    from reportlab.pdfgen import canvas

    path = tmp_path / "text.pdf"
    pdf = canvas.Canvas(str(path))
    pdf.drawString(100, 700, "This page has a real text layer.")
    pdf.save()

    parsed = parse_pdf(path.read_bytes(), "text.pdf")
    assert parsed.metadata["likely_scanned"] is False
    assert "real text layer" in parsed.text_blocks[0].content


def test_pages_render_to_pngs():
    pages = render_pdf_pages(build_scanned_pdf(3))

    assert len(pages) == 3
    assert [p.page_number for p in pages] == [1, 2, 3]
    for page in pages:
        assert page.png_bytes.startswith(b"\x89PNG")
        # Actually decodable, not just PNG-shaped.
        assert Image.open(io.BytesIO(page.png_bytes)).size[0] > 0


def test_rendering_is_bounded():
    """Every page becomes a vision call, so an unbounded render turns one
    upload into an unbounded bill."""
    pages = render_pdf_pages(build_scanned_pdf(10), max_pages=4)
    assert len(pages) == 4
    assert [p.page_number for p in pages] == [1, 2, 3, 4]


def test_page_count_reads_the_document():
    assert page_count(build_scanned_pdf(5)) == 5


def test_a_corrupt_pdf_is_rejected_clearly():
    with pytest.raises(ValidationError, match="Could not open"):
        render_pdf_pages(b"not a pdf at all")


def test_page_count_of_a_corrupt_pdf_is_zero():
    assert page_count(b"not a pdf") == 0
