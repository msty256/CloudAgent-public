#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""域闸测试（阶段 1 · T1.5）。

三组断言：

1. **判据**：三档（off / same_target / strict）各自的拦截条件，纯函数、无 I/O；
2. **不误伤**：一个域被拦时，其他域照常派发，且被拦的派发**不消耗预算**；
3. **归因**：缺口能落到域上（``source_domain``），``gap_summary(domain)`` 能按域切分。

``same_target`` 的判据是"objective 覆盖某条 blocked/inconclusive 缺口的**全部关键词**"，
所以下面用 ``_SUBAGENT_BLOCKED``（limitations = "缺 Kafka 消费位点权限"，关键词 ``kafka``）
配两种 prompt：带 kafka 的会被拦，不带的不受影响。
"""

from __future__ import annotations

import pytest

from cloudagent_ext.diagnosis.domain_gate import (
    GATE_MODE_OFF,
    GATE_MODE_SAME_TARGET,
    GATE_MODE_STRICT,
    BlockedDomainEvaluator,
    DomainGateContext,
    DomainQuotaEvaluator,
    build_domain_chain,
    domain_of,
)
from cloudagent_ext.diagnosis.models import DiagnosisRequest, DiagnosisResult, Gap
from cloudagent_ext.diagnosis.runtime_session import (
    DiagnosisSessionRuntime,
    default_domain_quota,
    domain_gate_mode,
    harvest_gaps,
)
from cloudagent_ext.diagnosis.session import InvestigationSession, SessionBudget
from tests.diagnosis.test_gap_orchestration import _LoopProvider, _SUBAGENT_BLOCKED

BLOCKED_STATEMENT = "缺 Kafka 消费位点权限"


def _rt(*, budget: SessionBudget | None = None) -> DiagnosisSessionRuntime:
    return DiagnosisSessionRuntime(
        session=InvestigationSession(
            DiagnosisRequest(request_id="req-1", question="q"),
            budget=budget or SessionBudget(9, 9),
        )
    )


def _blocked_gap(gap_id: str = "gap-1", *, domain: str = "code-diagnosis") -> Gap:
    return Gap(
        gap_id=gap_id,
        statement=BLOCKED_STATEMENT,
        status="blocked",
        source_domain=domain,
    )


def _ctx(**kwargs) -> DomainGateContext:
    base = dict(
        domain="code",
        objective="查 Kafka 消费位点",
        gaps=(_blocked_gap(),),
        used=0,
        quota=None,
        mode=GATE_MODE_SAME_TARGET,
    )
    base.update(kwargs)
    return DomainGateContext(**base)


# ---------------------------------------------------------------------------
# 归因
# ---------------------------------------------------------------------------


class TestDomainOf:
    @pytest.mark.parametrize(
        "agent_type,expected",
        [
            ("code-diagnosis", "code"),
            ("sql-diagnosis", "sql"),
            ("log-diagnosis", "log"),
            ("fork", "fork"),
            ("general-purpose", "general-purpose"),
            ("", ""),
        ],
    )
    def test_mapping(self, agent_type: str, expected: str) -> None:
        assert domain_of(agent_type) == expected


class TestGapAttribution:
    def test_harvest_records_source_domain(self) -> None:
        rt = _rt()
        harvest_gaps(
            rt,
            DiagnosisResult(
                request_id="req-1",
                agent_name="code-diagnosis",
                status="success",
                summary="s",
                limitations=[BLOCKED_STATEMENT],
            ),
            domain="code-diagnosis",
        )
        assert rt.gaps[0].source_domain == "code-diagnosis"

    def test_gap_summary_filters_by_domain(self) -> None:
        rt = _rt()
        for gap in (
            _blocked_gap("gap-1", domain="code-diagnosis"),
            Gap(gap_id="gap-2", statement="核对 orders 表 order-1", status="open", source_domain="sql-diagnosis"),
        ):
            rt.gap_store.add_existing(gap)
        assert rt.gap_summary("code").total == 1
        assert rt.gap_summary("sql").total == 1
        assert rt.gap_summary().total == 2  # 全量口径不变

    def test_unattributed_gap_only_in_full_summary(self) -> None:
        rt = _rt()
        rt.gap_store.add_existing(Gap(gap_id="gap-1", statement="核对 orders 表 order-1", status="open"))
        assert rt.gap_summary("code").total == 0
        assert rt.gap_summary().total == 1

    def test_backfill_on_reharvest(self) -> None:
        """老缺口（无域）再次被收割时应补上归因，而不是永远"未归因"。"""

        rt = _rt()
        harvest_gaps(rt, DiagnosisResult(
            request_id="req-1", agent_name="code-diagnosis", status="success", summary="s",
            limitations=[BLOCKED_STATEMENT],
        ))
        assert rt.gaps[0].source_domain == ""
        harvest_gaps(
            rt,
            DiagnosisResult(
                request_id="req-1", agent_name="code-diagnosis", status="success", summary="s",
                limitations=[BLOCKED_STATEMENT],
            ),
            domain="code-diagnosis",
        )
        assert rt.gaps[0].source_domain == "code-diagnosis"


# ---------------------------------------------------------------------------
# 判据：三档
# ---------------------------------------------------------------------------


class TestSameTargetJudge:
    def test_hits_when_objective_covers_gap_keywords(self) -> None:
        decision = BlockedDomainEvaluator().evaluate(_ctx(objective="再查一下 Kafka 消费位点"))
        assert decision is not None
        assert decision.should_continue is False
        assert decision.domain == "code"
        assert decision.reason.startswith("domain_blocked:")

    def test_passes_when_objective_is_about_something_else(self) -> None:
        # 现有测试 test_blocked_only_is_advisory 就是靠这条放行的
        assert BlockedDomainEvaluator().evaluate(_ctx(objective="查 orders 表是否有记录")) is None

    def test_passes_when_gap_has_no_keywords(self) -> None:
        gap = Gap(gap_id="g", statement="确认下游是否已收到", status="blocked", source_domain="code-diagnosis")
        assert BlockedDomainEvaluator().evaluate(_ctx(gaps=(gap,), objective="确认下游")) is None

    def test_ignores_open_gaps(self) -> None:
        gap = Gap(gap_id="g", statement="核对 Kafka 位点", status="open", source_domain="code-diagnosis")
        assert BlockedDomainEvaluator().evaluate(_ctx(gaps=(gap,), objective="核对 Kafka 位点")) is None

    def test_inconclusive_also_counts(self) -> None:
        gap = Gap(gap_id="g", statement=BLOCKED_STATEMENT, status="inconclusive", source_domain="code")
        assert BlockedDomainEvaluator().evaluate(_ctx(gaps=(gap,), objective="查 Kafka")) is not None


class TestStrictJudge:
    def test_blocks_any_dispatch_when_domain_is_stuck(self) -> None:
        decision = BlockedDomainEvaluator().evaluate(
            _ctx(mode=GATE_MODE_STRICT, objective="查 orders 表")
        )
        assert decision is not None and decision.domain == "code"

    def test_passes_when_not_stuck(self) -> None:
        gap = Gap(gap_id="g", statement="x", status="open", source_domain="code")
        assert BlockedDomainEvaluator().evaluate(_ctx(mode=GATE_MODE_STRICT, gaps=(gap,))) is None


class TestOffMode:
    def test_off_never_blocks(self) -> None:
        assert BlockedDomainEvaluator().evaluate(_ctx(mode=GATE_MODE_OFF)) is None
        assert BlockedDomainEvaluator().evaluate(
            _ctx(mode=GATE_MODE_OFF, objective="查 Kafka")
        ) is None


class TestQuota:
    def test_blocks_at_limit_with_readable_reason(self) -> None:
        decision = DomainQuotaEvaluator().evaluate(_ctx(used=3, quota=3))
        assert decision is not None
        assert decision.hard is True
        assert decision.reason == "domain_quota_exhausted:3/3"

    def test_passes_below_limit(self) -> None:
        assert DomainQuotaEvaluator().evaluate(_ctx(used=2, quota=3)) is None

    def test_no_quota_means_off(self) -> None:
        assert DomainQuotaEvaluator().evaluate(_ctx(used=99, quota=None)) is None

    def test_quota_wins_over_blocked(self) -> None:
        """配额是硬约束，同时命中时应该它说了算（注册序 + hard 双保险）。"""

        decision = build_domain_chain().evaluate(_ctx(used=3, quota=3, objective="查 Kafka"))
        assert decision is not None
        assert decision.evaluator == "domain_quota"


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------


class TestConfig:
    def test_default_mode_is_same_target(self, monkeypatch) -> None:
        monkeypatch.delenv("CLOUDAGENT_DOMAIN_GATE", raising=False)
        assert domain_gate_mode() == GATE_MODE_SAME_TARGET

    def test_invalid_mode_falls_back(self, monkeypatch) -> None:
        monkeypatch.setenv("CLOUDAGENT_DOMAIN_GATE", "bogus")
        assert domain_gate_mode() == GATE_MODE_SAME_TARGET

    def test_zero_quota_means_disabled(self, monkeypatch) -> None:
        monkeypatch.setenv("CLOUDAGENT_DIAGNOSIS_DOMAIN_MAX_DELEGATIONS", "0")
        assert default_domain_quota() is None

    def test_default_quota(self, monkeypatch) -> None:
        monkeypatch.delenv("CLOUDAGENT_DIAGNOSIS_DOMAIN_MAX_DELEGATIONS", raising=False)
        assert default_domain_quota() == 3


# ---------------------------------------------------------------------------
# 集成：真实 Agent 工具 + 多域不误伤
# ---------------------------------------------------------------------------


def _agent_tool(tmp_path):
    from cloudagent_ext.tool_system.context import ToolContext
    from cloudagent_ext.tool_system.defaults import build_default_registry

    provider = _LoopProvider(_SUBAGENT_BLOCKED)
    registry = build_default_registry(provider=provider, load_agent_tools=False)
    context = ToolContext(workspace_root=tmp_path)
    context.tool_registry = registry
    tool = registry.get("Agent")
    assert tool is not None
    return tool, context


class TestDispatchIntegration:
    def test_same_target_blocked_other_domain_passes(self, tmp_path, monkeypatch) -> None:
        # 只测 blocked 判据，配额关掉（否则第三次派发会被配额拦，混淆结论）
        monkeypatch.setenv("CLOUDAGENT_DIAGNOSIS_DOMAIN_MAX_DELEGATIONS", "0")
        monkeypatch.setenv("CLOUDAGENT_DOMAIN_GATE", GATE_MODE_SAME_TARGET)
        tool, context = _agent_tool(tmp_path)

        # ① code 域第一次派发：产出 blocked 缺口
        first = tool.call(
            {"description": "d1", "prompt": "查 Kafka 消费位点", "subagent_type": "code-diagnosis"},
            context,
        )
        assert first.is_error is False, first.output
        runtime = context.diagnosis_session_runtime
        assert runtime.gaps and runtime.gaps[0].status == "blocked"
        assert runtime.gaps[0].source_domain == "code-diagnosis"
        used_after_first = runtime.session.delegations_used

        # ② 同一问法再派 code：被域闸拦下
        second = tool.call(
            {"description": "d2", "prompt": "再查一次 Kafka 消费位点", "subagent_type": "code-diagnosis"},
            context,
        )
        assert second.is_error is True
        assert second.output["error_type"] == "DomainGated"
        assert second.output["domain"] == "code"
        assert second.output["status"] == "error" and second.output["error"]
        assert "Kafka" in second.output["error"]
        # 被拦的派发不消耗预算
        assert runtime.session.delegations_used == used_after_first
        assert runtime.domain_blocks == {"code": 1}

        # ③ 换一个域、换一个问题：照常放行
        third = tool.call(
            {"description": "d3", "prompt": "查 orders 表是否有记录", "subagent_type": "log-diagnosis"},
            context,
        )
        assert third.is_error is False, third.output
        assert runtime.session.delegations_used == used_after_first + 1

    def test_gate_off_restores_old_behaviour(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("CLOUDAGENT_DIAGNOSIS_DOMAIN_MAX_DELEGATIONS", "0")
        monkeypatch.setenv("CLOUDAGENT_DOMAIN_GATE", GATE_MODE_OFF)
        tool, context = _agent_tool(tmp_path)

        tool.call(
            {"description": "d1", "prompt": "查 Kafka 消费位点", "subagent_type": "code-diagnosis"},
            context,
        )
        again = tool.call(
            {"description": "d2", "prompt": "再查一次 Kafka 消费位点", "subagent_type": "code-diagnosis"},
            context,
        )
        assert again.is_error is False, again.output
        assert context.diagnosis_session_runtime.domain_blocks == {}

    def test_quota_blocks_domain_but_not_others(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("CLOUDAGENT_DOMAIN_GATE", GATE_MODE_OFF)  # 只测配额
        monkeypatch.setenv("CLOUDAGENT_DIAGNOSIS_DOMAIN_MAX_DELEGATIONS", "1")
        tool, context = _agent_tool(tmp_path)

        first = tool.call(
            {"description": "d1", "prompt": "查 A 表", "subagent_type": "code-diagnosis"}, context
        )
        assert first.is_error is False, first.output

        blocked = tool.call(
            {"description": "d2", "prompt": "查 B 表", "subagent_type": "code-diagnosis"}, context
        )
        assert blocked.is_error is True
        assert blocked.output["error_type"] == "DomainGated"
        assert blocked.output["reason"] == "domain_quota_exhausted:1/1"

        other = tool.call(
            {"description": "d3", "prompt": "查 C 表", "subagent_type": "log-diagnosis"}, context
        )
        assert other.is_error is False, other.output
