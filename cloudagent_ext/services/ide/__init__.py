#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""IDE Integration subsystem.

Provides types and connection management for IDE integration (VSCode, JetBrains, etc.)
via JSON-RPC. Mirrors TypeScript ide/ directory.
"""

from __future__ import annotations

from .connection import IDEConnectionManager
from .diagnostics import DiagnosticsCollector
from .selection import SelectionTracker
from .types import (
    IDEConnection,
    IDEDiagnostic,
    IDEDiagnosticSeverity,
    IDERange,
    IDESelection,
    IDEType,
)

__all__ = [
    "DiagnosticsCollector",
    "IDEConnection",
    "IDEConnectionManager",
    "IDEDiagnostic",
    "IDEDiagnosticSeverity",
    "IDERange",
    "IDESelection",
    "IDEType",
    "SelectionTracker",
]
