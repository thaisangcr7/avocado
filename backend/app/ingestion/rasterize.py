"""Rendering PDF pages to images, for documents that carry no extractable text.

A scanned PDF is a stack of photographs. `pypdfium2` renders each page to a
bitmap so the vision model can read it, which recovers documents that would
otherwise ingest as empty and be invisible to retrieval.

Rendered with `pypdfium2` rather than PyMuPDF specifically because of licensing
— PyMuPDF is AGPL, which would propagate to this project, while pypdfium2 is
BSD/Apache.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from app.core.errors import ValidationError

# 150 DPI is the point where scanned text becomes reliably legible without the
# image size growing faster than the accuracy does.
DEFAULT_SCALE = 150 / 72


@dataclass(slots=True)
class RenderedPage:
    page_number: int
    png_bytes: bytes


def render_pdf_pages(
    data: bytes, *, max_pages: int = 20, scale: float = DEFAULT_SCALE
) -> list[RenderedPage]:
    """Render the first `max_pages` pages to PNG.

    Bounded deliberately: every page becomes a vision call, so an unbounded
    render turns one upload into an unbounded bill. Callers record how many
    pages were skipped so the omission is visible rather than silent.
    """
    import pypdfium2 as pdfium

    try:
        document = pdfium.PdfDocument(data)
    except Exception as exc:
        raise ValidationError("Could not open this PDF for rendering.") from exc

    pages: list[RenderedPage] = []
    try:
        for index in range(min(len(document), max_pages)):
            page = document[index]
            bitmap = page.render(scale=scale)
            image = bitmap.to_pil()

            buffer = io.BytesIO()
            image.save(buffer, format="PNG", optimize=True)
            pages.append(RenderedPage(page_number=index + 1, png_bytes=buffer.getvalue()))
    finally:
        document.close()

    return pages


def page_count(data: bytes) -> int:
    import pypdfium2 as pdfium

    try:
        document = pdfium.PdfDocument(data)
    except Exception:
        return 0
    try:
        return len(document)
    finally:
        document.close()
