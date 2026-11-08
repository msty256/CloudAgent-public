#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""``search_knowledge`` 工具契约测试：schema、只读语义、错误结构化、注册幂等。"""

from __future__ import annotations

import json

import pytest

from cloudagent_ext.diagnosis.knowledge import retriever
from cloudagent_ext.diagnosis.knowledge.store import KnowledgeIndex, build_chunks
from cloudagent_ext.diagnosis.knowledge.tools import (
    TOOL_NAME,
    register_knowledge_tools,
    search_knowledge_tool,
)


class FakeRegistry:
    """最小注册表：只实现 get/register，够验证装配接缝。"""

    def __init__(self) -> None:
        self._tools: dict[str, object] = {}

    def register(self, tool) -> None:  # noqa: ANN001
        self._tools[tool.name] = tool

    def get(self, name: str):  # noqa: ANN201
        return self._tools.get(name)


@pytest.fixture()
def index_file(tmp_path, monkeypatch):
    root = tmp_path / "cases"
    root.mkdir()
    payload = {
        "case_id": "demo-a",
        "domain": "sync",
        "scenario": "upstream_has_downstream_missing",
        "input": {"question": "orders 上游 50000 行、下游 0 行，确认是否真的没落库"},
        "ground_truth": {"root_causes": [{"description": "orders 表未落库"}]},
    }
    (root / "demo-a.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    path = KnowledgeIndex(build_chunks(root)).save(tmp_path / "index.json")
    monkeypatch.setenv(retriever.INDEX_ENV, str(path))
    retriever.reset_cache()
    yield path
    retriever.reset_cache()


def _call(tool_input: dict):
    return search_knowledge_tool.call(tool_input, None)  # type: ignore[arg-type]


def test_tool_metadata_and_schema():
    assert search_knowledge_tool.name == TOOL_NAME == "search_knowledge"
    schema = search_knowledge_tool.input_schema
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["query"]
    assert schema["properties"]["top_k"]["maximum"] == retriever.MAX_TOP_K
    assert search_knowledge_tool.is_read_only({}) is True
    assert search_knowledge_tool.is_concurrency_safe({}) is True


def test_permissions_are_explicitly_allowed(index_file):
    decision = search_knowledge_tool.check_permissions({"query": "上游"}, None)  # type: ignore[arg-type]
    assert decision.behavior == "allow"
    assert "read-only" in decision.decision_reason.reason


def test_successful_call_returns_chunks(index_file):
    result = _call({"query": "上游有数据下游没有", "top_k": 3})
    assert result.is_error is False
    assert result.name == TOOL_NAME
    assert result.output["chunks"]
    assert result.output["chunks"][0]["chunk_id"]
    # 输出必须是可序列化的数据（不是指令）
    json.dumps(result.output, ensure_ascii=False)


def test_empty_query_returns_structured_error(index_file):
    result = _call({"query": "  "})
    assert result.is_error is True
    assert result.output["error_type"] == "KnowledgeQueryError"
    assert "empty" in result.output["message"]


def test_missing_index_returns_structured_error(tmp_path, monkeypatch):
    monkeypatch.setenv(retriever.INDEX_ENV, str(tmp_path / "missing" / "index.json"))
    retriever.reset_cache()
    result = _call({"query": "上游"})
    assert result.is_error is True
    assert result.output["error_type"] == "knowledge_index_missing"
    assert "ingest" in result.output["message"]


def test_register_is_idempotent():
    registry = FakeRegistry()
    assert register_knowledge_tools(registry) is True
    assert registry.get(TOOL_NAME) is search_knowledge_tool
    assert register_knowledge_tools(registry) is True
    assert len(registry._tools) == 1
