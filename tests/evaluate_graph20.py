"""Reproducible 20-paper *local graph* engineering trial.

Uses an isolated temporary DB and the unmodified official pdf/ files.
The report is NOT a manually labelled precision/recall study; only two
explicit positive citation edges are independently checked as spot cases.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app

SOURCE = Path(__file__).resolve().parents[2] / "pdf"
OUTPUT = Path(__file__).with_name("graph20_report.json")
FILES = [
    "1607.06450v1.pdf",   # Layer Normalization
    "1706.03762v7.pdf",   # Transformer
    "1910.02054v3.pdf",   # ZeRO
    "2001.08361v1.pdf",   # Scaling Laws
    "2002.04745v2.pdf",   # LN in Transformer
    "2005.14165v4.pdf",   # GPT-3
    "2010.11929v2.pdf",   # ViT
    "2103.00020v1.pdf",   # CLIP
    "2106.09685v2.pdf",   # LoRA
    "2107.03374v2.pdf",   # Codex paper
    "2201.11903v6.pdf",   # Chain-of-Thought
    "2203.02155v1.pdf",   # Instruction following
    "2205.14135v2.pdf",   # FlashAttention
    "2206.07682v2.pdf",   # Emergent Abilities
    "2210.02414v2.pdf",   # GLM-130B
    "2211.05100v4.pdf",   # BLOOM
    "2303.08774v6.pdf",   # GPT-4
    "2304.08485v2.pdf",   # Visual Instruction Tuning
    "2305.14314v1.pdf",   # QLoRA
    "2305.18290v3.pdf",   # DPO
]
SPOT_POSITIVES = [
    ("1706.03762v7.pdf", "1607.06450v1.pdf", 10),
    ("2305.14314v1.pdf", "2106.09685v2.pdf", 18),
]


def run():
    if len(FILES) != 20 or len(set(FILES)) != 20:
        raise ValueError("必须恰好选择 20 篇互不重复的测试文件")
    missing = [name for name in FILES if not (SOURCE / name).is_file()]
    if missing:
        raise FileNotFoundError("缺少官方 PDF：" + ", ".join(missing))
    originals = app.DATA, app.FILES, app.DB_FILE
    entries = []
    try:
        with tempfile.TemporaryDirectory() as scratch:
            app.DATA = Path(scratch)
            app.FILES = app.DATA / "uploads"
            app.DB_FILE = app.DATA / "graph20.sqlite3"
            app.init_db()
            for name in FILES:
                path = (SOURCE / name).resolve()
                paper_id = uuid.uuid4().hex[:14]
                with app.db() as conn:
                    conn.execute(
                        "INSERT INTO papers(id,filename,filepath,created_at) VALUES(?,?,?,?)",
                        (paper_id, name, str(path), app.now()),
                    )
                started = time.perf_counter()
                app.ingest(paper_id)
                with app.db() as conn:
                    row = conn.execute(
                        "SELECT status,error,title,pages,chunks FROM papers WHERE id=?",
                        (paper_id,),
                    ).fetchone()
                entries.append({
                    "filename": name, "id": paper_id,
                    "status": row["status"], "error": row["error"],
                    "title": row["title"], "pages": row["pages"],
                    "chunks": row["chunks"],
                    "ingest_seconds": round(time.perf_counter() - started, 3),
                })
                print(
                    f"[{len(entries):02}/20] {name}: {row['status']} "
                    f"{row['pages']} pages, {row['chunks']} chunks",
                    flush=True,
                )
            started = time.perf_counter()
            graph = app.citation_graph()
            graph_seconds = round(time.perf_counter() - started, 3)
            by_name = {item["filename"]: item for item in entries}
            positives = []
            for citing, cited, expected_page in SPOT_POSITIVES:
                source_id = by_name[citing]["id"]
                target_id = by_name[cited]["id"]
                observed = next(
                    (edge for edge in graph["edges"]
                     if edge["source"] == source_id and edge["target"] == target_id),
                    None,
                )
                positives.append({
                    "source_filename": citing, "target_filename": cited,
                    "expected_source_page": expected_page,
                    "found": observed is not None,
                    "observed_source_page": observed["page_no"] if observed else None,
                    "excerpt": observed["excerpt"] if observed else "",
                    "match_type": observed["match_type"] if observed else None,
                    "page_match": bool(
                        observed and observed["page_no"] == expected_page
                    ),
                })
            reported_edges = [
                {
                    "source_filename": next(
                        node["filename"] for node in graph["nodes"]
                        if node["id"] == edge["source"]
                    ),
                    "target_filename": next(
                        node["filename"] for node in graph["nodes"]
                        if node["id"] == edge["target"]
                    ),
                    "source_page": edge["page_no"],
                    "match_type": edge["match_type"],
                    "excerpt": edge["excerpt"][:240],
                }
                for edge in graph["edges"]
            ]
    finally:
        app.DATA, app.FILES, app.DB_FILE = originals
    return {
        "files_requested": len(FILES),
        "ready": sum(item["status"] == "ready" for item in entries),
        "unique_graph_nodes": len(graph["nodes"]),
        "graph_edges": len(graph["edges"]),
        "graph_seconds": graph_seconds,
        "ingest_seconds_total": round(
            sum(item["ingest_seconds"] for item in entries), 3
        ),
        "papers": entries,
        "spot_positive_edges": positives,
        "all_edges": reported_edges,
        "limitations": (
            "这 20 篇是 Transformer/大模型相关的局域样本，不是严格单一方向"
            "的完整引文全集；只人工抽查了两条已知正例。边总数≠准确边数，"
            "未人工标注全部参考文献，不能报告边精确率或召回率。"
            "运行耗时仅是本机一次测试，不含浏览器交互/内存峰值。"
        ),
    }


if __name__ == "__main__":
    report = run()
    OUTPUT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        "20-paper trial",
        f"{report['ready']}/{report['files_requested']} ready",
        f"{report['unique_graph_nodes']} nodes",
        f"{report['graph_edges']} edges",
        f"graph {report['graph_seconds']} s",
        flush=True,
    )
    for positive in report["spot_positive_edges"]:
        print(
            "spot-check",
            positive["source_filename"], "→", positive["target_filename"],
            "found", positive["found"],
            "page", positive["observed_source_page"],
            flush=True,
        )
    print(OUTPUT)
    if (report["ready"] != 20 or report["unique_graph_nodes"] != 20
            or not all(item["page_match"] for item in report["spot_positive_edges"])):
        raise SystemExit(
            "20 篇导入/建图或已知正例没有全部通过；请先检查 graph20_report.json"
        )
