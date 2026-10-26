#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""``log-diagnosis`` bundled Agent 的契约测试（P3.3）。

覆盖：注册（when_to_use 说明非聚合）/ 系统提示（协议 + 红线）/ 工具白名单
（装配前/后两态）/ 装配幂等 / 默认注册表不含。
"""

from __future__ import annotations

from cloudagent_ext.agent._bundled_agents import log_diagnosis
from cloudagent_ext.agent.agent_tool_utils import resolve_agent_tools
from cloudagent_ext.agent.registry import AgentRegistry
from cloudagent_ext.diagnosis.protocol import render_result_contract
from cloudagent_ext.tool_system.defaults import build_default_registry

_LOG_TOOLS = ("search_logs", "get_log_context", "parse_stack_trace", "correlate_events")


def _agent():
    agent = AgentRegistry.find("log-diagnosis")
    assert agent is not None, "log-diagnosis 未注册"
    return agent


def test_registered_and_discoverable() -> None:
    agent = _agent()
    assert agent.agent_type == "log-diagnosis"
    assert agent.when_to_use and "log" in agent.when_to_use.lower()
    assert "NOT for log aggregation" in agent.when_to_use
    assert agent.tools is not None


def test_system_prompt_includes_contract_and_red_lines() -> None:
    prompt = _agent().get_system_prompt()
    assert render_result_contract().strip() in prompt
    for keyword in ("log-analysis", "search_logs", "correlate_events", "read-only"):
        assert keyword in prompt
    assert "NOT the root cause" in prompt
    assert "limitations" in prompt


def test_tool_allowlist_before_assembly() -> None:
    agent = _agent()
    registry = build_default_registry(load_agent_tools=False)
    resolved = resolve_agent_tools(agent, registry.list_tools(), is_async=False)
    names = {tool.name for tool in resolved.resolved_tools}
    assert "Skill" in names
    assert set(_LOG_TOOLS).isdisjoint(names)
    assert {"Edit", "Write", "NotebookEdit", "Agent"}.isdisjoint(names)


def test_tool_allowlist_after_assembly() -> None:
    agent = _agent()
    registry = build_default_registry(load_agent_tools=False)
    assert log_diagnosis.register_log_diagnosis_tools(registry) is True
    resolved = resolve_agent_tools(agent, registry.list_tools(), is_async=False)
    names = {tool.name for tool in resolved.resolved_tools}
    assert set(_LOG_TOOLS) <= names


def test_provision_is_idempotent() -> None:
    registry = build_default_registry(load_agent_tools=False)
    assert log_diagnosis.register_log_diagnosis_tools(registry) is True
    assert log_diagnosis.register_log_diagnosis_tools(registry) is True
    for name in _LOG_TOOLS:
        assert registry.get(name) is not None


def test_default_registry_has_no_log_tools() -> None:
    registry = build_default_registry(load_agent_tools=False)
    for name in _LOG_TOOLS:
        assert registry.get(name) is None
