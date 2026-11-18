"""Render an equation *image from the original PDF* by printed equation number.

The OCR/text layer cannot restore source mathematics. This is a review crop,
not a transcription, equation identity proof or LaTeX extraction.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

import pymupdf


def _clean_pdf_text(text: str) -> str:
    """Make private-use font glyphs visibly auditable, never silently fake math."""
    # Common Symbol/MathType private-use glyphs are not reliably decodable by
    # PyMuPDF. Preserve an explicit text marker instead of rendering a box;
    # the source-PDF screenshot remains the visual authority.
    text = re.sub(r"[\uf000-\uf8ff\ufffd]", "[未解码符号]", text)
    return text


def equation_source_region(pdf_path: Path, page_no: int, number: int):
    """Source PDF text geometry; text remains lossy if embedded fonts are bad."""
    if type(page_no) is not int or type(number) is not int or not 1 <= number <= 999:
        raise ValueError("公式页码或编号无效")
    with pymupdf.open(str(pdf_path)) as doc:
        if not 1 <= page_no <= len(doc):
            raise ValueError("公式页码无效")
        page = doc[page_no - 1]
        blocks = [
            (pymupdf.Rect(b[:4]), b[4]) for b in page.get_text("blocks")
            if len(b) > 6 and b[6] == 0
        ]
        marker = re.compile(rf"\(\s*{number}\s*\)\s*$")
        candidates = [
            (rect, text) for rect, text in blocks
            if marker.search(text.strip())
            and not re.search(r"\b(?:eqs?|equations?)\.?\s*\(\s*"
                              + str(number) + r"\s*\)\s*$", text, re.I)
        ]
        if not candidates:
            raise ValueError("原始 PDF 页中没有可定位的该编号公式；请打开整页核对")
        label, _ = min(candidates, key=lambda item: (
            abs(item[0].x1 - (page.rect.width / 2)), item[0].y0))
        # Include formula segments split into adjacent PDF text blocks.
        # Restrict to label's column and same horizontal band; never reach
        # across page columns or vertically into unrelated captions.
        column_right = page.rect.width / 2 + 7 \
            if label.x0 < page.rect.width / 2 else page.rect.width - 28
        column_left = 28 if label.x0 < page.rect.width / 2 \
            else page.rect.width / 2 - 7
        band_top, band_bottom = label.y0 - 13, label.y1 + 9
        neighboring = [
            rect for rect, _ in blocks
            if rect.x0 >= column_left and rect.x1 <= column_right
            and rect.y0 <= band_bottom and rect.y1 >= band_top
            and rect.height < 42
        ]
        if not neighboring:
            neighboring = [label]
        region = pymupdf.Rect(
            max(column_left, min(rect.x0 for rect in neighboring) - 11),
            max(0, min(rect.y0 for rect in neighboring) - 9),
            min(column_right, max(rect.x1 for rect in neighboring) + 11),
            min(page.rect.height, max(rect.y1 for rect in neighboring) + 9),
        ) & page.rect
        if region.is_empty or region.width < 20 or region.height < 10:
            raise ValueError("编号公式的 PDF 定位框无效")
        ordered = sorted(
            ((rect, text) for rect, text in blocks
             if rect in neighboring),
            key=lambda item: (item[0].x0, item[0].y0),
        )
        extracted = " ".join(
            _clean_pdf_text(" ".join(text.split())) for _, text in ordered
        )
        return (
            [round(v, 1) for v in region], extracted[:340],
        )


def original_equation_crop(pdf_path: Path, page_no: int, number: int):
    region, _ = equation_source_region(pdf_path, page_no, number)
    with pymupdf.open(str(pdf_path)) as doc:
        page = doc[page_no - 1]
        bitmap = page.get_pixmap(
            matrix=pymupdf.Matrix(2.5, 2.5),
            clip=pymupdf.Rect(region), alpha=False,
        )
    return bitmap.tobytes("png"), region
