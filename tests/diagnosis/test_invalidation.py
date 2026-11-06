#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""证据失效传播测试（阶段 4 · T4.2 / T4.3）。

这组用例守的是一条**以前做不到**的能力：缺口状态能往回走。

改造前 `resolved` 一旦写入就再也改不回去，`blocked` 也没有解除路径——
于是"证据被推翻、但结论还挂着、且看起来一切正常"是必然结果。

两类断言：

1. **能回去**：冲突声明到达 → 依赖旧证据的 resolved 退回 open，原因写进 note；
2. **回得有限**：反复冲突到上限就转 inconclusive，不再无限循环
   （否则每轮都烧委派预算，模型一直被告知"重查同一件事"）。
"""

from __future__ import annotations

import pytest

from cloudagent_ext.diagnosis.gap_store import MAX_REVERTS, GapStore
from cloudagent_ext.diagnosis.models import (
    DiagnosisRequest,
    DiagnosisResult,
    Evidence,
    Gap,
)
from cloudagent_ext.diagnosis.runtime_session import (
    DiagnosisSessionRuntime,
    harvest_gaps,
    propagate_invalidation,
)
from cloudagent_ext.diagnosis.session import InvestigationSession, SessionBudget


def _runtime() -> DiagnosisSessionRuntime:
    session = InvestigationSession(
        DiagnosisRequest(request_id="req-1", question="q"), budget=SessionBudget(15, 5)
    )
    return DiagnosisSessionRuntime(session=session)


def _evidence(
    evidence_id: str,
    observation: str,
    *,
    conflicts_with: str | None = None,
) -> Evidence:
    relation = []
    if conflicts_with:
        relation = [{"kind": "conflict", "with": conflicts_with, "why": "计数对不上"}]
    return Evidence(
        evidence_id=evidence_id,
        source_type="sql",
        source_ref="orders",
        observation=observation,
        relation=relation,
    )


def _result(status: str = "success", *, evidences: list[Evidence] | None = None) -> DiagnosisResult:
    return DiagnosisResult(
        request_id="req-1",
        agent_name="code-diagnosis",
        status=status,
        summary="s",
        evidence=evidences or [],
        next_steps=[],
        limitations=[],
    )


def _resolved_gap(store: GapStore, gap_id: str, *, statement: str, evidence_id: str) -> Gap:
    gap = store.add_existing(Gap(gap_id=gap_id, statement=statement, status="open"))
    store.mark_resolved(gap.gap_id, evidence_id=evidence_id)
    assert gap.status == "resolved"
    return gap


class TestConflictRevertsResolved:
    def test_resolved_goes_back_to_open(self) -> None:
        runtime = _runtime()
        store = runtime.gap_store
        gap = _resolved_gap(store, "gap-1", statement="核对 orders 表 order-1", evidence_id="ev:sql:1")

        reverted = propagate_invalidation(
            runtime, _result(evidences=[_evidence("ev:sql:7", "count 由 0 变为 5", conflicts_with="ev:sql:1")])
        )

        assert reverted == 1
        assert gap.status == "open"
        assert "证据冲突" in gap.note
        assert "ev:sql:7" in gap.note and "ev:sql:1" in gap.note

    def test_event_recorded_as_invalidated(self) -> None:
        runtime = _runtime()
        store = runtime.gap_store
        _resolved_gap(store, "gap-1", statement="核对 orders 表 order-1", evidence_id="ev:sql:1")
        propagate_invalidation(
            runtime, _result(evidences=[_evidence("ev:sql:7", "x", conflicts_with="ev:sql:1")])
        )
        events = [e for e in runtime.gap_events if e["why"] == "invalidated"]
        assert len(events) == 1
        assert events[0]["from"] == "resolved" and events[0]["to"] == "open"
        assert events[0]["evidence_id"] == "ev:sql:7"

    def test_unrelated_gap_untouched(self) -> None:
        runtime = _runtime()
        store = runtime.gap_store
        keep = _resolved_gap(store, "gap-1", statement="核对 orders 表 order-1", evidence_id="ev:sql:1")
        other = _resolved_gap(store, "gap-2", statement="核对 orders 表 order-2", evidence_id="ev:sql:2")

        propagate_invalidation(
            runtime, _result(evidences=[_evidence("ev:sql:9", "x", conflicts_with="ev:sql:1")])
        )

        assert keep.status == "open"
        assert other.status == "resolved", "只该回退依赖该证据的那条"

    def test_open_gap_not_affected(self) -> None:
        """回退只针对 resolved——open 本来就在待取证，没有什么可退的。"""

        runtime = _runtime()
        runtime.gap_store.add_existing(Gap(gap_id="gap-1", statement="核对 orders 表 order-1", status="open"))
        reverted = propagate_invalidation(
            runtime, _result(evidences=[_evidence("ev:sql:7", "x", conflicts_with="ev:sql:1")])
        )
        assert reverted == 0

    def test_failed_does_not_propagate(self) -> None:
        """只有 success / partial 才传播——failed 的结果不该推动状态变更。"""

        self._assert_not_propagated("failed")

    def test_partial_does_propagate(self) -> None:
        """partial 也算"有可用观测"，冲突照样要传播。"""

        runtime = _runtime()
        gap = _resolved_gap(
            runtime.gap_store, "gap-1", statement="核对 orders 表 order-1", evidence_id="ev:sql:1"
        )
        reverted = propagate_invalidation(
            runtime,
            _result(status="partial", evidences=[_evidence("ev:sql:7", "x", conflicts_with="ev:sql:1")]),
        )
        assert reverted == 1
        assert gap.status == "open"

    def _assert_not_propagated(self, status: str) -> None:
        runtime = _runtime()
        store = runtime.gap_store
        gap = _resolved_gap(store, "gap-1", statement="核对 orders 表 order-1", evidence_id="ev:sql:1")
        reverted = propagate_invalidation(
            runtime,
            _result(status=status, evidences=[_evidence("ev:sql:7", "x", conflicts_with="ev:sql:1")]),
        )
        assert reverted == 0
        assert gap.status == "resolved"

    def test_no_relation_is_noop(self) -> None:
        runtime = _runtime()
        store = runtime.gap_store
        gap = _resolved_gap(store, "gap-1", statement="核对 orders 表 order-1", evidence_id="ev:sql:1")
        propagate_invalidation(runtime, _result(evidences=[_evidence("ev:sql:7", "只是补充观测")]))
        assert gap.status == "resolved"


class TestOscillationIsBounded:
    def test_reaches_inconclusive_after_limit(self) -> None:
        """反复回退到上限就放弃自动收敛。

        不加这条约束会形成 `resolved → 冲突 → open → 再 resolved → 再冲突` 的循环，
        每一轮都烧委派预算，模型也会一直被要求重查同一件事。
        """

        runtime = _runtime()
        store = runtime.gap_store
        gap = _resolved_gap(store, "gap-1", statement="核对 orders 表 order-1", evidence_id="ev:sql:1")

        for round_index in range(MAX_REVERTS):
            propagate_invalidation(
                runtime,
                _result(evidences=[_evidence(f"ev:sql:1{round_index}", "x", conflicts_with="ev:sql:1")]),
            )
            if round_index < MAX_REVERTS - 1:
                # 中间轮次：被判 open，然后又被"取证"核销
                assert gap.status == "open"
                store.mark_resolved(gap.gap_id, evidence_id="ev:sql:1")

        assert gap.status == "inconclusive"
        assert "放弃自动收敛" in gap.note
        assert gap.revert_count == MAX_REVERTS

    def test_revert_count_separate_from_restatements(self) -> None:
        """回退次数与复述次数分开记——混在一起会让震荡上限提前触发。"""

        runtime = _runtime()
        store = runtime.gap_store
        gap = _resolved_gap(store, "gap-1", statement="核对 orders 表 order-1", evidence_id="ev:sql:1")
        propagate_invalidation(
            runtime, _result(evidences=[_evidence("ev:sql:7", "x", conflicts_with="ev:sql:1")])
        )
        assert gap.revert_count == 1
        assert gap.restatements == 0


class TestForceVerifyAfterRevert:
    """T4.4：回退过的缺口再次 resolved，必须强制走独立核查。

    理由：那条结论**曾经被证据推翻过**。如果还用同一个关键词判定让它
    "再 resolved"一次，等于什么都没改变——快慢配对原则要求
    "传播走确定性快路径，收敛必须走核查慢路径"。
    """

    def test_should_verify_honours_forced_even_in_agent_report(self) -> None:
        from cloudagent_ext.diagnosis.assessor import (
            STRATEGY_AGENT_REPORT,
            STRATEGY_HYBRID,
            should_verify,
        )

        # 未被强制时：agent_report 从不核
        assert should_verify(strategy=STRATEGY_AGENT_REPORT, result_status="success") is False
        # 被强制时：无视策略
        assert (
            should_verify(strategy=STRATEGY_AGENT_REPORT, result_status="success", forced=True)
            is True
        )
        assert should_verify(strategy=STRATEGY_HYBRID, result_status="failed", forced=True) is True

    def test_reverted_gap_sets_force_flag(self) -> None:
        runtime = _runtime()
        store = runtime.gap_store
        gap = _resolved_gap(store, "gap-1", statement="核对 orders 表 order-1", evidence_id="ev:sql:1")

        # 先被推翻一次
        propagate_invalidation(
            runtime, _result(evidences=[_evidence("ev:sql:7", "x", conflicts_with="ev:sql:1")])
        )
        assert gap.status == "open" and gap.revert_count == 1
        assert runtime.force_verify_reason == ""

        # 再次被"取证"核销 → 应置强制核查标记
        harvest_gaps(
            runtime,
            _result(evidences=[_evidence("ev:sql:8", "orders 表 order-1 有记录，count=1")]),
        )
        assert gap.status == "resolved"
        assert runtime.force_verify_reason == "invalidated_then_resolved"

    def test_clean_gap_does_not_force(self) -> None:
        """从没被推翻过的缺口照旧——不然"强制核查"就等于全量核查了。"""

        runtime = _runtime()
        runtime.gap_store.add_existing(
            Gap(gap_id="gap-1", statement="核对 orders 表 order-1 是否有记录", status="open")
        )
        harvest_gaps(
            runtime,
            _result(evidences=[_evidence("ev:sql:1", "orders 表 order-1 有记录，count=1")]),
        )
        assert runtime.gap_store.gaps()[0].status == "resolved"
        assert runtime.force_verify_reason == ""

    def _blocked_gap(self, store: GapStore) -> Gap:
        gap = store.add_existing(
            Gap(gap_id="gap-1", statement="核对 orders 表 order-1 是否有记录", status="blocked")
        )
        return gap

    def test_coverage_releases_blocked_to_open(self) -> None:
        """覆盖性证据到达 → blocked 解成 open，**不是**直接 resolved。

        "能查了"不等于"已查清"。让它走正常流程，再次 resolved 还要过独立核查。
        """

        runtime = _runtime()
        gap = self._blocked_gap(runtime.gap_store)

        harvest_gaps(
            runtime,
            _result(evidences=[_evidence("ev:sql:1", "orders 表 order-1 有记录，count=1")]),
            domain="sql-diagnosis",
        )

        assert gap.status == "open"
        assert "解除阻塞" in gap.note
        released = [e for e in runtime.gap_events if e["why"] == "released"]
        assert len(released) == 1

    def test_open_still_resolves(self) -> None:
        """open 的现有行为不变：全覆盖直接 resolved。"""

        runtime = _runtime()
        gap = runtime.gap_store.add_existing(
            Gap(gap_id="gap-1", statement="核对 orders 表 order-1 是否有记录", status="open")
        )
        harvest_gaps(
            runtime,
            _result(evidences=[_evidence("ev:sql:1", "orders 表 order-1 有记录，count=1")]),
        )
        assert gap.status == "resolved"
