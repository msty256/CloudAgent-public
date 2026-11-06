#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""域闸：把"这个域卡住了"变成一次可归因的拦截（阶段 1 · T1.2）。

**为什么需要它**：``blocked_only`` 早就被 ``decide()`` 算出来了，但 ``_agent_call`` 只用
``logger.debug`` 记一笔（`agent.py:722-725`），因为硬停会打断「log → sql」这类多域流程。
域闸解决的是这个两难：**停的是域，不是会话**——被拦的那次派发返回结构化 tool_result
告诉模型"换个域"，其他域照常。

三个判定档（``mode``）：

=============  ==================================================
``off``        只做域归因，不拦（等价当前行为）
``same_target`` 只在"本次 objective 覆盖某条 blocked/inconclusive
                缺口的**全部关键词**"时拦——拦的是**用同一个问法死磕
                已知取不到的证**
``strict``     该域只剩 blocked/inconclusive 就拦该域**一切**派发
=============  ==================================================

``same_target`` 是默认档。选它而不是 ``strict`` 的理由：论文的 ``Φ=blocked`` 是**任务级**
判定，我们是**域级**，粒度更细——blocked 意味着"这个问法推进不了"，不是"这个域死了"。
判据方向也不能反：反过来（objective 被缺口覆盖）几乎永不成立，而"有交集就拦"会误伤
正常的多目标派发。

``inconclusive`` 与 ``blocked`` 一起判，口径与 ``GapSummary.only_blocked`` 对齐
（那里也把两者都算"不可继续"）：复述多次仍无进展，同一问法再派大概率还是无进展。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from cloudagent_ext.diagnosis.models import GAP_STATUS_BLOCKED, GAP_STATUS_INCONCLUSIVE
from cloudagent_ext.diagnosis.text_match import contains_all, extract_keywords
from cloudagent_ext.query.stop_decision import (
    ACTION_STOP,
    SCOPE_DOMAIN,
    EvaluatorChain,
    StopDecision,
)

__all__ = [
    "GATE_MODE_OFF",
    "GATE_MODE_SAME_TARGET",
    "GATE_MODE_STRICT",
    "GATE_MODES",
    "DIAGNOSIS_SUFFIX",
    "domain_of",
    "DomainGateContext",
    "DomainQuotaEvaluator",
    "BlockedDomainEvaluator",
    "build_domain_chain",
]

GATE_MODE_OFF: str = "off"
GATE_MODE_SAME_TARGET: str = "same_target"
GATE_MODE_STRICT: str = "strict"
GATE_MODES: frozenset[str] = frozenset(
    {GATE_MODE_OFF, GATE_MODE_SAME_TARGET, GATE_MODE_STRICT}
)

#: 诊断子代理的类型后缀（``sql-diagnosis`` → ``sql``）
DIAGNOSIS_SUFFIX: str = "-diagnosis"

#: 视为"卡住"的状态（与 ``GapSummary.only_blocked`` 口径一致）
_STUCK_STATUSES: frozenset[str] = frozenset({GAP_STATUS_BLOCKED, GAP_STATUS_INCONCLUSIVE})


def domain_of(agent_type: str) -> str:
    """把委派类型归成域短名：``code-diagnosis`` → ``code``。

    非诊断类型（``fork`` / ``general-purpose``）原样返回——它们没有域语义，
    交给调用方决定要不要当"未归因"处理。
    """

    text = str(agent_type or "").strip()
    if text.endswith(DIAGNOSIS_SUFFIX):
        return text[: -len(DIAGNOSIS_SUFFIX)]
    return text


@dataclass(frozen=True)
class DomainGateContext:
    """一次域闸判定所需的全部输入（只读快照）。

    ``mode`` 放在上下文而不是评估器上：评估器保持无状态，配置一变换上下文即可。
    """

    domain: str
    objective: str
    #: 该域的缺口（调用方按域过滤后传入）
    gaps: tuple = ()
    #: 该域已用委派次数
    used: int = 0
    #: 该域配额（``None`` = 不设配额）
    quota: int | None = None
    mode: str = GATE_MODE_SAME_TARGET

    def stuck_gaps(self) -> tuple:
        return tuple(gap for gap in self.gaps if getattr(gap, "status", "") in _STUCK_STATUSES)


class DomainQuotaEvaluator:
    """域配额用尽 → 域级硬停。

    ``hard=True`` 表示这是不可协商的护栏（对应论文的 ``g_cap``）。它只在**域链**里排序，
    不影响会话链——两条链各自折叠（见 ``runtime_session.domain_gate``）。

    ``reason`` 带 ``已用/上限``，照 ``_apply_hard_limits`` 的 ``max_attempts_exhausted: n/m``
    做法给一个可读证据串，而不是只给一个枚举。
    """

    name = "domain_quota"

    def evaluate(self, context: DomainGateContext) -> StopDecision | None:
        quota = context.quota
        if quota is None or quota <= 0:
            return None
        if context.used < quota:
            return None
        return StopDecision(
            action=ACTION_STOP,
            scope=SCOPE_DOMAIN,
            domain=context.domain,
            hard=True,
            reason=f"domain_quota_exhausted:{context.used}/{quota}",
        )


class BlockedDomainEvaluator:
    """该域卡住且本次任务仍在问同一件事 → 域级拦停。

    三档语义见模块 docstring。``off`` 与"没有卡住的缺口"都弃权（返回 ``None``）。
    """

    name = "domain_blocked"

    def evaluate(self, context: DomainGateContext) -> StopDecision | None:
        mode = context.mode
        if mode not in (GATE_MODE_SAME_TARGET, GATE_MODE_STRICT):
            return None
        stuck = context.stuck_gaps()
        if not stuck:
            return None

        if mode == GATE_MODE_STRICT:
            return StopDecision(
                action=ACTION_STOP,
                scope=SCOPE_DOMAIN,
                domain=context.domain,
                reason=f"domain_blocked:{len(stuck)}",
            )

        for gap in stuck:
            keywords = extract_keywords(getattr(gap, "statement", ""))
            if not keywords:
                # 抽不出结构化关键词 → 无法判断"是否同一件事"，保守放行
                continue
            if contains_all(context.objective, keywords, normalize=True):
                return StopDecision(
                    action=ACTION_STOP,
                    scope=SCOPE_DOMAIN,
                    domain=context.domain,
                    reason=f"domain_blocked:{getattr(gap, 'gap_id', '')}",
                )
        return None


def build_domain_chain() -> EvaluatorChain[DomainGateContext]:
    """域链：配额（硬）优先于 blocked 判定。注册序即同级优先级。"""

    return EvaluatorChain([DomainQuotaEvaluator(), BlockedDomainEvaluator()])


def stuck_count(gaps: Iterable) -> int:
    """辅助：数一下有多少条缺口处于"卡住"状态（渲染与统计用）。"""

    return sum(1 for gap in gaps if getattr(gap, "status", "") in _STUCK_STATUSES)


def gate_blocks_any(gaps: Sequence) -> bool:
    """该域是否处于"全卡住"（渲染用；与 ``GapSummary.only_blocked`` 同口径前提）。"""

    items = list(gaps)
    return bool(items) and all(
        getattr(gap, "status", "") in _STUCK_STATUSES for gap in items
    )
