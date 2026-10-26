#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""统一调查协议：委派提示构造与结构化结果解析（变更 add-investigation-protocol）。

本模块补上统一数据契约（``models.py``）与运行时文本通道之间的薄协议：

* :func:`render_result_contract` —— 统一输出约定：子 Agent 最终消息以
  一个 json 代码块结束，内容为 DiagnosisResult JSON；供委派提示与四个
  专业 Skill 复用。
* :func:`build_investigation_prompt` —— 由 InvestigationTask 生成统一
  委派提示（任务要素 + 输出约定）。
* :func:`parse_diagnosis_result` —— 从子 Agent 文本中提取并解析诊断结果
  （优先最后一段 json 代码块；无代码块时回退整体文本；可选 request_id
  关联校验）；失败统一抛出 :class:`DiagnosisParseError`。

设计依据：``docs/cloudagent-development-guide.md`` §5 与
``openspec/changes/add-investigation-protocol/design.md``（决策：不改
Runtime 消息协议，适配"最后一段文本"的现成回传通道）。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from cloudagent_ext.diagnosis.models import DiagnosisResult, InvestigationTask

logger = logging.getLogger(__name__)

__all__ = [
    "DiagnosisParseError",
    "render_result_contract",
    "build_investigation_prompt",
    "parse_diagnosis_result",
]

_RESULT_CONTRACT = """## 输出约定（统一诊断结果协议）

你的最终消息必须在末尾以一个 json 代码块结束；代码块内容为诊断结果的 JSON 对象，其余分析说明写在代码块之前。

```json
{"request_id": "<父请求标识>", "task_id": "<任务标识>", "agent_name": "<你的 Agent 名称>", "status": "success|partial|failed", "summary": "<结论摘要>", "findings": [], "evidence": [], "root_causes": [], "recommendations": [], "validation_plan": [], "limitations": [], "next_steps": []}
```

字段与规则：

- request_id：**非空字符串**，标识本次诊断请求——**必须回填派发提示中的「父请求标识」**；没有提供时才自行生成（建议格式 `<agent_name>-<YYYYMMDD-HHMMSS>`，例如 "sql-diagnosis-20261017-003000"）；**不得为空串或缺失**；
- task_id：派发提示提供了「任务标识」时**必须回填该值**（用于把结果归属到具体委派）；未提供时可省略；
- agent_name：**非空字符串**——你自己的 Agent 名称（例如 "sql-diagnosis"；不要填技能名或其他 Agent 的名字）；
- status：三态之一——success（完成预定分析）/ partial（部分完成且有重要限制）/ failed（无法完成）；
- findings：关键事实发现（字符串数组，只写观测事实）；
- evidence：证据数组，元素字段 evidence_id / source_type / source_ref / observation / observed_at / scope（对象，如 {"note": "<范围说明>"}）/ reliability（字符串，如 "high"）；**evidence_id MUST 使用 `<domain>:<seq>` 或 `ev:<domain>:<seq>` 命名空间形式（如 `ev:code:001`），以便按域追溯**；
- evidence 可选语义字段（缺失即空值，**恒输出**）：proves（这条证据直接证明的一句话命题，≤120 字）/ cannot_prove（它明确**不能**证明的事项，≤5 条）/ applicability（成立条件，对象，≤4 键；推荐 window / filter / tenant / key，键名自由，但"给出了条件"要求至少一个键的值为非空字符串）/ relation（与其它证据的关系数组，≤3 条，元素 {"kind": "consistent|complementary|conflict", "with": "<evidence_id>", "why": "<可选>"}）；relation 的 kind 为**建议取值**，非常规取值不报错；`with` 指向不存在的 evidence_id 或缺失时，该条关系会被**忽略并记入告警**，不影响整条结果；
- 可选字段的**类型写错**（如 cannot_prove 写成字符串、applicability 写成字符串）不会导致失败：按空值处理并记入告警，整条结果照常解析；只有必填四项（evidence_id/source_type/source_ref/observation）的类型或空值错误才会被拒绝；
- 语义分工：observation 记**看到什么**（仍须写全可核验事实），proves 记**能说明什么**——proves 是 observation 的浓缩，不是替代；
- 冲突判定建议流程（非强制）：① 时间窗对齐 → ② 条件对齐（键/租户/过滤）→ ③ 命题对齐；三项都对齐才建议声明 kind="conflict"；对不上应写 complementary 或不做声明。"无法判断是否冲突"不写入 kind（用 complementary 或不声明表达）；
- root_causes：候选根因数组，元素字段 description / confidence（0.0–1.0）/ supporting_evidence_ids / counter_evidence（字符串数组，可为空数组）/ confidence_rationale；
- supporting_evidence_ids 只能引用 evidence 中已存在的 evidence_id；
- next_steps：每条必须是**一个能用一次委派回答的、针对具体证据缺口的命题**（例如「orders 同步任务是否被触发」「Kafka 消费位点是否停滞」）；不得写「建议增加监控」「需要业务方确认」这类非取证项；单条不超过 200 字、不得包含换行；没有待查项时留空数组 []；
- 不输出没有证据支持的根因；置信度必须给出依据；
- JSON 保持紧凑，只保留必要证据与摘要。"""

_CODE_FENCE_RE = re.compile(r"```[ \t]*([A-Za-z0-9_+.-]*)[ \t]*\r?\n(.*?)```", re.DOTALL)


class DiagnosisParseError(ValueError):
    """诊断结果解析失败（统一错误类型，便于调用方捕获并降级处理）。"""


def render_result_contract() -> str:
    """返回统一输出约定文本（供委派提示与专业 Skill 复用）。"""
    return _RESULT_CONTRACT


def _render_json_block(value: dict[str, Any]) -> str:
    try:
        return "```json\n" + json.dumps(value, ensure_ascii=False, indent=2) + "\n```"
    except (TypeError, ValueError):
        return str(value)


def build_investigation_prompt(task: InvestigationTask, *, extra_context: str = "") -> str:
    """按统一协议生成委派给专业子 Agent 的调查提示。"""
    evidence_text = "、".join(task.required_evidence) if task.required_evidence else "（未明确指定）"
    sections = [
        "\n".join(
            [
                f"# 调查任务（{task.agent_type}）",
                "",
                f"- 任务标识：{task.task_id}",
                f"- 父请求标识：{task.parent_request_id}",
                f"- 调查目标：{task.objective}",
            ]
        ),
        "## 输入上下文\n\n" + _render_json_block(task.inputs),
        "## 所需证据\n\n" + evidence_text,
        "## 约束\n\n" + _render_json_block(task.constraints),
        "## 预算\n\n" + _render_json_block(task.budget),
    ]
    if extra_context and extra_context.strip():
        sections.append(extra_context.strip())
    sections.append(render_result_contract())
    return "\n\n".join(sections)


def _extract_result_payload(text: str) -> str:
    candidates: list[str] = []
    for match in _CODE_FENCE_RE.finditer(text):
        language = (match.group(1) or "").strip().lower()
        if language in ("", "json"):
            candidates.append(match.group(2))
    if candidates:
        return candidates[-1].strip()
    return text.strip()


def _normalize_payload(data: Any) -> Any:
    """对模型输出的两类已知书写变体做最小宽容归一化（变更 fix-diagnosis-field-types）。

    * ``evidence[].scope``：单值字符串 → ``{"note": <原值>}``；
    * ``root_causes[].counter_evidence``：单值字符串 → 字符串数组（空串 → 空数组）。

    仅这两类修正；其余字段交由统一数据模型严格校验。修正经 logger 留痕（不静默）。
    """

    if not isinstance(data, dict):
        return data
    repaired: list[str] = []

    evidence_list = data.get("evidence")
    if isinstance(evidence_list, list):
        for index, evidence in enumerate(evidence_list):
            if isinstance(evidence, dict) and isinstance(evidence.get("scope"), str):
                evidence["scope"] = {"note": evidence["scope"]}
                repaired.append(f"evidence[{index}].scope")

    causes = data.get("root_causes")
    if isinstance(causes, list):
        for index, cause in enumerate(causes):
            if isinstance(cause, dict) and isinstance(cause.get("counter_evidence"), str):
                value = cause["counter_evidence"].strip()
                cause["counter_evidence"] = [value] if value else []
                repaired.append(f"root_causes[{index}].counter_evidence")

    if repaired:
        logger.info("diagnosis payload normalized: %s", ", ".join(repaired))
    return data


_BACKSLASH = chr(92)
_JSON_WHITESPACE = " \t\r\n"


def _loads_with_quote_repair(payload: str) -> tuple[Any, int]:
    """解析 JSON；对"字符串内未转义的英文引号"做**有界**修复。

    真实故障（2026-10-25 CLI 实跑）：子代理在 ``observation`` 里直接写
    ``日志写了 "task aborted" ...``，JSON 在第一个内层引号处被提前闭合 →
    ``Expecting ',' delimiter`` → 整条结构化结果作废、缺口也收不到。

    修复策略：仅当错误是 ``Expecting ',' delimiter`` 且错误位置左侧（跳过空白）
    是一个**未被转义的引号**时，为该引号补反斜杠后重试；最多 20 次。
    任何其它错误形态一律不修，保持原有失败语义——**宁可不猜，也不改语义**。
    """

    try:
        return json.loads(payload), 0
    except json.JSONDecodeError:
        pass

    text = payload
    fixes = 0
    for _ in range(20):
        try:
            data = json.loads(text)
            return data, fixes
        except json.JSONDecodeError as exc:
            if exc.msg != "Expecting ',' delimiter" or exc.pos == 0:
                raise
            index = exc.pos - 1
            while index >= 0 and text[index] in _JSON_WHITESPACE:
                index -= 1
            if index < 0 or text[index] != '"':
                raise
            if index > 0 and text[index - 1] == _BACKSLASH:
                raise
            text = text[:index] + _BACKSLASH + text[index:]
            fixes += 1
    return json.loads(text), fixes


def parse_diagnosis_result(
    text: str,
    *,
    expected_request_id: str | None = None,
) -> DiagnosisResult:
    """从子 Agent 文本中提取并解析诊断结果。

    解析优先级：最后一段 json 代码块 > 整体文本；解析结果经统一数据模型
    严格校验（已知书写变体先做最小宽容归一化，见 ``_normalize_payload``）；
    ``expected_request_id`` 非空时校验结果与期望的关联标识一致。
    """
    if not isinstance(text, str) or not text.strip():
        raise DiagnosisParseError("diagnosis result text must be a non-empty string")
    payload = _extract_result_payload(text)
    try:
        data, repaired = _loads_with_quote_repair(payload)
    except json.JSONDecodeError as exc:
        raise DiagnosisParseError(f"failed to parse diagnosis result JSON: {exc}") from exc
    if repaired:
        logger.info("diagnosis payload repaired: %d unescaped quote(s) escaped", repaired)
    data = _normalize_payload(data)
    try:
        result = DiagnosisResult.from_dict(data)
    except ValueError as exc:
        raise DiagnosisParseError(f"invalid diagnosis result: {exc}") from exc
    if expected_request_id is not None and result.request_id != expected_request_id:
        raise DiagnosisParseError(
            "request_id mismatch: expected "
            f"{expected_request_id!r}, got {result.request_id!r}"
        )
    return result
