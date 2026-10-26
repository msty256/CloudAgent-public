#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""``code-diagnosis`` bundled Agent 的契约测试（变更 add-code-analysis-domain，P3.2）。

覆盖：注册与发现（含与 code-reviewer 的路由区分）/ 系统提示（统一协议 +
静态风险红线）/ 工具白名单由运行时强制（装配前/后两态）/ 装配幂等 /
默认注册表不受影响。离线测试：不依赖外部服务。
"""

from __future__ import annotations

from cloudagent_ext.agent._bundled_agents import code_diagnosis
from cloudagent_ext.agent.agent_tool_utils import resolve_agent_tools
from cloudagent_ext.agent.registry import AgentRegistry
from cloudagent_ext.diagnosis.protocol import render_result_contract
from cloudagent_ext.tool_system.defaults import build_default_registry

_CODE_TOOLS = ("find_symbol", "find_references")


def _agent():
    agent = AgentRegistry.find("code-diagnosis")
    assert agent is not None, "code-diagnosis 未注册"
    return agent


def test_registered_and_discoverable() -> None:
    agent = _agent()
    assert agent.agent_type == "code-diagnosis"
    assert agent.when_to_use and "code" in agent.when_to_use.lower()
    # P2-3：与 code-reviewer 的路由区分必须写在 when_to_use（不是代码评审）
    assert "NOT code review" in agent.when_to_use
    assert agent.background is False
    assert agent.tools is not None  # 显式白名单（非通配）


def test_system_prompt_includes_contract_and_duties() -> None:
    prompt = _agent().get_system_prompt()
    assert render_result_contract().strip() in prompt
    for keyword in ("code-analysis", "find_symbol", "find_references", "read-only"):
        assert keyword in prompt
    # P2-4 红线（提示词层）
    assert "suspected" in prompt
    assert "不得表述为已发生" in prompt or "never claim" in prompt


def test_tool_allowlist_enforced_before_assembly() -> None:
    agent = _agent()
    registry = build_default_registry(load_agent_tools=False)
    resolved = resolve_agent_tools(agent, registry.list_tools(), is_async=False)
    names = {tool.name for tool in resolved.resolved_tools}
    assert "Skill" in names
    assert "Read" in names
    assert "Grep" in names
    assert set(_CODE_TOOLS).isdisjoint(names)  # 未装配 → 不可见
    assert {"Edit", "Write", "NotebookEdit", "Agent"}.isdisjoint(names)


def test_tool_allowlist_enforced_after_assembly() -> None:
    agent = _agent()
    registry = build_default_registry(load_agent_tools=False)
    assert code_diagnosis.register_code_diagnosis_tools(registry) is True
    resolved = resolve_agent_tools(agent, registry.list_tools(), is_async=False)
    names = {tool.name for tool in resolved.resolved_tools}
    assert set(_CODE_TOOLS) <= names
    assert {"Edit", "Write", "NotebookEdit", "Agent"}.isdisjoint(names)


def test_register_code_diagnosis_tools_is_idempotent() -> None:
    registry = build_default_registry(load_agent_tools=False)
    assert code_diagnosis.register_code_diagnosis_tools(registry) is True
    assert code_diagnosis.register_code_diagnosis_tools(registry) is True  # no-op
    for name in _CODE_TOOLS:
        assert registry.get(name) is not None


def test_default_registry_has_no_code_tools() -> None:
    registry = build_default_registry(load_agent_tools=False)
    for name in _CODE_TOOLS:
        assert registry.get(name) is None
