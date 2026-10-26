#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""结论冲突检测与裁决策略（指南 P4 任务 9）。

**只做两件事：把冲突找出来、给一个明确的处理口径。**

不做的：替模型判断谁对。
同一现象两个子代理给出相反结论时，代码既没有地面真值、也没有比证据更可靠的依据——
自动"裁决"只会把错误藏起来。

因此策略是：

| 场景 | 处理 | 依据 |
|---|---|---|
| 跨子代理冲突 | ``unresolved``：不裁决，报告必须并列两侧证据 | 代码无法判断哪侧取证更充分 |
| 同一子代理内部冲突 | ``internal``：该子代理结论置信度封顶 0.4 | 内部自洽性都不满足，可信度必须下调 |

检测规则只有两条，都是可复核的：
1. 证据自报 ``relation.kind == "conflict"``；
2. 跨子代理的**相反 severity**（一侧 ``none`` 表示"正常/已同步"，另一侧 ``primary``），
   且两侧 ``match_terms`` 有交集（指向同一对象）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

__all__ = [
    "Conflict",
    "CONFLICT_UNRESOLVED",
    "CONFLICT_INTERNAL",
    "INTERNAL_CONFIDENCE_CAP",
    "detect_conflicts",
    "summarize",
]

CONFLICT_UNRESOLVED = "unresolved"      # 跨子代理：不裁决
CONFLICT_INTERNAL = "internal"          # 同一子代理自相矛盾
INTERNAL_CONFIDENCE_CAP = 0.4

_SEVERITY_NONE = "none"
_SEVERITY_PRIMARY = "primary"


@dataclass(frozen=True)
class Conflict:
    """一处冲突。``resolution`` 表示本模块的处理口径，不代表谁对。"""

    kind: str                 # evidence_relation / opposing_severity
    agents: list[str]
    subject: str
    evidence_ids: list[str]
    detail: str
    resolution: str = CONFLICT_UNRESOLVED

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "agents": list(self.agents),
            "subject": self.subject,
            "evidence_ids": list(self.evidence_ids),
            "detail": self.detail,
            "resolution": self.resolution,
        }


@dataclass
class _Owner:
    agent: str
    result: Any


def _agent_of(result: Any) -> str:
    return str(getattr(result, "agent_name", "") or "unknown")


def _iter_results(entries: Iterable[Any]) -> list[Any]:
    results = []
    for entry in entries:
        result = getattr(entry, "result", None)
        if result is not None:
            results.append(result)
    return results


def _detect_relation_conflicts(results: list[Any]) -> list[Conflict]:
    owners: dict[str, str] = {}
    for result in results:
        for evidence in getattr(result, "evidence", []) or []:
            owners[evidence.evidence_id] = _agent_of(result)

    found: list[Conflict] = []
    seen: set[tuple[str, str]] = set()
    for result in results:
        agent = _agent_of(result)
        for evidence in getattr(result, "evidence", []) or []:
            for relation in getattr(evidence, "relation", []) or []:
                if str(relation.get("kind", "")) != "conflict":
                    continue
                other = str(relation.get("with") or "")
                pair = tuple(sorted((evidence.evidence_id, other)))
                if pair in seen:
                    continue
                seen.add(pair)
                other_agent = owners.get(other, "unknown")
                same_agent = other_agent == agent and other_agent != "unknown"
                found.append(
                    Conflict(
                        kind="evidence_relation",
                        agents=sorted({agent, other_agent}),
                        subject=f"{evidence.evidence_id} ↔ {other or '（悬空引用）'}",
                        evidence_ids=[evidence.evidence_id, other] if other else [evidence.evidence_id],
                        detail=str(relation.get("why") or "证据自报关系为 conflict"),
                        resolution=CONFLICT_INTERNAL if same_agent else CONFLICT_UNRESOLVED,
                    )
                )
    return found


# 对立陈述对：左侧与右侧互斥。命中同一对象时视为疑似冲突。
# 只收「语义明确、误判代价可控」的几组；宁可漏判，不可乱判。
_OPPOSING_PAIRS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("未同步", "没有同步", "未落库", "没有落库", "缺失", "为空", "0 行"),
     ("已同步", "同步正常", "已落库", "行数一致", "一致", "有数据")),
    (("正常", "无异常", "没有问题"),
     ("异常", "失败", "有问题", "故障")),
)


def _keywords(text: str) -> set[str]:
    """抽取可对齐的对象名（表名/键名），抽不出返回空集合。

    复用协议里的保守策略：只认 ASCII 标识符，不做中文分词。
    因此这条规则**只在描述里带英文对象名时生效**，中文纯叙述会被跳过——
    属于有意接受的漏判。
    """

    from cloudagent_ext.diagnosis.text_match import extract_keywords

    return {item.lower() for item in extract_keywords(text)}


def _polarity(text: str) -> str | None:
    """判断陈述极性：negative / positive / None（无法判断）。"""

    raw = str(text or "")
    for negative, positive in _OPPOSING_PAIRS:
        has_negative = any(word in raw for word in negative)
        has_positive = any(word in raw for word in positive)
        if has_negative and not has_positive:
            return "negative"
        if has_positive and not has_negative:
            return "positive"
    return None


def _detect_opposing_claims(results: list[Any]) -> list[Conflict]:
    """跨子代理：一侧说"有问题"，另一侧说"正常"，且描述里指向同一对象。"""

    claims: list[tuple[str, str, str | None, set[str]]] = []
    for result in results:
        agent = _agent_of(result)
        for root in getattr(result, "root_causes", []) or []:
            description = str(getattr(root, "description", "") or "")
            claims.append((agent, description, _polarity(description), _keywords(description)))

    found: list[Conflict] = []
    for index, (agent_a, desc_a, polarity_a, keys_a) in enumerate(claims):
        for agent_b, desc_b, polarity_b, keys_b in claims[index + 1:]:
            if agent_a == agent_b or polarity_a is None or polarity_b is None:
                continue
            if polarity_a == polarity_b:
                continue
            shared = keys_a & keys_b
            if not shared:
                continue
            found.append(
                Conflict(
                    kind="opposing_claim",
                    agents=sorted({agent_a, agent_b}),
                    subject="、".join(sorted(shared)),
                    evidence_ids=[],
                    detail=(
                        f"{agent_a}：{desc_a[:60]}｜{agent_b}：{desc_b[:60]}"
                        "（按对立词表判定为疑似冲突，需人工确认）"
                    ),
                    resolution=CONFLICT_UNRESOLVED,
                )
            )
    return found


def detect_conflicts(entries: Iterable[Any]) -> list[Conflict]:
    """从会话账本里检测冲突（只读，不修改任何结果）。"""

    results = _iter_results(entries)
    if len(results) < 1:
        return []
    return _detect_relation_conflicts(results) + _detect_opposing_claims(results)


def summarize(conflicts: list[Conflict]) -> dict[str, Any]:
    """汇总：给报告与 /tasks 用的一行数据。"""

    unresolved = [item for item in conflicts if item.resolution == CONFLICT_UNRESOLVED]
    internal = [item for item in conflicts if item.resolution == CONFLICT_INTERNAL]
    return {
        "total": len(conflicts),
        "unresolved": len(unresolved),
        "internal": len(internal),
        "items": [item.to_dict() for item in conflicts],
        "policy": (
            "跨子代理冲突不自动裁决：报告必须并列两侧证据并说明未消解；"
            f"同子代理内部矛盾：该结论置信度封顶 {INTERNAL_CONFIDENCE_CAP}"
        ),
    }
