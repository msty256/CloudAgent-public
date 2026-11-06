#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""重排（rerank）：用交叉编码器对初步召回结果重排。

**为什么需要**：向量检索是"双塔"——问题和文档分开编码，各自变成向量算距离。
快，但精确度有限，因为两边在编码时**互相看不见**。

重排用"交叉编码器"（cross-encoder）：把 "问题 + 文档" 拼在一起送进模型，
让模型同时看到两段文本再打分。慢得多，但精度高，所以只对**少量候选**（Top-N）使用。

本模块的设计取舍：

* 只对召回结果的 Top-N（默认 20）重排，不参与全库检索；
* 模型不可用时**静默降级**为原始顺序（不阻塞诊断，也不假装重排过）；
* 分数归一化到 0–1 区间，便于日志观察（但排序只用相对大小）。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Protocol, Sequence

MODEL_ENV = "CLOUDAGENT_RERANK_MODEL"
DISABLE_ENV = "CLOUDAGENT_KB_RERANK"
DEFAULT_MODEL_DIR = Path.home() / ".cloudagent" / "models" / "bge-reranker-base"
MAX_PAIR_LEN = 512
BATCH_SIZE = 8
# 召回 Top-N 才重排：N 越大越准、越慢。
# 实测（单次）：N=5 约 73ms、N=10 约 271ms、N=20 约 751ms、N=40 约 1827ms。
# 诊断链路上超过 300ms 会明显拖慢体验，默认取 10。
DEFAULT_CANDIDATES = 10


class RerankUnavailable(RuntimeError):
    """重排模型不可用（缺依赖 / 缺模型）。"""


class Reranker(Protocol):
    """最小重排接口：给问题和候选文本，返回每条的分数。"""

    name: str

    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        ...


class NullReranker:
    """降级实现：保持原顺序（分数全等）。"""

    name = "null"

    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        return [0.0] * len(documents)


class OnnxBgeReranker:
    """bge-reranker-base 的本地 ONNX 实现。

    输入 "query[SEP]document" 形式，模型输出一个 logit；
    经 sigmoid 归一化到 0–1（单调变换，不改变排序，只便于观察）。
    """

    name = "bge-reranker-base"

    def __init__(self, model_dir: Path) -> None:
        self.model_dir = Path(model_dir)
        self._session: Any = None
        self._tokenizer: Any = None
        self._input_names: set[str] = set()
        self._load()

    def _load(self) -> None:
        onnx_path = self.model_dir / "model.onnx"
        tokenizer_path = self.model_dir / "tokenizer.json"
        if not onnx_path.is_file():
            raise RerankUnavailable(f"model.onnx not found in {self.model_dir}")
        if not tokenizer_path.is_file():
            raise RerankUnavailable(f"tokenizer.json not found in {self.model_dir}")
        try:
            import onnxruntime
            from tokenizers import Tokenizer
        except ImportError as exc:  # pragma: no cover
            raise RerankUnavailable(
                'rerank needs `onnxruntime` and `tokenizers` (pip install -e ".[kb]")'
            ) from exc

        import onnxruntime as ort

        self._tokenizer = Tokenizer.from_file(str(tokenizer_path))
        self._session = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
        self._input_names = {item.name for item in self._session.get_inputs()}

    def _infer(self, pairs: Sequence[tuple[str, str]]) -> list[float]:
        import numpy as np

        encodings = [
            self._tokenizer.encode(query, document, add_special_tokens=True).ids[:MAX_PAIR_LEN]
            for query, document in pairs
        ]
        max_len = max(len(ids) for ids in encodings)
        input_ids = np.zeros((len(encodings), max_len), dtype="int64")
        attention = np.zeros((len(encodings), max_len), dtype="int64")
        token_type = np.zeros((len(encodings), max_len), dtype="int64")
        for row, ids in enumerate(encodings):
            input_ids[row, : len(ids)] = ids
            attention[row, : len(ids)] = 1
        feed = {
            "input_ids": input_ids,
            "attention_mask": attention,
            "token_type_ids": token_type,
        }
        feed = {name: value for name, value in feed.items() if name in self._input_names}
        logits = self._session.run(None, feed)[0]
        # 输出形状 (batch, 1) 或 (batch,)，统一压平成 batch
        flat = np.asarray(logits).reshape(len(pairs), -1)[:, 0]
        # sigmoid → 0..1（单调，不改变排序）
        scores = 1.0 / (1.0 + np.exp(-flat.astype("float32")))
        return [float(value) for value in scores]

    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        if not documents:
            return []
        out: list[float] = []
        for start in range(0, len(documents), BATCH_SIZE):
            batch = documents[start : start + BATCH_SIZE]
            out.extend(self._infer([(query, doc) for doc in batch]))
        return out


_RERANKER: Reranker | None = None


def model_dir() -> Path:
    override = os.environ.get(MODEL_ENV)
    return Path(override).expanduser() if override else DEFAULT_MODEL_DIR


def rerank_disabled() -> bool:
    return os.environ.get(DISABLE_ENV, "").strip().lower() in {"0", "off", "false", "none", "no"}


def get_reranker(*, refresh: bool = False) -> Reranker:
    """返回进程级 reranker；不可用时返回 ``NullReranker``（不抛异常）。"""

    global _RERANKER
    if _RERANKER is not None and not refresh:
        return _RERANKER
    if rerank_disabled():
        _RERANKER = NullReranker()
        return _RERANKER
    try:
        _RERANKER = OnnxBgeReranker(model_dir())
    except RerankUnavailable:
        _RERANKER = NullReranker()
    return _RERANKER


def reset_reranker() -> None:
    global _RERANKER
    _RERANKER = None


def rerank_top(
    query: str,
    candidates: Sequence[tuple[float, int]],
    texts: Sequence[str],
    *,
    top_n: int,
    reranker: Reranker | None = None,
) -> tuple[list[tuple[float, int]], bool]:
    """对前 ``top_n`` 个候选重排，其余保持原顺序追加。

    Args:
        query: 用户问题。
        candidates: ``[(原始分数, 位置下标), ...]``，已按原始分数降序。
        texts: 与位置下标对应的文本。
        top_n: 参与重排的候选数。
        reranker: 可注入（测试用）；默认取进程级实例。

    Returns:
        ``(重排后的候选列表, 是否真的执行了重排)``。
        reranker 不可用时原样返回，第二个值为 ``False``，调用方据此如实报告。
    """

    if not candidates:
        return [], False
    active = reranker if reranker is not None else get_reranker()
    if isinstance(active, NullReranker) or getattr(active, "name", "null") == "null":
        return list(candidates), False

    head = candidates[:top_n]
    tail = candidates[top_n:]
    try:
        scores = active.score(query, [texts[position] for _score, position in head])
    except Exception:  # noqa: BLE001 — 重排失败退回原序，不影响主流程
        return list(candidates), False
    if len(scores) != len(head):
        return list(candidates), False

    reordered = [
        (float(score), position) for score, (_original, position) in zip(scores, head)
    ]
    reordered.sort(key=lambda item: item[0], reverse=True)
    return reordered + list(tail), True
