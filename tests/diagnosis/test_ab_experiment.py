#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""对照实验框架测试（变更 add-diagnosis-ab-experiment）。

覆盖：注入开关（函数式读 env）、注入计数、variant/repeat 落盘、对比报告的
元信息与"不构成结论"标注。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from cloudagent_ext.diagnosis.evaluation.runner import (
    _compare_runs,
    run_evaluation,
)
from cloudagent_ext.tool_system.tools.agent import _with_open_gaps, gap_injection_enabled


def _runtime(open_gap: str = "核对 orders 表 order-1") -> SimpleNamespace:
    return SimpleNamespace(
        gaps=[SimpleNamespace(status="open", statement=open_gap, restatements=0)],
        injected_dispatches=0,
    )


class TestInjectionSwitch:
    def test_enabled_by_default(self, monkeypatch) -> None:
        monkeypatch.delenv("CLOUDAGENT_GAP_INJECTION", raising=False)
        assert gap_injection_enabled() is True

    def test_disabled_by_env(self, monkeypatch) -> None:
        monkeypatch.setenv("CLOUDAGENT_GAP_INJECTION", "off")
        assert gap_injection_enabled() is False

    def test_injection_skipped_and_not_counted(self, monkeypatch) -> None:
        monkeypatch.setenv("CLOUDAGENT_GAP_INJECTION", "off")
        runtime = _runtime()
        assert _with_open_gaps("BASE", runtime) == "BASE"
        assert runtime.injected_dispatches == 0

    def test_injection_applied_and_counted(self, monkeypatch) -> None:
        monkeypatch.setenv("CLOUDAGENT_GAP_INJECTION", "on")
        runtime = _runtime()
        prompt = _with_open_gaps("BASE", runtime)
        assert "当前未解决缺口" in prompt
        assert runtime.injected_dispatches == 1


class TestRunnerVariant:
    def test_variant_and_repeat_recorded(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("CLOUDAGENT_GAP_INJECTION", raising=False)
        summary = run_evaluation(
            mode="offline",
            domain="sync",
            out_dir=tmp_path,
            variant="gaps-om" if False else "gaps-on",
            repeat=2,
        )
        run = json.loads((tmp_path / summary["run_id"] / "run.json").read_text(encoding="utf-8"))
        assert run["variant"] == "gaps-on"
        assert run["repeat"] == 2
        assert run["repeats"]["rounds"] == 2
        assert "experiment" in run

    def test_gaps_off_forces_env(self, tmp_path, monkeypatch) -> None:
        from cloudagent_ext.diagnosis.evaluation.executors import CaseRun

        monkeypatch.delenv("CLOUDAGENT_GAP_INJECTION", raising=False)
        seen: list[str | None] = []

        class _EnvCheckExecutor:
            model_label = "stub"

            def prepare(self) -> None:
                return None

            def run_case(self, case):
                import os

                seen.append(os.environ.get("CLOUDAGENT_GAP_INJECTION"))
                return CaseRun(case_id=case["case_id"], source="stub", raw_output="", error="stop")

        run_evaluation(
            mode="offline",
            domain="sync",
            out_dir=tmp_path,
            variant="gaps-off",
            executor=_EnvCheckExecutor(),
        )
        assert seen and all(value == "off" for value in seen)
        # runner 结束后必须还原，避免污染同进程的其他评测
        import os

        assert os.environ.get("CLOUDAGENT_GAP_INJECTION") is None

    def test_unknown_variant_rejected(self, tmp_path) -> None:
        from cloudagent_ext.diagnosis.evaluation.runner import EvaluationError

        with pytest.raises(EvaluationError):
            run_evaluation(mode="offline", domain="sync", out_dir=tmp_path, variant="bogus")


class TestCompareReport:
    def test_offline_compare_marks_no_conclusion(self, tmp_path) -> None:
        a = run_evaluation(mode="offline", domain="sync", out_dir=tmp_path, variant="gaps-on")
        b = run_evaluation(mode="offline", domain="sync", out_dir=tmp_path, variant="gaps-off")
        code = _compare_runs(a["run_id"], b["run_id"], out_dir=str(tmp_path))
        assert code == 0
        report = next(tmp_path.glob("compare-*.md")).read_text(encoding="utf-8")
        assert "不构成对照结论" in report
        assert "treatment 未施加" in report  # offline 无注入
        assert "样本量" in report and "重复轮次" in report and "模式" in report
