#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""SQL Guard 对抗面测试（R2 加固固化）。

复用对照：``tests/diagnosis/db/test_sql_guard.py`` 已覆盖单语句、写/DDL 拒绝、
写 CTE、EXPLAIN 前缀、空白与超长——本文件**不重复**上述断言，仅覆盖：
危险函数（逐项 / 大小写 / pg_catalog 前缀 / 嵌套 CTE）、注释与多余分号边界、
正常函数零误杀。
"""

from __future__ import annotations

import pytest

from cloudagent_ext.diagnosis.db.sql_guard import (
    DISALLOWED_FUNCTIONS,
    SqlGuardError,
    validate_readonly_sql,
)


class TestDangerousFunctions:
    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT pg_read_file('/etc/passwd')",
            "SELECT pg_read_binary_file('/etc/shadow')",
            "SELECT pg_ls_dir('/')",
            "SELECT lo_import('/etc/passwd')",
            "SELECT lo_export(1, '/tmp/x')",
            "SELECT pg_sleep(10)",
            "SELECT pg_sleep_for('1 minute')",
            "SELECT pg_sleep_until(now() + interval '1 hour')",
            "SELECT dblink('host=x', 'SELECT 1')",
            "SELECT dblink_exec('host=x', 'UPDATE t SET a=1')",
            "SELECT pg_terminate_backend(123)",
            "SELECT pg_cancel_backend(123)",
        ],
    )
    def test_disallowed_function_rejected(self, sql: str) -> None:
        with pytest.raises(SqlGuardError) as excinfo:
            validate_readonly_sql(sql)
        assert "disallowed function" in str(excinfo.value)

    def test_case_insensitive(self) -> None:
        with pytest.raises(SqlGuardError):
            validate_readonly_sql("SELECT PG_READ_FILE('/etc/passwd')")

    def test_schema_prefixed_call(self) -> None:
        with pytest.raises(SqlGuardError):
            validate_readonly_sql("SELECT pg_catalog.pg_read_file('/etc/passwd')")

    def test_nested_cte_call(self) -> None:
        with pytest.raises(SqlGuardError):
            validate_readonly_sql("WITH a AS (SELECT pg_sleep(1)) SELECT * FROM a")

    def test_in_where_clause(self) -> None:
        with pytest.raises(SqlGuardError):
            validate_readonly_sql("SELECT id FROM orders WHERE pg_sleep(1) IS NULL")

    def test_disallowed_set_documented(self) -> None:
        assert {"pg_read_file", "pg_sleep", "dblink", "pg_terminate_backend"} <= DISALLOWED_FUNCTIONS

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT count(*), sum(amount), avg(amount) FROM orders",
            "SELECT lower(status), string_agg(name, ',') FROM t GROUP BY 1",
            "SELECT row_number() OVER (ORDER BY id) FROM t",
            "SELECT now(), date_trunc('hour', created_at) FROM t",
            "SELECT upper(region) FROM customers WHERE coalesce(amount, 0) > 0",
        ],
    )
    def test_common_functions_not_false_positive(self, sql: str) -> None:
        validate_readonly_sql(sql)  # 不应抛出


class TestParseEdgeCases:
    def test_trailing_line_comment_ok(self) -> None:
        validate_readonly_sql("SELECT 1 -- trailing comment")

    def test_trailing_block_comment_with_semicolon_ok(self) -> None:
        validate_readonly_sql("SELECT 1 /* note */;")

    def test_multi_statement_with_comment_rejected(self) -> None:
        with pytest.raises(SqlGuardError):
            validate_readonly_sql("SELECT 1; DROP TABLE orders -- comment")

    def test_extra_empty_statement_passes_guard_but_execution_is_protected(self) -> None:
        # 行为固化："SELECT 1;;" 解析为一条语句 → guard 通过；执行层（psycopg
        # 多语句保护）会拒绝，纵深防御不依赖单点。若未来 guard 直接拒绝，
        # 本用例应同步更新为 pytest.raises。
        result = validate_readonly_sql("SELECT 1;;")
        assert result == "SELECT 1;;"
