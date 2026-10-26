#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""同步域案例集与 Skill 内容契约（变更 add-sync-analysis-skill）。

覆盖：5 个案例可加载、域级 agent 约束、禁项长度、阴性案例的 severity、
离线夹具齐全，以及 SKILL.md 的两条结构性约束（主会话适用 / 委派区分词前置）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cloudagent_ext.diagnosis.case_library import _EXPECTED_AGENTS, load_cases

_CASES = load_cases("sync")
_BY_ID = {case["case_id"]: case for case in _CASES}
_FIXTURES = Path("cloudagent_ext/diagnosis/evaluation/fixtures/offline_responses.json")


def test_five_cases_loaded() -> None:
    assert [case["case_id"] for case in _CASES] == [
        "sync-001",
        "sync-002",
        "sync-003",
        "sync-004",
        "sync-005",
    ]


@pytest.mark.parametrize("case", _CASES, ids=lambda c: c["case_id"])
def test_domain_minimum_agents_present(case: dict) -> None:
    assert set(_EXPECTED_AGENTS["sync"]) <= set(case["expected_agents"])
    assert "sql-diagnosis" in case["expected_agents"]


def test_log_and_code_cases_declare_extra_agents() -> None:
    assert "log-diagnosis" in _BY_ID["sync-002"]["expected_agents"]
    assert {"log-diagnosis", "code-diagnosis"} <= set(_BY_ID["sync-003"]["expected_agents"])
    # 其余案例不应为了过校验而虚构委派
    assert _BY_ID["sync-001"]["expected_agents"] == ["sql-diagnosis"]
    assert _BY_ID["sync-005"]["expected_agents"] == ["sql-diagnosis"]


@pytest.mark.parametrize("case", _CASES, ids=lambda c: c["case_id"])
def test_forbidden_findings_are_short_enough(case: dict) -> None:
    """safety.py 只匹配 ≤14 字的禁项，超长短语会静默失效。"""

    for finding in case["ground_truth"].get("forbidden_findings", []):
        assert len(finding) <= 14, f"{case['case_id']} 的禁项过长: {finding}"


def test_negative_cases_use_severity_none() -> None:
    for case_id in ("sync-004", "sync-005"):
        causes = _BY_ID[case_id]["ground_truth"]["root_causes"]
        assert causes, f"{case_id} 必须有 root_causes（空 GT 会被 validate_case 拒绝）"
        assert all(cause["severity"] == "none" for cause in causes)


def test_kafka_red_line_present() -> None:
    forbidden = _BY_ID["sync-004"]["ground_truth"]["forbidden_findings"]
    assert any("Kafka" in item for item in forbidden)


def test_offline_fixtures_cover_all_cases() -> None:
    data = json.loads(_FIXTURES.read_text(encoding="utf-8"))
    responses = data["responses"]
    for case in _CASES:
        assert case["case_id"] in responses, f"缺少离线夹具: {case['case_id']}"
        assert responses[case["case_id"]]["response_text"].strip()


@pytest.fixture(scope="module")
def skill_body() -> str:
    from cloudagent_ext.skills.bundled.sync_analysis import _load_portable_skill

    return _load_portable_skill()[1]


class TestSkillContent:
    def test_scope_line_targets_main_session(self, skill_body: str) -> None:
        body = skill_body
        head = body.strip().splitlines()[0] + body.strip().splitlines()[1]
        assert "主会话" in head or "主会话" in body[:200]

    def test_seven_steps_present(self, skill_body: str) -> None:
        body = skill_body
        steps = (
            "是否被触发",
            "消费是否成功",
            "业务处理是否成功",
            "是否落库",
            "上游对照",
            "判阶段",
            "声明缺口",
        )
        for index, title in enumerate(steps, start=1):
            assert f"{index}. **{title}" in body, f"缺少第 {index} 步：{title}"

    def test_forbids_reading_credentials(self, skill_body: str) -> None:
        assert "db_sim.env" in skill_body
        assert "config.json" in skill_body
        assert "不要读凭据" in skill_body

    def test_names_the_log_root_convention(self, skill_body: str) -> None:
        """实跑踩过：主 Agent 猜到旧夹具 logs-sim，关键词全 0 命中。"""

        assert "logs-sim" in skill_body
        assert "CLOUDAGENT_LOG_ROOT" in skill_body

    def test_delegation_templates_differ_within_200_chars(self, skill_body: str) -> None:
        body = skill_body
        """objective 会被截断到 200 字：两条模板必须在前 200 字内就能区分。"""

        lines = [
            line.strip()
            for line in body.splitlines()
            if "下游/secondary" in line or "上游/primary" in line
        ]
        assert len(lines) >= 2, "找不到两句委派模板"
        down = next(line for line in lines if "下游/secondary" in line)
        up = next(line for line in lines if "上游/primary" in line)
        assert down[:200] != up[:200]

    def test_has_no_db_tools_in_allowed_list(self) -> None:
        from cloudagent_ext.skills.bundled.sync_analysis import _ALLOWED_TOOLS

        assert not any(name.endswith("_sql") or name.startswith("get_") for name in _ALLOWED_TOOLS)
        assert "Agent" not in _ALLOWED_TOOLS
