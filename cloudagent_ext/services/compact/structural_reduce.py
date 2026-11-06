#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""把结构归约接进消息列表（阶段 3 · T3.3 的接入层）。

职责边界很清楚：

* **本模块**：遍历消息、识别取证工具结果、调归约器、写句柄、替换成"摘要 + 句柄"；
* ``context_system/reducers.py``：只做纯归约，不知道消息、不知道磁盘；
* ``services/compact/evidence_store.py``：只管存取。

三层分开的好处是每一层都能单独测——归约器不用造假文件系统，
存储层不用造消息。

**三条硬约束（都来自提案）**：

1. **绝不退回 `[Old tool result content cleared]`**：归约失败就原样保留。
   清空是"丢证据"，而 `pipeline.py:270-273` 的注释已经记着这件事的后果——
   模型被告知"参考之前的内容"，而那份内容已经被 erasure 掉了，于是它只好重新 `cat`。
2. **不动 `COMPACTABLE_TOOL_NAMES`**：那张表的语义是清空，和这里正交。
3. **句柄写失败就不写句柄**：留一个取不回来的句柄比没有更糟。

**幂等**：已经带 ``[已归约]`` 前缀的结果直接跳过——否则每轮压缩都重折一遍，
既浪费又会让摘要层层嵌套。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from cloudagent_ext.context_system.reducers import (
    reduce_log_block,
    reduce_sql_rows,
    render_summary,
)
from cloudagent_ext.services.compact.evidence_store import EvidenceStore
from cloudagent_ext.types.content_blocks import ToolResultBlock
from cloudagent_ext.types.messages import UserMessage

__all__ = [
    "FORENSIC_TOOL_NAMES",
    "REDUCED_MARKER",
    "ReduceOutcome",
    "reduce_forensic_messages",
]

logger = logging.getLogger("cloudagent.compact.structural_reduce")

#: 取证类工具：它们的结果是"一次性取到的证据"，该折不该丢。
#: **刻意不包含** `Read` / `Grep` / `Bash`——那些是可重新获得的中间产物，
#: 交给 `microcompact` 的清空语义处理即可（两边职责不重叠）。
FORENSIC_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "query_table_rows",
        "get_schema",
        "get_indexes",
        "explain_sql",
        "get_table_stats",
        "get_lock_info",
        "search_logs",
        "get_log_context",
        "correlate_events",
        "parse_stack_trace",
    }
)

#: 幂等标记：带这个前缀的结果不再重折
REDUCED_MARKER = "[已归约]"

#: 归档失败时的尾注（**不写句柄**，见提案 §2.3 的"不传播"）
_NO_HANDLE_NOTE = "（原文未归档；如需细节请重新取证）"


@dataclass
class ReduceOutcome:
    """一次接入的统计（直接进 meta 用）。"""

    messages: list[Any] = field(default_factory=list)
    reduced_count: int = 0
    handles: list[str] = field(default_factory=list)
    failures: int = 0
    chars_before: int = 0
    chars_after: int = 0

    @property
    def saved_chars(self) -> int:
        return max(self.chars_before - self.chars_after, 0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "reduced_count": self.reduced_count,
            "handles": list(self.handles),
            "failures": self.failures,
            "chars_before": self.chars_before,
            "chars_after": self.chars_after,
            "saved_chars": self.saved_chars,
        }


def _tool_use_names(messages: list[Any]) -> dict[str, str]:
    """tool_use_id → 工具名（从 assistant 消息里收集）。"""

    names: dict[str, str] = {}
    for message in messages:
        if getattr(message, "role", "") != "assistant":
            continue
        content = getattr(message, "content", None)
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                tool_id = str(block.get("id") or "")
                if tool_id:
                    names[tool_id] = str(block.get("name") or "")
            else:
                tool_id = str(getattr(block, "id", "") or "")
                name = str(getattr(block, "name", "") or "")
                if tool_id and name:
                    names[tool_id] = name
    return names


def _text_of(block: Any) -> str | None:
    content = block.get("content") if isinstance(block, dict) else getattr(block, "content", None)
    return content if isinstance(content, str) else None


def _structured_output(block: Any, text: str) -> Any:
    """尽量拿到结构化 output：优先 ``metadata.output``，否则尝试解析文本。"""

    metadata = block.get("metadata") if isinstance(block, dict) else getattr(block, "metadata", None)
    if isinstance(metadata, dict):
        output = metadata.get("output")
        if isinstance(output, dict):
            return output
    stripped = text.lstrip()
    if stripped.startswith("{"):
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _reduce_one(text: str, output: Any) -> Any:
    """按内容分派归约器；认不出来返回 ``None``。"""

    if isinstance(output, dict):
        reduced = reduce_sql_rows(output)
        if reduced is not None:
            return reduced
    return reduce_log_block(text)


def _replacement(summary: str, *, original_chars: int, handle: str | None) -> str:
    if handle:
        note = (
            f"（原文 {original_chars} 字符已归档为 {handle}；"
            f"需要细节时用 recall_evidence 取回）"
        )
    else:
        note = _NO_HANDLE_NOTE
    return f"{summary}\n\n{note}"


def reduce_forensic_messages(
    messages: list[Any],
    *,
    store: EvidenceStore | None,
    session_id: str,
    min_chars: int = 4_000,
    max_items: int = 8,
    keep_recent: int = 2,
) -> ReduceOutcome:
    """把消息里的取证结果折成摘要（**不抛异常**）。

    ``min_chars`` 是"值不值得归档"的门槛：太短的结果存句柄不划算，
    而且摘要未必比原文短。默认 4000 字符（约 1–2k token）。

    ``max_items`` 限制一轮最多折几条——改历史消息会让 prompt cache 失效，
    一次改太多等于把缓存全废掉。

    ``keep_recent`` 是**最新 N 条取证结果不折**。这一条是补出来的坑：压缩发生在
    "每轮请求前"，如果连当轮刚查到的那条也折掉，模型就看不到明细了——
    省 token 变成了拿诊断质量换。默认保留 2 条（当轮 + 上一条）。

    ⚠️ ``keep_recent=0`` 不能靠切片实现：Python 里 ``xs[:-0]`` 等于 ``xs[:0]``（空列表），
    所以"全折"必须显式判断，否则会静默变成"全不折"。`microcompact` 那边踩过同一个坑。
    """

    outcome = ReduceOutcome(messages=list(messages))
    if max_items <= 0 or not messages:
        return outcome

    tool_names = _tool_use_names(messages)
    if not tool_names:
        return outcome

    # ---- 第一遍：收集候选（位置 → 内容），不修改任何东西 ----
    candidates: list[dict[str, Any]] = []
    for msg_index, message in enumerate(messages):
        content = getattr(message, "content", None)
        if getattr(message, "role", "") != "user" or not isinstance(content, list):
            continue
        for block_index, block in enumerate(content):
            kind = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
            if kind != "tool_result":
                continue
            tool_id = str(
                block.get("tool_use_id")
                if isinstance(block, dict)
                else getattr(block, "tool_use_id", "")
            )
            tool_name = tool_names.get(tool_id, "")
            text = _text_of(block)
            if (
                tool_name not in FORENSIC_TOOL_NAMES
                or text is None
                or len(text) < min_chars
                or text.lstrip().startswith(REDUCED_MARKER)
            ):
                continue
            candidates.append(
                {
                    "msg_index": msg_index,
                    "block_index": block_index,
                    "tool_name": tool_name,
                    "text": text,
                    "block": block,
                }
            )

    if not candidates:
        return outcome

    # ---- 决定折哪些：保护最新 keep_recent 条，再从旧到新取前 max_items 条 ----
    if keep_recent > 0 and len(candidates) > keep_recent:
        reducible = candidates[:-keep_recent]
    elif keep_recent <= 0:
        reducible = candidates  # 显式分支：避免 [:-0] 的空列表陷阱
    else:
        reducible = []  # 候选还不够 keep_recent 条，全部保留

    selected = {item["msg_index"]: set() for item in reducible[:max_items]}
    for item in reducible[:max_items]:
        selected[item["msg_index"]].add(item["block_index"])

    by_position = {(item["msg_index"], item["block_index"]): item for item in candidates}

    # ---- 第二遍：按位置替换 ----
    result: list[Any] = []
    for msg_index, message in enumerate(messages):
        targets = selected.get(msg_index)
        content = getattr(message, "content", None)
        if not targets or not isinstance(content, list):
            result.append(message)
            continue

        new_content: list[Any] = []
        changed = False
        for block_index, block in enumerate(content):
            if block_index not in targets:
                new_content.append(block)
                continue

            item = by_position[(msg_index, block_index)]
            output = _structured_output(item["block"], item["text"])
            try:
                reduced = _reduce_one(item["text"], output)
            except Exception:  # noqa: BLE001 — 归约失败按"没折"处理
                logger.debug("structural reduce failed for %s", item["tool_name"], exc_info=True)
                reduced = None

            if reduced is None:
                # 折不动 → 原样保留（**不**退回清空语义）
                outcome.failures += 1
                new_content.append(block)
                continue

            summary = render_summary(reduced)
            if not summary:
                outcome.failures += 1
                new_content.append(block)
                continue

            handle = None
            if store is not None and session_id:
                handle = store.save(
                    session_id=session_id,
                    domain=_domain_bucket(item["tool_name"]),
                    tool=item["tool_name"],
                    payload=item["text"],
                )
            if handle:
                outcome.handles.append(handle)

            replacement = _replacement(
                summary, original_chars=len(item["text"]), handle=handle
            )
            outcome.chars_before += len(item["text"])
            outcome.chars_after += len(replacement)
            outcome.reduced_count += 1
            changed = True
            new_content.append(_rebuild_block(block, replacement))

        result.append(_rebuild_message(message, new_content) if changed else message)

    outcome.messages = result
    return outcome


def _domain_bucket(tool_name: str) -> str:
    """句柄里的域桶：按工具归类（不是诊断域，别和 ``ev:sql:1`` 混了）。"""

    if tool_name in {"search_logs", "get_log_context", "correlate_events", "parse_stack_trace"}:
        return "log"
    if tool_name in {"query_table_rows", "get_schema", "get_indexes", "explain_sql",
                     "get_table_stats", "get_lock_info"}:
        return "db"
    return "misc"


def _rebuild_block(block: Any, text: str) -> Any:
    if isinstance(block, dict):
        return {**block, "content": text}
    return ToolResultBlock(
        tool_use_id=getattr(block, "tool_use_id", ""),
        content=text,
        is_error=bool(getattr(block, "is_error", False)),
        metadata=dict(getattr(block, "metadata", {}) or {}),
    )


def _rebuild_message(message: Any, content: list[Any]) -> Any:
    return UserMessage(
        content=content,
        uuid=getattr(message, "uuid", None),
        timestamp=getattr(message, "timestamp", None),
        isMeta=bool(getattr(message, "isMeta", False)),
    )
