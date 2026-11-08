#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""``kb-query`` 只读 CLI（EVAL-P8 T8.1）——检索层的被测接口。

stdout 即契约（设计 ``eval-p8-rag.md`` §4，单行 JSON）::

    {"query": "...", "top_k": 5, "domain": null,
     "index": {"version": 1, "chunk_count": 432, "content_hash": "<16hex>"},
     "latency_ms": 12.3,
     "chunks": [{"chunk_id": "...", "source": "...", "kind": "doc",
                 "score": 0.83, "section": "..."}]}

纪律：
- **只读、不调模型**（走 :func:`retriever.search`，与产品运行时同一实现）；
- **状态诚实**（P7c 口径）：索引缺失/参数非法 → stderr + 非 0 退出，
  **绝不返回空数组冒充成功**；合法空结果（索引在但无命中）→ rc 0 且 chunks=[]；
- ``index.content_hash`` 与评测仓 ``report._index_content_hash`` 同一算方
  （排序后 sha256(chunk_id+text) 取 16 hex）——R7 版本化跨仓可比。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

__all__ = ["run_kb_query", "index_content_hash"]


def index_content_hash(index_file: Path) -> str:
    """索引内容哈希（与评测仓 report._index_content_hash 同一算方，R7 可比）。"""

    data = json.loads(index_file.read_text(encoding="utf-8"))
    sha = hashlib.sha256()
    for chunk in sorted(data.get("chunks", []), key=lambda c: c.get("chunk_id", "")):
        sha.update(str(chunk.get("chunk_id", "")).encode("utf-8"))
        sha.update(str(chunk.get("text", "")).encode("utf-8"))
    return sha.hexdigest()[:16]


def run_kb_query(argv: list[str] | None = None) -> int:
    """执行一次只读检索并按 §4 契约输出 JSON；错误 → stderr + 非 0。"""

    from .retriever import (
        KnowledgeIndexMissing,
        KnowledgeQueryError,
        index_path,
        search,
    )
    from cloudagent_ext.utils.redaction import redact_sensitive

    parser = argparse.ArgumentParser(
        prog="kb-query",
        description="只读检索知识库（不调模型；stdout=单行 JSON 契约）",
    )
    parser.add_argument("--query", required=True, help="检索语句（建议症状词）")
    parser.add_argument("--top-k", type=int, default=5, help="返回条数（1..retriever.MAX_TOP_K）")
    parser.add_argument("--domain", default=None,
                        help="可选领域过滤（sql/log/code/sync/cross；只影响案例块）")
    parser.add_argument("--json", action="store_true",
                        help="输出 JSON（当前唯一输出形态；为设计契约显式保留）")
    args = parser.parse_args(argv)

    started = time.perf_counter()
    try:
        result = search(args.query, top_k=args.top_k, domain=args.domain)
    except (KnowledgeIndexMissing, KnowledgeQueryError, ValueError, OSError) as exc:
        # 状态诚实：失败必须可判别——stderr 一行 + 非 0，不输出任何 JSON
        print(f"kb-query: {redact_sensitive(str(exc))}", file=sys.stderr)
        return 2

    index_file = Path(result["index"]["path"])
    try:
        version: Any = json.loads(index_file.read_text(encoding="utf-8")).get("version")
        content_hash = index_content_hash(index_file)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"kb-query: 索引元数据读取失败：{redact_sensitive(str(exc))}", file=sys.stderr)
        return 2

    payload = {
        "query": result["query"],
        "top_k": args.top_k,
        "domain": args.domain,
        "index": {
            "version": version,
            "chunk_count": int(result["index"]["chunk_count"]),
            "content_hash": content_hash,
        },
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        "chunks": [
            {
                "chunk_id": chunk["chunk_id"],
                "source": chunk["source"],
                "kind": chunk["kind"],
                "score": chunk["score"],
                "section": chunk["section"],
            }
            for chunk in result["chunks"]
        ],
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover — python -m 直跑入口
    raise SystemExit(run_kb_query())
