#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Retention cleanup for IM gateway data."""

from __future__ import annotations

import logging

from .config import ReliabilityConfig
from .store import ReliabilityStore

logger = logging.getLogger(__name__)


def run_retention_sweep(
    store: ReliabilityStore,
    reliability: ReliabilityConfig,
) -> dict[str, int]:
    """Apply retention limits to IM gateway data files."""
    if not reliability.retention_enabled:
        return {}
    try:
        removed = store.purge_all(reliability)
        if any(removed.values()):
            logger.info("im_gateway retention sweep: %s", removed)
        return removed
    except Exception:  # noqa: BLE001
        logger.exception("im_gateway retention sweep failed")
        return {}


__all__ = ["run_retention_sweep"]
