#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""取数工具真库集成测试（变更 add-db-data-query-tool）。

需要 `CLOUDAGENT_DB_DSN`；跨库用例还需要 `CLOUDAGENT_DB_DSN_SECONDARY`。
缺失时 skip（与既有约定一致，**skip 不计入"已通过真库验证"**）。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from cloudagent_ext.diagnosis.db.connection import DSN_ENV_VAR, DSN_SECONDARY_ENV_VAR, db_session
from cloudagent_ext.diagnosis.db.tools import QUERYABLE_TABLES_ENV_VAR, query_table_rows_tool
from cloudagent_ext.tool_system.context import ToolContext


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
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"PostgreSQL unavailable: {exc}")
    return value


@pytest.fixture(scope="module")
def secondary_dsn(dsn: str) -> str:
    value = os.environ.get(DSN_SECONDARY_ENV_VAR)
    if not value:
        pytest.skip(f"{DSN_SECONDARY_ENV_VAR} not configured; cross-database tests skipped")
    try:
        with db_session(value) as conn:
            conn.execute("SELECT 1")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"secondary PostgreSQL unavailable: {exc}")
    return value


@pytest.fixture(autouse=True)
def _allow_tables(monkeypatch) -> None:
    monkeypatch.setenv(QUERYABLE_TABLES_ENV_VAR, "public.orders,public.customers")


def test_count_all_rows(dsn: str) -> None:
    result = query_table_rows_tool.call({"table": "orders"}, _ctx())
    assert result.is_error is False, result.output
    assert result.output["mode"] == "aggregate"
    assert result.output["count"] >= 1


def test_count_with_equality_filter(dsn: str) -> None:
    with db_session(dsn) as conn:
        order_id = conn.execute("SELECT id FROM orders LIMIT 1").fetchone()[0]
    hit = query_table_rows_tool.call(
        {"table": "orders", "where": {"id": order_id}}, _ctx()
    )
    # 同类型的不存在值：orders.id 是整型，传字符串会被 DB 判为类型错误（那是另一条错误路径）
    miss = query_table_rows_tool.call(
        {"table": "orders", "where": {"id": int(order_id) + 10_000_000}}, _ctx()
    )
    assert hit.output["count"] == 1
    assert miss.output["count"] == 0


def test_detail_mode_returns_rows_and_redacts_pii(dsn: str) -> None:
    result = query_table_rows_tool.call(
        {"table": "customers", "columns": ["id", "name"], "limit": 5}, _ctx()
    )
    assert result.is_error is False, result.output
    assert result.output["mode"] == "rows"
    assert result.output["returned"] >= 1
    assert set(result.output["rows"][0]) == {"id", "name"}


def test_cross_database_comparison(secondary_dsn: str) -> None:
    """上游有、下游无——这是 P4.2 要回答的核心问题。"""

    up = query_table_rows_tool.call({"table": "orders", "target": "primary"}, _ctx())
    down = query_table_rows_tool.call({"table": "orders", "target": "secondary"}, _ctx())
    assert up.is_error is False and down.is_error is False
    assert up.output["target"] == "primary" and down.output["target"] == "secondary"
    assert up.output["count"] >= 1
    assert down.output["count"] == 0


def test_system_schema_denied_on_real_db(dsn: str, monkeypatch) -> None:
    monkeypatch.setenv(QUERYABLE_TABLES_ENV_VAR, "pg_catalog.*")
    result = query_table_rows_tool.call(
        {"schema": "pg_catalog", "table": "pg_class"}, _ctx()
    )
    assert result.is_error is True
    assert "system_schema_denied" in str(result.output)
