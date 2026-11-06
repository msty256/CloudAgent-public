#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""诊断域停止评估器（变更 add-stop-decision-protocol）。

原先 ``InvestigationSession.decide()`` 把五条规则写成一个 if-else 序列（design D4）：
语义规则与预算规则耦合在同一个函数里，判定顺序写死，加一条规则就得改函数体。
这里把它们拆成五个评估器，注册进 :class:`cloudagent_ext.query.stop_decision.EvaluatorChain`：

===================  ===================================================
评估器                原规则
===================  ===================================================
``budget_exhausted``  ①总预算耗尽（含非诊断委派）→ 硬停（``hard=True``）
``gap_open``          ②最近一轮新增/复述了 open 缺口 → 继续
``blocked_only``      ③有缺口且全 blocked/inconclusive → 停
``success_recorded``  ④有成功结果且无 open 缺口 → 停
``budget_available``  ⑤其余 → 继续（**兜底，永远不弃权**）
===================  ===================================================

注册序 = 同 tier 内的优先级，因此链的构造顺序（:func:`build_default_chain`）
就是原 D4 的判定顺序，**不是**随便排的。其中 ② 必须先于 ③④：它俩的差异只在
"最近这轮是否刚产出缺口"，而这个信息只由 ② 负责消费。

语义等价性由 ``tests/diagnosis/test_stop_decision.py`` 的等价性表驱动用例锁死，
并受 ``tests/diagnosis/test_gap_orchestration.py::TestDecidePolicy``（未改一行）约束。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from cloudagent_ext.query.stop_decision import (
    ACTION_CONTINUE,
    ACTION_STOP,
    SCOPE_SESSION,
    EvaluatorChain,
    StopDecision,
)

if TYPE_CHECKING:  # 仅类型用途：避免 session.py ↔ evaluators.py 的运行时循环导入
    from cloudagent_ext.diagnosis.session import GapSummary

__all__ = [
    "DiagnosisStopContext",
    "BudgetExhaustedEvaluator",
    "OpenGapEvaluator",
    "BlockedOnlyEvaluator",
    "SuccessRecordedEvaluator",
    "FallbackContinueEvaluator",
    "build_default_chain",
]


@dataclass(frozen=True)
class DiagnosisStopContext:
    """一次停止决策所需的全部输入（只读快照，评估器不得回写）。

    刻意不把 ``InvestigationSession`` 直接传进来：评估器只看这几个量，
    这样"决策依赖什么"是显式的，加一个依赖就必须改这个 dataclass。
    """

    #: 缺口快照（由 ``runtime_session.gap_summary()`` 计算，会话层不持有缺口状态）
    gap_summary: "GapSummary"
    #: 已消耗委派次数（含非诊断委派，防绕过口径见 runtime_session）
    delegations_used: int
    #: 会话级上限
    max_delegations: int
    #: 是否已有至少一条子代理**自报** success 的结果
    has_success: bool


class BudgetExhaustedEvaluator:
    """①总预算耗尽 → 硬停。

    ``hard=True`` 是它与他人的根本差别：这是护栏，不允许被"还有缺口"之类的
    语义规则推翻。
    """

    name = "budget_exhausted"

    def evaluate(self, context: DiagnosisStopContext) -> StopDecision | None:
        if context.delegations_used >= context.max_delegations:
            return StopDecision(
                action=ACTION_STOP,
                scope=SCOPE_SESSION,
                hard=True,
                reason="budget_exhausted",
            )
        return None


class OpenGapEvaluator:
    """②最近一轮收割新增/复述了仍 open 的缺口 → 继续。"""

    name = "gap_open"

    def evaluate(self, context: DiagnosisStopContext) -> StopDecision | None:
        if context.gap_summary.recent_open_ids:
            return StopDecision(action=ACTION_CONTINUE, reason="gap_open")
        return None


class BlockedOnlyEvaluator:
    """③存在缺口且没有 open（blocked / inconclusive）→ 停。

    "存在缺口"这个前提是**必须**的：空列表上 ``all()`` 真空成立，
    会把"第一次就答对"误判成 ``blocked_only``。
    """

    name = "blocked_only"

    def evaluate(self, context: DiagnosisStopContext) -> StopDecision | None:
        if context.gap_summary.only_blocked:
            return StopDecision(action=ACTION_STOP, reason="blocked_only")
        return None


class SuccessRecordedEvaluator:
    """④已有成功结果且最近没有新缺口 → 停。

    注意这里的"成功"仍是子代理**自报**的 ``result.status``——独立核查是 B2 的事，
    本评估器不冒充核查。
    """

    name = "success_recorded"

    def evaluate(self, context: DiagnosisStopContext) -> StopDecision | None:
        if context.has_success and not context.gap_summary.recent_open_ids:
            return StopDecision(action=ACTION_STOP, reason="success_recorded")
        return None


class FallbackContinueEvaluator:
    """⑤兜底：继续。**永不弃权**——链上必须有一条"总得有个结论"的规则。"""

    name = "budget_available"

    def evaluate(self, context: DiagnosisStopContext) -> StopDecision | None:
        return StopDecision(action=ACTION_CONTINUE, reason="budget_available")


def build_default_chain() -> EvaluatorChain[DiagnosisStopContext]:
    """按 design D4 的判定顺序构造默认链（注册序即同级优先级）。"""

    return EvaluatorChain(
        [
            BudgetExhaustedEvaluator(),
            OpenGapEvaluator(),
            BlockedOnlyEvaluator(),
            SuccessRecordedEvaluator(),
            FallbackContinueEvaluator(),
        ]
    )
