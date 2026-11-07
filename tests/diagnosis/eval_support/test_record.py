#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""RunRecord v1 契约测试（EVAL-P1a）——零模型、零数据库成本。"""

from __future__ import annotations

import json

import pytest

from cloudagent_ext.diagnosis.eval_support.record import (
    OUTCOME_STATUSES,
    SCHEMA_VERSION,
    RunRecord,
    RunRecordError,
    RunRequest,
    RunRequestError,
    record_from_json,
    record_to_json,
    request_from_json,
    request_to_json,
)


def _valid_record_payload() -> dict:
    return {
        "schema_version": 1,
        "record_id": "rec-sql-001-20261107T113000",
        "request_id": "req-0001",
        "case": {"case_id": "sql-001", "domain": "sql"},
        "run": {
            "started_at": "2026-11-07T11:28:00+08:00",
            "finished_at": "2026-11-07T11:30:03+08:00",
            "elapsed_sec": 123.4,
        },
        "subject": {
            "product": "cloudagent",
            "version": "1.2.1",
            "git_sha": "ab12cd3",
            "model": "deepseek-v4.1-flash",
            "provider": "deepseek",
            "dispatch_mode": "main",
            "grade_source": "auto",
            "permission_mode": "dontAsk",
            "arm_env": {"CLOUDAGENT_GAP_INJECTION": "on"},
        },
        "outcome": {
            "status": "ok",
            "error": None,
            "raw_output": '{"root_causes": []}',
            "main_answer": "诊断完成",
            "graded_text": '{"root_causes": []}',
        },
        "trace": {"events": [], "calls": []},
        "mechanism": {"delegations": 2, "gaps_total": 3},
        "usage": {
            "input_tokens": 1167134,
            "output_tokens": 30708,
            "cached_input_tokens": 0,
            "model_calls": 45,
            "calls_without_usage": 0,
            "available": True,
        },
    }


class TestRunRequestStrictness:
    def test_valid_request_round_trip(self) -> None:
        payload = {
            "schema_version": 1,
            "request_id": "req-0001",
            "case_id": "sql-001",
            "domain": "sql",
            "question": "订单列表页变慢，请诊断",
            "context": {"sql": "SELECT * FROM orders WHERE tenant_id = 7"},
            "options": {"dispatch_mode": "main", "grade_source": "auto"},
        }
        request = request_from_json(payload)
        assert request.request_id == "req-0001"
        assert request.options["timeout_sec"] == 300  # 缺省补全
        assert request_to_json(request)["schema_version"] == SCHEMA_VERSION

    def test_rejects_ground_truth_field(self) -> None:
        """安全边界：把整份 case（带答案）传进来必须当场报错，不是静默忽略。"""

        payload = {
            "schema_version": 1,
            "request_id": "req-0001",
            "case_id": "sql-001",
            "domain": "sql",
            "question": "x",
            "ground_truth": {"root_causes": [{"match_terms": ["索引"]}]},
        }
        with pytest.raises(RunRequestError, match="ground_truth"):
            request_from_json(payload)

    @pytest.mark.parametrize(
        "field", ["root_causes", "expected_agents", "match_terms", "verification"]
    )
    def test_rejects_other_gt_smuggling_fields(self, field: str) -> None:
        payload = {
            "schema_version": 1,
            "request_id": "req-0001",
            "case_id": "sql-001",
            "domain": "sql",
            "question": "x",
            field: "whatever",
        }
        with pytest.raises(RunRequestError, match=field):
            request_from_json(payload)

    def test_rejects_wrong_schema_version(self) -> None:
        payload = {
            "schema_version": 2,
            "request_id": "r",
            "case_id": "c",
            "domain": "sql",
            "question": "x",
        }
        with pytest.raises(RunRequestError, match="schema_version"):
            request_from_json(payload)

    @pytest.mark.parametrize("key", ["request_id", "case_id", "question"])
    @pytest.mark.parametrize("bad", ["", "   "])
    def test_rejects_empty_required_fields(self, key: str, bad: str) -> None:
        payload = {
            "schema_version": 1,
            "request_id": "req-0001",
            "case_id": "sql-001",
            "domain": "sql",
            "question": "x",
        }
        payload[key] = bad
        with pytest.raises(RunRequestError, match=key):
            request_from_json(payload)

    @pytest.mark.parametrize("domain", ["kafka", "SQL", ""])
    def test_rejects_unknown_domain(self, domain: str) -> None:
        payload = {
            "schema_version": 1,
            "request_id": "req-0001",
            "case_id": "sql-001",
            "domain": domain or "sql",
            "question": "x",
        }
        if domain == "":
            payload["domain"] = ""
        with pytest.raises(RunRequestError):
            request_from_json(payload)

    def test_rejects_non_dontask_permission_mode(self) -> None:
        """permission_mode 白名单只有 dontAsk——口子留着，放宽时能看见 diff。"""

        payload = {
            "schema_version": 1,
            "request_id": "req-0001",
            "case_id": "sql-001",
            "domain": "sql",
            "question": "x",
            "options": {"permission_mode": "bypassPermissions"},
        }
        with pytest.raises(RunRequestError, match="permission_mode"):
            request_from_json(payload)

    def test_rejects_unknown_option_key(self) -> None:
        payload = {
            "schema_version": 1,
            "request_id": "req-0001",
            "case_id": "sql-001",
            "domain": "sql",
            "question": "x",
            "options": {"temperature": 0.7},
        }
        with pytest.raises(RunRequestError, match="temperature"):
            request_from_json(payload)

    def test_rejects_non_positive_timeout(self) -> None:
        payload = {
            "schema_version": 1,
            "request_id": "req-0001",
            "case_id": "sql-001",
            "domain": "sql",
            "question": "x",
            "options": {"timeout_sec": 0},
        }
        with pytest.raises(RunRequestError, match="timeout_sec"):
            request_from_json(payload)

    def test_rejects_non_object_payload(self) -> None:
        with pytest.raises(RunRequestError):
            request_from_json(["not", "a", "dict"])  # type: ignore[arg-type]


class TestRunRecordRoundTrip:
    def test_round_trip_field_by_field(self) -> None:
        payload = _valid_record_payload()
        record = record_from_json(payload)
        assert record_to_json(record) == payload

    def test_serialization_is_byte_stable(self) -> None:
        """record_to_json 两次序列化必须逐字节相等（P2 等价性 diff 的前提）。"""

        record = record_from_json(_valid_record_payload())
        first = json.dumps(record_to_json(record), ensure_ascii=False, sort_keys=False)
        second = json.dumps(record_to_json(record), ensure_ascii=False, sort_keys=False)
        assert first == second

    def test_json_field_order_matches_schema(self) -> None:
        """顶层字段顺序按 schema §3.1 固定（可读 diff 依赖它）。"""

        record = record_from_json(_valid_record_payload())
        assert list(record_to_json(record)) == [
            "schema_version",
            "record_id",
            "request_id",
            "case",
            "run",
            "subject",
            "outcome",
            "trace",
            "mechanism",
            "usage",
        ]

    def test_trace_and_mechanism_may_be_null(self) -> None:
        """黑盒 subject 不提供 trace/mechanism 也合法。"""

        payload = _valid_record_payload()
        payload["trace"] = None
        payload["mechanism"] = None
        record = record_from_json(payload)
        assert record.trace is None and record.mechanism is None
        assert record_to_json(record)["trace"] is None

    def test_reads_schema_version_1_only(self) -> None:
        payload = _valid_record_payload()
        payload["schema_version"] = 2
        with pytest.raises(RunRecordError, match="schema_version"):
            record_from_json(payload)

    @pytest.mark.parametrize("status", sorted(OUTCOME_STATUSES))
    def test_all_five_outcome_statuses_accepted(self, status: str) -> None:
        payload = _valid_record_payload()
        payload["outcome"]["status"] = status
        record = record_from_json(payload)
        assert record.outcome["status"] == status

    def test_rejects_removed_empty_status(self) -> None:
        """``empty`` 档已删除（审查裁决：空输出归 unfinished，与 categorize 一致）——
        写它会红，防止旧口径悄悄回流。"""

        payload = _valid_record_payload()
        payload["outcome"]["status"] = "empty"
        with pytest.raises(RunRecordError, match="outcome.status"):
            record_from_json(payload)

    def test_rejects_unknown_outcome_status(self) -> None:
        payload = _valid_record_payload()
        payload["outcome"]["status"] = "great_success"
        with pytest.raises(RunRecordError, match="outcome.status"):
            record_from_json(payload)

    def test_rejects_invalid_domain(self) -> None:
        payload = _valid_record_payload()
        payload["case"]["domain"] = "kafka"
        with pytest.raises(RunRecordError, match="domain"):
            record_from_json(payload)

    def test_tolerates_unknown_top_level_fields(self) -> None:
        """只增不改：同版本内新增字段，旧读取方必须照常能读已知部分。"""

        payload = _valid_record_payload()
        payload["future_field"] = {"whatever": True}
        record = record_from_json(payload)
        assert record.case_id == "sql-001"


class TestUsageContract:
    def test_available_false_means_null_not_zero(self) -> None:
        """没采到的 token 必须是 null——0 会冒充"零消耗"。"""

        payload = _valid_record_payload()
        payload["usage"] = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cached_input_tokens": 0,
            "model_calls": 45,
            "calls_without_usage": 45,
            "available": False,
        }
        with pytest.raises(RunRecordError, match="必须为 null"):
            record_from_json(payload)

        payload["usage"]["input_tokens"] = None
        payload["usage"]["output_tokens"] = None
        payload["usage"]["cached_input_tokens"] = None
        record = record_from_json(payload)
        assert record.usage["input_tokens"] is None
        assert record.usage["output_tokens"] is None
        assert record.usage["cached_input_tokens"] is None
        assert record.usage["calls_without_usage"] == 45
        assert record.usage["available"] is False

    def test_available_true_requires_integer_tokens(self) -> None:
        payload = _valid_record_payload()
        payload["usage"]["input_tokens"] = "很多"
        with pytest.raises(RunRecordError, match="input_tokens"):
            record_from_json(payload)

    def test_usage_missing_available_flag_rejected(self) -> None:
        payload = _valid_record_payload()
        del payload["usage"]["available"]
        with pytest.raises(RunRecordError, match="available"):
            record_from_json(payload)


def test_run_request_dataclass_defaults() -> None:
    """RunRequest 结构上没有 ground_truth 字段（dataclass 自身就是防线的一部分）。"""

    request = RunRequest()
    assert "ground_truth" not in RunRequest.__dataclass_fields__
    assert request.schema_version == SCHEMA_VERSION


def test_record_dataclass_trace_optional() -> None:
    record = RunRecord()
    assert record.trace is None and record.mechanism is None
