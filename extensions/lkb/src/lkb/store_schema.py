#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Single-source schema constants for persisted LKB board envelopes."""

from __future__ import annotations

LEGACY_STORE_FORMAT = "lkb-json-v1"
STORE_FORMAT = "lkb-json-v2"
CURRENT_SCHEMA_VERSION = 2
HASH_ALGORITHM = "sha256"

__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "HASH_ALGORITHM",
    "LEGACY_STORE_FORMAT",
    "STORE_FORMAT",
]
