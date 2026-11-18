"""Deterministic, inspectable task routing; no fictional agent reasoning."""

from __future__ import annotations

import re
import json

MODEL_TOOLS = frozenset({
    "retrieve", "compare_papers", "version_comparison",
    "future_work", "citation_graph",
})

def is_generic_comparison(instruction):
    """A question about shared properties without a concrete comparison axis."""
    return isinstance(instruction, str) and bool(re.fullmatch(
        r"(?:这|那)?(?:两|二|几|多)?篇?(?:论文|文章|文献)"
        r"(?:有无|有|是否有|有哪些|的)?(?:共同点|相同点|相似点|相似之处|异同|区别)"
        r"[？?。!！]?", instruction.strip()
    ))


def task_plan(instruction):
    if not isinstance(instruction, str) or not 3 <= len(instruction.strip()) <= 400:
        raise ValueError("任务描述须在 3–400 字之间")
    text = instruction.lower()
    steps = []
    if re.search(r"导入|上传|下载|\bimport\b|\bupload\b|\bdownload\b", text):
        steps.append({
            "tool": "import_requires_confirmation",
            "reason": "文件上传及外部下载需要用户明确选择文件或核对论文元数据",
        })
    comparing = bool(re.search(
        r"对比|比较|异同|区别|共同点|相同点|相似之处|相似点|有哪些相同|"
        r"compare|versus|\bvs\.?\b", text
    ))
    if comparing and re.search(r"版本|\bv\d+\b|version", text):
        steps.append({"tool": "version_comparison", "reason": "任务涉及论文版本差异"})
    elif comparing:
        steps.append({"tool": "compare_papers", "reason": "任务要求跨论文证据对照"})
    if re.search(r"future\s*work|future\s*research|未来工作|研究方向|后续研究|前沿", text):
        steps.append({"tool": "future_work", "reason": "任务要求未来工作原文线索"})
    if re.search(r"图谱|引文网络|引用关系|基石论文|citation\s*(?:network|graph)|\bgraph\b", text):
        steps.append({"tool": "citation_graph", "reason": "任务要求局域引用网络"})
    if len(steps) == 0:
        steps.append({"tool": "retrieve", "reason": "未命中复合任务关键词，按证据检索执行"})
    return steps


def parse_model_plan(raw, instruction, selected_count=None):
    """Validate a model suggestion against an explicit non-destructive whitelist."""
    if not isinstance(raw, str) or len(raw) > 3000:
        raise ValueError("模型任务计划为空或过长")
    value = raw.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*|\s*```$", "", value).strip()
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("模型未返回合法 JSON 计划") from exc
    proposed = payload.get("tools") if isinstance(payload, dict) else None
    if (not isinstance(proposed, list) or not 1 <= len(proposed) <= 4
            or any(not isinstance(tool, str) or tool not in MODEL_TOOLS
                   for tool in proposed) or len(set(proposed)) != len(proposed)):
        raise ValueError("模型提出越权、重复或过多的工具调用")
    if selected_count is not None:
        if "compare_papers" in proposed and selected_count < 2:
            raise ValueError("模型对照计划缺少至少两篇所选论文")
        if "version_comparison" in proposed and selected_count != 2:
            raise ValueError("模型版本计划须选择恰好两篇文献")
        if "future_work" in proposed and selected_count < 1:
            raise ValueError("模型未来工作计划缺少所选论文")
    if any(step["tool"] == "import_requires_confirmation"
           for step in task_plan(instruction)):
        # A model cannot bypass user confirmation for file/network writes.
        proposed = ["import_requires_confirmation"] + proposed
    return [
        {
            "tool": tool,
            "reason": "需用户确认外部操作" if tool == "import_requires_confirmation"
            else "模型提出；服务端白名单校验通过",
        }
        for tool in proposed
    ]
