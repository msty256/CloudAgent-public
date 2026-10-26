#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""``code-analysis`` bundled Skill 的离线测试（变更 add-code-analysis-domain，P3.2）。

覆盖：注册与目录收录 / allowed_tools 真实工具名（P1-1）/ 提示词防漂移拼接 /
九节内容契约 / **静态风险红线 token 断言**（P2-4）/ 工具名说明正确性。
不依赖任何外部服务。
"""

from __future__ import annotations

from typing import Any

import pytest

from cloudagent_ext.diagnosis.protocol import render_result_contract
from cloudagent_ext.skills.bundled.resource_loader import load_bundled_text_resources
from cloudagent_ext.skills.bundled_skills import (
    clear_bundled_skills,
    get_bundled_skill_by_name,
    get_bundled_skills,
)
from cloudagent_ext.skills.frontmatter import parse_frontmatter

_SKILL_NAME = "code-analysis"
_RESOURCE_PACKAGE = "cloudagent_ext.skills.bundled.code_analysis_resources"

# P1-1：必须是真实工具名；git 用 Bash(...) 规则
_ALLOWED_TOOLS = [
    "find_symbol",
    "find_references",
    "Read",
    "Grep",
    "Bash(git diff)",
    "Bash(git log)",
]
_FAKE_TOOL_NAMES = ("read_file", "search_code", "git_diff", "git_log")
_SECTIONS = (
    "## 1. 触发条件",
    "## 2. 输入充分性检查",
    "## 3. 证据规范",
    "## 4. 分析流程",
    "## 5. 静态风险分级（本 Skill 的核心约束）",
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
    get_bundled_skills()  # 触发 bundled 目录懒初始化（含本技能）
    resolved = get_bundled_skill_by_name(_SKILL_NAME)
    assert resolved is not None, "code-analysis 未注册"
    return resolved


class TestRegistration:
    def test_registered_as_bundled_skill(self, skill: Any) -> None:
        assert skill.name == _SKILL_NAME
        assert skill.source == "bundled"
        assert skill.loaded_from == "bundled"
        assert skill.user_invocable is True

    def test_allowed_tools_use_real_names(self, skill: Any) -> None:
        assert skill.allowed_tools == _ALLOWED_TOOLS
        # P1-1：不得出现仓库中不存在的工具名
        for fake in _FAKE_TOOL_NAMES:
            assert fake not in skill.allowed_tools

    def test_model_visible_only_in_code_diagnosis(self, skill: Any) -> None:
        assert skill.model_visible_agents == ["code-diagnosis"]

    def test_when_to_use_declared(self, skill: Any) -> None:
        assert skill.when_to_use
        assert "代码" in skill.when_to_use


class TestPromptAntiDrift:
    def test_prompt_includes_full_contract(self, skill: Any) -> None:
        prompt = skill.get_prompt("")
        assert render_result_contract().strip() in prompt

    def test_prompt_includes_skill_body_sections(self, skill: Any) -> None:
        prompt = skill.get_prompt("")
        for section in _SECTIONS:
            assert section in prompt

    def test_red_line_tokens_present(self, skill_markdown: str) -> None:
        """P2-4：红线必须有可执行 token 断言（非自然语言承诺）。"""

        assert "suspected" in skill_markdown
        assert "confirmed" in skill_markdown
        assert "不得表述为" in skill_markdown
        assert "已发生" in skill_markdown

    def test_reference_boundary_declared(self, skill_markdown: str) -> None:
        """P1-2：Skill 不得声称精确定位引用，必须声明边界。"""

        assert "同名不区分作用域" in skill_markdown
        assert "getattr" in skill_markdown
        # 不得出现"精确定位引用"这类承诺
        assert "精确定位引用" not in skill_markdown

    def test_frontmatter_valid(self, skill_markdown: str) -> None:
        parsed = parse_frontmatter(skill_markdown)
        assert parsed.frontmatter.get("name") == _SKILL_NAME
        assert parsed.body.strip()
