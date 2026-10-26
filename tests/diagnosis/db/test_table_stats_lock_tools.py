#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""expand-sql-diagnostic-db-tools：get_table_stats / get_lock_info 测试。

离线（无需 DSN）：参数校验、装配、注入拒绝。
真库（``CLOUDAGENT_DB_DSN`` 缺失或不可达时自动 skip）：统计查询、脱敏、
锁等待（advisory lock 双会话）。
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest

psycopg = pytest.importorskip("psycopg")
pytest.importorskip("sqlglot")

from cloudagent_ext.diagnosis.db.connection import DSN_ENV_VAR, db_session  # noqa: E402
from cloudagent_ext.diagnosis.db.tools import (  # noqa: E402
    get_lock_info_tool,
    get_table_stats_tool,
    register_sql_db_tools,
)
from cloudagent_ext.tool_system.context import ToolContext  # noqa: E402
from cloudagent_ext.tool_system.registry import ToolRegistry  # noqa: E402


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


# ---------------------------------------------------------------------------
# 离线：装配与参数校验（不触库）
# ---------------------------------------------------------------------------


def test_register_includes_new_tools() -> None:
    registry = ToolRegistry()
    register_sql_db_tools(registry)
    for name in (
        "get_schema",
        "get_indexes",
        "explain_sql",
        "get_table_stats",
        "get_lock_info",
        "query_table_rows",
    ):
        assert registry.get(name) is not None, name


def test_table_stats_rejects_missing_table() -> None:
    result = get_table_stats_tool.call({}, _ctx())
    assert result.is_error is True
    assert "invalid table" in str(result.output)


def test_table_stats_rejects_sql_injection_in_table() -> None:
    result = get_table_stats_tool.call({"table": "orders; DROP TABLE customers"}, _ctx())
    assert result.is_error is True
    assert "invalid table" in str(result.output)


def test_table_stats_rejects_non_public_schema() -> None:
    result = get_table_stats_tool.call({"table": "orders", "schema": "pg_catalog"}, _ctx())
    assert result.is_error is True
    assert "invalid schema" in str(result.output)


def test_lock_info_rejects_negative_wait() -> None:
    result = get_lock_info_tool.call({"min_wait_seconds": -1}, _ctx())
    assert result.is_error is True
    assert "must be >= 0" in str(result.output)


# ---------------------------------------------------------------------------
# 真库：统计查询与脱敏
# ---------------------------------------------------------------------------


def test_table_stats_orders_real_db(dsn: str) -> None:
    result = get_table_stats_tool.call({"table": "orders"}, _ctx())
    assert result.is_error is False
    out = result.output
    relation = out["relation"]
    assert relation["n_live_tup"] and relation["n_live_tup"] > 0
    assert relation["reltuples"] is not None
    assert relation["total_bytes"] and relation["total_bytes"] > 0
    assert out["columns"], "column statistics expected"
    # 脱敏：任何列值样本字段都不得出现
    blob = str(out)
    for banned in ("most_common_vals", "most_common_freqs", "histogram_bounds"):
        assert banned not in blob
    assert out["stats_never_analyzed"] is False


def test_table_stats_unknown_table(dsn: str) -> None:
    result = get_table_stats_tool.call({"table": "no_such_table_xyz"}, _ctx())
    assert result.is_error is True
    assert "not found" in str(result.output)


def test_lock_info_empty_is_explicit(dsn: str) -> None:
    # 单会话（本测试）通常无等待锁——返回明确的空结构而非错误
    result = get_lock_info_tool.call({}, _ctx())
    assert result.is_error is False
    out = result.output
    assert out["summary"]["waiting_count"] == len(out["waiting"])
    assert out["database"]
    # 脱敏：不得包含 query/usename 字段
    assert "query" not in out
    blob = str(out["waiting"])
    assert "SELECT" not in blob.upper()


def test_lock_info_detects_advisory_lock_wait(dsn: str) -> None:
    lock_key = 918273
    holder = psycopg.connect(dsn, autocommit=True)
    try:
        holder.execute("SELECT pg_advisory_lock(%s)", (lock_key,))
        waiter_done = threading.Event()

        def _waiter() -> None:
            try:
                with psycopg.connect(dsn, autocommit=True) as conn:
                    conn.execute("SELECT pg_advisory_lock(%s)", (lock_key,))
                    conn.execute("SELECT pg_advisory_unlock(%s)", (lock_key,))
            finally:
                waiter_done.set()

        thread = threading.Thread(target=_waiter, daemon=True)
        thread.start()
        observed = None
        for _ in range(100):  # 最多 ~10s
            result = get_lock_info_tool.call({}, _ctx())
            assert result.is_error is False
            if result.output["summary"]["waiting_count"] >= 1:
                observed = result.output
                break
            time.sleep(0.1)
        assert observed is not None, "waiter did not appear in get_lock_info"
        advisory = [w for w in observed["waiting"] if w["locktype"] == "advisory"]
        assert advisory, "advisory lock wait expected"
        assert advisory[0]["blocking_pids"], "blocking pids expected"
        assert observed["blocking"], "held locks of blockers expected"
        holder.execute("SELECT pg_advisory_unlock(%s)", (lock_key,))
        waiter_done.wait(timeout=5)
    finally:
        holder.close()
