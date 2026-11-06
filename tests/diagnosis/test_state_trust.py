#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""阶段 2「状态可信」测试。

四组：

1. **状态版本**：正常收割不推进版本、显式 bump 才作废在飞结果、陈旧写入不污染缺口；
2. **注入预算**：默认值不变（5/200/1000）、可配置；
3. **独立核查**：三档调度、JSON 解析、四种结论路径、回写语义；
4. **状态段**：三块渲染 + "没核查就不宣称已确认" + 按域过滤。

第 4 组的第 3 条是本阶段的**核心不变量**：``resolved`` 但没过核查的缺口**不得**出现在
"已确认"块里——否则就是把"关键词命中"当成了"结论成立"。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from cloudagent_ext.diagnosis.assessor import (
    ASSESS_OK,
    ASSESS_OVERCLAIMED,
    ASSESS_SKIPPED,
    ASSESS_UNAVAILABLE,
    Assessment,
    assess_result,
    assessor_strategy,
    parse_assessment,
    should_verify,
    summarize_assessments,
    verify_interval,
)
from cloudagent_ext.diagnosis.models import DiagnosisRequest, DiagnosisResult, Evidence, Gap
from cloudagent_ext.diagnosis.runtime_session import (
    DiagnosisSessionRuntime,
    finish_delegation,
    harvest_gaps,
)
from cloudagent_ext.diagnosis.session import InvestigationSession, SessionBudget
from cloudagent_ext.tool_system.tools.agent import (
    _with_current_state,
    _with_open_gaps,
    gap_injection_limits,
)


def _rt() -> DiagnosisSessionRuntime:
    return DiagnosisSessionRuntime(
        session=InvestigationSession(
            DiagnosisRequest(request_id="req-1", question="q"), budget=SessionBudget(9, 9)
        )
    )


def _result_text(request_id: str = "req-1", task_id: str = "", status: str = "success") -> str:
    payload = {
        "request_id": request_id,
        "agent_name": "code-diagnosis",
        "status": status,
        "summary": "ok",
        "findings": [],
        "evidence": [],
        "root_causes": [],
        "recommendations": [],
        "validation_plan": [],
        "limitations": [],
        "next_steps": [],
    }
    if task_id:
        payload["task_id"] = task_id
    import json

    return json.dumps(payload, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 1. 状态版本
# ---------------------------------------------------------------------------


class TestStateRevision:
    def test_normal_harvest_does_not_bump(self) -> None:
        rt = _rt()
        first = rt.session.delegate("code-diagnosis", "查 A")
        rt.dispatch_revisions[first.task_id] = rt.state_revision
        harvest_gaps(rt, DiagnosisResult(
            request_id="req-1", agent_name="code-diagnosis", status="success", summary="s",
            next_steps=["核对 orders 表 order-1"],
        ), domain="code-diagnosis")

        # 另一个"在飞"的委派（派发早于这次收割）不应被判陈旧
        assert rt.state_revision == 0
        assert rt.is_stale("some-other-task") is False

    def test_bump_makes_inflight_stale(self) -> None:
        rt = _rt()
        task = rt.session.delegate("code-diagnosis", "查 A")
        rt.dispatch_revisions[task.task_id] = rt.state_revision
        rt.bump_state_revision(reason="objective changed")
        assert rt.is_stale(task.task_id) is True

        status = finish_delegation(rt, task, _result_text(task_id=task.task_id))
        assert status == "stale"
        assert rt.stale_discarded == 1

    def test_stale_write_does_not_touch_gaps(self) -> None:
        rt = _rt()
        task = rt.session.delegate("code-diagnosis", "查 A")
        rt.dispatch_revisions[task.task_id] = rt.state_revision
        rt.bump_state_revision(reason="objective changed")

        finish_delegation(
            rt,
            task,
            _result_text(task_id=task.task_id).replace(
                '"next_steps": []', '"next_steps": ["核对 orders 表 order-1"]'
            ),
        )
        assert rt.gaps == ()
        assert rt.gap_events == ()

    def test_stale_task_closed_so_redispatch_works(self) -> None:
        """陈旧的委派必须被关掉（记 failed），不能留 pending——否则重复派发被防护拦住。"""

        rt = _rt()
        task = rt.session.delegate("code-diagnosis", "查 A")
        rt.dispatch_revisions[task.task_id] = rt.state_revision
        rt.bump_state_revision(reason="x")
        finish_delegation(rt, task, _result_text(task_id=task.task_id))

        # 同一目标可以重新派发（pending 的重复防护不再命中）
        again = rt.session.delegate("code-diagnosis", "查 A")
        assert again.task_id != task.task_id

    def test_unknown_task_is_not_stale(self) -> None:
        rt = _rt()
        assert rt.is_stale("never-dispatched") is False


# ---------------------------------------------------------------------------
# 2. 注入预算
# ---------------------------------------------------------------------------


class TestInjectionLimits:
    def test_defaults_unchanged(self, monkeypatch) -> None:
        for name in (
            "CLOUDAGENT_GAP_MAX_ITEMS",
            "CLOUDAGENT_GAP_MAX_CHARS_PER_ITEM",
            "CLOUDAGENT_GAP_MAX_TOTAL_CHARS",
        ):
            monkeypatch.delenv(name, raising=False)
        gap_injection_limits.cache_clear()
        limits = gap_injection_limits()
        assert (limits.max_items, limits.max_chars_per_item, limits.max_total_chars) == (
            5,
            200,
            1000,
        )

    def test_env_override(self, monkeypatch) -> None:
        monkeypatch.setenv("CLOUDAGENT_GAP_MAX_ITEMS", "2")
        gap_injection_limits.cache_clear()
        assert gap_injection_limits().max_items == 2
        gap_injection_limits.cache_clear()
        monkeypatch.delenv("CLOUDAGENT_GAP_MAX_ITEMS", raising=False)


# ---------------------------------------------------------------------------
# 3. 独立核查
# ---------------------------------------------------------------------------


class _FakeProvider:
    """只回一个固定 content；可选抛异常。"""

    def __init__(self, content: str = "", *, raises: Exception | None = None) -> None:
        self.content = content
        self.raises = raises
        self.calls: list[dict] = []

    def chat(self, messages, tools=None, **kwargs):  # noqa: ANN001
        self.calls.append({"messages": messages})
        if self.raises is not None:
            raise self.raises
        return SimpleNamespace(content=self.content)


def _task(objective: str = "查 orders") -> SimpleNamespace:
    return SimpleNamespace(objective=objective)


def _parsed(status: str = "success") -> DiagnosisResult:
    return DiagnosisResult(
        request_id="req-1",
        agent_name="code-diagnosis",
        status=status,
        summary="s",
        evidence=[
            Evidence(
                evidence_id="ev:code:1",
                source_type="read_file",
                source_ref="session.py",
                observation="SessionBudget 在 _agent_call 里被读取",
            )
        ],
    )


class TestShouldVerify:
    def test_agent_report_never(self) -> None:
        assert should_verify(strategy="agent_report", result_status="success") is False

    def test_transcript_always(self) -> None:
        assert should_verify(strategy="transcript", result_status="failed") is True

    def test_hybrid_verifies_terminal(self) -> None:
        assert should_verify(strategy="hybrid", result_status="success", interval=0) is True
        assert should_verify(strategy="hybrid", result_status="partial", interval=0) is True

    def test_hybrid_trusts_continue_unless_spot_check(self) -> None:
        assert should_verify(strategy="hybrid", result_status="failed", attempt=1, interval=3) is False
        assert should_verify(strategy="hybrid", result_status="failed", attempt=3, interval=3) is True

    def test_hybrid_no_interval_means_no_spot_check(self) -> None:
        assert should_verify(strategy="hybrid", result_status="failed", attempt=9, interval=0) is False


class TestParseAssessment:
    def test_bare_json(self) -> None:
        data = parse_assessment('{"verdict": "ok", "verified_gaps": ["g1"], "reason": "r"}')
        assert data is not None and data["verdict"] == "ok"

    def test_fenced_json(self) -> None:
        text = '前言\n```json\n{"verdict": "overclaimed", "reason": "x"}\n```\n后记'
        data = parse_assessment(text)
        assert data is not None and data["verdict"] == "overclaimed"

    def test_no_json_returns_none(self) -> None:
        assert parse_assessment("我觉得没问题") is None
        assert parse_assessment("") is None

    def test_json_without_verdict_returns_none(self) -> None:
        assert parse_assessment('{"foo": 1}') is None


class TestAssessResult:
    def test_no_provider_is_unavailable(self) -> None:
        gap = Gap(gap_id="g1", statement="核对 orders 表 order-1", status="resolved")
        assessment = assess_result(task=_task(), result=_parsed(), gaps=[gap], provider=None)
        assert assessment.status == ASSESS_UNAVAILABLE
        assert assessment.claimed_gaps == ("g1",)
        assert assessment.calls == 0  # 没发出调用

    def test_ok_marks_all_claimed(self) -> None:
        provider = _FakeProvider('{"verdict": "ok", "verified_gaps": ["g1"], "reason": "r"}')
        gap = Gap(gap_id="g1", statement="x", status="resolved")
        assessment = assess_result(task=_task(), result=_parsed(), gaps=[gap], provider=provider)
        assert assessment.status == ASSESS_OK
        assert assessment.verified_gaps == ("g1",)
        assert assessment.calls == 1

    def test_overclaimed_only_lists_verified(self) -> None:
        provider = _FakeProvider(
            '{"verdict": "overclaimed", "verified_gaps": [], "reason": "证据只提到表名"}'
        )
        gap = Gap(gap_id="g1", statement="x", status="resolved")
        assessment = assess_result(task=_task(), result=_parsed(), gaps=[gap], provider=provider)
        assert assessment.status == ASSESS_OVERCLAIMED
        assert assessment.verified_gaps == ()

    def test_call_failure_is_unavailable(self) -> None:
        provider = _FakeProvider(raises=RuntimeError("boom"))
        assessment = assess_result(
            task=_task(), result=_parsed(), gaps=[], provider=provider
        )
        assert assessment.status == ASSESS_UNAVAILABLE
        assert "call failed" in assessment.reason

    def test_unparseable_is_unavailable(self) -> None:
        provider = _FakeProvider("模型不肯输出 JSON")
        assessment = assess_result(task=_task(), result=_parsed(), gaps=[], provider=provider)
        assert assessment.status == ASSESS_UNAVAILABLE
        assert assessment.reason == "unparseable response"

    def test_messages_shape(self) -> None:
        provider = _FakeProvider('{"verdict": "ok"}')
        assess_result(task=_task("查 orders"), result=_parsed(), gaps=[], provider=provider)
        messages = provider.calls[0]["messages"]
        assert messages[0]["role"] == "system"
        assert "审核员" in messages[0]["content"]
        assert "查 orders" in messages[1]["content"]


class TestWriteback:
    def test_verified_flag_and_reason(self) -> None:
        rt = _rt()
        ok_gap = Gap(gap_id="g1", statement="x", status="resolved")
        bad_gap = Gap(gap_id="g2", statement="y", status="resolved")
        rt.record_assessment(
            Assessment(status=ASSESS_OK, claimed_gaps=("g1",), verified_gaps=("g1",), reason="r"),
            [ok_gap],
        )
        rt.record_assessment(
            Assessment(
                status=ASSESS_OVERCLAIMED, claimed_gaps=("g2",), verified_gaps=(), reason="证据不足"
            ),
            [bad_gap],
        )
        assert ok_gap.verified is True and ok_gap.verification == "ok"
        assert bad_gap.verified is False
        assert bad_gap.verification.startswith("overclaimed")

    def test_summary_disagreement_rate(self) -> None:
        summary = summarize_assessments(
            [
                Assessment(status=ASSESS_OK, claimed_gaps=("g1",), verified_gaps=("g1",)),
                Assessment(status=ASSESS_OVERCLAIMED, claimed_gaps=("g2",), verified_gaps=()),
                Assessment(status=ASSESS_UNAVAILABLE, claimed_gaps=("g3",), verified_gaps=()),
                Assessment(status=ASSESS_SKIPPED),
            ]
        )
        assert summary["assessments"] == 4
        assert summary["by_status"][ASSESS_UNAVAILABLE] == 1
        assert summary["claimed_gaps"] == 3
        assert summary["verified_gaps"] == 1
        assert summary["disagreement_rate"] == pytest.approx(2 / 3, abs=1e-3)


class TestAssessorConfig:
    def test_default_strategy_is_hybrid(self, monkeypatch) -> None:
        monkeypatch.delenv("CLOUDAGENT_GOAL_STOP_STRATEGY", raising=False)
        assert assessor_strategy() == "hybrid"

    def test_invalid_strategy_falls_back(self, monkeypatch) -> None:
        monkeypatch.setenv("CLOUDAGENT_GOAL_STOP_STRATEGY", "bogus")
        assert assessor_strategy() == "hybrid"

    def test_default_interval(self, monkeypatch) -> None:
        monkeypatch.delenv("CLOUDAGENT_ASSESSOR_VERIFY_INTERVAL", raising=False)
        assert verify_interval() == 3

    def test_zero_interval(self, monkeypatch) -> None:
        monkeypatch.setenv("CLOUDAGENT_ASSESSOR_VERIFY_INTERVAL", "0")
        assert verify_interval() == 0


# ---------------------------------------------------------------------------
# 4. 状态段（B1b）
# ---------------------------------------------------------------------------


def _runtime_with(gaps, *, dispatches: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        gaps=list(gaps),
        injected_dispatches=0,
        domain_stats=lambda: dict(dispatches or {}),
    )


class TestCurrentStateSection:
    def test_open_only_has_no_confirmed_block(self) -> None:
        runtime = _runtime_with(
            [Gap(gap_id="g1", statement="核对 orders 表 order-1", status="open")]
        )
        prompt = _with_current_state("BASE", runtime)
        assert "当前有效状态" in prompt
        assert "当前未解决缺口" in prompt
        assert "已确认" not in prompt

    def test_verified_resolved_goes_to_confirmed(self) -> None:
        runtime = _runtime_with(
            [
                Gap(
                    gap_id="g1",
                    statement="orders 表 order-1 无记录",
                    status="resolved",
                    evidence_refs=["ev:code:1"],
                    verified=True,
                )
            ]
        )
        prompt = _with_current_state("BASE", runtime)
        assert "已确认" in prompt
        assert "ev:code:1" in prompt

    def test_unverified_resolved_is_never_claimed(self) -> None:
        """核心不变量：没核查过的 resolved 不得进"已确认"块。"""

        runtime = _runtime_with(
            [Gap(gap_id="g1", statement="orders 表 order-1 无记录", status="resolved")]
        )
        prompt = _with_current_state("BASE", runtime)
        assert "已确认" not in prompt
        assert "order-1" not in prompt

    def test_budget_line_rendered(self) -> None:
        runtime = _runtime_with(
            [Gap(gap_id="g1", statement="核对 orders 表 order-1", status="open")],
            dispatches={"code": 1, "log": 2},
        )
        prompt = _with_current_state("BASE", runtime)
        assert "预算余量" in prompt
        assert "code 1/" in prompt

    def test_filters_by_domain(self) -> None:
        runtime = _runtime_with(
            [
                Gap(gap_id="g1", statement="核对 orders 表 order-1", status="open", source_domain="sql-diagnosis"),
                Gap(gap_id="g2", statement="核对 session.py 的 decide", status="open", source_domain="code-diagnosis"),
            ]
        )
        prompt = _with_current_state("BASE", runtime, domain="code")
        assert "session.py" in prompt
        assert "order-1" not in prompt

    def test_disabled_returns_prompt_unchanged(self, monkeypatch) -> None:
        monkeypatch.setenv("CLOUDAGENT_GAP_INJECTION", "off")
        runtime = _runtime_with(
            [Gap(gap_id="g1", statement="核对 orders 表 order-1", status="open")]
        )
        assert _with_current_state("BASE", runtime) == "BASE"
        assert runtime.injected_dispatches == 0

    def test_empty_state_returns_prompt(self) -> None:
        assert _with_current_state("BASE", _runtime_with([])) == "BASE"

    def test_legacy_alias_still_works(self) -> None:
        runtime = _runtime_with(
            [Gap(gap_id="g1", statement="核对 orders 表 order-1", status="open")]
        )
        assert "当前未解决缺口" in _with_open_gaps("BASE", runtime)
