#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""日志→代码「至多追加一次」的脚本化 provider 测试（P3.6 tasks 4.3 / 二次审查 P2-2）。

用脚本化 provider 驱动主 Agent 循环：
  第 1 轮 Agent(log-diagnosis) → 第 2 轮 Agent(code-diagnosis) → 第 3 轮最终答复，
断言主 Agent 的 Agent tool 调用次数 <= 2（不出现第二轮追加）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from cloudagent_ext.providers.base import ChatResponse
from cloudagent_ext.diagnosis.session import DiagnosisSessionError
from cloudagent_ext.query.agent_loop_compat import run_query_as_agent_loop
from cloudagent_ext.tool_system.context import ToolContext
from cloudagent_ext.tool_system.defaults import build_default_registry
from cloudagent_ext.tool_system.renderers import ToolEvent
from cloudagent_ext.types.messages import UserMessage

_MODEL = "fake-handoff"
_USAGE = {"input_tokens": 3, "output_tokens": 3}


class _ScriptedProvider:
    """按调用顺序回放响应的脚本化 provider（与 test_sql_agent_delegation 同款最小版）。"""

    def __init__(self, responses: list[ChatResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[list] = []
        self.model = _MODEL

    def chat(self, messages, tools=None, **kwargs):
        self.calls.append(messages)
        index = len(self.calls) - 1
        if index < len(self._responses):
            return self._responses[index]
        return _text("(unexpected extra model call)")

    def chat_stream(self, messages, tools=None, **kwargs):
        return iter(())


def _text(text: str) -> ChatResponse:
    return ChatResponse(content=text, model=_MODEL, usage=dict(_USAGE), finish_reason="stop", tool_uses=None)


def _agent_call(tool_use_id: str, subagent_type: str, prompt: str) -> ChatResponse:
    return ChatResponse(
        content="",
        model=_MODEL,
        usage=dict(_USAGE),
        finish_reason="tool_use",
        tool_uses=[
            {
                "id": tool_use_id,
                "name": "Agent",
                "input": {"description": "diagnosis delegation", "prompt": prompt, "subagent_type": subagent_type},
            }
        ],
    )


def test_log_to_code_handoff_at_most_once(tmp_path: Path) -> None:
    provider = _ScriptedProvider(
        [
            # 主 Agent 第 1 轮：委派日志诊断
            _agent_call("call_log_1", "log-diagnosis", "请分析订单报错的日志，定位最早失败点"),
            # 子 Agent（log-diagnosis）第 1 轮：直接给结论
            _text("日志结论：首异常在 svc-b（NullPointerException），svc-a 为级联；建议追加一次 code-diagnosis"),
            # 主 Agent 第 2 轮：按结论追加一次代码诊断
            _agent_call("call_code_1", "code-diagnosis", "请检查 Repository.resolveTenant 的 tenant 配置读取"),
            # 子 Agent（code-diagnosis）第 1 轮：直接给结论
            _text("代码结论：Repository.resolveTenant 读取 tenant 配置时未判空"),
            # 主 Agent 第 3 轮：最终答复（不再追加第二轮）
            _text("最终结论：日志定位 svc-b，代码确认 resolveTenant 未判空；调查结束。"),
        ]
    )
    events: list[ToolEvent] = []
    registry = build_default_registry(provider=provider, load_agent_tools=False)
    context = ToolContext(workspace_root=tmp_path)
    context.tool_registry = registry

    result = asyncio.run(
        run_query_as_agent_loop(
            initial_messages=[UserMessage(content="订单报错，请先看日志，再判断是否需要代码调查")],
            provider=provider,
            tool_registry=registry,
            tool_context=context,
            system_prompt="You are the CloudAgent main agent (deterministic offline test mode).",
            max_turns=6,
            on_event=events.append,
        )
    )

    assert result.terminal is not None and result.terminal.reason == "completed"
    agent_calls = [e for e in events if e.kind == "tool_use" and e.tool_name == "Agent"]
    # 至多追加一次：log-diagnosis + code-diagnosis = 2 次，且没有第三轮
    assert len(agent_calls) == 2, f"expected <= 2 Agent delegations, got {len(agent_calls)}"
    agent_results = [
        e for e in events if e.kind == "tool_result" and e.tool_use_id in {"call_log_1", "call_code_1"}
    ]
    assert len(agent_results) == 2
    assert all(not e.is_error for e in agent_results)


def test_omitted_subagent_type_counts_under_routed_type(tmp_path: Path, monkeypatch) -> None:
    """P2-4：省略 subagent_type 时，预算键必须是路由后的真实类型（不是 'default'）。"""

    from cloudagent_ext.tool_system.defaults import build_default_registry
    from cloudagent_ext.tool_system.errors import ToolInputError
    from cloudagent_ext.tool_system.tools import agent as agent_tools

    captured: list[str] = []

    def _fake_begin(runtime, key, prompt):
        # 变更 wire-investigation-session：预算检查改由 begin_delegation 承担，
        # 这里用它作为"派发前中止"的注入点（原先挂在 _check_delegation_budget）。
        captured.append(key)
        raise DiagnosisSessionError("stop-within-budget-check")

    monkeypatch.setattr(agent_tools, "begin_delegation", _fake_begin)
    registry = build_default_registry(provider=None, load_agent_tools=False)
    tool = registry.get("Agent")

    # 含 Plan 路由短语、省略 subagent_type
    import pytest

    with pytest.raises(ToolInputError, match="stop-within-budget-check"):
        tool.call({"prompt": "make a plan for the migration"}, ToolContext(workspace_root=tmp_path))
    assert captured == ["Plan"], f"budget key must be routed type, got {captured}"
