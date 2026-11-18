"""Page-anchored bilingual reading units and guarded academic translation spans."""

from __future__ import annotations

import html
import re
from collections import Counter
from pathlib import Path

import pymupdf

PROTECTED = re.compile(
    r"```[\s\S]*?```|`[^`\n]+`|\$\$[\s\S]*?\$\$"
    r"|\$(?!\s)[^$\n]+?\$|\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\]"
    r"|https?://[^\s<>)]+|\[\s*\d{1,3}\s*\]"
)
PLACEHOLDER = re.compile(r"\[\[SRC_KEEP_(\d{3})\]\]")
NUMBER = re.compile(r"(?<![A-Za-z])\d+(?:[,.]\d+)*")


def protected_translation_input(text):
    """Protect formula/code/citation/link and numeric spans from translation."""
    if PLACEHOLDER.search(text):
        raise ValueError("原文包含与受保护标记冲突的字符串")
    originals = []

    def replace(match):
        index = len(originals)
        if index >= 100:
            raise ValueError("单段受保护元素超过 100 个，请分段翻译")
        originals.append(match.group())
        return f"[[SRC_KEEP_{index:03}]]"

    # Mask numbers outside already protected spans as well.  Dates, DOI
    # fragments, measurements and page numbers must not be rewritten by the
    # model; failing to keep a placeholder still raises on restoration.
    pieces = []
    cursor = 0
    for match in PROTECTED.finditer(text):
        pieces.append(NUMBER.sub(replace, text[cursor:match.start()]))
        pieces.append(replace(match))
        cursor = match.end()
    pieces.append(NUMBER.sub(replace, text[cursor:]))
    return "".join(pieces), originals


def restored_translation(source, output, originals):
    """Reject omitted/reordered protected spans and changed numeric values."""
    actual = PLACEHOLDER.findall(output)
    expected = [f"{index:03}" for index in range(len(originals))]
    if actual != expected:
        raise ValueError("译文未按原顺序完整保留公式、代码或引用标记")
    result = PLACEHOLDER.sub(lambda m: originals[int(m.group(1))], output)

    def counts(text):
        return Counter(value.strip(".,") for value in NUMBER.findall(text))

    if counts(source) != counts(result):
        raise ValueError("译文数字与原文不一致，请人工复核后重新翻译")
    return result


def page_units(pdf_path: Path, page_no: int, ocr_lines=None):
    """Extract bounded page-aligned blocks; layout reading order is heuristic."""
    with pymupdf.open(str(pdf_path)) as doc:
        if not 1 <= page_no <= len(doc):
            raise ValueError("页码超出 PDF 范围")
        page = doc[page_no - 1]
        width, height = page.rect.width, page.rect.height
        blocks = [
            (b[:4], b[4].strip()) for b in page.get_text("blocks", sort=True)
            if len(b) > 6 and b[6] == 0 and b[4].strip()
        ]
    source = "vector"
    if not blocks and ocr_lines:
        source = "ocr"
        blocks = []
        for line in ocr_lines:
            box = (
                line["x0"] * width, line["y0"] * height,
                line["x1"] * width, line["y1"] * height,
            )
            blocks.append((box, line["content"]))
    units = []
    for bbox, content in blocks[:180]:
        for start in range(0, len(content), 1800):
            text = content[start:start + 1800].strip()
            if len(text) < 3:
                continue
            units.append({
                "page_no": page_no, "ordinal": len(units),
                "bbox": [round(float(x), 1) for x in bbox],
                "source": source, "original": text,
            })
            if len(units) >= 200:
                break
        if len(units) >= 200:
            break
    return units


def export_bilingual_html(title, pages):
    """Escape both source PDF and model output before emitting offline HTML."""
    heading = html.escape(title)
    rows = []
    for page_no, units in pages:
        for unit in units:
            rows.append(
                '<section class="pair" data-page="{page}"><div class="source">'
                '<small>原文 · p.{page} / #{ordinal}</small><p>{original}</p></div>'
                '<div class="target"><small>译文 · p.{page} / #{ordinal}</small>'
                '<p>{translated}</p></div></section>'.format(
                    page=page_no, ordinal=unit["ordinal"] + 1,
                    original=html.escape(unit["original"]),
                    translated=html.escape(unit["translated"]),
                )
            )
    return (
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        '<title>' + heading + " · 原译对照</title>"
        '<style>body{font:14px/1.6 system-ui,sans-serif;max-width:1200px;'
        'margin:auto;padding:22px;color:#243f36}h1{font-size:22px}.pair{display:'
        'grid;grid-template-columns:1fr 1fr;gap:14px;border-bottom:1px solid #dde8e1;'
        'padding:12px 0}.pair>div{padding:8px 14px;white-space:pre-wrap;'
        'overflow-wrap:anywhere}.source{background:#f5f8f6}.target{background:#f0faf3}'
        'small{color:#637d70}@media(max-width:760px){.pair{grid-template-columns:1fr}}'
        '</style><h1>' + heading + "</h1>"
        "<p>由模型生成的学术翻译，须核对公式、术语和原文。"
        "版式以文本块对齐，不保证原 PDF 双栏及图表保真。</p>"
        + "".join(rows) + "</html>"
    )
