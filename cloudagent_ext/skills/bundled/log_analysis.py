#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Bundled adapter for the portable ``log-analysis`` skill package.

变更 add-log-analysis-domain（P3.3）：

* 内容来自 ``log_analysis_resources/SKILL.md``；
* 提示词 = SKILL.md 正文（含参数替换）+ 运行时统一输出约定（防漂移）；
* ``allowed_tools`` 与 ``TOOL_SET_LOG_DIAGNOSIS`` 对齐（真实工具名）。
"""

from __future__ import annotations

from functools import lru_cache

from ..argument_substitution import substitute_arguments
from ..bundled_skills import BundledSkillDefinition, register_bundled_skill
from ..frontmatter import parse_frontmatter
from .resource_loader import load_bundled_text_resources

_RESOURCE_PACKAGE = "cloudagent_ext.skills.bundled.log_analysis_resources"
_SKILL_NAME = "log-analysis"

_WHEN_TO_USE = (
    "用于日志类故障诊断：应用/任务日志的事件链重建、首异常定位、Trace/Request ID "
    "关联，以及日志缺失/采样/时间偏差的显式声明（只读）。"
)

_ALLOWED_TOOLS = [
    "search_logs",
    "get_log_context",
    "parse_stack_trace",
    "correlate_events",
    "Read",
    "Glob",
    "Grep",
]

_MODEL_VISIBLE_AGENTS = ["log-diagnosis"]


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


def _build_log_analysis_prompt(args: str) -> str:
    """组装技能提示词：SKILL.md 正文 + 统一输出约定（契约压轴）。"""

    from cloudagent_ext.diagnosis.protocol import render_result_contract

    _, prompt, _ = _load_portable_skill()
    content = substitute_arguments(prompt, args, append_if_no_placeholder=True)
    return content.rstrip() + "\n\n" + render_result_contract().strip()


def register_log_analysis_skill() -> bool:
    """Register the portable Log-Analysis package in the bundled catalogue."""

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
            get_prompt_for_command=_build_log_analysis_prompt,
        )
    )


__all__ = ["register_log_analysis_skill"]
