#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Buddy feature gate. Always returns ``True``; existence of the symbol
allows future env-var or config gating without touching every consumer.
"""

from __future__ import annotations


def is_buddy_enabled() -> bool:
    """Whether the companion / buddy subsystem is active in this build."""
    return True


__all__ = ["is_buddy_enabled"]
