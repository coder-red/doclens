from __future__ import annotations

import io

from docx import Document as DocxDocument
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import mm
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas as rl_canvas


class DocxRenderError(ValueError):
    pass


_MARGIN = 18 * mm
_FONT = "Helvetica"
_SIZE = 9.5
_LEAD = 12
_TABLE_SEP = "   |   "


def render_docx_to_pdf(data: bytes) -> bytes:
    try:
        doc = DocxDocument(io.BytesIO(data))
    except Exception as exc:
        raise DocxRenderError(f"unreadable .docx: {exc}") from exc

    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=letter)
    width, height = letter
    y = height - _MARGIN

    def new_page() -> None:
        nonlocal y
        c.showPage()
        y = height - _MARGIN

    def draw(text: str, bold: bool) -> None:
        nonlocal y
        font = "Helvetica-Bold" if bold else _FONT
        size = _SIZE + (1.5 if bold else 0)
        c.setFont(font, size)
        for line in simpleSplit(text, font, size, width - 2 * _MARGIN):
            if y < _MARGIN + _LEAD:
                new_page()
            c.drawString(_MARGIN, y, line)
            y -= _LEAD * (1.25 if bold else 1.0)

    for block in _iter_blocks(doc):
        if isinstance(block, Paragraph):
            text = block.text.strip()
            if not text:
                y -= _LEAD * 0.6
                continue
            bold = any(r.bold for r in block.runs if r.bold is not None) or (
                block.style is not None and block.style.name.startswith("Heading")
            )
            draw(text, bold)
        elif isinstance(block, Table):
            for row in block.rows:
                cells = [(cell.text or "").strip() for cell in row.cells]
                draw(_TABLE_SEP.join(cells), False)
            y -= _LEAD * 0.5

    c.save()
    return buf.getvalue()


def _iter_blocks(doc: DocxDocument):
    body = doc.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, doc)
        elif child.tag == qn("w:tbl"):
            yield Table(child, doc)
