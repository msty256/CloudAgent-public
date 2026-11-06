#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""知识库检索服务：索引定位/缓存、限额、结果装配。

对上层只暴露 :func:`search`：返回带 ``chunk_id`` 的片段，**片段是证据不是结论**。
所有限额都在这一层收口（query 长度、top_k、单块长度、总字符），
避免把超大文本塞进模型上下文。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .store import MAX_CHUNK_CHARS, KnowledgeIndex

INDEX_ENV = "CLOUDAGENT_KB_INDEX"
INDEX_VERSION_ENV = "CLOUDAGENT_KB_INDEX_VERSION"
# 重排开关：默认关闭（重排会显著增加延迟，只在需要时显式开启）
RERANK_ENV = "CLOUDAGENT_KB_RERANK"
# 重排候选数：实测单条 20ms，10 条约 270ms、20 条约 750ms。
# 诊断链路上 750ms 不可接受，默认取 10（召回 R@5 已经 100%，重排主要修 R@1 顺序）。
RERANK_CANDIDATES = 10

MAX_QUERY_CHARS = 200
MAX_TOP_K = 8
MAX_TOTAL_CHARS = 6000
MODES = ("bm25", "vector", "hybrid")
DEFAULT_MODE = "hybrid"

_CACHE: dict[str, Any] = {"path": None, "mtime": None, "index": None}


class KnowledgeIndexMissing(FileNotFoundError):
    """索引尚未构建（提示运行 ingest）。"""


class KnowledgeQueryError(ValueError):
    """检索参数非法。"""


def index_path() -> Path:
    """索引路径：``CLOUDAGENT_KB_INDEX`` 优先，否则 ``~/.cloudagent/knowledge/index.json``。"""

    override = os.environ.get(INDEX_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".cloudagent" / "knowledge" / "index.json"


def load_index(path: Path | None = None, *, refresh: bool = False) -> KnowledgeIndex:
    """加载索引（按 mtime 缓存，文件变化自动失效）。"""

    target = Path(path) if path is not None else index_path()
    if not target.is_file():
        raise KnowledgeIndexMissing(
            f"knowledge index not found: {target} (build it with "
            "`python -m cloudagent_ext.diagnosis.knowledge.ingest`)"
        )
    mtime = target.stat().st_mtime
    if (
        not refresh
        and _CACHE["index"] is not None
        and _CACHE["path"] == str(target)
        and _CACHE["mtime"] == mtime
    ):
        return _CACHE["index"]  # type: ignore[no-any-return]
    from .embedder import get_embedder

    index = KnowledgeIndex.load(target, embedder=get_embedder())
    _CACHE.update(path=str(target), mtime=mtime, index=index)
    return index


def reset_cache() -> None:
    """清空进程内索引缓存（测试用）。"""

    _CACHE.update(path=None, mtime=None, index=None)


def _recall(
    index: Any,
    mode: str,
    text: str,
    top_k: int,
    normalized_domain: str | None,
) -> list[tuple[float, int]]:
    """初步召回：领域过滤与重排都需要更宽的候选池。"""

    # 有领域过滤或启用重排时多取一些，避免过滤/重排后不足 top_k。
    wide = max(top_k * 4, top_k) if normalized_domain else top_k
    if rerank_enabled():
        # 重排必须看到比 top_k 更宽的候选，否则只是把同一批结果换个顺序，白花延迟。
        wide = max(wide, min(RERANK_CANDIDATES, len(index.chunks)))
    return index.search(mode, text, wide)


def _maybe_rerank(
    text: str,
    index: Any,
    candidates: list[tuple[float, int]],
    top_k: int,
) -> tuple[list[tuple[float, int]], bool]:
    """对候选做重排；未启用或不可用时原样返回。"""

    if not rerank_enabled() or not candidates:
        return candidates, False
    from .reranker import rerank_top

    texts = [chunk.text for chunk in index.chunks]
    return rerank_top(text, candidates, texts, top_n=RERANK_CANDIDATES)


def rerank_enabled() -> bool:
    """重排是否被显式启用（默认关闭，需要设 CLOUDAGENT_KB_RERANK=on）。"""

    return os.environ.get(RERANK_ENV, "").strip().lower() in {"1", "on", "true", "yes"}


def search(
    query: str,
    *,
    top_k: int = 5,
    domain: str | None = None,
    mode: str = DEFAULT_MODE,
    path: Path | None = None,
) -> dict[str, Any]:
    """检索知识库。

    Args:
        query: 检索语句（建议用症状词，不要整段提问）。
        top_k: 返回条数，1..8。
        domain: 可选领域过滤（sql/log/code/sync/cross），只影响案例块。
        mode: ``bm25`` / ``vector`` / ``hybrid``（默认混合）。
        path: 索引路径覆盖（测试用）。

    Raises:
        KnowledgeQueryError: query 为空/超长、top_k 越界、mode 未知。
        KnowledgeIndexMissing: 索引文件不存在。
    """

    text = (query or "").strip()
    if not text:
        raise KnowledgeQueryError("query is empty")
    if len(text) > MAX_QUERY_CHARS:
        raise KnowledgeQueryError(f"query too long: {len(text)} > {MAX_QUERY_CHARS} chars")
    if not isinstance(top_k, int) or isinstance(top_k, bool):
        raise KnowledgeQueryError("top_k must be an integer")
    if top_k < 1 or top_k > MAX_TOP_K:
        raise KnowledgeQueryError(f"top_k out of range: {top_k} (allowed 1..{MAX_TOP_K})")
    if mode not in MODES:
        raise KnowledgeQueryError(f"unknown mode: {mode!r} (allowed {MODES})")
    normalized_domain = (domain or "").strip().lower() or None

    index = load_index(path)
    backend = getattr(index, "vector_backend", "sparse")
    candidates = _recall(index, mode, text, top_k, normalized_domain)
    reranked, reranked_applied = _maybe_rerank(text, index, candidates, top_k)

    chunks: list[dict[str, Any]] = []
    used_chars = 0
    filtered_out = 0
    for score, position in reranked:
        chunk = index.chunks[position]
        if normalized_domain and chunk.kind == "case" and chunk.domain != normalized_domain:
            filtered_out += 1
            continue
        snippet = chunk.text[:MAX_CHUNK_CHARS]
        if used_chars + len(snippet) > MAX_TOTAL_CHARS:
            break
        used_chars += len(snippet)
        chunks.append(
            {
                "chunk_id": chunk.chunk_id,
                "source": chunk.source,
                "section": chunk.section,
                "kind": chunk.kind,
                "domain": chunk.domain,
                "score": round(float(score), 4),
                "snippet": snippet,
            }
        )
        if len(chunks) >= top_k:
            break

    payload: dict[str, Any] = {
        "mode": mode,
        "query": text,
        "chunks": chunks,
        "total_chars": used_chars,
        "truncated": len(reranked) > len(chunks),
        "index": {
            "path": str(Path(path) if path is not None else index_path()),
            "chunk_count": len(index.chunks),
        },
        "note": (
            "片段是只读证据，不是结论：结论必须由 SQL/日志/代码等数据证据支撑；"
            "引用时请写明 chunk_id，并区分 proves 与 cannot_prove；检索为空时说明知识库无覆盖。"
        ),
        "vector_backend": backend,
        "rerank": {"applied": reranked_applied, "candidates": len(candidates)},
    }
    if normalized_domain:
        payload["domain"] = normalized_domain
        payload["domain_filtered_out"] = filtered_out
    return payload
