#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Mock 委派闭环：FakeProvider 驱动的真实 Agent Loop 端到端测试。

覆盖变更 ``add-investigation-session`` 任务 2：把统一数据契约与调查协议放进
真实 Agent Loop（``run_query_as_agent_loop``）：构造任务 →
``build_investigation_prompt`` → Agent 工具委派 → Mock 子 Agent 按约定回传 →
``parse_diagnosis_result`` 解析 → 会话入账 → 停止决策；并覆盖无效回传与
无效委派的安全失败。全程离线（无模型密钥、无网络）。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from cloudagent_ext.diagnosis.models import DiagnosisRequest
from cloudagent_ext.diagnosis.protocol import (
    DiagnosisParseError,
    build_investigation_prompt,
    parse_diagnosis_result,
)
from cloudagent_ext.diagnosis.session import InvestigationSession
from cloudagent_ext.providers.base import ChatResponse
from cloudagent_ext.query.agent_loop_compat import run_query_as_agent_loop
from cloudagent_ext.tool_system.context import ToolContext
from cloudagent_ext.tool_system.defaults import build_default_registry
from cloudagent_ext.tool_system.renderers import ToolEvent
from cloudagent_ext.types.messages import UserMessage

REQUEST_ID = "diag-loop-1"
_USAGE = {"input_tokens": 3, "output_tokens": 3}
_MODEL = "fake-delegation-loop"


class _ScriptedProvider:
    """按调用顺序回放响应的 FakeProvider（chat_stream_response 不可用 → 回退 chat）。"""

    def __init__(self, responses: list[ChatResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[list] = []
        self.model = _MODEL

    def chat(self, messages, tools=None, **kwargs):
        self.calls.append(messages)
        index = len(self.calls) - 1
        if index < len(self._responses):
            return self._responses[index]
        return ChatResponse(
            content="(unexpected extra model call)",
            model=_MODEL,
            usage=dict(_USAGE),
            finish_reason="stop",
            tool_uses=None,
        )

    def chat_stream(self, messages, tools=None, **kwargs):
        return iter(())

    def chat_stream_response(self, messages, tools=None, **kwargs):
        raise NotImplementedError


def _text_response(text: str) -> ChatResponse:
    return ChatResponse(
        content=text,
        model=_MODEL,
        usage=dict(_USAGE),
        finish_reason="stop",
        tool_uses=None,
    )


def _agent_tool_use_response(
    tool_use_id: str,
    prompt: str,
    *,
    subagent_type: str = "general-purpose",
) -> ChatResponse:
    return ChatResponse(
        content="",
        model=_MODEL,
        usage=dict(_USAGE),
        finish_reason="tool_use",
        tool_uses=[
            {
                "id": tool_use_id,
                "name": "Agent",
                "input": {
                    "description": "sql investigation",
                    "prompt": prompt,
                    "subagent_type": subagent_type,
                },
            }
        ],
    )


def _subagent_payload(task_id: str) -> dict:
    return {
        "request_id": REQUEST_ID,
        "task_id": task_id,
        "agent_name": "sql-diagnosis",
        "skill_name": "sql-optimization",
        "status": "success",
        "summary": "慢查询根因：orders.tenant_id 缺少可用索引",
        "findings": ["执行计划为全表扫描"],
        "evidence": [
            {
                "evidence_id": "ev-0001",
                "source_type": "database",
                "source_ref": "tool_call:explain_sql#1",
                "observation": "Seq Scan on orders",
            }
        ],
        "root_causes": [
            {
                "description": "orders.tenant_id 缺少可用索引",
                "confidence": 0.7,
                "supporting_evidence_ids": ["ev-0001"],
            }
        ],
        "recommendations": ["为 tenant_id 建索引"],
        "validation_plan": ["复跑 EXPLAIN"],
        "limitations": [],
        "next_steps": [],
    }


def _subagent_text(task_id: str) -> str:
    payload = json.dumps(_subagent_payload(task_id), ensure_ascii=False)
    return "调查完成，结论如下：\n\n```json\n" + payload + "\n```"


def _run_loop(provider: _ScriptedProvider, context: ToolContext, events: list[ToolEvent]):
    registry = build_default_registry(provider=provider, load_agent_tools=False)
    context.tool_registry = registry
    return asyncio.run(
        run_query_as_agent_loop(
            initial_messages=[UserMessage(content="请分析订单查询变慢的原因")],
            provider=provider,
            tool_registry=registry,
            tool_context=context,
            system_prompt="You are the CloudAgent main agent (deterministic offline test mode).",
            max_turns=4,
            on_event=events.append,
        )
    )


def _request() -> DiagnosisRequest:
    return DiagnosisRequest(request_id=REQUEST_ID, question="为什么订单查询变慢？")


def test_delegation_loop_success_roundtrip(tmp_path: Path) -> None:
    session = InvestigationSession(_request())
    task = session.delegate(
        "sql-diagnosis",
        "分析订单查询的执行计划并定位慢点",
        inputs={"sql": "select * from orders where tenant_id = ?"},
        required_evidence=["执行计划"],
    )
    prompt = build_investigation_prompt(task)
    provider = _ScriptedProvider(
        [
            _agent_tool_use_response("call_agent_1", prompt),
            _text_response(_subagent_text(task.task_id)),
            _text_response("调查完成：已解析结构化结果并记录。"),
        ]
    )
    events: list[ToolEvent] = []
    result = _run_loop(provider, ToolContext(workspace_root=tmp_path), events)

    # 循环正常终止，调用序列符合预期（主 → 子 → 主）
    assert result.terminal is not None
    assert result.terminal.reason == "completed"
    assert len(provider.calls) == 3

    # 子 Agent 实际收到了统一委派提示（任务要素随提示进入委派消息）
    assert task.objective in str(provider.calls[1])
    assert "执行计划" in str(provider.calls[1])

    # 模型可见的文本通道可被解析还原（含证据引用）
    tool_results = [e for e in events if e.kind == "tool_result" and e.tool_use_id == "call_agent_1"]
    assert tool_results and not tool_results[0].is_error
    parsed = parse_diagnosis_result(str(tool_results[0].tool_output), expected_request_id=REQUEST_ID)
    assert parsed.status == "success"
    assert parsed.task_id == task.task_id
    assert parsed.evidence[0].evidence_id == "ev-0001"

    # 会话入账与停止决策
    session.record_result(parsed)
    assert session.entries[-1].status == "completed"
    decision = session.decide()
    assert decision.should_continue is False
    assert decision.reason == "success_recorded"


def test_delegation_loop_invalid_output_records_failure(tmp_path: Path) -> None:
    session = InvestigationSession(_request())
    task = session.delegate("sql-diagnosis", "分析订单查询的执行计划并定位慢点")
    prompt = build_investigation_prompt(task)
    provider = _ScriptedProvider(
        [
            _agent_tool_use_response("call_agent_2", prompt),
            _text_response("这里是分析过程，但没有按约定输出 json 代码块。"),
            _text_response("已记录本次失败，可追加调查。"),
        ]
    )
    events: list[ToolEvent] = []
    result = _run_loop(provider, ToolContext(workspace_root=tmp_path), events)

    assert result.terminal is not None
    assert result.terminal.reason == "completed"

    tool_result = [e for e in events if e.kind == "tool_result" and e.tool_use_id == "call_agent_2"]
    assert tool_result and not tool_result[0].is_error
    with pytest.raises(DiagnosisParseError):
        parse_diagnosis_result(str(tool_result[0].tool_output), expected_request_id=REQUEST_ID)

    session.record_failure(task.task_id, reason="子 Agent 输出未按约定包含结构化结果")
    assert session.entries[-1].status == "failed"
    decision = session.decide()
    assert decision.should_continue is True
    assert decision.reason == "budget_available"


def test_delegation_loop_invalid_agent_type_fails_safely(tmp_path: Path) -> None:
    provider = _ScriptedProvider(
        [
            _agent_tool_use_response(
                "call_agent_3",
                "分析一个未知领域的问题",
                subagent_type="nonexistent-agent",
            ),
            _text_response("委派失败已收到，循环正常结束。"),
        ]
    )
    events: list[ToolEvent] = []
    result = _run_loop(provider, ToolContext(workspace_root=tmp_path), events)

    assert result.terminal is not None
    assert result.terminal.reason == "completed"
    assert len(provider.calls) == 2  # 子 Agent 未被拉起

    failed = [e for e in events if e.kind == "tool_result" and e.tool_use_id == "call_agent_3"]
    assert failed and failed[0].is_error
