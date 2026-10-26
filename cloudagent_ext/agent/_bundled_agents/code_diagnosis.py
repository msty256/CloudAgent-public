#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Bundled ``code-diagnosis`` agent（变更 add-code-analysis-domain，P3.2）。

* 以只读方式诊断代码问题（调用链/异常路径/变更影响），加载 ``code-analysis``
  Skill 并遵循其方法论，通过只读代码工具（find_symbol/find_references）与
  现有只读工具（Read/Grep/Bash 白名单）按需取证，最终按 P1 统一协议回传；
* **静态风险分级**：无运行证据时结论只能到 ``suspected``——不得表述为已发生；
* 系统提示运行时拼接 ``render_result_contract()``（单一来源、防漂移）；
* 同模块提供工具装配入口 :func:`register_code_diagnosis_tools`（幂等薄封装；
  不接入任何全局默认路径——默认注册表保持不含代码工具）。
"""

from __future__ import annotations

from typing import Any

from cloudagent_ext.agent.policy import (
    TOOL_SET_CODE_DIAGNOSIS,
    build_agent_prompt,
)
from cloudagent_ext.agent.registry import AgentRegistry

_CODE_DIAGNOSIS_IDENTITY = (
    "You are the code diagnosis specialist for CloudAgent. Investigate code-related "
    "failures (call chains, exception paths, change impact, null/concurrency/resource "
    "risks) strictly with read-only evidence. This is NOT code review — it is "
    "evidence-based root-cause diagnosis for problems that already happened."
)

_CODE_DIAGNOSIS_GUIDANCE = (
    "Workflow:\n"
    "- Load the `code-analysis` skill first (Skill tool, skill=\"code-analysis\") "
    "and follow its methodology for the whole investigation.\n"
    "- Locate definitions with `find_symbol` and call sites with `find_references`; "
    "read context with `Read`; search text with `Grep`; inspect change history with "
    "`Bash(git diff)` / `Bash(git log)` only. Reuse identical results instead of "
    "repeating calls.\n"
    "- Never execute target code (no import/exec/eval, no running tests or scripts) "
    "and never modify files — this agent is strictly read-only.\n"
    "- Static risks MUST be reported with `risk_level=suspected` unless runtime "
    "evidence (stack trace / reproduced failure) confirms them; never claim "
    "'已经发生/已导致/已引起' from static analysis alone.\n"
    "- `find_references` is name-only: same-name symbols are not scope-disambiguated; "
    "getattr string refs and decorator aliases are NOT covered — state this boundary "
    "in limitations.\n"
    "- You may be invoked as a **single follow-up** from a log investigation "
    "(P3 limit: at most one such hand-off; multi-round orchestration is P4).\n"
    "- Return the final result in the unified diagnosis protocol appended below, with "
    "evidence ids `ev:code:<seq>` (the namespace prefix carries the domain)."
)

_CODE_TOOL_NAMES: tuple[str, ...] = (
    "find_symbol",
    "find_references",
)


@AgentRegistry.register(
    "code-diagnosis",
    when_to_use=(
        "Code diagnosis specialist. Use when the caller reports a code-related "
        "failure (exception path, broken call chain, suspicious change) and needs an "
        "evidence-backed root-cause analysis with file:line references. This is NOT "
        "code review (use code-reviewer for quality/style feedback). Read-only — "
        "never modifies code."
    ),
    tools=TOOL_SET_CODE_DIAGNOSIS,
    # 声明依赖的 skill——子会话获得会话级预授权（Skill(code-analysis)）；
    # deny 规则仍优先（见 run_agent._build_permission_context）。
    skills=["code-analysis"],
    # 诊断只读权限语义（覆盖 default/plan 父模式；父为 bypassPermissions 时尊重用户）
    permission_mode="dontAsk",
    # 按需装配接缝：Agent tool 在 spawn 前调用，把只读代码工具注册进子代理注册表
    # （幂等；lambda 延迟解析，函数定义在本模块后部）。
    provision_tools=lambda registry: register_code_diagnosis_tools(registry),
)
def _code_diagnosis_prompt() -> str:
    """系统提示 = identity + guidance + 统一输出约定（运行时拼接，防漂移）。"""

    from cloudagent_ext.diagnosis.protocol import render_result_contract

    base = build_agent_prompt(
        identity=_CODE_DIAGNOSIS_IDENTITY,
        extra=_CODE_DIAGNOSIS_GUIDANCE,
    )
    return base.rstrip() + "\n\n" + render_result_contract().strip()


def register_code_diagnosis_tools(registry: Any) -> bool:
    """把只读代码工具集幂等装配进 *registry*（不触碰全局默认路径）。

    Returns:
        ``True`` 当调用后工具集齐备（含"已装配"的 no-op 路径）；否则 ``False``。
    """

    try:
        if all(registry.get(name) is not None for name in _CODE_TOOL_NAMES):
            return True
        from cloudagent_ext.diagnosis.code.tools import register_code_tools

        register_code_tools(registry)
        return all(registry.get(name) is not None for name in _CODE_TOOL_NAMES)
    except Exception:  # noqa: BLE001 — 装配失败以 False 返回，由调用方决定降级
        return False


__all__ = [
    "register_code_diagnosis_tools",
]
