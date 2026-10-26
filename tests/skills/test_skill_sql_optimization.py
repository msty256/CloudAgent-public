#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""``sql-optimization`` bundled Skill 的离线测试（变更 add-sql-optimization-skill）。

覆盖规范场景：注册与目录收录 / allowed_tools 冻结名 / 提示词防漂移拼接 /
九节内容契约 / 安全边界表述 / 无连接降级指引。不依赖数据库。
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

_SKILL_NAME = "sql-optimization"
_RESOURCE_PACKAGE = "cloudagent_ext.skills.bundled.sql_optimization_resources"
# expand-sql-diagnostic-db-tools：工具集扩展（统计/锁证据）
_ALLOWED_TOOLS = [
    "get_schema",
    "get_indexes",
    "explain_sql",
    "get_table_stats",
    "get_lock_info",
    "query_table_rows",
]
_SECTIONS = (
    "## 适用场景",
    "## 输入要求",
    "## 诊断流程（按需取证）",
    "## 证据规则",
    "## 工具使用规范",
    "## 停止条件",
    "## 输出说明",
    "## 安全限制",
    "## 异常与降级",
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
    assert resolved is not None, "sql-optimization 未注册"
    return resolved


class TestRegistration:
    def test_registered_as_bundled_skill(self, skill: Any) -> None:
        assert skill.name == _SKILL_NAME
        assert skill.source == "bundled"
        assert skill.loaded_from == "bundled"
        assert skill.user_invocable is True
        assert skill.disable_model_invocation is False

    def test_allowed_tools_are_frozen_names(self, skill: Any) -> None:
        assert skill.allowed_tools == _ALLOWED_TOOLS

    def test_when_to_use_declared(self, skill: Any) -> None:
        assert skill.when_to_use
        assert "SQL" in skill.when_to_use

    def test_lazy_init_keeps_single_entry(self) -> None:
        names = [s.name for s in get_bundled_skills()]
        assert names.count(_SKILL_NAME) == 1

        from cloudagent_ext.skills.bundled import init_bundled_skills

        assert init_bundled_skills() is True  # 幂等
        names = [s.name for s in get_bundled_skills()]
        assert names.count(_SKILL_NAME) == 1


class TestPromptAntiDrift:
    def test_prompt_includes_full_contract(self, skill: Any) -> None:
        prompt = skill.get_prompt("")
        assert render_result_contract().strip() in prompt

    def test_prompt_includes_skill_body_sections(self, skill: Any) -> None:
        prompt = skill.get_prompt("")
        for section in _SECTIONS:
            assert section in prompt

    def test_contract_stays_single_source(self, skill_markdown: str) -> None:
        assert "## 输出约定（统一诊断结果协议）" not in skill_markdown
        marker = "你的最终消息必须在末尾以一个 json 代码块结束"
        assert marker not in skill_markdown

    def test_args_are_appended_before_contract(self, skill: Any) -> None:
        args = "请诊断这条 SQL：SELECT * FROM orders WHERE tenant_id = 7"
        prompt = skill.get_prompt(args)
        assert args in prompt
        assert prompt.rstrip().endswith(render_result_contract().strip())


    def test_contract_covers_all_status_values(self) -> None:
        """协议文本必须覆盖统一状态枚举的全部取值（防跨模块漂移）。"""

        from cloudagent_ext.diagnosis.models import VALID_STATUSES

        contract = render_result_contract()
        for status in sorted(VALID_STATUSES):
            assert status in contract


class TestContentContract:
    def test_nine_sections_present(self, skill_markdown: str) -> None:
        for section in _SECTIONS:
            assert section in skill_markdown

    def test_analysis_checkpoints_present(self, skill_markdown: str) -> None:
        for keyword in ("扫描", "JOIN", "过滤", "排序", "分页", "估算行数"):
            assert keyword in skill_markdown

    def test_tool_names_present(self, skill_markdown: str) -> None:
        for name in _ALLOWED_TOOLS:
            assert name in skill_markdown

    def test_stop_conditions_documented(self, skill_markdown: str) -> None:
        for keyword in ("success", "partial", "failed"):
            assert keyword in skill_markdown

    def test_evidence_rules_documented(self, skill_markdown: str) -> None:
        assert "观测事实" in skill_markdown
        assert "候选根因" in skill_markdown
        assert "预估" in skill_markdown
        assert "不得虚构" in skill_markdown

    def test_no_connection_guidance(self, skill_markdown: str) -> None:
        assert "受控配置" in skill_markdown
        assert "静态分析" in skill_markdown
        assert "不索取" in skill_markdown  # 凭据纪律：不索取 / 输出 / 持久化


    def test_lock_wait_boundary(self, skill_markdown: str) -> None:
        assert "锁等待" in skill_markdown
        # 2026-10-18：P2.9 起支持实时快照（get_lock_info），历史不可回溯——
        # 由"有限支持（无锁工具）"更新为"仅支持当前时刻取证"
        assert "仅支持" in skill_markdown
        assert "当前时刻" in skill_markdown
        assert "证据缺口" in skill_markdown

    def test_ten_step_flow(self, skill_markdown: str) -> None:
        assert "10. 检查证据充分性" in skill_markdown
        for keyword in ("输入充分性", "反证", "缺失证据"):
            assert keyword in skill_markdown

    def test_auxiliary_evidence_caution(self, skill_markdown: str) -> None:
        assert "辅助证据" in skill_markdown
        assert "不得仅凭" in skill_markdown

    def test_static_analysis_candidate_only(self, skill_markdown: str) -> None:
        assert "静态分析" in skill_markdown
        assert "只能表述为候选" in skill_markdown
        assert "不得表述为已确认" in skill_markdown

    def test_tool_failure_and_truncation(self, skill_markdown: str) -> None:
        assert "工具失败" in skill_markdown
        assert "证据缺口" in skill_markdown
        assert "截断" in skill_markdown


class TestSafetyContract:
    def test_read_only_and_layering(self, skill_markdown: str) -> None:
        assert "只读" in skill_markdown
        assert "不自行建立数据库连接" in skill_markdown
        assert "不绕过" in skill_markdown

    def test_target_query_not_executed(self, skill_markdown: str) -> None:
        assert "不执行目标查询获取数据" in skill_markdown
        assert "不构成安全边界" in skill_markdown

    def test_no_credentials_requested(self, skill_markdown: str) -> None:
        assert "凭据" in skill_markdown
        assert "密码" in skill_markdown


class TestResources:
    def test_resources_include_skill_md(self) -> None:
        resources = load_bundled_text_resources(_RESOURCE_PACKAGE)
        assert "SKILL.md" in resources

    def test_frontmatter_name_and_description(self, skill_markdown: str) -> None:
        parsed = parse_frontmatter(skill_markdown)
        assert parsed.frontmatter.get("name") == _SKILL_NAME
        description = parsed.frontmatter.get("description")
        assert isinstance(description, str) and description.strip()
