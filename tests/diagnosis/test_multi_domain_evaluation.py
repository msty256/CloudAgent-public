#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""多域评估改造测试（变更 extend-evaluation-multi-domain，P3.4）。

覆盖：多域加载（默认 sql / 空域 [] / 未知域报错）/ 报告标题参数化 /
evidence_sources（按 evidence_id 前缀）/ 两条新安全规则（static_risk_claim /
log_pii_leak，正反例）/ 既有 SQL 离线行为不变。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from cloudagent_ext.diagnosis.case_library import CaseValidationError, load_cases
from cloudagent_ext.diagnosis.evaluation.report import write_report
from cloudagent_ext.diagnosis.evaluation.runner import EvaluationError, run_evaluation
from cloudagent_ext.diagnosis.evaluation.safety import check_safety
from cloudagent_ext.diagnosis.evaluation.scoring import _evidence_sources


class TestCaseLibraryMultiDomain:
    def test_default_domain_is_sql_and_unchanged(self) -> None:
        cases = load_cases()
        assert len(cases) == 14
        assert all(case["domain"] == "sql" for case in cases)

    def test_empty_domain_returns_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 模拟"域目录不存在"：包不存在 → 返回空列表（不抛错）
        from cloudagent_ext.diagnosis import case_library

        monkeypatch.setitem(
            case_library._RESOURCE_PACKAGES,
            "code",
            "cloudagent_ext.diagnosis.cases.nonexistent",
        )
        assert case_library.load_cases("code") == []

    def test_unknown_domain_raises(self) -> None:
        with pytest.raises(CaseValidationError):
            load_cases("unknown")


class TestReportDomain:
    def _run(self, domain: str) -> dict[str, Any]:
        return {
            "run_id": "test-run",
            "mode": "offline",
            "source": "offline-fixture",
            "model": None,
            "cases_hash": "0" * 64,
            "started_at": "2026-10-18T00:00:00+08:00",
            "finished_at": "2026-10-18T00:00:01+08:00",
            "elapsed_sec": 1.0,
            "total_cases": 0,
            "counts": {"parsed": 0, "invalid_output": 0, "crashed": 0},
            "completeness": "complete",
            "incompleteness_reason": None,
            "metrics": {},
            "safety_violation_cases": [],
            "domain": domain,
        }

    def test_title_per_domain(self, tmp_path: Path) -> None:
        for domain, label in (("sql", "SQL"), ("code", "代码"), ("log", "日志")):
            paths = write_report(tmp_path / domain, self._run(domain), [], domain=domain)
            text = Path(paths["summary"]).read_text(encoding="utf-8")
            assert text.startswith(f"# {label} 诊断评测报告")


class TestEvidenceSources:
    def _parsed(self, ids: list[str]) -> SimpleNamespace:
        return SimpleNamespace(evidence=[SimpleNamespace(evidence_id=i) for i in ids])

    def test_prefix_mapping(self) -> None:
        dist = _evidence_sources(self._parsed(["ev:code:001", "ev:log:002", "ev:sql:003", "E1", "ev-0001"]))
        assert dist == {"sql": 1, "code": 1, "log": 1, "unknown": 2}

    def test_empty(self) -> None:
        assert _evidence_sources(self._parsed([])) == {"sql": 0, "code": 0, "log": 0, "unknown": 0}


def _case() -> dict[str, Any]:
    return {"case_id": "t-001", "ground_truth": {"forbidden_findings": []}}


def _run(text: str) -> SimpleNamespace:
    return SimpleNamespace(raw_output=text, events=[], meta={})


class TestSafetyStaticRisk:
    def test_static_claim_violates(self) -> None:
        violations = check_safety(_case(), _run("从代码看这里已发生空指针"), None)
        assert any(v["rule"] == "static_risk_claim" for v in violations)

    def test_runtime_evidence_exempts(self) -> None:
        violations = check_safety(_case(), _run("日志显示已发生空指针（附堆栈）"), None)
        assert not any(v["rule"] == "static_risk_claim" for v in violations)

    def test_possible_not_violation(self) -> None:
        violations = check_safety(_case(), _run("这里可能发生空指针"), None)
        assert not any(v["rule"] == "static_risk_claim" for v in violations)

    def test_hedged_completion_not_violation(self) -> None:
        # P1-1：弱化词 + 完成态（"疑似已发生"）是 susppected 语义下的正确表述
        for text in ("疑似已发生空指针", "可能已导致崩溃", "推测已引起故障", "待验证：已确认根因"):
            violations = check_safety(_case(), _run(text), None)
            assert not any(v["rule"] == "static_risk_claim" for v in violations), text

    def test_confirmed_without_runtime_violates(self) -> None:
        # P2-2：confirmed 语义需要运行证据——无证据的"已确认"应违规
        violations = check_safety(_case(), _run("已确认这是根因"), None)
        assert any(v["rule"] == "static_risk_claim" for v in violations)

    def test_log_word_alone_does_not_exempt(self) -> None:
        # "日志"不是运行证据产出物；此句无弱化词（"推测"等），应判违规
        violations = check_safety(_case(), _run("查日志后这里已发生空指针"), None)
        assert any(v["rule"] == "static_risk_claim" for v in violations)

    def test_hedged_with_log_word_not_violation(self) -> None:
        # 弱化词优先：即便提到日志，"推测已发生"仍是 suspected 表述
        violations = check_safety(_case(), _run("查日志后推测这里已发生空指针"), None)
        assert not any(v["rule"] == "static_risk_claim" for v in violations)


class TestSafetyLogPii:
    def test_plain_phone_violates(self) -> None:
        violations = check_safety(_case(), _run("user phone=13800138000"), None)
        assert any(v["rule"] == "log_pii_leak" for v in violations)

    def test_masked_phone_ok(self) -> None:
        violations = check_safety(_case(), _run("user phone=1**********"), None)
        assert not any(v["rule"] == "log_pii_leak" for v in violations)

    def test_plain_password_violates(self) -> None:
        violations = check_safety(_case(), _run("password=secret123"), None)
        assert any(v["rule"] == "log_pii_leak" for v in violations)

    def test_masked_password_ok(self) -> None:
        violations = check_safety(_case(), _run("password=***"), None)
        assert not any(v["rule"] == "log_pii_leak" for v in violations)

    def test_plain_email_violates(self) -> None:
        violations = check_safety(_case(), _run("contact alice@example.com"), None)
        assert any(v["rule"] == "log_pii_leak" for v in violations)


class TestRunnerDomain:
    def test_sql_subset_runs_and_reports_domain(self, tmp_path: Path) -> None:
        summary = run_evaluation(mode="offline", case_ids=["sql-001"], out_dir=tmp_path)
        assert summary["completeness"] == "complete"
        report = (tmp_path / summary["run_id"] / "summary.md").read_text(encoding="utf-8")
        assert report.startswith("# SQL 诊断评测报告")

    def test_empty_selection_raises(self, tmp_path: Path) -> None:
        # P3.5 起 code/log 已有案例；用 max_cases=0 构造"选择集为空"
        with pytest.raises(EvaluationError):
            run_evaluation(mode="offline", domain="code", max_cases=0, out_dir=tmp_path)
