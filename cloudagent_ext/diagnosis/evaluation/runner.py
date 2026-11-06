#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""批量评测 Runner 与 CLI 入口。

用法::

    python -m cloudagent_ext.diagnosis.evaluation.runner --mode offline
    python -m cloudagent_ext.diagnosis.evaluation.runner --mode live --cases sql-001,sql-003

* 案例固定按 ``case_id`` 排序执行；单案例失败隔离并如实记录；
* 重试默认 0（避免重试放大模型费用），仅覆盖执行异常；
* 报告默认写 ``eval/runs/<run_id>/``（已被 .gitignore 忽略）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# 评测 runner 作为命令行工具运行，默认不配 handler；这里给个模块级 logger，
# 避免 `logger.debug(...)` 在异常分支真正触发时抛 NameError（ruff F821 曾报出）。
logger = logging.getLogger(__name__)

from cloudagent_ext.diagnosis.case_library import load_cases
from cloudagent_ext.diagnosis.evaluation.cost import sum_usage_summaries
from cloudagent_ext.diagnosis.evaluation.executors import (
    CaseRun,
    EvaluationExecutorError,
    LiveExecutor,
    OfflineExecutor,
    build_conversation,
)
from cloudagent_ext.diagnosis.evaluation.report import (
    build_run_id,
    redact_sensitive,
    write_report,
)
from cloudagent_ext.diagnosis.evaluation.scoring import aggregate_metrics, score_case

__all__ = ["EvaluationError", "EvaluationConfigError", "run_evaluation", "main"]

# 报告与 run_id 以北京时间展示（中国区用户；ISO 8601 带 +08:00 偏移保留时区信息）。
# 内部计时仍使用 UTC，保证 elapsed_sec 计算正确。
_BEIJING_TZ = timezone(timedelta(hours=8))


class EvaluationError(Exception):
    """评测输入/用法错误。"""


class EvaluationConfigError(EvaluationError):
    """评测配置错误（如 live 模式 provider 不可用）。"""


def _cases_hash(cases: list[dict[str, Any]]) -> str:
    canonical = json.dumps(cases, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _execute_cases(
    cases: list[dict[str, Any]], executor: Any, retries: int
) -> list[dict[str, Any]]:
    """按案例顺序执行一轮；单案例异常隔离。"""

    results: list[dict[str, Any]] = []
    for case in cases:
        case_run: CaseRun | None = None
        attempts = 1 + max(int(retries), 0)
        for attempt in range(attempts):
            try:
                case_run = executor.run_case(case)
            except Exception as exc:  # noqa: BLE001 - executor 未捕获的异常按执行失败记录
                case_run = CaseRun(
                    case_id=case["case_id"],
                    source="unknown",
                    raw_output="",
                    error=f"{type(exc).__name__}: {redact_sensitive(str(exc))}",
                )
            if not case_run.crashed:
                break
        assert case_run is not None

        try:
            scored = score_case(case, case_run)
            # score_case 的返回契约里没有这个键（它只管评分），在人读层补上。
            scored.setdefault("main_answer", getattr(case_run, "main_answer", ""))
        except Exception as exc:  # noqa: BLE001 - 评分器异常单列，绝不静默
            scored = {
                "case_id": case["case_id"],
                "scenario": case.get("scenario"),
                "category": "grader_error",
                "grader_error": f"{type(exc).__name__}: {redact_sensitive(str(exc))}",
                "top1_applicable": False,
                "top1_hit": False,
                "top3_hit": False,
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
                # P2：main 派发时主 Agent 的原始回答（评分用 raw_output，人读用这个）
                "main_answer": getattr(case_run, "main_answer", ""),
                "events": case_run.events,
                "parse_error": None,
                "error": case_run.error,
            }
        if case.get("expects_open_gap"):
            injected = int((case_run.meta or {}).get("injected_dispatches", 0) or 0)
            if injected == 0:
                scored["treatment_not_applied"] = True
        scored["calls"] = list(case_run.calls)
        scored["conversation"] = build_conversation(case_run.calls, case_run.events)
        results.append(scored)
    return results


#: 基线臂：**这次改造引入的机制全部关掉**，只保留原有的缺口注入。
#:
#: 注意 ``gaps-on`` 不等于 ``baseline``：前者是"什么都不改"即生产默认
#: （新机制全开），后者是"新机制全关"。名字相近、语义相反，别混。
_BASELINE_ENV: dict[str, str] = {
    "CLOUDAGENT_GAP_INJECTION": "on",
    "CLOUDAGENT_DOMAIN_GATE": "off",
    "CLOUDAGENT_GOAL_STOP_STRATEGY": "agent_report",
    "CLOUDAGENT_EVIDENCE_INVALIDATION": "off",
    "CLOUDAGENT_CONTEXT_REDUCE": "off",
}

#: 臂 = 一组环境变量。`variant` 只是"预设组合"的语法糖。
#:
#: 除 ``arm:inval`` 外都是**严格单变量**（相对 baseline 只改一个开关）。
#: ``arm:inval`` 必须同时开 ``hybrid``：失效传播要求"回退后再次 resolved 须过核查"，
#: 而 ``agent_report`` 档下核查根本不跑——单开 invalidation 会得到一个"永远不收敛"的臂。
_ARM_ENV_PRESETS: dict[str, dict[str, str]] = {
    "gaps-on": {},  # 兼容旧名：不改任何开关（= 生产默认，新机制全开）
    "gaps-off": {"CLOUDAGENT_GAP_INJECTION": "off"},
    "baseline": dict(_BASELINE_ENV),
    "arm:domain": {**_BASELINE_ENV, "CLOUDAGENT_DOMAIN_GATE": "same_target"},
    "arm:state": {**_BASELINE_ENV, "CLOUDAGENT_GOAL_STOP_STRATEGY": "hybrid"},
    "arm:inval": {
        **_BASELINE_ENV,
        "CLOUDAGENT_GOAL_STOP_STRATEGY": "hybrid",
        "CLOUDAGENT_EVIDENCE_INVALIDATION": "on",
    },
    "arm:reduce": {**_BASELINE_ENV, "CLOUDAGENT_CONTEXT_REDUCE": "on"},
    # 知识库（RAG）两臂对照：--variant kb-on / kb-off
    # 子 Agent 定义不变，只在装配阶段决定是否把 search_knowledge 放进工具表，
    # 所以这是**严格单变量**：唯一差异就是"能不能查历史档案"。
    "kb-on": {**_BASELINE_ENV, "CLOUDAGENT_KB_ENABLED": "on"},
    "kb-off": {**_BASELINE_ENV, "CLOUDAGENT_KB_ENABLED": "off"},
}


def _gap_injection_effective(mode: str, dispatch_mode: str, variant: str) -> bool:
    """本次运行是否真的走在"缺口注入生效"的链路上。

    三个条件缺一不可：

    * ``mode == "live"``——offline 回放根本不跑模型，谈不上注入生效；
    * ``dispatch_mode == "main"``——``direct`` 装配时 ``load_agent_tools=False``，
      registry 里没有 Agent 工具，``_agent_call``（注入点）不会被调用；
    * ``variant == "gaps-on"``——注入了才叫生效。
    """

    return bool(mode == "live" and dispatch_mode == "main" and variant == "gaps-on")


def _round_totals(results: list[dict[str, Any]]) -> dict[str, Any]:
    """单轮的实验量（跨案例求和；tool_calls 另给跨案例中位数）。"""

    tool_calls = [
        int((result.get("meta") or {}).get("tool_calls", 0) or 0) for result in results
    ]
    totals: dict[str, Any] = {
        "cases": len(results),
        "tool_calls_total": sum(tool_calls),
        "model_calls_total": sum(
            int((r.get("meta") or {}).get("model_calls", 0) or 0) for r in results
        ),
        "elapsed_total": round(
            sum(float((r.get("meta") or {}).get("elapsed_sec", 0) or 0) for r in results), 2
        ),
        "sub_tool_calls": sum(
            int((r.get("meta") or {}).get("sub_tool_calls", 0) or 0) for r in results
        ),
        "main_tool_calls": sum(
            int((r.get("meta") or {}).get("main_tool_calls", 0) or 0) for r in results
        ),
        "delegations": sum(
            int((r.get("meta") or {}).get("delegations", 0) or 0) for r in results
        ),
        "gaps_total": sum(int((r.get("meta") or {}).get("gaps_total", 0) or 0) for r in results),
        "gaps_resolved": sum(
            int((r.get("meta") or {}).get("gaps_resolved", 0) or 0) for r in results
        ),
        "injected_dispatches": sum(
            int((r.get("meta") or {}).get("injected_dispatches", 0) or 0) for r in results
        ),
        "cases_with_injection": sum(
            1
            for r in results
            if int((r.get("meta") or {}).get("injected_dispatches", 0) or 0) > 0
        ),
        # T0.2：token / cache（逐 case 的 meta.usage 求和；不可得时 available=False）
        "usage": sum_usage_summaries(
            [
                (r.get("meta") or {}).get("usage") or {}
                for r in results
            ]
        ),
        "cases_without_usage": sum(
            1
            for r in results
            if not ((r.get("meta") or {}).get("usage") or {}).get("available")
        ),
    }
    tool_calls.sort()
    totals["tool_calls_median"] = tool_calls[len(tool_calls) // 2] if tool_calls else 0
    return totals


_METRIC_KEYS = ("tool_calls_total", "model_calls_total", "elapsed_total", "sub_tool_calls")

# T0.5：这些键以前直接取 ``per_round[0]``，于是 ``--repeat 2`` 时第 2 轮对它们毫无影响
# （等于白跑一半）。现在统一给出 median / min / max 三个标量 + 每轮原始序列。
# 字段名保持原样（下游 ``int(experiment.get(...))`` 的读法不会断），但**语义变了**：
# 从"第一轮的值"变成"跨轮中位数"。读报告时要注意这一点。
_SCALAR_KEYS = (
    "tool_calls_median",
    "delegations",
    "gaps_total",
    "gaps_resolved",
    "injected_dispatches",
    "cases_with_injection",
    "main_tool_calls",
    "sub_tool_calls",
)


def _median_of(values: list[float]) -> float | int:
    """中位数（偶数个取中间两个的均值）；全为整数且中位数是整数时返回 int。"""

    if not values:
        return 0
    ordered = sorted(values)
    n = len(ordered)
    result = (
        ordered[n // 2]
        if n % 2
        else (ordered[n // 2 - 1] + ordered[n // 2]) / 2
    )
    if float(result).is_integer():
        return int(result)
    return result


def _experiment_stats(rounds: list[list[dict[str, Any]]]) -> dict[str, Any]:
    """跨轮聚合。

    * ``_METRIC_KEYS``：``{key: {median,min,max}}`` + ``series``（原有形状，未改）
    * ``_SCALAR_KEYS``：``key`` = 跨轮中位数，另有 ``key_min`` / ``key_max`` / ``key_series``
    * token / cache：``usage_*`` 同上（``usage_available=False`` 表示本批根本没采到 usage）
    """

    per_round = [_round_totals(items) for items in rounds if items]
    if not per_round:
        return {"cases": 0, "rounds": 0}
    stats: dict[str, Any] = {
        "cases": per_round[0]["cases"],
        "rounds": len(per_round),
    }
    stats["series"] = {
        key: [float(item[key]) for item in per_round] for key in _METRIC_KEYS
    }
    for key in _METRIC_KEYS:
        values = sorted(float(item[key]) for item in per_round)
        stats[key] = {
            "median": values[len(values) // 2] if len(values) % 2 else (
                values[len(values) // 2 - 1] + values[len(values) // 2]
            ) / 2,
            "min": values[0],
            "max": values[-1],
        }

    for key in _SCALAR_KEYS:
        values = [float(item.get(key, 0) or 0) for item in per_round]
        stats[key] = _median_of(values)
        stats[f"{key}_min"] = min(values)
        stats[f"{key}_max"] = max(values)
        stats[f"{key}_series"] = values

    # token / cache：跨轮取中位数；不可得时 available=False（报告应写"不可得"而非 0）
    usage_rounds = [item.get("usage") or {} for item in per_round]
    for field in ("input_tokens", "output_tokens", "cached_input_tokens", "total_tokens"):
        values = [float(item.get(field, 0) or 0) for item in usage_rounds]
        stats[f"usage_{field}"] = _median_of(values)
        stats[f"usage_{field}_series"] = values
    stats["usage_available"] = any(bool(item.get("available")) for item in usage_rounds)
    stats["cache_field"] = next(
        (str(item.get("cache_field")) for item in usage_rounds if item.get("cache_field")),
        "",
    )
    return stats


def _metric_snapshot(metrics: dict[str, Any]) -> dict[str, float]:
    """把一轮指标压成"比率"快照（供 --repeat 聚合与对比报告使用）。"""

    keys = (
        "top1_hit_rate",
        "top3_hit_rate",
        "evidence_sufficient_rate",
        "evidence_verified_rate",
        "recommendation_acceptable_rate",
    )
    snapshot: dict[str, float] = {}
    for key in keys:
        item = metrics.get(key) or {}
        numerator = item.get("numerator")
        denominator = item.get("denominator")
        if isinstance(numerator, (int, float)) and isinstance(denominator, (int, float)):
            if denominator:
                snapshot[key] = round(float(numerator) / float(denominator), 4)
    return snapshot


def _bootstrap_config_environment() -> None:
    """把 ``config.json`` 的 ``env`` 段注入进程环境（幂等）。

    评测 runner 是**直接调 API** 的，跳过了 CLI 的启动初始化——
    而 ``CLOUDAGENT_LOG_ROOT`` / ``CLOUDAGENT_DB_DSN`` 这些恰恰配在
    config.json 的 ``env`` 段里，正式应用由 ``permissions.trust_boundary`` 负责。

    不注入的后果：log 域 ``search_logs`` 首次调用就返回 ``log_root_not_configured``，
    整个域"无法诊断"——而**报错信息看起来像环境没准备好，不像代码漏了一步**。
    2026-11-04 实测 log-002/003 全因此失败。
    """

    try:
        from cloudagent_ext.permissions.trust_boundary import (
            apply_safe_config_environment_variables,
        )

        apply_safe_config_environment_variables()
    except Exception:  # noqa: BLE001 — 环境注入失败不该让评测起不来
        logger.debug("config environment bootstrap failed", exc_info=True)


def run_evaluation(
    *,
    mode: str,
    case_ids: list[str] | None = None,
    out_dir: str | Path | None = None,
    max_cases: int | None = None,
    timeout_per_case: float = 180.0,
    retries: int = 0,
    provider_factory: Any = None,
    executor: Any = None,
    domain: str = "sql",
    variant: str = "gaps-on",
    repeat: int = 1,
    dispatch_mode: str = "direct",
    grade_source: str = "auto",
) -> dict[str, Any]:
    """执行一次完整评测；返回汇总 dict（同时已落盘报告）。"""

    started = datetime.now(timezone.utc)

    variant = str(variant or "gaps-on")
    repeat = max(int(repeat or 1), 1)
    if variant not in _ARM_ENV_PRESETS:
        raise EvaluationError(
            f"未知 variant：{variant!r}（支持 {', '.join(sorted(_ARM_ENV_PRESETS))}）"
        )
    _bootstrap_config_environment()

    # 按臂设置开关，结束后**逐个还原**，避免污染进程（连续跑多臂时尤其重要）
    import os

    _arm_preset = _ARM_ENV_PRESETS[variant]
    _previous_env = {key: os.environ.get(key) for key in _arm_preset}
    os.environ.update(_arm_preset)

    cases = load_cases(domain)
    if case_ids:
        known = {case["case_id"] for case in cases}
        unknown = [case_id for case_id in case_ids if case_id not in known]
        if unknown:
            raise EvaluationError("未知案例 ID：" + ", ".join(sorted(unknown)))
        selected = set(case_ids)
        cases = [case for case in cases if case["case_id"] in selected]
    cases = sorted(cases, key=lambda case: case["case_id"])
    if max_cases is not None:
        cases = cases[: max(int(max_cases), 0)]
    if not cases:
        raise EvaluationError("没有可执行的案例（选择集为空）")

    # 执行器：显式传入（测试）优先；否则按模式构建。
    if executor is None:
        if mode == "offline":
            executor = OfflineExecutor()
        elif mode == "live":
            executor = LiveExecutor(
                provider_factory=provider_factory,
                timeout_per_case=timeout_per_case,
                dispatch_mode=dispatch_mode,
                grade_source=grade_source,
            )
        else:
            raise EvaluationError(f"未知评测模式：{mode!r}（支持 offline / live）")
    try:
        executor.prepare()
    except EvaluationExecutorError as exc:
        raise EvaluationConfigError(str(exc)) from exc

    results = _execute_cases(cases, executor, retries)

    finished = datetime.now(timezone.utc)
    counted = [r for r in results if not r.get("grader_error")]
    grader_errors = len(results) - len(counted)
    counts = {
        "parsed": sum(1 for r in counted if r["category"] == "parsed"),
        "invalid_output": sum(1 for r in counted if r["category"] == "invalid_output"),
        "crashed": sum(1 for r in counted if r["category"] == "crashed"),
        # 阶段 5：撞轮数上限 / 输出被截断，单独计数——它们不是"答错"
        "unfinished": sum(1 for r in counted if r["category"] == "unfinished"),
        "grader_error": grader_errors,
    }

    rounds_results: list[list[dict[str, Any]]] = [results]
    for _ in range(repeat - 1):
        rounds_results.append(_execute_cases(cases, executor, retries))
    repeats_metrics = [aggregate_metrics(items) for items in rounds_results]

    metrics = aggregate_metrics(results)
    repeat_stats: dict[str, Any] = {
        "rounds": len(repeats_metrics),
        "metrics": [_metric_snapshot(item) for item in repeats_metrics],
    }
    cases_hash = _cases_hash(cases)
    started_local = started.astimezone(_BEIJING_TZ)
    started_at = started_local.isoformat(timespec="seconds")
    # run_id 纳入 variant：同一秒内跑两臂时不会互相覆盖（不能用 ":"，Windows 文件名非法）
    run_id = (
        f"{started_local.strftime('%Y%m%dT%H%M%S')}-{mode}-{variant}-{cases_hash[:8]}"
    )

    completeness = "complete" if grader_errors == 0 else "incomplete"
    incompleteness_reason = (
        None if completeness == "complete" else f"{grader_errors} 个案例评分器异常（grader_error）"
    )

    run_payload: dict[str, Any] = {
        "run_id": run_id,
        "mode": mode,
        "source": results[0]["source"] if results else mode,
        "model": getattr(executor, "model_label", None),
        "cases_hash": cases_hash,
        "case_ids": [case["case_id"] for case in cases],
        "started_at": started_at,
        "finished_at": finished.astimezone(_BEIJING_TZ).isoformat(timespec="seconds"),
        "elapsed_sec": round((finished - started).total_seconds(), 1),
        "total_cases": len(results),
        "counts": counts,
        "metrics": metrics,
        "safety_violation_cases": sum(1 for r in results if r["safety_violations"]),
        "completeness": completeness,
        "incompleteness_reason": incompleteness_reason,
        "retries": int(retries),
        "timeout_per_case": timeout_per_case,
        "domain": domain,
        "variant": variant,
        # 本臂实际设置的开关（空 dict = 不改任何东西）。事后核对"声明关了是否真关"的依据。
        "arm_env": dict(_arm_preset),
        "repeat": repeat,
        "dispatch_mode": dispatch_mode,
        # P2：评分对象。auto 在 main 模式下 → subagent；实际生效值见每个 case 的 meta.grade_source。
        "grade_source": grade_source,
        # T0.6：让报告能自证"这次跑的到底是不是缺口编排生效的那条链路"。
        "gap_injection_effective": _gap_injection_effective(mode, dispatch_mode, variant),
        "repeats": repeat_stats,
        "experiment": _experiment_stats(rounds_results),
    }

    base_out = Path(out_dir) if out_dir else Path("eval") / "runs"
    paths = write_report(base_out / run_id, run_payload, results, domain=domain)

    if dispatch_mode == "direct" and variant == "gaps-on" and mode == "live":
        # 不 raise：`direct` 仍是合法用法（只测子代理单独干活的能力）。
        # 但结论不能用于缺口编排对照，所以要在控制台上说清楚。
        print(
            "[eval] ⚠ 派发模式为 direct：该模式不装配 Agent 工具，"
            "缺口注入 / decide() / 域闸都不会生效。\n"
            "        本次结果只反映子代理自身能力，不能用于缺口编排的对照结论；"
            "如需对照请加 --dispatch main。",
            file=sys.stderr,
        )

    # T0.5：`injected_dispatches` 现在是跨轮中位数；泄漏判定要看"任意一轮是否泄漏"，
    # 所以用 _max——否则 2 轮里 1 轮泄漏、1 轮为 0 时中位数会把泄漏抹平。
    leaked = int(
        run_payload["experiment"].get(
            "injected_dispatches_max",
            run_payload["experiment"].get("injected_dispatches", 0),
        )
        or 0
    )
    if variant == "gaps-off" and leaked > 0:
        raise EvaluationError(
            "开关泄漏：gaps-off 臂出现 injected_dispatches > 0（env 未生效或被覆盖）"
        )

    for _key, _old in _previous_env.items():
        if _old is None:
            os.environ.pop(_key, None)
        else:
            os.environ[_key] = _old

    return {
        "run_id": run_id,
        "completeness": completeness,
        "counts": counts,
        "metrics": metrics,
        "paths": paths,
        "safety_violation_cases": run_payload["safety_violation_cases"],
    }


def _resolve_run(ref: str, out_dir: str | None) -> Path:
    base = Path(out_dir) if out_dir else Path("eval") / "runs"
    candidate = Path(ref)
    if candidate.is_dir():
        return candidate
    direct = base / ref
    if direct.is_dir():
        return direct
    raise EvaluationError(f"找不到 run：{ref}（已查 {candidate} 与 {direct}）")


def _load_run(path: Path) -> dict[str, Any]:
    payload = json.loads((path / "run.json").read_text(encoding="utf-8"))
    payload["_path"] = str(path)
    return payload


def _arm_summary(run: dict[str, Any]) -> dict[str, Any]:
    metrics = run.get("metrics") or {}
    experiment = run.get("experiment") or {}
    meta = run.get("repeats") or {}
    rounds = meta.get("metrics") or []

    def _value(key: str) -> str:
        item = metrics.get(key) or {}
        return str(item.get("value", "—"))

    def _median_of(snapshot_key: str) -> str:
        values = sorted(float(item[snapshot_key]) for item in rounds if snapshot_key in item)
        if not values:
            return "—"
        middle = len(values) // 2
        value = values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2
        return f"{value:.0%}"

    def _stat(key: str, field: str) -> float:
        """读实验统计量，容忍两种历史形状。

        ``experiment`` 里同名键存在两种写法：早期是 ``{"median": x, "min": …, "max": …}``
        形态的 dict，后来部分指标直接存裸数字。这里统一兼容，否则对比会
        在 ``'int' object has no attribute 'get'`` 上崩掉（2026-11-05 实测踩到）。
        """

        item = experiment.get(key)
        if isinstance(item, dict):
            return float(item.get(field, 0) or 0)
        if isinstance(item, (int, float)):
            return float(item)
        return 0.0

    return {
        "variant": run.get("variant", "gaps-on"),
        "mode": run.get("mode"),
        "rounds": int(meta.get("rounds", 1) or 1),
        "cases": int(run.get("total_cases", 0) or 0),
        "tool_calls": _stat("tool_calls_total", "median"),
        "tool_calls_series": list((experiment.get("series") or {}).get("tool_calls_total") or []),
        "model_calls": _stat("model_calls_total", "median"),
        "elapsed": _stat("elapsed_total", "median"),
        "sub_tool_calls": _stat("sub_tool_calls", "median"),
        "gaps_total": int(experiment.get("gaps_total", 0) or 0),
        "injected_dispatches": int(experiment.get("injected_dispatches", 0) or 0),
        "delegations": int(experiment.get("delegations", 0) or 0),
        "top1": _value("top1_hit_rate"),
        "sufficiency": _value("evidence_sufficient_rate"),
        "top1_value": _ratio_value(metrics, "top1_hit_rate"),
        "sufficiency_value": _ratio_value(metrics, "evidence_sufficient_rate"),
        "top1_median": _median_of("top1_hit_rate"),
        "sufficiency_median": _median_of("evidence_sufficient_rate"),
    }


def _ratio_value(metrics: dict[str, Any], key: str) -> float | None:
    item = metrics.get(key) or {}
    numerator = item.get("numerator")
    denominator = item.get("denominator")
    if isinstance(numerator, (int, float)) and isinstance(denominator, (int, float)) and denominator:
        return float(numerator) / float(denominator)
    return None


def _pp_delta(left: float | None, right: float | None) -> str:
    if left is None or right is None:
        return "—"
    return f"{(right - left) * 100:+.0f}pp"


def _diff_interval(left: list[float], right: list[float]) -> tuple[str, float | None]:
    """逐轮差值区间 + MDE 粗估（1.96·sd/√N；N<2 无法估计）。"""

    length = min(len(left), len(right))
    if length == 0:
        return ("—", None)
    diffs = [right[index] - left[index] for index in range(length)]
    if length == 1:
        return (f"{diffs[0]:+.0f}（单轮）", None)
    mean = sum(diffs) / length
    variance = sum((value - mean) ** 2 for value in diffs) / (length - 1)
    sd = variance ** 0.5
    mde = 1.96 * sd / (length ** 0.5)
    return (f"{min(diffs):+.0f} ~ {max(diffs):+.0f}", mde)


def _compare_runs(ref_a: str, ref_b: str, *, out_dir: str | None = None) -> int:
    run_a = _load_run(_resolve_run(ref_a, out_dir))
    run_b = _load_run(_resolve_run(ref_b, out_dir))
    left = _arm_summary(run_a)
    right = _arm_summary(run_b)

    if left["variant"] == right["variant"]:
        raise EvaluationError(
            f"两臂 variant 相同（{left['variant']}）：请分别用 --variant gaps-on / gaps-off 运行"
        )

    any_offline = "offline" in (left["mode"], right["mode"])
    applied = (left["injected_dispatches"] + right["injected_dispatches"]) > 0
    interval, mde = _diff_interval(left["tool_calls_series"], right["tool_calls_series"])

    if not applied:
        conclusion = "**无效**：treatment 未施加（两臂 injected_dispatches 均为 0），该批次不得用于结论"
    elif left["rounds"] < 2 or right["rounds"] < 2:
        conclusion = "**无可测差异（样本量不足以排除中等效应）**：单轮无法估计区间与 MDE"
    elif interval != "—" and mde is not None and abs(right["tool_calls"] - left["tool_calls"]) <= mde:
        conclusion = (
            "**无可测差异（样本量不足以排除中等效应）**：观测差值在 MDE "
            f"({mde:.1f}) 以内"
        )
    else:
        conclusion = "**有可测差异**：差值超出重复区间与 MDE 粗估"

    lines: list[str] = [
        f"# 对照报告：{run_a['run_id']} vs {run_b['run_id']}",
        "",
        f"- 样本量：{left['cases']} 例/臂",
        f"- 重复轮次：{left['rounds']} / {right['rounds']}",
        f"- 模式：{left['mode']} / {right['mode']}",
        "",
    ]
    if any_offline:
        lines += ["> ⚠ **夹具回放，不构成对照结论。**", ""]
    if not applied:
        lines += ["> ⚠ **treatment 未施加（两臂 injected_dispatches 均为 0）。**", ""]

    lines += [
        f"| 指标 | {left['variant']} | {right['variant']} | 差值 |",
        "|---|---|---|---|",
        f"| tool_calls（跨轮中位数，总） | {left['tool_calls']:.0f} | {right['tool_calls']:.0f} | "
        f"{right['tool_calls'] - left['tool_calls']:+.0f}（区间 {interval}） |",
        f"| model_calls（跨轮中位数，总） | {left['model_calls']:.0f} | {right['model_calls']:.0f} | "
        f"{right['model_calls'] - left['model_calls']:+.0f} |",
        f"| elapsed（跨轮中位数，秒） | {left['elapsed']:.1f} | {right['elapsed']:.1f} | "
        f"{right['elapsed'] - left['elapsed']:+.1f} |",
        f"| 子代理工具调用 | {left['sub_tool_calls']:.0f} | {right['sub_tool_calls']:.0f} | "
        f"{right['sub_tool_calls'] - left['sub_tool_calls']:+.0f} |",
        f"| 委派次数（过程指标） | {left['delegations']} | {right['delegations']} | "
        f"{right['delegations'] - left['delegations']:+d} |",
        f"| 缺口总数 | {left['gaps_total']} | {right['gaps_total']} | "
        f"{right['gaps_total'] - left['gaps_total']:+d} |",
        f"| 注入命中 | {left['injected_dispatches']} | {right['injected_dispatches']} | "
        f"{right['injected_dispatches'] - left['injected_dispatches']:+d} |",
        f"| Top-1 命中率 | {left['top1']} | {right['top1']} | "
        f"{_pp_delta(left['top1_value'], right['top1_value'])} |",
        f"| 证据充分率 | {left['sufficiency']} | {right['sufficiency']} | "
        f"{_pp_delta(left['sufficiency_value'], right['sufficiency_value'])} |",
        f"| Top-1（跨轮中位数） | {left['top1_median']} | {right['top1_median']} | — |",
        f"| 充分率（跨轮中位数） | {left['sufficiency_median']} | {right['sufficiency_median']} | — |",
        "",
        f"MDE 粗估（tool_calls，1.96·sd/√N）：{'—（N<2 无法估计）' if mde is None else f'{mde:.1f}'}",
        "",
        f"结论：{conclusion}",
        "",
    ]
    text = chr(10).join(lines) + chr(10)

    out_path = Path(out_dir) if out_dir else Path("eval") / "runs"
    out_path.mkdir(parents=True, exist_ok=True)
    target = out_path / f"compare-{run_a['run_id']}--{run_b['run_id']}.md"
    target.write_text(text, encoding="utf-8")
    print(text)
    print(f"[compare] 报告：{target}")
    return 0


def _compare_last(domain: str, *, out_dir: str | None = None) -> int:
    base = Path(out_dir) if out_dir else Path("eval") / "runs"
    runs = sorted(
        (path for path in base.iterdir() if (path / "run.json").exists()),
        key=lambda path: path.name,
    )
    by_variant: dict[str, Path] = {}
    for path in runs:
        payload = _load_run(path)
        if payload.get("domain") != domain:
            continue
        by_variant[str(payload.get("variant", "gaps-on"))] = path
    missing = {"gaps-on", "gaps-off"} - set(by_variant)
    if missing:
        raise EvaluationError(f"域 {domain} 缺少分组 {sorted(missing)} 的 run，无法对比")
    return _compare_runs(str(by_variant["gaps-on"]), str(by_variant["gaps-off"]), out_dir=out_dir)


ROUTING_CASES_DIR = Path("cloudagent_ext") / "diagnosis" / "cases" / "routing"


def load_routing_cases() -> list[dict[str, Any]]:
    """读取路由评测题库（``cases/routing/*.json``）。"""

    base = Path(__file__).resolve().parents[1] / "cases" / "routing"
    cases: list[dict[str, Any]] = []
    for path in sorted(base.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for case in payload.get("cases", []) if isinstance(payload, dict) else []:
            cases.append(case)
    return cases


def score_routing_case(case: dict[str, Any], dispatched: list[str]) -> dict[str, Any]:
    """判定一次路由是否合格：期望的都在、禁止的一个都没出现。"""

    expected = set(case.get("expected_agents") or [])
    forbidden = set(case.get("forbidden_agents") or [])
    actual = set(dispatched)
    missing = sorted(expected - actual)
    violated = sorted(forbidden & actual)
    return {
        "case_id": case.get("case_id"),
        "question": case.get("question"),
        "expected": sorted(expected),
        "forbidden": sorted(forbidden),
        "actual": sorted(actual),
        "missing": missing,
        "violated": violated,
        "passed": not missing and not violated,
    }


def run_routing_evaluation(
    *,
    out_dir: str | Path | None = None,
    max_cases: int | None = None,
    provider_factory: Any = None,
    executor: Any = None,
    timeout_per_case: float = 240.0,
) -> dict[str, Any]:
    """主 Agent 路由评测：只看"派给了谁"，不评价诊断质量。"""

    cases = load_routing_cases()
    if max_cases is not None:
        cases = cases[: max(int(max_cases), 0)]
    if not cases:
        raise EvaluationError("路由题库为空（cloudagent_ext/diagnosis/cases/routing/）")

    if executor is None:
        executor = LiveExecutor(
            provider_factory=provider_factory,
            timeout_per_case=timeout_per_case,
            dispatch_mode="main",
        )
    try:
        executor.prepare()
    except EvaluationExecutorError as exc:
        raise EvaluationConfigError(str(exc)) from exc

    results: list[dict[str, Any]] = []
    for case in cases:
        run = executor.run_case({"case_id": case["case_id"], "input": {"question": case["question"]}})
        dispatched = list((run.meta or {}).get("agents_dispatched") or [])
        scored = score_routing_case(case, dispatched)
        scored["error"] = run.error
        scored["elapsed_sec"] = (run.meta or {}).get("elapsed_sec")
        results.append(scored)

    passed = sum(1 for item in results if item["passed"])
    run_id = (
        datetime.now(_BEIJING_TZ).strftime("%Y%m%dT%H%M%S")
        + "-routing-"
        + str(len(results))
    )

    lines = [
        "# 路由评测",
        "",
        f"- 案例数：{len(results)}",
        f"- 通过：{passed}（{passed / len(results):.0%}）",
        f"- 生成时间：{datetime.now(_BEIJING_TZ).isoformat(timespec='seconds')}",
        "",
        "| case | 期望 | 禁止 | 实际 | 缺失 | 越界 | 结果 |",
        "|---|---|---|---|---|---|---|",
    ]
    for item in results:
        lines.append(
            f"| {item['case_id']} | {', '.join(item['expected']) or '—'} | "
            f"{', '.join(item['forbidden']) or '—'} | {', '.join(item['actual']) or '（无派发）'} | "
            f"{', '.join(item['missing']) or '—'} | {', '.join(item['violated']) or '—'} | "
            f"{'✅' if item['passed'] else '❌'} |"
        )
    lines += [
        "",
        "> 判分只看派发对象，不评价回答质量；`actual` 来自会话账本的 agent_type 集合。",
        "",
    ]

    base = Path(out_dir) if out_dir else Path("eval") / "runs"
    (base / run_id).mkdir(parents=True, exist_ok=True)
    (base / run_id / "routing.md").write_text(chr(10).join(lines) + chr(10), encoding="utf-8")
    (base / run_id / "run.json").write_text(
        json.dumps(
            {"run_id": run_id, "mode": "routing", "cases": results, "passed": passed},
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(chr(10).join(lines))
    print(f"[routing] 报告：{base / run_id / 'routing.md'}")
    return {"run_id": run_id, "passed": passed, "total": len(results), "results": results}


def _run_rates(run: dict[str, Any]) -> dict[str, str]:
    """从 run.json 里抽四个对外指标（缺失显示 —）。"""

    metrics = run.get("metrics") or {}

    def _value(key: str) -> str:
        item = metrics.get(key) or {}
        return str(item.get("value", "—"))

    counts = run.get("counts") or {}
    failures = "／".join(
        f"{name} {counts.get(name, 0)}"
        for name in ("parsed", "invalid_output", "unfinished", "crashed", "grader_error")
        if counts.get(name)
    )
    return {
        "top1": _value("top1_hit_rate"),
        "sufficiency": _value("evidence_sufficient_rate"),
        "verified": _value("evidence_verified_rate"),
        "failures": failures or "—",
    }


def _summary_runs(
    *,
    domain: str | None = None,
    last: int = 10,
    out_dir: str | None = None,
) -> int:
    """跨域汇总：把最近 N 次 run 拼成一张表（P5.4）。"""

    base = Path(out_dir) if out_dir else Path("eval") / "runs"
    if not base.is_dir():
        raise EvaluationError(f"报告目录不存在：{base}")

    runs: list[dict[str, Any]] = []
    for path in sorted(base.glob("*/run.json"), key=lambda item: item.parent.name, reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if domain and payload.get("domain") != domain:
            continue
        payload["_run_id"] = payload.get("run_id") or path.parent.name
        runs.append(payload)
        if len(runs) >= max(int(last), 1):
            break

    if not runs:
        raise EvaluationError("没有可汇总的 run（先跑一次评测）")

    runs.sort(key=lambda item: item["_run_id"])

    lines: list[str] = [
        "# 跨域评测汇总",
        "",
        f"- 覆盖 run 数：{len(runs)}" + (f"（域：{domain}）" if domain else "（全部域）"),
        f"- 生成时间：{datetime.now(_BEIJING_TZ).isoformat(timespec='seconds')}",
        "",
        "| run_id | 域 | 模式 | 案例 | 完好率 | Top-1 | 证据充分率 | 可核验率 | 失败构成 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for run in runs:
        rates = _run_rates(run)
        completeness = run.get("completeness", "—")
        cases = run.get("total_cases", 0)
        lines.append(
            f"| {run['_run_id']} | {run.get('domain', '—')} | {run.get('mode', '—')} | {cases} | "
            f"{completeness} | {rates['top1']} | {rates['sufficiency']} | {rates['verified']} | "
            f"{rates['failures']} |"
        )

    # 按域聚合（每域取最近一次）
    latest_by_domain: dict[str, dict[str, Any]] = {}
    for run in reversed(runs):  # runs 已按 run_id 升序，倒序遍历即最近优先
        latest_by_domain.setdefault(run.get("domain", "—"), run)

    lines += [
        "",
        "## 各域最近一次",
        "",
        "| 域 | run_id | Top-1 | 证据充分率 | 可核验率 |",
        "|---|---|---|---|---|",
    ]
    for name, run in sorted(latest_by_domain.items()):
        rates = _run_rates(run)
        lines.append(
            f"| {name} | {run['_run_id']} | {rates['top1']} | {rates['sufficiency']} | {rates['verified']} |"
        )

    lines += [
        "",
        "> offline 模式为夹具回放，不能代表真实诊断能力；可核验率分母为「含可抽取关键词的 proves」，",
        "> 分母为 0 时显示 n/a。",
        "> `crashed` 多为该 case 缺少 offline 夹具（sql / cross 域目前如此），不代表 live 也失败。",
        "",
    ]

    base.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(_BEIJING_TZ).strftime("%Y%m%dT%H%M%S")
    target = base / f"summary-{stamp}.md"
    target.write_text(chr(10).join(lines) + chr(10), encoding="utf-8")
    print(chr(10).join(lines))
    print(f"[summary] 报告：{target}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m cloudagent_ext.diagnosis.evaluation.runner",
        description="CloudAgent SQL 诊断批量评测（offline=fixture 验证设施 / live=真实模型）",
    )
    parser.add_argument("--mode", default="offline", choices=["offline", "live"],
                        help="评测模式（对比模式下可省略）")
    parser.add_argument("--domain", default="sql", choices=["sql", "code", "log", "cross", "sync"], help="案例域（默认 sql）")
    parser.add_argument("--cases", default=None, help="逗号分隔的 case_id 子集，如 sql-001,sql-003")
    parser.add_argument("--out", default=None, help="报告输出目录（默认 eval/runs/）")
    parser.add_argument("--max-cases", type=int, default=None)
    parser.add_argument("--timeout-per-case", type=float, default=180.0)
    parser.add_argument("--retries", type=int, default=0)
    parser.add_argument("--variant", default="gaps-on", choices=sorted(_ARM_ENV_PRESETS),
                        help="对照实验分组：gaps-off 强制关闭缺口注入")
    parser.add_argument("--repeat", type=int, default=1, help="同臂重复轮数（run 内聚合）")
    parser.add_argument("--compare", nargs=2, default=None, metavar=("RUN_A", "RUN_B"),
                        help="对比两个 run（run_id 或目录路径）")
    parser.add_argument("--compare-last", action="store_true",
                        help="对比最近两个同域 run")
    parser.add_argument("--routing", action="store_true",
                        help="路由评测：只判派发对象（需 --mode live）")
    parser.add_argument("--dispatch", default="direct", choices=["direct", "main"],
                        help="live 执行器的派发模式：direct=直驱子代理（默认）/ main=走主 Agent")
    parser.add_argument("--grade-source", default="auto", choices=["auto", "main", "subagent"],
                        help="评分对象：auto=main 模式下取子代理协议结果（默认）/ "
                             "main=评主 Agent 回答（散文，通常无法解析）/ subagent=评子代理结果")
    parser.add_argument("--summary", action="store_true",
                        help="跨域汇总最近 N 次 run（见 --summary-last）")
    parser.add_argument("--summary-last", type=int, default=10, metavar="N",
                        help="汇总最近 N 次 run（默认 10）")
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    if not raw_argv:
        parser.print_help()
        sys.stderr.write(
            chr(10)
            + "[eval] 未提供参数：为避免误触批量评测，未执行任何运行。"
            + "示例：--mode offline --domain sql"
            + chr(10)
        )
        return 2
    args = parser.parse_args(raw_argv)

    if args.compare:
        return _compare_runs(args.compare[0], args.compare[1], out_dir=args.out)
    if args.compare_last:
        return _compare_last(args.domain, out_dir=args.out)
    if args.summary:
        return _summary_runs(last=args.summary_last, out_dir=args.out)
    if args.routing:
        if args.mode != "live":
            sys.stderr.write("[routing] 需要 --mode live（路由依赖真实模型决策）\n")
            return 2
        run_routing_evaluation(out_dir=args.out, max_cases=args.max_cases)
        return 0

    case_ids = [item.strip() for item in (args.cases or "").split(",") if item.strip()] or None
    try:
        summary = run_evaluation(
            mode=args.mode,
            case_ids=case_ids,
            out_dir=args.out,
            max_cases=args.max_cases,
            timeout_per_case=args.timeout_per_case,
            retries=args.retries,
            domain=args.domain,
            variant=args.variant,
            repeat=args.repeat,
            dispatch_mode=args.dispatch,
            grade_source=args.grade_source,
        )
    except EvaluationError as exc:
        sys.stderr.write(f"[eval] 错误：{redact_sensitive(str(exc))}\n")
        return 2

    print(f"[eval] run_id={summary['run_id']} completeness={summary['completeness']}")
    for key, meta in summary["metrics"].items():
        print(f"  {meta['label']}: {meta['value']} ({meta.get('numerator', '-')}/{meta.get('denominator', '-')})")
    print(f"  报告：{summary['paths']['summary']}")
    return 0 if summary["completeness"] == "complete" else 3


if __name__ == "__main__":
    raise SystemExit(main())
