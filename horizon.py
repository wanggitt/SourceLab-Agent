"""Evidence-first Future Work candidates from a *local* paper collection.

This module does not decide whether an idea is novel, attempted, or solved.
Any related-paper hit is a search lead, not a temporal or causal conclusion.
"""

from __future__ import annotations

import re


SIGNALS = re.compile(
    r"(?i)\b(?:future\s+work|future\s+research|future\s+directions?"
    r"|further\s+research\s+is\s+needed"
    r"|further\s+work\s+is\s+needed"
    r"|we\s+plan\s+to|we\s+hope\s+to|we\s+intend\s+to"
    r"|we\s+will\s+(?:investigate|explore|extend)"
    r"|open\s+question|limitations?\s+and\s+outlook)\b"
)
STOP = {
    "the", "and", "for", "from", "with", "that", "this", "were", "have",
    "will", "would", "could", "their", "more", "some", "such", "into",
    "paper", "future", "work", "research", "direction", "directions",
    "approach", "investigate", "model", "models", "using", "also",
    "these", "those", "which", "about", "further", "tasks", "task",
    "question", "questions", "potentially", "methods", "method",
    "language", "languages", "large", "study",
    # Generic training/prose overlap is not a meaningful research connection.
    "after", "before", "then", "when", "each", "over", "between",
    "increase", "decrease", "higher", "lower", "iterations",
    "result", "results", "performance", "loss", "training", "trained",
    "tests", "test", "used", "found", "there", "number",
}


def arxiv_month(identifier):
    """First-submission month encoded by modern arXiv IDs, not publication date."""
    if not isinstance(identifier, str):
        return None
    match = re.fullmatch(r"(\d{2})(0[1-9]|1[0-2])\.\d{4,5}", identifier)
    if not match:
        return None
    return f"20{match.group(1)}-{match.group(2)}"


def page_texts(conn, paper_id):
    current, parts = None, []
    for row in conn.execute(
        "SELECT page_no,content FROM chunks WHERE paper_id=? ORDER BY page_no,id",
        (paper_id,),
    ):
        page = row["page_no"]
        if page != current:
            if parts:
                yield current, parts[0] + "".join(piece[140:] for piece in parts[1:])
            current, parts = page, []
        parts.append(row["content"])
    if parts:
        yield current, parts[0] + "".join(piece[140:] for piece in parts[1:])


def keyword_candidates(conn, origin_id, origin_arxiv, excerpt, limit=3):
    """Rank by FTS5 within other locally indexed documents, then verify overlap."""
    words = [
        word for word in re.findall(r"[a-z][a-z0-9-]{3,}", excerpt.lower())
        if word not in STOP
    ]
    words = list(dict.fromkeys(words))[:10]
    if len(words) < 2:
        return []
    expression = " OR ".join('"' + word.replace('"', "") + '"' for word in words)
    hits = conn.execute(
        """SELECT ch.id AS chunk_id, ch.paper_id, ch.page_no, ch.content,
                  p.title,p.filename,p.arxiv_id,bm25(chunks_fts) AS rank
           FROM chunks_fts f
           JOIN chunks ch ON ch.id=f.rowid
           JOIN papers p ON p.id=ch.paper_id
           WHERE chunks_fts MATCH ? AND p.status='ready' AND p.id<>?
                 AND (?='' OR p.arxiv_id<>?)
           ORDER BY rank LIMIT 45""",
        (expression, origin_id, origin_arxiv, origin_arxiv),
    ).fetchall()
    results, seen = [], set()
    for row in hits:
        if row["paper_id"] in seen:
            continue
        matched = [
            word for word in words
            if re.search(r"\b" + re.escape(word) + r"\b", row["content"].lower())
        ]
        if len(matched) < 2:
            continue
        seen.add(row["paper_id"])
        origin_month = arxiv_month(origin_arxiv)
        found_month = arxiv_month(row["arxiv_id"])
        if not origin_month or not found_month:
            time_relation = "unknown"
        elif found_month > origin_month:
            time_relation = "later_arxiv_month"
        elif found_month < origin_month:
            time_relation = "earlier_arxiv_month"
        else:
            time_relation = "same_arxiv_month_unknown_order"
        results.append({
            "paper_id": row["paper_id"], "title": row["title"],
            "filename": row["filename"], "page_no": row["page_no"],
            "chunk_id": row["chunk_id"], "excerpt": row["content"][:380],
            "shared_terms": matched[:5],
            "arxiv_first_month": found_month,
            "time_relation": time_relation,
        })
        if len(results) >= limit:
            break
    return results


def scan_future_work(conn, paper_id, limit=12):
    origin = conn.execute(
        "SELECT id,title,arxiv_id,status FROM papers WHERE id=?", (paper_id,)
    ).fetchone()
    if origin is None:
        raise ValueError("论文不存在")
    if origin["status"] != "ready":
        raise ValueError("论文尚未完成解析")
    items = []
    review_pages = []
    for page_no, text in page_texts(conn, paper_id):
        # The bibliography can contain the words "future work" in titles.
        starts_bibliography = bool(re.search(
            r"(?im)^\s*(?:references|bibliography)\s*$", text
        ))
        text = re.split(r"(?im)^\s*(?:references|bibliography)\s*$", text, maxsplit=1)[0]
        for heading in re.finditer(
            r"(?im)(?:^|\n)\s*(?:\d{1,2}(?:\.\d+)?[.\s]+)?"
            r"(?:conclusions?|limitations?(?:\s+and\s+outlook)?|discussion)"
            r"\b[^\n]{0,48}", text
        ):
            if len(review_pages) < 10 and page_no not in review_pages:
                review_pages.append(page_no)
        last_at = -500
        for signal in SIGNALS.finditer(text):
            if signal.start() - last_at < 110:
                continue
            last_at = signal.start()
            segment = re.sub(
                r"\s+", " ", text[max(0, signal.start() - 115): signal.end() + 235]
            ).strip()
            if len(segment) < 45:
                continue
            items.append({
                "source_page": page_no,
                "signal": signal.group(0),
                "source_excerpt": segment[:390],
                "status": (
                    "限制与展望原文候选；待人工核验，不等于作者明确提出未来工作"
                    if "limitation" in signal.group(0).lower()
                    else "未来工作原文候选；待人工核验，不能断言未被研究或已经解决"
                ),
            })
            if len(items) >= limit:
                break
        if len(items) >= limit:
            break
        if starts_bibliography:
            break
    for item in items:
        item["origin_arxiv_first_month"] = arxiv_month(origin["arxiv_id"])
        item["related_local_papers"] = keyword_candidates(
            conn, paper_id, origin["arxiv_id"], item["source_excerpt"]
        )
    return {
        "paper_id": paper_id, "title": origin["title"], "items": items,
        "review_pages": review_pages,
        "note": (
            "提取带原文页码的 Future Work、未来计划和明确的 Limitations and Outlook 候选；"
            "限制陈述不自动等同于未来工作计划。"
            "过滤常见词后，仍只按共同词展示本地检索候选；"
            "仅用有效 arXiv ID 推定初次提交月份，未知时间不属于后续论文。"
            "这不是准确发表/修订日期，也没有核验研究对象、是否尝试或解决；"
            "未命中不能证明想法新颖。"
        ),
    }
