"""Run a *retrieval page* baseline on one official vector PDF, not factual QA.

Writes tests/evaluation_report.json. Inspect the original PDF before changing
the hand-checked expected page numbers.
"""

import json
import sys
import tempfile
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "pdf" / "1706.03762v7.pdf"
OUTPUT = Path(__file__).with_name("evaluation_report.json")
CASES = [
    {"question": "第六位作者属于哪个机构", "expected_pages": [1]},
    {"question": "Adam 优化器 beta1 beta2 参数", "expected_pages": [7]},
    {"question": "Transformer base model GPU 型号 数量", "expected_pages": [7]},
    {"question": "Transformer big BLEU English German", "expected_pages": [8]},
    {"question": "Layer normalization references", "expected_pages": [10]},
]


def main():
    if not SOURCE.is_file():
        raise SystemExit(f"缺少官方样例 {SOURCE}")
    original = (app.DATA, app.FILES, app.DB_FILE)
    try:
        with tempfile.TemporaryDirectory() as directory:
            app.DATA = Path(directory)
            app.FILES = app.DATA / "uploads"
            app.DB_FILE = app.DATA / "eval.sqlite3"
            app.init_db()
            paper_id = uuid.uuid4().hex[:14]
            with app.db() as c:
                c.execute(
                    "INSERT INTO papers(id,filename,filepath,created_at) VALUES(?,?,?,?)",
                    (paper_id, SOURCE.name, str(SOURCE), app.now()),
                )
            app.ingest(paper_id)
            cases = []
            timings = {"sparse": 0.0, "latent": 0.0, "hybrid": 0.0}
            for case in CASES:
                results = {}
                for mode in ("sparse", "latent", "hybrid"):
                    started = time.perf_counter()
                    evidence = app.retrieve(case["question"], paper_id, limit=3,
                                            method=mode)
                    timings[mode] += time.perf_counter() - started
                    results[mode] = [entry["page_no"] for entry in evidence]
                cases.append({
                    "question": case["question"], "expected_pages": case["expected_pages"],
                    "top_3_pages": results["hybrid"],
                    "top_3_page_hit": any(
                        page in case["expected_pages"] for page in results["hybrid"]
                    ),
                    "sparse_top_3_pages": results["sparse"],
                    "sparse_top_3_page_hit": any(
                        page in case["expected_pages"] for page in results["sparse"]
                    ),
                    "latent_top_3_pages": results["latent"],
                    "latent_top_3_page_hit": any(
                        page in case["expected_pages"] for page in results["latent"]
                    ),
                })
            controls = {
                "nonsense_query_returns_no_evidence":
                    not app.retrieve("zzqplmxyvvvzz", paper_id)
            }
    finally:
        app.DATA, app.FILES, app.DB_FILE = original
    result = {
        "source_file": SOURCE.name,
        "metric": "top-3 evidence page hit; NOT answer correctness",
        "cases": cases,
        "top_3_page_hit_count": sum(case["top_3_page_hit"] for case in cases),
        "sparse_top_3_page_hit_count": sum(
            case["sparse_top_3_page_hit"] for case in cases
        ),
        "latent_top_3_page_hit_count": sum(
            case["latent_top_3_page_hit"] for case in cases
        ),
        "query_seconds_by_method": {
            mode: round(seconds, 3) for mode, seconds in timings.items()
        },
        "total": len(cases),
        "controls": controls,
        "limitations": (
            "五条手工指定问题与页码的小样本；PDF 同一事实可能出现在多个页。"
            "没有对答案真假、跨文推理、引用精确位置、OCR 质量或错误拒答率作出评估。"
        ),
    }
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Top-3 页命中 BM25={result['sparse_top_3_page_hit_count']}/{result['total']} "
          f"LSA={result['latent_top_3_page_hit_count']}/{result['total']} "
          f"BM25+LSA={result['top_3_page_hit_count']}/{result['total']}")
    for case in cases:
        print(f"{'PASS' if case['top_3_page_hit'] else 'MISS'} "
              f"{case['question']}: {case['top_3_pages']} expected={case['expected_pages']}")
    print(OUTPUT)


if __name__ == "__main__":
    main()
