#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""元数据工具的 ``target`` 参数（变更 extend-db-tools-target）。

离线部分只验"参数确实透传到连接层"：未配 secondary 时必须报
``secondary_dsn_not_configured``，而不是静默查主库。真库部分在文件末尾。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from cloudagent_ext.diagnosis.db.connection import (
    DSN_ENV_VAR,
    DSN_SECONDARY_ENV_VAR,
    db_session,
)
from cloudagent_ext.diagnosis.db.tools import (
    QUERYABLE_TABLES_ENV_VAR,
    explain_sql_tool,
    get_indexes_tool,
    get_lock_info_tool,
    get_schema_tool,
    get_table_stats_tool,
    query_table_rows_tool,
)
from cloudagent_ext.tool_system.errors import ToolInputError
from cloudagent_ext.tool_system.schema_validation import validate_tool_input
from cloudagent_ext.tool_system.context import ToolContext


def _ctx() -> ToolContext:
    return ToolContext(workspace_root=Path.cwd())


TOOLS = (get_schema_tool, get_indexes_tool, get_table_stats_tool, query_table_rows_tool)


class TestTargetPlumbing:
    @pytest.mark.parametrize("tool", TOOLS, ids=lambda t: t.name)
    def test_secondary_requires_second_dsn(self, monkeypatch, tool) -> None:
        monkeypatch.setenv(DSN_ENV_VAR, "postgresql://u:p@127.0.0.1:1/none")
        monkeypatch.delenv(DSN_SECONDARY_ENV_VAR, raising=False)
        monkeypatch.setenv(QUERYABLE_TABLES_ENV_VAR, "public.orders")
        result = tool.call({"table": "orders", "target": "secondary"}, _ctx())
        assert result.is_error is True
        assert "secondary_dsn_not_configured" in str(result.output)

    @pytest.mark.parametrize("tool", TOOLS, ids=lambda t: t.name)
    def test_invalid_target_rejected(self, monkeypatch, tool) -> None:
        monkeypatch.setenv(DSN_ENV_VAR, "postgresql://u:p@127.0.0.1:1/none")
        monkeypatch.setenv(QUERYABLE_TABLES_ENV_VAR, "public.orders")
        result = tool.call({"table": "orders", "target": "replica"}, _ctx())
        assert result.is_error is True
        assert "invalid_target" in str(result.output)


@pytest.fixture(scope="module")
def dsn_pair() -> tuple[str, str]:
    primary = os.environ.get(DSN_ENV_VAR)
    secondary = os.environ.get(DSN_SECONDARY_ENV_VAR)
    if not primary or not secondary:
        pytest.skip("双 DSN 未配置；跨库元数据测试跳过")
    try:
        with db_session(primary) as conn:
            conn.execute("SELECT 1")
        with db_session(secondary) as conn:
            conn.execute("SELECT 1")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"PostgreSQL unavailable: {exc}")
    return primary, secondary


@pytest.mark.usefixtures("dsn_pair")
class TestTargetOnRealDatabases:
    def test_schema_on_secondary_lists_same_tables(self, monkeypatch) -> None:
        monkeypatch.setenv(QUERYABLE_TABLES_ENV_VAR, "public.orders")
        primary = get_schema_tool.call({"schema": "public", "target": "primary"}, _ctx())
        secondary = get_schema_tool.call({"schema": "public", "target": "secondary"}, _ctx())
        assert primary.is_error is False, primary.output
        assert secondary.is_error is False, secondary.output
        assert secondary.output["target"] == "secondary"
        assert set(secondary.output["tables"]) == set(primary.output["tables"])

    def test_table_stats_on_secondary_shows_empty_tables(self, monkeypatch) -> None:
        monkeypatch.setenv(QUERYABLE_TABLES_ENV_VAR, "public.orders")
        result = get_table_stats_tool.call(
            {"schema": "public", "table": "orders", "target": "secondary"}, _ctx()
        )
        assert result.is_error is False, result.output
        assert result.output["target"] == "secondary"

    def test_indexes_on_secondary_is_readable(self, monkeypatch) -> None:
        monkeypatch.setenv(QUERYABLE_TABLES_ENV_VAR, "public.orders")
        result = get_indexes_tool.call(
            {"schema": "public", "table": "orders", "target": "secondary"}, _ctx()
        )
        assert result.is_error is False, result.output
        assert result.output["target"] == "secondary"


PRIMARY_ONLY = (explain_sql_tool, get_lock_info_tool)


class TestPrimaryOnlyTools:
    """规范：explain_sql / get_lock_info MUST NOT 接受 target。

    机制上已由 ``additionalProperties: False`` + ``validate_tool_input`` 强制，
    这里把约束钉成测试——否则将来有人为"对称"补个 target 字段，现有用例全绿。
    """

    @pytest.mark.parametrize("tool", PRIMARY_ONLY, ids=lambda t: t.name)
    def test_schema_has_no_target(self, tool) -> None:
        assert "target" not in (tool.input_schema.get("properties") or {})

    @pytest.mark.parametrize("tool", PRIMARY_ONLY, ids=lambda t: t.name)
    def test_passing_target_is_rejected(self, tool) -> None:
        payload = {"target": "secondary"}
        if tool.name == "explain_sql":
            payload["sql"] = "SELECT 1"
        else:
            payload["min_wait_seconds"] = 0
        with pytest.raises(ToolInputError):
            validate_tool_input(tool.name, payload, tool.input_schema)

    def test_supported_tools_still_accept_target(self) -> None:
        """对照组：支持 target 的工具不应被同一条断言误伤。"""

        from cloudagent_ext.tool_system.schema_validation import validate_tool_input as _v

        for tool in TOOLS:
            _v(tool.name, {"table": "orders", "target": "secondary"}, tool.input_schema)
