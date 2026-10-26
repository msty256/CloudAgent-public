#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

from __future__ import annotations

import importlib
import threading
from typing import Any, Callable

_builders: dict[str, Callable[..., Any]] | None = None
_builders_lock = threading.RLock()


def register_mcp_skill_builders(builders: dict[str, Callable[..., Any]]) -> None:
    """Register the process MCP builders once and invalidate live catalogs."""

    global _builders
    with _builders_lock:
        if _builders is not None:
            return
        _builders = dict(builders)

    # Registration can happen after an SDK/headless catalog was first read.
    # Drop only derived catalog views; disk discovery remains reusable.
    catalog = importlib.import_module(f"{__package__}.catalog")
    invalidate = getattr(catalog, "_invalidate_catalog_cache_only", None)
    if callable(invalidate):
        invalidate()


def get_mcp_skill_builders() -> dict[str, Callable[..., Any]] | None:
    """Return a copy so callers cannot mutate a cached catalog source in place."""

    with _builders_lock:
        return dict(_builders) if _builders is not None else None
