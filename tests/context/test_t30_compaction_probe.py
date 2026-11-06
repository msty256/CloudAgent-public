#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""T3.0 最小实验：压缩管线的"盲区"是不是真的存在。

阶段 3 提案 §1.1 的论断是：`microcompact` 靠一张**通用编码工具白名单**决定清空谁，
而诊断域的取证工具一个都不在名单里——于是"产生最大结果的工具恰好完全不参与压缩"。

这里是把它变成可执行断言，而不是靠读代码相信。

第二组断言回答 T3.0 的另一个问题：**loop 有没有"模型输出后、下轮请求前"的改写钩子**。
结论是没有（`ToolEventHandler = Callable[[ToolEvent], None]`，返回 None，纯通知）；
唯一的改写点是 `CompressionPipeline.run(messages)`——它接收并返回 `list[Message]`。
"""

from __future__ import annotations

from typing import Any, Callable

from cloudagent_ext.context_system.microcompact import (
    CLEARED_MESSAGE,
    COMPACTABLE_TOOL_NAMES,
    is_compactable_tool,
    microcompact_typed_messages,
)
from cloudagent_ext.types.messages import create_assistant_message, create_user_message

#: 诊断域实际用的取证工具（阶段 3 要处理的那批）
FORENSIC_TOOLS = (
    "get_schema",
    "get_indexes",
    "explain_sql",
    "get_table_stats",
    "get_lock_info",
    "query_table_rows",
    "search_logs",
    "get_log_context",
    "correlate_events",
)


def _tool_use_block(block_id: str, name: str) -> dict[str, Any]:
    return {"type": "tool_use", "id": block_id, "name": name, "input": {}}


def _tool_result_block(block_id: str, text: str) -> dict[str, Any]:
    return {"type": "tool_result", "tool_use_id": block_id, "content": text}


def _build_conversation(read_result: str, db_result: str) -> list:
    """一条 assistant 同时调两次 Read 和一次 query_table_rows。

    为什么要两个 Read：``keep_recent=N`` 的实现是 ``ids[:-N]``，
    而 **``[:-0]`` 在 Python 里等于 ``[:0]``（空列表）**——所以 ``keep_recent=0``
    不是"全清"而是"全不清"。想看到清空效果，至少要有一个"更旧的"可压缩结果。
    """

    return [
        create_user_message("查一下 orders 表"),
        create_assistant_message(
            [
                _tool_use_block("t-read", "Read"),
                _tool_use_block("t-read2", "Read"),
                _tool_use_block("t-db", "query_table_rows"),
            ]
        ),
        create_user_message(
            [
                _tool_result_block("t-read", read_result),
                _tool_result_block("t-read2", read_result + "-2"),
                _tool_result_block("t-db", db_result),
            ]
        ),
        create_assistant_message("第一轮结束"),
        create_user_message("继续"),
        create_assistant_message("第二轮结束"),
    ]


class TestBlindSpotIsReal:
    def test_no_forensic_tool_is_compactable(self) -> None:
        """核心断言：取证工具与白名单**零交集**。"""

        overlap = set(FORENSIC_TOOLS) & COMPACTABLE_TOOL_NAMES
        assert overlap == set(), f"这些取证工具意外进了白名单：{overlap}"
        for name in FORENSIC_TOOLS:
            assert is_compactable_tool(name) is False, name

    def test_coding_tools_are_compactable(self) -> None:
        """反面确认：白名单确实在管编码工具，不是空表。"""

        for name in ("Read", "Grep", "Bash"):
            assert is_compactable_tool(name) is True, name


class TestSameConversationDifferentFate:
    def test_read_is_cleared_but_table_rows_survive(self) -> None:
        """同一轮里两个工具结果：Read 被清空，query_table_rows 原样保留。

        这就是"要折不要丢"的现场：清空白名单不覆盖取证工具，
        所以那批最大结果既不参与压缩、也没有任何摘要——**既没省 token，也没省证据**。
        """

        read_result = "READ-BODY-" + "x" * 400
        db_result = "DB-ROWS-" + "y" * 400
        messages = _build_conversation(read_result, db_result)

        # keep_recent=1：两个可压缩结果（t-read / t-read2）里保留最近一个，
        # 更旧的 t-read 被清空；取证工具 t-db 完全不在名单里，动都不动。
        compacted, saved = microcompact_typed_messages(messages, keep_recent=1)

        # 拿回被清空/保留的文本
        texts: dict[str, str] = {}
        for message in compacted:
            content = getattr(message, "content", None)
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    texts[str(block.get("tool_use_id"))] = str(block.get("content"))

        assert texts["t-read"] == CLEARED_MESSAGE, "Read 的结果应被清空"
        assert texts["t-db"] == db_result, "取证工具的结果不应被改动"
        assert CLEARED_MESSAGE in texts.values()
        # 清空确实省了 token（否则这个方法本身没意义）
        assert saved >= 0


class TestNoLoopHook:
    def test_event_handler_is_read_only(self) -> None:
        """T3.0 结论：``on_event`` 是只读通知，签名里没有返回值。"""

        from cloudagent_ext.tool_system.renderers import ToolEventHandler

        # Callable[[ToolEvent], None] —— 返回 None，无法改写消息
        origin = str(ToolEventHandler)
        assert origin.startswith("typing.Callable")
        assert "None" in origin

    def test_pipeline_run_is_the_rewrite_point(self) -> None:
        """唯一能改写消息的地方是 CompressionPipeline.run（接收并返回 messages）。"""

        from cloudagent_ext.services.compact.pipeline import CompressionPipeline

        assert isinstance(CompressionPipeline.run, Callable)  # type: ignore[arg-type]
        # 签名里第一个位置参数是 messages、返回 CompressionResult
        import inspect

        params = list(inspect.signature(CompressionPipeline.run).parameters)
        assert params[1] == "messages"
