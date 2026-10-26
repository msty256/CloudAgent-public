#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""跨域汇总报告测试（P5.4 ``--summary``）。"""

from __future__ import annotations

import pytest

from cloudagent_ext.diagnosis.evaluation.runner import (
    EvaluationError,
    _summary_runs,
    run_evaluation,
)


class TestCrossDomainSummary:
    def test_summary_lists_both_domains(self, tmp_path) -> None:
        run_evaluation(mode="offline", domain="sync", out_dir=tmp_path)
        run_evaluation(mode="offline", domain="cross", out_dir=tmp_path)

        assert _summary_runs(last=5, out_dir=str(tmp_path)) == 0

        report = next(tmp_path.glob("summary-*.md")).read_text(encoding="utf-8")
        assert "# 跨域评测汇总" in report
        assert "| run_id | 域 | 模式 |" in report
        assert "sync" in report and "cross" in report
        assert "## 各域最近一次" in report

    def test_summary_reports_meta(self, tmp_path) -> None:
        run_evaluation(mode="offline", domain="sync", out_dir=tmp_path)
        _summary_runs(last=1, out_dir=str(tmp_path))
        report = next(tmp_path.glob("summary-*.md")).read_text(encoding="utf-8")
        assert "覆盖 run 数：1" in report
        assert "生成时间：" in report

    def test_summary_empty_dir_fails_loudly(self, tmp_path) -> None:
        with pytest.raises(EvaluationError):
            _summary_runs(last=3, out_dir=str(tmp_path / "missing"))

    def test_summary_filters_by_domain(self, tmp_path) -> None:
        run_evaluation(mode="offline", domain="sync", out_dir=tmp_path)
        run_evaluation(mode="offline", domain="cross", out_dir=tmp_path)
        _summary_runs(domain="sync", last=5, out_dir=str(tmp_path))
        report = next(tmp_path.glob("summary-*.md")).read_text(encoding="utf-8")
        assert "| sync |" in report
        assert "| cross |" not in report
