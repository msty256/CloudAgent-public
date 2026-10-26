#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""``cloudagent_ext.diagnosis.models`` 单元测试。

覆盖变更 ``add-diagnosis-data-model`` 的规范场景：诊断请求 / 调查任务 /
证据 / 候选根因 / 诊断结果与状态枚举 / JSON 往返与前向兼容 /
证据引用完整性校验 / 关联标识生成。
"""

from __future__ import annotations

import json

import pytest

from cloudagent_ext.diagnosis.models import (
    EVIDENCE_SOURCE_DATABASE,
    STATUS_FAILED,
    STATUS_PARTIAL,
    STATUS_SUCCESS,
    VALID_STATUSES,
    DiagnosisRequest,
    DiagnosisResult,
    Evidence,
    InvestigationTask,
    RootCause,
    new_evidence_id,
    new_id,
    new_request_id,
    new_task_id,
)


def _sample_request() -> DiagnosisRequest:
    return DiagnosisRequest(
        request_id=new_request_id(),
        question="为什么订单查询接口变慢？",
        context={"sql": "select * from orders where tenant_id = ?"},
        constraints={"read_only": True, "time_range": "2026-10-10"},
        requested_agents=["sql-diagnosis"],
    )


def _sample_task() -> InvestigationTask:
    return InvestigationTask(
        task_id=new_task_id(),
        parent_request_id="diag-x",
        agent_type="sql-diagnosis",
        objective="分析订单查询的执行计划并定位慢点",
        inputs={"sql": "select ..."},
        required_evidence=["执行计划", "表与索引元数据"],
        constraints={"read_only": True},
        budget={"max_turns": 10},
    )


def _sample_evidence(evidence_id: str = "ev-0001") -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        source_type=EVIDENCE_SOURCE_DATABASE,
        source_ref="tool_call:explain_sql#1",
        observation="Seq Scan on orders (cost=0.00..18334.00 rows=1 width=12)",
        observed_at="2026-10-11T00:00:00+08:00",
        scope={"table": "orders", "env": "sim-pg"},
        reliability="high",
    )


def _sample_root_cause() -> RootCause:
    return RootCause(
        description="orders.tenant_id 缺少可用索引，导致全表扫描",
        confidence=0.72,
        supporting_evidence_ids=["ev-0001", "ev-0002"],
        counter_evidence=["统计信息可能过期，需 ANALYZE 后复测"],
        confidence_rationale="两条独立证据方向一致，但未复现生产数据量",
    )


def _sample_result() -> DiagnosisResult:
    return DiagnosisResult(
        request_id="diag-abc123",
        task_id="task-abc123",
        agent_name="sql-diagnosis",
        skill_name="sql-optimization",
        status=STATUS_SUCCESS,
        summary="慢查询根因为索引缺失",
        findings=["执行计划为全表扫描"],
        evidence=[_sample_evidence("ev-0001"), _sample_evidence("ev-0002")],
        root_causes=[_sample_root_cause()],
        recommendations=["为 (tenant_id, created_at) 建联合索引"],
        validation_plan=["建索引后重跑 EXPLAIN，确认走 Index Scan"],
        limitations=["未获取生产统计信息"],
        next_steps=[],
    )


# ---------------------------------------------------------------------------
# 诊断请求数据契约
# ---------------------------------------------------------------------------


def test_request_defaults_and_roundtrip() -> None:
    request = _sample_request()
    assert request.context
    assert DiagnosisRequest.from_dict(request.to_dict()) == request
    assert DiagnosisRequest.from_dict(json.loads(json.dumps(request.to_dict()))) == request


def test_request_defaults_are_empty() -> None:
    request = DiagnosisRequest(request_id="diag-1", question="q")
    assert request.context == {}
    assert request.constraints == {}
    assert request.requested_agents is None


def test_request_requires_non_empty_id_and_question() -> None:
    with pytest.raises(ValueError):
        DiagnosisRequest(request_id="", question="q")
    with pytest.raises(ValueError):
        DiagnosisRequest(request_id="diag-1", question="   ")


def test_request_rejects_non_string_agent_list() -> None:
    with pytest.raises(ValueError):
        DiagnosisRequest(request_id="diag-1", question="q", requested_agents="sql-diagnosis")


# ---------------------------------------------------------------------------
# 调查任务数据契约
# ---------------------------------------------------------------------------


def test_task_roundtrip_and_defaults() -> None:
    task = _sample_task()
    assert InvestigationTask.from_dict(task.to_dict()) == task
    minimal = InvestigationTask(
        task_id="t-1",
        parent_request_id="diag-1",
        agent_type="sql-diagnosis",
        objective="o",
    )
    assert minimal.inputs == {}
    assert minimal.required_evidence == []
    assert minimal.constraints == {}
    assert minimal.budget == {}


def test_task_requires_objective() -> None:
    with pytest.raises(ValueError):
        InvestigationTask(
            task_id="t-1",
            parent_request_id="diag-1",
            agent_type="sql-diagnosis",
            objective="",
        )


# ---------------------------------------------------------------------------
# 证据数据契约
# ---------------------------------------------------------------------------


def test_evidence_roundtrip_full() -> None:
    evidence = _sample_evidence()
    assert Evidence.from_dict(evidence.to_dict()) == evidence


def test_evidence_requires_core_fields() -> None:
    with pytest.raises(ValueError):
        Evidence(evidence_id="ev-1", source_type="database", source_ref="r", observation="")
    with pytest.raises(ValueError):
        Evidence(evidence_id="", source_type="database", source_ref="r", observation="o")
    with pytest.raises(ValueError):
        Evidence(evidence_id="ev-1", source_type="", source_ref="r", observation="o")


# ---------------------------------------------------------------------------
# 候选根因与置信度约束
# ---------------------------------------------------------------------------


def test_root_cause_confidence_bounds() -> None:
    assert RootCause(description="d", confidence=0.0).confidence == 0.0
    assert RootCause(description="d", confidence=1.0).confidence == 1.0
    assert RootCause(description="d", confidence=1).confidence == 1.0


def test_root_cause_rejects_invalid_confidence() -> None:
    for bad in (1.5, -0.01, True):
        with pytest.raises(ValueError):
            RootCause(description="d", confidence=bad)


def test_root_cause_roundtrip() -> None:
    cause = _sample_root_cause()
    assert RootCause.from_dict(cause.to_dict()) == cause


# ---------------------------------------------------------------------------
# 诊断结果与状态枚举
# ---------------------------------------------------------------------------


def test_result_accepts_all_valid_statuses() -> None:
    for status in (STATUS_SUCCESS, STATUS_PARTIAL, STATUS_FAILED):
        DiagnosisResult(request_id="r", agent_name="a", status=status, summary="s")
    assert VALID_STATUSES == frozenset({"success", "partial", "failed"})


def test_result_rejects_unknown_status() -> None:
    with pytest.raises(ValueError):
        DiagnosisResult(request_id="r", agent_name="a", status="unknown", summary="s")


def test_result_requires_summary_and_agent_name() -> None:
    with pytest.raises(ValueError):
        DiagnosisResult(request_id="r", agent_name="", status=STATUS_SUCCESS, summary="s")
    with pytest.raises(ValueError):
        DiagnosisResult(request_id="r", agent_name="a", status=STATUS_SUCCESS, summary="")


# ---------------------------------------------------------------------------
# JSON 往返与前向兼容
# ---------------------------------------------------------------------------


def test_result_roundtrip_full() -> None:
    result = _sample_result()
    assert DiagnosisResult.from_dict(result.to_dict()) == result
    assert DiagnosisResult.from_dict(json.loads(json.dumps(result.to_dict()))) == result


def test_result_ignores_unknown_fields() -> None:
    payload = _sample_result().to_dict()
    payload["future_field"] = {"anything": True}
    payload["evidence"][0]["extra_note"] = "nested-extension"
    restored = DiagnosisResult.from_dict(payload)
    assert restored == _sample_result()


def test_from_dict_rejects_wrong_types() -> None:
    base = {
        "request_id": "r",
        "agent_name": "a",
        "status": "success",
        "summary": "s",
    }
    with pytest.raises(ValueError):
        DiagnosisResult.from_dict("not-a-dict")
    with pytest.raises(ValueError):
        DiagnosisResult.from_dict({**base, "evidence": "not-a-list"})
    with pytest.raises(ValueError):
        DiagnosisResult.from_dict({**base, "evidence": ["not-a-dict"]})
    with pytest.raises(ValueError):
        DiagnosisResult.from_dict({**base, "root_causes": [{"description": "d"}]})


# ---------------------------------------------------------------------------
# 证据引用完整性校验
# ---------------------------------------------------------------------------


def test_validate_references_ok_returns_empty() -> None:
    assert _sample_result().validate_references() == []


def test_validate_references_reports_dangling() -> None:
    result = _sample_result()
    result.root_causes[0].supporting_evidence_ids.append("ev-missing")
    problems = result.validate_references()
    assert any("ev-missing" in problem for problem in problems)


def test_validate_references_reports_duplicate_evidence() -> None:
    result = _sample_result()
    result.evidence.append(_sample_evidence("ev-0001"))
    problems = result.validate_references()
    assert any("duplicate evidence_id: ev-0001" in problem for problem in problems)


# ---------------------------------------------------------------------------
# 关联标识生成
# ---------------------------------------------------------------------------


def test_id_helpers_unique_and_prefixed() -> None:
    first_evidence_id, second_evidence_id = new_evidence_id(), new_evidence_id()
    assert first_evidence_id.startswith("ev-")
    assert first_evidence_id != second_evidence_id
    assert new_request_id().startswith("diag-")
    assert new_task_id().startswith("task-")
    assert new_id("custom").startswith("custom-")
