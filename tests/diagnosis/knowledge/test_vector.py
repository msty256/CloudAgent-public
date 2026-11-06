#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""稠密向量层测试：embedder 降级、FAISS 存取、RRF 融合、索引版本一致性。

这些测试**不依赖模型文件**（用假 embedder），保证 CI 在无 bge 环境下可跑。
真实模型的端到端验证在 ``scripts/eval_kb.py``（见 docs/knowledge.md）。
"""

from __future__ import annotations

import importlib.util

import pytest

from cloudagent_ext.diagnosis.knowledge import embedder as embedder_mod
from cloudagent_ext.diagnosis.knowledge.embedder import (
    EmbeddingUnavailable,
    NullEmbedder,
    OnnxBgeEmbedder,
    get_embedder,
    reset_embedder,
)
from cloudagent_ext.diagnosis.knowledge.store import Chunk, KnowledgeIndex
from cloudagent_ext.diagnosis.knowledge.vector_store import FaissVectorStore, VectorIndexError

#: ``faiss`` 属于可选依赖（``pip install -e ".[kb]"``），最小安装下没有它。
#: 稠密层测试必须跟着它一起跳过——否则 CI 上"装了什么"会变成隐式前置条件，
#: 而下面的降级路径测试（无需 faiss）必须照常跑，不能被整体 skip 掉。
requires_faiss = pytest.mark.skipif(
    importlib.util.find_spec("faiss") is None,
    reason='dense retrieval needs `faiss-cpu` (pip install -e ".[kb]")',
)


class FakeEmbedder:
    """可预测的假 embedder：按字符出现情况生成 4 维向量。"""

    name = "fake"
    dim = 4

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts):
        self.calls.append(list(texts))
        out = []
        for text in texts:
            out.append(
                [
                    1.0 if "上游" in text else 0.0,
                    1.0 if "下游" in text else 0.0,
                    1.0 if "索引" in text else 0.0,
                    0.01,
                ]
            )
        return out


@pytest.fixture()
def chunks():
    return [
        Chunk("kb:a#0", "cases/a.json", "a", "上游 50000 行、下游 0 行，没有落库", "case", "sync"),
        Chunk("kb:b#0", "cases/b.json", "b", "这条查询走了全表扫描，索引没有命中", "case", "sql"),
        Chunk("kb:c#0", "docs/c.md", "c", "只读三重防线：只读事务、SQL 白名单、只读账号", "doc"),
    ]


# ---------------------------------------------------------------------------
# embedder：降级与可用性
# ---------------------------------------------------------------------------


def test_null_embedder_is_inert():
    null = NullEmbedder()
    assert null.dim == 0
    assert null.embed(["任意文本"]) == []


def test_missing_model_raises_embedding_unavailable(tmp_path):
    with pytest.raises(EmbeddingUnavailable, match="model.onnx not found"):
        OnnxBgeEmbedder(tmp_path)


def test_get_embedder_falls_back_to_null_when_model_missing(tmp_path, monkeypatch):
    monkeypatch.setenv(embedder_mod.MODEL_ENV, str(tmp_path))
    embedder_mod.reset_embedder()
    assert isinstance(get_embedder(), NullEmbedder)
    embedder_mod.reset_embedder()


def test_dense_can_be_disabled_by_env(tmp_path, monkeypatch):
    monkeypatch.setenv(embedder_mod.DISABLE_ENV, "off")
    embedder_mod.reset_embedder()
    assert isinstance(get_embedder(), NullEmbedder)
    embedder_mod.reset_embedder()


def test_model_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv(embedder_mod.MODEL_ENV, str(tmp_path))
    assert embedder_mod.model_dir() == tmp_path


# ---------------------------------------------------------------------------
# FAISS 存储
# ---------------------------------------------------------------------------


@requires_faiss
def test_faiss_store_search_orders_by_similarity():
    store = FaissVectorStore(dim=4)
    store.add(["a", "b"], [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]])
    hits = store.search([1.0, 0.0, 0.0, 0.0], top_k=2)
    assert hits[0][1] == "a"
    assert hits[0][0] == pytest.approx(1.0, abs=1e-5)


@requires_faiss
def test_faiss_store_rejects_dim_mismatch():
    store = FaissVectorStore(dim=4)
    with pytest.raises(VectorIndexError, match="expected"):
        store.add(["a"], [[1.0, 0.0]])


@requires_faiss
def test_faiss_store_rejects_length_mismatch():
    store = FaissVectorStore(dim=4)
    with pytest.raises(VectorIndexError, match="length mismatch"):
        store.add(["a", "b"], [[1.0, 0.0, 0.0, 0.0]])


@requires_faiss
def test_faiss_store_save_load_roundtrip(tmp_path):
    store = FaissVectorStore(dim=4)
    store.add(["a", "b"], [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]])
    index_path = tmp_path / "kb.faiss"
    ids_path = tmp_path / "kb.ids.json"
    store.save(index_path, ids_path)

    loaded = FaissVectorStore.load(index_path, ids_path)
    assert loaded.ids == ["a", "b"]
    assert loaded.search([0.0, 1.0, 0.0, 0.0], top_k=1)[0][1] == "b"


@requires_faiss
def test_faiss_store_rejects_version_mismatch(tmp_path):
    import json

    store = FaissVectorStore(dim=4)
    store.add(["a"], [[1.0, 0.0, 0.0, 0.0]])
    index_path = tmp_path / "kb.faiss"
    ids_path = tmp_path / "kb.ids.json"
    store.save(index_path, ids_path)
    payload = json.loads(ids_path.read_text(encoding="utf-8"))
    payload["version"] = 999
    ids_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(VectorIndexError, match="unsupported vector index version"):
        FaissVectorStore.load(index_path, ids_path)


@requires_faiss
def test_faiss_store_rejects_ids_size_mismatch(tmp_path):
    import json

    store = FaissVectorStore(dim=4)
    store.add(["a", "b"], [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]])
    index_path = tmp_path / "kb.faiss"
    ids_path = tmp_path / "kb.ids.json"
    store.save(index_path, ids_path)
    payload = json.loads(ids_path.read_text(encoding="utf-8"))
    payload["ids"] = ["a"]
    ids_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(VectorIndexError, match="size mismatch"):
        FaissVectorStore.load(index_path, ids_path)


# ---------------------------------------------------------------------------
# KnowledgeIndex：稠密 / 稀疏 / 融合
# ---------------------------------------------------------------------------


@requires_faiss
def test_index_uses_dense_backend_when_available(chunks):
    fake = FakeEmbedder()
    index = KnowledgeIndex(chunks, dense=FaissVectorStore(dim=fake.dim), embedder=fake)
    assert index.vector_backend == "dense"
    hits = index.search_vector("上游 下游", top_k=2)
    assert hits
    assert index.chunks[hits[0][1]].chunk_id == "kb:a#0"


def test_index_falls_back_to_sparse_without_embedder(chunks):
    index = KnowledgeIndex(chunks)
    assert index.vector_backend == "sparse"
    assert index.search_vector("索引", top_k=2)


@requires_faiss
def test_dense_failure_falls_back_to_sparse(chunks):
    class BrokenEmbedder(FakeEmbedder):
        def embed(self, texts):
            raise RuntimeError("model crashed")

    index = KnowledgeIndex(chunks, dense=FaissVectorStore(dim=4), embedder=BrokenEmbedder())
    # 构建阶段就会失败 -> dense 被丢弃，检索退回稀疏
    assert index.vector_backend == "sparse"
    assert index.search_vector("索引", top_k=2)


@requires_faiss
def test_hybrid_combines_bm25_and_dense(chunks):
    fake = FakeEmbedder()
    index = KnowledgeIndex(chunks, dense=FaissVectorStore(dim=fake.dim), embedder=fake)
    fused = index.search_hybrid("上游 下游 没有落库", top_k=3)
    assert fused
    assert index.chunks[fused[0][1]].chunk_id == "kb:a#0"


@requires_faiss
def test_null_embedder_means_sparse_backend(chunks):
    """回归：NullEmbedder(dim=0) 必须被视为"无稠密能力"，不能报告 dense。"""

    index = KnowledgeIndex(chunks, dense=FaissVectorStore(dim=4), embedder=NullEmbedder())
    assert index.vector_backend == "sparse"
    assert index.search_vector("索引", top_k=2)


@requires_faiss
def test_degraded_index_still_retrieves(chunks, tmp_path):
    fake = FakeEmbedder()
    index = KnowledgeIndex(chunks, dense=FaissVectorStore(dim=fake.dim), embedder=fake)
    path = index.save(tmp_path / "index.json")

    degraded = KnowledgeIndex.load(path, embedder=NullEmbedder())
    assert degraded.vector_backend == "sparse"
    assert degraded.search_vector("上游", top_k=1)


@requires_faiss
def test_save_load_keeps_dense_index(chunks, tmp_path):
    fake = FakeEmbedder()
    index = KnowledgeIndex(chunks, dense=FaissVectorStore(dim=fake.dim), embedder=fake)
    path = index.save(tmp_path / "index.json")
    assert path.with_suffix(".faiss").is_file()
    assert path.with_suffix(".ids.json").is_file()

    loaded = KnowledgeIndex.load(path, embedder=fake)
    assert loaded.vector_backend == "dense"
    hits = loaded.search_vector("上游", top_k=1)
    assert loaded.chunks[hits[0][1]].chunk_id == "kb:a#0"


@requires_faiss
def test_load_without_embedder_uses_sparse(chunks, tmp_path):
    fake = FakeEmbedder()
    index = KnowledgeIndex(chunks, dense=FaissVectorStore(dim=fake.dim), embedder=fake)
    path = index.save(tmp_path / "index.json")
    loaded = KnowledgeIndex.load(path)
    assert loaded.vector_backend == "sparse"
