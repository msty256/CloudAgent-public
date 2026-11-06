#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""重排层测试：模型缺失降级、重排顺序、候选截断、异常回退、开关。

不依赖真实模型（用假 reranker），保证 CI 无模型环境也能跑。
"""

from __future__ import annotations

import pytest

from cloudagent_ext.diagnosis.knowledge import reranker as reranker_mod
from cloudagent_ext.diagnosis.knowledge.reranker import (
    NullReranker,
    OnnxBgeReranker,
    RerankUnavailable,
    get_reranker,
    rerank_top,
    reset_reranker,
)


class FakeReranker:
    """可预测的假重排器：谁包含 query 里的词，分越高。"""

    name = "fake"

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []

    def score(self, query: str, documents):
        self.calls.append((query, list(documents)))
        out = []
        for doc in documents:
            hits = sum(1 for token in query if token in doc)
            out.append(float(hits))
        return out


CANDIDATES = [(0.9, 0), (0.8, 1), (0.7, 2), (0.6, 3)]
TEXTS = [
    "SQL 白名单只允许 SELECT",      # 与 query 无关
    "查询走了全表扫描，索引没命中",   # 高度相关
    "索引失效的常见原因",            # 相关
    "设备生命周期管理",              # 无关
]


# ---------------------------------------------------------------------------
# 降级与可用性
# ---------------------------------------------------------------------------


def test_null_reranker_keeps_everything():
    null = NullReranker()
    assert null.score("任意问题", ["文档A", "文档B"]) == [0.0, 0.0]


def test_missing_model_raises_rerank_unavailable(tmp_path):
    with pytest.raises(RerankUnavailable, match="model.onnx not found"):
        OnnxBgeReranker(tmp_path)


def test_get_reranker_falls_back_to_null(tmp_path, monkeypatch):
    monkeypatch.setenv(reranker_mod.MODEL_ENV, str(tmp_path))
    reranker_mod.reset_reranker()
    assert isinstance(get_reranker(), NullReranker)
    reranker_mod.reset_reranker()


def test_rerank_can_be_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv(reranker_mod.DISABLE_ENV, "off")
    reranker_mod.reset_reranker()
    assert isinstance(get_reranker(), NullReranker)
    reranker_mod.reset_reranker()


def test_model_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv(reranker_mod.MODEL_ENV, str(tmp_path))
    assert reranker_mod.model_dir() == tmp_path


# ---------------------------------------------------------------------------
# 重排逻辑
# ---------------------------------------------------------------------------


def test_rerank_reorders_candidates_by_model_score():
    """原本排第 2 的（索引没命中）应该被提到第 1。"""

    fake = FakeReranker()
    reordered, applied = rerank_top("索引没命中", CANDIDATES, TEXTS, top_n=4, reranker=fake)
    assert applied is True
    positions = [position for _score, position in reordered]
    assert positions[0] == 1, "相关文档应被提到第一位"


def test_rerank_only_touches_top_n():
    """tail 部分保持原顺序追加，不参与打分。"""

    fake = FakeReranker()
    reordered, applied = rerank_top("索引", CANDIDATES, TEXTS, top_n=2, reranker=fake)
    assert applied is True
    # 只对前 2 个打分：候选 0 和 1
    assert len(fake.calls[0][1]) == 2
    # 后 2 个保持原序（2, 3）
    assert [p for _s, p in reordered[2:]] == [2, 3]


def test_rerank_returns_false_when_null_reranker():
    reordered, applied = rerank_top("索引", CANDIDATES, TEXTS, top_n=4, reranker=NullReranker())
    assert applied is False
    assert [p for _s, p in reordered] == [0, 1, 2, 3]


def test_rerank_falls_back_when_model_raises():
    class BrokenReranker:
        name = "broken"

        def score(self, query, documents):
            raise RuntimeError("model exploded")

    reordered, applied = rerank_top("索引", CANDIDATES, TEXTS, top_n=4, reranker=BrokenReranker())
    assert applied is False
    assert [p for _s, p in reordered] == [0, 1, 2, 3]


def test_rerank_falls_back_on_score_count_mismatch():
    class ShortReranker:
        name = "short"

        def score(self, query, documents):
            return [1.0]  # 数量对不上

    reordered, applied = rerank_top("索引", CANDIDATES, TEXTS, top_n=4, reranker=ShortReranker())
    assert applied is False
    assert [p for _s, p in reordered] == [0, 1, 2, 3]


def test_rerank_empty_candidates():
    reordered, applied = rerank_top("索引", [], [], top_n=4, reranker=FakeReranker())
    assert reordered == []
    assert applied is False


def test_rerank_scores_are_attached():
    fake = FakeReranker()
    reordered, _ = rerank_top("索引没命中", CANDIDATES, TEXTS, top_n=2, reranker=fake)
    head_scores = [score for score, _pos in reordered[:2]]
    assert head_scores == sorted(head_scores, reverse=True)
