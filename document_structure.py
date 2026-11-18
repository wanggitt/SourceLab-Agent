"""Bounded, source-page-linked structural candidates from indexed PDF text.

Never label a text heuristic as a faithful reconstruction of PDF figures,
equations, appendix boundaries or LaTeX source.
"""

from __future__ import annotations

import re

MAX_ITEMS = 200
CAPTION = re.compile(r"^(figure|fig\.?|table)\s*(\d{1,3})\s*[:.]\s*(.{0,220})$", re.I)
EQUATION = re.compile(r"\(\s*(\d{1,3})\s*\)\s*$")
APPENDIX = re.compile(
    r"^(appendix|appendices|附录)(?:\s+([A-Z]|\d{1,2}))?(?:\s*[:.]\s*|\s+)?(.{0,110})$",
    re.I,
)


def _entry(kind, page, text, limit=260):
    return {"type": kind, "page_no": page, "excerpt": text[:limit],
            "source": "indexed_page_text", "confidence": "pattern_candidate"}


def build_structure(pages, headings, citations):
    """Make an explicit 3-level heading tree and separate bounded candidates.

    `pages` is an iterable of (physical PDF page, reconstructed indexed text).
    Indexed OCR may have uncertain reading order; empty sections mean *not
    detected*, not that the source document contains none.
    """
    title_tree, stack = [], []
    for heading in headings[:MAX_ITEMS]:
        level = heading.get("level")
        if level not in (1, 2, 3):
            continue
        node = {"title": heading["title"], "level": level,
                "page_no": heading["page_no"], "children": []}
        while stack and stack[-1]["level"] >= level:
            stack.pop()
        if stack:
            stack[-1]["children"].append(node)
        else:
            title_tree.append(node)
        stack.append(node)

    captions, equations, appendices, bibliography = [], [], [], []
    counts = {
        "captions": 0, "equations": 0, "appendices": 0,
        "references_headings": 0,
    }
    seen = set()
    for page_no, text in pages:
        for raw in text.splitlines():
            line = " ".join(raw.split())
            if not line or len(line) > 320:
                continue
            kind = None
            caption = CAPTION.match(line)
            appendix = APPENDIX.match(line) if len(line) <= 125 else None
            if re.fullmatch(r"(?:references|bibliography|参考文献)", line, re.I):
                kind = "references_heading"
            elif appendix and (appendix.group(2) or len(line) < 45):
                kind = "appendix_heading"
            elif caption:
                kind = "table_caption" if caption.group(1).lower() == "table" else "figure_caption"
            elif (len(line) <= 210 and EQUATION.search(line)
                  and not re.search(r"\b(?:eqs?\.?|equations?)\s*\(\s*\d+\s*\)\s*$", line, re.I)
                  and re.search(r"[=<>∑√×±−÷∈≤≥≲≳⟺∂α-ωΑ-Ω]", line)):
                kind = "equation_candidate"
            if not kind or (page_no, kind, line.casefold()) in seen:
                continue
            seen.add((page_no, kind, line.casefold()))
            destination = {
                "references_heading": bibliography,
                "appendix_heading": appendices,
                "table_caption": captions,
                "figure_caption": captions,
                "equation_candidate": equations,
            }[kind]
            category = {
                "references_heading": "references_headings",
                "appendix_heading": "appendices",
                "table_caption": "captions",
                "figure_caption": "captions",
                "equation_candidate": "equations",
            }[kind]
            counts[category] += 1
            if len(destination) < MAX_ITEMS:
                destination.append(_entry(kind, page_no, line))

    return {
        "heading_tree": title_tree,
        "captions": captions,
        "equations": equations,
        "appendices": appendices,
        "references": {
            "headings": bibliography,
            "numbered_entries": [
                {"number": ref["number"], "page_no": ref["page_no"],
                 "excerpt": ref["snippet"], "source": "indexed_page_text"}
                for ref in citations[:MAX_ITEMS]
            ],
        },
        "truncated": {
            "heading_tree": len(headings) > MAX_ITEMS,
            "numbered_references_at_source_limit": len(citations) >= 100,
            **{name: count > MAX_ITEMS for name, count in counts.items()},
        },
        "note": (
            "基于已索引原文/OCR 的页级候选：标题仅显示可识别的编号层级；"
            "图表只列图注，公式只列可识别编号附近文字，不还原 LaTeX 或图像；"
            "附录/参考文献与扫描件顺序均需对照原 PDF 核查。"
            "候选每类最多展示 200 项、编号参考文献最多 100 项；"
            "空列表表示未识别，不能据此断言论文没有该结构。"
        ),
    }
