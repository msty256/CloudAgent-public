#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""RunRecord v1 契约：``RunRequest``（评测仓 → 产品）与 ``RunRecord``（产品 → 评测仓）。

**这是本包唯一"必须完全独立"的模块**：只 import 标准库。评测仓将来会拿这份
schema 当共同语言——它一旦依赖产品内部，"独立评测项目"就名不副实。

两条协议层红线（字段级规则见
``docs/collab/design/eval-p1a-runrecord-schema.md``）：

1. **两个类型都不含 ground_truth**——答案是评测仓的私有资产。
   ``RunRequest`` 对未知字段（尤其 ``ground_truth``）**报错而不是静默忽略**：
   静默忽略会让"把整份 case 传进来"发生得无声无息，症状是"分数莫名特别高"。
2. **``usage.available == false`` 时 token 字段为 ``None``，不是 ``0``**——
   继承 ``evaluation/cost.py`` 的纪律：没采到不能冒充零消耗。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "SCHEMA_VERSION",
    "OUTCOME_STATUSES",
    "VALID_DOMAINS",
    "RunRecord",
    "RunRecordError",
    "RunRequest",
    "RunRequestError",
    "record_from_json",
    "record_to_json",
    "request_from_json",
    "request_to_json",
]

#: 本文件实现的 schema 版本
SCHEMA_VERSION = 1

#: ``outcome.status`` 五档——语义对齐 ``evaluation/scoring.categorize()``，不另立标准
#: （原六档里的 ``empty`` 已删除：空输出=没拿到作答机会=链路问题，归 ``unfinished``，
#: 与 categorize 的既有论证一致；审查 eval-p1a-round1 §2 疑问 2 裁决）
OUTCOME_STATUSES = frozenset(
    {"ok", "timeout", "crashed", "unfinished", "invalid_output"}
)

#: 合法诊断域（与案例库口径一致；硬编码以保持本模块零内部依赖）
VALID_DOMAINS = frozenset({"sql", "code", "log", "cross", "sync"})

#: ``options.permission_mode`` 白名单——只有一个值是有意的：口子留着，放宽时能看见 diff
_ALLOWED_PERMISSION_MODES = frozenset({"dontAsk"})

_ALLOWED_DISPATCH_MODES = frozenset({"direct", "main"})
_ALLOWED_GRADE_SOURCES = frozenset({"auto", "main", "subagent"})

_REQUEST_FIELDS = (
    "schema_version",
    "request_id",
    "case_id",
    "domain",
    "question",
    "context",
    "options",
)

_REQUEST_OPTION_KEYS = frozenset(
    {"dispatch_mode", "grade_source", "timeout_sec", "permission_mode"}
)


class RunRequestError(ValueError):
    """``RunRequest`` 载荷非法（未知字段 / 缺必填 / 取值越界）。"""


class RunRecordError(ValueError):
    """``RunRecord`` 载荷非法。"""


@dataclass(frozen=True)
class RunRequest:
    """评测仓发给产品的一次执行请求。**结构上没有 ground_truth。**"""

    schema_version: int = SCHEMA_VERSION
    request_id: str = ""
    case_id: str = ""
    domain: str = ""
    question: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RunRecord:
    """产品对一次执行的结构化记录（产品 → 评测仓，单向）。

    * ``trace`` / ``mechanism`` 是 optional：黑盒 subject 只填 ``outcome`` 也合法；
    * 读取方必须能在无 trace 时降级。
    """

    schema_version: int = SCHEMA_VERSION
    record_id: str = ""
    request_id: str = ""
    case_id: str = ""
    domain: str = ""
    started_at: str = ""
    finished_at: str = ""
    elapsed_sec: float = 0.0
    subject: dict[str, Any] = field(default_factory=dict)
    outcome: dict[str, Any] = field(default_factory=dict)
    trace: dict[str, Any] | None = None
    mechanism: dict[str, Any] | None = None
    usage: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# RunRequest：严格校验（未知字段报错）
# ---------------------------------------------------------------------------


def request_to_json(request: RunRequest) -> dict[str, Any]:
    """按 schema 字段顺序输出（稳定顺序，便于 diff）。"""

    return {
        "schema_version": request.schema_version,
        "request_id": request.request_id,
        "case_id": request.case_id,
        "domain": request.domain,
        "question": request.question,
        "context": dict(request.context),
        "options": dict(request.options),
    }


def _require_non_empty(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RunRequestError(f"{key} 必须是非空字符串")
    return value


def request_from_json(payload: dict[str, Any]) -> RunRequest:
    """严格校验并构造 :class:`RunRequest`。

    * 未知字段一律 :class:`RunRequestError`（尤其 ``ground_truth``——这是本卡
      的安全价值所在，不许放宽）；
    * ``options`` 的键与取值也受白名单约束。
    """

    if not isinstance(payload, dict):
        raise RunRequestError("RunRequest 载荷必须是 JSON 对象")

    unknown = sorted(set(payload) - set(_REQUEST_FIELDS))
    if unknown:
        raise RunRequestError(
            "RunRequest 存在未知字段（协议层拒绝，防止把整份 case 连答案带进来）："
            + ", ".join(unknown)
        )

    version = payload.get("schema_version")
    if version != SCHEMA_VERSION:
        raise RunRequestError(f"schema_version 必须是 {SCHEMA_VERSION}，收到 {version!r}")

    request_id = _require_non_empty(payload, "request_id")
    case_id = _require_non_empty(payload, "case_id")
    question = _require_non_empty(payload, "question")

    domain = _require_non_empty(payload, "domain")
    if domain not in VALID_DOMAINS:
        raise RunRequestError(
            f"domain 必须是 {sorted(VALID_DOMAINS)} 之一，收到 {domain!r}"
        )

    context = payload.get("context", {})
    options = payload.get("options", {})
    if not isinstance(context, dict):
        raise RunRequestError("context 必须是对象")
    if not isinstance(options, dict):
        raise RunRequestError("options 必须是对象")

    unknown_options = sorted(set(options) - _REQUEST_OPTION_KEYS)
    if unknown_options:
        raise RunRequestError("options 存在未知键：" + ", ".join(unknown_options))

    dispatch_mode = options.get("dispatch_mode", "main")
    if dispatch_mode not in _ALLOWED_DISPATCH_MODES:
        raise RunRequestError(
            f"options.dispatch_mode 必须是 {sorted(_ALLOWED_DISPATCH_MODES)} 之一"
        )
    grade_source = options.get("grade_source", "auto")
    if grade_source not in _ALLOWED_GRADE_SOURCES:
        raise RunRequestError(
            f"options.grade_source 必须是 {sorted(_ALLOWED_GRADE_SOURCES)} 之一"
        )
    permission_mode = options.get("permission_mode", "dontAsk")
    if permission_mode not in _ALLOWED_PERMISSION_MODES:
        raise RunRequestError(
            f"options.permission_mode 本版本只允许 {sorted(_ALLOWED_PERMISSION_MODES)}"
        )
    timeout_sec = options.get("timeout_sec", 300)
    if not isinstance(timeout_sec, (int, float)) or isinstance(timeout_sec, bool) or timeout_sec <= 0:
        raise RunRequestError("options.timeout_sec 必须是正数")

    return RunRequest(
        schema_version=SCHEMA_VERSION,
        request_id=request_id,
        case_id=case_id,
        domain=domain,
        question=question,
        context=dict(context),
        options={
            "dispatch_mode": dispatch_mode,
            "grade_source": grade_source,
            "timeout_sec": timeout_sec,
            "permission_mode": permission_mode,
        },
    )


# ---------------------------------------------------------------------------
# RunRecord：序列化 + 回读（未知字段容忍——只增不改的演进规则）
# ---------------------------------------------------------------------------


def record_to_json(record: RunRecord) -> dict[str, Any]:
    """按 schema §3.1 的字段顺序输出（两次序列化必须逐字节相等）。"""

    return {
        "schema_version": record.schema_version,
        "record_id": record.record_id,
        "request_id": record.request_id,
        "case": {"case_id": record.case_id, "domain": record.domain},
        "run": {
            "started_at": record.started_at,
            "finished_at": record.finished_at,
            "elapsed_sec": record.elapsed_sec,
        },
        "subject": dict(record.subject),
        "outcome": dict(record.outcome),
        "trace": None if record.trace is None else dict(record.trace),
        "mechanism": None if record.mechanism is None else dict(record.mechanism),
        "usage": dict(record.usage),
    }


def _normalize_usage(usage: Any) -> dict[str, Any]:
    """usage 的形状校验 + ``available=false ⇒ token 为 None`` 的契约落地。

    这条继承 ``evaluation/cost.py``：没采到的 token 必须是"不可得"（None），
    不许冒充 0——否则报告永远分不清"真省了"还是"没采到"。
    """

    if not isinstance(usage, dict):
        raise RunRecordError("usage 必须是对象")
    available = usage.get("available")
    if not isinstance(available, bool):
        raise RunRecordError("usage.available 必须是布尔值")

    token_keys = ("input_tokens", "output_tokens", "cached_input_tokens")
    normalized: dict[str, Any] = {}
    if available:
        for key in token_keys:
            value = usage.get(key)
            if value is not None and not isinstance(value, int):
                raise RunRecordError(f"usage.{key} 必须是整数或缺失")
            normalized[key] = value
    else:
        for key in token_keys:
            if usage.get(key) not in (None,):
                raise RunRecordError(
                    "usage.available=false 时 token 字段必须为 null（不许写 0）"
                )
            normalized[key] = None

    model_calls = usage.get("model_calls", 0)
    if not isinstance(model_calls, int) or isinstance(model_calls, bool) or model_calls < 0:
        raise RunRecordError("usage.model_calls 必须是非负整数")
    without = usage.get("calls_without_usage", 0)
    if not isinstance(without, int) or isinstance(without, bool) or without < 0:
        raise RunRecordError("usage.calls_without_usage 必须是非负整数")
    normalized["model_calls"] = model_calls
    normalized["calls_without_usage"] = without
    normalized["available"] = available
    return normalized


def _validate_outcome(outcome: Any) -> dict[str, Any]:
    if not isinstance(outcome, dict):
        raise RunRecordError("outcome 必须是对象")
    status = outcome.get("status")
    if status not in OUTCOME_STATUSES:
        raise RunRecordError(
            f"outcome.status 必须是 {sorted(OUTCOME_STATUSES)} 之一，收到 {status!r}"
        )
    return dict(outcome)


def record_from_json(payload: dict[str, Any]) -> RunRecord:
    """读 :class:`RunRecord`（schema_version 1）。

    未知顶层字段**容忍**（"只增不改"允许不升版本地加字段；读取方严格校验已知字段）；
    与 ``request_from_json`` 的不对称是有意的：request 是安全边界，record 是数据面。
    """

    if not isinstance(payload, dict):
        raise RunRecordError("RunRecord 载荷必须是 JSON 对象")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise RunRecordError(
            f"schema_version 必须是 {SCHEMA_VERSION}，收到 {payload.get('schema_version')!r}"
        )

    case = payload.get("case")
    if not isinstance(case, dict):
        raise RunRecordError("case 必须是对象")
    case_id = case.get("case_id")
    domain = case.get("domain")
    if not isinstance(case_id, str) or not case_id:
        raise RunRecordError("case.case_id 必须是非空字符串")
    if domain not in VALID_DOMAINS:
        raise RunRecordError(f"case.domain 非法：{domain!r}")

    run = payload.get("run")
    if not isinstance(run, dict):
        raise RunRecordError("run 必须是对象")
    started_at = run.get("started_at")
    finished_at = run.get("finished_at")
    if not isinstance(started_at, str) or not started_at:
        raise RunRecordError("run.started_at 必须是非空字符串")
    if not isinstance(finished_at, str) or not finished_at:
        raise RunRecordError("run.finished_at 必须是非空字符串")
    elapsed = run.get("elapsed_sec")
    if not isinstance(elapsed, (int, float)) or isinstance(elapsed, bool) or elapsed < 0:
        raise RunRecordError("run.elapsed_sec 必须是非负数")

    record_id = payload.get("record_id")
    request_id = payload.get("request_id")
    if not isinstance(record_id, str) or not record_id:
        raise RunRecordError("record_id 必须是非空字符串")
    if not isinstance(request_id, str) or not request_id:
        raise RunRecordError("request_id 必须是非空字符串")

    trace = payload.get("trace")
    if trace is not None and not isinstance(trace, dict):
        raise RunRecordError("trace 必须是对象或 null")
    mechanism = payload.get("mechanism")
    if mechanism is not None and not isinstance(mechanism, dict):
        raise RunRecordError("mechanism 必须是对象或 null")

    subject = payload.get("subject")
    if not isinstance(subject, dict):
        raise RunRecordError("subject 必须是对象")

    return RunRecord(
        schema_version=SCHEMA_VERSION,
        record_id=record_id,
        request_id=request_id,
        case_id=case_id,
        domain=domain,
        started_at=started_at,
        finished_at=finished_at,
        elapsed_sec=float(elapsed),
        subject=dict(subject),
        outcome=_validate_outcome(payload.get("outcome")),
        trace=None if trace is None else dict(trace),
        mechanism=None if mechanism is None else dict(mechanism),
        usage=_normalize_usage(payload.get("usage")),
    )
