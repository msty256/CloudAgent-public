#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""切块、索引、BM25/向量/RRF 检索的单元测试。"""

from __future__ import annotations

import json

import pytest

from cloudagent_ext.diagnosis.knowledge.store import (
    Chunk,
    KnowledgeIndex,
    build_chunks,
    chunk_case,
    split_text,
    tokenize,
)


def _case_payload(case_id: str, domain: str, scenario: str, question: str, cause: str) -> dict:
    return {
        "case_id": case_id,
        "domain": domain,
        "scenario": scenario,
        "input": {"question": question},
        "ground_truth": {
            "root_causes": [{"description": cause}],
            "acceptable_recommendations": [{"description": "检查调度日志与消费位点"}],
        },
    }


@pytest.fixture()
def cases_dir(tmp_path):
    root = tmp_path / "cases" / "sync"
    root.mkdir(parents=True)
    (root / "sync-001.json").write_text(
        json.dumps(
            _case_payload(
                "sync-001",
                "sync",
                "upstream_has_downstream_missing",
                "orders 上游 50000 行、下游 0 行，确认是否真的没落库",
                "orders 表未落库；下游写入通道未完全阻断",
            ),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    sql_root = tmp_path / "cases" / "sql"
    sql_root.mkdir(parents=True)
    (sql_root / "sql-001.json").write_text(
        json.dumps(
            _case_payload(
                "sql-001",
                "sql",
                "index_not_used",
                "这条查询走了全表扫描，索引为什么没命中",
                "关联列类型不一致导致索引失效",
            ),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return tmp_path / "cases"


@pytest.fixture()
def docs_dir(tmp_path):
    root = tmp_path / "docs"
    root.mkdir()
    (root / "security.md").write_text(
        "# 安全模型\n\n只读三重防线：只读事务、SQL 白名单、只读账号。\n\n"
        "## 权限隔离\n\n子 Agent 不允许写文件，也不允许继续派发任务。\n",
        encoding="utf-8",
    )
    return root


# ---------------------------------------------------------------------------
# 切块
# ---------------------------------------------------------------------------


def test_split_text_respects_max_chars_and_overlap():
    text = "字" * 50 + "\n\n" + "b" * 1200
    pieces = split_text(text, max_chars=700, overlap=100)
    assert all(len(piece) <= 700 for piece in pieces)
    assert len(pieces) >= 2
    # 硬切带 overlap：相邻两块应有 100 字符重叠
    assert pieces[-2][-100:] == pieces[-1][:100]


def test_split_text_keeps_short_paragraphs_whole():
    assert split_text("第一段\n\n第二段") == ["第一段", "第二段"]


def test_doc_chunks_never_exceed_budget_including_heading_prefix(tmp_path):
    """回归：标题前缀也算进配额，块长不得突破 MAX_CHUNK_CHARS。

    早期实现先切 700 再拼标题前缀，导致 20/640 个块超限。
    """

    from cloudagent_ext.diagnosis.knowledge.store import MAX_CHUNK_CHARS, chunk_doc

    long_section = "很长的标题" * 12  # 72 字符，留出前缀预算验证空间
    body = "内容" * 900
    path = tmp_path / "long.md"
    path.write_text(f"# {long_section}\n\n{body}\n", encoding="utf-8")

    chunks = chunk_doc(path, "docs/long.md")
    assert chunks
    assert max(len(chunk.text) for chunk in chunks) <= MAX_CHUNK_CHARS
    assert all(chunk.text.startswith(long_section) for chunk in chunks)


def test_tokenize_cjk_bigrams_and_ascii_words():
    tokens = tokenize("orders 未落库")
    assert "orders" in tokens
    assert "未" in tokens and "落" in tokens
    assert "未落" in tokens and "落库" in tokens


def test_chunk_case_is_structured_single_block():
    chunks = chunk_case(_case_payload("sync-009", "sync", "x", "上游有数据下游没有", "未落库"), "cases/sync-009.json")
    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.kind == "case"
    assert chunk.domain == "sync"
    assert chunk.chunk_id.startswith("kb:cases/sync-009.json#")
    text = chunk.text
    for label in ("案例 sync-009", "领域 sync", "场景 x", "问题：", "根因：未落库", "建议："):
        assert label in text


def test_build_chunks_reads_cases_and_docs_and_dedupes(cases_dir, docs_dir):
    chunks = build_chunks(cases_dir, docs_dir)
    assert sum(1 for c in chunks if c.kind == "case") == 2
    assert sum(1 for c in chunks if c.kind == "doc") == 2
    texts = [c.text for c in chunks]
    assert len(texts) == len(set(texts))


# ---------------------------------------------------------------------------
# 索引与检索
# ---------------------------------------------------------------------------


def test_bm25_finds_exact_identifier(cases_dir, docs_dir):
    index = KnowledgeIndex(build_chunks(cases_dir, docs_dir))
    hits = index.search_bm25("orders 50000", top_k=3)
    assert hits
    assert index.chunks[hits[0][1]].source.endswith("sync-001.json")


def test_vector_and_hybrid_return_results(cases_dir, docs_dir):
    index = KnowledgeIndex(build_chunks(cases_dir, docs_dir))
    assert index.search_vector("索引没命中", top_k=3)
    hybrid = index.search_hybrid("索引没命中", top_k=3)
    assert hybrid
    assert index.search("bm25", "索引", 3) == index.search_bm25("索引", 3)


def test_search_rejects_unknown_mode(cases_dir, docs_dir):
    index = KnowledgeIndex(build_chunks(cases_dir, docs_dir))
    with pytest.raises(ValueError):
        index.search("fuzzy", "anything", 3)


def test_empty_query_returns_no_hits(cases_dir):
    index = KnowledgeIndex(build_chunks(cases_dir))
    assert index.search_bm25("", 3) == []
    assert index.search_vector("", 3) == []


# ---------------------------------------------------------------------------
# 序列化
# ---------------------------------------------------------------------------


def test_save_load_roundtrip(tmp_path, cases_dir, docs_dir):
    index = KnowledgeIndex(build_chunks(cases_dir, docs_dir))
    path = index.save(tmp_path / "index.json")
    loaded = KnowledgeIndex.load(path)
    assert [c.chunk_id for c in loaded.chunks] == [c.chunk_id for c in index.chunks]
    assert loaded.search_bm25("orders 50000", 1)[0][1] == index.search_bm25("orders 50000", 1)[0][1]


def test_load_rejects_unknown_version(tmp_path):
    path = tmp_path / "index.json"
    path.write_text(json.dumps({"version": 999, "chunks": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported knowledge index version"):
        KnowledgeIndex.load(path)


def test_chunk_roundtrip_dict():
    chunk = Chunk("kb:a#b#0", "docs/a.md", "b", "text", "doc")
    assert Chunk.from_dict(chunk.to_dict()) == chunk
