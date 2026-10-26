#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Memory scope isolation extension.

Provides scope-aware memory prompt building that integrates with
``src.memdir.load_memory_prompts()`` without modifying upstream code.

Usage::

    from cloudagent_ext.memory.scope_aware_prompt import (
        build_scope_aware_memory_prompt,
        VALID_MEMORY_SCOPES,
    )

    prompt = build_scope_aware_memory_prompt(["user", "team"])
"""


# ---------------------------------------------------------------------------
# Upstream memory API (relocated from the removed ``src/memory`` package)
# ---------------------------------------------------------------------------
from cloudagent_ext.memory.provenance import (  # noqa: E402, F401
    BACKGROUND_REVIEW,
    get_current_write_origin,
    is_background_review,
    reset_current_write_origin,
    set_current_write_origin,
)
from cloudagent_ext.memory.store import (  # noqa: E402, F401
    ENTRY_DELIMITER,
    MemoryStore,
    get_memory_dir,
    get_memory_store,
    reset_memory_store_cache,
)

__all__ = sorted(set(globals().get("__all__", ())) | {
    "BACKGROUND_REVIEW",
    "ENTRY_DELIMITER",
    "MemoryStore",
    "get_current_write_origin",
    "get_memory_dir",
    "get_memory_store",
    "is_background_review",
    "reset_current_write_origin",
    "reset_memory_store_cache",
    "set_current_write_origin",
})
