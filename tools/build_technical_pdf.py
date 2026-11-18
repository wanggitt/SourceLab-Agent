"""Render the explicitly labelled technical-plan DRAFT (not a final contest submission).

Usage: python tools/build_technical_pdf.py
Dependency: reportlab>=4.2; finds a local CJK font on Windows or Linux.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable, KeepTogether, Paragraph, Preformatted, SimpleDocTemplate, Spacer,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "技术方案与演示脚本.md"
OUTPUT = ROOT / "技术方案草稿.pdf"
FONTS = [
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("C:/Windows/Fonts/NotoSansSC-VF.ttf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
]


def font_name():
    for path in FONTS:
        if not path.is_file():
            continue
        try:
            pdfmetrics.registerFont(TTFont("SourceLabCJK", str(path), subfontIndex=0))
            pdfmetrics.registerFontFamily(
                "SourceLabCJK", normal="SourceLabCJK", bold="SourceLabCJK"
            )
            return "SourceLabCJK"
        except Exception:
            continue
    raise RuntimeError("未找到可嵌入中文 PDF 的字体，请安装 Noto Sans CJK / SimHei")


def format_text(raw):
    escaped = html.escape(raw)
    escaped = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", escaped)
    escaped = re.sub(r"`([^`]+)`", r"<font color='#15745a'>\1</font>", escaped)
    return escaped


def page_decoration(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#dce9e2"))
    canvas.line(44, 47, A4[0] - 44, 47)
    canvas.setFillColor(colors.HexColor("#617871"))
    canvas.setFont("SourceLabCJK", 8)
    canvas.drawString(44, 34, "SourceLab  ·  技术方案草稿  ·  非最终参赛材料")
    canvas.drawRightString(A4[0] - 44, 34, str(doc.page))
    canvas.restoreState()


def build():
    font = font_name()
    body = ParagraphStyle(
        "Body", fontName=font, fontSize=9.2, leading=15.2,
        textColor=colors.HexColor("#253c36"), wordWrap="CJK",
        spaceAfter=7, allowWidows=0, allowOrphans=0,
    )
    heading = ParagraphStyle(
        "Heading", parent=body, fontSize=13, leading=19,
        textColor=colors.HexColor("#14674f"), spaceBefore=17, spaceAfter=9,
        keepWithNext=True,
    )
    title = ParagraphStyle(
        "Title", parent=body, fontSize=20, leading=28, spaceAfter=13,
        textColor=colors.HexColor("#0f483b"),
    )
    subtitle = ParagraphStyle(
        "Subtitle", parent=body, fontSize=8.4, leading=13,
        textColor=colors.HexColor("#667e70"),
    )
    code = ParagraphStyle(
        "Code", parent=body, fontSize=8, leading=13, leftIndent=9,
        backColor=colors.HexColor("#f1f7f3"),
        spaceBefore=6, spaceAfter=11, wordWrap="CJK",
    )
    rows = SOURCE.read_text(encoding="utf-8").splitlines()
    story = []
    in_code, code_lines = False, []
    for line in rows:
        if line.strip().startswith("```"):
            if in_code:
                story.append(Preformatted("\n".join(code_lines), code))
                code_lines = []
            in_code = not in_code
            continue
        if in_code:
            code_lines.append(line)
            continue
        if not line.strip() or line.lstrip().startswith("|---"):
            continue
        if line.startswith("# "):
            story.append(Paragraph(format_text(line[2:]), title))
            story.append(HRFlowable(width="100%", thickness=2, color="#58b18d"))
            story.append(Spacer(1, 10))
        elif line.startswith("## "):
            story.append(Paragraph(format_text(line[3:]), heading))
        elif line.startswith(">"):
            story.append(Paragraph(format_text(line[1:].strip()), subtitle))
        elif line.startswith("|"):
            cells = [part.strip() for part in line.strip().strip("|").split("|")]
            story.append(Paragraph("  ·  ".join(format_text(x) for x in cells), body))
        elif line.startswith("- "):
            story.append(Paragraph("•  " + format_text(line[2:]), body))
        else:
            story.append(Paragraph(format_text(line), body))
    doc = SimpleDocTemplate(
        str(OUTPUT), pagesize=A4, leftMargin=47, rightMargin=47,
        topMargin=52, bottomMargin=61,
        title="SourceLab 技术方案草稿",
        author="SourceLab Project (draft, unverified submission)",
    )
    doc.build(story, onFirstPage=page_decoration, onLaterPages=page_decoration)
    print(OUTPUT)


if __name__ == "__main__":
    build()
