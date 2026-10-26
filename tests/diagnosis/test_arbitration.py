#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""结论冲突检测与裁决策略测试（指南 P4 任务 9）。

策略的核心断言：**跨子代理冲突不自动裁决**（标 unresolved），
**同一子代理内部矛盾**降级处理（标 internal）。
两条检测规则各自正反用例，避免"永远报冲突"的假阳性。
"""

from __future__ import annotations

from types import SimpleNamespace

from cloudagent_ext.diagnosis.arbitration import (
    CONFLICT_INTERNAL,
    CONFLICT_UNRESOLVED,
    detect_conflicts,
    summarize,
)
from cloudagent_ext.diagnosis.models import DiagnosisResult, Evidence, RootCause


def _result(agent: str, *, evidence=(), roots=()) -> DiagnosisResult:
    return DiagnosisResult(
        request_id="req",
        agent_name=agent,
        status="success",
        summary="s",
        evidence=list(evidence),
        root_causes=list(roots),
    )


def _entry(result: DiagnosisResult) -> SimpleNamespace:
    return SimpleNamespace(result=result)


def _ev(evidence_id: str, relation=()) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        source_type="tool",
        source_ref="ref",
        observation="o",
        relation=list(relation),
    )


class TestEvidenceRelationConflict:
    def test_cross_result_relation_is_dropped_by_model(self) -> None:
        """已知协议边界：跨结果的 relation 在构造期被判悬空并丢弃。

        这意味着**子代理无法显式声明"我和另一个子代理冲突"**。
        跨域冲突只能靠 ``opposing_claim`` 的文本启发式。此处把该行为固化，
        将来若改协议（允许前向引用），这个用例会失败并提醒同步更新文档。
        """

        a = _result("sql-diagnosis", evidence=[_ev("e1", [{"kind": "conflict", "with": "e2"}])])
        b = _result("log-diagnosis", evidence=[_ev("e2")])
        assert a.evidence[0].relation == []          # 被模型层丢弃
        assert detect_conflicts([_entry(a), _entry(b)]) == []

    def test_same_agent_conflict_is_internal(self) -> None:
        a = _result(
            "sql-diagnosis",
            evidence=[
                _ev("e1", [{"kind": "conflict", "with": "e2"}]),
                _ev("e2"),
            ],
        )
        conflicts = detect_conflicts([_entry(a)])
        assert len(conflicts) == 1
        assert conflicts[0].resolution == CONFLICT_INTERNAL

    def test_duplicate_pair_counted_once(self) -> None:
        """同一结果内，两条证据互相声明冲突只算一处。"""

        a = _result(
            "sql",
            evidence=[
                _ev("e1", [{"kind": "conflict", "with": "e2"}]),
                _ev("e2", [{"kind": "conflict", "with": "e1"}]),
            ],
        )
        assert len(detect_conflicts([_entry(a)])) == 1

    def test_no_conflict_when_kind_is_complementary(self) -> None:
        a = _result(
            "sql",
            evidence=[
                _ev("e1", [{"kind": "complementary", "with": "e2"}]),
                _ev("e2"),
            ],
        )
        assert detect_conflicts([_entry(a)]) == []


class TestOpposingClaims:
    def test_missing_vs_synced_same_object(self) -> None:
        a = _result("sql-diagnosis", roots=[RootCause("public.orders 未落库", 0.8)])
        b = _result("log-diagnosis", roots=[RootCause("public.orders 已同步", 0.6)])
        conflicts = detect_conflicts([_entry(a), _entry(b)])
        assert len(conflicts) == 1
        assert conflicts[0].kind == "opposing_claim"
        assert conflicts[0].resolution == CONFLICT_UNRESOLVED

    def test_different_objects_no_conflict(self) -> None:
        a = _result("sql-diagnosis", roots=[RootCause("orders 未落库", 0.8)])
        b = _result("log-diagnosis", roots=[RootCause("customers 已同步", 0.6)])
        assert detect_conflicts([_entry(a), _entry(b)]) == []

    def test_same_polarity_no_conflict(self) -> None:
        a = _result("sql", roots=[RootCause("orders 未落库", 0.8)])
        b = _result("log", roots=[RootCause("orders 缺失", 0.7)])
        assert detect_conflicts([_entry(a), _entry(b)]) == []

    def test_chinese_only_description_is_skipped(self) -> None:
        """抽不出英文对象名时宁可漏判——与协议的关键词策略保持一致。"""

        a = _result("sql", roots=[RootCause("订单未落库", 0.8)])
        b = _result("log", roots=[RootCause("订单已同步", 0.6)])
        assert detect_conflicts([_entry(a), _entry(b)]) == []


class TestSummary:
    def test_summary_counts_and_policy(self) -> None:
        a = _result("sql-diagnosis", roots=[RootCause("orders 未落库", 0.8)])
        b = _result("log-diagnosis", roots=[RootCause("orders 已同步", 0.6)])
        summary = summarize(detect_conflicts([_entry(a), _entry(b)]))
        assert summary["total"] == 1
        assert summary["unresolved"] == 1
        assert summary["internal"] == 0
        assert "不自动裁决" in summary["policy"]

    def test_empty_is_zero(self) -> None:
        summary = summarize(detect_conflicts([]))
        assert summary["total"] == 0
