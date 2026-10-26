#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Per-hook shell selection — Chapter 12 round 2.

**Deprecated**: Import from ``cloudagent_ext.utils.shell_resolver`` instead.
This module is kept as a re-export shim for existing consumers.
"""

from __future__ import annotations

from cloudagent_ext.utils.shell_resolver import (
    DEFAULT_HOOK_SHELL,
    SHELL_TYPES,
    ShellType,
    build_powershell_args,
    find_powershell_path,
)

__all__ = [
    "DEFAULT_HOOK_SHELL",
    "SHELL_TYPES",
    "ShellType",
    "build_powershell_args",
    "find_powershell_path",
]
