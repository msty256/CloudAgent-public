#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""阶段 0「度量地基」的采集与聚合测试。

对应提案 `docs/proposals/phase-0-measurement.md`：

* T0.2 usage 键名归一（OpenAI / Anthropic / 嵌套 details / 缺失）
* T0.3 终止原因分布
* T0.4 缺口迁移事件
* T0.5 `--repeat` 跨轮聚合（原来是取第一轮）
* T0.6 派发模式自证字段
"""

from __future__ import annotations

import pytest

from cloudagent_ext.diagnosis.evaluation.cost import (
    summarize_usage,
    sum_usage_summaries,
)
from cloudagent_ext.diagnosis.evaluation.runner import (
    _experiment_stats,
    run_evaluation,
)
from cloudagent_ext.diagnosis.models import DiagnosisRequest, DiagnosisResult, Evidence
from cloudagent_ext.diagnosis.runtime_session import (
    DiagnosisSessionRuntime,
    harvest_gaps,
)
from cloudagent_ext.diagnosis.session import InvestigationSession, SessionBudget


def _rt() -> DiagnosisSessionRuntime:
    return DiagnosisSessionRuntime(
        session=InvestigationSession(
            DiagnosisRequest(request_id="req-1", question="q"), budget=SessionBudget(9, 9)
        )
    )


def _result(
    *,
    status: str = "success",
    next_steps: list[str] | None = None,
    limitations: list[str] | None = None,
    evidences: list[Evidence] | None = None,
) -> DiagnosisResult:
    return DiagnosisResult(
        request_id="req-1",
        agent_name="code-diagnosis",
        status=status,
        summary="s",
        evidence=evidences or [],
        next_steps=next_steps or [],
        limitations=limitations or [],
    )


# ---------------------------------------------------------------------------
# T0.2：usage 归一
# ---------------------------------------------------------------------------


class TestSummarizeUsage:
    def test_openai_style_keys(self) -> None:
        calls = [
            {"usage": {"prompt_tokens": 100, "completion_tokens": 20}},
            {"usage": {"prompt_tokens": 50, "completion_tokens": 10}},
        ]
        summary = summarize_usage(calls)
        assert summary["input_tokens"] == 150
        assert summary["output_tokens"] == 30
        assert summary["total_tokens"] == 180
        assert summary["calls_with_usage"] == 2
        assert summary["calls_without_usage"] == 0
        assert summary["available"] is True
        # 这批没有缓存字段 → 必须留空，不能写成 0 命中
        assert summary["cache_field"] == ""

    def test_anthropic_style_keys_with_cache(self) -> None:
        calls = [
            {
                "usage": {
                    "input_tokens": 1000,
                    "output_tokens": 200,
                    "cache_read_input_tokens": 800,
                }
            }
        ]
        summary = summarize_usage(calls)
        assert summary["input_tokens"] == 1000
        assert summary["cached_input_tokens"] == 800
        assert summary["cache_field"] == "cache_read_input_tokens"
        # 缓存已含在输入里，不重复计入 total
        assert summary["total_tokens"] == 1200

    def test_nested_cached_tokens(self) -> None:
        calls = [
            {
                "usage": {
                    "prompt_tokens": 500,
                    "completion_tokens": 50,
                    "prompt_tokens_details": {"cached_tokens": 300},
                }
            }
        ]
        summary = summarize_usage(calls)
        assert summary["cached_input_tokens"] == 300
        assert summary["cache_field"] == "prompt_tokens_details.cached_tokens"

    def test_missing_usage_is_counted_not_zeroed(self) -> None:
        calls = [{"usage": None}, {}, {"usage": {"input_tokens": 10, "output_tokens": 5}}]
        summary = summarize_usage(calls)
        assert summary["calls_without_usage"] == 2
        assert summary["calls_with_usage"] == 1
        assert summary["input_tokens"] == 10

    def test_all_missing_marks_unavailable(self) -> None:
        summary = summarize_usage([{"usage": None}])
        assert summary["available"] is False
        assert summary["total_tokens"] == 0

    def test_sum_usage_summaries(self) -> None:
        a = summarize_usage([{"usage": {"input_tokens": 10, "output_tokens": 1}}])
        b = summarize_usage([{"usage": {"prompt_tokens": 5, "completion_tokens": 2}}])
        total = sum_usage_summaries([a, b])
        assert total["input_tokens"] == 15
        assert total["output_tokens"] == 3
        assert total["available"] is True


# ---------------------------------------------------------------------------
# T0.3：终止原因分布
# ---------------------------------------------------------------------------


class TestDecisionLog:
    def test_counts_by_reason(self) -> None:
        rt = _rt()
        rt.decide()  # budget_available
        task = rt.session.delegate("code-diagnosis", "查 A")
        rt.session.record_result(
            DiagnosisResult(
                request_id="req-1",
                agent_name="code-diagnosis",
                status="success",
                summary="ok",
                task_id=task.task_id,
            )
        )
        rt.decide()  # success_recorded
        assert rt.decision_counts == {"budget_available": 1, "success_recorded": 1}
        assert [item["reason"] for item in rt.decision_log] == [
            "budget_available",
            "success_recorded",
        ]

    def test_log_is_capped(self, monkeypatch) -> None:
        import cloudagent_ext.diagnosis.runtime_session as mod

        monkeypatch.setattr(mod, "_MAX_DECISION_LOG", 3)
        rt = _rt()
        for _ in range(6):
            rt.decide()
        assert len(rt.decision_log) == 3
        # n 是递增序号，不因截断重置
        assert rt.decision_log[-1]["n"] == 6

    def test_counts_survive_log_truncation(self, monkeypatch) -> None:
        """计数不能从 decision_log 反推——日志有上限，反推会漏计早期判定。"""

        import cloudagent_ext.diagnosis.runtime_session as mod

        monkeypatch.setattr(mod, "_MAX_DECISION_LOG", 3)
        rt = _rt()
        for _ in range(8):
            rt.decide()
        assert len(rt.decision_log) == 3
        assert rt.decision_counts == {"budget_available": 8}

    def test_log_records_evaluator(self) -> None:
        rt = _rt()
        rt.decide()
        assert rt.decision_log[0]["evaluator"] == "budget_available"


# ---------------------------------------------------------------------------
# T0.4：缺口迁移事件
# ---------------------------------------------------------------------------


class TestGapEvents:
    def test_new_open_gap_records_event(self) -> None:
        rt = _rt()
        harvest_gaps(rt, _result(next_steps=["核对 orders 表 order-1 是否有记录"]))
        assert [e["why"] for e in rt.gap_events] == ["new"]
        assert rt.gap_events[0]["from"] == ""
        assert rt.gap_events[0]["to"] == "open"

    def test_open_to_blocked(self) -> None:
        rt = _rt()
        harvest_gaps(rt, _result(next_steps=["核对 orders 表 order-1 是否有记录"]))
        harvest_gaps(rt, _result(limitations=["核对 orders 表 order-1 是否有记录"]))
        transitions = [(e["from"], e["to"], e["why"]) for e in rt.gap_events]
        assert ("open", "blocked", "blocked") in transitions

    def test_open_to_resolved_carries_evidence_id(self) -> None:
        rt = _rt()
        harvest_gaps(
            rt,
            _result(
                next_steps=["核对 orders 表 order-12345 是否有记录"],
                evidences=[
                    Evidence(
                        evidence_id="ev:sql:1",
                        source_type="query_table_rows",
                        source_ref="public.orders",
                        observation="orders 表 order-12345 计数为 0",
                    )
                ],
            ),
        )
        resolved = [e for e in rt.gap_events if e["why"] == "resolved"]
        assert resolved and resolved[0]["evidence_id"] == "ev:sql:1"

    def test_open_to_inconclusive(self) -> None:
        rt = _rt()
        for _ in range(3):
            harvest_gaps(rt, _result(next_steps=["核对 orders 是否被触发"]))
        assert any(e["why"] == "restated" for e in rt.gap_events)

    def test_events_are_capped(self, monkeypatch) -> None:
        # 阶段 4：事件上限的真相源移到了 GapStore（单写者），这里跟着改
        import cloudagent_ext.diagnosis.gap_store as store_mod

        monkeypatch.setattr(store_mod, "MAX_EVENTS", 2)
        rt = _rt()
        for i in range(5):
            harvest_gaps(rt, _result(next_steps=[f"核对 orders 表 order-{i} 是否有记录"]))
        assert len(rt.gap_events) == 2


# ---------------------------------------------------------------------------
# T0.5：跨轮聚合
# ---------------------------------------------------------------------------


def _case_result(*, delegations: int, gaps_total: int = 0, injected: int = 0) -> dict:
    return {
        "meta": {
            "delegations": delegations,
            "gaps_total": gaps_total,
            "injected_dispatches": injected,
            "tool_calls": 1,
            "model_calls": 1,
            "elapsed_sec": 1.0,
            "sub_tool_calls": 1,
            "main_tool_calls": 0,
            "usage": {
                "input_tokens": 10,
                "output_tokens": 2,
                "cached_input_tokens": 0,
                "total_tokens": 12,
                "available": True,
            },
        }
    }


class TestRepeatAggregation:
    def test_scalar_keys_are_median_not_first_round(self) -> None:
        round1 = [_case_result(delegations=2), _case_result(delegations=4)]
        round2 = [_case_result(delegations=6), _case_result(delegations=8)]
        stats = _experiment_stats([round1, round2])
        # 两轮分别是 6 与 14 → 中位数 10；改造前会取第一轮的 6
        assert stats["delegations"] == 10
        assert stats["delegations_series"] == [6.0, 14.0]
        assert stats["delegations_min"] == 6
        assert stats["delegations_max"] == 14

    def test_injected_max_exposes_leak_in_any_round(self) -> None:
        round1 = [_case_result(delegations=1, injected=0)]
        round2 = [_case_result(delegations=1, injected=3)]
        stats = _experiment_stats([round1, round2])
        # 两轮 0 与 3 → 中位数 1.5：中位数会把"只有一轮泄漏"抹平一半，
        # 所以泄漏判定必须看 _max（runner 的守卫已改用它）。
        assert stats["injected_dispatches"] == 1.5
        assert stats["injected_dispatches_max"] == 3

    def test_usage_aggregated_across_rounds(self) -> None:
        round1 = [_case_result(delegations=1)]
        round2 = [_case_result(delegations=1), _case_result(delegations=1)]
        stats = _experiment_stats([round1, round2])
        assert stats["usage_input_tokens_series"] == [10.0, 20.0]
        assert stats["usage_available"] is True
        assert stats["cache_field"] == ""

    def test_usage_unavailable_is_explicit(self) -> None:
        result = _case_result(delegations=1)
        result["meta"]["usage"] = {"available": False, "input_tokens": 0}
        stats = _experiment_stats([[result]])
        assert stats["usage_available"] is False


# ---------------------------------------------------------------------------
# T0.6：派发模式自证
# ---------------------------------------------------------------------------


class TestDispatchSelfCheck:
    def test_helper_requires_all_three_conditions(self) -> None:
        from cloudagent_ext.diagnosis.evaluation.runner import _gap_injection_effective

        # 只有 live + main + gaps-on 三者同时成立才算"注入生效"
        assert _gap_injection_effective("live", "main", "gaps-on") is True
        assert _gap_injection_effective("live", "direct", "gaps-on") is False
        assert _gap_injection_effective("live", "main", "gaps-off") is False
        # offline 回放不跑模型——即使参数看起来对，也不能标"生效"
        assert _gap_injection_effective("offline", "main", "gaps-on") is False

    def test_offline_run_never_claims_effective(self, tmp_path) -> None:
        import json

        summary = run_evaluation(
            mode="offline",
            domain="sync",
            out_dir=tmp_path,
            variant="gaps-on",
            dispatch_mode="main",
        )
        run = json.loads((tmp_path / summary["run_id"] / "run.json").read_text(encoding="utf-8"))
        assert run["dispatch_mode"] == "main"
        assert run["gap_injection_effective"] is False

    def test_payload_records_dispatch_mode(self, tmp_path) -> None:
        import json

        summary = run_evaluation(
            mode="offline",
            domain="sync",
            out_dir=tmp_path,
            variant="gaps-on",
            dispatch_mode="direct",
        )
        run = json.loads((tmp_path / summary["run_id"] / "run.json").read_text(encoding="utf-8"))
        assert run["dispatch_mode"] == "direct"
        assert run["gap_injection_effective"] is False


# ---------------------------------------------------------------------------
# 端到端：meta 里能读到三个新采集
# ---------------------------------------------------------------------------


def test_meta_carries_new_collections(tmp_path, monkeypatch) -> None:
    """离线执行器不跑模型，但 meta 的键必须存在（形状契约）。"""

    from cloudagent_ext.diagnosis.evaluation.executors import OfflineExecutor

    summary = run_evaluation(
        mode="offline", domain="sync", out_dir=tmp_path, executor=OfflineExecutor()
    )
    import json

    run_dir = tmp_path / summary["run_id"]
    case_files = sorted((run_dir / "cases").glob("*.json"))
    assert case_files, "没有产出逐 case 明细"
    case = json.loads(case_files[0].read_text(encoding="utf-8"))
    for key in ("decision_counts", "decision_log", "gap_events", "usage"):
        assert key in case["meta"], f"meta 缺 {key}"
    assert "available" in case["meta"]["usage"]
