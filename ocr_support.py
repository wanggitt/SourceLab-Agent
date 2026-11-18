"""可选的本地 CPU OCR：PDFium 按需渲染页面并保存 OCR 行位置。

不在模块导入时初始化模型；只有文本层缺失的页面才占用 OCR 推理资源。
"""

from __future__ import annotations

import threading

_ENGINE = None
_ENGINE_LOCK = threading.Lock()


def scan_page(pdf_document, page_index: int, with_boxes=False):
    global _ENGINE
    try:
        from rapidocr import RapidOCR
    except ImportError as exc:
        raise RuntimeError("缺少 RapidOCR/onnxruntime，请安装 requirements.txt") from exc
    with _ENGINE_LOCK:
        if _ENGINE is None:
            _ENGINE = RapidOCR()
        # 一页一页渲染，不持久化图片；控制扫描件、长 PDF 的内存占用。
        page = pdf_document[page_index]
        try:
            # 对当前官方扫描样例，1.0x 已可读标题；CPU 推理比高 DPI 快。
            image = page.render(scale=1.0).to_pil()
            # 避免用户上传异常超大页面导致推理内存爆炸。
            image.thumbnail((2200, 3000))
            width, height = image.size
            try:
                output = _ENGINE(image)
            finally:
                image.close()
        finally:
            page.close()
    lines = []
    if output is not None and output.txts:
        scores = getattr(output, "scores", None)
        boxes = getattr(output, "boxes", None)
        for index, line in enumerate(output.txts):
            score = float(scores[index]) if scores is not None else 1.0
            if not line.strip() or score < 0.35:
                continue
            entry = {"text": line.strip(), "confidence": round(score, 4)}
            if boxes is not None and index < len(boxes):
                points = boxes[index]
                try:
                    xs = [float(p[0]) for p in points]
                    ys = [float(p[1]) for p in points]
                    x0, y0 = max(0, min(xs)), max(0, min(ys))
                    x1, y1 = min(width, max(xs)), min(height, max(ys))
                    if x1 > x0 and y1 > y0:
                        entry["box"] = [round(x0 / width, 6), round(y0 / height, 6),
                                        round(x1 / width, 6), round(y1 / height, 6)]
                except (ValueError, TypeError, IndexError):
                    pass
            lines.append(entry)
    text = "\n".join(item["text"] for item in lines)
    return {"text": text, "lines": lines} if with_boxes else text
