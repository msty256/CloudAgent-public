#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""FAISS 向量索引的构建、持久化与检索。

* 归一化后用内积（``IndexFlatIP``）等价余弦相似度；
* 索引文件与块清单 ``ids`` 必须同源同版本（不一致直接报错，不做静默对齐）；
* 数据量小（千级）用 Flat 精确检索；上到数万再换 ``HNSW``，接口不变。
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

VECTOR_INDEX_VERSION = 1


class VectorIndexError(RuntimeError):
    """向量索引不可用/不一致。"""


class FaissVectorStore:
    """薄封装：只做 add / search / save / load。"""

    def __init__(self, dim: int) -> None:
        if dim <= 0:
            raise VectorIndexError(f"invalid embedding dim: {dim}")
        try:
            import faiss
        except ImportError as exc:  # pragma: no cover - 依赖缺失路径
            raise VectorIndexError(
                'dense retrieval needs `faiss-cpu` (pip install -e ".[kb]")'
            ) from exc
        self._faiss = faiss
        self.dim = dim
        self.index = faiss.IndexFlatIP(dim)
        self.ids: list[str] = []

    # -- 构建 ---------------------------------------------------------
    def add(self, chunk_ids: Sequence[str], vectors: Sequence[Sequence[float]]) -> None:
        if len(chunk_ids) != len(vectors):
            raise VectorIndexError(
                f"ids/vectors length mismatch: {len(chunk_ids)} vs {len(vectors)}"
            )
        if not chunk_ids:
            return
        matrix = self._as_matrix(vectors)
        self.index.add(matrix)
        self.ids.extend(str(chunk_id) for chunk_id in chunk_ids)

    def _as_matrix(self, vectors: Sequence[Sequence[float]]):
        import numpy as np

        matrix = np.asarray(vectors, dtype="float32")
        if matrix.ndim != 2 or matrix.shape[1] != self.dim:
            raise VectorIndexError(f"expected (*, {self.dim}) vectors, got {matrix.shape}")
        self._faiss.normalize_L2(matrix)
        return matrix

    # -- 检索 ---------------------------------------------------------
    def search(self, query_vector: Sequence[float], top_k: int = 5) -> list[tuple[float, str]]:
        if not self.ids:
            return []
        matrix = self._as_matrix([query_vector])
        scores, positions = self.index.search(matrix, min(top_k, len(self.ids)))
        out: list[tuple[float, str]] = []
        for score, position in zip(scores[0], positions[0]):
            if position < 0:
                continue
            out.append((float(score), self.ids[int(position)]))
        return out

    # -- 持久化 -------------------------------------------------------
    def save(self, index_path: Path, ids_path: Path) -> None:
        import json

        index_path = Path(index_path)
        index_path.parent.mkdir(parents=True, exist_ok=True)
        self._faiss.write_index(self.index, str(index_path))
        Path(ids_path).write_text(
            json.dumps(
                {"version": VECTOR_INDEX_VERSION, "dim": self.dim, "ids": self.ids},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, index_path: Path, ids_path: Path) -> "FaissVectorStore":
        import json

        index_path = Path(index_path)
        ids_path = Path(ids_path)
        if not index_path.is_file() or not ids_path.is_file():
            raise VectorIndexError(f"vector index or ids file missing: {index_path} / {ids_path}")
        payload = json.loads(ids_path.read_text(encoding="utf-8"))
        if payload.get("version") != VECTOR_INDEX_VERSION:
            raise VectorIndexError(
                f"unsupported vector index version: {payload.get('version')!r} "
                f"(expected {VECTOR_INDEX_VERSION})"
            )
        store = cls(int(payload.get("dim") or 0))
        store.index = store._faiss.read_index(str(index_path))
        if store.index.d != store.dim:
            raise VectorIndexError(
                f"vector index dim mismatch: file={store.index.d} ids={store.dim}"
            )
        ids = [str(item) for item in payload.get("ids") or []]
        if len(ids) != store.index.ntotal:
            raise VectorIndexError(
                f"vector index/ids size mismatch: ntotal={store.index.ntotal} ids={len(ids)}"
            )
        store.ids = ids
        return store

    def __len__(self) -> int:
        return len(self.ids)
