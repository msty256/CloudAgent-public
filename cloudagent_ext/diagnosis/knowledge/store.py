#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""知识库切块与混合检索索引（BM25 + 稀疏向量 + RRF）。

设计要点：

* **零第三方依赖**：纯标准库实现，离线可跑。向量层当前是 TF-IDF 稀疏向量，
  语义向量（bge / FAISS）后续可通过 ``EmbeddingBackend`` 接入，融合逻辑不变。
* **只读**：本模块只读 cases/docs 文本；索引落盘由 :mod:`ingest` 负责。
* **可解释**：检索结果带 ``chunk_id / source / section / score``，可直接
  作为证据引用（``ev:kb:<seq>``）。
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

INDEX_VERSION = 1
MAX_CHUNK_CHARS = 700
CHUNK_OVERLAP = 100
RRF_K = 60

_CJK = "\u4e00-\u9fff"
_TOKEN_RE = re.compile(rf"[a-zA-Z_][a-zA-Z0-9_]*|[{_CJK}]")


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Chunk:
    """一段可检索知识。"""

    chunk_id: str
    source: str  # "cases/sync-001.json" / "docs/security.md"
    section: str
    text: str
    kind: str  # "case" | "doc"
    domain: str = ""  # case: sql/log/code/sync/cross；doc: 空

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "source": self.source,
            "section": self.section,
            "text": self.text,
            "kind": self.kind,
            "domain": self.domain,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Chunk":
        return cls(
            chunk_id=str(payload["chunk_id"]),
            source=str(payload["source"]),
            section=str(payload.get("section") or ""),
            text=str(payload["text"]),
            kind=str(payload.get("kind") or "doc"),
            domain=str(payload.get("domain") or ""),
        )


# ---------------------------------------------------------------------------
# 切块
# ---------------------------------------------------------------------------


def split_text(text: str, max_chars: int = MAX_CHUNK_CHARS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """按空行/段落切块；超长段再按字符硬切，带 overlap 防止结论被切断。"""

    parts = [part.strip() for part in re.split(r"\n\s*\n", text or "") if part.strip()]
    out: list[str] = []
    for part in parts:
        if len(part) <= max_chars:
            out.append(part)
            continue
        step = max(1, max_chars - overlap)
        for start in range(0, len(part), step):
            piece = part[start : start + max_chars].strip()
            if piece:
                out.append(piece)
    return out


def _relative(path: Path, root: Path) -> str:
    """返回相对路径；越界（``../``）直接拒绝。"""

    resolved = path.resolve()
    root_resolved = root.resolve()
    try:
        rel = resolved.relative_to(root_resolved)
    except ValueError as exc:  # pragma: no cover - 防御性分支
        raise ValueError(f"path escapes allowed root: {path}") from exc
    return rel.as_posix()


def chunk_case(payload: dict[str, Any], rel: str) -> list[Chunk]:
    """把一个诊断案例压成"症状 → 根因 → 建议"知识块（整条不切）。"""

    case_id = str(payload.get("case_id") or Path(rel).stem)
    domain = str(payload.get("domain") or "")
    ground_truth = payload.get("ground_truth") or {}
    input_block = payload.get("input") or {}
    lines = [
        f"案例 {case_id}｜领域 {domain}｜场景 {payload.get('scenario') or '?'}",
        "问题：" + str(input_block.get("question") or ""),
    ]
    for cause in ground_truth.get("root_causes") or []:
        if isinstance(cause, dict) and cause.get("description"):
            lines.append("根因：" + str(cause["description"]))
    for rec in ground_truth.get("acceptable_recommendations") or []:
        if isinstance(rec, dict) and rec.get("description"):
            lines.append("建议：" + str(rec["description"]))
    forbidden = ground_truth.get("forbidden_findings") or []
    if forbidden:
        lines.append("禁止结论：" + "；".join(str(item) for item in forbidden))
    if payload.get("notes"):
        lines.append("备注：" + str(payload["notes"]))
    text = "\n".join(line for line in lines if line and not line.endswith("："))
    return [
        Chunk(f"kb:{rel}#{index}", rel, case_id, piece, "case", domain)
        for index, piece in enumerate(split_text(text))
    ]


def chunk_doc(path: Path, rel: str) -> list[Chunk]:
    """按 Markdown 标题分段，再把超长段切成 ``MAX_CHUNK_CHARS``。"""

    text = path.read_text(encoding="utf-8", errors="ignore")
    chunks: list[Chunk] = []
    section = "root"
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        if not buffer:
            return
        body = "\n".join(buffer).strip()
        # 标题进正文：让「评测」「证据协议」这类小节标题参与召回（BM25/向量都能用上）。
        # 注意前缀也算进配额，否则切块会突破 MAX_CHUNK_CHARS（早期实现踩过）。
        prefix = "" if section == "root" else section + "\n"
        budget = max(1, MAX_CHUNK_CHARS - len(prefix))
        for index, piece in enumerate(split_text(body, max_chars=budget)):
            chunks.append(Chunk(f"kb:{rel}#{section}#{index}", rel, section, prefix + piece, "doc"))
        buffer = []

    for line in text.splitlines():
        if line.startswith("#"):
            flush()
            section = line.lstrip("#").strip() or "root"
        else:
            buffer.append(line)
    flush()
    return chunks


def build_chunks(cases_dir: Path, docs_dir: Path | None = None) -> list[Chunk]:
    """从案例目录与文档目录构建去重后的知识块列表（只读）。"""

    chunks: list[Chunk] = []
    cases_dir = Path(cases_dir)
    if cases_dir.is_dir():
        for path in sorted(cases_dir.rglob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict) or "case_id" not in payload:
                continue
            chunks.extend(chunk_case(payload, "cases/" + _relative(path, cases_dir)))
    if docs_dir is not None:
        docs_dir = Path(docs_dir)
        if docs_dir.is_dir():
            for path in sorted(docs_dir.glob("*.md")):
                chunks.extend(chunk_doc(path, "docs/" + path.name))
    return _dedupe(chunks)


def _dedupe(chunks: Iterable[Chunk]) -> list[Chunk]:
    seen: set[str] = set()
    out: list[Chunk] = []
    for chunk in chunks:
        key = chunk.text.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(chunk)
    return out


# ---------------------------------------------------------------------------
# 分词
# ---------------------------------------------------------------------------


def tokenize(text: str) -> list[str]:
    """英文按词、中文按单字 + 二元组（不引入分词器，零依赖）。"""

    raw = _TOKEN_RE.findall((text or "").lower())
    tokens: list[str] = []
    cjk: list[str] = []

    def flush() -> None:
        if len(cjk) >= 2:
            tokens.extend(cjk)
            tokens.extend(first + second for first, second in zip(cjk, cjk[1:]))
        elif cjk:
            tokens.extend(cjk)
        cjk.clear()

    for token in raw:
        if len(token) == 1 and "\u4e00" <= token <= "\u9fff":
            cjk.append(token)
        else:
            flush()
            tokens.append(token)
    flush()
    return tokens


# ---------------------------------------------------------------------------
# 索引与检索
# ---------------------------------------------------------------------------


class KnowledgeIndex:
    """BM25 + 向量检索（稠密优先、稀疏降级）+ RRF 融合。"""

    def __init__(
        self,
        chunks: Iterable[Chunk] = (),
        *,
        k1: float = 1.5,
        b: float = 0.75,
        dense: Any = None,
        embedder: Any = None,
    ) -> None:
        self.k1 = k1
        self.b = b
        self.chunks: list[Chunk] = []
        self._df: dict[str, int] = {}
        self._tfs: list[dict[str, int]] = []
        self._lens: list[int] = []
        self._vecs: list[dict[str, float]] = []
        self._n = 0
        self._avgdl = 0.0
        # 稠密检索组件（FaissVectorStore + Embedder）；为空时走稀疏向量
        self._dense = dense
        self._embedder = embedder
        for chunk in chunks:
            self._add(chunk)
        # NullEmbedder（dim=0）等价于"没有可用的稠密能力"，直接丢弃
        if self._embedder is not None and getattr(self._embedder, "dim", 0) <= 0:
            self._dense = None
            self._embedder = None
        if self._dense is not None and not getattr(self._dense, "ids", None):
            self._build_dense()

    @property
    def _by_id(self) -> list[str]:
        return [chunk.chunk_id for chunk in self.chunks]

    def _build_dense(self) -> None:
        """为全部块生成稠密向量并写入 FAISS（需要 embedder 可用）。

        任何一步失败都退回稀疏检索——知识库不可用不应该让诊断会话挂掉。
        """

        if self._dense is None or self._embedder is None or not self.chunks:
            return
        if getattr(self._dense, "ids", None):
            return
        try:
            vectors = self._embedder.embed([chunk.text for chunk in self.chunks])
            if not vectors:
                raise ValueError("embedder returned no vectors")
            self._dense.add(self._by_id, vectors)
        except Exception:  # noqa: BLE001 — 稠密构建失败即降级
            self._dense = None
            self._embedder = None

    @property
    def vector_backend(self) -> str:
        """当前向量检索的实际实现：``dense`` / ``sparse``。"""

        return "dense" if self._dense is not None and self._embedder is not None else "sparse"

    # -- 构建 ---------------------------------------------------------
    def _add(self, chunk: Chunk) -> None:
        tokens = tokenize(chunk.text)
        tf: dict[str, int] = {}
        for token in tokens:
            tf[token] = tf.get(token, 0) + 1
        self.chunks.append(chunk)
        self._tfs.append(tf)
        self._lens.append(len(tokens))
        for token in tf:
            self._df[token] = self._df.get(token, 0) + 1
        self._n = len(self.chunks)
        self._avgdl = sum(self._lens) / self._n if self._n else 0.0
        self._vecs.append(self._doc_vector(tf))

    def _idf(self, token: str) -> float:
        df = self._df.get(token, 0)
        return math.log(1 + (self._n - df + 0.5) / (df + 0.5))

    def _doc_vector(self, tf: dict[str, int]) -> dict[str, float]:
        vector = {token: (1 + math.log(count)) * self._idf(token) for token, count in tf.items()}
        return _normalize(vector)

    def _query_vector(self, query: str) -> dict[str, float]:
        tf: dict[str, int] = {}
        for token in tokenize(query):
            if token in self._df:
                tf[token] = tf.get(token, 0) + 1
        vector = {token: (1 + math.log(count)) * self._idf(token) for token, count in tf.items()}
        return _normalize(vector)

    # -- 三路检索 -----------------------------------------------------
    def search_bm25(self, query: str, top_k: int = 5) -> list[tuple[float, int]]:
        query_tokens = tokenize(query)
        if not query_tokens:
            return []
        scored: list[tuple[float, int]] = []
        for index, tf in enumerate(self._tfs):
            score = 0.0
            length = self._lens[index]
            for token in query_tokens:
                freq = tf.get(token, 0)
                if not freq:
                    continue
                denominator = freq + self.k1 * (1 - self.b + self.b * length / (self._avgdl or 1.0))
                score += self._idf(token) * freq * (self.k1 + 1) / denominator
            if score > 0:
                scored.append((score, index))
        scored.sort(key=lambda item: item[0], reverse=True)
        return scored[:top_k]

    def search_vector(self, query: str, top_k: int = 5) -> list[tuple[float, int]]:
        """向量检索：优先稠密向量（bge + FAISS），不可用时退回 TF-IDF 稀疏向量。"""

        if self._dense is not None and self._embedder is not None:
            try:
                query_vector = self._embedder.embed([query])[0]
                hits = self._dense.search(query_vector, top_k)
                positions = {chunk_id: index for index, chunk_id in enumerate(self._by_id)}
                out = [
                    (score, positions[chunk_id])
                    for score, chunk_id in hits
                    if chunk_id in positions
                ]
                if out:
                    return out
            except Exception:  # noqa: BLE001 — 稠密检索失败退回稀疏，不阻塞诊断
                pass
        return self.search_sparse(query, top_k)

    def search_sparse(self, query: str, top_k: int = 5) -> list[tuple[float, int]]:
        """TF-IDF 稀疏向量检索（零依赖，作为降级路径保留）。"""

        query_vector = self._query_vector(query)
        if not query_vector:
            return []
        scored: list[tuple[float, int]] = []
        for index, doc_vector in enumerate(self._vecs):
            score = sum(weight * doc_vector.get(token, 0.0) for token, weight in query_vector.items())
            if score > 0:
                scored.append((score, index))
        scored.sort(key=lambda item: item[0], reverse=True)
        return scored[:top_k]

    def search_hybrid(self, query: str, top_k: int = 5, *, rrf_k: int = RRF_K) -> list[tuple[float, int]]:
        """RRF 融合：只看名次，避免两路分数量纲不可比。"""

        fused: dict[int, float] = {}
        for rank, (_, index) in enumerate(self.search_bm25(query, max(top_k * 4, top_k)), start=1):
            fused[index] = fused.get(index, 0.0) + 1.0 / (rrf_k + rank)
        for rank, (_, index) in enumerate(self.search_vector(query, max(top_k * 4, top_k)), start=1):
            fused[index] = fused.get(index, 0.0) + 1.0 / (rrf_k + rank)
        ranked = sorted(fused.items(), key=lambda item: item[1], reverse=True)
        return [(score, index) for index, score in ranked[:top_k]]

    def search(self, mode: str, query: str, top_k: int = 5) -> list[tuple[float, int]]:
        if mode == "bm25":
            return self.search_bm25(query, top_k)
        if mode == "vector":
            return self.search_vector(query, top_k)
        if mode == "hybrid":
            return self.search_hybrid(query, top_k)
        raise ValueError(f"unknown retrieval mode: {mode}")

    # -- 序列化 -------------------------------------------------------
    def to_payload(self, *, built_at: str | None = None) -> dict[str, Any]:
        return {
            "version": INDEX_VERSION,
            "built_at": built_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "chunk_count": len(self.chunks),
            "chunks": [chunk.to_dict() for chunk in self.chunks],
        }

    def save(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.to_payload(), ensure_ascii=False, indent=0), encoding="utf-8")
        tmp.replace(path)
        if self._dense is not None and getattr(self._dense, "ids", None):
            self._dense.save(path.with_suffix(".faiss"), path.with_suffix(".ids.json"))
        return path

    @classmethod
    def load(cls, path: Path, *, embedder: Any = None) -> "KnowledgeIndex":
        path = Path(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        version = payload.get("version")
        if version != INDEX_VERSION:
            raise ValueError(f"unsupported knowledge index version: {version!r} (expected {INDEX_VERSION})")
        chunks = [Chunk.from_dict(item) for item in payload.get("chunks") or []]
        dense = None
        index_file = path.with_suffix(".faiss")
        ids_file = path.with_suffix(".ids.json")
        if index_file.is_file() and ids_file.is_file() and embedder is not None:
            try:
                from .vector_store import FaissVectorStore

                dense = FaissVectorStore.load(index_file, ids_file)
            except Exception:  # noqa: BLE001 — 向量索引损坏时退回稀疏检索
                dense = None
        if embedder is None:
            return cls(chunks)
        return cls(chunks, dense=dense, embedder=embedder)


def _normalize(vector: dict[str, float]) -> dict[str, float]:
    norm = math.sqrt(sum(value * value for value in vector.values())) or 1.0
    return {token: value / norm for token, value in vector.items()}
