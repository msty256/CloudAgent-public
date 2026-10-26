#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""统一诊断数据模型（变更 add-diagnosis-data-model）。

主 Agent 与四个专业诊断子 Agent（sql-diagnosis / code-analysis /
log-analysis / sync-diagnosis）之间传递诊断请求、调查任务、证据与
结构化诊断结果的统一数据契约。

设计依据：``docs/cloudagent-development-guide.md`` §5.2–§5.5。核心规则：

* 事实与推断分离——``Evidence.observation`` 只记录观测事实，
  ``RootCause`` 才承载候选根因、置信度与反证；
* 不允许无依据结论——``RootCause.supporting_evidence_ids`` 应能对应到
  ``DiagnosisResult.evidence`` 中的 ``evidence_id``，由
  :meth:`DiagnosisResult.validate_references` 校验；
* ``DiagnosisResult.status`` 仅允许 ``success`` / ``partial`` / ``failed``；
* 反序列化时忽略未知字段（前向兼容），已定义字段严格校验。

实现约定：标准库 ``dataclasses``，与仓库既有数据模型（如
``cloudagent_ext.tool_system.protocol.ToolResult``）风格一致；
每个模型提供 ``to_dict`` / ``from_dict`` 做 JSON 往返。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# 常量：状态与证据来源词表
# ---------------------------------------------------------------------------

STATUS_SUCCESS: str = "success"
STATUS_PARTIAL: str = "partial"
STATUS_FAILED: str = "failed"

VALID_STATUSES: frozenset[str] = frozenset({STATUS_SUCCESS, STATUS_PARTIAL, STATUS_FAILED})

#: 证据来源约定词表（指南 §5.4；允许其他合法来源取值）。
EVIDENCE_SOURCE_DATABASE: str = "database"
EVIDENCE_SOURCE_GIT: str = "git"
EVIDENCE_SOURCE_LOG: str = "log"
EVIDENCE_SOURCE_KAFKA: str = "kafka"
EVIDENCE_SOURCE_SYNC_JOB: str = "sync_job"
EVIDENCE_SOURCE_TOOL: str = "tool"
EVIDENCE_SOURCE_AGENT: str = "agent"
EVIDENCE_SOURCE_USER: str = "user"
EVIDENCE_SOURCE_OTHER: str = "other"


# ---------------------------------------------------------------------------
# 字段校验辅助（英文错误消息，与仓库既有校验风格一致）
# ---------------------------------------------------------------------------


def _require_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _require_text(value, name)


def _require_dict(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a dict, got {type(value).__name__}")
    return dict(value)


def _require_str_list(value: Any, name: str) -> list[str]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{name} must be a list of strings, got {type(value).__name__}")
    items: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"{name} must contain only strings, got {type(item).__name__}")
        items.append(item)
    return items


def _require_confidence(value: Any, name: str = "confidence") -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number between 0.0 and 1.0")
    result = float(value)
    if not 0.0 <= result <= 1.0:
        raise ValueError(f"{name} must be between 0.0 and 1.0, got {result!r}")
    return result


# ---------------------------------------------------------------------------
# 关联标识生成
# ---------------------------------------------------------------------------


def new_id(prefix: str) -> str:
    """Return a unique ``<prefix>-<12-hex>`` identifier."""
    clean = _require_text(prefix, "prefix")
    return f"{clean}-{uuid.uuid4().hex[:12]}"


def new_request_id() -> str:
    """诊断请求标识（``diag-`` 前缀）。"""
    return new_id("diag")


def new_task_id() -> str:
    """调查任务标识（``task-`` 前缀）。"""
    return new_id("task")


def new_evidence_id() -> str:
    """证据标识（``ev-`` 前缀）。"""
    return new_id("ev")


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass
class DiagnosisRequest:
    """一次诊断的入口请求（指南 §5.2）。"""

    request_id: str
    question: str
    context: dict[str, Any] = field(default_factory=dict)
    constraints: dict[str, Any] = field(default_factory=dict)
    requested_agents: list[str] | None = None

    def __post_init__(self) -> None:
        self.request_id = _require_text(self.request_id, "request_id")
        self.question = _require_text(self.question, "question")
        self.context = _require_dict(self.context, "context")
        self.constraints = _require_dict(self.constraints, "constraints")
        if self.requested_agents is not None:
            self.requested_agents = _require_str_list(
                self.requested_agents, "requested_agents"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "question": self.question,
            "context": dict(self.context),
            "constraints": dict(self.constraints),
            "requested_agents": (
                None if self.requested_agents is None else list(self.requested_agents)
            ),
        }

    @classmethod
    def from_dict(cls, data: Any) -> DiagnosisRequest:
        raw = _require_dict(data, "DiagnosisRequest")
        return cls(
            request_id=raw.get("request_id"),
            question=raw.get("question"),
            context=raw.get("context", {}),
            constraints=raw.get("constraints", {}),
            requested_agents=raw.get("requested_agents"),
        )


@dataclass
class InvestigationTask:
    """主 Agent 委派给专业子 Agent 的调查任务（指南 §5.3）。"""

    task_id: str
    parent_request_id: str
    agent_type: str
    objective: str
    inputs: dict[str, Any] = field(default_factory=dict)
    required_evidence: list[str] = field(default_factory=list)
    constraints: dict[str, Any] = field(default_factory=dict)
    budget: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.task_id = _require_text(self.task_id, "task_id")
        self.parent_request_id = _require_text(self.parent_request_id, "parent_request_id")
        self.agent_type = _require_text(self.agent_type, "agent_type")
        self.objective = _require_text(self.objective, "objective")
        self.inputs = _require_dict(self.inputs, "inputs")
        self.required_evidence = _require_str_list(
            self.required_evidence, "required_evidence"
        )
        self.constraints = _require_dict(self.constraints, "constraints")
        self.budget = _require_dict(self.budget, "budget")

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "parent_request_id": self.parent_request_id,
            "agent_type": self.agent_type,
            "objective": self.objective,
            "inputs": dict(self.inputs),
            "required_evidence": list(self.required_evidence),
            "constraints": dict(self.constraints),
            "budget": dict(self.budget),
        }

    @classmethod
    def from_dict(cls, data: Any) -> InvestigationTask:
        raw = _require_dict(data, "InvestigationTask")
        return cls(
            task_id=raw.get("task_id"),
            parent_request_id=raw.get("parent_request_id"),
            agent_type=raw.get("agent_type"),
            objective=raw.get("objective"),
            inputs=raw.get("inputs", {}),
            required_evidence=raw.get("required_evidence", []),
            constraints=raw.get("constraints", {}),
            budget=raw.get("budget", {}),
        )


# extend-evidence-semantics：可选字段上限（截断而非拒绝）
_PROVES_MAX_CHARS = 120
_CANNOT_PROVE_MAX_ITEMS = 5
_CANNOT_PROVE_ITEM_MAX_CHARS = 60
_APPLICABILITY_MAX_KEYS = 4
_RELATION_MAX_ITEMS = 3
_RELATION_KINDS = ("consistent", "complementary", "conflict")


@dataclass
class Evidence:
    """一条结构化证据（指南 §5.4）。``observation`` 只记录观测事实。"""

    evidence_id: str
    source_type: str
    source_ref: str
    observation: str
    observed_at: str | None = None
    scope: dict[str, Any] = field(default_factory=dict)
    reliability: str = ""
    # extend-evidence-semantics：四个可选语义字段（恒输出，缺失即空值）
    proves: str = ""
    cannot_prove: list[str] = field(default_factory=list)
    applicability: dict[str, Any] = field(default_factory=dict)
    relation: list[dict[str, Any]] = field(default_factory=list)
    # soft-warnings：可选字段类型降级时记录（不参与 eq/repr/序列化）
    _soft_warnings: list[str] = field(
        default_factory=list, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        self.evidence_id = _require_text(self.evidence_id, "evidence_id")
        self.source_type = _require_text(self.source_type, "source_type")
        self.source_ref = _require_text(self.source_ref, "source_ref")
        self.observation = _require_text(self.observation, "observation")
        # 可选字段一律软失败：类型不符 → 降级默认值 + warning，绝不因此拒绝整条结果
        # （变更 soften-optional-evidence-types；必填四项仍严格拒绝）
        warnings: list[str] = []
        if self.observed_at is not None and not isinstance(self.observed_at, str):
            warnings.append("evidence.observed_at: non-string value dropped")
            self.observed_at = None
        self.observed_at = _optional_text(self.observed_at, "observed_at")

        if not isinstance(self.scope, dict):
            warnings.append("evidence.scope: non-object value dropped")
            self.scope = {}
        self.scope = dict(self.scope)

        if not isinstance(self.reliability, str):
            warnings.append("evidence.reliability: non-string value dropped")
            self.reliability = ""
        self.reliability = self.reliability.strip()

        if not isinstance(self.proves, str):
            warnings.append("evidence.proves: non-string value dropped")
            self.proves = ""
        trimmed = self.proves.strip()
        self.proves = (
            trimmed if len(trimmed) <= _PROVES_MAX_CHARS else trimmed[: _PROVES_MAX_CHARS - 1] + "…"
        )

        if not isinstance(self.cannot_prove, (list, tuple)):
            warnings.append("evidence.cannot_prove: non-list value dropped")
            self.cannot_prove = []
        else:
            cleaned: list[str] = []
            dropped = 0
            for item in self.cannot_prove:
                if not isinstance(item, str):
                    dropped += 1
                    continue
                if item.strip():
                    cleaned.append(item.strip()[: _CANNOT_PROVE_ITEM_MAX_CHARS])
            if dropped:
                warnings.append(
                    f"evidence.cannot_prove: {dropped} non-string item(s) dropped"
                )
            self.cannot_prove = cleaned[: _CANNOT_PROVE_MAX_ITEMS]

        if not isinstance(self.applicability, dict):
            warnings.append("evidence.applicability: non-object value dropped")
            self.applicability = {}
        else:
            self.applicability = dict(self.applicability)
        if len(self.applicability) > _APPLICABILITY_MAX_KEYS:
            kept = list(self.applicability.items())[: _APPLICABILITY_MAX_KEYS]
            self.applicability = dict(kept)

        # relation 元素结构问题交给 DiagnosisResult 清洗（缺 with / 悬空 / kind 非常规）
        if not isinstance(self.relation, (list, tuple)):
            warnings.append("evidence.relation: non-list value dropped")
            self.relation = []
        else:
            items: list[dict[str, Any]] = []
            for item in self.relation:
                if not isinstance(item, dict):
                    warnings.append("evidence.relation: non-object item dropped")
                    continue
                items.append(dict(item))
            self.relation = items[: _RELATION_MAX_ITEMS]

        self._soft_warnings = warnings

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "source_type": self.source_type,
            "source_ref": self.source_ref,
            "observation": self.observation,
            "observed_at": self.observed_at,
            "scope": dict(self.scope),
            "reliability": self.reliability,
            "proves": self.proves,
            "cannot_prove": list(self.cannot_prove),
            "applicability": dict(self.applicability),
            "relation": [dict(item) for item in self.relation],
        }

    @classmethod
    def from_dict(cls, data: Any) -> Evidence:
        raw = _require_dict(data, "Evidence")
        return cls(
            evidence_id=raw.get("evidence_id"),
            source_type=raw.get("source_type"),
            source_ref=raw.get("source_ref"),
            observation=raw.get("observation"),
            observed_at=raw.get("observed_at"),
            scope=raw.get("scope", {}),
            reliability=raw.get("reliability", ""),
            proves=raw.get("proves", ""),
            cannot_prove=raw.get("cannot_prove", []),
            applicability=raw.get("applicability", {}),
            relation=raw.get("relation", []),
        )


@dataclass
class RootCause:
    """候选根因：描述 + 置信度 + 支持证据 + 反证（指南 §5.5）。"""

    description: str
    confidence: float
    supporting_evidence_ids: list[str] = field(default_factory=list)
    counter_evidence: list[str] = field(default_factory=list)
    confidence_rationale: str = ""

    def __post_init__(self) -> None:
        self.description = _require_text(self.description, "description")
        self.confidence = _require_confidence(self.confidence)
        self.supporting_evidence_ids = _require_str_list(
            self.supporting_evidence_ids, "supporting_evidence_ids"
        )
        self.counter_evidence = _require_str_list(
            self.counter_evidence, "counter_evidence"
        )
        if not isinstance(self.confidence_rationale, str):
            raise ValueError("confidence_rationale must be a string")
        self.confidence_rationale = self.confidence_rationale.strip()

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "confidence": self.confidence,
            "supporting_evidence_ids": list(self.supporting_evidence_ids),
            "counter_evidence": list(self.counter_evidence),
            "confidence_rationale": self.confidence_rationale,
        }

    @classmethod
    def from_dict(cls, data: Any) -> RootCause:
        raw = _require_dict(data, "RootCause")
        return cls(
            description=raw.get("description"),
            confidence=raw.get("confidence"),
            supporting_evidence_ids=raw.get("supporting_evidence_ids", []),
            counter_evidence=raw.get("counter_evidence", []),
            confidence_rationale=raw.get("confidence_rationale", ""),
        )


@dataclass
class DiagnosisResult:
    """统一诊断结果（指南 §5.5）。``status`` 仅允许三态。"""

    request_id: str
    agent_name: str
    status: str
    summary: str
    task_id: str | None = None
    skill_name: str = ""
    findings: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    root_causes: list[RootCause] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    validation_plan: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    # extend-evidence-semantics：构造期清洗出的软问题（不参与 eq/repr/序列化）
    _soft_warnings: list[str] = field(
        default_factory=list, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        self.request_id = _require_text(self.request_id, "request_id")
        self.agent_name = _require_text(self.agent_name, "agent_name")
        if self.status not in VALID_STATUSES:
            raise ValueError(
                f"status must be one of {sorted(VALID_STATUSES)}, got {self.status!r}"
            )
        self.summary = _require_text(self.summary, "summary")
        self.task_id = _optional_text(self.task_id, "task_id")
        if not isinstance(self.skill_name, str):
            raise ValueError("skill_name must be a string")
        self.skill_name = self.skill_name.strip()
        self.findings = _require_str_list(self.findings, "findings")
        self.evidence = _require_evidence_list(self.evidence)
        self.root_causes = _require_root_cause_list(self.root_causes)
        self.recommendations = _require_str_list(self.recommendations, "recommendations")
        self.validation_plan = _require_str_list(self.validation_plan, "validation_plan")
        self.limitations = _require_str_list(self.limitations, "limitations")
        self.next_steps = _require_str_list(self.next_steps, "next_steps")
        self._collect_soft_warnings()

    def _collect_soft_warnings(self) -> None:
        """构造期一次性清洗：丢弃悬空 ``relation``，记录软问题。

        **必须在这里做**，不能放进 ``reference_warnings()``——查询方法带副作用会导致
        "没人调用就不丢弃"、"调用两次结果不同"、``to_dict()`` 依赖调用顺序。
        """

        known = {item.evidence_id for item in self.evidence}
        # 先收 Evidence 层的类型降级告警，再做 relation 清洗
        warnings: list[str] = [
            f"{item.evidence_id}: {message}" for item in self.evidence for message in item._soft_warnings
        ]
        for item in self.evidence:
            kept: list[dict[str, Any]] = []
            for rel in item.relation:
                raw_target = rel.get("with")
                if not isinstance(raw_target, str) or not raw_target.strip():
                    warnings.append(
                        f"{item.evidence_id}: relation: dropped (invalid 'with')"
                    )
                    continue
                target = raw_target
                if target not in known:
                    warnings.append(
                        f"{item.evidence_id}: relation: references unknown evidence_id {target}"
                    )
                    continue
                kind = str(rel.get("kind", ""))
                if kind and kind not in _RELATION_KINDS:
                    warnings.append(
                        f"{item.evidence_id}: relation: unconventional kind {kind!r}"
                    )
                kept.append(rel)
            item.relation = kept
        self._soft_warnings = warnings

    def reference_warnings(self) -> list[str]:
        """返回构造期清洗出的**非致命**问题（纯查询、幂等、无副作用）。

        契约：仅用于非致命标注；致命问题一律走 :meth:`validate_references`。
        """

        return list(self._soft_warnings)

    def validate_references(self) -> list[str]:
        """Return reference-integrity problems (empty list when valid).

        检查项：

        * ``evidence`` 内是否有重复的 ``evidence_id``；
        * ``root_causes[*].supporting_evidence_ids`` 是否引用了不存在的证据。
        """
        problems: list[str] = []
        seen: set[str] = set()
        for item in self.evidence:
            if item.evidence_id in seen:
                problems.append(f"duplicate evidence_id: {item.evidence_id}")
            seen.add(item.evidence_id)
        for index, cause in enumerate(self.root_causes):
            for ref in cause.supporting_evidence_ids:
                if ref not in seen:
                    problems.append(
                        f"root_causes[{index}] references unknown evidence_id: {ref}"
                    )
        return problems

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "task_id": self.task_id,
            "agent_name": self.agent_name,
            "skill_name": self.skill_name,
            "status": self.status,
            "summary": self.summary,
            "findings": list(self.findings),
            "evidence": [item.to_dict() for item in self.evidence],
            "root_causes": [cause.to_dict() for cause in self.root_causes],
            "recommendations": list(self.recommendations),
            "validation_plan": list(self.validation_plan),
            "limitations": list(self.limitations),
            "next_steps": list(self.next_steps),
        }

    @classmethod
    def from_dict(cls, data: Any) -> DiagnosisResult:
        """Rebuild from a mapping; unknown fields are ignored (forward compatible)."""
        raw = _require_dict(data, "DiagnosisResult")
        evidence_raw = raw.get("evidence", [])
        root_causes_raw = raw.get("root_causes", [])
        if not isinstance(evidence_raw, (list, tuple)):
            raise ValueError("evidence must be a list")
        if not isinstance(root_causes_raw, (list, tuple)):
            raise ValueError("root_causes must be a list")
        return cls(
            request_id=raw.get("request_id"),
            task_id=raw.get("task_id"),
            agent_name=raw.get("agent_name"),
            skill_name=raw.get("skill_name", ""),
            status=raw.get("status"),
            summary=raw.get("summary"),
            findings=raw.get("findings", []),
            evidence=[Evidence.from_dict(item) for item in evidence_raw],
            root_causes=[RootCause.from_dict(item) for item in root_causes_raw],
            recommendations=raw.get("recommendations", []),
            validation_plan=raw.get("validation_plan", []),
            limitations=raw.get("limitations", []),
            next_steps=raw.get("next_steps", []),
        )


def _require_evidence_list(value: Any) -> list[Evidence]:
    if not isinstance(value, (list, tuple)):
        raise ValueError("evidence must be a list of Evidence")
    items: list[Evidence] = []
    for item in value:
        if not isinstance(item, Evidence):
            raise ValueError(
                f"evidence must contain only Evidence items, got {type(item).__name__}"
            )
        items.append(item)
    return items


def _require_root_cause_list(value: Any) -> list[RootCause]:
    if not isinstance(value, (list, tuple)):
        raise ValueError("root_causes must be a list of RootCause")
    items: list[RootCause] = []
    for item in value:
        if not isinstance(item, RootCause):
            raise ValueError(
                f"root_causes must contain only RootCause items, got {type(item).__name__}"
            )
        items.append(item)
    return items


# ---------------------------------------------------------------------------
# 缺口（变更 add-gap-driven-orchestration）
# ---------------------------------------------------------------------------

GAP_STATUS_OPEN = "open"
GAP_STATUS_RESOLVED = "resolved"
GAP_STATUS_BLOCKED = "blocked"
GAP_STATUS_INCONCLUSIVE = "inconclusive"
GAP_STATUSES = frozenset(
    {GAP_STATUS_OPEN, GAP_STATUS_RESOLVED, GAP_STATUS_BLOCKED, GAP_STATUS_INCONCLUSIVE}
)


@dataclass
class Gap:
    """一条证据缺口：命题 + 状态 + 复述次数 + 关联证据。

    ``restatements`` 表示**命题被再次陈述的次数**，不是"为该缺口派发过的次数"
    （渲染时必须写「复述 N 次」）。
    """

    gap_id: str
    statement: str
    status: str = GAP_STATUS_OPEN
    restatements: int = 0
    evidence_refs: list[str] = field(default_factory=list)
    note: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.gap_id, str) or not self.gap_id.strip():
            raise ValueError("gap_id must be a non-empty string")
        if not isinstance(self.statement, str) or not self.statement.strip():
            raise ValueError("gap statement must be a non-empty string")
        if self.status not in GAP_STATUSES:
            raise ValueError(f"gap status must be one of {sorted(GAP_STATUSES)}")
        if self.restatements < 0:
            raise ValueError("restatements must be >= 0")

    @property
    def is_open(self) -> bool:
        return self.status == GAP_STATUS_OPEN

