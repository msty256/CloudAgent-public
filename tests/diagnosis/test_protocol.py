#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""``cloudagent_ext.diagnosis.protocol`` 单元测试。

覆盖变更 ``add-investigation-protocol`` 的规范场景：调查任务委派提示 /
子 Agent 输出约定 / 结构化结果解析 / 解析错误与关联校验。
"""

from __future__ import annotations

import json

import pytest

from cloudagent_ext.diagnosis.models import InvestigationTask
from cloudagent_ext.diagnosis.protocol import (
    DiagnosisParseError,
    build_investigation_prompt,
    parse_diagnosis_result,
    render_result_contract,
)


def _sample_task() -> InvestigationTask:
    return InvestigationTask(
        task_id="task-abc123",
        parent_request_id="diag-abc123",
        agent_type="sql-diagnosis",
        objective="分析订单查询的执行计划并定位慢点",
        inputs={"sql": "select * from orders where tenant_id = ?"},
        required_evidence=["执行计划", "表与索引元数据"],
        constraints={"read_only": True},
        budget={"max_turns": 10},
    )


def _sample_result_dict() -> dict:
    return {
        "request_id": "diag-abc123",
        "task_id": "task-abc123",
        "agent_name": "sql-diagnosis",
        "skill_name": "sql-optimization",
        "status": "success",
        "summary": "慢查询根因为索引缺失",
        "findings": ["执行计划为全表扫描"],
        "evidence": [
            {
                "evidence_id": "ev-0001",
                "source_type": "database",
                "source_ref": "tool_call:explain_sql#1",
                "observation": "Seq Scan on orders",
                "observed_at": "2026-10-11T00:00:00+08:00",
                "scope": {"table": "orders"},
                "reliability": "high",
            }
        ],
        "root_causes": [
            {
                "description": "orders.tenant_id 缺少可用索引",
                "confidence": 0.72,
                "supporting_evidence_ids": ["ev-0001"],
                "counter_evidence": ["统计信息可能过期"],
                "confidence_rationale": "单一证据支持，需复测",
            }
        ],
        "recommendations": ["为 (tenant_id, created_at) 建联合索引"],
        "validation_plan": ["建索引后重跑 EXPLAIN"],
        "limitations": ["未获取生产统计信息"],
        "next_steps": [],
    }


# ---------------------------------------------------------------------------
# 调查任务委派提示
# ---------------------------------------------------------------------------


def test_prompt_contains_task_elements() -> None:
    task = _sample_task()
    prompt = build_investigation_prompt(task)
    assert task.task_id in prompt
    assert task.parent_request_id in prompt
    assert task.objective in prompt
    assert "orders" in prompt  # 来自 inputs
    assert "执行计划" in prompt  # 来自 required_evidence
    assert "read_only" in prompt  # 来自 constraints
    assert "max_turns" in prompt  # 来自 budget


def test_prompt_includes_output_contract() -> None:
    prompt = build_investigation_prompt(_sample_task())
    assert render_result_contract() in prompt
    assert "```json" in prompt
    assert "json 代码块结束" in prompt


def test_prompt_appends_extra_context() -> None:
    prompt = build_investigation_prompt(_sample_task(), extra_context="附加上下文：目标表为 orders")
    assert "附加上下文：目标表为 orders" in prompt


# ---------------------------------------------------------------------------
# 子 Agent 输出约定
# ---------------------------------------------------------------------------


def test_contract_text_has_key_elements() -> None:
    contract = render_result_contract()
    for token in (
        "```json",
        "json 代码块结束",
        "request_id",
        "非空字符串",
        "status",
        "success",
        "partial",
        "failed",
        "evidence",
        "root_causes",
    ):
        assert token in contract


# ---------------------------------------------------------------------------
# 结构化结果解析
# ---------------------------------------------------------------------------


def test_parse_fenced_block_with_prose() -> None:
    payload = json.dumps(_sample_result_dict(), ensure_ascii=False)
    text = "分析过程如下……\n\n```json\n" + payload + "\n```"
    result = parse_diagnosis_result(text)
    assert result.request_id == "diag-abc123"
    assert result.status == "success"
    assert len(result.evidence) == 1
    assert result.root_causes[0].confidence == 0.72


def test_parse_multiple_blocks_takes_last() -> None:
    first = _sample_result_dict()
    first["summary"] = "第一个结论"
    second = _sample_result_dict()
    second["summary"] = "最终的结论"
    text = (
        "```json\n" + json.dumps(first, ensure_ascii=False) + "\n```\n\n"
        "修正后：\n\n```json\n" + json.dumps(second, ensure_ascii=False) + "\n```"
    )
    result = parse_diagnosis_result(text)
    assert result.summary == "最终的结论"


def test_parse_uppercase_language_tag() -> None:
    payload = json.dumps(_sample_result_dict(), ensure_ascii=False)
    text = "```JSON\n" + payload + "\n```"
    assert parse_diagnosis_result(text).request_id == "diag-abc123"


def test_parse_bare_json_text() -> None:
    text = json.dumps(_sample_result_dict(), ensure_ascii=False)
    assert parse_diagnosis_result(text).status == "success"


# ---------------------------------------------------------------------------
# 解析错误与关联校验
# ---------------------------------------------------------------------------


def test_parse_error_is_value_error_subclass() -> None:
    assert issubclass(DiagnosisParseError, ValueError)


def test_parse_rejects_plain_text() -> None:
    with pytest.raises(DiagnosisParseError):
        parse_diagnosis_result("这里没有任何结构化结果")


def test_parse_rejects_bad_json_syntax() -> None:
    with pytest.raises(DiagnosisParseError):
        parse_diagnosis_result("```json\n{not-valid-json}\n```")


def test_parse_rejects_invalid_field_values() -> None:
    bad = _sample_result_dict()
    bad["status"] = "unknown"
    text = "```json\n" + json.dumps(bad, ensure_ascii=False) + "\n```"
    with pytest.raises(DiagnosisParseError) as excinfo:
        parse_diagnosis_result(text)
    assert "status" in str(excinfo.value)


def test_parse_rejects_missing_required_field() -> None:
    bad = _sample_result_dict()
    del bad["summary"]
    with pytest.raises(DiagnosisParseError) as excinfo:
        parse_diagnosis_result(json.dumps(bad, ensure_ascii=False))
    assert "summary" in str(excinfo.value)


def test_request_id_mismatch_rejected() -> None:
    text = json.dumps(_sample_result_dict(), ensure_ascii=False)
    with pytest.raises(DiagnosisParseError) as excinfo:
        parse_diagnosis_result(text, expected_request_id="diag-other")
    assert "mismatch" in str(excinfo.value)


def test_request_id_match_accepted() -> None:
    text = json.dumps(_sample_result_dict(), ensure_ascii=False)
    result = parse_diagnosis_result(text, expected_request_id="diag-abc123")
    assert result.request_id == "diag-abc123"


# ---------------------------------------------------------------------------
# 已知书写变体的宽容归一化（变更 fix-diagnosis-field-types）
# ---------------------------------------------------------------------------


def test_scope_string_normalized_to_note_object() -> None:
    payload = _sample_result_dict()
    payload["evidence"][0]["scope"] = "表结构"
    result = parse_diagnosis_result(json.dumps(payload, ensure_ascii=False))
    assert result.evidence[0].scope == {"note": "表结构"}


def test_counter_evidence_string_normalized_to_list() -> None:
    payload = _sample_result_dict()
    payload["root_causes"][0]["counter_evidence"] = "统计信息可能过期"
    result = parse_diagnosis_result(json.dumps(payload, ensure_ascii=False))
    assert result.root_causes[0].counter_evidence == ["统计信息可能过期"]


def test_counter_evidence_empty_string_normalized_to_empty_list() -> None:
    payload = _sample_result_dict()
    payload["root_causes"][0]["counter_evidence"] = ""
    result = parse_diagnosis_result(json.dumps(payload, ensure_ascii=False))
    assert result.root_causes[0].counter_evidence == []


def test_normal_shapes_unaffected_by_normalization() -> None:
    result = parse_diagnosis_result(json.dumps(_sample_result_dict(), ensure_ascii=False))
    assert result.evidence[0].scope == {"table": "orders"}
    assert result.root_causes[0].counter_evidence == ["统计信息可能过期"]


def test_normalization_scope_limited_to_known_variants() -> None:
    # 范围之外的类型错误仍然严格拒绝（例如 evidence 缺 observation）
    payload = _sample_result_dict()
    del payload["evidence"][0]["observation"]
    with pytest.raises(DiagnosisParseError) as excinfo:
        parse_diagnosis_result(json.dumps(payload, ensure_ascii=False))
    assert "observation" in str(excinfo.value)


def test_contract_text_states_field_types() -> None:
    text = render_result_contract()
    assert "scope（对象" in text
    assert "counter_evidence（字符串数组" in text


class TestUnescapedQuoteRepair:
    """子代理在字符串里直接写英文引号时，JSON 会被提前闭合（2026-10-25 实跑）。"""

    def test_unescaped_quotes_are_escaped(self) -> None:
        from cloudagent_ext.diagnosis.protocol import parse_diagnosis_result

        text = (
            '```json' + chr(10)
            + '{"request_id":"r","agent_name":"a","status":"success",'
            + '"summary":"日志写了 "task aborted" 后面还有","evidence":[]}'
            + chr(10) + "```"
        )
        result = parse_diagnosis_result(text)
        assert result.summary == '日志写了 "task aborted" 后面还有'

    def test_valid_json_untouched(self) -> None:
        from cloudagent_ext.diagnosis.protocol import parse_diagnosis_result

        text = (
            '```json' + chr(10)
            + '{"request_id":"r","agent_name":"a","status":"success","summary":"正常","evidence":[]}'
            + chr(10) + "```"
        )
        assert parse_diagnosis_result(text).summary == "正常"

    def test_genuine_syntax_error_still_rejected(self) -> None:
        import pytest

        from cloudagent_ext.diagnosis.protocol import DiagnosisParseError, parse_diagnosis_result

        text = (
            '```json' + chr(10)
            + '{"request_id":"r" "agent_name":"a","status":"success","summary":"s","evidence":[]}'
            + chr(10) + "```"
        )
        with pytest.raises(DiagnosisParseError):
            parse_diagnosis_result(text)
