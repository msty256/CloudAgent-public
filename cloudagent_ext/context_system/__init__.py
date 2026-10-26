#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Context system — package init.

Mirrors the original ``src/context_system/__init__.py`` (legacy build
helpers, prompt-assembly, CLAUDE.md loading, git-context snapshot,
and shared models). Each submodule now lives under
``cloudagent_ext.context_system.*``; this ``__init__`` re-exports the
same public surface so callers can keep using either
``from cloudagent_ext.context_system import build_context_prompt`` or
the older ``from cloudagent_ext.context_system import build_context_prompt``
(wired through a thin facade).
"""

from __future__ import annotations

# ``cloudagent_md`` replaces its module object at runtime to preserve the
# upstream compatibility surface, so Pylint cannot statically see its exports.
# pylint: disable=no-name-in-module

from .builder import build_context_prompt
from .prompt_assembly import (
    append_system_context,
    clear_context_caches,
    fetch_system_prompt_parts,
    get_system_context,
    get_user_context,
    prepend_user_context,
)
from .cloudagent_md import (
    clear_memory_file_caches,
    get_cloudagent_mds,
    get_memory_files,
    reset_get_memory_files_cache,
)
from .git_context import (
    GitContextSnapshot,
    clear_git_caches,
    collect_git_context,
    format_git_status,
    get_is_git,
)
from .models import (
    MemoryFileInfo,
    MemoryType,
    SystemPromptParts,
)

__all__ = [
    # Legacy (backward compat)
    "build_context_prompt",
    # Prompt assembly (WS-5)
    "append_system_context",
    "clear_context_caches",
    "fetch_system_prompt_parts",
    "get_system_context",
    "get_user_context",
    "prepend_user_context",
    # CLOUDAGENT.md
    "clear_memory_file_caches",
    "get_cloudagent_mds",
    "get_memory_files",
    "reset_get_memory_files_cache",
    # Git context
    "GitContextSnapshot",
    "clear_git_caches",
    "collect_git_context",
    "format_git_status",
    "get_is_git",
    # Models
    "MemoryFileInfo",
    "MemoryType",
    "SystemPromptParts",
]
