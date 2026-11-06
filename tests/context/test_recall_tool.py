#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""召回工具测试（阶段 3 · T3.4）。

重点不是"能取回"，而是**取不回时说什么**。

模型遇到"失败"的第一反应是重试。如果错误信息只说"失败"，它会换个句柄再试、
再试——白烧轮次。所以这里的核心断言是：错误结果必须明确写"别重试、请重新取证"。

另一半是边界：句柄格式非法、跨会话、超长截断、归档目录不存在，
都必须返回结构化错误而不是抛异常。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from cloudagent_ext.agent.policy import (
    TOOL_SET_CODE_DIAGNOSIS,
    TOOL_SET_LOG_DIAGNOSIS,
    TOOL_SET_SQL_DIAGNOSIS,
)
from cloudagent_ext.services.compact.evidence_store import EvidenceStore
from cloudagent_ext.services.compact.recall_tool import (
    MAX_RECALL_CHARS,
    RECALL_TOOL_NAME,
    _recall_call,
    recall_evidence_tool,
    register_recall_tool,
)

SESSION = "req-1"


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """把用户配置目录指到临时目录，避免污染真实 ~/.cloudagent。"""

    monkeypatch.setenv("CLOUDAGENT_CONFIG_DIR", str(tmp_path))
    store = EvidenceStore()
    return store, SimpleNamespace(session_id=SESSION)


def _save(store: EvidenceStore, text: str, *, tool: str = "query_table_rows") -> str:
    handle = store.save(session_id=SESSION, domain="db", tool=tool, payload=text)
    assert handle is not None
    return handle


class TestRecallSuccess:
    def test_returns_full_text(self, env) -> None:
        store, context = env
        original = "ROWS-" + "x" * 5000
        handle = _save(store, original)

        result = _recall_call({"handle": handle}, context)

        assert result.is_error is False
        assert result.output["status"] == "success"
        assert result.output["content"] == original
        assert result.output["chars"] == len(original)
        assert result.output["truncated"] is False

    def test_oversize_is_truncated_with_flag(self, env) -> None:
        store, context = env
        huge = "y" * (MAX_RECALL_CHARS + 500)
        # 归档上限是 4MB，这里能存下
        handle = _save(store, huge)

        result = _recall_call({"handle": handle}, context)

        assert result.is_error is False
        assert result.output["chars"] == MAX_RECALL_CHARS
        assert result.output["truncated"] is True


class TestRecallFailuresTellTheModelNotToRetry:
    def test_missing_handle(self, env) -> None:
        _, context = env
        result = _recall_call({"handle": "evh:db:999"}, context)
        assert result.is_error is True
        assert "不要重复尝试" in result.output["error"]
        assert "重新取证" in result.output["error"]

    def test_bad_format(self, env) -> None:
        _, context = env
        result = _recall_call({"handle": "../../etc/passwd"}, context)
        assert result.is_error is True
        assert "格式不正确" in result.output["error"]
        assert "重新取证" in result.output["error"]

    def test_empty_handle(self, env) -> None:
        _, context = env
        result = _recall_call({}, context)
        assert result.is_error is True

    def test_cross_session_isolated(self, env) -> None:
        store, _ = env
        handle = _save(store, "secret")
        other = SimpleNamespace(session_id="req-2")
        result = _recall_call({"handle": handle}, other)
        assert result.is_error is True
        assert "不属于本次会话" in result.output["error"]

    def test_no_session_identity(self, env) -> None:
        store, _ = env
        handle = _save(store, "x")
        bare = SimpleNamespace()
        result = _recall_call({"handle": handle}, bare)
        assert result.is_error is True
        assert "无法取回" in result.output["error"]

    def test_never_raises_on_weird_context(self, env) -> None:
        store, _ = env
        handle = _save(store, "x")
        for context in (None, object(), SimpleNamespace(session_id=None)):
            result = _recall_call({"handle": handle}, context)
            assert result.is_error is True


class TestCoordinatesMustMatch:
    """存和取必须看到同一组坐标（session + 根目录）。

    这条不是"功能"，是**一类隐蔽故障**：坐标不一致时不报错，只是永远取不到。
    之前 `_recall_call` 硬编默认根目录，而管线可配 `sr_evidence_root`——
    两边一错开，句柄就成了废纸。
    """

    def test_root_from_context_is_used(self, tmp_path: Path) -> None:
        custom = tmp_path / "custom-root"
        store = EvidenceStore(root=custom)
        handle = store.save(session_id=SESSION, domain="db", tool="query_table_rows", payload="PAYLOAD")
        assert handle is not None

        context = SimpleNamespace(session_id=SESSION, evidence_root=str(custom))
        result = _recall_call({"handle": handle}, context)
        assert result.is_error is False
        assert result.output["content"] == "PAYLOAD"

    def test_mismatched_root_misses(self, tmp_path: Path) -> None:
        """文件在不一致的根目录下 → 取不到（这正是要防的情形）。"""

        custom = tmp_path / "custom-root"
        store = EvidenceStore(root=custom)
        handle = store.save(session_id=SESSION, domain="db", tool="query_table_rows", payload="PAYLOAD")
        assert handle is not None

        # context 没带 evidence_root → 走默认目录 → 找不到
        context = SimpleNamespace(session_id=SESSION)
        result = _recall_call({"handle": handle}, context)
        assert result.is_error is True

    def test_pipeline_publishes_root_to_sink(self, tmp_path: Path) -> None:
        """管线要把 sr_evidence_root 写到 sink 上，召回端才拿得到。"""

        import asyncio

        from cloudagent_ext.services.compact.pipeline import CompressionPipeline, PipelineConfig
        from cloudagent_ext.types.messages import create_assistant_message, create_user_message

        payload = {
            "mode": "rows",
            "table": "public.orders",
            "rows": [{"id": i} for i in range(1, 61)],
        }
        messages = [
            create_user_message("q"),
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
        sink = SimpleNamespace(compaction_stats=None, evidence_root=None)
        config = PipelineConfig(
            sr_enabled=True,
            sr_session_id=SESSION,
            sr_evidence_root=tmp_path / "ev",
            sr_keep_recent=0,
            stats_sink=sink,
        )
        asyncio.run(CompressionPipeline(config).run(messages, input_token_count=0))
        assert sink.evidence_root == str(tmp_path / "ev")


class TestWiring:
    def test_tool_metadata(self) -> None:
        assert recall_evidence_tool.name == RECALL_TOOL_NAME
        assert RECALL_TOOL_NAME == "recall_evidence"

    @pytest.mark.parametrize(
        "tool_set",
        [TOOL_SET_CODE_DIAGNOSIS, TOOL_SET_LOG_DIAGNOSIS, TOOL_SET_SQL_DIAGNOSIS],
    )
    def test_all_diagnosis_tool_sets_include_recall(self, tool_set) -> None:
        assert RECALL_TOOL_NAME in tool_set

    def test_tool_set_still_read_only(self) -> None:
        """加的是只读工具，白名单的"无写操作"性质不能破。"""

        for tool_set in (
            TOOL_SET_CODE_DIAGNOSIS,
            TOOL_SET_LOG_DIAGNOSIS,
            TOOL_SET_SQL_DIAGNOSIS,
        ):
            for forbidden in ("Edit", "Write", "NotebookEdit", "Agent"):
                assert forbidden not in tool_set

    def test_register_is_idempotent(self) -> None:
        class _Registry:
            def __init__(self) -> None:
                self.tools: dict[str, object] = {}

            def get(self, name: str):
                return self.tools.get(name)

            def register(self, tool) -> None:
                self.tools[tool.name] = tool

        registry = _Registry()
        assert register_recall_tool(registry) is True
        assert register_recall_tool(registry) is True
        assert len(registry.tools) == 1

    def test_provision_with_recall_covers_early_return(self) -> None:
        """域装配走"已装配就早退"的分支时，召回工具仍要被补上。"""

        from cloudagent_ext.services.compact.recall_tool import provision_with_recall

        class _Registry:
            def __init__(self) -> None:
                self.tools: dict[str, object] = {}

            def get(self, name: str):
                return self.tools.get(name)

            def register(self, tool) -> None:
                self.tools[tool.name] = tool

        registry = _Registry()
        # 域装配函数直接返回 True（模拟早退），不注册任何东西
        assert provision_with_recall(lambda _r: True, registry) is True
        assert registry.get(RECALL_TOOL_NAME) is not None
