#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""统一停止决策协议 + 确定性折叠（变更 add-stop-decision-protocol）。

**为什么在通用层**：仓库里原先有三套互不相通的决策词汇——

* :class:`cloudagent_ext.diagnosis.session.SessionDecision`（``should_continue`` + ``reason``）
* :class:`cloudagent_ext.query.token_budget.ContinueDecision` / ``StopDecision``
* :class:`cloudagent_ext.services.context_collapse.trigger.CollapseDecision`

三者的判定口径各自硬编码在各自的函数里，无法横向比较、无法归因。本模块只定义
**最小公共协议**（:class:`StopDecision`）与**纯函数折叠**（:func:`fold_decisions`），
不理解任何领域的业务语义：具体评估器由各域自己实现
（诊断域见 :mod:`cloudagent_ext.diagnosis.evaluators`）。

折叠规则（design A1）：

1. ``hard`` 约束（预算这类不可协商的护栏）优先，其次**域级** stop，最后会话级启发；
2. 同一层内**按注册序**取第一个非弃权决策——``sorted`` 是稳定排序，同级自然保持
   评估器的注册顺序，因此"注册序即优先级"这件事写在链的构造处，而不是散落在 if-else；
3. 每次**全量**评估后再折叠，不做短路：这样"当时还有哪些评估器认为可以继续"
   同样可观测，停止原因可统计。

参照：openJiuwen ``harness/rails/task_completion_rail.py`` 的 ``build_evaluators()``
（MaxRounds / Timeout / CompletionPromise 组成有序链，语义停止与硬限制统一为可插拔
评估器）。本模块只取"有序链 + 确定性裁决"这一形态，不引入该仓库的 Rail 体系。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Generic, Protocol, Sequence, TypeVar, runtime_checkable

__all__ = [
    "ACTION_CONTINUE",
    "ACTION_STOP",
    "SCOPE_DELEGATION",
    "SCOPE_DOMAIN",
    "SCOPE_SESSION",
    "TIER_HARD",
    "TIER_DOMAIN",
    "TIER_SESSION",
    "StopDecision",
    "decision_tier",
    "fold_decisions",
    "StopEvaluator",
    "EvaluatorChain",
]

ACTION_CONTINUE: str = "continue"
ACTION_STOP: str = "stop"
_ACTIONS: frozenset[str] = frozenset({ACTION_CONTINUE, ACTION_STOP})

#: 一次委派（单个子任务）：最细粒度，仅影响"这一次派发"。
SCOPE_DELEGATION: str = "delegation"
#: 一个域（sql / log / code…）：影响该域后续所有派发，其他域不受影响。
SCOPE_DOMAIN: str = "domain"
#: 整个会话：影响所有后续派发。
SCOPE_SESSION: str = "session"
_SCOPES: frozenset[str] = frozenset({SCOPE_DELEGATION, SCOPE_DOMAIN, SCOPE_SESSION})

# 折叠梯队：数字越小越先被采纳。
TIER_HARD: int = 0
TIER_DOMAIN: int = 1
TIER_SESSION: int = 2


@dataclass(frozen=True)
class StopDecision:
    """一个评估器给出的单条决策（不带任何领域字段）。

    字段与 design A1 一一对应：``action`` / ``scope`` / ``hard`` / ``domain`` /
    ``reason`` / ``evaluator``。``evaluator`` 由 :class:`EvaluatorChain` 统一补全，
    评估器自己不需要（也不应该）填——归因只允许有一个来源。
    """

    action: str
    scope: str = SCOPE_SESSION
    hard: bool = False
    domain: str | None = None
    reason: str = ""
    evaluator: str = ""

    def __post_init__(self) -> None:
        if self.action not in _ACTIONS:
            raise ValueError(f"action must be one of {sorted(_ACTIONS)}, got {self.action!r}")
        if self.scope not in _SCOPES:
            raise ValueError(f"scope must be one of {sorted(_SCOPES)}, got {self.scope!r}")
        if self.scope != SCOPE_SESSION and not (self.domain or "").strip():
            raise ValueError(
                f"scope={self.scope!r} requires a non-empty domain "
                "(domain-scoped decisions must say which domain they apply to)"
            )

    @property
    def should_continue(self) -> bool:
        return self.action == ACTION_CONTINUE

    @property
    def is_stop(self) -> bool:
        return self.action == ACTION_STOP


def decision_tier(decision: StopDecision) -> int:
    """折叠梯队：hard 约束 → 域级 → 会话级。"""

    if decision.hard:
        return TIER_HARD
    if decision.scope in (SCOPE_DOMAIN, SCOPE_DELEGATION):
        return TIER_DOMAIN
    return TIER_SESSION


def fold_decisions(decisions: Sequence[StopDecision]) -> StopDecision | None:
    """确定性折叠：纯函数，无副作用、无 I/O、不读时钟。

    返回值语义：``None`` 表示**所有评估器都弃权**（没有意见）。调用方须自己决定
    这种状态怎么处理——本函数不发明默认行为。

    ``sorted`` 的稳定性是"同级按注册序"的全部实现：同一 tier 内保持入参顺序，
    而入参顺序就是评估器在链里的注册顺序。
    """

    if not decisions:
        return None
    return sorted(decisions, key=decision_tier)[0]


@runtime_checkable
class StopEvaluator(Protocol):
    """评估器：看当前状态，给出（或弃权）一条决策。

    * 弃权返回 ``None``——"我这条规则不适用"，不是"我同意继续"；
    * 禁止在 ``evaluate`` 里做 I/O 或改状态：快路径必须是确定性的
      （慢路径的 LLM 核查属于另一条通道，见 C2/B2）。
    """

    name: str

    def evaluate(self, context: object) -> StopDecision | None: ...


CtxT = TypeVar("CtxT")


class EvaluatorChain(Generic[CtxT]):
    """有序评估器链：全量评估 → 确定性折叠。

    链本身无状态（不累加、不记忆），因此可以安全地做成模块级常量被并发复用。
    """

    def __init__(self, evaluators: Sequence[StopEvaluator]) -> None:
        if not evaluators:
            raise ValueError("EvaluatorChain requires at least one evaluator")
        names = [str(getattr(ev, "name", "") or "") for ev in evaluators]
        for name in names:
            if not name:
                raise ValueError("every evaluator must declare a non-empty name")
        duplicated = {name for name in names if names.count(name) > 1}
        if duplicated:
            raise ValueError(f"duplicated evaluator names: {sorted(duplicated)}")
        self._evaluators: tuple[StopEvaluator, ...] = tuple(evaluators)

    @property
    def evaluators(self) -> tuple[StopEvaluator, ...]:
        return self._evaluators

    @property
    def names(self) -> tuple[str, ...]:
        """注册序（= 同级折叠时的优先级）。"""

        return tuple(str(ev.name) for ev in self._evaluators)

    def evaluate(self, context: CtxT) -> StopDecision | None:
        decisions: list[StopDecision] = []
        for evaluator in self._evaluators:
            decision = evaluator.evaluate(context)
            if decision is None:
                continue
            if not decision.evaluator:
                # 归因只允许有一个来源：链负责补名字，评估器不得自称。
                decision = replace(decision, evaluator=str(evaluator.name))
            decisions.append(decision)
        return fold_decisions(decisions)
