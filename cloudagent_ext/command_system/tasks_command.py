"""tasks — ``/tasks`` background-task list (port of local-jsx, degraded).
 ``/tasks`` (``commands/tasks/``) renders ``BackgroundTasksDialog`` — it **lists and
manages** (kill) background tasks. Python's TUI ``/tasks`` focuses a live task panel
(app-bound). This registry port provides the **headless list** — the running tasks ARE
reachable from the command surface via ``context.tool_context.runtime_tasks`` (the same
``RuntimeTaskRegistry`` tools write to) — and **drops management** (kill needs the
app/async ``Task.kill`` path). The TUI keeps its live panel (inversion).
Follows the output-style/``/mcp`` precedent: ``run()`` returns text **without touching
``ctx.ui``**, so it works on every surface; on the SDK (where ``tool_context`` is None)
it reports the list is unavailable rather than raising.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .types import (
    CommandContext,
    InteractiveCommand,
    InteractiveOutcome,
)


def _coerce(x: Any) -> Any:
    """Defensive: a ``.value``-bearing object → its ``.value``, else the value unchanged.
    ``TaskType``/``TaskStatus`` are ``Literal[str]`` today (already plain strings, so this
    just passes them through) — this only future-proofs against an enum/wrapper."""
    return getattr(x, "value", x)


def _format_task(t: Any) -> str:
    status = _coerce(getattr(t, "status", "")) or "?"
    label = getattr(t, "description", "") or _coerce(getattr(t, "type", "")) or "(task)"
    return f"[{status}] {label} (id: {getattr(t, 'id', '')})"


#: 视为"卡住"的缺口状态（与 GapSummary.only_blocked / 域闸同一口径）
GAP_STUCK = frozenset({"blocked", "inconclusive"})


def _domain_of(agent_type: str) -> str:
    """``code-diagnosis`` → ``code``。延迟导入避免命令层反向依赖诊断域。"""

    from cloudagent_ext.diagnosis.domain_gate import domain_of

    return domain_of(agent_type)


def _format_gap_line(gap: Any) -> str:
    """单条缺口的渲染（保持改造前的格式，两种分组共用）。"""

    status = getattr(gap, "status", "?")
    statement = str(getattr(gap, "statement", "") or "").strip()
    if len(statement) > 80:
        statement = statement[:80] + "…"
    restatements = getattr(gap, "restatements", 0)
    return f"• [{status}] {statement}（复述 {restatements} 次）"


def _format_diagnosis_session(tc: Any) -> list[str]:
    """诊断会话轨迹（change wire-investigation-session）。

    只读渲染：不触碰会话状态。无记录时返回空列表（不输出空区块）。
    """

    runtime = getattr(tc, "diagnosis_session_runtime", None)
    session = getattr(runtime, "session", None)
    entries = getattr(session, "entries", ()) if session is not None else ()
    if not entries:
        return []

    lines = [f"诊断会话（request_id: {getattr(session, 'request_id', '?')}）："]
    for entry in entries:
        task = getattr(entry, "task", None)
        status = getattr(entry, "status", "?")
        agent_type = getattr(task, "agent_type", "?")
        objective = str(getattr(task, "objective", "") or "").strip()
        if len(objective) > 80:
            objective = objective[:80] + "…"
        lines.append(f"• [{status}] {agent_type} — {objective} (task: {getattr(task, 'task_id', '?')})")
        reason = getattr(entry, "failure_reason", None)
        if status == "failed" and reason:
            lines.append(f"     └ 原因：{reason}")
    gaps = getattr(runtime, "gaps", None) or []
    if gaps:
        open_count = sum(1 for gap in gaps if getattr(gap, "status", "") == "open")
        resolved_count = sum(1 for gap in gaps if getattr(gap, "status", "") == "resolved")
        blocked_count = len(gaps) - open_count - resolved_count
        lines.append(
            f"缺口（{open_count} open / {blocked_count} blocked 或待定 / {resolved_count} resolved）："
        )
        # 阶段 1：有域归因时按域分组（"人看的视图"与"Agent 用的状态"是同一份数据）。
        # 全是没有域的历史数据时保持原来的平铺格式，避免给老数据加无意义的"(未归因)"分组。
        has_domain = any(str(getattr(gap, "source_domain", "") or "") for gap in gaps)
        if not has_domain:
            for gap in gaps:
                lines.append(_format_gap_line(gap))
        else:
            grouped: dict[str, list] = {}
            for gap in gaps:
                key = _domain_of(getattr(gap, "source_domain", "")) or "(未归因)"
                grouped.setdefault(key, []).append(gap)
            for key in sorted(grouped):
                items = grouped[key]
                d_open = sum(1 for gap in items if getattr(gap, "status", "") == "open")
                d_stuck = sum(1 for gap in items if getattr(gap, "status", "") in GAP_STUCK)
                lines.append(f"  [{key}] {len(items)} 条（{d_open} open / {d_stuck} 卡住）")
                for gap in items:
                    lines.append("    " + _format_gap_line(gap))

    # 阶段 1：域闸拦截（与"缺口注入"并列，都是编排行为的事后视图）
    used = getattr(session, "delegations_used", None)
    budget = getattr(session, "budget", None)
    if used is not None and budget is not None:
        lines.append(
            f"已用 {used}/{getattr(budget, 'max_delegations', '?')} 次委派"
        )
    blocks = getattr(runtime, "domain_blocks", None) or {}
    if blocks:
        detail = "、".join(f"{name} {count} 次" for name, count in sorted(blocks.items()))
        lines.append(f"域闸拦截：{detail}")
    injected = getattr(runtime, "injected_dispatches", 0)
    if injected:
        lines.append(f"缺口注入：{injected} 次（子代理提示含「当前未解决缺口」段）")

    # 阶段 2：状态版本 / 陈旧丢弃 / 独立核查（人看的与 Agent 用的是同一份状态）
    revision = int(getattr(runtime, "state_revision", 0) or 0)
    stale = int(getattr(runtime, "stale_discarded", 0) or 0)
    if revision or stale:
        lines.append(f"状态版本：v{revision}（陈旧丢弃 {stale} 次）")
    assessments = getattr(runtime, "assessments", None) or []
    if assessments:
        try:
            from cloudagent_ext.diagnosis.assessor import summarize_assessments

            summary = summarize_assessments(assessments)
            parts = [
                f"{name} {count}"
                for name, count in sorted((summary.get("by_status") or {}).items())
                if count
            ]
            line = f"独立核查：{summary.get('assessments', 0)} 次（{'、'.join(parts)}）"
            rate = summary.get("disagreement_rate")
            if rate is not None:
                line += f"，分歧率 {rate:.0%}"
            lines.append(line)
        except Exception:  # noqa: BLE001 — 渲染失败不影响其它行
            pass

    report_method = getattr(session, "conflict_report", None)
    if callable(report_method):
        try:
            conflicts = report_method()
        except Exception:  # noqa: BLE001 - 渲染失败不影响其它行
            conflicts = {}
        total = int(conflicts.get("total", 0) or 0)
        if total:
            lines.append(
                f"结论冲突：{total} 处（跨 agent 未裁决 {conflicts.get('unresolved', 0)}"
                f" / 同 agent 内部 {conflicts.get('internal', 0)}）"
            )
    return lines


def build_sections(tool_context: Any) -> list[str]:
    """同步渲染背景任务 + 诊断会话（REPL 内联 /tasks 与命令引擎共用）。

    REPL 的 ``/tasks`` 由自己处理（不含诊断会话），若不共用这个函数，
    轨迹在真实 CLI 里就永远看不到——这正是实现审查后实测发现的问题。
    """

    if tool_context is None:
        return []
    registry = getattr(tool_context, "runtime_tasks", None)
    tasks: list[Any] = []
    if registry is not None:
        try:
            tasks = list(registry.all())
        except Exception:
            tasks = []

    sections: list[str] = []
    if tasks:
        sections.append("Background tasks:\n" + "\n".join(f"• {_format_task(t)}" for t in tasks))

    diagnosis_lines = _format_diagnosis_session(tool_context)
    if diagnosis_lines:
        sections.append("\n".join(diagnosis_lines))
    return sections


@dataclass(frozen=True)
class TasksCommand(InteractiveCommand):
    """List the running background tasks. Frozen + no new fields (the ``McpCommand``
    pattern); ``run()`` returns text without touching ``ctx.ui``."""

    async def run(self, args: str, context: CommandContext) -> InteractiveOutcome:
        tc = getattr(context, "tool_context", None)
        registry = getattr(tc, "runtime_tasks", None) if tc is not None else None
        if registry is None:
            # SDK / listing surfaces have no live task registry.
            return InteractiveOutcome(
                message="Background tasks are unavailable on this surface.",
                display="system",
            )

        sections = build_sections(tc)
        if not sections:
            return InteractiveOutcome(message="No background tasks.", display="system")
        return InteractiveOutcome(message="\n\n".join(sections), display="system")


TASKS_COMMAND = TasksCommand(
    name="tasks",
    description="List and manage background tasks",  # verbatim TS (port only LISTS)
    aliases=["bashes"],  # verbatim TS index.ts
)


__all__ = ["TASKS_COMMAND", "TasksCommand"]
