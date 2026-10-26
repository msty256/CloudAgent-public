#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""只读 DB 工具集与按需装配（变更 add-sql-diagnostic-db-tools / expand-sql-diagnostic-db-tools）。

* ``get_schema`` / ``get_indexes`` / ``explain_sql`` / ``get_table_stats`` /
  ``get_lock_info`` 通过 ``build_tool`` 工厂构建；
* **按需装配**：``register_sql_db_tools(registry)`` 显式注册——默认工具注册表
  不包含它们；
* 失败（校验拒绝 / 连接不可用 / 权限不足 / 超时）返回**结构化错误**
  （``is_error=True`` 的 ToolResult，含 error_type 与打码后的 message）；
* 结果限额：行数默认 200、单结果集字节上限 256KB，超限截断并置 ``truncated``。
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

import psycopg

from cloudagent_ext.tool_system.build_tool import Tool, build_tool
from cloudagent_ext.tool_system.context import ToolContext
from cloudagent_ext.tool_system.protocol import ToolResult

from cloudagent_ext.diagnosis.db import postgres
from cloudagent_ext.diagnosis.db.connection import (
    DbConnectionError,
    db_session,
    resolve_dsn,
)
from cloudagent_ext.diagnosis.db.sql_guard import SqlGuardError, validate_readonly_sql

__all__ = [
    "MAX_RESULT_ROWS",
    "MAX_RESULT_BYTES",
    "MAX_QUERY_ROWS",
    "QUERYABLE_TABLES_ENV_VAR",
    "get_schema_tool",
    "get_indexes_tool",
    "explain_sql_tool",
    "get_table_stats_tool",
    "get_lock_info_tool",
    "query_table_rows_tool",
    "register_sql_db_tools",
]

MAX_RESULT_ROWS: int = 200
MAX_RESULT_BYTES: int = 256 * 1024

_ALLOWED_SCHEMAS = frozenset({"public"})
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")

_EXPLAIN_NOTE = "estimated plan only — 优化器预估计划，不含实际执行数据（无 ANALYZE）"

# ---------------------------------------------------------------------------
# 取数工具（变更 add-db-data-query-tool）
# ---------------------------------------------------------------------------
QUERYABLE_TABLES_ENV_VAR: str = "CLOUDAGENT_DB_QUERYABLE_TABLES"
# 明细默认返回行数；硬上限复用 MAX_RESULT_ROWS（200）。两者语义不同，勿合并。
MAX_QUERY_ROWS: int = 20

# 系统 schema 永久拒绝：白名单也不能开。
# 用「前缀 + 精确名」而不是精确集合——PostgreSQL 的系统 schema 有变体
# （pg_temp_N、pg_toast_temp_N），精确集合挡不住，实测可被白名单打开。
_SYSTEM_SCHEMA_PREFIXES: tuple[str, ...] = ("pg_",)
_SYSTEM_SCHEMAS_EXACT = frozenset({"information_schema"})


def _is_system_schema(name: str) -> bool:
    """``pg_`` 前缀是 PostgreSQL 保留给系统对象的；用户业务 schema 不应以它开头。"""

    return name in _SYSTEM_SCHEMAS_EXACT or name.startswith(_SYSTEM_SCHEMA_PREFIXES)

# 凭证类：既不能返回，也不能作过滤键（防「COUNT=1 即确认存在」的探测）。
_CREDENTIAL_COLUMNS = frozenset(
    {
        "password",
        "passwd",
        "pwd",
        "password_hash",
        "secret",
        "client_secret",
        "token",
        "access_token",
        "refresh_token",
        "api_key",
        "apikey",
        "access_key",
        "secret_key",
        "private_key",
    }
)
# PII：允许作过滤键（业务常用：按手机号查订单），但返回时脱敏。
_PII_COLUMNS = frozenset(
    {"phone", "mobile", "tel", "id_card", "id_no", "email", "address", "bank_card"}
)



def _cap_rows(items: list[Any], limit: int = MAX_RESULT_ROWS) -> tuple[list[Any], bool]:
    if len(items) > limit:
        return items[:limit], True
    return items, False


def _cap_bytes(payload: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    if len(encoded) <= MAX_RESULT_BYTES:
        return payload
    return {
        "truncated": True,
        "note": f"result exceeded {MAX_RESULT_BYTES} bytes and was cut",
        "preview": encoded[:4096].decode("utf-8", errors="ignore"),
    }


def _error_result(name: str, exc: Exception) -> ToolResult:
    return ToolResult(
        name=name,
        output={"error_type": type(exc).__name__, "message": str(exc)},
        is_error=True,
    )


def _target_of(tool_input: dict[str, Any]) -> str:
    """取 ``target`` 枚举值（默认 primary）；非法值由 resolve_dsn 抛 invalid_target。"""

    return str(tool_input.get("target") or "primary").strip().lower()


def _readonly_tool_permissions(tool_input: dict[str, Any], _context: Any) -> Any:
    """诊断只读工具的权限决策：显式允许（fix-sql-diagnosis-tool-provisioning）。

    三个 DB 工具此前未声明权限处理——在 ask 链路上默认落入"需要询问"，
    于 dontAsk（诊断会话语义）下被执行前拒绝（P2.7 测试因沿 unknown-tool
    路径而假通过；P2.8-fix 的硬断言暴露）。工具自身持三重只读防线
    （SQL guard / 只读事务 / 只读账号），权限层显式放行与其安全语义一致。
    """

    from cloudagent_ext.permissions.types import (
        OtherDecisionReason,
        PermissionAllowDecision,
    )

    return PermissionAllowDecision(
        behavior="allow",
        updated_input=tool_input,
        decision_reason=OtherDecisionReason(
            reason="read-only DB tool (triple read-only guards: sql guard / read-only tx / read-only role)"
        ),
    )


def _validate_schema(raw: Any) -> str:
    schema = str(raw or "public").strip()
    if schema not in _ALLOWED_SCHEMAS:
        raise ValueError(f"invalid schema: only {sorted(_ALLOWED_SCHEMAS)} is allowed")
    return schema


def _validate_identifier(raw: Any, field: str) -> str:
    text = str(raw or "").strip()
    if not _IDENTIFIER_RE.match(text):
        raise ValueError(
            f"invalid {field}: plain identifier required (letters/digits/underscore, "
            "starting with a letter or underscore)"
        )
    return text


def _get_schema_call(tool_input: dict[str, Any], _context: ToolContext) -> ToolResult:
    name = "get_schema"
    schema = str(tool_input.get("schema") or "public")
    table = tool_input.get("table")
    target = _target_of(tool_input)
    try:
        with db_session(resolve_dsn(target)) as conn:
            result = postgres.fetch_schema(conn, schema=schema, table=table)
    except (DbConnectionError, LookupError, psycopg.Error) as exc:
        return _error_result(name, exc)
    result["target"] = target
    tables = result.get("tables")
    if isinstance(tables, list):
        capped, truncated = _cap_rows(tables)
        result["tables"] = capped
        if truncated:
            result["truncated"] = True
    return ToolResult(name=name, output=_cap_bytes(result))


def _get_indexes_call(tool_input: dict[str, Any], _context: ToolContext) -> ToolResult:
    name = "get_indexes"
    schema = str(tool_input.get("schema") or "public")
    table = tool_input.get("table")
    target = _target_of(tool_input)
    try:
        with db_session(resolve_dsn(target)) as conn:
            rows = postgres.fetch_indexes(conn, schema=schema, table=table)
    except (DbConnectionError, psycopg.Error) as exc:
        return _error_result(name, exc)
    capped, truncated = _cap_rows(rows)
    payload: dict[str, Any] = {"schema": schema, "target": target, "indexes": capped}
    if table is not None:
        payload["table"] = table
    if truncated:
        payload["truncated"] = True
    return ToolResult(name=name, output=_cap_bytes(payload))


def _explain_sql_call(tool_input: dict[str, Any], _context: ToolContext) -> ToolResult:
    name = "explain_sql"
    try:
        safe_sql = validate_readonly_sql(tool_input.get("sql"))
    except SqlGuardError as exc:
        return _error_result(name, exc)
    try:
        with db_session() as conn:
            plan = postgres.explain_sql(conn, safe_sql)
    except (DbConnectionError, psycopg.Error) as exc:
        return _error_result(name, exc)
    capped, truncated = _cap_rows(plan)
    payload: dict[str, Any] = {"sql": safe_sql, "plan": capped, "note": _EXPLAIN_NOTE}
    if truncated:
        payload["truncated"] = True
    return ToolResult(name=name, output=_cap_bytes(payload))


get_schema_tool: Tool = build_tool(
    name="get_schema",
    input_schema={
        "type": "object",
        "properties": {
            "schema": {"type": "string", "description": "Schema name (default: public)"},
            "table": {"type": "string", "description": "Table name; omit to list tables"},
            "target": {
                "type": "string",
                "enum": ["primary", "secondary"],
                "description": "Which pre-configured read-only database to inspect (never a host/DSN)",
            },
        },
        "additionalProperties": False,
    },
    call=_get_schema_call,
    prompt="Read table/column metadata from the configured read-only PostgreSQL database.",
    description="Get the table list, or one table's columns (name/type/nullable/default) and primary key.",
    is_read_only=lambda _input: True,
    is_concurrency_safe=lambda _input: True,
    check_permissions=_readonly_tool_permissions,
)

get_indexes_tool: Tool = build_tool(
    name="get_indexes",
    input_schema={
        "type": "object",
        "properties": {
            "schema": {"type": "string", "description": "Schema name (default: public)"},
            "table": {"type": "string", "description": "Table name; omit for all tables in schema"},
            "target": {
                "type": "string",
                "enum": ["primary", "secondary"],
                "description": "Which pre-configured read-only database to inspect (never a host/DSN)",
            },
        },
        "additionalProperties": False,
    },
    call=_get_indexes_call,
    prompt="Read index definitions and usage statistics from the configured read-only PostgreSQL database.",
    description="Get index definitions (columns/unique/method) and usage statistics (idx_scan/idx_tup_read).",
    is_read_only=lambda _input: True,
    is_concurrency_safe=lambda _input: True,
    check_permissions=_readonly_tool_permissions,
)

explain_sql_tool: Tool = build_tool(
    name="explain_sql",
    input_schema={
        "type": "object",
        "properties": {
            "sql": {
                "type": "string",
                "description": "The target read-only query to plan (single SELECT/WITH)",
            },
        },
        "required": ["sql"],
        "additionalProperties": False,
    },
    call=_explain_sql_call,
    prompt="Return the optimizer's EXPLAIN plan (estimated only, no ANALYZE) for a read-only query.",
    description="Get the estimated execution plan for a read-only query; the query itself is not executed.",
    is_read_only=lambda _input: True,
    is_concurrency_safe=lambda _input: True,
    check_permissions=_readonly_tool_permissions,
)


def _get_table_stats_call(tool_input: dict[str, Any], _context: ToolContext) -> ToolResult:
    name = "get_table_stats"
    try:
        schema = _validate_schema(tool_input.get("schema"))
        table = _validate_identifier(tool_input.get("table"), "table")
    except ValueError as exc:
        return _error_result(name, exc)
    target = _target_of(tool_input)
    try:
        with db_session(resolve_dsn(target)) as conn:
            result = postgres.fetch_table_stats(conn, schema=schema, table=table)
    except (DbConnectionError, LookupError, psycopg.Error) as exc:
        return _error_result(name, exc)
    result["target"] = target
    return ToolResult(name=name, output=_cap_bytes(result))


def _get_lock_info_call(tool_input: dict[str, Any], _context: ToolContext) -> ToolResult:
    name = "get_lock_info"
    try:
        min_wait = float(tool_input.get("min_wait_seconds") or 0)
        if min_wait < 0:
            raise ValueError("min_wait_seconds must be >= 0")
    except (TypeError, ValueError) as exc:
        return _error_result(name, ValueError(str(exc)))
    try:
        with db_session() as conn:
            result = postgres.fetch_lock_info(conn, min_wait_seconds=min_wait)
    except (DbConnectionError, LookupError, psycopg.Error) as exc:
        return _error_result(name, exc)
    return ToolResult(name=name, output=_cap_bytes(result))


get_table_stats_tool: Tool = build_tool(
    name="get_table_stats",
    input_schema={
        "type": "object",
        "properties": {
            "schema": {
                "type": "string",
                "description": "Schema name (default: public; only public is allowed)",
            },
            "table": {"type": "string", "description": "Table name (plain identifier)"},
            "target": {
                "type": "string",
                "enum": ["primary", "secondary"],
                "description": "Which pre-configured read-only database to inspect (never a host/DSN)",
            },
        },
        "required": ["table"],
        "additionalProperties": False,
    },
    call=_get_table_stats_call,
    prompt=(
        "Read relation size, row/statistics freshness and column selectivity "
        "aggregates from the configured read-only PostgreSQL database "
        "(no column value samples)."
    ),
    description=(
        "Get relation size, row estimates, analyze/vacuum timestamps, scan counts, "
        "and per-column aggregates (null_frac/n_distinct/correlation)."
    ),
    is_read_only=lambda _input: True,
    is_concurrency_safe=lambda _input: True,
    check_permissions=_readonly_tool_permissions,
)

get_lock_info_tool: Tool = build_tool(
    name="get_lock_info",
    input_schema={
        "type": "object",
        "properties": {
            "min_wait_seconds": {
                "type": "number",
                "description": "Only include waiters blocked at least this long (default 0)",
            },
        },
        "additionalProperties": False,
    },
    call=_get_lock_info_call,
    prompt=(
        "Read lock waits and blocking relations from pg_locks/pg_stat_activity "
        "(no SQL text, no usernames)."
    ),
    description="List waiting locks with blocking pids, held locks of blockers, and wait durations.",
    is_read_only=lambda _input: True,
    is_concurrency_safe=lambda _input: True,
    check_permissions=_readonly_tool_permissions,
)



def _json_safe(value: Any) -> Any:
    """把行值转成 JSON 安全形态（证据要能进 tool_result 与 transcript）。

    明细模式曾直接返回 ``datetime`` / ``Decimal``，下游 ``json.dumps`` 抛
    ``TypeError``——子代理因此报"明细取不出来"（2026-10-24 实跑复现）。
    """

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return str(value)


def _classify_column(name: str) -> str:
    """凭证类 / PII / 普通。后缀归一（``*_hash`` / ``*_token`` / ``*_secret`` / ``*_key``）。"""

    lowered = name.strip().lower()
    if lowered in _CREDENTIAL_COLUMNS:
        return "credential"
    if lowered.endswith(("_hash", "_token", "_secret")) and lowered not in _PII_COLUMNS:
        return "credential"
    if lowered in _PII_COLUMNS:
        return "pii"
    return "normal"


def _load_queryable_tables(
    env: dict[str, str] | None = None,
) -> tuple[frozenset[str], frozenset[str]]:
    """解析白名单：返回 (精确 ``schema.table`` 集合, 整 schema 集合)。默认空。"""

    source = env if env is not None else os.environ
    raw = str(source.get(QUERYABLE_TABLES_ENV_VAR) or "")
    exact: set[str] = set()
    wildcard: set[str] = set()
    for item in raw.split(","):
        entry = item.strip().lower()
        if not entry:
            continue
        schema, _, table = entry.partition(".")
        if not schema or not table:
            continue
        if table == "*":
            wildcard.add(schema)
        else:
            exact.add(f"{schema}.{table}")
    return frozenset(exact), frozenset(wildcard)


def _validate_queryable_table(
    schema: Any,
    table: Any,
    *,
    env: dict[str, str] | None = None,
) -> tuple[str, str]:
    """取数专用校验链：**不复用** ``_validate_schema``，避免回归 ``get_table_stats``。"""

    schema_name = _validate_identifier(schema or "public", "schema").lower()
    table_name = _validate_identifier(table, "table").lower()
    if _is_system_schema(schema_name):
        raise ValueError(
            f"system_schema_denied: schema {schema_name!r} is never queryable "
            "(system catalogs cannot be allow-listed)"
        )
    exact, wildcard = _load_queryable_tables(env)
    if f"{schema_name}.{table_name}" in exact or schema_name in wildcard:
        return schema_name, table_name
    raise ValueError(
        f"table_not_allowlisted: {schema_name}.{table_name} is not in "
        f"{QUERYABLE_TABLES_ENV_VAR} (default denies everything; entries are "
        "'schema.table' or 'schema.*')"
    )


_WHERE_OPERATORS: dict[str, str] = {
    "eq": "=",
    "ne": "<>",
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
}
_MAX_IN_VALUES = 100


def _build_where_clause(column: str, value: Any) -> tuple[str, list[Any]]:
    """把``where``的一个条目变成 ``(sql片段, 参数)``。

    标量 = 等值；对象形式支持 ``{"op": "gte", "value": "2026-10-22T08:00:00"}``
    与 ``{"op": "in", "value": [..]}``。运算符取自**白名单**（不拼接用户字符串），
    值一律走参数，标识符已在调用方校验。
    """

    if not isinstance(value, dict):
        return f"{column} = %s", [value]

    raw_op = str(value.get("op", "")).strip().lower()
    operand = value.get("value")
    if raw_op == "in":
        if not isinstance(operand, (list, tuple)) or not operand:
            raise ValueError(
                f"invalid where value for {column!r}: op=in requires a non-empty list"
            )
        if len(operand) > _MAX_IN_VALUES:
            raise ValueError(
                f"invalid where value for {column!r}: op=in supports at most "
                f"{_MAX_IN_VALUES} values"
            )
        if any(item is None for item in operand):
            raise ValueError(
                f"invalid where value for {column!r}: op=in does not accept null"
            )
        return f"{column} = ANY(%s)", [list(operand)]

    sql_op = _WHERE_OPERATORS.get(raw_op)
    if sql_op is None:
        raise ValueError(
            f"invalid where operator for {column!r}: {raw_op!r} "
            f"(supported: {sorted([*_WHERE_OPERATORS, 'in'])})"
        )
    if operand is None:
        raise ValueError(
            f"invalid where value for {column!r}: op={raw_op} requires a concrete value"
        )
    return f"{column} {sql_op} %s", [operand]


def _build_select(
    schema: str,
    table: str,
    columns: list[str] | None,
    where: dict[str, Any] | None,
    limit: int,
) -> tuple[str, list[Any], list[str]]:
    """拼只读 SQL：标识符**直接插入**（已校验），只有 where 的值走参数。"""

    params: list[Any] = []
    clauses: list[str] = []
    for raw_key, value in (where or {}).items():
        column = _validate_identifier(raw_key, "column").lower()
        if _classify_column(column) == "credential":
            raise ValueError(
                f"sensitive_column_denied: {column!r} is a credential column and cannot "
                "be used as a filter (equality counting would allow existence probing)"
            )
        if value is None:
            # PostgreSQL 里 `col = NULL` 恒为 NULL → COUNT(*) 恒 0 且不报错。
            # 静默返回 0 会被误读成「数据不存在」，而本工具正是用来证实/证伪这件事的。
            raise ValueError(
                f"invalid where value for {column!r}: null is not supported "
                "(use a concrete value; NULL comparisons never match)"
            )
        clause, clause_params = _build_where_clause(column, value)
        clauses.append(clause)
        params.extend(clause_params)

    where_sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    if columns:
        names: list[str] = []
        for raw_column in columns:
            column = _validate_identifier(raw_column, "column").lower()
            if _classify_column(column) == "credential":
                raise ValueError(
                    f"sensitive_column_denied: {column!r} is a credential column and "
                    "cannot be returned"
                )
            names.append(column)
        # 多取一行用于精确判定是否被截断（否则"恰好 limit 行"会被误报为截断）
        sql = (
            f"SELECT {', '.join(names)} FROM {schema}.{table}{where_sql} "
            f"LIMIT {int(limit) + 1}"
        )
        return sql, params, names
    sql = f"SELECT COUNT(*) AS count FROM {schema}.{table}{where_sql}"
    return sql, params, []


def _get_query_table_rows_call(tool_input: dict[str, Any], _context: ToolContext) -> ToolResult:
    name = "query_table_rows"
    from cloudagent_ext.diagnosis.db.connection import resolve_dsn

    try:
        schema, table = _validate_queryable_table(
            tool_input.get("schema"), tool_input.get("table")
        )
        target = str(tool_input.get("target") or "primary").strip().lower()
        raw_limit = tool_input.get("limit")
        limit = MAX_QUERY_ROWS if raw_limit is None else int(raw_limit)
        if limit < 1:
            raise ValueError("invalid limit: must be >= 1")
        if limit > MAX_RESULT_ROWS:
            limit = MAX_RESULT_ROWS
        columns = tool_input.get("columns") or None
        if columns is not None and not isinstance(columns, list):
            raise ValueError("invalid columns: expected an array of column names")
        where = tool_input.get("where") or None
        if where is not None and not isinstance(where, dict):
            raise ValueError("invalid where: expected an object of column -> value")
        sql, params, selected = _build_select(schema, table, columns, where, limit)
        dsn = resolve_dsn(target)
    except (ValueError, DbConnectionError) as exc:
        return _error_result(name, exc)

    try:
        validate_readonly_sql(sql)
    except SqlGuardError as exc:
        return _error_result(name, exc)

    try:
        with db_session(dsn) as conn:
            rows = conn.execute(sql, params).fetchall()
    except (DbConnectionError, psycopg.Error) as exc:
        return _error_result(name, exc)

    payload: dict[str, Any] = {"target": target, "table": f"{schema}.{table}"}
    if selected:
        truncated = len(rows) > limit
        if truncated:
            rows = rows[:limit]
        records: list[dict[str, Any]] = []
        redacted: set[str] = set()
        for row in rows:
            item: dict[str, Any] = {}
            for index, column in enumerate(selected):
                value = row[index]
                if _classify_column(column) == "pii" and value is not None:
                    redacted.add(column)
                    item[column] = "***"
                else:
                    item[column] = _json_safe(value)
            records.append(item)
        payload.update(
            {
                "mode": "rows",
                "returned": len(records),
                "truncated": truncated,
                "rows": records,
                "redacted_columns": sorted(redacted),
            }
        )
    else:
        payload.update({"mode": "aggregate", "count": int(rows[0][0]) if rows else 0})
    return ToolResult(name=name, output=_cap_bytes(payload))


query_table_rows_tool: Tool = build_tool(
    name="query_table_rows",
    input_schema={
        "type": "object",
        "properties": {
            "schema": {
                "type": "string",
                "description": "Schema name (default: public; must be allow-listed)",
            },
            "table": {"type": "string", "description": "Table name (plain identifier)"},
            "columns": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Columns to return. Omit for aggregate COUNT only (default, minimal exposure)."
                ),
            },
            "where": {
                "type": "object",
                "description": (
                    "Equality filters: {column: value}. Values are bound as parameters; "
                    "credential columns are rejected."
                ),
            },
            "limit": {
                "type": "integer",
                "description": (
                    f"Row limit for detail mode (default {MAX_QUERY_ROWS}, max {MAX_RESULT_ROWS})"
                ),
            },
            "target": {
                "type": "string",
                "enum": ["primary", "secondary"],
                "description": "Which pre-configured read-only database to query (never a host/DSN)",
            },
        },
        "required": ["table"],
        "additionalProperties": False,
    },
    call=_get_query_table_rows_call,
    prompt=(
        "Count or read rows from an allow-listed table in the configured read-only "
        "PostgreSQL database. Default returns COUNT only; pass columns for detail rows. "
        "Equality filters only; credential columns are rejected."
    ),
    description=(
        "Query an allow-listed table: aggregate count by default, detail rows when columns "
        "are given. Supports target=primary|secondary for upstream/downstream comparison."
    ),
    is_read_only=lambda _input: True,
    is_concurrency_safe=lambda _input: True,
    check_permissions=_readonly_tool_permissions,
)


def register_sql_db_tools(registry: Any) -> None:
    """按需装配：把只读 DB 工具集注册进给定注册表（默认注册表不含）。"""
    for tool in (
        get_schema_tool,
        get_indexes_tool,
        explain_sql_tool,
        get_table_stats_tool,
        get_lock_info_tool,
        query_table_rows_tool,
    ):
        registry.register(tool)
