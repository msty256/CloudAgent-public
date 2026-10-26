#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""工具装配与限额离线单测（不依赖数据库）。

覆盖规范场景：默认注册表不含 DB 工具 / 装配后包含且只读 / 工具输入不含
连接参数（受控连接）/ 限额截断。
"""

from __future__ import annotations

import pytest

pytest.importorskip("psycopg")
pytest.importorskip("sqlglot")

from cloudagent_ext.diagnosis.db.tools import (  # noqa: E402
    MAX_RESULT_ROWS,
    _cap_bytes,
    _cap_rows,
    explain_sql_tool,
    get_indexes_tool,
    get_schema_tool,
    register_sql_db_tools,
)
from cloudagent_ext.tool_system.defaults import build_default_registry  # noqa: E402

_TOOL_NAMES = ("get_schema", "get_indexes", "explain_sql")


def test_default_registry_excludes_sql_db_tools() -> None:
    registry = build_default_registry(load_agent_tools=False)
    for name in _TOOL_NAMES:
        assert registry.get(name) is None


def test_register_sql_db_tools_adds_read_only_tools() -> None:
    registry = build_default_registry(load_agent_tools=False)
    register_sql_db_tools(registry)
    for name in _TOOL_NAMES:
        tool = registry.get(name)
        assert tool is not None
        assert tool.is_read_only({}) is True
        assert tool.is_concurrency_safe({}) is True


def test_tool_inputs_do_not_accept_connection_parameters() -> None:
    forbidden = {"dsn", "conninfo", "host", "port", "password", "user", "connection"}
    for tool in (get_schema_tool, get_indexes_tool, explain_sql_tool):
        properties = tool.input_schema.get("properties") or {}
        assert set(properties).isdisjoint(forbidden)


def test_cap_rows_truncates_to_limit() -> None:
    items, truncated = _cap_rows(list(range(MAX_RESULT_ROWS + 5)))
    assert len(items) == MAX_RESULT_ROWS
    assert truncated is True


def test_cap_rows_passthrough_when_small() -> None:
    items, truncated = _cap_rows([1, 2, 3])
    assert items == [1, 2, 3]
    assert truncated is False


def test_cap_bytes_marks_oversize_payload() -> None:
    payload = {"data": "x" * (300 * 1024)}
    capped = _cap_bytes(payload)
    assert capped["truncated"] is True
    assert "preview" in capped
