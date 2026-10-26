#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""取数工具离线测试（变更 add-db-data-query-tool）。

覆盖白名单（空 / 精确 / `schema.*` / 系统 schema）、目标枚举与未配置回退、
凭证列禁止作过滤键、明细限额与 PII 脱敏的构造行为。真实数据库用例在
``test_db_tools_integration.py``（无 DSN 时 skip）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cloudagent_ext.diagnosis.db.tools import (
    MAX_QUERY_ROWS,
    MAX_RESULT_ROWS,
    QUERYABLE_TABLES_ENV_VAR,
    _build_select,
    _classify_column,
    _validate_queryable_table,
    query_table_rows_tool,
)
from cloudagent_ext.tool_system.context import ToolContext


def _ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(workspace_root=tmp_path)


class TestWhitelist:
    def test_empty_whitelist_denies_everything(self, monkeypatch) -> None:
        monkeypatch.delenv(QUERYABLE_TABLES_ENV_VAR, raising=False)
        with pytest.raises(ValueError, match="table_not_allowlisted"):
            _validate_queryable_table("public", "orders")

    def test_exact_entry_allows_only_that_table(self, monkeypatch) -> None:
        monkeypatch.setenv(QUERYABLE_TABLES_ENV_VAR, "public.orders")
        assert _validate_queryable_table("public", "orders") == ("public", "orders")
        with pytest.raises(ValueError, match="table_not_allowlisted"):
            _validate_queryable_table("public", "customers")

    def test_schema_wildcard_allows_any_table(self, monkeypatch) -> None:
        monkeypatch.setenv(QUERYABLE_TABLES_ENV_VAR, "biz.*")
        assert _validate_queryable_table("biz", "orders") == ("biz", "orders")
        assert _validate_queryable_table("biz", "sync_job") == ("biz", "sync_job")

    def test_schema_wildcard_does_not_leak_other_schema(self, monkeypatch) -> None:
        monkeypatch.setenv(QUERYABLE_TABLES_ENV_VAR, "biz.*")
        with pytest.raises(ValueError, match="table_not_allowlisted"):
            _validate_queryable_table("public", "orders")

    @pytest.mark.parametrize(
        "schema",
        [
            "pg_catalog",
            "information_schema",
            "pg_toast",
            # 变体：PostgreSQL 会生成 pg_temp_N / pg_toast_temp_N，精确集合挡不住
            "pg_toast_temp_1",
            "pg_temp_3",
        ],
    )
    def test_system_schema_denied_even_if_allowlisted(self, monkeypatch, schema: str) -> None:
        monkeypatch.setenv(QUERYABLE_TABLES_ENV_VAR, f"{schema}.*")
        with pytest.raises(ValueError, match="system_schema_denied"):
            _validate_queryable_table(schema, "anything")

    def test_invalid_identifier_rejected(self, monkeypatch) -> None:
        monkeypatch.setenv(QUERYABLE_TABLES_ENV_VAR, "public.*")
        with pytest.raises(ValueError, match="invalid table"):
            _validate_queryable_table("public", "orders; DROP TABLE x")


class TestColumnTiers:
    @pytest.mark.parametrize("column", ["password", "password_hash", "api_key", "token"])
    def test_credential_classification(self, column: str) -> None:
        assert _classify_column(column) == "credential"

    @pytest.mark.parametrize("column", ["phone", "id_card", "email"])
    def test_pii_classification(self, column: str) -> None:
        assert _classify_column(column) == "pii"

    def test_credential_column_as_filter_is_denied(self) -> None:
        with pytest.raises(ValueError, match="sensitive_column_denied"):
            _build_select("public", "users", None, {"password_hash": "guess"}, 20)

    def test_credential_column_as_output_is_denied(self) -> None:
        with pytest.raises(ValueError, match="sensitive_column_denied"):
            _build_select("public", "users", ["id", "token"], None, 20)

    def test_business_key_suffix_is_not_credential(self) -> None:
        """``order_key`` / ``idempotency_key`` 是业务键，不能因为 ``_key`` 后缀被当成凭证列。"""

        assert _classify_column("order_key") == "normal"
        assert _classify_column("idempotency_key") == "normal"
        assert _classify_column("access_key") == "credential"

    def test_pii_column_can_filter(self) -> None:
        sql, params, selected = _build_select("public", "orders", None, {"phone": "138"}, 20)
        assert "phone = %s" in sql
        assert params == ["138"]
        assert selected == []


class TestSqlShape:
    def test_default_is_count_only(self) -> None:
        sql, params, selected = _build_select("public", "orders", None, None, 20)
        assert sql == "SELECT COUNT(*) AS count FROM public.orders"
        assert params == [] and selected == []

    def test_detail_selects_columns_with_limit(self) -> None:
        # 多取一行（limit+1）用于精确判定是否被截断
        sql, _, selected = _build_select("public", "orders", ["order_id"], None, 20)
        assert sql == "SELECT order_id FROM public.orders LIMIT 21"
        assert selected == ["order_id"]

    def test_identifiers_are_interpolated_not_bound(self) -> None:
        sql, params, _ = _build_select("public", "orders", ["order_id"], {"order_id": "A1"}, 20)
        # 表名/列名直接出现在 SQL 里；只有值走参数
        assert "public.orders" in sql and "order_id = %s" in sql
        assert params == ["A1"]


class TestNullFilter:
    def test_null_value_is_rejected(self) -> None:
        """``col = NULL`` 恒不匹配 → COUNT 恒 0，会被误读成"数据不存在"。"""

        with pytest.raises(ValueError, match="null is not supported"):
            _build_select("public", "orders", None, {"id": None}, 20)


class TestToolCall:
    def test_denied_table_returns_structured_error(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv(QUERYABLE_TABLES_ENV_VAR, raising=False)
        result = query_table_rows_tool.call({"table": "orders"}, _ctx(tmp_path))
        assert result.is_error is True
        assert "table_not_allowlisted" in str(result.output)

    def test_invalid_target_rejected(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv(QUERYABLE_TABLES_ENV_VAR, "public.orders")
        result = query_table_rows_tool.call(
            {"table": "orders", "target": "other"}, _ctx(tmp_path)
        )
        assert result.is_error is True
        assert "invalid_target" in str(result.output)

    def test_secondary_not_configured_never_falls_back(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv(QUERYABLE_TABLES_ENV_VAR, "public.orders")
        monkeypatch.setenv("CLOUDAGENT_DB_DSN", "postgresql://u:p@127.0.0.1:1/none")
        monkeypatch.delenv("CLOUDAGENT_DB_DSN_SECONDARY", raising=False)
        result = query_table_rows_tool.call(
            {"table": "orders", "target": "secondary"}, _ctx(tmp_path)
        )
        assert result.is_error is True
        assert "secondary_dsn_not_configured" in str(result.output)

    def test_limit_above_hard_cap_is_clamped(self, tmp_path, monkeypatch) -> None:
        """硬上限 200 生效：超限请求被截到 MAX_RESULT_ROWS，而不是报错。"""

        captured: dict = {}

        def _fake_build(schema, table, columns, where, limit):
            captured["limit"] = limit
            return "SELECT COUNT(*) AS count FROM public.orders", [], []

        monkeypatch.setenv(QUERYABLE_TABLES_ENV_VAR, "public.orders")
        monkeypatch.setattr(
            "cloudagent_ext.diagnosis.db.tools._build_select", _fake_build
        )

        class _Conn:
            def execute(self, *_a, **_k):
                class _R:
                    @staticmethod
                    def fetchall():
                        return [(0,)]

                return _R()

        class _Session:
            def __enter__(self):
                return _Conn()

            def __exit__(self, *exc):
                return False

        monkeypatch.setattr(
            "cloudagent_ext.diagnosis.db.tools.resolve_dsn", lambda *_a, **_k: "dsn", raising=False
        )
        monkeypatch.setattr(
            "cloudagent_ext.diagnosis.db.connection.resolve_dsn", lambda *_a, **_k: "dsn"
        )
        monkeypatch.setattr(
            "cloudagent_ext.diagnosis.db.tools.db_session", lambda *_a, **_k: _Session()
        )
        result = query_table_rows_tool.call(
            {"table": "orders", "limit": MAX_RESULT_ROWS + 500}, _ctx(tmp_path)
        )
        assert result.is_error is False, result.output
        assert captured["limit"] == MAX_RESULT_ROWS

    def test_default_limit_is_max_query_rows(self, tmp_path, monkeypatch) -> None:
        captured: dict = {}

        def _fake_build(schema, table, columns, where, limit):
            captured["limit"] = limit
            return "SELECT COUNT(*) AS count FROM public.orders", [], []

        monkeypatch.setenv(QUERYABLE_TABLES_ENV_VAR, "public.orders")
        monkeypatch.setattr(
            "cloudagent_ext.diagnosis.db.tools._build_select", _fake_build
        )

        class _Conn:
            def execute(self, *_a, **_k):
                class _R:
                    @staticmethod
                    def fetchall():
                        return [(0,)]

                return _R()

        class _Session:
            def __enter__(self):
                return _Conn()

            def __exit__(self, *exc):
                return False

        monkeypatch.setattr(
            "cloudagent_ext.diagnosis.db.connection.resolve_dsn", lambda *_a, **_k: "dsn"
        )
        monkeypatch.setattr(
            "cloudagent_ext.diagnosis.db.tools.db_session", lambda *_a, **_k: _Session()
        )
        query_table_rows_tool.call({"table": "orders"}, _ctx(tmp_path))
        assert captured["limit"] == MAX_QUERY_ROWS


class TestTruncationBoundary:
    """truncated 必须精确：恰好 limit 行不算截断（实现用 limit+1 多取一行判定）。"""

    def _run(self, row_count: int, limit: int, tmp_path, monkeypatch):
        rows = [(index,) for index in range(row_count)]

        class _Conn:
            def execute(self, *_a, **_k):
                class _R:
                    @staticmethod
                    def fetchall():
                        return rows

                return _R()

        class _Session:
            def __enter__(self):
                return _Conn()

            def __exit__(self, *exc):
                return False

        monkeypatch.setenv(QUERYABLE_TABLES_ENV_VAR, "public.orders")
        monkeypatch.setattr(
            "cloudagent_ext.diagnosis.db.connection.resolve_dsn", lambda *_a, **_k: "dsn"
        )
        monkeypatch.setattr(
            "cloudagent_ext.diagnosis.db.tools.db_session", lambda *_a, **_k: _Session()
        )
        return query_table_rows_tool.call(
            {"table": "orders", "columns": ["id"], "limit": limit}, _ctx(tmp_path)
        )

    def test_exact_limit_rows_is_not_truncated(self, tmp_path, monkeypatch) -> None:
        result = self._run(2, 2, tmp_path, monkeypatch)
        assert result.is_error is False, result.output
        assert result.output["returned"] == 2
        assert result.output["truncated"] is False

    def test_more_rows_than_limit_is_truncated(self, tmp_path, monkeypatch) -> None:
        result = self._run(3, 2, tmp_path, monkeypatch)
        assert result.output["returned"] == 2
        assert result.output["truncated"] is True


class TestRowsAreJsonSafe:
    """明细行必须能直接 json.dumps（否则证据进不了 tool_result）。"""

    def test_datetime_and_decimal_are_converted(self) -> None:
        import datetime
        import decimal
        import json

        from cloudagent_ext.diagnosis.db.tools import _json_safe

        raw = {
            "id": 1,
            "created_at": datetime.datetime(2026, 10, 5, 10, 24, 32, tzinfo=datetime.timezone.utc),
            "amount": decimal.Decimal("34.50"),
            "payload": b"\x01\x02",
            "nested": [decimal.Decimal("1.5")],
        }
        safe = _json_safe(raw)
        encoded = json.dumps(safe, ensure_ascii=False)
        assert '"34.50"' in encoded
        assert "2026-10-05T10:24:32" in encoded
        assert safe["payload"] == "0102"
        assert safe["nested"] == ["1.5"]

    def test_scalars_pass_through(self) -> None:
        from cloudagent_ext.diagnosis.db.tools import _json_safe

        assert _json_safe(None) is None
        assert _json_safe(1) == 1
        assert _json_safe("x") == "x"
        assert _json_safe(True) is True


class TestRangeFilters:
    """where 支持范围/集合过滤（2026-10-24：日志用 created_at >= 窗口，工具只有等值）。"""

    def test_scalar_is_equality(self) -> None:
        from cloudagent_ext.diagnosis.db.tools import _build_where_clause

        assert _build_where_clause("order_no", "x") == ("order_no = %s", ["x"])

    def test_range_operators(self) -> None:
        from cloudagent_ext.diagnosis.db.tools import _build_where_clause

        for op, sql_op in (("gt", ">"), ("gte", ">="), ("lt", "<"), ("lte", "<="), ("ne", "<>")):
            clause, params = _build_where_clause("created_at", {"op": op, "value": "2026-10-22"})
            assert clause == f"created_at {sql_op} %s"
            assert params == ["2026-10-22"]

    def test_in_operator(self) -> None:
        from cloudagent_ext.diagnosis.db.tools import _build_where_clause

        clause, params = _build_where_clause("tenant_id", {"op": "in", "value": [1, 2]})
        assert clause == "tenant_id = ANY(%s)"
        assert params == [[1, 2]]

    def test_rejects_unknown_operator(self) -> None:
        import pytest

        from cloudagent_ext.diagnosis.db.tools import _build_where_clause

        with pytest.raises(ValueError, match="invalid where operator"):
            _build_where_clause("x", {"op": "like", "value": "%a%"})

    def test_rejects_empty_in(self) -> None:
        import pytest

        from cloudagent_ext.diagnosis.db.tools import _build_where_clause

        with pytest.raises(ValueError, match="non-empty list"):
            _build_where_clause("tenant_id", {"op": "in", "value": []})
