#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""
Post-compact cleanup — clear caches and tracking state after compaction.
Port.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PostCompactContext:
    """Minimal context for post-compact cleanup."""

    # Caches to clear (name → clear callable)
    caches: dict[str, Callable[[], None]] = field(default_factory=dict)
    # Read-file state tracking
    read_file_state: dict[str, Any] | None = None
    # Loaded nested memory paths
    loaded_nested_memory_paths: set[str] | None = None


def run_post_compact_cleanup(
    context: PostCompactContext | None = None,
) -> list[str]:
    """
    Clear caches and tracking state after a successful compaction.
    Returns a list of cache names that were cleared.
    """
    cleared: list[str] = []

    if context is None:
        return cleared

    # Clear registered caches
    for name, clear_fn in context.caches.items():
        try:
            clear_fn()
            cleared.append(name)
        except Exception:
            logger.warning("Failed to clear cache %r during post-compact cleanup", name)

    # Clear read-file state
    if context.read_file_state is not None:
        context.read_file_state.clear()
        cleared.append("read_file_state")

    # Clear loaded nested memory paths
    if context.loaded_nested_memory_paths is not None:
        context.loaded_nested_memory_paths.clear()
        cleared.append("loaded_nested_memory_paths")

    return cleared
