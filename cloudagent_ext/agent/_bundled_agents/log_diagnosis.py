#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Bundled ``log-diagnosis`` agent（变更 add-log-analysis-domain，P3.3）。

* 以只读方式诊断日志类问题（事件链/首异常/Trace 关联），加载 ``log-analysis``
  Skill 并遵循其方法论，通过 4 个只读日志工具取证，最终按 P1 统一协议回传；
* **首异常≠根因**；日志缺失/采样/时间偏差必须列入 limitations；
* 系统提示运行时拼接 ``render_result_contract()``；
* 同模块提供工具装配入口 :func:`register_log_diagnosis_tools`（幂等；不触碰默认注册表）。
"""

from __future__ import annotations

from typing import Any

from cloudagent_ext.agent.policy import (
    TOOL_SET_LOG_DIAGNOSIS,
    build_agent_prompt,
)
from cloudagent_ext.agent.registry import AgentRegistry

_LOG_DIAGNOSIS_IDENTITY = (
    "You are the log diagnosis specialist for CloudAgent. Investigate failures from "
    "application/task logs (event chains, first error, trace correlation) strictly with "
    "read-only evidence. This is NOT log aggregation or monitoring."
)

_LOG_DIAGNOSIS_GUIDANCE = (
    "Workflow:\n"
    "- Load the `log-analysis` skill first (Skill tool, skill=\"log-analysis\") and "
    "follow its methodology for the whole investigation.\n"
    "- **First read the searchable scope**: call `search_logs` without filters (or "
    "limit=1) and read `log_root` / `available_files` from the payload. This tool makes "
    "**no service-name or directory-structure assumptions** — filter by `file` (path "
    "substring) when you know a path pattern. If `scope_empty`, report the configuration "
    "problem (CLOUDAGENT_LOG_ROOT) instead of guessing; if `no_match_in_scope`, widen "
    "the filters and never claim 'the log has nothing'.\n"
    "- Search with `search_logs` (service/keyword/level/time window; the window is "
    "datetime-compared; continuation lines inherit record fields), inspect context with "
    "`get_log_context` (includes continuation lines), parse stacks with "
    "`parse_stack_trace` (give any line; it resolves upward to the nearest exception), "
    "and correlate by traceId with `correlate_events` (missing services are reported in "
    "`missing_events`). Reuse identical results instead of repeating calls.\n"
    "- Never modify log files. PII is redacted by the tools; traceId is preserved.\n"
    "- The first error is the earliest observed failure point, NOT the root cause: "
    "root cause needs code/config/data evidence. Log gaps, sampling and clock skew MUST "
    "be listed in limitations; never fabricate unobserved events.\n"
    "- If the logs only localize the call site and a code-path confirmation is "
    "needed, say so explicitly: the caller may delegate **once** to code-diagnosis "
    "(P3 limit; multi-round investigation is a P4 feature) — do not do it yourself.\n"
    "- Return the final result in the unified diagnosis protocol appended below, with "
    "evidence ids `ev:log:<seq>` (the namespace prefix carries the domain)."
)

_LOG_TOOL_NAMES: tuple[str, ...] = (
    "search_logs",
    "get_log_context",
    "parse_stack_trace",
    "correlate_events",
)


@AgentRegistry.register(
    "log-diagnosis",
    when_to_use=(
        "Log diagnosis specialist. Use when the caller reports a failure from "
        "application/task logs (event chain, first error, trace correlation) and needs "
        "an evidence-backed analysis with file:line references. NOT for log aggregation "
        "or monitoring queries. Read-only — never modifies logs."
    ),
    tools=TOOL_SET_LOG_DIAGNOSIS,
    skills=["log-analysis"],
    permission_mode="dontAsk",
    provision_tools=lambda registry: register_log_diagnosis_tools(registry),
)
def _log_diagnosis_prompt() -> str:
    """系统提示 = identity + guidance + 统一输出约定（运行时拼接，防漂移）。"""

    from cloudagent_ext.diagnosis.protocol import render_result_contract

    base = build_agent_prompt(
        identity=_LOG_DIAGNOSIS_IDENTITY,
        extra=_LOG_DIAGNOSIS_GUIDANCE,
    )
    return base.rstrip() + "\n\n" + render_result_contract().strip()


def register_log_diagnosis_tools(registry: Any) -> bool:
    """把只读日志工具集幂等装配进 *registry*（不触碰全局默认路径）。"""

    try:
        if all(registry.get(name) is not None for name in _LOG_TOOL_NAMES):
            return True
        from cloudagent_ext.diagnosis.log.tools import register_log_tools

        register_log_tools(registry)
        return all(registry.get(name) is not None for name in _LOG_TOOL_NAMES)
    except Exception:  # noqa: BLE001 — 装配失败以 False 返回，由调用方决定降级
        return False


__all__ = [
    "register_log_diagnosis_tools",
]
