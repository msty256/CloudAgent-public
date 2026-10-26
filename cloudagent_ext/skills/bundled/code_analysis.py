#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Bundled adapter for the portable ``code-analysis`` skill package.

变更 add-code-analysis-domain（P3.2）：

* 内容来自 ``code_analysis_resources/SKILL.md``；
* 提示词 = SKILL.md 正文（含参数替换）+ 运行时统一输出约定
  （``render_result_contract()``）——动态拼接防漂移；
* ``allowed_tools`` 使用**真实工具名**（``Read``/``Grep``/``Bash(...)`` 规则），
  不得使用 ``read_file``/``search_code``/``git_diff``/``git_log``（仓库中不存在）。
"""

from __future__ import annotations

from functools import lru_cache

from ..argument_substitution import substitute_arguments
from ..bundled_skills import BundledSkillDefinition, register_bundled_skill
from ..frontmatter import parse_frontmatter
from .resource_loader import load_bundled_text_resources

_RESOURCE_PACKAGE = "cloudagent_ext.skills.bundled.code_analysis_resources"
_SKILL_NAME = "code-analysis"

_WHEN_TO_USE = (
    "用于代码相关故障诊断：调用链、异常路径、变更影响、空指针/并发/资源管理可疑点的"
    "证据化分析（只读，不修改代码；静态风险分级，不把可疑当已发生）。"
)

# 真实工具名（P3.2 审查 P1-1）：Read/Grep 为现有工具；git 用 Bash(...) 规则形式
_ALLOWED_TOOLS = [
    "find_symbol",
    "find_references",
    "Read",
    "Grep",
    "Bash(git diff)",
    "Bash(git log)",
]

# 该 skill 是 code-diagnosis 子代理的工作手册
_MODEL_VISIBLE_AGENTS = ["code-diagnosis"]


@lru_cache(maxsize=1)
def _load_portable_skill() -> tuple[str, str, tuple[tuple[str, str], ...]]:
    resources = load_bundled_text_resources(_RESOURCE_PACKAGE)
    try:
        skill_markdown = resources["SKILL.md"]
    except KeyError as exc:
        raise FileNotFoundError(f"{_RESOURCE_PACKAGE} does not contain SKILL.md") from exc

    parsed = parse_frontmatter(skill_markdown)
    if parsed.frontmatter.get("name") != _SKILL_NAME:
        raise ValueError(f"bundled {_SKILL_NAME} package has invalid name frontmatter")
    description = parsed.frontmatter.get("description")
    if not isinstance(description, str) or not description.strip():
        raise ValueError(f"bundled {_SKILL_NAME} package has no description frontmatter")
    if not parsed.body.strip():
        raise ValueError(f"bundled {_SKILL_NAME} package has an empty prompt body")

    return description.strip(), parsed.body, tuple(resources.items())


def _build_code_analysis_prompt(args: str) -> str:
    """组装技能提示词：SKILL.md 正文 + 统一输出约定（契约压轴，防漂移）。"""

    from cloudagent_ext.diagnosis.protocol import render_result_contract

    _, prompt, _ = _load_portable_skill()
    content = substitute_arguments(prompt, args, append_if_no_placeholder=True)
    return content.rstrip() + "\n\n" + render_result_contract().strip()


def register_code_analysis_skill() -> bool:
    """Register the portable Code-Analysis package in the bundled catalogue."""

    description, _, resource_items = _load_portable_skill()
    return register_bundled_skill(
        BundledSkillDefinition(
            name=_SKILL_NAME,
            description=description,
            when_to_use=_WHEN_TO_USE,
            allowed_tools=list(_ALLOWED_TOOLS),
            user_invocable=True,
            model_visible_agents=list(_MODEL_VISIBLE_AGENTS),
            files=dict(resource_items),
            requires_resources=True,
            get_prompt_for_command=_build_code_analysis_prompt,
        )
    )


__all__ = ["register_code_analysis_skill"]
