from __future__ import annotations

import base64
import io
from dataclasses import dataclass

import pymupdf
from PIL import Image, ImageOps

from .config import Settings


class IngestError(ValueError):
    pass


@dataclass
class PageImage:
    index: int
    png_bytes: bytes
    width: int
    height: int

    def data_url(self) -> str:
        return "data:image/png;base64," + base64.b64encode(self.png_bytes).decode()


_PDF_MAGIC = b"%PDF"


def load_document(data: bytes, filename: str, settings: Settings) -> list[PageImage]:
    if data.startswith(_PDF_MAGIC):
        return _render_pdf(data, settings)
    lower = filename.lower()
    if lower.endswith(".docx"):
        from .docx_render import DocxRenderError, render_docx_to_pdf

        try:
            pdf_bytes = render_docx_to_pdf(data)
        except DocxRenderError as exc:
            raise IngestError(str(exc)) from exc
        return _render_pdf(pdf_bytes, settings)
    if _sniff_image(data):
        return _load_image(data, settings)
    if lower.endswith(".pdf"):
        return _render_pdf(data, settings)
    if lower.endswith((".png", ".jpg", ".jpeg", ".webp")):
        return _load_image(data, settings)
    raise IngestError(
        f"unsupported file type for '{filename}': provide a PDF, DOCX, PNG, JPG, or WEBP document"
    )


def _sniff_image(data: bytes) -> bool:
    return (
        data.startswith(b"\x89PNG")
        or data.startswith(b"\xff\xd8")
        or (data[:4] == b"RIFF" and data[8:12] == b"WEBP")
    )


def _render_pdf(data: bytes, settings: Settings) -> list[PageImage]:
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise IngestError(f"unreadable PDF: {exc}") from exc
    pages: list[PageImage] = []
    limit = min(doc.page_count, settings.max_pages)
    matrix = pymupdf.Matrix(2.2, 2.2)
    try:
        for i in range(limit):
            pix = doc[i].get_pixmap(matrix=matrix, alpha=False)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            pages.append(_to_page(i, _clamp(img, settings.max_image_px)))
    finally:
        doc.close()
    if not pages:
        raise IngestError("PDF contained no renderable pages")
    return pages


def _load_image(data: bytes, settings: Settings) -> list[PageImage]:
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as exc:
        raise IngestError(f"unsupported or corrupt image: {exc}") from exc
    img = ImageOps.exif_transpose(img).convert("RGB")
    return [_to_page(0, _clamp(img, settings.max_image_px))]


def _clamp(img: Image.Image, max_px: int) -> Image.Image:
    w, h = img.size
    longest = max(w, h)
    if longest > max_px:
        scale = max_px / longest
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
    return img


def _to_page(index: int, img: Image.Image) -> PageImage:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return PageImage(index=index, png_bytes=buf.getvalue(), width=img.width, height=img.height)
