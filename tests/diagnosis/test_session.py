#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""``cloudagent_ext.diagnosis.session`` 单元测试。

覆盖变更 ``add-investigation-session`` 的规范场景：调查会话与任务轨迹 /
委派预算控制 / 重复委派防护 / 诊断结果入账校验 / 调查停止决策。
"""

from __future__ import annotations

import pytest

from cloudagent_ext.diagnosis.models import (
    DiagnosisRequest,
    DiagnosisResult,
    Evidence,
    RootCause,
)
from cloudagent_ext.diagnosis.session import (
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
    TASK_STATUS_PENDING,
    DiagnosisSessionError,
    InvestigationSession,
    SessionBudget,
)


def _request() -> DiagnosisRequest:
    return DiagnosisRequest(request_id="diag-session-1", question="为什么订单查询变慢？")


def _evidence(evidence_id: str = "ev-0001") -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        source_type="database",
        source_ref="tool_call:explain_sql#1",
        observation="Seq Scan on orders",
    )


def _result(
    task_id: str,
    *,
    status: str = "success",
    request_id: str = "diag-session-1",
    evidence: list[Evidence] | None = None,
    root_causes: list[RootCause] | None = None,
) -> DiagnosisResult:
    return DiagnosisResult(
        request_id=request_id,
        task_id=task_id,
        agent_name="sql-diagnosis",
        status=status,
        summary="索引缺失导致全表扫描",
        evidence=evidence or [],
        root_causes=root_causes or [],
    )


# ---------------------------------------------------------------------------
# 调查会话与任务轨迹
# ---------------------------------------------------------------------------


def test_delegate_creates_trace_entry() -> None:
    session = InvestigationSession(_request())
    task = session.delegate("sql-diagnosis", "分析慢查询")
    assert task.task_id.startswith("task-")
    assert task.parent_request_id == "diag-session-1"
    assert session.delegations_used == 1
    entry = session.entries[0]
    assert entry.task is task
    assert entry.status == TASK_STATUS_PENDING


def test_record_success_flow() -> None:
    session = InvestigationSession(_request())
    task = session.delegate("sql-diagnosis", "分析慢查询")
    session.record_result(_result(task.task_id))
    assert session.entries[0].status == TASK_STATUS_COMPLETED
    decision = session.decide()
    assert decision.should_continue is False
    assert decision.reason == "success_recorded"


def test_record_failure_flow() -> None:
    session = InvestigationSession(_request())
    task = session.delegate("sql-diagnosis", "分析慢查询")
    session.record_failure(task.task_id, reason="子 Agent 输出无法解析")
    entry = session.entries[0]
    assert entry.status == TASK_STATUS_FAILED
    assert entry.failure_reason == "子 Agent 输出无法解析"
    decision = session.decide()
    assert decision.should_continue is True
    assert decision.reason == "budget_available"


# ---------------------------------------------------------------------------
# 委派预算控制
# ---------------------------------------------------------------------------


def test_budget_total_exhausted() -> None:
    session = InvestigationSession(_request(), budget=SessionBudget(max_delegations=1, max_delegations_per_agent=2))
    session.delegate("sql-diagnosis", "目标一")
    with pytest.raises(DiagnosisSessionError, match="budget exhausted"):
        session.delegate("code-analysis", "目标二")
    decision = session.decide()
    assert decision.should_continue is False
    assert decision.reason == "budget_exhausted"


def test_budget_per_agent_enforced() -> None:
    session = InvestigationSession(_request(), budget=SessionBudget(max_delegations=5, max_delegations_per_agent=1))
    session.delegate("sql-diagnosis", "目标一")
    session.delegate("code-analysis", "目标二")
    with pytest.raises(DiagnosisSessionError, match="for agent"):
        session.delegate("sql-diagnosis", "目标三")


# ---------------------------------------------------------------------------
# 重复委派防护
# ---------------------------------------------------------------------------


def test_duplicate_pending_rejected() -> None:
    session = InvestigationSession(_request())
    session.delegate("sql-diagnosis", "分析慢查询")
    with pytest.raises(DiagnosisSessionError, match="already pending"):
        session.delegate("sql-diagnosis", "分析慢查询")


def test_duplicate_after_success_rejected() -> None:
    session = InvestigationSession(_request())
    task = session.delegate("sql-diagnosis", "分析慢查询")
    session.record_result(_result(task.task_id))
    with pytest.raises(DiagnosisSessionError, match="already satisfied"):
        session.delegate("sql-diagnosis", "分析慢查询")


def test_retry_allowed_after_failure() -> None:
    session = InvestigationSession(_request())
    task = session.delegate("sql-diagnosis", "分析慢查询")
    session.record_failure(task.task_id, reason="第一次失败")
    retried = session.delegate("sql-diagnosis", "分析慢查询")
    assert retried.task_id != task.task_id
    assert session.delegations_used == 2


def test_partial_result_allows_redelegation() -> None:
    session = InvestigationSession(_request())
    task = session.delegate("sql-diagnosis", "分析慢查询")
    session.record_result(_result(task.task_id, status="partial"))
    assert session.entries[0].status == TASK_STATUS_COMPLETED
    retried = session.delegate("sql-diagnosis", "分析慢查询")
    assert retried.task_id != task.task_id


# ---------------------------------------------------------------------------
# 诊断结果入账校验
# ---------------------------------------------------------------------------


def test_record_result_request_id_mismatch_rejected() -> None:
    session = InvestigationSession(_request())
    task = session.delegate("sql-diagnosis", "分析慢查询")
    with pytest.raises(DiagnosisSessionError, match="request_id mismatch"):
        session.record_result(_result(task.task_id, request_id="diag-other"))


def test_record_result_dangling_reference_rejected() -> None:
    session = InvestigationSession(_request())
    task = session.delegate("sql-diagnosis", "分析慢查询")
    bad = _result(
        task.task_id,
        root_causes=[
            RootCause(description="假设根因", confidence=0.5, supporting_evidence_ids=["ev-missing"])
        ],
    )
    with pytest.raises(DiagnosisSessionError, match="references"):
        session.record_result(bad)


def test_record_result_unknown_task_rejected() -> None:
    session = InvestigationSession(_request())
    with pytest.raises(DiagnosisSessionError, match="unknown task_id"):
        session.record_result(_result("task-unknown"))


def test_double_record_rejected() -> None:
    session = InvestigationSession(_request())
    task = session.delegate("sql-diagnosis", "分析慢查询")
    session.record_result(_result(task.task_id))
    with pytest.raises(DiagnosisSessionError, match="already completed"):
        session.record_result(_result(task.task_id))


def test_record_failure_requires_reason() -> None:
    session = InvestigationSession(_request())
    task = session.delegate("sql-diagnosis", "分析慢查询")
    with pytest.raises(DiagnosisSessionError, match="non-empty"):
        session.record_failure(task.task_id, reason="   ")


# ---------------------------------------------------------------------------
# 调查停止决策
# ---------------------------------------------------------------------------


def test_decide_budget_exhausted_without_success() -> None:
    session = InvestigationSession(_request(), budget=SessionBudget(max_delegations=1, max_delegations_per_agent=1))
    task = session.delegate("sql-diagnosis", "分析慢查询")
    session.record_failure(task.task_id, reason="失败")
    decision = session.decide()
    assert decision.should_continue is False
    assert decision.reason == "budget_exhausted"


def test_decide_success_recorded() -> None:
    session = InvestigationSession(_request())
    task = session.delegate("sql-diagnosis", "分析慢查询")
    session.record_result(_result(task.task_id))
    decision = session.decide()
    assert decision.should_continue is False
    assert decision.reason == "success_recorded"


def test_decide_failure_with_budget_continues() -> None:
    session = InvestigationSession(_request())
    task = session.delegate("sql-diagnosis", "分析慢查询")
    session.record_failure(task.task_id, reason="失败")
    decision = session.decide()
    assert decision.should_continue is True
    assert decision.reason == "budget_available"
