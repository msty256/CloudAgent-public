#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""代码/日志两域案例测试（变更 add-code-log-diagnosis-cases，P3.5）。

覆盖：多域加载（数量/唯一性/按域 expected_agents）/ GT 复验（tool_called 调真实
工具）/ 离线评测跑通（completeness=complete）/ fixture 不触发新安全规则。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from cloudagent_ext.diagnosis.case_library import load_cases
from cloudagent_ext.diagnosis.code.tools import find_references_tool, find_symbol_tool
from cloudagent_ext.diagnosis.evaluation.runner import run_evaluation
from cloudagent_ext.diagnosis.log.fixtures.sim_logs import write_sim_logs
from cloudagent_ext.diagnosis.log.tools import (
    correlate_events_tool,
    get_log_context_tool,
    parse_stack_trace_tool,
    search_logs_tool,
)
from cloudagent_ext.diagnosis.protocol import parse_diagnosis_result
from cloudagent_ext.tool_system.context import ToolContext

_TOOL_MAP = {
    "find_symbol": find_symbol_tool,
    "find_references": find_references_tool,
    "correlate_events": correlate_events_tool,
    "search_logs": search_logs_tool,
    "parse_stack_trace": parse_stack_trace_tool,
    "get_log_context": get_log_context_tool,
}


def _assert_tool_called(domain: str, ctx: ToolContext) -> None:
    for case in load_cases(domain):
        for evidence in case["ground_truth"]["required_evidence"]:
            check = evidence.get("check") or {}
            if check.get("kind") != "tool_called":
                continue
            tool = _TOOL_MAP.get(check["tool"])
            assert tool is not None, f"{case['case_id']}: tool {check['tool']} not mapped"
            result = tool.call(check.get("input") or {}, ctx)
            assert result.is_error is False, f"{case['case_id']}: {result.output}"


@pytest.fixture(autouse=True)
def _log_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    info = write_sim_logs(tmp_path / "logs")
    monkeypatch.setenv("CLOUDAGENT_LOG_ROOT", str(info["dir"]))


class TestCaseLoading:
    def test_code_domain(self) -> None:
        cases = load_cases("code")
        # P3.6 后续：code-002 反转为回归守卫，另加 code-007（异步缺口）→ 7 例
        assert len(cases) == 7
        assert [c["case_id"] for c in cases] == [f"code-{i:03d}" for i in range(1, 8)]
        assert all(c["domain"] == "code" for c in cases)
        assert all("code-diagnosis" in c["expected_agents"] for c in cases)

    def test_log_domain(self) -> None:
        cases = load_cases("log")
        assert len(cases) == 6
        assert [c["case_id"] for c in cases] == [f"log-{i:03d}" for i in range(1, 7)]
        assert all(c["domain"] == "log" for c in cases)
        assert all("log-diagnosis" in c["expected_agents"] for c in cases)

    def test_negative_cases_have_none_severity(self) -> None:
        code_cases = {c["case_id"]: c for c in load_cases("code")}
        # code-002 已反转为阴性回归守卫（三域分派无缺陷）
        for case_id in ("code-002", "code-004", "code-005"):
            severities = [cause["severity"] for cause in code_cases[case_id]["ground_truth"]["root_causes"]]
            assert severities == ["none"]
        # P3-2：log 域阴性案例同样断言
        log_cases = {c["case_id"]: c for c in load_cases("log")}
        assert [c["severity"] for c in log_cases["log-003"]["ground_truth"]["root_causes"]] == ["none"]


class TestGtReverification:
    def test_code_tool_called(self) -> None:
        _assert_tool_called("code", ToolContext(workspace_root=Path.cwd()))

    def test_log_tool_called(self) -> None:
        # P1-1：log 域 6 个案例的 required_evidence 全部真实调用（correlate_events/search_logs）
        _assert_tool_called("log", ToolContext(workspace_root=Path.cwd()))

    def test_all_new_fixtures_are_parsable(self) -> None:
        # P1-2 防回归：新案例的 fixture 必须能被协议解析器成功解析
        # （防止"围栏写坏 → invalid_output → top1_hit=False 假象"再次发生）
        import json

        fixture = (
            Path(__file__).resolve().parents[2]
            / "cloudagent_ext"
            / "diagnosis"
            / "evaluation"
            / "fixtures"
            / "offline_responses.json"
        )
        responses = {
            key: entry["response_text"]
            for key, entry in json.loads(fixture.read_text(encoding="utf-8"))["responses"].items()
        }
        for domain in ("code", "log"):
            for case in load_cases(domain):
                case_id = case["case_id"]
                parsed = parse_diagnosis_result(responses[case_id])
                assert parsed is not None, f"{case_id}: fixture not parsable"


class TestOfflineEvaluation:
    def test_code_domain_runs(self, tmp_path: Path) -> None:
        summary = run_evaluation(mode="offline", domain="code", out_dir=tmp_path)
        assert summary["completeness"] == "complete"
        report = (tmp_path / summary["run_id"] / "summary.md").read_text(encoding="utf-8")
        assert report.startswith("# 代码 诊断评测报告")

    def test_log_domain_runs(self, tmp_path: Path) -> None:
        summary = run_evaluation(mode="offline", domain="log", out_dir=tmp_path)
        assert summary["completeness"] == "complete"
        report = (tmp_path / summary["run_id"] / "summary.md").read_text(encoding="utf-8")
        assert report.startswith("# 日志 诊断评测报告")

    def test_new_safety_rules_not_triggered(self, tmp_path: Path) -> None:
        for domain in ("code", "log"):
            summary = run_evaluation(mode="offline", domain=domain, out_dir=tmp_path / domain)
            assert summary["safety_violation_cases"] == 0, domain
