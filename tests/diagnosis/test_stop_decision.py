#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""停止决策协议与评估器链测试（变更 add-stop-decision-protocol）。

三组断言：

1. **折叠是纯函数且确定**：优先级 hard > domain > session，同级按注册序；
2. **语义等价**：``EvaluatorChain`` 的输出与改造前 ``decide()`` 的 if-else 逐条等价
   （表驱动，覆盖预算 × 缺口形态 × 是否已有成功结果的全组合）——
   等价性用例是这次重构唯一的行为契约，允许它随设计变更而改，不允许它悄悄变绿；
3. **归因**：``reason`` 之外还要能回答"谁做的决定"。
"""

from __future__ import annotations

import ast
from itertools import product
from pathlib import Path

import pytest

from cloudagent_ext.diagnosis.evaluators import (
    BudgetExhaustedEvaluator,
    DiagnosisStopContext,
    FallbackContinueEvaluator,
    OpenGapEvaluator,
    SuccessRecordedEvaluator,
    build_default_chain,
)
from cloudagent_ext.diagnosis.models import DiagnosisRequest, DiagnosisResult
from cloudagent_ext.diagnosis.session import GapSummary, InvestigationSession, SessionBudget
from cloudagent_ext.query.stop_decision import (
    ACTION_CONTINUE,
    ACTION_STOP,
    SCOPE_DOMAIN,
    SCOPE_SESSION,
    EvaluatorChain,
    StopDecision,
    decision_tier,
    fold_decisions,
)

import cloudagent_ext.query.stop_decision as stop_decision_module


def _ctx(
    *,
    gaps: GapSummary | None = None,
    used: int = 0,
    limit: int = 15,
    has_success: bool = False,
) -> DiagnosisStopContext:
    return DiagnosisStopContext(
        gap_summary=gaps or GapSummary(),
        delegations_used=used,
        max_delegations=limit,
        has_success=has_success,
    )


class TestStopDecisionValue:
    def test_rejects_unknown_action(self) -> None:
        with pytest.raises(ValueError):
            StopDecision(action="maybe")

    def test_rejects_unknown_scope(self) -> None:
        with pytest.raises(ValueError):
            StopDecision(action=ACTION_STOP, scope="galaxy", domain="sql")

    def test_domain_scope_requires_domain(self) -> None:
        with pytest.raises(ValueError):
            StopDecision(action=ACTION_STOP, scope=SCOPE_DOMAIN)
        assert StopDecision(action=ACTION_STOP, scope=SCOPE_DOMAIN, domain="sql").is_stop

    def test_should_continue_property(self) -> None:
        assert StopDecision(action=ACTION_CONTINUE).should_continue is True
        assert StopDecision(action=ACTION_STOP).should_continue is False


class TestFoldPriority:
    def test_empty_returns_none(self) -> None:
        assert fold_decisions([]) is None

    def test_hard_beats_everything(self) -> None:
        session_continue = StopDecision(action=ACTION_CONTINUE, reason="weak")
        domain_stop = StopDecision(
            action=ACTION_STOP, scope=SCOPE_DOMAIN, domain="sql", reason="domain"
        )
        hard_stop = StopDecision(
            action=ACTION_STOP, scope=SCOPE_SESSION, hard=True, reason="budget_exhausted"
        )
        folded = fold_decisions([session_continue, domain_stop, hard_stop])
        assert folded is not None and folded.reason == "budget_exhausted"

    def test_domain_stop_beats_session_rules(self) -> None:
        session_continue = StopDecision(action=ACTION_CONTINUE, reason="weak")
        domain_stop = StopDecision(
            action=ACTION_STOP, scope=SCOPE_DOMAIN, domain="sql", reason="domain"
        )
        folded = fold_decisions([session_continue, domain_stop])
        assert folded is not None and folded.reason == "domain"

    def test_same_tier_keeps_registration_order(self) -> None:
        first = StopDecision(action=ACTION_CONTINUE, reason="first")
        second = StopDecision(action=ACTION_STOP, reason="second")
        folded = fold_decisions([first, second])
        assert folded is not None and folded.reason == "first"

    def test_tier_mapping(self) -> None:
        assert decision_tier(StopDecision(action=ACTION_STOP, hard=True)) == 0
        assert (
            decision_tier(StopDecision(action=ACTION_STOP, scope=SCOPE_DOMAIN, domain="sql"))
            == 1
        )
        assert decision_tier(StopDecision(action=ACTION_STOP)) == 2

    def test_fold_is_pure(self) -> None:
        decisions = [StopDecision(action=ACTION_STOP), StopDecision(action=ACTION_CONTINUE)]
        snapshot = list(decisions)
        fold_decisions(decisions)
        assert decisions == snapshot  # 入参未被排序/篡改


class TestEvaluatorChain:
    def test_empty_chain_rejected(self) -> None:
        with pytest.raises(ValueError):
            EvaluatorChain([])

    def test_duplicate_names_rejected(self) -> None:
        a = BudgetExhaustedEvaluator()
        b = BudgetExhaustedEvaluator()
        with pytest.raises(ValueError):
            EvaluatorChain([a, b])

    def test_attribution_is_filled_by_chain(self) -> None:
        decision = build_default_chain().evaluate(_ctx(used=15))
        assert decision is not None
        assert decision.reason == "budget_exhausted"
        assert decision.evaluator == "budget_exhausted"

    def test_registration_order_is_visible(self) -> None:
        assert build_default_chain().names == (
            "budget_exhausted",
            "gap_open",
            "blocked_only",
            "success_recorded",
            "budget_available",
        )

    def test_all_abstain_returns_none(self) -> None:
        class _Abstain:
            name = "abstain"

            def evaluate(self, context: DiagnosisStopContext) -> StopDecision | None:
                return None

        assert EvaluatorChain([_Abstain()]).evaluate(_ctx()) is None


class TestSingleEvaluators:
    def test_budget_evaluator(self) -> None:
        ev = BudgetExhaustedEvaluator()
        assert ev.evaluate(_ctx(used=14, limit=15)) is None
        decision = ev.evaluate(_ctx(used=15, limit=15))
        assert decision is not None and decision.hard is True

    def test_open_gap_evaluator(self) -> None:
        ev = OpenGapEvaluator()
        assert ev.evaluate(_ctx()) is None
        decision = ev.evaluate(
            _ctx(gaps=GapSummary(total=1, open_ids=("g1",), recent_open_ids=("g1",)))
        )
        assert decision is not None and decision.should_continue is True

    def test_success_evaluator(self) -> None:
        ev = SuccessRecordedEvaluator()
        assert ev.evaluate(_ctx(has_success=False)) is None
        decision = ev.evaluate(_ctx(has_success=True))
        assert decision is not None and decision.reason == "success_recorded"

    def test_fallback_never_abstains(self) -> None:
        decision = FallbackContinueEvaluator().evaluate(_ctx())
        assert decision is not None and decision.reason == "budget_available"


# ---------------------------------------------------------------------------
# 等价性：改造前的 if-else（逐字保留）vs 改造后的评估器链
# ---------------------------------------------------------------------------

_GAP_SHAPES: dict[str, GapSummary] = {
    "no_gaps": GapSummary(),
    "open_recent": GapSummary(total=1, open_ids=("g1",), recent_open_ids=("g1",)),
    "open_not_recent": GapSummary(total=1, open_ids=("g1",)),
    "blocked_only": GapSummary(total=2, blocked_ids=("g1", "g2")),
    "resolved_only": GapSummary(total=1),
    "open_and_blocked": GapSummary(
        total=2, open_ids=("g1",), blocked_ids=("g2",)
    ),
}


def _legacy_decide(ctx: DiagnosisStopContext) -> tuple[bool, str]:
    """改造前的五条 if-else（``InvestigationSession.decide()`` 原文语义）。"""

    if ctx.delegations_used >= ctx.max_delegations:
        return False, "budget_exhausted"

    summary = ctx.gap_summary
    if summary.recent_open_ids:
        return True, "gap_open"
    if summary.only_blocked:
        return False, "blocked_only"

    if ctx.has_success and not summary.recent_open_ids:
        return False, "success_recorded"
    return True, "budget_available"


class TestEquivalenceWithLegacy:
    @pytest.mark.parametrize(
        "shape,used,has_success",
        list(product(_GAP_SHAPES, (0, 14, 15), (False, True))),
    )
    def test_chain_matches_legacy(self, shape: str, used: int, has_success: bool) -> None:
        ctx = _ctx(gaps=_GAP_SHAPES[shape], used=used, limit=15, has_success=has_success)
        decision = build_default_chain().evaluate(ctx)
        assert decision is not None
        assert (decision.should_continue, decision.reason) == _legacy_decide(ctx)
        # 归因必须与 reason 一致（同一评估器既决定动作也署名）
        assert decision.evaluator == decision.reason

    def test_missing_total_falls_back_to_entries(self) -> None:
        """``total_delegations=None`` 时必须退回轨迹条目数（原实现语义）。"""

        session = InvestigationSession(
            DiagnosisRequest(request_id="req-1", question="q"), budget=SessionBudget(1, 1)
        )
        session.delegate("code-diagnosis", "查 A")
        assert session.decide().reason == "budget_exhausted"


class TestDecideSurface:
    def test_reason_and_evaluator_surface(self) -> None:
        session = InvestigationSession(
            DiagnosisRequest(request_id="req-1", question="q"), budget=SessionBudget(5, 2)
        )
        assert session.decide().reason == "budget_available"
        assert session.decide().evaluator == "budget_available"

    def test_success_surfaces_evaluator(self) -> None:
        session = InvestigationSession(
            DiagnosisRequest(request_id="req-1", question="q"), budget=SessionBudget(5, 2)
        )
        task = session.delegate("code-diagnosis", "查 A")
        session.record_result(
            DiagnosisResult(
                request_id="req-1",
                agent_name="code-diagnosis",
                status="success",
                summary="ok",
                task_id=task.task_id,
            )
        )
        decision = session.decide()
        assert decision.reason == "success_recorded"
        assert decision.evaluator == "success_recorded"


class TestGenericLayerPurity:
    def test_protocol_module_does_not_import_domain_layer(self) -> None:
        """通用层不得依赖领域层（含类型注解里的运行期依赖）。

        用 AST 检查真实 import 语句而不是文本搜索——docstring 里提到
        ``cloudagent_ext.diagnosis`` 是允许的（那是引用说明，不是依赖）。
        """

        source = Path(stop_decision_module.__file__).read_text(encoding="utf-8")
        imported: list[str] = []
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        offenders = [name for name in imported if name.startswith("cloudagent_ext.diagnosis")]
        assert offenders == [], f"通用层反向依赖了领域层：{offenders}"
