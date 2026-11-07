#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""``CaseRun → RunRecord`` 映射测试（EVAL-P1a）——全部用 fake 数据，零模型成本。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from cloudagent_ext.diagnosis.eval_support.execute import (
    _CALL_TEXT_LIMIT,
    case_run_to_record,
    execute_case,
)
from cloudagent_ext.diagnosis.eval_support.record import (
    RunRequest,
    record_from_json,
    record_to_json,
)


def _request(**options: Any) -> RunRequest:
    return request_of(
        dispatch_mode=options.get("dispatch_mode", "main"),
        grade_source=options.get("grade_source", "auto"),
    )


def request_of(dispatch_mode: str = "main", grade_source: str = "auto") -> RunRequest:
    return RunRequest(
        request_id="req-0001",
        case_id="sql-001",
        domain="sql",
        question="订单列表页变慢，请诊断",
        options={"dispatch_mode": dispatch_mode, "grade_source": grade_source},
    )


@dataclass
class FakeCaseRun:
    """只带映射表用到的字段（CaseRun 的测试替身）。"""

    case_id: str = "sql-001"
    source: str = "live"
    raw_output: str = '{"root_causes": []}'
    events: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    error: str | None = None
    calls: list = field(default_factory=list)
    main_answer: str = ""


class FakeExecutor:
    """返回固定 CaseRun 的桩（任务卡 4.4：不调模型）。"""

    def __init__(self, case_run: FakeCaseRun) -> None:
        self._case_run = case_run
        self.model_label = "fake-model"

    def run_case(self, case: dict) -> FakeCaseRun:
        assert case["case_id"] == "sql-001"
        assert case["input"]["question"]
        return self._case_run


_SUBJECT = {"product": "cloudagent", "version": "test", "git_sha": "unknown",
            "model": "fake-model", "provider": "deepseek", "dispatch_mode": "main",
            "grade_source": "auto", "permission_mode": "dontAsk", "arm_env": {}}


def _to_record(case_run: FakeCaseRun, request: RunRequest | None = None, **kw: Any):
    return case_run_to_record(
        case_run,
        request or _request(),
        record_id="rec-sql-001-x",
        started_at="2026-11-07T11:28:00+08:00",
        finished_at="2026-11-07T11:30:03+08:00",
        subject=dict(_SUBJECT),
        **kw,
    )


_META = {
    "model": "fake-model",
    "elapsed_sec": 12.5,
    "model_calls": 3,
    "delegations": 2,
    "agents_dispatched": ["sql-diagnosis"],
    "gaps_total": 5,
    "gaps_resolved": 1,
    "injected_dispatches": 0,
    "decision_counts": {"gap_resolved": 1},
    "decision_log": [{"reason": "x"}],
    "gap_events": [{"gap_id": "g1"}],
    "compaction": {"sr_applied": 1},
    "recall_count": 0,
    "recall_miss": 0,
    "state_revision": 0,
    "stale_discarded": 0,
    "assessments": {"ok": 1},
    # 不在白名单里的字段（将来 meta 可能新增的调试字段）——必须被排除
    "tools_resolved": ["Read", "Grep"],
    "terminal": "completed",
    "dispatch_incomplete": False,
    "grade_source": "subagent",
    "usage": {
        "input_tokens": 1000,
        "output_tokens": 200,
        "cached_input_tokens": 50,
        "calls_with_usage": 3,
        "calls_without_usage": 0,
        "available": True,
    },
}


class TestStatusDetermination:
    """五档口径（审查裁决：empty 档已删除，空输出归 unfinished）。"""

    def test_ok_is_provisional(self) -> None:
        record = _to_record(FakeCaseRun(meta=dict(_META)))
        assert record.outcome["status"] == "ok"
        assert record.outcome["status_provisional"] is True

    def test_timeout_by_error_text(self) -> None:
        record = _to_record(FakeCaseRun(error="timeout after 300s", meta=dict(_META)))
        assert record.outcome["status"] == "timeout"
        assert "status_provisional" not in record.outcome

    def test_crashed_by_other_error(self) -> None:
        record = _to_record(FakeCaseRun(error="RuntimeError: boom", meta=dict(_META)))
        assert record.outcome["status"] == "crashed"

    def test_empty_output_is_unfinished(self) -> None:
        """空输出 = 没拿到作答机会 → unfinished（不是独立的 empty 档）。"""

        record = _to_record(FakeCaseRun(raw_output="   ", main_answer="", meta=dict(_META)))
        assert record.outcome["status"] == "unfinished"
        assert "status_provisional" not in record.outcome


class TestGradedText:
    """schema §5：选谁评分只有这一处实现。"""

    def test_main_mode_auto_takes_subagent_payload(self) -> None:
        record = _to_record(FakeCaseRun(meta=dict(_META)))  # auto + main + effective=subagent
        assert record.outcome["graded_text"] == '{"root_causes": []}'

    def test_main_mode_without_subagent_payload_is_unfinished(self) -> None:
        """main 模式没派发子代理 → graded_text 空串、status 记 unfinished
        （空输出=没拿到作答机会；审查裁决后不再有 empty 档）。"""

        meta = dict(_META, grade_source="main")
        record = _to_record(FakeCaseRun(meta=meta))
        assert record.outcome["graded_text"] == ""
        assert record.outcome["status"] == "unfinished"
        assert "status_provisional" not in record.outcome

    def test_explicit_main_grade_takes_prose(self) -> None:
        record = _to_record(
            FakeCaseRun(meta=dict(_META, grade_source="subagent"),
                        main_answer="主代理散文结论"),
            _request(grade_source="main"),
        )
        assert record.outcome["graded_text"] == "主代理散文结论"
        assert record.outcome["status"] == "ok"

    def test_direct_mode_takes_main_output(self) -> None:
        record = _to_record(
            FakeCaseRun(raw_output="直驱协议输出", main_answer="直驱协议输出",
                        meta=dict(_META, grade_source="main")),
            _request(dispatch_mode="direct"),
        )
        assert record.outcome["graded_text"] == "直驱协议输出"


class TestMechanismWhitelist:
    def test_whitelisted_keys_copied(self) -> None:
        record = _to_record(FakeCaseRun(meta=dict(_META)))
        mechanism = record.mechanism or {}
        assert mechanism["delegations"] == 2
        assert mechanism["agents_dispatched"] == ["sql-diagnosis"]
        assert mechanism["gaps_total"] == 5
        assert mechanism["decision_counts"] == {"gap_resolved": 1}
        assert mechanism["compaction"] == {"sr_applied": 1}
        assert mechanism["state_revision"] == 0

    def test_non_whitelisted_keys_excluded(self) -> None:
        """白名单而非黑名单：meta 新增的调试字段不进契约。"""

        record = _to_record(FakeCaseRun(meta=dict(_META)))
        mechanism = record.mechanism or {}
        assert "tools_resolved" not in mechanism
        assert "terminal" not in mechanism
        assert "dispatch_incomplete" not in mechanism
        assert "grade_source" not in mechanism

    def test_error_is_redacted(self) -> None:
        dsn = "postgresql://user:secret@host:5433/db"
        record = _to_record(FakeCaseRun(error=f"RuntimeError: {dsn}"))
        assert record.outcome["error"] is not None
        assert "secret" not in str(record.outcome["error"])


class TestUsageMapping:
    def test_available_true_maps_tokens(self) -> None:
        record = _to_record(FakeCaseRun(meta=dict(_META)))
        assert record.usage == {
            "input_tokens": 1000,
            "output_tokens": 200,
            "cached_input_tokens": 50,
            "model_calls": 3,
            "calls_without_usage": 0,
            "available": True,
        }

    def test_available_false_means_null_not_zero(self) -> None:
        meta = dict(
            _META,
            usage={
                "input_tokens": 0,
                "output_tokens": 0,
                "cached_input_tokens": 0,
                "calls_with_usage": 0,
                "calls_without_usage": 3,
                "available": False,
            },
        )
        record = _to_record(FakeCaseRun(meta=meta))
        assert record.usage["input_tokens"] is None
        assert record.usage["output_tokens"] is None
        assert record.usage["cached_input_tokens"] is None
        assert record.usage["calls_without_usage"] == 3
        assert record.usage["available"] is False


class TestTraceTruncation:
    def test_long_call_content_truncated_with_marker(self) -> None:
        long_call = {"n": 1, "content": "x" * (_CALL_TEXT_LIMIT + 100), "usage": None}
        record = _to_record(FakeCaseRun(calls=[long_call]))
        call = (record.trace or {})["calls"][0]
        assert len(call["content"]) == _CALL_TEXT_LIMIT
        assert call["truncated"] is True

    def test_short_call_untouched(self) -> None:
        call = {"n": 1, "content": "short", "usage": None}
        record = _to_record(FakeCaseRun(calls=[call]))
        assert (record.trace or {})["calls"][0] == call


class TestExecuteCaseWithFakeExecutor:
    def test_end_to_end_with_injected_executor(self) -> None:
        """端到端（fake executor）：产出可通过 record_from_json 校验的 RunRecord。"""

        record = execute_case(_request(), executor=FakeExecutor(FakeCaseRun(meta=dict(_META))))
        assert record.case_id == "sql-001"
        assert record.record_id.startswith("rec-sql-001-")
        assert record.subject["model"] == "fake-model"
        # 产物必须过得了契约自己的校验
        parsed = record_from_json(record_to_json(record))
        assert parsed.outcome["status"] == record.outcome["status"]

    def test_elapsed_falls_back_to_measured(self) -> None:
        record = execute_case(
            _request(), executor=FakeExecutor(FakeCaseRun(meta={"model": "m"}))
        )
        assert record.elapsed_sec >= 0.0


class TestSubjectArmEnv:
    def test_arm_env_only_records_set_switches(self, monkeypatch) -> None:
        monkeypatch.setenv("CLOUDAGENT_GAP_INJECTION", "off")
        monkeypatch.delenv("CLOUDAGENT_CONTEXT_REDUCE", raising=False)
        from cloudagent_ext.diagnosis.eval_support.execute import build_subject

        subject = build_subject(_request(), "m")
        assert subject["arm_env"] == {"CLOUDAGENT_GAP_INJECTION": "off"}
        assert subject["dispatch_mode"] == "main"
        assert subject["permission_mode"] == "dontAsk"
