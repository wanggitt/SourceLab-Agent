"""Smoke-test served UI assets and evidence-only task routing without user data."""
import json
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app


class UIHTTPSmoke(unittest.TestCase):
    def setUp(self):
        self.model_env = patch.dict(
            app.os.environ, {
                "LLM_CHAT_ENDPOINT": "", "LLM_MODEL": "", "LLM_API_KEY": "",
            },
        )
        self.model_env.start()

    def tearDown(self):
        self.model_env.stop()

    def test_served_layout_assets_and_shared_points_prompt(self):
        with tempfile.TemporaryDirectory() as folder:
            original = app.DATA, app.FILES, app.DB_FILE
            server = None
            try:
                app.DATA = Path(folder)
                app.FILES = app.DATA / "uploads"
                app.DB_FILE = app.DATA / "temporary.sqlite3"
                app.init_db()
                server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                url = f"http://127.0.0.1:{server.server_port}"
                with urllib.request.urlopen(url + "/") as response:
                    home = response.read().decode()
                with urllib.request.urlopen(url + "/style.css") as response:
                    css = response.read().decode()
                with urllib.request.urlopen(url + "/app.js") as response:
                    javascript = response.read().decode()
                self.assertIn('id="toggle-library"', home)
                self.assertIn('id="audit-window"', home)
                self.assertIn('id="structure-panel"', home)
                self.assertIn(".panel-resizer", css)
                self.assertIn("initLayout();", javascript)
                request = urllib.request.Request(
                    url + "/api/tasks/run",
                    data=json.dumps({
                        "instruction": "两篇论文有无共同点?",
                        "paper_ids": [],
                    }).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request) as response:
                    result = json.load(response)
                self.assertEqual(result["plan"][0]["tool"], "compare_papers")
                self.assertEqual(result["plan"][0]["status"], "needs_input")
                ask = urllib.request.Request(
                    url + "/api/ask",
                    data=json.dumps({
                        "question": "两篇论文有无共同点?",
                        "paper_id": "",
                    }).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(ask) as response:
                    answer = json.load(response)
                self.assertEqual(answer["mode"], "needs_attention")
                self.assertIn("勾选 2–4 篇", answer["answer"])
                with app.db() as connection:
                    connection.execute(
                        """INSERT INTO papers
                           (id,filename,filepath,title,status,pages,created_at)
                           VALUES(?,?,?,?,?,?,?)""",
                        ("a" * 14, "synthetic.pdf", "unused",
                         "Synthetic Paper", "ready", 2, app.now()),
                    )
                    connection.execute(
                        "INSERT INTO chunks(paper_id,page_no,content) VALUES(?,?,?)",
                        ("a" * 14, 1,
                         "Synthetic Paper\nAbstract\nSample abstract.\n"
                         "1 Introduction\nFigure 1: Sample diagram"),
                    )
                    connection.execute(
                        """INSERT INTO papers
                           (id,filename,filepath,title,arxiv_id,status,pages,created_at)
                           VALUES(?,?,?,?,?,?,?,?)""",
                        ("b" * 14, "arxiv.pdf", "unused",
                         "Transformer Test", "1706.03762", "ready", 1, app.now()),
                    )
                    cursor = connection.execute(
                        "INSERT INTO chunks(paper_id,page_no,content) VALUES(?,?,?)",
                        ("b" * 14, 1, "Transformer attention normalization experiment."),
                    )
                    connection.execute(
                        """INSERT INTO chunks_fts(rowid,paper_id,page_no,content)
                           VALUES(?,?,?,?)""",
                        (cursor.lastrowid, "b" * 14, 1,
                         "Transformer attention normalization experiment."),
                    )
                    backbone = (
                        "The text-alignment channel uses CLIP ViT-L/14 at "
                        "336-pixel resolution [1]. The visual-support channel "
                        "uses a frozen DINOv3 ViT-B/16 visual encoder [29]."
                    )
                    connection.execute(
                        """INSERT INTO papers
                           (id,filename,filepath,title,status,pages,created_at)
                           VALUES(?,?,?,?,?,?,?)""",
                        ("c" * 14, "frozen.pdf", "unused",
                         "Frozen channels", "ready", 4, app.now()),
                    )
                    cursor = connection.execute(
                        "INSERT INTO chunks(paper_id,page_no,content) VALUES(?,4,?)",
                        ("c" * 14, backbone),
                    )
                    connection.execute(
                        """INSERT INTO chunks_fts(rowid,paper_id,page_no,content)
                           VALUES(?,?,4,?)""",
                        (cursor.lastrowid, "c" * 14, backbone),
                    )
                with urllib.request.urlopen(
                    url + "/api/papers/" + "a" * 14 + "/structure"
                ) as response:
                    structure = json.load(response)
                self.assertEqual(structure["metadata"]["title"], "Synthetic Paper")
                self.assertEqual(structure["captions"][0]["page_no"], 1)
                self.assertEqual(structure["heading_tree"][0]["level"], 1)
                overview_request = urllib.request.Request(
                    url + "/api/ask",
                    data=json.dumps({
                        "question": "这篇论文讲什么?",
                        "paper_id": "a" * 14,
                    }).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(overview_request) as response:
                    overview = json.load(response)
                self.assertEqual(overview["mode"], "evidence_only")
                self.assertEqual(overview["evidence"][0]["page_no"], 1)
                self.assertIn("Sample abstract", overview["evidence"][0]["content"])
                backbone_request = urllib.request.Request(
                    url + "/api/ask",
                    data=json.dumps({
                        "question": "采用的骨干模型是什么",
                        "paper_id": "c" * 14,
                    }).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(backbone_request) as response:
                    backbone_result = json.load(response)
                self.assertEqual(backbone_result["mode"], "evidence_only")
                self.assertEqual(backbone_result["evidence"][0]["page_no"], 4)
                self.assertIn("CLIP ViT-L/14", backbone_result["answer"])
                self.assertIn("DINOv3 ViT-B/16", backbone_result["answer"])
                writing_request = urllib.request.Request(
                    url + "/api/writing/grounded",
                    data=json.dumps({
                        "idea": "Transformer attention", "paper_ids": ["b" * 14],
                    }).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(writing_request) as response:
                    writing = json.load(response)
                self.assertEqual(writing["status"], "evidence_candidates")
                self.assertTrue(writing["audit_id"])
                with urllib.request.urlopen(url + "/api/audit") as response:
                    audited = json.load(response)
                self.assertTrue(any(
                    event["id"] == writing["audit_id"] and event["event_type"] == "writing"
                    for event in audited["events"]
                ))
                self.assertEqual(writing["model_status"], "not_requested")
                model_request = urllib.request.Request(
                    url + "/api/writing/grounded",
                    data=json.dumps({
                        "idea": "Transformer attention",
                        "paper_ids": ["b" * 14], "use_model": True,
                    }).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(model_request) as response:
                    fallback = json.load(response)
                self.assertEqual(fallback["model_status"], "fallback")
                self.assertFalse(fallback["model_draft"])
                self.assertTrue(fallback["evidence"])
                source_pdf = Path(__file__).resolve().parents[2] / "pdf" / "1706.03762v7.pdf"
                if source_pdf.is_file():
                    with app.db() as connection:
                        connection.execute(
                            """UPDATE papers SET filepath=?,pages=15
                               WHERE id=?""",
                            (str(source_pdf), "a" * 14),
                        )
                    with urllib.request.urlopen(
                        url + "/api/papers/" + "a" * 14 + "/layout?page=4"
                    ) as response:
                        layout = json.load(response)
                    self.assertTrue(layout["visuals"])
                    with urllib.request.urlopen(
                        url + "/api/papers/" + "a" * 14
                        + "/visual-crop?page=4&visual=0"
                    ) as response:
                        self.assertEqual(response.headers["Content-Type"], "image/png")
                        self.assertTrue(response.read(8).startswith(b"\x89PNG"))
                    equation_request = urllib.request.Request(
                        url + "/api/papers/" + "a" * 14 + "/equations/explain",
                        data=json.dumps({
                            "page_no": 4, "index": 0, "confirm_cost": True,
                        }).encode(),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(equation_request) as response:
                        explanation = json.load(response)
                    self.assertEqual(explanation["status"], "error")
                    self.assertIsNone(explanation["draft"])
                    self.assertIn("模型未配置", explanation["message"])
                    self.assertTrue(explanation["equation"])
            finally:
                if server:
                    server.shutdown()
                    server.server_close()
                app.DATA, app.FILES, app.DB_FILE = original
