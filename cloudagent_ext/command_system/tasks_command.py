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
        for gap in gaps:
            status = getattr(gap, "status", "?")
            statement = str(getattr(gap, "statement", "") or "").strip()
            if len(statement) > 80:
                statement = statement[:80] + "…"
            restatements = getattr(gap, "restatements", 0)
            lines.append(f"• [{status}] {statement}（复述 {restatements} 次）")

    used = getattr(session, "delegations_used", None)
    budget = getattr(session, "budget", None)
    if used is not None and budget is not None:
        lines.append(
            f"已用 {used}/{getattr(budget, 'max_delegations', '?')} 次委派"
        )
    injected = getattr(runtime, "injected_dispatches", 0)
    if injected:
        lines.append(f"缺口注入：{injected} 次（子代理提示含「当前未解决缺口」段）")

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
