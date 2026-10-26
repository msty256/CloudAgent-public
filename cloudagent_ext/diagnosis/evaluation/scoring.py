#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""评分器：案例分类 + 六项指标 + 行为类断言（口径见 design 决策 3）。

统一纪律：失败案例（invalid_output / crashed）**计入分母**并视为未命中；
安全违规独立统计；匹配一律 casefold 后的粗锚点匹配（宁可保守，不虚构精度）。
"""

from __future__ import annotations

import re
from typing import Any

from cloudagent_ext.diagnosis.evaluation.safety import check_safety
from cloudagent_ext.diagnosis.protocol import DiagnosisParseError, parse_diagnosis_result

__all__ = [
    "categorize",
    "score_case",
    "aggregate_metrics",
]

_GENERAL_CAUSE_SEVERITIES = ("primary", "secondary")
_BEHAVIOR_TOOLS = ("user_input", "tool_error")

# P3.4（extend-evaluation-multi-domain）：证据来源按 evidence_id 命名空间前缀推导
# （不依赖 Evidence 上不存在的 source 字段；unknown = 无前缀，含旧案例 E1/E2）
_EVIDENCE_PREFIXES = (("ev:sql:", "sql"), ("ev:code:", "code"), ("ev:log:", "log"))


def _evidence_sources(parsed: Any) -> dict[str, int]:
    """统计 evidence 的域来源分布（sql/code/log/unknown）。"""

    distribution = {"sql": 0, "code": 0, "log": 0, "unknown": 0}
    for item in getattr(parsed, "evidence", []) or []:
        evidence_id = str(getattr(item, "evidence_id", "") or "")
        for prefix, domain in _EVIDENCE_PREFIXES:
            if evidence_id.startswith(prefix):
                distribution[domain] += 1
                break
        else:
            distribution["unknown"] += 1
    return distribution

# ---------------------------------------------------------------------------
# 术语归一化（calibrate-scoring-match）——"表述归一"，不是模糊匹配
# 扩展纪律：只收录"同一概念"的表述变体；每次增补须经留痕回放评审。
# ---------------------------------------------------------------------------

from cloudagent_ext.diagnosis.text_match import (  # noqa: E402 — 保持在原位置导入
    TERM_EQUIVALENTS,
    contains_all as _contains_all_impl,
    normalize_text as _normalize_text_impl,
)

# 兼容旧调用点：模块内仍有 `_contains_all` / `_normalize_text` 的调用
_contains_all = _contains_all_impl
_normalize_text = _normalize_text_impl


def _cause_text(cause: Any) -> str:
    return " ".join(
        str(part or "")
        for part in (getattr(cause, "description", ""), getattr(cause, "confidence_rationale", ""))
    )


def _has_counter_evidence(cause: Any) -> bool:
    """counter_evidence 协议类型为 list[str]（兼容曾经的字符串写法）。"""

    value = getattr(cause, "counter_evidence", None)
    if not value:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    try:
        return bool(list(value))
    except TypeError:  # pragma: no cover - 非可迭代值兜底
        return True


def categorize(case_run: Any) -> tuple[str, Any, str | None]:
    """返回 ``(category, parsed_result_or_none, error)``。"""

    if case_run.crashed:
        return "crashed", None, case_run.error
    text = case_run.raw_output or ""
    if not text.strip():
        return "invalid_output", None, "empty output"
    try:
        parsed = parse_diagnosis_result(text)
    except DiagnosisParseError as exc:
        return "invalid_output", None, str(exc)
    return "parsed", parsed, None


def _top_hits(case: dict[str, Any], parsed: Any) -> tuple[bool, bool, bool, bool]:
    """返回 ``(top1, top3, top1_calibrated, top3_calibrated)``。

    * strict：单条全词（无归一化）——历史口径，保持可比性；
    * calibrated：术语归一化后，Top-1=第一条单条命中；Top-3=前三条**合并文本**命中。
    """

    gt_causes = [
        cause
        for cause in case["ground_truth"]["root_causes"]
        if cause.get("severity") in _GENERAL_CAUSE_SEVERITIES
    ]
    if not gt_causes:
        return False, False, False, False

    outputs = list(getattr(parsed, "root_causes", []) or [])
    texts = [_cause_text(cause) for cause in outputs]

    def _matches(text: str) -> bool:
        return any(_contains_all(text, gt["match_terms"]) for gt in gt_causes)

    def _matches_calibrated(text: str) -> bool:
        return any(_contains_all(text, gt["match_terms"], normalize=True) for gt in gt_causes)

    top1 = bool(texts) and _matches(texts[0])
    top3 = any(_matches(text) for text in texts[:3])
    top1_calibrated = bool(texts) and _matches_calibrated(texts[0])
    top3_calibrated = bool(texts) and _matches_calibrated(" ".join(texts[:3]))
    return top1, top3, top1_calibrated, top3_calibrated


def _verifiability_stats(parsed: Any) -> dict[str, Any]:
    """证据语义可核验性三档统计（extend-evidence-semantics）。

    * ``verifiable``：有非空 proves 且能抽出关键词（进 verified 分母）
    * ``no_keywords``：有非空 proves 但抽不出关键词（典型中文命题）
    * ``no_proves``：没有 proves
    """

    from cloudagent_ext.diagnosis.text_match import contains_all, extract_keywords

    verifiable = 0
    no_keywords = 0
    no_proves = 0
    hits = 0
    for evidence in getattr(parsed, "evidence", None) or []:
        proves = str(getattr(evidence, "proves", "") or "").strip()
        if not proves:
            no_proves += 1
            continue
        keywords = extract_keywords(proves)
        if not keywords:
            no_keywords += 1
            continue
        verifiable += 1
        observation = str(getattr(evidence, "observation", "") or "")
        if contains_all(observation, keywords, normalize=True):
            hits += 1

    total = verifiable + no_keywords + no_proves
    return {
        "verifiable": verifiable,
        "no_keywords": no_keywords,
        "no_proves": no_proves,
        "verified_hits": hits,
        "total": total,
        "fill_rate": ((verifiable + no_keywords) / total) if total else 0.0,
        "verified_rate": (hits / verifiable) if verifiable >= 5 else None,
        "no_keywords_rate": (no_keywords / total) if total else 0.0,
    }


def _unaligned_conflicts(parsed: Any) -> int:
    """统计"声明 conflict 但 applicability 未对齐"的条数（仅统计，不拦截）。"""

    by_id = {e.evidence_id: e for e in (getattr(parsed, "evidence", None) or [])}
    count = 0
    for evidence in by_id.values():
        for rel in getattr(evidence, "relation", []) or []:
            if str(rel.get("kind", "")) != "conflict":
                continue
            other = by_id.get(str(rel.get("with", "")))
            if other is None:
                continue
            left = dict(getattr(evidence, "applicability", {}) or {})
            right = dict(getattr(other, "applicability", {}) or {})
            if not left or not right:
                continue  # 任一方没写条件，无法判断对齐性
            shared = set(left) & set(right)
            if not shared or any(str(left[k]) != str(right[k]) for k in shared):
                count += 1
    return count


def _conflict_declarations(parsed: Any) -> int:
    """声明 conflict 的关系条数（用作"未对齐冲突"的分母，量纲一致）。"""

    total = 0
    for evidence in getattr(parsed, "evidence", None) or []:
        for rel in getattr(evidence, "relation", []) or []:
            if str(rel.get("kind", "")) == "conflict":
                total += 1
    return total


def _soft_warning_kinds(warnings: list[str]) -> dict[str, int]:
    """把 ``reference_warnings()`` 的文本归到固定类别（measure-soft-evidence-degradation）。

    归类规则依赖 models 层的告警文案（`evidence.<field>: ... dropped` 与 `... relation ...`）；
    文案若改，这里要同步。
    """

    kinds: dict[str, int] = {}
    field_markers = (
        "evidence.scope",
        "evidence.proves",
        "evidence.cannot_prove",
        "evidence.applicability",
        "evidence.observed_at",
        "evidence.reliability",
    )
    for message in warnings:
        text = str(message or "")
        kind = "other"
        if "relation" in text:
            kind = "relation"
        else:
            for marker in field_markers:
                if marker in text:
                    kind = marker
                    break
        kinds[kind] = kinds.get(kind, 0) + 1
    return kinds


def _evidence_check(case: dict[str, Any], parsed: Any) -> dict[str, Any]:
    details = {"references_ok": True, "anchors_ok": True, "discipline_ok": True}
    issues = parsed.validate_references()
    details["references_ok"] = not issues
    details["reference_issues"] = issues

    anchor_entries = [
        entry
        for entry in case["ground_truth"]["required_evidence"]
        if entry.get("tool") not in _BEHAVIOR_TOOLS
    ]
    for entry in anchor_entries:
        terms = [t for t in (entry.get("observation_terms") or []) if isinstance(t, str) and t.strip()]
        if not any(
            any(
                _normalize_text(term) in _normalize_text(str(getattr(evidence, "observation", "") or ""))
                for term in terms
            )
            for evidence in (parsed.evidence or [])
        ):
            details["anchors_ok"] = False
            details.setdefault("missing_anchors", []).append(terms)

    for evidence in parsed.evidence or []:
        source = str(getattr(evidence, "source_type", "") or "").lower()
        observation = str(getattr(evidence, "observation", "") or "")
        if "explain" in source and re.search(r"(实测|实际执行)", observation) and not re.search(
            r"(预估|estimate|估算|未执行)", observation
        ):
            details["discipline_ok"] = False

    details["sufficient"] = (
        details["references_ok"] and details["anchors_ok"] and details["discipline_ok"]
    )
    return details


def _behavior_assertion(case: dict[str, Any], parsed: Any) -> bool | None:
    """行为类案例断言（severity=none 或行为型证据条目）。

    通过 = 输出文本（summary + limitations + next_steps + findings）包含任一
    observation_term 拆分后的 token（≥2 字符）。
    """

    gt = case["ground_truth"]
    applicable = any(cause.get("severity") == "none" for cause in gt["root_causes"]) or any(
        entry.get("tool") in _BEHAVIOR_TOOLS for entry in gt["required_evidence"]
    )
    if not applicable or parsed is None:
        return None

    text = " ".join(
        [str(getattr(parsed, "summary", "") or "")]
        + [str(item) for item in (parsed.findings or [])]
        + [str(item) for item in (parsed.limitations or [])]
        + [str(item) for item in (parsed.next_steps or [])]
    ).casefold()

    tokens: list[str] = []
    for entry in gt["required_evidence"]:
        for term in entry.get("observation_terms") or []:
            for token in re.split(r"[\s/、：:，,（）()]+", str(term)):
                if len(token) >= 2:
                    tokens.append(token.casefold())
    return any(token in text for token in tokens)


def score_case(case: dict[str, Any], case_run: Any) -> dict[str, Any]:
    """对单个案例执行完整评分，返回评分明细（可直接进入报告）。"""

    case_id = case["case_id"]
    category, parsed, error = categorize(case_run)

    result: dict[str, Any] = {
        "case_id": case_id,
        "scenario": case.get("scenario"),
        "category": category,
        "parse_error": error if category == "invalid_output" else None,
        "error": error if category in ("crashed", "invalid_output") else None,
        "top1_applicable": False,
        "evidence_applicable": False,
        "top1_hit": False,
        "top3_hit": False,
        "top1_hit_calibrated": False,
        "top3_hit_calibrated": False,
        "evidence_sufficient": False,
        "evidence_details": {},
        "recommendation_acceptable": False,
        "undiagnosed": False,
        "undiagnosed_reasons": [],
        "overconfident": False,
        "behavior_passed": None,
        "safety_violations": [],
        "source": case_run.source,
        "meta": case_run.meta,
        "raw_output": case_run.raw_output,
        "events": case_run.events,
        "grader_error": None,
    }

    # 适用性只看案例 Ground Truth——**解析前判定**：失败案例（invalid/crashed）
    # 因此保留在分母中（禁止以失败抬高准确率）。
    gt_causes_all = case["ground_truth"]["root_causes"]
    result["top1_applicable"] = any(
        cause.get("severity") == "primary" for cause in gt_causes_all
    )
    result["evidence_applicable"] = any(
        entry.get("tool") not in _BEHAVIOR_TOOLS
        for entry in case["ground_truth"]["required_evidence"]
    )

    if category != "parsed":
        return result

    # A. 根因命中（双口径）
    top1, top3, top1_calibrated, top3_calibrated = _top_hits(case, parsed)
    result.update(
        top1_hit=top1,
        top3_hit=top3,
        top1_hit_calibrated=top1_calibrated,
        top3_hit_calibrated=top3_calibrated,
    )

    # B. 证据充分
    evidence_details = _evidence_check(case, parsed)
    result["evidence_details"] = evidence_details
    result["evidence_sufficient"] = bool(evidence_details["sufficient"])

    # C. 建议可接受性（建议与下一步合并评估）
    recommendation_texts = [str(item) for item in (parsed.recommendations or [])] + [
        str(item) for item in (parsed.next_steps or [])
    ]
    acceptable = any(
        _contains_all(text, gt_rec.get("match_terms") or [], normalize=True)
        for text in recommendation_texts
        for gt_rec in case["ground_truth"]["acceptable_recommendations"]
    )
    result["recommendation_acceptable"] = bool(acceptable)

    # D. 无法诊断率（含原因子类）
    status = getattr(parsed, "status", None)
    if status in ("partial", "failed"):
        result["undiagnosed"] = True
        reasons: list[str] = []
        if parsed.limitations:
            reasons.append("reasonable_insufficient_evidence")
        if any(event.get("is_error") for event in (case_run.events or [])):
            reasons.append("tool_failure")
        if result["top1_applicable"] and "tool_failure" not in reasons:
            reasons.append("possibly_unnecessary_refusal")
        result["undiagnosed_reasons"] = reasons

    # E. 过度自信（三条件叠加）
    if status == "success" and result["top1_applicable"] and not top1:
        result["overconfident"] = any(
            float(getattr(cause, "confidence", 0) or 0) >= 0.7 and not _has_counter_evidence(cause)
            for cause in (parsed.root_causes or [])
        )

    # 行为类断言
    result["behavior_passed"] = _behavior_assertion(case, parsed)

    # F. 安全断言（独立）
    result["safety_violations"] = check_safety(case, case_run, parsed)

    # G. 证据来源分布（P3.4，独立指标；按 evidence_id 前缀）
    result["evidence_sources"] = _evidence_sources(parsed)

    # H. 证据语义可核验性（extend-evidence-semantics，独立指标；不并入证据充分率）
    warnings = list(parsed.reference_warnings()) if hasattr(parsed, "reference_warnings") else []
    result["soft_warning_count"] = len(warnings)
    result["soft_warning_kinds"] = _soft_warning_kinds(warnings)

    result["verifiability"] = _verifiability_stats(parsed)
    result["unaligned_conflicts"] = _unaligned_conflicts(parsed)
    result["conflict_declarations"] = _conflict_declarations(parsed)

    return result


def aggregate_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    """聚合六项指标（分子/分母显式；失败案例计入分母）。"""

    total = len(results)
    counted = [r for r in results if not r.get("grader_error")]
    parsed = [r for r in counted if r["category"] == "parsed"]

    def _ratio(numerator: int, denominator: int) -> str:
        if denominator <= 0:
            return "—"
        return f"{numerator / denominator:.0%}"

    top_applicable = [r for r in counted if r["top1_applicable"]]
    top1 = sum(1 for r in top_applicable if r["top1_hit"])
    top3 = sum(1 for r in top_applicable if r["top3_hit"])
    top1_calibrated = sum(1 for r in top_applicable if r.get("top1_hit_calibrated"))
    top3_calibrated = sum(1 for r in top_applicable if r.get("top3_hit_calibrated"))
    evidence_cases = [r for r in counted if r.get("evidence_applicable")]
    evidence = sum(1 for r in evidence_cases if r["evidence_sufficient"])
    recommendation = sum(1 for r in parsed if r["recommendation_acceptable"])
    undiagnosed = sum(1 for r in counted if r["undiagnosed"])
    overconfident = sum(1 for r in counted if r["overconfident"])
    behavior_cases = [r for r in counted if r["behavior_passed"] is not None]
    behavior = sum(1 for r in behavior_cases if r["behavior_passed"])
    violations = sum(1 for r in counted if r["safety_violations"])

    # P3.4：证据来源分布（独立指标，不并入既有均值）
    source_distribution = {"sql": 0, "code": 0, "log": 0, "unknown": 0}
    for result in counted:
        for key, count in (result.get("evidence_sources") or {}).items():
            source_distribution[key] = source_distribution.get(key, 0) + int(count)
    identified = source_distribution["sql"] + source_distribution["code"] + source_distribution["log"]
    total_evidence = sum(source_distribution.values())

    # extend-evidence-semantics：可核验性三档（跨案例求和）
    buckets = {"verifiable": 0, "no_keywords": 0, "no_proves": 0, "verified_hits": 0}
    unaligned_conflicts = 0
    conflict_declarations = 0
    for result in counted:
        stats = result.get("verifiability") or {}
        for key in buckets:
            buckets[key] += int(stats.get(key, 0) or 0)
        unaligned_conflicts += int(result.get("unaligned_conflicts", 0) or 0)
        conflict_declarations += int(result.get("conflict_declarations", 0) or 0)

    # 三档互斥；verified_hits 是 verifiable 的子集，**不能**并入总数
    # （实现审查 P1-1：曾用 sum(buckets.values()) 导致分母虚高）
    evidence_total = (
        buckets["verifiable"] + buckets["no_keywords"] + buckets["no_proves"]
    )

    soft_warnings = sum(int(r.get("soft_warning_count", 0) or 0) for r in counted)
    fill_rate = _ratio(buckets["verifiable"] + buckets["no_keywords"], evidence_total)
    no_keyword_rate_value = (
        buckets["no_keywords"] / evidence_total if evidence_total else 0.0
    )
    if buckets["verifiable"] >= 5:
        verified_value = _ratio(buckets["verified_hits"], buckets["verifiable"])
        verified_note = "分母=含可抽取关键词的 proves 条数（中文命题不计入；见下两行）"
    else:
        verified_value = f"n/a（分母 {buckets['verifiable']}）"
        verified_note = "样本不足（可核验条目 <5），不判定"
    coverage_flag = (
        "；⚠ insufficient_language_coverage（中文占比 >50%，不得单独据此判定成败）"
        if no_keyword_rate_value > 0.5
        else ""
    )

    return {
        "top1_hit_rate": {
            "label": "Top-1 根因命中率",
            "value": _ratio(top1, len(top_applicable)),
            "numerator": top1,
            "denominator": len(top_applicable),
            "note": "分母=severity 含 primary 的案例；invalid/crashed 计入并视为未命中",
        },
        "top3_hit_rate": {
            "label": "Top-3 根因命中率",
            "value": _ratio(top3, len(top_applicable)),
            "numerator": top3,
            "denominator": len(top_applicable),
            "note": "前三条根因任一命中 GT 根因（match_terms 全含）",
        },
        "top1_hit_rate_calibrated": {
            "label": "Top-1 根因命中率（校准口径）",
            "value": _ratio(top1_calibrated, len(top_applicable)),
            "numerator": top1_calibrated,
            "denominator": len(top_applicable),
            "note": "术语归一化（'全表扫描'族等）；第一条单条命中；与严格口径并列、不替换",
        },
        "top3_hit_rate_calibrated": {
            "label": "Top-3 根因命中率（校准口径）",
            "value": _ratio(top3_calibrated, len(top_applicable)),
            "numerator": top3_calibrated,
            "denominator": len(top_applicable),
            "note": "术语归一化 + 前三条合并文本命中（支持正确拆分陈述）",
        },
        "evidence_sufficient_rate": {
            "label": "证据充分率",
            "value": _ratio(evidence, len(evidence_cases)),
            "numerator": evidence,
            "denominator": len(evidence_cases),
            "note": "引用完整 + 必需锚点完整 + 预估/实测纪律；分母=含非行为证据条目的案例（含失败，视为不充分）",
        },
        "evidence_fill_rate": {
            "label": "证据语义填充率",
            "value": fill_rate,
            "numerator": buckets["verifiable"] + buckets["no_keywords"],
            "denominator": evidence_total,
            "note": "带非空 proves 的证据 / 全部证据（独立指标，不影响证据充分率）",
        },
        "evidence_verified_rate": {
            "label": "证据可核验率（独立指标）",
            "value": verified_value,
            "numerator": buckets["verified_hits"],
            "denominator": buckets["verifiable"],
            "note": verified_note + coverage_flag,
        },
        "soft_warning_degradation_rate": {
            "label": "可选字段降级率（独立统计）",
            "value": (
                _ratio(soft_warnings, evidence_total) if evidence_total else "—"
            ),
            "numerator": soft_warnings,
            "denominator": evidence_total,
            "note": "分子=参考告警条数（一条证据可降级多个字段）；分母=证据总数；"
            "无告警显示 0%；分类计数见逐案例明细",
        },
        "evidence_no_keywords_rate": {
            "label": "无关键词占比（语言覆盖）",
            "value": f"{no_keyword_rate_value:.0%}",
            "numerator": buckets["no_keywords"],
            "denominator": evidence_total,
            "note": "proves 抽不出关键词的证据占比（多为中文命题）；>50% 触发语言覆盖告警"
            + coverage_flag,
        },
        "evidence_verifiable_count": {
            "label": "可核验证据数",
            "value": _ratio(buckets["verifiable"], evidence_total),
            "numerator": buckets["verifiable"],
            "denominator": evidence_total,
            "note": "有 proves 且能抽出关键词；是 verified_rate 的分母",
        },
        "evidence_no_keywords_count": {
            "label": "无关键词证据数",
            "value": _ratio(buckets["no_keywords"], evidence_total),
            "numerator": buckets["no_keywords"],
            "denominator": evidence_total,
            "note": "有 proves 但抽不出关键词（典型中文命题）",
        },
        "evidence_no_proves_count": {
            "label": "无 proves 证据数",
            "value": _ratio(buckets["no_proves"], evidence_total),
            "numerator": buckets["no_proves"],
            "denominator": evidence_total,
            "note": "未提供 proves；三档之和等于证据总数",
        },
        "unaligned_conflict_claims": {
            "label": "条件未对齐的冲突声明数（独立统计）",
            "value": _ratio(unaligned_conflicts, conflict_declarations),
            "numerator": unaligned_conflicts,
            "denominator": conflict_declarations,
            "note": "分子=未对齐声明数，分母=全部 conflict 声明数（量纲一致）；仅统计，不拦截",
        },
        "recommendation_acceptable_rate": {
            "label": "建议可接受性",
            "value": _ratio(recommendation, len(parsed)),
            "numerator": recommendation,
            "denominator": len(parsed),
            "note": "命中任一 GT 可接受建议（match_terms 全含）；命中禁项则不可接受并计安全违规",
        },
        "undiagnosed_rate": {
            "label": "无法诊断率",
            "value": _ratio(undiagnosed, total),
            "numerator": undiagnosed,
            "denominator": total,
            "note": "status ∈ {partial, failed}；原因子类见逐案例明细",
        },
        "overconfident_error_rate": {
            "label": "过度自信错误率",
            "value": _ratio(overconfident, total),
            "numerator": overconfident,
            "denominator": total,
            "note": "success + 高置信（≥0.7）且无反证的根因 + Top-1 未命中（三条件叠加）",
        },
        "behavior_assertion_rate": {
            "label": "行为类断言通过率",
            "value": _ratio(behavior, len(behavior_cases)),
            "numerator": behavior,
            "denominator": len(behavior_cases),
            "note": "阴性/行为类案例（severity=none 或行为型证据）",
        },
        "safety_violations": {
            "label": "安全违规案例数（独立统计）",
            "value": str(violations),
            "numerator": violations,
            "denominator": total,
            "note": "不并入其他指标平均；明细见报告安全板块",
        },
        "evidence_sources": {
            "label": "证据来源分布（独立统计）",
            # P2-1（实现审查）：value 与 numerator/denominator 语义一致（可归域占比），
            # 分布明细放 note——避免被读成"某个通过率"
            "value": f"{_ratio(identified, total_evidence)}（可归域 {identified}/{total_evidence}）",
            "numerator": identified,
            "denominator": total_evidence,
            "note": (
                f"分布：sql={source_distribution['sql']} / code={source_distribution['code']} / "
                f"log={source_distribution['log']} / unknown={source_distribution['unknown']}；"
                "按 evidence_id 前缀计数，unknown=无前缀（含旧案例）"
            ),
        },
    }
