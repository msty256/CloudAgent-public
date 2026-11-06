#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""检索服务测试：限额、领域过滤、索引缺失、环境变量与缓存。"""

from __future__ import annotations

import json

import pytest

from cloudagent_ext.diagnosis.knowledge import retriever
from cloudagent_ext.diagnosis.knowledge.store import KnowledgeIndex, build_chunks


def _write_case(root, case_id: str, domain: str, question: str, cause: str) -> None:
    target = root / domain
    target.mkdir(parents=True, exist_ok=True)
    payload = {
        "case_id": case_id,
        "domain": domain,
        "scenario": "demo",
        "input": {"question": question},
        "ground_truth": {"root_causes": [{"description": cause}]},
    }
    (target / f"{case_id}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


@pytest.fixture()
def index_file(tmp_path):
    root = tmp_path / "cases"
    _write_case(root, "sync-001", "sync", "orders 上游 50000 行、下游 0 行，确认是否真的没落库", "未落库")
    _write_case(root, "sql-001", "sql", "这条查询走了全表扫描，索引为什么没命中", "关联列类型不一致")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "security.md").write_text("# 安全模型\n\n只读三重防线：只读事务、SQL 白名单、只读账号。\n", encoding="utf-8")
    index = KnowledgeIndex(build_chunks(root, docs))
    path = index.save(tmp_path / "index.json")
    retriever.reset_cache()
    yield path
    retriever.reset_cache()


def test_search_returns_structured_chunks(index_file):
    payload = retriever.search("上游有数据下游没有", path=index_file)
    assert payload["chunks"], "expected at least one chunk"
    first = payload["chunks"][0]
    for key in ("chunk_id", "source", "section", "kind", "score", "snippet"):
        assert key in first
    assert first["chunk_id"].startswith("kb:")
    assert payload["total_chars"] == sum(len(chunk["snippet"]) for chunk in payload["chunks"])
    assert payload["total_chars"] <= retriever.MAX_TOTAL_CHARS
    assert "不是结论" in payload["note"]
    assert payload["index"]["chunk_count"] >= 3


def test_search_uses_environment_override(index_file, monkeypatch):
    monkeypatch.setenv(retriever.INDEX_ENV, str(index_file))
    retriever.reset_cache()
    payload = retriever.search("只读防线", top_k=2)
    assert payload["chunks"]
    assert payload["index"]["path"] == str(index_file)


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"query": ""}, "query is empty"),
        ({"query": "x" * (retriever.MAX_QUERY_CHARS + 1)}, "query too long"),
        ({"query": "ok", "top_k": 0}, "top_k out of range"),
        ({"query": "ok", "top_k": retriever.MAX_TOP_K + 1}, "top_k out of range"),
        ({"query": "ok", "mode": "fuzzy"}, "unknown mode"),
    ],
)
def test_search_rejects_invalid_arguments(index_file, kwargs, message):
    with pytest.raises(retriever.KnowledgeQueryError, match=message):
        retriever.search(path=index_file, **kwargs)


def test_search_rejects_non_integer_top_k(index_file):
    with pytest.raises(retriever.KnowledgeQueryError, match="top_k must be an integer"):
        retriever.search("上游", top_k="5", path=index_file)  # type: ignore[arg-type]


def test_domain_filter_only_keeps_matching_case_domain(index_file):
    payload = retriever.search("索引 没命中 全表扫描", domain="sql", path=index_file)
    for chunk in payload["chunks"]:
        if chunk["kind"] == "case":
            assert chunk["domain"] == "sql"
    assert payload["domain"] == "sql"


def test_missing_index_raises(index_file, tmp_path):
    missing = tmp_path / "nope" / "index.json"
    with pytest.raises(retriever.KnowledgeIndexMissing, match="knowledge index not found"):
        retriever.search("anything", path=missing)


def test_total_chars_cap(index_file, monkeypatch):
    monkeypatch.setattr(retriever, "MAX_TOTAL_CHARS", 40)
    payload = retriever.search("只读 防线 上游 索引", top_k=8, path=index_file)
    assert payload["total_chars"] <= 40
    assert payload["truncated"] is True
