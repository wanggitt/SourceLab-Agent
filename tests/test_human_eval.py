"""Guard against claiming unreviewed cases are measured performance."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

FILE = Path(__file__).with_name("human_eval.py")
SPEC = importlib.util.spec_from_file_location("human_eval", FILE)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class HumanEvaluationTests(unittest.TestCase):
    def test_initial_state_is_unscored(self):
        original = module.WORK
        try:
            with tempfile.TemporaryDirectory() as temp:
                module.WORK = Path(temp)
                module.init()
                module.score()
                report = module.read("results.json")
                self.assertEqual(len(module.read("graph_labels.json")), 380)
                self.assertIsNone(report["graph"]["complete_precision"])
                self.assertIsNone(report["graph"]["complete_recall"])
                self.assertIsNone(report["qa"]["answer_correct_human_only"]["value"])
                self.assertIsNone(report["qa"]["negative_correct_refusal_human_only"]["value"])
        finally:
            module.WORK = original

    def test_gold_preserved_on_reinit_and_partial_precision(self):
        original = module.WORK
        try:
            with tempfile.TemporaryDirectory() as temp:
                module.WORK = Path(temp)
                module.init()
                rows = module.read("graph_labels.json")
                edge = next(x for x in rows if x["predicted"])
                edge["gold_cites_target"] = True
                edge["predicted_evidence_valid"] = False
                module.write("graph_labels.json", rows)
                module.init()
                module.score()
                result = module.read("results.json")["graph"]
                self.assertEqual(result["pairs_reviewed"]["numerator"], 1)
                self.assertIsNone(result["complete_precision"])
                self.assertIsNone(result["complete_recall"])
                self.assertFalse(next(x for x in module.read("graph_labels.json")
                                      if x["id"] == edge["id"])["predicted_evidence_valid"])
        finally:
            module.WORK = original

    def test_geometry_and_cost_are_not_guessed(self):
        self.assertEqual(module.bbox_iou([0, 0, 4, 4], [2, 2, 6, 6]), round(4 / 28, 4))
        self.assertIsNone(module.bbox_iou(None, [0, 0, 4, 4]))
        self.assertIsNone(module.charge({"prompt_tokens": 100}))
        self.assertEqual(module.charge({"prompt_tokens": 100, "completion_tokens": 50,
                                        "input_usd_per_million": 1,
                                        "output_usd_per_million": 2}), 0.0002)

    def test_collect_existing_human_label_in_isolated_db(self):
        official = json.loads((FILE.parent / "official_fact_cases.json").read_text(encoding="utf-8"))
        first = official["cases"][0]
        original = module.WORK
        try:
            with tempfile.TemporaryDirectory() as temp:
                module.WORK = Path(temp)
                module.write("qa_labels.json", [{
                    "id": first["id"], "task_type": "fact",
                    "source_pdfs": [official["source_file"]],
                    "question": first["question"], "answerable": True,
                    "gold_answer": first["reference_answer"],
                    "gold_pages": first["expected_pages"],
                    "gold_anchors": first["required_evidence"],
                    "model_answer": "", "answer_review": None,
                }])
                module.collect()
                prediction = module.read("qa_predictions.json")[0]
                self.assertTrue(prediction["gold_page_hit"])
                self.assertTrue(prediction["gold_anchor_hit"])
                self.assertEqual(prediction["by_paper"][0]["source_pdf"],
                                 official["source_file"])
        finally:
            module.WORK = original


if __name__ == "__main__":
    unittest.main()
