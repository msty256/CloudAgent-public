#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Bundled ``sql-diagnosis`` agent（变更 add-sql-diagnostic-agent）。

* 以只读方式调查 SQL 性能问题：加载 ``sql-optimization`` Skill 并遵循其方法论，
  通过只读 DB 工具集按需取证，最终按 P1 统一诊断结果协议回传；
* 系统提示运行时拼接 ``render_result_contract()``（单一来源、防漂移）；
* 同模块提供工具装配入口 :func:`register_sql_diagnosis_tools`（幂等薄封装；
  不接入任何全局默认路径——默认注册表保持不含 DB 工具）。
"""

from __future__ import annotations

from typing import Any

from cloudagent_ext.agent.policy import (
    TOOL_SET_SQL_DIAGNOSIS,
    build_agent_prompt,
)
from cloudagent_ext.agent.registry import AgentRegistry

_SQL_DIAGNOSIS_IDENTITY = (
    "You are the SQL diagnosis specialist for CloudAgent. Investigate SQL performance "
    "problems (slow queries, poor execution plans, missing or unused indexes, JOIN / "
    "ordering / pagination issues) strictly with read-only evidence."
)

_SQL_DIAGNOSIS_GUIDANCE = (
    "Workflow:\n"
    "- Load the `sql-optimization` skill first (Skill tool, skill=\"sql-optimization\") "
    "and follow its methodology for the whole investigation.\n"
    "- Collect evidence on demand with the read-only database tools `get_schema`, "
    "`get_indexes`, `explain_sql`, `get_table_stats` (size / statistics freshness / "
    "column selectivity aggregates), `get_lock_info` (current lock waits only; "
    "historical waits are not recoverable) and `query_table_rows` (COUNT by default; "
    "pass columns for detail rows; equality filters only; `target=primary|secondary` "
    "compares upstream vs downstream; the metadata tools `get_schema` / `get_indexes` / "
    "`get_table_stats` accept the same `target`, so downstream schema/indexes are inspectable; "
    "`explain_sql` and `get_lock_info` are primary-only); reuse identical results instead of "
    "repeating calls, and treat `explain_sql` output as an estimated plan only.\n"
    "- Use `Bash` only for read-only local checks (reading SQL files, formatting or "
    "diffing); never to modify data or the system.\n"
    "- Never fabricate schema, index or plan facts. When evidence is missing or a tool "
    "fails, record the limitation explicitly and degrade safely (partial / failed) — "
    "never claim a confirmed diagnosis without supporting evidence.\n"
    "- Return the final result in the unified diagnosis protocol appended below."
)

_DB_TOOL_NAMES: tuple[str, ...] = (
    "get_schema",
    "get_indexes",
    "explain_sql",
    "get_table_stats",
    "get_lock_info",
    "query_table_rows",
)


@AgentRegistry.register(
    "sql-diagnosis",
    when_to_use=(
        "SQL diagnosis specialist. Use when the caller reports a SQL/DB performance "
        "problem (slow query, timeout, plan / index / pagination concerns) and needs "
        "an evidence-backed root-cause analysis with optimization suggestions. "
        "Read-only — never modifies data or schema."
    ),
    tools=TOOL_SET_SQL_DIAGNOSIS,
    # fix-sql-diagnosis-tool-provisioning：声明依赖的 skill——子会话获得
    # 会话级预授权（Skill(sql-optimization)），dontAsk 下不再被拒
    # （deny 规则仍优先；见 run_agent._build_permission_context）。
    skills=["sql-optimization"],
    # P2.8 (integrate-sql-diagnostic-agent)：诊断只读权限语义——覆盖
    # default/plan 父模式；父为 bypassPermissions 时尊重用户的显式选择
    # （runtime 既有继承规则，见 run_agent.resolve_permission_mode）。
    permission_mode="dontAsk",
    # fix-sql-diagnosis-tool-provisioning：按需装配接缝——Agent tool 在
    # spawn 前调用它，把只读 DB 工具集注册进子代理的生效注册表（幂等；
    # lambda 延迟解析，函数定义在本模块后部）。
    provision_tools=lambda registry: register_sql_diagnosis_tools(registry),
)
def _sql_diagnosis_prompt() -> str:
    """系统提示 = identity + guidance + 统一输出约定（运行时拼接，防漂移）。"""

    from cloudagent_ext.diagnosis.protocol import render_result_contract

    base = build_agent_prompt(
        identity=_SQL_DIAGNOSIS_IDENTITY,
        extra=_SQL_DIAGNOSIS_GUIDANCE,
    )
    return base.rstrip() + "\n\n" + render_result_contract().strip()


def register_sql_diagnosis_tools(registry: Any) -> bool:
    """把只读 DB 工具集幂等装配进 *registry*（不触碰全局默认路径）。

    Returns:
        ``True`` 当调用后工具集齐备（含"已装配"的 no-op 路径）；否则 ``False``。
    """

    try:
        if all(registry.get(name) is not None for name in _DB_TOOL_NAMES):
            return True
        from cloudagent_ext.diagnosis.db.tools import register_sql_db_tools

        register_sql_db_tools(registry)
        return all(registry.get(name) is not None for name in _DB_TOOL_NAMES)
    except Exception:  # noqa: BLE001 — 装配失败以 False 返回，由调用方决定降级
        return False


def _recover_text_from_transcript(transcript_path: Any) -> str | None:
    """从会话记录（jsonl）宽松解析恢复完整最终文本（fix-diagnosis-result-truncation）。

    取最后一个 ``role == "assistant"`` 的文本块拼接结果；任何一步失败返回
    ``None``（调用方退化到显式 FAILED 标注——不伪造、不静默）。
    """

    if not transcript_path or not isinstance(transcript_path, str):
        return None
    try:
        import json
        from pathlib import Path

        path = Path(transcript_path)
        if not path.is_file():
            return None
        last_text: str | None = None
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except Exception:  # noqa: BLE001 — 宽松：坏行跳过
                continue
            if not isinstance(obj, dict) or obj.get("role") != "assistant":
                continue
            parts = [
                str(block.get("text"))
                for block in (obj.get("content") or [])
                if isinstance(block, dict)
                and block.get("type") == "text"
                and block.get("text")
            ]
            if parts:
                last_text = "\n".join(parts)
        return last_text
    except Exception:  # noqa: BLE001 — 恢复是尽力而为
        return None


def augment_agent_result(result: Any, agent_definition: Any) -> Any:
    """P2.8：对 ``sql-diagnosis`` 子会话结果做 **P1 协议校验后处理**（安全降级）。

    * 仅对 ``sql-diagnosis`` 生效（其他 agent 原样返回）；错误/失败结果原样返回；
    * 解析成功：在 tool_result 内容尾部附加结构化校验块（状态 / 候选根因数 /
      证据引用校验 / 限制摘要）——供主 Agent 稳定汇总；
    * 解析失败：附加 ``validation: FAILED`` 标注并保留原文——**不吞错、
      不伪造结论**；候选根因明确标注"不得直接升级为已确认事实"。
    """

    # P2-4（P3.6）：保持既有签名——内部转调参数化实现（sql 域）。
    return _augment_diagnosis_result(result, agent_definition, domain_label="sql")


def _build_augment_block(
    text: str,
    domain_label: str,
    transcript_path: Any,
) -> str:
    """构造协议校验块文本（同步与异步共用，禁止复制文案）。

    * 解析成功 → ``passed`` 块（状态 / 候选根因 / 证据引用 / 限制）；
    * 解析失败 → ``FAILED`` 块并保留原文语义（先尝试从 transcript 恢复）。
    """

    from cloudagent_ext.diagnosis.protocol import (
        DiagnosisParseError,
        parse_diagnosis_result,
    )

    try:
        parsed = parse_diagnosis_result(text)
        recovered_from: str | None = None
    except DiagnosisParseError as exc:
        # fix-diagnosis-result-truncation：注入文本可能因截断丢失协议 JSON
        # （JSON 压轴）——尝试从会话记录恢复完整文本后重试；恢复不可用或
        # 仍解析失败才标注 FAILED（不伪造、不静默）。
        recovered_text = _recover_text_from_transcript(transcript_path)
        parsed = None
        recovered_from = None
        if recovered_text and recovered_text.strip() != text.strip():
            try:
                parsed = parse_diagnosis_result(recovered_text)
                recovered_from = "transcript"
            except DiagnosisParseError:
                parsed = None
        if parsed is None:
            return (
                "\n\n---\n**[CloudAgent 集成] diagnosis-protocol 校验：FAILED**\n"
                f"- 原因：{exc}\n"
                f"- 域：{domain_label}\n"
                "- 提示：原始报告未通过统一协议解析；请勿将其中的未验证内容"
                "当作已确认结论。"
            )

    reference_issues = parsed.validate_references()
    # extend-evidence-semantics：软问题（悬空 relation 等）单独渲染，不影响 status
    reference_warnings = list(parsed.reference_warnings())
    root_summary = "; ".join(
        f"{str(cause.description)[:80]}（confidence={cause.confidence}）"
        for cause in parsed.root_causes[:3]
    ) or "（无）"
    limitations = "; ".join(str(item) for item in parsed.limitations[:2]) or "（无）"
    recovery_note = "（经会话记录恢复完整文本）" if recovered_from else ""
    return (
        "\n\n---\n**[CloudAgent 集成] diagnosis-protocol 校验：passed**\n"
        f"- 域：{domain_label}｜status：{parsed.status}｜request_id：{parsed.request_id}{recovery_note}\n"
        f"- 候选根因（{len(parsed.root_causes)}）：{root_summary}\n"
        f"- 证据数：{len(parsed.evidence)}｜引用校验："
        f"{'通过' if not reference_issues else '；'.join(reference_issues)}\n"
        + (
            "- 引用告警（非致命）："
            + "；".join(reference_warnings[:3])
            + (f"（共 {len(reference_warnings)} 条）" if len(reference_warnings) > 3 else "")
            + "\n"
            if reference_warnings
            else ""
        )
        + f"- 限制：{limitations}\n"
        "- 汇总提示：候选根因为待验证结论，不得直接升级为已确认事实。"
    )


def augment_agent_text(
    text: str,
    agent_type: Any,
    *,
    transcript_path: Any = None,
) -> str:
    """文本级协议后处理（异步路径用）：返回 ``text`` + 校验块。

    非诊断类 / 空文本原样返回。与 :func:`_augment_diagnosis_result` 共用
    :func:`_build_augment_block`，保证同步与异步的文案完全一致。
    """

    if not isinstance(text, str) or not text.strip():
        return text
    if not isinstance(agent_type, str) or not agent_type.endswith("-diagnosis"):
        return text
    domain_label = agent_type[: -len("-diagnosis")]
    block = _build_augment_block(text, domain_label, transcript_path)
    return text + block if block else text


def _augment_diagnosis_result(
    result: Any,
    agent_definition: Any,
    *,
    domain_label: str,
) -> Any:
    """参数化的协议校验后处理（P3.6）：``domain_label`` 决定早退条件与校验块文案。

    * 仅对 ``{domain_label}-diagnosis`` 生效；复用 ``_recover_text_from_transcript``
      的截断恢复逻辑（P2 fix 的成果）。
    """

    if getattr(agent_definition, "agent_type", None) != f"{domain_label}-diagnosis":
        return result
    if getattr(result, "is_error", False):
        return result
    output = getattr(result, "output", None)
    if not isinstance(output, dict) or output.get("status") == "failed":
        return result
    content = output.get("content")
    if not isinstance(content, list):
        return result
    text = "\n".join(
        str(block.get("text") or "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    ).strip()
    if not text:
        return result

    block = _build_augment_block(text, domain_label, output.get("transcript_path"))
    if block:
        content.append({"type": "text", "text": block})
    return result


__all__ = ["register_sql_diagnosis_tools"]
