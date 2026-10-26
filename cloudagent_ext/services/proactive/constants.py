#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

from __future__ import annotations

TICK_INTERVAL_MS: int = 30_000
TICK_TAG: str = "tick"
CONTEXT_BLOCKED_TTL_SEC: int = 60
DEFAULT_JITTER_FRACTION: float = 0.05

FOCUS_LEVELS: tuple[str, ...] = ("full", "medium", "minimal")
DEFAULT_FOCUS_LEVEL: str = "medium"
MAX_LAST_TICK_SUMMARY_CHARS: int = 800
