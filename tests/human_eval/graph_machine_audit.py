"""Read-only machine audit for predicted citation-graph edges.

This helper never writes graph_labels.json and never sets gold_cites_target.
It only checks the source PDF's References area for a target arXiv identifier
or a conservative title phrase.  Results are advisory; all edges still need
human confirmation against the PDF.

Run from research_agent_mvp:
    python tests/human_eval/graph_machine_audit.py

Output:
    tests/human_eval/graph_machine_audit.json
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import fitz  # PyMuPDF

BASE = Path(__file__).resolve().parents[2]
WORK = Path(__file__).resolve().parent
PDF_DIR = BASE.parent / "pdf"
GRAPH = BASE / "tests" / "graph20_report.json"
OUT = WORK / "graph_machine_audit_result.json"


def norm(s: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s.casefold()).split())


def target_id(filename: str) -> str:
    m = re.match(r"(\d{4}\.\d{4,5})v\d+\.pdf$", filename)
    return m.group(1) if m else Path(filename).stem


def title_tokens(title: str) -> list[str]:
    # Keep a compact phrase that is unlikely to match unrelated references.
    words = re.findall(r"[a-z0-9]{4,}", title.casefold())
    stop = {"with", "from", "into", "using", "toward", "towards", "for", "the"}
    words = [w for w in words if w not in stop]
    return words[:4]


def reference_start(pages: list[str]) -> int | None:
    patterns = [
        re.compile(r"(?im)^\s*(?:\d+\s*[.]?\s*)?references\s*$"),
        re.compile(r"(?im)^\s*bibliography\s*$"),
    ]
    for i, text in enumerate(pages):
        if any(p.search(text) for p in patterns):
            return i
    # Many extraction layouts put the heading on the same line as nearby text.
    for i, text in enumerate(pages):
        if re.search(r"(?i)\breferences\b", text):
            return i
    return None


def find_match(page_text: str, arxiv: str, title: str):
    # arXiv IDs are the strongest machine evidence; permit "arXiv:" and
    # punctuation but not a bare substring in another number.
    id_re = re.compile(rf"(?<!\d){re.escape(arxiv)}(?!\d)", re.I)
    m = id_re.search(page_text)
    if m:
        a = max(0, m.start() - 180)
        b = min(len(page_text), m.end() + 220)
        return "direct_arxiv_id", page_text[a:b].replace("\n", " ").strip()
    toks = title_tokens(title)
    if toks:
        pattern = re.compile(r"(?<![a-z0-9])" + r"[\W_]+".join(
            re.escape(tok) for tok in toks) + r"(?![a-z0-9])", re.I)
        matched = pattern.search(page_text)
        if matched:
            a = max(0, matched.start() - 180)
            b = min(len(page_text), matched.end() + 220)
            return "title_phrase", page_text[a:b].replace("\n", " ").strip()
    return None, ""


def main() -> int:
    graph = json.loads(GRAPH.read_text(encoding="utf-8"))
    titles = {p["filename"]: p.get("title", "") for p in graph["papers"]}
    predicted = [e for e in graph["all_edges"] if e.get("source_filename") and e.get("target_filename")]
    rows = []
    cache: dict[str, tuple[list[str], int | None]] = {}
    for e in predicted:
        source = e["source_filename"]
        target = e["target_filename"]
        if not e.get("excerpt"):
            continue
        if source not in cache:
            path = PDF_DIR / source
            try:
                doc = fitz.open(path)
                pages = [p.get_text("text", sort=True) for p in doc]
                cache[source] = (pages, reference_start(pages))
            except Exception as exc:
                cache[source] = ([], None)
        pages, start = cache[source]
        result = {
            "id": f"{source} -> {target}",
            "source_pdf": source,
            "target_pdf": target,
            "predicted_source_page": e.get("source_page"),
            "reference_start_page": (start + 1) if start is not None else None,
            "target_arxiv_id": target_id(target),
            "target_title": titles.get(target, ""),
            "status": "manual_required",
            "evidence_page": None,
            "match_type": None,
            "evidence_excerpt": "",
            "notes": "",
        }
        if not pages or start is None:
            result["status"] = "manual_required"
            result["notes"] = "References heading not reliably found; inspect source PDF."
        else:
            for page_no, text in enumerate(pages[start:], start=start + 1):
                kind, excerpt = find_match(text, target_id(target), titles.get(target, ""))
                if kind:
                    result["status"] = "machine_candidate_true"
                    result["evidence_page"] = page_no
                    result["match_type"] = kind
                    result["evidence_excerpt"] = excerpt
                    result["notes"] = (
                        "Advisory only: direct ID/title match in References; "
                        "human must confirm the bibliography entry and target identity."
                    )
                    break
            if result["status"] == "manual_required":
                result["notes"] = (
                    "No direct arXiv ID or conservative title phrase found in extracted "
                    "References text; OCR/layout/alternate citation may hide a real edge."
                )
        rows.append(result)
    summary = {
        "scope": "predicted edges only; read-only advisory audit",
        "predicted_edges": len(rows),
        "machine_candidate_true": sum(r["status"] == "machine_candidate_true" for r in rows),
        "manual_required": sum(r["status"] == "manual_required" for r in rows),
        "output_does_not_modify_gold_labels": True,
        "rows": rows,
    }
    try:
        OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        destination = str(OUT)
    except PermissionError:
        # A browser/preview may hold the existing result file.  Keep the audit
        # read-only and still provide the summary; the previous JSON remains
        # valid and no gold label is touched.
        destination = f"(could not replace locked {OUT}; see stdout)"
    print(json.dumps({k: summary[k] for k in summary if k != "rows"}, ensure_ascii=False))
    print(f"Result: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
