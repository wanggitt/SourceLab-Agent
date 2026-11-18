"""对文件名无关的近重复、查询证据和扫描件降级做回归测试。"""
import json
import shutil
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import app
import scholar_api
from evaluate_facts import CASES_FILE, inspect_case, normalize
from hybrid_retrieval import latent_candidates, reciprocal_rank_fusion
from layout_inspection import inspect_page
from equation_review import (
    equation_prompt, check_equation_response,
    batch_equation_prompt, check_batch_response, parse_batch_model_reply,
)
from diagram_review import topology_prompt, verify_topology, parse_topology_response
from equation_visual import original_equation_crop, equation_source_region
from publication_lookup import lookup_publication
from research_plan import research_plan_prompt, verify_research_plan, PLAN_FIELDS
from document_structure import build_structure
from horizon import arxiv_month, scan_future_work
from horizon import keyword_candidates
from task_workflow import parse_model_plan, task_plan
from source_preview import render_evidence
from bilingual import (
    export_bilingual_html, page_units, protected_translation_input,
    restored_translation,
)


SAMPLE_DIR = Path(__file__).resolve().parents[2] / "pdf"


class MVPTests(unittest.TestCase):
    def setUp(self):
        self.model_env = patch.dict(
            app.os.environ, {
                "LLM_CHAT_ENDPOINT": "", "LLM_MODEL": "", "LLM_API_KEY": "",
            },
        )
        self.model_env.start()
        self.temp = tempfile.TemporaryDirectory()
        self.original = (app.DATA, app.FILES, app.DB_FILE)
        app.DATA = Path(self.temp.name)
        app.FILES = app.DATA / "uploads"
        app.DB_FILE = app.DATA / "test.sqlite3"
        app.init_db()

    def tearDown(self):
        app.DATA, app.FILES, app.DB_FILE = self.original
        self.temp.cleanup()
        self.model_env.stop()

    def ingest_one(self, filename, shown_name=None):
        path = SAMPLE_DIR / filename
        if not path.is_file():
            self.skipTest(f"缺少样例 {path}")
        paper_id = __import__("uuid").uuid4().hex[:14]
        with app.db() as c:
            c.execute("INSERT INTO papers(id,filename,filepath,created_at) VALUES(?,?,?,?)",
                      (paper_id, shown_name or filename, str(path.resolve()), app.now()))
        app.ingest(paper_id)
        return paper_id

    def test_query_cites_existing_page(self):
        paper = self.ingest_one("1706.03762v1.pdf")
        result = app.retrieve("Transformer base model GPU", paper)
        self.assertTrue(result)
        self.assertEqual(result[0]["paper_id"], paper)
        self.assertGreaterEqual(result[0]["page_no"], 1)
        self.assertTrue(result[0]["content"])

    def test_chinese_architecture_query_hits_sciencedirect_framework(self):
        cover = (
            "Contents lists available at ScienceDirect\n"
            "Information Fusion\n"
            "journal homepage: www.elsevier.com/locate/inffus\n"
            "Full Length Article\n"
            "Burden of proof: Calibrated evidential arbitration for asymmetric \n"
            "decision-level fusion in vision–language recognition\n"
            "Guichao Zhou\n"
        )
        title = app.guess_title(cover, "CEA.pdf")
        self.assertEqual(title,
                         "Burden of proof: Calibrated evidential arbitration for "
                         "asymmetric decision-level fusion in vision–language recognition")
        self.assertIn("framework", app.terms_for("该模型架构"))
        paper_id = "d" * 14
        with app.db() as conn:
            conn.execute(
                """INSERT INTO papers(id,filename,filepath,title,status,pages,
                   chunks,created_at) VALUES(?,?,?,?,?,?,?,?)""",
                (paper_id, "CEA.pdf", "unused", title, "ready", 4, 1, app.now()),
            )
            source = ("3. Calibrated evidential arbitration\n"
                      "We propose Calibrated Evidential Arbitration (CEA), a framework "
                      "in which an auxiliary source should overturn a default prediction.")
            row = conn.execute(
                "INSERT INTO chunks(paper_id,page_no,content) VALUES(?,?,?)",
                (paper_id, 4, source),
            )
            conn.execute(
                "INSERT INTO chunks_fts(rowid,paper_id,page_no,content) VALUES(?,?,?,?)",
                (row.lastrowid, paper_id, 4, source),
            )
        evidence = app.retrieve("该模型架构", paper_id, method="sparse")
        self.assertEqual(evidence[0]["page_no"], 4)
        self.assertIn("framework", evidence[0]["content"])

    def test_chinese_dataset_question_locates_benchmark_page(self):
        paper_id = "e" * 14
        with app.db() as conn:
            conn.execute(
                """INSERT INTO papers(id,filename,filepath,title,status,created_at)
                   VALUES(?,?,?,?,'ready',?)""",
                (paper_id, "study.pdf", "unused", "Benchmark Study", app.now()),
            )
            text = ("4.1 Experimental setup\nDatasets and Episode Suites. "
                    "We evaluate on CIFAR-FS, DTD, EuroSAT, and miniImageNet.")
            row = conn.execute(
                "INSERT INTO chunks(paper_id,page_no,content) VALUES(?,6,?)",
                (paper_id, text),
            )
            conn.execute(
                "INSERT INTO chunks_fts(rowid,paper_id,page_no,content) VALUES(?,?,6,?)",
                (row.lastrowid, paper_id, text),
            )
        found = app.retrieve("该模型使用什么数据集", paper_id, method="sparse")
        self.assertEqual(found[0]["page_no"], 6)
        self.assertIn("EuroSAT", found[0]["content"])

    def test_chinese_backbone_question_cites_both_original_channels(self):
        paper_id = "f" * 14
        source = (
            "The text-alignment channel uses CLIP ViT-L/14 at 336-pixel "
            "resolution [1]. The visual-support channel uses a frozen DINOv3 "
            "ViT-B/16 visual encoder [29]."
        )
        with app.db() as conn:
            conn.execute(
                """INSERT INTO papers(id,filename,filepath,title,status,created_at)
                   VALUES(?,?,?,?,'ready',?)""",
                (paper_id, "study.pdf", "unused", "Frozen channels", app.now()),
            )
            cursor = conn.execute(
                "INSERT INTO chunks(paper_id,page_no,content) VALUES(?,4,?)",
                (paper_id, source),
            )
            conn.execute(
                "INSERT INTO chunks_fts(rowid,paper_id,page_no,content) VALUES(?,?,4,?)",
                (cursor.lastrowid, paper_id, source),
            )
        hits = app.retrieve("采用的骨干模型是什么", paper_id, method="sparse")
        self.assertEqual(hits[0]["page_no"], 4)
        text = app.extractive_answer("采用的骨干模型是什么", hits)
        self.assertIn("CLIP ViT-L/14", text)
        self.assertIn("DINOv3 ViT-B/16", text)
        self.assertIn("并非从数据集推断", text)

    def test_spaced_abstract_and_wrapped_title_keep_real_authors(self):
        paper_id = "f" * 14
        title = ("Burden of proof: Calibrated evidential arbitration "
                 "for asymmetric decision-level fusion")
        text = (
            "Contents lists available at ScienceDirect\nInformation Fusion\n"
            "Full Length Article\n"
            "Burden of proof: Calibrated evidential arbitration for asymmetric \n"
            "decision-level fusion\nGuichao Zhou\n, Yuwu Lu\n"
            "School of Artificial Intelligence, South China Normal University\n"
            "a r t i c l e i n f o\nKeywords:\nVision-language\n"
            "a b s t r a c t\nWe propose CEA using two frozen evidence channels.\n"
            "1. Introduction\nUnrelated introductory paragraph."
        )
        with app.db() as conn:
            conn.execute(
                """INSERT INTO papers(id,filename,filepath,title,status,pages,created_at)
                   VALUES(?,?,?,?,'ready',1,?)""",
                (paper_id, "CEA.pdf", "unused", title, app.now()),
            )
            conn.execute(
                "INSERT INTO chunks(paper_id,page_no,content) VALUES(?,1,?)",
                (paper_id, text),
            )
        profile = app.paper_profile(paper_id)
        self.assertEqual(profile["authors"], ["Guichao Zhou", "Yuwu Lu"])
        self.assertIn("South China Normal University", profile["affiliations"][0])
        self.assertEqual(profile["abstract"],
                         "We propose CEA using two frozen evidence channels.")

    def test_profile_extracts_title_authors_affiliation_and_abstract(self):
        paper = self.ingest_one("1706.03762v7.pdf")
        profile = app.paper_profile(paper)
        self.assertIn("Attention Is All You Need", profile["title"])
        self.assertTrue(profile["authors"])
        self.assertTrue(profile["affiliations"])
        self.assertTrue(profile["abstract"])
        self.assertEqual(profile["pages"], 15)
        self.assertIn("启发式", profile["note"])

    def test_layout_inspection_finds_caption_equation_and_table_candidates(self):
        self.ingest_one("1706.03762v7.pdf")
        page4 = inspect_page(SAMPLE_DIR / "1706.03762v7.pdf", 4)
        self.assertTrue(any(c["type"] == "figure_caption" and c["label"] == "Figure 2"
                            for c in page4["candidates"]))
        self.assertTrue(any(c["type"] == "equation_candidate"
                            for c in page4["candidates"]))
        page9 = inspect_page(SAMPLE_DIR / "1706.03762v7.pdf", 9)
        self.assertTrue(any(c["type"] == "table_caption" and c["label"] == "Table 3"
                            for c in page9["candidates"]))
        self.assertTrue(any(t["rows"] >= 2 and t["columns"] >= 2
                            for t in page9["tables"]))
        with self.assertRaisesRegex(ValueError, "页码"):
            inspect_page(SAMPLE_DIR / "1706.03762v7.pdf", 999)
        from layout_inspection import render_layout_preview
        png, preview = render_layout_preview(SAMPLE_DIR / "1706.03762v7.pdf", 9)
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertTrue(preview["tables"])
        from layout_inspection import render_visual_crop
        page4 = inspect_page(SAMPLE_DIR / "1706.03762v7.pdf", 4)
        self.assertTrue(page4["visuals"])
        figure_png, visual = render_visual_crop(SAMPLE_DIR / "1706.03762v7.pdf", 4, 0)
        self.assertTrue(figure_png.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertIn("candidate", visual["type"])
        with self.assertRaisesRegex(ValueError, "编号"):
            render_visual_crop(SAMPLE_DIR / "1706.03762v7.pdf", 4, 99)
        emerging = SAMPLE_DIR / "209_Emergent_Abilities_of_Larg.pdf"
        if emerging.is_file():
            page = inspect_page(emerging, 4)
            fig = next(v for v in page["visuals"] if v["label"] == "Figure 2")
            self.assertLess(fig["bbox"][1], 110)
            self.assertGreater(fig["bbox"][3], 480)
            self.assertTrue(fig["visual_content_detected"])
            png, _ = render_visual_crop(emerging, 4,
                next(i for i, visual in enumerate(page["visuals"])
                     if visual["label"] == "Figure 2"))
            from PIL import Image
            image = Image.open(__import__("io").BytesIO(png))
            self.assertGreater(image.height, 650)

    def test_equation_review_prompt_uses_source_and_explicit_consent(self):
        paper_id = self.ingest_one("1706.03762v7.pdf")
        with self.assertRaisesRegex(ValueError, "确认"):
            app.review_equation(paper_id, 4, 0)
        inspected = inspect_page(SAMPLE_DIR / "1706.03762v7.pdf", 4)
        formula = next(x for x in inspected["candidates"]
                       if x["type"] == "equation_candidate")
        system, user = equation_prompt("Paper", 4, formula["excerpt"], "same page")
        self.assertIn("变量是否在证据中定义", system)
        self.assertIn(formula["excerpt"], user)
        short_quote = formula["excerpt"][:28]
        answer = {
            "choices": [{"message": {"content": json.dumps({
                "input": "原文未说明变量的完整来源 [1]",
                "transformation": "该式表示局部计算，符号须核查 [1]",
                "output": "结果含义需核对上下文 [1]",
                "uncertainty": "PDF 候选可能缺符号",
                "source_quote": short_quote,
            }, ensure_ascii=False)}}],
            "usage": {"prompt_tokens": 85, "completion_tokens": 42,
                      "total_tokens": 127},
        }

        class Response:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def read(self): return json.dumps(
                answer, ensure_ascii=False
            ).encode("utf-8")

        with patch.dict(app.os.environ, {
            "LLM_CHAT_ENDPOINT": "http://model.local/v1/chat/completions",
            "LLM_MODEL": "mock-reviewer", "LLM_API_KEY": "not-real",
        }), patch("app.urllib.request.urlopen", return_value=Response()) as outbound:
            result = app.review_equation(paper_id, 4, 0, confirm_cost=True)
        self.assertEqual(result["status"], "draft_needs_review")
        self.assertEqual(result["usage"]["total_tokens"], 127)
        self.assertEqual(result["draft"]["source_quote"], short_quote)
        self.assertEqual(result["page_no"], 4)
        self.assertEqual(outbound.call_count, 1)
        sent = json.loads(outbound.call_args.args[0].data.decode("utf-8"))
        self.assertIn(formula["excerpt"], sent["messages"][1]["content"])
        self.assertIn("低信任", sent["messages"][0]["content"])
        audit = next(x for x in app.audit_events() if x["id"] == result["audit_id"])
        self.assertEqual(audit["event_type"], "equation_review")
        self.assertEqual(audit["total_tokens"], 127)
        with self.assertRaisesRegex(ValueError, "数字"):
            check_equation_response({
                **result["draft"], "input": "虚构数字 9999999 [1]",
            }, formula["excerpt"])

    def test_equation_review_401_keeps_original_and_no_model_draft(self):
        import io
        paper_id = self.ingest_one("1706.03762v7.pdf")
        unauthorized = urllib.error.HTTPError(
            "http://model.local/", 401, "Authorization Required",
            {}, io.BytesIO(b"secret response must not be logged"),
        )
        with patch.dict(app.os.environ, {
            "LLM_CHAT_ENDPOINT": "http://model.local/v1/chat/completions",
            "LLM_MODEL": "mock", "LLM_API_KEY": "not-real",
        }), patch("app.urllib.request.urlopen", side_effect=unauthorized):
            result = app.review_equation(paper_id, 4, 0, confirm_cost=True)
        self.assertEqual(result["status"], "error")
        self.assertIsNone(result["draft"])
        self.assertIn("401", result["message"])
        self.assertTrue(result["equation"])
        self.assertNotIn("secret response", result["message"])

    def test_batch_review_uses_indexed_equations_not_layout_index(self):
        paper_id = self.ingest_one("1706.03762v7.pdf")
        source_equations = app.document_structure(paper_id)["equations"]
        self.assertGreaterEqual(len(source_equations), 2)
        with self.assertRaisesRegex(ValueError, "确认"):
            app.review_all_equations(paper_id, confirm_cost=False)
        with patch.dict(app.os.environ, {
            "LLM_CHAT_ENDPOINT": "", "LLM_MODEL": "",
        }):
            result = app.review_all_equations(paper_id, confirm_cost=True)
        self.assertEqual(result["count"], len(source_equations))
        self.assertEqual(result["equations"][0]["formula"],
                         source_equations[0]["excerpt"])
        self.assertEqual(result["status"], "error")
        self.assertIsNone(result["draft"])
        self.assertTrue(result["audit_id"])
        self.assertEqual(
            next(x for x in app.audit_events() if x["id"] == result["audit_id"])["mode"],
            "error",
        )

    def test_batch_report_flags_number_gaps_and_skips_prose_eq_references(self):
        from document_structure import build_structure
        structured = build_structure(
            [(4, "a = b + c (1)\n"
                  "r ⟺ h (2)\n"
                  "> P(H)P(R) (4)\n"
                  "n ≳ alpha (12)\n"
                  "2: Combine. For each x ∈ S, apply rule (Eqs. (9)\n"
                  "y = a + c (3)")], [], [],
        )
        self.assertEqual(
            [row["excerpt"] for row in structured["equations"]],
            ["a = b + c (1)", "r ⟺ h (2)", "> P(H)P(R) (4)",
             "n ≳ alpha (12)", "y = a + c (3)"],
        )

    def test_equation_crop_recombines_same_row_from_source_pdf(self):
        import pymupdf
        pdf = Path(self.temp.name) / "formula.pdf"
        doc = pymupdf.open()
        for _ in range(4):
            doc.new_page()
        page = doc[3]
        page.insert_text((40, 100), "delta = r - h")
        page.insert_text((190, 100), "SH = h / |S|")
        page.insert_text((273, 100), "(1)")
        doc.save(str(pdf))
        doc.close()
        png, rect = original_equation_crop(pdf, 4, 1)
        self.assertTrue(png.startswith(b"\x89PNG"))
        self.assertLess(rect[0], 50)
        self.assertGreater(rect[2], 265)
        _, text = equation_source_region(pdf, 4, 1)
        self.assertIn("delta", text)
        self.assertIn("SH", text)
        with self.assertRaisesRegex(ValueError, "没有可定位"):
            original_equation_crop(pdf, 4, 2)

    def test_figure_caption_right_and_table_caption_below_have_real_crop(self):
        import pymupdf
        file_path = Path(self.temp.name) / "horizontal-caption.pdf"
        doc = pymupdf.open()
        figure = doc.new_page(width=612, height=792)
        figure.draw_rect(pymupdf.Rect(125, 82, 350, 195))
        figure.insert_text((390, 145), "Figure 2: Actual graph at the left.")
        table = doc.new_page(width=612, height=792)
        for y in (91, 118, 145):
            table.draw_line((105, y), (500, y))
        table.insert_text((118, 112), "Model")
        table.insert_text((250, 112), "Metric")
        table.insert_text((118, 138), "Baseline")
        table.insert_text((250, 138), "0.75")
        table.insert_text((110, 181), "Table 2: Experimental results.")
        doc.save(str(file_path))
        doc.close()
        picture = next(x for x in inspect_page(file_path, 1)["visuals"]
                       if x["label"] == "Figure 2")
        self.assertLess(picture["bbox"][0], 130)
        self.assertLess(picture["bbox"][1], 90)
        self.assertGreater(picture["bbox"][2], 390)
        preview, _ = __import__("layout_inspection").render_visual_crop(
            file_path, 1, 0)
        self.assertTrue(preview.startswith(b"\x89PNG"))
        numbers = next(x for x in inspect_page(file_path, 2)["visuals"]
                       if x["label"] == "Table 2")
        self.assertLess(numbers["bbox"][1], 92)
        self.assertGreater(numbers["bbox"][3], 180)

    def test_batch_prompt_requires_full_list_quotes_and_per_formula_ids(self):
        items = [
            {"source_id": "E1", "page_no": 4,
             "formula": "a = b + c (1)", "context": "b and c are inputs."},
            {"source_id": "E2", "page_no": 5,
             "formula": "y = a (2)", "context": "The output is y."},
        ]
        system, user = batch_equation_prompt("Example paper", items)
        self.assertIn("每一条", user)
        self.assertIn("[E1]", user)
        self.assertIn("[E2]", user)
        self.assertIn("不代表任何顶刊", system)
        body = {
            "equations": [
                {
                    "source_id": item["source_id"],
                    "input": f"输入见原文 [{item['source_id']}]",
                    "transformation": f"变换须核对 [{item['source_id']}]",
                    "output": f"输出未明 [{item['source_id']}]",
                    "why": f"原因原文未说明 [{item['source_id']}]",
                    "uncertainty": "需要确认实际定义",
                    "source_quote": item["formula"],
                }
                for item in items
            ],
            "chain": "原文未说明如何衔接",
            "chain_uncertainty": "不能推断变量传递",
        }
        self.assertEqual(len(check_batch_response(body, items)["equations"]), 2)
        missing_label = json.loads(json.dumps(body))
        missing_label["equations"][1]["input"] = "输入未定义"
        repaired = check_batch_response(missing_label, items)
        self.assertIn("E2.input", repaired["system_added_labels"])
        self.assertTrue(repaired["equations"][1]["input"].endswith("[E2]"))
        wrong_label = json.loads(json.dumps(body))
        wrong_label["equations"][1]["input"] = "引用其他公式 [E1]"
        with self.assertRaisesRegex(ValueError, "错引"):
            check_batch_response(wrong_label, items)
        with self.assertRaisesRegex(ValueError, "漏掉"):
            check_batch_response({**body, "equations": body["equations"][:1]},
                                 items)
        changed = json.loads(json.dumps(body))
        changed["equations"][1]["source_quote"] = "not in selected source"
        with self.assertRaisesRegex(ValueError, "短引文"):
            check_batch_response(changed, items)
        fixed = parse_batch_model_reply({
            "choices": [{"message": {"content": json.dumps(changed, ensure_ascii=False)}}]
        }, items)
        self.assertEqual(fixed["system_quote_anchors"], ["E2"])
        self.assertEqual(fixed["equations"][1]["source_quote"], items[1]["formula"])
        unsupported = json.loads(json.dumps(body))
        unsupported["equations"][1]["input"] = "模型输入设置为 9999999 [E2]"
        safe = parse_batch_model_reply({
            "choices": [{"message": {
                "content": json.dumps(unsupported, ensure_ascii=False)}}]
        }, items)
        self.assertEqual(safe["redacted_numeric_fields"], ["E2.input"])
        self.assertNotIn("9999999", safe["equations"][1]["input"])
        with self.assertRaisesRegex(ValueError, "数字"):
            check_batch_response(unsupported, items)

        eleven = [
            {"source_id": f"E{i}", "page_no": i,
             "formula": f"y = x + {i} ({i})", "context": "x is an input"}
            for i in range(1, 12)
        ]
        _, prompt = batch_equation_prompt("Full list", eleven)
        self.assertIn("[E11]", prompt)
        single_system, _ = batch_equation_prompt(
            "Single", [eleven[-1]],
        )
        self.assertIn('"source_id":"E11"', single_system)
        self.assertNotIn('"source_id":"E1"', single_system)
        full = {
            "equations": [
                {"source_id": row["source_id"],
                 "input": f"输入 x [{row['source_id']}]",
                 "transformation": f"加法 [{row['source_id']}]",
                 "output": f"输出 y [{row['source_id']}]",
                 "why": f"原文未说明 [{row['source_id']}]",
                 "uncertainty": "尚需核对原文",
                 "source_quote": row["formula"]}
                for row in eleven
            ],
            "chain": "原文未说明如何衔接",
            "chain_uncertainty": "仅能核验每条原始公式",
        }
        self.assertEqual(len(check_batch_response(full, eleven)["equations"]), 11)
        payload = {
            "choices": [{"message": {
                "content": "模型结果：\n```json\n" + json.dumps(full, ensure_ascii=False) + "\n```"
            }, "finish_reason": "stop"}]
        }
        self.assertEqual(len(parse_batch_model_reply(payload, eleven)["equations"]), 11)
        payload["choices"][0] = {
            "message": {"content": ""}, "finish_reason": "length",
        }
        with self.assertRaisesRegex(ValueError, "耗尽输出长度"):
            parse_batch_model_reply(payload, eleven)

    def test_batch_review_preserves_partial_verified_groups_and_token_usage(self):
        import re as _re
        paper_id = self.ingest_one("1706.03762v7.pdf")
        generated = [
            {"page_no": 4, "excerpt": f"y = x + {i} ({i})"}
            for i in range(1, 10)
        ]
        original_structure = app.document_structure

        def synthetic_structure(selected):
            result = original_structure(selected)
            result["equations"] = generated
            result["truncated"]["equations"] = False
            return result

        class Response:
            def __init__(self, payload):
                self.payload = payload
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return False
            def read(self):
                return json.dumps(self.payload, ensure_ascii=False).encode()

        calls = []
        fail_second = [True]

        def fake_request(request, timeout):
            body = json.loads(request.data)
            calls.append(body)
            if fail_second[0] and len(calls) == 2:
                return Response({
                    "choices": [{"message": {"content": ""}, "finish_reason": "length"}],
                    "usage": {"prompt_tokens": 101, "completion_tokens": 4000,
                              "total_tokens": 4101},
                })
            matched = _re.findall(
                r"\[(E\d+)\] PDF 物理页 \d+，编号公式候选（不是 LaTeX）：([^\n]+)",
                body["messages"][1]["content"],
            )
            rows = [
                {"source_id": key, "input": f"输入见原文 [{key}]",
                 "transformation": f"运算见原文 [{key}]",
                 "output": f"结果见原文 [{key}]",
                 "why": f"原文未说明 [{key}]",
                 "uncertainty": "尚需核对", "source_quote": formula}
                for key, formula in matched
            ]
            reply = {"equations": rows, "chain": "原文未说明如何衔接",
                     "chain_uncertainty": "需要核对原文"}
            return Response({
                "choices": [{"message": {"content": json.dumps(reply, ensure_ascii=False)},
                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 90, "completion_tokens": 200,
                          "total_tokens": 290},
            })

        with patch.dict(app.os.environ, {
            "LLM_CHAT_ENDPOINT": "https://mock.test/chat/completions",
            "LLM_MODEL": "mock", "LLM_API_KEY": "mock-only",
        }), patch("app.document_structure", side_effect=synthetic_structure), patch(
            "app.urllib.request.urlopen", side_effect=fake_request,
        ):
            result = app.review_all_equations(paper_id, confirm_cost=True)
        self.assertEqual(result["status"], "partial_needs_review")
        self.assertEqual((result["attempted_groups"], result["completed_groups"],
                          result["total_groups"]), (2, 1, 3))
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(result["draft"]["equations"]), 9)
        self.assertIsNotNone(result["draft"]["equations"][0])
        self.assertIsNone(result["draft"]["equations"][4])
        self.assertEqual(result["usage"]["total_tokens"], 4391)
        self.assertIn("失败组再次请求仍可能计费", result["message"])
        calls.clear()
        # Same model/source: reuse group 1; retry only failed group 2.
        with patch.dict(app.os.environ, {
            "LLM_CHAT_ENDPOINT": "https://mock.test/chat/completions",
            "LLM_MODEL": "mock", "LLM_API_KEY": "mock-only",
        }), patch("app.document_structure", side_effect=synthetic_structure), patch(
            "app.urllib.request.urlopen", side_effect=fake_request,
        ):
            resumed = app.review_all_equations(paper_id, confirm_cost=True)
        self.assertEqual(resumed["reused_groups"], 1)
        self.assertEqual(resumed["attempted_groups"], 2)
        self.assertEqual(len(calls), 2)
        calls.clear()
        fail_second[0] = False
        with patch.dict(app.os.environ, {
            "LLM_CHAT_ENDPOINT": "https://api.deepseek.com/chat/completions",
            "LLM_MODEL": "deepseek-flash", "LLM_API_KEY": "mock-only",
        }), patch("app.document_structure", side_effect=synthetic_structure), patch(
            "app.urllib.request.urlopen", side_effect=fake_request,
        ):
            completed = app.review_all_equations(paper_id, confirm_cost=True)
        self.assertEqual(completed["status"], "draft_needs_review")
        self.assertEqual((completed["attempted_groups"], completed["completed_groups"]),
                         (3, 3))
        self.assertTrue(all(completed["draft"]["equations"]))
        self.assertEqual(completed["usage"]["total_tokens"], 870)
        self.assertEqual(completed["thinking_mode"], "disabled")
        self.assertTrue(all(
            item.get("thinking") == {"type": "disabled"} for item in calls
        ))

    def test_evidence_topology_guardrails_and_mock_model(self):
        evidence = [{"source_id": "E1", "title": "Example",
                     "page_no": 4, "content": "The encoder creates representations."}]
        system, user = topology_prompt("把模型迁移到遥感", evidence)
        self.assertIn("proposal", system)
        self.assertIn("[E1]", user)
        diagram = {
            "nodes": [
                {"id": "N1", "label": "编码器", "kind": "source",
                 "source_id": "E1", "source_quote": "The encoder creates representations."},
                {"id": "N2", "label": "遥感适配", "kind": "proposal",
                 "source_id": "", "source_quote": ""},
            ],
            "edges": [{"from": "N1", "to": "N2", "label": "待验证传递"}],
        }
        self.assertEqual(len(verify_topology(diagram, evidence)["nodes"]), 2)
        wrong = json.loads(json.dumps(diagram))
        wrong["nodes"][0]["source_quote"] = "fabricated evidence"
        corrected = verify_topology(wrong, evidence)
        self.assertEqual(corrected["system_quote_anchors"], ["N1"])
        self.assertIn(corrected["nodes"][0]["source_quote"],
                      evidence[0]["content"])
        wrong = json.loads(json.dumps(diagram))
        wrong["nodes"][0]["source_id"] = "E9"
        with self.assertRaisesRegex(ValueError, "不存在"):
            verify_topology(wrong, evidence)
        wrong = json.loads(json.dumps(diagram))
        wrong["nodes"][1]["source_id"] = "E1"
        with self.assertRaisesRegex(ValueError, "冒充"):
            verify_topology(wrong, evidence)
        wrong = json.loads(json.dumps(diagram))
        wrong["nodes"][0]["kind"] = "proposal"
        wrong["nodes"][0]["source_id"] = ""
        wrong["nodes"][0]["source_quote"] = ""
        with self.assertRaisesRegex(ValueError, "至少需要一个"):
            verify_topology(wrong, evidence)
        self.assertEqual(len(parse_topology_response({
            "choices": [{"message": {"content": json.dumps(diagram)}}]
        }, evidence)["edges"]), 1)

        paper_id = self.ingest_one("1706.03762v7.pdf")
        with self.assertRaisesRegex(ValueError, "确认"):
            app.propose_evidence_topology(
                "Transformer attention for translation", [paper_id],
            )
        with patch.dict(app.os.environ, {
            "LLM_CHAT_ENDPOINT": "https://api.deepseek.com/chat/completions",
            "LLM_MODEL": "deepseek-flash", "LLM_API_KEY": "mock-only",
        }), patch("app.urllib.request.urlopen") as outbound:
            class Response:
                def __enter__(self):
                    return self
                def __exit__(self, *_):
                    return False
                def read(self):
                    published = app.grounded_writing(
                        "Transformer attention for translation", [paper_id],
                    )["evidence"][0]
                    with app.db() as connection:
                        original = connection.execute(
                            "SELECT content FROM chunks WHERE id=?",
                            (published["chunk_id"],),
                        ).fetchone()["content"]
                    exact_quote = original[:35]
                    return json.dumps({"choices": [{"message": {
                        "content": json.dumps({
                            "nodes": [
                                {"id": "N1", "label": "来源候选", "kind": "source",
                                 "source_id": "E1", "source_quote": exact_quote},
                                {"id": "N2", "label": "实验检查", "kind": "proposal",
                                 "source_id": "", "source_quote": ""},
                            ], "edges": [{"from": "N1", "to": "N2",
                                        "label": "待验证连接"}],
                        }, ensure_ascii=False)
                    }}], "usage": {"prompt_tokens": 15,
                                   "completion_tokens": 40,
                                   "total_tokens": 55}}).encode()
            outbound.return_value = Response()
            result = app.propose_evidence_topology(
                "Transformer attention for translation",
                [paper_id], confirm_cost=True,
            )
            self.assertEqual(result["status"], "draft_needs_review",
                             result["message"])
            self.assertEqual(result["usage"]["total_tokens"], 55)
            sent = json.loads(outbound.call_args.args[0].data)
            self.assertEqual(sent["thinking"], {"type": "disabled"})
            self.assertEqual(outbound.call_count, 1)

    def test_optional_ai_research_plan_prompts_and_quote_scope(self):
        sources = [{"source_id": "E1", "title": "Local paper",
                    "page_no": 4, "content": "Fusion uses scores from encoders."}]
        system, user = research_plan_prompt("迁移融合方法到遥感", "", sources)
        self.assertIn("可证伪", system)
        self.assertIn("未提供", user)
        draft = {field: "建议（未验证）：检查输入、对照、可复现性 [E1]"
                 for field in PLAN_FIELDS}
        payload = {"choices": [{"message": {"content":
                                           json.dumps(draft, ensure_ascii=False)}}]}
        self.assertEqual(
            verify_research_plan(payload, sources)["dataset_plan"],
            draft["dataset_plan"],
        )
        changed = dict(draft)
        changed["dataset_plan"] = "凭空编造的支持 [E9]"
        with self.assertRaisesRegex(ValueError, "不存在"):
            verify_research_plan({"choices": [{
                "message": {"content": json.dumps(changed, ensure_ascii=False)}
            }]}, sources)
        paper = self.ingest_one("1706.03762v7.pdf")
        with self.assertRaisesRegex(ValueError, "确认"):
            app.propose_research_plan("Transformer attention for translation",
                                      [paper], "数据集待定")
        with patch.dict(app.os.environ, {
            "LLM_CHAT_ENDPOINT": "https://api.deepseek.com/chat/completions",
            "LLM_MODEL": "deepseek-flash", "LLM_API_KEY": "test-only",
        }), patch("app.urllib.request.urlopen") as outbound:
            class MockResponse:
                def __enter__(self):
                    return self
                def __exit__(self, *_):
                    return False
                def read(self):
                    return json.dumps({
                        "choices": [{"message": {
                            "content": json.dumps(draft, ensure_ascii=False)
                        }}], "usage": {"prompt_tokens": 25,
                                      "completion_tokens": 34,
                                      "total_tokens": 59},
                    }, ensure_ascii=False).encode()
            outbound.return_value = MockResponse()
            result = app.propose_research_plan(
                "Transformer attention for translation", [paper],
                "数据集待定", confirm_cost=True,
            )
            self.assertEqual(result["status"], "proposal_needs_review")
            self.assertEqual(result["usage"]["total_tokens"], 59)
            sent = json.loads(outbound.call_args.args[0].data)
            self.assertEqual(sent["thinking"], {"type": "disabled"})

    def test_batch_review_401_retains_all_original_equations(self):
        import io
        paper_id = self.ingest_one("1706.03762v7.pdf")
        unauthorized = urllib.error.HTTPError(
            "http://model.local/", 401, "Authorization Required",
            {}, io.BytesIO(b"private credentials"),
        )
        with patch.dict(app.os.environ, {
            "LLM_CHAT_ENDPOINT": "http://model.local/v1/chat/completions",
            "LLM_MODEL": "mock", "LLM_API_KEY": "test-only",
        }), patch("app.urllib.request.urlopen", side_effect=unauthorized):
            result = app.review_all_equations(paper_id, confirm_cost=True)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["count"], len(result["equations"]))
        self.assertTrue(all(item["formula"] for item in result["equations"]))
        self.assertIn("401", result["message"])
        self.assertNotIn("private credentials", result["message"])

    def test_404_model_message_identifies_missing_chat_path(self):
        error = urllib.error.HTTPError(
            "https://api.deepseek.com", 404, "Not Found", {}, None,
        )
        explanation = app.model_error_message(error)
        self.assertIn("LLM_CHAT_ENDPOINT", explanation)
        self.assertIn("/chat/completions", explanation)
        self.assertNotIn("LLM_API_KEY", explanation)

    def test_deepseek_flash_disables_default_thinking_only_on_official_endpoint(self):
        self.assertEqual(
            app.structured_model_options(
                "https://api.deepseek.com/chat/completions", "deepseek-flash",
            ),
            {"thinking": {"type": "disabled"}},
        )
        self.assertEqual(
            app.structured_model_options(
                "https://api.deepseek.com/v1/chat/completions", "deepseek-flash",
            ),
            {"thinking": {"type": "disabled"}},
        )
        self.assertEqual(
            app.structured_model_options(
                "https://mock.local/v1/chat/completions", "deepseek-flash",
            ), {},
        )
        self.assertEqual(
            app.structured_model_options(
                "https://api.deepseek.com/chat/completions", "other-model",
            ), {},
        )

    def test_structure_from_indexed_pages_has_source_links_and_no_fake_latex(self):
        synthetic = build_structure(
            [
                (2, "Figure 1: System overview\nTable 2: Results\n"
                     "y = x + 2 (3)\n2 Methods\n2.1 Model\n2.1.1 Layers"),
                (9, "References\n[1] Example work.\nAppendix A: Experiments"),
            ],
            [
                {"title": "2 Methods", "level": 1, "page_no": 2},
                {"title": "2.1 Model", "level": 2, "page_no": 2},
                {"title": "2.1.1 Layers", "level": 3, "page_no": 2},
            ],
            [{"number": 1, "page_no": 9, "snippet": "[1] Example work."}],
        )
        self.assertEqual(
            synthetic["heading_tree"][0]["children"][0]["children"][0]["level"], 3
        )
        self.assertEqual({item["type"] for item in synthetic["captions"]},
                         {"figure_caption", "table_caption"})
        self.assertEqual(synthetic["equations"][0]["page_no"], 2)
        self.assertIn("不还原 LaTeX", synthetic["note"])
        self.assertEqual(synthetic["appendices"][0]["page_no"], 9)
        self.assertEqual(synthetic["references"]["numbered_entries"][0]["page_no"], 9)
        paper = self.ingest_one("1706.03762v7.pdf")
        structure = app.document_structure(paper)
        self.assertIn("Attention Is All You Need", structure["metadata"]["title"])
        self.assertTrue(structure["metadata"]["abstract"])
        self.assertTrue(any(entry["type"] == "figure_caption"
                            for entry in structure["captions"]))
        self.assertTrue(structure["references"]["numbered_entries"])
        with app.db() as c:
            page = structure["captions"][0]["page_no"]
            self.assertTrue(c.execute(
                "SELECT 1 FROM chunks WHERE paper_id=? AND page_no=?",
                (paper, page),
            ).fetchone())

    def test_structure_over_541_indexed_pages_keeps_late_appendix(self):
        paper_id = "b" * 14
        with app.db() as connection:
            connection.execute(
                """INSERT INTO papers
                   (id,filename,filepath,title,status,pages,created_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (paper_id, "long.pdf", "unused", "Long Book", "ready",
                 541, app.now()),
            )
            connection.executemany(
                "INSERT INTO chunks(paper_id,page_no,content) VALUES(?,?,?)",
                [(
                    paper_id, page,
                    "Figure 12: Intermediate overview" if page == 260 else
                    "Appendix A: Additional results" if page == 530 else
                    "References\n[1] Work." if page == 541 else
                    f"Page {page} of the book."
                ) for page in range(1, 542)]
            )
        result = app.document_structure(paper_id)
        self.assertEqual(result["metadata"]["pages"], 541)
        self.assertEqual(result["captions"][0]["page_no"], 260)
        self.assertEqual(result["appendices"][0]["page_no"], 530)
        self.assertEqual(result["references"]["headings"][0]["page_no"], 541)

    def test_future_work_excerpts_with_pages_and_uncertain_related_papers(self):
        origin = self.ingest_one("1706.03762v7.pdf")
        other = self.ingest_one("1607.06450v1.pdf")
        with app.db() as c:
            result = scan_future_work(c, origin)
        self.assertTrue(result["items"])
        excerpt = next(
            item for item in result["items"]
            if item["source_page"] == 7 and "plan to" in item["signal"].lower()
        )
        self.assertIn("We plan to investigate", excerpt["source_excerpt"])
        self.assertIn("待人工核验", excerpt["status"])
        self.assertFalse(any(hit["paper_id"] == origin
                             for item in result["items"]
                             for hit in item["related_local_papers"]))
        self.assertIn("不能", result["note"])
        self.assertEqual(arxiv_month("1706.03762"), "2017-06")
        self.assertIsNone(arxiv_month("invalid"))
        for candidate in result["items"]:
            self.assertEqual(candidate["origin_arxiv_first_month"], "2017-06")
            for related in candidate["related_local_papers"]:
                self.assertIn(related["time_relation"], {
                    "earlier_arxiv_month", "later_arxiv_month",
                    "same_arxiv_month_unknown_order", "unknown"
                })
        with app.db() as c:
            none = scan_future_work(c, other)
        self.assertTrue(any(
            item["source_page"] == 10
            and "further research is needed" in item["signal"].lower()
            for item in none["items"]
        ))
        self.assertTrue(any(
            "ConvNets" in item["source_excerpt"]
            for item in none["items"]
        ))

    def test_frontier_snapshot_keeps_uncertainty_and_source_pages(self):
        self.ingest_one("1706.03762v7.pdf")
        self.ingest_one("1607.06450v1.pdf")
        report = app.frontier_survey()
        self.assertEqual(len(report["timeline"]), 2)
        self.assertTrue(report["future_directions"])
        self.assertTrue(all(
            item["source_page"] > 0 and item["source_excerpt"]
            for item in report["future_directions"]
        ))
        self.assertTrue(any(
            item["origin_title"] == "Layer Normalization"
            and item["source_page"] == 10
            for item in report["future_directions"]
        ))
        self.assertIn("不自动删除旧 idea", report["note"])

    def test_frontier_recent_leads_remains_date_and_keyword_candidate_only(self):
        first = self.ingest_one("1607.06450v1.pdf")
        with patch("app.recent_arxiv", return_value=[
            {"identifier":"2504.12345v1", "title":"Layer normalization for ConvNets",
             "published":"2025-04-09", "summary":"Convnets further research needed"},
            {"identifier":"1502.12345v1", "title":"Layer normalization for ConvNets",
             "published":"2015-02-02", "summary":"Convnets context"},
            {"identifier":"2510.55555v1", "title":"Unrelated",
             "published":"2025-10-01", "summary":"another topic"},
        ]) as arxiv:
            response = app.frontier_recent_leads(first, 10)
        arxiv.assert_called_once()
        self.assertEqual(response["origin_page"],10)
        self.assertEqual(len(response["items"]),1)
        self.assertEqual(response["items"][0]["identifier"],"2504.12345v1")
        self.assertIn("未核验",response["items"][0]["status"])
        with self.assertRaisesRegex(ValueError,"页没有"):
            app.frontier_recent_leads(first, 14)

    def test_frontier_model_review_requires_consent_and_checks_fake_numbers(self):
        self.ingest_one("1706.03762v7.pdf")
        self.ingest_one("1607.06450v1.pdf")
        with self.assertRaisesRegex(ValueError, "确认"):
            app.frontier_model_review()

        class Response:
            def __init__(self, text):
                self.text = text
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def read(self):
                return json.dumps({
                    "choices":[{"message":{"content":self.text}}],
                    "usage":{"prompt_tokens":25,"completion_tokens":15,
                             "total_tokens":40}
                },ensure_ascii=False).encode()

        with patch.dict(app.os.environ,{
            "LLM_CHAT_ENDPOINT":"https://api.deepseek.com/chat/completions",
            "LLM_MODEL":"deepseek-flash","LLM_API_KEY":"mock-only",
        }),patch("app.urllib.request.urlopen",
                 return_value=Response(json.dumps({"claims":[{
                     "text":"原文提出进一步研究",
                     "evidence_ids":[1]}]},ensure_ascii=False))) as outbound:
            review = app.frontier_model_review(confirm_cost=True)
        self.assertIn("原文提出",review["answer"])
        self.assertIn("[1]",review["answer"])
        self.assertEqual(review["usage"]["total_tokens"],40)
        self.assertTrue(review["sources"])
        self.assertEqual(json.loads(outbound.call_args.args[0].data)
                         ["thinking"],{"type":"disabled"})

        with patch.dict(app.os.environ,{
            "LLM_CHAT_ENDPOINT":"https://mock.local/chat/completions",
            "LLM_MODEL":"mock","LLM_API_KEY":"test-only",
        }),patch("app.urllib.request.urlopen",
                 return_value=Response(json.dumps({"claims":[{
                     "text":"该领域已经彻底解决了 99999999",
                     "evidence_ids":[1]}]},ensure_ascii=False))):
            blocked = app.frontier_model_review(confirm_cost=True)
        self.assertIsNone(blocked["answer"])
        self.assertTrue(blocked["warning"])
        self.assertEqual(blocked["usage"]["total_tokens"],40)

    def test_frontier_structured_claims_fail_closed_on_unsourced_extra_sentence(self):
        evidence = [{"content":"We think further research is needed on ConvNets.",
                     "title":"Layer Normalization","page_no":10}]
        good = json.dumps({"claims":[
            {"text":"论文原文提出需要进一步研究 ConvNets","evidence_ids":[1]},
            {"text":"ConvNets 方面仍有后续工作建议","evidence_ids":[1]},
        ]},ensure_ascii=False)
        answer = app.verify_frontier_claims(good,evidence)
        self.assertEqual(answer.count("[1]"),2)
        self.assertEqual(app.verify_model_draft(answer,evidence),"")
        with self.assertRaisesRegex(ValueError,"多句"):
            app.verify_frontier_claims(json.dumps({"claims":[{
                "text":"原文提出进一步研究。全领域尚无解决","evidence_ids":[1],
            }]},ensure_ascii=False),evidence)
        with self.assertRaisesRegex(ValueError,"缺少有效原文编号"):
            app.verify_frontier_claims(json.dumps({"claims":[{
                "text":"模型声称未来研究方向","evidence_ids":[],
            }]},ensure_ascii=False),evidence)

    def test_future_work_generic_words_are_not_related_evidence(self):
        with app.db() as conn:
            for paper_id, title, arxiv, content in (
                ("a" * 14, "Origin", "1706.03762", "after iterations decrease loss"),
                ("b" * 14, "Candidate", "", "after iterations decrease loss"),
            ):
                conn.execute(
                    """INSERT INTO papers(id,filename,filepath,title,arxiv_id,status,created_at)
                       VALUES(?,?,?,?,?,'ready',?)""",
                    (paper_id, title + ".pdf", title + ".pdf", title, arxiv, app.now()),
                )
                row = conn.execute(
                    "INSERT INTO chunks(paper_id,page_no,content) VALUES(?,1,?)",
                    (paper_id, content),
                )
                conn.execute(
                    "INSERT INTO chunks_fts(rowid,paper_id,page_no,content) VALUES(?,?,1,?)",
                    (row.lastrowid, paper_id, content),
                )
            self.assertEqual(
                keyword_candidates(conn, "a" * 14, "1706.03762",
                                   "after iterations decrease loss"), [],
            )

    def test_limitation_outlook_is_labelled_not_fake_future_plan(self):
        paper_id = "c" * 14
        with app.db() as conn:
            conn.execute(
                """INSERT INTO papers(id,filename,filepath,title,status,created_at)
                   VALUES(?,?,?,?,'ready',?)""",
                (paper_id, "study.pdf", "unused", "Study", app.now()),
            )
            conn.execute(
                "INSERT INTO chunks(paper_id,page_no,content) VALUES(?,9,?)",
                (paper_id, "5. Conclusion\nLimitations and Outlook. Tight screening "
                 "requires a sufficiently large sample; small pools can limit "
                 "coverage, and this observation needs further investigation."),
            )
            result = scan_future_work(conn, paper_id)
        self.assertEqual(result["items"][0]["source_page"], 9)
        self.assertIn("限制与展望", result["items"][0]["status"])
        self.assertIn(9, result["review_pages"])

    def test_model_http_401_is_safely_explained(self):
        import io
        exc = urllib.error.HTTPError(
            "https://example.invalid/chat/completions", 401,
            "Authorization Required", {}, io.BytesIO(b"do not expose the key"),
        )
        message = app.model_error_message(exc)
        self.assertIn("HTTP 401", message)
        self.assertIn("API Key", message)
        self.assertNotIn("do not expose", message)

    def test_ask_401_keeps_page_evidence_and_explains_auth_in_answer(self):
        import io
        paper = self.ingest_one("1706.03762v7.pdf")
        server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/api/ask",
            data=json.dumps({
                "question": "Transformer base GPU", "paper_id": paper,
            }).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            failure = urllib.error.HTTPError(
                "https://example.invalid/chat/completions", 401,
                "Authorization Required", {}, io.BytesIO(b"private token"),
            )
            with patch("app.model_draft", side_effect=failure):
                with urllib.request.urlopen(request, timeout=15) as response:
                    result = json.load(response)
            self.assertEqual(result["mode"], "evidence_only")
            self.assertTrue(result["evidence"])
            self.assertIn("HTTP 401", result["answer"])
            self.assertNotIn("private token", result["answer"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_model_usage_is_provider_reported_and_price_only_when_configured(self):
        first = self.ingest_one("1706.03762v7.pdf")
        evidence = app.retrieve("Transformer base GPU", first, limit=1)
        self.assertTrue(evidence)
        event = app.record_audit(
            "Transformer base GPU", first, "hybrid", evidence,
            "model_draft", ["核验"], "带证据草稿",
            usage={"prompt_tokens": 240, "completion_tokens": 60,
                   "total_tokens": 300},
        )
        audit = next(row for row in app.audit_events() if row["id"] == event)
        self.assertEqual(audit["prompt_tokens"], 240)
        self.assertEqual(audit["completion_tokens"], 60)
        self.assertEqual(audit["total_tokens"], 300)
        self.assertIsNone(audit["estimated_cost_usd"])
        with patch.dict(app.os.environ, {
            "LLM_INPUT_USD_PER_MILLION": "1",
            "LLM_OUTPUT_USD_PER_MILLION": "2",
        }):
            measured = app.model_usage_cost({
                "prompt_tokens": 240, "completion_tokens": 60
            })
        self.assertEqual(measured["estimated_cost_usd"], 0.00036)

    def test_author_year_citations_diagnose_unsupported_format(self):
        paper_id = "c" * 14
        with app.db() as conn:
            conn.execute(
                """INSERT INTO papers(id,filename,filepath,title,status,created_at)
                   VALUES(?,?,?,?,'ready',?)""",
                (paper_id, "author_year.pdf", "unused", "Author-year", app.now()),
            )
            conn.execute(
                "INSERT INTO chunks(paper_id,page_no,content) VALUES(?,1,?)",
                (paper_id,
                 "Prior work (Smith et al., 2014) explains the method.\n"
                 "References\nSmith et al. 2014. A paper."),
            )
        nav = app.document_navigation(paper_id)
        self.assertEqual(nav["citations"], [])
        self.assertIn("作者—年份", nav["citation_diagnostic"])

    def test_author_year_reference_candidates_not_labeled_original_numbers(self):
        paper = self.ingest_one("1607.06450v1.pdf")
        result = app.cited_references(paper)
        self.assertTrue(result["references"])
        self.assertTrue(all(
            ref["number_source"] == "author_year_arxiv_candidate"
            for ref in result["references"]
        ))
        self.assertTrue(any(ref["arxiv_id"] == "1510.01378"
                            for ref in result["references"]))
        self.assertTrue(any(not ref["arxiv_id"]
                            for ref in result["references"]))
        self.assertIn("并非原文引用编号", result["note"])

    def test_author_year_wrapped_proceedings_entries_keep_full_record(self):
        paper_id = "d" * 14
        with app.db() as conn:
            conn.execute(
                """INSERT INTO papers(id,filename,filepath,title,status,created_at)
                   VALUES(?,?,?,?,'ready',?)""",
                (paper_id, "author_year_wrapped.pdf", "unused",
                 "Author-year wrapped", app.now()),
            )
            conn.execute(
                "INSERT INTO chunks(paper_id,page_no,content) VALUES(?,1,?)",
                (paper_id,
                 "References\n"
                 "[Andreas et al.2016] Jacob Andreas, Marcus Rohrbach,\n"
                 "Trevor Darrell, and Dan Klein. 2016. Learning to compose\n"
                 "neural networks for question answering. In Proceedings of\n"
                 "the 2016 NAACL: HLT, pages 1545–1554, San Diego, California.\n"
                 "[Bahdanau et al.2014] Dzmitry Bahdanau, Kyunghyun Cho, and\n"
                 "Yoshua Bengio. 2014. Neural machine translation by jointly\n"
                 "learning to align and translate. In Proceedings of the 2014 ICLR."),
            )
        result = app.cited_references(paper_id)
        self.assertEqual(len(result["references"]), 2)
        first = result["references"][0]
        self.assertEqual(first["citation_label"], "Andreas et al. 2016")
        self.assertIn("Learning to compose neural networks", first["excerpt"])
        self.assertIn("NAACL", first["excerpt"])
        self.assertTrue(all(item["number_source"] == "author_year_arxiv_candidate"
                            for item in result["references"]))

    def test_numbered_reference_drilldown_keeps_original_first_mention(self):
        paper = self.ingest_one("1706.03762v7.pdf")
        nav = app.document_navigation(paper)
        first = next(item for item in nav["citations"]
                     if item["number"] == 1)
        entry = next(item for item in app.cited_references(paper)["references"]
                     if item["number"] == 1)
        self.assertEqual(entry["first_mention_page"],
                         first["mention"]["page_no"])
        self.assertGreater(entry["page_no"],entry["first_mention_page"])

    def test_task_router_executes_real_tools_and_records_partial_failures(self):
        first = self.ingest_one("1706.03762v7.pdf")
        second = self.ingest_one("1607.06450v1.pdf")
        task = app.run_research_task(
            "比较两篇论文的注意力机制，并查看未来工作与局域引文图谱",
            [first, second],
        )
        self.assertEqual(
            [step["tool"] for step in task["plan"]],
            ["compare_papers", "future_work", "citation_graph"],
        )
        self.assertTrue(task["audit_id"])
        self.assertEqual(task["status"], "completed")
        self.assertEqual(len(task["results"][0]["data"]["rows"]), 2)
        self.assertTrue(task["results"][1]["data"]["papers"][0]["items"])
        self.assertTrue(task["results"][2]["data"]["edges"])
        event = next(
            e for e in app.audit_events() if e["id"] == task["audit_id"]
        )
        self.assertEqual(event["event_type"], "workflow")
        self.assertEqual(len(event["steps"]), 3)
        self.assertTrue(event["evidence_ids"])
        incomplete = app.run_research_task(
            "比较两篇论文方法并查未来工作", [first],
        )
        self.assertEqual(incomplete["status"], "partial")
        self.assertEqual(incomplete["plan"][0]["status"], "needs_input")
        self.assertEqual(incomplete["plan"][1]["status"], "ok")
        self.assertIsNone(incomplete["results"][0]["data"])
        with self.assertRaisesRegex(ValueError, "最多"):
            app.run_research_task("比较论文", [first] * 5)

    def test_version_task_router_keeps_preferred_order_and_no_fake_reasoning(self):
        old = self.ingest_one("1706.03762v1.pdf")
        new = self.ingest_one("1706.03762v7.pdf")
        task = app.run_research_task("比较 v1 和 v7 版本的差异", [new, old])
        self.assertEqual(task["mode"], "deterministic_workflow")
        self.assertEqual(task["plan"][0]["tool"], "version_comparison")
        self.assertEqual(task["results"][0]["data"]["first"]["id"], old)
        self.assertEqual(task["results"][0]["data"]["second"]["id"], new)
        self.assertEqual(task_plan("局域引用图谱")[0]["tool"], "citation_graph")
        self.assertEqual(task_plan("请检索 Transformer 参数")[0]["tool"], "retrieve")
        assert_plan = task_plan("先导入论文再比较两篇 Transformer 方法")
        self.assertEqual(
            [step["tool"] for step in assert_plan],
            ["import_requires_confirmation", "compare_papers"],
        )
        blocked = app.run_research_task(
            "先导入论文再比较两篇 Transformer 方法", [old, new],
        )
        self.assertEqual(blocked["status"], "partial")
        self.assertEqual(blocked["plan"][0]["status"], "needs_input")
        self.assertIsNone(blocked["results"][0]["data"])

    def test_generic_shared_points_requires_selection_and_shows_real_pages(self):
        question = "两篇论文有无共同点?"
        self.assertEqual(task_plan(question)[0]["tool"], "compare_papers")
        missing = app.run_research_task(question, [])
        self.assertEqual(missing["status"], "needs_attention")
        self.assertEqual(missing["plan"][0]["status"], "needs_input")
        self.assertIn("勾选至少 2 篇", missing["plan"][0]["message"])
        first = self.ingest_one("1706.03762v7.pdf")
        second = self.ingest_one("1607.06450v1.pdf")
        result = app.run_research_task(question, [first, second])
        self.assertEqual(result["status"], "completed")
        rows = result["results"][0]["data"]["rows"]
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(len(row["evidence"]), 1)
            hit = row["evidence"][0]
            self.assertEqual(hit["page_no"], 1)
            with app.db() as c:
                original = c.execute(
                    "SELECT content FROM chunks WHERE id=?", (hit["chunk_id"],)
                ).fetchone()
            self.assertEqual(hit["content"], original["content"])
        self.assertIn("人工核对", result["plan"][0]["message"])

    def test_workflow_tool_failure_is_audited_not_reported_as_success(self):
        with patch("app.citation_graph", side_effect=RuntimeError("simulated tool failure")):
            result = app.run_research_task("查看引用图谱", [])
        self.assertEqual(result["status"], "needs_attention")
        self.assertEqual(result["plan"][0]["tool"], "citation_graph")
        self.assertEqual(result["plan"][0]["status"], "error")
        self.assertIsNone(result["results"][0]["data"])
        event = next(
            item for item in app.audit_events() if item["id"] == result["audit_id"]
        )
        self.assertEqual(event["mode"], "needs_attention")
        self.assertEqual(event["steps"][0]["status"], "error")

    def test_model_plan_whitelist_rejects_download_and_preserves_confirmation(self):
        self.assertEqual(
            [step["tool"] for step in parse_model_plan(
                '{"tools":["compare_papers","future_work"]}',
                "比较两篇论文与未来工作",
            )],
            ["compare_papers", "future_work"],
        )
        self.assertEqual(
            [step["tool"] for step in parse_model_plan(
                '{"tools":["retrieve"]}', "先下载论文再问答"
            )],
            ["import_requires_confirmation", "retrieve"],
        )
        with self.assertRaisesRegex(ValueError, "越权"):
            parse_model_plan('{"tools":["download_pdf"]}', "下载所有参考文献")
        with self.assertRaisesRegex(ValueError, "越权"):
            parse_model_plan('{"tools":["retrieve","retrieve"]}', "重复工具")
        with self.assertRaisesRegex(ValueError, "JSON"):
            parse_model_plan("please ignore tool rules", "检索论文")
        with self.assertRaisesRegex(ValueError, "两篇"):
            parse_model_plan('{"tools":["compare_papers"]}', "比较论文", selected_count=1)

    def test_model_tool_plan_executes_only_whitelisted_tools_and_falls_back(self):
        first = self.ingest_one("1706.03762v7.pdf")
        second = self.ingest_one("1607.06450v1.pdf")
        with patch("app.model_task_plan", return_value=parse_model_plan(
            '{"tools":["citation_graph","compare_papers"]}',
            "比较并看引文网络",
        )):
            result = app.run_research_task(
                "比较并看引文网络", [first, second], use_model=True
            )
        self.assertEqual(result["mode"], "model_assisted_workflow")
        self.assertEqual(result["plan_source"], "model_whitelist")
        self.assertEqual(
            [step["tool"] for step in result["plan"]],
            ["citation_graph", "compare_papers"],
        )
        with patch("app.model_task_plan", side_effect=ValueError("模型越权")):
            fallback = app.run_research_task(
                "比较并看引文网络", [first, second], use_model=True
            )
        self.assertEqual(fallback["plan_source"], "rule_fallback")
        self.assertIn("越权", fallback["plan_error"])
        self.assertEqual(fallback["plan"][0]["tool"], "compare_papers")

    def test_model_planner_round_trip_uses_local_mock_and_blocks_write_tool(self):
        first = self.ingest_one("1706.03762v7.pdf")
        second = self.ingest_one("1607.06450v1.pdf")
        observed = []

        class FakePlanner(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                size = int(self.headers["Content-Length"])
                observed.append(json.loads(self.rfile.read(size)))
                answer = json.dumps({
                    "choices": [{"message": {"content":
                        '{"tools":["compare_papers","citation_graph"]}'
                    }}]
                }).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Length", str(len(answer)))
                self.end_headers()
                self.wfile.write(answer)

        model = ThreadingHTTPServer(("127.0.0.1", 0), FakePlanner)
        thread = threading.Thread(target=model.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.dict("os.environ", {
                "LLM_CHAT_ENDPOINT":
                    f"http://127.0.0.1:{model.server_port}/v1/chat/completions",
                "LLM_MODEL": "mock-planner-not-real",
            }):
                result = app.run_research_task(
                    "请比较两篇论文并查看引用图谱",
                    [first, second], use_model=True
                )
            self.assertEqual(result["plan_source"], "model_whitelist")
            self.assertEqual(result["status"], "completed")
            self.assertEqual(
                [s["tool"] for s in result["plan"]],
                ["compare_papers", "citation_graph"],
            )
            self.assertEqual(len(observed), 2)
            self.assertEqual(observed[0]["model"], "mock-planner-not-real")
            self.assertIsNone(result["answer"])
            self.assertTrue(result["answer_warning"])
        finally:
            model.shutdown()
            model.server_close()
            thread.join(timeout=3)

    def test_workflow_optional_answer_uses_retrieved_citable_evidence(self):
        first = self.ingest_one("1706.03762v7.pdf")
        with patch("app.model_task_plan", return_value=[
            {"tool": "retrieve", "reason": "mock non destructive"}
        ]), patch("app.model_draft", return_value=(
            "原论文片段提到了 Transformer [1]。",
            {"prompt_tokens": 45, "completion_tokens": 20, "total_tokens": 65}
        )) as model:
            result = app.run_research_task("Transformer attention GPU",
                                           [first], use_model=True)
        self.assertTrue(result["answer"])
        self.assertTrue(result["answer_evidence"])
        self.assertTrue(result["answer_evidence"][0]["chunk_id"])
        self.assertEqual(result["usage"]["total_tokens"], 65)
        self.assertTrue(model.called)
        audit = next(row for row in app.audit_events()
                     if row["id"] == result["audit_id"])
        self.assertEqual(audit["mode"], "model_answer")
        with patch("app.model_task_plan", return_value=[
            {"tool": "retrieve", "reason": "mock non destructive"}
        ]), patch("app.model_draft", return_value=(
            "该论文用了虚构数字 9999999 [1]。",
            {"prompt_tokens": 40, "completion_tokens": 10, "total_tokens": 50},
        )):
            unsafe = app.run_research_task("Transformer attention GPU",
                                           [first], use_model=True)
        self.assertIsNone(unsafe["answer"])
        self.assertEqual(unsafe["answer_evidence"], [])
        self.assertIn("未通过", unsafe["answer_warning"])
        self.assertEqual(unsafe["usage"]["total_tokens"], 50)

    def test_workflow_http_endpoint_routes_and_checks_selected_papers(self):
        first = self.ingest_one("1706.03762v7.pdf")
        second = self.ingest_one("1607.06450v1.pdf")
        server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        address = f"http://127.0.0.1:{server.server_port}/api/tasks/run"
        try:
            def run(ids):
                request = urllib.request.Request(
                    address, method="POST",
                    data=json.dumps({
                        "instruction": "对比两篇论文的注意力机制并查看局域引用图谱",
                        "paper_ids": ids,
                    }, ensure_ascii=False).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                return urllib.request.urlopen(request, timeout=25)
            with self.assertRaises(urllib.error.HTTPError) as invalid:
                run(["not_an_id"])
            self.assertEqual(invalid.exception.code, 400)
            with run([first, second]) as response:
                self.assertEqual(response.status, 200)
                data = json.load(response)
            self.assertEqual(data["mode"], "deterministic_workflow")
            self.assertEqual(
                [step["tool"] for step in data["plan"]],
                ["compare_papers", "citation_graph"],
            )
            self.assertEqual(data["status"], "completed")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_ask_persists_auditable_event_for_evidence_and_no_evidence(self):
        paper = self.ingest_one("1706.03762v7.pdf")
        first = app.retrieve("Transformer GPU", paper)
        self.assertTrue(first)
        event_id = app.record_audit(
            "Transformer GPU", paper, "hybrid", first, "evidence_only",
            ["识别任务", "检索", "核验"], "返回原文证据片段",
        )
        events = app.audit_events()
        event = next(row for row in events if row["id"] == event_id)
        self.assertEqual(event["paper_id"], paper)
        self.assertEqual(event["evidence_ids"], [item["chunk_id"] for item in first])
        self.assertEqual(event["steps"], ["识别任务", "检索", "核验"])
        no_event = app.record_audit(
            "zzqplmxyvvvzz", paper, "hybrid", [], "no_evidence",
            ["识别任务", "核验"], "无检索证据，拒绝生成事实性回答",
        )
        self.assertEqual(next(row for row in app.audit_events() if row["id"] == no_event)["mode"],
                         "no_evidence")

    def test_translation_requires_model_and_preserves_academic_prompt(self):
        with self.assertRaisesRegex(RuntimeError, "未配置"):
            app.translate_text("Attention [1] $x^2$", "en", "zh-CN")
        class Response:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def __init__(self):
                self.payload = None
            def read(self): return b""
        response = Response()
        payloads = []
        with patch.dict("os.environ", {
            "LLM_CHAT_ENDPOINT": "http://model.local/v1/chat/completions",
            "LLM_MODEL": "test-model", "LLM_API_KEY": "secret",
        }), patch(
            "app.urllib.request.urlopen",
            return_value=type(
                "Answer", (), {
                    "__enter__": lambda self: self,
                    "__exit__": lambda self, *_: False,
                    "read": lambda self: json.dumps(
                        {"choices": [{"message": {
                            "content": "注意力 [[SRC_KEEP_000]] [[SRC_KEEP_001]]"
                        }}]}, ensure_ascii=False
                    ).encode("utf-8"),
                }
            )(),
        ) as request:
            self.assertEqual(
                app.translate_text("Attention [1] $x^2$", "en", "zh-CN"),
                "注意力 [1] $x^2$",
            )
            body = json.loads(request.call_args.args[0].data.decode("utf-8"))
            payloads.append(body)
        self.assertIn("保留 LaTeX 公式", payloads[0]["messages"][0]["content"]
                      if payloads[0]["messages"][0]["role"] == "user"
                      else payloads[0]["messages"][1]["content"])
        self.assertIn("[[SRC_KEEP_000]]", payloads[0]["messages"][1]["content"])
        self.assertNotIn("thinking", payloads[0])
        with patch.dict("os.environ", {
            "LLM_CHAT_ENDPOINT": "https://api.deepseek.com/chat/completions",
            "LLM_MODEL": "deepseek-flash", "LLM_API_KEY": "mock-only",
        }), patch("app.urllib.request.urlopen", return_value=request.return_value) as official:
            self.assertEqual(
                app.translate_text("Attention [1] $x^2$", "en", "zh-CN"),
                "注意力 [1] $x^2$",
            )
            sent = json.loads(official.call_args.args[0].data)
            self.assertEqual(sent["thinking"], {"type": "disabled"})

    def test_translation_protected_spans_numeric_guard_and_safe_export(self):
        source = "BLEU=28.4 [1] with $x^2$ and `train()`: https://example.org"
        masked, spans = protected_translation_input(source)
        self.assertEqual(len(spans), 5)
        self.assertIn("[[SRC_KEEP_000]]", masked)
        self.assertNotIn("28.4", masked)
        translated = masked.replace(" with ", " 搭配 ").replace(" and ", " 和 ")
        restored = restored_translation(source, translated, spans)
        self.assertIn("$x^2$", restored)
        self.assertIn("[1]", restored)
        with self.assertRaisesRegex(ValueError, "数字"):
            restored_translation(source, translated + " 99", spans)
        with self.assertRaisesRegex(ValueError, "公式|代码|引用标记"):
            restored_translation(source, translated.replace("[[SRC_KEEP_000]]", ""), spans)
        with self.assertRaisesRegex(ValueError, "公式"):
            restored_translation(source, translated.replace("[[SRC_KEEP_001]]", ""), spans)
        with self.assertRaisesRegex(ValueError, "冲突"):
            protected_translation_input("Paper [[SRC_KEEP_000]] is not a model placeholder")
        rendered = export_bilingual_html("<script>alert(1)</script>", [
            (1, [{
                "ordinal": 0, "original": "<img src=x onerror=alert(1)>",
                "translated": "<script>alert(2)</script>",
            }])
        ])
        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;script&gt;", rendered)

    def test_translation_protects_publication_dates_and_doi_numbers(self):
        source = ("https://doi.org/10.1016/j.inffus.2026.104860\n"
                  "Received 22 June 2026; revised 28 September 2026")
        masked, spans = protected_translation_input(source)
        self.assertNotIn("2026", masked)
        translated = masked.replace("Received", "收稿").replace("revised", "修订")
        self.assertEqual(
            restored_translation(source, translated, spans),
            source.replace("Received", "收稿").replace("revised", "修订"),
        )

    def test_bilingual_page_units_are_bounded_and_page_anchored(self):
        units = page_units(SAMPLE_DIR / "1706.03762v7.pdf", 1)
        self.assertTrue(units)
        self.assertTrue(all(unit["page_no"] == 1 for unit in units))
        self.assertTrue(all(unit["source"] == "vector" for unit in units))
        self.assertTrue(any("Attention Is All You Need" in unit["original"] for unit in units))
        with self.assertRaisesRegex(ValueError, "页码"):
            page_units(SAMPLE_DIR / "1706.03762v7.pdf", 1000)

    def test_translation_job_persists_page_aligned_units_and_exports(self):
        paper = self.ingest_one("1706.03762v7.pdf")
        estimate = app.bilingual_estimate(paper, 1, 1)
        self.assertGreater(estimate["units"], 0)
        with patch.dict("os.environ", {
            "LLM_CHAT_ENDPOINT": "http://example.local/v1/chat/completions",
            "LLM_MODEL": "test-only",
        }):
            with self.assertRaisesRegex(ValueError, "确认"):
                app.create_translation_job(paper, 1, 1, confirm_cost=False)
            job = app.create_translation_job(paper, 1, 1, confirm_cost=True)
        self.assertEqual(job["status"], "queued")
        result = app.process_translation_job(
            job["id"], translate_fn=lambda text, _src, _dst: "译文：" + text,
        )
        self.assertEqual(result["status"], "completed")
        detail = app.translation_job(job["id"])
        self.assertEqual(detail["processed_units"], estimate["units"])
        page = app.translation_page(job["id"], 1)
        self.assertEqual(len(page["units"]), estimate["units"])
        self.assertTrue(all(
            item["translated"].startswith("译文：") for item in page["units"]
        ))
        rendered_html, html_type = app.export_translation(job["id"], "html")
        self.assertIn(b"<!doctype html>", rendered_html)
        self.assertIn("text/html", html_type)
        rendered_md, md_type = app.export_translation(job["id"], "md")
        self.assertIn("PDF 第 1 页".encode("utf-8"), rendered_md)
        self.assertIn("markdown", md_type)

    def test_translation_job_error_does_not_fake_completion_and_can_resume(self):
        paper = self.ingest_one("1706.03762v7.pdf")
        with patch.dict("os.environ", {
            "LLM_CHAT_ENDPOINT": "http://example.local/v1/chat/completions",
            "LLM_MODEL": "test-only",
        }):
            job = app.create_translation_job(paper, 1, 1, confirm_cost=True)
        failed = app.process_translation_job(
            job["id"],
            translate_fn=lambda *_: (_ for _ in ()).throw(
                RuntimeError("simulated model failure")
            ),
        )
        self.assertEqual(failed["status"], "error")
        self.assertIn("simulated", app.translation_job(job["id"])["error"])
        with self.assertRaisesRegex(ValueError, "完成"):
            app.export_translation(job["id"], "html")
        with app.db() as c:
            c.execute(
                "UPDATE translation_jobs SET status='queued' WHERE id=?",
                (job["id"],),
            )
        self.assertEqual(app.process_translation_job(
            job["id"], translate_fn=lambda text, _src, _dst: text,
        )["status"], "completed")
        self.assertTrue(app.translation_page(job["id"], 1)["units"])

    def test_translation_job_with_local_mock_chat_completion_round_trip(self):
        paper = self.ingest_one("1706.03762v7.pdf")
        requests_seen = []

        class FakeModel(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                request = json.loads(self.rfile.read(length))
                content = request["messages"][-1]["content"]
                masked = content.split("文本如下：\n\n", 1)[-1]
                requests_seen.append(masked)
                reply = json.dumps({
                    "choices": [{
                        "message": {"content": "模拟译文：" + masked}
                    }]
                }, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(reply)))
                self.end_headers()
                self.wfile.write(reply)

        model_server = ThreadingHTTPServer(("127.0.0.1", 0), FakeModel)
        thread = threading.Thread(target=model_server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.dict("os.environ", {
                "LLM_CHAT_ENDPOINT": (
                    f"http://127.0.0.1:{model_server.server_port}/v1/chat/completions"
                ),
                "LLM_MODEL": "test-model-not-a-real-translation",
            }):
                job = app.create_translation_job(
                    paper, 1, 1, confirm_cost=True,
                )
                outcome = app.process_translation_job(job["id"])
            self.assertEqual(outcome["status"], "completed")
            self.assertEqual(len(requests_seen), job["units"])
            page = app.translation_page(job["id"], 1)
            self.assertEqual(len(page["units"]), job["units"])
            self.assertTrue(all(
                unit["translated"].startswith("模拟译文：")
                for unit in page["units"]
            ))
        finally:
            model_server.shutdown()
            model_server.server_close()
            thread.join(timeout=3)

    def test_translation_http_estimate_queue_page_and_export(self):
        paper = self.ingest_one("1706.03762v7.pdf")
        server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with urllib.request.urlopen(
                base + f"/api/papers/{paper}/translation-estimate?first=1&last=1",
                timeout=5,
            ) as response:
                estimate = json.load(response)
            self.assertGreater(estimate["estimate_calls"], 0)
            data = json.dumps({
                "paper_id": paper, "first_page": 1, "last_page": 1,
                "target_language": "zh-CN", "confirm_cost": True,
            }).encode("utf-8")
            request = urllib.request.Request(
                base + "/api/translation-jobs", data=data,
                method="POST", headers={"Content-Type": "application/json"},
            )
            with self.assertRaises(urllib.error.HTTPError) as no_model:
                urllib.request.urlopen(request, timeout=5)
            self.assertEqual(no_model.exception.code, 503)
            with patch.dict("os.environ", {
                "LLM_CHAT_ENDPOINT": "http://model.local/v1/chat/completions",
                "LLM_MODEL": "test-only",
            }):
                with urllib.request.urlopen(request, timeout=5) as response:
                    queued = json.load(response)
            job_id = queued["id"]
            self.assertEqual(queued["status"], "queued")
            self.assertEqual(
                app.process_translation_job(
                    job_id, translate_fn=lambda text, _src, _dst: text,
                )["status"], "completed",
            )
            with urllib.request.urlopen(
                base + f"/api/translation-jobs/{job_id}/page?n=1",
                timeout=5,
            ) as response:
                page = json.load(response)
            self.assertEqual(len(page["units"]), estimate["units"])
            with urllib.request.urlopen(
                base + f"/api/translation-jobs/{job_id}/export?format=html",
                timeout=5,
            ) as response:
                self.assertIn("attachment;", response.headers["Content-Disposition"])
                self.assertIn(b"<!doctype html>", response.read())
            deleted = urllib.request.Request(
                base + f"/api/translation-jobs/{job_id}", method="DELETE",
            )
            self.assertEqual(json.load(urllib.request.urlopen(
                deleted, timeout=5
            ))["deleted"], job_id)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_hybrid_index_ranks_and_limits_to_requested_papers(self):
        one = self.ingest_one("1706.03762v7.pdf")
        two = self.ingest_one("1607.06450v1.pdf")
        with app.db() as c:
            ranked = latent_candidates(c, [one], "transformer attention encoder", limit=12)
            self.assertTrue(ranked)
            allowed = {row["id"] for row in c.execute(
                "SELECT id FROM chunks WHERE paper_id=?", (one,)
            )}
            self.assertTrue(all(chunk_id in allowed for chunk_id, _ in ranked))
            unknown = latent_candidates(c, [one], "zzqplmxyvvvzz")
            self.assertEqual(unknown, [])
            other = latent_candidates(c, [two], "layer normalization", limit=5)
            self.assertTrue(other)
            self.assertTrue(all(chunk_id not in allowed for chunk_id, _ in other))
        sparse = app.retrieve("transformer attention", one, method="sparse")
        latent = app.retrieve("transformer attention", one, method="latent")
        hybrid = app.retrieve("transformer attention", one, method="hybrid")
        self.assertTrue(sparse and latent and hybrid)
        self.assertTrue(all(item["paper_id"] == one for item in hybrid))
        self.assertTrue(any(item["retrieval"] in ("LSA", "BM25+LSA") for item in hybrid))
        self.assertEqual(
            reciprocal_rank_fusion([2, 1], [1, 3]), [1, 2, 3]
        )

    def test_vector_evidence_has_highlightable_page_image(self):
        paper = self.ingest_one("1706.03762v7.pdf")
        hit = app.retrieve("Transformer base GPU", paper)[0]
        data, marked, phrase = render_evidence(
            SAMPLE_DIR / "1706.03762v7.pdf", hit["page_no"], hit["content"],
        )
        self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertTrue(marked, "Expected at least one evidence chunk to map to PDF geometry")
        self.assertGreater(len(phrase), 35)

    def test_pdf_http_byte_ranges(self):
        paper_id = self.ingest_one("1706.03762v1.pdf")
        server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}/api/papers/{paper_id}/file"
        try:
            request = urllib.request.Request(base, headers={"Range": "bytes=0-15"})
            with urllib.request.urlopen(request, timeout=5) as response:
                self.assertEqual(response.status, 206)
                self.assertEqual(len(response.read()), 16)
                self.assertEqual(response.headers["Accept-Ranges"], "bytes")
                self.assertTrue(response.headers["Content-Range"].startswith("bytes 0-15/"))
            with urllib.request.urlopen(
                urllib.request.Request(base, method="HEAD"), timeout=5
            ) as response:
                self.assertEqual(response.status, 200)
                self.assertTrue(int(response.headers["Content-Length"]) > 10000)
                self.assertEqual(response.read(), b"")
            with self.assertRaises(urllib.error.HTTPError) as err:
                urllib.request.urlopen(
                    urllib.request.Request(base, headers={"Range": "bytes=999999999-"}),
                    timeout=5,
                )
            self.assertEqual(err.exception.code, 416)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_two_concurrent_imports_and_reads_keep_document_isolation(self):
        names = ["1706.03762v7.pdf", "1607.06450v1.pdf"]
        paper_ids = [__import__("uuid").uuid4().hex[:14] for _ in names]
        with app.db() as conn:
            for pid, name in zip(paper_ids, names):
                conn.execute(
                    "INSERT INTO papers(id,filename,filepath,created_at) VALUES(?,?,?,?)",
                    (pid, name, str((SAMPLE_DIR / name).resolve()), app.now()),
                )
        failures = []
        workers = [
            threading.Thread(target=app.ingest, args=(pid,), daemon=True)
            for pid in paper_ids
        ]
        for worker in workers:
            worker.start()
        for _ in range(60):
            try:
                app.papers()
                app.retrieve("Transformer attention", paper_ids[0], method="sparse")
            except Exception as exc:
                failures.append(str(exc))
            if not any(worker.is_alive() for worker in workers):
                break
            time.sleep(.02)
        for worker in workers:
            worker.join(timeout=20)
        self.assertFalse(failures, failures[:3])
        self.assertFalse(any(worker.is_alive() for worker in workers))
        with app.db() as conn:
            for pid in paper_ids:
                row = conn.execute(
                    "SELECT status,error,chunks FROM papers WHERE id=?",
                    (pid,),
                ).fetchone()
                self.assertEqual(row["status"], "ready", row["error"])
                self.assertGreater(row["chunks"], 0)
            for pid in paper_ids:
                mismatches = conn.execute(
                    """SELECT COUNT(*) FROM chunks_fts f JOIN chunks ch ON ch.id=f.rowid
                       WHERE ch.paper_id=? AND f.paper_id<>ch.paper_id""",
                    (pid,),
                ).fetchone()[0]
                self.assertEqual(mismatches, 0)
        self.assertTrue(all(
            row["paper_id"] == paper_ids[0]
            for row in app.retrieve("Transformer attention", paper_ids[0])
        ))

    def test_navigation_citation_bidirectional(self):
        paper = self.ingest_one("1706.03762v7.pdf")
        nav = app.document_navigation(paper)
        self.assertTrue(any(
            "3.2.2 Multi-Head Attention" in h["title"] and h["page_no"] == 4
            for h in nav["headings"]
        ))
        ref = next(x for x in nav["citations"] if x["number"] == 1)
        self.assertEqual(ref["page_no"], 10)
        self.assertEqual(ref["mention"]["page_no"], 3)
        self.assertIn("Layer normalization", ref["snippet"])

    def test_reference_drilldown_extracts_arxiv_ids_and_does_not_auto_download(self):
        paper = self.ingest_one("1706.03762v7.pdf")
        self.ingest_one("1607.06450v1.pdf")
        result = app.cited_references(paper)
        self.assertEqual(result["references"][0]["number"], 1)
        self.assertEqual(result["references"][0]["page_no"], 10)
        self.assertEqual(result["references"][0]["arxiv_id"], "1607.06450")
        self.assertTrue(result["references"][0]["already_imported"])
        candidate = next(item for item in result["references"] if item["arxiv_id"] == "1409.0473")
        self.assertFalse(candidate["already_imported"])
        with self.assertRaisesRegex(ValueError, "论文不存在"):
            # No HTTP endpoint is called by extraction itself; this exercises
            # that import requires an API-verified identifier in the route.
            app.cited_references("bad" * 4)

    def test_arxiv_metadata_requires_exact_work_id(self):
        atom = b"""<?xml version="1.0" encoding="utf-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry><id>http://arxiv.org/abs/1409.0473v7</id>
            <title>Neural Machine Translation by Jointly Learning to Align and Translate</title>
          </entry></feed>"""
        class Feed:
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return False
            def read(self, _):
                return atom
        with patch("scholar_api._wait_turn"), patch(
            "scholar_api.urllib.request.urlopen", return_value=Feed()
        ) as outbound:
            result = scholar_api.metadata("1409.0473")
            self.assertEqual(result["identifier"], "1409.0473v7")
            self.assertIn("id_list=1409.0473", outbound.call_args.args[0].full_url)
        with self.assertRaisesRegex(ValueError, "数字型"):
            scholar_api.metadata("https://example.com")
        with patch("scholar_api._wait_turn"), patch(
            "scholar_api.urllib.request.urlopen", return_value=Feed()
        ):
            with self.assertRaisesRegex(ValueError, "未返回"):
                scholar_api.metadata("1607.06450")

    def test_arxiv_lookup_uses_one_network_connection_at_a_time(self):
        feed = (
            b'<?xml version="1.0" encoding="utf-8"?>'
            b'<feed xmlns="http://www.w3.org/2005/Atom"></feed>'
        )
        active = [0, 0]
        guard = threading.Lock()

        class Feed:
            def __enter__(self):
                with guard:
                    active[0] += 1
                    active[1] = max(active[1], active[0])
                __import__("time").sleep(0.02)
                return self
            def __exit__(self, *_):
                with guard:
                    active[0] -= 1
                return False
            def read(self, _):
                return feed

        with patch("scholar_api._wait_turn"), patch(
            "scholar_api.urllib.request.urlopen", side_effect=lambda *_args, **_kw: Feed()
        ):
            threads = [
                threading.Thread(
                    target=scholar_api.lookup,
                    args=("machine translation",),
                ) for _ in range(4)
            ]
            for task in threads:
                task.start()
            for task in threads:
                task.join(timeout=4)
        self.assertEqual(active[0], 0)
        self.assertEqual(active[1], 1)

    def test_split_uppercase_title_is_combined(self):
        preview = ("Published as a conference paper at ICLR 2015\n"
                   "NEURAL MACHINE TRANSLATION\n"
                   "BY JOINTLY LEARNING TO ALIGN AND TRANSLATE\n"
                   "Dzmitry Bahdanau\n")
        self.assertEqual(app.guess_title(preview, "1409.0473v7.pdf"),
                         "NEURAL MACHINE TRANSLATION BY JOINTLY LEARNING TO ALIGN AND TRANSLATE")

    def test_compare_is_evidence_matrix_not_generated_claim(self):
        one = self.ingest_one("1706.03762v1.pdf")
        two = self.ingest_one("1607.06450v1.pdf")
        result = app.compare_papers("Transformer base GPU", [one, two])
        self.assertEqual([x["paper_id"] for x in result["rows"]], [one, two])
        self.assertTrue(result["rows"][0]["evidence"])
        self.assertTrue(all(x["paper_id"] == one for x in result["rows"][0]["evidence"]))
        self.assertIn("逐篇", result["note"])
        with self.assertRaisesRegex(ValueError, "重复"):
            app.compare_papers("Transformer base GPU", [one, one])

    def test_model_draft_guardrails_reject_fake_citation_or_number(self):
        evidence = [{"content": "The model used 8 GPUs. BLEU reached 28.4 on this task."}]
        self.assertIn("不存在", app.verify_model_draft("We used 8 GPUs [2].", evidence))
        self.assertIn("未提供", app.verify_model_draft("We used 8 GPUs.", evidence))
        self.assertIn("数值", app.verify_model_draft("We used 99 GPUs [1].", evidence))
        self.assertEqual(app.verify_model_draft("The paper reports 8 GPUs [1].", evidence), "")
        self.assertEqual(
            app.verify_model_draft("模型架构：\nThe paper reports 8 GPUs [1].", evidence),
            "",
        )
        self.assertIn(
            "未提供", app.verify_model_draft(
                "该模型架构使用两个融合分支。\nThe paper reports 8 GPUs [1].",
                evidence,
            ),
        )

    def test_manual_publication_lookup_requires_exact_title_and_never_guesses_if(self):
        title = "Neural Machine Translation by Jointly Learning to Align and Translate"
        def fake_fetch(url):
            if "dblp.org" in url:
                return {"result": {"hits": {"hit": [
                    {"info": {"title": title, "venue": "ICLR", "year": "2015",
                              "type": "Conference and Workshop Papers"}}
                ]}}}
            return {"message": {"items": [
                {"title": ["Unrelated translation paper"],
                 "container-title": ["Journal of Guesses"],
                 "type": "journal-article", "DOI": "10.1234/incorrect"},
            ]}}
        with patch("publication_lookup._get_json", side_effect=fake_fetch):
            info = lookup_publication(title)
        self.assertEqual(info["venue"], "ICLR")
        self.assertEqual(info["venue_source"], "DBLP bibliographic index")
        self.assertIsNone(info["impact_factor"])
        self.assertIn("scholar.google.com", info["manual_links"]["google_scholar"])
        with self.assertRaisesRegex(ValueError, "DOI"):
            lookup_publication(title, "https://example.com/attacker")
        with patch("publication_lookup._get_json", side_effect=ValueError(
            "bot check",
        )):
            unavailable = lookup_publication(title)
        self.assertFalse(unavailable["venue"])
        self.assertTrue(any("DBLP" in e for e in unavailable["errors"]))

    def test_guardrails_check_each_claim_against_its_own_cited_source(self):
        evidence = [
            {"content": "This version trains on 8 NVIDIA P100 GPUs."},
            {"content": "The second paper uses 4 TPU chips only."},
        ]
        self.assertEqual(
            app.verify_model_draft("It uses 8 GPUs [1]. The other uses 4 chips [2].",
                                   evidence),
            "",
        )
        self.assertIn(
            "该句引用的原文",
            app.verify_model_draft("It uses 8 GPUs [2].", evidence),
        )
        self.assertIn(
            "未提供",
            app.verify_model_draft("It uses 8 GPUs [1]. The other uses 4 chips.",
                                   evidence),
        )
        self.assertIn(
            "数值",
            app.verify_model_draft("It uses 99 GPUs [1][2].", evidence),
        )

    def test_ask_rejects_wrong_model_citation_and_keeps_evidence(self):
        paper = self.ingest_one("1706.03762v7.pdf")
        server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/api/ask",
            data=json.dumps({
                "question": "Transformer base GPU", "paper_id": paper,
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with patch("app.model_draft", return_value="It uses 999 GPUs [1]."):
                with urllib.request.urlopen(request, timeout=15) as response:
                    result = json.load(response)
            self.assertEqual(result["mode"], "evidence_only")
            self.assertTrue(result["evidence"])
            self.assertNotIn("999 GPUs", result["answer"])
            event = next(
                e for e in app.audit_events() if e["id"] == result["audit_id"]
            )
            self.assertTrue(any("草稿被规则拦截" in step for step in event["steps"]))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_arxiv_candidate_parsing_and_safe_download(self):
        atom = b"""<?xml version="1.0" encoding="utf-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry><id>http://arxiv.org/abs/1706.03762v7</id>
            <title>Attention Is All You Need</title><published>2017-06-12T00:00:00Z</published>
            <summary>A paper about attention.</summary>
            <author><name>Ashish Vaswani</name></author>
          </entry></feed>"""
        class Response:
            headers = {"Content-Type": "application/pdf"}
            def __init__(self, value):
                self.value = value
                self.used = False
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return False
            def read(self, _=None):
                if self.used:
                    return b""
                self.used = True
                return self.value

        with patch("scholar_api._wait_turn"), patch(
            "scholar_api.urllib.request.urlopen", return_value=Response(atom)
        ) as outbound:
            hits = scholar_api.lookup("Attention Is All You Need")
            self.assertEqual(hits[0]["identifier"], "1706.03762v7")
            self.assertEqual(hits[0]["authors"], ["Ashish Vaswani"])
            self.assertIn("export.arxiv.org/api/query?", outbound.call_args.args[0].full_url)
        with patch("scholar_api._wait_turn"), patch(
            "scholar_api.urllib.request.urlopen",
            side_effect=[OSError("temporary failure"), Response(atom)],
        ) as outbound:
            self.assertEqual(scholar_api.lookup("Attention Is All You Need")[0]["identifier"],
                             "1706.03762v7")
            self.assertEqual(outbound.call_count, 2)
        with patch("scholar_api._wait_turn"), patch(
            "scholar_api.urllib.request.urlopen", return_value=Response(b"%PDF-1.5\nTEST")
        ) as outbound:
            downloaded = scholar_api.download("1706.03762v7", self.temp.name)
            self.assertEqual(downloaded.read_bytes(), b"%PDF-1.5\nTEST")
            self.assertEqual(outbound.call_args.args[0].full_url,
                             "https://arxiv.org/pdf/1706.03762v7")
        with self.assertRaisesRegex(ValueError, "数字型 ID"):
            scholar_api.download("https://example.org/private", self.temp.name)
        with patch("scholar_api._wait_turn"), patch(
            "scholar_api.urllib.request.urlopen", return_value=Response(b"%PDF-1.5\nTOO_LONG")
        ):
            with self.assertRaisesRegex(ValueError, "30 MB"):
                scholar_api.download("1706.03762v7", self.temp.name, max_bytes=10)
        self.assertEqual(list(Path(self.temp.name).glob("*.pdf")), [downloaded])
        with patch("scholar_api._wait_turn"), patch(
            "scholar_api.urllib.request.urlopen",
            side_effect=[OSError("temporary failure"), Response(b"%PDF-1.5\nOK")],
        ) as outbound:
            self.assertTrue(scholar_api.download("1706.03762v7", self.temp.name).is_file())
            self.assertEqual(outbound.call_count, 2)

    def test_recent_recommendation_reasons_and_feedback(self):
        sample = {
            "title": "New Machine Translation Study",
            "identifier": "2601.12345v1", "summary": "Machine translation https://github.com/example/repo",
            "authors": ["Researcher"], "published": "2026-01-01", "source": "arXiv API",
        }
        imported = dict(sample, identifier="1706.03762v7", title="Already Imported")
        with app.db() as c:
            c.execute(
                """INSERT INTO papers(id,filename,filepath,title,arxiv_id,version,status,created_at)
                   VALUES(?,?,?,?,?,7,'ready',?)""",
                ("a" * 14, "old.pdf", "old.pdf", "Machine Translation Foundation",
                 "1706.03762", app.now()),
            )
        with patch("app.recent_arxiv", return_value=[sample, imported]):
            first = app.recommend_recent("machine translation")
            self.assertEqual(len(first["items"]), 1)
            item = first["items"][0]
            self.assertTrue(item["has_github_link"])
            self.assertTrue(any("未核验" in reason for reason in item["reasons"]))
            before = item["score"]
            with app.db() as c:
                c.execute(
                    "INSERT INTO recommendation_feedback(identifier,vote,updated_at) VALUES(?,1,?)",
                    (sample["identifier"], app.now()),
                )
            self.assertGreater(app.recommend_recent("machine translation")["items"][0]["score"], before)

    def test_arxiv_journal_ref_and_code_are_distinguished_from_jif(self):
        atom = b"""<?xml version="1.0" encoding="utf-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom"
              xmlns:arxiv="http://arxiv.org/schemas/atom">
          <entry>
            <id>http://arxiv.org/abs/2601.12345v1</id>
            <title>Example method</title>
            <summary>Code released at https://github.com/example/method.</summary>
            <arxiv:comment>Also see https://gitlab.com/team/method).</arxiv:comment>
            <arxiv:journal_ref>Example Journal 12 (2026) 100-108</arxiv:journal_ref>
            <arxiv:doi>10.1000/example</arxiv:doi>
          </entry>
        </feed>"""
        class Feed:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def read(self, _): return atom
        with patch("scholar_api._wait_turn"), patch(
            "scholar_api.urllib.request.urlopen", return_value=Feed()
        ):
            item = scholar_api.recent("example method")[0]
        self.assertEqual(item["journal_ref"], "Example Journal 12 (2026) 100-108")
        self.assertEqual(item["doi"], "10.1000/example")
        self.assertEqual(item["code_urls"], [
            "https://github.com/example/method",
            "https://gitlab.com/team/method",
        ])
        with patch("app.recent_arxiv", return_value=[item]):
            displayed = app.recommend_recent("example method")["items"][0]
        self.assertEqual(displayed["venue"], item["journal_ref"])
        self.assertEqual(displayed["code_status"], "link_found_unverified")
        self.assertIsNone(displayed["impact_factor"])
        item["summary"] = "No link"
        item["comment"] = ""
        item["code_urls"] = []
        with patch("app.recent_arxiv", return_value=[item]):
            missing = app.recommend_recent("example method")["items"][0]
        self.assertEqual(missing["code_status"], "not_found_not_proven_closed")
        item["journal_ref"] = ""
        item["comment"] = "Accepted at ICML 2026; revised version forthcoming"
        with patch("app.recent_arxiv", return_value=[item]):
            conference = app.recommend_recent("example method")["items"][0]
        self.assertIn("ICML 2026", conference["venue"])
        self.assertIn("arXiv", conference["venue_source"])
        self.assertIsNone(conference["impact_factor"])

    def test_tracking_deduplicates_work_and_records_new_versions(self):
        sub_id = app.create_tracking("machine translation", 360, 10)
        v1 = {
            "identifier": "2610.12345v1", "title": "New translation work",
            "published": "2026-10-10", "summary": "translation",
            "authors": ["Researcher"], "source": "arXiv API",
        }
        with patch("app.recent_arxiv", side_effect=[
            [v1], [v1], [dict(v1, identifier="2610.12345v2")]
        ]) as remote:
            first = app.run_tracking(sub_id)
            second = app.run_tracking(sub_id)
            third = app.run_tracking(sub_id)
        self.assertEqual(remote.call_count, 3)
        self.assertEqual(first["new_count"], 1)
        self.assertEqual(second["new_count"], 0)
        self.assertEqual(third["new_count"], 0)
        self.assertEqual(third["updated_versions"], ["2610.12345v2"])
        items = app.tracking_items(sub_id)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["identifier"], "2610.12345")
        self.assertEqual(items[0]["latest_identifier"], "2610.12345v2")
        subscription = next(
            s for s in app.tracking_subscriptions() if s["id"] == sub_id
        )
        self.assertIsNotNone(subscription["last_success"])
        self.assertIsNotNone(subscription["next_run"])
        self.assertEqual(subscription["last_error"], "")
        app.toggle_tracking(sub_id, False)
        self.assertFalse(next(
            s for s in app.tracking_subscriptions() if s["id"] == sub_id
        )["enabled"])
        with self.assertRaisesRegex(ValueError, "停用"):
            app.run_tracking(sub_id)
        self.assertTrue(app.toggle_tracking(sub_id, True)["enabled"])

    def test_tracking_failure_records_error_and_does_not_claim_success(self):
        sub_id = app.create_tracking("transformer research", 1440, 20)
        with patch("app.recent_arxiv", side_effect=TimeoutError("simulated timeout")):
            result = app.run_tracking(sub_id)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["new_count"], 0)
        subscription = next(
            s for s in app.tracking_subscriptions() if s["id"] == sub_id
        )
        self.assertIsNone(subscription["last_success"])
        self.assertIn("simulated timeout", subscription["last_error"])
        self.assertIsNotNone(subscription["next_run"])
        self.assertTrue(any(
            e["event_type"] == "tracking_refresh" and e["mode"] == "error"
            for e in app.audit_events()
        ))
        with patch("app.recent_arxiv", return_value=[]):
            recovery = app.run_tracking(sub_id)
        self.assertEqual(recovery["status"], "ok")
        self.assertEqual(recovery["new_count"], 0)

    def test_tracking_rejects_unbounded_intervals_and_batched_queries(self):
        with self.assertRaisesRegex(ValueError, "360"):
            app.create_tracking("machine translation", 1, 20)
        with self.assertRaisesRegex(ValueError, "1–50"):
            app.create_tracking("machine translation", 1440, 1000)
        first = app.create_tracking("machine translation")
        with self.assertRaisesRegex(ValueError, "已订阅"):
            app.create_tracking("MACHINE TRANSLATION")
        self.assertEqual(first, app.tracking_subscriptions()[0]["id"])
        with self.assertRaisesRegex(ValueError, "50"):
            scholar_api.recent("machine translation", 500)

    def test_tracking_http_create_refresh_pause_resume_and_delete(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        sample = {
            "identifier": "2610.12345v1", "title": "Machine Translation",
            "published": "2026-10-10", "summary": "translation test",
            "authors": ["Scientist"], "source": "arXiv API",
        }
        def post(url, payload=None):
            req = urllib.request.Request(
                base + url, method="POST",
                data=json.dumps(payload or {}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            return urllib.request.urlopen(req, timeout=8)
        try:
            created = json.load(post("/api/subscriptions", {
                "topic": "machine translation",
                "interval_minutes": 360, "max_results": 20,
            }))
            sub_id = created["id"]
            subscriptions = json.load(urllib.request.urlopen(
                base + "/api/subscriptions", timeout=5,
            ))["subscriptions"]
            self.assertEqual(subscriptions[0]["id"], sub_id)
            with patch("app.recent_arxiv", return_value=[sample]):
                refreshed = json.load(post(
                    f"/api/subscriptions/{sub_id}/refresh"
                ))
            self.assertEqual(refreshed["new_count"], 1)
            candidates = json.load(urllib.request.urlopen(
                base + f"/api/subscriptions/{sub_id}/candidates", timeout=5
            ))["candidates"]
            self.assertEqual(candidates[0]["latest_identifier"], "2610.12345v1")
            self.assertFalse(json.load(post(
                f"/api/subscriptions/{sub_id}/pause"
            ))["enabled"])
            with self.assertRaises(urllib.error.HTTPError) as paused:
                post(f"/api/subscriptions/{sub_id}/refresh")
            self.assertEqual(paused.exception.code, 400)
            self.assertTrue(json.load(post(
                f"/api/subscriptions/{sub_id}/resume"
            ))["enabled"])
            deleted = urllib.request.Request(
                base + f"/api/subscriptions/{sub_id}", method="DELETE",
            )
            self.assertEqual(json.load(urllib.request.urlopen(
                deleted, timeout=5
            ))["deleted"], sub_id)
            with app.db() as c:
                self.assertEqual(c.execute(
                    "SELECT COUNT(*) FROM tracking_items"
                ).fetchone()[0], 0)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_feedback_http_rejects_bad_id_and_allows_reset(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}/api/recommendations/feedback"
        try:
            def vote(identifier, number):
                request = urllib.request.Request(
                    url, method="POST",
                    data=__import__("json").dumps(
                        {"identifier": identifier, "vote": number}
                    ).encode(),
                    headers={"Content-Type": "application/json"},
                )
                return urllib.request.urlopen(request, timeout=4)
            with self.assertRaises(urllib.error.HTTPError) as invalid:
                vote("https://localhost/private", 1)
            self.assertEqual(invalid.exception.code, 400)
            self.assertEqual(vote("2601.12345v1", 1).status, 200)
            with app.db() as c:
                self.assertEqual(c.execute(
                    "SELECT vote FROM recommendation_feedback WHERE identifier='2601.12345v1'"
                ).fetchone()["vote"], 1)
            self.assertEqual(vote("2601.12345v1", 0).status, 200)
            with app.db() as c:
                self.assertIsNone(c.execute(
                    "SELECT vote FROM recommendation_feedback WHERE identifier='2601.12345v1'"
                ).fetchone())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_renamed_file_still_detects_content_duplicate(self):
        newest = self.ingest_one("1706.03762v7.pdf")
        with app.db() as c:
            title = c.execute("SELECT title FROM papers WHERE id=?", (newest,)).fetchone()["title"]
        self.assertEqual(title, "Attention Is All You Need")
        older = self.ingest_one("1706.03762v1.pdf", "renamed_no_version.pdf")
        with app.db() as c:
            row = c.execute("SELECT duplicate_of,similarity,status FROM papers WHERE id=?", (older,)).fetchone()
        self.assertEqual(row["status"], "ready")
        self.assertEqual(row["duplicate_of"], newest)
        self.assertGreaterEqual(row["similarity"], 0.42)

    def test_duplicate_keep_existing_removes_new_copy_and_index(self):
        newest = self.ingest_one("1706.03762v7.pdf")
        older = self.ingest_one("1706.03762v1.pdf")
        with app.db() as c:
            ids = [r["id"] for r in c.execute(
                "SELECT id FROM chunks WHERE paper_id=?", (older,)
            )]
            self.assertTrue(ids)
        result = app.resolve_duplicate(older, newest, "keep_existing")
        self.assertEqual(result["kept_id"], newest)
        self.assertEqual(result["removed_id"], older)
        with app.db() as c:
            self.assertIsNone(c.execute(
                "SELECT id FROM papers WHERE id=?", (older,)
            ).fetchone())
            self.assertEqual(c.execute(
                "SELECT COUNT(*) FROM chunks WHERE paper_id=?", (older,)
            ).fetchone()[0], 0)
            self.assertEqual(c.execute(
                "SELECT COUNT(*) FROM chunks_fts WHERE paper_id=?", (older,)
            ).fetchone()[0], 0)
        self.assertTrue((SAMPLE_DIR / "1706.03762v1.pdf").is_file())
        self.assertTrue(app.retrieve("Transformer base GPU", newest))
        self.assertEqual(app.retrieve("Transformer base GPU", older), [])
        self.assertTrue(any(
            event["mode"] == "keep_existing" and event["paper_id"] == newest
            for event in app.audit_events()
        ))

    def test_resolution_deletes_owned_upload_only_after_commit(self):
        newest = self.ingest_one("1706.03762v7.pdf")
        local_path = app.FILES / "owned_upload.pdf"
        shutil.copyfile(SAMPLE_DIR / "1706.03762v1.pdf", local_path)
        incoming = __import__("uuid").uuid4().hex[:14]
        with app.db() as conn:
            conn.execute(
                "INSERT INTO papers(id,filename,filepath,created_at) VALUES(?,?,?,?)",
                (incoming, "1706.03762v1.pdf", str(local_path.resolve()), app.now()),
            )
        app.ingest(incoming)
        self.assertTrue(local_path.exists())
        app.resolve_duplicate(incoming, newest, "keep_existing")
        self.assertFalse(local_path.exists())
        self.assertTrue((SAMPLE_DIR / "1706.03762v7.pdf").exists())

    def test_http_resolution_older_requires_reconfirmation(self):
        newest = self.ingest_one("1706.03762v7.pdf")
        older = self.ingest_one("1706.03762v1.pdf")
        server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = (
            f"http://127.0.0.1:{server.server_port}"
            f"/api/papers/{older}/resolve-duplicate"
        )
        try:
            def post(confirm):
                req = urllib.request.Request(
                    url, method="POST",
                    data=json.dumps({
                        "existing_id": newest, "action": "replace_existing",
                        "confirm_older": confirm,
                    }).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                return urllib.request.urlopen(req, timeout=6)
            with self.assertRaises(urllib.error.HTTPError) as denied:
                post(False)
            self.assertEqual(denied.exception.code, 400)
            self.assertEqual(json.load(post(True))["kept_id"], older)
            with self.assertRaises(urllib.error.HTTPError) as replay:
                post(True)
            self.assertEqual(replay.exception.code, 400)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_replacing_newer_version_requires_explicit_older_confirmation(self):
        newest = self.ingest_one("1706.03762v7.pdf")
        older = self.ingest_one("1706.03762v1.pdf")
        with self.assertRaisesRegex(ValueError, "再次明确确认"):
            app.resolve_duplicate(older, newest, "replace_existing")
        with app.db() as c:
            self.assertEqual(c.execute(
                "SELECT COUNT(*) FROM papers WHERE id IN (?,?)", (older, newest)
            ).fetchone()[0], 2)
        result = app.resolve_duplicate(
            older, newest, "replace_existing", confirm_older=True
        )
        self.assertEqual(result["kept_id"], older)
        self.assertTrue(result["older_version_confirmed"])
        with app.db() as c:
            self.assertIsNone(c.execute(
                "SELECT id FROM papers WHERE id=?", (newest,)
            ).fetchone())
            self.assertEqual(c.execute(
                "SELECT COUNT(*) FROM chunks_fts WHERE paper_id=?", (newest,)
            ).fetchone()[0], 0)
        self.assertTrue((SAMPLE_DIR / "1706.03762v7.pdf").is_file())
        self.assertTrue(all(
            item["paper_id"] == older
            for item in app.retrieve("Transformer base GPU")
        ))

    def test_duplicate_keep_both_is_non_destructive_and_replay_safe(self):
        newest = self.ingest_one("1706.03762v7.pdf")
        older = self.ingest_one("1706.03762v1.pdf")
        result = app.resolve_duplicate(older, newest, "keep_both")
        self.assertIsNone(result["removed_id"])
        with app.db() as c:
            self.assertEqual(c.execute(
                "SELECT COUNT(*) FROM papers WHERE id IN (?,?)", (older, newest)
            ).fetchone()[0], 2)
            row = c.execute(
                "SELECT duplicate_resolution,duplicate_of,similarity FROM papers WHERE id=?", (older,)
            ).fetchone()
            self.assertEqual(row["duplicate_resolution"], "kept_both")
            self.assertEqual(row["duplicate_of"], newest)
            self.assertGreaterEqual(row["similarity"], 0.42)
        with self.assertRaisesRegex(ValueError, "待处理"):
            app.resolve_duplicate(older, newest, "keep_existing")
        self.assertTrue(app.retrieve("Transformer base GPU", older))
        self.assertTrue(app.retrieve("Transformer base GPU", newest))

    def test_version_comparison_and_preferred_latest(self):
        first = self.ingest_one("1706.03762v1.pdf")
        latest = self.ingest_one("1706.03762v7.pdf")
        result = app.version_comparison(first, latest)
        self.assertEqual(result["first"]["version"], 1)
        self.assertEqual(result["second"]["version"], 7)
        self.assertTrue(result["candidates"])
        self.assertTrue(any("41.0" in x["before"] and "41.8" in x["after"]
                            for x in result["candidates"]))
        self.assertTrue(any(change["before_page"] for change in result["candidates"]))
        self.assertTrue(any(change["after_page"] for change in result["candidates"]))
        for change in result["candidates"]:
            self.assertTrue(1 <= change["before_page"] <= 15)
            self.assertTrue(1 <= change["after_page"] <= 15)
        result_latest = app.retrieve("Transformer base model GPU")
        self.assertTrue(result_latest)
        self.assertTrue(all(item["paper_id"] == latest for item in result_latest))
        scoped = app.retrieve("Transformer base model GPU", first)
        self.assertTrue(scoped)
        self.assertTrue(all(item["paper_id"] == first for item in scoped))

    def test_compare_rejects_unrelated_papers(self):
        first = self.ingest_one("1706.03762v1.pdf")
        other = self.ingest_one("language_understanding_paper.pdf")
        with self.assertRaisesRegex(ValueError, "arXiv ID"):
            app.version_comparison(first, other)

    def test_preferred_copy_does_not_depend_on_import_order(self):
        records = [
            {"id": "old", "arxiv_id": "1706.03762", "version": 1, "ocr_pages": 0, "created_at": "later"},
            {"id": "new", "arxiv_id": "1706.03762", "version": 7, "ocr_pages": 0, "created_at": "earlier"},
            {"id": "scan", "arxiv_id": "1706.03762", "version": 7, "ocr_pages": 15, "created_at": "latest"},
        ]
        self.assertEqual(app.preferred_papers(records), ["new"])

    def test_citation_graph_uses_bibliography_evidence_and_local_rank(self):
        foundation = self.ingest_one("1607.06450v1.pdf")
        citing_v1 = self.ingest_one("1706.03762v1.pdf")
        self.ingest_one("1706.03762v7.pdf")
        graph = app.citation_graph()
        self.assertEqual(len(graph["nodes"]), 2)
        self.assertTrue(graph["collapsed_versions"])
        edge = next(e for e in graph["edges"] if e["target"] == foundation)
        self.assertNotEqual(edge["source"], citing_v1)
        self.assertEqual(edge["page_no"], 10)
        self.assertEqual(edge["match_type"], "arxiv_id")
        self.assertIn("1607.06450", edge["excerpt"])
        nodes = {node["id"]: node for node in graph["nodes"]}
        self.assertEqual(nodes[foundation]["in_degree"], 1)
        self.assertGreater(nodes[foundation]["pagerank"], nodes[edge["source"]]["pagerank"])

    def test_official_qlora_citation_points_to_lora_source_page(self):
        lora = self.ingest_one("2106.09685v2.pdf")
        qlora = self.ingest_one("2305.14314v1.pdf")
        graph = app.citation_graph()
        edge = next(
            e for e in graph["edges"]
            if e["source"] == qlora and e["target"] == lora
        )
        self.assertEqual(edge["page_no"], 18)
        self.assertEqual(edge["match_type"], "arxiv_id")
        self.assertIn("2106.09685", edge["excerpt"])

    def test_graph_review_only_makes_backed_local_citation_claims(self):
        foundation = self.ingest_one("1607.06450v1.pdf")
        citing = self.ingest_one("1706.03762v7.pdf")
        result = app.graph_survey()
        self.assertEqual(len(result["statements"]), 1)
        statement = result["statements"][0]
        self.assertEqual(statement["source_paper_id"], citing)
        self.assertEqual(statement["target_paper_id"], foundation)
        self.assertEqual(statement["source_page"], 10)
        self.assertIn("1607.06450", statement["source_excerpt"])
        self.assertIn("不是", result["note"])

    def test_grounded_writing_has_no_references_without_matching_evidence(self):
        transformer = self.ingest_one("1706.03762v7.pdf")
        layer = self.ingest_one("1607.06450v1.pdf")
        draft = app.grounded_writing(
            "Transformer attention normalization", [transformer, layer]
        )
        self.assertEqual(draft["status"], "evidence_candidates")
        self.assertTrue(draft["evidence"])
        self.assertTrue(all(
            entry["paper_id"] in (transformer, layer) and entry["page_no"] >= 1
            for entry in draft["evidence"]
        ))
        self.assertTrue(all(ref["arxiv_id"] for ref in draft["references"]))
        self.assertIn("核验", draft["note"])
        missing = app.grounded_writing("zzqplmxyvvvzz", [transformer, layer])
        self.assertEqual(missing["status"], "no_evidence")
        self.assertEqual(missing["references"], [])
        self.assertEqual(missing["evidence"], [])
        with self.assertRaisesRegex(ValueError, "请选择"):
            app.grounded_writing("Transformer attention", [])

    def test_transfer_idea_shows_original_pdf_even_without_arxiv_id(self):
        paper_id = "c" * 14
        source = (
            "We propose calibrated evidential arbitration (CEA), a framework "
            "for asymmetric decision-level fusion. The experiments use EuroSAT "
            "as a few-shot recognition benchmark; no transfer success claim is "
            "made for a different task."
        )
        with app.db() as conn:
            conn.execute(
                """INSERT INTO papers(id,filename,filepath,title,status,created_at)
                   VALUES(?,?,?,?,'ready',?)""",
                (paper_id, "cea.pdf", "unused",
                 "Calibrated evidential arbitration", app.now()),
            )
            row = conn.execute(
                "INSERT INTO chunks(paper_id,page_no,content) VALUES(?,6,?)",
                (paper_id, source),
            )
            conn.execute(
                "INSERT INTO chunks_fts(rowid,paper_id,page_no,content) VALUES(?,?,6,?)",
                (row.lastrowid, paper_id, source),
            )
        result = app.grounded_writing("把模型迁移到遥感领域", [paper_id])
        self.assertEqual(result["status"], "evidence_candidates")
        self.assertEqual(result["references"], [])
        self.assertTrue(result["target_domain_matches"])
        self.assertEqual(result["evidence"][0]["page_no"], 6)
        self.assertIn("实验验证", result["outline"]["Research Plan（待验证）"][-1])
        self.assertIn("遥感", result["transfer_plan"][1])

    def test_optional_writing_model_requires_citable_sentences_and_keeps_fallback(self):
        paper = self.ingest_one("1706.03762v7.pdf")
        base = app.grounded_writing("Transformer attention", [paper])
        self.assertTrue(base["evidence"])
        with patch("app.model_writing_draft", return_value="It uses 999 GPUs [1]."):
            draft, reason = app.writing_draft_with_guardrails(base)
        self.assertIsNone(draft)
        self.assertIn("数值", reason)
        with patch("app.model_writing_draft",
                   return_value="The paper discusses attention [1]."):
            draft, reason = app.writing_draft_with_guardrails(base)
        self.assertIn("attention [1]", draft)
        self.assertEqual(reason, "")
        with patch("app.model_writing_draft", side_effect=RuntimeError("未配置模型")):
            draft, reason = app.writing_draft_with_guardrails(base)
        self.assertIsNone(draft)
        self.assertIn("退回", reason)

    def test_reference_verification_reports_official_match_and_conflict(self):
        transformer = self.ingest_one("1706.03762v7.pdf")
        layer = self.ingest_one("1607.06450v1.pdf")
        with patch("app.arxiv_metadata", side_effect=[
            {
                "identifier": "1706.03762v7", "title": "Attention Is All You Need",
                "authors": ["Ashish Vaswani"], "published": "2017-06-12",
                "source": "arXiv API",
            },
            {
                "identifier": "1607.06450v1", "title": "Totally Unrelated Paper",
                "authors": ["Other Author"], "published": "2016-07-01",
                "source": "arXiv API",
            },
        ]):
            output = app.verify_writing_references([transformer, layer])
        self.assertEqual(output["verified"], 1)
        self.assertEqual(
            [row["status"] for row in output["items"]],
            ["verified_metadata", "title_conflict"],
        )
        self.assertEqual(output["items"][0]["official"]["authors"],
                         ["Ashish Vaswani"])
        with patch("app.arxiv_metadata", side_effect=OSError("offline")):
            offline = app.verify_writing_references([transformer])
        self.assertEqual(offline["items"][0]["status"], "unavailable")

    def test_reference_mentions_outside_bibliography_do_not_create_edge(self):
        records = [
            ("a" * 14, "A source study", "1706.03762", "Intro mentions arXiv:1607.06450 and Layer Normalization."),
            ("b" * 14, "Layer Normalization", "1607.06450", "This is the study."),
        ]
        with app.db() as c:
            for paper_id, title, arxiv, content in records:
                c.execute(
                    """INSERT INTO papers(id,filename,filepath,title,arxiv_id,version,status,pages,created_at)
                       VALUES(?,?,?,?,?,1,'ready',1,?)""",
                    (paper_id, f"{paper_id}.pdf", f"{paper_id}.pdf", title, arxiv, app.now()),
                )
                c.execute(
                    "INSERT INTO chunks(paper_id,page_no,content) VALUES(?,1,?)",
                    (paper_id, content),
                )
        self.assertEqual(app.citation_graph()["edges"], [])
        with app.db() as c:
            c.execute(
                "INSERT INTO chunks(paper_id,page_no,content) VALUES(?,2,?)",
                ("a" * 14, "References\n[1] Jimmy Ba. Layer Normalization. arXiv:1607.06450, 2016."),
            )
        edges = app.citation_graph()["edges"]
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0]["page_no"], 2)
        self.assertEqual(edges[0]["source"], "a" * 14)
        self.assertEqual(edges[0]["target"], "b" * 14)

    def test_scan_ocr_indexes_official_pdf(self):
        paper = self.ingest_one("1706.03762v1_img.pdf")
        with app.db() as c:
            row = c.execute(
                "SELECT status,pages,processed_pages,ocr_pages,chunks,title FROM papers WHERE id=?",
                (paper,),
            ).fetchone()
        self.assertEqual(row["status"], "ready")
        self.assertEqual(row["pages"], 15)
        self.assertEqual(row["processed_pages"], 15)
        self.assertGreaterEqual(row["ocr_pages"], 12)
        self.assertGreater(row["chunks"], 0)
        self.assertIn("Attention", row["title"])
        self.assertTrue(app.retrieve("Transformer attention", paper))
        with app.db() as c:
            box_count = c.execute(
                "SELECT COUNT(*) FROM ocr_lines WHERE paper_id=?", (paper,)
            ).fetchone()[0]
        self.assertGreater(box_count, 0)
        hit = app.retrieve("Transformer attention", paper)[0]
        with app.db() as c:
            lines = [dict(row) for row in c.execute(
                """SELECT line_no,content,confidence,x0,y0,x1,y1
                   FROM ocr_lines WHERE paper_id=? AND page_no=? ORDER BY line_no""",
                (paper, hit["page_no"]),
            )]
        image, marked, method = render_evidence(
            SAMPLE_DIR / "1706.03762v1_img.pdf",
            hit["page_no"], hit["content"], lines, "Transformer attention",
        )
        self.assertTrue(image.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertTrue(marked)
        self.assertEqual(method, "OCR question-term overlap")

    def test_ocr_dependency_failure_is_visible(self):
        with patch("app.scan_page", side_effect=RuntimeError("OCR engine unavailable")):
            paper = self.ingest_one("1706.03762v1_img.pdf")
        with app.db() as c:
            row = c.execute("SELECT status,error FROM papers WHERE id=?", (paper,)).fetchone()
        self.assertEqual(row["status"], "ocr_required")
        self.assertIn("OCR engine unavailable", row["error"])

    def test_no_evidence_for_nonsense(self):
        self.ingest_one("1706.03762v1.pdf")
        self.assertEqual(app.retrieve("zzqplmxyvvvzz"), [])

    def test_unseen_numeric_constraint_never_becomes_guessed_gpu_evidence(self):
        paper = self.ingest_one("1706.03762v7.pdf")
        query = "What GPU was used to train fictional XQ-9999 accelerator?"
        self.assertEqual(app.explicit_numeric_constraints(query), ["9999"])
        self.assertEqual(app.retrieve(query, paper), [])
        self.assertTrue(app.retrieve("Which GPU was used for base training?", paper))

    def test_fact_evidence_metric_rejects_right_word_on_wrong_page(self):
        case = {
            "id": "test", "question": "GPU?", "expected_pages": [7],
            "reference_answer": "8 NVIDIA P100", "required_evidence": ["P100", "8"],
        }
        hits = [{
            "chunk_id": 1, "page_no": 8,
            "retrieval": "BM25", "content": "8 NVIDIA P100 GPUs",
        }]
        wrong = inspect_case(case, hits)
        self.assertFalse(wrong["page_hit"])
        self.assertFalse(wrong["all_anchors_in_top_3"])
        hits[0]["page_no"] = 7
        right = inspect_case(case, hits)
        self.assertTrue(right["page_hit"])
        self.assertTrue(right["single_passage_covers_all_anchors"])

    def test_gold_fact_labels_are_present_on_the_cited_original_pdf_pages(self):
        from pypdf import PdfReader

        fixture = json.loads(CASES_FILE.read_text(encoding="utf-8"))
        source = SAMPLE_DIR / fixture["source_file"]
        reader = PdfReader(source)
        case_ids = [row["id"] for row in fixture["cases"]]
        self.assertEqual(len(case_ids), len(set(case_ids)))
        for case in fixture["cases"]:
            for page_no in case["expected_pages"]:
                self.assertGreaterEqual(page_no, 1)
                self.assertLessEqual(page_no, len(reader.pages))
            page_text = normalize(" ".join(
                reader.pages[page_no - 1].extract_text() or ""
                for page_no in case["expected_pages"]
            ))
            for anchor in case["required_evidence"]:
                self.assertIn(normalize(anchor), page_text, case["id"])

    def test_evidence_expands_only_adjacent_chunks_of_same_page(self):
        paper = self.ingest_one("1706.03762v7.pdf")
        hit = next(
            row for row in app.retrieve("Layer Normalization references", paper)
            if row["page_no"] == 10
        )
        self.assertEqual(hit["context_scope"], "same_pdf_page")
        self.assertIn("Jimmy Lei Ba", hit["content"])
        self.assertIn("1607.06450", hit["content"])
        with app.db() as c:
            page = c.execute(
                "SELECT page_no FROM chunks WHERE id=?", (hit["chunk_id"],)
            ).fetchone()["page_no"]
        self.assertEqual(hit["page_no"], page)
        with app.db() as c:
            c.execute(
                """INSERT INTO papers(id,filename,filepath,title,status,pages,created_at)
                   VALUES('aaaaaaaaaaaaaa','isolation.pdf','isolation.pdf',
                          'isolation','ready',2,?)""",
                (app.now(),),
            )
            c.execute(
                "INSERT INTO chunks(paper_id,page_no,content) VALUES('aaaaaaaaaaaaaa',1,?)",
                ("A" * 1000,),
            )
            c.execute(
                "INSERT INTO chunks(paper_id,page_no,content) VALUES('aaaaaaaaaaaaaa',2,?)",
                ("B" * 800 + "PRIVATE_NEXT_PAGE_ONLY",),
            )
            chunk_id = c.execute(
                "SELECT id FROM chunks WHERE paper_id='aaaaaaaaaaaaaa' AND page_no=1"
            ).fetchone()["id"]
        expanded = app.same_page_context([{
            "chunk_id": chunk_id, "paper_id": "aaaaaaaaaaaaaa",
            "page_no": 1, "content": "A" * 800,
        }])[0]["content"]
        self.assertIn("A" * 10, expanded)
        self.assertNotIn("PRIVATE_NEXT_PAGE_ONLY", expanded)


if __name__ == "__main__":
    unittest.main()
