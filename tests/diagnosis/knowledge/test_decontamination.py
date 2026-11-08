#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""知识库去污染守卫（EVAL-KB1 K1.2）——机制保证，不是口头约定。

背景：产品知识库默认开启（provision.knowledge_enabled 默认 True），而历史索引
把 38 题 golden 的 GT 根因/建议作为 case chunk 装进了检索源（654 = 39 case + 615 doc）——
答案在检索源里，任何 KB-on 分数都有污染风险（历史 kb-arm 对照因此作废）。

四条守卫：

1. docs-only 构建的索引 kind 只有 doc；
2. 默认参数构建不产生 case chunk；
3. 不显式传 --cases 时 CLI 行为是 docs-only（不是"找默认目录"）；
4. 泄漏探针：38 个 case_id 硬编码在本文件（产品仓不读评测仓路径），
   索引的 source/text 里不得出现。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cloudagent_ext.diagnosis.knowledge.ingest import build
from cloudagent_ext.diagnosis.knowledge.store import build_chunks

#: 38 题 golden 的 case_id（硬编码——产品仓禁止读评测仓路径，P2 一审裁决）
GOLDEN_CASE_IDS = (
    [f"code-{i:03d}" for i in range(1, 8)]
    + [f"sql-{i:03d}" for i in range(1, 15)]
    + [f"log-{i:03d}" for i in range(1, 7)]
    + [f"cross-{i:03d}" for i in range(1, 7)]
    + [f"sync-{i:03d}" for i in range(1, 6)]
)

_DOCS_DIR = Path(__file__).resolve().parents[3] / "docs"


class TestDocsOnlyBuild:
    def test_docs_only_index_has_no_case_chunks(self, tmp_path: Path) -> None:
        """守卫 1：docs-only 构建的索引 kind 只有 doc。"""

        chunks = build_chunks(cases_dir=None, docs_dir=_DOCS_DIR)
        assert chunks, "docs-only 构建应产出 doc chunk（docs/ 在产品仓内）"
        assert all(chunk.kind == "doc" for chunk in chunks), (
            f"docs-only 索引混入了非 doc chunk："
            f"{sorted({c.kind for c in chunks if c.kind != 'doc'})}"
        )

    def test_default_build_excludes_cases(self) -> None:
        """守卫 2：默认参数（不传案例目录）不产生 kind=='case' 的 chunk。"""

        chunks = build_chunks()
        assert all(chunk.kind != "case" for chunk in chunks)

    def test_explicit_cases_still_works(self, tmp_path: Path) -> None:
        """反向对照：显式传案例目录仍能产出 case chunk（机制未被砍死，
        只是不再作为默认/不被 benchmark 数据喂进）。"""

        case_dir = tmp_path / "cases"
        case_dir.mkdir()
        (case_dir / "demo-001.json").write_text(
            json.dumps({
                "case_id": "demo-001", "domain": "sql",
                "input": {"question": "q"},
                "ground_truth": {"root_causes": [{"description": "演示根因"}]},
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        chunks = build_chunks(cases_dir=case_dir, docs_dir=None)
        assert any(chunk.kind == "case" for chunk in chunks)


class TestIngestCliDocsOnly:
    def test_case_ingest_requires_explicit_flag(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        """守卫 3：不显式传 --cases 时，CLI 行为是 docs-only（不是"找默认目录"）。"""

        from cloudagent_ext.diagnosis.knowledge import ingest

        monkeypatch.setattr(ingest, "default_docs_dir", lambda: _DOCS_DIR)
        out = tmp_path / "index.json"
        rc = ingest.main(["--out", str(out)])  # 不传 --cases
        assert rc == 0
        payload = json.loads(out.read_text(encoding="utf-8"))
        chunks = payload["chunks"]
        assert chunks
        assert all(chunk.get("kind") != "case" for chunk in chunks)

    def test_cases_none_is_explicit_docs_only(self, tmp_path: Path, monkeypatch) -> None:
        from cloudagent_ext.diagnosis.knowledge import ingest

        monkeypatch.setattr(ingest, "default_docs_dir", lambda: _DOCS_DIR)
        out = tmp_path / "index.json"
        rc = ingest.main(["--cases", "none", "--out", str(out)])
        assert rc == 0
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert all(chunk.get("kind") == "doc" for chunk in payload["chunks"])


class TestLeakProbe:
    def test_built_index_never_contains_golden_case_ids(self, tmp_path: Path) -> None:
        """守卫 4（泄漏探针·构建侧）：38 个 case_id 不得出现在索引的 source/text。"""

        chunks = build_chunks(cases_dir=None, docs_dir=_DOCS_DIR)
        for chunk in chunks:
            for case_id in GOLDEN_CASE_IDS:
                assert case_id not in chunk.source, f"{chunk.chunk_id} 泄漏 {case_id}（source）"
                assert case_id not in chunk.text, f"{chunk.chunk_id} 泄漏 {case_id}（text）"

    def test_local_index_never_contains_golden_case_ids(self) -> None:
        """守卫 4（泄漏探针·本机索引）：重建后的真实索引不得含 case chunk / case_id。

        本机索引不存在（未重建/他机）则跳过——重建本机索引是 K1.3 的一次性动作。
        """

        index_path = Path.home() / ".cloudagent" / "knowledge" / "index.json"
        if not index_path.is_file():
            pytest.skip("本机索引不存在（未重建或他机）")
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        case_chunks = [c for c in payload["chunks"] if c.get("kind") == "case"]
        assert case_chunks == [], (
            f"本机索引含 {len(case_chunks)} 个 case chunk——KB1 去污染被回退或索引未重建"
        )
        for chunk in payload["chunks"]:
            for case_id in GOLDEN_CASE_IDS:
                assert case_id not in str(chunk.get("source", "")), chunk["chunk_id"]
                assert case_id not in str(chunk.get("text", "")), chunk["chunk_id"]


class TestChunkLevelFilter:
    """一审 B′ 新增：chunk 级过滤防静默回退——含 case_id 的 doc 块整块丢弃。"""

    def test_doc_chunk_with_case_id_is_dropped(self, tmp_path: Path) -> None:
        """设计文档里 "code-007 的 gt 写的是…" 这类直接引用 GT 的段落必须被丢弃。"""

        docs = tmp_path / "docs"
        docs.mkdir(parents=True)
        (docs / "diagnosis-redesign.md").write_text(
            "# 设计\n\n正常段落，讲预算与派发链路。\n\n"
            "## 一审记录\n\ncode-007 的 gt 写的是「异步已覆盖校验」，已过期。\n",
            encoding="utf-8",
        )
        chunks = build_chunks(cases_dir=None, docs_dir=docs)
        # 含 case_id 的块被丢；不含的正常保留
        assert all("code-007" not in c.text for c in chunks), (
            "含 case_id 的 chunk 未被 chunk 级过滤丢弃——防回退断言失败"
        )
        assert any("预算与派发链路" in c.text for c in chunks), (
            "不含 case_id 的设计内容被误杀"
        )

    def test_filter_applies_to_source_field_too(self, tmp_path: Path) -> None:
        """source 路径含 case_id（如 cases/sql-001.json）的 chunk 同样丢弃。"""

        case_dir = tmp_path / "cases"
        case_dir.mkdir(parents=True)
        import json as _json

        (case_dir / "sql-001.json").write_text(
            _json.dumps({
                "case_id": "sql-001", "domain": "sql",
                "input": {"question": "q"},
                "ground_truth": {"root_causes": [{"description": "索引"}]},
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        chunks = build_chunks(cases_dir=case_dir, docs_dir=None)
        assert chunks == [], "source 含 case_id 的 chunk 未被过滤"


class TestDocsIncludeFailClosed:
    """KB1 二审遗留 R1（reviews/eval-kb1-round2.md §4）：
    _DOCS_INCLUDE 是 fail-closed 允许清单——不在清单里的 docs/*.md 不进索引。"""

    def _make_docs(self, tmp_path: Path) -> tuple[Path, Path, Path]:
        """两个 md：一个在 _DOCS_INCLUDE 里（installation.md）、一个不在（stray.md）。"""

        docs = tmp_path / "docs"
        docs.mkdir(parents=True)
        (docs / "installation.md").write_text(
            "# 安装\n\n配置只读数据库账号。\n", encoding="utf-8"
        )
        (docs / "stray.md").write_text(
            "# 不在清单里的文档\n\n这段内容不应该进索引。\n", encoding="utf-8"
        )
        return docs, docs / "installation.md", docs / "stray.md"

    def test_only_allowlisted_doc_produces_chunks(self, tmp_path: Path) -> None:
        docs, _in_list, _not_in_list = self._make_docs(tmp_path)
        chunks = build_chunks(cases_dir=None, docs_dir=docs)
        sources = {c.source for c in chunks}
        assert any("installation.md" in s for s in sources), "清单内文档应产出 chunk"
        assert not any("stray.md" in s for s in sources), "不在清单的文档不得进索引"

    def test_removing_from_allowlist_removes_chunks(self, tmp_path: Path, monkeypatch) -> None:
        """从清单移除文档 → 该文档 chunk 消失（防清单被误改而静默放行）。"""

        import cloudagent_ext.diagnosis.knowledge.store as store_mod

        docs, _in_list, _not_in_list = self._make_docs(tmp_path)
        # 正常：installation.md 在清单里 → 有 chunk
        assert any("installation.md" in c.source for c in build_chunks(cases_dir=None, docs_dir=docs))
        # 模拟从清单移除 installation.md
        monkeypatch.setattr(
            store_mod, "_DOCS_INCLUDE",
            store_mod._DOCS_INCLUDE - {"installation.md"},
        )
        chunks = build_chunks(cases_dir=None, docs_dir=docs)
        assert not any("installation.md" in c.source for c in chunks), (
            "从 _DOCS_INCLUDE 移除后该文档的 chunk 仍存在——fail-closed 失效"
        )
