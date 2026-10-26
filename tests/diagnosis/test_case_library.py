#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""案例库离线测试 + GT 真库复核（变更 add-sql-diagnostic-case-library）。

离线部分（总是运行）：schema 校验（空 Ground Truth / 缺字段 / 类型 /
severity / 安全期望）、加载接口、案例集数量与覆盖类别、expected_agents
与 safety 约束。

真库复核（DSN 存在时运行，否则跳过）：对 ``verifiable_on_sim`` 案例实际
执行 ``explain_sql`` / ``get_indexes``，断言 GT 锚点（plan_contains /
index_absent / index_present）与 cloudagent_sim 现实一致。
"""

from __future__ import annotations

import copy
import os
from pathlib import Path

import pytest

from cloudagent_ext.diagnosis.case_library import (
    CaseValidationError,
    load_case,
    load_cases,
    validate_case,
)

_CASE_IDS = ["sql-%03d" % i for i in range(1, 15)]


# ---------------------------------------------------------------------------
# 离线：schema 校验
# ---------------------------------------------------------------------------


class TestValidation:
    def test_valid_case_passes(self) -> None:
        validate_case(load_case("sql-001"))

    def test_empty_ground_truth_rejected(self) -> None:
        bad = copy.deepcopy(load_case("sql-001"))
        bad["ground_truth"] = {
            "root_causes": [],
            "required_evidence": [],
            "acceptable_recommendations": [],
        }
        with pytest.raises(CaseValidationError):
            validate_case(bad)

    def test_empty_root_causes_rejected(self) -> None:
        bad = copy.deepcopy(load_case("sql-001"))
        bad["ground_truth"]["root_causes"] = []
        with pytest.raises(CaseValidationError):
            validate_case(bad)

    def test_missing_case_id_rejected(self) -> None:
        bad = copy.deepcopy(load_case("sql-001"))
        del bad["case_id"]
        with pytest.raises(CaseValidationError):
            validate_case(bad)

    def test_bad_severity_rejected(self) -> None:
        bad = copy.deepcopy(load_case("sql-001"))
        bad["ground_truth"]["root_causes"][0]["severity"] = "critical"
        with pytest.raises(CaseValidationError):
            validate_case(bad)

    def test_must_be_read_only_enforced(self) -> None:
        bad = copy.deepcopy(load_case("sql-001"))
        bad["safety_expectations"]["must_be_read_only"] = False
        with pytest.raises(CaseValidationError):
            validate_case(bad)

    def test_expected_agent_enforced(self) -> None:
        bad = copy.deepcopy(load_case("sql-001"))
        bad["expected_agents"] = ["general-purpose"]
        with pytest.raises(CaseValidationError):
            validate_case(bad)


# ---------------------------------------------------------------------------
# 离线：加载接口与案例集覆盖
# ---------------------------------------------------------------------------


class TestLoading:
    def test_load_all_cases(self) -> None:
        cases = load_cases("sql")
        assert len(cases) >= 10
        ids = [case["case_id"] for case in cases]
        assert ids == sorted(ids)
        assert len(set(ids)) == len(ids)

    def test_expected_case_set_present(self) -> None:
        ids = {case["case_id"] for case in load_cases()}
        assert set(_CASE_IDS) <= ids

    def test_unknown_case_raises(self) -> None:
        with pytest.raises(KeyError):
            load_case("sql-999")

    def test_unknown_domain_raises(self) -> None:
        with pytest.raises(CaseValidationError):
            load_cases("kafka")

    def test_all_cases_have_agent_and_safety(self) -> None:
        for case in load_cases():
            assert "sql-diagnosis" in case["expected_agents"]
            assert case["safety_expectations"]["must_be_read_only"] is True
            assert case["ground_truth"]["required_evidence"]

    def test_coverage_categories(self) -> None:
        cases = load_cases()
        verifiable = [c for c in cases if c["verifiable_on_sim"]]
        behavior_only = [c for c in cases if not c["verifiable_on_sim"]]
        negative = [
            c for c in cases
            if any(rc["severity"] == "none" for rc in c["ground_truth"]["root_causes"])
        ]
        assert len(verifiable) >= 7   # 数据库层可复核的阳性/阴性案例
        assert len(behavior_only) >= 3  # 行为类边界/降级案例
        assert any(c["case_id"] == "sql-003" for c in negative)  # 阴性对照必须存在

    def test_case_files_read_via_package_resources(self) -> None:
        for case in load_cases():
            # load 路径已通过包资源读取；此处补充关键字段完整性
            assert case["input"]["question"].strip()
            assert case["notes"].strip()


# ---------------------------------------------------------------------------
# 真库复核（DSN 可选；db extra 缺失或数据库不可用时跳过——离线部分不受影响）
# ---------------------------------------------------------------------------

_DB_EXTRA_AVAILABLE = True
try:  # 可选依赖：缺失时保留离线测试可用
    import psycopg  # noqa: F401
    import sqlglot  # noqa: F401

    from cloudagent_ext.diagnosis.db.connection import DSN_ENV_VAR, db_session
    from cloudagent_ext.diagnosis.db.tools import explain_sql_tool, get_indexes_tool
    from cloudagent_ext.tool_system.context import ToolContext
except ImportError:  # pragma: no cover
    _DB_EXTRA_AVAILABLE = False


@pytest.fixture(scope="module")
def _case_ctx():
    if not _DB_EXTRA_AVAILABLE:
        pytest.skip("db extra (psycopg/sqlglot) not installed; case re-verification skipped")
    value = os.environ.get(DSN_ENV_VAR)
    if not value:
        pytest.skip(f"{DSN_ENV_VAR} not configured; case re-verification skipped")
    try:
        with db_session(value) as conn:
            conn.execute("SELECT 1")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"PostgreSQL unavailable: {exc}")
    return ToolContext(workspace_root=Path.cwd())


def _plan_text(case: dict, ctx) -> str:
    result = explain_sql_tool.call({"sql": case["input"]["context"]["sql"]}, ctx)
    assert result.is_error is False, f"explain failed for {case['case_id']}: {result.output}"
    return "\n".join(result.output.get("plan") or [])


class TestGtReverification:
    def test_verifiable_cases_match_ground_truth(self, _case_ctx) -> None:
        ctx = _case_ctx
        checked = 0
        for case in load_cases():
            if not case["verifiable_on_sim"]:
                continue
            plan_text: str | None = None
            for entry in case["ground_truth"]["required_evidence"]:
                check = entry.get("check")
                if not check:
                    continue
                kind = check["kind"]
                if kind == "plan_contains":
                    if plan_text is None:
                        plan_text = _plan_text(case, ctx)
                    assert check["substring"] in plan_text, (
                        f"{case['case_id']}: expected plan fragment "
                        f"{check['substring']!r} not found in plan:\n{plan_text}"
                    )
                elif kind in ("index_absent", "index_present"):
                    result = get_indexes_tool.call({"table": check["table"]}, ctx)
                    assert result.is_error is False
                    indexes = result.output.get("indexes") or []
                    if kind == "index_absent":
                        for index in indexes:
                            assert check["column"] not in (index.get("columns") or []), (
                                f"{case['case_id']}: unexpected index on "
                                f"{check['table']}.{check['column']}"
                            )
                    else:
                        assert any(index["name"] == check["index"] for index in indexes), (
                            f"{case['case_id']}: expected index {check['index']!r} missing"
                        )
                elif kind == "tool_called":
                    # expand: 统计/锁工具 + P3.5: 代码/日志域工具
                    # 注意（审查 P2-2）：本测试遍历 load_cases() 默认 sql 域，
                    # code/log 的 6 个映射当前不会被触发；它们由
                    # tests/diagnosis/test_code_log_cases.py 的按域复验覆盖。
                    from cloudagent_ext.diagnosis.code.tools import (
                        find_references_tool,
                        find_symbol_tool,
                    )
                    from cloudagent_ext.diagnosis.db.tools import (
                        get_lock_info_tool,
                        get_table_stats_tool,
                    )
                    from cloudagent_ext.diagnosis.log.tools import (
                        correlate_events_tool,
                        get_log_context_tool,
                        parse_stack_trace_tool,
                        search_logs_tool,
                    )

                    tool = {
                        "get_table_stats": get_table_stats_tool,
                        "get_lock_info": get_lock_info_tool,
                        # P3.5（add-code-log-diagnosis-cases）
                        "find_symbol": find_symbol_tool,
                        "find_references": find_references_tool,
                        "search_logs": search_logs_tool,
                        "get_log_context": get_log_context_tool,
                        "parse_stack_trace": parse_stack_trace_tool,
                        "correlate_events": correlate_events_tool,
                    }.get(check["tool"])
                    assert tool is not None, f"{case['case_id']}: unknown tool {check['tool']!r}"
                    result = tool.call(check.get("input") or {}, ctx)
                    assert result.is_error is False, (
                        f"{case['case_id']}: {check['tool']} call failed: {result.output}"
                    )
                    expect = check.get("expect") or {}
                    if expect:
                        output = result.output or {}
                        relation = output.get("relation") or {}
                        if "n_live_tup" in expect:
                            assert relation.get("n_live_tup") == expect["n_live_tup"], (
                                f"{case['case_id']}: n_live_tup expected "
                                f"{expect['n_live_tup']}, got {relation.get('n_live_tup')}"
                            )
                        if "region_n_distinct" in expect:
                            columns = {c.get("name"): c for c in output.get("columns") or []}
                            actual = (columns.get("region") or {}).get("n_distinct")
                            assert actual == expect["region_n_distinct"], (
                                f"{case['case_id']}: region n_distinct expected "
                                f"{expect['region_n_distinct']}, got {actual}"
                            )
                else:  # pragma: no cover - 未知 check 一律失败（严格）
                    pytest.fail(f"{case['case_id']}: unknown check kind {kind!r}")
                checked += 1
        assert checked >= 10, "verifiable case checks did not run as expected"
