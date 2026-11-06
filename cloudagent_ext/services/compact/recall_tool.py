#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""召回工具 ``recall_evidence``（阶段 3 · T3.4）。

压缩把取证结果折成摘要后，原文归档在本地，句柄写进摘要。这个工具就是"取回"的那一端。

**为什么是工具而不是自动注入**（T3.0 的结论）：

压缩那一刻**不知道模型下一步想看什么**——注入式只能猜着塞回去，猜错就是纯浪费。
工具式把"要不要取、取哪条"交还给模型，而且调用天然带句柄参数，可观测、可计数。

**为什么取不到要明确说"别重试"**：

归档可能因为清理、跨会话、文件损坏而失效。如果只返回一句"失败"，模型大概率会
换个句柄再试一次、再试一次——白烧轮次。所以错误结果里写清"这条取不回来了，
请重新取证"，把死路堵死。
"""

from __future__ import annotations

import json
from typing import Any

from cloudagent_ext.services.compact.evidence_store import (
    EvidenceStore,
    parse_handle,
    resolve_session_id,
)
from cloudagent_ext.tool_system.build_tool import Tool, ToolResult, build_tool

__all__ = [
    "RECALL_TOOL_NAME",
    "REQUIRED_AGENT_TOOL_SETS",
    "MAX_RECALL_CHARS",
    "recall_evidence_tool",
    "register_recall_tool",
    "provision_with_recall",
]

RECALL_TOOL_NAME: str = "recall_evidence"

#: 单次召回的返回上限（原文上限本来就是 4MB，这里防的是一次灌爆上下文）
MAX_RECALL_CHARS: int = 60_000

#: 需要这个工具的白名单（诊断子代理）。主 Agent 不在其中——它没有句柄。
REQUIRED_AGENT_TOOL_SETS: tuple[str, ...] = (
    "TOOL_SET_CODE_DIAGNOSIS",
    "TOOL_SET_LOG_DIAGNOSIS",
    "TOOL_SET_SQL_DIAGNOSIS",
)

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "handle": {
            "type": "string",
            "description": "摘要里给出的证据句柄，形如 evh:db:1",
        }
    },
    "required": ["handle"],
}

_DESCRIPTION = (
    "取回被压缩归档的取证结果原文。当摘要不足以判断、需要看完整行集/日志细节时调用。"
)


def _error_result(message: str, *, handle: str = "") -> ToolResult:
    return ToolResult(
        name=RECALL_TOOL_NAME,
        output={
            "status": "error",
            "error": message,
            "handle": handle,
        },
        is_error=True,
    )


def _recall_call(tool_input: dict[str, Any], context: Any) -> ToolResult:
    handle = str(tool_input.get("handle") or "").strip()
    if parse_handle(handle) is None:
        return _error_result(
            f"句柄格式不正确：{handle!r}。正确形如 evh:db:1；"
            "如果摘要里没有句柄，说明这条原文没有被归档，请重新取证。",
            handle=handle,
        )

    session_id = resolve_session_id(context)
    if not session_id:
        return _error_result(
            "当前会话没有归档目录标识，无法取回原文。请重新取证。", handle=handle
        )

    # 根目录也要和写入端一致：配置了 evidence_root 就用它，否则走默认目录。
    # 这一步和 session_id 是同一类要求——**存和取必须看到同一组坐标**。
    root = getattr(context, "evidence_root", None)
    store = EvidenceStore(root=root) if root else EvidenceStore()

    text = store.load(session_id, handle)
    if text is None:
        return _error_result(
            f"句柄 {handle} 取不到原文（可能已被清理、或不属于本次会话）。"
            "**不要重复尝试同一个句柄**，请重新取证。",
            handle=handle,
        )

    truncated = False
    if len(text) > MAX_RECALL_CHARS:
        text = text[:MAX_RECALL_CHARS]
        truncated = True

    return ToolResult(
        name=RECALL_TOOL_NAME,
        output={
            "status": "success",
            "handle": handle,
            "content": text,
            "chars": len(text),
            "truncated": truncated,
        },
    )


recall_evidence_tool: Tool = build_tool(
    name=RECALL_TOOL_NAME,
    input_schema=_INPUT_SCHEMA,
    call=_recall_call,
    description=_DESCRIPTION,
    max_result_size_chars=MAX_RECALL_CHARS + 2_000,
)


def register_recall_tool(registry: Any) -> bool:
    """把召回工具注册进 *registry*（幂等；失败返回 ``False``，不抛）。

    只做"注册"，**不改白名单**——白名单在 ``agent/policy.py`` 里，
    由各诊断子代理的 ``TOOL_SET_*`` 决定可见性。
    """

    try:
        if registry.get(RECALL_TOOL_NAME) is not None:
            return True
        registry.register(recall_evidence_tool)
        return registry.get(RECALL_TOOL_NAME) is not None
    except Exception:  # noqa: BLE001 — 装配失败由调用方降级
        return False


def provision_with_recall(provision: Any, registry: Any) -> bool:
    """先跑域自己的装配，再补召回工具。

    单独包一层的原因：域注册函数里常有"已装配就 return True"的早退，
    直接在里面加一行会漏掉早退路径——第二次装配时召回工具就悄悄没了。
    """

    try:
        ok = bool(provision(registry))
    except Exception:  # noqa: BLE001 — 域装配失败不该影响召回装配
        ok = False
    registered = register_recall_tool(registry)
    return ok and registered
