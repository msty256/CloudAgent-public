#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""调查会话：最小任务状态、预算控制与停止决策（变更 add-investigation-session）。

本模块是调查编排的最小控制面（纯内存账本，不做模型调用）：

* :class:`InvestigationSession` —— 围绕一个 :class:`DiagnosisRequest` 管理
  委派任务的轨迹（pending / completed / failed）、预算上限、重复委派防护、
  结果入账校验与停止决策；
* :class:`SessionBudget` / :class:`SessionTask` / :class:`SessionDecision` ——
  配套数据结构；
* :class:`DiagnosisSessionError` —— 会话级统一错误（``ValueError`` 子类）。

设计依据：``docs/cloudagent-development-guide.md`` §7.6（预算与停止条件的最小
子集）与 ``openspec/changes/add-investigation-session/design.md``。
实际委派仍由现有 Agent 工具执行；本模块只负责记账与决策。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cloudagent_ext.diagnosis.models import (
    STATUS_SUCCESS,
    DiagnosisRequest,
    DiagnosisResult,
    InvestigationTask,
    new_task_id,
)

__all__ = [
    "TASK_STATUS_PENDING",
    "TASK_STATUS_COMPLETED",
    "TASK_STATUS_FAILED",
    "DiagnosisSessionError",
    "SessionBudget",
    "GapSummary",
    "SessionDecision",
    "SessionTask",
    "InvestigationSession",
]

TASK_STATUS_PENDING: str = "pending"
TASK_STATUS_COMPLETED: str = "completed"
TASK_STATUS_FAILED: str = "failed"

_RESULT_TO_TASK_STATUS: dict[str, str] = {
    "success": TASK_STATUS_COMPLETED,
    "partial": TASK_STATUS_COMPLETED,
    "failed": TASK_STATUS_FAILED,
}


class DiagnosisSessionError(ValueError):
    """调查会话级错误（预算 / 防重复 / 状态 / 入账校验）。"""


@dataclass(frozen=True)
class SessionBudget:
    """会话预算（最小子集：委派次数上限）。"""

    max_delegations: int = 4
    max_delegations_per_agent: int = 2

    def __post_init__(self) -> None:
        if self.max_delegations < 1 or self.max_delegations_per_agent < 1:
            raise ValueError("budget limits must be positive integers")


@dataclass(frozen=True)
class SessionDecision:
    """停止决策：``should_continue`` + 机器可读原因。"""

    should_continue: bool
    reason: str


@dataclass(frozen=True)
class GapSummary:
    """缺口快照（由 runtime 计算后传给 ``decide()``，保持会话层不持有缺口状态）。"""

    total: int = 0
    open_ids: tuple[str, ...] = ()
    recent_open_ids: tuple[str, ...] = ()
    blocked_ids: tuple[str, ...] = ()

    @property
    def has_open(self) -> bool:
        return bool(self.open_ids)

    @property
    def only_blocked(self) -> bool:
        """存在缺口且没有 open（blocked / inconclusive 都算"不可继续"）。"""

        return bool(self.blocked_ids) and not self.open_ids


@dataclass(frozen=True)
class SessionTask:
    """会话内的一次委派记录（任务 + 状态 + 结果 / 失败原因）。"""

    task: InvestigationTask
    status: str = TASK_STATUS_PENDING
    result: DiagnosisResult | None = None
    failure_reason: str | None = None


@dataclass
class InvestigationSession:
    """一次诊断请求的调查会话（纯内存账本）。

    使用方式（与 Mock 委派闭环一致）：

    1. ``delegate(...)`` 创建委派任务（强制预算与防重复）；
    2. 委派执行后，用 ``record_result(...)`` 或 ``record_failure(...)`` 入账；
    3. ``decide()`` 给出继续 / 停止决策。
    """

    request: DiagnosisRequest
    budget: SessionBudget = field(default_factory=SessionBudget)
    _entries: list[SessionTask] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.request, DiagnosisRequest):
            raise DiagnosisSessionError("request must be a DiagnosisRequest")

    @property
    def request_id(self) -> str:
        return self.request.request_id

    @property
    def entries(self) -> tuple[SessionTask, ...]:
        """调用轨迹（只读快照）。"""
        return tuple(self._entries)

    @property
    def delegations_used(self) -> int:
        return len(self._entries)

    def delegate(
        self,
        agent_type: str,
        objective: str,
        *,
        inputs: dict[str, Any] | None = None,
        required_evidence: list[str] | None = None,
        constraints: dict[str, Any] | None = None,
        budget: dict[str, Any] | None = None,
    ) -> InvestigationTask:
        """创建一次委派任务（预算与防重复在创建前强制）。"""
        if self.delegations_used >= self.budget.max_delegations:
            raise DiagnosisSessionError(
                "budget exhausted: "
                f"{self.delegations_used}/{self.budget.max_delegations} delegations used"
            )
        agent_used = sum(1 for entry in self._entries if entry.task.agent_type == agent_type)
        if agent_used >= self.budget.max_delegations_per_agent:
            raise DiagnosisSessionError(
                f"budget exhausted for agent {agent_type!r}: "
                f"{agent_used}/{self.budget.max_delegations_per_agent} delegations used"
            )
        for entry in self._entries:
            if entry.task.agent_type != agent_type or entry.task.objective != objective:
                continue
            if entry.status == TASK_STATUS_PENDING:
                raise DiagnosisSessionError(
                    "duplicate delegation: identical task is already pending "
                    f"({entry.task.task_id})"
                )
            if entry.result is not None and entry.result.status == STATUS_SUCCESS:
                raise DiagnosisSessionError(
                    "duplicate delegation: identical task is already satisfied "
                    f"({entry.task.task_id})"
                )
        task = InvestigationTask(
            task_id=new_task_id(),
            parent_request_id=self.request_id,
            agent_type=agent_type,
            objective=objective,
            inputs=dict(inputs or {}),
            required_evidence=list(required_evidence or []),
            constraints=dict(constraints or {}),
            budget=dict(budget or {}),
        )
        self._entries.append(SessionTask(task=task))
        return task

    def record_result(self, result: DiagnosisResult) -> None:
        """记录一次诊断结果（校验后入账到对应的进行中任务）。"""
        if not isinstance(result, DiagnosisResult):
            raise DiagnosisSessionError("result must be a DiagnosisResult")
        if result.request_id != self.request_id:
            raise DiagnosisSessionError(
                f"request_id mismatch: expected {self.request_id!r}, got {result.request_id!r}"
            )
        problems = result.validate_references()
        if problems:
            raise DiagnosisSessionError(
                "invalid evidence references: " + "; ".join(problems)
            )
        index = self._find_pending_entry_index(result.task_id)
        entry = self._entries[index]
        status = _RESULT_TO_TASK_STATUS[result.status]
        self._entries[index] = SessionTask(
            task=entry.task,
            status=status,
            result=result,
            failure_reason=None if status == TASK_STATUS_COMPLETED else result.summary,
        )

    def conflict_report(self) -> dict[str, Any]:
        """汇总本次会话内的结论冲突（只读，不修改任何结果）。

        策略见 :mod:`cloudagent_ext.diagnosis.arbitration`：跨子代理冲突不裁决，
        只保证它被"看见"并写进报告。
        """

        from cloudagent_ext.diagnosis.arbitration import detect_conflicts, summarize

        return summarize(detect_conflicts(self._entries))

    def record_failure(self, task_id: str, *, reason: str) -> None:
        """记录一次委派失败（无结构化结果时使用，例如解析失败 / 执行异常）。"""
        if not isinstance(reason, str) or not reason.strip():
            raise DiagnosisSessionError("failure reason must be a non-empty string")
        index = self._find_pending_entry_index(task_id)
        entry = self._entries[index]
        self._entries[index] = SessionTask(
            task=entry.task,
            status=TASK_STATUS_FAILED,
            failure_reason=reason.strip(),
        )

    def decide(
        self,
        *,
        total_delegations: int | None = None,
        gaps: GapSummary | None = None,
    ) -> SessionDecision:
        """缺口驱动的停止决策（变更 add-gap-driven-orchestration）。

        判定顺序（design D4）：

        1. 预算耗尽（``total_delegations`` 含非诊断委派；``None`` 退回诊断条目数）
        2. 最近一次委派新增/复述了 open 缺口 → 继续
        3. 存在缺口且只剩 blocked/inconclusive → 停止
        4. 有成功结果且最近没有新缺口 → 停止
        5. 其余 → 继续

        注意：第 3 条的"存在缺口"是**必须**的——空列表上 ``all()`` 真空成立，
        会把"第一次就答对"误判成 ``blocked_only``。
        """

        used = self.delegations_used if total_delegations is None else total_delegations
        if used >= self.budget.max_delegations:
            return SessionDecision(should_continue=False, reason="budget_exhausted")

        summary = gaps or GapSummary()
        if summary.recent_open_ids:
            return SessionDecision(should_continue=True, reason="gap_open")
        if summary.only_blocked:
            return SessionDecision(should_continue=False, reason="blocked_only")

        has_success = any(
            entry.result is not None and entry.result.status == STATUS_SUCCESS
            for entry in self._entries
        )
        if has_success and not summary.recent_open_ids:
            return SessionDecision(should_continue=False, reason="success_recorded")
        return SessionDecision(should_continue=True, reason="budget_available")

    def _find_pending_entry_index(self, task_id: str | None) -> int:
        if not task_id:
            raise DiagnosisSessionError(
                "result has no task_id; cannot attribute it to a delegation"
            )
        for index, entry in enumerate(self._entries):
            if entry.task.task_id != task_id:
                continue
            if entry.status != TASK_STATUS_PENDING:
                raise DiagnosisSessionError(
                    f"task {task_id!r} is already {entry.status}; recording rejected"
                )
            return index
        raise DiagnosisSessionError(f"unknown task_id: {task_id!r}")
