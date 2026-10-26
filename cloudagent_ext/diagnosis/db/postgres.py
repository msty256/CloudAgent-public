#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""PostgreSQL 专属查询实现（未来 Database Adapter 的接缝；决策 8）。

本模块集中所有 PostgreSQL 方言的元数据查询 SQL；``tools.py`` 只负责契约、
装配与限额。第二个数据库实现出现时，本模块的边界即抽取 ``adapters/``
目录的接缝。
"""

from __future__ import annotations

from typing import Any

__all__ = ["fetch_schema", "fetch_indexes", "fetch_table_stats", "fetch_lock_info", "explain_sql"]


def fetch_schema(conn: Any, schema: str = "public", table: str | None = None) -> dict[str, Any]:
    """表清单（无 ``table``）或单表列 / 主键元数据（有 ``table``）。"""
    if table is None:
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = %s AND table_type = 'BASE TABLE' "
            "ORDER BY table_name",
            (schema,),
        ).fetchall()
        return {"schema": schema, "tables": [row[0] for row in rows]}
    columns = conn.execute(
        "SELECT column_name, data_type, is_nullable, column_default "
        "FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s "
        "ORDER BY ordinal_position",
        (schema, table),
    ).fetchall()
    if not columns:
        raise LookupError(f"table not found: {schema}.{table}")
    primary_key_rows = conn.execute(
        "SELECT a.attname FROM pg_index i "
        "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
        "WHERE i.indrelid = %s::regclass AND i.indisprimary "
        "ORDER BY array_position(i.indkey, a.attnum)",
        (f"{schema}.{table}",),
    ).fetchall()
    return {
        "schema": schema,
        "table": table,
        "columns": [
            {
                "name": row[0],
                "type": row[1],
                "nullable": row[2] == "YES",
                "default": row[3],
            }
            for row in columns
        ],
        "primary_key": [row[0] for row in primary_key_rows],
    }


def fetch_indexes(conn: Any, schema: str = "public", table: str | None = None) -> list[dict[str, Any]]:
    """索引定义与使用统计（``pg_index`` + ``pg_stat_user_indexes``）。"""
    sql = (
        "SELECT i.relname AS index_name,"
        "       t.relname AS table_name,"
        "       ix.indisunique AS is_unique,"
        "       am.amname AS method,"
        "       pg_get_indexdef(ix.indexrelid) AS definition,"
        "       COALESCE(s.idx_scan, 0) AS idx_scan,"
        "       COALESCE(s.idx_tup_read, 0) AS idx_tup_read,"
        "       (SELECT array_agg(a.attname ORDER BY u.ord)"
        "          FROM unnest(ix.indkey) WITH ORDINALITY AS u(attnum, ord)"
        "          JOIN pg_attribute a ON a.attrelid = ix.indrelid AND a.attnum = u.attnum"
        "       ) AS columns"
        " FROM pg_index ix"
        " JOIN pg_class i ON i.oid = ix.indexrelid"
        " JOIN pg_class t ON t.oid = ix.indrelid"
        " JOIN pg_namespace n ON n.oid = t.relnamespace"
        " JOIN pg_am am ON am.oid = i.relam"
        " LEFT JOIN pg_stat_user_indexes s ON s.indexrelid = ix.indexrelid"
        " WHERE n.nspname = %s"
    )
    params: list[Any] = [schema]
    if table is not None:
        sql += " AND t.relname = %s"
        params.append(table)
    sql += " ORDER BY t.relname, i.relname"
    rows = conn.execute(sql, tuple(params)).fetchall()
    return [
        {
            "name": row[0],
            "table": row[1],
            "unique": bool(row[2]),
            "method": row[3],
            "definition": row[4],
            "idx_scan": int(row[5]),
            "idx_tup_read": int(row[6]),
            "columns": list(row[7] or []),
        }
        for row in rows
    ]


def _iso(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else value


def fetch_table_stats(conn: Any, schema: str = "public", table: str = "") -> dict[str, Any]:
    """表规模、统计新鲜度与列选择性聚合量（expand-sql-diagnostic-db-tools）。

    数据源：``pg_class``（reltuples/relpages/大小）+ ``pg_stat_user_tables``
    （活/死行、分析/清理时间、扫描计数）+ ``pg_stats``（仅聚合量）。

    **脱敏**：不读取/不回显 ``most_common_vals``、``most_common_freqs``、
    ``histogram_bounds``（可能含业务值）——只输出 null_frac / n_distinct /
    correlation。``n_distinct=-1`` 表示"所有值唯一"（PostgreSQL 约定）。
    """

    if not table or not str(table).strip():
        raise LookupError("table is required for table stats")
    row = conn.execute(
        "SELECT c.reltuples, c.relpages,"
        "       pg_total_relation_size(c.oid) AS total_bytes,"
        "       s.n_live_tup, s.n_dead_tup,"
        "       s.last_vacuum, s.last_autovacuum, s.last_analyze, s.last_autoanalyze,"
        "       s.seq_scan, s.idx_scan"
        " FROM pg_class c"
        " JOIN pg_namespace n ON n.oid = c.relnamespace"
        " LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid"
        " WHERE n.nspname = %s AND c.relname = %s AND c.relkind IN ('r','p')",
        (schema, table),
    ).fetchone()
    if row is None:
        raise LookupError(f"table not found: {schema}.{table}")
    columns = conn.execute(
        "SELECT attname, null_frac, n_distinct, correlation"
        " FROM pg_stats WHERE schemaname = %s AND tablename = %s ORDER BY attname",
        (schema, table),
    ).fetchall()
    return {
        "schema": schema,
        "table": table,
        "relation": {
            "reltuples": float(row[0]) if row[0] is not None else None,
            "relpages": int(row[1]) if row[1] is not None else None,
            "total_bytes": int(row[2]) if row[2] is not None else None,
            "n_live_tup": int(row[3]) if row[3] is not None else None,
            "n_dead_tup": int(row[4]) if row[4] is not None else None,
            "last_vacuum": _iso(row[5]),
            "last_autovacuum": _iso(row[6]),
            "last_analyze": _iso(row[7]),
            "last_autoanalyze": _iso(row[8]),
            "seq_scan": int(row[9]) if row[9] is not None else None,
            "idx_scan": int(row[10]) if row[10] is not None else None,
        },
        "columns": [
            {
                "name": r[0],
                "null_frac": float(r[1]) if r[1] is not None else None,
                "n_distinct": float(r[2]) if r[2] is not None else None,
                "correlation": float(r[3]) if r[3] is not None else None,
            }
            for r in columns
        ],
        "note": "列统计仅含聚合量（null_frac/n_distinct/correlation），不返回列值样本；n_distinct=-1 表示值全唯一",
        "stats_never_analyzed": row[7] is None and row[8] is None,
    }


def fetch_lock_info(conn: Any, min_wait_seconds: float = 0.0) -> dict[str, Any]:
    """锁等待与阻塞关系（expand-sql-diagnostic-db-tools）。

    数据源：``pg_locks`` + ``pg_stat_activity``（state / wait_event_type）+
    ``pg_blocking_pids()``。

    **脱敏**：不返回 ``query`` 文本、不返回 ``usename``——只暴露锁形态、
    等待秒数与阻塞 pid。
    """

    database = conn.execute("SELECT current_database()").fetchone()[0]
    rows = conn.execute(
        "SELECT l.pid, l.locktype, c.relname, l.mode, l.granted,"
        "       EXTRACT(EPOCH FROM (now() - a.query_start)) AS wait_seconds,"
        "       pg_blocking_pids(l.pid) AS blocking_pids,"
        "       a.state, a.wait_event_type"
        " FROM pg_locks l"
        " LEFT JOIN pg_class c ON c.oid = l.relation"
        " LEFT JOIN pg_stat_activity a ON a.pid = l.pid"
        " WHERE NOT l.granted AND l.pid <> pg_backend_pid()",
    ).fetchall()
    waiting: list[dict[str, Any]] = []
    blocker_pids: set[int] = set()
    for r in rows:
        wait_seconds = float(r[5]) if r[5] is not None else None
        if min_wait_seconds and (wait_seconds is None or wait_seconds < min_wait_seconds):
            continue
        blockers = [int(p) for p in (r[6] or [])]
        blocker_pids.update(blockers)
        waiting.append(
            {
                "pid": int(r[0]),
                "locktype": r[1],
                "relation": r[2],
                "mode": r[3],
                "granted": False,
                "wait_seconds": wait_seconds,
                "blocking_pids": blockers,
                "state": r[7],
                "wait_event_type": r[8],
            }
        )
    blocking: list[dict[str, Any]] = []
    if blocker_pids:
        brows = conn.execute(
            "SELECT l.pid, l.locktype, c.relname, l.mode,"
            "       EXTRACT(EPOCH FROM (now() - a.query_start))"
            " FROM pg_locks l"
            " LEFT JOIN pg_class c ON c.oid = l.relation"
            " LEFT JOIN pg_stat_activity a ON a.pid = l.pid"
            " WHERE l.granted AND l.pid = ANY(%s) AND l.pid <> pg_backend_pid()"
            " ORDER BY l.pid, l.locktype",
            (list(blocker_pids),),
        ).fetchall()
        blocking = [
            {
                "pid": int(r[0]),
                "locktype": r[1],
                "relation": r[2],
                "mode": r[3],
                "granted": True,
                "held_seconds": float(r[4]) if r[4] is not None else None,
            }
            for r in brows
        ]
    return {
        "database": database,
        "waiting": waiting,
        "blocking": blocking,
        "summary": {
            "waiting_count": len(waiting),
            "blocking_count": len(blocking),
            "max_wait_seconds": max(
                (w["wait_seconds"] for w in waiting if w["wait_seconds"] is not None),
                default=None,
            ),
        },
        "note": (
            "lock inventory only —— 不包含 SQL 文本与用户名（脱敏）；"
            "wait_seconds/held_seconds = 会话查询已运行时长（now()-query_start 近似值），"
            "非精确锁等待时长——长查询短暂等锁时会被高估"
        ),
    }


def explain_sql(conn: Any, sql: str) -> list[str]:
    """对已通过只读校验的查询返回 EXPLAIN（文本）计划行。

    注意：不带 ``ANALYZE`` —— 返回的是**优化器预估计划**，不会执行目标查询。
    """
    rows = conn.execute("EXPLAIN " + sql).fetchall()
    return [row[0] for row in rows]
