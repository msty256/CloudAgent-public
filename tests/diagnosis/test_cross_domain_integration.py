#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""跨域集成测试（变更 integrate-code-log-diagnosis，P3.6）。

覆盖：协议增强分派（code/log 复用 sql 实现）/ 派发预算（总量、单 Agent、
并发计数）/ 跨域案例加载与离线评测。
"""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from cloudagent_ext.agent._bundled_agents.sql_diagnosis import _augment_diagnosis_result
from cloudagent_ext.diagnosis.case_library import load_cases
from cloudagent_ext.diagnosis.session import SessionBudget as _SessionBudget
from cloudagent_ext.diagnosis.evaluation.runner import run_evaluation
from cloudagent_ext.tool_system.errors import ToolInputError
from cloudagent_ext.tool_system.tools import agent as agent_tools


def _result(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        is_error=False,
        output={"content": [{"type": "text", "text": text}]},
        meta={},
    )


def _agent(agent_type: str) -> SimpleNamespace:
    return SimpleNamespace(agent_type=agent_type)


class TestAugmentDispatch:
    def test_code_domain_passes_with_validation_block(self) -> None:
        text = (
            '```json\n{"request_id":"t","agent_name":"code-diagnosis","status":"success",'
            '"summary":"s","findings":[],"evidence":[],"root_causes":[],'
            '"recommendations":[],"validation_plan":[],"limitations":[],"next_steps":[]}\n```'
        )
        result = _augment_diagnosis_result(_result(text), _agent("code-diagnosis"), domain_label="code")
        blocks = [b for b in result.output["content"] if b.get("type") == "text"]
        assert any("域：code" in b["text"] for b in blocks)

    def test_log_domain_passes_with_validation_block(self) -> None:
        text = (
            '```json\n{"request_id":"t","agent_name":"log-diagnosis","status":"success",'
            '"summary":"s","findings":[],"evidence":[],"root_causes":[],'
            '"recommendations":[],"validation_plan":[],"limitations":[],"next_steps":[]}\n```'
        )
        result = _augment_diagnosis_result(_result(text), _agent("log-diagnosis"), domain_label="log")
        assert any("域：log" in b["text"] for b in result.output["content"] if b.get("type") == "text")

    def test_other_domain_passthrough(self) -> None:
        result = _augment_diagnosis_result(_result("hello"), _agent("general-purpose"), domain_label="code")
        assert result.output["content"] == [{"type": "text", "text": "hello"}]


class TestDelegationBudget:
    """预算语义未变（总 6 / 单 Agent 3），但账本改为「每上下文一个会话」。

    变更 wire-investigation-session 之前这里测的是模块级 ``_check_delegation_budget``；
    现在直接测 ``runtime_session.begin_delegation``（Agent 工具调用的就是它）。
    """

    def _ctx(self) -> SimpleNamespace:
        return SimpleNamespace(diagnosis_session_runtime=None)

    def test_total_budget(self) -> None:
        from cloudagent_ext.diagnosis.runtime_session import begin_delegation, get_or_create_runtime

        runtime = get_or_create_runtime(self._ctx(), budget=_SessionBudget(6, 3))
        # 总预算 6：两个 agent 各 3 次正好用满（单 Agent 上限 3 同时生效）
        for key in ("a", "b"):
            for index in range(3):
                # objective 必须互不相同——同 agent + 同目标会被"重复委派"防护拒绝
                begin_delegation(runtime, key, f"objective-{key}-{index}")
        from cloudagent_ext.diagnosis.session import DiagnosisSessionError

        with pytest.raises(DiagnosisSessionError, match="budget exhausted"):
            begin_delegation(runtime, "a", "objective")

    def test_per_agent_budget(self) -> None:
        from cloudagent_ext.diagnosis.runtime_session import begin_delegation, get_or_create_runtime
        from cloudagent_ext.diagnosis.session import DiagnosisSessionError

        runtime = get_or_create_runtime(self._ctx(), budget=_SessionBudget(6, 3))
        for index in range(3):
            begin_delegation(runtime, "code-diagnosis", f"objective-{index}")
        with pytest.raises(DiagnosisSessionError, match="budget exhausted for agent"):
            begin_delegation(runtime, "code-diagnosis", "objective")

    def test_concurrent_counting_is_safe(self) -> None:
        from cloudagent_ext.diagnosis.runtime_session import begin_delegation, get_or_create_runtime
        from cloudagent_ext.diagnosis.session import DiagnosisSessionError

        runtime = get_or_create_runtime(self._ctx(), budget=_SessionBudget(6, 3))

        def worker(index: int) -> None:
            try:
                # 目标互不相同，排除"重复委派"防护的干扰，只测计数竞态
                begin_delegation(runtime, "log-diagnosis", f"objective-{index}")
            except DiagnosisSessionError:
                pass

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # 锁保护下最多放行 3 次（单 Agent 上限）；无锁会超过上限
        assert runtime.session.delegations_used == 3

    def test_contexts_are_isolated(self) -> None:
        from cloudagent_ext.diagnosis.runtime_session import begin_delegation, get_or_create_runtime

        rt_a = get_or_create_runtime(self._ctx())
        rt_b = get_or_create_runtime(self._ctx())
        assert rt_a is not rt_b

        for index in range(3):
            begin_delegation(rt_a, "code-diagnosis", f"objective-{index}")
        # B 不受 A 影响
        begin_delegation(rt_b, "code-diagnosis", "objective-0")
        assert rt_a.session.delegations_used == 3
        assert rt_b.session.delegations_used == 1


class TestCrossDomainCase:
    def test_cross_case_loads(self) -> None:
        cases = load_cases("cross")
        # 对照实验要求最小样本量，cross 域已扩到 6 例（原 1 例）
        assert len(cases) >= 6
        assert any(case["case_id"] == "cross-001" for case in cases)
        for case in cases:
            assert set(case["expected_agents"]) == {"log-diagnosis", "code-diagnosis"}
            assert case["domain"] == "cross"

    def test_cross_offline_runs(self, tmp_path: Path) -> None:
        summary = run_evaluation(mode="offline", domain="cross", out_dir=tmp_path)
        assert summary["completeness"] == "complete"
        report = (tmp_path / summary["run_id"] / "summary.md").read_text(encoding="utf-8")
        assert report.startswith("# 跨域 诊断评测报告")
