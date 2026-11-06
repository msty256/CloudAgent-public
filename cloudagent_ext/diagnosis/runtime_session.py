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

from cloudagent_ext.diagnosis.domain_gate import (
    GATE_MODE_SAME_TARGET,
    GATE_MODES,
    DomainGateContext,
    build_domain_chain,
    domain_of,
)
from cloudagent_ext.diagnosis.models import (
    DiagnosisRequest,
    InvestigationTask,
    new_request_id,
)
from cloudagent_ext.diagnosis.protocol import DiagnosisParseError, parse_diagnosis_result
from cloudagent_ext.diagnosis.models import Gap  # noqa: E402
from cloudagent_ext.diagnosis.gap_store import GapStore  # noqa: E402

# 单次收割的产量上限（实跑：2 次委派产出 15 条缺口，纯叙述类无筛选价值）
_MAX_GAPS_PER_SOURCE = 3

# T0.3：一次会话最多保留多少条停止判定记录（避免报告随轮次无限膨胀）
_MAX_DECISION_LOG = 50

# T0.4：一次会话最多保留多少条缺口迁移事件（同上）
_MAX_GAP_EVENTS = 200

# --- 阶段 1：域闸 ------------------------------------------------
# off / same_target / strict（详见 diagnosis/domain_gate.py 的模块说明）
ENV_DOMAIN_GATE: str = "CLOUDAGENT_DOMAIN_GATE"
ENV_DOMAIN_MAX_DELEGATIONS: str = "CLOUDAGENT_DIAGNOSIS_DOMAIN_MAX_DELEGATIONS"

DEFAULT_DOMAIN_GATE: str = GATE_MODE_SAME_TARGET
# 单域最多派几次就转向。**这个数字要拿基线复核**：阶段 0 测出"每结论平均委派数"若
# 常态就是 4–5，3 就太紧。所以可配，且不替代 max_delegations_per_agent（硬兜底）。
DEFAULT_DOMAIN_MAX_DELEGATIONS: int = 3

_DOMAIN_CHAIN = build_domain_chain()
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
    "propagate_invalidation",
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
    # 阶段 4（T4.1）：缺口账本的**唯一写者**。阶段 4 之前 `gaps` 是个裸 list，
    # 只有一个写者所以没问题；加了"回退/解除"之后就有了第二个写者，
    # 两个写者直接改同一个 list，最终状态由调用顺序决定——这种 bug 不会立刻显现，
    # 只会在某次结果迟到时让人查一整天。
    gap_store: GapStore = field(default_factory=GapStore)
    last_harvest_ids: list[str] = field(default_factory=list)
    # 对照实验用：真正把缺口段落追加进子代理提示的次数（关闭注入时恒 0）
    injected_dispatches: int = 0
    # T0.3（度量地基）：每次停止判定的记录。缺口机制原来只把 reason 丢进 debug 日志，
    # 导致"为什么停"无法统计；这里按时间顺序留最近 N 条，报告侧直接读。
    decision_log: list[dict] = field(default_factory=list)
    # 序号必须单调递增（截断后不重置），否则事件的先后顺序就丢了
    decision_seq: int = 0
    # 计数**不能**从 decision_log 反推：日志有上限（见 _MAX_DECISION_LOG），
    # 一旦截断，早期的判定就漏计了。所以单独维护累加器。
    decision_tallies: dict[str, int] = field(default_factory=dict)
    # T0.4（度量地基）：缺口状态迁移事件。现在只有"向前"的迁移（新增/降级/核销），
    # 但阶段 4 要加"回退/解除"，那两类指标的采集口必须提前存在——否则到时
    # 逻辑与埋点会同时改动，分不清回归来自哪一边。
    # 阶段 4：事件与序号都移交给 GapStore 维护，这里只做转发（单一真相源）。
    # 阶段 1：域闸拦截计数（域短名 → 次数）+ 明细。
    # 与 decision_log 分开：域闸不产生会话级判定，混在一起会让"终止原因分布"失真。
    domain_blocks: dict[str, int] = field(default_factory=dict)
    domain_block_log: list[dict] = field(default_factory=list)
    # 阶段 2（T2.1）：状态版本。**只在"语义推翻"时递增**（改目标 / 缺口回退），
    # 正常收割**不递增**——否则每个委派收割后版本都变，下一个委派结果回来时必然
    # 被判"陈旧"而丢弃，症状是"证据全丢但日志一切正常"。
    state_revision: int = 0
    # 派发时记下的版本（task_id → revision）。**不靠模型回显**：
    # request_id / task_id 已经证明模型遵从度不可靠，版本号同理。
    dispatch_revisions: dict[str, int] = field(default_factory=dict)
    # 被判定陈旧而丢弃的写入次数（正常流程应恒 0）
    stale_discarded: int = 0
    # 版本推进的原因记录（谁把它推进的，事后可查）
    bump_log: list[dict] = field(default_factory=list)
    # 阶段 2（B2）：独立核查结论（每条一次；skipped 也记，便于算"该核没核"）
    assessments: list[Any] = field(default_factory=list)
    # 阶段 4（T4.4）：本轮有"回退过的缺口再次 resolved" → 强制走核查（无视策略）。
    # 由 harvest_gaps 置位、由核查器消费并清除；存在这里是因为核查的触发点在
    # agent.py，而决定权在缺口账本——两者之间只能用会话级标记传话。
    force_verify_reason: str = ""

    # ---- 只读视图（阶段 4）：外部代码照旧读，但改状态必须走 `gap_store` ----

    @property
    def gaps(self) -> tuple[Gap, ...]:
        """当前缺口。返回 tuple：想改状态请用 ``gap_store`` 的方法。"""

        return self.gap_store.gaps()

    @property
    def gap_events(self) -> tuple[dict, ...]:
        return self.gap_store.events()

    @property
    def gap_event_seq(self) -> int:
        return self.gap_store.seq

    def record_assessment(self, assessment: Any, gaps: Any = ()) -> None:
        """回写核查结论到缺口（失败不影响主链路）。

        ``verified`` 只管"这条 resolved 过没过核查"；``verification`` 记原因
        （``ok`` / ``overclaimed: …`` / ``unavailable: …``），便于事后区分
        "核了没过"与"压根没核"。
        """

        try:
            self.assessments.append(assessment)
            verified = {str(gid) for gid in (getattr(assessment, "verified_gaps", ()) or ())}
            status = str(getattr(assessment, "status", "") or "")
            reason = str(getattr(assessment, "reason", "") or "")[:200]
            for gap in gaps or ():
                gap_id = str(getattr(gap, "gap_id", ""))
                passed = gap_id in verified
                gap.verified = passed
                gap.verification = "ok" if passed else f"{status}: {reason}".strip(": ")
        except Exception:  # noqa: BLE001 — 核查回写是旁路
            logger.debug("diagnosis assessment writeback failed", exc_info=True)

    def gap_summary(self, domain: str | None = None):
        """把缺口清单压成决策用的快照（只读）。

        ``domain=None`` 是全量（会话级判定用的口径，与改造前一致）；
        传域短名（``code``）则只统计该域的缺口——域闸与状态段都按域取。
        空 ``source_domain``（历史数据/非诊断委派）只在全量口径里出现。
        """

        from cloudagent_ext.diagnosis.session import GapSummary

        gaps = self.gaps
        if domain is not None:
            gaps = [g for g in self.gaps if domain_of(getattr(g, "source_domain", "")) == domain]

        open_ids = tuple(g.gap_id for g in gaps if g.status == "open")
        recent = tuple(gid for gid in self.last_harvest_ids if gid in open_ids)
        # resolved 不是"卡住"：只有 blocked / inconclusive 才计入 blocked_ids
        blocked = tuple(
            g.gap_id for g in gaps if g.status in {"blocked", "inconclusive"}
        )
        return GapSummary(
            total=len(gaps),
            open_ids=open_ids,
            recent_open_ids=recent,
            blocked_ids=blocked,
        )

    def decide(self):
        """基于当前状态给出继续/停止决策（口径含非诊断委派）。

        每次调用都会记一条到 :attr:`decision_log`——包括主流程。这样"终止原因分布"
        与"误停止率"不需要靠 grep 日志重算，落盘产物里直接可读。
        """

        summary = self.gap_summary()
        decision = self.session.decide(
            total_delegations=self.total_delegations,
            gaps=summary,
        )
        self._record_decision(decision, summary)
        return decision

    def _record_decision(self, decision: Any, summary: Any) -> None:
        """记录一次判定（失败不得影响派发）。调用方须持有锁或处于单线程路径。"""

        try:
            self.decision_seq += 1
            reason = str(getattr(decision, "reason", "") or "")
            if reason:
                self.decision_tallies[reason] = self.decision_tallies.get(reason, 0) + 1
            self.decision_log.append(
                {
                    "n": self.decision_seq,
                    "should_continue": bool(getattr(decision, "should_continue", True)),
                    "reason": reason,
                    "evaluator": str(getattr(decision, "evaluator", "") or ""),
                    "total_delegations": self.total_delegations,
                    "open_gaps": len(getattr(summary, "open_ids", ()) or ()),
                    "blocked_gaps": len(getattr(summary, "blocked_ids", ()) or ()),
                    "gaps_total": int(getattr(summary, "total", 0) or 0),
                }
            )
            if len(self.decision_log) > _MAX_DECISION_LOG:
                del self.decision_log[: -_MAX_DECISION_LOG]
        except Exception:  # noqa: BLE001 — 度量失败不得阻断决策
            logger.debug("diagnosis decision log append failed", exc_info=True)

    @property
    def decision_counts(self) -> dict[str, int]:
        """reason → 累计次数（不受 ``decision_log`` 截断影响）。"""

        return dict(self.decision_tallies)

    # -- 阶段 1：域闸 ----------------------------------------------------

    def domain_stats(self) -> dict[str, int]:
        """域短名 → 已用委派次数（诊断条目；非诊断委派没有域语义，不计入）。"""

        stats: dict[str, int] = {}
        for entry in self.session.entries:
            name = domain_of(getattr(entry.task, "agent_type", ""))
            if not name:
                continue
            stats[name] = stats.get(name, 0) + 1
        return stats

    def domain_gate(self, domain: str, objective: str = "") -> Any | None:
        """该域当前该不该拦（返回 :class:`StopDecision` 或 ``None``=放行）。

        **独立的域链**，与会话链（``decide()``）互不影响：

        * 会话链回答"整个会话还该不该继续"；
        * 域链回答"这一次派给这个域还有没有意义"。

        两者分开的原因是折叠只产出单一决策——把域配额（``hard``）塞进会话链会赢得折叠，
        导致"一个域卡住 → 整个会话停"，正好是域闸要避免的事。
        """

        if not domain:
            return None
        try:
            gaps = tuple(
                g
                for g in self.gaps
                if domain_of(getattr(g, "source_domain", "")) == domain
            )
            context = DomainGateContext(
                domain=domain,
                objective=str(objective or ""),
                gaps=gaps,
                used=self.domain_stats().get(domain, 0),
                quota=default_domain_quota(),
                mode=domain_gate_mode(),
            )
            return _DOMAIN_CHAIN.evaluate(context)
        except Exception:  # noqa: BLE001 — 域闸是旁路，异常一律放行
            logger.debug("diagnosis domain gate failed; allowing dispatch", exc_info=True)
            return None

    # -- 阶段 2（T2.1）：状态版本 ------------------------------------------

    def bump_state_revision(self, *, reason: str = "") -> int:
        """显式推进状态版本。**只应在"语义被推翻"时调用。**

        调用时机（写死在文档里，避免以后有人顺手在收割后也调一次）：

        * 调查目标被改写（旧快照的前提没了）；
        * 缺口被回退（阶段 4 的证据失效传播）。

        **不要在正常收割后调用**——那会让所有在飞的委派结果被判陈旧。
        """

        self.state_revision += 1
        self.bump_log.append({"revision": self.state_revision, "reason": str(reason or "")})
        if len(self.bump_log) > _MAX_DECISION_LOG:
            del self.bump_log[: -_MAX_DECISION_LOG]
        return self.state_revision

    def is_stale(self, task_id: str) -> bool:
        """这次委派的结果是否已过期（派发后状态版本变过）。"""

        dispatched_at = self.dispatch_revisions.get(task_id)
        if dispatched_at is None:
            return False  # 没记录过 = 不是我们派的，不做判断
        return dispatched_at != self.state_revision

    def record_domain_block(self, domain: str, decision: Any) -> None:
        """记一次域闸拦截（失败不影响派发）。"""

        try:
            reason = str(getattr(decision, "reason", "") or "")
            self.domain_blocks[domain] = self.domain_blocks.get(domain, 0) + 1
            self.domain_block_log.append(
                {
                    "domain": domain,
                    "reason": reason,
                    "evaluator": str(getattr(decision, "evaluator", "") or ""),
                    "used": self.domain_stats().get(domain, 0),
                }
            )
            if len(self.domain_block_log) > _MAX_DECISION_LOG:
                del self.domain_block_log[: -_MAX_DECISION_LOG]
        except Exception:  # noqa: BLE001
            logger.debug("diagnosis domain block record failed", exc_info=True)

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


def domain_gate_mode() -> str:
    """域闸档位（``off`` / ``same_target`` / ``strict``）；非法值回退默认并告警。"""

    raw = os.environ.get(ENV_DOMAIN_GATE)
    if raw is None or not str(raw).strip():
        return DEFAULT_DOMAIN_GATE
    text = str(raw).strip().lower()
    if text not in GATE_MODES:
        logger.warning(
            "invalid %s=%r (must be one of %s); falling back to %s",
            ENV_DOMAIN_GATE,
            raw,
            sorted(GATE_MODES),
            DEFAULT_DOMAIN_GATE,
        )
        return DEFAULT_DOMAIN_GATE
    return text


def default_domain_quota() -> int | None:
    """单域配额；``0`` 表示不设配额（阶段 5 分臂需要"只关配额、只关 blocked"两种组合）。"""

    raw = os.environ.get(ENV_DOMAIN_MAX_DELEGATIONS)
    if raw is not None and str(raw).strip() == "0":
        return None
    return _read_limit(ENV_DOMAIN_MAX_DELEGATIONS, DEFAULT_DOMAIN_MAX_DELEGATIONS)


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
        task = runtime.session.delegate(agent_type, objective_text)
        # 阶段 2（T2.1）：记下派发时的状态版本，回来时比对（不依赖模型回显）。
        runtime.dispatch_revisions[task.task_id] = runtime.state_revision
        return task


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
    """入账一次委派结果，返回 ``completed`` / ``failed`` / ``skipped`` / ``stale``。

    **绝不抛出**：会话是旁路账本，不能成为派发链路的单点。
    """

    if runtime is None or task is None:
        return "skipped"
    if not isinstance(text, str) or not text.strip():
        _record_failure(runtime, task, "empty result text")
        return "failed"

    # 阶段 2（T2.1）：陈旧结果丢弃。派发后状态版本变过（改目标 / 缺口被推翻），
    # 这次委派的结果对应的是旧前提，写进账本会污染 has_success 与缺口。
    #
    # 注意这里仍然**关掉这条任务**（记成 failed）而不是让它留在 pending：
    # 留 pending 会让 session.delegate() 的"重复委派"防护把后续同题派发全拦住。
    if runtime.is_stale(task.task_id):
        runtime.stale_discarded += 1
        _record_failure(runtime, task, "stale result discarded (state revision changed)")
        return "stale"

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

    # 阶段 1：把委派类型带进收割，让缺口能按域归因（域闸与状态段都依赖它）。
    harvest_gaps(runtime, parsed, domain=task.agent_type)
    _log_event(runtime, task, "completed", request_id_corrected, task_id_injected, "")
    return "completed"


def _append_gap_event(
    runtime: DiagnosisSessionRuntime,
    gap: Any,
    from_status: str,
    to_status: str,
    why: str,
    evidence_id: str = "",
) -> None:
    """记录一次缺口状态迁移（T0.4）。**绝不抛出**：度量不得影响收割。

    ``why`` 取值：``new`` / ``blocked`` / ``resolved`` / ``restated``；
    阶段 4 会新增 ``invalidated``（证据推翻）与 ``released``（blocked 解除）。
    """

    try:
        runtime.gap_event_seq += 1
        runtime.gap_events.append(
            {
                "seq": runtime.gap_event_seq,
                "gap_id": str(getattr(gap, "gap_id", "") or ""),
                "domain": str(getattr(gap, "source_domain", "") or ""),
                "from": from_status,
                "to": to_status,
                "why": why,
                "evidence_id": evidence_id,
            }
        )
        if len(runtime.gap_events) > _MAX_GAP_EVENTS:
            del runtime.gap_events[: -_MAX_GAP_EVENTS]
    except Exception:  # noqa: BLE001 — 度量失败不得影响收割
        logger.debug("diagnosis gap event append failed", exc_info=True)


def harvest_gaps(
    runtime: DiagnosisSessionRuntime,
    parsed: object,
    *,
    domain: str = "",
) -> None:
    """把一次成功入账的结果收割成缺口（变更 add-gap-driven-orchestration）。

    * ``success`` / ``partial`` 的 ``next_steps`` → ``open``
    * ``failed`` 的 ``next_steps`` → ``blocked``（多为"先补权限"这类前提）
    * ``limitations``（任何状态）→ ``blocked``
    * 相同命题去重并累加 ``restatements``；达到 2 且仍 open → ``inconclusive``
    * ``success`` 且某条 evidence 的 observation 覆盖命题全部关键词 → ``resolved``

    ``domain`` 是本次委派的 agent_type（如 ``code-diagnosis``），写进 ``Gap.source_domain``。
    默认空是为了兼容既有调用方（测试里有十处两参调用）——空域 = 未归因，域闸会放行。

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
            store = runtime.gap_store
            for statement, gap_status in records:
                if not statement.strip():
                    continue
                # 去重 / 累加 restatements / 域回填 / blocked 降级 全部在 store 里，
                # 语义与改造前逐条一致（T4.1 是行为等价重构）。
                gap = store.add(statement, domain=domain, status=gap_status)
                if gap.status == "open":
                    touched.append(gap.gap_id)

            if status == "success":
                for gap in store.gaps():
                    # 阶段 4（T4.3）：覆盖检查的适用范围从 open 扩到 open + blocked，
                    # 但**结果不同**——覆盖说明"前提可能已满足"，不等于"已经查清"。
                    if gap.status not in ("open", "blocked"):
                        continue
                    keywords = extract_keywords(gap.statement)
                    if not keywords:
                        continue
                    for evidence in getattr(parsed, "evidence", None) or []:
                        observation = str(getattr(evidence, "observation", "") or "")
                        if contains_all(observation, keywords, normalize=True):
                            evidence_id = str(getattr(evidence, "evidence_id", ""))
                            if gap.status == "open":
                                store.mark_resolved(gap.gap_id, evidence_id=evidence_id)
                                # 阶段 4（T4.4）：这条结论曾被证据推翻过。
                                # 用同一个关键词判定让它"再 resolved"一次等于什么都没变，
                                # 所以强制走独立核查——传播走快路径，收敛必须走慢路径。
                                if getattr(gap, "revert_count", 0) > 0:
                                    runtime.force_verify_reason = "invalidated_then_resolved"
                            else:
                                # blocked → open：走正常流程，再次 resolved 还要过核查
                                store.release(
                                    gap.gap_id,
                                    why=f"覆盖性证据 {evidence_id} 已到达，解除阻塞待复核",
                                    evidence_id=evidence_id,
                                )
                            break

            for gap in store.gaps():
                if gap.status == "open" and gap.restatements >= 2:
                    store.mark_inconclusive(gap.gap_id, why="restated")

            open_ids = {g.gap_id for g in store.gaps() if g.status == "open"}
            runtime.last_harvest_ids = [gid for gid in touched if gid in open_ids]

            # 阶段 4（T4.2）：收割之后再做失效传播（同一把锁内）。
            # 顺序有讲究：先让本轮证据正常入账，再看它是否推翻了早先的结论——
            # 反过来的话，本轮刚核销的缺口会被自己推翻。
            propagate_invalidation(runtime, parsed)
    except Exception:  # noqa: BLE001 — 收割失败不得影响入账
        return


def propagate_invalidation(
    runtime: DiagnosisSessionRuntime,
    parsed: object,
) -> int:
    """把本次结果里的**证据冲突声明**传播成缺口回退（阶段 4 · T4.2）。返回回退条数。

    **只降级，不裁决。** 仲裁模块的策略一直是"跨子代理冲突不裁决，只保证它被看见"，
    这里不破坏那条规则：

    * 裁决（不做）：判断 ``ev:sql:1`` 和 ``ev:sql:7`` 谁对——需要领域判断；
    * 降级（这里做）：把**依赖旧证据**的缺口退回待复核——只需要"存在冲突声明"这个事实。

    所以输出是**可信度**，不是**胜负**。这也解释了它为什么能走确定性快路径：
    检测冲突是结构匹配，不需要理解语义。

    触发源是子代理已经在用的 ``Evidence.relation``（``kind == "conflict"``，
    ``with`` 指向被冲突的证据 id）——**不新增协议字段**。

    绝不抛出：失效传播是旁路，不能影响入账。
    """

    try:
        from cloudagent_ext.diagnosis.switches import evidence_invalidation_enabled

        if not evidence_invalidation_enabled():
            return 0
        status = str(getattr(parsed, "status", "") or "")
        if status not in ("success", "partial"):
            return 0

        with runtime.lock:
            store = runtime.gap_store
            reverted = 0
            for evidence in getattr(parsed, "evidence", None) or []:
                new_id = str(getattr(evidence, "evidence_id", "") or "")
                for relation in getattr(evidence, "relation", []) or []:
                    if str(relation.get("kind", "")) != "conflict":
                        continue
                    old_id = str(relation.get("with") or "")
                    if not old_id:
                        continue
                    why = f"证据冲突：{new_id} vs {old_id}；已退回待复核"
                    for gap in store.resolved_claiming(old_id):
                        if store.revert(gap.gap_id, why=why, evidence_id=new_id):
                            reverted += 1
            if reverted:
                logger.info("invalidated %d resolved gaps via evidence conflict", reverted)
            return reverted
    except Exception:  # noqa: BLE001 — 传播失败不得影响收割
        logger.debug("propagate_invalidation failed", exc_info=True)
        return 0


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
