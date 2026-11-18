"""Measure labelled fact *evidence coverage* on an isolated official-paper index.

This cannot measure factual correctness of a generated LLM answer. A model may
hallucinate despite finding every required phrase, and text matches are not
semantic entailment. Report such gaps explicitly.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import unicodedata
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app

ROOT = Path(__file__).resolve().parents[2]
CASES_FILE = Path(__file__).with_name("official_fact_cases.json")
OUTPUT = Path(__file__).with_name("fact_evidence_report.json")


def normalize(value):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value).lower()).strip()


def inspect_case(case, evidence):
    """A passage must be on the labelled page; no blending unrelated pages."""
    matched = {}
    for phrase in case["required_evidence"]:
        hits = [
            {
                "chunk_id": row["chunk_id"], "page_no": row["page_no"],
                "retrieval": row["retrieval"],
            }
            for row in evidence
            if row["page_no"] in case["expected_pages"]
            and normalize(phrase) in normalize(row["content"])
        ]
        matched[phrase] = hits
    return {
        "case_id": case["id"],
        "question": case["question"],
        "expected_pages": case["expected_pages"],
        "reference_answer_human_label": case["reference_answer"],
        "top_3": [
            {
                "chunk_id": row["chunk_id"], "page_no": row["page_no"],
                "retrieval": row["retrieval"]
            }
            for row in evidence
        ],
        "page_hit": any(row["page_no"] in case["expected_pages"] for row in evidence),
        "anchor_matches": matched,
        "all_anchors_in_top_3": all(bool(rows) for rows in matched.values()),
        "single_passage_covers_all_anchors": any(
            all(normalize(phrase) in normalize(row["content"])
                for phrase in case["required_evidence"])
            and row["page_no"] in case["expected_pages"]
            for row in evidence
        ),
    }


def evaluate():
    fixture = json.loads(CASES_FILE.read_text(encoding="utf-8"))
    source = ROOT / "pdf" / fixture["source_file"]
    if not source.is_file():
        raise FileNotFoundError(f"官方 PDF 不存在：{source}")
    original = app.DATA, app.FILES, app.DB_FILE
    try:
        with tempfile.TemporaryDirectory() as temp:
            app.DATA = Path(temp)
            app.FILES = app.DATA / "uploads"
            app.DB_FILE = app.DATA / "fact_eval.sqlite3"
            app.init_db()
            paper_id = uuid.uuid4().hex[:14]
            with app.db() as conn:
                conn.execute(
                    "INSERT INTO papers(id,filename,filepath,created_at) VALUES(?,?,?,?)",
                    (paper_id, source.name, str(source.resolve()), app.now()),
                )
            app.ingest(paper_id)
            report = []
            for case in fixture["cases"]:
                evidence = app.retrieve(
                    case["question"], paper_id, limit=3, method="hybrid"
                )
                report.append(inspect_case(case, evidence))
            controls = []
            for case in fixture["negative_controls"]:
                evidence = app.retrieve(case["question"], paper_id)
                controls.append({
                    "question": case["question"],
                    "no_retrieved_evidence": not evidence,
                    "note": (
                        "验证此具体负例没有返回证据；无词匹配与明确数字约束"
                        "不能证明所有自然语言虚构事实都会被拒答。"
                    )
                })
    finally:
        app.DATA, app.FILES, app.DB_FILE = original
    result = {
        "source_file": source.name,
        "sample_size": len(report),
        "top_3_page_hits": sum(row["page_hit"] for row in report),
        "top_3_all_anchor_coverage": sum(
            row["all_anchors_in_top_3"] for row in report
        ),
        "top_3_single_passage_coverage": sum(
            row["single_passage_covers_all_anchors"] for row in report
        ),
        "cases": report,
        "negative_controls": controls,
        "limits": (
            "标签经人工对照该版 PDF 创建；仅检查前 3 条检索片段中是否出现"
            "精确词串及页码，不是问答事实正确率、推理有效性或语义蕴含率。"
            "人工作答是独立参考标签，程序并未自动生成该答案。"
        )
    }
    OUTPUT.write_text(json.dumps(result, indent=2, ensure_ascii=False),
                      encoding="utf-8")
    return result


if __name__ == "__main__":
    result = evaluate()
    print(f"page hits {result['top_3_page_hits']}/{result['sample_size']}; "
          f"all anchors {result['top_3_all_anchor_coverage']}/{result['sample_size']}; "
          f"single passage {result['top_3_single_passage_coverage']}/{result['sample_size']}")
    for case in result["cases"]:
        missing = [
            key for key, hits in case["anchor_matches"].items() if not hits
        ]
        print(f"{case['case_id']}: page={case['page_hit']}, "
              f"all_anchors={case['all_anchors_in_top_3']}, "
              f"missing={missing!r}, pages={[x['page_no'] for x in case['top_3']]}")
    print(OUTPUT)
