#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""独立完成核查（阶段 2 · B2）。

**为什么需要**：``decide()`` 里那条 ``success_recorded`` 的"成功"是子代理**自报**的；
``resolved`` 是**关键词全覆盖**判出来的（词表 ``TERM_EQUIVALENTS`` 同时影响评分与生产判定）。
两条都可能在"字段齐全、计算自洽、结论仍错"的情况下给出乐观信号。

**照抄的是调度，不是形态。** 参考实现（openJiuwen ``harness/goal/evaluation.py``）里，
无工具 / ``temperature=0`` / 64k 尾部截断只是**评估器的执行形态**；真正的成本控制在那三条调度规则上：

=============  ================================================================
``agent_report`` 不核查（= 改造前）
``transcript``   每次都核查
``hybrid``（默认）报终态（success/partial）→ **必核查**；报 continue → 信任；
                 每 ``verification_interval`` 次额外抽查一次；冲突以核查为准；
                 核查器不可用 → 保守回落（保留自报，记 ``unavailable``）
=============  ================================================================

只抄形态不抄调度，结果是"每轮多花一次 LLM 调用"——成本翻倍而收益不明，所以默认档是 hybrid。

**本模块绝不抛出**：核查是旁路，失败只降级为 ``unavailable``。
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

__all__ = [
    "STRATEGY_AGENT_REPORT",
    "STRATEGY_TRANSCRIPT",
    "STRATEGY_HYBRID",
    "STRATEGIES",
    "ASSESS_OK",
    "ASSESS_OVERCLAIMED",
    "ASSESS_UNAVAILABLE",
    "ASSESS_SKIPPED",
    "Assessment",
    "assessor_strategy",
    "verify_interval",
    "assessor_max_chars",
    "should_verify",
    "assess_result",
    "summarize_assessments",
]

logger = logging.getLogger("cloudagent.diagnosis.assessor")

STRATEGY_AGENT_REPORT = "agent_report"
STRATEGY_TRANSCRIPT = "transcript"
STRATEGY_HYBRID = "hybrid"
STRATEGIES = frozenset({STRATEGY_AGENT_REPORT, STRATEGY_TRANSCRIPT, STRATEGY_HYBRID})

ASSESS_OK = "ok"
ASSESS_OVERCLAIMED = "overclaimed"
ASSESS_UNAVAILABLE = "unavailable"
ASSESS_SKIPPED = "skipped"

ENV_STRATEGY = "CLOUDAGENT_GOAL_STOP_STRATEGY"
ENV_INTERVAL = "CLOUDAGENT_ASSESSOR_VERIFY_INTERVAL"
ENV_MAX_CHARS = "CLOUDAGENT_ASSESSOR_MAX_CHARS"

DEFAULT_STRATEGY = STRATEGY_HYBRID
DEFAULT_INTERVAL = 3
DEFAULT_MAX_CHARS = 64_000

#: 视为"终态声明"的子代理状态（这两种才需要核查）
TERMINAL_STATUSES = frozenset({"success", "partial"})

_SYSTEM_PROMPT = (
    "你是独立的诊断结果审核员。你的任务只有一件：判断给定的「证据」是否真的支持"
    "「被判定为已查清（resolved）的缺口」。\n"
    "规则：\n"
    "1. 只依据给定材料判断，不要引入外部知识，不要猜测；\n"
    "2. 证据的 observation 里必须**明确出现**支持该缺口结论的观测事实，"
    "仅仅提到相关名词不算支持；\n"
    "3. 无法判断时判 overclaimed（宁可保守）；\n"
    "4. 只输出 JSON，不要解释、不要 markdown 代码块以外的内容。\n"
    '输出格式：{"verdict": "ok" | "overclaimed", '
    '"verified_gaps": ["<gap_id>", ...], "reason": "<一句话>"}'
)


@dataclass(frozen=True)
class Assessment:
    """一次核查的结论（不可变，便于直接进 meta）。"""

    status: str
    claimed_gaps: tuple[str, ...] = ()
    verified_gaps: tuple[str, ...] = ()
    reason: str = ""
    calls: int = 0
    truncated_chars: int = 0

    @property
    def is_ok(self) -> bool:
        return self.status == ASSESS_OK

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "claimed_gaps": list(self.claimed_gaps),
            "verified_gaps": list(self.verified_gaps),
            "reason": self.reason,
            "calls": self.calls,
        }


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------


def assessor_strategy() -> str:
    """核查策略；非法值回退 hybrid 并告警（不在导入时求值）。"""

    raw = os.environ.get(ENV_STRATEGY)
    if raw is None or not str(raw).strip():
        return DEFAULT_STRATEGY
    text = str(raw).strip().lower()
    if text not in STRATEGIES:
        logger.warning(
            "invalid %s=%r (must be one of %s); falling back to %s",
            ENV_STRATEGY,
            raw,
            sorted(STRATEGIES),
            DEFAULT_STRATEGY,
        )
        return DEFAULT_STRATEGY
    return text


def verify_interval() -> int:
    """抽查间隔；``0`` = 不抽查（只核查终态）。"""

    raw = os.environ.get(ENV_INTERVAL)
    if raw is None or not str(raw).strip():
        return DEFAULT_INTERVAL
    try:
        value = int(str(raw).strip())
    except ValueError:
        logger.warning("invalid %s=%r; falling back to %d", ENV_INTERVAL, raw, DEFAULT_INTERVAL)
        return DEFAULT_INTERVAL
    return max(value, 0)


def assessor_max_chars() -> int:
    raw = os.environ.get(ENV_MAX_CHARS)
    if raw is None or not str(raw).strip():
        return DEFAULT_MAX_CHARS
    try:
        value = int(str(raw).strip())
    except ValueError:
        return DEFAULT_MAX_CHARS
    return value if value > 0 else DEFAULT_MAX_CHARS


# ---------------------------------------------------------------------------
# 调度（这才是 hybrid 的关键）
# ---------------------------------------------------------------------------


def should_verify(
    *,
    strategy: str,
    result_status: str,
    attempt: int = 0,
    interval: int | None = None,
    forced: bool = False,
) -> bool:
    """本次结果要不要送核查。

    * ``agent_report``：从不；
    * ``transcript``：总是；
    * ``hybrid``：终态声明必核；非终态只在"到了抽查间隔"时核一次。

    ``forced=True`` 时**无视策略**直接核。阶段 4（T4.4）用它处理"回退过的
    缺口再次 resolved"：那条结论曾经被证据推翻过，用同一个关键词判定让它
    "再 resolved"一次等于什么都没变——**传播走确定性快路径，收敛必须走核查慢路径**。
    """

    if forced:
        return True
    if strategy == STRATEGY_AGENT_REPORT:
        return False
    if strategy == STRATEGY_TRANSCRIPT:
        return True
    if strategy != STRATEGY_HYBRID:
        return False

    if str(result_status or "").strip().lower() in TERMINAL_STATUSES:
        return True

    step = verify_interval() if interval is None else interval
    if step <= 0:
        return False
    return attempt > 0 and attempt % step == 0


# ---------------------------------------------------------------------------
# 提示构造与解析
# ---------------------------------------------------------------------------


def _tail_truncate(text: str, max_chars: int) -> tuple[str, int]:
    """保留尾部 ``max_chars``（最新证据在尾部；截掉多少必然告知）。"""

    if max_chars <= 0 or len(text) <= max_chars:
        return text, 0
    omitted = len(text) - max_chars
    return (
        f"[已省略前 {omitted} 字符，以下为末尾 {max_chars} 字符]\n" + text[-max_chars:],
        omitted,
    )


def _render_gaps(gaps: Sequence[Any]) -> str:
    lines: list[str] = []
    for gap in gaps:
        refs = ", ".join(str(r) for r in (getattr(gap, "evidence_refs", None) or []))
        lines.append(
            f"- gap_id={getattr(gap, 'gap_id', '')} | 命题：{getattr(gap, 'statement', '')} "
            f"| 关联证据：{refs or '（无）'}"
        )
    return "\n".join(lines) if lines else "（无）"


def _render_evidence(result: Any) -> str:
    lines: list[str] = []
    for ev in getattr(result, "evidence", None) or []:
        lines.append(
            f"- evidence_id={getattr(ev, 'evidence_id', '')} "
            f"| 来源={getattr(ev, 'source_type', '')}:{getattr(ev, 'source_ref', '')} "
            f"| 观测：{getattr(ev, 'observation', '')}"
        )
    return "\n".join(lines) if lines else "（无）"


def build_messages(task: Any, result: Any, gaps: Sequence[Any], *, max_chars: int) -> list[dict]:
    """构造核查用的消息（单轮，无工具）。"""

    body = "\n".join(
        [
            f"## 调查目标\n{getattr(task, 'objective', '')}",
            f"## 子代理自报\n状态：{getattr(result, 'status', '')}\n"
            f"摘要：{getattr(result, 'summary', '')}",
            f"## 子代理给出的证据\n{_render_evidence(result)}",
            f"## 被判定为已查清（resolved）的缺口\n{_render_gaps(gaps)}",
            "## 请判断\n上列每条缺口，是否都被「子代理给出的证据」的观测事实真正支持？"
            "只输出 JSON。",
        ]
    )
    truncated, omitted = _tail_truncate(body, max_chars)
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": truncated},
    ]


_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def parse_assessment(text: str) -> dict[str, Any] | None:
    """从模型输出里取出判定 JSON；取不到返回 ``None``（**不猜**）。"""

    raw = str(text or "").strip()
    if not raw:
        return None
    candidates: list[str] = [m.group(1) for m in _JSON_BLOCK_RE.finditer(raw)]
    candidates.append(raw)
    start = raw.find("{")
    end = raw.rfind("}")
    if 0 <= start < end:
        candidates.append(raw[start : end + 1])

    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except (TypeError, ValueError):
            continue
        if isinstance(data, dict) and "verdict" in data:
            return data
    return None


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def _call_provider(provider: Any, messages: list[dict]) -> Any:
    """单轮、无工具、``temperature=0`` 的调用。

    ``temperature`` 走 provider 的 ``**kwargs``（OpenAI 适配器白名单里有它，
    Anthropic/Gemini 也接受）；个别端点（Kimi）会主动丢弃它——那是端点自身的策略，
    不是我们的 bug，所以**失败不重试、不降级成别的参数**，只是退回不带 temperature 再试一次。
    """

    try:
        return provider.chat(messages=messages, temperature=0.0)
    except TypeError:
        # 某些 provider 的 chat 签名不接受 temperature（不该有，但兜一下）
        return provider.chat(messages=messages)


def assess_result(
    *,
    task: Any,
    result: Any,
    gaps: Iterable[Any] = (),
    provider: Any = None,
) -> Assessment:
    """对一次委派结果做独立核查。**绝不抛出**。

    ``provider`` 由调用方从 ``ToolContext._active_provider`` 取；取不到就返回
    ``unavailable``——保守回落（对应 hybrid 的"核查不可用则信任自报"），
    并且在 meta 里如实标记"没核过"，而不是假装核过了。
    """

    gap_list = list(gaps or ())
    claimed = tuple(str(getattr(gap, "gap_id", "")) for gap in gap_list)

    if provider is None:
        return Assessment(
            status=ASSESS_UNAVAILABLE,
            claimed_gaps=claimed,
            reason="no provider available",
        )

    max_chars = assessor_max_chars()
    messages = build_messages(task, result, gap_list, max_chars=max_chars)
    omitted = 0
    if max_chars > 0:
        body_len = len(messages[1]["content"])
        omitted = max(0, body_len - max_chars) if body_len > max_chars else 0

    try:
        response = _call_provider(provider, messages)
    except Exception as exc:  # noqa: BLE001 — 核查失败不影响主链路
        logger.info("assessor call failed: %s", exc)
        return Assessment(
            status=ASSESS_UNAVAILABLE,
            claimed_gaps=claimed,
            reason=f"call failed: {type(exc).__name__}",
            calls=1,
        )

    text = str(getattr(response, "content", "") or "")
    data = parse_assessment(text)
    if data is None:
        return Assessment(
            status=ASSESS_UNAVAILABLE,
            claimed_gaps=claimed,
            reason="unparseable response",
            calls=1,
            truncated_chars=omitted,
        )

    verdict = str(data.get("verdict") or "").strip().lower()
    verified_raw = data.get("verified_gaps") or []
    verified = tuple(str(item) for item in verified_raw if str(item).strip())
    reason = str(data.get("reason") or "")[:200]

    if verdict == "ok":
        # 模型若只给 verdict 不给清单，按"全部通过"处理（避免把已核过的又当没核过）
        return Assessment(
            status=ASSESS_OK,
            claimed_gaps=claimed,
            verified_gaps=verified or claimed,
            reason=reason,
            calls=1,
            truncated_chars=omitted,
        )

    return Assessment(
        status=ASSESS_OVERCLAIMED,
        claimed_gaps=claimed,
        verified_gaps=verified,
        reason=reason or f"verdict={verdict or 'invalid'}",
        calls=1,
        truncated_chars=omitted,
    )


def summarize_assessments(items: Iterable[Assessment]) -> dict[str, Any]:
    """聚合：各状态计数 + 分歧率（关键词判 resolved 但核查未通过的占比）。"""

    counts = {ASSESS_OK: 0, ASSESS_OVERCLAIMED: 0, ASSESS_UNAVAILABLE: 0, ASSESS_SKIPPED: 0}
    claimed = 0
    verified = 0
    calls = 0
    for item in items or ():
        counts[item.status] = counts.get(item.status, 0) + 1
        claimed += len(item.claimed_gaps)
        verified += len(item.verified_gaps)
        calls += item.calls
    judged = claimed
    return {
        "assessments": sum(counts.values()),
        "by_status": counts,
        "claimed_gaps": claimed,
        "verified_gaps": verified,
        # 分歧率：被判 resolved 但没通过核查的比例（分母是"被核查过的缺口数"）
        "disagreement_rate": (
            round((judged - verified) / judged, 4) if judged else None
        ),
        "model_calls": calls,
    }
