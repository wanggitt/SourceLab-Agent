"""On-demand, conservative PDF layout inspection; candidates are not LaTeX."""

from __future__ import annotations

import re
import io
from pathlib import Path

import pymupdf

MAX_TABLE_ROWS = 15
MAX_TABLE_COLS = 12
MAX_CANDIDATES = 30
MAX_VISUALS = 8


def inspect_page(pdf_path: Path, page_no: int):
    """Locate captions/equation labels; parse tables when PyMuPDF supports it.

    All rectangles are PDF page coordinates, and text is copied from this
    particular physical page. No model-generated transcription is returned.
    """
    with pymupdf.open(str(pdf_path)) as doc:
        if not 1 <= page_no <= len(doc):
            raise ValueError("页码不存在")
        page = doc[page_no - 1]
        blocks = page.get_text("blocks", sort=True)
        candidates = []
        for x0, y0, x1, y1, text, *_ in blocks:
            clean = " ".join(text.split())
            if not clean:
                continue
            caption = re.match(r"(?i)^(figure|fig\.?|table)\s*(\d{1,3})\s*[:.]\s*",
                               clean)
            if caption:
                kind = "table_caption" if caption.group(1).lower() == "table" else "figure_caption"
                candidates.append({
                    "type": kind, "label": f"{caption.group(1)} {caption.group(2)}",
                    "page_no": page_no, "excerpt": clean[:500],
                    "bbox": [round(v, 1) for v in (x0, y0, x1, y1)],
                    "confidence": "caption_pattern",
                })
            if (
                not caption and len(clean) < 210
                and re.search(r"\(\s*\d{1,2}\s*\)\s*$", clean)
                and (re.search(r"[=∑√×±−÷∈≤≥∂α-ωΑ-Ω]", clean)
                     or clean.count("(") >= 2)
            ):
                candidates.append({
                    "type": "equation_candidate", "label": "公式编号候选",
                    "page_no": page_no, "excerpt": clean[:210],
                    "bbox": [round(v, 1) for v in (x0, y0, x1, y1)],
                    "confidence": "heuristic_label_only",
                })
            if len(candidates) >= MAX_CANDIDATES:
                break
        tables = []
        try:
            detector = page.find_tables()
            for table in detector.tables[:5]:
                matrix = table.extract()
                cropped = [
                    [((cell or "")[:220] if isinstance(cell, str) else "")
                     for cell in row[:MAX_TABLE_COLS]]
                    for row in matrix[:MAX_TABLE_ROWS]
                ]
                tables.append({
                    "page_no": page_no,
                    "bbox": [round(float(x), 1) for x in table.bbox],
                    "rows": table.row_count, "columns": table.col_count,
                    "cells": cropped,
                    "truncated": (
                        table.row_count > MAX_TABLE_ROWS
                        or table.col_count > MAX_TABLE_COLS
                    ),
                })
        except (ValueError, RuntimeError):
            # Lack of ruling lines or complex content is not evidence of no tables.
            pass
        # Publisher captions can appear BELOW the vector figure (not above).
        # Use text, image and bounded vector-drawing geometry to find that
        # region; image OCR is not necessary to render the real PDF pixels.
        visuals = []
        cached_drawings = None
        cached_images = page.get_image_info()[:100]
        for candidate in candidates:
            if candidate["type"] not in {"figure_caption", "table_caption"}:
                continue
            x0, y0, x1, y1 = candidate["bbox"]
            full_width = x1 - x0 > page.rect.width * .58
            left = max(0, (0 if full_width else x0 - 8))
            right = min(page.rect.width, (page.rect.width if full_width else x1 + 8))
            if candidate["type"] == "table_caption":
                matching = min(
                    tables,
                    key=lambda t: min(abs(t["bbox"][1] - y1),
                                      abs(t["bbox"][3] - y0)),
                    default=None,
                )
                if matching and min(abs(matching["bbox"][1] - y1),
                                    abs(matching["bbox"][3] - y0)) <= 95:
                    tx0, ty0, tx1, ty1 = matching["bbox"]
                    crop = [min(left, tx0 - 9), min(y0 - 8, ty0 - 8),
                            max(right, tx1 + 9), max(y1 + 8, ty1 + 8)]
                else:
                    # Publisher tables may have the caption BELOW the table;
                    # a vector-only table can evade find_tables(). In that
                    # case collect same-column text/drawing geometry above
                    # instead of blindly cropping hundreds of pixels below.
                    preceding = [
                        pymupdf.Rect(b[:4]) for b in blocks
                        if b[3] <= y0 + 3 and y0 - b[3] <= 140
                        and b[1] >= 48 and b[2] - b[0] > 80
                        and b[2] > left + 10 and b[0] < right - 10
                    ]
                    if cached_drawings is None:
                        try:
                            cached_drawings = page.get_drawings()[:2000]
                        except Exception:
                            cached_drawings = []
                    preceding.extend(
                        path["rect"] for path in cached_drawings
                        if path["rect"].y1 <= y0 + 3
                        and y0 - path["rect"].y1 <= 140
                        and path["rect"].y0 >= 48
                        and path["rect"].x1 > left + 10
                        and path["rect"].x0 < right - 10
                    )
                    if preceding:
                        crop = [min(left, min(v.x0 for v in preceding) - 8),
                                max(45, min(v.y0 for v in preceding) - 9),
                                max(right, max(v.x1 for v in preceding) + 8),
                                y1 + 8]
                    else:
                        crop = [left, y0 - 8, right, y1 + 240]
            else:
                # A previous caption in the same column bounds this figure;
                # figure 4 cannot absorb figure 3 above it.
                above = [
                    other["bbox"][3] for other in candidates
                    if other is not candidate
                    and other["type"] in {"figure_caption", "table_caption"}
                    and other["bbox"][3] < y0
                    and (full_width or other["bbox"][2] > left
                         and other["bbox"][0] < right)
                ]
                boundary = max(50, max(above, default=50) + 4)
                if cached_drawings is None:
                    try:
                        cached_drawings = page.get_drawings()[:2000]
                    except Exception:
                        cached_drawings = []
                regions = [
                    entry["rect"] for entry in cached_drawings
                    if entry["rect"].y0 >= boundary - 5
                    and entry["rect"].y1 < y0 - 2
                    and entry["rect"].x1 > left + 4
                    and entry["rect"].x0 < right - 4
                ] + [
                    pymupdf.Rect(image["bbox"]) for image in cached_images
                    if image["bbox"][1] >= boundary - 5
                    and image["bbox"][3] < y0 - 2
                    and image["bbox"][2] > left + 4
                    and image["bbox"][0] < right - 4
                ]
                # Side-by-side layout: graph on the LEFT and caption on
                # the RIGHT at the same vertical level. Restrict to drawings
                # wholly left of the caption to avoid borrowing another
                # column or swallowing text below.
                side_regions = [
                    path["rect"] for path in cached_drawings
                    if x0 > page.rect.width * .55
                    and path["rect"].x0 >= 45
                    and path["rect"].x1 <= x0 + 8
                    and path["rect"].y0 >= max(45, y0 - 180)
                    and path["rect"].y1 <= min(page.rect.height, y1 + 95)
                    and path["rect"].y1 > y0 - 110
                    and path["rect"].width > 40
                    and path["rect"].height > 24
                ] + [
                    pymupdf.Rect(image["bbox"]) for image in cached_images
                    if x0 > page.rect.width * .55
                    and image["bbox"][2] <= x0 + 8
                    and image["bbox"][1] >= max(45, y0 - 180)
                    and image["bbox"][3] > y0 - 110
                    and image["bbox"][3] <= y1 + 95
                ]
                if side_regions:
                    left = max(0, min(left, min(v.x0 for v in side_regions) - 12))
                    regions.extend(side_regions)
                if regions:
                    top = min(rect.y0 for rect in regions) - 12
                    bottom = max(y1 + 7,
                                 max((v.y1 for v in side_regions), default=y1) + 9)
                else:
                    # No safe isolated figure was detected. Show a generous
                    # review crop, never assert that it is the entire figure.
                    top, bottom = y0 - min(300, y0 - boundary), y1 + 7
                crop = [left, max(boundary, top), right, bottom]
            crop = [max(0, min(page.rect.width, crop[0])),
                    max(0, min(page.rect.height, crop[1])),
                    max(0, min(page.rect.width, crop[2])),
                    max(0, min(page.rect.height, crop[3]))]
            # Image/drawing presence is a useful indication, not a semantic
            # guarantee that the crop contains a complete figure.
            has_visual = any(
                pymupdf.Rect(image["bbox"]).intersects(pymupdf.Rect(crop))
                for image in cached_images
            )
            if not has_visual:
                try:
                    if cached_drawings is None:
                        cached_drawings = page.get_drawings()[:1200]
                    has_visual = any(
                        path["rect"].intersects(pymupdf.Rect(crop))
                        for path in cached_drawings
                    )
                except Exception:
                    has_visual = False
            visuals.append({
                "type": "figure_crop_candidate"
                if candidate["type"] == "figure_caption" else "table_crop_candidate",
                "label": candidate["label"], "page_no": page_no,
                "bbox": [round(float(v), 1) for v in crop],
                "source_caption": candidate["excerpt"][:500],
                "visual_content_detected": has_visual,
                "crop_confidence": "geometry_candidate"
                if has_visual else "unverified_review_crop",
            })
            if len(visuals) >= MAX_VISUALS:
                break
        return {
            "page_no": page_no,
            "page_size": [round(page.rect.width, 1), round(page.rect.height, 1)],
            "candidates": candidates,
            "tables": tables,
            "visuals": visuals,
            "note": (
                "页面候选均来自原 PDF 文本块；表格仅在结构检测成功时返回单元格。"
                "公式仅识别编号附近的文本，不是 LaTeX 还原；visuals 是可裁剪的图表候选区域，"
                "不是图像语义识别；扫描页通常需先做 OCR，"
                "此接口不应把空列表解释为不存在图表或公式。"
            ),
        }


def render_layout_preview(pdf_path: Path, page_no: int):
    """Render a page with detected captions/tables marked for visual review."""
    import pymupdf
    from PIL import Image, ImageDraw

    data = inspect_page(pdf_path, page_no)
    with pymupdf.open(str(pdf_path)) as doc:
        page = doc[page_no - 1]
        pix = page.get_pixmap(matrix=pymupdf.Matrix(1.45, 1.45), alpha=False)
    image = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
    draw = ImageDraw.Draw(image, "RGBA")
    sx = sy = 1.45
    for candidate in data["candidates"]:
        x0, y0, x1, y1 = candidate["bbox"]
        color = (255, 173, 50, 75) if candidate["type"] == "equation_candidate" else (54, 160, 220, 70)
        draw.rectangle((x0 * sx, y0 * sy, x1 * sx, y1 * sy),
                       fill=color, outline=(20, 90, 120, 230), width=3)
    for table in data["tables"]:
        x0, y0, x1, y1 = table["bbox"]
        draw.rectangle((x0 * sx, y0 * sy, x1 * sx, y1 * sy),
                       fill=(60, 190, 110, 40), outline=(20, 120, 70, 230), width=4)
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue(), data


def render_visual_crop(pdf_path: Path, page_no: int, visual_index: int):
    """Render one bounded figure/table candidate crop as a PNG."""
    import pymupdf
    from PIL import Image

    data = inspect_page(pdf_path, page_no)
    visuals = data.get("visuals", [])
    if not isinstance(visual_index, int) or not 0 <= visual_index < len(visuals):
        raise ValueError("图表候选编号不存在")
    crop = pymupdf.Rect(visuals[visual_index]["bbox"])
    with pymupdf.open(str(pdf_path)) as doc:
        page = doc[page_no - 1]
        crop = crop & page.rect
        if crop.is_empty or crop.width < 8 or crop.height < 8:
            raise ValueError("图表裁剪区域无效")
        pix = page.get_pixmap(matrix=pymupdf.Matrix(2.0, 2.0),
                              clip=crop, alpha=False)
    output = io.BytesIO()
    Image.open(io.BytesIO(pix.tobytes("png"))).save(output, format="PNG",
                                                     optimize=True)
    return output.getvalue(), visuals[visual_index]
