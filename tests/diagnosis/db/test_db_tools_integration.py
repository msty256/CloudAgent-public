#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""真库集成测试（``CLOUDAGENT_DB_DSN`` 缺失或不可达时自动 skip）。

覆盖规范场景：三工具 / 执行计划不执行目标查询 / 计划标注为预估 /
只读会话拒绝写入 / 语句超时 / 未配置连接给指引 / 不可用错误脱敏。
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

psycopg = pytest.importorskip("psycopg")
pytest.importorskip("sqlglot")

from cloudagent_ext.diagnosis.db.connection import (  # noqa: E402
    DSN_ENV_VAR,
    db_session,
)
from cloudagent_ext.diagnosis.db.tools import (  # noqa: E402
    explain_sql_tool,
    get_indexes_tool,
    get_schema_tool,
)
from cloudagent_ext.tool_system.context import ToolContext  # noqa: E402


def _ctx() -> ToolContext:
    return ToolContext(workspace_root=Path.cwd())


@pytest.fixture(scope="module")
def dsn() -> str:
    value = os.environ.get(DSN_ENV_VAR)
    if not value:
        pytest.skip(f"{DSN_ENV_VAR} not configured; integration tests skipped")
    try:
        with db_session(value) as conn:
            conn.execute("SELECT 1")
    except Exception as exc:  # noqa: BLE001 — 任意连接失败都退化为 skip
        pytest.skip(f"PostgreSQL unavailable: {exc}")
    return value


def test_get_schema_lists_tables(dsn: str) -> None:
    result = get_schema_tool.call({"schema": "public"}, _ctx())
    assert result.is_error is False
    tables = set(result.output["tables"])
    assert {"orders", "customers"} <= tables


def test_get_schema_returns_columns_and_primary_key(dsn: str) -> None:
    result = get_schema_tool.call({"table": "orders"}, _ctx())
    assert result.is_error is False
    names = {column["name"] for column in result.output["columns"]}
    assert {"id", "customer_id", "tenant_id", "created_at", "status", "amount"} <= names
    assert result.output["primary_key"] == ["id"]


def test_get_indexes_reports_region_index(dsn: str) -> None:
    result = get_indexes_tool.call({"table": "customers"}, _ctx())
    assert result.is_error is False
    by_name = {index["name"]: index for index in result.output["indexes"]}
    assert "idx_customers_region" in by_name
    assert by_name["idx_customers_region"]["method"] == "btree"


def test_get_indexes_orders_has_no_tenant_index(dsn: str) -> None:
    result = get_indexes_tool.call({"table": "orders"}, _ctx())
    assert result.is_error is False
    indexed_columns = {column for index in result.output["indexes"] for column in index["columns"]}
    assert "tenant_id" not in indexed_columns


def test_explain_returns_estimated_plan(dsn: str) -> None:
    result = explain_sql_tool.call({"sql": "SELECT * FROM orders WHERE tenant_id = 1"}, _ctx())
    assert result.is_error is False
    plan = result.output["plan"]
    assert any("Seq Scan on orders" in line for line in plan)
    assert "estimated plan only" in result.output["note"]
    assert all("actual time" not in line for line in plan)


def test_explain_does_not_execute_target_query(dsn: str) -> None:
    # 原手法 SELECT pg_sleep(3)（按耗时验证）已被 P2.7 危险函数防线拦截；
    # 改用"执行必错"表达式验证同一语义：该表达式实际执行必然触发
    # division by zero，而 EXPLAIN（无 ANALYZE）只返回预估计划。
    result = explain_sql_tool.call(
        {"sql": "SELECT amount / (amount - amount) FROM orders"}, _ctx()
    )
    assert result.is_error is False
    assert any("orders" in line for line in result.output["plan"])
    assert all("division by zero" not in line for line in result.output["plan"])


def test_explain_rejects_write_sql(dsn: str) -> None:
    result = explain_sql_tool.call({"sql": "DELETE FROM orders"}, _ctx())
    assert result.is_error is True
    assert result.output["error_type"] == "SqlGuardError"


def test_readonly_session_rejects_writes(dsn: str) -> None:
    with pytest.raises(psycopg.Error):
        with db_session(dsn) as conn:
            conn.execute("CREATE TABLE should_not_exist (id int)")


def test_statement_timeout_aborts_long_query(dsn: str) -> None:
    started = time.monotonic()
    with pytest.raises(psycopg.Error):
        with db_session(dsn) as conn:
            conn.execute("SELECT pg_sleep(6)")
    assert time.monotonic() - started < 15.0


def test_missing_dsn_gives_guidance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(DSN_ENV_VAR, raising=False)
    result = get_schema_tool.call({}, _ctx())
    assert result.is_error is True
    assert result.output["error_type"] == "DbConnectionError"
    assert DSN_ENV_VAR in result.output["message"]
    assert "config.json" in result.output["message"]


def test_unavailable_database_error_is_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(DSN_ENV_VAR, "postgresql://cloudagent_ro:leakme@127.0.0.1:59999/nope")
    result = get_schema_tool.call({}, _ctx())
    assert result.is_error is True
    assert result.output["error_type"] == "DbConnectionError"
    assert "leakme" not in result.output["message"]
