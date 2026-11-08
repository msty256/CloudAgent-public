#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""重建诊断知识库索引（离线、只读源文件）。

用法::

    # 默认：诊断案例 + 仓库 docs/
    python -m cloudagent_ext.diagnosis.knowledge.ingest

    # 指定目录与输出
    python -m cloudagent_ext.diagnosis.knowledge.ingest \\
        --cases cloudagent_ext/diagnosis/cases --docs docs \\
        --out ~/.cloudagent/knowledge/index.json

安全约束：``--cases`` / ``--docs`` 必须落在仓库根目录内（拒绝 ``../`` 逃逸）；
``--out`` 可以写到任意位置（索引是派生产物）。

退出码：0 成功；2 参数/路径非法。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

from . import retriever
from .store import KnowledgeIndex, build_chunks


def repo_root() -> Path:
    """本文件位于 ``<repo>/cloudagent_ext/diagnosis/knowledge/ingest.py``。"""

    return Path(__file__).resolve().parents[3]


def default_cases_dir() -> Path:
    """EVAL-P2 后案例数据集归评测仓所有（datasets/golden），本仓内目录已删除。

    安全边界（--cases 必须落在仓库根内）未随数据集迁移放开——跨仓默认值
    会与该约束冲突，故默认仍指旧路径（已不存在）；未显式传 --cases 时
    由 CLI 给出可操作的报错，而不是静默指到边界之外。
    """

    return Path(__file__).resolve().parents[1] / "cases"


def default_docs_dir() -> Path:
    return repo_root() / "docs"


def _index_content_hash(index_path: Path) -> str:
    """索引内容 hash：chunks 按 chunk_id 排序后对 (chunk_id, source, kind, text) 级联 sha256。"""

    data = json.loads(Path(index_path).read_text(encoding="utf-8"))
    sha = hashlib.sha256()
    for chunk in sorted(data.get("chunks", []), key=lambda c: c.get("chunk_id", "")):
        sha.update(chunk.get("chunk_id", "").encode("utf-8"))
        sha.update(chunk.get("source", "").encode("utf-8"))
        sha.update(chunk.get("kind", "").encode("utf-8"))
        sha.update(chunk.get("text", "").encode("utf-8"))
    return sha.hexdigest()[:16]


def _ensure_within(path: Path, root: Path) -> Path:
    resolved = Path(path).expanduser().resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"path escapes repository root: {path} (root={root})") from exc
    return resolved


def build(*, cases_dir: Path | None, docs_dir: Path | None, out: Path, dense: bool = True) -> dict[str, Any]:
    """构建并落盘索引，返回摘要（不打印）。

    ``dense=True`` 时额外生成稠密向量与 FAISS 索引（需要 bge 模型 + faiss）；
    模型或依赖缺失时自动退回纯稀疏索引，不阻塞 ingest。
    """

    started = time.perf_counter()
    chunks = build_chunks(
        Path(cases_dir) if cases_dir else None,
        Path(docs_dir) if docs_dir else None,
    )
    embedder = None
    dense_store = None
    if dense:
        try:
            from .embedder import get_embedder
            from .vector_store import FaissVectorStore

            candidate = get_embedder()
            if getattr(candidate, "dim", 0) > 0:
                embedder = candidate
                dense_store = FaissVectorStore(candidate.dim)
        except Exception:  # noqa: BLE001 — 稠密不可用时退回稀疏索引
            embedder = None
            dense_store = None
    index = KnowledgeIndex(chunks, dense=dense_store, embedder=embedder)
    path = index.save(Path(out))
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    return {
        "index": str(path),
        "chunks": len(index.chunks),
        "cases": len({chunk.source for chunk in index.chunks if chunk.kind == "case"}),
        "docs": len({chunk.source for chunk in index.chunks if chunk.kind == "doc"}),
        "vectors": len(getattr(index._dense, "ids", []) or []),  # noqa: SLF001 — 摘要用
        "backend": index.vector_backend,
        "bytes": path.stat().st_size,
        "elapsed_ms": elapsed_ms,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m cloudagent_ext.diagnosis.knowledge.ingest",
        description="Build the CloudAgent diagnosis knowledge index (read-only sources).",
    )
    parser.add_argument(
        "--cases",
        default=None,
        help="案例目录；传 none 表示不含案例（docs-only）。不传时默认 docs-only。"
             "⚠️ benchmark 数据集不在本仓（EVAL-P2 迁至评测仓），禁止用 --cases 指向评测仓 golden",
    )

    parser.add_argument("--docs", default=None, help="文档目录（默认 <repo>/docs；传 none 表示不含文档）")
    parser.add_argument("--out", default=None, help="索引输出路径（默认见 retriever.index_path()）")
    parser.add_argument(
        "--allow-outside-root",
        action="store_true",
        help="允许 --cases/--docs 指向仓库外（仅用于测试/临时数据）",
    )
    parser.add_argument(
        "--sparse-only",
        action="store_true",
        help="只建 BM25/稀疏索引，不生成稠密向量（无 bge 模型时用）",
    )
    args = parser.parse_args(argv)

    root = repo_root()
    try:
        docs_disabled = args.docs is not None and str(args.docs).strip().lower() == "none"
        cases_disabled = args.cases is not None and str(args.cases).strip().lower() == "none"
        # EVAL-KB1：默认 docs-only（不找默认案例目录）——benchmark 数据集不在本仓；
        # 显式 --cases <dir> 仍受仓库根守卫；--cases none 与默认等价（显式写法）。
        cases_dir = None
        if args.cases and not cases_disabled:
            cases_dir = Path(args.cases)
            if not cases_dir.is_dir():
                raise ValueError(f"cases directory not found: {cases_dir}")
            if not args.allow_outside_root:
                cases_dir = _ensure_within(cases_dir, root)
        docs_dir = None if docs_disabled else (Path(args.docs) if args.docs else default_docs_dir())
        if not args.allow_outside_root and docs_dir is not None:
            docs_dir = _ensure_within(docs_dir, root)
        out = Path(args.out) if args.out else retriever.index_path()
    except ValueError as exc:
        print(f"ingest: {exc}", file=sys.stderr)
        return 2

    summary = build(cases_dir=cases_dir, docs_dir=docs_dir, out=out, dense=not args.sparse_only)

    # K1.4：索引内容 hash（对 chunks 排序后 sha256）——P8 的 R7 版本化用
    index_hash = _index_content_hash(out)

    print(
        "ingest: {chunks} chunks ({cases} cases + {docs} docs) -> {index} "
        "({bytes} bytes, {elapsed_ms} ms) | vectors={vectors} backend={backend}".format(**summary)
    )
    print(f"ingest: chunk_count={summary['chunks']} index_content_hash={index_hash}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
