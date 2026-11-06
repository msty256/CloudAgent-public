#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""稠密向量编码（bge-small-zh-v1.5 / ONNX Runtime）。

设计要点：

* **本地推理**：模型文件放本地目录，文本不出机器；
* **可降级**：缺依赖或模型缺失时返回 ``NullEmbedder``，检索自动退回 BM25；
* **有缓存**：按 ``sha1(文本)`` 缓存向量到 ``.npz``，重复建索引不重复推理；
* **确定性**：mean pooling + L2 归一化，同样输入必得同样输出。

模型目录结构（``CLOUDAGENT_BGE_MODEL`` 或默认位置）::

    <model_dir>/
      model.onnx
      tokenizer.json
      config.json        # 可选，用于读取 hidden size
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Iterable, Protocol, Sequence

MODEL_ENV = "CLOUDAGENT_BGE_MODEL"
DISABLE_ENV = "CLOUDAGENT_KB_DENSE"
DEFAULT_MODEL_DIR = Path.home() / ".cloudagent" / "models" / "bge-small-zh-v1.5"
MAX_SEQ_LEN = 512
BATCH_SIZE = 16


class EmbeddingUnavailable(RuntimeError):
    """稠密向量不可用（缺依赖 / 缺模型）。"""


class Embedder(Protocol):
    """最小向量编码接口。"""

    name: str
    dim: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """把一批文本编码成等长向量（已 L2 归一化）。"""


class NullEmbedder:
    """降级实现：永远返回空向量，调用方据此退回 BM25。"""

    name = "null"
    dim = 0

    def embed(self, texts: Sequence[str]) -> list[list[float]]:  # noqa: D401
        return []


class OnnxBgeEmbedder:
    """bge-small-zh-v1.5 的本地 ONNX 实现（mean pooling + L2 normalize）。"""

    name = "bge-small-zh-v1.5"

    def __init__(self, model_dir: Path, *, dim: int = 0, cache_path: Path | None = None) -> None:
        self.model_dir = Path(model_dir)
        self.cache_path = Path(cache_path) if cache_path else self.model_dir / "vectors.npz"
        self._session: Any = None
        self._tokenizer: Any = None
        self._cache: dict[str, list[float]] = {}
        self._dirty = False
        self._dim = dim
        self._load()

    # -- 加载 ---------------------------------------------------------
    def _load(self) -> None:
        onnx_path = self.model_dir / "model.onnx"
        tokenizer_path = self.model_dir / "tokenizer.json"
        if not onnx_path.is_file():
            raise EmbeddingUnavailable(f"model.onnx not found in {self.model_dir}")
        if not tokenizer_path.is_file():
            raise EmbeddingUnavailable(f"tokenizer.json not found in {self.model_dir}")
        try:
            import onnxruntime  # noqa: F401
            from tokenizers import Tokenizer
        except ImportError as exc:  # pragma: no cover - 依赖缺失路径
            raise EmbeddingUnavailable(
                "dense embeddings need `onnxruntime` and `tokenizers` "
                "(pip install -e \".[kb]\")"
            ) from exc

        import onnxruntime as ort

        self._tokenizer = Tokenizer.from_file(str(tokenizer_path))
        # bge 系列按句编码，禁用 padding 由我们手工控制
        self._session = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
        self._input_names = {item.name for item in self._session.get_inputs()}
        if self._dim <= 0:
            self._dim = self._probe_dim()
        self._load_cache()

    def _probe_dim(self) -> int:
        vector = self._infer(["维度探测"])[0]
        return len(vector)

    # -- 缓存 ---------------------------------------------------------
    @staticmethod
    def _key(text: str) -> str:
        return hashlib.sha1(text.encode("utf-8")).hexdigest()

    def _load_cache(self) -> None:
        if not self.cache_path.is_file():
            return
        try:
            import numpy as np

            with np.load(self.cache_path, allow_pickle=False) as payload:
                keys = payload["keys"]
                vectors = payload["vectors"]
            if int(vectors.shape[1]) != self.dim:
                # 维度漂移：不静默截断，直接丢弃缓存重建
                return
            self._cache = {
                str(key): vectors[index].astype("float32").tolist()
                for index, key in enumerate(keys)
            }
        except Exception:  # noqa: BLE001 — 缓存损坏等价于没有缓存
            self._cache = {}

    def save_cache(self) -> None:
        if not self._dirty:
            return
        import numpy as np

        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        keys = list(self._cache)
        vectors = np.asarray([self._cache[key] for key in keys], dtype="float32")
        tmp = self.cache_path.with_suffix(".tmp.npz")
        np.savez(tmp, keys=np.asarray(keys), vectors=vectors)
        os.replace(tmp, self.cache_path)
        self._dirty = False

    # -- 推理 ---------------------------------------------------------
    @property
    def dim(self) -> int:
        return self._dim

    def _infer(self, texts: Sequence[str]) -> list[list[float]]:
        import numpy as np

        encodings = [
            self._tokenizer.encode(text, add_special_tokens=True).ids[:MAX_SEQ_LEN]
            for text in texts
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
        # 只喂模型实际声明的输入，避免不同导出方式的差异
        feed = {name: value for name, value in feed.items() if name in self._input_names}
        outputs = self._session.run(None, feed)
        hidden = outputs[0]  # (batch, seq, hidden)

        mask = attention[..., None].astype("float32")
        summed = (hidden * mask).sum(axis=1)
        counts = np.clip(mask.sum(axis=1), 1e-6, None)
        pooled = summed / counts
        norms = np.linalg.norm(pooled, axis=1, keepdims=True)
        normalized = pooled / np.clip(norms, 1e-12, None)
        return normalized.astype("float32").tolist()

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        missing: list[str] = []
        seen: set[str] = set()
        for text in texts:
            key = self._key(text)
            if key not in self._cache and key not in seen:
                seen.add(key)
                missing.append(text)
        for start in range(0, len(missing), BATCH_SIZE):
            batch = missing[start : start + BATCH_SIZE]
            for text, vector in zip(batch, self._infer(batch)):
                self._cache[self._key(text)] = vector
                self._dirty = True
        return [self._cache[self._key(text)] for text in texts]

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]


_EMBEDDER: Embedder | None = None


def model_dir() -> Path:
    override = os.environ.get(MODEL_ENV)
    return Path(override).expanduser() if override else DEFAULT_MODEL_DIR


def dense_disabled() -> bool:
    return os.environ.get(DISABLE_ENV, "").strip().lower() in {"0", "off", "false", "none", "no"}


def get_embedder(*, refresh: bool = False) -> Embedder:
    """返回进程级 embedder；不可用时返回 ``NullEmbedder``（不抛异常）。"""

    global _EMBEDDER
    if _EMBEDDER is not None and not refresh:
        return _EMBEDDER
    if dense_disabled():
        _EMBEDDER = NullEmbedder()
        return _EMBEDDER
    try:
        _EMBEDDER = OnnxBgeEmbedder(model_dir())
    except EmbeddingUnavailable:
        _EMBEDDER = NullEmbedder()
    return _EMBEDDER


def reset_embedder() -> None:
    """清空进程级 embedder（测试用）。"""

    global _EMBEDDER
    _EMBEDDER = None


def embed_texts(texts: Iterable[str]) -> list[list[float]]:
    return get_embedder().embed(list(texts))
