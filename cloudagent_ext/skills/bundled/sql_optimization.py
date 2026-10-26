#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Bundled adapter for the portable ``sql-optimization`` skill package.

变更 add-sql-optimization-skill：

* 内容来自 ``sql_optimization_resources/SKILL.md``（对齐开发指南 §6.1）；
* 提示词 = SKILL.md 正文（含参数替换）+ 运行时的统一输出约定
  （``render_result_contract()``）——**动态拼接防漂移**，SKILL.md 不复制契约文本；
* ``allowed_tools`` 声明 P2.2 的三只读工具与 P2.9 的统计/锁工具名，调用后由既有
  context modifier 机制过滤会话工具集（与 P2.4 的按需装配协同）。
"""

from __future__ import annotations

from functools import lru_cache

from ..argument_substitution import substitute_arguments
from ..bundled_skills import BundledSkillDefinition, register_bundled_skill
from ..frontmatter import parse_frontmatter
from .resource_loader import load_bundled_text_resources

_RESOURCE_PACKAGE = "cloudagent_ext.skills.bundled.sql_optimization_resources"
_SKILL_NAME = "sql-optimization"

_WHEN_TO_USE = (
    "用于 SQL 性能问题诊断：慢查询、执行计划解读、索引缺失或未命中、"
    "JOIN 策略、分页陷阱与锁等待类问题的分析。"
)

_ALLOWED_TOOLS = [
    "get_schema",
    "get_indexes",
    "explain_sql",
    # expand-sql-diagnostic-db-tools：新增只读证据工具（统计/锁）
    "get_table_stats",
    "get_lock_info",
    "query_table_rows",
]

# fix-sql-diagnosis-tool-provisioning：该 skill 是 sql-diagnosis 子代理的
# 工作手册（其声明工具仅子代理会话持有、输出为诊断协议）——模型可见性
# 收窄至诊断子代理；用户斜杠命令不受影响。
_MODEL_VISIBLE_AGENTS = ["sql-diagnosis"]


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


def _build_sql_optimization_prompt(args: str) -> str:
    """组装技能提示词：SKILL.md 正文（含参数替换）+ 统一输出约定（防漂移）。

    延迟导入 ``render_result_contract``，保持注册路径与 diagnosis 运行时的
    导入解耦；契约始终位于提示词末尾（与委派提示 ``build_investigation_prompt``
    的「契约压轴」结构一致）。
    """

    from cloudagent_ext.diagnosis.protocol import render_result_contract

    _, prompt, _ = _load_portable_skill()
    content = substitute_arguments(prompt, args, append_if_no_placeholder=True)
    return content.rstrip() + "\n\n" + render_result_contract().strip()


def register_sql_optimization_skill() -> bool:
    """Register the portable SQL-Optimization package in the bundled catalogue.

    Returns:
        ``True`` when the bundled registry accepts the definition.

    Raises:
        FileNotFoundError: If the packaged skill or its ``SKILL.md`` is missing.
        ValueError: If the packaged ``SKILL.md`` metadata or body is invalid.
    """

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
            get_prompt_for_command=_build_sql_optimization_prompt,
        )
    )


__all__ = ["register_sql_optimization_skill"]
