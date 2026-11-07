#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""跑一个 case → RunRecord（EVAL-P1a）。

**只做执行与序列化**：任何评分、GT 比对、markdown 都不在这里——
看到 ``match_terms`` / ``top1`` / ``score`` 出现在本文件即为越界（任务卡红线 1）。

# KNOWN-ISSUE(eval-bash-empty)
``dontAsk`` 权限模式下，子代理调 ``Bash`` 返回空字符串（``is_error=None``），
模型于是自己总结成 "Bash is unavailable" 改用 Read/Grep/Glob——评测环境里任何
需要跑命令的代码诊断都做不到，且症状表现为"模型答不好"而不是"链路坏了"。
**本卡不修**（属执行层改动，会与 P2 迁移纠缠）；建议在 EVAL-P3（修评分口径）一起修。
"""

from __future__ import annotations

import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from cloudagent_ext.diagnosis.eval_support.record import (
    RunRecord,
    RunRequest,
    record_to_json,
)
from cloudagent_ext.utils.redaction import redact_sensitive

__all__ = ["execute_case", "case_run_to_record", "build_subject"]

#: trace.calls 的 content 截断长度（与 evaluation.executors._EVENT_TEXT_LIMIT 一致）
_CALL_TEXT_LIMIT = 20000

#: mechanism 的搬运白名单（schema §4.2）——白名单而非黑名单：
#: meta 里将来新增的调试字段不进契约，否则"契约稳定"变成空话
_MECHANISM_KEYS = (
    "delegations",
    "agents_dispatched",
    "gaps_total",
    "gaps_resolved",
    "injected_dispatches",
    "decision_counts",
    "decision_log",
    "gap_events",
    "compaction",
    "recall_count",
    "recall_miss",
    "state_revision",
    "stale_discarded",
    "assessments",
)

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _product_version() -> str:
    try:
        from cloudagent_ext._version import __version__

        return str(__version__) or "unknown"
    except Exception:  # noqa: BLE001 — 取不到就写 unknown，不许编
        return "unknown"


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        sha = out.stdout.strip()
        return sha or "unknown"
    except Exception:  # noqa: BLE001 — 非 git 环境 / 无 git 命令 → unknown
        return "unknown"


def _provider_name() -> str:
    """配置面 provider 名（与 evaluation.executors._default_provider_factory 的取值顺序一致）。

    只读配置，不构造 provider——构造失败会在执行阶段以 EvaluationExecutorError 暴露。
    """

    name = str(os.environ.get("CLOUDAGENT_PROVIDER", "") or "").strip()
    if name:
        return name
    try:
        from cloudagent_ext.config import get_default_provider

        return str(get_default_provider() or "").strip() or "unknown"
    except Exception:  # noqa: BLE001 — 读配置失败就写 unknown
        return "unknown"


def build_subject(request: RunRequest, model_label: str = "") -> dict[str, Any]:
    """被测系统身份（schema §3.2，R7 全链路版本化）。取不到的写 ``"unknown"``，不许猜。"""

    from cloudagent_ext.diagnosis.switches import SWITCHES

    # arm_env 只记机制开关的原始环境值（不 dump 整个 os.environ——那会把凭据写进记录）
    arm_env = {
        spec.env: os.environ[spec.env]
        for spec in SWITCHES.values()
        if spec.env in os.environ
    }
    return {
        "product": "cloudagent",
        "version": _product_version(),
        "git_sha": _git_sha(),
        "model": str(model_label or "").strip() or "unknown",
        "provider": _provider_name(),
        "dispatch_mode": request.options.get("dispatch_mode", "main"),
        "grade_source": request.options.get("grade_source", "auto"),
        "permission_mode": request.options.get("permission_mode", "dontAsk"),
        "arm_env": arm_env,
    }


def _wants_subagent_grade(dispatch_mode: str, grade_source: str) -> bool:
    """与 ``evaluation.executors._wants_subagent_grade`` 同语义（照抄不另立）。

    P2 搬迁该函数后，这里改为从唯一实现导入。
    """

    if grade_source == "subagent":
        return True
    if grade_source == "main":
        return False
    return dispatch_mode == "main"


def _truncate_calls(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """``content`` 可能很大：截断到 20000 字符并打 ``truncated`` 标记。"""

    trimmed: list[dict[str, Any]] = []
    for call in calls:
        item = dict(call)
        content = item.get("content")
        if isinstance(content, str) and len(content) > _CALL_TEXT_LIMIT:
            item["content"] = content[:_CALL_TEXT_LIMIT]
            item["truncated"] = True
        trimmed.append(item)
    return trimmed


def _determine_status(case_run: Any) -> tuple[str, bool]:
    """status 判定（审查 eval-p1a-round1 §2 疑问 2 裁决后的五档口径）。

    * 空输出 → ``unfinished``（与 ``scoring.categorize()`` 一致：空输出=
      没拿到作答机会=链路问题，不是独立的 "empty" 档）；
    * "撞轮次上限 / 明显截断" 与 "输出不合协议" 的细分是评分层的事（P3）：
      本卡对"非空、无错"的输出记 ``ok`` 并打 ``status_provisional``，
      让 P3 知道这条还没细分过。
    """

    error = case_run.error
    if error and "timeout" in str(error).lower():
        return "timeout", False
    if error:
        return "crashed", False
    if not str(case_run.raw_output or "").strip():
        return "unfinished", False
    return "ok", True


def case_run_to_record(
    case_run: Any,
    request: RunRequest,
    *,
    record_id: str,
    started_at: str,
    finished_at: str,
    subject: dict[str, Any],
    elapsed_sec: float | None = None,
) -> RunRecord:
    """``CaseRun → RunRecord`` 的字段映射（实现时唯一要对照的是 schema §4 的表）。"""

    meta: dict[str, Any] = dict(getattr(case_run, "meta", None) or {})
    status, provisional = _determine_status(case_run)

    # ---- graded_text（schema §5）：选谁评分只有这一处实现 ----
    raw_output = str(case_run.raw_output or "")
    main_answer = str(case_run.main_answer or "")
    dispatch_mode = request.options.get("dispatch_mode", "main")
    grade_source = request.options.get("grade_source", "auto")
    if _wants_subagent_grade(dispatch_mode, grade_source):
        # LiveExecutor 在拿到子代理结果时会把 meta.grade_source 记为 "subagent"；
        # 请求要子代理结果但没拿到（如 main 模式没派发）→ graded_text 留空、
        # status 记 unfinished（空输出=没拿到作答机会，与 categorize 口径一致）
        if str(meta.get("grade_source") or "") == "subagent":
            graded_text = raw_output
        else:
            graded_text = ""
            if status == "ok":
                status, provisional = "unfinished", False
    else:
        graded_text = main_answer

    outcome: dict[str, Any] = {
        "status": status,
        "error": None if case_run.error is None else redact_sensitive(str(case_run.error)),
        "raw_output": raw_output,
        "main_answer": main_answer,
        "graded_text": graded_text,
    }
    if provisional:
        outcome["status_provisional"] = True

    mechanism = {key: meta[key] for key in _MECHANISM_KEYS if key in meta}

    usage_meta = meta.get("usage") or {}
    available = bool(usage_meta.get("available"))
    usage: dict[str, Any] = {
        "input_tokens": usage_meta.get("input_tokens") if available else None,
        "output_tokens": usage_meta.get("output_tokens") if available else None,
        "cached_input_tokens": usage_meta.get("cached_input_tokens") if available else None,
        "model_calls": int(meta.get("model_calls", 0) or 0),
        "calls_without_usage": int(usage_meta.get("calls_without_usage", 0) or 0),
        "available": available,
    }

    events = list(getattr(case_run, "events", None) or [])
    trace = {"events": events, "calls": _truncate_calls(list(getattr(case_run, "calls", None) or []))}

    if elapsed_sec is None:
        elapsed_sec = float(meta.get("elapsed_sec", 0.0) or 0.0)

    return RunRecord(
        schema_version=1,
        record_id=record_id,
        request_id=request.request_id,
        case_id=request.case_id,
        domain=request.domain,
        started_at=started_at,
        finished_at=finished_at,
        elapsed_sec=float(elapsed_sec),
        subject=dict(subject),
        outcome=outcome,
        trace=trace,
        mechanism=mechanism,
        usage=usage,
    )


def execute_case(
    request: RunRequest,
    *,
    executor: Any = None,
) -> RunRecord:
    """跑一个 case，产出 :class:`RunRecord`。

    ⚠️ 技术债（EVAL-P2 偿还）：
    当前复用 ``evaluation.executors.LiveExecutor`` 的装配与采集逻辑——它已能产出
    ``CaseRun``（含 meta/calls/events/main_answer），本函数只负责
    ``CaseRun → RunRecord`` 的转换（:func:`case_run_to_record`）。

    P2 要搬进本模块的函数清单（届时删除 evaluation/）：
      - ``_ensure_ready()``             provider + registry + system_prompt 装配
      - ``build_diagnosis_tool_context()``  dontAsk 受限上下文
      - ``_build_restricted_registry()``    执行层白名单强制
      - ``build_main_dispatch_prompt()``    main 模式系统提示
      - ``_agent_for_domain()``             域 → 子代理映射

    ``executor`` 参数用于测试注入（fake executor，零模型成本）。
    """

    if executor is None:
        from cloudagent_ext.diagnosis.evaluation.executors import LiveExecutor

        executor = LiveExecutor(
            timeout_per_case=float(request.options.get("timeout_sec", 300)),
            dispatch_mode=request.options.get("dispatch_mode", "main"),
            grade_source=request.options.get("grade_source", "auto"),
        )

    case = {
        "case_id": request.case_id,
        "domain": request.domain,
        "input": {
            "question": request.question,
            "context": dict(request.context),
        },
    }

    started = time.time()
    started_at = datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        case_run = executor.run_case(case)
    except Exception as exc:  # noqa: BLE001 — 执行层异常也要落记录（脱敏）
        # 契约要求"执行失败仍写出 RunRecord"：构造最小 crashed CaseRun，
        # 让失败样本与成功样本走同一条序列化路径
        from cloudagent_ext.diagnosis.evaluation.executors import CaseRun

        case_run = CaseRun(
            case_id=request.case_id,
            source="live",
            raw_output="",
            meta={
                "model": getattr(executor, "model_label", "") or "",
                "elapsed_sec": round(time.time() - started, 2),
            },
            error=f"{type(exc).__name__}: {redact_sensitive(str(exc))}",
        )
    finished_at = datetime.now().astimezone().isoformat(timespec="seconds")

    meta: dict[str, Any] = dict(getattr(case_run, "meta", None) or {})
    model_label = str(meta.get("model", "") or getattr(executor, "model_label", "") or "")
    record_id = "rec-{}-{}".format(
        request.case_id, datetime.now().strftime("%Y%m%dT%H%M%S")
    )
    elapsed = float(meta.get("elapsed_sec", 0.0) or 0.0) or round(time.time() - started, 2)
    return case_run_to_record(
        case_run,
        request,
        record_id=record_id,
        started_at=started_at,
        finished_at=finished_at,
        subject=build_subject(request, model_label),
        elapsed_sec=elapsed,
    )


def write_record(record: RunRecord, out_path: str | Path) -> None:
    """把 RunRecord 写成 JSON（字段顺序稳定，便于 diff）。"""

    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json_dumps(record)
    path.write_text(payload, encoding="utf-8")


def json_dumps(record: RunRecord) -> str:
    import json

    return json.dumps(record_to_json(record), ensure_ascii=False, indent=2) + "\n"
