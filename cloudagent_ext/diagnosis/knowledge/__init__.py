#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""诊断知识库检索（RAG）。

对外接口：

* :func:`search` —— 检索片段（带 ``chunk_id``，只读证据）；
* :data:`search_knowledge_tool` —— 装配给诊断子 Agent 的 ``Tool``；
* :func:`register_knowledge_tools` —— 把工具注册进给定注册表；
* :class:`KnowledgeIndex` / :func:`build_chunks` —— 索引构建（供 ingest/测试）。
"""

from __future__ import annotations

from .retriever import (
    KnowledgeIndexMissing,
    KnowledgeQueryError,
    index_path,
    load_index,
    reset_cache,
    search,
)
from .store import Chunk, KnowledgeIndex, build_chunks, chunk_case, chunk_doc, split_text, tokenize
from .tools import INPUT_SCHEMA, TOOL_NAME, register_knowledge_tools, search_knowledge_tool

__all__ = [
    "Chunk",
    "INPUT_SCHEMA",
    "KnowledgeIndex",
    "KnowledgeIndexMissing",
    "KnowledgeQueryError",
    "TOOL_NAME",
    "build_chunks",
    "chunk_case",
    "chunk_doc",
    "index_path",
    "load_index",
    "register_knowledge_tools",
    "reset_cache",
    "search",
    "search_knowledge_tool",
    "split_text",
    "tokenize",
]
