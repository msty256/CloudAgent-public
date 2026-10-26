#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""SQL 诊断 Agent 的离线端到端委派验证（变更 add-sql-diagnostic-agent）。

复用 P1 的脚本化 provider 模式（tests/diagnosis/test_delegation_loop.py）：
主 Agent 委派 ``subagent_type="sql-diagnosis"`` → 子 Agent 按脚本回放
（含真实工具执行：只读校验拒绝 / DSN 未配置 / 连接不可达且脱敏）→ 统一
协议结果 → 解析与会话入账。

全程离线：无模型 API Key、无真实数据库（连接失败路径不依赖数据库在线）。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

pytest.importorskip("psycopg")
pytest.importorskip("sqlglot")

from cloudagent_ext.agent._bundled_agents import sql_diagnosis  # noqa: E402
from cloudagent_ext.diagnosis.db.connection import DSN_ENV_VAR  # noqa: E402
from cloudagent_ext.diagnosis.models import DiagnosisRequest  # noqa: E402
from cloudagent_ext.diagnosis.protocol import (  # noqa: E402
    DiagnosisParseError,
    build_investigation_prompt,
    parse_diagnosis_result,
)
from cloudagent_ext.diagnosis.session import InvestigationSession  # noqa: E402
from cloudagent_ext.providers.base import ChatResponse  # noqa: E402
from cloudagent_ext.query.agent_loop_compat import run_query_as_agent_loop  # noqa: E402
from cloudagent_ext.tool_system.context import ToolContext  # noqa: E402
from cloudagent_ext.tool_system.defaults import build_default_registry  # noqa: E402
from cloudagent_ext.tool_system.renderers import ToolEvent  # noqa: E402
from cloudagent_ext.types.messages import UserMessage  # noqa: E402

REQUEST_ID = "sql-agent-e2e-1"
_MODEL = "fake-sql-agent"
_USAGE = {"input_tokens": 3, "output_tokens": 3}


class _ScriptedProvider:
    """按调用顺序回放响应的脚本化 provider（同 P1 委派测试的离线设施）。"""

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
    subagent_type: str = "sql-diagnosis",
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


def _tool_use_response(tool_use_id: str, name: str, tool_input: dict) -> ChatResponse:
    return ChatResponse(
        content="",
        model=_MODEL,
        usage=dict(_USAGE),
        finish_reason="tool_use",
        tool_uses=[{"id": tool_use_id, "name": name, "input": tool_input}],
    )


def _subagent_payload(task_id: str, *, status: str = "success", limitations: list[str] | None = None) -> dict:
    payload = {
        "request_id": REQUEST_ID,
        "task_id": task_id,
        "agent_name": "sql-diagnosis",
        "skill_name": "sql-optimization",
        "status": status,
        "summary": "慢查询根因：orders.tenant_id 缺少可用索引",
        "findings": ["执行计划为全表扫描（Seq Scan on orders）"],
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
        "validation_plan": ["复跑 EXPLAIN 对比"],
        "limitations": list(limitations or []),
        "next_steps": [],
    }
    return payload


def _subagent_text(task_id: str, *, status: str = "success", limitations: list[str] | None = None) -> str:
    payload = json.dumps(_subagent_payload(task_id, status=status, limitations=limitations), ensure_ascii=False)
    return "调查完成，结论如下：\n\n```json\n" + payload + "\n```"


def _registry_with_db_tools(provider: _ScriptedProvider):
    # provider 经 build_default_registry 注入 Agent 工具（子 Agent 的 effective_provider）。
    registry = build_default_registry(provider=provider, load_agent_tools=False)
    assert sql_diagnosis.register_sql_diagnosis_tools(registry) is True
    return registry


def _run_loop(provider: _ScriptedProvider, context: ToolContext, events: list[ToolEvent]):
    registry = _registry_with_db_tools(provider)
    context.tool_registry = registry
    return asyncio.run(
        run_query_as_agent_loop(
            initial_messages=[UserMessage(content="请诊断订单查询变慢的问题")],
            provider=provider,
            tool_registry=registry,
            tool_context=context,
            system_prompt="You are the CloudAgent main agent (deterministic offline test mode).",
            max_turns=6,
            on_event=events.append,
        )
    )


def _session_and_prompt():
    session = InvestigationSession(DiagnosisRequest(request_id=REQUEST_ID, question="为什么订单查询变慢？"))
    task = session.delegate(
        "sql-diagnosis",
        "分析订单查询的执行计划并定位慢点",
        inputs={"sql": "select * from orders where tenant_id = ?"},
        required_evidence=["执行计划"],
    )
    prompt = build_investigation_prompt(task)
    return session, task, prompt


def test_sql_agent_delegation_success_roundtrip(tmp_path: Path) -> None:
    session, task, prompt = _session_and_prompt()
    provider = _ScriptedProvider(
        [
            _agent_tool_use_response("call_agent_sql_1", prompt),
            _text_response(_subagent_text(task.task_id)),
            _text_response("调查完成：已解析结构化结果并记录。"),
        ]
    )
    events: list[ToolEvent] = []
    result = _run_loop(provider, ToolContext(workspace_root=tmp_path), events)

    assert result.terminal is not None and result.terminal.reason == "completed"
    assert task.objective in str(provider.calls[1])  # 子 Agent 收到统一委派提示

    tool_results = [e for e in events if e.kind == "tool_result" and e.tool_use_id == "call_agent_sql_1"]
    assert tool_results and not tool_results[0].is_error
    parsed = parse_diagnosis_result(str(tool_results[0].tool_output), expected_request_id=REQUEST_ID)
    assert parsed.status == "success"
    assert parsed.agent_name == "sql-diagnosis"
    assert parsed.evidence[0].evidence_id == "ev-0001"

    session.record_result(parsed)
    assert session.entries[-1].status == "completed"  # 会话记账：任务已回传
    assert session.decide().reason == "success_recorded"


def test_sql_agent_partial_result_keeps_limitations(tmp_path: Path) -> None:
    session, task, prompt = _session_and_prompt()
    limitations = ["未获取到实际数据库连接，仅完成部分取证"]
    provider = _ScriptedProvider(
        [
            _agent_tool_use_response("call_agent_sql_2", prompt),
            _text_response(_subagent_text(task.task_id, status="partial", limitations=limitations)),
            _text_response("已记录部分结论与限制。"),
        ]
    )
    events: list[ToolEvent] = []
    _run_loop(provider, ToolContext(workspace_root=tmp_path), events)

    tool_results = [e for e in events if e.kind == "tool_result" and e.tool_use_id == "call_agent_sql_2"]
    parsed = parse_diagnosis_result(str(tool_results[0].tool_output), expected_request_id=REQUEST_ID)
    assert parsed.status == "partial"
    assert limitations[0] in parsed.limitations

    session.record_result(parsed)
    assert session.entries[-1].status == "completed"  # 会话记账：任务已回传（结果保留 partial）


def test_sql_agent_invalid_output_uses_existing_error_path(tmp_path: Path) -> None:
    session, task, prompt = _session_and_prompt()
    provider = _ScriptedProvider(
        [
            _agent_tool_use_response("call_agent_sql_3", prompt),
            _text_response("这里是分析过程，但没有按约定输出 json 代码块。"),
            _text_response("已记录本次失败，可追加调查。"),
        ]
    )
    events: list[ToolEvent] = []
    _run_loop(provider, ToolContext(workspace_root=tmp_path), events)

    tool_results = [e for e in events if e.kind == "tool_result" and e.tool_use_id == "call_agent_sql_3"]
    assert tool_results and not tool_results[0].is_error
    with pytest.raises(DiagnosisParseError):
        parse_diagnosis_result(str(tool_results[0].tool_output), expected_request_id=REQUEST_ID)

    session.record_failure(task.task_id, reason="子 Agent 输出未按约定包含结构化结果")
    assert session.entries[-1].status == "failed"


def test_sql_agent_tool_guard_rejection_degrades_safely(tmp_path: Path) -> None:
    """子 Agent 真实调用 explain_sql（写 SQL 被只读校验拒绝）→ 结构化错误 → 降级 partial。"""

    session, task, prompt = _session_and_prompt()
    provider = _ScriptedProvider(
        [
            _agent_tool_use_response("call_agent_sql_4", prompt),
            _tool_use_response("call_tool_4", "explain_sql", {"sql": "DELETE FROM orders"}),
            _text_response(
                _subagent_text(
                    task.task_id,
                    status="partial",
                    limitations=["只读校验拒绝：未能获取执行计划（不可执行写操作）"],
                )
            ),
            _text_response("已记录限制。"),
        ]
    )
    events: list[ToolEvent] = []
    _run_loop(provider, ToolContext(workspace_root=tmp_path), events)

    # 子 Agent 第 2 次模型调用看到了结构化工具错误（真实执行了只读校验）
    subagent_feed = str(provider.calls[2])
    assert "read-only" in subagent_feed

    tool_results = [e for e in events if e.kind == "tool_result" and e.tool_use_id == "call_agent_sql_4"]
    parsed = parse_diagnosis_result(str(tool_results[0].tool_output), expected_request_id=REQUEST_ID)
    assert parsed.status == "partial"  # 不伪成功
    assert parsed.limitations


def test_sql_agent_db_unavailable_without_dsn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """DSN 未配置：get_schema 返回配置指引错误 → 子 Agent 降级 partial、不崩溃。"""

    monkeypatch.delenv(DSN_ENV_VAR, raising=False)
    session, task, prompt = _session_and_prompt()
    provider = _ScriptedProvider(
        [
            _agent_tool_use_response("call_agent_sql_5", prompt),
            _tool_use_response("call_tool_5", "get_schema", {"table": "orders"}),
            _text_response(
                _subagent_text(
                    task.task_id,
                    status="partial",
                    limitations=["数据库连接未配置，无法获取 Schema 证据"],
                )
            ),
            _text_response("已记录限制并给出配置指引。"),
        ]
    )
    events: list[ToolEvent] = []
    result = _run_loop(provider, ToolContext(workspace_root=tmp_path), events)

    assert result.terminal is not None and result.terminal.reason == "completed"  # 不崩溃
    subagent_feed = str(provider.calls[2])
    assert f"{DSN_ENV_VAR} is not set" in subagent_feed  # 结构化错误附带配置指引

    tool_results = [e for e in events if e.kind == "tool_result" and e.tool_use_id == "call_agent_sql_5"]
    parsed = parse_diagnosis_result(str(tool_results[0].tool_output), expected_request_id=REQUEST_ID)
    assert parsed.status == "partial"


def test_sql_agent_db_unreachable_redacts_credentials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """不可达连接 + 含密码 DSN：错误消息脱敏；不泄露到模型输入与最终结果。"""

    secret = "supersecret-e2e"
    monkeypatch.setenv(DSN_ENV_VAR, f"postgresql://cloudagent_ro:{secret}@127.0.0.1:59999/nope")
    session, task, prompt = _session_and_prompt()
    provider = _ScriptedProvider(
        [
            _agent_tool_use_response("call_agent_sql_6", prompt),
            _tool_use_response("call_tool_6", "get_schema", {"schema": "public"}),
            _text_response(
                _subagent_text(
                    task.task_id,
                    status="partial",
                    limitations=["数据库不可达，未能获取证据（连接信息已脱敏）"],
                )
            ),
            _text_response("已记录限制。"),
        ]
    )
    events: list[ToolEvent] = []
    _run_loop(provider, ToolContext(workspace_root=tmp_path), events)

    subagent_feed = str(provider.calls[2])
    assert secret not in subagent_feed  # 喂给模型的工具错误已脱敏
    assert "***" in subagent_feed

    tool_results = [e for e in events if e.kind == "tool_result" and e.tool_use_id == "call_agent_sql_6"]
    assert secret not in str(tool_results[0].tool_output)  # 最终结果不泄露
    parsed = parse_diagnosis_result(str(tool_results[0].tool_output), expected_request_id=REQUEST_ID)
    assert parsed.status == "partial"
