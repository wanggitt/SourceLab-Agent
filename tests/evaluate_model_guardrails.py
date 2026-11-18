"""Synthetic checks for citation/numeric guardrails, not model factuality."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app

OUTPUT = Path(__file__).with_name("model_guardrail_report.json")
EVIDENCE = [
    {"content": "The base model uses 8 NVIDIA P100 GPUs."},
    {"content": "The other study reports 4 TPU chips."},
]
CASES = [
    ("two_supported_claims", "The model uses 8 GPUs [1]. Another uses 4 chips [2].", True),
    ("wrong_citation", "The model uses 8 GPUs [2].", False),
    ("unsupported_number", "The model uses 999 GPUs [1].", False),
    ("uncited_claim", "The model uses 8 GPUs [1]. Another uses 4 chips.", False),
    ("missing_source_id", "The model uses 8 GPUs [3].", False),
    ("prose_without_numbers_but_wrong_meaning",
     "The paper proves all GPUs are unnecessary [1].", True),
]


def run():
    cases = []
    for name, draft, expected_accept in CASES:
        failure = app.verify_model_draft(draft, EVIDENCE)
        accepted = failure == ""
        cases.append({
            "name": name, "expected_accept": expected_accept,
            "accepted": accepted,
            "behaved_as_expected": accepted == expected_accept,
            "reason": failure,
        })
    return {
        "test_type": "synthetic_guardrail_checks_only",
        "passed": sum(item["behaved_as_expected"] for item in cases),
        "total": len(cases),
        "cases": cases,
        "limits": (
            "最后一条错误语义陈述刻意穿过了规则检查，证明此机制"
            "无法验证推断语义；不能据此报告模型回答正确率、幻觉率"
            "或在真实科研问题上的安全保障水平。"
        ),
    }


if __name__ == "__main__":
    report = run()
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    print("synthetic guardrail cases", report["passed"], "/", report["total"])
    print("semantic false acceptance", next(
        item["accepted"] for item in report["cases"]
        if item["name"] == "prose_without_numbers_but_wrong_meaning"
    ))
    print(OUTPUT)
    if report["passed"] != report["total"]:
        raise SystemExit("Synthetic guardrail regression failed")
