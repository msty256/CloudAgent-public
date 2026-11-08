#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""知识库检索评测：BM25 / 向量 / 混合三路对比（Recall@k、MRR、延迟）。

标注格式（``eval/kb_queries.jsonl``）::

    {"query": "上游有数据下游没有", "expected": []},  # EVAL-KB1：case 数据集已迁评测仓，期望列表待重建

用法::

    python scripts/eval_kb.py
    python scripts/eval_kb.py --queries eval/kb_queries.jsonl --topk 5
    python scripts/eval_kb.py --index ~/.cloudagent/knowledge/index.json

说明：``expected`` 里可以写多个来源，命中任意一个即算召回；只评估**检索层**，
不涉及诊断结论正确率（那是 38 题评分器的事，两套指标不要混）。
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cloudagent_ext.diagnosis.knowledge.store import KnowledgeIndex, build_chunks  # noqa: E402

MODES = ("bm25", "vector", "hybrid")
KS = (1, 3, 5)


def load_queries(path: Path) -> list[tuple[str, set[str]]]:
    pairs: list[tuple[str, set[str]]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        payload = json.loads(line)
        pairs.append((str(payload["query"]), {str(item) for item in payload["expected"]}))
    return pairs


def evaluate(
    index: KnowledgeIndex,
    mode: str,
    pairs: list[tuple[str, set[str]]],
    topk: int,
    *,
    rerank: bool = False,
    reranker=None,
) -> dict:
    hits = {k: 0 for k in KS}
    reciprocal_ranks: list[float] = []
    latencies: list[float] = []
    misses: list[str] = []
    pool = max(topk, max(KS))
    for query, expected in pairs:
        started = time.perf_counter()
        results = index.search(mode, query, pool)
        if rerank:
            from cloudagent_ext.diagnosis.knowledge.reranker import rerank_top

            texts = [chunk.text for chunk in index.chunks]
            results, _applied = rerank_top(
                query, results, texts, top_n=len(results), reranker=reranker
            )
        latencies.append((time.perf_counter() - started) * 1000)
        ranks = [
            rank
            for rank, (_score, position) in enumerate(results, start=1)
            if index.chunks[position].source in expected
        ]
        if not ranks:
            misses.append(query)
            reciprocal_ranks.append(0.0)
            continue
        rank = min(ranks)
        for k in KS:
            hits[k] += 1 if rank <= k else 0
        reciprocal_ranks.append(1.0 / rank)
    total = len(pairs) or 1
    return {
        "mode": mode,
        "n": len(pairs),
        "recall": {k: hits[k] / total for k in KS},
        "mrr": sum(reciprocal_ranks) / total,
        "p50_ms": statistics.median(latencies) if latencies else 0.0,
        "misses": misses,
    }


def build_or_load(args) -> KnowledgeIndex:
    """优先加载已构建索引（含稠密向量）；否则现建（会尝试稠密，失败则稀疏）。"""

    from cloudagent_ext.diagnosis.knowledge.embedder import get_embedder
    from cloudagent_ext.diagnosis.knowledge.retriever import index_path

    if args.index:
        return KnowledgeIndex.load(Path(args.index), embedder=get_embedder())
    built = index_path()
    if built.is_file():
        return KnowledgeIndex.load(built, embedder=get_embedder())
    cases = Path(args.cases)
    docs = Path(args.docs) if args.docs else None
    return KnowledgeIndex(build_chunks(cases, docs), embedder=get_embedder())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate knowledge retrieval (BM25 / vector / hybrid).")
    parser.add_argument(
        "--cases", default="none",
        help="EVAL-KB1 后案例数据集不在本仓（benchmark 归评测仓）；"
             "默认 docs-only。历史 CASES 期望列表（cases/sync-001.json 等）已失效",
    )
    parser.add_argument("--docs", default=str(REPO_ROOT / "docs"))
    parser.add_argument("--queries", default=str(REPO_ROOT / "eval" / "kb_queries.jsonl"))
    parser.add_argument("--index", default=None, help="直接加载已构建索引（优先于 --cases/--docs）")
    parser.add_argument("--topk", type=int, default=5)
    parser.add_argument(
        "--rerank",
        action="store_true",
        help="额外跑一组『混合 + 重排』对比（需要 bge-reranker 模型）",
    )
    args = parser.parse_args(argv)

    pairs = load_queries(Path(args.queries))
    if not pairs:
        print("eval_kb: no queries found", file=sys.stderr)
        return 2
    index = build_or_load(args)
    print(f"index: {len(index.chunks)} chunks | backend: {index.vector_backend} | queries: {len(pairs)}\n")
    print(f"{'mode':16s} {'Recall@1':>8s} {'Recall@3':>8s} {'Recall@5':>8s} {'MRR':>7s} {'p50 ms':>7s}")
    print("-" * 62)
    for mode in MODES:
        result = evaluate(index, mode, pairs, args.topk)
        recall = result["recall"]
        print(
            f"{mode:16s} {recall[1]:8.1%} {recall[3]:8.1%} {recall[5]:8.1%} "
            f"{result['mrr']:7.3f} {result['p50_ms']:7.2f}"
        )
        if result["misses"]:
            for miss in result["misses"]:
                print(f"    miss: {miss}")

    if args.rerank:
        from cloudagent_ext.diagnosis.knowledge.reranker import get_reranker

        reranker = get_reranker()
        if getattr(reranker, "name", "null") == "null":
            print("\n[rerank] 模型不可用，跳过（检查 ~/.cloudagent/models/bge-reranker-base）")
            return 0
        print(f"\n[rerank] model={reranker.name}\n")
        print(f"{'mode':16s} {'Recall@1':>8s} {'Recall@3':>8s} {'Recall@5':>8s} {'MRR':>7s} {'p50 ms':>7s}")
        print("-" * 62)
        for mode in MODES:
            result = evaluate(index, mode, pairs, args.topk, rerank=True, reranker=reranker)
            recall = result["recall"]
            print(
                f"{mode + '+rerank':16s} {recall[1]:8.1%} {recall[3]:8.1%} {recall[5]:8.1%} "
                f"{result['mrr']:7.3f} {result['p50_ms']:7.2f}"
            )
            if result["misses"]:
                for miss in result["misses"]:
                    print(f"    miss: {miss}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
