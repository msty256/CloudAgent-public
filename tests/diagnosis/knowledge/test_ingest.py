#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""ingest CLI 测试：默认目录、路径逃逸防护、构建产物可加载。"""

from __future__ import annotations

import json

from cloudagent_ext.diagnosis.knowledge import ingest
from cloudagent_ext.diagnosis.knowledge.store import KnowledgeIndex, build_chunks


def test_default_roots_live_inside_repo():
    assert ingest.default_cases_dir().is_dir()
    assert ingest.default_docs_dir().is_dir()
    assert ingest.repo_root() == ingest.default_docs_dir().parent


def test_repo_cases_build_to_38_case_sources():
    chunks = build_chunks(ingest.default_cases_dir(), None)
    sources = {chunk.source for chunk in chunks if chunk.kind == "case"}
    assert len(sources) == 38, f"expected 38 case sources, got {len(sources)}"


def test_cli_rejects_outside_root_path(tmp_path, capsys):
    outside = tmp_path / "outside"
    outside.mkdir()
    code = ingest.main(["--cases", str(outside), "--out", str(tmp_path / "index.json")])
    captured = capsys.readouterr()
    assert code == 2
    assert "escapes repository root" in captured.err


def test_cli_can_build_with_allow_outside_root(tmp_path, capsys):
    cases = tmp_path / "cases"
    cases.mkdir()
    payload = {
        "case_id": "sync-777",
        "domain": "sync",
        "scenario": "demo",
        "input": {"question": "上游有数据下游没有"},
        "ground_truth": {"root_causes": [{"description": "未落库"}]},
    }
    (cases / "sync-777.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "faq.md").write_text("# FAQ\n\nMySQL 暂不支持。\n", encoding="utf-8")
    out = tmp_path / "index.json"

    code = ingest.main(
        [
            "--cases",
            str(cases),
            "--docs",
            str(docs),
            "--out",
            str(out),
            "--allow-outside-root",
        ]
    )
    captured = capsys.readouterr()
    assert code == 0, captured.err
    assert out.is_file()
    index = KnowledgeIndex.load(out)
    assert [chunk.domain for chunk in index.chunks if chunk.kind == "case"] == ["sync"]
    assert any(chunk.kind == "doc" for chunk in index.chunks)
