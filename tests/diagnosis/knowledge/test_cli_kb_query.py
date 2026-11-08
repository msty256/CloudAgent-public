#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""``kb-query`` CLI 测试（EVAL-P8 T8.1）——fake index 为主，真索引 skipif。

契约（设计 eval-p8-rag.md §4）：stdout=单行 JSON；错误 → stderr + 非 0
（状态诚实：不返回空数组冒充成功）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cloudagent_ext.diagnosis.knowledge import retriever
from cloudagent_ext.diagnosis.knowledge.cli_kb_query import (
    index_content_hash,
    run_kb_query,
)
from cloudagent_ext.diagnosis.knowledge.store import KnowledgeIndex, build_chunks


def _write_case(root: Path, case_id: str, domain: str, question: str, cause: str) -> None:
    target = root / domain
    target.mkdir(parents=True, exist_ok=True)
    payload = {
        "case_id": case_id,
        "domain": domain,
        "scenario": "demo",
        "input": {"question": question},
        "ground_truth": {"root_causes": [{"description": cause}]},
    }
    (target / f"{case_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


@pytest.fixture()
def index_file(tmp_path, monkeypatch):
    root = tmp_path / "cases"
    _write_case(root, "demo-a", "sql", "orders 按 tenant_id 查询走全表扫描，索引为什么没命中",
                "tenant_id 列无索引")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "security.md").write_text(
        "# 安全模型\n\n只读三重防线：只读事务、SQL 白名单、只读账号。\n",
        encoding="utf-8",
    )
    path = KnowledgeIndex(build_chunks(root, docs)).save(tmp_path / "index.json")
    monkeypatch.setenv("CLOUDAGENT_KB_INDEX", str(path))
    retriever.reset_cache()
    yield path
    retriever.reset_cache()


class TestKbQueryCli:
    def test_contract_json_on_stdout(self, index_file, capsys) -> None:
        rc = run_kb_query(["--query", "tenant_id 查询为什么慢", "--top-k", "3", "--json"])
        assert rc == 0
        out = capsys.readouterr().out.strip()
        payload = json.loads(out)  # stdout 必须是干净 JSON（单行）
        for key in ("query", "top_k", "domain", "index", "latency_ms", "chunks"):
            assert key in payload
        idx = payload["index"]
        for key in ("version", "chunk_count", "content_hash"):
            assert key in idx, f"index.{key} 必填（R7）"
        assert idx["chunk_count"] >= 2
        assert idx["version"] == 1
        assert len(idx["content_hash"]) == 16
        assert payload["top_k"] == 3
        assert payload["latency_ms"] >= 0
        assert isinstance(payload["chunks"], list)
        for chunk in payload["chunks"]:
            assert set(chunk) == {"chunk_id", "source", "kind", "score", "section"}

    def test_domain_filter_echoed(self, index_file, capsys) -> None:
        rc = run_kb_query(["--query", "tenant_id 查询慢", "--domain", "sql", "--json"])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["domain"] == "sql"

    def test_top_k_over_max_fails_honestly(self, index_file, capsys) -> None:
        """状态诚实：top_k 越界 → 非 0 + stderr，不输出任何 JSON。"""

        from cloudagent_ext.diagnosis.knowledge.retriever import MAX_TOP_K

        rc = run_kb_query(["--query", "q", "--top-k", str(MAX_TOP_K + 1)])
        assert rc == 2
        captured = capsys.readouterr()
        assert captured.out.strip() == ""  # stdout 干净
        assert "kb-query:" in captured.err

    def test_missing_index_fails_honestly(self, tmp_path, monkeypatch, capsys) -> None:
        monkeypatch.setenv("CLOUDAGENT_KB_INDEX", str(tmp_path / "nope.json"))
        retriever.reset_cache()
        rc = run_kb_query(["--query", "q"])
        assert rc == 2
        captured = capsys.readouterr()
        assert captured.out.strip() == ""
        assert "not found" in captured.err

    def test_empty_result_is_success_with_empty_chunks(self, tmp_path, monkeypatch, capsys) -> None:
        """合法空结果（域过滤把唯一案例块滤掉）→ rc 0 且 chunks=[]（与'错误'可判别）。

        BM25 对任何查询都会排出候选，所以用域过滤构造真空：索引里只有 sql 案例块，
        按 code 域过滤 → 案例块全被滤掉（doc 不存在）。
        """

        from cloudagent_ext.diagnosis.knowledge.store import Chunk

        only_case = KnowledgeIndex([
            Chunk(chunk_id="kb:test:sql-c1", source="cases/sql/c1.json", section="q",
                  text="orders tenant_id 全表扫描 索引", kind="case", domain="sql"),
        ])
        path = only_case.save(tmp_path / "only-case-index.json")
        monkeypatch.setenv("CLOUDAGENT_KB_INDEX", str(path))
        retriever.reset_cache()
        rc = run_kb_query(["--query", "tenant_id 索引", "--domain", "code"])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["chunks"] == []

    def test_content_hash_matches_report_recipe(self, index_file) -> None:
        """content_hash 与评测仓 report._index_content_hash 同一算方（R7 可比）。"""

        import hashlib

        data = json.loads(index_file.read_text(encoding="utf-8"))
        sha = hashlib.sha256()
        for chunk in sorted(data.get("chunks", []), key=lambda c: c.get("chunk_id", "")):
            sha.update(str(chunk.get("chunk_id", "")).encode("utf-8"))
            sha.update(str(chunk.get("text", "")).encode("utf-8"))
        assert index_content_hash(index_file) == sha.hexdigest()[:16]


class TestDispatchFastPath:
    def test_main_routes_kb_query(self, index_file, capsys, monkeypatch) -> None:
        """`python -m cloudagent_ext.cli.main kb-query ...` 走 fast-path（stdout=JSON）。"""

        from cloudagent_ext.cli.main import main

        monkeypatch.setattr(
            "sys.argv",
            ["cloudagent", "kb-query", "--query", "tenant_id 查询慢", "--top-k", "2", "--json"],
        )
        rc = main()
        assert rc == 0
        payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert payload["query"] == "tenant_id 查询慢"
        assert payload["index"]["content_hash"]


@pytest.mark.skipif(
    not (Path.home() / ".cloudagent" / "knowledge" / "index.json").is_file(),
    reason="本机未构建真实知识库索引",
)
class TestRealIndex:
    """真索引冒烟（skipif 保护；供 Lead 逐条校验检索 golden 时的人工对照）。"""

    def test_real_index_query(self, capsys) -> None:
        rc = run_kb_query(["--query", "装 CloudAgent 要准备哪些环境", "--top-k", "5", "--json"])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["index"]["chunk_count"] > 0
        assert payload["index"]["content_hash"]
