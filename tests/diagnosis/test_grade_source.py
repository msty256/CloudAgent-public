#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""评分对象选择（P2）的测试。

起因（2026-11-01 实测）：`main` 派发下 `raw_output` 是**主 Agent 的散文**，
而评分器要求诊断协议 JSON，于是 `code-001` / `code-007` 两次都是 `invalid_output`、
正确率恒 0%——不是诊断失败，是量错了对象。

修法是显式化"评谁"：`--grade-source {auto,main,subagent}`，`auto` 在 `main` 模式下取
**最后一个诊断子代理的协议结果**（来自会话账本的 `entry.result`，不经主 Agent 转述）。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from cloudagent_ext.diagnosis.evaluation.executors import (
    CaseRun,
    LiveExecutor,
    _last_subagent_payload,
    _wants_subagent_grade,
)
from cloudagent_ext.diagnosis.models import DiagnosisResult, Evidence


class TestWantsSubagent:
    @pytest.mark.parametrize(
        "dispatch,source,expected",
        [
            ("main", "auto", True),      # ← 修的就是这一格：以前恒取散文
            ("main", "main", False),
            ("main", "subagent", True),
            ("direct", "auto", False),   # direct 的主输出本来就是子代理输出
            ("direct", "subagent", True),
            ("direct", "main", False),
        ],
    )
    def test_matrix(self, dispatch: str, source: str, expected: bool) -> None:
        assert _wants_subagent_grade(dispatch, source) is expected


class TestInvalidChoice:
    def test_rejects_unknown_grade_source(self) -> None:
        with pytest.raises(ValueError, match="grade_source"):
            LiveExecutor(grade_source="whatever")

    def test_accepts_valid(self) -> None:
        for value in ("auto", "main", "subagent"):
            assert LiveExecutor(grade_source=value)._grade_source == value


def _result(status: str = "success", summary: str = "ok") -> DiagnosisResult:
    return DiagnosisResult(
        request_id="req-1",
        agent_name="code-diagnosis",
        status=status,
        summary=summary,
        evidence=[
            Evidence(
                evidence_id="ev:code:1",
                source_type="read_file",
                source_ref="a.py:1",
                observation="观察到的事实",
            )
        ],
    )


class TestLastSubagentPayload:
    def test_returns_protocol_json(self) -> None:
        runtime = SimpleNamespace(
            session=SimpleNamespace(entries=[SimpleNamespace(result=_result(summary="第一条"))])
        )
        payload = json.loads(_last_subagent_payload(runtime))
        assert payload["summary"] == "第一条"
        assert payload["evidence"][0]["evidence_id"] == "ev:code:1"

    def test_takes_the_last_one(self) -> None:
        runtime = SimpleNamespace(
            session=SimpleNamespace(
                entries=[
                    SimpleNamespace(result=_result(summary="旧")),
                    SimpleNamespace(result=_result(summary="新")),
                ]
            )
        )
        assert json.loads(_last_subagent_payload(runtime))["summary"] == "新"

    def test_skips_entries_without_result(self) -> None:
        runtime = SimpleNamespace(
            session=SimpleNamespace(
                entries=[
                    SimpleNamespace(result=_result(summary="有结果")),
                    SimpleNamespace(result=None),  # 还在飞 / 失败
                ]
            )
        )
        assert json.loads(_last_subagent_payload(runtime))["summary"] == "有结果"

    def test_empty_when_no_entries(self) -> None:
        assert _last_subagent_payload(SimpleNamespace(session=SimpleNamespace(entries=[]))) == ""
        assert _last_subagent_payload(None) == ""
        assert _last_subagent_payload(SimpleNamespace(session=None)) == ""


class TestCaseRunCarriesBoth:
    def test_main_answer_separate_from_raw_output(self) -> None:
        """评分用 raw_output，人读用 main_answer——替换掉会丢信息。"""

        run = CaseRun(case_id="c1", source="live-model", raw_output='{"a":1}', main_answer="散文")
        assert run.raw_output == '{"a":1}'
        assert run.main_answer == "散文"

    def test_default_is_empty(self) -> None:
        assert CaseRun(case_id="c1", source="x", raw_output="").main_answer == ""


class TestPayloadField:
    def test_offline_run_records_grade_source(self, tmp_path) -> None:
        from cloudagent_ext.diagnosis.evaluation.runner import run_evaluation

        summary = run_evaluation(mode="offline", domain="sync", out_dir=tmp_path)
        run = json.loads(
            (tmp_path / summary["run_id"] / "run.json").read_text(encoding="utf-8")
        )
        assert run["grade_source"] == "auto"

        case_files = sorted((tmp_path / summary["run_id"] / "cases").glob("*.json"))
        case = json.loads(case_files[0].read_text(encoding="utf-8"))
        assert "main_answer" in case  # 形状稳定：即使离线也有这个键
