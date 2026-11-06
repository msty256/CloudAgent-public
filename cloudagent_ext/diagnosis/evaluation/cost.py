#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""token / cache 用量归一与聚合（阶段 0 · T0.2）。

**为什么单独一个模块**：`_RecordingProvider` 早就把每次模型调用的 ``usage`` 原始字典记下来了
（``executors.py:213-230``），但从来没人聚合——于是报告里没有 token，也看不出
prompt cache 有没有命中。不同 provider 的键名还不一样，所以这里做两件事：

1. **键名归一**：把 OpenAI 风格（``prompt_tokens`` / ``completion_tokens`` / 嵌套
   ``prompt_tokens_details.cached_tokens``）与 Anthropic 风格
   （``input_tokens`` / ``output_tokens`` / ``cache_read_input_tokens``）映射到同一组字段；
2. **如实计数**：认不出的 usage **不能静默当 0**——否则"某臂省了 token"可能是
   根本没采到。这里用 ``calls_without_usage`` 与 ``available`` 把"不可得"显性标出来。
"""

from __future__ import annotations

from typing import Any, Iterable

__all__ = [
    "INPUT_KEYS",
    "OUTPUT_KEYS",
    "CACHE_KEYS",
    "summarize_usage",
    "sum_usage_summaries",
]

#: 输入 token 的候选键（按优先级）
INPUT_KEYS: tuple[str, ...] = ("input_tokens", "prompt_tokens")
#: 输出 token 的候选键
OUTPUT_KEYS: tuple[str, ...] = ("output_tokens", "completion_tokens")
#: 缓存命中 token 的候选键（含嵌套路径，用 ``.`` 分隔）
CACHE_KEYS: tuple[str, ...] = (
    "cache_read_input_tokens",
    "prompt_cache_hit_tokens",
    "cached_tokens",
    "prompt_tokens_details.cached_tokens",
)


def _as_mapping(usage: Any) -> dict[str, Any]:
    """把 usage 统一成 dict（可能是 pydantic 模型 / SimpleNamespace / None）。"""

    if usage is None:
        return {}
    if isinstance(usage, dict):
        return usage
    dump = getattr(usage, "model_dump", None)
    if callable(dump):
        try:
            data = dump()
            return data if isinstance(data, dict) else {}
        except Exception:  # noqa: BLE001 — 归一失败按"没有 usage"处理
            return {}
    if hasattr(usage, "__dict__"):
        return {k: v for k, v in vars(usage).items() if not k.startswith("_")}
    return {}


def _lookup(usage: dict[str, Any], path: str) -> int | None:
    """按 ``a.b.c`` 路径取一个非负整数；取不到或不是数字返回 ``None``。"""

    node: Any = usage
    for part in path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    if isinstance(node, bool):  # bool 是 int 的子类，单独排除
        return None
    if isinstance(node, int):
        return node if node >= 0 else None
    if isinstance(node, float) and node >= 0:
        return int(node)
    return None


def _first(usage: dict[str, Any], keys: Iterable[str]) -> tuple[int | None, str]:
    for key in keys:
        value = _lookup(usage, key)
        if value is not None:
            return value, key
    return None, ""


def summarize_usage(calls: Iterable[Any]) -> dict[str, Any]:
    """聚合一组 ``_RecordingProvider.calls`` 的 token 用量。

    ``calls`` 里每项是 ``{"usage": <原始 usage>}`` 形状；缺失或为 None 都算"没采到"。
    """

    input_tokens = 0
    output_tokens = 0
    cached_tokens = 0
    with_usage = 0
    without_usage = 0
    cache_field = ""

    for call in calls or []:
        usage = _as_mapping(call.get("usage") if isinstance(call, dict) else None)
        if not usage:
            without_usage += 1
            continue
        with_usage += 1

        value, _ = _first(usage, INPUT_KEYS)
        if value is not None:
            input_tokens += value
        value, _ = _first(usage, OUTPUT_KEYS)
        if value is not None:
            output_tokens += value
        value, key = _first(usage, CACHE_KEYS)
        if value is not None:
            cached_tokens += value
            cache_field = key

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        # 缓存命中已计入输入侧，不再重复加到 total
        "cached_input_tokens": cached_tokens,
        "total_tokens": input_tokens + output_tokens,
        "calls_with_usage": with_usage,
        "calls_without_usage": without_usage,
        # "" 表示本批次没有任何一次调用返回缓存字段 → 报告里应写"不可得"而不是 0
        "cache_field": cache_field,
        "available": with_usage > 0,
    }


def sum_usage_summaries(items: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """把多个 :func:`summarize_usage` 的结果相加（跨 case / 跨轮聚合用）。"""

    total = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cached_input_tokens": 0,
        "total_tokens": 0,
        "calls_with_usage": 0,
        "calls_without_usage": 0,
        "cache_field": "",
        "available": False,
    }
    for item in items or []:
        if not isinstance(item, dict):
            continue
        for key in (
            "input_tokens",
            "output_tokens",
            "cached_input_tokens",
            "total_tokens",
            "calls_with_usage",
            "calls_without_usage",
        ):
            try:
                total[key] += int(item.get(key) or 0)
            except (TypeError, ValueError):
                continue
        if not total["cache_field"] and item.get("cache_field"):
            total["cache_field"] = str(item["cache_field"])
        total["available"] = total["available"] or bool(item.get("available"))
    return total
