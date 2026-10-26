#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""把 :class:`InvestigationSession` 绑到 ``ToolContext`` 上（变更 wire-investigation-session）。

背景：P1 建好了调查会话（``diagnosis/session.py``），但 ``Agent`` 工具一直用
模块级计数器（进程级、跨会话共享、无任务轨迹）。本模块负责：

* 每个 ``ToolContext`` 一个 :class:`DiagnosisSessionRuntime`（会话 + 会话锁），
  不同上下文互不影响；
* 委派前 ``begin_delegation``（预算 / 重复防护由会话强制）；
* 结束后 ``finish_delegation`` 入账：解析 ``DiagnosisResult`` → 归一化标识 →
  ``record_result``；解析失败或入账失败一律 ``record_failure``，**绝不抛出**。

标识归一化（design D2）：``request_id`` 与 ``task_id`` 都由工具生成并注入提示，
工具才是权威来源。模型回显只作为"契约遵从度"信号，不是归账前提——因此不一致时
就地纠正并记日志（``request_id_corrected`` / ``task_id_injected``），而不是把
一次本来成功的诊断记为失败。被放宽的只有标识符：``status`` 与证据引用仍由
``InvestigationSession.record_result`` 严格校验。
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Any

from cloudagent_ext.diagnosis.models import (
    DiagnosisRequest,
    InvestigationTask,
    new_request_id,
)
from cloudagent_ext.diagnosis.protocol import DiagnosisParseError, parse_diagnosis_result
from cloudagent_ext.diagnosis.models import Gap  # noqa: E402

# 单次收割的产量上限（实跑：2 次委派产出 15 条缺口，纯叙述类无筛选价值）
_MAX_GAPS_PER_SOURCE = 3
from cloudagent_ext.diagnosis.text_match import (  # noqa: E402
    contains_all,
    extract_keywords,
    normalize_statement,
)
from cloudagent_ext.diagnosis.session import (
    DiagnosisSessionError,
    InvestigationSession,
    SessionBudget,
)

__all__ = [
    "DEFAULT_MAX_DELEGATIONS",
    "DEFAULT_MAX_DELEGATIONS_PER_AGENT",
    "DIAGNOSIS_AGENT_SUFFIX",
    "DiagnosisSessionRuntime",
    "begin_delegation",
    "default_budget",
    "finish_delegation",
    "get_or_create_runtime",
    "is_diagnosis_agent",
    "reset_session",
]

logger = logging.getLogger("cloudagent.diagnosis.session")

DIAGNOSIS_AGENT_SUFFIX: str = "-diagnosis"

# 预算默认值与可配置入口（变更 make-diagnosis-budget-configurable）。
# 配置走环境变量；``~/.cloudagent/config.json`` 的 ``env`` 块会在启动阶段由
# trust_boundary 注入 ``os.environ``，因此配置文件无需额外支持。
ENV_MAX_DELEGATIONS: str = "CLOUDAGENT_DIAGNOSIS_MAX_DELEGATIONS"
ENV_MAX_DELEGATIONS_PER_AGENT: str = "CLOUDAGENT_DIAGNOSIS_MAX_DELEGATIONS_PER_AGENT"

DEFAULT_MAX_DELEGATIONS: int = 15
DEFAULT_MAX_DELEGATIONS_PER_AGENT: int = 5

# 误配上界：超过这个量级多半是手滑（例如写成 99999），等于把护栏去掉。
_MAX_DELEGATIONS_CEILING: int = 1000

# 目标摘要长度：InvestigationTask.objective 会进子代理提示，不宜过长。
_OBJECTIVE_MAX_CHARS = 200

# 会话创建临界区：同一 context 可能被并发调用，避免各建一个会话导致预算翻倍。
_CREATION_LOCK = threading.RLock()

# 会话创建时还不知道目标是什麼；首个委派会把它替换掉（见 begin_delegation）。
_QUESTION_PLACEHOLDER = "(未提供调查目标)"


@dataclass
class DiagnosisSessionRuntime:
    """一个上下文持有的会话 + 会话锁（锁必须覆盖读-改-写全程）。

    ``other_delegations`` 记录**非诊断类**委派（Explore / Plan / general-purpose…）：
    它们与诊断共享同一份预算（保持 P3.6 的 6/3 语义），但不进会话轨迹——否则
    这些委派只能被记成 "failed"（没有协议结果可解析），或者永远停在 pending。
    """

    session: InvestigationSession
    lock: threading.RLock = field(default_factory=threading.RLock)
    other_delegations: dict[str, int] = field(default_factory=dict)
    # add-gap-driven-orchestration：缺口清单与"最近一次收割"（决定是否继续）
    gaps: list[Gap] = field(default_factory=list)
    last_harvest_ids: list[str] = field(default_factory=list)
    # 对照实验用：真正把缺口段落追加进子代理提示的次数（关闭注入时恒 0）
    injected_dispatches: int = 0

    def gap_summary(self):
        """把缺口清单压成决策用的快照（只读）。"""

        from cloudagent_ext.diagnosis.session import GapSummary

        open_ids = tuple(g.gap_id for g in self.gaps if g.status == "open")
        recent = tuple(gid for gid in self.last_harvest_ids if gid in open_ids)
        # resolved 不是"卡住"：只有 blocked / inconclusive 才计入 blocked_ids
        blocked = tuple(
            g.gap_id for g in self.gaps if g.status in {"blocked", "inconclusive"}
        )
        return GapSummary(
            total=len(self.gaps),
            open_ids=open_ids,
            recent_open_ids=recent,
            blocked_ids=blocked,
        )

    def decide(self):
        """基于当前状态给出继续/停止决策（口径含非诊断委派）。"""

        return self.session.decide(
            total_delegations=self.total_delegations,
            gaps=self.gap_summary(),
        )

    @property
    def total_delegations(self) -> int:
        return self.session.delegations_used + sum(self.other_delegations.values())


def is_diagnosis_agent(agent_type: Any) -> bool:
    """``sql-diagnosis`` / ``code-diagnosis`` / ``log-diagnosis`` 等。"""

    return isinstance(agent_type, str) and agent_type.endswith(DIAGNOSIS_AGENT_SUFFIX)


def _objective_from_prompt(prompt: str) -> str:
    text = " ".join(str(prompt or "").split())
    if not text:
        return _QUESTION_PLACEHOLDER
    if len(text) <= _OBJECTIVE_MAX_CHARS:
        return text
    return text[:_OBJECTIVE_MAX_CHARS] + "…"


def _read_limit(env_name: str, default: int) -> int:
    """读取正整数限额；缺失/非法/越界一律回退默认并告警（不阻断启动）。"""

    raw = os.environ.get(env_name)
    if raw is None or not str(raw).strip():
        return default
    text = str(raw).strip()
    try:
        value = int(text)
    except ValueError:
        logger.warning(
            "invalid %s=%r (not an integer); falling back to %d", env_name, text, default
        )
        return default
    if value < 1 or value > _MAX_DELEGATIONS_CEILING:
        logger.warning(
            "invalid %s=%r (must be 1..%d); falling back to %d",
            env_name,
            text,
            _MAX_DELEGATIONS_CEILING,
            default,
        )
        return default
    return value


def default_budget() -> SessionBudget:
    """当前生效的默认预算（每次调用重新读环境变量）。

    不在模块导入时求值：配置注入发生在启动阶段，可能晚于导入。
    """

    return SessionBudget(
        max_delegations=_read_limit(ENV_MAX_DELEGATIONS, DEFAULT_MAX_DELEGATIONS),
        max_delegations_per_agent=_read_limit(
            ENV_MAX_DELEGATIONS_PER_AGENT, DEFAULT_MAX_DELEGATIONS_PER_AGENT
        ),
    )


def get_or_create_runtime(
    context: Any,
    *,
    budget: SessionBudget | None = None,
) -> DiagnosisSessionRuntime | None:
    """取当前上下文的会话运行时；``context`` 不可用时返回 ``None``。

    首次调用时合成 ``DiagnosisRequest``：``request_id`` 由 ``new_request_id()``
    生成，``question`` 取"首个委派目标"——**它不是用户原话**，仅作会话标识用途。
    ``ToolContext`` 是 ``slots=True`` 的 dataclass，字段必须在类里声明。
    """

    if context is None:
        return None
    runtime = getattr(context, "diagnosis_session_runtime", None)
    if runtime is not None:
        return runtime

    # 创建竞态：同一 context 可能被并发调用。这里用一个极短的临界区，避免
    # 两个调用各建一个会话导致预算翻倍。
    with _CREATION_LOCK:
        runtime = getattr(context, "diagnosis_session_runtime", None)
        if runtime is not None:
            return runtime
        runtime = DiagnosisSessionRuntime(
            session=InvestigationSession(
                request=DiagnosisRequest(
                    request_id=new_request_id(),
                    question=_QUESTION_PLACEHOLDER,
                ),
                budget=budget if budget is not None else default_budget(),
            )
        )
        context.diagnosis_session_runtime = runtime
        return runtime


def reset_session(context: Any) -> None:
    """清空当前上下文的会话（测试用；也用于显式开始新一轮诊断）。"""

    if context is None:
        return
    with _CREATION_LOCK:
        context.diagnosis_session_runtime = None


def begin_delegation(
    runtime: DiagnosisSessionRuntime | None,
    agent_type: str,
    objective: str,
) -> InvestigationTask | None:
    """登记一次委派。预算/重复错误以 ``DiagnosisSessionError`` 抛出（应阻断）。

    诊断类委派进入会话轨迹并返回 ``InvestigationTask``；非诊断类只占用预算
    （返回 ``None``），不写入轨迹——它们没有协议结果可解析，写进去只会变成
    "failed" 或永久 pending。
    """

    if runtime is None:
        return None
    objective_text = _objective_from_prompt(objective)
    with runtime.lock:
        # 总预算必须在这里统一检查：session.delegate() 只数轨迹里的诊断条目
        # （session.py 的 self.delegations_used），看不到 other_delegations。
        # 若只在非诊断分支检查，诊断分支就能把总数推过上限（实现审查 P1-1）。
        _check_total_budget(runtime)
        if not is_diagnosis_agent(agent_type):
            _reserve_other_delegation(runtime, agent_type)
            return None
        # 首个委派把"未提供调查目标"占位替换为真实目标（design D1）。
        if runtime.session.request.question == _QUESTION_PLACEHOLDER:
            runtime.session.request.question = objective_text
        return runtime.session.delegate(agent_type, objective_text)


def _check_total_budget(runtime: DiagnosisSessionRuntime) -> None:
    """总预算检查（诊断 + 非诊断合并计数）。调用方须持有锁。"""

    budget = runtime.session.budget
    if runtime.total_delegations >= budget.max_delegations:
        raise DiagnosisSessionError(
            "budget exhausted: "
            f"{runtime.total_delegations}/{budget.max_delegations} delegations used"
        )


def _reserve_other_delegation(runtime: DiagnosisSessionRuntime, agent_type: str) -> None:
    """非诊断委派：沿用同一份 6/3 预算，但不进会话轨迹。调用方须持有锁。

    总预算由 :func:`_check_total_budget` 在入口统一检查（两条路径共用），
    这里只负责单 Agent 上限与计数——避免两条路径检查逻辑不对称。
    """

    budget = runtime.session.budget
    used = runtime.other_delegations.get(agent_type, 0)
    if used >= budget.max_delegations_per_agent:
        raise DiagnosisSessionError(
            f"budget exhausted for agent {agent_type!r}: "
            f"{used}/{budget.max_delegations_per_agent} delegations used"
        )
    runtime.other_delegations[agent_type] = used + 1


def finish_delegation(
    runtime: DiagnosisSessionRuntime | None,
    task: InvestigationTask | None,
    text: str,
) -> str:
    """入账一次委派结果，返回 ``completed`` / ``failed`` / ``skipped``。

    **绝不抛出**：会话是旁路账本，不能成为派发链路的单点。
    """

    if runtime is None or task is None:
        return "skipped"
    if not isinstance(text, str) or not text.strip():
        _record_failure(runtime, task, "empty result text")
        return "failed"

    request_id_corrected = False
    task_id_injected = False
    try:
        parsed = parse_diagnosis_result(text)
    except DiagnosisParseError as exc:
        _record_failure(runtime, task, f"protocol parse failed: {exc}")
        return "failed"
    except Exception as exc:  # noqa: BLE001 — 账本不阻断
        _record_failure(runtime, task, f"result parsing raised: {exc}")
        return "failed"

    with runtime.lock:
        if parsed.request_id != runtime.session.request_id:
            # 工具是标识的权威来源：纠正但不记失败（design D2）。
            request_id_corrected = True
            parsed.request_id = runtime.session.request_id
        if getattr(parsed, "task_id", None) != task.task_id:
            # 缺失或写错都覆盖：本次委派就是唯一的归属依据。
            task_id_injected = True
            parsed.task_id = task.task_id

        try:
            runtime.session.record_result(parsed)
        except DiagnosisSessionError as exc:
            _record_failure(runtime, task, f"record rejected: {exc}")
            _log_event(runtime, task, "failed", request_id_corrected, task_id_injected, str(exc))
            return "failed"
        except Exception as exc:  # noqa: BLE001
            _record_failure(runtime, task, f"record raised: {exc}")
            return "failed"

    harvest_gaps(runtime, parsed)
    _log_event(runtime, task, "completed", request_id_corrected, task_id_injected, "")
    return "completed"


def harvest_gaps(runtime: DiagnosisSessionRuntime, parsed: object) -> None:
    """把一次成功入账的结果收割成缺口（变更 add-gap-driven-orchestration）。

    * ``success`` / ``partial`` 的 ``next_steps`` → ``open``
    * ``failed`` 的 ``next_steps`` → ``blocked``（多为"先补权限"这类前提）
    * ``limitations``（任何状态）→ ``blocked``
    * 相同命题去重并累加 ``restatements``；达到 2 且仍 open → ``inconclusive``
    * ``success`` 且某条 evidence 的 observation 覆盖命题全部关键词 → ``resolved``

    绝不抛出：缺口是旁路账本。
    """

    try:
        with runtime.lock:
            records: list[tuple[str, str]] = []
            status = str(getattr(parsed, "status", "") or "")
            next_steps = getattr(parsed, "next_steps", None) or []
            limitations = getattr(parsed, "limitations", None) or []
            def _actionable(statement: Any) -> bool:
                """命题必须含至少一个结构化标识符/数字，纯叙述条目不入账。

                理由（2026-10-24 实跑）：一次委派可产出十几条"无法判断/未检查…"
                的自述，既不可核销也无法被证据命中的命题只会淹没注入段。
                这是**结构化**门槛（有没有标识符），不是语义分类。
                """

                return bool(extract_keywords(str(statement or "")))

            steps = [str(item or "") for item in next_steps]
            limits = [str(item or "") for item in limitations]
            kept_steps = [item for item in steps if _actionable(item)][: _MAX_GAPS_PER_SOURCE]
            kept_limits = [item for item in limits if _actionable(item)][: _MAX_GAPS_PER_SOURCE]
            for step in kept_steps:
                records.append((step, "blocked" if status == "failed" else "open"))
            for limit in kept_limits:
                records.append((limit, "blocked"))

            touched: list[str] = []
            for statement, gap_status in records:
                if not statement.strip():
                    continue
                normalized = normalize_statement(statement)
                existing = next(
                    (g for g in runtime.gaps if normalize_statement(g.statement) == normalized),
                    None,
                )
                if existing is None:
                    gap = Gap(
                        gap_id=f"gap-{len(runtime.gaps) + 1}",
                        statement=statement.strip(),
                        status=gap_status,
                    )
                    runtime.gaps.append(gap)
                else:
                    gap = existing
                    gap.restatements += 1
                    if gap_status == "blocked" and gap.status == "open":
                        gap.status = "blocked"
                if gap.status == "open":
                    touched.append(gap.gap_id)

            if status == "success":
                for gap in runtime.gaps:
                    if gap.status != "open":
                        continue
                    keywords = extract_keywords(gap.statement)
                    if not keywords:
                        continue
                    for evidence in getattr(parsed, "evidence", None) or []:
                        observation = str(getattr(evidence, "observation", "") or "")
                        if contains_all(observation, keywords, normalize=True):
                            gap.status = "resolved"
                            gap.evidence_refs.append(str(getattr(evidence, "evidence_id", "")))
                            break

            for gap in runtime.gaps:
                if gap.status == "open" and gap.restatements >= 2:
                    gap.status = "inconclusive"

            open_ids = {g.gap_id for g in runtime.gaps if g.status == "open"}
            runtime.last_harvest_ids = [gid for gid in touched if gid in open_ids]
    except Exception:  # noqa: BLE001 — 收割失败不得影响入账
        return


def _record_failure(runtime: DiagnosisSessionRuntime, task: InvestigationTask, reason: str) -> None:
    try:
        with runtime.lock:
            runtime.session.record_failure(task.task_id, reason=reason)
        _log_event(runtime, task, "failed", False, False, reason)
    except Exception:  # noqa: BLE001 — 二次失败只能吞掉
        logger.debug("diagnosis session record_failure failed for %s", task.task_id, exc_info=True)


def _log_event(
    runtime: DiagnosisSessionRuntime,
    task: InvestigationTask,
    status: str,
    request_id_corrected: bool,
    task_id_injected: bool,
    detail: str,
) -> None:
    """结构化日志：单行 JSON，便于 grep 与评测采集。"""

    payload = {
        "event": "diagnosis_delegation",
        "request_id": runtime.session.request_id,
        "task_id": task.task_id,
        "agent_type": task.agent_type,
        "status": status,
        "request_id_corrected": request_id_corrected,
        "task_id_injected": task_id_injected,
    }
    if detail:
        payload["detail"] = detail[:200]
    try:
        logger.info("diagnosis_delegation %s", json.dumps(payload, ensure_ascii=False))
    except Exception:  # noqa: BLE001
        logger.debug("diagnosis session log serialization failed", exc_info=True)
