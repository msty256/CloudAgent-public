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
from pathlib import Path

from cloudagent_ext.diagnosis.knowledge import ingest
from cloudagent_ext.diagnosis.knowledge.store import KnowledgeIndex, build_chunks


def test_default_roots_after_dataset_moved_to_eval_repo():
    """EVAL-P2 后：案例数据集归评测仓（本仓内默认目录已删，须显式 --cases）；
    docs 默认目录仍在仓内，安全边界（根内约束）不变。"""

    assert not ingest.default_cases_dir().is_dir()
    assert ingest.default_docs_dir().is_dir()
    assert ingest.repo_root() == ingest.default_docs_dir().parent


def _golden_cases_dir() -> Path | None:
    """EVAL-P2 后案例数据集归独立评测仓所有（datasets/golden）；不在本机则跳过。

    路径通过 ``CLOUDAGENT_EVAL_GOLDEN_DIR`` 注入（或放在同级的 cloudagent-eval
    检出目录里）——**不在代码里硬编本机绝对路径**，否则测试不可移植。
    """

    import os

    candidates = []
    env = os.environ.get("CLOUDAGENT_EVAL_GOLDEN_DIR", "").strip()
    if env:
        candidates.append(Path(env))
    # 常见布局：<parent>/cloudagent-eval/datasets/golden
    for base in Path(__file__).resolve().parents:
        candidates.append(base / "cloudagent-eval" / "datasets" / "golden")
        candidates.append(base / "cloudagent_eval" / "datasets" / "golden")
    for cand in candidates:
        if cand.is_dir():
            return cand
    return None


def test_golden_dataset_chunks_are_filtered_out():
    """EVAL-KB1 一审 B′：真实 golden 数据喂进 build_chunks → case chunk 全部被
    chunk 级过滤器丢弃（0 存活）。这是"产品 KB 不吃 benchmark"的数据侧实测；
    38 题计数口径已由评测仓 dataset_audit 负责，本测试只守泄漏面。"""

    golden = _golden_cases_dir()
    if golden is None:
        import pytest

        pytest.skip("评测仓数据集不在本机")
    chunks = build_chunks(golden, None)
    case_chunks = [c for c in chunks if c.kind == "case"]
    assert case_chunks == [], (
        f"golden 数据 {len(case_chunks)} 个 case chunk 存活——chunk 级过滤失效"
    )


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
        "case_id": "demo-777",
        "domain": "sync",
        "scenario": "demo",
        "input": {"question": "上游有数据下游没有"},
        "ground_truth": {"root_causes": [{"description": "未落库"}]},
    }
    (cases / "demo-777.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
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
