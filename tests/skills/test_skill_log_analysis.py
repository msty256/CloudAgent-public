#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""``log-analysis`` bundled Skill 的离线测试（P3.3）。

覆盖：注册/ allowed_tools 与 TOOL_SET_LOG_DIAGNOSIS 对齐 / 九节结构 /
红线 token（首异常≠根因、缺失/采样/时间偏差、续行语义）。
"""

from __future__ import annotations

from typing import Any

import pytest

from cloudagent_ext.agent.policy import TOOL_SET_LOG_DIAGNOSIS
from cloudagent_ext.diagnosis.protocol import render_result_contract
from cloudagent_ext.skills.bundled.resource_loader import load_bundled_text_resources
from cloudagent_ext.skills.bundled_skills import (
    clear_bundled_skills,
    get_bundled_skill_by_name,
    get_bundled_skills,
)

_SKILL_NAME = "log-analysis"
_RESOURCE_PACKAGE = "cloudagent_ext.skills.bundled.log_analysis_resources"
_SECTIONS = (
    "## 1. 触发条件",
    "## 2. 输入充分性检查",
    "## 3. 证据规范",
    "## 4. 分析流程",
    "## 5. 首异常 ≠ 根因（本 Skill 的核心约束）",
    "## 6. 输出契约",
    "## 7. 工具使用规范",
    "## 8. 分析深度与停止条件",
    "## 9. 红线（违反即结论无效）",
)


@pytest.fixture(autouse=True)
def _clean_registry() -> None:
    clear_bundled_skills()
    yield  # type: ignore[misc]
    clear_bundled_skills()


@pytest.fixture()
def skill_markdown() -> str:
    return load_bundled_text_resources(_RESOURCE_PACKAGE)["SKILL.md"]


@pytest.fixture()
def skill() -> Any:
    get_bundled_skills()
    resolved = get_bundled_skill_by_name(_SKILL_NAME)
    assert resolved is not None, "log-analysis 未注册"
    return resolved


class TestRegistration:
    def test_registered(self, skill: Any) -> None:
        assert skill.name == _SKILL_NAME
        assert skill.source == "bundled"
        assert skill.user_invocable is True

    def test_allowed_tools_subset_of_agent_toolset(self, skill: Any) -> None:
        assert set(skill.allowed_tools) <= set(TOOL_SET_LOG_DIAGNOSIS)

    def test_model_visible_only_in_log_diagnosis(self, skill: Any) -> None:
        assert skill.model_visible_agents == ["log-diagnosis"]


class TestPromptAndRedLines:
    def test_prompt_includes_contract(self, skill: Any) -> None:
        assert render_result_contract().strip() in skill.get_prompt("")

    def test_sections_present(self, skill: Any) -> None:
        prompt = skill.get_prompt("")
        for section in _SECTIONS:
            assert section in prompt

    def test_red_line_tokens(self, skill_markdown: str) -> None:
        assert "首异常 ≠ 根因" in skill_markdown
        assert "缺失" in skill_markdown
        assert "采样" in skill_markdown
        assert "时间偏差" in skill_markdown
        assert "continuation" in skill_markdown
        # 不得承诺"首异常即根因"
        assert "首异常即根因" not in skill_markdown
