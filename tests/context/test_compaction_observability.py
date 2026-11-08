#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""压缩观测测试（阶段 3 · T3.5）。

观测的意义不在于"有字段"，而在于**这组字段放在一起能不能戳穿假象**：

* 只看"折了几条"→ 一个折完就取不回的管线也会显得很漂亮；
* 加上"取回未命中几次"→ 假象立刻破。

所以这里除了"字段被写回"，还专门测**未命中计数**的口径。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from cloudagent_ext.diagnosis.eval_support.execute import _recall_stats
from cloudagent_ext.services.compact.pipeline import CompressionPipeline, PipelineConfig
from cloudagent_ext.types.messages import create_assistant_message, create_user_message


def _payload(rows: int = 200) -> dict:
    return {
        "mode": "rows",
        "table": "public.orders",
        "target": "primary",
        "returned": rows,
        "rows": [{"id": i, "amount": float(i * 10)} for i in range(1, rows + 1)],
    }


def _conversation() -> list:
    payload = _payload()
    return [
        create_user_message("查 orders"),
        create_assistant_message(
            [{"type": "tool_use", "id": "t1", "name": "query_table_rows", "input": {}}]
        ),
        create_user_message(
            [
                {
                    "type": "tool_result",
                    "tool_use_id": "t1",
                    "content": json.dumps(payload, ensure_ascii=False),
                    "metadata": {"output": payload},
                }
            ]
        ),
    ]


class TestStatsPublished:
    def test_sink_receives_stats(self, tmp_path: Path) -> None:
        sink = SimpleNamespace(compaction_stats=None)
        config = PipelineConfig(
            sr_enabled=True,
            sr_session_id="req-1",
            sr_evidence_root=tmp_path,
            sr_keep_recent=0,
            stats_sink=sink,
        )
        asyncio.run(CompressionPipeline(config).run(_conversation(), input_token_count=0))

        stats = sink.compaction_stats
        assert stats is not None
        assert stats["reduced_count"] == 1
        assert stats["handles"]
        assert stats["saved_chars"] > 0

    def test_no_sink_is_safe(self, tmp_path: Path) -> None:
        config = PipelineConfig(
            sr_enabled=True, sr_session_id="req-1", sr_evidence_root=tmp_path, sr_keep_recent=0
        )
        result = asyncio.run(CompressionPipeline(config).run(_conversation(), input_token_count=0))
        assert result.reduce_stats["reduced_count"] == 1  # 返回值里照样有

    def test_sink_without_slot_is_safe(self, tmp_path: Path) -> None:
        """sink 是 slots 类且没有该字段时，不能把管线带崩。"""

        class _Slots:
            __slots__ = ("other",)

            def __init__(self) -> None:
                self.other = 1

        config = PipelineConfig(
            sr_enabled=True,
            sr_session_id="req-1",
            sr_evidence_root=tmp_path,
            sr_keep_recent=0,
            stats_sink=_Slots(),
        )
        result = asyncio.run(CompressionPipeline(config).run(_conversation(), input_token_count=0))
        assert result.reduce_stats["reduced_count"] == 1

    def test_disabled_publishes_nothing(self, tmp_path: Path) -> None:
        sink = SimpleNamespace(compaction_stats=None)
        config = PipelineConfig(sr_enabled=False, stats_sink=sink)
        asyncio.run(CompressionPipeline(config).run(_conversation(), input_token_count=0))
        assert sink.compaction_stats is None


class TestRecallStats:
    def test_counts_calls(self) -> None:
        uses = [
            {"id": "a", "name": "recall_evidence"},
            {"id": "b", "name": "query_table_rows"},
            {"id": "c", "name": "recall_evidence"},
        ]
        assert _recall_stats(uses, []) == (2, 0)

    def test_counts_misses_only_for_recall(self) -> None:
        uses = [{"id": "a", "name": "recall_evidence"}, {"id": "b", "name": "Read"}]
        events = [
            SimpleNamespace(kind="tool_result", tool_use_id="a", is_error=True),   # 召回失败
            SimpleNamespace(kind="tool_result", tool_use_id="b", is_error=True),   # 别的工具失败，不算
            SimpleNamespace(kind="tool_use", tool_use_id="a", is_error=False),
        ]
        assert _recall_stats(uses, events) == (1, 1)

    def test_no_recall(self) -> None:
        assert _recall_stats([{"id": "a", "name": "Read"}], []) == (0, 0)
