#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""SQL 只读白名单校验（sqlglot AST；变更 add-sql-diagnostic-db-tools 决策 2/4）。

规则（只读三重防线的第 ① 层）：

* 必须能解析为**恰好一条**语句；
* 顶层必须是只读查询表达式（``SELECT`` / ``UNION`` / ``INTERSECT`` /
  ``EXCEPT`` / ``VALUES`` / 括号子查询）；
* ``WITH`` 的每个 CTE 内不得包含写操作（``INSERT`` / ``UPDATE`` /
  ``DELETE`` 等一律拒绝——PostgreSQL 的数据修改 CTE 也在拦截面内）；
* 查询不得调用**危险函数**（文件/大对象读写、睡眠、外联、会话终止类——
  变更 harden-sql-diagnostic-safety 加固；不依赖数据库侧权限兜底）；
* SQL 长度不超过 ``MAX_SQL_LENGTH``（20,000 字符）。

失败统一抛 :class:`SqlGuardError`（``ValueError`` 子类），消息含可定位原因。
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp

__all__ = ["MAX_SQL_LENGTH", "DISALLOWED_FUNCTIONS", "SqlGuardError", "validate_readonly_sql"]

MAX_SQL_LENGTH: int = 20_000

_QUERY_EXPRESSIONS: tuple[type[exp.Expression], ...] = (
    exp.Select,
    exp.Union,
    exp.Intersect,
    exp.Except,
    exp.Values,
    exp.Subquery,
)

# 危险函数集（harden-sql-diagnostic-safety 决策 2）：只读查询中无正当诊断用途
# 且可造成越权/资源危害的函数。保守子集——仅收录明确危险项，避免误杀诊断场景。
DISALLOWED_FUNCTIONS: frozenset[str] = frozenset(
    {
        # 文件 / 大对象读写
        "pg_read_file",
        "pg_read_binary_file",
        "pg_ls_dir",
        "lo_import",
        "lo_export",
        # 资源消耗
        "pg_sleep",
        "pg_sleep_for",
        "pg_sleep_until",
        # 外联 / 会话终止
        "dblink",
        "dblink_exec",
        "pg_terminate_backend",
        "pg_cancel_backend",
    }
)


class SqlGuardError(ValueError):
    """SQL 只读白名单校验失败。"""


def validate_readonly_sql(
    sql: str,
    *,
    max_length: int = MAX_SQL_LENGTH,
    dialect: str = "postgres",
) -> str:
    """校验并返回规范化（strip）后的 SQL 文本；失败抛 :class:`SqlGuardError`。"""
    if not isinstance(sql, str) or not sql.strip():
        raise SqlGuardError("sql must be a non-empty string")
    text = sql.strip()
    if len(text) > max_length:
        raise SqlGuardError(f"sql length {len(text)} exceeds limit {max_length}")
    try:
        statements = sqlglot.parse(text, read=dialect)
    except Exception as exc:  # sqlglot 解析异常（ParseError 等）
        raise SqlGuardError(f"sql parse failed: {exc}") from exc
    parsed = [statement for statement in statements if statement is not None]
    if len(parsed) != 1:
        raise SqlGuardError(f"expected exactly one statement, got {len(parsed)}")
    statement = parsed[0]
    if not isinstance(statement, _QUERY_EXPRESSIONS):
        raise SqlGuardError(
            "only read-only queries are allowed "
            f"(SELECT/UNION/INTERSECT/EXCEPT/VALUES), got {type(statement).__name__}"
        )
    _reject_write_ctes(statement)
    _reject_dangerous_functions(statement)
    return text


def _reject_write_ctes(statement: exp.Expression) -> None:
    """检查语法树中的每个 CTE（含嵌套 WITH）都必须只读。

    使用 ``find_all(exp.CTE)`` 而不是按 ``with`` 参数键取：不同 sqlglot
    版本对 WITH 子句的存储键不同（``with`` / ``with_``），遍历方式与版本无关，
    并且会连带检查嵌套子查询中的 CTE。
    """
    for cte in statement.find_all(exp.CTE):
        inner = cte.this
        if inner is None or not isinstance(inner, _QUERY_EXPRESSIONS):
            alias = cte.alias or "<unnamed>"
            raise SqlGuardError(f"WITH clause contains a non-read-only CTE: {alias}")


def _function_name(node: exp.Expression) -> str | None:
    """提取函数调用节点的规范化名称（未识别函数为 Anonymous；标准函数走 sql_name）。"""

    if isinstance(node, exp.Anonymous):
        return str(node.this)
    if isinstance(node, exp.Func):
        try:
            return node.sql_name()
        except (AttributeError, ValueError):  # pragma: no cover - 防御性
            return None
    return None


def _reject_dangerous_functions(statement: exp.Expression) -> None:
    """拒绝危险函数调用（大小写不敏感；兼容 ``pg_catalog.`` 前缀写法）。"""

    for node in statement.walk():
        name = _function_name(node)
        if not name:
            continue
        bare = name.rsplit(".", 1)[-1].strip('"').casefold()
        if bare in DISALLOWED_FUNCTIONS:
            raise SqlGuardError(f"sql calls a disallowed function: {name}")
