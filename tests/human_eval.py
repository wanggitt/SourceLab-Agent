"""Human-grounded, opt-in evaluation. Never invent labels or call paid models.

Usage:
  python tests/human_eval.py init
  python tests/human_eval.py collect
  python tests/human_eval.py score
All label edits are preserved; generated predictions are stored separately.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unicodedata
import uuid

BASE = Path(__file__).resolve().parents[1]
ROOT = BASE.parent
WORK = Path(__file__).with_name("human_eval")
sys.path.insert(0, str(BASE))


def read(name, default=None):
    p = WORK / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def write(name, data):
    WORK.mkdir(exist_ok=True)
    (WORK / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")


def fingerprint(path):
    """Stable across re-indexes with new random paper IDs or timing fields."""
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    evidence = {
        "files": sorted(x["filename"] for x in snapshot["papers"]),
        "edges": sorted((
            x["source_filename"], x["target_filename"], x["source_page"],
            x["excerpt"], x["match_type"]
        ) for x in snapshot["all_edges"]),
    }
    payload = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def normalized(value):
    return " ".join(unicodedata.normalize("NFKC", str(value)).casefold().split())


def init():
    graph_file = BASE / "tests" / "graph20_report.json"
    graph = json.loads(graph_file.read_text(encoding="utf-8"))
    papers = [p["filename"] for p in graph["papers"]]
    predicted = {(e["source_filename"], e["target_filename"]): e
                 for e in graph["all_edges"]}
    if len(papers) != 20 or len(set(papers)) != 20:
        raise ValueError("Graph snapshot must contain 20 unique files")
    old = {x["id"]: x for x in read("graph_labels.json", [])}
    rows = []
    for source in papers:
        for target in papers:
            if source == target:  # self-citations are not part of this benchmark
                continue
            key = source + " -> " + target
            evidence = predicted.get((source, target))
            previous = old.get(key, {})
            rows.append({
                "id": key, "source_pdf": source, "target_pdf": target,
                "predicted": bool(evidence),
                "source_page_predicted": evidence["source_page"] if evidence else None,
                "evidence_excerpt": evidence["excerpt"] if evidence else "",
                "gold_cites_target": previous.get("gold_cites_target"),
                "gold_reference_page": previous.get("gold_reference_page"),
                "predicted_evidence_valid": previous.get("predicted_evidence_valid"),
                "reviewer": previous.get("reviewer", ""),
                "notes": previous.get("notes", ""),
            })
    old_meta = read("graph_manifest.json", {})
    current_hash = fingerprint(graph_file)
    if old_meta and old_meta.get("report_sha256") != current_hash and any(
        x.get("gold_cites_target") is not None for x in old.values()
    ):
        raise ValueError("Graph snapshot changed: back up existing labels and review source/version first")
    write("graph_labels.json", rows)
    write("graph_manifest.json", {
        "report_path": "tests/graph20_report.json", "report_sha256": current_hash,
        "sample": "20 works; all 380 directed non-self pairs; local graph only",
        "criterion": "gold_cites_target must be independently checked in source PDF References",
    })
    # Questions are intentionally new prompts, not fabricated gold answers.
    example = [
        ("q01", "fact", ["1706.03762v7.pdf"],
         "Transformer base 模型使用什么硬件？"),
        ("q02", "negative", ["1706.03762v7.pdf"],
         "论文是否证明 Transformer 在所有语言任务上永远优于其他方法？"),
        ("q03", "cross_paper", ["1706.03762v7.pdf", "1607.06450v1.pdf"],
         "这两篇论文在归一化的作用上有什么有据可查的联系？"),
        ("q04", "layout", ["2206.07682v2.pdf"],
         "Figure 2 的横纵轴及图例分别是什么？"),
        ("q05", "ocr", ["1706.03762v1_img.pdf"],
         "Transformer base 模型训练硬件是什么？"),
    ]
    if not (WORK / "qa_labels.json").exists():
        write("qa_labels.json", [
            {
                "id": qid, "task_type": kind, "source_pdfs": source,
                "question": question, "answerable": None,
                "gold_answer": "", "gold_pages": [], "gold_anchors": [],
                "gold_pages_by_pdf": {},
                "gold_anchors_by_pdf": {},
                "model_answer": "",  # paste actual generated answer; no LLM called by this script
                "answer_review": None,  # correct / partial / incorrect / correct_refusal
                "evidence_location_review": None,  # correct / incorrect
                "reviewer": "", "notes": "",
            }
            for qid, kind, source, question in example
        ])
    else:
        questions = read("qa_labels.json", [])
        for case in questions:
            case.setdefault("model_answer", "")
            case.setdefault("gold_pages_by_pdf", {})
            case.setdefault("gold_anchors_by_pdf", {})
        write("qa_labels.json", questions)
    if not (WORK / "layout_labels.json").exists():
        # Gold items, including undetected ones, should be entered by the reviewer.
        template = [
            {
                "id": "l01", "source_pdf": "2206.07682v2.pdf", "page": 4,
                "kind": "figure", "label": "Figure 2",
                "gold_bbox": None, "gold_latex": "",
                "predicted_bbox": None, "predicted_text": "",
                "crop_review": None,  # complete / partial / incorrect / missed
                "formula_review": None,  # correct / partial / incorrect / missed
                "reviewer": "", "notes": "",
            },
            {
                "id": "l02", "source_pdf": "1706.03762v7.pdf", "page": 8,
                "kind": "table", "label": "Table 2",
                "gold_bbox": None, "gold_latex": "",
                "predicted_bbox": None, "predicted_text": "",
                "crop_review": None, "formula_review": None,
                "reviewer": "", "notes": "",
            },
            {
                "id": "l03", "source_pdf": "1706.03762v1_img.pdf", "page": 4,
                "kind": "formula", "label": "formula to choose manually",
                "gold_bbox": None, "gold_latex": "",
                "predicted_bbox": None, "predicted_text": "",
                "crop_review": None, "formula_review": None,
                "reviewer": "", "notes": "",
            },
        ]
        for id_, file, page, kind, label in [
            ("l04", "1707.06347v2.pdf", 4, "figure", "Figure 2"),
            ("l05", "1707.06347v2.pdf", 8, "table", "Table 2"),
            ("l06", "1706.03762v7.pdf", 5, "formula", "Equation (2)"),
        ]:
            template.append({
                "id": id_, "source_pdf": file, "page": page, "kind": kind,
                "label": label, "gold_bbox": None, "gold_latex": "",
                "predicted_bbox": None, "predicted_text": "",
                "crop_review": None, "formula_review": None,
                "reviewer": "", "notes": "",
            })
        write("layout_labels.json", template)
    else:
        layout = read("layout_labels.json", [])
        additions = [
            ("l04", "1707.06347v2.pdf", 4, "figure", "Figure 2"),
            ("l05", "1707.06347v2.pdf", 8, "table", "Table 2"),
            ("l06", "1706.03762v7.pdf", 5, "formula", "Equation (2)"),
        ]
        for id_, file, page, kind, label in additions:
            if id_ not in {case["id"] for case in layout}:
                layout.append({
                    "id": id_, "source_pdf": file, "page": page, "kind": kind,
                    "label": label, "gold_bbox": None, "gold_latex": "",
                    "predicted_bbox": None, "predicted_text": "",
                    "crop_review": None, "formula_review": None,
                    "reviewer": "", "notes": "",
                })
        write("layout_labels.json", layout)
    if not (WORK / "translation_labels.json").exists():
        write("translation_labels.json", [{
            "id": "t01", "source_pdf": "1706.03762v7.pdf",
            "page": None, "source_text": "", "translation_text": "",
            "glossary": [],  # [{"source_term": "attention", "expected_translation": "注意力"}]
            "semantic_review": None, "reviewer": "", "notes": "",
            "prompt_tokens": None, "completion_tokens": None,
            "input_usd_per_million": None, "output_usd_per_million": None,
        }])
    if not (WORK / "formula_explanations.json").exists():
        write("formula_explanations.json", [{
            "id": "e01", "source_pdf": "", "page": None,
            "formula_identifier": "", "original_formula": "", "model_explanation": "",
            "input_review": None, "transform_review": None, "output_review": None,
            "citation_review": None, "reviewer": "", "notes": "",
            "prompt_tokens": None, "completion_tokens": None,
            "input_usd_per_million": None, "output_usd_per_million": None,
        }])
    print(f"Initialized {WORK} (380 directed pair labels, preserved existing answers)")


def collect():
    """Evaluate actual retrieval against *user-provided* gold, in an isolated DB."""
    import app
    cases = read("qa_labels.json", [])
    eligible = [c for c in cases if c.get("answerable") in (True, False)
                and c.get("question") and c.get("source_pdfs")]
    filenames = {file for case in eligible for file in case["source_pdfs"]}
    missing = [name for name in filenames if not (ROOT / "pdf" / name).is_file()]
    if missing:
        raise FileNotFoundError("Missing PDF(s): " + ", ".join(sorted(missing)))
    previous = (app.DATA, app.FILES, app.DB_FILE)
    outputs = []
    try:
        with tempfile.TemporaryDirectory() as tmp:
            app.DATA = Path(tmp)
            app.FILES = app.DATA / "uploads"
            app.DB_FILE = app.DATA / "human_eval.sqlite3"
            app.init_db()
            ids = {}
            for filename in sorted(filenames):
                paper_id = uuid.uuid4().hex[:14]
                ids[filename] = paper_id
                with app.db() as db:
                    db.execute(
                        "INSERT INTO papers(id,filename,filepath,created_at) VALUES(?,?,?,?)",
                        (paper_id, filename, str((ROOT / "pdf" / filename).resolve()),
                         app.now()),
                    )
                app.ingest(paper_id)
                with app.db() as db:
                    status = db.execute("SELECT status,error FROM papers WHERE id=?",
                                        (paper_id,)).fetchone()
                if status["status"] != "ready":
                    raise RuntimeError(f"{filename}: {status['error']}")
            for case in eligible:
                by_paper = []
                for filename in case["source_pdfs"]:
                    snippets = app.retrieve(case["question"], ids[filename], limit=3)
                    by_paper.append({
                        "source_pdf": filename,
                        "top3": [{
                            "page": s["page_no"], "chunk_id": s["chunk_id"],
                            "excerpt": s["content"],  # the actual retrieved passage, not a cropped metric string
                        } for s in snippets],
                    })
                anchors = case.get("gold_anchors_by_pdf") or {}
                if not anchors and len(by_paper) == 1 and case.get("gold_anchors"):
                    anchors = {by_paper[0]["source_pdf"]: case["gold_anchors"]}
                anchor_hit = (
                    all(
                        all(any(normalized(anchor) in normalized(item["excerpt"])
                                for item in paper["top3"])
                            for anchor in anchors[paper["source_pdf"]])
                        for paper in by_paper
                    )
                    if all(anchors.get(name) for name in case["source_pdfs"])
                    else None
                )
                outputs.append({
                    "id": case["id"], "by_paper": by_paper,
                    "any_evidence": any(p["top3"] for p in by_paper),
                    "gold_anchor_hit": anchor_hit,
                    "gold_page_hit": (
                        all(set(case["gold_pages_by_pdf"][paper["source_pdf"]]) &
                            {item["page"] for item in paper["top3"]}
                            for paper in by_paper)
                        if all(case.get("gold_pages_by_pdf", {}).get(name)
                               for name in case["source_pdfs"])
                        else bool(set(case.get("gold_pages", [])) &
                                  {item["page"] for p in by_paper for item in p["top3"]})
                        if len(by_paper) == 1 and case.get("gold_pages")
                        else None
                    ),
                })
    finally:
        app.DATA, app.FILES, app.DB_FILE = previous
    write("qa_predictions.json", outputs)
    print(f"Collected local retrieval for {len(outputs)} human-labelled cases; no paid model calls")


def layout_preview():
    """Create reproducible page/candidate images for blinded manual review."""
    import pymupdf
    from layout_inspection import inspect_page, render_visual_crop

    destination = WORK / "previews"
    destination.mkdir(parents=True, exist_ok=True)
    out = []
    for case in read("layout_labels.json", []):
        path = ROOT / "pdf" / case["source_pdf"]
        if not path.is_file():
            raise FileNotFoundError(path)
        with pymupdf.open(path) as pdf:
            page_no = case["page"]
            if not isinstance(page_no, int) or not 1 <= page_no <= len(pdf):
                raise ValueError(f"{case['id']}: invalid physical PDF page")
            page = pdf[page_no - 1]
            page_image = destination / f"{case['id']}_full_page.png"
            page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5),
                            alpha=False).save(page_image)
        inspected = inspect_page(path, page_no)
        kind = case["kind"]
        selected = None
        image = None
        if kind in ("figure", "table"):
            matches = [(index, item) for index, item in enumerate(inspected["visuals"])
                       if item["type"].startswith(kind)
                       and item["label"].casefold().replace(".", "") ==
                       case["label"].casefold().replace(".", "")]
            if len(matches) == 1:
                index, selected = matches[0]
                data, _ = render_visual_crop(path, page_no, index)
                image = destination / f"{case['id']}_candidate.png"
                image.write_bytes(data)
        elif kind == "formula":
            matches = [item for item in inspected["candidates"]
                       if item["type"] == "equation_candidate"]
            if len(matches) == 1:
                selected = matches[0]
        out.append({
            "id": case["id"], "source_pdf": case["source_pdf"],
            "page": page_no, "full_page_image": str(page_image.relative_to(WORK)),
            "candidate_image": str(image.relative_to(WORK)) if image else None,
            "candidate_bbox": selected["bbox"] if selected else None,
            "candidate_text": selected.get("excerpt", selected.get("source_caption", ""))
                              if selected else "",
            "all_candidates": inspected["visuals"] if kind in ("figure", "table")
                              else inspected["candidates"],
            "note": "No unique match means not detected or ambiguous; inspect full page manually.",
        })
    write("layout_predictions.json", out)
    print(f"Generated {len(out)} page previews and candidate inventory in {destination}")


def review_ui():
    """Offline, local-only reviewer UI; export JSON explicitly for scoring."""
    rows = read("graph_labels.json")
    if not rows:
        raise ValueError("Run init first")
    machine_rows = {
        row["id"]: row
        for row in read("graph_machine_audit_result.json", {}).get("rows", [])
    }
    rows = [
        dict(row, machine_audit=machine_rows.get(row["id"], {}))
        for row in rows
    ]
    payload = json.dumps(rows, ensure_ascii=False).replace("</", "<\\/")
    page = r"""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>SourceLab 引文边逐对人工审核</title>
<style>
body{font:16px/1.6 system-ui,"Microsoft YaHei",sans-serif;max-width:1050px;margin:24px auto;padding:0 18px;color:#193042}
button,input,select,textarea{font:inherit}button{padding:5px 12px;margin:4px;cursor:pointer}
button:focus-visible,input:focus-visible{outline:3px solid #2783b1}
section{border:1px solid #b6cbd6;border-radius:8px;margin:16px 0;padding:14px}
textarea{width:98%;min-height:65px} .muted{color:#526676}
code{overflow-wrap:anywhere} .badge{background:#eaf4f9;padding:2px 8px}
</style>
<h1>20 篇局域引用图：逐对核验</h1>
<p>仅本地打开，不连接网络；每条判断需查看源论文 References，确认是否引用目标论文。
共 380 个有向非自引用组合；只查算法预测的 64 条<strong>不能测召回率</strong>。</p>
<p>浏览器允许本地存储时自动暂存；请定期按「导出人工标注 JSON」，将下载文件覆盖
<code>tests/human_eval/graph_labels.json</code> 后运行 <code>python tests/human_eval.py score</code>。
若在别的浏览器继续，先「导入 JSON」。</p>
<p><label>筛选 <select id="filter">
<option value="all">全部</option><option value="pending">未审</option>
<option value="predicted">算法预测</option><option value="unpredicted">算法未预测</option>
<option value="machine_candidate">Agent 机器候选</option>
<option value="machine_manual">机器未直接命中</option>
</select></label> <span id="progress"></span></p>
<section><h2 id="title"></h2><p id="details"></p><p id="links"></p>
<p><strong>算法证据节选：</strong><code id="excerpt"></code></p>
<p><strong>Agent 只读预审：</strong><span id="machine"></span>
（仅提示是否在 References 文本找到目标 arXiv ID/保守标题短语，不能替代人工标签）</p>
<p>源论文 References 是否真实引用目标论文？</p>
<button onclick="decide(true)">是</button>
<button onclick="decide(false)">否</button>
<button onclick="decide(null)">待核对/撤销</button>
<p><label>References 的 PDF 物理页码（仅确认有引用时填写）
<input id="page" type="number" min="1"></label></p>
<p><label>算法预测页是否包含正确的目标引用？
<select id="valid"><option value="">尚未审</option>
<option value="true">是</option><option value="false">否</option></select></label></p>
<p><label>审核人 <input id="reviewer" placeholder="姓名或代号"></label></p>
<p><label>失败类型/核对说明 <textarea id="notes" placeholder="例如：目标仅在正文出现；误匹配其他论文；References 第 N 页"></textarea></label></p></section>
<button onclick="move(-1)">← 上一对</button><button onclick="move(1)">下一对 →</button>
<button onclick="exportData()">导出人工标注 JSON</button>
<label>导入 JSON <input id="import" type="file" accept=".json,application/json"></label>
<script>
const seed = __ROWS__;
const storageKey = "sourcelab-human-graph-v1";
let rows;
try {const saved=JSON.parse(localStorage.getItem(storageKey));
  rows=Array.isArray(saved)&&saved.length===seed.length&&saved[0].id===seed[0].id?saved:seed;
} catch(e) {rows=seed;}
let position=0;
const byId=id=>document.getElementById(id);
const subset=()=>rows.map((r,i)=>i).filter(i=>{
  const mode=byId("filter").value, r=rows[i];
  return mode==="all" || mode==="pending"&&r.gold_cites_target===null ||
    mode==="predicted"&&r.predicted || mode==="unpredicted"&&!r.predicted ||
    mode==="machine_candidate"&&r.machine_audit?.status==="machine_candidate_true" ||
    mode==="machine_manual"&&r.predicted&&r.machine_audit?.status!=="machine_candidate_true";
});
function save(){try{localStorage.setItem(storageKey,JSON.stringify(rows))}
  catch(e){console.warn("本机浏览器禁用自动暂存；请及时导出标注 JSON",e)}}
function sync(){
  const r=rows[position]; if(!r)return;
  const n=subset(),reviewed=rows.filter(x=>x.gold_cites_target!==null).length;
  byId("progress").textContent=`已审 ${reviewed}/380；当前第 ${n.indexOf(position)+1}/${n.length}`;
  byId("title").textContent=r.source_pdf+" → "+r.target_pdf;
  byId("details").textContent=`算法预测：${r.predicted?"是":"否"}；预测页：${r.source_page_predicted??"无"}；人工标签：${r.gold_cites_target===null?"未审":r.gold_cites_target?"真实引用":"未引用"}`;
  const audit=r.machine_audit||{};
  byId("machine").textContent=audit.status==="machine_candidate_true"?
    `候选命中（${audit.match_type}，建议查看第 ${audit.evidence_page} 页）`:
    "未找到直接机器匹配；不等于未引用，仍需查看 PDF";
  const pdf="../../../pdf/"+encodeURIComponent(r.source_pdf);
  byId("links").innerHTML=`<a target="_blank" rel="noopener" href="${pdf}#page=${r.source_page_predicted??1}">打开源论文 PDF（核对 References）</a>`;
  byId("excerpt").textContent=r.evidence_excerpt||"未发现算法预测边；仍需人工核对原论文 References，不能默认为未引用。";
  byId("page").value=r.gold_reference_page??"";
  byId("valid").value=r.predicted_evidence_valid===null?"":String(r.predicted_evidence_valid);
  byId("reviewer").value=r.reviewer||"";
  byId("notes").value=r.notes||"";
}
function persistFields(){const r=rows[position];if(!r)return;
  r.gold_reference_page=byId("page").value?Number(byId("page").value):null;
  r.predicted_evidence_valid=byId("valid").value===""?null:byId("valid").value==="true";
  r.reviewer=byId("reviewer").value;r.notes=byId("notes").value;save();
}
["page","valid","reviewer","notes"].forEach(id=>byId(id).addEventListener("change",persistFields));
function decide(value){persistFields();rows[position].gold_cites_target=value;save();sync()}
function move(offset){persistFields();const n=subset();if(!n.length)return;
  const here=n.indexOf(position);position=n[Math.max(0,Math.min(n.length-1,here+offset))]??n[0];sync();
}
byId("filter").onchange=()=>{position=subset()[0]??position;sync()};
function exportData(){persistFields();const url=URL.createObjectURL(new Blob(
  [JSON.stringify(rows,null,2)],{type:"application/json"}));
  const a=document.createElement("a");a.href=url;a.download="graph_labels.json";a.click();
  setTimeout(()=>URL.revokeObjectURL(url),3000);
}
byId("import").onchange=async e=>{
  const file=e.target.files[0];if(!file)return;
  try{const data=JSON.parse(await file.text());
    if(!Array.isArray(data)||data.length!==seed.length||
      data.some((x,i)=>x.id!==seed[i].id||x.predicted!==seed[i].predicted))
      throw Error("标注文件的论文顺序或算法预测与当前快照不一致");
    rows=data;save();position=0;sync();
  }catch(err){alert("导入失败："+err.message)}
}; sync();
</script></html>""".replace("__ROWS__", payload)
    (WORK / "review_graph.html").write_text(page, encoding="utf-8")
    questions = read("qa_labels.json", [])
    q_payload = json.dumps(questions, ensure_ascii=False).replace("</", "<\\/")
    qa_page = r"""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>SourceLab 问答人工真值填写</title>
<style>body{font:16px/1.6 system-ui,"Microsoft YaHei",sans-serif;
max-width:1050px;margin:24px auto;padding:0 18px;color:#193042}
button,input,select,textarea{font:inherit}button{padding:5px 12px;margin:4px;cursor:pointer}
textarea{width:98%;min-height:65px}label{display:block;margin:12px 0}
section{border:1px solid #b6cbd6;border-radius:8px;padding:16px;margin:12px 0}
</style>
<h1>原文问答：人工真值填写</h1>
<p>只在本机运行，未调用 AI。核对原论文物理页（从 1 开始）后填写。
定期导出 JSON，覆盖 <code>tests/human_eval/qa_labels.json</code>；刷新程序页面不会自动写回磁盘。
已有问题不能覆盖全部任务类型，可在 JSON 中复制条目并增加唯一 id。</p>
<p id="progress"></p>
<section><h2 id="question"></h2><p id="papers"></p>
<label>是否可从所选论文回答
<select id="answerable"><option value="">待标</option><option value="true">有足够证据</option>
<option value="false">不可回答/证据不足</option></select></label>
<label>人工标准答案（不可回答时写无法确定）<textarea id="answer"></textarea></label>
<label>单篇 PDF 物理页（逗号分隔）<input id="pages" size="65"></label>
<label>单篇原文证据短语（每行一个，精确包含匹配）<textarea id="anchors"></textarea></label>
<label>跨论文每篇金标准页（可选；单篇论文留 <code>{}</code>），JSON 对象，例如 {"a.pdf":[4],"b.pdf":[8]}
<textarea id="crosspages"></textarea></label>
<label>跨论文每篇证据词组（可选；单篇论文留 <code>{}</code>）。必须是原文短语；推荐严格 JSON，例如 {"a.pdf":["attention"],"b.pdf":["normalization"]}。
也兼容方括号中的未加引号短词，但导出时会自动规范化。
<textarea id="crossanchors"></textarea></label>
<label>网站实际答复（若没有向模型提问则留空）
<textarea id="model"></textarea></label>
<label>人工判定实际答复<select id="review"><option value="">未审</option>
<option value="correct">正确</option><option value="partial">部分正确</option>
<option value="incorrect">错误</option><option value="correct_refusal">正确拒答</option></select></label>
<label>证据跳转/高亮位置人工判定<select id="location"><option value="">未审</option>
<option value="correct">正确位置</option><option value="incorrect">定位错误</option></select></label>
<label>审核人 <input id="reviewer"></label>
<label>原因或失败类型 <textarea id="notes"></textarea></label>
</section>
<button onclick="move(-1)">← 上一题</button><button onclick="move(1)">下一题 →</button>
<button onclick="exportData()">导出问答真值 JSON</button>
<label>导入先前标注 JSON <input id="import" type="file" accept=".json,application/json"></label>
<script>
const seed=__ROWS__,key="sourcelab-human-qa-v1";
let rows;try{const prev=JSON.parse(localStorage.getItem(key));rows=Array.isArray(prev)&&
  prev.length===seed.length&&prev.every((x,i)=>x.id===seed[i].id)?prev:seed;
}catch(e){rows=seed}let i=0;
const el=id=>document.getElementById(id);
function save(){try{localStorage.setItem(key,JSON.stringify(rows))}catch(e){console.warn(e)}}
function parseObject(text, field, tolerant=false){
  let s=(text||"").trim().replace(/[，]/g,",").replace(/[：]/g,":")
    .replace(/[“”]/g,'"').replace(/[‘’]/g,"'");
  if(!s)return {};
  try{
    const value=JSON.parse(s);
    if(!value||Array.isArray(value)||typeof value!=="object")
      throw Error("必须是对象，例如 {}");
    return value;
  }catch(strictError){
    if(!tolerant)throw Error(field+" 必须是合法 JSON 对象；键和值都要用双引号");
    // Friendly fallback for the common reviewer shorthand:
    // {"paper.pdf": [GPU, 8 P100], "other.pdf": [normalization]}
    const result={}, pair=/"([^"]+)"\s*:\s*\[([^\]]*)\]/g;
    let match, count=0;
    while((match=pair.exec(s))){
      const key=match[1].trim();
      const values=match[2].split(",").map(x=>x.trim())
        .filter(Boolean).map(x=>x.replace(/^"|"$/g,"").trim());
      if(!key||!values.length)continue;
      result[key]=(result[key]||[]).concat(values);
      count++;
    }
    if(count===0)throw Error(field+" 不是可识别的对象；请使用 {\"文件.pdf\":[\"原文短语\"]}");
    return result;
  }
}
function render(){const r=rows[i];el("question").textContent=r.id+" · "+r.question;
el("progress").textContent=`第 ${i+1}/${rows.length} 题；已标 ${rows.filter(x=>typeof x.answerable==="boolean").length}/${rows.length}`;
const pdfs=r.source_pdfs.map(name=>{
  const a=document.createElement("a");a.href="../../../pdf/"+encodeURIComponent(name);
  a.target="_blank";a.rel="noopener";a.textContent=name;
  return a;});
el("papers").replaceChildren(...pdfs.flatMap((a,j)=>j?[document.createTextNode("　"),a]:[a]));
el("answerable").value=r.answerable===null?"":String(r.answerable);
el("answer").value=r.gold_answer||"";el("pages").value=(r.gold_pages||[]).join(",");
el("anchors").value=(r.gold_anchors||[]).join("\n");
el("crosspages").value=JSON.stringify(r.gold_pages_by_pdf||{},null,2);
el("crossanchors").value=JSON.stringify(r.gold_anchors_by_pdf||{},null,2);
el("model").value=r.model_answer||"";el("review").value=r.answer_review||"";
el("location").value=r.evidence_location_review||"";
el("reviewer").value=r.reviewer||"";el("notes").value=r.notes||"";
}
function persist(){const r=rows[i];
  let cp,ca;try{
    cp=parseObject(el("crosspages").value,"跨论文金标准页",false);
    Object.entries(cp).forEach(([name,pages])=>{
      if(!Array.isArray(pages)||pages.some(x=>!Number.isInteger(Number(x))||Number(x)<1))
        throw Error("金标准页必须是正整数数组，例如 {\"paper.pdf\":[8]}");
      cp[name]=pages.map(Number);
    });
    ca=parseObject(el("crossanchors").value,"跨论文证据词组",true);
    Object.entries(ca).forEach(([name,phrases])=>{
      if(!Array.isArray(phrases)||phrases.some(x=>!String(x).trim()))
        throw Error("证据词组必须是非空字符串数组");
      ca[name]=phrases.map(x=>String(x).trim());
    });
  }catch(err){alert("导出前请修正：\n"+err.message+
    "\n\n推荐格式：{\"1706.03762v7.pdf\":[\"GPU\",\"8 P100\"]}");return false}
  const raw=el("pages").value.trim();
  const pages=raw?raw.split(",").map(x=>Number(x.trim())):[];
  if(pages.some(x=>!Number.isInteger(x)||x<1)){alert("PDF 页码必须是正整数");return false}
  r.answerable=el("answerable").value===""?null:el("answerable").value==="true";
  r.gold_answer=el("answer").value;r.gold_pages=pages;
  r.gold_anchors=el("anchors").value.split("\n").map(x=>x.trim()).filter(Boolean);
  r.gold_pages_by_pdf=cp;r.gold_anchors_by_pdf=ca;
  r.model_answer=el("model").value;r.answer_review=el("review").value||null;
  r.evidence_location_review=el("location").value||null;
  r.reviewer=el("reviewer").value;r.notes=el("notes").value;save();return true;
}
function move(d){if(persist()){i=Math.max(0,Math.min(rows.length-1,i+d));render()}}
function exportData(){if(!persist())return;const url=URL.createObjectURL(new Blob(
  [JSON.stringify(rows,null,2)],{type:"application/json"}));
  const a=document.createElement("a");a.href=url;a.download="qa_labels.json";a.click();
  setTimeout(()=>URL.revokeObjectURL(url),3000)}
el("import").onchange=async event=>{const file=event.target.files[0];if(!file)return;
  try{const data=JSON.parse(await file.text());
    if(!Array.isArray(data)||!data.length||data.some(x=>!x.id||!Array.isArray(x.source_pdfs)))
      throw Error("问答标注 JSON 格式不符");
    rows=data;i=0;save();render();
  }catch(err){alert("导入失败："+err.message)}
};render();
</script></html>""".replace("__ROWS__", q_payload)
    (WORK / "review_qa.html").write_text(qa_page, encoding="utf-8")
    print(f"Open offline reviewers: {WORK / 'review_graph.html'} ; "
          f"{WORK / 'review_qa.html'}")


def ratio(count, total):
    return {"numerator": count, "denominator": total,
            "value": round(count / total, 4) if total else None}


def bbox_iou(a, b):
    if not (isinstance(a, list) and isinstance(b, list) and len(a) == len(b) == 4):
        return None
    if a[2] <= a[0] or a[3] <= a[1] or b[2] <= b[0] or b[3] <= b[1]:
        return None
    area1, area2 = (a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])
    intersect = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(
        0, min(a[3], b[3]) - max(a[1], b[1]))
    return round(intersect / (area1 + area2 - intersect), 4)


def charge(row):
    keys = ("prompt_tokens", "completion_tokens",
            "input_usd_per_million", "output_usd_per_million")
    vals = [row.get(k) for k in keys]
    if any(v is None or isinstance(v, bool) or not isinstance(v, (int, float))
           or v < 0 for v in vals):
        return None
    return round((vals[0] * vals[2] + vals[1] * vals[3]) / 1e6, 8)


def score():
    labels = read("graph_labels.json")
    manifest = read("graph_manifest.json")
    graph_path = BASE / "tests" / "graph20_report.json"
    if not labels or not manifest or manifest["report_sha256"] != fingerprint(graph_path):
        raise ValueError("Run init first, or reconcile changed graph snapshot")
    if len(labels) != 380 or len({x["id"] for x in labels}) != 380:
        raise ValueError("Gold must cover exactly 380 unique directed pairs")
    allowed = (True, False, None)
    for row in labels:
        if row["gold_cites_target"] not in allowed or row["predicted_evidence_valid"] not in allowed:
            raise ValueError(f"Invalid graph label: {row['id']}")
    reviewed = [x for x in labels if x["gold_cites_target"] is not None]
    all_reviewed = len(reviewed) == len(labels)
    predicted = [x for x in labels if x["predicted"]]
    predicted_reviewed = [x for x in predicted if x["gold_cites_target"] is not None]
    tp = sum(x["predicted"] and x["gold_cites_target"] is True for x in labels)
    fp = sum(x["predicted"] and x["gold_cites_target"] is False for x in labels)
    fn = sum(not x["predicted"] and x["gold_cites_target"] is True for x in labels)
    graph = {
        "pairs_reviewed": ratio(len(reviewed), len(labels)),
        "predicted_edges_reviewed": ratio(len(predicted_reviewed), len(predicted)),
        "provisional_precision_reviewed_only": ratio(tp, tp + fp),
        "complete_precision": ratio(tp, len(predicted)) if len(predicted_reviewed) == len(predicted) else None,
        "complete_recall": ratio(tp, tp + fn) if all_reviewed else None,
        "true_positive": tp, "false_positive": fp, "false_negative": fn,
        "source_page_validity_reviewed_only": ratio(
            sum(x["predicted_evidence_valid"] is True for x in predicted),
            sum(x["predicted_evidence_valid"] is not None for x in predicted)),
        "failure_examples": [x["id"] for x in labels
                             if x["gold_cites_target"] is False and x["predicted"] or
                             x["gold_cites_target"] is True and not x["predicted"]][:20],
        "warning": "No recall until all 380 pairs independently reviewed; PageRank never scores quality.",
    }
    if graph["complete_precision"] is not None and graph["complete_recall"]["denominator"]:
        precision = graph["complete_precision"]["value"]
        recall = graph["complete_recall"]["value"]
        graph["f1"] = round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0
    qa = read("qa_labels.json", [])
    predictions = {x["id"]: x for x in read("qa_predictions.json", [])}
    answerable = [x for x in qa if x.get("answerable") is True]
    unanswerable = [x for x in qa if x.get("answerable") is False]
    page_cases = [x for x in answerable if x["id"] in predictions
                  and predictions[x["id"]]["gold_page_hit"] is not None]
    anchor_cases = [x for x in answerable if x["id"] in predictions
                    and predictions[x["id"]]["gold_anchor_hit"] is not None]
    answer_rated = [x for x in qa if x.get("model_answer") and x.get("answer_review") in
                    ("correct", "partial", "incorrect", "correct_refusal")]
    refuse_rated = [x for x in unanswerable if x.get("model_answer")
                    and x.get("answer_review") in
                    ("correct", "partial", "incorrect", "correct_refusal")]
    location_rated = [x for x in qa if x.get("evidence_location_review")
                      in ("correct", "incorrect")]
    output_qa = {
        "top3_gold_page_coverage": ratio(sum(
            predictions[x["id"]]["gold_page_hit"] is True for x in page_cases),
            len(page_cases)),
        "top3_gold_anchor_coverage": ratio(sum(
            predictions[x["id"]]["gold_anchor_hit"] is True for x in anchor_cases),
            len(anchor_cases)),
        "answer_correct_human_only": ratio(sum(
            x["answer_review"] == "correct" for x in answer_rated if x["answerable"] is True),
            sum(x["answerable"] is True for x in answer_rated)),
        "negative_correct_refusal_human_only": ratio(sum(
            x["answer_review"] == "correct_refusal" for x in refuse_rated),
            len(refuse_rated)),
        "negative_no_evidence_observed": ratio(sum(
            not predictions[x["id"]]["any_evidence"] for x in unanswerable
            if x["id"] in predictions), sum(x["id"] in predictions for x in unanswerable)),
        "source_location_human_only": ratio(
            sum(x["evidence_location_review"] == "correct" for x in location_rated),
            len(location_rated)),
        "failure_examples": [x["id"] for x in qa if x.get("answer_review") == "incorrect"
                             or x.get("evidence_location_review") == "incorrect"][:20],
        "warning": "A missing retrieval snippet is not a model refusal; correctness and refusal require human-judged responses.",
    }
    layouts = read("layout_labels.json", [])
    layout_predictions = {x["id"]: x for x in read("layout_predictions.json", [])}
    crop_cases = [x for x in layouts if x.get("kind") in ("figure", "table")
                  and x.get("crop_review") in ("complete", "partial", "incorrect", "missed")]
    formula_cases = [x for x in layouts if x.get("kind") == "formula"
                     and x.get("formula_review") in ("correct", "partial", "incorrect", "missed")]
    crop_ious = {x["id"]: bbox_iou(
                       x.get("gold_bbox"),
                       x.get("predicted_bbox") or
                       layout_predictions.get(x["id"], {}).get("candidate_bbox"))
                 for x in layouts if x.get("gold_bbox")}
    available_ious = [value for value in crop_ious.values() if value is not None]
    translations = read("translation_labels.json", [])
    translation_cases = [x for x in translations
                         if x.get("source_text") and x.get("translation_text")]
    import bilingual
    translation_checks = []
    for x in translation_cases:
        src_nums = Counter(n.strip(".,") for n in bilingual.NUMBER.findall(x["source_text"]))
        dst_nums = Counter(n.strip(".,") for n in bilingual.NUMBER.findall(x["translation_text"]))
        terms = x.get("glossary", [])
        translation_checks.append({
            "id": x["id"], "numbers_preserved": src_nums == dst_nums,
            "term_pairs_matched": sum(y.get("expected_translation", "")
                                      in x["translation_text"]
                                      for y in terms if y.get("expected_translation")),
            "term_pairs_specified": sum(bool(y.get("expected_translation")) for y in terms),
            "manual_semantics": x.get("semantic_review"), "estimated_usd": charge(x),
        })
    explanations = read("formula_explanations.json", [])
    explanation_cases = [x for x in explanations if x.get("model_explanation")]
    result = {
        "graph": graph, "qa": output_qa,
        "layout": {
            "figure_table_complete_crop": ratio(
                sum(x["crop_review"] == "complete" for x in crop_cases), len(crop_cases)),
            "figure_table_iou": crop_ious,
            "mean_iou_of_detected_with_gold": round(
                sum(available_ious) / len(available_ious), 4) if available_ious else None,
            "formula_correct_human_only": ratio(
                sum(x["formula_review"] == "correct" for x in formula_cases),
                len(formula_cases)),
            "warning": "No LaTeX recovery score without independent gold LaTeX and actual decoded predictions.",
        },
        "translation": {
            "blocks_checked": len(translation_checks),
            "digit_preservation": ratio(sum(x["numbers_preserved"] for x in translation_checks),
                                        len(translation_checks)),
            "details": translation_checks,
            "warning": "Digit equality and glossary string match do not prove semantic translation quality.",
        },
        "formula_explanation": {
            "human_rated": sum(x.get("input_review") in ("correct", "incorrect", "partial")
                               and x.get("transform_review") in ("correct", "incorrect", "partial")
                               and x.get("output_review") in ("correct", "incorrect", "partial")
                               for x in explanation_cases),
            "details": [{ "id": x["id"], "estimate_usd": charge(x),
                          "input_review": x.get("input_review"),
                          "transform_review": x.get("transform_review"),
                          "output_review": x.get("output_review"),
                          "citation_review": x.get("citation_review")}
                        for x in explanation_cases],
            "warning": "Model explanations require reviewer checks against original PDF; no generated correctness claim.",
        },
    }
    write("results.json", result)
    print(f"Wrote {WORK / 'results.json'}")
    print(f"Graph labels: {len(reviewed)}/380; complete precision = {graph['complete_precision']}; "
          f"recall = {graph['complete_recall']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "collect", "layout_preview", "review_ui", "score"))
    command = parser.parse_args().command
    globals()[command]()
