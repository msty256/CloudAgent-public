#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

from extensions.sop_converter.core.tool_retrieval import (
    MacroCoverage,
    RETRIEVAL_INDEX_RELATIVE_PATH,
    RETRIEVAL_INDEX_VERSION,
    ToolRetrievalIndex,
    ToolRetrievalProfile,
    index_from_routes,
    load_tool_retrieval_index,
    normalize_tool_ref,
    resolve_tool_references,
    retrieval_index_path,
    write_tool_retrieval_index,
)

__all__ = [
    "MacroCoverage",
    "RETRIEVAL_INDEX_RELATIVE_PATH",
    "RETRIEVAL_INDEX_VERSION",
    "ToolRetrievalIndex",
    "ToolRetrievalProfile",
    "index_from_routes",
    "load_tool_retrieval_index",
    "normalize_tool_ref",
    "resolve_tool_references",
    "retrieval_index_path",
    "write_tool_retrieval_index",
]

from extensions.sop_converter.core import tool_retrieval as _impl

for _name, _value in vars(_impl).items():
    if _name.startswith("_") and not _name.startswith("__"):
        globals()[_name] = _value
del _name, _value, _impl
