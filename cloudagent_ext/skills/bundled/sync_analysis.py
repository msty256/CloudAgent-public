#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Bundled adapter for the portable ``sync-analysis`` skill package.

变更 add-sync-analysis-skill：

* 内容来自 ``sync_analysis_resources/SKILL.md``；
* **不设** ``model_visible_agents``——sync 没有专属子代理，方法必须由主会话
  使用（``visibility.py`` 中 ``visible_to=None`` 即"处处可见"）；
* ``allowed_tools`` 只做预授权（``invocation.py``：写入 always_allow_rules），
  不含 ``Agent``（委派不依赖预授权）也不含 DB 工具（主会话注册表本就没有）。
"""

from __future__ import annotations

from functools import lru_cache

from ..argument_substitution import substitute_arguments
from ..bundled_skills import BundledSkillDefinition, register_bundled_skill
from ..frontmatter import parse_frontmatter
from .resource_loader import load_bundled_text_resources

_RESOURCE_PACKAGE = "cloudagent_ext.skills.bundled.sync_analysis_resources"
_SKILL_NAME = "sync-analysis"

_WHEN_TO_USE = (
    "用于同步类问题：数据没有同步到下游、同步任务失败或延迟、消费成功但业务数据异常、"
    "上下游数据不一致。按「触发 → 消费 → 业务处理 → 落库计数 → 上游对照」的顺序取证。"
)

# 预授权清单：排查时要读配置与样例日志，三者均为只读工具。
# 故意不含 Agent（委派不依赖预授权）与任何 DB 工具（见模块 docstring）。
_ALLOWED_TOOLS = ["Read", "Grep", "Glob"]


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


def _build_sync_analysis_prompt(args: str) -> str:
    """SKILL.md 正文（含参数替换）+ 统一输出契约（与其它诊断 skill 一致）。"""

    from cloudagent_ext.diagnosis.protocol import render_result_contract

    _, prompt, _ = _load_portable_skill()
    content = substitute_arguments(prompt, args, append_if_no_placeholder=True)
    return content.rstrip() + "\n\n" + render_result_contract().strip()


def register_sync_analysis_skill() -> bool:
    """Register the portable sync-analysis package in the bundled catalogue."""

    description, _, resource_items = _load_portable_skill()
    return register_bundled_skill(
        BundledSkillDefinition(
            name=_SKILL_NAME,
            description=description,
            when_to_use=_WHEN_TO_USE,
            allowed_tools=list(_ALLOWED_TOOLS),
            user_invocable=True,
            files=dict(resource_items),
            requires_resources=True,
            get_prompt_for_command=_build_sync_analysis_prompt,
        )
    )
