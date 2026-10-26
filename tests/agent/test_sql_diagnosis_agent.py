#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""``sql-diagnosis`` bundled Agent 的契约测试（变更 add-sql-diagnostic-agent）。

覆盖：注册与发现 / 系统提示（含统一协议与关键职责）/ 工具白名单由运行时
强制（装配前与装配后两态）/ 装配入口幂等 / 默认注册表不受影响。
离线测试：不依赖数据库与模型 API。
"""

from __future__ import annotations

from cloudagent_ext.agent._bundled_agents import sql_diagnosis
from cloudagent_ext.agent.agent_tool_utils import resolve_agent_tools
from cloudagent_ext.agent.registry import AgentRegistry
from cloudagent_ext.diagnosis.protocol import render_result_contract
from cloudagent_ext.tool_system.defaults import build_default_registry

_DB_TOOLS = ("get_schema", "get_indexes", "explain_sql")


def _agent():
    agent = AgentRegistry.find("sql-diagnosis")
    assert agent is not None, "sql-diagnosis 未注册"
    return agent


def test_registered_and_discoverable() -> None:
    agent = _agent()
    assert agent.agent_type == "sql-diagnosis"
    assert agent.when_to_use and "SQL" in agent.when_to_use
    assert agent.background is False
    assert agent.tools is not None  # 显式白名单（非通配）


def test_system_prompt_includes_contract_and_duties() -> None:
    prompt = _agent().get_system_prompt()
    assert render_result_contract().strip() in prompt
    for keyword in ("sql-optimization", "get_schema", "get_indexes", "explain_sql", "read-only"):
        assert keyword in prompt


def test_tool_allowlist_enforced_before_assembly() -> None:
    agent = _agent()
    registry = build_default_registry(load_agent_tools=False)
    resolved = resolve_agent_tools(agent, registry.list_tools(), is_async=False)
    names = {tool.name for tool in resolved.resolved_tools}
    assert "Skill" in names
    assert "Bash" in names  # 白名单惯例（仅限只读本地检查，见提示约束）
    assert set(_DB_TOOLS).isdisjoint(names)  # 未装配 → 不可见（不因声明而虚构可用）
    assert {"Edit", "Write", "NotebookEdit", "Agent"}.isdisjoint(names)


def test_tool_allowlist_enforced_after_assembly() -> None:
    agent = _agent()
    registry = build_default_registry(load_agent_tools=False)
    assert sql_diagnosis.register_sql_diagnosis_tools(registry) is True
    resolved = resolve_agent_tools(agent, registry.list_tools(), is_async=False)
    names = {tool.name for tool in resolved.resolved_tools}
    assert set(_DB_TOOLS) <= names
    assert "Skill" in names
    assert "Bash" in names
    assert {"Edit", "Write", "NotebookEdit", "Agent"}.isdisjoint(names)


def test_register_sql_diagnosis_tools_is_idempotent() -> None:
    registry = build_default_registry(load_agent_tools=False)
    assert sql_diagnosis.register_sql_diagnosis_tools(registry) is True
    assert sql_diagnosis.register_sql_diagnosis_tools(registry) is True  # no-op
    for name in _DB_TOOLS:
        assert registry.get(name) is not None


def test_default_registry_has_no_db_tools() -> None:
    registry = build_default_registry(load_agent_tools=False)
    for name in _DB_TOOLS:
        assert registry.get(name) is None


def test_registration_via_runtime_entrypoint() -> None:
    """运行时注册入口（ensure_bundled_agents_registered）必须覆盖 sql-diagnosis。"""

    from cloudagent_ext.agent import ensure_bundled_agents_registered

    ensure_bundled_agents_registered()
    assert AgentRegistry.find("sql-diagnosis") is not None
