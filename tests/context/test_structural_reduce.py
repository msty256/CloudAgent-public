#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""结构归约接入层的测试（阶段 3 · T3.3）。

接入层最容易犯的错是**越界**：为了"省 token"把结果清空。
所以这里有一组专门的"不许发生"用例：

* 归约失败不得退回 ``[Old tool result content cleared]``（那是丢证据）；
* 非取证工具（``Read``/``Grep``）的结果一个字都不许动——它们归 microcompact 管；
* 已经折过的结果不得二次折叠（幂等）；
* 归档失败时**不得写出句柄**（留一个取不回的句柄比没有更糟）。

另一半是正向用例：折完之后摘要里有离群值、句柄能取回完整原文。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cloudagent_ext.context_system.microcompact import CLEARED_MESSAGE
from cloudagent_ext.services.compact.evidence_store import EvidenceStore
from cloudagent_ext.services.compact.structural_reduce import (
    FORENSIC_TOOL_NAMES,
    REDUCED_MARKER,
    reduce_forensic_messages,
)
from cloudagent_ext.types.messages import create_assistant_message, create_user_message

SESSION = "req-1"


def _payload(rows: int = 200, *, outlier: bool = True) -> dict:
    return {
        "mode": "rows",
        "table": "public.orders",
        "target": "primary",
        "returned": rows,
        "truncated": True,
        "rows": [
            {
                "id": index,
                "order_no": f"order-{index}",
                "amount": 999_999.0 if (outlier and index == rows // 2) else float(index * 10),
                "status": "paid" if index % 2 else "pending",
            }
            for index in range(1, rows + 1)
        ],
    }


def _conversation(*, tool: str = "query_table_rows", payload: dict | None = None,
                  text: str | None = None, history: int = 2) -> list:
    payload = payload if payload is not None else _payload()
    body = text if text is not None else json.dumps(payload, ensure_ascii=False)
    messages = [
        create_user_message("查一下 orders"),
        create_assistant_message([{"type": "tool_use", "id": "t1", "name": tool, "input": {}}]),
        create_user_message(
            [{"type": "tool_result", "tool_use_id": "t1", "content": body, "metadata": {"output": payload}}]
        ),
    ]
    for index in range(history):
        messages.append(create_assistant_message(f"第 {index} 轮"))
        messages.append(create_user_message(f"继续 {index}"))
    return messages


def _result_texts(messages) -> list[str]:
    texts: list[str] = []
    for message in messages:
        content = getattr(message, "content", None)
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                texts.append(str(block.get("content")))
            elif getattr(block, "type", "") == "tool_result":
                texts.append(str(getattr(block, "content", "")))
    return texts


@pytest.fixture()
def store(tmp_path: Path) -> EvidenceStore:
    return EvidenceStore(root=tmp_path / "evidence")


class TestReducesForensicResults:
    def test_replaces_with_summary_and_handle(self, store: EvidenceStore) -> None:
        messages = _conversation()
        outcome = reduce_forensic_messages(messages, store=store, session_id=SESSION, min_chars=1000, keep_recent=0)

        assert outcome.reduced_count == 1
        assert len(outcome.handles) == 1
        assert outcome.saved_chars > 0

        text = _result_texts(outcome.messages)[0]
        assert text.startswith(REDUCED_MARKER)
        assert outcome.handles[0] in text

    def test_outlier_survives_reduction(self, store: EvidenceStore) -> None:
        messages = _conversation()
        outcome = reduce_forensic_messages(messages, store=store, session_id=SESSION, min_chars=1000, keep_recent=0)
        text = _result_texts(outcome.messages)[0]
        assert "999999" in text, "离群值被摘要吃掉了"

    def test_handle_returns_full_original(self, store: EvidenceStore) -> None:
        messages = _conversation()
        original = _result_texts(messages)[0]
        outcome = reduce_forensic_messages(messages, store=store, session_id=SESSION, min_chars=1000, keep_recent=0)

        loaded = store.load(SESSION, outcome.handles[0])
        assert loaded == original

    def test_idempotent(self, store: EvidenceStore) -> None:
        messages = _conversation()
        first = reduce_forensic_messages(messages, store=store, session_id=SESSION, min_chars=1000, keep_recent=0)
        second = reduce_forensic_messages(
            first.messages, store=store, session_id=SESSION, min_chars=1000, keep_recent=0
        )
        assert first.reduced_count == 1
        assert second.reduced_count == 0, "已经折过的结果被二次折叠"
        assert second.handles == []


class TestMustNotClear:
    def test_unreducible_result_kept_verbatim(self, store: EvidenceStore) -> None:
        """取证工具但折不动（行数太少）→ 原样保留，绝不清空。"""

        small = _payload(rows=3)
        messages = _conversation(payload=small, text="x" * 5000 + json.dumps(small, ensure_ascii=False))
        outcome = reduce_forensic_messages(messages, store=store, session_id=SESSION, min_chars=1000, keep_recent=0)

        assert outcome.reduced_count == 0
        assert outcome.failures == 1
        text = _result_texts(outcome.messages)[0]
        assert text != CLEARED_MESSAGE
        assert "x" * 100 in text  # 原文还在

    def test_non_forensic_tool_untouched(self, store: EvidenceStore) -> None:
        """Read 的结果不许动——它归 microcompact 的清空语义管。"""

        messages = _conversation(tool="Read", text="y" * 6000)
        outcome = reduce_forensic_messages(messages, store=store, session_id=SESSION, min_chars=1000, keep_recent=0)

        assert outcome.reduced_count == 0
        assert _result_texts(outcome.messages)[0] == "y" * 6000

    def test_forensic_names_exclude_coding_tools(self) -> None:
        for name in ("Read", "Grep", "Bash", "Edit", "Write"):
            assert name not in FORENSIC_TOOL_NAMES


class TestHandleFailure:
    def test_no_store_means_no_handle(self, store: EvidenceStore) -> None:
        """归档不可用 → 摘要照旧生成，但**不写句柄**。"""

        messages = _conversation()
        outcome = reduce_forensic_messages(messages, store=None, session_id=SESSION, min_chars=1000, keep_recent=0)
        assert outcome.reduced_count == 1
        assert outcome.handles == []
        text = _result_texts(outcome.messages)[0]
        assert REDUCED_MARKER in text
        assert "evh:" not in text, "没有句柄却写了句柄标记"

    def test_empty_session_means_no_handle(self, store: EvidenceStore) -> None:
        messages = _conversation()
        outcome = reduce_forensic_messages(messages, store=store, session_id="", min_chars=1000)
        assert outcome.handles == []
        assert "evh:" not in _result_texts(outcome.messages)[0]

    def test_store_write_failure_no_handle(self, tmp_path: Path) -> None:
        blocker = tmp_path / "blocker"
        blocker.write_text("file", encoding="utf-8")
        broken = EvidenceStore(root=blocker)

        messages = _conversation()
        outcome = reduce_forensic_messages(messages, store=broken, session_id=SESSION, min_chars=1000, keep_recent=0)
        assert outcome.reduced_count == 1
        assert outcome.handles == []
        assert "evh:" not in _result_texts(outcome.messages)[0]


class TestKeepRecent:
    """最新 N 条不折——补的是"当轮刚查到的结果被折掉"这个坑。

    压缩发生在"每轮请求前"，如果连当轮刚返回的那条也折成摘要，
    模型就看不到明细了：省 token 变成了拿诊断质量换。
    """

    def _multi(self, count: int, *, rows: int = 200) -> list:
        payload = _payload(rows)
        body = json.dumps(payload, ensure_ascii=False)
        messages = [create_user_message("查 orders")]
        for index in range(count):
            messages.append(
                create_assistant_message(
                    [{"type": "tool_use", "id": f"t{index}", "name": "query_table_rows", "input": {}}]
                )
            )
            messages.append(
                create_user_message(
                    [
                        {
                            "type": "tool_result",
                            "tool_use_id": f"t{index}",
                            "content": json.dumps({**payload, "table": f"public.orders_{index}"}, ensure_ascii=False),
                            "metadata": {"output": {**payload, "table": f"public.orders_{index}"}},
                        }
                    ]
                )
            )
        return messages

    def test_latest_n_kept(self, store: EvidenceStore) -> None:
        messages = self._multi(3)
        outcome = reduce_forensic_messages(
            messages, store=store, session_id=SESSION, min_chars=1000, keep_recent=2
        )
        assert outcome.reduced_count == 1, "应只折最旧的那一条"

        texts = _result_texts(outcome.messages)
        assert texts[0].startswith(REDUCED_MARKER)     # 旧 → 折了
        assert not texts[1].startswith(REDUCED_MARKER)  # 次新 → 保留
        assert not texts[2].startswith(REDUCED_MARKER)  # 最新 → 保留

    def test_kept_results_are_byte_identical(self, store: EvidenceStore) -> None:
        messages = self._multi(2)
        before = _result_texts(messages)
        outcome = reduce_forensic_messages(
            messages, store=store, session_id=SESSION, min_chars=1000, keep_recent=1
        )
        after = _result_texts(outcome.messages)
        assert after[1] == before[1], "被保护的结果不能有一个字节的改动"

    def test_keep_recent_zero_reduces_all(self, store: EvidenceStore) -> None:
        """``keep_recent=0`` 必须是"全折"。

        这是个防回归用例：Python 里 ``xs[:-0]`` 等于 ``xs[:0]``（空列表），
        用切片实现"全折"会静默变成"全不折"。`microcompact` 已经踩过一次。
        """

        messages = self._multi(3)
        outcome = reduce_forensic_messages(
            messages, store=store, session_id=SESSION, min_chars=1000, keep_recent=0
        )
        assert outcome.reduced_count == 3

    def test_fewer_candidates_than_keep_recent(self, store: EvidenceStore) -> None:
        messages = self._multi(2)
        outcome = reduce_forensic_messages(
            messages, store=store, session_id=SESSION, min_chars=1000, keep_recent=5
        )
        assert outcome.reduced_count == 0
        assert outcome.failures == 0, "被保护的不该记成失败"

    def test_max_items_applies_after_keep_recent(self, store: EvidenceStore) -> None:
        """先保护最新 N 条，再在剩下的里从旧到新取 max_items 条。"""

        messages = self._multi(5)
        outcome = reduce_forensic_messages(
            messages,
            store=store,
            session_id=SESSION,
            min_chars=1000,
            keep_recent=2,
            max_items=2,
        )
        assert outcome.reduced_count == 2
        texts = _result_texts(outcome.messages)
        # 最旧的两条被折，后三条保持原样
        assert [t.startswith(REDUCED_MARKER) for t in texts] == [True, True, False, False, False]

    def test_min_chars_gate(self, store: EvidenceStore) -> None:
        messages = _conversation()
        outcome = reduce_forensic_messages(
            messages, store=store, session_id=SESSION, min_chars=10_000_000
        )
        assert outcome.reduced_count == 0

    def test_max_items(self, store: EvidenceStore) -> None:
        payload = _payload()
        messages = [create_user_message("q")]
        assistant_blocks = []
        result_blocks = []
        for index in range(3):
            assistant_blocks.append(
                {"type": "tool_use", "id": f"t{index}", "name": "query_table_rows", "input": {}}
            )
            # 三条各自是**合法** JSON（只是表名不同），确保都能被归约
            body = json.dumps({**payload, "table": f"public.orders_{index}"}, ensure_ascii=False)
            result_blocks.append(
                {"type": "tool_result", "tool_use_id": f"t{index}", "content": body}
            )
        messages.append(create_assistant_message(assistant_blocks))
        messages.append(create_user_message(result_blocks))

        outcome = reduce_forensic_messages(
            messages, store=store, session_id=SESSION, min_chars=1000, keep_recent=0, max_items=2
        )
        assert outcome.reduced_count == 2, f"max_items 没生效：{outcome.as_dict()}"


class TestPipelineIntegration:
    def test_pipeline_reports_reduce_stats(self, tmp_path: Path) -> None:
        """管线要把归约统计带回来（否则 meta 里看不到效果）。"""

        import asyncio

        from cloudagent_ext.services.compact.pipeline import CompressionPipeline, PipelineConfig

        config = PipelineConfig(
            sr_enabled=True,
            sr_session_id=SESSION,
            sr_evidence_root=tmp_path / "ev",
            mc_enabled=False,
            sr_keep_recent=0,
        )
        result = asyncio.run(
            CompressionPipeline(config).run(_conversation(), input_token_count=0)
        )
        assert "structural_reduce" in result.layers_applied
        assert result.reduce_stats.get("reduced_count") == 1
        assert result.reduce_stats.get("handles")

    def test_pipeline_sr_disabled_is_noop(self, tmp_path: Path) -> None:
        import asyncio

        from cloudagent_ext.services.compact.pipeline import CompressionPipeline, PipelineConfig

        config = PipelineConfig(sr_enabled=False, sr_session_id=SESSION)
        result = asyncio.run(
            CompressionPipeline(config).run(_conversation(), input_token_count=0)
        )
        assert "structural_reduce" not in result.layers_applied
        assert result.reduce_stats == {}


class TestProbe:
    def test_probe_runs_and_reports_savings(self) -> None:
        from cloudagent_ext.services.compact.probe import run_probe

        stats = run_probe(rows=200)
        assert stats["chars_after"] < stats["chars_before"]
        assert stats["handles"]
        assert all(size > 0 for size in stats["reloaded_sizes"].values())

    def test_probe_without_sr_keeps_everything(self) -> None:
        from cloudagent_ext.services.compact.probe import run_probe

        stats = run_probe(sr_enabled=False)
        assert stats["chars_after"] == stats["chars_before"]
        assert stats["layers_applied"] == []
