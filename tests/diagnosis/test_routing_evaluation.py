#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""路由评测的判定逻辑测试（P5.2）。

不调模型：只验"给了派发集合，评分对不对"，以及题库能被正确加载。
真实路由（模型是否照做）必须 live 跑，见 ``runner --routing``。
"""

from __future__ import annotations

from cloudagent_ext.diagnosis.evaluation.runner import (
    load_routing_cases,
    score_routing_case,
)


class TestScoreRoutingCase:
    def test_full_hit(self) -> None:
        case = {"case_id": "r1", "expected_agents": ["log-diagnosis"], "forbidden_agents": []}
        scored = score_routing_case(case, ["log-diagnosis"])
        assert scored["passed"] is True
        assert scored["missing"] == []

    def test_missing_agent_fails(self) -> None:
        case = {"expected_agents": ["sql-diagnosis", "code-diagnosis"], "forbidden_agents": []}
        scored = score_routing_case(case, ["sql-diagnosis"])
        assert scored["passed"] is False
        assert scored["missing"] == ["code-diagnosis"]

    def test_forbidden_agent_fails(self) -> None:
        case = {"expected_agents": ["log-diagnosis"], "forbidden_agents": ["sql-diagnosis"]}
        scored = score_routing_case(case, ["log-diagnosis", "sql-diagnosis"])
        assert scored["passed"] is False
        assert scored["violated"] == ["sql-diagnosis"]

    def test_extra_agents_allowed(self) -> None:
        """多派不是错（除非显式禁止），避免把"多查一步"判成失败。"""

        case = {"expected_agents": ["sql-diagnosis"], "forbidden_agents": []}
        scored = score_routing_case(case, ["sql-diagnosis", "log-diagnosis"])
        assert scored["passed"] is True

    def test_no_dispatch_fails(self) -> None:
        case = {"expected_agents": ["log-diagnosis"], "forbidden_agents": []}
        scored = score_routing_case(case, [])
        assert scored["passed"] is False
        assert scored["actual"] == []


class TestLoadRoutingCases:
    def test_cases_loaded(self) -> None:
        cases = load_routing_cases()
        assert len(cases) >= 5
        ids = {case["case_id"] for case in cases}
        assert {"route-001", "route-002", "route-003"} <= ids

    def test_every_case_has_expectation(self) -> None:
        for case in load_routing_cases():
            assert case.get("question")
            assert case.get("expected_agents"), f"{case.get('case_id')} 缺 expected_agents"
