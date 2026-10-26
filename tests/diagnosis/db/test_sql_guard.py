#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""``sql_guard`` 离线单测（不依赖数据库）。

覆盖规范场景：单条 SELECT 通过 / 写入与 DDL 拒绝 / 多语句拒绝 /
含数据修改的 WITH 拒绝 / 超长拒绝。
"""

from __future__ import annotations

import pytest

pytest.importorskip("sqlglot")

from cloudagent_ext.diagnosis.db.sql_guard import (  # noqa: E402
    MAX_SQL_LENGTH,
    SqlGuardError,
    validate_readonly_sql,
)


def test_accepts_simple_select() -> None:
    text = validate_readonly_sql("SELECT id FROM orders WHERE tenant_id = 1")
    assert text.startswith("SELECT")


def test_accepts_with_query() -> None:
    sql = "WITH t AS (SELECT id FROM orders) SELECT * FROM t"
    assert validate_readonly_sql(sql) == sql


def test_accepts_union_and_trailing_semicolon() -> None:
    sql = "SELECT 1 UNION SELECT 2;"
    assert validate_readonly_sql(sql) == sql


def test_accepts_values_query() -> None:
    validate_readonly_sql("VALUES (1), (2)")


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO orders (id) VALUES (1)",
        "UPDATE orders SET status = 'x' WHERE id = 1",
        "DELETE FROM orders WHERE id = 1",
        "CREATE TABLE t (id int)",
        "DROP TABLE orders",
        "TRUNCATE orders",
        "ALTER TABLE orders ADD COLUMN x int",
    ],
)
def test_rejects_write_and_ddl(sql: str) -> None:
    with pytest.raises(SqlGuardError):
        validate_readonly_sql(sql)


def test_rejects_multiple_statements() -> None:
    with pytest.raises(SqlGuardError, match="exactly one"):
        validate_readonly_sql("SELECT 1; SELECT 2")


def test_rejects_write_cte() -> None:
    with pytest.raises(SqlGuardError):
        validate_readonly_sql("WITH x AS (DELETE FROM orders RETURNING id) SELECT * FROM x")


def test_rejects_explain_prefix() -> None:
    with pytest.raises(SqlGuardError):
        validate_readonly_sql("EXPLAIN SELECT 1")


def test_rejects_blank() -> None:
    with pytest.raises(SqlGuardError, match="non-empty"):
        validate_readonly_sql("   ")


def test_rejects_overlong_sql() -> None:
    sql = "SELECT " + "1" * MAX_SQL_LENGTH
    with pytest.raises(SqlGuardError, match="exceeds limit"):
        validate_readonly_sql(sql)
