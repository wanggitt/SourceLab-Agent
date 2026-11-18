"""Best-effort source geometry for vector and OCR pages."""

import io
import re


def find_excerpt_rects(page, content):
    """Use a phrase *from this indexed chunk*; reject ambiguous page matches."""
    # Char-based chunks can start/end mid-word. Skip the first two tokens.
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9-]*|\d+(?:\.\d+)?", content[:850])
    for offset in (2, 10, 22, 38, 60):
        phrase = " ".join(tokens[offset:offset + 10])
        if len(phrase) < 35:
            continue
        rects = page.search_for(phrase)
        if rects and len(rects) <= 3:
            return phrase, rects
    return None, []


def find_ocr_rects(lines, content, question):
    """Only mark OCR lines matching >=2 query tokens in the indexed chunk.

    A hit is a helpful visual pointer, *not* an assertion that the OCR text
    proves the question's answer. Avoid arbitrary top-line or full-page marks.
    """
    def tokens(value):
        words = re.findall(r"[a-z][a-z0-9]+|\d+(?:\.\d+)?", value.lower())
        return {word[:-1] if word.endswith("s") and len(word) > 4 else word
                for word in words if len(word) >= 3}

    question_terms = tokens(question) - {"what", "which", "where", "paper", "about"}
    source_terms = tokens(content)
    if len(question_terms) < 2:
        return []
    ranked = []
    for line in lines:
        line_terms = tokens(line["content"])
        matched = question_terms & line_terms
        # The chunk is indexed from this page, but it may not contain this
        # particular OCR line: enforce substantial line/chunk overlap.
        if len(matched) < 2 or len(source_terms & line_terms) < min(2, len(line_terms)):
            continue
        if float(line["confidence"]) < 0.35:
            continue
        bounds = (line["x0"], line["y0"], line["x1"], line["y1"])
        if not (0 <= bounds[0] < bounds[2] <= 1 and 0 <= bounds[1] < bounds[3] <= 1):
            continue
        ranked.append((len(matched), line["line_no"], bounds))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in ranked[:3]]


def render_evidence(pdf_path, page_no, content, ocr_lines=None, question=""):
    """Render only an eligible page; never trust user-supplied bounding boxes."""
    import pymupdf

    with pymupdf.open(str(pdf_path)) as doc:
        page = doc[page_no - 1]
        if page.rect.width * page.rect.height > 2_000_000:
            raise ValueError("页面尺寸过大，无法安全预览")
        is_ocr = ocr_lines is not None
        phrase, rects = (None, []) if is_ocr else find_excerpt_rects(page, content)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(1.45, 1.45), alpha=False)
        from PIL import Image, ImageDraw

        img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
        if rects:
            draw = ImageDraw.Draw(img, "RGBA")
            for box in rects:
                draw.rectangle(
                    tuple(int(value * 1.45) for value in box),
                    fill=(255, 223, 55, 78), outline=(215, 127, 0, 220), width=2,
                )
        ocr_rects = find_ocr_rects(ocr_lines, content, question) if is_ocr else []
        if ocr_rects:
            draw = ImageDraw.Draw(img, "RGBA")
            for x0, y0, x1, y1 in ocr_rects:
                draw.rectangle(
                    (int(x0 * img.width), int(y0 * img.height),
                     int(x1 * img.width), int(y1 * img.height)),
                    fill=(255, 223, 55, 70), outline=(215, 127, 0, 230), width=2,
                )
        output = io.BytesIO()
        img.save(output, format="PNG", optimize=True)
        return output.getvalue(), bool(rects or ocr_rects), (
            "OCR question-term overlap" if ocr_rects else phrase
        )
