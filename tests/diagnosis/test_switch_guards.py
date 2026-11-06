#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""机制守卫：每个开关"关掉 ⇒ 行为消失"（P2a · 规格 T2a.3）。

判据（不许造假的守卫）：断言的是**行为差异**，不是"开关读到了什么"——
把开关的读取逻辑改坏，对应用例必须红（本地验证记录见 handoff）。

诚实边界：``goal_stop_strategy`` 的守卫标记 ``[strategy-layer-only]``——
离线只能守到"策略函数在该档位不调度核查"；"核查器确实没被调用"需要 live。

所有用例不依赖任何预先设置的 ``CLOUDAGENT_*`` 环境变量（monkeypatch 自带清理）。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from cloudagent_ext.diagnosis.assessor import (
    STRATEGY_AGENT_REPORT,
    STRATEGY_HYBRID,
    assessor_strategy,
    should_verify,
)
from cloudagent_ext.diagnosis.models import DiagnosisRequest, DiagnosisResult, Evidence, Gap
from cloudagent_ext.diagnosis.runtime_session import (
    DiagnosisSessionRuntime,
    propagate_invalidation,
)
from cloudagent_ext.diagnosis.session import InvestigationSession, SessionBudget
from cloudagent_ext.diagnosis.switches import SWITCHES, is_off
from cloudagent_ext.tool_system.tools.agent import _with_current_state, gap_injection_enabled


def _runtime() -> DiagnosisSessionRuntime:
    return DiagnosisSessionRuntime(
        session=InvestigationSession(
            DiagnosisRequest(request_id="req-1", question="q"), budget=SessionBudget(15, 5)
        )
    )


# ---------------------------------------------------------------------------
# 登记表自身健全（守卫的地基，不是行为守卫本身）
# ---------------------------------------------------------------------------


class TestRegistryShape:
    def test_five_switches_registered(self) -> None:
        assert set(SWITCHES) == {
            "context_reduce",
            "evidence_invalidation",
            "gap_injection",
            "domain_gate",
            "goal_stop_strategy",
        }

    @pytest.mark.parametrize("name", sorted(SWITCHES))
    def test_spec_shape(self, name: str) -> None:
        spec = SWITCHES[name]
        assert spec.name == name
        assert spec.env.startswith("CLOUDAGENT_")
        assert spec.kind in ("bool", "mode")
        assert spec.off_effect.strip(), "off_effect 必须写人话（守卫与报告都按它表述）"
        if spec.kind == "bool":
            assert spec.off_value is False
        else:
            assert spec.off_value in spec.modes

    @pytest.mark.parametrize("name", sorted(SWITCHES))
    def test_defaults_match_production(self, monkeypatch, name: str) -> None:
        """不设环境变量时一律不在"关"档——默认值即生产行为。"""

        monkeypatch.delenv(SWITCHES[name].env, raising=False)
        assert is_off(name) is False


# ---------------------------------------------------------------------------
# context_reduce：关掉 ⇒ 大结果不做结构归约
# ---------------------------------------------------------------------------


def _tool_messages() -> list:
    from cloudagent_ext.types.messages import create_assistant_message, create_user_message

    payload = {
        "mode": "rows",
        "table": "public.orders",
        "rows": [{"id": i, "amount": float(i * 10)} for i in range(1, 201)],
    }
    return [
        create_user_message("q"),
        create_assistant_message(
            [{"type": "tool_use", "id": "t1", "name": "query_table_rows", "input": {}}]
        ),
        create_user_message(
            [
                {
                    "type": "tool_result",
                    "tool_use_id": "t1",
                    "content": json.dumps(payload, ensure_ascii=False),
                    "metadata": {"output": payload},
                }
            ]
        ),
    ]


def _run_pipeline(tmp_path: Path):
    from cloudagent_ext.diagnosis.switches import context_reduce_enabled
    from cloudagent_ext.services.compact.pipeline import CompressionPipeline, PipelineConfig

    config = PipelineConfig(
        sr_enabled=context_reduce_enabled(),
        sr_session_id="req-1",
        sr_evidence_root=tmp_path,
        sr_keep_recent=0,
        sr_min_chars=500,
    )
    return asyncio.run(
        CompressionPipeline(config).run(_tool_messages(), input_token_count=0)
    )


class TestContextReduceBehavior:
    def test_default_on_reduces(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.delenv("CLOUDAGENT_CONTEXT_REDUCE", raising=False)
        assert "structural_reduce" in _run_pipeline(tmp_path).layers_applied

    def test_off_false_disables_reduction(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.setenv("CLOUDAGENT_CONTEXT_REDUCE", "false")
        result = _run_pipeline(tmp_path)
        assert "structural_reduce" not in result.layers_applied
        assert is_off("context_reduce") is True


# ---------------------------------------------------------------------------
# evidence_invalidation：关掉 ⇒ 冲突不再把 resolved 退回 open
# ---------------------------------------------------------------------------


def _conflict_result() -> DiagnosisResult:
    evidence = Evidence(
        evidence_id="ev:sql:7",
        source_type="sql",
        source_ref="orders",
        observation="count 由 0 变为 5",
        relation=[{"kind": "conflict", "with": "ev:sql:1"}],
    )
    return DiagnosisResult(
        request_id="req-1",
        agent_name="sql-diagnosis",
        status="success",
        summary="s",
        evidence=[evidence],
        next_steps=[],
        limitations=[],
    )


def _resolved(runtime: DiagnosisSessionRuntime) -> Gap:
    runtime.gap_store.add_existing(
        Gap(gap_id="gap-1", statement="核对 orders 表 order-1", status="open")
    )
    runtime.gap_store.mark_resolved("gap-1", evidence_id="ev:sql:1")
    return runtime.gap_store.gaps()[0]


class TestEvidenceInvalidationBehavior:
    def test_default_on_reverts(self, monkeypatch) -> None:
        monkeypatch.delenv("CLOUDAGENT_EVIDENCE_INVALIDATION", raising=False)
        runtime = _runtime()
        gap = _resolved(runtime)
        assert propagate_invalidation(runtime, _conflict_result()) == 1
        assert gap.status == "open"

    def test_off_zero_keeps_resolved(self, monkeypatch) -> None:
        monkeypatch.setenv("CLOUDAGENT_EVIDENCE_INVALIDATION", "0")
        runtime = _runtime()
        gap = _resolved(runtime)
        assert propagate_invalidation(runtime, _conflict_result()) == 0
        assert gap.status == "resolved", "声明关掉了，就不能再回退"
        assert gap.revert_count == 0
        assert is_off("evidence_invalidation") is True


# ---------------------------------------------------------------------------
# gap_injection：关掉 ⇒ 提示词不出现「当前有效状态」段（真 bug 修复的守卫）
# ---------------------------------------------------------------------------


class TestGapInjectionBehavior:
    def _prompt_with_gap(self) -> str:
        runtime = _runtime()
        runtime.gap_store.add_existing(
            Gap(gap_id="gap-1", statement="核对 orders 表 order-1 的金额", status="open")
        )
        return _with_current_state("基础调研提示", runtime)

    def test_default_on_injects_state_block(self, monkeypatch) -> None:
        monkeypatch.delenv("CLOUDAGENT_GAP_INJECTION", raising=False)
        prompt = self._prompt_with_gap()
        assert "## 当前有效状态" in prompt
        assert "核对 orders 表 order-1 的金额" in prompt

    @pytest.mark.parametrize("value", ["false", "0", "no", "off"])
    def test_off_keeps_prompt_untouched(self, monkeypatch, value: str) -> None:
        """``=false``/``=0``/``=no`` 修前会静默继续注入（真 bug）；修后必须原样返回。"""

        monkeypatch.setenv("CLOUDAGENT_GAP_INJECTION", value)
        prompt = self._prompt_with_gap()
        assert prompt == "基础调研提示", f"GAP_INJECTION={value!r} 仍在注入缺口段"
        assert gap_injection_enabled() is False


# ---------------------------------------------------------------------------
# domain_gate：off 档 ⇒ 对"同目标 blocked"放行
# ---------------------------------------------------------------------------


class TestDomainGateBehavior:
    def _gated_runtime(self) -> DiagnosisSessionRuntime:
        runtime = _runtime()
        runtime.gap_store.add_existing(
            Gap(
                gap_id="gap-1",
                statement="缺 Kafka 消费位点权限",
                status="blocked",
                source_domain="code-diagnosis",
            )
        )
        return runtime

    def test_default_same_target_blocks(self, monkeypatch) -> None:
        monkeypatch.delenv("CLOUDAGENT_DOMAIN_GATE", raising=False)
        decision = self._gated_runtime().domain_gate("code", "再查一次 Kafka 消费位点")
        assert decision is not None, "same_target 档对同目标 blocked 应拦停"

    def test_off_allows(self, monkeypatch) -> None:
        monkeypatch.setenv("CLOUDAGENT_DOMAIN_GATE", "off")
        decision = self._gated_runtime().domain_gate("code", "再查一次 Kafka 消费位点")
        assert decision is None, "off 档必须放行（域闸整体停用）"
        assert is_off("domain_gate") is True


# ---------------------------------------------------------------------------
# goal_stop_strategy：[strategy-layer-only] 离线只守策略函数
# ---------------------------------------------------------------------------


class TestGoalStopStrategyBehavior:
    """[strategy-layer-only] "核查器确实没被调用"需要 live；这里守到策略层为止。"""

    def test_agent_report_never_schedules(self, monkeypatch) -> None:
        monkeypatch.setenv("CLOUDAGENT_GOAL_STOP_STRATEGY", "agent_report")
        assert assessor_strategy() == STRATEGY_AGENT_REPORT
        # 终态声明、多次尝试都不核查——这就是"关"
        assert (
            should_verify(strategy=assessor_strategy(), result_status="success", attempt=99)
            is False
        )
        assert is_off("goal_stop_strategy") is True

    def test_default_hybrid_verifies_terminal(self, monkeypatch) -> None:
        monkeypatch.delenv("CLOUDAGENT_GOAL_STOP_STRATEGY", raising=False)
        assert assessor_strategy() == STRATEGY_HYBRID
        assert should_verify(strategy=assessor_strategy(), result_status="success") is True

    def test_invalid_value_falls_back_to_default(self, monkeypatch) -> None:
        monkeypatch.setenv("CLOUDAGENT_GOAL_STOP_STRATEGY", "bogus")
        assert assessor_strategy() == STRATEGY_HYBRID, "认不出 → 回退默认，不猜"
